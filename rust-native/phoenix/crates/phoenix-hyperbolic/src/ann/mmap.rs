use crate::ann::archive::{
    decode_header, validate_parts, ArchiveHeader, ArchiveLimits, ArchiveReceipt, SectionDescriptor,
    SectionKind, HEADER_BYTES, PAGE_ALIGNMENT, REQUIRED_FLAGS,
};
use crate::ann::frozen::{DiskAnnSourceView, FrozenHnsw, NodeRecord, UpperRowRecord};
use crate::ann::legacy::{LegacyDiskMetadata, PackedHnswGraph, PackedHnswMetadata};
use crate::ann::search::{search_view, GraphView};
use crate::{
    Candidate, DenseVectorId, HyperbolicDiskError, MetricF32, NoFilter, SearchFilter, SearchHit,
    SearchParams, SearchScratch, StableVectorId,
};
use bytemuck::Pod;
use memmap2::Mmap;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArchiveFormat {
    VerifiedV2,
    QuarantinedLegacyV1,
}

#[derive(Debug)]
struct MappedArchive {
    path: PathBuf,
    mmap: Mmap,
    header: ArchiveHeader,
}

#[derive(Debug)]
enum Backing {
    Mapped(MappedArchive),
    LegacyOwned(FrozenHnsw),
}

#[derive(Debug)]
pub struct HyperbolicDiskHnsw<M> {
    backing: Backing,
    metric: M,
}

impl<M: MetricF32> HyperbolicDiskHnsw<M> {
    pub fn open(path: impl AsRef<Path>, metric: M) -> Result<Self, HyperbolicDiskError> {
        Self::open_with_limits(path, metric, ArchiveLimits::default())
    }

    pub fn open_with_limits(
        path: impl AsRef<Path>,
        metric: M,
        limits: ArchiveLimits,
    ) -> Result<Self, HyperbolicDiskError> {
        let archive = MappedArchive::open(path.as_ref(), limits)?;
        if archive.header.metric != metric.identity() {
            return Err(HyperbolicDiskError::MetricMismatch {
                expected: archive.header.metric,
                actual: metric.identity(),
            });
        }
        Ok(Self {
            backing: Backing::Mapped(archive),
            metric,
        })
    }

    /// Explicitly opens the quarantined host-sized V1 cache format.
    ///
    /// This is deliberately not an automatic fallback from `open`: callers
    /// must name the compatibility boundary, and production V2 publication
    /// can therefore fail closed.
    pub fn open_legacy(path: impl AsRef<Path>, metric: M) -> Result<Self, HyperbolicDiskError> {
        let packed = read_legacy(path.as_ref())?;
        Self::from_packed(packed, metric)
    }

    pub fn from_packed(packed: PackedHnswGraph, metric: M) -> Result<Self, HyperbolicDiskError> {
        let frozen = packed.into_frozen(metric.identity())?;
        Ok(Self {
            backing: Backing::LegacyOwned(frozen),
            metric,
        })
    }

    pub fn format(&self) -> ArchiveFormat {
        match self.backing {
            Backing::Mapped(_) => ArchiveFormat::VerifiedV2,
            Backing::LegacyOwned(_) => ArchiveFormat::QuarantinedLegacyV1,
        }
    }

    pub fn len(&self) -> usize {
        match &self.backing {
            Backing::Mapped(archive) => archive.header.node_count as usize,
            Backing::LegacyOwned(frozen) => frozen.len(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn dimension(&self) -> usize {
        match &self.backing {
            Backing::Mapped(archive) => archive.header.dimension as usize,
            Backing::LegacyOwned(frozen) => frozen.dimension(),
        }
    }

    pub fn archive_receipt(&self) -> Option<ArchiveReceipt> {
        let Backing::Mapped(archive) = &self.backing else {
            return None;
        };
        Some(ArchiveReceipt {
            path: archive.path.clone(),
            bytes: archive.header.file_length,
            nodes: archive.header.node_count,
            dimension: archive.header.dimension,
            root_hash: archive.header.root_hash,
            diskann: crate::DiskAnnReadiness {
                page_aligned_sections: true,
                full_precision_vectors: true,
                stable_external_ids: true,
                base_graph_csr: true,
                filter_tags: true,
                tombstones: true,
                vamana_built: false,
                pq_codes: false,
                asynchronous_beam_io: false,
            },
        })
    }

    /// Borrows verified V2 pages for a future Vamana/DiskANN build. The
    /// quarantined V1 compatibility cache is intentionally ineligible.
    pub fn diskann_source(&self) -> Result<DiskAnnSourceView<'_>, HyperbolicDiskError> {
        let Backing::Mapped(archive) = &self.backing else {
            return Err(HyperbolicDiskError::UnsupportedArchive);
        };
        let view = archive.view()?;
        Ok(DiskAnnSourceView::new(
            view.dimension,
            view.nodes,
            view.vectors,
            view.base_offsets,
            view.base_neighbors,
        ))
    }

    pub fn vector(&self, id: DenseVectorId) -> Option<&[f32]> {
        match &self.backing {
            Backing::Mapped(archive) => {
                let view = archive.view().ok()?;
                let start = id.get() as usize * view.dimension;
                view.vectors.get(start..start + view.dimension)
            }
            Backing::LegacyOwned(frozen) => frozen.vector(id),
        }
    }

    pub fn stable_id(&self, id: DenseVectorId) -> Option<StableVectorId> {
        match &self.backing {
            Backing::Mapped(archive) => archive
                .view()
                .ok()?
                .node(id.get())
                .and_then(|node| StableVectorId::new(node.stable_id).ok()),
            Backing::LegacyOwned(frozen) => frozen.stable_id(id),
        }
    }

    pub fn search(&self, query: &[f32], k: usize, ef_search: usize) -> Vec<Candidate> {
        let mut scratch = SearchScratch::new();
        self.search_with_scratch(
            query,
            SearchParams::new(k, ef_search.max(k)),
            &NoFilter,
            &mut scratch,
        )
        .map(|hits| {
            hits.iter()
                .map(|hit| Candidate {
                    id: hit.dense_id.get(),
                    dist: hit.distance,
                })
                .collect()
        })
        .unwrap_or_default()
    }

    pub fn search_with_scratch<'a, F>(
        &self,
        query: &[f32],
        params: SearchParams,
        filter: &F,
        scratch: &'a mut SearchScratch,
    ) -> Result<&'a [SearchHit], HyperbolicDiskError>
    where
        F: SearchFilter,
    {
        match &self.backing {
            Backing::Mapped(archive) => {
                let view = archive.view()?;
                search_view(&view, &self.metric, query, params, filter, scratch)
            }
            Backing::LegacyOwned(frozen) => {
                frozen.search_with_scratch(&self.metric, query, params, filter, scratch)
            }
        }
    }
}

impl MappedArchive {
    fn open(path: &Path, limits: ArchiveLimits) -> Result<Self, HyperbolicDiskError> {
        let file = File::open(path)?;
        let actual_length = file.metadata()?.len();
        if actual_length < HEADER_BYTES as u64 {
            return Err(HyperbolicDiskError::UnsupportedArchive);
        }
        if actual_length > limits.maximum_bytes {
            return Err(HyperbolicDiskError::OversizedArchive {
                declared: actual_length,
                maximum: limits.maximum_bytes,
            });
        }
        // SAFETY: the mapping is read-only, the file handle remains valid for
        // creation, and the immutable archive contract forbids in-place writes.
        let mmap = unsafe { Mmap::map(&file)? };
        let header = decode_header(&mmap[..HEADER_BYTES], limits)?;
        if header.file_length != actual_length || header.flags & REQUIRED_FLAGS != REQUIRED_FLAGS {
            return Err(HyperbolicDiskError::InvalidArchiveRange);
        }
        validate_section_directory(&header, actual_length)?;
        for section in &header.sections {
            let bytes = section_bytes(&mmap, section)?;
            if blake3::hash(bytes).as_bytes() != &section.hash {
                return Err(HyperbolicDiskError::CorruptSection {
                    section: section.kind as u32,
                });
            }
        }
        let archive = Self {
            path: path.to_path_buf(),
            mmap,
            header,
        };
        let view = archive.view()?;
        validate_parts(
            archive.header.dimension,
            archive.header.entry_point,
            archive.header.maximum_level,
            archive.header.options,
            view.nodes,
            view.vectors,
            view.base_offsets,
            view.base_neighbors,
            view.upper_rows,
            view.upper_neighbors,
            limits,
        )?;
        Ok(archive)
    }

    fn view(&self) -> Result<MappedView<'_>, HyperbolicDiskError> {
        Ok(MappedView {
            dimension: self.header.dimension as usize,
            entry_point: self.header.entry_point,
            maximum_level: self.header.maximum_level,
            nodes: self.typed(SectionKind::Nodes)?,
            vectors: self.typed(SectionKind::Vectors)?,
            base_offsets: self.typed(SectionKind::BaseOffsets)?,
            base_neighbors: self.typed(SectionKind::BaseNeighbors)?,
            upper_rows: self.typed(SectionKind::UpperRows)?,
            upper_neighbors: self.typed(SectionKind::UpperNeighbors)?,
        })
    }

    fn typed<T: Pod>(&self, kind: SectionKind) -> Result<&[T], HyperbolicDiskError> {
        let section = self
            .header
            .sections
            .iter()
            .find(|section| section.kind == kind)
            .ok_or(HyperbolicDiskError::MissingSection {
                section: kind as u32,
            })?;
        bytemuck::try_cast_slice(section_bytes(&self.mmap, section)?)
            .map_err(|_| HyperbolicDiskError::InvalidArchiveRange)
    }
}

struct MappedView<'a> {
    dimension: usize,
    entry_point: u32,
    maximum_level: u8,
    nodes: &'a [NodeRecord],
    vectors: &'a [f32],
    base_offsets: &'a [u64],
    base_neighbors: &'a [u32],
    upper_rows: &'a [UpperRowRecord],
    upper_neighbors: &'a [u32],
}

impl GraphView for MappedView<'_> {
    fn dimension(&self) -> usize {
        self.dimension
    }

    fn node_count(&self) -> usize {
        self.nodes.len()
    }

    fn maximum_level(&self) -> u8 {
        self.maximum_level
    }

    fn entry_point(&self) -> u32 {
        self.entry_point
    }

    fn node(&self, id: u32) -> Option<NodeRecord> {
        self.nodes.get(id as usize).copied()
    }

    fn vector(&self, id: u32) -> Option<&[f32]> {
        let start = id as usize * self.dimension;
        self.vectors.get(start..start + self.dimension)
    }

    fn base_neighbors(&self, id: u32) -> Option<&[u32]> {
        let id = id as usize;
        let start = *self.base_offsets.get(id)? as usize;
        let end = *self.base_offsets.get(id + 1)? as usize;
        self.base_neighbors.get(start..end)
    }

    fn upper_neighbors(&self, id: u32, level: u8) -> Option<&[u32]> {
        let node = self.nodes.get(id as usize)?;
        let row_start = node.upper_row_start as usize;
        let rows = self
            .upper_rows
            .get(row_start..row_start + node.upper_row_count as usize)?;
        let row = rows.iter().find(|row| row.level == u16::from(level))?;
        let start = row.neighbor_offset as usize;
        self.upper_neighbors
            .get(start..start + row.neighbor_count as usize)
    }
}

fn validate_section_directory(
    header: &ArchiveHeader,
    file_length: u64,
) -> Result<(), HyperbolicDiskError> {
    let mut previous_end = HEADER_BYTES as u64;
    for kind in SectionKind::ALL {
        let section = header
            .sections
            .iter()
            .find(|section| section.kind == kind)
            .ok_or(HyperbolicDiskError::MissingSection {
                section: kind as u32,
            })?;
        let expected_size = section_size(kind);
        let expected_length = section
            .element_count
            .checked_mul(u64::from(expected_size))
            .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
        let end = section
            .offset
            .checked_add(section.length)
            .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
        if section.alignment as u64 != PAGE_ALIGNMENT
            || section.offset % PAGE_ALIGNMENT != 0
            || section.offset < previous_end
            || section.element_size != expected_size
            || section.length != expected_length
            || end > file_length
        {
            return Err(HyperbolicDiskError::InvalidArchiveRange);
        }
        validate_expected_count(header, kind, section.element_count)?;
        previous_end = end;
    }
    Ok(())
}

fn validate_expected_count(
    header: &ArchiveHeader,
    kind: SectionKind,
    count: u64,
) -> Result<(), HyperbolicDiskError> {
    let expected = match kind {
        SectionKind::Nodes => Some(u64::from(header.node_count)),
        SectionKind::Vectors => Some(
            u64::from(header.node_count)
                .checked_mul(u64::from(header.dimension))
                .ok_or(HyperbolicDiskError::InvalidArchiveRange)?,
        ),
        SectionKind::BaseOffsets => Some(u64::from(header.node_count) + 1),
        SectionKind::BaseNeighbors | SectionKind::UpperRows | SectionKind::UpperNeighbors => None,
    };
    if expected.is_some_and(|expected| count != expected) {
        return Err(HyperbolicDiskError::InvalidArchiveRange);
    }
    Ok(())
}

const fn section_size(kind: SectionKind) -> u32 {
    match kind {
        SectionKind::Nodes => std::mem::size_of::<NodeRecord>() as u32,
        SectionKind::Vectors => std::mem::size_of::<f32>() as u32,
        SectionKind::BaseOffsets => std::mem::size_of::<u64>() as u32,
        SectionKind::BaseNeighbors | SectionKind::UpperNeighbors => {
            std::mem::size_of::<u32>() as u32
        }
        SectionKind::UpperRows => std::mem::size_of::<UpperRowRecord>() as u32,
    }
}

fn section_bytes<'a>(
    mmap: &'a [u8],
    section: &SectionDescriptor,
) -> Result<&'a [u8], HyperbolicDiskError> {
    let start =
        usize::try_from(section.offset).map_err(|_| HyperbolicDiskError::InvalidArchiveRange)?;
    let length =
        usize::try_from(section.length).map_err(|_| HyperbolicDiskError::InvalidArchiveRange)?;
    mmap.get(
        start
            ..start
                .checked_add(length)
                .ok_or(HyperbolicDiskError::InvalidArchiveRange)?,
    )
    .ok_or(HyperbolicDiskError::InvalidArchiveRange)
}

fn read_legacy(path: &Path) -> Result<PackedHnswGraph, HyperbolicDiskError> {
    let mut file = File::open(path)?;
    let file_length = file.metadata()?.len();
    let mut length_bytes = [0_u8; 8];
    file.read_exact(&mut length_bytes)?;
    let metadata_length = u64::from_le_bytes(length_bytes);
    if metadata_length > 64 * 1024 || metadata_length + 8 > file_length {
        return Err(HyperbolicDiskError::InvalidArchiveRange);
    }
    let mut metadata_bytes = vec![0_u8; metadata_length as usize];
    file.read_exact(&mut metadata_bytes)?;
    let metadata: LegacyDiskMetadata = bincode::deserialize(&metadata_bytes)?;
    validate_legacy_ranges(&metadata, file_length)?;
    let all = std::fs::read(path)?;
    let range = |start: u64, end: u64| -> Result<Vec<u8>, HyperbolicDiskError> {
        let start = usize::try_from(start).map_err(|_| HyperbolicDiskError::InvalidArchiveRange)?;
        let end = usize::try_from(end).map_err(|_| HyperbolicDiskError::InvalidArchiveRange)?;
        all.get(start..end)
            .map(ToOwned::to_owned)
            .ok_or(HyperbolicDiskError::InvalidArchiveRange)
    };
    Ok(PackedHnswGraph {
        metadata: PackedHnswMetadata::new(
            metadata.dim,
            metadata.num_vectors,
            metadata.max_level,
            metadata.entry_point,
            metadata.elem_size,
        ),
        vectors: range(metadata.vectors_offset, metadata.levels_offset)?,
        levels: range(metadata.levels_offset, metadata.offsets_offset)?,
        offsets: range(metadata.offsets_offset, metadata.adjacency_offset)?,
        adjacency: range(metadata.adjacency_offset, file_length)?,
    })
}

fn validate_legacy_ranges(
    metadata: &LegacyDiskMetadata,
    file_length: u64,
) -> Result<(), HyperbolicDiskError> {
    if metadata.vectors_offset < 8
        || metadata.vectors_offset > metadata.levels_offset
        || metadata.levels_offset > metadata.offsets_offset
        || metadata.offsets_offset > metadata.adjacency_offset
        || metadata.adjacency_offset > file_length
    {
        return Err(HyperbolicDiskError::InvalidArchiveRange);
    }
    Ok(())
}

use crate::ann::frozen::{FrozenHnsw, NodeRecord, UpperRowRecord};
use crate::{HnswBuildOptions, HyperbolicDiskError, MetricIdentity, MetricKind, StableVectorId};
use hashbrown::HashSet;
use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

pub(crate) const MAGIC: [u8; 8] = *b"PHXANN2\0";
pub(crate) const VERSION: u32 = 2;
pub(crate) const ENDIAN_MARKER: u32 = 0x0102_0304;
pub(crate) const HEADER_BYTES: usize = 4096;
pub(crate) const DIRECTORY_OFFSET: usize = 256;
pub(crate) const DIRECTORY_ENTRY_BYTES: usize = 72;
pub(crate) const PAGE_ALIGNMENT: u64 = 4096;

const ROOT_HASH_OFFSET: usize = 128;
const ROOT_HASH_END: usize = ROOT_HASH_OFFSET + 32;
pub(crate) const FLAG_BASE_CSR: u32 = 1;
pub(crate) const FLAG_FULL_VECTORS: u32 = 1 << 1;
pub(crate) const FLAG_STABLE_IDS: u32 = 1 << 2;
pub(crate) const FLAG_FILTER_TAGS: u32 = 1 << 3;
pub(crate) const FLAG_TOMBSTONES: u32 = 1 << 4;
pub(crate) const REQUIRED_FLAGS: u32 =
    FLAG_BASE_CSR | FLAG_FULL_VECTORS | FLAG_STABLE_IDS | FLAG_FILTER_TAGS | FLAG_TOMBSTONES;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u32)]
pub(crate) enum SectionKind {
    Nodes = 1,
    Vectors = 2,
    BaseOffsets = 3,
    BaseNeighbors = 4,
    UpperRows = 5,
    UpperNeighbors = 6,
}

impl SectionKind {
    pub(crate) const ALL: [Self; 6] = [
        Self::Nodes,
        Self::Vectors,
        Self::BaseOffsets,
        Self::BaseNeighbors,
        Self::UpperRows,
        Self::UpperNeighbors,
    ];

    pub(crate) const fn from_raw(raw: u32) -> Option<Self> {
        match raw {
            1 => Some(Self::Nodes),
            2 => Some(Self::Vectors),
            3 => Some(Self::BaseOffsets),
            4 => Some(Self::BaseNeighbors),
            5 => Some(Self::UpperRows),
            6 => Some(Self::UpperNeighbors),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct SectionDescriptor {
    pub kind: SectionKind,
    pub offset: u64,
    pub length: u64,
    pub element_count: u64,
    pub element_size: u32,
    pub alignment: u32,
    pub hash: [u8; 32],
}

#[derive(Clone, Debug)]
pub(crate) struct ArchiveHeader {
    pub file_length: u64,
    pub dimension: u32,
    pub node_count: u32,
    pub entry_point: u32,
    pub maximum_level: u8,
    pub options: HnswBuildOptions,
    pub metric: MetricIdentity,
    pub flags: u32,
    pub root_hash: [u8; 32],
    pub sections: Vec<SectionDescriptor>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArchiveLimits {
    pub maximum_bytes: u64,
    pub maximum_nodes: u64,
    pub maximum_dimension: u32,
    pub maximum_degree: u32,
}

impl Default for ArchiveLimits {
    fn default() -> Self {
        Self {
            maximum_bytes: 1_u64 << 40,
            maximum_nodes: u32::MAX as u64,
            maximum_dimension: 65_536,
            maximum_degree: 65_535,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DiskAnnReadiness {
    pub page_aligned_sections: bool,
    pub full_precision_vectors: bool,
    pub stable_external_ids: bool,
    pub base_graph_csr: bool,
    pub filter_tags: bool,
    pub tombstones: bool,
    pub vamana_built: bool,
    pub pq_codes: bool,
    pub asynchronous_beam_io: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArchiveReceipt {
    pub path: PathBuf,
    pub bytes: u64,
    pub nodes: u32,
    pub dimension: u32,
    pub root_hash: [u8; 32],
    pub diskann: DiskAnnReadiness,
}

impl FrozenHnsw {
    pub fn diskann_readiness(&self) -> DiskAnnReadiness {
        DiskAnnReadiness {
            page_aligned_sections: true,
            full_precision_vectors: true,
            stable_external_ids: true,
            base_graph_csr: true,
            filter_tags: true,
            tombstones: true,
            vamana_built: false,
            pq_codes: false,
            asynchronous_beam_io: false,
        }
    }

    pub fn write_new(&self, path: impl AsRef<Path>) -> Result<ArchiveReceipt, HyperbolicDiskError> {
        validate_frozen(self, ArchiveLimits::default())?;
        let path = path.as_ref();
        if path.exists() {
            return Err(HyperbolicDiskError::ImmutableTargetExists(
                path.to_path_buf(),
            ));
        }
        if !cfg!(target_endian = "little") {
            return Err(HyperbolicDiskError::UnsupportedArchive);
        }
        let temporary = temporary_path(path);
        let result = write_archive(self, &temporary);
        match result {
            Ok((bytes, root_hash)) => {
                if let Err(error) = std::fs::rename(&temporary, path) {
                    let _ = std::fs::remove_file(&temporary);
                    Err(error.into())
                } else {
                    Ok(ArchiveReceipt {
                        path: path.to_path_buf(),
                        bytes,
                        nodes: self.nodes.len() as u32,
                        dimension: self.dimension,
                        root_hash,
                        diskann: self.diskann_readiness(),
                    })
                }
            }
            Err(error) => {
                let _ = std::fs::remove_file(&temporary);
                Err(error)
            }
        }
    }
}

fn write_archive(
    frozen: &FrozenHnsw,
    temporary: &Path,
) -> Result<(u64, [u8; 32]), HyperbolicDiskError> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temporary)?;
    file.write_all(&vec![0_u8; HEADER_BYTES])?;
    let pages: [(SectionKind, &[u8], usize, usize); 6] = [
        (
            SectionKind::Nodes,
            bytemuck::cast_slice(&frozen.nodes),
            frozen.nodes.len(),
            std::mem::size_of::<NodeRecord>(),
        ),
        (
            SectionKind::Vectors,
            bytemuck::cast_slice(&frozen.vectors),
            frozen.vectors.len(),
            std::mem::size_of::<f32>(),
        ),
        (
            SectionKind::BaseOffsets,
            bytemuck::cast_slice(&frozen.base_offsets),
            frozen.base_offsets.len(),
            std::mem::size_of::<u64>(),
        ),
        (
            SectionKind::BaseNeighbors,
            bytemuck::cast_slice(&frozen.base_neighbors),
            frozen.base_neighbors.len(),
            std::mem::size_of::<u32>(),
        ),
        (
            SectionKind::UpperRows,
            bytemuck::cast_slice(&frozen.upper_rows),
            frozen.upper_rows.len(),
            std::mem::size_of::<UpperRowRecord>(),
        ),
        (
            SectionKind::UpperNeighbors,
            bytemuck::cast_slice(&frozen.upper_neighbors),
            frozen.upper_neighbors.len(),
            std::mem::size_of::<u32>(),
        ),
    ];
    let mut sections = Vec::with_capacity(pages.len());
    let mut cursor = HEADER_BYTES as u64;
    for (kind, bytes, count, size) in pages {
        cursor = align_up(cursor, PAGE_ALIGNMENT)?;
        file.seek(SeekFrom::Start(cursor))?;
        file.write_all(bytes)?;
        sections.push(SectionDescriptor {
            kind,
            offset: cursor,
            length: bytes.len() as u64,
            element_count: count as u64,
            element_size: size as u32,
            alignment: PAGE_ALIGNMENT as u32,
            hash: *blake3::hash(bytes).as_bytes(),
        });
        cursor = cursor
            .checked_add(bytes.len() as u64)
            .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
    }
    let file_length = cursor;
    let mut header = encode_header(frozen, file_length, &sections, [0; 32])?;
    let root_hash = root_hash(&header, &sections);
    header[ROOT_HASH_OFFSET..ROOT_HASH_END].copy_from_slice(&root_hash);
    file.seek(SeekFrom::Start(0))?;
    file.write_all(&header)?;
    file.set_len(file_length)?;
    file.sync_all()?;
    Ok((file_length, root_hash))
}

fn encode_header(
    frozen: &FrozenHnsw,
    file_length: u64,
    sections: &[SectionDescriptor],
    root_hash: [u8; 32],
) -> Result<Vec<u8>, HyperbolicDiskError> {
    let mut bytes = vec![0_u8; HEADER_BYTES];
    bytes[0..8].copy_from_slice(&MAGIC);
    put_u32(&mut bytes, 8, VERSION);
    put_u32(&mut bytes, 12, ENDIAN_MARKER);
    put_u32(&mut bytes, 16, HEADER_BYTES as u32);
    put_u32(&mut bytes, 20, sections.len() as u32);
    put_u64(&mut bytes, 24, file_length);
    put_u32(&mut bytes, 32, frozen.dimension);
    put_u32(&mut bytes, 36, frozen.nodes.len() as u32);
    put_u32(&mut bytes, 40, frozen.entry_point);
    bytes[44] = frozen.maximum_level;
    put_u32(&mut bytes, 48, frozen.metric_identity.kind as u32);
    for (index, value) in frozen.metric_identity.parameter_bits.iter().enumerate() {
        put_u32(&mut bytes, 52 + index * 4, *value);
    }
    put_u32(&mut bytes, 68, frozen.options.params.m as u32);
    put_u32(&mut bytes, 72, frozen.options.params.m0 as u32);
    put_u32(&mut bytes, 76, frozen.options.params.ef_construction as u32);
    put_u32(&mut bytes, 80, frozen.options.params.level_mult.to_bits());
    put_u64(&mut bytes, 84, frozen.options.seed);
    bytes[92] = frozen.options.maximum_level;
    bytes[96..128].copy_from_slice(&frozen.metric_identity.implementation_hash);
    bytes[ROOT_HASH_OFFSET..ROOT_HASH_END].copy_from_slice(&root_hash);
    put_u32(&mut bytes, 160, REQUIRED_FLAGS);
    for (index, section) in sections.iter().enumerate() {
        let start = DIRECTORY_OFFSET + index * DIRECTORY_ENTRY_BYTES;
        encode_section(&mut bytes[start..start + DIRECTORY_ENTRY_BYTES], section);
    }
    Ok(bytes)
}

pub(crate) fn decode_header(
    bytes: &[u8],
    limits: ArchiveLimits,
) -> Result<ArchiveHeader, HyperbolicDiskError> {
    if bytes.len() < HEADER_BYTES
        || bytes[0..8] != MAGIC
        || get_u32(bytes, 8)? != VERSION
        || get_u32(bytes, 12)? != ENDIAN_MARKER
        || get_u32(bytes, 16)? as usize != HEADER_BYTES
        || !cfg!(target_endian = "little")
    {
        return Err(HyperbolicDiskError::UnsupportedArchive);
    }
    let section_count = get_u32(bytes, 20)? as usize;
    if section_count != SectionKind::ALL.len()
        || DIRECTORY_OFFSET + section_count * DIRECTORY_ENTRY_BYTES > HEADER_BYTES
    {
        return Err(HyperbolicDiskError::UnsupportedArchive);
    }
    let file_length = get_u64(bytes, 24)?;
    if file_length > limits.maximum_bytes {
        return Err(HyperbolicDiskError::OversizedArchive {
            declared: file_length,
            maximum: limits.maximum_bytes,
        });
    }
    let dimension = get_u32(bytes, 32)?;
    let node_count = get_u32(bytes, 36)?;
    if dimension == 0 || dimension > limits.maximum_dimension {
        return Err(HyperbolicDiskError::InvalidArchiveRange);
    }
    if u64::from(node_count) > limits.maximum_nodes {
        return Err(HyperbolicDiskError::OversizedArchive {
            declared: u64::from(node_count),
            maximum: limits.maximum_nodes,
        });
    }
    let kind =
        MetricKind::from_raw(get_u32(bytes, 48)?).ok_or(HyperbolicDiskError::UnsupportedArchive)?;
    let mut parameter_bits = [0; 4];
    for (index, value) in parameter_bits.iter_mut().enumerate() {
        *value = get_u32(bytes, 52 + index * 4)?;
    }
    let mut implementation_hash = [0; 32];
    implementation_hash.copy_from_slice(&bytes[96..128]);
    let metric = MetricIdentity {
        kind,
        parameter_bits,
        implementation_hash,
    };
    let options = HnswBuildOptions {
        params: crate::HnswBuildParams {
            m: get_u32(bytes, 68)? as usize,
            m0: get_u32(bytes, 72)? as usize,
            ef_construction: get_u32(bytes, 76)? as usize,
            level_mult: f32::from_bits(get_u32(bytes, 80)?),
        },
        seed: get_u64(bytes, 84)?,
        maximum_level: bytes[92],
    }
    .validate()?;
    let mut root = [0; 32];
    root.copy_from_slice(&bytes[ROOT_HASH_OFFSET..ROOT_HASH_END]);
    let mut sections = Vec::with_capacity(section_count);
    let mut seen = HashSet::with_capacity(section_count);
    for index in 0..section_count {
        let start = DIRECTORY_OFFSET + index * DIRECTORY_ENTRY_BYTES;
        let section = decode_section(&bytes[start..start + DIRECTORY_ENTRY_BYTES])?;
        if !seen.insert(section.kind as u32) {
            return Err(HyperbolicDiskError::DuplicateSection {
                section: section.kind as u32,
            });
        }
        sections.push(section);
    }
    for kind in SectionKind::ALL {
        if !seen.contains(&(kind as u32)) {
            return Err(HyperbolicDiskError::MissingSection {
                section: kind as u32,
            });
        }
    }
    let header = ArchiveHeader {
        file_length,
        dimension,
        node_count,
        entry_point: get_u32(bytes, 40)?,
        maximum_level: bytes[44],
        options,
        metric,
        flags: get_u32(bytes, 160)?,
        root_hash: root,
        sections,
    };
    let mut canonical = bytes[..HEADER_BYTES].to_vec();
    canonical[ROOT_HASH_OFFSET..ROOT_HASH_END].fill(0);
    if root_hash(&canonical, &header.sections) != header.root_hash {
        return Err(HyperbolicDiskError::CorruptRoot);
    }
    Ok(header)
}

pub(crate) fn validate_frozen(
    frozen: &FrozenHnsw,
    limits: ArchiveLimits,
) -> Result<(), HyperbolicDiskError> {
    validate_parts(
        frozen.dimension,
        frozen.entry_point,
        frozen.maximum_level,
        frozen.options,
        &frozen.nodes,
        &frozen.vectors,
        &frozen.base_offsets,
        &frozen.base_neighbors,
        &frozen.upper_rows,
        &frozen.upper_neighbors,
        limits,
    )
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn validate_parts(
    dimension: u32,
    entry_point: u32,
    maximum_level: u8,
    options: HnswBuildOptions,
    node_records: &[NodeRecord],
    vectors: &[f32],
    base_offsets: &[u64],
    base_neighbors: &[u32],
    upper_rows: &[UpperRowRecord],
    upper_neighbors: &[u32],
    limits: ArchiveLimits,
) -> Result<(), HyperbolicDiskError> {
    let nodes = node_records.len();
    if nodes as u64 > limits.maximum_nodes
        || dimension == 0
        || dimension > limits.maximum_dimension
        || vectors.len() != nodes.saturating_mul(dimension as usize)
        || base_offsets.len() != nodes + 1
        || (nodes > 0 && entry_point as usize >= nodes)
    {
        return Err(HyperbolicDiskError::InvalidTopology(
            "counts, dimensions, or entry point do not match",
        ));
    }
    let mut stable_ids = HashSet::with_capacity(nodes);
    let mut next_upper_row = 0_usize;
    let mut next_upper_neighbor = 0_u64;
    let mut observed_live_maximum_level = 0_u8;
    let mut live_nodes = 0_usize;
    for (node_id, node) in node_records.iter().enumerate() {
        let stable = StableVectorId::new(node.stable_id)?;
        if !stable_ids.insert(stable) {
            return Err(HyperbolicDiskError::InvalidTopology(
                "stable vector IDs are not unique",
            ));
        }
        if node.flags & !crate::ann::frozen::NODE_FLAG_DELETED != 0
            || node.level > options.maximum_level
        {
            return Err(HyperbolicDiskError::InvalidTopology(
                "node flags or level are invalid",
            ));
        }
        if node.flags & crate::ann::frozen::NODE_FLAG_DELETED == 0 {
            observed_live_maximum_level = observed_live_maximum_level.max(node.level);
            live_nodes += 1;
        }
        let row_start = node.upper_row_start as usize;
        let row_end = row_start
            .checked_add(node.upper_row_count as usize)
            .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
        if row_start != next_upper_row {
            return Err(HyperbolicDiskError::InvalidTopology(
                "upper-row ranges are not canonical and contiguous",
            ));
        }
        let rows =
            upper_rows
                .get(row_start..row_end)
                .ok_or(HyperbolicDiskError::InvalidTopology(
                    "upper-row range is invalid",
                ))?;
        if rows.len() != node.level as usize {
            return Err(HyperbolicDiskError::InvalidTopology(
                "node level and upper rows disagree",
            ));
        }
        for (ordinal, row) in rows.iter().enumerate() {
            if row.level as usize != ordinal + 1
                || row.reserved != 0
                || row.neighbor_offset != next_upper_neighbor
                || row.neighbor_count > limits.maximum_degree
                || row.neighbor_count as usize > options.params.m
            {
                return Err(HyperbolicDiskError::InvalidTopology(
                    "upper-row level or degree is invalid",
                ));
            }
            validate_neighbor_row(
                node_id,
                row.neighbor_offset,
                row.neighbor_count,
                upper_neighbors,
                nodes,
            )?;
            next_upper_neighbor = next_upper_neighbor
                .checked_add(u64::from(row.neighbor_count))
                .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
        }
        next_upper_row = row_end;
    }
    if next_upper_row != upper_rows.len()
        || next_upper_neighbor != upper_neighbors.len() as u64
        || maximum_level != observed_live_maximum_level
        || (live_nodes > 0
            && (node_records[entry_point as usize].level != maximum_level
                || node_records[entry_point as usize].flags
                    & crate::ann::frozen::NODE_FLAG_DELETED
                    != 0))
    {
        return Err(HyperbolicDiskError::InvalidTopology(
            "upper adjacency contains orphaned rows or neighbors",
        ));
    }
    validate_offsets(
        base_offsets,
        base_neighbors,
        options.params.m0,
        limits.maximum_degree,
        nodes,
    )?;
    if vectors.iter().any(|value| !value.is_finite()) {
        return Err(HyperbolicDiskError::NonFiniteVector);
    }
    Ok(())
}

fn validate_offsets(
    offsets: &[u64],
    adjacency: &[u32],
    configured_degree: usize,
    maximum_degree: u32,
    nodes: usize,
) -> Result<(), HyperbolicDiskError> {
    if offsets.first().copied() != Some(0)
        || offsets.last().copied() != Some(adjacency.len() as u64)
    {
        return Err(HyperbolicDiskError::InvalidTopology(
            "base offsets do not cover adjacency",
        ));
    }
    for node_id in 0..nodes {
        let start = offsets[node_id];
        let end = offsets[node_id + 1];
        if end < start
            || end - start > configured_degree as u64
            || end - start > u64::from(maximum_degree)
        {
            return Err(HyperbolicDiskError::InvalidTopology(
                "base adjacency degree is invalid",
            ));
        }
        validate_neighbor_row(node_id, start, (end - start) as u32, adjacency, nodes)?;
    }
    Ok(())
}

fn validate_neighbor_row(
    node_id: usize,
    offset: u64,
    count: u32,
    adjacency: &[u32],
    nodes: usize,
) -> Result<(), HyperbolicDiskError> {
    let start = usize::try_from(offset).map_err(|_| HyperbolicDiskError::InvalidArchiveRange)?;
    let end = start
        .checked_add(count as usize)
        .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
    let row = adjacency
        .get(start..end)
        .ok_or(HyperbolicDiskError::InvalidTopology(
            "neighbor range is invalid",
        ))?;
    let mut seen = HashSet::with_capacity(row.len());
    for &neighbor in row {
        if neighbor as usize >= nodes || neighbor as usize == node_id || !seen.insert(neighbor) {
            return Err(HyperbolicDiskError::InvalidTopology(
                "neighbor ID is invalid, duplicated, or self-referential",
            ));
        }
    }
    Ok(())
}

fn root_hash(header_without_root: &[u8], sections: &[SectionDescriptor]) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix.ann.archive-root/v2\0");
    hasher.update(header_without_root);
    for section in sections {
        hasher.update(&section.hash);
    }
    *hasher.finalize().as_bytes()
}

fn encode_section(bytes: &mut [u8], section: &SectionDescriptor) {
    put_u32(bytes, 0, section.kind as u32);
    put_u64(bytes, 8, section.offset);
    put_u64(bytes, 16, section.length);
    put_u64(bytes, 24, section.element_count);
    put_u32(bytes, 32, section.element_size);
    put_u32(bytes, 36, section.alignment);
    bytes[40..72].copy_from_slice(&section.hash);
}

fn decode_section(bytes: &[u8]) -> Result<SectionDescriptor, HyperbolicDiskError> {
    let kind =
        SectionKind::from_raw(get_u32(bytes, 0)?).ok_or(HyperbolicDiskError::UnsupportedArchive)?;
    let mut hash = [0; 32];
    hash.copy_from_slice(&bytes[40..72]);
    Ok(SectionDescriptor {
        kind,
        offset: get_u64(bytes, 8)?,
        length: get_u64(bytes, 16)?,
        element_count: get_u64(bytes, 24)?,
        element_size: get_u32(bytes, 32)?,
        alignment: get_u32(bytes, 36)?,
        hash,
    })
}

fn align_up(value: u64, alignment: u64) -> Result<u64, HyperbolicDiskError> {
    value
        .checked_add(alignment - 1)
        .map(|sum| sum & !(alignment - 1))
        .ok_or(HyperbolicDiskError::InvalidArchiveRange)
}

fn temporary_path(path: &Path) -> PathBuf {
    let suffix = format!(
        ".tmp-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |duration| duration.as_nanos())
    );
    let mut os = path.as_os_str().to_os_string();
    os.push(suffix);
    PathBuf::from(os)
}

fn put_u32(bytes: &mut [u8], offset: usize, value: u32) {
    bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn put_u64(bytes: &mut [u8], offset: usize, value: u64) {
    bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

fn get_u32(bytes: &[u8], offset: usize) -> Result<u32, HyperbolicDiskError> {
    Ok(u32::from_le_bytes(
        bytes
            .get(offset..offset + 4)
            .ok_or(HyperbolicDiskError::InvalidArchiveRange)?
            .try_into()
            .map_err(|_| HyperbolicDiskError::InvalidArchiveRange)?,
    ))
}

fn get_u64(bytes: &[u8], offset: usize) -> Result<u64, HyperbolicDiskError> {
    Ok(u64::from_le_bytes(
        bytes
            .get(offset..offset + 8)
            .ok_or(HyperbolicDiskError::InvalidArchiveRange)?
            .try_into()
            .map_err(|_| HyperbolicDiskError::InvalidArchiveRange)?,
    ))
}

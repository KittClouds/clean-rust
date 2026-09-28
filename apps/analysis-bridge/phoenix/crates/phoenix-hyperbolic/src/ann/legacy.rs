use crate::ann::archive::{validate_frozen, ArchiveLimits};
use crate::ann::frozen::{FrozenHnsw, NodeRecord, UpperRowRecord};
use crate::{HnswBuildOptions, HyperbolicDiskError, MetricIdentity, NodeMetadata, StableVectorId};
use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::path::Path;

const LEGACY_HEADER_RESERVATION: u64 = 4096;

#[derive(Clone, Serialize, Deserialize, Debug, PartialEq)]
pub struct PackedHnswMetadata {
    dim: usize,
    num_vectors: usize,
    max_level: u32,
    entry_point: u32,
    elem_size: u8,
}

impl PackedHnswMetadata {
    pub const fn new(
        dim: usize,
        num_vectors: usize,
        max_level: u32,
        entry_point: u32,
        elem_size: u8,
    ) -> Self {
        Self {
            dim,
            num_vectors,
            max_level,
            entry_point,
            elem_size,
        }
    }

    pub const fn dim(&self) -> usize {
        self.dim
    }

    pub const fn num_vectors(&self) -> usize {
        self.num_vectors
    }

    pub const fn max_level(&self) -> u32 {
        self.max_level
    }

    pub const fn entry_point(&self) -> u32 {
        self.entry_point
    }

    pub const fn elem_size(&self) -> u8 {
        self.elem_size
    }
}

#[derive(Clone, Serialize, Deserialize, Debug, PartialEq)]
pub struct PackedHnswGraph {
    pub metadata: PackedHnswMetadata,
    pub vectors: Vec<u8>,
    pub levels: Vec<u8>,
    pub offsets: Vec<u8>,
    pub adjacency: Vec<u8>,
}

impl PackedHnswGraph {
    pub(crate) fn from_frozen(frozen: &FrozenHnsw) -> Self {
        let mut levels = Vec::with_capacity(frozen.nodes.len());
        let mut offsets = Vec::with_capacity(frozen.nodes.len());
        let mut adjacency = Vec::<u32>::new();
        for (dense_id, node) in frozen.nodes.iter().enumerate() {
            levels.push(u32::from(node.level));
            offsets.push((adjacency.len() * std::mem::size_of::<u32>()) as u64);
            let base_start = frozen.base_offsets[dense_id] as usize;
            let base_end = frozen.base_offsets[dense_id + 1] as usize;
            push_legacy_row(&mut adjacency, &frozen.base_neighbors[base_start..base_end]);
            let row_start = node.upper_row_start as usize;
            let row_end = row_start + node.upper_row_count as usize;
            for row in &frozen.upper_rows[row_start..row_end] {
                let start = row.neighbor_offset as usize;
                let end = start + row.neighbor_count as usize;
                push_legacy_row(&mut adjacency, &frozen.upper_neighbors[start..end]);
            }
        }
        Self {
            metadata: PackedHnswMetadata::new(
                frozen.dimension(),
                frozen.len(),
                u32::from(frozen.maximum_level),
                frozen.entry_point,
                std::mem::size_of::<f32>() as u8,
            ),
            vectors: bytemuck::cast_slice(&frozen.vectors).to_vec(),
            levels: bytemuck::cast_slice(&levels).to_vec(),
            offsets: bytemuck::cast_slice(&offsets).to_vec(),
            adjacency: bytemuck::cast_slice(&adjacency).to_vec(),
        }
    }

    pub(crate) fn into_frozen(
        self,
        metric_identity: MetricIdentity,
    ) -> Result<FrozenHnsw, HyperbolicDiskError> {
        if self.metadata.elem_size != std::mem::size_of::<f32>() as u8
            || self.metadata.dim == 0
            || self.metadata.num_vectors > u32::MAX as usize
            || self.metadata.max_level > u8::MAX as u32
        {
            return Err(HyperbolicDiskError::UnsupportedArchive);
        }
        let vector_count = self
            .metadata
            .num_vectors
            .checked_mul(self.metadata.dim)
            .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
        let vectors = parse_f32s(&self.vectors, vector_count)?;
        let levels = parse_u32s(&self.levels, self.metadata.num_vectors)?;
        let offsets = parse_u64s(&self.offsets, self.metadata.num_vectors)?;
        let adjacency = parse_u32s_any(&self.adjacency)?;

        let mut nodes = Vec::with_capacity(self.metadata.num_vectors);
        let mut base_offsets = Vec::with_capacity(self.metadata.num_vectors + 1);
        let mut base_neighbors = Vec::new();
        let mut upper_rows = Vec::new();
        let mut upper_neighbors = Vec::new();
        base_offsets.push(0);
        for dense_id in 0..self.metadata.num_vectors {
            let level = u8::try_from(levels[dense_id])
                .map_err(|_| HyperbolicDiskError::UnsupportedArchive)?;
            let byte_offset = offsets[dense_id];
            if byte_offset % std::mem::size_of::<u32>() as u64 != 0 {
                return Err(HyperbolicDiskError::InvalidArchiveRange);
            }
            let mut cursor = usize::try_from(byte_offset / 4)
                .map_err(|_| HyperbolicDiskError::InvalidArchiveRange)?;
            let base = take_legacy_row(&adjacency, &mut cursor)?;
            base_neighbors.extend_from_slice(base);
            base_offsets.push(base_neighbors.len() as u64);
            let upper_row_start = upper_rows.len() as u32;
            for upper_level in 1..=level {
                let row = take_legacy_row(&adjacency, &mut cursor)?;
                upper_rows.push(UpperRowRecord {
                    neighbor_offset: upper_neighbors.len() as u64,
                    neighbor_count: row.len() as u32,
                    level: u16::from(upper_level),
                    reserved: 0,
                });
                upper_neighbors.extend_from_slice(row);
            }
            nodes.push(NodeRecord {
                stable_id: StableVectorId::from_sequential(dense_id as u32).get(),
                tag_mask: NodeMetadata::default().tag_mask,
                upper_row_start,
                upper_row_count: u16::from(level),
                level,
                flags: 0,
            });
        }
        let frozen = FrozenHnsw {
            dimension: self.metadata.dim as u32,
            entry_point: self.metadata.entry_point,
            maximum_level: self.metadata.max_level as u8,
            options: HnswBuildOptions::default(),
            metric_identity,
            nodes: nodes.into_boxed_slice(),
            vectors: vectors.into_boxed_slice(),
            base_offsets: base_offsets.into_boxed_slice(),
            base_neighbors: base_neighbors.into_boxed_slice(),
            upper_rows: upper_rows.into_boxed_slice(),
            upper_neighbors: upper_neighbors.into_boxed_slice(),
        };
        validate_frozen(&frozen, ArchiveLimits::default())?;
        Ok(frozen)
    }

    /// Writes the quarantined V1 cache format used by the Overgraph adapter.
    ///
    /// New native indexes should use `FrozenHnsw::write_new`, whose fixed,
    /// hash-bound directory is mmap-safe and architecture-independent.
    pub fn write_to_file(&self, file_path: &str) -> Result<(), HyperbolicDiskError> {
        let path = Path::new(file_path);
        let mut file = OpenOptions::new()
            .create(true)
            .write(true)
            .read(true)
            .truncate(true)
            .open(path)?;
        let vectors_offset = LEGACY_HEADER_RESERVATION;
        let levels_offset = vectors_offset + self.vectors.len() as u64;
        let offsets_offset = levels_offset + self.levels.len() as u64;
        let adjacency_offset = offsets_offset + self.offsets.len() as u64;
        let metadata = LegacyDiskMetadata {
            dim: self.metadata.dim,
            num_vectors: self.metadata.num_vectors,
            max_level: self.metadata.max_level,
            entry_point: self.metadata.entry_point,
            vectors_offset,
            levels_offset,
            offsets_offset,
            adjacency_offset,
            elem_size: self.metadata.elem_size,
        };
        let metadata_bytes = bincode::serialize(&metadata)?;
        if metadata_bytes.len() + 8 > LEGACY_HEADER_RESERVATION as usize {
            return Err(HyperbolicDiskError::InvalidArchiveRange);
        }
        file.write_all(&(metadata_bytes.len() as u64).to_le_bytes())?;
        file.write_all(&metadata_bytes)?;
        file.seek(SeekFrom::Start(vectors_offset))?;
        file.write_all(&self.vectors)?;
        file.write_all(&self.levels)?;
        file.write_all(&self.offsets)?;
        file.write_all(&self.adjacency)?;
        file.set_len(adjacency_offset + self.adjacency.len() as u64)?;
        file.sync_all()?;
        Ok(())
    }
}

#[derive(Clone, Serialize, Deserialize, Debug)]
pub(crate) struct LegacyDiskMetadata {
    pub dim: usize,
    pub num_vectors: usize,
    pub max_level: u32,
    pub entry_point: u32,
    pub vectors_offset: u64,
    pub levels_offset: u64,
    pub offsets_offset: u64,
    pub adjacency_offset: u64,
    pub elem_size: u8,
}

fn push_legacy_row(output: &mut Vec<u32>, row: &[u32]) {
    output.push(row.len() as u32);
    output.extend_from_slice(row);
}

fn take_legacy_row<'a>(
    adjacency: &'a [u32],
    cursor: &mut usize,
) -> Result<&'a [u32], HyperbolicDiskError> {
    let count = *adjacency
        .get(*cursor)
        .ok_or(HyperbolicDiskError::InvalidArchiveRange)? as usize;
    *cursor += 1;
    let end = (*cursor)
        .checked_add(count)
        .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
    let row = adjacency
        .get(*cursor..end)
        .ok_or(HyperbolicDiskError::InvalidArchiveRange)?;
    *cursor = end;
    Ok(row)
}

fn parse_f32s(bytes: &[u8], count: usize) -> Result<Vec<f32>, HyperbolicDiskError> {
    parse_fixed(bytes, count, |chunk| {
        f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]])
    })
}

fn parse_u32s(bytes: &[u8], count: usize) -> Result<Vec<u32>, HyperbolicDiskError> {
    parse_fixed(bytes, count, |chunk| {
        u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]])
    })
}

fn parse_u32s_any(bytes: &[u8]) -> Result<Vec<u32>, HyperbolicDiskError> {
    if !bytes.len().is_multiple_of(4) {
        return Err(HyperbolicDiskError::InvalidArchiveRange);
    }
    parse_u32s(bytes, bytes.len() / 4)
}

fn parse_u64s(bytes: &[u8], count: usize) -> Result<Vec<u64>, HyperbolicDiskError> {
    parse_fixed(bytes, count, |chunk| {
        u64::from_le_bytes([
            chunk[0], chunk[1], chunk[2], chunk[3], chunk[4], chunk[5], chunk[6], chunk[7],
        ])
    })
}

fn parse_fixed<T>(
    bytes: &[u8],
    count: usize,
    decode: impl Fn(&[u8]) -> T,
) -> Result<Vec<T>, HyperbolicDiskError> {
    let width = std::mem::size_of::<T>();
    if bytes.len() != count.saturating_mul(width) {
        return Err(HyperbolicDiskError::InvalidArchiveRange);
    }
    Ok(bytes.chunks_exact(width).map(decode).collect())
}

use std::fs::{File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use memmap2::{Mmap, MmapOptions};
use serde::{Deserialize, Serialize};

use crate::constants::{GRAPH_ARTIFACT_MAGIC, GRAPH_ARTIFACT_VERSION};
use crate::error::io_error;
use crate::graph::IncomingCsr;
use crate::{GfmError, Result};

const HEADER_BYTES: usize = 64;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ArtifactManifest {
    pub schema: String,
    pub byte_length: u64,
    pub blake3: String,
    pub node_count: u64,
    pub relation_count: u32,
    pub edge_count: u64,
}

pub fn write_graph_artifact(
    graph: &IncomingCsr,
    path: impl AsRef<Path>,
) -> Result<ArtifactManifest> {
    let path = path.as_ref();
    let file = File::create(path).map_err(|error| io_error(path, error))?;
    let mut writer = BufWriter::new(file);
    let offsets_offset = HEADER_BYTES as u64;
    let src_offset = offsets_offset + (graph.dst_offsets().len() * 8) as u64;
    let relation_offset = src_offset + (graph.src_nodes().len() * 4) as u64;

    let mut header = [0_u8; HEADER_BYTES];
    header[0..8].copy_from_slice(&GRAPH_ARTIFACT_MAGIC);
    header[8..12].copy_from_slice(&GRAPH_ARTIFACT_VERSION.to_le_bytes());
    header[12..16].copy_from_slice(&(HEADER_BYTES as u32).to_le_bytes());
    header[16..24].copy_from_slice(&(graph.node_count() as u64).to_le_bytes());
    header[24..28].copy_from_slice(&(graph.relation_count() as u32).to_le_bytes());
    header[32..40].copy_from_slice(&(graph.edge_count() as u64).to_le_bytes());
    header[40..48].copy_from_slice(&offsets_offset.to_le_bytes());
    header[48..56].copy_from_slice(&src_offset.to_le_bytes());
    header[56..64].copy_from_slice(&relation_offset.to_le_bytes());
    writer
        .write_all(&header)
        .map_err(|error| io_error(path, error))?;
    write_u64s(&mut writer, graph.dst_offsets()).map_err(|error| io_error(path, error))?;
    write_u32s(&mut writer, graph.src_nodes()).map_err(|error| io_error(path, error))?;
    write_u32s(&mut writer, graph.relation_ids()).map_err(|error| io_error(path, error))?;
    writer.flush().map_err(|error| io_error(path, error))?;
    drop(writer);

    let mut reader = BufReader::new(File::open(path).map_err(|error| io_error(path, error))?);
    let mut hasher = blake3::Hasher::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut byte_length = 0_u64;
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|error| io_error(path, error))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
        byte_length += read as u64;
    }
    Ok(ArtifactManifest {
        schema: "phoenix.gfm.incoming-csr.v1".into(),
        byte_length,
        blake3: hasher.finalize().to_hex().to_string(),
        node_count: graph.node_count() as u64,
        relation_count: graph.relation_count() as u32,
        edge_count: graph.edge_count() as u64,
    })
}

fn write_u64s(writer: &mut impl Write, values: &[u64]) -> std::io::Result<()> {
    for value in values {
        writer.write_all(&value.to_le_bytes())?;
    }
    Ok(())
}

fn write_u32s(writer: &mut impl Write, values: &[u32]) -> std::io::Result<()> {
    for value in values {
        writer.write_all(&value.to_le_bytes())?;
    }
    Ok(())
}

/// Immutable mmap view. The packed sections are borrowed directly from the map.
pub struct MappedIncomingCsr {
    mmap: Mmap,
    node_count: usize,
    relation_count: usize,
    edge_count: usize,
    offsets_offset: usize,
    src_offset: usize,
    relation_offset: usize,
    path: PathBuf,
}

impl std::fmt::Debug for MappedIncomingCsr {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("MappedIncomingCsr")
            .field("path", &self.path)
            .field("node_count", &self.node_count)
            .field("relation_count", &self.relation_count)
            .field("edge_count", &self.edge_count)
            .finish()
    }
}

impl MappedIncomingCsr {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        let file = OpenOptions::new()
            .read(true)
            .open(&path)
            .map_err(|error| io_error(&path, error))?;
        // SAFETY: the file is held through mmap creation and the returned map is
        // read-only. Artifacts are immutable after publication.
        let mmap =
            unsafe { MmapOptions::new().map(&file) }.map_err(|error| io_error(&path, error))?;
        if mmap.len() < HEADER_BYTES {
            return Err(GfmError::InvalidArtifact("truncated CSR header".into()));
        }
        if memchr::memmem::find(&mmap[..HEADER_BYTES], &GRAPH_ARTIFACT_MAGIC) != Some(0) {
            return Err(GfmError::InvalidArtifact("bad CSR magic".into()));
        }
        let version = read_u32(&mmap, 8)?;
        if version != GRAPH_ARTIFACT_VERSION || read_u32(&mmap, 12)? as usize != HEADER_BYTES {
            return Err(GfmError::InvalidArtifact(format!(
                "unsupported CSR version {version}"
            )));
        }
        let node_count = usize::try_from(read_u64(&mmap, 16)?)
            .map_err(|_| GfmError::InvalidArtifact("node count overflow".into()))?;
        let relation_count = read_u32(&mmap, 24)? as usize;
        let edge_count = usize::try_from(read_u64(&mmap, 32)?)
            .map_err(|_| GfmError::InvalidArtifact("edge count overflow".into()))?;
        let offsets_offset = read_u64(&mmap, 40)? as usize;
        let src_offset = read_u64(&mmap, 48)? as usize;
        let relation_offset = read_u64(&mmap, 56)? as usize;
        let expected = relation_offset
            .checked_add(edge_count * 4)
            .ok_or_else(|| GfmError::InvalidArtifact("CSR length overflow".into()))?;
        if offsets_offset != HEADER_BYTES
            || src_offset != offsets_offset + (node_count + 1) * 8
            || relation_offset != src_offset + edge_count * 4
            || mmap.len() != expected
        {
            return Err(GfmError::InvalidArtifact(
                "non-canonical CSR section layout".into(),
            ));
        }
        Ok(Self {
            mmap,
            node_count,
            relation_count,
            edge_count,
            offsets_offset,
            src_offset,
            relation_offset,
            path,
        })
    }

    pub fn node_count(&self) -> usize {
        self.node_count
    }
    pub fn relation_count(&self) -> usize {
        self.relation_count
    }
    pub fn edge_count(&self) -> usize {
        self.edge_count
    }

    pub fn dst_offsets(&self) -> &[u64] {
        cast_aligned(&self.mmap[self.offsets_offset..self.src_offset])
    }

    pub fn src_nodes(&self) -> &[u32] {
        cast_aligned(&self.mmap[self.src_offset..self.relation_offset])
    }

    pub fn relation_ids(&self) -> &[u32] {
        cast_aligned(&self.mmap[self.relation_offset..])
    }
}

#[cfg(target_endian = "little")]
fn cast_aligned<T: bytemuck::Pod>(bytes: &[u8]) -> &[T] {
    // Section offsets are aligned by construction. The mmap base is page aligned.
    bytemuck::cast_slice(bytes)
}

#[cfg(not(target_endian = "little"))]
compile_error!("GFM graph artifacts currently require a little-endian target");

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32> {
    let raw = bytes
        .get(offset..offset + 4)
        .ok_or_else(|| GfmError::InvalidArtifact("truncated u32".into()))?;
    let value = zerocopy::Ref::<_, zerocopy::little_endian::U32>::new(raw)
        .ok_or_else(|| GfmError::InvalidArtifact("unaligned u32".into()))?;
    Ok(value.get())
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64> {
    let raw = bytes
        .get(offset..offset + 8)
        .ok_or_else(|| GfmError::InvalidArtifact("truncated u64".into()))?;
    let value = zerocopy::Ref::<_, zerocopy::little_endian::U64>::new(raw)
        .ok_or_else(|| GfmError::InvalidArtifact("unaligned u64".into()))?;
    Ok(value.get())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::Edge;

    #[test]
    fn round_trips_through_read_only_mmap() {
        let graph = IncomingCsr::from_edges(
            3,
            2,
            [Edge {
                src: 0,
                relation: 1,
                dst: 2,
            }],
        )
        .unwrap();
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("graph.gfmcsr");
        let manifest = write_graph_artifact(&graph, &path).unwrap();
        let mapped = MappedIncomingCsr::open(path).unwrap();
        assert_eq!(manifest.edge_count, 1);
        assert_eq!(mapped.dst_offsets(), graph.dst_offsets());
        assert_eq!(mapped.src_nodes(), graph.src_nodes());
        assert_eq!(mapped.relation_ids(), graph.relation_ids());
    }
}

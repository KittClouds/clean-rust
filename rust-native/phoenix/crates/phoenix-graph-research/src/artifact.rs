use crate::model::*;
use hashbrown::HashMap;
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Path, PathBuf};
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MAGIC: [u8; 8] = *b"PHXFGR01";

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct BinaryHeader {
    magic: [u8; 8],
    version: [u8; 2],
    flags: [u8; 2],
    total_bytes: [u8; 8],
    frozen_at_ms: [u8; 8],
    checkpoint_generation: [u8; 8],
    node_offset: [u8; 8],
    node_count: [u8; 8],
    edge_offset: [u8; 8],
    edge_count: [u8; 8],
    incidence_offset: [u8; 8],
    incidence_count: [u8; 8],
    proposal_offset: [u8; 8],
    proposal_count: [u8; 8],
    arena_offset: [u8; 8],
    arena_bytes: [u8; 8],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct FrozenNodeRecord {
    id: StringRef,
    kind: StringRef,
    available_at_ms: [u8; 8],
    source_generation: [u8; 8],
    authority: u8,
    split: u8,
    reserved: [u8; 6],
}

impl FrozenNodeRecord {
    pub fn available_at_ms(self) -> i64 {
        i64::from_le_bytes(self.available_at_ms)
    }
    pub fn source_generation(self) -> u64 {
        u64::from_le_bytes(self.source_generation)
    }
    pub fn authority(self) -> u8 {
        self.authority
    }
    pub fn split(self) -> u8 {
        self.split
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct FrozenEdgeRecord {
    source: [u8; 4],
    target: [u8; 4],
    relation: StringRef,
    available_at_ms: [u8; 8],
    weight: [u8; 4],
    authority: u8,
    split: u8,
    reserved: [u8; 2],
}

impl FrozenEdgeRecord {
    pub fn source(self) -> u32 {
        u32::from_le_bytes(self.source)
    }
    pub fn target(self) -> u32 {
        u32::from_le_bytes(self.target)
    }
    pub fn available_at_ms(self) -> i64 {
        i64::from_le_bytes(self.available_at_ms)
    }
    pub fn weight(self) -> f32 {
        f32::from_bits(u32::from_le_bytes(self.weight))
    }
    pub fn authority(self) -> u8 {
        self.authority
    }
    pub fn split(self) -> u8 {
        self.split
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct FrozenIncidenceRecord {
    hyperedge: [u8; 4],
    participant: [u8; 4],
    role: StringRef,
    split: u8,
    resolved: u8,
    reserved: [u8; 6],
}

impl FrozenIncidenceRecord {
    pub fn hyperedge(self) -> u32 {
        u32::from_le_bytes(self.hyperedge)
    }
    pub fn participant(self) -> u32 {
        u32::from_le_bytes(self.participant)
    }
    pub fn split(self) -> u8 {
        self.split
    }
    pub fn resolved(self) -> bool {
        self.resolved != 0
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct FrozenProposalRecord {
    proposal_id: StringRef,
    receipt_id: StringRef,
    feature_schema_id: StringRef,
    observed_at_ms: [u8; 8],
    label_available_at_ms: [u8; 8],
    features: [[u8; 2]; PROPOSAL_FEATURE_DIM],
    split: u8,
    label: u8,
    reserved: [u8; 6],
}

impl FrozenProposalRecord {
    pub fn observed_at_ms(self) -> i64 {
        i64::from_le_bytes(self.observed_at_ms)
    }
    pub fn label_available_at_ms(self) -> i64 {
        i64::from_le_bytes(self.label_available_at_ms)
    }
    pub fn feature(self, index: usize) -> Option<i16> {
        self.features
            .get(index)
            .map(|value| i16::from_le_bytes(*value))
    }
    pub fn split(self) -> u8 {
        self.split
    }
    pub fn label(self) -> u8 {
        self.label
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct StringRef {
    offset: [u8; 4],
    len: [u8; 4],
}

impl StringRef {
    fn new(offset: usize, len: usize) -> Result<Self, FrozenGraphResearchError> {
        Ok(Self {
            offset: checked_u32(offset, "string offset")?.to_le_bytes(),
            len: checked_u32(len, "string length")?.to_le_bytes(),
        })
    }

    fn range(self, arena_offset: usize, arena_len: usize) -> Option<std::ops::Range<usize>> {
        let relative = u32::from_le_bytes(self.offset) as usize;
        let len = u32::from_le_bytes(self.len) as usize;
        let end = relative.checked_add(len)?;
        if end > arena_len {
            return None;
        }
        Some(arena_offset + relative..arena_offset + end)
    }
}

#[derive(Default)]
struct StringArena {
    bytes: Vec<u8>,
    refs: HashMap<String, StringRef>,
}

impl StringArena {
    fn intern(&mut self, value: &str) -> Result<StringRef, FrozenGraphResearchError> {
        if let Some(reference) = self.refs.get(value).copied() {
            return Ok(reference);
        }
        let reference = StringRef::new(self.bytes.len(), value.len())?;
        self.bytes.extend_from_slice(value.as_bytes());
        self.refs.insert(value.to_owned(), reference);
        Ok(reference)
    }
}

pub struct FrozenGraphResearchBundle;

impl FrozenGraphResearchBundle {
    pub fn write(
        snapshot: &FrozenGraphResearchSnapshot,
        root: impl AsRef<Path>,
    ) -> Result<FrozenGraphResearchPaths, FrozenGraphResearchError> {
        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let binary_name = format!("{}.fgr", snapshot.dataset_id);
        let manifest_name = format!("{}.manifest.json", snapshot.dataset_id);
        let binary_path = root.join(&binary_name);
        let manifest_path = root.join(manifest_name);
        if binary_path.exists() || manifest_path.exists() {
            return Err(FrozenGraphResearchError::ArtifactExists(binary_path));
        }
        let bytes = encode(snapshot)?;
        let binary_blake3 = format!("b3-{}", blake3::hash(&bytes).to_hex());
        write_immutable(&binary_path, &bytes)?;
        let manifest = FrozenGraphResearchManifest {
            schema_version: FROZEN_GRAPH_RESEARCH_SCHEMA.into(),
            dataset_id: snapshot.dataset_id.clone(),
            checkpoint_id: snapshot.checkpoint_id.clone(),
            checkpoint_generation: snapshot.checkpoint_generation,
            frozen_at_ms: snapshot.frozen_at_ms,
            split_policy: snapshot.split_policy,
            binary_file: binary_name.into(),
            binary_blake3: binary_blake3.into(),
            binary_bytes: bytes.len() as u64,
            nodes: snapshot.nodes.len() as u64,
            edges: snapshot.edges.len() as u64,
            incidences: snapshot.incidences.len() as u64,
            proposals: snapshot.proposals.len() as u64,
        };
        let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
        if let Err(error) = write_immutable(&manifest_path, &manifest_bytes) {
            let _ = std::fs::remove_file(&binary_path);
            return Err(error);
        }
        Ok(FrozenGraphResearchPaths {
            manifest: manifest_path,
            binary: binary_path,
        })
    }
}

pub struct FrozenGraphResearchMapped {
    manifest: FrozenGraphResearchManifest,
    map: Mmap,
}

impl FrozenGraphResearchMapped {
    pub fn open(manifest_path: impl AsRef<Path>) -> Result<Self, FrozenGraphResearchError> {
        let manifest_path = manifest_path.as_ref();
        let manifest: FrozenGraphResearchManifest =
            serde_json::from_slice(&std::fs::read(manifest_path)?)?;
        if manifest.schema_version != FROZEN_GRAPH_RESEARCH_SCHEMA {
            return Err(FrozenGraphResearchError::CorruptArtifact("schema version"));
        }
        let binary_path = manifest_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(manifest.binary_file.as_str());
        let file = File::open(binary_path)?;
        let map = unsafe { Mmap::map(&file)? };
        let digest = format!("b3-{}", blake3::hash(&map).to_hex());
        if digest != manifest.binary_blake3 || map.len() as u64 != manifest.binary_bytes {
            return Err(FrozenGraphResearchError::CorruptArtifact("binary digest"));
        }
        let result = Self { manifest, map };
        result.validate_header()?;
        Ok(result)
    }

    pub fn manifest(&self) -> &FrozenGraphResearchManifest {
        &self.manifest
    }

    pub fn node_records(&self) -> Result<Ref<&[u8], [FrozenNodeRecord]>, FrozenGraphResearchError> {
        self.table(self.header()?.node_offset, self.header()?.node_count)
    }

    pub fn edge_records(&self) -> Result<Ref<&[u8], [FrozenEdgeRecord]>, FrozenGraphResearchError> {
        self.table(self.header()?.edge_offset, self.header()?.edge_count)
    }

    pub fn incidence_records(
        &self,
    ) -> Result<Ref<&[u8], [FrozenIncidenceRecord]>, FrozenGraphResearchError> {
        self.table(
            self.header()?.incidence_offset,
            self.header()?.incidence_count,
        )
    }

    pub fn proposal_records(
        &self,
    ) -> Result<Ref<&[u8], [FrozenProposalRecord]>, FrozenGraphResearchError> {
        self.table(
            self.header()?.proposal_offset,
            self.header()?.proposal_count,
        )
    }

    pub fn node_id(&self, record: FrozenNodeRecord) -> Option<&str> {
        self.string(record.id)
    }

    pub fn node_kind(&self, record: FrozenNodeRecord) -> Option<&str> {
        self.string(record.kind)
    }

    pub fn edge_relation(&self, record: FrozenEdgeRecord) -> Option<&str> {
        self.string(record.relation)
    }

    pub fn incidence_role(&self, record: FrozenIncidenceRecord) -> Option<&str> {
        self.string(record.role)
    }

    pub fn proposal_id(&self, record: FrozenProposalRecord) -> Option<&str> {
        self.string(record.proposal_id)
    }

    pub fn proposal_receipt_id(&self, record: FrozenProposalRecord) -> Option<&str> {
        self.string(record.receipt_id)
    }

    pub fn proposal_feature_schema_id(&self, record: FrozenProposalRecord) -> Option<&str> {
        self.string(record.feature_schema_id)
    }

    fn validate_header(&self) -> Result<(), FrozenGraphResearchError> {
        let header = self.header()?;
        if header.magic != MAGIC
            || u16::from_le_bytes(header.version) != FROZEN_GRAPH_RESEARCH_BINARY_VERSION
            || u64::from_le_bytes(header.total_bytes) as usize != self.map.len()
            || i64::from_le_bytes(header.frozen_at_ms) != self.manifest.frozen_at_ms
            || u64::from_le_bytes(header.checkpoint_generation)
                != self.manifest.checkpoint_generation
            || u64::from_le_bytes(header.node_count) != self.manifest.nodes
            || u64::from_le_bytes(header.edge_count) != self.manifest.edges
            || u64::from_le_bytes(header.incidence_count) != self.manifest.incidences
            || u64::from_le_bytes(header.proposal_count) != self.manifest.proposals
        {
            return Err(FrozenGraphResearchError::CorruptArtifact("binary header"));
        }
        self.node_records()?;
        self.edge_records()?;
        self.incidence_records()?;
        self.proposal_records()?;
        Ok(())
    }

    fn header(&self) -> Result<BinaryHeader, FrozenGraphResearchError> {
        Ref::<_, BinaryHeader>::new(
            self.map
                .get(..size_of::<BinaryHeader>())
                .ok_or(FrozenGraphResearchError::CorruptArtifact("short header"))?,
        )
        .map(|value| *value)
        .ok_or(FrozenGraphResearchError::CorruptArtifact("header layout"))
    }

    fn table<T: FromBytes + Unaligned>(
        &self,
        offset: [u8; 8],
        count: [u8; 8],
    ) -> Result<Ref<&[u8], [T]>, FrozenGraphResearchError> {
        let start = u64::from_le_bytes(offset) as usize;
        let count = u64::from_le_bytes(count) as usize;
        let byte_len = count
            .checked_mul(size_of::<T>())
            .ok_or(FrozenGraphResearchError::CorruptArtifact("table overflow"))?;
        let end = start
            .checked_add(byte_len)
            .ok_or(FrozenGraphResearchError::CorruptArtifact("table range"))?;
        Ref::<_, [T]>::new_slice(
            self.map
                .get(start..end)
                .ok_or(FrozenGraphResearchError::CorruptArtifact("table bounds"))?,
        )
        .ok_or(FrozenGraphResearchError::CorruptArtifact("table layout"))
    }

    fn string(&self, reference: StringRef) -> Option<&str> {
        let header = self.header().ok()?;
        let arena_offset = u64::from_le_bytes(header.arena_offset) as usize;
        let arena_len = u64::from_le_bytes(header.arena_bytes) as usize;
        let range = reference.range(arena_offset, arena_len)?;
        std::str::from_utf8(self.map.get(range)?).ok()
    }
}

fn encode(snapshot: &FrozenGraphResearchSnapshot) -> Result<Vec<u8>, FrozenGraphResearchError> {
    let mut arena = StringArena::default();
    let nodes = snapshot
        .nodes
        .iter()
        .map(|node| {
            Ok(FrozenNodeRecord {
                id: arena.intern(&node.id)?,
                kind: arena.intern(&node.kind)?,
                available_at_ms: node.available_at_ms.to_le_bytes(),
                source_generation: node.source_generation.to_le_bytes(),
                authority: node.authority as u8,
                split: node.split as u8,
                reserved: [0; 6],
            })
        })
        .collect::<Result<Vec<_>, FrozenGraphResearchError>>()?;
    let edges = snapshot
        .edges
        .iter()
        .map(|edge| {
            Ok(FrozenEdgeRecord {
                source: edge.source.to_le_bytes(),
                target: edge.target.to_le_bytes(),
                relation: arena.intern(&edge.relation)?,
                available_at_ms: edge.available_at_ms.to_le_bytes(),
                weight: edge.weight.to_bits().to_le_bytes(),
                authority: edge.authority as u8,
                split: edge.split as u8,
                reserved: [0; 2],
            })
        })
        .collect::<Result<Vec<_>, FrozenGraphResearchError>>()?;
    let incidences = snapshot
        .incidences
        .iter()
        .map(|row| {
            Ok(FrozenIncidenceRecord {
                hyperedge: row.hyperedge.to_le_bytes(),
                participant: row.participant.to_le_bytes(),
                role: arena.intern(&row.role)?,
                split: row.split as u8,
                resolved: u8::from(row.resolved),
                reserved: [0; 6],
            })
        })
        .collect::<Result<Vec<_>, FrozenGraphResearchError>>()?;
    let proposals = snapshot
        .proposals
        .iter()
        .map(|row| {
            Ok(FrozenProposalRecord {
                proposal_id: arena.intern(&row.proposal_id)?,
                receipt_id: arena.intern(&row.receipt_id)?,
                feature_schema_id: arena.intern(&row.feature_schema_id)?,
                observed_at_ms: row.observed_at_ms.to_le_bytes(),
                label_available_at_ms: row.label_available_at_ms.to_le_bytes(),
                features: row.features.map(i16::to_le_bytes),
                split: row.split as u8,
                label: row.label as u8,
                reserved: [0; 6],
            })
        })
        .collect::<Result<Vec<_>, FrozenGraphResearchError>>()?;
    let header_len = size_of::<BinaryHeader>();
    let node_offset = header_len;
    let edge_offset = node_offset + size_of_val(nodes.as_slice());
    let incidence_offset = edge_offset + size_of_val(edges.as_slice());
    let proposal_offset = incidence_offset + size_of_val(incidences.as_slice());
    let arena_offset = proposal_offset + size_of_val(proposals.as_slice());
    let total_bytes = arena_offset + arena.bytes.len();
    let header = BinaryHeader {
        magic: MAGIC,
        version: FROZEN_GRAPH_RESEARCH_BINARY_VERSION.to_le_bytes(),
        flags: [0; 2],
        total_bytes: (total_bytes as u64).to_le_bytes(),
        frozen_at_ms: snapshot.frozen_at_ms.to_le_bytes(),
        checkpoint_generation: snapshot.checkpoint_generation.to_le_bytes(),
        node_offset: (node_offset as u64).to_le_bytes(),
        node_count: (nodes.len() as u64).to_le_bytes(),
        edge_offset: (edge_offset as u64).to_le_bytes(),
        edge_count: (edges.len() as u64).to_le_bytes(),
        incidence_offset: (incidence_offset as u64).to_le_bytes(),
        incidence_count: (incidences.len() as u64).to_le_bytes(),
        proposal_offset: (proposal_offset as u64).to_le_bytes(),
        proposal_count: (proposals.len() as u64).to_le_bytes(),
        arena_offset: (arena_offset as u64).to_le_bytes(),
        arena_bytes: (arena.bytes.len() as u64).to_le_bytes(),
    };
    let mut bytes = Vec::with_capacity(total_bytes);
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(nodes.as_bytes());
    bytes.extend_from_slice(edges.as_bytes());
    bytes.extend_from_slice(incidences.as_bytes());
    bytes.extend_from_slice(proposals.as_bytes());
    bytes.extend_from_slice(&arena.bytes);
    Ok(bytes)
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), FrozenGraphResearchError> {
    let temporary = temporary_path(path);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    if let Err(error) = file.write_all(bytes).and_then(|_| file.sync_all()) {
        let _ = std::fs::remove_file(&temporary);
        return Err(error.into());
    }
    if path.exists() {
        let _ = std::fs::remove_file(&temporary);
        return Err(FrozenGraphResearchError::ArtifactExists(path.to_path_buf()));
    }
    std::fs::rename(temporary, path)?;
    Ok(())
}

fn temporary_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("research");
    path.with_file_name(format!(".{name}.tmp"))
}

fn checked_u32(value: usize, field: &'static str) -> Result<u32, FrozenGraphResearchError> {
    u32::try_from(value).map_err(|_| FrozenGraphResearchError::CorruptArtifact(field))
}

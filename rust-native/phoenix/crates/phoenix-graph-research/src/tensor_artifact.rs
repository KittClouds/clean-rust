use crate::{
    FrozenGraphResearchError, FrozenTensorManifest, FrozenTensorPaths, FrozenTensorSnapshot,
    FROZEN_TENSOR_BINARY_VERSION, FROZEN_TENSOR_SCHEMA, PROPOSAL_FEATURE_DIM,
};
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::size_of;
use std::path::{Path, PathBuf};
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MAGIC: [u8; 8] = *b"PHXFGT01";
const SECTION_COUNT: usize = 27;
const NODE_TYPE: usize = 0;
const NODE_AUTHORITY: usize = 1;
const NODE_SPLIT: usize = 2;
const NODE_AVAILABLE: usize = 3;
const COO_SOURCE: usize = 4;
const COO_TARGET: usize = 5;
const COO_RELATION: usize = 6;
const COO_AUTHORITY: usize = 7;
const COO_SPLIT: usize = 8;
const COO_AVAILABLE: usize = 9;
const COO_WEIGHT: usize = 10;
const CSR_OFFSETS: usize = 11;
const CSR_COLUMNS: usize = 12;
const CSR_EDGE_INDEX: usize = 13;
const INCIDENCE_HYPEREDGE: usize = 14;
const INCIDENCE_PARTICIPANT: usize = 15;
const INCIDENCE_ROLE: usize = 16;
const INCIDENCE_SPLIT: usize = 17;
const INCIDENCE_RESOLVED: usize = 18;
const PROPOSAL_FEATURE: usize = 19;
const PROPOSAL_LABEL: usize = 20;
const PROPOSAL_LABEL_OBSERVED: usize = 21;
const PROPOSAL_SPLIT: usize = 22;
const PROPOSAL_OBSERVED: usize = 23;
const PROPOSAL_LABEL_AVAILABLE: usize = 24;
const PROPOSAL_SCHEMA: usize = 25;
const NEGATIVE: usize = 26;

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
struct SectionHeader {
    offset: [u8; 8],
    count: [u8; 8],
    element_bytes: [u8; 4],
    reserved: [u8; 4],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy)]
#[repr(C)]
struct TensorHeader {
    magic: [u8; 8],
    version: [u8; 2],
    section_count: [u8; 2],
    total_bytes: [u8; 8],
    sections: [SectionHeader; SECTION_COUNT],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct LeU32([u8; 4]);
impl LeU32 {
    pub fn get(self) -> u32 {
        u32::from_le_bytes(self.0)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct LeU64([u8; 8]);
impl LeU64 {
    pub fn get(self) -> u64 {
        u64::from_le_bytes(self.0)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct LeI64([u8; 8]);
impl LeI64 {
    pub fn get(self) -> i64 {
        i64::from_le_bytes(self.0)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct LeI16([u8; 2]);
impl LeI16 {
    pub fn get(self) -> i16 {
        i16::from_le_bytes(self.0)
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct LeF32([u8; 4]);
impl LeF32 {
    pub fn get(self) -> f32 {
        f32::from_bits(u32::from_le_bytes(self.0))
    }
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy, Default)]
#[repr(C)]
pub struct TensorNegativeRecord {
    positive_edge: [u8; 4],
    source: [u8; 4],
    target: [u8; 4],
    relation_type: [u8; 4],
    split: u8,
    reserved: [u8; 3],
}

impl TensorNegativeRecord {
    pub fn positive_edge(self) -> u32 {
        u32::from_le_bytes(self.positive_edge)
    }
    pub fn source(self) -> u32 {
        u32::from_le_bytes(self.source)
    }
    pub fn target(self) -> u32 {
        u32::from_le_bytes(self.target)
    }
    pub fn relation_type(self) -> u32 {
        u32::from_le_bytes(self.relation_type)
    }
    pub fn split(self) -> u8 {
        self.split
    }
}

pub struct FrozenTensorBundle;

impl FrozenTensorBundle {
    pub fn write(
        snapshot: &FrozenTensorSnapshot,
        root: impl AsRef<Path>,
    ) -> Result<FrozenTensorPaths, FrozenGraphResearchError> {
        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let binary_name = format!("{}.fgt", snapshot.tensor_id);
        let manifest_name = format!("{}.tensor-manifest.json", snapshot.tensor_id);
        let binary = root.join(&binary_name);
        let manifest = root.join(manifest_name);
        if binary.exists() || manifest.exists() {
            return Err(FrozenGraphResearchError::ArtifactExists(binary));
        }
        let bytes = encode(snapshot)?;
        let binary_blake3 = format!("b3-{}", blake3::hash(&bytes).to_hex());
        write_immutable(&binary, &bytes)?;
        let metadata = FrozenTensorManifest {
            schema_version: FROZEN_TENSOR_SCHEMA.into(),
            tensor_id: snapshot.tensor_id.clone(),
            source_dataset_id: snapshot.source_dataset_id.clone(),
            policy: snapshot.policy,
            binary_file: binary_name.into(),
            binary_blake3: binary_blake3.into(),
            binary_bytes: bytes.len() as u64,
            nodes: snapshot.node_type_ids.len() as u64,
            edges: snapshot.coo_sources.len() as u64,
            incidences: snapshot.incidence_hyperedges.len() as u64,
            proposals: snapshot.proposal_labels.len() as u64,
            negatives: snapshot.negatives.len() as u64,
            node_type_vocabulary: snapshot.node_type_vocabulary.clone(),
            relation_vocabulary: snapshot.relation_vocabulary.clone(),
            role_vocabulary: snapshot.role_vocabulary.clone(),
            feature_schema_vocabulary: snapshot.feature_schema_vocabulary.clone(),
            feature_certificates: snapshot.feature_certificates.clone(),
        };
        let manifest_bytes = serde_json::to_vec_pretty(&metadata)?;
        if let Err(error) = write_immutable(&manifest, &manifest_bytes) {
            let _ = std::fs::remove_file(&binary);
            return Err(error);
        }
        Ok(FrozenTensorPaths { manifest, binary })
    }
}

pub struct FrozenTensorMapped {
    manifest: FrozenTensorManifest,
    map: Mmap,
}

impl FrozenTensorMapped {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, FrozenGraphResearchError> {
        let path = path.as_ref();
        let manifest: FrozenTensorManifest = serde_json::from_slice(&std::fs::read(path)?)?;
        if manifest.schema_version != FROZEN_TENSOR_SCHEMA {
            return Err(FrozenGraphResearchError::CorruptArtifact("tensor schema"));
        }
        let binary = path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(manifest.binary_file.as_str());
        let file = File::open(binary)?;
        let map = unsafe { Mmap::map(&file)? };
        if map.len() as u64 != manifest.binary_bytes
            || format!("b3-{}", blake3::hash(&map).to_hex()) != manifest.binary_blake3
        {
            return Err(FrozenGraphResearchError::CorruptArtifact(
                "tensor binary digest",
            ));
        }
        let mapped = Self { manifest, map };
        mapped.validate()?;
        Ok(mapped)
    }

    pub fn manifest(&self) -> &FrozenTensorManifest {
        &self.manifest
    }

    pub fn node_type_ids(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(NODE_TYPE)
    }
    pub fn node_authority(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(NODE_AUTHORITY)
    }
    pub fn node_splits(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(NODE_SPLIT)
    }
    pub fn node_available_at_ms(&self) -> Result<Ref<&[u8], [LeI64]>, FrozenGraphResearchError> {
        self.section(NODE_AVAILABLE)
    }
    pub fn coo_sources(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(COO_SOURCE)
    }
    pub fn coo_targets(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(COO_TARGET)
    }
    pub fn coo_relation_types(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(COO_RELATION)
    }
    pub fn coo_authority(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(COO_AUTHORITY)
    }
    pub fn coo_splits(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(COO_SPLIT)
    }
    pub fn coo_available_at_ms(&self) -> Result<Ref<&[u8], [LeI64]>, FrozenGraphResearchError> {
        self.section(COO_AVAILABLE)
    }
    pub fn coo_weights(&self) -> Result<Ref<&[u8], [LeF32]>, FrozenGraphResearchError> {
        self.section(COO_WEIGHT)
    }
    pub fn csr_row_offsets(&self) -> Result<Ref<&[u8], [LeU64]>, FrozenGraphResearchError> {
        self.section(CSR_OFFSETS)
    }
    pub fn csr_columns(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(CSR_COLUMNS)
    }
    pub fn csr_edge_indices(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(CSR_EDGE_INDEX)
    }
    pub fn incidence_hyperedges(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(INCIDENCE_HYPEREDGE)
    }
    pub fn incidence_participants(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(INCIDENCE_PARTICIPANT)
    }
    pub fn incidence_role_types(&self) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(INCIDENCE_ROLE)
    }
    pub fn incidence_splits(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(INCIDENCE_SPLIT)
    }
    pub fn incidence_resolved(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(INCIDENCE_RESOLVED)
    }
    pub fn proposal_features(&self) -> Result<Ref<&[u8], [LeI16]>, FrozenGraphResearchError> {
        self.section(PROPOSAL_FEATURE)
    }
    pub fn proposal_labels(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(PROPOSAL_LABEL)
    }
    pub fn proposal_label_observed(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(PROPOSAL_LABEL_OBSERVED)
    }
    pub fn proposal_splits(&self) -> Result<&[u8], FrozenGraphResearchError> {
        self.byte_section(PROPOSAL_SPLIT)
    }
    pub fn proposal_observed_at_ms(&self) -> Result<Ref<&[u8], [LeI64]>, FrozenGraphResearchError> {
        self.section(PROPOSAL_OBSERVED)
    }
    pub fn proposal_label_available_at_ms(
        &self,
    ) -> Result<Ref<&[u8], [LeI64]>, FrozenGraphResearchError> {
        self.section(PROPOSAL_LABEL_AVAILABLE)
    }
    pub fn proposal_feature_schema_ids(
        &self,
    ) -> Result<Ref<&[u8], [LeU32]>, FrozenGraphResearchError> {
        self.section(PROPOSAL_SCHEMA)
    }
    pub fn negatives(
        &self,
    ) -> Result<Ref<&[u8], [TensorNegativeRecord]>, FrozenGraphResearchError> {
        self.section(NEGATIVE)
    }

    fn validate(&self) -> Result<(), FrozenGraphResearchError> {
        let header = self.header()?;
        if header.magic != MAGIC
            || u16::from_le_bytes(header.version) != FROZEN_TENSOR_BINARY_VERSION
            || u16::from_le_bytes(header.section_count) as usize != SECTION_COUNT
            || u64::from_le_bytes(header.total_bytes) as usize != self.map.len()
        {
            return Err(FrozenGraphResearchError::CorruptArtifact("tensor header"));
        }
        let expected = [
            (NODE_TYPE, self.manifest.nodes),
            (NODE_AUTHORITY, self.manifest.nodes),
            (NODE_SPLIT, self.manifest.nodes),
            (NODE_AVAILABLE, self.manifest.nodes),
            (COO_SOURCE, self.manifest.edges),
            (COO_TARGET, self.manifest.edges),
            (COO_RELATION, self.manifest.edges),
            (COO_AUTHORITY, self.manifest.edges),
            (COO_SPLIT, self.manifest.edges),
            (COO_AVAILABLE, self.manifest.edges),
            (COO_WEIGHT, self.manifest.edges),
            (CSR_OFFSETS, self.manifest.nodes + 1),
            (CSR_COLUMNS, self.manifest.edges),
            (CSR_EDGE_INDEX, self.manifest.edges),
            (INCIDENCE_HYPEREDGE, self.manifest.incidences),
            (INCIDENCE_PARTICIPANT, self.manifest.incidences),
            (INCIDENCE_ROLE, self.manifest.incidences),
            (INCIDENCE_SPLIT, self.manifest.incidences),
            (INCIDENCE_RESOLVED, self.manifest.incidences),
            (
                PROPOSAL_FEATURE,
                self.manifest.proposals * PROPOSAL_FEATURE_DIM as u64,
            ),
            (PROPOSAL_LABEL, self.manifest.proposals),
            (PROPOSAL_LABEL_OBSERVED, self.manifest.proposals),
            (PROPOSAL_SPLIT, self.manifest.proposals),
            (PROPOSAL_OBSERVED, self.manifest.proposals),
            (PROPOSAL_LABEL_AVAILABLE, self.manifest.proposals),
            (PROPOSAL_SCHEMA, self.manifest.proposals),
            (NEGATIVE, self.manifest.negatives),
        ];
        for (index, count) in expected {
            let section = header.sections[index];
            if u64::from_le_bytes(section.count) != count {
                return Err(FrozenGraphResearchError::CorruptArtifact(
                    "tensor section count",
                ));
            }
            self.section_bytes(section)?;
        }
        Ok(())
    }

    fn header(&self) -> Result<TensorHeader, FrozenGraphResearchError> {
        Ref::<_, TensorHeader>::new(self.map.get(..size_of::<TensorHeader>()).ok_or(
            FrozenGraphResearchError::CorruptArtifact("short tensor header"),
        )?)
        .map(|value| *value)
        .ok_or(FrozenGraphResearchError::CorruptArtifact(
            "tensor header layout",
        ))
    }

    fn section<T: FromBytes + Unaligned>(
        &self,
        index: usize,
    ) -> Result<Ref<&[u8], [T]>, FrozenGraphResearchError> {
        let header = self.header()?;
        let section =
            *header
                .sections
                .get(index)
                .ok_or(FrozenGraphResearchError::CorruptArtifact(
                    "tensor section index",
                ))?;
        if u32::from_le_bytes(section.element_bytes) as usize != size_of::<T>() {
            return Err(FrozenGraphResearchError::CorruptArtifact(
                "tensor element width",
            ));
        }
        Ref::<_, [T]>::new_slice(self.section_bytes(section)?)
            .ok_or(FrozenGraphResearchError::CorruptArtifact("tensor layout"))
    }

    fn byte_section(&self, index: usize) -> Result<&[u8], FrozenGraphResearchError> {
        let header = self.header()?;
        let section =
            *header
                .sections
                .get(index)
                .ok_or(FrozenGraphResearchError::CorruptArtifact(
                    "tensor byte section index",
                ))?;
        if u32::from_le_bytes(section.element_bytes) != 1 {
            return Err(FrozenGraphResearchError::CorruptArtifact(
                "tensor byte width",
            ));
        }
        self.section_bytes(section)
    }

    fn section_bytes(&self, section: SectionHeader) -> Result<&[u8], FrozenGraphResearchError> {
        let start = u64::from_le_bytes(section.offset) as usize;
        let count = u64::from_le_bytes(section.count) as usize;
        let width = u32::from_le_bytes(section.element_bytes) as usize;
        let end = start
            .checked_add(count.checked_mul(width).ok_or(
                FrozenGraphResearchError::CorruptArtifact("tensor section overflow"),
            )?)
            .ok_or(FrozenGraphResearchError::CorruptArtifact(
                "tensor section range",
            ))?;
        self.map
            .get(start..end)
            .ok_or(FrozenGraphResearchError::CorruptArtifact(
                "tensor section bounds",
            ))
    }
}

fn encode(snapshot: &FrozenTensorSnapshot) -> Result<Vec<u8>, FrozenGraphResearchError> {
    let mut sections = [SectionHeader::default(); SECTION_COUNT];
    let mut bytes = vec![0_u8; size_of::<TensorHeader>()];
    append_u32(
        &mut bytes,
        &mut sections[NODE_TYPE],
        &snapshot.node_type_ids,
    );
    append_u8(
        &mut bytes,
        &mut sections[NODE_AUTHORITY],
        snapshot.node_authority.iter().map(|v| *v as u8),
    );
    append_u8(
        &mut bytes,
        &mut sections[NODE_SPLIT],
        snapshot.node_splits.iter().map(|v| *v as u8),
    );
    append_i64(
        &mut bytes,
        &mut sections[NODE_AVAILABLE],
        &snapshot.node_available_at_ms,
    );
    append_u32(&mut bytes, &mut sections[COO_SOURCE], &snapshot.coo_sources);
    append_u32(&mut bytes, &mut sections[COO_TARGET], &snapshot.coo_targets);
    append_u32(
        &mut bytes,
        &mut sections[COO_RELATION],
        &snapshot.coo_relation_types,
    );
    append_u8(
        &mut bytes,
        &mut sections[COO_AUTHORITY],
        snapshot.coo_authority.iter().map(|v| *v as u8),
    );
    append_u8(
        &mut bytes,
        &mut sections[COO_SPLIT],
        snapshot.coo_splits.iter().map(|v| *v as u8),
    );
    append_i64(
        &mut bytes,
        &mut sections[COO_AVAILABLE],
        &snapshot.coo_available_at_ms,
    );
    append_f32(&mut bytes, &mut sections[COO_WEIGHT], &snapshot.coo_weights);
    append_u64(
        &mut bytes,
        &mut sections[CSR_OFFSETS],
        &snapshot.csr_row_offsets,
    );
    append_u32(
        &mut bytes,
        &mut sections[CSR_COLUMNS],
        &snapshot.csr_columns,
    );
    append_u32(
        &mut bytes,
        &mut sections[CSR_EDGE_INDEX],
        &snapshot.csr_edge_indices,
    );
    append_u32(
        &mut bytes,
        &mut sections[INCIDENCE_HYPEREDGE],
        &snapshot.incidence_hyperedges,
    );
    append_u32(
        &mut bytes,
        &mut sections[INCIDENCE_PARTICIPANT],
        &snapshot.incidence_participants,
    );
    append_u32(
        &mut bytes,
        &mut sections[INCIDENCE_ROLE],
        &snapshot.incidence_role_types,
    );
    append_u8(
        &mut bytes,
        &mut sections[INCIDENCE_SPLIT],
        snapshot.incidence_splits.iter().map(|v| *v as u8),
    );
    append_u8(
        &mut bytes,
        &mut sections[INCIDENCE_RESOLVED],
        snapshot.incidence_resolved.iter().map(|v| u8::from(*v)),
    );
    append_i16(
        &mut bytes,
        &mut sections[PROPOSAL_FEATURE],
        &snapshot.proposal_features,
    );
    append_u8(
        &mut bytes,
        &mut sections[PROPOSAL_LABEL],
        snapshot.proposal_labels.iter().map(|v| *v as u8),
    );
    append_u8(
        &mut bytes,
        &mut sections[PROPOSAL_LABEL_OBSERVED],
        snapshot
            .proposal_label_observed
            .iter()
            .map(|v| u8::from(*v)),
    );
    append_u8(
        &mut bytes,
        &mut sections[PROPOSAL_SPLIT],
        snapshot.proposal_splits.iter().map(|v| *v as u8),
    );
    append_i64(
        &mut bytes,
        &mut sections[PROPOSAL_OBSERVED],
        &snapshot.proposal_observed_at_ms,
    );
    append_i64(
        &mut bytes,
        &mut sections[PROPOSAL_LABEL_AVAILABLE],
        &snapshot.proposal_label_available_at_ms,
    );
    append_u32(
        &mut bytes,
        &mut sections[PROPOSAL_SCHEMA],
        &snapshot.proposal_feature_schema_ids,
    );
    let negative_records = snapshot
        .negatives
        .iter()
        .map(|row| TensorNegativeRecord {
            positive_edge: row.positive_edge.to_le_bytes(),
            source: row.source.to_le_bytes(),
            target: row.target.to_le_bytes(),
            relation_type: row.relation_type.to_le_bytes(),
            split: row.split as u8,
            reserved: [0; 3],
        })
        .collect::<Vec<_>>();
    append_records(&mut bytes, &mut sections[NEGATIVE], &negative_records);
    let header = TensorHeader {
        magic: MAGIC,
        version: FROZEN_TENSOR_BINARY_VERSION.to_le_bytes(),
        section_count: (SECTION_COUNT as u16).to_le_bytes(),
        total_bytes: (bytes.len() as u64).to_le_bytes(),
        sections,
    };
    bytes[..size_of::<TensorHeader>()].copy_from_slice(header.as_bytes());
    Ok(bytes)
}

fn append_records<T: AsBytes>(bytes: &mut Vec<u8>, header: &mut SectionHeader, rows: &[T]) {
    *header = section_header(bytes.len(), rows.len(), size_of::<T>());
    bytes.extend_from_slice(rows.as_bytes());
}
fn append_u32(bytes: &mut Vec<u8>, header: &mut SectionHeader, rows: &[u32]) {
    let encoded = rows
        .iter()
        .map(|v| LeU32(v.to_le_bytes()))
        .collect::<Vec<_>>();
    append_records(bytes, header, &encoded);
}
fn append_u64(bytes: &mut Vec<u8>, header: &mut SectionHeader, rows: &[u64]) {
    let encoded = rows
        .iter()
        .map(|v| LeU64(v.to_le_bytes()))
        .collect::<Vec<_>>();
    append_records(bytes, header, &encoded);
}
fn append_i64(bytes: &mut Vec<u8>, header: &mut SectionHeader, rows: &[i64]) {
    let encoded = rows
        .iter()
        .map(|v| LeI64(v.to_le_bytes()))
        .collect::<Vec<_>>();
    append_records(bytes, header, &encoded);
}
fn append_i16(bytes: &mut Vec<u8>, header: &mut SectionHeader, rows: &[i16]) {
    let encoded = rows
        .iter()
        .map(|v| LeI16(v.to_le_bytes()))
        .collect::<Vec<_>>();
    append_records(bytes, header, &encoded);
}
fn append_f32(bytes: &mut Vec<u8>, header: &mut SectionHeader, rows: &[f32]) {
    let encoded = rows
        .iter()
        .map(|v| LeF32(v.to_bits().to_le_bytes()))
        .collect::<Vec<_>>();
    append_records(bytes, header, &encoded);
}
fn append_u8(bytes: &mut Vec<u8>, header: &mut SectionHeader, rows: impl Iterator<Item = u8>) {
    let start = bytes.len();
    bytes.extend(rows);
    *header = section_header(start, bytes.len() - start, 1);
}
fn section_header(offset: usize, count: usize, width: usize) -> SectionHeader {
    SectionHeader {
        offset: (offset as u64).to_le_bytes(),
        count: (count as u64).to_le_bytes(),
        element_bytes: (width as u32).to_le_bytes(),
        reserved: [0; 4],
    }
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
        .and_then(|v| v.to_str())
        .unwrap_or("tensor");
    path.with_file_name(format!(".{name}.tmp"))
}

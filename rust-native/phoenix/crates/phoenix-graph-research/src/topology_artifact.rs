use crate::{
    ResearchEvaluationError, TrainTopologyFeatureManifest, TrainTopologyFeaturePaths,
    TrainTopologyFeatureSnapshot, TRAIN_TOPOLOGY_BINARY_VERSION, TRAIN_TOPOLOGY_FEATURE_SCHEMA,
};
use memmap2::Mmap;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::mem::{size_of, size_of_val};
use std::path::{Path, PathBuf};
use zerocopy::{AsBytes, FromBytes, FromZeroes, Ref, Unaligned};

const MAGIC: [u8; 8] = *b"PHXTTF01";

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy)]
#[repr(C)]
struct Header {
    magic: [u8; 8],
    version: [u8; 2],
    reserved: [u8; 6],
    total_bytes: [u8; 8],
    link_offset: [u8; 8],
    link_count: [u8; 8],
    incidence_offset: [u8; 8],
    incidence_count: [u8; 8],
}

#[derive(AsBytes, FromBytes, FromZeroes, Unaligned, Clone, Copy)]
#[repr(C)]
pub struct TopologyFeatureRecord {
    positive_index: [u8; 4],
    candidate: [u8; 4],
    features: [[u8; 4]; 16],
    split: u8,
    label: u8,
    reserved: [u8; 6],
}

impl TopologyFeatureRecord {
    pub fn positive_index(self) -> u32 {
        u32::from_le_bytes(self.positive_index)
    }

    pub fn candidate(self) -> u32 {
        u32::from_le_bytes(self.candidate)
    }

    pub fn feature(self, column: usize) -> Option<f32> {
        self.features
            .get(column)
            .copied()
            .map(u32::from_le_bytes)
            .map(f32::from_bits)
    }

    pub fn split(self) -> u8 {
        self.split
    }

    pub fn label(self) -> bool {
        self.label != 0
    }
}

pub struct TrainTopologyFeatureBundle;

impl TrainTopologyFeatureBundle {
    pub fn write(
        snapshot: &TrainTopologyFeatureSnapshot,
        root: impl AsRef<Path>,
    ) -> Result<TrainTopologyFeaturePaths, ResearchEvaluationError> {
        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let binary_name = format!("{}.ttf", snapshot.derivation_id);
        let manifest_name = format!("{}.ttf-manifest.json", snapshot.derivation_id);
        let binary = root.join(&binary_name);
        let manifest = root.join(manifest_name);
        let bytes = encode(snapshot);
        let descriptor = TrainTopologyFeatureManifest {
            schema_version: TRAIN_TOPOLOGY_FEATURE_SCHEMA.into(),
            derivation_id: snapshot.derivation_id.clone(),
            source_dataset_id: snapshot.source_dataset_id.clone(),
            source_tensor_id: snapshot.source_tensor_id.clone(),
            evaluation_protocol_id: snapshot.evaluation_protocol_id.clone(),
            binary_file: binary_name.into(),
            binary_blake3: format!("b3-{}", blake3::hash(&bytes).to_hex()).into(),
            binary_bytes: bytes.len() as u64,
            link_rows: snapshot.link_rows.len() as u64,
            incidence_rows: snapshot.incidence_rows.len() as u64,
            audit: snapshot.audit.clone(),
            feature_certificates: snapshot.feature_certificates.clone(),
        };
        write_immutable(&binary, &bytes)?;
        write_immutable(&manifest, &serde_json::to_vec_pretty(&descriptor)?)?;
        Ok(TrainTopologyFeaturePaths { manifest, binary })
    }
}

pub struct TrainTopologyFeatureMapped {
    manifest: TrainTopologyFeatureManifest,
    map: Mmap,
}

impl TrainTopologyFeatureMapped {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ResearchEvaluationError> {
        let path = path.as_ref();
        let manifest: TrainTopologyFeatureManifest = serde_json::from_slice(&std::fs::read(path)?)?;
        if manifest.schema_version != TRAIN_TOPOLOGY_FEATURE_SCHEMA {
            return Err(ResearchEvaluationError::CorruptTopologyArtifact("schema"));
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
            return Err(ResearchEvaluationError::CorruptTopologyArtifact("digest"));
        }
        let mapped = Self { manifest, map };
        mapped.validate()?;
        Ok(mapped)
    }

    pub fn manifest(&self) -> &TrainTopologyFeatureManifest {
        &self.manifest
    }

    pub fn link_rows(
        &self,
    ) -> Result<Ref<&[u8], [TopologyFeatureRecord]>, ResearchEvaluationError> {
        self.rows(true)
    }

    pub fn incidence_rows(
        &self,
    ) -> Result<Ref<&[u8], [TopologyFeatureRecord]>, ResearchEvaluationError> {
        self.rows(false)
    }

    fn validate(&self) -> Result<(), ResearchEvaluationError> {
        let header = header(&self.map)?;
        if header.magic != MAGIC
            || u16::from_le_bytes(header.version) != TRAIN_TOPOLOGY_BINARY_VERSION
            || u64::from_le_bytes(header.total_bytes) != self.map.len() as u64
            || u64::from_le_bytes(header.link_count) != self.manifest.link_rows
            || u64::from_le_bytes(header.incidence_count) != self.manifest.incidence_rows
        {
            return Err(ResearchEvaluationError::CorruptTopologyArtifact("header"));
        }
        self.link_rows()?;
        self.incidence_rows()?;
        Ok(())
    }

    fn rows(
        &self,
        link: bool,
    ) -> Result<Ref<&[u8], [TopologyFeatureRecord]>, ResearchEvaluationError> {
        let header = header(&self.map)?;
        let (offset, count) = if link {
            (
                u64::from_le_bytes(header.link_offset),
                u64::from_le_bytes(header.link_count),
            )
        } else {
            (
                u64::from_le_bytes(header.incidence_offset),
                u64::from_le_bytes(header.incidence_count),
            )
        };
        let start = usize::try_from(offset)
            .map_err(|_| ResearchEvaluationError::CorruptTopologyArtifact("offset"))?;
        let len = usize::try_from(count)
            .map_err(|_| ResearchEvaluationError::CorruptTopologyArtifact("count"))?
            .checked_mul(size_of::<TopologyFeatureRecord>())
            .ok_or(ResearchEvaluationError::CorruptTopologyArtifact("size"))?;
        let end = start
            .checked_add(len)
            .ok_or(ResearchEvaluationError::CorruptTopologyArtifact("range"))?;
        Ref::new_slice_unaligned(
            self.map
                .get(start..end)
                .ok_or(ResearchEvaluationError::CorruptTopologyArtifact("bounds"))?,
        )
        .ok_or(ResearchEvaluationError::CorruptTopologyArtifact("records"))
    }
}

fn header(bytes: &[u8]) -> Result<Header, ResearchEvaluationError> {
    Ref::<_, Header>::new_unaligned(bytes.get(..size_of::<Header>()).ok_or(
        ResearchEvaluationError::CorruptTopologyArtifact("short header"),
    )?)
    .map(|value| *value)
    .ok_or(ResearchEvaluationError::CorruptTopologyArtifact(
        "header alignment",
    ))
}

fn encode(snapshot: &TrainTopologyFeatureSnapshot) -> Vec<u8> {
    let links = records(&snapshot.link_rows);
    let incidences = records(&snapshot.incidence_rows);
    let link_offset = size_of::<Header>();
    let incidence_offset = link_offset + size_of_val(links.as_slice());
    let total = incidence_offset + size_of_val(incidences.as_slice());
    let header = Header {
        magic: MAGIC,
        version: TRAIN_TOPOLOGY_BINARY_VERSION.to_le_bytes(),
        reserved: [0; 6],
        total_bytes: (total as u64).to_le_bytes(),
        link_offset: (link_offset as u64).to_le_bytes(),
        link_count: (links.len() as u64).to_le_bytes(),
        incidence_offset: (incidence_offset as u64).to_le_bytes(),
        incidence_count: (incidences.len() as u64).to_le_bytes(),
    };
    let mut bytes = Vec::with_capacity(total);
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(links.as_bytes());
    bytes.extend_from_slice(incidences.as_bytes());
    bytes
}

fn records(rows: &[crate::DerivedFeatureRow]) -> Vec<TopologyFeatureRecord> {
    rows.iter()
        .map(|row| TopologyFeatureRecord {
            positive_index: row.positive_index.to_le_bytes(),
            candidate: row.candidate.to_le_bytes(),
            features: row.features.map(|value| value.to_bits().to_le_bytes()),
            split: row.split as u8,
            label: u8::from(row.label),
            reserved: [0; 6],
        })
        .collect()
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), ResearchEvaluationError> {
    if path.exists() {
        return if std::fs::read(path)? == bytes {
            Ok(())
        } else {
            Err(ResearchEvaluationError::ArtifactExists(path.to_path_buf()))
        };
    }
    let temporary = temporary_path(path);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    if let Err(error) = file.write_all(bytes).and_then(|_| file.sync_all()) {
        let _ = std::fs::remove_file(&temporary);
        return Err(error.into());
    }
    std::fs::rename(temporary, path)?;
    Ok(())
}

fn temporary_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("topology");
    path.with_file_name(format!(".{name}.tmp-{}", std::process::id()))
}

use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

pub const EXTERNAL_DATASET_SCHEMA: &str = "phoenix-external-graph-dataset/v1";
pub const EXTERNAL_DATASET_BINARY_VERSION: u16 = 1;
pub const TGB_SMALLPEDIA_URL: &str =
    "https://object-arbutus.cloud.computecanada.ca/tgb/tkgl-smallpedia.zip";
pub const TGB_SMALLPEDIA_VERSION: &str = "tgb-2.2.0/tkgl-smallpedia-v1";
pub const STARE_WD50K_COMMIT: &str = "b294b9e2cde97ab9e81d2736b7f1f0959c9fd98b";
pub const STARE_WD50K_URL: &str = "https://github.com/migalkin/StarE/tree/master/data/clean/wd50k";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[repr(u8)]
pub enum ExternalDatasetKind {
    TemporalKnowledgeGraph = 1,
    HyperRelationalKnowledgeGraph = 2,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[repr(u8)]
pub enum ExternalFactSplit {
    Unsplit = 0,
    Train = 1,
    Validation = 2,
    Test = 3,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
pub enum ExternalSplitPolicy {
    TemporalQuantile {
        train_through: i64,
        validation_through: i64,
        validation_basis_points: u16,
        test_basis_points: u16,
    },
    OfficialFixed {
        train_partition: CompactString,
        validation_partition: CompactString,
        test_partition: CompactString,
    },
}

impl ExternalSplitPolicy {
    pub fn authority_code(&self) -> u8 {
        match self {
            Self::TemporalQuantile { .. } => 1,
            Self::OfficialFixed { .. } => 2,
        }
    }

    pub fn validate(&self) -> Result<(), ExternalDatasetError> {
        match self {
            Self::TemporalQuantile {
                train_through,
                validation_through,
                validation_basis_points,
                test_basis_points,
            } if *train_through > 0
                && validation_through > train_through
                && *validation_basis_points > 0
                && *test_basis_points > 0
                && u32::from(*validation_basis_points) + u32::from(*test_basis_points) < 10_000 =>
            {
                Ok(())
            }
            Self::OfficialFixed {
                train_partition,
                validation_partition,
                test_partition,
            } if !train_partition.is_empty()
                && !validation_partition.is_empty()
                && !test_partition.is_empty() =>
            {
                Ok(())
            }
            _ => Err(ExternalDatasetError::InvalidInput("split policy")),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExternalSourceFile {
    pub logical_name: CompactString,
    pub blake3: CompactString,
    pub bytes: u64,
    pub role: CompactString,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExternalFact {
    pub subject: u32,
    pub predicate: u32,
    pub object: u32,
    pub qualifier_offset: u32,
    pub qualifier_count: u32,
    pub observed_at: Option<i64>,
    pub split: ExternalFactSplit,
    pub is_static: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ExternalQualifier {
    pub predicate: u32,
    pub object: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExternalDatasetSnapshot {
    pub name: CompactString,
    pub kind: ExternalDatasetKind,
    pub upstream_url: CompactString,
    pub upstream_version: CompactString,
    pub license_notice: CompactString,
    pub split_policy: ExternalSplitPolicy,
    pub source_files: Vec<ExternalSourceFile>,
    pub entities: Vec<CompactString>,
    pub relations: Vec<CompactString>,
    pub facts: Vec<ExternalFact>,
    pub qualifiers: Vec<ExternalQualifier>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExternalDatasetManifest {
    pub schema_version: CompactString,
    pub dataset_id: CompactString,
    pub name: CompactString,
    pub kind: ExternalDatasetKind,
    pub upstream_url: CompactString,
    pub upstream_version: CompactString,
    pub license_notice: CompactString,
    pub split_policy: ExternalSplitPolicy,
    pub source_identity: CompactString,
    pub source_files: Vec<ExternalSourceFile>,
    pub binary_file: CompactString,
    pub binary_blake3: CompactString,
    pub binary_bytes: u64,
    pub entities: u64,
    pub relations: u64,
    pub facts: u64,
    pub temporal_facts: u64,
    pub static_facts: u64,
    pub qualifiers: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExternalDatasetPaths {
    pub manifest: PathBuf,
    pub binary: PathBuf,
    pub dataset_id: CompactString,
}

#[derive(Debug, Error)]
pub enum ExternalDatasetError {
    #[error("external dataset input is invalid: {0}")]
    InvalidInput(&'static str),
    #[error("external dataset row {line} is invalid: {reason}")]
    InvalidRow { line: u64, reason: &'static str },
    #[error("external dataset index exceeds u32")]
    IndexOverflow,
    #[error("external dataset artifact already exists: {0}")]
    ArtifactExists(PathBuf),
    #[error("external dataset artifact is corrupt: {0}")]
    CorruptArtifact(&'static str),
    #[error("external dataset I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("external dataset JSON failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("external dataset contains non-UTF8 identifiers")]
    Utf8(#[from] std::str::Utf8Error),
}

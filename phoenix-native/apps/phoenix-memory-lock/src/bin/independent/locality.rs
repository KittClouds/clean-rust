use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use phoenix_lexical_qps::{PairwiseJudgmentV3, RelevanceTier, SearchHit};
use serde::Serialize;
use sha2::{Digest, Sha256};

const CONTRACT: &str = "phoenix.qps.phase8.6-locality-sidecar/v1";

#[derive(Debug, Serialize)]
pub(super) struct LocalityCapture {
    #[serde(skip)]
    enabled: bool,
    pairs: Vec<PairLocality>,
    graded_queries: Vec<GradedQueryLocality>,
}

impl LocalityCapture {
    pub(super) fn new(enabled: bool) -> Self {
        Self {
            enabled,
            pairs: Vec::new(),
            graded_queries: Vec::new(),
        }
    }

    pub(super) fn capture_pair(
        &mut self,
        judgment: &PairwiseJudgmentV3,
        positive: SearchHit,
        negative: SearchHit,
    ) {
        if !self.enabled {
            return;
        }
        self.pairs.push(PairLocality {
            judgment_identity: hex(judgment.identity.as_bytes()),
            query_identity: hex(judgment.query_identity.as_bytes()),
            positive_document_version: hex(judgment.positive_document_version.as_bytes()),
            negative_document_version: hex(judgment.negative_document_version.as_bytes()),
            positive_locality: positive.matched_group_locality,
            negative_locality: negative.matched_group_locality,
            positive_v2_position: judgment.positive_position,
            negative_v2_position: judgment.negative_position,
            positive_v2_score_bits: positive.v2_score.to_bits(),
            negative_v2_score_bits: negative.v2_score.to_bits(),
            positive_tier: positive.relevance_tier,
            negative_tier: negative.relevance_tier,
        });
    }

    pub(super) fn capture_graded(
        &mut self,
        query_identity: String,
        candidates: &[GradedCandidateLocality],
    ) {
        if self.enabled {
            self.graded_queries.push(GradedQueryLocality {
                query_identity,
                candidates: candidates.to_vec(),
            });
        }
    }

    pub(super) fn write(self, path: &Path, ledger_path: &Path, graded_path: &Path) -> Result<()> {
        if !self.enabled {
            return Ok(());
        }
        let artifact = LocalitySidecar {
            contract: CONTRACT,
            schema_version: 1,
            architecture: "diagnostic_only_replace_redundant_slot_8_with_matched_group_locality",
            replaced_canonical_coordinate: 8,
            replaced_canonical_feature: "missing_group_absence",
            experimental_feature: "matched_group_locality",
            canonical_ledger: file_identity(ledger_path)?,
            canonical_graded_suite: file_identity(graded_path)?,
            pairs: self.pairs,
            graded_queries: self.graded_queries,
        };
        write_json_atomic(path, &artifact)
    }
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct GradedCandidateLocality {
    pub(super) document_identity: String,
    pub(super) v2_order: usize,
    pub(super) v2_score_bits: u32,
    pub(super) matched_group_locality: f32,
    pub(super) relevance_tier: RelevanceTier,
}

#[derive(Debug, Serialize)]
struct LocalitySidecar {
    contract: &'static str,
    schema_version: u16,
    architecture: &'static str,
    replaced_canonical_coordinate: usize,
    replaced_canonical_feature: &'static str,
    experimental_feature: &'static str,
    canonical_ledger: FileIdentity,
    canonical_graded_suite: FileIdentity,
    pairs: Vec<PairLocality>,
    graded_queries: Vec<GradedQueryLocality>,
}

#[derive(Debug, Serialize)]
struct PairLocality {
    judgment_identity: String,
    query_identity: String,
    positive_document_version: String,
    negative_document_version: String,
    positive_locality: f32,
    negative_locality: f32,
    positive_v2_position: u16,
    negative_v2_position: u16,
    positive_v2_score_bits: u32,
    negative_v2_score_bits: u32,
    positive_tier: RelevanceTier,
    negative_tier: RelevanceTier,
}

#[derive(Debug, Serialize)]
struct GradedQueryLocality {
    query_identity: String,
    candidates: Vec<GradedCandidateLocality>,
}

#[derive(Debug, Serialize)]
struct FileIdentity {
    path: PathBuf,
    bytes: u64,
    sha256: String,
}

fn file_identity(path: &Path) -> Result<FileIdentity> {
    let bytes = fs::read(path)?;
    Ok(FileIdentity {
        path: path.to_path_buf(),
        bytes: bytes.len() as u64,
        sha256: hex(Sha256::digest(&bytes).into()),
    })
}

fn write_json_atomic<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    if path.exists() {
        bail!("refusing to overwrite {}", path.display());
    }
    let parent = path.parent().context("locality sidecar has no parent")?;
    fs::create_dir_all(parent)?;
    let temporary = path.with_extension("json.tmp");
    if temporary.exists() {
        fs::remove_file(&temporary)?;
    }
    {
        let mut writer = BufWriter::new(
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)?,
        );
        serde_json::to_writer_pretty(&mut writer, value)?;
        writer.write_all(b"\n")?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
    }
    fs::rename(temporary, path)?;
    Ok(())
}

fn hex<const N: usize>(bytes: [u8; N]) -> String {
    bytes.iter().map(|value| format!("{value:02x}")).collect()
}

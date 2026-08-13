use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use phoenix_lexical_qps::{PairwiseJudgmentV3, RelevanceTier, SearchHit};
use serde::Serialize;
use sha2::{Digest, Sha256};

const CONTRACT: &str = "phoenix.qps.phase8.9-group-distribution-sidecar/v1";

#[derive(Debug, Serialize)]
pub(super) struct GroupDistributionCapture {
    #[serde(skip)]
    enabled: bool,
    pairs: Vec<PairGroupDistribution>,
    graded_queries: Vec<GradedQueryGroupDistribution>,
}

impl GroupDistributionCapture {
    pub(super) fn new(enabled: bool) -> Self {
        Self {
            enabled,
            pairs: Vec::new(),
            graded_queries: Vec::new(),
        }
    }

    pub(super) fn capture_pair(
        &mut self,
        dataset: &'static str,
        judgment: &PairwiseJudgmentV3,
        positive: SearchHit,
        negative: SearchHit,
        positive_strengths: &[f32],
        negative_strengths: &[f32],
    ) {
        if !self.enabled {
            return;
        }
        debug_assert_eq!(positive_strengths.len(), negative_strengths.len());
        self.pairs.push(PairGroupDistribution {
            judgment_identity: hex(judgment.identity.as_bytes()),
            query_identity: hex(judgment.query_identity.as_bytes()),
            dataset,
            positive_document_version: hex(judgment.positive_document_version.as_bytes()),
            negative_document_version: hex(judgment.negative_document_version.as_bytes()),
            positive_strengths: positive_strengths.to_vec(),
            negative_strengths: negative_strengths.to_vec(),
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
        dataset: &'static str,
        query_identity: String,
        candidates: Vec<GradedCandidateGroupDistribution>,
    ) {
        if self.enabled {
            self.graded_queries.push(GradedQueryGroupDistribution {
                dataset,
                query_identity,
                candidates,
            });
        }
    }

    pub(super) fn write(self, path: &Path, ledger_path: &Path, graded_path: &Path) -> Result<()> {
        if !self.enabled {
            return Ok(());
        }
        let artifact = GroupDistributionSidecar {
            contract: CONTRACT,
            schema_version: 1,
            architecture: "diagnostic_only_raw_per_query_group_selected_lexical_evidence",
            group_strength: "s_j=(expansion_quality*sum_field_bm25f_impact)/(1+expansion_quality*sum_field_bm25f_impact)",
            unmatched_group_policy: "explicit_zero_excluded_from_matched_tail_statistics",
            candidate_independent_learning: false,
            canonical_schema_changed: false,
            serving_kernel_changed: false,
            canonical_ledger: file_identity(ledger_path)?,
            canonical_graded_suite: file_identity(graded_path)?,
            pairs: self.pairs,
            graded_queries: self.graded_queries,
        };
        write_json_atomic(path, &artifact)
    }
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct GradedCandidateGroupDistribution {
    pub(super) document_identity: String,
    pub(super) v2_order: usize,
    pub(super) v2_score_bits: u32,
    pub(super) relevance_tier: RelevanceTier,
    pub(super) strengths: Vec<f32>,
}

#[derive(Debug, Serialize)]
struct GroupDistributionSidecar {
    contract: &'static str,
    schema_version: u16,
    architecture: &'static str,
    group_strength: &'static str,
    unmatched_group_policy: &'static str,
    candidate_independent_learning: bool,
    canonical_schema_changed: bool,
    serving_kernel_changed: bool,
    canonical_ledger: FileIdentity,
    canonical_graded_suite: FileIdentity,
    pairs: Vec<PairGroupDistribution>,
    graded_queries: Vec<GradedQueryGroupDistribution>,
}

#[derive(Debug, Serialize)]
struct PairGroupDistribution {
    judgment_identity: String,
    query_identity: String,
    dataset: &'static str,
    positive_document_version: String,
    negative_document_version: String,
    positive_strengths: Vec<f32>,
    negative_strengths: Vec<f32>,
    positive_v2_position: u16,
    negative_v2_position: u16,
    positive_v2_score_bits: u32,
    negative_v2_score_bits: u32,
    positive_tier: RelevanceTier,
    negative_tier: RelevanceTier,
}

#[derive(Debug, Serialize)]
struct GradedQueryGroupDistribution {
    dataset: &'static str,
    query_identity: String,
    candidates: Vec<GradedCandidateGroupDistribution>,
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
    let parent = path
        .parent()
        .context("group-distribution sidecar has no parent")?;
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

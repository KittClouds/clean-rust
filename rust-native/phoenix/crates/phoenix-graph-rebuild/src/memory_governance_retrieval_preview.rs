use compact_str::{format_compact, CompactString};
use hashbrown::HashMap;
use serde::{Deserialize, Serialize};

use crate::types::{
    GraphMemoryGovernanceAction, GraphMemoryGovernanceCandidate, GraphMemoryGovernanceTargetKind,
};

pub const MEMORY_GOVERNANCE_RETRIEVAL_PREVIEW_SCHEMA_VERSION: &str =
    "phoenix-memory-governance-retrieval-preview/v1";
pub const MEMORY_GOVERNANCE_RETRIEVAL_WEIGHTING_EXPERIMENT_SCHEMA_VERSION: &str =
    "phoenix-memory-governance-retrieval-weighting-experiment/v1";
pub const MEMORY_GOVERNANCE_COMPRESSION_DOMINANCE_POLICY: &str =
    "memory_governance:compression_dominance_policy";
const COMPRESSION_FREE_CHUNK_FANOUT: usize = 3;
const COMPRESSION_FREE_EVIDENCE_FANOUT: usize = 12;
const COMPRESSION_EVIDENCE_FANOUT_WEIGHT: f32 = 0.25;
const COMPRESSION_PROOF_SCORE_EPSILON: f32 = 0.001;
const PROOF_VIOLATION_SAMPLE_LIMIT: usize = 12;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRetrievalCandidate {
    pub id: CompactString,
    pub target_id: CompactString,
    pub target_kind: GraphMemoryGovernanceTargetKind,
    pub score: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct MemoryGovernanceRetrievalPreviewInput<'a> {
    pub retrieval_candidates: &'a [MemoryGovernanceRetrievalCandidate],
    pub governance_candidates: &'a [GraphMemoryGovernanceCandidate],
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRetrievalWeightPolicy {
    pub id: CompactString,
    pub retain_confidence_boost: f32,
    pub retain_causal_boost: f32,
    pub retain_retrieval_boost: f32,
    pub compress_confidence_boost: f32,
    pub compress_narrative_boost: f32,
    pub compress_max_boost: f32,
    pub compress_score_ceiling: f32,
    pub compress_fanout_dampening: f32,
    pub attenuate_confidence_penalty: f32,
    pub quarantine_multiplier: f32,
    pub retire_multiplier: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRetrievalWeightingExperiment {
    pub schema_version: CompactString,
    pub baseline_policy_id: CompactString,
    pub variants: Vec<MemoryGovernanceRetrievalWeightingVariant>,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRetrievalWeightingVariant {
    pub policy: MemoryGovernanceRetrievalWeightPolicy,
    pub summary: MemoryGovernanceRetrievalPreviewSummary,
    pub full_row_proof: MemoryGovernanceRetrievalFullRowProof,
    pub top_rows: Vec<MemoryGovernanceRetrievalPreviewRow>,
    pub mean_abs_rank_delta_millis: u32,
    pub retained_mean_score_delta_millis: i32,
    pub compressed_mean_score_delta_millis: i32,
    pub attenuated_mean_score_delta_millis: i32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRetrievalFullRowProof {
    pub row_count: usize,
    pub no_topology_rows: usize,
    pub compression_dominance: MemoryGovernanceCompressionDominanceProof,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceCompressionDominanceProof {
    pub passed: bool,
    pub compressed_rows: usize,
    pub policy_rows: usize,
    pub bounded_rows: usize,
    pub max_positive_delta: f32,
    pub max_adjusted_score: f32,
    pub violation_count: usize,
    pub violations: Vec<CompactString>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRetrievalPreview {
    pub schema_version: CompactString,
    pub rows: Vec<MemoryGovernanceRetrievalPreviewRow>,
    pub summary: MemoryGovernanceRetrievalPreviewSummary,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRetrievalPreviewRow {
    pub id: CompactString,
    pub target_id: CompactString,
    pub target_kind: GraphMemoryGovernanceTargetKind,
    pub original_rank: usize,
    pub adjusted_rank: usize,
    pub original_score: f32,
    pub adjusted_score: f32,
    pub score_delta: f32,
    pub governance_candidate_id: Option<CompactString>,
    pub governance_action: Option<GraphMemoryGovernanceAction>,
    pub governance_confidence: Option<f32>,
    pub reason: Option<CompactString>,
    pub rationale: Vec<CompactString>,
    pub no_topology_commit: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryGovernanceRetrievalPreviewSummary {
    pub candidate_count: usize,
    pub governed_count: usize,
    pub retained_count: usize,
    pub attenuated_count: usize,
    pub compressed_count: usize,
    pub unchanged_count: usize,
    pub changed_rank_count: usize,
    pub promoted_count: usize,
    pub demoted_count: usize,
}

pub fn build_memory_governance_retrieval_preview(
    input: MemoryGovernanceRetrievalPreviewInput<'_>,
) -> MemoryGovernanceRetrievalPreview {
    build_memory_governance_retrieval_preview_with_policy(
        input,
        &balanced_retrieval_weight_policy(),
    )
}

pub fn build_memory_governance_retrieval_preview_with_policy(
    input: MemoryGovernanceRetrievalPreviewInput<'_>,
    policy: &MemoryGovernanceRetrievalWeightPolicy,
) -> MemoryGovernanceRetrievalPreview {
    let governance_by_target = input
        .governance_candidates
        .iter()
        .map(|row| ((row.target_kind, row.target_id.as_str()), row))
        .collect::<HashMap<_, _>>();
    let mut rows = Vec::with_capacity(input.retrieval_candidates.len());

    for (index, retrieval) in input.retrieval_candidates.iter().enumerate() {
        let original_rank = index + 1;
        let governance =
            governance_by_target.get(&(retrieval.target_kind, retrieval.target_id.as_str()));
        let adjusted_score = adjusted_score(retrieval.score, governance.copied(), policy);
        let mut rationale = governance
            .map(|row| row.rationale.clone())
            .unwrap_or_default();
        if let Some(row) = governance.copied() {
            append_retrieval_policy_rationale(&mut rationale, row, policy);
        }
        rows.push(MemoryGovernanceRetrievalPreviewRow {
            id: format_compact!("memory_governance_retrieval_preview:{}", retrieval.id),
            target_id: retrieval.target_id.clone(),
            target_kind: retrieval.target_kind,
            original_rank,
            adjusted_rank: original_rank,
            original_score: round_score(retrieval.score),
            adjusted_score,
            score_delta: round_score(adjusted_score - retrieval.score),
            governance_candidate_id: governance.map(|row| row.id.clone()),
            governance_action: governance.map(|row| row.action),
            governance_confidence: governance.map(|row| round_score(row.confidence)),
            reason: governance.map(|row| row.reason.clone()),
            rationale,
            no_topology_commit: true,
        });
    }

    rows.sort_by(|left, right| {
        right
            .adjusted_score
            .total_cmp(&left.adjusted_score)
            .then_with(|| left.original_rank.cmp(&right.original_rank))
            .then_with(|| left.target_id.cmp(&right.target_id))
    });
    for (index, row) in rows.iter_mut().enumerate() {
        row.adjusted_rank = index + 1;
    }
    let summary = summary_for(&rows);
    MemoryGovernanceRetrievalPreview {
        schema_version: MEMORY_GOVERNANCE_RETRIEVAL_PREVIEW_SCHEMA_VERSION.into(),
        rows,
        summary,
        no_topology_commit: true,
    }
}

pub fn build_memory_governance_retrieval_weighting_experiment(
    input: MemoryGovernanceRetrievalPreviewInput<'_>,
) -> MemoryGovernanceRetrievalWeightingExperiment {
    let policies = default_retrieval_weight_experiment_policies();
    let variants = policies
        .iter()
        .map(|policy| {
            let preview = build_memory_governance_retrieval_preview_with_policy(input, policy);
            weighting_variant(policy.clone(), preview)
        })
        .collect();
    MemoryGovernanceRetrievalWeightingExperiment {
        schema_version: MEMORY_GOVERNANCE_RETRIEVAL_WEIGHTING_EXPERIMENT_SCHEMA_VERSION.into(),
        baseline_policy_id: "balanced".into(),
        variants,
        no_topology_commit: true,
    }
}

pub fn default_retrieval_weight_experiment_policies() -> Vec<MemoryGovernanceRetrievalWeightPolicy>
{
    vec![
        conservative_retrieval_weight_policy(),
        balanced_retrieval_weight_policy(),
        episode_anchor_retrieval_weight_policy(),
        decay_heavy_retrieval_weight_policy(),
    ]
}

fn adjusted_score(
    original_score: f32,
    governance: Option<&GraphMemoryGovernanceCandidate>,
    policy: &MemoryGovernanceRetrievalWeightPolicy,
) -> f32 {
    let Some(governance) = governance else {
        return round_score(original_score);
    };
    let score = match governance.action {
        GraphMemoryGovernanceAction::Retain => {
            original_score
                + governance.confidence * policy.retain_confidence_boost
                + governance.signals.causal_importance * policy.retain_causal_boost
                + governance.signals.retrieval_utility * policy.retain_retrieval_boost
        }
        GraphMemoryGovernanceAction::Compress => {
            compression_adjusted_score(original_score, governance, policy)
        }
        GraphMemoryGovernanceAction::Attenuate => {
            original_score * (1.0 - governance.confidence * policy.attenuate_confidence_penalty)
        }
        GraphMemoryGovernanceAction::Quarantine => original_score * policy.quarantine_multiplier,
        GraphMemoryGovernanceAction::Retire => original_score * policy.retire_multiplier,
    };
    round_score(score.clamp(0.0, 1.0))
}

fn compression_adjusted_score(
    original_score: f32,
    governance: &GraphMemoryGovernanceCandidate,
    policy: &MemoryGovernanceRetrievalWeightPolicy,
) -> f32 {
    let raw_boost = governance.confidence * policy.compress_confidence_boost
        + governance.signals.narrative_salience * policy.compress_narrative_boost;
    let boost = (raw_boost * compression_fanout_multiplier(governance, policy))
        .min(policy.compress_max_boost)
        .max(0.0);
    let ceiling = original_score.max(policy.compress_score_ceiling).min(1.0);
    (original_score + boost).min(ceiling)
}

fn compression_fanout_multiplier(
    governance: &GraphMemoryGovernanceCandidate,
    policy: &MemoryGovernanceRetrievalWeightPolicy,
) -> f32 {
    let chunk_fanout = governance
        .related_chunk_ids
        .len()
        .saturating_sub(COMPRESSION_FREE_CHUNK_FANOUT) as f32;
    let evidence_fanout = governance
        .evidence_ids
        .len()
        .saturating_sub(COMPRESSION_FREE_EVIDENCE_FANOUT) as f32;
    let pressure = chunk_fanout + evidence_fanout * COMPRESSION_EVIDENCE_FANOUT_WEIGHT;
    (1.0 / (1.0 + pressure * policy.compress_fanout_dampening)).clamp(0.35, 1.0)
}

fn append_retrieval_policy_rationale(
    out: &mut Vec<CompactString>,
    governance: &GraphMemoryGovernanceCandidate,
    policy: &MemoryGovernanceRetrievalWeightPolicy,
) {
    if governance.action != GraphMemoryGovernanceAction::Compress {
        return;
    }
    out.push(MEMORY_GOVERNANCE_COMPRESSION_DOMINANCE_POLICY.into());
    out.push(format_compact!(
        "compression:max_boost:{:.3}",
        policy.compress_max_boost
    ));
    out.push(format_compact!(
        "compression:score_ceiling:{:.3}",
        policy.compress_score_ceiling
    ));
    out.push(format_compact!(
        "compression:fanout_multiplier:{:.3}",
        compression_fanout_multiplier(governance, policy)
    ));
}

fn summary_for(
    rows: &[MemoryGovernanceRetrievalPreviewRow],
) -> MemoryGovernanceRetrievalPreviewSummary {
    let mut summary = MemoryGovernanceRetrievalPreviewSummary {
        candidate_count: rows.len(),
        ..MemoryGovernanceRetrievalPreviewSummary::default()
    };
    for row in rows {
        if let Some(action) = row.governance_action {
            summary.governed_count += 1;
            match action {
                GraphMemoryGovernanceAction::Retain => summary.retained_count += 1,
                GraphMemoryGovernanceAction::Attenuate => summary.attenuated_count += 1,
                GraphMemoryGovernanceAction::Compress => summary.compressed_count += 1,
                GraphMemoryGovernanceAction::Quarantine | GraphMemoryGovernanceAction::Retire => {}
            }
        } else {
            summary.unchanged_count += 1;
        }
        if row.adjusted_rank != row.original_rank {
            summary.changed_rank_count += 1;
        }
        if row.adjusted_rank < row.original_rank {
            summary.promoted_count += 1;
        } else if row.adjusted_rank > row.original_rank {
            summary.demoted_count += 1;
        }
    }
    summary
}

fn round_score(value: f32) -> f32 {
    (value * 1000.0).round() / 1000.0
}

fn weighting_variant(
    policy: MemoryGovernanceRetrievalWeightPolicy,
    preview: MemoryGovernanceRetrievalPreview,
) -> MemoryGovernanceRetrievalWeightingVariant {
    let full_row_proof = full_row_proof(&preview.rows, &policy);
    MemoryGovernanceRetrievalWeightingVariant {
        policy,
        full_row_proof,
        mean_abs_rank_delta_millis: mean_abs_rank_delta_millis(&preview.rows),
        retained_mean_score_delta_millis: mean_score_delta_millis(
            &preview.rows,
            GraphMemoryGovernanceAction::Retain,
        ),
        compressed_mean_score_delta_millis: mean_score_delta_millis(
            &preview.rows,
            GraphMemoryGovernanceAction::Compress,
        ),
        attenuated_mean_score_delta_millis: mean_score_delta_millis(
            &preview.rows,
            GraphMemoryGovernanceAction::Attenuate,
        ),
        top_rows: preview.rows.into_iter().take(8).collect(),
        summary: preview.summary,
    }
}

fn full_row_proof(
    rows: &[MemoryGovernanceRetrievalPreviewRow],
    policy: &MemoryGovernanceRetrievalWeightPolicy,
) -> MemoryGovernanceRetrievalFullRowProof {
    MemoryGovernanceRetrievalFullRowProof {
        row_count: rows.len(),
        no_topology_rows: rows.iter().filter(|row| row.no_topology_commit).count(),
        compression_dominance: compression_dominance_proof(rows, policy),
    }
}

fn compression_dominance_proof(
    rows: &[MemoryGovernanceRetrievalPreviewRow],
    policy: &MemoryGovernanceRetrievalWeightPolicy,
) -> MemoryGovernanceCompressionDominanceProof {
    let mut proof = MemoryGovernanceCompressionDominanceProof {
        passed: true,
        compressed_rows: 0,
        policy_rows: 0,
        bounded_rows: 0,
        max_positive_delta: 0.0,
        max_adjusted_score: 0.0,
        violation_count: 0,
        violations: Vec::new(),
    };
    for row in rows
        .iter()
        .filter(|row| row.governance_action == Some(GraphMemoryGovernanceAction::Compress))
    {
        proof.compressed_rows += 1;
        proof.max_positive_delta = proof.max_positive_delta.max(row.score_delta.max(0.0));
        proof.max_adjusted_score = proof.max_adjusted_score.max(row.adjusted_score);
        if row
            .rationale
            .iter()
            .any(|line| line == MEMORY_GOVERNANCE_COMPRESSION_DOMINANCE_POLICY)
        {
            proof.policy_rows += 1;
        } else {
            push_proof_violation(
                &mut proof,
                format_compact!("{}:missing_compression_policy", row.id),
            );
        }
        let ceiling = row.original_score.max(policy.compress_score_ceiling);
        let bounded_by_delta =
            row.score_delta <= policy.compress_max_boost + COMPRESSION_PROOF_SCORE_EPSILON;
        let bounded_by_ceiling = row.adjusted_score <= ceiling + COMPRESSION_PROOF_SCORE_EPSILON;
        if bounded_by_delta && bounded_by_ceiling {
            proof.bounded_rows += 1;
        }
        if !bounded_by_delta {
            push_proof_violation(
                &mut proof,
                format_compact!("{}:compress_boost_exceeds_cap", row.id),
            );
        }
        if !bounded_by_ceiling {
            push_proof_violation(
                &mut proof,
                format_compact!("{}:compress_score_exceeds_ceiling", row.id),
            );
        }
    }
    proof.max_positive_delta = round_score(proof.max_positive_delta);
    proof.max_adjusted_score = round_score(proof.max_adjusted_score);
    proof.passed = proof.violation_count == 0;
    proof
}

fn push_proof_violation(
    proof: &mut MemoryGovernanceCompressionDominanceProof,
    violation: CompactString,
) {
    proof.violation_count += 1;
    if proof.violations.len() < PROOF_VIOLATION_SAMPLE_LIMIT {
        proof.violations.push(violation);
    }
}

fn mean_abs_rank_delta_millis(rows: &[MemoryGovernanceRetrievalPreviewRow]) -> u32 {
    if rows.is_empty() {
        return 0;
    }
    let total = rows
        .iter()
        .map(|row| row.adjusted_rank.abs_diff(row.original_rank) as u32)
        .sum::<u32>();
    total * 1000 / rows.len() as u32
}

fn mean_score_delta_millis(
    rows: &[MemoryGovernanceRetrievalPreviewRow],
    action: GraphMemoryGovernanceAction,
) -> i32 {
    let mut count = 0_i32;
    let mut total = 0_i32;
    for row in rows
        .iter()
        .filter(|row| row.governance_action == Some(action))
    {
        count += 1;
        total += (row.score_delta * 1000.0).round() as i32;
    }
    if count == 0 {
        0
    } else {
        total / count
    }
}

fn conservative_retrieval_weight_policy() -> MemoryGovernanceRetrievalWeightPolicy {
    MemoryGovernanceRetrievalWeightPolicy {
        id: "conservative".into(),
        retain_confidence_boost: 0.04,
        retain_causal_boost: 0.015,
        retain_retrieval_boost: 0.01,
        compress_confidence_boost: 0.07,
        compress_narrative_boost: 0.015,
        compress_max_boost: 0.035,
        compress_score_ceiling: 0.92,
        compress_fanout_dampening: 0.20,
        attenuate_confidence_penalty: 0.18,
        quarantine_multiplier: 0.50,
        retire_multiplier: 0.10,
    }
}

fn balanced_retrieval_weight_policy() -> MemoryGovernanceRetrievalWeightPolicy {
    MemoryGovernanceRetrievalWeightPolicy {
        id: "balanced".into(),
        retain_confidence_boost: 0.08,
        retain_causal_boost: 0.03,
        retain_retrieval_boost: 0.02,
        compress_confidence_boost: 0.14,
        compress_narrative_boost: 0.03,
        compress_max_boost: 0.045,
        compress_score_ceiling: 0.94,
        compress_fanout_dampening: 0.18,
        attenuate_confidence_penalty: 0.36,
        quarantine_multiplier: 0.35,
        retire_multiplier: 0.05,
    }
}

fn episode_anchor_retrieval_weight_policy() -> MemoryGovernanceRetrievalWeightPolicy {
    MemoryGovernanceRetrievalWeightPolicy {
        id: "episode_anchor".into(),
        retain_confidence_boost: 0.06,
        retain_causal_boost: 0.02,
        retain_retrieval_boost: 0.015,
        compress_confidence_boost: 0.22,
        compress_narrative_boost: 0.05,
        compress_max_boost: 0.065,
        compress_score_ceiling: 0.96,
        compress_fanout_dampening: 0.16,
        attenuate_confidence_penalty: 0.30,
        quarantine_multiplier: 0.35,
        retire_multiplier: 0.05,
    }
}

fn decay_heavy_retrieval_weight_policy() -> MemoryGovernanceRetrievalWeightPolicy {
    MemoryGovernanceRetrievalWeightPolicy {
        id: "decay_heavy".into(),
        retain_confidence_boost: 0.07,
        retain_causal_boost: 0.025,
        retain_retrieval_boost: 0.015,
        compress_confidence_boost: 0.12,
        compress_narrative_boost: 0.025,
        compress_max_boost: 0.040,
        compress_score_ceiling: 0.93,
        compress_fanout_dampening: 0.22,
        attenuate_confidence_penalty: 0.58,
        quarantine_multiplier: 0.25,
        retire_multiplier: 0.02,
    }
}

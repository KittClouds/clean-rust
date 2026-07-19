use std::collections::BTreeMap;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use hashbrown::HashSet;
use memmap2::MmapOptions;
use phoenix_graph_kernel::GraphTruthCommit;
use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    GraphDecisionRewardDimension, NativeDecisionOutcomeReceipt, NativeDecisionReceipt,
    NativeDecisionRewardEvidenceReceipt, NativeDecisionRewardObservationOperation,
    NativeDecisionRewardObservationReceipt,
};
use serde::{Deserialize, Serialize};

const SCHEMA: &str = "phoenix-stability-mature-training-cohort/v1";
const COHORT: &str = "b3-41b1287722cae9438c412f5a818f446c0386bbb44c7b48870a1e2806a4ea2a14";
const AUTHORITY: &str = "deterministic_reconstruction_not_original_recovery";
const EXPECTED_DECISIONS: usize = 760;
const EXPECTED_CANDIDATES: usize = 2_718;

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct Certificate {
    schema_version: String,
    arm_id: String,
    cohort_blake3: String,
    receipt_count: usize,
    candidate_count: usize,
    outcome_receipt_count: usize,
    first_observed_at: i64,
    last_observed_at: i64,
    cohort_window_ms: i64,
    source_lineage_count: usize,
    feature_authority: String,
    evaluation_split: String,
    promotion_eligible: bool,
    promotion_locks: Vec<String>,
    #[serde(flatten)]
    remainder: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReconstructionBundle {
    schema_version: String,
    authority_class: String,
    cohort_blake3: String,
    source_manifest_id: String,
    source_snapshot_id: String,
    source_continuity_snapshot_id: String,
    reconstruction_receipt_id: String,
    commits_blake3: String,
    bundle_blake3: String,
    commits: Vec<GraphTruthCommit>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ArtifactHashes {
    decisions_blake3: String,
    outcomes_blake3: String,
    reward_evidence_blake3: String,
    reward_observations_blake3: String,
    graph_truth_commits_blake3: String,
    certificate_blake3: String,
    reconstruction_bundle_blake3: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SourceWindow {
    first_observed_at: i64,
    last_observed_at: i64,
    duration_ms: i64,
    source_lineage_count: usize,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Census {
    decisions: usize,
    candidates: usize,
    outcomes: usize,
    graph_truth_commits: usize,
    human_acceptance_evidence: usize,
    future_stability_evidence: usize,
    human_acceptance_observations: usize,
    future_stability_observations: usize,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LeakageAuthority {
    supported_checks: Vec<&'static str>,
    unavailable_witnesses: Vec<&'static str>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct FreezePayload {
    schema_version: &'static str,
    cohort_blake3: &'static str,
    authority_class: &'static str,
    frozen_at: i64,
    training_contract: &'static str,
    train_only: bool,
    partitions: Vec<String>,
    fgdt_emitted: bool,
    reward_complete: bool,
    observed_reward_dimensions: Vec<&'static str>,
    pending_reward_dimensions: Vec<&'static str>,
    promotion_locked: bool,
    promotion_locks: Vec<String>,
    source_window: SourceWindow,
    census: Census,
    leakage_authority: LeakageAuthority,
    source_manifest_id: String,
    source_snapshot_id: String,
    source_continuity_snapshot_id: String,
    reconstruction_receipt_id: String,
    reconstruction_bundle_blake3: String,
    artifact_hashes: ArtifactHashes,
    certificate: Certificate,
    decisions: Vec<NativeDecisionReceipt>,
    outcomes: Vec<NativeDecisionOutcomeReceipt>,
    reward_evidence: Vec<NativeDecisionRewardEvidenceReceipt>,
    reward_observations: Vec<NativeDecisionRewardObservationReceipt>,
    graph_truth_commits: Vec<GraphTruthCommit>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct FreezeArtifact {
    artifact_id: String,
    payload_blake3: String,
    payload: FreezePayload,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct FreezeReport {
    schema_version: &'static str,
    artifact_id: String,
    artifact_path: PathBuf,
    artifact_file_blake3: String,
    cohort_blake3: &'static str,
    decisions: usize,
    candidates: usize,
    outcomes: usize,
    reward_evidence: usize,
    reward_observations: usize,
    graph_truth_commits: usize,
    train_only: bool,
    promotion_locked: bool,
    unavailable_leakage_witnesses: usize,
}

fn main() -> Result<(), String> {
    let mut args = env::args_os().skip(1);
    let store_path = path_arg(&mut args)?;
    let certificate_path = path_arg(&mut args)?;
    let reconstruction_path = path_arg(&mut args)?;
    let output_root = path_arg(&mut args)?;
    if args.next().is_some() {
        return Err(usage());
    }

    let certificate: Certificate = read_mmap_json(&certificate_path)?;
    let reconstruction: ReconstructionBundle = read_mmap_json(&reconstruction_path)?;
    require_source_contract(&certificate, &reconstruction)?;
    let certificate_blake3 = content_id(&certificate)?;

    let store = PhoenixOvergraphStore::open(&store_path).map_err(stringify)?;
    let mut decisions = store.load_native_decision_receipts().map_err(stringify)?;
    decisions.sort_unstable_by(|left, right| {
        (left.observed_at, left.receipt_id.as_str())
            .cmp(&(right.observed_at, right.receipt_id.as_str()))
    });
    let mut outcomes = Vec::with_capacity(EXPECTED_DECISIONS);
    let mut evidence = Vec::with_capacity(EXPECTED_DECISIONS * 2);
    let mut observations = Vec::with_capacity(EXPECTED_DECISIONS * 2);
    for decision in &decisions {
        let mut rows = store
            .load_native_decision_outcome_receipts(&decision.receipt_id)
            .map_err(stringify)?;
        rows.sort_unstable_by(|left, right| {
            (left.observed_at, left.receipt_id.as_str())
                .cmp(&(right.observed_at, right.receipt_id.as_str()))
        });
        outcomes.extend(rows);
        let mut rows = store
            .load_native_decision_reward_evidence_for_decision(&decision.receipt_id)
            .map_err(stringify)?;
        rows.sort_unstable_by(|left, right| {
            (
                dimension_ordinal(left.dimension),
                left.observed_at,
                left.receipt_id.as_str(),
            )
                .cmp(&(
                    dimension_ordinal(right.dimension),
                    right.observed_at,
                    right.receipt_id.as_str(),
                ))
        });
        evidence.extend(rows);
        let mut rows = store
            .load_native_decision_reward_observations(&decision.receipt_id)
            .map_err(stringify)?;
        rows.sort_unstable_by(|left, right| {
            (
                dimension_ordinal(left.dimension),
                left.observed_at,
                left.receipt_id.as_str(),
            )
                .cmp(&(
                    dimension_ordinal(right.dimension),
                    right.observed_at,
                    right.receipt_id.as_str(),
                ))
        });
        observations.extend(rows);
    }
    let commits = store.load_graph_truth_commits().map_err(stringify)?;
    store.close_fast().map_err(stringify)?;

    let census = validate_authorities(
        &certificate,
        &reconstruction,
        &decisions,
        &outcomes,
        &evidence,
        &observations,
        &commits,
    )?;
    let frozen_at = observations
        .iter()
        .filter(|row| row.dimension == GraphDecisionRewardDimension::FutureStability)
        .map(|row| row.observed_at)
        .max()
        .ok_or("FutureStability observation timestamp is unavailable")?;
    let source_window = SourceWindow {
        first_observed_at: certificate.first_observed_at,
        last_observed_at: certificate.last_observed_at,
        duration_ms: certificate.cohort_window_ms,
        source_lineage_count: certificate.source_lineage_count,
    };
    let leakage_authority = LeakageAuthority {
        supported_checks: vec![
            "exact-decision-receipt-identity-uniqueness",
            "exact-outcome-receipt-identity-uniqueness",
            "one-authoritative-outcome-per-decision",
            "exact-decision-to-graph-truth-lineage",
            "one-human-acceptance-authority-per-decision",
            "one-future-stability-authority-per-decision",
            "future-stability-observed-after-full-authoritative-horizon",
            "single-source-lineage-and-exact-source-window",
        ],
        unavailable_witnesses: vec![
            "train-validation-receipt-overlap-witness-unavailable-no-validation-partition",
            "train-test-receipt-overlap-witness-unavailable-no-test-partition",
            "cross-split-lineage-overlap-witness-unavailable-no-splits",
            "chronological-split-order-witness-unavailable-single-source-window",
            "validation-24h-embargo-witness-unavailable-no-validation-partition",
            "test-24h-embargo-witness-unavailable-no-test-partition",
            "validation-label-lookahead-witness-unavailable-no-validation-partition",
            "test-label-lookahead-witness-unavailable-no-test-partition",
        ],
    };
    let artifact_hashes = ArtifactHashes {
        decisions_blake3: content_id(&decisions)?,
        outcomes_blake3: content_id(&outcomes)?,
        reward_evidence_blake3: content_id(&evidence)?,
        reward_observations_blake3: content_id(&observations)?,
        graph_truth_commits_blake3: content_id(&commits)?,
        certificate_blake3,
        reconstruction_bundle_blake3: reconstruction.bundle_blake3.clone(),
    };
    let payload = FreezePayload {
        schema_version: SCHEMA,
        cohort_blake3: COHORT,
        authority_class: AUTHORITY,
        frozen_at,
        training_contract: "immutable-content-addressed-stability-mature-train-only/v1",
        train_only: true,
        partitions: Vec::new(),
        fgdt_emitted: false,
        reward_complete: false,
        observed_reward_dimensions: vec!["human_acceptance", "future_stability"],
        pending_reward_dimensions: vec![
            "evidence_support",
            "temporal_consistency",
            "canonical_identity_preservation",
            "contradiction_reduction",
            "minimal_edit_cost",
            "abstention_correctness",
        ],
        promotion_locked: true,
        promotion_locks: promotion_locks(&certificate),
        source_window,
        census,
        leakage_authority,
        source_manifest_id: reconstruction.source_manifest_id.clone(),
        source_snapshot_id: reconstruction.source_snapshot_id.clone(),
        source_continuity_snapshot_id: reconstruction.source_continuity_snapshot_id.clone(),
        reconstruction_receipt_id: reconstruction.reconstruction_receipt_id.clone(),
        reconstruction_bundle_blake3: reconstruction.bundle_blake3.clone(),
        artifact_hashes,
        certificate,
        decisions,
        outcomes,
        reward_evidence: evidence,
        reward_observations: observations,
        graph_truth_commits: commits,
    };
    let payload_blake3 = content_id(&payload)?;
    let artifact_id = payload_blake3.clone();
    let artifact = FreezeArtifact {
        artifact_id: artifact_id.clone(),
        payload_blake3,
        payload,
    };
    let directory = output_root.join(&artifact_id);
    fs::create_dir_all(&directory).map_err(stringify)?;
    let artifact_path = directory.join("stability-mature-train-only.json");
    write_immutable_json(&artifact_path, &artifact)?;
    let artifact_file_blake3 = file_blake3(&artifact_path)?;
    let report = FreezeReport {
        schema_version: SCHEMA,
        artifact_id,
        artifact_path,
        artifact_file_blake3,
        cohort_blake3: COHORT,
        decisions: artifact.payload.census.decisions,
        candidates: artifact.payload.census.candidates,
        outcomes: artifact.payload.census.outcomes,
        reward_evidence: artifact.payload.reward_evidence.len(),
        reward_observations: artifact.payload.reward_observations.len(),
        graph_truth_commits: artifact.payload.graph_truth_commits.len(),
        train_only: artifact.payload.train_only,
        promotion_locked: artifact.payload.promotion_locked,
        unavailable_leakage_witnesses: artifact
            .payload
            .leakage_authority
            .unavailable_witnesses
            .len(),
    };
    println!(
        "{}",
        serde_json::to_string_pretty(&report).map_err(stringify)?
    );
    Ok(())
}

fn validate_authorities(
    certificate: &Certificate,
    reconstruction: &ReconstructionBundle,
    decisions: &[NativeDecisionReceipt],
    outcomes: &[NativeDecisionOutcomeReceipt],
    evidence: &[NativeDecisionRewardEvidenceReceipt],
    observations: &[NativeDecisionRewardObservationReceipt],
    commits: &[GraphTruthCommit],
) -> Result<Census, String> {
    let candidates = decisions
        .iter()
        .map(|row| row.candidates.len())
        .sum::<usize>();
    if decisions.len() != EXPECTED_DECISIONS
        || candidates != EXPECTED_CANDIDATES
        || outcomes.len() != EXPECTED_DECISIONS
        || commits.len() != EXPECTED_DECISIONS
        || commits != reconstruction.commits
    {
        return Err("exact cohort/store/reconstruction census mismatch".to_owned());
    }
    require_unique(
        decisions.iter().map(|row| row.receipt_id.as_str()),
        "decision receipt",
    )?;
    require_unique(
        decisions.iter().map(|row| row.decision_id.as_str()),
        "decision",
    )?;
    require_unique(
        outcomes.iter().map(|row| row.receipt_id.as_str()),
        "outcome receipt",
    )?;
    require_unique(
        evidence.iter().map(|row| row.receipt_id.as_str()),
        "reward evidence",
    )?;
    require_unique(
        observations.iter().map(|row| row.receipt_id.as_str()),
        "reward observation",
    )?;

    let mut human_evidence = 0;
    let mut stability_evidence = 0;
    let mut human_observations = 0;
    let mut stability_observations = 0;
    for (index, decision) in decisions.iter().enumerate() {
        let decision_outcomes = outcomes
            .iter()
            .filter(|row| row.decision_receipt_id == decision.receipt_id)
            .collect::<Vec<_>>();
        if decision_outcomes.len() != 1 || decision_outcomes[0].decision_id != decision.decision_id
        {
            return Err(format!(
                "decision {} lacks exactly one outcome",
                decision.receipt_id
            ));
        }
        let commit = &commits[index];
        if commit.header.generation != index as u64 + 1
            || !commit.header.receipt_ids.contains(&decision.receipt_id)
        {
            return Err(format!(
                "decision {} GraphTruth lineage mismatch",
                decision.receipt_id
            ));
        }
        for dimension in [
            GraphDecisionRewardDimension::HumanAcceptance,
            GraphDecisionRewardDimension::FutureStability,
        ] {
            let rows = evidence
                .iter()
                .filter(|row| {
                    row.decision_receipt_id == decision.receipt_id && row.dimension == dimension
                })
                .collect::<Vec<_>>();
            if rows.len() != 1 || rows[0].graph_truth_commit_id != commit.header.commit_id {
                return Err(format!(
                    "decision {} reward evidence lineage mismatch",
                    decision.receipt_id
                ));
            }
            let observed = observations
                .iter()
                .filter(|row| {
                    row.decision_receipt_id == decision.receipt_id && row.dimension == dimension
                })
                .collect::<Vec<_>>();
            if observed.len() != 1
                || observed[0].graph_truth_commit_id != commit.header.commit_id
                || observed[0].operation != NativeDecisionRewardObservationOperation::Observe
                || observed[0].score_micros.is_none()
            {
                return Err(format!(
                    "decision {} reward observation lineage mismatch",
                    decision.receipt_id
                ));
            }
            match dimension {
                GraphDecisionRewardDimension::HumanAcceptance => {
                    human_evidence += 1;
                    human_observations += 1;
                }
                GraphDecisionRewardDimension::FutureStability => {
                    if rows[0].observed_at < rows[0].stability_eligible_at {
                        return Err(format!(
                            "decision {} stability evidence is premature",
                            decision.receipt_id
                        ));
                    }
                    stability_evidence += 1;
                    stability_observations += 1;
                }
                _ => unreachable!(),
            }
        }
    }
    if decisions.first().map(|row| row.observed_at) != Some(certificate.first_observed_at)
        || decisions.last().map(|row| row.observed_at) != Some(certificate.last_observed_at)
        || certificate.last_observed_at - certificate.first_observed_at
            != certificate.cohort_window_ms
    {
        return Err("certificate source window does not match exact receipts".to_owned());
    }
    Ok(Census {
        decisions: decisions.len(),
        candidates,
        outcomes: outcomes.len(),
        graph_truth_commits: commits.len(),
        human_acceptance_evidence: human_evidence,
        future_stability_evidence: stability_evidence,
        human_acceptance_observations: human_observations,
        future_stability_observations: stability_observations,
    })
}

fn require_source_contract(
    certificate: &Certificate,
    reconstruction: &ReconstructionBundle,
) -> Result<(), String> {
    if certificate.cohort_blake3 != COHORT
        || certificate.receipt_count != EXPECTED_DECISIONS
        || certificate.candidate_count != EXPECTED_CANDIDATES
        || certificate.outcome_receipt_count != EXPECTED_DECISIONS
        || certificate.source_lineage_count != 1
        || certificate.promotion_eligible
        || reconstruction.schema_version != "phoenix-reconstructed-graph-truth-bundle/v1"
        || reconstruction.authority_class != AUTHORITY
        || reconstruction.cohort_blake3 != COHORT
        || reconstruction.commits.len() != EXPECTED_DECISIONS
        || content_id(&reconstruction.commits)? != reconstruction.commits_blake3
    {
        return Err("certificate/reconstruction authority contract mismatch".to_owned());
    }
    Ok(())
}

fn promotion_locks(certificate: &Certificate) -> Vec<String> {
    let mut locks = certificate
        .promotion_locks
        .iter()
        .filter(|lock| lock.as_str() != "zero-mature-trajectories")
        .cloned()
        .collect::<Vec<_>>();
    for lock in [
        "deterministic-graph-truth-reconstruction-is-not-original-authority-recovery",
        "train-only-cohort-has-no-validation-or-test-partition",
        "six-reward-dimensions-remain-pending",
        "supported-leakage-checks-do-not-supply-unavailable-split-witnesses",
    ] {
        if !locks.iter().any(|value| value == lock) {
            locks.push(lock.to_owned());
        }
    }
    locks
}

fn require_unique<'a>(values: impl Iterator<Item = &'a str>, label: &str) -> Result<(), String> {
    let mut seen = HashSet::new();
    for value in values {
        if !seen.insert(value) {
            return Err(format!("duplicate {label}: {value}"));
        }
    }
    Ok(())
}

fn dimension_ordinal(dimension: GraphDecisionRewardDimension) -> u8 {
    match dimension {
        GraphDecisionRewardDimension::EvidenceSupport => 0,
        GraphDecisionRewardDimension::TemporalConsistency => 1,
        GraphDecisionRewardDimension::CanonicalIdentityPreservation => 2,
        GraphDecisionRewardDimension::ContradictionReduction => 3,
        GraphDecisionRewardDimension::MinimalEditCost => 4,
        GraphDecisionRewardDimension::HumanAcceptance => 5,
        GraphDecisionRewardDimension::FutureStability => 6,
        GraphDecisionRewardDimension::AbstentionCorrectness => 7,
    }
}

fn read_mmap_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, String> {
    let file = File::open(path).map_err(stringify)?;
    let mapped = unsafe { MmapOptions::new().map(&file) }.map_err(stringify)?;
    serde_json::from_slice(&mapped).map_err(stringify)
}

fn write_immutable_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(value).map_err(stringify)?;
    match OpenOptions::new().write(true).create_new(true).open(path) {
        Ok(mut file) => {
            file.write_all(&bytes).map_err(stringify)?;
            file.sync_all().map_err(stringify)
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let existing = fs::read(path).map_err(stringify)?;
            if existing == bytes {
                Ok(())
            } else {
                Err(format!("immutable artifact differs: {}", path.display()))
            }
        }
        Err(error) => Err(error.to_string()),
    }
}

fn content_id<T: Serialize>(value: &T) -> Result<String, String> {
    let bytes = serde_json::to_vec(value).map_err(stringify)?;
    Ok(format!("b3-{}", blake3::hash(&bytes).to_hex()))
}

fn file_blake3(path: &Path) -> Result<String, String> {
    let file = File::open(path).map_err(stringify)?;
    let mapped = unsafe { MmapOptions::new().map(&file) }.map_err(stringify)?;
    Ok(format!("b3-{}", blake3::hash(&mapped).to_hex()))
}

fn path_arg(args: &mut impl Iterator<Item = std::ffi::OsString>) -> Result<PathBuf, String> {
    args.next().map(PathBuf::from).ok_or_else(usage)
}

fn usage() -> String {
    "usage: canonical-stability-mature-freeze <store> <certificate> <reconstruction-bundle> <output-root>".to_owned()
}

fn stringify(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn content_identity_is_stable() {
        assert_eq!(
            content_id(&(1_u8, "authority")).unwrap(),
            content_id(&(1_u8, "authority")).unwrap()
        );
    }

    #[test]
    fn pending_dimensions_are_exactly_the_unobserved_six() {
        let observed = [
            GraphDecisionRewardDimension::HumanAcceptance,
            GraphDecisionRewardDimension::FutureStability,
        ];
        assert_eq!(
            GraphDecisionRewardDimension::ALL
                .iter()
                .filter(|row| !observed.contains(row))
                .count(),
            6
        );
    }
}

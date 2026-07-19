use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Cursor, Write};
use std::path::{Path, PathBuf};

use hashbrown::{HashMap, HashSet};
use memmap2::MmapOptions;
use phoenix_graph_kernel::{
    GraphTruthCommit, GraphTruthLineage, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
};
use phoenix_graph_rebuild::StoryContinuityContract;
use phoenix_store_native_core::{
    GraphTruthCommitAppend, PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    GraphDecisionAction, GraphDecisionRewardDimension, GraphTruthCommitHeader,
    GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest, GraphTruthKind,
    GraphTruthOperation, GraphTruthSourceGenerationRef, NativeDecisionReceipt,
    NativeDecisionRewardEvidenceReceipt, NativeDecisionTaskFamily,
    CANONICAL_HUMAN_EVALUATION_POLICY,
};
use serde::{Deserialize, Serialize};

#[path = "canonical_graph_truth_reconstruction_support.rs"]
mod reconstruction_support;

use reconstruction_support::{episode_event_edge, episode_vertex, event_vertex};

const TOOL_SCHEMA: &str = "phoenix-canonical-graph-truth-reconstruction/v1";
const BUNDLE_SCHEMA: &str = "phoenix-reconstructed-graph-truth-bundle/v1";
const REPORT_SCHEMA: &str = "phoenix-reconstructed-graph-truth-report/v1";
const EPISODE_ASSIGNMENT_POLICY: &str = "canonical-episode-assignment/operator-accept/v1";

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CohortCertificate {
    cohort_blake3: String,
    receipt_count: u64,
    candidate_count: u64,
    outcome_receipt_count: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DurableSectionRef {
    identity: String,
    encoding: String,
    raw_bytes: u64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DurableGraphRunManifest {
    schema_version: String,
    manifest_id: String,
    snapshot_id: String,
    sections: BTreeMap<String, DurableSectionRef>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ContinuityEnvelope {
    contract: StoryContinuityContract,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReconstructionBundle {
    schema_version: String,
    tool_schema: String,
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
struct ReconstructionReport {
    schema_version: &'static str,
    mode: &'static str,
    store_path: String,
    cohort_blake3: String,
    source_snapshot_id: String,
    bundle_path: Option<String>,
    bundle_blake3: String,
    commits_blake3: String,
    decisions: usize,
    candidates: usize,
    outcomes: usize,
    human_acceptance: usize,
    commits: usize,
    appended: usize,
    already_present: usize,
    kernel_generation: u64,
    exact_expected_commit_ids: bool,
    exact_decision_receipt_membership: bool,
    explicit_reconstruction_provenance: bool,
}

struct ReconstructionRow {
    decision: NativeDecisionReceipt,
    human: NativeDecisionRewardEvidenceReceipt,
}

fn main() -> Result<(), String> {
    let mut arguments = env::args_os().skip(1);
    let mode = arguments
        .next()
        .ok_or_else(usage)?
        .to_string_lossy()
        .into_owned();
    match mode.as_str() {
        "preview" => {
            let store_path = path_arg(&mut arguments)?;
            let graph_run_root = path_arg(&mut arguments)?;
            let manifest_path = path_arg(&mut arguments)?;
            let certificate_path = path_arg(&mut arguments)?;
            let output_root = path_arg(&mut arguments)?;
            require_end(arguments)?;
            preview(
                &store_path,
                &graph_run_root,
                &manifest_path,
                &certificate_path,
                &output_root,
            )
        }
        "apply" | "verify" => {
            let store_path = path_arg(&mut arguments)?;
            let bundle_path = path_arg(&mut arguments)?;
            require_end(arguments)?;
            apply_or_verify(&store_path, &bundle_path, mode == "apply")
        }
        _ => Err(usage()),
    }
}

fn preview(
    store_path: &Path,
    graph_run_root: &Path,
    manifest_path: &Path,
    certificate_path: &Path,
    output_root: &Path,
) -> Result<(), String> {
    let certificate: CohortCertificate = read_json(certificate_path)?;
    require_certificate(&certificate)?;
    let manifest: DurableGraphRunManifest = read_json(manifest_path)?;
    if manifest.schema_version != "phoenix-graph-run-store/v1" {
        return Err("durable graph-run manifest schema mismatch".to_owned());
    }
    let continuity = load_continuity(graph_run_root, &manifest)?;
    if snapshot_scope_prefix(continuity.source_snapshot_id.as_str())
        != snapshot_scope_prefix(&manifest.snapshot_id)
        || !continuity.no_topology_commit
        || !continuity.certificate.no_topology_writes
        || !continuity.certificate.stable_source_identities
    {
        return Err("reused continuity section authority contract mismatch".to_owned());
    }

    let store = PhoenixOvergraphStore::open(store_path).map_err(stringify)?;
    let rows = authoritative_rows(&store, &manifest.snapshot_id, &certificate)?;
    let reconstruction_receipt_id = content_id(&(
        TOOL_SCHEMA,
        certificate.cohort_blake3.as_str(),
        manifest.manifest_id.as_str(),
        manifest.snapshot_id.as_str(),
        continuity.source_snapshot_id.as_str(),
    ))?;
    let commits = reconstruct_commits(
        &rows,
        &continuity,
        &manifest.snapshot_id,
        &reconstruction_receipt_id,
    )?;
    store.close_fast().map_err(stringify)?;

    let commits_blake3 = content_id(&commits)?;
    let bundle_blake3 = content_id(&(
        BUNDLE_SCHEMA,
        certificate.cohort_blake3.as_str(),
        manifest.manifest_id.as_str(),
        manifest.snapshot_id.as_str(),
        continuity.source_snapshot_id.as_str(),
        reconstruction_receipt_id.as_str(),
        commits_blake3.as_str(),
    ))?;
    let bundle = ReconstructionBundle {
        schema_version: BUNDLE_SCHEMA.to_owned(),
        tool_schema: TOOL_SCHEMA.to_owned(),
        authority_class: "deterministic_reconstruction_not_original_recovery".to_owned(),
        cohort_blake3: certificate.cohort_blake3,
        source_manifest_id: manifest.manifest_id,
        source_snapshot_id: manifest.snapshot_id,
        source_continuity_snapshot_id: continuity.source_snapshot_id.to_string(),
        reconstruction_receipt_id,
        commits_blake3: commits_blake3.clone(),
        bundle_blake3: bundle_blake3.clone(),
        commits,
    };
    validate_bundle(&bundle)?;
    fs::create_dir_all(output_root).map_err(stringify)?;
    let bundle_path = output_root.join(format!("reconstructed-graph-truth-{bundle_blake3}.json"));
    write_immutable_json(&bundle_path, &bundle)?;
    print_report(ReconstructionReport {
        schema_version: REPORT_SCHEMA,
        mode: "preview",
        store_path: store_path.display().to_string(),
        cohort_blake3: bundle.cohort_blake3.clone(),
        source_snapshot_id: bundle.source_snapshot_id.clone(),
        bundle_path: Some(bundle_path.display().to_string()),
        bundle_blake3,
        commits_blake3,
        decisions: rows.len(),
        candidates: rows.iter().map(|row| row.decision.candidates.len()).sum(),
        outcomes: rows.len(),
        human_acceptance: rows.len(),
        commits: bundle.commits.len(),
        appended: 0,
        already_present: 0,
        kernel_generation: 0,
        exact_expected_commit_ids: true,
        exact_decision_receipt_membership: true,
        explicit_reconstruction_provenance: true,
    })
}

fn apply_or_verify(store_path: &Path, bundle_path: &Path, apply: bool) -> Result<(), String> {
    let bundle: ReconstructionBundle = read_json(bundle_path)?;
    validate_bundle(&bundle)?;
    let store = PhoenixOvergraphStore::open(store_path).map_err(stringify)?;
    verify_store_authorities(&store, &bundle, apply)?;
    let mut appended = 0;
    let mut already_present = 0;
    if apply {
        for commit in &bundle.commits {
            match store.append_graph_truth_commit(commit).map_err(stringify)? {
                GraphTruthCommitAppend::Appended => appended += 1,
                GraphTruthCommitAppend::AlreadyPresent { .. } => already_present += 1,
            }
        }
        store.publish_and_close().map_err(stringify)?;
    } else {
        already_present = bundle.commits.len();
        store.close_fast().map_err(stringify)?;
    }

    let reopened = PhoenixOvergraphStore::open(store_path).map_err(stringify)?;
    verify_store_authorities(&reopened, &bundle, false)?;
    let decisions = reopened
        .load_native_decision_receipts()
        .map_err(stringify)?;
    let outcomes = count_outcomes(&reopened, &decisions)?;
    let human_acceptance = count_human_acceptance(&reopened, &decisions)?;
    let kernel_generation = reopened.kernel_current_generation().map_err(stringify)?;
    reopened.close_fast().map_err(stringify)?;
    print_report(ReconstructionReport {
        schema_version: REPORT_SCHEMA,
        mode: if apply { "apply" } else { "verify" },
        store_path: store_path.display().to_string(),
        cohort_blake3: bundle.cohort_blake3,
        source_snapshot_id: bundle.source_snapshot_id,
        bundle_path: Some(bundle_path.display().to_string()),
        bundle_blake3: bundle.bundle_blake3,
        commits_blake3: bundle.commits_blake3,
        decisions: decisions.len(),
        candidates: decisions.iter().map(|row| row.candidates.len()).sum(),
        outcomes,
        human_acceptance,
        commits: bundle.commits.len(),
        appended,
        already_present,
        kernel_generation,
        exact_expected_commit_ids: true,
        exact_decision_receipt_membership: true,
        explicit_reconstruction_provenance: true,
    })
}

fn authoritative_rows(
    store: &PhoenixOvergraphStore,
    snapshot_id: &str,
    certificate: &CohortCertificate,
) -> Result<Vec<ReconstructionRow>, String> {
    let decisions = store.load_native_decision_receipts().map_err(stringify)?;
    if decisions.len() as u64 != certificate.receipt_count {
        return Err("decision count does not match certificate".to_owned());
    }
    let candidate_count = decisions
        .iter()
        .map(|row| row.candidates.len())
        .sum::<usize>();
    if candidate_count as u64 != certificate.candidate_count {
        return Err("candidate count does not match certificate".to_owned());
    }
    if count_outcomes(store, &decisions)? as u64 != certificate.outcome_receipt_count {
        return Err("outcome count does not match certificate".to_owned());
    }
    let mut rows = Vec::with_capacity(decisions.len());
    for decision in decisions {
        if decision.task_family != NativeDecisionTaskFamily::CanonicalEpisodeAssignment
            || !decision
                .lineage_ids
                .iter()
                .any(|value| value == snapshot_id)
        {
            return Err(format!(
                "decision {} is outside the reconstruction cohort",
                decision.receipt_id
            ));
        }
        let evidence = store
            .load_native_decision_reward_evidence_for_decision(&decision.receipt_id)
            .map_err(stringify)?;
        let mut human = evidence.into_iter().filter(|row| {
            row.dimension == GraphDecisionRewardDimension::HumanAcceptance
                && row.policy_id == CANONICAL_HUMAN_EVALUATION_POLICY
        });
        let row = human.next().ok_or_else(|| {
            format!(
                "decision {} lacks HumanAcceptance authority",
                decision.receipt_id
            )
        })?;
        if human.next().is_some() {
            return Err(format!(
                "decision {} has duplicate HumanAcceptance authority",
                decision.receipt_id
            ));
        }
        rows.push(ReconstructionRow {
            decision,
            human: row,
        });
    }
    rows.sort_unstable_by_key(|row| row.human.lineage_generation);
    for (index, row) in rows.iter().enumerate() {
        if row.human.lineage_generation != index as u64 + 1 {
            return Err("HumanAcceptance lineage generations are not exactly 1..760".to_owned());
        }
    }
    Ok(rows)
}

fn reconstruct_commits(
    rows: &[ReconstructionRow],
    continuity: &StoryContinuityContract,
    snapshot_id: &str,
    reconstruction_receipt_id: &str,
) -> Result<Vec<GraphTruthCommit>, String> {
    let events = continuity
        .events
        .iter()
        .map(|row| (row.id.as_str(), row))
        .collect::<HashMap<_, _>>();
    let episodes = continuity
        .episodes
        .iter()
        .map(|row| (row.id.as_str(), row))
        .collect::<HashMap<_, _>>();
    let mut active_vertices = HashSet::<String>::new();
    let mut commits = Vec::with_capacity(rows.len());
    for row in rows {
        let decision = &row.decision;
        let chosen = decision
            .candidates
            .get(decision.chosen_candidate_ordinal as usize)
            .ok_or_else(|| format!("decision {} chosen ordinal is invalid", decision.receipt_id))?;
        let (event_id, episode_id) = match &chosen.action {
            GraphDecisionAction::AttachToEpisode(action) => {
                (action.event_id.as_str(), action.episode_id.as_str())
            }
            _ => return Err("reconstruction cohort contains a non-attach action".to_owned()),
        };
        let event = events
            .get(event_id)
            .copied()
            .ok_or_else(|| format!("continuity event is missing: {event_id}"))?;
        let episode = episodes
            .get(episode_id)
            .copied()
            .ok_or_else(|| format!("continuity episode is missing: {episode_id}"))?;
        if event.note_id != episode.note_id {
            return Err(format!(
                "event {event_id} and episode {episode_id} cross scopes"
            ));
        }
        let commit_id = content_id(&(
            "phoenix-canonical-episode-assignment-commit-id/v1",
            decision.receipt_id.as_str(),
            chosen.action_identity.as_str(),
        ))?;
        if commit_id != row.human.graph_truth_commit_id {
            return Err(format!(
                "decision {} expected commit id mismatch",
                decision.receipt_id
            ));
        }
        let operator_id = decision.authority.authority_id.as_str();
        let operator_receipt_id = content_id(&(
            "phoenix-canonical-episode-assignment-operator-authorization/v1",
            decision.receipt_id.as_str(),
            chosen.action_identity.as_str(),
            commit_id.as_str(),
            operator_id,
        ))?;
        if !row
            .human
            .source_receipt_ids
            .contains(&operator_receipt_id.as_str().into())
        {
            return Err(format!(
                "decision {} operator receipt mismatch",
                decision.receipt_id
            ));
        }
        let built_at = decision
            .evidence_anchors
            .iter()
            .map(|anchor| anchor.available_at)
            .collect::<BTreeSet<_>>();
        if built_at.len() != 1 {
            return Err(format!(
                "decision {} source build time is ambiguous",
                decision.receipt_id
            ));
        }
        let source_snapshot_built_at = *built_at.iter().next().expect("one build timestamp");
        if source_snapshot_built_at <= 0 || row.human.observed_at != decision.observed_at {
            return Err(format!(
                "decision {} authoritative timestamps drift",
                decision.receipt_id
            ));
        }
        let mut vertices = Vec::with_capacity(2);
        if active_vertices.insert(event_id.to_owned()) {
            vertices.push(event_vertex(event, snapshot_id, decision.observed_at));
        }
        if active_vertices.insert(episode_id.to_owned()) {
            vertices.push(episode_vertex(episode, snapshot_id, decision.observed_at));
        }
        let digest = blake3::hash(
            format!(
                "phoenix-canonical-episode-assignment-idempotency/v1\0{}\0{}",
                decision.receipt_id, decision.candidate_set_id
            )
            .as_bytes(),
        );
        let commit = GraphTruthCommit {
            header: GraphTruthCommitHeader {
                commit_id: commit_id.into(),
                generation: row.human.lineage_generation,
                operation: GraphTruthOperation::Assert,
                truth: GraphTruthDescriptor {
                    kind: GraphTruthKind::Structural,
                    plane: None,
                },
                source_generations: vec![GraphTruthSourceGenerationRef {
                    source_id: snapshot_id.into(),
                    generation: source_snapshot_built_at as u64,
                }]
                .into(),
                receipt_ids: vec![
                    decision.receipt_id.clone(),
                    operator_receipt_id.into(),
                    reconstruction_receipt_id.into(),
                ]
                .into(),
                compiler_policy: GraphTruthCompilerPolicy {
                    compiler_id: "phoenix-api-reconstruction".into(),
                    compiler_version: "1".into(),
                    policy_id: EPISODE_ASSIGNMENT_POLICY.into(),
                    policy_version: "1-reconstructed".into(),
                },
                idempotency_hash: GraphTruthDigest(*digest.as_bytes()),
                committed_at: row.human.observed_at,
                ..GraphTruthCommitHeader::default()
            },
            batch: KernelMutationBatch {
                layer: KernelGraphLayer::Asserted,
                scope: KernelMutationScope::Document {
                    document_id: event.note_id.to_string(),
                },
                recorded_at: Some(row.human.observed_at),
                vertices,
                edges: vec![episode_event_edge(
                    event,
                    episode,
                    decision,
                    snapshot_id,
                    row.human.observed_at,
                )],
            },
        };
        commit.validate().map_err(stringify)?;
        commits.push(commit);
    }
    GraphTruthLineage::build(commits.clone()).map_err(stringify)?;
    Ok(commits)
}

fn validate_bundle(bundle: &ReconstructionBundle) -> Result<(), String> {
    if bundle.schema_version != BUNDLE_SCHEMA
        || bundle.tool_schema != TOOL_SCHEMA
        || bundle.authority_class != "deterministic_reconstruction_not_original_recovery"
        || bundle.commits.len() != 760
    {
        return Err("reconstruction bundle contract mismatch".to_owned());
    }
    let commits_blake3 = content_id(&bundle.commits)?;
    if commits_blake3 != bundle.commits_blake3 {
        return Err("reconstruction commits digest mismatch".to_owned());
    }
    let bundle_blake3 = content_id(&(
        BUNDLE_SCHEMA,
        bundle.cohort_blake3.as_str(),
        bundle.source_manifest_id.as_str(),
        bundle.source_snapshot_id.as_str(),
        bundle.source_continuity_snapshot_id.as_str(),
        bundle.reconstruction_receipt_id.as_str(),
        bundle.commits_blake3.as_str(),
    ))?;
    if bundle_blake3 != bundle.bundle_blake3 {
        return Err("reconstruction bundle digest mismatch".to_owned());
    }
    for (index, commit) in bundle.commits.iter().enumerate() {
        commit.validate().map_err(stringify)?;
        if commit.header.generation != index as u64 + 1
            || !commit
                .header
                .receipt_ids
                .contains(&bundle.reconstruction_receipt_id.as_str().into())
        {
            return Err("reconstruction commit provenance/generation mismatch".to_owned());
        }
    }
    GraphTruthLineage::build(bundle.commits.clone()).map_err(stringify)?;
    Ok(())
}

fn verify_store_authorities(
    store: &PhoenixOvergraphStore,
    bundle: &ReconstructionBundle,
    allow_empty: bool,
) -> Result<(), String> {
    let decisions = store.load_native_decision_receipts().map_err(stringify)?;
    if decisions.len() != 760
        || decisions
            .iter()
            .map(|row| row.candidates.len())
            .sum::<usize>()
            != 2718
    {
        return Err("store cohort identity drift".to_owned());
    }
    if count_outcomes(store, &decisions)? != 760
        || count_human_acceptance(store, &decisions)? != 760
    {
        return Err("store outcome/reward authority drift".to_owned());
    }
    let commits = store.load_graph_truth_commits().map_err(stringify)?;
    if allow_empty && commits.is_empty() {
        return Ok(());
    }
    if commits != bundle.commits {
        return Err(
            "store GraphTruth commits do not exactly match reconstruction bundle".to_owned(),
        );
    }
    Ok(())
}

fn count_outcomes(
    store: &PhoenixOvergraphStore,
    decisions: &[NativeDecisionReceipt],
) -> Result<usize, String> {
    let mut count = 0;
    for decision in decisions {
        count += store
            .load_native_decision_outcome_receipts(&decision.receipt_id)
            .map_err(stringify)?
            .len();
    }
    Ok(count)
}

fn count_human_acceptance(
    store: &PhoenixOvergraphStore,
    decisions: &[NativeDecisionReceipt],
) -> Result<usize, String> {
    let mut count = 0;
    for decision in decisions {
        count += store
            .load_native_decision_reward_evidence_for_decision(&decision.receipt_id)
            .map_err(stringify)?
            .into_iter()
            .filter(|row| {
                row.dimension == GraphDecisionRewardDimension::HumanAcceptance
                    && row.policy_id == CANONICAL_HUMAN_EVALUATION_POLICY
            })
            .count();
    }
    Ok(count)
}

fn load_continuity(
    graph_run_root: &Path,
    manifest: &DurableGraphRunManifest,
) -> Result<StoryContinuityContract, String> {
    let section = manifest
        .sections
        .get("continuity")
        .ok_or("durable continuity section is missing")?;
    if section.encoding != "zstd+json" {
        return Err("durable continuity encoding mismatch".to_owned());
    }
    let path = graph_run_root
        .join("blobs")
        .join(format!("{}.zst", section.identity));
    let file = File::open(&path).map_err(stringify)?;
    let mapped = unsafe { MmapOptions::new().map(&file) }.map_err(stringify)?;
    let bytes = zstd::stream::decode_all(Cursor::new(&mapped[..])).map_err(stringify)?;
    if bytes.len() as u64 != section.raw_bytes {
        return Err("durable continuity raw byte count mismatch".to_owned());
    }
    let envelope: ContinuityEnvelope = serde_json::from_slice(&bytes).map_err(stringify)?;
    Ok(envelope.contract)
}

fn require_certificate(certificate: &CohortCertificate) -> Result<(), String> {
    if certificate.cohort_blake3
        != "b3-41b1287722cae9438c412f5a818f446c0386bbb44c7b48870a1e2806a4ea2a14"
        || certificate.receipt_count != 760
        || certificate.outcome_receipt_count != 760
        || certificate.candidate_count != 2_718
    {
        return Err("R-GCN cohort certificate identity mismatch".to_owned());
    }
    Ok(())
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, String> {
    let bytes = fs::read(path).map_err(stringify)?;
    serde_json::from_slice(&bytes).map_err(stringify)
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
                Err(format!(
                    "immutable artifact already exists with different bytes: {}",
                    path.display()
                ))
            }
        }
        Err(error) => Err(error.to_string()),
    }
}

fn content_id<T: Serialize>(value: &T) -> Result<String, String> {
    let bytes = serde_json::to_vec(value).map_err(stringify)?;
    Ok(format!("b3-{}", blake3::hash(&bytes).to_hex()))
}

fn snapshot_scope_prefix(value: &str) -> &str {
    value.rsplit_once(':').map_or(value, |(prefix, _)| prefix)
}

fn print_report(report: ReconstructionReport) -> Result<(), String> {
    println!(
        "{}",
        serde_json::to_string_pretty(&report).map_err(stringify)?
    );
    Ok(())
}

fn path_arg(arguments: &mut impl Iterator<Item = std::ffi::OsString>) -> Result<PathBuf, String> {
    arguments.next().map(PathBuf::from).ok_or_else(usage)
}

fn require_end(mut arguments: impl Iterator<Item = std::ffi::OsString>) -> Result<(), String> {
    if arguments.next().is_some() {
        return Err(usage());
    }
    Ok(())
}

fn stringify(error: impl std::fmt::Display) -> String {
    error.to_string()
}

fn usage() -> String {
    "usage: canonical-graph-truth-reconstruction preview <store> <graph-run-root> <manifest> <certificate> <output-root> | apply|verify <store> <bundle>".to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_scope_prefix_removes_only_the_terminal_build_identity() {
        assert_eq!(
            snapshot_scope_prefix("graph-rebuild:multi:scope:123"),
            "graph-rebuild:multi:scope"
        );
    }

    #[test]
    fn immutable_json_write_is_idempotent_and_rejects_different_bytes() {
        let root = tempfile::tempdir().expect("tempdir");
        let path = root.path().join("artifact.json");
        write_immutable_json(&path, &serde_json::json!({"value": 1})).expect("first write");
        write_immutable_json(&path, &serde_json::json!({"value": 1})).expect("idempotent write");
        assert!(write_immutable_json(&path, &serde_json::json!({"value": 2})).is_err());
    }

    #[test]
    fn content_identity_uses_canonical_json_bytes() {
        let value = ("schema/v1", "receipt", "action");
        let encoded = serde_json::to_vec(&value).expect("json");
        assert_eq!(
            content_id(&value).expect("identity"),
            format!("b3-{}", blake3::hash(&encoded).to_hex())
        );
    }
}

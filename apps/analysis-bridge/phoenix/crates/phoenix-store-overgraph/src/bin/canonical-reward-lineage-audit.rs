use std::collections::{HashMap, HashSet};
use std::{env, path::PathBuf};

use phoenix_store_native_core::{PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{GraphDecisionRewardDimension, CANONICAL_HUMAN_EVALUATION_POLICY};
use serde::Serialize;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct LineageAudit {
    schema_version: &'static str,
    decisions: usize,
    graph_truth_commits: usize,
    human_evidence: u64,
    unique_linked_commits: usize,
    missing_linked_commits: u64,
    missing_with_kernel_marker: u64,
    missing_without_kernel_marker: u64,
    marker_generation_min: Option<u64>,
    marker_generation_max: Option<u64>,
    kernel_current_generation: u64,
    kernel_checkpoint_generation: Option<u64>,
    retained_kernel_journal_entries: usize,
    linked_journal_entries: u64,
    linked_journal_entries_with_batch: u64,
    decision_receipts_missing_from_commit: u64,
    commits_after_stability_eligibility: u64,
    missing_samples: Vec<String>,
}

fn main() -> Result<(), String> {
    let store_path = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("usage: canonical-reward-lineage-audit <store-path>")?;
    let store = PhoenixOvergraphStore::open(store_path).map_err(|error| error.to_string())?;
    let decisions = store
        .load_native_decision_receipts()
        .map_err(|error| error.to_string())?;
    let commits = store
        .load_graph_truth_commits()
        .map_err(|error| error.to_string())?;
    let commit_by_id = commits
        .iter()
        .map(|commit| (commit.header.commit_id.as_str(), commit))
        .collect::<HashMap<_, _>>();
    let kernel_current_generation = store
        .kernel_current_generation()
        .map_err(|error| error.to_string())?;
    let kernel_checkpoint_generation = store
        .load_kernel_checkpoint()
        .map_err(|error| error.to_string())?
        .map(|checkpoint| checkpoint.meta.generation);
    let journal = store
        .load_kernel_journal_after(0)
        .map_err(|error| error.to_string())?;
    let mut linked = HashSet::<String>::new();
    let mut audit = LineageAudit {
        schema_version: "phoenix-canonical-reward-lineage-audit/v2",
        decisions: decisions.len(),
        graph_truth_commits: commits.len(),
        human_evidence: 0,
        unique_linked_commits: 0,
        missing_linked_commits: 0,
        missing_with_kernel_marker: 0,
        missing_without_kernel_marker: 0,
        marker_generation_min: None,
        marker_generation_max: None,
        kernel_current_generation,
        kernel_checkpoint_generation,
        retained_kernel_journal_entries: journal.len(),
        linked_journal_entries: 0,
        linked_journal_entries_with_batch: 0,
        decision_receipts_missing_from_commit: 0,
        commits_after_stability_eligibility: 0,
        missing_samples: Vec::new(),
    };
    for decision in &decisions {
        let evidence = store
            .load_native_decision_reward_evidence_for_decision(&decision.receipt_id)
            .map_err(|error| error.to_string())?;
        for human in evidence.iter().filter(|row| {
            row.dimension == GraphDecisionRewardDimension::HumanAcceptance
                && row.policy_id == CANONICAL_HUMAN_EVALUATION_POLICY
        }) {
            audit.human_evidence += 1;
            linked.insert(human.graph_truth_commit_id.to_string());
            let Some(commit) = commit_by_id.get(human.graph_truth_commit_id.as_str()) else {
                audit.missing_linked_commits += 1;
                match store
                    .kernel_generation_for_commit(human.graph_truth_commit_id.as_str())
                    .map_err(|error| error.to_string())?
                {
                    Some(generation) => {
                        audit.missing_with_kernel_marker += 1;
                        audit.marker_generation_min = Some(
                            audit
                                .marker_generation_min
                                .map_or(generation, |value| value.min(generation)),
                        );
                        audit.marker_generation_max = Some(
                            audit
                                .marker_generation_max
                                .map_or(generation, |value| value.max(generation)),
                        );
                    }
                    None => audit.missing_without_kernel_marker += 1,
                }
                for entry in journal.iter().filter(|entry| {
                    entry.commit_id.as_deref() == Some(human.graph_truth_commit_id.as_str())
                }) {
                    audit.linked_journal_entries += 1;
                    audit.linked_journal_entries_with_batch += u64::from(entry.batch.is_some());
                }
                if audit.missing_samples.len() < 16 {
                    audit.missing_samples.push(format!(
                        "{} -> {}",
                        decision.receipt_id, human.graph_truth_commit_id
                    ));
                }
                continue;
            };
            if !commit.header.receipt_ids.contains(&decision.receipt_id) {
                audit.decision_receipts_missing_from_commit += 1;
            }
            if commit.header.committed_at > human.stability_eligible_at {
                audit.commits_after_stability_eligibility += 1;
            }
        }
    }
    audit.unique_linked_commits = linked.len();
    store.close_fast().map_err(|error| error.to_string())?;
    println!(
        "{}",
        serde_json::to_string_pretty(&audit).map_err(|error| error.to_string())?
    );
    Ok(())
}

use crate::{run, SearchPolicy, SemanticFeatures, Stage1Run, Stage1RunConfig};
use r1_search::RunTrace;
use r1_world::InferenceTask;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReplayReport {
    pub passed: bool,
    pub semantic_match: bool,
    pub timestamps_monotone: bool,
    pub event_count: u64,
    pub expected_digest: String,
    pub replay_digest: String,
}

/// Re-run with a fresh deterministic callback instance and compare every
/// non-timing trace field, including RNG states, merges, resampling, and costs.
pub fn verify_replay(
    task: &InferenceTask,
    features: &SemanticFeatures,
    config: Stage1RunConfig,
    fresh_policy: &mut impl SearchPolicy,
    expected: &Stage1Run,
) -> Result<ReplayReport, crate::SearchError> {
    let replay = run(task, features, config, fresh_policy)?;
    let timestamps_monotone = monotone(&expected.trace) && monotone(&replay.trace);
    let expected_normalized = normalize(&expected.trace);
    let replay_normalized = normalize(&replay.trace);
    let expected_digest = digest(&expected_normalized);
    let replay_digest = digest(&replay_normalized);
    let semantic_match = expected_normalized == replay_normalized
        && expected.event_diagnostics == replay.event_diagnostics
        && expected.manifest.arm == replay.manifest.arm
        && expected.manifest.merge_mode == replay.manifest.merge_mode
        && expected.manifest.proposal_id == replay.manifest.proposal_id
        && expected.manifest.selector_id == replay.manifest.selector_id
        && expected.manifest.value_id == replay.manifest.value_id
        && expected.manifest.learned_sample_temperature
            == replay.manifest.learned_sample_temperature
        && expected.manifest.value_scoring_policy == replay.manifest.value_scoring_policy
        && expected.manifest.search_allocation_policy == replay.manifest.search_allocation_policy;
    Ok(ReplayReport {
        passed: semantic_match && timestamps_monotone,
        semantic_match,
        timestamps_monotone,
        event_count: expected.trace.events.len() as u64,
        expected_digest,
        replay_digest,
    })
}

fn monotone(trace: &RunTrace) -> bool {
    let mut active = trace.header.initial_completion_active_ns;
    let mut wall = trace.header.initial_completion_wall_ns;
    for event in &trace.events {
        if event.cumulative_active_ns < active || event.cumulative_wall_ns < wall {
            return false;
        }
        active = event.cumulative_active_ns;
        wall = event.cumulative_wall_ns;
    }
    trace.ledger.end_to_end_wall_ns >= wall
}

fn normalize(trace: &RunTrace) -> RunTrace {
    let mut result = trace.clone();
    result.header.timing_kind = "stage1_timing_excluded_for_replay".to_owned();
    result.header.initial_completion_active_ns = 0;
    result.header.initial_completion_wall_ns = 0;
    result.header.initial_costs.cpu_active_ns = 0;
    result.header.initial_costs.gpu_active_ns = 0;
    result.ledger.cpu_active_ns = 0;
    result.ledger.gpu_active_ns = 0;
    result.ledger.end_to_end_wall_ns = 0;
    result.ledger.trace_bytes_estimate = 0;
    for event in &mut result.events {
        event.cumulative_active_ns = 0;
        event.cumulative_wall_ns = 0;
        event.costs.cpu_active_ns = 0;
        event.costs.gpu_active_ns = 0;
    }
    result
}

fn digest(trace: &RunTrace) -> String {
    let bytes = serde_json::to_vec(trace).unwrap_or_default();
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

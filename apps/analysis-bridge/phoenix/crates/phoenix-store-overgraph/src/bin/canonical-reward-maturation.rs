use std::env;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use phoenix_store_native_core::PhoenixNativeDecisionStore;
use phoenix_store_overgraph::{CanonicalRewardProducerReport, PhoenixOvergraphStore};
use phoenix_types::{
    GraphDecisionRewardDimension, NativeDecisionRewardObservationOperation,
    NativeDecisionRewardObservationReceipt,
};
use serde::Serialize;

const SCHEMA: &str = "phoenix-canonical-reward-maturation-census/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Mode {
    DryRun,
    Reconcile,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct MaturationCensus {
    schema_version: &'static str,
    mode: &'static str,
    observed_at: i64,
    decisions: u64,
    candidates: u64,
    outcomes: u64,
    human_acceptance_observed: u64,
    future_stability_observed: u64,
    pending_stability_horizons: u64,
    first_stability_eligible_at: Option<i64>,
    full_cohort_stability_eligible_at: Option<i64>,
    producer: Option<CanonicalRewardProducerReport>,
}

fn main() -> Result<(), String> {
    let mut arguments = env::args_os().skip(1);
    let store_path = arguments
        .next()
        .map(PathBuf::from)
        .ok_or("usage: canonical-reward-maturation <store-path> <dry-run|reconcile> [observed-at-ms] [expected-decisions]")?;
    let mode = match arguments
        .next()
        .ok_or("missing dry-run or reconcile mode")?
        .to_string_lossy()
        .as_ref()
    {
        "dry-run" => Mode::DryRun,
        "reconcile" => Mode::Reconcile,
        _ => return Err("mode must be dry-run or reconcile".to_owned()),
    };
    let observed_at = arguments
        .next()
        .map(|value| value.to_string_lossy().parse::<i64>())
        .transpose()
        .map_err(|error| error.to_string())?
        .unwrap_or(now_ms()?);
    let expected = arguments
        .next()
        .map(|value| value.to_string_lossy().parse::<u64>())
        .transpose()
        .map_err(|error| error.to_string())?
        .unwrap_or(760);
    if observed_at <= 0 || expected == 0 || arguments.next().is_some() {
        return Err("invalid maturation arguments".to_owned());
    }

    let store = PhoenixOvergraphStore::open(&store_path).map_err(|error| error.to_string())?;
    let producer = (mode == Mode::Reconcile)
        .then(|| store.reconcile_canonical_reward_producers(observed_at))
        .transpose()
        .map_err(|error| error.to_string())?;
    let census = census(&store, mode, observed_at, producer)?;
    if census.decisions != expected
        || census.outcomes != expected
        || census.human_acceptance_observed != expected
    {
        return Err(format!(
            "exact maturation census failed: decisions {}, outcomes {}, human observations {}, expected {expected}",
            census.decisions, census.outcomes, census.human_acceptance_observed
        ));
    }
    if mode == Mode::Reconcile
        && census
            .full_cohort_stability_eligible_at
            .is_some_and(|eligible_at| observed_at >= eligible_at)
        && census.future_stability_observed != expected
    {
        return Err(format!(
            "full stability maturation failed: observed {}, expected {expected}",
            census.future_stability_observed
        ));
    }
    store.close_fast().map_err(|error| error.to_string())?;
    println!(
        "{}",
        serde_json::to_string_pretty(&census).map_err(|error| error.to_string())?
    );
    Ok(())
}

fn census(
    store: &PhoenixOvergraphStore,
    mode: Mode,
    observed_at: i64,
    producer: Option<CanonicalRewardProducerReport>,
) -> Result<MaturationCensus, String> {
    let decisions = store
        .load_native_decision_receipts()
        .map_err(|error| error.to_string())?;
    let mut candidates = 0_u64;
    let mut outcomes = 0_u64;
    let mut human = 0_u64;
    let mut stability = 0_u64;
    let mut first_eligible = None::<i64>;
    let mut full_eligible = None::<i64>;
    for decision in &decisions {
        candidates = candidates.saturating_add(decision.candidates.len() as u64);
        outcomes = outcomes.saturating_add(
            store
                .load_native_decision_outcome_receipts(&decision.receipt_id)
                .map_err(|error| error.to_string())?
                .len() as u64,
        );
        let evidence = store
            .load_native_decision_reward_evidence_for_decision(&decision.receipt_id)
            .map_err(|error| error.to_string())?;
        for row in evidence
            .iter()
            .filter(|row| row.dimension == GraphDecisionRewardDimension::HumanAcceptance)
        {
            first_eligible = Some(first_eligible.map_or(row.stability_eligible_at, |prior| {
                prior.min(row.stability_eligible_at)
            }));
            full_eligible = Some(full_eligible.map_or(row.stability_eligible_at, |prior| {
                prior.max(row.stability_eligible_at)
            }));
        }
        let observations = store
            .load_native_decision_reward_observations(&decision.receipt_id)
            .map_err(|error| error.to_string())?;
        human += u64::from(active_dimension(
            &observations,
            GraphDecisionRewardDimension::HumanAcceptance,
        ));
        stability += u64::from(active_dimension(
            &observations,
            GraphDecisionRewardDimension::FutureStability,
        ));
    }
    Ok(MaturationCensus {
        schema_version: SCHEMA,
        mode: match mode {
            Mode::DryRun => "dry-run",
            Mode::Reconcile => "reconcile",
        },
        observed_at,
        decisions: decisions.len() as u64,
        candidates,
        outcomes,
        human_acceptance_observed: human,
        future_stability_observed: stability,
        pending_stability_horizons: decisions.len() as u64 - stability,
        first_stability_eligible_at: first_eligible,
        full_cohort_stability_eligible_at: full_eligible,
        producer,
    })
}

fn active_dimension(
    rows: &[NativeDecisionRewardObservationReceipt],
    dimension: GraphDecisionRewardDimension,
) -> bool {
    rows.iter()
        .filter(|row| row.dimension == dimension)
        .max_by(|left, right| {
            (left.observed_at, left.receipt_id.as_str())
                .cmp(&(right.observed_at, right.receipt_id.as_str()))
        })
        .is_some_and(|row| {
            row.operation != NativeDecisionRewardObservationOperation::Retract
                && row.score_micros.is_some()
        })
}

fn now_ms() -> Result<i64, String> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_millis()
        .try_into()
        .map_err(|_| "system time exceeds i64 milliseconds".to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_types::{
        GraphDecisionEvidenceRef, NativeDecisionAuthorityClass,
        NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION,
    };

    #[test]
    fn latest_retraction_removes_dimension_from_the_mature_census() {
        let observed = observation(
            GraphDecisionRewardDimension::FutureStability,
            NativeDecisionRewardObservationOperation::Observe,
            100,
            Some(1_000_000),
        );
        let retracted = observation(
            GraphDecisionRewardDimension::FutureStability,
            NativeDecisionRewardObservationOperation::Retract,
            200,
            None,
        );
        assert!(!active_dimension(
            &[observed, retracted],
            GraphDecisionRewardDimension::FutureStability
        ));
    }

    #[test]
    fn dimensions_are_counted_independently() {
        let human = observation(
            GraphDecisionRewardDimension::HumanAcceptance,
            NativeDecisionRewardObservationOperation::Observe,
            100,
            Some(1_000_000),
        );
        assert!(active_dimension(
            std::slice::from_ref(&human),
            GraphDecisionRewardDimension::HumanAcceptance
        ));
        assert!(!active_dimension(
            &[human],
            GraphDecisionRewardDimension::FutureStability
        ));
    }

    fn observation(
        dimension: GraphDecisionRewardDimension,
        operation: NativeDecisionRewardObservationOperation,
        observed_at: i64,
        score_micros: Option<i32>,
    ) -> NativeDecisionRewardObservationReceipt {
        NativeDecisionRewardObservationReceipt {
            schema_version: NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION,
            receipt_id: format!("receipt-{observed_at}").into(),
            decision_receipt_id: "decision-receipt".into(),
            decision_id: "decision".into(),
            candidate_action_identity: "action".into(),
            truth_link_id: "truth-link".into(),
            graph_truth_commit_id: "commit".into(),
            dimension,
            operation,
            score_micros,
            observed_at,
            authority_class: NativeDecisionAuthorityClass::AuthoritativeGraphOutcome,
            authority_id: "authority".into(),
            predecessor_observation_receipt_id: None,
            evidence_anchors: vec![GraphDecisionEvidenceRef {
                evidence_id: "evidence".into(),
                authority_id: "authority".into(),
                available_at: observed_at,
            }],
        }
    }
}

use std::collections::{HashMap, HashSet};

use phoenix_store_native_core::{
    NativeDecisionReceiptAppend, PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore, StoreError,
};
use phoenix_types::{
    certify_native_decision_reward_observation, GraphDecisionEvidenceRef,
    GraphDecisionRewardDimension, NativeDecisionAuthorityClass,
    NativeDecisionRewardObservationError, NativeDecisionRewardObservationOperation,
    NativeDecisionRewardObservationReceipt, NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION,
};
use serde::{Deserialize, Serialize};

use crate::{
    certify_native_decision_graph_truth_link, NativeDecisionGraphTruthLinkRequest,
    NativeOperatorDecisionError,
};

pub const NATIVE_REWARD_OBSERVATION_SCHEMA: &str = "phoenix-native-reward-observation/v1";
pub const NATIVE_REWARD_OBSERVATION_CENSUS_SCHEMA: &str =
    "phoenix-native-reward-observation-census/v1";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeRewardObservationRequest {
    pub schema_version: String,
    pub truth_link: NativeDecisionGraphTruthLinkRequest,
    pub truth_link_id: String,
    pub dimension: GraphDecisionRewardDimension,
    pub operation: NativeDecisionRewardObservationOperation,
    pub score_micros: Option<i32>,
    pub observed_at: i64,
    pub authority_class: NativeDecisionAuthorityClass,
    pub authority_id: String,
    pub predecessor_observation_receipt_id: Option<String>,
    pub evidence_anchors: Vec<GraphDecisionEvidenceRef>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeRewardObservationResponse {
    pub schema_version: String,
    pub receipt_id: String,
    pub decision_id: String,
    pub decision_receipt_id: String,
    pub candidate_action_identity: String,
    pub truth_link_id: String,
    pub graph_truth_commit_id: String,
    pub dimension: GraphDecisionRewardDimension,
    pub operation: NativeDecisionRewardObservationOperation,
    pub score_micros: Option<i32>,
    pub observed_at: i64,
    pub appended: bool,
    pub reward_complete: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeRewardObservationCensus {
    pub schema_version: String,
    pub observation_receipts: u64,
    pub active_human_acceptance: u64,
    pub active_future_stability: u64,
    pub retracted_dimensions: u64,
    pub partially_observed_decisions: u64,
    pub fully_observed_decisions: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum NativeRewardObservationApiError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Link(#[from] NativeOperatorDecisionError),
    #[error(transparent)]
    Receipt(#[from] NativeDecisionRewardObservationError),
    #[error("invalid native reward observation: {0}")]
    Invalid(&'static str),
}

pub fn record_native_reward_observation<S>(
    store: &S,
    request: NativeRewardObservationRequest,
) -> Result<NativeRewardObservationResponse, NativeRewardObservationApiError>
where
    S: PhoenixNativeDecisionStore + PhoenixGraphKernelStoreV2 + ?Sized,
{
    if request.schema_version != NATIVE_REWARD_OBSERVATION_SCHEMA
        || request.truth_link_id.trim().is_empty()
        || request.observed_at <= 0
        || request.authority_id.trim().is_empty()
        || request.evidence_anchors.is_empty()
    {
        return Err(NativeRewardObservationApiError::Invalid("request contract"));
    }
    if !matches!(
        request.dimension,
        GraphDecisionRewardDimension::HumanAcceptance
            | GraphDecisionRewardDimension::FutureStability
    ) {
        return Err(NativeRewardObservationApiError::Invalid(
            "dimension producer is not installed",
        ));
    }
    let link = certify_native_decision_graph_truth_link(store, request.truth_link.clone())?;
    if request.truth_link_id != link.link_id || request.observed_at < link.linked_at {
        return Err(NativeRewardObservationApiError::Invalid(
            "truth link identity or chronology mismatch",
        ));
    }
    validate_dimension_authority(&request, link.linked_at, link.stability_eligible_at)?;
    let receipt =
        certify_native_decision_reward_observation(NativeDecisionRewardObservationReceipt {
            schema_version: NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION,
            receipt_id: "pending".into(),
            decision_receipt_id: link.decision_receipt_id.as_str().into(),
            decision_id: link.decision_id.as_str().into(),
            candidate_action_identity: link.chosen_action_identity.as_str().into(),
            truth_link_id: link.link_id.as_str().into(),
            graph_truth_commit_id: link.graph_truth_commit_id.as_str().into(),
            dimension: request.dimension,
            operation: request.operation,
            score_micros: request.score_micros,
            observed_at: request.observed_at,
            authority_class: request.authority_class,
            authority_id: request.authority_id.as_str().into(),
            predecessor_observation_receipt_id: request
                .predecessor_observation_receipt_id
                .as_deref()
                .map(Into::into),
            evidence_anchors: request.evidence_anchors,
        })?;
    let appended = matches!(
        store.append_native_decision_reward_observation(&receipt)?,
        NativeDecisionReceiptAppend::Appended { .. }
    );
    Ok(NativeRewardObservationResponse {
        schema_version: NATIVE_REWARD_OBSERVATION_SCHEMA.to_owned(),
        receipt_id: receipt.receipt_id.to_string(),
        decision_id: receipt.decision_id.to_string(),
        decision_receipt_id: receipt.decision_receipt_id.to_string(),
        candidate_action_identity: receipt.candidate_action_identity.to_string(),
        truth_link_id: receipt.truth_link_id.to_string(),
        graph_truth_commit_id: receipt.graph_truth_commit_id.to_string(),
        dimension: receipt.dimension,
        operation: receipt.operation,
        score_micros: receipt.score_micros,
        observed_at: receipt.observed_at,
        appended,
        reward_complete: false,
    })
}

pub fn native_reward_observation_census<S: PhoenixNativeDecisionStore + ?Sized>(
    store: &S,
) -> Result<NativeRewardObservationCensus, NativeRewardObservationApiError> {
    let decisions = store.load_native_decision_receipts()?;
    let mut census = NativeRewardObservationCensus {
        schema_version: NATIVE_REWARD_OBSERVATION_CENSUS_SCHEMA.to_owned(),
        ..NativeRewardObservationCensus::default()
    };
    for decision in decisions {
        let observations = store.load_native_decision_reward_observations(&decision.receipt_id)?;
        census.observation_receipts += observations.len() as u64;
        let mut terminal = HashMap::new();
        for observation in observations {
            let key = (
                observation.candidate_action_identity.clone(),
                observation.dimension,
            );
            if terminal
                .get(&key)
                .is_none_or(|prior: &NativeDecisionRewardObservationReceipt| {
                    prior.observed_at < observation.observed_at
                })
            {
                terminal.insert(key, observation);
            }
        }
        let chosen = &decision.candidates[decision.chosen_candidate_ordinal as usize];
        let chosen_terminal = terminal
            .into_iter()
            .filter(|((action, _), _)| action == chosen.action_identity)
            .collect::<Vec<_>>();
        let mut active = HashSet::new();
        for ((_, dimension), observation) in chosen_terminal {
            if observation.operation == NativeDecisionRewardObservationOperation::Retract {
                census.retracted_dimensions += 1;
                continue;
            }
            active.insert(dimension);
            match dimension {
                GraphDecisionRewardDimension::HumanAcceptance => {
                    census.active_human_acceptance += 1
                }
                GraphDecisionRewardDimension::FutureStability => {
                    census.active_future_stability += 1
                }
                _ => {}
            }
        }
        if active.len() == GraphDecisionRewardDimension::ALL.len() {
            census.fully_observed_decisions += 1;
        } else if !active.is_empty() {
            census.partially_observed_decisions += 1;
        }
    }
    Ok(census)
}

fn validate_dimension_authority(
    request: &NativeRewardObservationRequest,
    linked_at: i64,
    stability_eligible_at: i64,
) -> Result<(), NativeRewardObservationApiError> {
    let evidence_floor = match request.dimension {
        GraphDecisionRewardDimension::HumanAcceptance => {
            if request.authority_class != NativeDecisionAuthorityClass::OperatorPreference {
                return Err(NativeRewardObservationApiError::Invalid(
                    "human acceptance requires operator authority",
                ));
            }
            linked_at
        }
        GraphDecisionRewardDimension::FutureStability => {
            if request.authority_class != NativeDecisionAuthorityClass::AuthoritativeGraphOutcome
                || request.observed_at < stability_eligible_at
            {
                return Err(NativeRewardObservationApiError::Invalid(
                    "future stability requires mature graph authority",
                ));
            }
            stability_eligible_at
        }
        _ => unreachable!("unsupported dimensions rejected before authority validation"),
    };
    if request
        .evidence_anchors
        .iter()
        .any(|evidence| evidence.available_at < evidence_floor)
    {
        return Err(NativeRewardObservationApiError::Invalid(
            "reward evidence predates its authority boundary",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "native_reward_observation_tests.rs"]
mod tests;

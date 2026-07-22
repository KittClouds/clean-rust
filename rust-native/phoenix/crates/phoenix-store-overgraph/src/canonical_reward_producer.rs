use phoenix_graph_kernel::{GraphTruthCommit, GraphTruthLineage};
use phoenix_store_native_core::{
    NativeDecisionReceiptAppend, PhoenixGraphKernelStoreV2, PhoenixNativeDecisionStore, StoreError,
};
use phoenix_types::{
    certify_native_decision_reward_evidence, certify_native_decision_reward_observation,
    content_address_native_decision_graph_truth_link, GraphDecisionEvidenceRef,
    GraphDecisionRewardDimension, NativeDecisionAuthorityClass, NativeDecisionGraphTruthLink,
    NativeDecisionOutcomeOperation, NativeDecisionReceipt, NativeDecisionRewardEvidenceReceipt,
    NativeDecisionRewardObservationOperation, NativeDecisionRewardObservationReceipt,
    CANONICAL_FUTURE_STABILITY_POLICY, CANONICAL_HUMAN_EVALUATION_POLICY,
    CANONICAL_REWARD_STABILITY_HORIZON_MS, GRAPH_DECISION_REWARD_SCALE_MICROS,
    NATIVE_DECISION_REWARD_EVIDENCE_SCHEMA_VERSION,
    NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION, NATIVE_DECISION_TRUTH_LINK_SCHEMA,
};
use serde::{Deserialize, Serialize};

use super::PhoenixOvergraphStore;

pub const CANONICAL_REWARD_PRODUCER_REPORT_SCHEMA: &str =
    "phoenix-canonical-reward-producer-report/v1";
const GRAPH_OUTCOME_AUTHORITY: &str = "phoenix:graph-truth-lineage";

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CanonicalRewardProducerReport {
    pub schema_version: String,
    pub observed_at: i64,
    pub linked_commits: u64,
    pub human_evidence_appended: u64,
    pub human_observations_appended: u64,
    pub stability_evidence_appended: u64,
    pub stability_observations_appended: u64,
    pub already_observed: u64,
    pub pending_horizons: u64,
    pub next_eligible_at: Option<i64>,
}

impl PhoenixOvergraphStore {
    pub fn reconcile_canonical_reward_producers(
        &self,
        observed_at: i64,
    ) -> Result<CanonicalRewardProducerReport, StoreError> {
        if observed_at <= 0 {
            return Err(StoreError::Query(
                "canonical reward observer timestamp must be positive".to_owned(),
            ));
        }
        let commits = self.load_graph_truth_commits()?;
        let mut report = report(observed_at);
        for commit in commits
            .iter()
            .filter(|commit| commit.header.receipt_ids.len() >= 2)
        {
            produce_human_evaluations(self, commit, &mut report)?;
        }
        observe_future_stability(self, &commits, &mut report)?;
        Ok(report)
    }

    pub(super) fn after_canonical_graph_truth_commit(
        &self,
        commit: &GraphTruthCommit,
        observed_at: i64,
    ) -> Result<(), StoreError> {
        if commit.header.receipt_ids.len() < 2 {
            return Ok(());
        }
        let mut report = report(observed_at);
        produce_human_evaluations(self, commit, &mut report)
    }
}

fn produce_human_evaluations(
    store: &PhoenixOvergraphStore,
    commit: &GraphTruthCommit,
    report: &mut CanonicalRewardProducerReport,
) -> Result<(), StoreError> {
    for receipt_id in &commit.header.receipt_ids {
        let Some(decision) = store.load_native_decision_receipt(receipt_id)? else {
            continue;
        };
        report.linked_commits += 1;
        let chosen = decision
            .candidates
            .get(decision.chosen_candidate_ordinal as usize)
            .ok_or_else(|| {
                StoreError::Schema("canonical reward chosen action missing".to_owned())
            })?;
        let outcome = active_chosen_outcome(store, &decision, chosen.action_identity.as_str())?;
        let operator_receipt = outcome
            .evidence_anchors
            .iter()
            .find(|evidence| commit.header.receipt_ids.contains(&evidence.evidence_id))
            .ok_or_else(|| {
                StoreError::Schema(
                    "canonical commit is missing its operator mutation receipt".to_owned(),
                )
            })?;
        if commit.header.committed_at < outcome.observed_at {
            return Err(StoreError::Schema(
                "canonical commit predates its operator outcome".to_owned(),
            ));
        }
        let stability_eligible_at = commit
            .header
            .committed_at
            .checked_add(CANONICAL_REWARD_STABILITY_HORIZON_MS)
            .ok_or_else(|| StoreError::Schema("canonical reward horizon overflow".to_owned()))?;
        let link = content_address_native_decision_graph_truth_link(NativeDecisionGraphTruthLink {
            schema_version: NATIVE_DECISION_TRUTH_LINK_SCHEMA.to_owned(),
            link_id: "pending".to_owned(),
            decision_id: decision.decision_id.to_string(),
            decision_receipt_id: decision.receipt_id.to_string(),
            chosen_action_identity: chosen.action_identity.to_string(),
            operator_mutation_receipt_id: operator_receipt.evidence_id.to_string(),
            graph_truth_commit_id: commit.header.commit_id.to_string(),
            committed_at: commit.header.committed_at,
            linked_at: commit.header.committed_at,
            stability_eligible_at,
            reward_complete: false,
        })
        .map_err(|error| StoreError::Schema(error.to_string()))?;
        let evidence =
            certify_native_decision_reward_evidence(NativeDecisionRewardEvidenceReceipt {
                schema_version: NATIVE_DECISION_REWARD_EVIDENCE_SCHEMA_VERSION,
                receipt_id: "pending".into(),
                decision_receipt_id: decision.receipt_id.clone(),
                decision_id: decision.decision_id.clone(),
                candidate_action_identity: chosen.action_identity.clone(),
                truth_link_id: link.link_id.as_str().into(),
                graph_truth_commit_id: commit.header.commit_id.clone(),
                dimension: GraphDecisionRewardDimension::HumanAcceptance,
                score_micros: GRAPH_DECISION_REWARD_SCALE_MICROS,
                observed_at: commit.header.committed_at,
                stability_eligible_at,
                authority_class: NativeDecisionAuthorityClass::OperatorPreference,
                authority_id: outcome.outcome_authority_id.clone(),
                policy_id: CANONICAL_HUMAN_EVALUATION_POLICY.into(),
                lineage_generation: commit.header.generation,
                source_receipt_ids: vec![
                    outcome.receipt_id.clone(),
                    operator_receipt.evidence_id.clone(),
                    commit.header.commit_id.clone(),
                ],
            })
            .map_err(|error| StoreError::Schema(error.to_string()))?;
        if matches!(
            store.append_native_decision_reward_evidence(&evidence)?,
            NativeDecisionReceiptAppend::Appended { .. }
        ) {
            report.human_evidence_appended += 1;
        }
        let observation = reward_observation(&evidence)?;
        if matches!(
            store.append_native_decision_reward_observation(&observation)?,
            NativeDecisionReceiptAppend::Appended { .. }
        ) {
            report.human_observations_appended += 1;
        } else {
            report.already_observed += 1;
        }
    }
    Ok(())
}

fn observe_future_stability(
    store: &PhoenixOvergraphStore,
    commits: &[GraphTruthCommit],
    report: &mut CanonicalRewardProducerReport,
) -> Result<(), StoreError> {
    for decision in store.load_native_decision_receipts()? {
        let evidence_rows =
            store.load_native_decision_reward_evidence_for_decision(&decision.receipt_id)?;
        for human in evidence_rows.iter().filter(|row| {
            row.dimension == GraphDecisionRewardDimension::HumanAcceptance
                && row.policy_id == CANONICAL_HUMAN_EVALUATION_POLICY
        }) {
            if let Some(existing) = evidence_rows.iter().find(|row| {
                row.dimension == GraphDecisionRewardDimension::FutureStability
                    && row.truth_link_id == human.truth_link_id
            }) {
                let observation = reward_observation(existing)?;
                if matches!(
                    store.append_native_decision_reward_observation(&observation)?,
                    NativeDecisionReceiptAppend::Appended { .. }
                ) {
                    report.stability_observations_appended += 1;
                } else {
                    report.already_observed += 1;
                }
                continue;
            }
            if report.observed_at < human.stability_eligible_at {
                report.pending_horizons += 1;
                report.next_eligible_at = Some(
                    report
                        .next_eligible_at
                        .map_or(human.stability_eligible_at, |prior| {
                            prior.min(human.stability_eligible_at)
                        }),
                );
                continue;
            }
            let cutoff = commits
                .iter()
                .filter(|commit| commit.header.committed_at <= human.stability_eligible_at)
                .cloned()
                .collect::<Vec<_>>();
            let lineage = GraphTruthLineage::build(cutoff)
                .map_err(|error| StoreError::Schema(error.to_string()))?;
            let linked = lineage
                .commit_by_id(&human.graph_truth_commit_id)
                .ok_or_else(|| StoreError::Schema("linked canonical commit missing".to_owned()))?;
            let resolver = direct_resolver(lineage.commits(), linked.header.commit_id.as_str());
            let mut sources = vec![linked.header.commit_id.clone()];
            if let Some(value) = resolver {
                sources.push(value.header.commit_id.clone());
            } else {
                sources.push(
                    format!("graph-truth-lineage-cut:{}", human.stability_eligible_at).into(),
                );
            }
            let evidence =
                certify_native_decision_reward_evidence(NativeDecisionRewardEvidenceReceipt {
                    schema_version: NATIVE_DECISION_REWARD_EVIDENCE_SCHEMA_VERSION,
                    receipt_id: "pending".into(),
                    decision_receipt_id: human.decision_receipt_id.clone(),
                    decision_id: human.decision_id.clone(),
                    candidate_action_identity: human.candidate_action_identity.clone(),
                    truth_link_id: human.truth_link_id.clone(),
                    graph_truth_commit_id: human.graph_truth_commit_id.clone(),
                    dimension: GraphDecisionRewardDimension::FutureStability,
                    score_micros: if resolver.is_none() {
                        GRAPH_DECISION_REWARD_SCALE_MICROS
                    } else {
                        -GRAPH_DECISION_REWARD_SCALE_MICROS
                    },
                    observed_at: human.stability_eligible_at,
                    stability_eligible_at: human.stability_eligible_at,
                    authority_class: NativeDecisionAuthorityClass::AuthoritativeGraphOutcome,
                    authority_id: GRAPH_OUTCOME_AUTHORITY.into(),
                    policy_id: CANONICAL_FUTURE_STABILITY_POLICY.into(),
                    lineage_generation: lineage
                        .commits()
                        .last()
                        .map_or(linked.header.generation, |commit| commit.header.generation),
                    source_receipt_ids: sources,
                })
                .map_err(|error| StoreError::Schema(error.to_string()))?;
            if matches!(
                store.append_native_decision_reward_evidence(&evidence)?,
                NativeDecisionReceiptAppend::Appended { .. }
            ) {
                report.stability_evidence_appended += 1;
            }
            let observation = reward_observation(&evidence)?;
            if matches!(
                store.append_native_decision_reward_observation(&observation)?,
                NativeDecisionReceiptAppend::Appended { .. }
            ) {
                report.stability_observations_appended += 1;
            } else {
                report.already_observed += 1;
            }
        }
    }
    Ok(())
}

fn active_chosen_outcome(
    store: &PhoenixOvergraphStore,
    decision: &NativeDecisionReceipt,
    action_identity: &str,
) -> Result<phoenix_types::NativeDecisionOutcomeReceipt, StoreError> {
    store
        .load_native_decision_outcome_receipts(&decision.receipt_id)?
        .into_iter()
        .filter(|outcome| outcome.candidate_action_identity == action_identity)
        .max_by_key(|outcome| outcome.observed_at)
        .filter(|outcome| {
            outcome.operation != NativeDecisionOutcomeOperation::Retract
                && outcome.authority_class == NativeDecisionAuthorityClass::OperatorPreference
                && outcome.hard_constraints.passed
        })
        .ok_or_else(|| StoreError::Schema("canonical reward operator outcome missing".to_owned()))
}

fn direct_resolver<'a>(
    commits: &'a [GraphTruthCommit],
    linked_commit_id: &str,
) -> Option<&'a GraphTruthCommit> {
    commits.iter().find(|commit| {
        commit
            .header
            .predecessor_commit_ids
            .iter()
            .any(|id| id == linked_commit_id)
            || commit.header.reverses_commit_id.as_deref() == Some(linked_commit_id)
    })
}

fn reward_observation(
    evidence: &NativeDecisionRewardEvidenceReceipt,
) -> Result<NativeDecisionRewardObservationReceipt, StoreError> {
    certify_native_decision_reward_observation(NativeDecisionRewardObservationReceipt {
        schema_version: NATIVE_DECISION_REWARD_OBSERVATION_SCHEMA_VERSION,
        receipt_id: "pending".into(),
        decision_receipt_id: evidence.decision_receipt_id.clone(),
        decision_id: evidence.decision_id.clone(),
        candidate_action_identity: evidence.candidate_action_identity.clone(),
        truth_link_id: evidence.truth_link_id.clone(),
        graph_truth_commit_id: evidence.graph_truth_commit_id.clone(),
        dimension: evidence.dimension,
        operation: NativeDecisionRewardObservationOperation::Observe,
        score_micros: Some(evidence.score_micros),
        observed_at: evidence.observed_at,
        authority_class: evidence.authority_class,
        authority_id: evidence.authority_id.clone(),
        predecessor_observation_receipt_id: None,
        evidence_anchors: vec![GraphDecisionEvidenceRef {
            evidence_id: evidence.receipt_id.clone(),
            authority_id: evidence.authority_id.clone(),
            available_at: evidence.observed_at,
        }],
    })
    .map_err(|error| StoreError::Schema(error.to_string()))
}

fn report(observed_at: i64) -> CanonicalRewardProducerReport {
    CanonicalRewardProducerReport {
        schema_version: CANONICAL_REWARD_PRODUCER_REPORT_SCHEMA.to_owned(),
        observed_at,
        ..CanonicalRewardProducerReport::default()
    }
}

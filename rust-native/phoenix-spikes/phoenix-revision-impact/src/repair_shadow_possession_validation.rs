use std::collections::BTreeSet;

use super::*;
use crate::ShadowOutcomeValidation;

#[allow(clippy::too_many_arguments)]
pub(super) fn validate_outcomes(
    mutations: &[StoryMutation],
    requirements: &RevisionRequirementSidecar,
    temporal: &TemporalScopeSidecar,
    causal: &CausalScopeSidecar,
    memory: &MemoryScopeSidecar,
    deltas: &[SemanticDelta],
    candidate: &crate::RepairCandidate,
) -> Vec<ShadowOutcomeValidation> {
    let mutation = mutations.iter().any(|mutation| matches!(mutation,
        StoryMutation::ChangeState { subject_id, state_kind, replacement: FactValue::Entity(owner), valid_from }
            if subject_id.0 == "entity:kai" && state_kind.0 == POSSESSION_STATE_KIND
                && owner.0 == "entity:hazel" && *valid_from == StoryTime(600)));
    let fixed = candidate
        .fixed_constraints
        .iter()
        .map(CompactString::as_str)
        .collect::<BTreeSet<_>>();
    let added = requirements
        .requirements
        .iter()
        .map(|row| row.constraint_id.as_str())
        .collect::<BTreeSet<_>>();
    let edges = causal
        .edge_records
        .iter()
        .map(|row| row.edge_id.0.as_str())
        .collect::<BTreeSet<_>>();
    let beliefs = temporal
        .belief_atoms
        .iter()
        .map(|row| row.belief_id.as_str())
        .collect::<BTreeSet<_>>();
    let states = memory
        .states
        .iter()
        .map(|row| {
            (
                row.entity_id.0.as_str(),
                row.slot_key.as_str(),
                row.value.as_str(),
            )
        })
        .collect::<BTreeSet<_>>();
    let identity = deltas.iter().find_map(|delta| match delta {
        SemanticDelta::AddObjectIdentityRule { record } => Some(record),
        _ => None,
    });
    vec![
        outcome(
            "chronal_key_possession_remains_with_hazel",
            mutation
                && fixed.contains(ORIGINAL_CONSTRAINTS[1])
                && added.contains(POSSESSION_CONSTRAINT),
            &[POSSESSION_EDGE.into()],
        ),
        outcome(
            "hazel_is_present_and_responsible_for_using_the_key",
            states.contains(&("entity:hazel", PRESENCE_STATE_KIND, "present"))
                && states.contains(&("entity:hazel", OPERATOR_STATE_KIND, "operator"))
                && edges.contains(PRESENCE_EDGE)
                && edges.contains(OPERATOR_EDGE),
            &[PRESENCE_EDGE.into(), OPERATOR_EDGE.into()],
        ),
        outcome(
            "kai_cooperates_with_prior_knowledge_and_trust",
            beliefs.contains(KAI_KNOWS_BELIEF)
                && beliefs.contains(KAI_TRUSTS_BELIEF)
                && added.contains(COOPERATION_CONSTRAINT)
                && edges.contains(COOPERATION_EDGE),
            &[KAI_KNOWS_BELIEF.into(), KAI_TRUSTS_BELIEF.into()],
        ),
        outcome(
            "possession_based_suspicion_shifts_to_hazel",
            fixed.contains(ORIGINAL_CONSTRAINTS[0])
                && beliefs.contains(SILAS_SUSPICION_BELIEF)
                && added.contains(SUSPICION_CONSTRAINT)
                && edges.contains(SUSPICION_EDGE),
            &[SUSPICION_EDGE.into()],
        ),
        outcome(
            "duplicate_key_claim_is_a_false_rumor_not_identity_uncertainty",
            identity.is_some_and(|rule| {
                rule.object_id == KEY_OBJECT
                    && rule.unique_identity
                    && rule.duplicate_claim_status == DuplicateClaimStatus::FalseRumor
            }) && beliefs.contains(DUPLICATE_RUMOR_BELIEF)
                && added.contains(FALSE_RUMOR_CONSTRAINT)
                && edges.contains(FALSE_RUMOR_EDGE),
            &[OBJECT_RULE_ID.into(), DUPLICATE_RUMOR_BELIEF.into()],
        ),
    ]
}

fn outcome(
    outcome_id: &str,
    satisfied: bool,
    evidence_ids: &[CompactString],
) -> ShadowOutcomeValidation {
    ShadowOutcomeValidation {
        outcome_id: outcome_id.into(),
        satisfied,
        evidence_ids: evidence_ids.to_vec(),
    }
}

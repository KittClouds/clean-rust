use crate::model::{
    AffineCorrespondence, CandidateKey, CandidatePair, ComparabilityStatus, ContextAnchor,
    LawProof, MatchVerdict, MatchingDisposition, ObservableRule, ProtectedEvent, Side,
    TransitionOutcome,
};
use hashbrown::HashMap;

pub const ARCHITECTURE_ID: &str = "THETA_STAR_RELATIVE_TOKEN_AFFINE_ROLE_FIBER_ARCHITECTURE_V1";
pub const COUPLING_ID: &str = "RELATIVE_COMPLETED_BAR_COUPLING_V1";
pub const CORRESPONDENCE_ID: &str = "AFFINE_PRICE_TIME_STRUCTURAL_GENEALOGY_V1";

pub fn observable_rules() -> Vec<ObservableRule> {
    use MatchingDisposition::*;
    [
        (
            "COB_LIFECYCLE_STATE",
            SemanticClassEquality,
            "LIFECYCLE_CLASS",
            "M_Q",
        ),
        (
            "COB_TRANSITION_ORDINAL",
            OrderedRelationalMatch,
            "EXACT_CAUSAL_ORDINAL",
            "M_DELTA",
        ),
        (
            "COB_AUTHORITATIVE_TIME",
            TemporalCorrespondence,
            "AFFINE_SEMANTIC_TIME",
            "M_T",
        ),
        (
            "COB_UPPER_CANDIDATE_GENEALOGY",
            RelationalIsomorphism,
            "UPPER_ORDERED_ALPHA_ISOMORPHISM",
            "M_G",
        ),
        (
            "COB_LOWER_CANDIDATE_GENEALOGY",
            RelationalIsomorphism,
            "LOWER_ORDERED_ALPHA_ISOMORPHISM",
            "M_G",
        ),
        (
            "COB_RUNNING_EXTREME_GEOMETRY",
            RoleCorrespondence,
            "AFFINE_PRICE_BY_SIDE",
            "M_R",
        ),
        (
            "COB_COMMITTED_CLOSE",
            RoleCorrespondence,
            "AFFINE_PRICE",
            "M_R",
        ),
        (
            "COB_GIVEBACK_GEOMETRY",
            LiteralSemanticEquality,
            "TRANSLATION_INVARIANT_TICK_MAGNITUDE",
            "M_R",
        ),
        (
            "COB_RANGE_LOCATION_STATE",
            SemanticClassEquality,
            "PER_K_LOCATION_CLASS",
            "M_Q",
        ),
        (
            "COB_RANGE_EXTENSION_GEOMETRY",
            LiteralSemanticEquality,
            "PER_K_TRANSLATION_INVARIANT_EXTENSION",
            "M_R",
        ),
        (
            "COB_COVERAGE_STATE",
            SemanticClassEquality,
            "COVERAGE_CLASS",
            "M_Q",
        ),
        (
            "COB_SESSION_TIME_CONTEXT",
            TemporalCorrespondence,
            "AFFINE_SESSION_TIME_WITH_EXACT_DURATION_CADENCE",
            "M_C",
        ),
        (
            "COB_PRICE_UNIT_CONTEXT",
            LiteralSemanticEquality,
            "EXACT_PRICE_SCALE",
            "M_C",
        ),
        (
            "COB_TIME_RESOLUTION_CONTEXT",
            LiteralSemanticEquality,
            "EXACT_SOURCE_AND_STORAGE_RESOLUTION",
            "M_C",
        ),
        (
            "COB_RANGE_CONTEXT",
            CouplingRelativeMatch,
            "PER_K_AFFINE_RAIL_AND_FREEZE_CORRESPONDENCE",
            "M_C",
        ),
        (
            "COB_INPUT_AUTHORITY_CLASS",
            SemanticClassEquality,
            "INPUT_AUTHORITY_CLASS",
            "M_DELTA",
        ),
        (
            "COB_PRESENTED_BAR_GEOMETRY",
            CouplingRelativeMatch,
            "COMMON_RELATIVE_TOKEN_REALIZATION",
            "LAMBDA",
        ),
        (
            "COB_OBSERVATION_COMMIT_EVENT",
            OrderedRelationalMatch,
            "ORDERED_COMMIT_PAYLOAD_MATCH",
            "M_DELTA",
        ),
        (
            "COB_CANDIDATE_RENEWAL_EVENT_ORDER",
            OrderedRelationalMatch,
            "ORDERED_GENEALOGY_EVENT_MATCH",
            "M_G",
        ),
        (
            "COB_LOCATION_TRANSITION_EVENT_ORDER",
            OrderedRelationalMatch,
            "ORDERED_PER_K_LOCATION_EVENT_MATCH",
            "M_DELTA",
        ),
        (
            "COB_TRANSITION_RESULT_CLASS",
            SemanticClassEquality,
            "APPLIED_OR_REJECTED_REASON_CLASS",
            "M_DELTA",
        ),
        (
            "COB_ORDERED_TRACE_COORDINATES",
            OrderedRelationalMatch,
            "EXPERIMENT_CAUSAL_EMISSION_ORDINALS",
            "M_DELTA",
        ),
        (
            "COB_CAUSAL_TRANSITION_LAW",
            RelationalIsomorphism,
            "SEALED_G1_TRANSDUCTION_LAW_IDENTITY",
            "M_DELTA",
        ),
    ]
    .into_iter()
    .map(|(id, disposition, rule, component)| ObservableRule {
        observable_id: id.into(),
        disposition,
        rule_id: rule.into(),
        literal_identity_required: matches!(disposition, LiteralSemanticEquality),
        correspondence_component: component.into(),
    })
    .collect()
}

pub fn instantiate_correspondence(
    left: &ContextAnchor,
    right: &ContextAnchor,
) -> Result<AffineCorrespondence, &'static str> {
    if left.fiber != right.fiber {
        return Err("CONTEXT_FIBER_MISMATCH");
    }
    Ok(AffineCorrespondence {
        price_delta_ticks: right
            .price_origin_ticks
            .checked_sub(left.price_origin_ticks)
            .ok_or("PRICE_DELTA_OVERFLOW")?,
        time_delta_ns: right
            .time_origin_ns
            .checked_sub(left.time_origin_ns)
            .ok_or("TIME_DELTA_OVERFLOW")?,
        candidate_pairs: Vec::new(),
        architecture_id: CORRESPONDENCE_ID.into(),
    })
}

pub fn compare_price(left: i64, right: i64, correspondence: &AffineCorrespondence) -> bool {
    left.checked_add(correspondence.price_delta_ticks) == Some(right)
}

pub fn compare_time(left: i64, right: i64, correspondence: &AffineCorrespondence) -> bool {
    left.checked_add(correspondence.time_delta_ns) == Some(right)
}

pub fn compare_outcome(left: &TransitionOutcome, right: &TransitionOutcome) -> MatchVerdict {
    match (left, right) {
        (TransitionOutcome::Applied, TransitionOutcome::Applied) => MatchVerdict::Match,
        (TransitionOutcome::Rejected(a), TransitionOutcome::Rejected(b)) if a == b => {
            MatchVerdict::Match
        }
        (TransitionOutcome::PrePresentationInvalid(_), _)
        | (_, TransitionOutcome::PrePresentationInvalid(_)) => {
            MatchVerdict::PairNotComparableForThisToken
        }
        _ => MatchVerdict::BehavioralMismatch,
    }
}

pub fn compare_ordered_events(
    left: &[ProtectedEvent],
    right: &[ProtectedEvent],
    correspondence: &AffineCorrespondence,
) -> bool {
    left.len() == right.len()
        && left.iter().zip(right).all(|(a, b)| {
            a.kind == b.kind
                && a.side == b.side
                && a.experiment_ordinal == b.experiment_ordinal
                && a.causal_ordinal == b.causal_ordinal
                && a.emission_ordinal == b.emission_ordinal
                && compare_time(a.semantic_time_ns, b.semantic_time_ns, correspondence)
                && candidate_ids_match(a, b, correspondence)
        })
}

fn candidate_ids_match(
    left: &ProtectedEvent,
    right: &ProtectedEvent,
    correspondence: &AffineCorrespondence,
) -> bool {
    match (left.side, left.candidate_id, right.side, right.candidate_id) {
        (None, None, None, None) => true,
        (Some(ls), Some(li), Some(rs), Some(ri)) if ls == rs => {
            correspondence.candidate_pairs.iter().any(|pair| {
                pair.left == CandidateKey { side: ls, id: li }
                    && pair.right == CandidateKey { side: rs, id: ri }
            })
        }
        _ => false,
    }
}

pub fn classify_comparability(
    same_fiber: bool,
    continuation_languages_consonant: bool,
    epsilon_only: bool,
    start_reachability_proven: bool,
) -> ComparabilityStatus {
    if !same_fiber {
        ComparabilityStatus::ContextIncompatible
    } else if !continuation_languages_consonant {
        ComparabilityStatus::CouplingUnavailable
    } else if !start_reachability_proven {
        ComparabilityStatus::ConditionalOnReachability
    } else if epsilon_only {
        ComparabilityStatus::EpsilonOnly
    } else {
        ComparabilityStatus::Comparable
    }
}

pub struct CorrespondenceTransaction {
    committed: HashMap<CandidateKey, CandidateKey>,
    staged: Vec<CandidatePair>,
}

impl CorrespondenceTransaction {
    pub fn new(existing: &[CandidatePair]) -> Result<Self, &'static str> {
        let mut committed = HashMap::with_capacity(existing.len());
        for pair in existing {
            if committed.insert(pair.left, pair.right).is_some() {
                return Err("DUPLICATE_LEFT_CORRESPONDENCE");
            }
        }
        Ok(Self {
            committed,
            staged: Vec::new(),
        })
    }

    pub fn stage(&mut self, pair: CandidatePair) -> Result<(), &'static str> {
        if let Some(current) = self.committed.get(&pair.left) {
            return if *current == pair.right {
                Ok(())
            } else {
                Err("CORRESPONDENCE_BACKPATCH_FORBIDDEN")
            };
        }
        if self.staged.iter().any(|x| {
            x.left == pair.left && x.right != pair.right
                || x.right == pair.right && x.left != pair.left
        }) {
            return Err("STAGED_CORRESPONDENCE_NOT_BIJECTIVE");
        }
        self.staged.push(pair);
        Ok(())
    }

    pub fn finish(mut self, protected_match: bool) -> Result<Vec<CandidatePair>, &'static str> {
        if !protected_match {
            return Err("CORRESPONDENCE_EXTENSION_NOT_COMMITTED_AFTER_MISMATCH");
        }
        for pair in self.staged.drain(..) {
            self.committed.insert(pair.left, pair.right);
        }
        let mut pairs = self
            .committed
            .into_iter()
            .map(|(left, right)| CandidatePair { left, right })
            .collect::<Vec<_>>();
        pairs.sort_unstable_by_key(|pair| (pair.left.side as u8, pair.left.id));
        Ok(pairs)
    }
}

pub fn relation_law_proofs() -> Vec<LawProof> {
    vec![
        proof(
            "REFLEXIVITY",
            vec![
                "identity context translation is (0,0)",
                "candidate alpha-map is identity",
                "relative-token realization is identical under self-comparison",
                "each observable matching rule is reflexive",
            ],
        ),
        proof(
            "SYMMETRY",
            vec![
                "affine translations invert by negation",
                "candidate bijection inverts",
                "common neutral token language is side-swap invariant",
                "each observable rule is symmetric under inverse correspondence",
            ],
        ),
        proof(
            "TRANSITIVITY",
            vec![
                "context translations compose by integer addition",
                "candidate bijections compose by relational composition",
                "couplings compose through common neutral-token refinement, not raw stimulus composition",
                "continuation-language consonance is transitive within each fiber",
                "ordered observable matches compose componentwise",
            ],
        ),
        proof(
            "DOMAIN_CLOSURE",
            vec![
                "fiber key equality is closed under identity, inversion and composition",
                "continuation-language consonance is an equality relation on true unilateral token languages",
            ],
        ),
        proof(
            "COMPARABILITY_REFLEXIVE",
            vec!["every admitted prefix shares its own fiber and unilateral token language"],
        ),
        proof(
            "COMPARABILITY_SYMMETRIC",
            vec!["fiber equality and token-language equality are symmetric"],
        ),
        proof(
            "COMPARABILITY_TRANSITIVE",
            vec!["fiber equality and token-language equality are transitive"],
        ),
    ]
}

fn proof(law: &str, derivation: Vec<&str>) -> LawProof {
    LawProof {
        law: law.into(),
        status: "PROVEN_WITHIN_DECLARED_COMPARISON_FIBER".into(),
        domain: "D_THETA_STAR_GAMMA".into(),
        derivation: derivation.into_iter().map(str::to_owned).collect(),
        fixture_is_proof: false,
    }
}

pub fn candidate(side: Side, id: u32) -> CandidateKey {
    CandidateKey { side, id }
}

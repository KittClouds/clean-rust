use crate::model::{CarryStatus, ElementRole, Role, Surface};
use crate::registry::e;

pub(crate) fn emission_elements() -> Vec<ElementRole> {
    use CarryStatus as C;
    use Role as R;
    use Surface as S;
    [
        (
            "emission.commit.source_row_id",
            vec![R::DerivedEmission, R::ProvenanceP],
            "input.source_row_id",
            "ObservationCommit.source_row_id",
        ),
        (
            "emission.commit.knowledge_time_ns",
            vec![R::DerivedEmission, R::TimeBearing],
            "input.knowledge_time_ns",
            "ObservationCommit.knowledge_time_ns",
        ),
        (
            "emission.commit.coverage",
            vec![R::DerivedEmission, R::ControlStateQ],
            "input.coverage",
            "ObservationCommit.coverage",
        ),
        (
            "emission.new_upper.candidate_id",
            vec![R::DerivedEmission, R::IdentityBearing],
            "state.upper.id",
            "NewUpperExtreme.candidate_id",
        ),
        (
            "emission.upper_id_change.prior",
            vec![R::DerivedEmission, R::IdentityBearing],
            "prior state.upper.id",
            "UpperCandidateIdChange.prior",
        ),
        (
            "emission.upper_id_change.current",
            vec![R::DerivedEmission, R::IdentityBearing],
            "next state.upper.id",
            "UpperCandidateIdChange.current",
        ),
        (
            "emission.new_lower.candidate_id",
            vec![R::DerivedEmission, R::IdentityBearing],
            "state.lower.id",
            "NewLowerExtreme.candidate_id",
        ),
        (
            "emission.lower_id_change.prior",
            vec![R::DerivedEmission, R::IdentityBearing],
            "prior state.lower.id",
            "LowerCandidateIdChange.prior",
        ),
        (
            "emission.lower_id_change.current",
            vec![R::DerivedEmission, R::IdentityBearing],
            "next state.lower.id",
            "LowerCandidateIdChange.current",
        ),
        (
            "emission.location.k",
            vec![R::DerivedEmission, R::IdentityBearing, R::ProvenanceP],
            "ordered range identity",
            "LocationTransition.k",
        ),
        (
            "emission.location.prior",
            vec![R::DerivedEmission, R::ControlStateQ],
            "prior state.range_locations",
            "LocationTransition.prior",
        ),
        (
            "emission.location.current",
            vec![R::DerivedEmission, R::ControlStateQ],
            "next state.range_locations",
            "LocationTransition.current",
        ),
        (
            "emission.location.knowledge_time_ns",
            vec![R::DerivedEmission, R::TimeBearing],
            "input.knowledge_time_ns",
            "LocationTransition.knowledge_time_ns",
        ),
    ]
    .into_iter()
    .map(|(id, roles, origin, ancestor)| {
        e(
            id,
            S::Emission,
            &[C::EmissionOnly],
            &roles,
            &[origin],
            "emitted in frozen G1 order when its transition predicate admits it",
            false,
            true,
            ancestor,
        )
    })
    .collect()
}

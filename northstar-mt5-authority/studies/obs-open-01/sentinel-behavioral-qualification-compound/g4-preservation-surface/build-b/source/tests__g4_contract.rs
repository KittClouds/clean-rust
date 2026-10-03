use obs_open_04a_g4::census::execute;
use obs_open_04a_g4::model::{AuthorityMembership, ComparisonStatus, ElementG4Role};
use std::collections::HashSet;

#[test]
fn all_57_elements_are_dispositioned_once() {
    let p = execute().unwrap();
    assert_eq!(p.elements.len(), 57);
    assert_eq!(
        p.elements
            .iter()
            .map(|x| &x.element_id)
            .collect::<HashSet<_>>()
            .len(),
        57
    );
}
#[test]
fn every_in_authority_element_maps_to_named_observable() {
    let p = execute().unwrap();
    assert!(
        p.elements
            .iter()
            .filter(|x| x.authority_membership == AuthorityMembership::InAuthority)
            .all(|x| !x.mapped_observable_ids.is_empty() && x.retention_fidelity.is_some())
    );
}
#[test]
fn every_exclusion_has_affirmative_normative_basis() {
    let p = execute().unwrap();
    let excluded = p
        .elements
        .iter()
        .filter(|x| x.authority_membership == AuthorityMembership::NotInAuthority)
        .collect::<Vec<_>>();
    assert_eq!(excluded.len(), 3);
    assert!(
        excluded
            .iter()
            .all(|x| x.element_g4_role == ElementG4Role::NotInAuthority
                && x.normative_reason.contains("OPAQUE"))
    );
}
#[test]
fn cross_history_comparison_is_never_defined() {
    let p = execute().unwrap();
    assert!(
        p.observables
            .iter()
            .all(|x| x.cross_history_comparison == ComparisonStatus::Deferred)
    );
    assert!(p.elements.iter().all(|x| matches!(
        x.cross_history_comparison,
        ComparisonStatus::Deferred | ComparisonStatus::NotApplicable
    )));
}
#[test]
fn six_carried_not_next_read_measurements_remain_protected() {
    let p = execute().unwrap();
    for id in [
        "state.close_ticks",
        "state.upper_giveback_ticks",
        "state.lower_giveback_ticks",
        "state.upper_extensions_ticks",
        "state.lower_extensions_ticks",
        "state.coverage_complete",
    ] {
        let row = p.elements.iter().find(|x| x.element_id == id).unwrap();
        assert_eq!(row.authority_membership, AuthorityMembership::InAuthority);
    }
}
#[test]
fn candidate_labels_feed_genealogy_not_literal_comparison() {
    let p = execute().unwrap();
    for id in ["state.upper.id", "state.lower.id"] {
        let row = p.elements.iter().find(|x| x.element_id == id).unwrap();
        assert!(row.genealogy_sensitive);
        assert_eq!(row.cross_history_comparison, ComparisonStatus::Deferred);
    }
}

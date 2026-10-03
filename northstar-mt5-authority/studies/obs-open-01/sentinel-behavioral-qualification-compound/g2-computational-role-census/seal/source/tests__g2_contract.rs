use obs_open_04a_g2::census::execute;
use obs_open_04a_g2::model::{CarryStatus, EdgeKind, Role, Surface};
use std::collections::HashSet;

#[test]
fn census_covers_complete_g1_state_surface() {
    let products = execute().unwrap();
    let state = products
        .elements
        .iter()
        .filter(|x| x.surface == Surface::KernelState)
        .collect::<Vec<_>>();
    assert_eq!(state.len(), 21);
    assert!(state.iter().all(|x| !x.roles.is_empty()));
    assert!(
        state
            .iter()
            .all(|x| x.carry_status.contains(&CarryStatus::MutableCarriedState))
    );
}

#[test]
fn guard_arithmetic_collision_is_preserved() {
    let products = execute().unwrap();
    let upper = products
        .elements
        .iter()
        .find(|x| x.element_id == "state.upper.value_ticks")
        .unwrap();
    assert!(upper.roles.contains(&Role::UsedInGuard));
    assert!(upper.roles.contains(&Role::UsedInArithmetic));
    assert!(upper.multi_role_collision);
}

#[test]
fn age_is_piecewise_arithmetic_not_a_guard() {
    let products = execute().unwrap();
    let age = products
        .elements
        .iter()
        .find(|x| x.element_id == "state.upper.age_bars")
        .unwrap();
    assert!(age.roles.contains(&Role::PiecewiseAffineUpdate));
    assert!(!age.roles.contains(&Role::UsedInGuard));
}

#[test]
fn graph_has_every_required_edge_kind() {
    let products = execute().unwrap();
    let kinds = products
        .graph
        .edges
        .iter()
        .map(|x| x.kind)
        .collect::<HashSet<_>>();
    for required in [
        EdgeKind::Reads,
        EdgeKind::Guards,
        EdgeKind::Updates,
        EdgeKind::Derives,
        EdgeKind::Emits,
        EdgeKind::Copies,
        EdgeKind::Resets,
        EdgeKind::Increments,
        EdgeKind::Compares,
    ] {
        assert!(kinds.contains(&required));
    }
    assert_eq!(products.graph.dangling_edge_count, 0);
}

#[test]
fn provenance_only_context_is_not_promoted_to_computation() {
    let products = execute().unwrap();
    let session = products
        .elements
        .iter()
        .find(|x| x.element_id == "context.session_id")
        .unwrap();
    assert!(session.roles.contains(&Role::ProvenanceOnly));
    assert!(!session.roles.contains(&Role::UsedInGuard));
}

#[test]
fn role_census_contains_no_removability_vocabulary() {
    let products = execute().unwrap();
    let text = serde_json::to_string(&products.elements).unwrap();
    for forbidden in ["REDUNDANT", "REMOVABLE", "UNIMPORTANT", "MINIMAL_STATE"] {
        assert!(!text.contains(forbidden));
    }
}

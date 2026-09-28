use super::*;
use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};

fn assert_close(left: f32, right: f32, tol: f32) {
    assert!(
        (left - right).abs() <= tol,
        "expected {left} ~= {right} within {tol}, diff={}",
        (left - right).abs()
    );
}

fn point(v: [f32; 4]) -> HyperboloidPoint {
    HyperboloidPoint::from_tangent(v, 1.0).assert_ok()
}

fn node(id: &str, label: &str, v: [f32; 4]) -> LorentzNode {
    LorentzNode::new(id, label, point(v)).assert_ok()
}

fn fixture_forest() -> LorentzForest {
    let mut forest = LorentzForest::new();
    forest
        .add_tree(LorentzTree::new(
            "identity",
            LorentzTreeKind::Identity,
            "identity",
        ))
        .assert_ok();
    forest
        .add_tree(LorentzTree::new(
            "causal",
            LorentzTreeKind::Causal,
            "causal",
        ))
        .assert_ok();
    forest
        .add_node(node("echo", "Echo", [1.20, 0.0, 0.0, 0.0]))
        .assert_ok();
    forest
        .add_node(node("kai", "Kai", [0.20, 0.0, 0.0, 0.0]))
        .assert_ok();
    forest
        .add_node(node("ruby", "Ruby", [0.55, 0.0, 0.0, 0.0]))
        .assert_ok();
    forest.attach_root("identity", "kai").assert_ok();
    forest
        .attach_child("identity", "kai", "echo", 0)
        .assert_ok();
    forest.attach_root("causal", "kai").assert_ok();
    forest.attach_child("causal", "kai", "ruby", 0).assert_ok();
    forest
}

#[test]
fn origin_and_tangent_map_are_valid_h4_points() {
    let origin = HyperboloidPoint::origin();
    assert_close(lorentz_dot(origin, origin), -1.0, 1e-6);
    assert_eq!(origin.time(), 1.0);

    let p = HyperboloidPoint::from_tangent([1.0, 0.0, 0.0, 0.0], 1.0).assert_ok();
    assert_close(lorentz_dot(p, p), -1.0, 1e-4);
    let d = hyperbolic_distance(origin, p).assert_ok();
    assert_close(d, 1.0, 1e-4);
}

#[test]
fn hyperbolic_distance_is_monotone_with_tangent_radius() {
    let origin = HyperboloidPoint::origin();
    let near = point([0.25, 0.0, 0.0, 0.0]);
    let far = point([1.25, 0.0, 0.0, 0.0]);
    assert!(
        hyperbolic_distance(origin, near).assert_ok()
            < hyperbolic_distance(origin, far).assert_ok()
    );
}

#[test]
fn duplicates_are_rejected() {
    let mut forest = LorentzForest::new();
    forest
        .add_tree(LorentzTree::new(
            "identity",
            LorentzTreeKind::Identity,
            "id",
        ))
        .assert_ok();
    assert!(matches!(
        forest.add_tree(LorentzTree::new(
            "identity",
            LorentzTreeKind::Identity,
            "id"
        )),
        Err(LorentzTreeError::DuplicateTree(_))
    ));
    forest
        .add_node(node("kai", "Kai", [0.0, 0.0, 0.0, 0.0]))
        .assert_ok();
    assert!(matches!(
        forest.add_node(node("kai", "Kai", [0.0, 0.0, 0.0, 0.0])),
        Err(LorentzTreeError::DuplicateNode(_))
    ));
    forest.attach_root("identity", "kai").assert_ok();
    assert!(matches!(
        forest.attach_root("identity", "kai"),
        Err(LorentzTreeError::DuplicateMembership { .. })
    ));
}

#[test]
fn same_node_can_live_in_multiple_trees_without_identity_clone() {
    let forest = fixture_forest();
    let candidates = forest.candidate_refs();
    let kai = candidates
        .iter()
        .filter(|candidate| candidate.node.node_id == "kai")
        .collect::<Vec<_>>();
    assert_eq!(kai.len(), 2);
    assert!(kai.iter().all(|candidate| candidate.has_cross_tree_support));
    assert_eq!(forest.nodes.len(), 3);
}

#[test]
fn child_and_ancestor_traversal_is_deterministic() {
    let forest = fixture_forest();
    let children = forest.children_of("identity", "kai").assert_ok();
    assert_eq!(
        children
            .iter()
            .map(|node| node.node_id.as_str())
            .collect::<Vec<_>>(),
        ["echo"]
    );
    let ancestors = forest.ancestors_of("identity", "echo").assert_ok();
    assert_eq!(
        ancestors
            .iter()
            .map(|node| node.node_id.as_str())
            .collect::<Vec<_>>(),
        ["kai"]
    );

    let index = LorentzForestIndex::from_forest(&forest).assert_ok();
    let indexed_children = index.children_of("identity", "kai").assert_ok();
    assert_eq!(
        indexed_children
            .iter()
            .map(|node| node.node_id.as_str())
            .collect::<Vec<_>>(),
        ["echo"]
    );
}

#[test]
fn ancestor_traversal_rejects_per_tree_cycles() {
    let mut forest = LorentzForest::new();
    forest
        .add_tree(LorentzTree::new(
            "causal",
            LorentzTreeKind::Causal,
            "causal",
        ))
        .assert_ok();
    forest
        .add_node(node("a", "A", [0.1, 0.0, 0.0, 0.0]))
        .assert_ok();
    forest
        .add_node(node("b", "B", [0.2, 0.0, 0.0, 0.0]))
        .assert_ok();
    forest.memberships = BTreeMap::from([
        (
            ("causal".to_owned(), "a".to_owned()),
            LorentzTreeMembership {
                parent_node_id: Some("b".to_owned()),
                ..LorentzTreeMembership::root("causal", "a")
            },
        ),
        (
            ("causal".to_owned(), "b".to_owned()),
            LorentzTreeMembership {
                parent_node_id: Some("a".to_owned()),
                level: 1,
                ..LorentzTreeMembership::root("causal", "b")
            },
        ),
    ]);
    forest.rebuild_indexes();
    assert!(matches!(
        forest.ancestors_of("causal", "a"),
        Err(LorentzTreeError::CycleRejected { .. })
    ));
}

#[test]
fn hierarchy_lane_scoring_prefers_matching_tree_kind() {
    let forest = fixture_forest();
    let query = LorentzTreeQuery::new(point([0.20, 0.0, 0.0, 0.0]))
        .assert_ok()
        .with_tree_kinds(vec![LorentzTreeKind::Causal]);
    let scores = forest
        .rank(&query, LorentzScoreConfig::default())
        .assert_ok();
    assert_eq!(scores[0].tree_id.as_deref(), Some("causal"));
    assert!(scores.iter().any(|score| score.tree_drift_penalty > 0.0));
}

#[test]
fn cross_hierarchy_mode_penalizes_unsupported_nodes() {
    let forest = fixture_forest();
    let query = LorentzTreeQuery::new(point([0.55, 0.0, 0.0, 0.0]))
        .assert_ok()
        .with_tree_kinds(vec![LorentzTreeKind::Causal])
        .with_mode(LorentzQueryMode::CrossHierarchySynthesis);
    let scores = forest
        .rank(&query, LorentzScoreConfig::default())
        .assert_ok();
    let ruby = scores
        .iter()
        .find(|score| score.node_id == "ruby")
        .expect("ruby score");
    assert!(ruby.unsupported_cross_tree_penalty > 0.0);
}

#[test]
fn roaring_index_candidate_filter_is_stable() {
    let forest = fixture_forest();
    let index = LorentzForestIndex::from_forest(&forest).assert_ok();
    let query = LorentzTreeQuery::new(point([0.2, 0.0, 0.0, 0.0]))
        .assert_ok()
        .with_tree_ids(vec!["causal".to_owned()]);
    let pool = index.candidate_pool(&query);
    assert_eq!(index.candidate_ids(&pool), ["causal:kai", "causal:ruby"]);
    assert_eq!(index.members_at_level(1).len(), 2);
}

#[test]
fn indexed_ranking_matches_direct_forest_ranking() {
    let forest = fixture_forest();
    let index = LorentzForestIndex::from_forest(&forest).assert_ok();
    let query = LorentzTreeQuery::new(point([0.20, 0.0, 0.0, 0.0])).assert_ok();
    let direct = forest
        .rank(&query, LorentzScoreConfig::default())
        .assert_ok();
    let indexed = index
        .rank(&query, LorentzScoreConfig::default())
        .assert_ok();
    assert_eq!(
        direct
            .iter()
            .map(|score| &score.candidate_id)
            .collect::<Vec<_>>(),
        indexed
            .iter()
            .map(|score| &score.candidate_id)
            .collect::<Vec<_>>()
    );
}

#[test]
fn mmap_roundtrip_preserves_index_query_behavior() {
    let forest = fixture_forest();
    let index = LorentzForestIndex::from_forest(&forest).assert_ok();
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("lorentz-forest-{stamp}.bin"));
    MmapLorentzForestIndex::write_index_to_file(&index, &path).assert_ok();
    let mmap = MmapLorentzForestIndex::open(&path).assert_ok();
    let query = LorentzTreeQuery::new(point([0.20, 0.0, 0.0, 0.0])).assert_ok();
    let direct = index
        .rank(&query, LorentzScoreConfig::default())
        .assert_ok();
    let mapped = mmap.rank(&query, LorentzScoreConfig::default()).assert_ok();
    assert_eq!(
        direct
            .iter()
            .map(|score| &score.candidate_id)
            .collect::<Vec<_>>(),
        mapped
            .iter()
            .map(|score| &score.candidate_id)
            .collect::<Vec<_>>()
    );
    assert_eq!(
        mmap.index()
            .children_of("causal", "kai")
            .assert_ok()
            .iter()
            .map(|node| node.node_id.as_str())
            .collect::<Vec<_>>(),
        ["ruby"]
    );
    let _ = std::fs::remove_file(path);
}

trait AssertOk<T> {
    fn assert_ok(self) -> T;
}

impl<T, E: core::fmt::Debug> AssertOk<T> for Result<T, E> {
    fn assert_ok(self) -> T {
        match self {
            Ok(value) => value,
            Err(error) => panic!("expected Ok(..), got Err({error:?})"),
        }
    }
}

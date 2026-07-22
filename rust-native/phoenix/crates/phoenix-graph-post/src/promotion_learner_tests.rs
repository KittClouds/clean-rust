use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Instant;

use phoenix_graph_kernel::{GraphProposalFeatures, KernelMutationBatch};
use phoenix_semantic_v2::{
    SemanticCandidateStatus, SemanticEdgeFamily, SemanticGraphEdgeCandidate, SemanticGraphNodeKind,
    SemanticGraphNodeRecord, SemanticGraphScopeSidecar,
};

use crate::promotion_learner::{
    reset_default_promotion_model_cache_for_tests, GraphPromotionLinearModel,
    GraphPromotionTrainingConfig, GraphPromotionTrainingExample, MmapGraphPromotionModel,
};
use crate::promotion_receipts::build_semantic_proposal_receipt;

static MODEL_ENV_LOCK: Mutex<()> = Mutex::new(());

#[test]
fn ftrl_model_learns_support_without_learning_contradiction_as_truth() {
    let examples = training_examples();
    let model = GraphPromotionLinearModel::fit_ftrl(
        "promotion-unit-v1",
        &examples,
        GraphPromotionTrainingConfig::default(),
    )
    .expect("fit model");
    let supported = model.score_millis(features(900, 820, 80, 1));
    let contradicted = model.score_millis(features(900, 100, 900, -1));
    let weak = model.score_millis(features(300, 0, 0, 0));
    assert!(
        supported > contradicted + 250,
        "{supported} vs {contradicted}"
    );
    assert!(supported > weak + 150, "{supported} vs {weak}");
}

#[test]
fn immutable_mmap_artifact_preserves_scores() {
    let path = temp_path("artifact");
    let model = GraphPromotionLinearModel::fit_ftrl(
        "promotion-mmap-v1",
        &training_examples(),
        GraphPromotionTrainingConfig::default(),
    )
    .expect("fit model");
    model.write_immutable(&path).expect("write model");
    let mapped = MmapGraphPromotionModel::open(&path).expect("open mmap model");
    for value in [
        features(910, 850, 40, 1),
        features(500, 420, 430, 0),
        features(820, 90, 920, -1),
    ] {
        assert_eq!(
            model.score_millis(value),
            mapped.model().score_millis(value)
        );
    }
    let _ = fs::remove_file(path);
}

#[test]
fn simd_shadow_scoring_stays_bounded_for_192_candidates() {
    let model = GraphPromotionLinearModel::fit_ftrl(
        "promotion-perf-v1",
        &training_examples(),
        GraphPromotionTrainingConfig::default(),
    )
    .expect("fit model");
    let candidates = (0..192)
        .map(|index| {
            features(
                400 + (index % 550) as i16,
                (index * 7 % 1000) as i16,
                (index * 11 % 1000) as i16,
                if index % 2 == 0 { 1 } else { 0 },
            )
        })
        .collect::<Vec<_>>();
    let started = Instant::now();
    let checksum = candidates
        .iter()
        .map(|features| model.score_millis(*features) as u64)
        .sum::<u64>();
    let elapsed = started.elapsed();
    eprintln!("promotion SIMD scoring: 192 candidates in {elapsed:?}");
    assert!(checksum > 0);
    assert!(elapsed.as_millis() < 20, "scoring took {elapsed:?}");
}

#[test]
fn deleting_default_model_returns_receipts_to_feature_only_behavior() {
    let _guard = MODEL_ENV_LOCK.lock().expect("model env lock");
    let path = temp_path("delete-feature-only");
    let model = GraphPromotionLinearModel::fit_ftrl(
        "promotion-delete-v1",
        &training_examples(),
        GraphPromotionTrainingConfig::default(),
    )
    .expect("fit model");
    model.write_immutable(&path).expect("write model");
    std::env::set_var("PHOENIX_GRAPH_PROMOTION_MODEL_PATH", &path);
    reset_default_promotion_model_cache_for_tests();

    let scored = build_semantic_proposal_receipt(&sidecar())
        .expect("build scored receipt")
        .expect("scored receipt");
    assert_eq!(scored.model_id.as_deref(), Some("promotion-delete-v1"));
    assert!(scored.proposals[0].shadow_score_millis.is_some());

    fs::remove_file(&path).expect("delete model");
    reset_default_promotion_model_cache_for_tests();
    let feature_only = build_semantic_proposal_receipt(&sidecar())
        .expect("build feature-only receipt")
        .expect("feature-only receipt");
    assert_eq!(feature_only.model_id, None);
    assert_eq!(feature_only.proposals[0].shadow_score_millis, None);
    std::env::remove_var("PHOENIX_GRAPH_PROMOTION_MODEL_PATH");
    reset_default_promotion_model_cache_for_tests();
}

fn training_examples() -> Vec<GraphPromotionTrainingExample> {
    let mut examples = Vec::new();
    for index in 0..64 {
        examples.push(GraphPromotionTrainingExample {
            features: features(760 + (index % 200) as i16, 800, 60, 1),
            label: true,
            weight: 1.0,
        });
        examples.push(GraphPromotionTrainingExample {
            features: features(720 + (index % 220) as i16, 80, 850, -1),
            label: false,
            weight: 1.0,
        });
        examples.push(GraphPromotionTrainingExample {
            features: features(220 + (index % 250) as i16, 0, 0, 0),
            label: false,
            weight: 0.8,
        });
    }
    examples
}

fn features(score: i16, support: i16, contradiction: i16, reviewed: i16) -> GraphProposalFeatures {
    GraphProposalFeatures([
        score,
        score,
        support,
        contradiction,
        support.saturating_sub(contradiction),
        400,
        250,
        score.saturating_sub(540),
        1000,
        1000,
        0,
        if reviewed > 0 { 1000 } else { 0 },
        if reviewed < 0 { 1000 } else { 0 },
        0,
        0,
        if support > 0 { 1000 } else { 0 },
    ])
}

fn temp_path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "phoenix-promotion-model-{name}-{}-{}.bin",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ))
}

fn sidecar() -> SemanticGraphScopeSidecar {
    SemanticGraphScopeSidecar {
        scope_key: "scope-model-delete".to_owned(),
        updated_at: 42,
        generation: 42,
        candidate_nodes: vec![
            SemanticGraphNodeRecord {
                node_id: "semantic-unit::state::1".to_owned(),
                node_kind: SemanticGraphNodeKind::State,
                truth_plane: Some("world".to_owned()),
                ..Default::default()
            },
            SemanticGraphNodeRecord {
                node_id: "semantic-unit::state::2".to_owned(),
                node_kind: SemanticGraphNodeKind::State,
                truth_plane: Some("world".to_owned()),
                ..Default::default()
            },
        ],
        candidate_edges: vec![SemanticGraphEdgeCandidate {
            edge_id: "semantic-unit::state::1:semantic-unit::state::2".to_owned(),
            family: SemanticEdgeFamily::StateSupport,
            source_node_id: "semantic-unit::state::1".to_owned(),
            source_kind: SemanticGraphNodeKind::State,
            target_node_id: "semantic-unit::state::2".to_owned(),
            target_kind: SemanticGraphNodeKind::State,
            candidate_status: SemanticCandidateStatus::ReviewedSupport,
            ..Default::default()
        }],
        candidate_graph_batch: KernelMutationBatch::default(),
        ..Default::default()
    }
}

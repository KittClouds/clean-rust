use super::*;
use std::time::Instant;

fn row(query: u32, candidate: u32, label: bool, split: ResearchSplit) -> DerivedFeatureRow {
    DerivedFeatureRow {
        positive_index: query,
        candidate,
        split,
        label,
        features: [0.0; 16],
    }
}

#[test]
fn filtered_metrics_use_average_rank_and_fractional_hits_for_ties() {
    let rows = vec![
        row(1, 10, true, ResearchSplit::Validation),
        row(1, 11, false, ResearchSplit::Validation),
        row(1, 12, false, ResearchSplit::Validation),
    ];
    let metrics = evaluate_ranking_scores(&rows, &[0.5, 0.5, 0.1], ResearchSplit::Validation)
        .expect("ranking")
        .expect("validation metrics");
    assert!((metrics.mean_reciprocal_rank - (2.0 / 3.0)).abs() < 1.0e-12);
    assert_eq!(metrics.hits_at_1, 0.5);
    assert_eq!(metrics.hits_at_3, 1.0);
    assert_eq!(metrics.hits_at_10, 1.0);
}

#[test]
fn ranking_rejects_invalid_groups_and_nonfinite_framework_scores() {
    let rows = vec![
        row(1, 10, true, ResearchSplit::Validation),
        row(1, 11, true, ResearchSplit::Validation),
    ];
    assert!(matches!(
        evaluate_ranking_scores(&rows, &[0.5, 0.4], ResearchSplit::Validation),
        Err(RankingEvaluationError::InvalidGroup)
    ));
    assert!(matches!(
        evaluate_ranking_scores(&rows, &[f32::NAN, 0.4], ResearchSplit::Validation),
        Err(RankingEvaluationError::NonFiniteScore)
    ));
}

#[test]
fn structural_ladder_selects_on_validation_and_locks_losing_tests() {
    let mut source = crate::tests::evaluation_snapshot();
    let find = |id: &str| {
        source
            .nodes
            .iter()
            .position(|node| node.id == id)
            .expect("fixture node") as u32
    };
    let a = find("a");
    let b = find("b");
    let c = find("c");
    let d = find("d");
    for node in [a, b, c] {
        source.nodes[node as usize].available_at_ms = 80;
        source.nodes[node as usize].split = ResearchSplit::Train;
    }
    source.nodes.push(ResearchNode {
        id: "e".into(),
        kind: "entity".into(),
        authority: ResearchAuthority::Asserted,
        split: ResearchSplit::Validation,
        available_at_ms: 140,
        source_generation: 9,
    });
    source.edges = vec![
        ResearchEdge {
            source: a,
            target: b,
            relation: "knows".into(),
            authority: ResearchAuthority::Asserted,
            split: ResearchSplit::Train,
            available_at_ms: 90,
            weight: 1.0,
        },
        ResearchEdge {
            source: a,
            target: c,
            relation: "knows".into(),
            authority: ResearchAuthority::Asserted,
            split: ResearchSplit::Validation,
            available_at_ms: 150,
            weight: 1.0,
        },
        ResearchEdge {
            source: c,
            target: d,
            relation: "knows".into(),
            authority: ResearchAuthority::Asserted,
            split: ResearchSplit::Test,
            available_at_ms: 260,
            weight: 1.0,
        },
    ];
    let incidence = source.incidences[0].clone();
    source.nodes[incidence.hyperedge as usize].available_at_ms = 80;
    source.nodes[incidence.hyperedge as usize].split = ResearchSplit::Train;
    source.incidences = [
        ResearchSplit::Train,
        ResearchSplit::Validation,
        ResearchSplit::Test,
    ]
    .into_iter()
    .map(|split| ResearchIncidence {
        split,
        ..incidence.clone()
    })
    .collect();
    source.dataset_id = "b3-ranking-fixture".into();
    let tensors = tensorize_frozen_graph(
        &source,
        TensorizationPolicy {
            negatives_per_asserted_edge: 2,
        },
    )
    .expect("tensorize ranking fixture");
    let protocol =
        certify_evaluation_protocol(&source, &tensors, crate::tests::evaluation_policy(&source))
            .expect("protocol");
    let features = derive_train_topology_features(
        &source,
        &tensors,
        &protocol,
        TrainTopologyFeaturePolicy {
            incidence_negatives_per_positive: 2,
        },
    )
    .expect("features");
    let report = run_structural_ranking_baselines(&features).expect("ranking baselines");
    for task in [&report.link_prediction, &report.hyperedge_role_completion] {
        let selected = task.selected_family.expect("selected family");
        assert!(task
            .runs
            .iter()
            .all(|run| { run.held_out_test.is_some() == (run.family == selected) }));
    }
    let directory = tempfile::tempdir().expect("ranking directory");
    let path = RankingEvaluationBundle::write(&report, directory.path()).expect("write report");
    assert!(path.report.exists());
    assert_eq!(
        path,
        RankingEvaluationBundle::write(&report, directory.path()).expect("reuse report")
    );
}

#[test]
fn evaluates_twenty_thousand_filtered_queries_within_gate() {
    let mut rows = Vec::with_capacity(40_000);
    let mut scores = Vec::with_capacity(40_000);
    for query in 0..20_000 {
        rows.push(row(query, query * 2, true, ResearchSplit::Validation));
        rows.push(row(query, query * 2 + 1, false, ResearchSplit::Validation));
        scores.extend_from_slice(&[1.0, 0.0]);
    }
    let started = Instant::now();
    let metrics = evaluate_ranking_scores(&rows, &scores, ResearchSplit::Validation)
        .expect("ranking scale")
        .expect("metrics");
    let elapsed = started.elapsed();
    eprintln!(
        "ranking scale: {} queries, {} candidates, {:.3}s",
        metrics.queries,
        metrics.candidates,
        elapsed.as_secs_f32()
    );
    assert_eq!(metrics.mean_reciprocal_rank, 1.0);
    assert!(elapsed.as_secs_f32() < 2.0);
}

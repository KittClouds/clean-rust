use super::*;
use crate::tests::{evaluation_policy, evaluation_snapshot};
use compact_str::format_compact;
use std::time::Instant;

#[test]
fn derives_leave_one_out_features_and_mmaps_immutable_artifact() {
    let mut source = evaluation_snapshot();
    source.edges[0].available_at_ms = 90;
    source.edges[0].split = ResearchSplit::Train;
    for node in [source.edges[0].source, source.edges[0].target] {
        source.nodes[node as usize].available_at_ms = 80;
        source.nodes[node as usize].split = ResearchSplit::Train;
    }
    for row in &mut source.incidences {
        row.split = ResearchSplit::Train;
        source.nodes[row.hyperedge as usize].available_at_ms = 80;
        source.nodes[row.hyperedge as usize].split = ResearchSplit::Train;
    }
    source.dataset_id = "b3-topology-fixture".into();
    let tensors = tensorize_frozen_graph(
        &source,
        TensorizationPolicy {
            negatives_per_asserted_edge: 2,
        },
    )
    .expect("tensorize topology fixture");
    let protocol = certify_evaluation_protocol(&source, &tensors, evaluation_policy(&source))
        .expect("certify evaluation");
    let first = derive_train_topology_features(
        &source,
        &tensors,
        &protocol,
        TrainTopologyFeaturePolicy {
            incidence_negatives_per_positive: 2,
        },
    )
    .expect("derive topology features");
    let second = derive_train_topology_features(
        &source,
        &tensors,
        &protocol,
        TrainTopologyFeaturePolicy {
            incidence_negatives_per_positive: 2,
        },
    )
    .expect("repeat derivation");
    assert_eq!(first, second);
    assert!(first.derivation_id.starts_with("b3-"));
    assert_eq!(first.audit.fit_edges, 1);
    assert!(first.audit.train_only && first.audit.leave_one_positive_out);
    let positive = first
        .link_rows
        .iter()
        .find(|row| row.label)
        .expect("positive");
    assert_eq!(positive.features[9], 0.0, "positive edge must be masked");
    let incidence = first
        .incidence_rows
        .iter()
        .find(|row| row.label)
        .expect("incidence positive");
    assert_eq!(
        incidence.features[0], 0.0,
        "positive incidence must be masked"
    );

    let directory = tempfile::tempdir().expect("topology directory");
    let paths = TrainTopologyFeatureBundle::write(&first, directory.path()).expect("write");
    let mapped = TrainTopologyFeatureMapped::open(&paths.manifest).expect("mmap");
    assert_eq!(
        mapped.link_rows().expect("links").len(),
        first.link_rows.len()
    );
    assert_eq!(
        mapped.incidence_rows().expect("incidences").len(),
        first.incidence_rows.len()
    );
    assert_eq!(
        mapped.link_rows().expect("links")[0].feature(9),
        Some(first.link_rows[0].features[9])
    );
}

#[test]
fn derivation_rejects_protocol_drift() {
    let source = evaluation_snapshot();
    let tensors = tensorize_frozen_graph(
        &source,
        TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
    )
    .expect("tensorize");
    let mut protocol = certify_evaluation_protocol(&source, &tensors, evaluation_policy(&source))
        .expect("certify");
    protocol.split_policy.train_through_ms += 1;
    assert!(matches!(
        derive_train_topology_features(
            &source,
            &tensors,
            &protocol,
            TrainTopologyFeaturePolicy {
                incidence_negatives_per_positive: 1,
            }
        ),
        Err(ResearchEvaluationError::Leakage(
            "evaluation protocol drift"
        ))
    ));
}

#[test]
fn derives_twenty_thousand_edge_topology_within_gate() {
    let mut source = evaluation_snapshot();
    source.nodes = (0..20_001)
        .map(|index| ResearchNode {
            id: format_compact!("scale-node-{index:05}"),
            kind: "entity".into(),
            authority: ResearchAuthority::Asserted,
            split: ResearchSplit::Train,
            available_at_ms: 80,
            source_generation: 9,
        })
        .collect();
    source.edges = (0..20_000)
        .map(|index| ResearchEdge {
            source: index,
            target: index + 1,
            relation: "next".into(),
            authority: ResearchAuthority::Asserted,
            split: ResearchSplit::Train,
            available_at_ms: 90,
            weight: 1.0,
        })
        .collect();
    source.incidences.clear();
    source.dataset_id = "b3-topology-scale".into();
    let tensors = tensorize_frozen_graph(
        &source,
        TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
    )
    .expect("tensorize scale topology");
    let protocol = certify_evaluation_protocol(&source, &tensors, evaluation_policy(&source))
        .expect("certify scale protocol");
    let started = Instant::now();
    let derived = derive_train_topology_features(
        &source,
        &tensors,
        &protocol,
        TrainTopologyFeaturePolicy {
            incidence_negatives_per_positive: 1,
        },
    )
    .expect("derive scale topology");
    let elapsed = started.elapsed();
    eprintln!(
        "topology scale: {} edges, {} rows, {:.3}s",
        source.edges.len(),
        derived.link_rows.len(),
        elapsed.as_secs_f32()
    );
    assert_eq!(derived.audit.fit_edges, 20_000);
    assert!(elapsed.as_secs_f32() < 5.0);
}

use super::*;
use compact_str::{format_compact, CompactString};
use phoenix_graph_kernel::{
    GraphProposalBatchReceipt, GraphProposalFeatures, GraphProposalObservation,
    GraphProposalStatus, GraphTruthAtomKey, KernelBiTemporal, KernelCheckpointData,
    KernelCheckpointMeta, KernelEdge, KernelEdgeType, KernelGraphLayer, KernelGraphSnapshot,
    KernelVertex, KernelVertexId,
};
use phoenix_graph_rebuild::{
    GraphDocumentCompilerHyperedge, GraphDocumentCompilerHyperedgeRole,
    GraphDocumentCompilerSummary,
};
use phoenix_types::{
    GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthKind, GraphTruthPlane,
    GraphTruthSourceGenerationRef,
};
use std::io::{Seek, SeekFrom, Write};
use std::time::Instant;

const SPLIT: TemporalSplitPolicy = TemporalSplitPolicy {
    train_through_ms: 100,
    validation_through_ms: 200,
};

#[test]
fn freeze_is_deterministic_and_keeps_reviewable_hyperedges_candidate_only() {
    let checkpoint = checkpoint();
    let compiler = compiler();
    let input = || FrozenGraphResearchInput {
        checkpoint: &checkpoint,
        commits: &[],
        proposal_receipts: &[],
        document_compiler: Some(&compiler),
        document_compiler_observed_at_ms: Some(220),
        frozen_at_ms: 300,
        split_policy: SPLIT,
    };

    let first = freeze_graph_research_snapshot(input()).expect("freeze");
    let second = freeze_graph_research_snapshot(input()).expect("repeat freeze");

    assert_eq!(first, second);
    assert!(first.dataset_id.starts_with("b3-"));
    assert_eq!(first.edges.len(), 1);
    assert_eq!(first.incidences.len(), 2);
    assert!(first
        .nodes
        .iter()
        .filter(|node| node.id.starts_with("hyperedge:"))
        .all(|node| node.authority == ResearchAuthority::Candidate));
    assert!(first
        .nodes
        .iter()
        .any(|node| node.id.starts_with("candidate-target:")));
    assert!(first
        .incidences
        .iter()
        .all(|row| row.split == ResearchSplit::Test));
}

#[test]
fn mmap_open_rejects_a_single_corrupt_byte() {
    let checkpoint = checkpoint();
    let snapshot = freeze_graph_research_snapshot(FrozenGraphResearchInput {
        checkpoint: &checkpoint,
        commits: &[],
        proposal_receipts: &[],
        document_compiler: None,
        document_compiler_observed_at_ms: None,
        frozen_at_ms: 300,
        split_policy: SPLIT,
    })
    .expect("freeze");
    let directory = tempfile::tempdir().expect("tempdir");
    let paths = FrozenGraphResearchBundle::write(&snapshot, directory.path()).expect("write");
    let mut binary = std::fs::OpenOptions::new()
        .write(true)
        .open(paths.binary)
        .expect("open binary");
    binary.seek(SeekFrom::End(-1)).expect("seek");
    binary.write_all(&[0xff]).expect("corrupt");
    binary.sync_all().expect("sync");

    assert!(matches!(
        FrozenGraphResearchMapped::open(paths.manifest),
        Err(FrozenGraphResearchError::CorruptArtifact("binary digest"))
    ));
}

#[test]
fn freezes_twenty_thousand_nodes_within_the_research_gate() {
    let mut checkpoint = checkpoint();
    checkpoint.snapshot.vertices = (0..20_000)
        .map(|index| {
            vertex(
                &format!("node-{index:05}"),
                80 + (index % 3) as i64 * 70,
                None,
            )
        })
        .collect();
    checkpoint.snapshot.asserted_edges = (0..19_999)
        .map(|index| {
            edge(
                &format!("node-{index:05}"),
                &format!("node-{:05}", index + 1),
                220,
            )
        })
        .collect();
    let started = Instant::now();
    let snapshot = freeze_graph_research_snapshot(FrozenGraphResearchInput {
        checkpoint: &checkpoint,
        commits: &[],
        proposal_receipts: &[],
        document_compiler: None,
        document_compiler_observed_at_ms: None,
        frozen_at_ms: 300,
        split_policy: SPLIT,
    })
    .expect("freeze at scale");
    let tensors = tensorize_frozen_graph(
        &snapshot,
        TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
    )
    .expect("tensorize at scale");

    assert_eq!(snapshot.nodes.len(), 20_000);
    assert_eq!(tensors.coo_sources.len(), 19_999);
    assert_eq!(tensors.csr_row_offsets.len(), 20_001);
    assert_eq!(tensors.negatives.len(), 19_999);
    assert!(started.elapsed().as_secs_f32() < 5.0);
}

#[test]
fn mmap_artifact_round_trips_fixed_width_tables_without_copying() {
    let checkpoint = checkpoint();
    let compiler = compiler();
    let snapshot = freeze_graph_research_snapshot(FrozenGraphResearchInput {
        checkpoint: &checkpoint,
        commits: &[],
        proposal_receipts: &[],
        document_compiler: Some(&compiler),
        document_compiler_observed_at_ms: Some(220),
        frozen_at_ms: 300,
        split_policy: SPLIT,
    })
    .expect("freeze");
    let directory = tempfile::tempdir().expect("tempdir");
    let paths = FrozenGraphResearchBundle::write(&snapshot, directory.path()).expect("write");
    let mapped = FrozenGraphResearchMapped::open(paths.manifest).expect("mmap");
    let nodes = mapped.node_records().expect("nodes");
    let edges = mapped.edge_records().expect("edges");
    let incidences = mapped.incidence_records().expect("incidences");

    assert_eq!(nodes.len(), snapshot.nodes.len());
    assert_eq!(edges.len(), 1);
    assert_eq!(incidences.len(), 2);
    assert_eq!(mapped.node_id(nodes[0]), Some("a"));
    assert_eq!(mapped.edge_relation(edges[0]), Some("knows"));
    assert!(mapped.incidence_role(incidences[0]).is_some());
    assert!(matches!(
        FrozenGraphResearchBundle::write(&snapshot, directory.path()),
        Err(FrozenGraphResearchError::ArtifactExists(_))
    ));
}

#[test]
fn future_graph_rows_fail_closed() {
    let mut checkpoint = checkpoint();
    checkpoint.snapshot.vertices[0].temporal.recorded_at = Some(301);
    let error = freeze_graph_research_snapshot(FrozenGraphResearchInput {
        checkpoint: &checkpoint,
        commits: &[],
        proposal_receipts: &[],
        document_compiler: None,
        document_compiler_observed_at_ms: None,
        frozen_at_ms: 300,
        split_policy: SPLIT,
    })
    .expect_err("future data must fail");
    assert!(matches!(error, FrozenGraphResearchError::FutureGraphData));
}

#[test]
fn unresolved_outcomes_are_not_collapsed_into_negative_labels() {
    let checkpoint = checkpoint();
    let receipt = proposal_receipt();
    let snapshot = freeze_graph_research_snapshot(FrozenGraphResearchInput {
        checkpoint: &checkpoint,
        commits: &[],
        proposal_receipts: &[receipt],
        document_compiler: None,
        document_compiler_observed_at_ms: None,
        frozen_at_ms: 300,
        split_policy: SPLIT,
    })
    .expect("freeze");

    assert_eq!(snapshot.proposals.len(), 1);
    assert_eq!(
        snapshot.proposals[0].label,
        ResearchProposalLabel::Uncommitted
    );
    assert_eq!(snapshot.proposals[0].label_available_at_ms, 300);
    assert_eq!(snapshot.proposals[0].split, ResearchSplit::Test);
}

#[test]
fn tensorization_builds_deterministic_typed_csr_incidence_and_safe_negatives() {
    let source = complete_research_snapshot();
    let policy = TensorizationPolicy {
        negatives_per_asserted_edge: 2,
    };
    let first = tensorize_frozen_graph(&source, policy).expect("tensorize");
    let second = tensorize_frozen_graph(&source, policy).expect("repeat tensorize");

    assert_eq!(first, second);
    assert!(first.tensor_id.starts_with("b3-"));
    assert_eq!(first.csr_row_offsets.len(), first.node_type_ids.len() + 1);
    assert_eq!(
        first.csr_row_offsets.last().copied(),
        Some(first.coo_sources.len() as u64)
    );
    assert_eq!(first.incidence_hyperedges.len(), 2);
    assert_eq!(first.proposal_features.len(), PROPOSAL_FEATURE_DIM);
    assert_eq!(first.proposal_label_observed, vec![false]);
    assert_eq!(first.feature_certificates.len(), PROPOSAL_FEATURE_DIM);
    assert_eq!(first.negatives.len(), 1);
    let negative = &first.negatives[0];
    let positive_target = first.coo_targets[negative.positive_edge as usize];
    assert_eq!(
        first.node_type_ids[negative.target as usize],
        first.node_type_ids[positive_target as usize]
    );
    assert!(
        source.nodes[negative.target as usize].available_at_ms
            <= first.coo_available_at_ms[negative.positive_edge as usize]
    );
    assert_eq!(
        source.nodes[negative.target as usize].authority,
        ResearchAuthority::Asserted
    );
    assert!(
        !first.coo_sources.iter().enumerate().any(|(index, source)| {
            *source == negative.source
                && first.coo_targets[index] == negative.target
                && first.coo_relation_types[index] == negative.relation_type
        })
    );
}

#[test]
fn tensor_artifact_is_mmap_ready_and_rejects_corruption() {
    let tensor = tensorize_frozen_graph(
        &complete_research_snapshot(),
        TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
    )
    .expect("tensorize");
    let directory = tempfile::tempdir().expect("tempdir");
    let paths = FrozenTensorBundle::write(&tensor, directory.path()).expect("write tensor");
    let mapped = FrozenTensorMapped::open(&paths.manifest).expect("mmap tensor");

    assert_eq!(
        mapped.node_type_ids().expect("node types").len(),
        tensor.node_type_ids.len()
    );
    assert_eq!(
        mapped.coo_sources().expect("sources")[0].get(),
        tensor.coo_sources[0]
    );
    assert_eq!(
        mapped
            .csr_row_offsets()
            .expect("csr")
            .last()
            .map(|row| row.get()),
        Some(tensor.coo_sources.len() as u64)
    );
    assert_eq!(
        mapped.negatives().expect("negatives").len(),
        tensor.negatives.len()
    );
    drop(mapped);

    let mut binary = std::fs::OpenOptions::new()
        .write(true)
        .open(paths.binary)
        .expect("open tensor");
    binary.seek(SeekFrom::End(-1)).expect("seek tensor");
    binary.write_all(&[0xfe]).expect("corrupt tensor");
    binary.sync_all().expect("sync tensor");
    assert!(matches!(
        FrozenTensorMapped::open(paths.manifest),
        Err(FrozenGraphResearchError::CorruptArtifact(
            "tensor binary digest"
        ))
    ));
}

#[test]
fn evaluation_protocol_and_baselines_are_deterministic_and_test_locked() {
    let source = evaluation_snapshot();
    let tensors = tensorize_frozen_graph(
        &source,
        TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
    )
    .expect("tensorize evaluation fixture");
    let policy = evaluation_policy(&source);
    let first = certify_evaluation_protocol(&source, &tensors, policy.clone()).expect("certify");
    let second = certify_evaluation_protocol(&source, &tensors, policy.clone()).expect("repeat");
    assert_eq!(first, second);
    assert!(first.protocol_id.starts_with("b3-"));
    assert_eq!(first.seed_certificate.seeds.len(), 3);
    assert_eq!(first.leakage_audit.train_examples, 2);
    assert_eq!(first.leakage_audit.validation_examples, 2);
    assert_eq!(first.leakage_audit.test_examples, 2);

    let report = run_baseline_ladder(&source, &tensors, policy).expect("baseline ladder");
    assert_ne!(report.selected_family, BaselineFamily::PriorHeuristic);
    assert_eq!(report.validation_summaries.len(), 3);
    assert_eq!(report.runs.len(), 9);
    assert!(report
        .runs
        .iter()
        .all(|run| { run.held_out_test.is_some() == (run.family == report.selected_family) }));
    assert_eq!(
        report,
        run_baseline_ladder(&source, &tensors, evaluation_policy(&source)).expect("repeat ladder")
    );
    let directory = tempfile::tempdir().expect("evaluation tempdir");
    let paths = ResearchEvaluationBundle::write(&first, &report, directory.path())
        .expect("write evaluation artifacts");
    assert!(paths.protocol.exists());
    assert!(paths.baselines.exists());
    assert_eq!(
        paths,
        ResearchEvaluationBundle::write(&first, &report, directory.path())
            .expect("content-addressed artifact reuse")
    );
}

#[test]
fn evaluation_fails_closed_on_temporal_or_schema_leakage() {
    let source = evaluation_snapshot();
    let mut tensors = tensorize_frozen_graph(
        &source,
        TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
    )
    .expect("tensorize");
    tensors.proposal_splits[0] = ResearchSplit::Test;
    assert!(matches!(
        certify_evaluation_protocol(&source, &tensors, evaluation_policy(&source)),
        Err(ResearchEvaluationError::Leakage("proposal chronology"))
    ));

    let mut tensors = tensorize_frozen_graph(
        &source,
        TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
    )
    .expect("tensorize");
    tensors.feature_certificates[0].label_free = false;
    assert!(matches!(
        certify_evaluation_protocol(&source, &tensors, evaluation_policy(&source)),
        Err(ResearchEvaluationError::FeatureSchema(_))
    ));
}

#[test]
fn binary_metrics_measure_ranking_probability_and_calibration() {
    let perfect = evaluate_binary_scores(&[false, true], &[0.0, 1.0], 10).expect("metrics");
    assert_eq!(perfect.average_precision, Some(1.0));
    assert_eq!(perfect.roc_auc, Some(1.0));
    assert!(perfect.brier_score < 1.0e-12);
    assert!(perfect.log_loss < 1.0e-6);
    assert!(perfect.expected_calibration_error < 2.0e-7);
}

#[test]
fn evaluates_ten_thousand_proposals_within_the_baseline_gate() {
    let mut source = evaluation_snapshot();
    let schema = source.proposals[0].feature_schema_id.clone();
    source.proposals = (0..10_002)
        .map(|index| {
            let (split, observed_at_ms, label_available_at_ms) = match index % 3 {
                0 => (ResearchSplit::Train, 80, 90),
                1 => (ResearchSplit::Validation, 140, 150),
                _ => (ResearchSplit::Test, 220, 230),
            };
            let positive = (index / 3) % 2 == 0;
            let mut features = [0_i16; PROPOSAL_FEATURE_DIM];
            features[0] = if positive { 1000 } else { -1000 };
            features[1] = (index % 997) as i16;
            ResearchProposal {
                proposal_id: format_compact!("scale-proposal-{index:05}"),
                receipt_id: "scale-receipt".into(),
                feature_schema_id: schema.clone(),
                split,
                label: if positive {
                    ResearchProposalLabel::Active
                } else {
                    ResearchProposalLabel::Retracted
                },
                observed_at_ms,
                label_available_at_ms,
                features,
            }
        })
        .collect();
    source.dataset_id = "b3-evaluation-scale".into();
    let tensors = tensorize_frozen_graph(
        &source,
        TensorizationPolicy {
            negatives_per_asserted_edge: 1,
        },
    )
    .expect("tensorize scale fixture");
    let mut policy = evaluation_policy(&source);
    policy.repeats = 1;
    policy.ftrl.epochs = 4;
    policy.mlp.epochs = 4;
    let started = Instant::now();
    let report = run_baseline_ladder(&source, &tensors, policy).expect("scale baseline ladder");
    let elapsed = started.elapsed();
    eprintln!(
        "baseline scale: {} proposals, 3 families, {:.3}s",
        source.proposals.len(),
        elapsed.as_secs_f32()
    );
    assert_eq!(report.runs.len(), 3);
    assert!(elapsed.as_secs_f32() < 5.0);
}

fn complete_research_snapshot() -> FrozenGraphResearchSnapshot {
    let checkpoint = checkpoint();
    let compiler = compiler();
    let receipt = proposal_receipt();
    freeze_graph_research_snapshot(FrozenGraphResearchInput {
        checkpoint: &checkpoint,
        commits: &[],
        proposal_receipts: &[receipt],
        document_compiler: Some(&compiler),
        document_compiler_observed_at_ms: Some(220),
        frozen_at_ms: 300,
        split_policy: SPLIT,
    })
    .expect("complete research snapshot")
}

fn checkpoint() -> KernelCheckpointData {
    KernelCheckpointData {
        meta: KernelCheckpointMeta {
            checkpoint_id: "checkpoint-9".to_owned(),
            generation: 9,
            source_revision: "revision-9".to_owned(),
            created_at: 150,
        },
        snapshot: KernelGraphSnapshot {
            vertices: vec![
                vertex("b", 150, Some("entity-b")),
                vertex("a", 80, None),
                vertex("c", 80, None),
                vertex("d", 250, None),
            ],
            asserted_edges: vec![edge("a", "b", 210)],
            candidate_edges: Vec::new(),
        },
    }
}

fn edge(source: &str, target: &str, recorded_at: i64) -> KernelEdge {
    KernelEdge {
        source_id: KernelVertexId(source.to_owned()),
        target_id: KernelVertexId(target.to_owned()),
        edge_type: KernelEdgeType("knows".to_owned()),
        weight: 750,
        layer: KernelGraphLayer::Asserted,
        temporal: KernelBiTemporal {
            recorded_at: Some(recorded_at),
            ..KernelBiTemporal::default()
        },
        ..KernelEdge::default()
    }
}

fn vertex(id: &str, recorded_at: i64, entity_id: Option<&str>) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(id.to_owned()),
        kind: "entity".to_owned(),
        weight: 1,
        temporal: KernelBiTemporal {
            recorded_at: Some(recorded_at),
            ..KernelBiTemporal::default()
        },
        entity_id: entity_id.map(str::to_owned),
        ..KernelVertex::default()
    }
}

fn compiler() -> GraphDocumentCompilerSummary {
    GraphDocumentCompilerSummary {
        hyperedges: vec![GraphDocumentCompilerHyperedge {
            id: "gift".into(),
            predicate: "transfer".into(),
            frame: Some("transferPossession".into()),
            roles: vec![
                role("actor", "a", "entity", true),
                role("theme", "key", "mention", false),
            ],
            confidence: 0.9,
            status: "reviewable".into(),
            ..GraphDocumentCompilerHyperedge::default()
        }],
    }
}

fn role(
    role: &str,
    target: &str,
    kind: &str,
    resolved: bool,
) -> GraphDocumentCompilerHyperedgeRole {
    GraphDocumentCompilerHyperedgeRole {
        id: CompactString::new(format!("role:{role}")),
        role: role.into(),
        target_id: target.into(),
        target_kind: kind.into(),
        resolved: Some(resolved),
        ..GraphDocumentCompilerHyperedgeRole::default()
    }
}

fn proposal_receipt() -> GraphProposalBatchReceipt {
    GraphProposalBatchReceipt {
        schema_version: 1,
        receipt_id: "receipt-1".into(),
        scope_key: "scope-1".into(),
        generation: 1,
        created_at: 90,
        compiler_policy: GraphTruthCompilerPolicy {
            compiler_id: "compiler".into(),
            compiler_version: "1".into(),
            policy_id: "policy".into(),
            policy_version: "1".into(),
        },
        source_generations: vec![GraphTruthSourceGenerationRef {
            source_id: "source-1".into(),
            generation: 1,
        }]
        .into(),
        model_id: None,
        proposals: vec![GraphProposalObservation {
            proposal_id: "proposal-1".into(),
            atom: GraphTruthAtomKey::Vertex {
                vertex_id: "candidate-1".into(),
            },
            family: "semantic".into(),
            source_kind: "fact".into(),
            target_kind: "entity".into(),
            truth: GraphTruthDescriptor {
                kind: GraphTruthKind::Semantic,
                plane: Some(GraphTruthPlane::Hypothetical),
            },
            status: GraphProposalStatus::Generated,
            evidence_refs: Default::default(),
            features: GraphProposalFeatures([0; 16]),
            shadow_score_millis: None,
        }],
    }
}

pub(crate) fn evaluation_snapshot() -> FrozenGraphResearchSnapshot {
    let mut source = complete_research_snapshot();
    let schema = source.proposals[0].feature_schema_id.clone();
    source.proposals = [
        (
            "train-negative",
            ResearchSplit::Train,
            ResearchProposalLabel::Retracted,
            80,
            90,
            -1000,
        ),
        (
            "train-positive",
            ResearchSplit::Train,
            ResearchProposalLabel::Active,
            80,
            90,
            1000,
        ),
        (
            "validation-negative",
            ResearchSplit::Validation,
            ResearchProposalLabel::Superseded,
            140,
            150,
            -1000,
        ),
        (
            "validation-positive",
            ResearchSplit::Validation,
            ResearchProposalLabel::Active,
            140,
            150,
            1000,
        ),
        (
            "test-negative",
            ResearchSplit::Test,
            ResearchProposalLabel::Reverted,
            220,
            230,
            -1000,
        ),
        (
            "test-positive",
            ResearchSplit::Test,
            ResearchProposalLabel::Active,
            220,
            230,
            1000,
        ),
    ]
    .into_iter()
    .map(
        |(id, split, label, observed_at_ms, label_available_at_ms, signal)| {
            let mut features = [0_i16; PROPOSAL_FEATURE_DIM];
            features[0] = signal;
            ResearchProposal {
                proposal_id: id.into(),
                receipt_id: "evaluation-receipt".into(),
                feature_schema_id: schema.clone(),
                split,
                label,
                observed_at_ms,
                label_available_at_ms,
                features,
            }
        },
    )
    .collect();
    source.dataset_id = "b3-evaluation-fixture".into();
    source
}

pub(crate) fn evaluation_policy(source: &FrozenGraphResearchSnapshot) -> EvaluationPolicy {
    EvaluationPolicy {
        feature_schema_id: source.proposals[0].feature_schema_id.clone(),
        seed_root: 0x5eed_cafe,
        repeats: 3,
        calibration_bins: 10,
        ftrl: FtrlConfig::default(),
        mlp: MlpConfig::default(),
    }
}

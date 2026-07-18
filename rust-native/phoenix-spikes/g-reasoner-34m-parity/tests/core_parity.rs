use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use candle_core::{DType, Device, Tensor};
use g_reasoner_34m_parity::artifact::{MappedIncomingCsr, write_graph_artifact};
use g_reasoner_34m_parity::checkpoint::MappedCheckpoint;
use g_reasoner_34m_parity::graph::{Edge, IncomingCsr};
use g_reasoner_34m_parity::model::{
    AggregationBackend, ForwardTrace, GraphReasonerModel, IncomingGraph, InferenceResult,
};
use g_reasoner_34m_parity::ranker::rank_typed_nodes;
use safetensors::SafeTensors;
use serde::Deserialize;

#[derive(Deserialize)]
struct FixtureMetadata {
    checkpoint_revision: String,
    upstream_revision: String,
    node_count: usize,
    relation_count: usize,
    dst_offsets: Vec<u64>,
    src_nodes: Vec<u32>,
    relation_ids: Vec<u32>,
    document_nodes: Vec<u32>,
    typed_top_k: usize,
}

struct Fixture {
    bytes: Vec<u8>,
    metadata: FixtureMetadata,
    graph: IncomingCsr,
}

impl Fixture {
    fn load() -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures");
        let metadata: FixtureMetadata =
            serde_json::from_slice(&std::fs::read(root.join("core-parity.json")).unwrap()).unwrap();
        let edges = metadata
            .src_nodes
            .iter()
            .zip(&metadata.relation_ids)
            .enumerate()
            .map(|(edge, (&src, &relation))| {
                let dst = metadata
                    .dst_offsets
                    .partition_point(|&offset| offset <= edge as u64)
                    - 1;
                Edge {
                    src,
                    relation,
                    dst: dst as u32,
                }
            });
        let graph =
            IncomingCsr::from_edges(metadata.node_count, metadata.relation_count, edges).unwrap();
        assert_eq!(graph.dst_offsets(), metadata.dst_offsets);
        Self {
            bytes: std::fs::read(root.join("core-parity.safetensors")).unwrap(),
            metadata,
            graph,
        }
    }

    fn tensor(&self, name: &str, device: &Device) -> Tensor {
        let tensors = SafeTensors::deserialize(&self.bytes).unwrap();
        let view = tensors.tensor(name).unwrap();
        let dtype = match view.dtype() {
            safetensors::Dtype::F32 => DType::F32,
            safetensors::Dtype::I64 => DType::I64,
            dtype => panic!("unsupported fixture dtype {dtype:?}"),
        };
        Tensor::from_raw_buffer(view.data(), dtype, view.shape(), device).unwrap()
    }
}

fn checkpoint_path() -> PathBuf {
    std::env::var_os("G_REASONER_CHECKPOINT_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\assets\g-reasoner-34m.safetensors")
        })
}

fn manifest_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("fixtures")
        .join("checkpoint-manifest.json")
}

fn run<G: IncomingGraph>(
    fixture: &Fixture,
    graph: &G,
    backend: AggregationBackend,
) -> ForwardTrace {
    let device = Device::Cpu;
    let checkpoint = MappedCheckpoint::open(checkpoint_path(), manifest_path()).unwrap();
    let model = GraphReasonerModel::load(&checkpoint, &device, 7).unwrap();
    model
        .forward(
            graph,
            &fixture.tensor("question_raw", &device),
            &fixture.tensor("relations_raw", &device),
            &fixture.tensor("entities_raw", &device),
            &fixture
                .tensor("start_mask", &device)
                .to_vec1::<f32>()
                .unwrap(),
            backend,
        )
        .unwrap()
}

fn run_inference<G: IncomingGraph>(fixture: &Fixture, graph: &G) -> InferenceResult {
    let device = Device::Cpu;
    let checkpoint = MappedCheckpoint::open(checkpoint_path(), manifest_path()).unwrap();
    let model = GraphReasonerModel::load(&checkpoint, &device, 7).unwrap();
    model
        .infer_logits(
            graph,
            &fixture.tensor("question_raw", &device),
            &fixture.tensor("relations_raw", &device),
            &fixture.tensor("entities_raw", &device),
            &fixture
                .tensor("start_mask", &device)
                .to_vec1::<f32>()
                .unwrap(),
            AggregationBackend::Fast,
        )
        .unwrap()
}

fn max_abs(actual: &Tensor, expected: &Tensor) -> f32 {
    let actual = actual.flatten_all().unwrap().to_vec1::<f32>().unwrap();
    let expected = expected.flatten_all().unwrap().to_vec1::<f32>().unwrap();
    actual
        .iter()
        .zip(expected)
        .map(|(left, right)| (left - right).abs())
        .fold(0.0, f32::max)
}

fn assert_close(label: &str, actual: &Tensor, expected: &Tensor, tolerance: f32) {
    let error = max_abs(actual, expected);
    assert!(
        error <= tolerance,
        "{label}: max abs error {error} > {tolerance}"
    );
    eprintln!("PARITY {label} max_abs={error:.9}");
}

#[test]
fn proves_graph_core_before_qwen_runtime() {
    let fixture = Fixture::load();
    assert_eq!(
        fixture.metadata.checkpoint_revision,
        g_reasoner_34m_parity::constants::CHECKPOINT_REVISION
    );
    assert_eq!(
        fixture.metadata.upstream_revision,
        g_reasoner_34m_parity::constants::UPSTREAM_REVISION
    );
    let device = Device::Cpu;
    let scalar = run(&fixture, &fixture.graph, AggregationBackend::Scalar);
    let gates = [
        ("question_projection", &scalar.question_projection, 1e-5),
        ("relation_projection", &scalar.relation_projection, 1e-5),
        ("entity_projection", &scalar.entity_projection, 1e-5),
        ("start_boundary", &scalar.start_boundary, 1e-5),
        ("early_fused", &scalar.early_fused, 2e-4),
        (
            "layer0_relation_projection",
            &scalar.layer0_relation_projection,
            2e-3,
        ),
        ("layer0_aggregate", &scalar.layer0_aggregate, 1e-2),
        ("layer0_hidden", &scalar.layer0_hidden, 2e-3),
        ("six_layer_hidden", &scalar.six_layer_hidden, 2e-2),
        ("logits", &scalar.logits, 2e-2),
    ];
    for (name, actual, tolerance) in gates {
        assert_close(name, actual, &fixture.tensor(name, &device), tolerance);
    }

    let logits = scalar.logits.to_vec1::<f32>().unwrap();
    let ranked = rank_typed_nodes(
        &logits,
        &fixture.metadata.document_nodes,
        fixture.metadata.typed_top_k,
    )
    .unwrap();
    let expected_top: BTreeSet<usize> = fixture
        .tensor("document_topk", &device)
        .to_vec1::<i64>()
        .unwrap()
        .into_iter()
        .map(|value| value as usize)
        .collect();
    assert_eq!(
        ranked.node_indices.into_iter().collect::<BTreeSet<_>>(),
        expected_top
    );
    let expected_order: Vec<usize> = fixture
        .tensor("document_order", &device)
        .to_vec1::<i64>()
        .unwrap()
        .into_iter()
        .map(|value| value as usize)
        .collect();
    let full_ranking = rank_typed_nodes(
        &logits,
        &fixture.metadata.document_nodes,
        fixture.metadata.document_nodes.len(),
    )
    .unwrap();
    assert_eq!(full_ranking.node_indices, expected_order);

    let mapped_directory = tempfile::tempdir().unwrap();
    let mapped_path = mapped_directory.path().join("fixture.gr34csr");
    write_graph_artifact(&fixture.graph, &mapped_path).unwrap();
    let mapped = MappedIncomingCsr::open(&mapped_path).unwrap();
    let fast = run_inference(&fixture, &mapped);
    assert!(fast.fast_kernel.is_some());
    assert_close("fast_vs_scalar_logits", &fast.logits, &scalar.logits, 2e-3);
    let fast_logits = fast.logits.to_vec1::<f32>().unwrap();
    assert_eq!(
        rank_typed_nodes(
            &fast_logits,
            &fixture.metadata.document_nodes,
            fixture.metadata.document_nodes.len(),
        )
        .unwrap()
        .node_indices,
        expected_order
    );
}

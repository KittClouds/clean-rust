use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use candle_core::{DType, Device, Tensor};
use gfm_rag_8m_parity::artifact::{MappedIncomingCsr, write_graph_artifact};
use gfm_rag_8m_parity::checkpoint::MappedCheckpoint;
use gfm_rag_8m_parity::graph::{Edge, IncomingCsr};
use gfm_rag_8m_parity::model::{
    AggregationBackend, ForwardTrace, GfmModel, IncomingGraph, InferenceResult,
};
use gfm_rag_8m_parity::ranker::reciprocal_frequency_rank;
use safetensors::SafeTensors;
use serde::Deserialize;

#[derive(Deserialize)]
struct FixtureMetadata {
    checkpoint_revision: String,
    upstream_revision: String,
    node_count: usize,
    relation_count: usize,
    document_count: usize,
    dst_offsets: Vec<u64>,
    src_nodes: Vec<u32>,
    relation_ids: Vec<u32>,
    entity_documents: Vec<Vec<u32>>,
    top_k: usize,
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
    std::env::var_os("GFM_CHECKPOINT_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\gfm-rag-8m.safetensors")
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
    let model = GfmModel::load(&checkpoint, &device, 7).unwrap();
    model
        .forward(
            graph,
            &fixture.tensor("question_raw", &device),
            &fixture.tensor("relations_raw", &device),
            &fixture
                .tensor("start_mask", &device)
                .to_vec1::<f32>()
                .unwrap(),
            &fixture
                .tensor("entity_frequency", &device)
                .to_vec1::<f32>()
                .unwrap(),
            backend,
        )
        .unwrap()
}

fn infer<G: IncomingGraph>(fixture: &Fixture, graph: &G) -> InferenceResult {
    let device = Device::Cpu;
    let checkpoint = MappedCheckpoint::open(checkpoint_path(), manifest_path()).unwrap();
    let model = GfmModel::load(&checkpoint, &device, 7).unwrap();
    model
        .infer_logits(
            graph,
            &fixture.tensor("question_raw", &device),
            &fixture.tensor("relations_raw", &device),
            &fixture
                .tensor("start_mask", &device)
                .to_vec1::<f32>()
                .unwrap(),
            &fixture
                .tensor("entity_frequency", &device)
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
fn proves_core_boundaries_before_mpnet() {
    let fixture = Fixture::load();
    assert_eq!(
        fixture.metadata.checkpoint_revision,
        gfm_rag_8m_parity::constants::CHECKPOINT_REVISION
    );
    assert_eq!(
        fixture.metadata.upstream_revision,
        gfm_rag_8m_parity::constants::UPSTREAM_REVISION
    );
    let device = Device::Cpu;
    let scalar = run(&fixture, &fixture.graph, AggregationBackend::Scalar);

    assert_close(
        "question_projection",
        &scalar.question_projection,
        &fixture.tensor("question_projection", &device),
        5e-6,
    );
    assert_close(
        "relation_projection",
        &scalar.relation_projection,
        &fixture.tensor("relation_projection", &device),
        5e-6,
    );
    assert_close(
        "layer0_relation_projection",
        &scalar.layer0_relation_projection,
        &fixture.tensor("layer0_relation_projection", &device),
        1e-3,
    );
    assert_close(
        "layer0_aggregate",
        &scalar.layer0_aggregate,
        &fixture.tensor("layer0_aggregate", &device),
        2e-3,
    );
    assert_close(
        "one_layer_hidden",
        &scalar.layer0_hidden,
        &fixture.tensor("layer0_hidden", &device),
        2e-3,
    );
    assert_close(
        "six_layer_hidden",
        &scalar.six_layer_hidden,
        &fixture.tensor("six_layer_hidden", &device),
        1e-2,
    );
    assert_close(
        "six_layer_logits",
        &scalar.logits,
        &fixture.tensor("logits", &device),
        1e-2,
    );

    let logits = scalar.logits.to_vec1::<f32>().unwrap();
    let mapping: Vec<Box<[u32]>> = fixture
        .metadata
        .entity_documents
        .iter()
        .cloned()
        .map(Vec::into_boxed_slice)
        .collect();
    let ranked = reciprocal_frequency_rank(
        &logits,
        &mapping,
        fixture.metadata.document_count,
        fixture.metadata.top_k,
    )
    .unwrap();
    let expected_top: BTreeSet<usize> = fixture
        .tensor("top20", &device)
        .to_vec1::<i64>()
        .unwrap()
        .into_iter()
        .map(|value| value as usize)
        .collect();
    let actual_top: BTreeSet<usize> = ranked.top_entities.iter().copied().collect();
    assert_eq!(actual_top, expected_top, "top-20 membership drifted");
    let expected_scores = fixture
        .tensor("document_scores", &device)
        .to_vec1::<f32>()
        .unwrap();
    for (index, (&actual, expected)) in ranked.scores.iter().zip(expected_scores).enumerate() {
        assert!(
            (actual - expected).abs() <= 1e-6,
            "document score {index} drifted"
        );
    }
    let expected_order: Vec<usize> = fixture
        .tensor("final_order", &device)
        .to_vec1::<i64>()
        .unwrap()
        .into_iter()
        .map(|value| value as usize)
        .collect();
    assert_eq!(
        ranked.order, expected_order,
        "final document ordering drifted"
    );

    let mapped_directory = tempfile::tempdir().unwrap();
    let mapped_path = mapped_directory.path().join("fixture.gfmcsr");
    write_graph_artifact(&fixture.graph, &mapped_path).unwrap();
    let mapped = MappedIncomingCsr::open(&mapped_path).unwrap();
    let fast = run(&fixture, &mapped, AggregationBackend::Fast);
    assert!(fast.fast_kernel.is_some());
    assert_close("fast_vs_scalar_logits", &fast.logits, &scalar.logits, 2e-4);
    let fast_logits = fast.logits.to_vec1::<f32>().unwrap();
    let fast_ranked = reciprocal_frequency_rank(
        &fast_logits,
        &mapping,
        fixture.metadata.document_count,
        fixture.metadata.top_k,
    )
    .unwrap();
    assert_eq!(
        fast_ranked
            .top_entities
            .into_iter()
            .collect::<BTreeSet<_>>(),
        expected_top
    );
    assert_eq!(fast_ranked.order, ranked.order);
    let inference_only = infer(&fixture, &mapped);
    assert!(inference_only.fast_kernel.is_some());
    assert_close(
        "inference_only_vs_trace_logits",
        &inference_only.logits,
        &fast.logits,
        1e-6,
    );
}

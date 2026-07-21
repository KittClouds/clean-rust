use std::hint::black_box;
use std::time::{Duration, Instant};

use gfm_wgpu_kernel::{GpuResidentChainRuntime, ResidentChainInput};

const GPU_BUDGET: u64 = 2 * 1024 * 1024 * 1024;
const SAMPLES: usize = 5;

fn main() {
    let runtime = GpuResidentChainRuntime::request(GPU_BUDGET).unwrap();
    let adapter = runtime.adapter_receipt();
    println!(
        "adapter\t{}\t{}\t{}",
        adapter.name, adapter.backend, adapter.driver
    );
    println!(
        "case\tnodes\tedges\tdim\tprepare_ms\tcold_compact_ms\twarm_dispatch_ms\tcompact_read_ms\ttrace_read_ms\tcompact_bytes\ttrace_bytes\tresident_mib"
    );
    for case in [
        Case::new("8m-width", 5_000, 4, 512),
        Case::new("34m-width", 2_000, 10, 1_024),
        Case::new("million-edge", 50_000, 20, 128),
    ] {
        run_case(&runtime, case);
    }
}

fn run_case(runtime: &GpuResidentChainRuntime, case: Case) {
    let fixture = Fixture::new(case.nodes, case.dim, 6, case.dim, case.fanout);
    let upload_started = Instant::now();
    let resident = runtime.upload(fixture.input(20)).unwrap();
    let upload_elapsed = upload_started.elapsed();
    let cold_started = Instant::now();
    let cold = black_box(resident.execute_top_k().unwrap());
    let cold_elapsed = cold_started.elapsed();
    let mut dispatches = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        dispatches.push(resident.dispatch_and_wait().unwrap());
    }
    dispatches.sort_unstable();
    let (_, compact_read) = resident.read_top_k().unwrap();
    let (_, _, trace_read) = resident.read_trace().unwrap();
    println!(
        "{}\t{}\t{}\t{}\t{:.3}\t{:.3}\t{:.3}\t{:.3}\t{:.3}\t{}\t{}\t{:.2}",
        case.name,
        case.nodes,
        case.nodes * case.fanout,
        case.dim,
        millis(upload_elapsed),
        millis(cold_elapsed),
        millis(dispatches[SAMPLES / 2]),
        millis(compact_read),
        millis(trace_read),
        cold.timing.readback_bytes,
        resident.shape().trace_readback_bytes,
        resident.shape().resident_bytes as f64 / (1024.0 * 1024.0),
    );
}

struct Case {
    name: &'static str,
    nodes: usize,
    fanout: usize,
    dim: usize,
}

impl Case {
    const fn new(name: &'static str, nodes: usize, fanout: usize, dim: usize) -> Self {
        Self {
            name,
            nodes,
            fanout,
            dim,
        }
    }
}

struct Fixture {
    offsets: Vec<u64>,
    sources: Vec<u32>,
    relation_ids: Vec<u32>,
    hidden: Vec<f32>,
    boundary: Vec<f32>,
    relations: Vec<f32>,
    old_weights: Vec<f32>,
    aggregate_weights: Vec<f32>,
    update_bias: Vec<f32>,
    norm_scale: Vec<f32>,
    norm_bias: Vec<f32>,
    score_weight: Vec<f32>,
    query: Vec<f32>,
    score_bias: Vec<f32>,
    output_weight: Vec<f32>,
    dim: usize,
}

impl Fixture {
    fn new(nodes: usize, dim: usize, layers: usize, score_dim: usize, fanout: usize) -> Self {
        let mut offsets = Vec::with_capacity(nodes + 1);
        let mut sources = Vec::with_capacity(nodes * fanout);
        let mut relation_ids = Vec::with_capacity(nodes * fanout);
        offsets.push(0);
        for node in 0..nodes {
            for edge in 0..fanout {
                sources.push(((node * 17 + edge * 29 + 3) % nodes) as u32);
                relation_ids.push(((node + edge * 3) % 8) as u32);
            }
            offsets.push(sources.len() as u64);
        }
        let node_values = nodes * dim;
        let layer_matrix = layers * dim * dim;
        let layer_vector = layers * dim;
        Self {
            offsets,
            sources,
            relation_ids,
            hidden: values(node_values, 0.025, 1),
            boundary: values(node_values, 0.004, 2),
            relations: values(layers * 8 * dim, 0.015, 3),
            old_weights: values(layer_matrix, 0.006, 4),
            aggregate_weights: values(layer_matrix, 0.004, 5),
            update_bias: values(layer_vector, 0.002, 6),
            norm_scale: vec![1.0; layer_vector],
            norm_bias: values(layer_vector, 0.002, 7),
            score_weight: values(score_dim * dim, 0.006, 8),
            query: values(score_dim, 0.01, 9),
            score_bias: values(score_dim, 0.002, 10),
            output_weight: values(score_dim, 0.01, 11),
            dim,
        }
    }

    fn input(&self, top_k: usize) -> ResidentChainInput<'_> {
        ResidentChainInput {
            offsets: &self.offsets,
            sources: &self.sources,
            relation_ids: &self.relation_ids,
            initial_hidden: &self.hidden,
            boundary: &self.boundary,
            layer_relations: &self.relations,
            old_weights: &self.old_weights,
            aggregate_weights: &self.aggregate_weights,
            update_bias: &self.update_bias,
            norm_scale: &self.norm_scale,
            norm_bias: &self.norm_bias,
            scorer_hidden_weight: &self.score_weight,
            scorer_entity: None,
            scorer_entity_weight: None,
            scorer_query_term: &self.query,
            scorer_bias: &self.score_bias,
            scorer_output_weight: &self.output_weight,
            scorer_output_bias: 0.0,
            dim: self.dim,
            layers: 6,
            score_dim: self.dim,
            top_k,
        }
    }
}

fn values(count: usize, scale: f32, salt: usize) -> Vec<f32> {
    (0..count)
        .map(|index| {
            let mixed = index
                .wrapping_mul(1_664_525)
                .wrapping_add(salt.wrapping_mul(1_013_904_223));
            ((mixed % 2_003) as f32 / 1_001.0 - 1.0) * scale
        })
        .collect()
}

fn millis(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1_000.0
}

use std::time::{Duration, Instant};

use g_reasoner_34m_parity::kernel::fast_distmult_sum as reasoner_cpu;
use gfm_rag_8m_parity::kernel::fast_distmult_sum as rag_cpu;
use gfm_wgpu_kernel::{DispatchPolicy, DistMultInput, GpuKernelRuntime};

const WARM_RUNS: usize = 7;

fn main() {
    let device_started = Instant::now();
    let runtime = GpuKernelRuntime::request(DispatchPolicy::default())
        .unwrap_or_else(|error| panic!("GPU benchmark requires a hardware adapter: {error}"));
    let device_ms = millis(device_started.elapsed());
    let adapter = runtime.adapter_receipt();
    println!(
        "adapter={:?} backend={} type={} driver={:?} device_init_ms={device_ms:.3} max_buffer_mib={:.1} max_binding_mib={:.1}",
        adapter.name,
        adapter.backend,
        adapter.device_type,
        adapter.driver,
        adapter.max_buffer_bytes as f64 / 1_048_576.0,
        adapter.max_storage_binding_bytes as f64 / 1_048_576.0,
    );
    println!(
        "case,nodes,edges,dim,resident_mib,cpu_ms,gpu_prepare_ms,gpu_cold_dispatch_ms,gpu_warm_median_ms,readback_ms,speedup,max_abs"
    );
    for case in cases() {
        run_case(&runtime, case);
    }
}

#[derive(Clone, Copy)]
struct Case {
    name: &'static str,
    nodes: usize,
    edges: usize,
    dim: usize,
    relations: usize,
}

fn cases() -> [Case; 4] {
    [
        Case {
            name: "g-reasoner-shape",
            nodes: 5_000,
            edges: 20_000,
            dim: 1_024,
            relations: 16,
        },
        Case {
            name: "gfm-rag-shape",
            nodes: 10_000,
            edges: 40_000,
            dim: 512,
            relations: 16,
        },
        Case {
            name: "medium-resident",
            nodes: 25_000,
            edges: 250_000,
            dim: 256,
            relations: 24,
        },
        Case {
            name: "million-edge",
            nodes: 50_000,
            edges: 1_000_000,
            dim: 128,
            relations: 24,
        },
    ]
}

fn run_case(runtime: &GpuKernelRuntime, case: Case) {
    let fixture = Fixture::new(case);
    let input = fixture.input();
    let mut cpu_times = Vec::with_capacity(3);
    let mut expected = Vec::new();
    for _ in 0..3 {
        let started = Instant::now();
        let (output, _) = rag_cpu(
            input.offsets,
            input.sources,
            input.relation_ids,
            input.input,
            input.relations,
            input.boundary,
            input.dim,
        )
        .unwrap();
        cpu_times.push(started.elapsed());
        expected = output;
    }
    if case.name == "g-reasoner-shape" {
        let (reasoner, _) = reasoner_cpu(
            input.offsets,
            input.sources,
            input.relation_ids,
            input.input,
            input.relations,
            input.boundary,
            input.dim,
        )
        .unwrap();
        assert_eq!(expected, reasoner, "the two CPU oracles diverged");
    }
    let resident = runtime.upload(input).unwrap();
    let cold = resident.dispatch_and_wait().unwrap();
    let mut warm = Vec::with_capacity(WARM_RUNS);
    for _ in 0..WARM_RUNS {
        warm.push(resident.dispatch_and_wait().unwrap());
    }
    let (actual, readback) = resident.read_output().unwrap();
    let cpu = median(&mut cpu_times);
    let gpu = median(&mut warm);
    let max_abs = max_abs(&expected, &actual);
    assert!(max_abs <= 1.0e-5, "{} parity drift {max_abs}", case.name);
    let receipt = resident.receipt();
    println!(
        "{},{},{},{},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.9}",
        case.name,
        case.nodes,
        case.edges,
        case.dim,
        (receipt.resident_bytes + receipt.readback_bytes) as f64 / 1_048_576.0,
        millis(cpu),
        receipt.prepare_micros as f64 / 1_000.0,
        millis(cold),
        millis(gpu),
        millis(readback),
        cpu.as_secs_f64() / gpu.as_secs_f64(),
        max_abs,
    );
}

struct Fixture {
    offsets: Vec<u64>,
    sources: Vec<u32>,
    relation_ids: Vec<u32>,
    input: Vec<f32>,
    relations: Vec<f32>,
    boundary: Vec<f32>,
    dim: usize,
}

impl Fixture {
    fn new(case: Case) -> Self {
        let mut offsets = Vec::with_capacity(case.nodes + 1);
        offsets.push(0);
        for node in 0..case.nodes {
            offsets.push((case.edges * (node + 1) / case.nodes) as u64);
        }
        Self {
            sources: (0..case.edges)
                .map(|edge| ((edge * 17 + edge / 7) % case.nodes) as u32)
                .collect(),
            relation_ids: (0..case.edges)
                .map(|edge| (edge % case.relations) as u32)
                .collect(),
            input: values(case.nodes * case.dim, 29, 0.0078125),
            relations: values(case.relations * case.dim, 13, -0.00390625),
            boundary: values(case.nodes * case.dim, 7, 0.001953125),
            offsets,
            dim: case.dim,
        }
    }

    fn input(&self) -> DistMultInput<'_> {
        DistMultInput {
            offsets: &self.offsets,
            sources: &self.sources,
            relation_ids: &self.relation_ids,
            input: &self.input,
            relations: &self.relations,
            boundary: &self.boundary,
            dim: self.dim,
        }
    }
}

fn values(count: usize, multiplier: usize, scale: f32) -> Vec<f32> {
    (0..count)
        .map(|index| ((index * multiplier % 251) as f32 - 125.0) * scale)
        .collect()
}

fn max_abs(left: &[f32], right: &[f32]) -> f32 {
    left.iter()
        .zip(right)
        .map(|(left, right)| (left - right).abs())
        .fold(0.0, f32::max)
}

fn median(values: &mut [Duration]) -> Duration {
    values.sort_unstable();
    values[values.len() / 2]
}

fn millis(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1_000.0
}

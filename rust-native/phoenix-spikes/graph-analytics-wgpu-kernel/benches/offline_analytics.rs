use std::hint::black_box;
use std::time::Instant;

use graph_analytics_wgpu_kernel::{
    AnalyticsInput, EdgePolicy, GpuGraphAnalyticsRuntime, PackedEdge, RunConfig, cpu_analyze,
};

fn main() {
    let structural_only = std::env::var("PHOENIX_ANALYTICS_BENCH_MODE")
        .is_ok_and(|mode| mode.eq_ignore_ascii_case("structural"));
    let (sources, diffusion_iterations, mode) = if structural_only {
        (0, 0, "structural")
    } else {
        (4, 8, "diffusion")
    };
    let runtime = GpuGraphAnalyticsRuntime::request(2 * 1024 * 1024 * 1024)
        .expect("high-performance GPU adapter");
    println!("adapter={:?}", runtime.adapter_receipt());
    for (nodes, edges) in [
        (1_000_u32, 10_000_u32),
        (2_500, 25_000),
        (5_000, 50_000),
        (10_000_u32, 100_000_u32),
        (25_000, 250_000),
        (50_000, 500_000),
        (100_000, 1_000_000),
        (250_000, 2_000_000),
    ] {
        let fixture = Fixture::new(nodes, edges, sources);
        let config = RunConfig {
            weak_component_iterations: 32,
            diffusion_iterations,
            diffusion_damping: 0.85,
        };
        let input = fixture.input();
        black_box(cpu_analyze(input, config).expect("warm CPU analytics"));
        black_box(resident_analyze(&runtime, input, config));
        let mut cpu_samples = Vec::new();
        let mut gpu_prepare = Vec::new();
        let mut gpu_execute = Vec::new();
        let mut gpu_readback = Vec::new();
        let mut gpu_total = Vec::new();
        let mut cpu = None;
        let mut gpu = None;
        for _ in 0..5 {
            let cpu_started = Instant::now();
            cpu = Some(black_box(
                cpu_analyze(input, config).expect("CPU analytics"),
            ));
            cpu_samples.push(cpu_started.elapsed().as_secs_f64() * 1_000.0);
            let output = black_box(resident_analyze(&runtime, input, config));
            gpu_prepare.push(output.timing.prepare_micros as f64 / 1_000.0);
            gpu_execute.push(output.timing.execute_micros as f64 / 1_000.0);
            gpu_readback.push(output.timing.readback_micros as f64 / 1_000.0);
            gpu_total.push(
                (output.timing.prepare_micros
                    + output.timing.execute_micros
                    + output.timing.readback_micros) as f64
                    / 1_000.0,
            );
            gpu = Some(output);
        }
        let cpu = cpu.unwrap();
        let gpu = gpu.unwrap();
        assert_integer_parity(&gpu, &cpu);
        let max_diffusion_error = gpu
            .diffusion_ranks
            .iter()
            .zip(&cpu.diffusion_ranks)
            .map(|(left, right)| (left - right).abs())
            .fold(0.0_f32, f32::max);
        println!(
            "mode={mode} nodes={nodes} edges={edges} sources={sources} iterations={diffusion_iterations} trials=5 cpu_ms={} gpu_total_ms={} gpu_prepare_ms={} gpu_execute_ms={} gpu_readback_ms={} resident_mib={:.2} readback_mib={:.2} max_diffusion_error={max_diffusion_error:.8}",
            summary(&mut cpu_samples),
            summary(&mut gpu_total),
            summary(&mut gpu_prepare),
            summary(&mut gpu_execute),
            summary(&mut gpu_readback),
            gpu.timing.gpu_resident_bytes as f64 / (1024.0 * 1024.0),
            gpu.timing.readback_bytes as f64 / (1024.0 * 1024.0),
        );
    }
}

fn resident_analyze(
    runtime: &GpuGraphAnalyticsRuntime,
    input: AnalyticsInput<'_>,
    config: RunConfig,
) -> graph_analytics_wgpu_kernel::AnalyticsOutput {
    let partition_labels = input.partition_labels;
    let mut resident = runtime
        .upload_generation(input, config)
        .expect("resident GPU upload");
    let prepartition = resident.prepartition().expect("resident GPU prepartition");
    let postpartition = resident
        .postpartition(partition_labels)
        .expect("resident GPU postpartition");
    prepartition.finish(postpartition)
}

fn assert_integer_parity(
    gpu: &graph_analytics_wgpu_kernel::AnalyticsOutput,
    cpu: &graph_analytics_wgpu_kernel::AnalyticsOutput,
) {
    assert_eq!(gpu.active_edge_mask, cpu.active_edge_mask);
    assert_eq!(gpu.out_degree, cpu.out_degree);
    assert_eq!(gpu.in_degree, cpu.in_degree);
    assert_eq!(gpu.incident_degree, cpu.incident_degree);
    assert_eq!(gpu.relation_family_histogram, cpu.relation_family_histogram);
    assert_eq!(gpu.component_labels, cpu.component_labels);
    assert_eq!(gpu.out_strength, cpu.out_strength);
    assert_eq!(gpu.total_strength, cpu.total_strength);
    assert_eq!(gpu.boundary_degree, cpu.boundary_degree);
    assert_eq!(gpu.boundary_strength, cpu.boundary_strength);
    assert_eq!(gpu.neighbor_degree_sum, cpu.neighbor_degree_sum);
}

fn summary(samples: &mut [f64]) -> String {
    samples.sort_by(f64::total_cmp);
    format!(
        "{:.3}[{:.3}..{:.3}]",
        samples[samples.len() / 2],
        samples[0],
        samples[samples.len() - 1]
    )
}

struct Fixture {
    nodes: u32,
    edges: Vec<PackedEdge>,
    mask: Vec<u32>,
    partition: Vec<u32>,
    seeds: Vec<f32>,
    sources: u32,
}

impl Fixture {
    fn new(nodes: u32, edge_count: u32, sources: u32) -> Self {
        let mut edges = Vec::with_capacity(edge_count as usize);
        for node in 0..nodes {
            edges.push(PackedEdge {
                source: node,
                target: (node + 1) % nodes,
                relation_family: node % 8,
                weight: node % 31 + 1,
            });
        }
        let mut state = 0x9e37_79b9_u32;
        while edges.len() < edge_count as usize {
            state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            let source = state % nodes;
            state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            let target = state % nodes;
            edges.push(PackedEdge {
                source,
                target,
                relation_family: state.rotate_left(7) % 8,
                weight: state.rotate_left(13) % 31 + 1,
            });
        }
        let mask = vec![1; nodes as usize];
        let partition = (0..nodes).map(|node| node / 1_024).collect();
        let mut seeds = vec![0.0; nodes as usize * sources as usize];
        for source in 0..sources as usize {
            seeds[source * nodes as usize + source * 997 % nodes as usize] = 1.0;
        }
        Self {
            nodes,
            edges,
            mask,
            partition,
            seeds,
            sources,
        }
    }

    fn input(&self) -> AnalyticsInput<'_> {
        AnalyticsInput {
            node_count: self.nodes,
            relation_family_count: 8,
            edges: &self.edges,
            node_policy_mask: &self.mask,
            partition_labels: &self.partition,
            diffusion_seeds: &self.seeds,
            diffusion_source_count: self.sources,
            edge_policy: EdgePolicy::default(),
        }
    }
}

use std::hint::black_box;
use std::time::{Duration, Instant};

use galaxy_wgpu_lod_kernel::{
    EdgeInput, GalaxyGpuRuntime, MortonRadixScratch, StageTiming, build_lod_ranges, cpu_lod,
    cpu_remap_edges, cpu_spatial,
};

const GPU_BUDGET: u64 = 2 * 1024 * 1024 * 1024;
const TILE_BITS: u8 = 6;
const SAMPLES: usize = 5;

fn main() {
    let runtime = GalaxyGpuRuntime::request(GPU_BUDGET).expect("high-performance GPU");
    let adapter = runtime.adapter_receipt();
    println!(
        "adapter\t{}\t{}\t{}\t{}",
        adapter.name, adapter.backend, adapter.device_type, adapter.driver
    );
    println!(
        "nodes\tedges\tstage\tcpu_ms\tgpu_prepare_ms\tgpu_dispatch_ms\tgpu_readback_ms\tgpu_e2e_ms\tgpu_mib"
    );
    for nodes in [100_000usize, 500_000, 1_000_000] {
        run_case(&runtime, nodes, nodes * 2);
    }
}

fn run_case(runtime: &GalaxyGpuRuntime, nodes: usize, edge_count: usize) {
    let positions = positions(nodes);
    let cpu_started = Instant::now();
    let cpu_spatial_output = black_box(cpu_spatial(&positions, TILE_BITS).unwrap());
    let cpu_spatial_time = cpu_started.elapsed();

    let resident = runtime.upload_positions(&positions, TILE_BITS).unwrap();
    let mut spatial_samples = Vec::with_capacity(SAMPLES);
    let mut gpu_spatial = None;
    for _ in 0..SAMPLES {
        let started = Instant::now();
        let output = black_box(resident.execute_spatial().unwrap());
        spatial_samples.push((started.elapsed(), output.timing));
        gpu_spatial = Some(output);
    }
    let gpu_spatial = gpu_spatial.unwrap();
    assert_eq!(gpu_spatial.node_tiles, cpu_spatial_output.node_tiles);
    print_row(
        nodes,
        edge_count,
        "spatial",
        cpu_spatial_time,
        median_sample(&mut spatial_samples),
    );

    let comparison_started = Instant::now();
    let mut order = (0..nodes as u32).collect::<Vec<_>>();
    order.sort_unstable_by_key(|node| (gpu_spatial.morton_keys[*node as usize], *node));
    let comparison_time = comparison_started.elapsed();
    println!(
        "{nodes}\t{edge_count}\tcomparison_sort\t{:.3}\t0\t0\t0\t0\t0",
        millis(comparison_time)
    );
    let mut radix = MortonRadixScratch::new();
    let mut radix_samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let started = Instant::now();
        black_box(radix.sort(&gpu_spatial.morton_keys).unwrap());
        radix_samples.push(started.elapsed());
    }
    radix_samples.sort_unstable();
    let radix_time = radix_samples[SAMPLES / 2];
    assert_eq!(radix.sort(&gpu_spatial.morton_keys).unwrap(), order);
    println!(
        "{nodes}\t{edge_count}\tradix_sort\t{:.3}\t0\t0\t0\t{:.3}\t{:.3}",
        millis(radix_time),
        millis(radix_time),
        radix.resident_bytes() as f64 / (1024.0 * 1024.0),
    );
    let ranges = build_lod_ranges(&gpu_spatial.morton_keys, &order, TILE_BITS).unwrap();

    let cpu_started = Instant::now();
    let cpu_lod_output = black_box(cpu_lod(&positions, &order, &ranges).unwrap());
    let cpu_lod_time = cpu_started.elapsed();
    let resident_lod = resident.build_lod(&order, &ranges).unwrap();
    let mut lod_samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let started = Instant::now();
        let output = black_box(resident_lod.execute().unwrap());
        assert_eq!(output.node_to_lod, cpu_lod_output.node_to_lod);
        lod_samples.push((started.elapsed(), output.timing));
    }
    print_row(
        nodes,
        edge_count,
        "lod",
        cpu_lod_time,
        median_sample(&mut lod_samples),
    );

    let edges = edges(edge_count, nodes as u32);
    let cpu_started = Instant::now();
    let cpu_keys = black_box(cpu_remap_edges(&edges, &cpu_lod_output.node_to_lod).unwrap());
    let cpu_edge_time = cpu_started.elapsed();
    let started = Instant::now();
    let gpu_keys = black_box(resident_lod.remap_edges(&edges).unwrap());
    let edge_sample = (started.elapsed(), gpu_keys.timing);
    assert_eq!(gpu_keys.keys, cpu_keys);
    print_row(nodes, edge_count, "edge_remap", cpu_edge_time, edge_sample);
}

fn print_row(
    nodes: usize,
    edges: usize,
    stage: &str,
    cpu: Duration,
    sample: (Duration, StageTiming),
) {
    println!(
        "{nodes}\t{edges}\t{stage}\t{:.3}\t{:.3}\t{:.3}\t{:.3}\t{:.3}\t{:.3}",
        millis(cpu),
        sample.1.prepare_micros as f64 / 1_000.0,
        sample.1.dispatch_micros as f64 / 1_000.0,
        sample.1.readback_micros as f64 / 1_000.0,
        millis(sample.0),
        sample.1.gpu_bytes as f64 / (1024.0 * 1024.0),
    );
}

fn median_sample(samples: &mut [(Duration, StageTiming)]) -> (Duration, StageTiming) {
    samples.sort_unstable_by_key(|sample| sample.0);
    samples[samples.len() / 2]
}

fn millis(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1_000.0
}

fn positions(count: usize) -> Vec<[f32; 3]> {
    let mut state = 0x517c_c1b7_2722_0a95u64;
    (0..count)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            [
                ((state & 0xffff) as f32 - 32_768.0) * 0.03125,
                (((state >> 16) & 0xffff) as f32 - 32_768.0) * 0.015625,
                (((state >> 32) & 0xffff) as f32 - 32_768.0) * 0.0078125,
            ]
        })
        .collect()
}

fn edges(count: usize, nodes: u32) -> Vec<EdgeInput> {
    (0..count as u32)
        .map(|edge| EdgeInput {
            source: edge.wrapping_mul(2_654_435_761) % nodes,
            target: edge.wrapping_mul(2_246_822_519).wrapping_add(17) % nodes,
            weight_millis: edge % 10_003,
            flags: 1 << (edge % 8),
        })
        .collect()
}

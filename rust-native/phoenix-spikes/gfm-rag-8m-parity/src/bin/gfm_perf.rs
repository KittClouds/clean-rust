use std::time::{Duration, Instant};

use gfm_rag_8m_parity::graph::{Edge, IncomingCsr};
use gfm_rag_8m_parity::kernel::{fast_distmult_sum, scalar_distmult_sum};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let nodes = env_usize("GFM_PERF_NODES", 10_000);
    let edges_per_node = env_usize("GFM_PERF_EDGES_PER_NODE", 4);
    let iterations = env_usize("GFM_PERF_ITERATIONS", 5);
    let relations = 64;
    let dim = 512;
    let edges = (0..nodes).flat_map(|dst| {
        (0..edges_per_node).map(move |slot| Edge {
            src: ((dst * 17 + slot * 7919 + 3) % nodes) as u32,
            relation: ((dst + slot * 13) % relations) as u32,
            dst: dst as u32,
        })
    });
    let graph = IncomingCsr::from_edges(nodes, relations, edges)?;
    let input: Vec<f32> = (0..nodes * dim).map(stable_value).collect();
    let relation_state: Vec<f32> = (0..relations * dim)
        .map(|index| stable_value(index + 0x9e37))
        .collect();
    let boundary = vec![0.0_f32; nodes * dim];

    let scalar_start = Instant::now();
    let reference = scalar_distmult_sum(
        graph.dst_offsets(),
        graph.src_nodes(),
        graph.relation_ids(),
        &input,
        &relation_state,
        &boundary,
        dim,
    )?;
    let scalar = scalar_start.elapsed();
    let mut timings = Vec::with_capacity(iterations);
    let mut kernel = None;
    let mut max_abs = 0_f32;
    for _ in 0..iterations {
        let start = Instant::now();
        let (actual, selected) = fast_distmult_sum(
            graph.dst_offsets(),
            graph.src_nodes(),
            graph.relation_ids(),
            &input,
            &relation_state,
            &boundary,
            dim,
        )?;
        timings.push(start.elapsed());
        kernel = Some(selected);
        max_abs = max_abs.max(
            actual
                .iter()
                .zip(&reference)
                .map(|(left, right)| (left - right).abs())
                .fold(0.0, f32::max),
        );
    }
    timings.sort_unstable();
    let median = timings[timings.len() / 2];
    let state_bytes = nodes * dim * size_of::<f32>();
    println!(
        "{{\"nodes\":{nodes},\"edges\":{},\"dim\":{dim},\"kernel\":\"{:?}\",\"scalar_ms\":{:.3},\"fast_median_ms\":{:.3},\"speedup\":{:.3},\"max_abs\":{max_abs:.9},\"state_bytes\":{state_bytes}}}",
        graph.edge_count(),
        kernel.unwrap(),
        millis(scalar),
        millis(median),
        scalar.as_secs_f64() / median.as_secs_f64(),
    );
    Ok(())
}

fn stable_value(index: usize) -> f32 {
    let mixed = (index as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15);
    ((mixed >> 48) as i32 - 32_768) as f32 / 65_536.0
}

fn env_usize(name: &str, fallback: usize) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|&value| value > 0)
        .unwrap_or(fallback)
}

fn millis(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1_000.0
}

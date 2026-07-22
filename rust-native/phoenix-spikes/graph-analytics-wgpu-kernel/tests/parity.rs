use graph_analytics_wgpu_kernel::{
    AnalyticsInput, EdgePolicy, GpuGraphAnalyticsRuntime, PackedEdge, RunConfig, cpu_analyze,
};

#[test]
fn gpu_matches_cpu_for_filtered_generation_batch() {
    let edges = [
        edge(0, 1, 0, 2),
        edge(1, 2, 1, 3),
        edge(2, 0, 0, 1),
        edge(2, 3, 2, 9),
        edge(3, 4, 0, 4),
        edge(5, 6, 1, 5),
        edge(6, 5, 1, 2),
        edge(6, 7, 0, 1),
    ];
    let mask = [1, 1, 1, 1, 0, 1, 1, 1];
    let partition = [0, 0, 1, 1, u32::MAX, 2, 3, 3];
    let seeds = [
        1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
    ];
    let input = AnalyticsInput {
        node_count: 8,
        relation_family_count: 3,
        edges: &edges,
        node_policy_mask: &mask,
        partition_labels: &partition,
        diffusion_seeds: &seeds,
        diffusion_source_count: 2,
        edge_policy: EdgePolicy {
            admitted_relation_families: 0b011,
            minimum_weight: 2,
        },
    };
    let config = RunConfig {
        weak_component_iterations: 8,
        diffusion_iterations: 12,
        diffusion_damping: 0.85,
    };
    let expected = cpu_analyze(input, config).unwrap();
    let runtime = match GpuGraphAnalyticsRuntime::request(512 * 1024 * 1024) {
        Ok(runtime) => runtime,
        Err(error) => {
            eprintln!("GPU parity skipped because no hardware adapter is available: {error}");
            return;
        }
    };
    let mut resident = runtime.upload_generation(input, config).unwrap();
    let resident_bytes = resident.resident_bytes();
    let prepartition = resident.prepartition().unwrap();
    assert!(resident.postpartition(&partition[..7]).is_err());
    let bridge = resident.postpartition(&partition).unwrap();
    assert!(resident.prepartition().is_err());
    let actual = prepartition.finish(bridge);

    assert_eq!(actual.active_edge_mask, expected.active_edge_mask);
    assert_eq!(actual.out_degree, expected.out_degree);
    assert_eq!(actual.in_degree, expected.in_degree);
    assert_eq!(actual.incident_degree, expected.incident_degree);
    assert_eq!(
        actual.relation_family_histogram,
        expected.relation_family_histogram
    );
    assert_eq!(actual.component_labels, expected.component_labels);
    assert_eq!(actual.out_strength, expected.out_strength);
    assert_eq!(actual.total_strength, expected.total_strength);
    assert_eq!(actual.boundary_degree, expected.boundary_degree);
    assert_eq!(actual.boundary_strength, expected.boundary_strength);
    assert_eq!(actual.neighbor_degree_sum, expected.neighbor_degree_sum);
    assert_eq!(actual.diffusion_ranks.len(), expected.diffusion_ranks.len());
    let max_error = actual
        .diffusion_ranks
        .iter()
        .zip(&expected.diffusion_ranks)
        .map(|(actual, expected)| (actual - expected).abs())
        .fold(0.0_f32, f32::max);
    assert!(max_error <= 1.0e-6, "diffusion drift {max_error}");
    assert_ne!(runtime.adapter_receipt().device_type, "Cpu");
    assert_eq!(actual.timing.gpu_resident_bytes, resident_bytes);
}

fn edge(source: u32, target: u32, relation_family: u32, weight: u32) -> PackedEdge {
    PackedEdge {
        source,
        target,
        relation_family,
        weight,
    }
}

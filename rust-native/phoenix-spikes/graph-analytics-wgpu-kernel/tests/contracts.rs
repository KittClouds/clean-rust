use graph_analytics_wgpu_kernel::{
    AnalyticsInput, EdgePolicy, GraphAnalyticsError, PackedEdge, RunConfig, cpu_analyze,
};

fn valid_input<'a>(
    edges: &'a [PackedEdge],
    mask: &'a [u32],
    partition: &'a [u32],
    seeds: &'a [f32],
) -> AnalyticsInput<'a> {
    AnalyticsInput {
        node_count: mask.len() as u32,
        relation_family_count: 2,
        edges,
        node_policy_mask: mask,
        partition_labels: partition,
        diffusion_seeds: seeds,
        diffusion_source_count: 1,
        edge_policy: EdgePolicy::default(),
    }
}

#[test]
fn invalid_capabilities_fail_closed_with_named_input_errors() {
    let edges = [PackedEdge {
        source: 0,
        target: 1,
        relation_family: 0,
        weight: 1,
    }];
    let mask = [1, 1];
    let partition = [0, 0];
    let seeds = [1.0, 0.0];
    let mut input = valid_input(&edges, &mask, &partition, &seeds);
    input.relation_family_count = 33;
    assert!(matches!(
        cpu_analyze(input, RunConfig::default()),
        Err(GraphAnalyticsError::Input(message)) if message.contains("1..=32")
    ));

    let input = valid_input(&edges, &mask, &partition, &seeds);
    let config = RunConfig {
        weak_component_iterations: 0,
        ..RunConfig::default()
    };
    assert!(matches!(
        cpu_analyze(input, config),
        Err(GraphAnalyticsError::Input(message)) if message.contains("must be nonzero")
    ));
}

#[test]
fn generation_batch_can_skip_diffusion_without_skipping_exact_integer_analytics() {
    let edges = [PackedEdge {
        source: 0,
        target: 1,
        relation_family: 0,
        weight: 7,
    }];
    let mask = [1, 1];
    let partition = [0, 1];
    let output = cpu_analyze(
        AnalyticsInput {
            node_count: 2,
            relation_family_count: 1,
            edges: &edges,
            node_policy_mask: &mask,
            partition_labels: &partition,
            diffusion_seeds: &[],
            diffusion_source_count: 0,
            edge_policy: EdgePolicy::default(),
        },
        RunConfig {
            diffusion_iterations: 0,
            ..RunConfig::default()
        },
    )
    .unwrap();
    assert_eq!(output.component_labels, [0, 0]);
    assert_eq!(output.total_strength, [7, 7]);
    assert_eq!(output.boundary_strength, [7, 7]);
    assert!(output.diffusion_ranks.is_empty());
}

#[test]
fn policy_mask_controls_every_integer_analytic() {
    let edges = [
        PackedEdge {
            source: 0,
            target: 1,
            relation_family: 0,
            weight: 3,
        },
        PackedEdge {
            source: 1,
            target: 2,
            relation_family: 1,
            weight: 5,
        },
        PackedEdge {
            source: 2,
            target: 3,
            relation_family: 0,
            weight: 1,
        },
    ];
    let mask = [1, 1, 1, 0];
    let partition = [0, 0, 1, u32::MAX];
    let seeds = [1.0, 0.0, 0.0, 0.0];
    let mut input = valid_input(&edges, &mask, &partition, &seeds);
    input.edge_policy = EdgePolicy {
        admitted_relation_families: 0b01,
        minimum_weight: 2,
    };
    let output = cpu_analyze(input, RunConfig::default()).unwrap();
    assert_eq!(output.active_edge_mask, [1, 0, 0]);
    assert_eq!(output.out_degree, [1, 0, 0, 0]);
    assert_eq!(output.in_degree, [0, 1, 0, 0]);
    assert_eq!(output.relation_family_histogram, [1, 0]);
    assert_eq!(output.component_labels, [0, 0, 2, u32::MAX]);
    assert_eq!(output.boundary_degree, [0, 0, 0, 0]);
}

#[test]
fn public_surface_has_no_leiden_or_partition_mutation_entry_point() {
    let source = include_str!("../src/lib.rs");
    assert!(!source.contains("fn leiden"));
    assert!(!source.contains("local_move"));
    assert!(source.contains("no Leiden/local-move API"));
}

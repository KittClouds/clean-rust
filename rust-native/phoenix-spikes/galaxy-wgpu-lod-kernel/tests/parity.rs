use galaxy_wgpu_lod_kernel::{
    EdgeInput, GalaxyGpuError, GalaxyGpuRuntime, LodAggregate, build_lod_ranges, cpu_lod,
    cpu_remap_edges, cpu_spatial, reduce_bundle_keys,
};

const GPU_BUDGET: u64 = 512 * 1024 * 1024;

#[test]
fn gpu_spatial_lod_and_edge_remap_match_cpu_oracle() {
    let positions = positions(32_777);
    let cpu_spatial = cpu_spatial(&positions, 7).unwrap();

    let runtime = GalaxyGpuRuntime::request(GPU_BUDGET).unwrap();
    let resident = runtime.upload_positions(&positions, 7).unwrap();
    let gpu_spatial = resident.execute_spatial().unwrap();
    assert_eq!(gpu_spatial.bounds_min, cpu_spatial.bounds_min);
    assert_eq!(gpu_spatial.bounds_max, cpu_spatial.bounds_max);
    assert_exact_u64("tile", &gpu_spatial.node_tiles, &cpu_spatial.node_tiles);
    assert_same_tile_prefix(&gpu_spatial.morton_keys, &cpu_spatial.morton_keys, 7);

    let repeated = resident.execute_spatial().unwrap();
    assert_eq!(repeated.morton_keys, gpu_spatial.morton_keys);
    assert_eq!(repeated.node_tiles, gpu_spatial.node_tiles);

    let mut order = (0..positions.len() as u32).collect::<Vec<_>>();
    order.sort_unstable_by_key(|node| (gpu_spatial.morton_keys[*node as usize], *node));
    let ranges = build_lod_ranges(&gpu_spatial.morton_keys, &order, 7).unwrap();
    let cpu_lod = cpu_lod(&positions, &order, &ranges).unwrap();
    let edges = edges(91_009, positions.len() as u32);
    let cpu_keys = cpu_remap_edges(&edges, &cpu_lod.node_to_lod).unwrap();
    let resident_lod = resident.build_lod(&order, &ranges).unwrap();
    let gpu_lod = resident_lod.execute().unwrap();
    assert_eq!(gpu_lod.node_to_lod, cpu_lod.node_to_lod);
    assert_aggregate_parity(&gpu_lod.aggregates, &cpu_lod.aggregates);

    let gpu_keys = resident_lod.remap_edges(&edges).unwrap();
    assert_eq!(gpu_keys.keys, cpu_keys);
    assert_eq!(
        reduce_bundle_keys(gpu_keys.keys),
        reduce_bundle_keys(cpu_keys)
    );
}

#[test]
fn invalid_shapes_fail_closed_before_dispatch() {
    assert!(matches!(
        GalaxyGpuRuntime::request(0),
        Err(GalaxyGpuError::Residency(_))
    ));
    let runtime = GalaxyGpuRuntime::request(GPU_BUDGET).unwrap();
    assert!(runtime.upload_positions(&[], 4).is_err());
    assert!(runtime.upload_positions(&[[0.0; 3]], 0).is_err());
    let resident = runtime.upload_positions(&[[0.0; 3], [1.0; 3]], 4).unwrap();
    assert!(resident.build_lod(&[0, 0], &[]).is_err());
}

fn positions(count: usize) -> Vec<[f32; 3]> {
    let mut state = 0x9e37_79b9_7f4a_7c15u64;
    (0..count)
        .map(|index| {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            let x = ((state & 0xffff) as f32 - 32_768.0) * 0.03125;
            let y = (((state >> 16) & 0xffff) as f32 - 32_768.0) * 0.015625;
            let z = (((state >> 32) & 0xffff) as f32 - 32_768.0) * 0.0078125;
            if index == 11 {
                [f32::NAN, y, z]
            } else if index == 29 {
                [x, f32::INFINITY, z]
            } else {
                [x, y, z]
            }
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

fn assert_aggregate_parity(actual: &[LodAggregate], expected: &[LodAggregate]) {
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        assert_eq!(actual.tile_id(), expected.tile_id());
        assert_eq!(actual.node_start, expected.node_start);
        assert_eq!(actual.node_count, expected.node_count);
        assert_eq!(actual.min, expected.min);
        assert_eq!(actual.max, expected.max);
        for axis in 0..3 {
            assert_close(actual.centroid[axis], expected.centroid[axis], 2.0e-5);
        }
        assert_close(actual.density, expected.density, 3.0e-5);
    }
}

fn assert_close(actual: f32, expected: f32, tolerance: f32) {
    let scale = expected.abs().max(1.0);
    assert!(
        (actual - expected).abs() <= tolerance * scale,
        "actual {actual} differs from expected {expected}"
    );
}

fn assert_exact_u64(label: &str, actual: &[u64], expected: &[u64]) {
    let mismatches = actual
        .iter()
        .zip(expected)
        .enumerate()
        .filter(|(_, (actual, expected))| actual != expected)
        .collect::<Vec<_>>();
    if let Some((index, (actual, expected))) = mismatches.first() {
        panic!(
            "{label} mismatch count {}, first at {index}: GPU {actual:#018x}, CPU {expected:#018x}, xor {:#018x}",
            mismatches.len(),
            **actual ^ **expected
        );
    }
}

fn assert_same_tile_prefix(actual: &[u64], expected: &[u64], bits: u32) {
    let shift = 63 - bits * 3;
    for (index, (actual, expected)) in actual.iter().zip(expected).enumerate() {
        assert_eq!(
            actual >> shift,
            expected >> shift,
            "tile prefix differs at node {index}"
        );
    }
}

struct Params {
    node_count: u32,
    edge_count: u32,
    family_count: u32,
    family_mask: u32,
    minimum_weight: u32,
    source_count: u32,
    wcc_iterations: u32,
    diffusion_iterations: u32,
    damping: f32,
    restart: f32,
    pad0: u32,
    pad1: u32,
}

struct Edge {
    source: u32,
    destination: u32,
    relation_family: u32,
    weight: u32,
}

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var<storage, read> edges: array<Edge>;
@group(0) @binding(2) var<storage, read> active_edges: array<u32>;
@group(0) @binding(3) var<storage, read> community_labels: array<u32>;
@group(0) @binding(4) var<storage, read_write> total_strength: array<atomic<u32>>;
@group(0) @binding(5) var<storage, read_write> boundary_degree: array<atomic<u32>>;
@group(0) @binding(6) var<storage, read_write> boundary_strength: array<atomic<u32>>;

@compute @workgroup_size(256)
fn accumulate_bridge_inputs(@builtin(global_invocation_id) gid: vec3<u32>) {
    let index = gid.x;
    if (index >= params.edge_count || active_edges[index] == 0u) {
        return;
    }
    let edge = edges[index];
    atomicAdd(&total_strength[edge.source], edge.weight);
    atomicAdd(&total_strength[edge.destination], edge.weight);
    let source_partition = community_labels[edge.source];
    let target_partition = community_labels[edge.destination];
    if (source_partition != 0xffffffffu
        && target_partition != 0xffffffffu
        && source_partition != target_partition) {
        atomicAdd(&boundary_degree[edge.source], 1u);
        atomicAdd(&boundary_degree[edge.destination], 1u);
        atomicAdd(&boundary_strength[edge.source], edge.weight);
        atomicAdd(&boundary_strength[edge.destination], edge.weight);
    }
}

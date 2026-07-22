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
@group(0) @binding(3) var<storage, read_write> out_degree: array<atomic<u32>>;
@group(0) @binding(4) var<storage, read_write> in_degree: array<atomic<u32>>;
@group(0) @binding(5) var<storage, read_write> incident_degree: array<atomic<u32>>;
@group(0) @binding(6) var<storage, read_write> family_histogram: array<atomic<u32>>;
@group(0) @binding(7) var<storage, read_write> out_strength: array<atomic<u32>>;

@compute @workgroup_size(256)
fn accumulate_degrees(@builtin(global_invocation_id) gid: vec3<u32>) {
    let index = gid.x;
    if (index >= params.edge_count || active_edges[index] == 0u) {
        return;
    }
    let edge = edges[index];
    atomicAdd(&out_degree[edge.source], 1u);
    atomicAdd(&in_degree[edge.destination], 1u);
    atomicAdd(&incident_degree[edge.source], 1u);
    atomicAdd(&incident_degree[edge.destination], 1u);
    atomicAdd(&family_histogram[edge.relation_family], 1u);
    atomicAdd(&out_strength[edge.source], edge.weight);
}

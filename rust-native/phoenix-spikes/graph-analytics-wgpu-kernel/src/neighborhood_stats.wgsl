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
@group(0) @binding(3) var<storage, read> incident_degree: array<u32>;
@group(0) @binding(4) var<storage, read_write> neighbor_degree_sum: array<atomic<u32>>;

@compute @workgroup_size(256)
fn accumulate_neighborhoods(@builtin(global_invocation_id) gid: vec3<u32>) {
    let index = gid.x;
    if (index >= params.edge_count || active_edges[index] == 0u) {
        return;
    }
    let edge = edges[index];
    atomicAdd(&neighbor_degree_sum[edge.source], incident_degree[edge.destination]);
    atomicAdd(&neighbor_degree_sum[edge.destination], incident_degree[edge.source]);
}

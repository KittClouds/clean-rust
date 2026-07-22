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
@group(0) @binding(2) var<storage, read> node_mask: array<u32>;
@group(0) @binding(3) var<storage, read_write> active_edges: array<atomic<u32>>;

@compute @workgroup_size(256)
fn classify_edges(@builtin(global_invocation_id) gid: vec3<u32>) {
    let index = gid.x;
    if (index >= params.edge_count) {
        return;
    }
    let edge = edges[index];
    let family_bit = 1u << edge.relation_family;
    let admitted = node_mask[edge.source] != 0u
        && node_mask[edge.destination] != 0u
        && edge.weight >= params.minimum_weight
        && (params.family_mask & family_bit) != 0u;
    atomicStore(&active_edges[index], select(0u, 1u, admitted));
}

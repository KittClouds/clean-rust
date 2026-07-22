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
@group(0) @binding(3) var<storage, read> incoming_offsets: array<u32>;
@group(0) @binding(4) var<storage, read> incoming_edges: array<u32>;
@group(0) @binding(5) var<storage, read> out_strength: array<u32>;
@group(0) @binding(6) var<storage, read> seeds: array<f32>;
@group(0) @binding(7) var<storage, read> rank_in: array<f32>;
@group(0) @binding(8) var<storage, read_write> rank_out: array<f32>;

@compute @workgroup_size(256)
fn diffuse(@builtin(global_invocation_id) gid: vec3<u32>) {
    let flat = gid.x;
    let total = params.node_count * params.source_count;
    if (flat >= total) {
        return;
    }
    let source = flat / params.node_count;
    let node = flat - source * params.node_count;
    var incoming_rank = 0.0;
    let start = incoming_offsets[node];
    let end = incoming_offsets[node + 1u];
    for (var cursor = start; cursor < end; cursor += 1u) {
        let edge_index = incoming_edges[cursor];
        if (active_edges[edge_index] == 0u) {
            continue;
        }
        let edge = edges[edge_index];
        let denominator = out_strength[edge.source];
        if (denominator != 0u) {
            incoming_rank += rank_in[source * params.node_count + edge.source]
                * f32(edge.weight) / f32(denominator);
        }
    }
    rank_out[flat] = params.restart * seeds[flat] + params.damping * incoming_rank;
}

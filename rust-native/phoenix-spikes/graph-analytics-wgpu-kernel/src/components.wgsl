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
@group(0) @binding(3) var<storage, read> active_edges: array<u32>;
@group(0) @binding(4) var<storage, read_write> labels: array<atomic<u32>>;
@group(0) @binding(5) var<storage, read_write> changed: atomic<u32>;

@compute @workgroup_size(256)
fn initialize_components(@builtin(global_invocation_id) gid: vec3<u32>) {
    let node = gid.x;
    if (node >= params.node_count) {
        return;
    }
    atomicStore(&labels[node], select(0xffffffffu, node, node_mask[node] != 0u));
}

@compute @workgroup_size(256)
fn hook_components(@builtin(global_invocation_id) gid: vec3<u32>) {
    let index = gid.x;
    if (index >= params.edge_count || active_edges[index] == 0u) {
        return;
    }
    let edge = edges[index];
    let left = atomicLoad(&labels[edge.source]);
    let right = atomicLoad(&labels[edge.destination]);
    let low = min(left, right);
    let high = max(left, right);
    if (high != 0xffffffffu && high != low) {
        atomicMin(&labels[high], low);
    }
}

@compute @workgroup_size(256)
fn compress_components(@builtin(global_invocation_id) gid: vec3<u32>) {
    let node = gid.x;
    if (node >= params.node_count) {
        return;
    }
    let parent = atomicLoad(&labels[node]);
    if (parent != 0xffffffffu) {
        atomicMin(&labels[node], atomicLoad(&labels[parent]));
    }
}

@compute @workgroup_size(256)
fn check_components(@builtin(global_invocation_id) gid: vec3<u32>) {
    let index = gid.x;
    if (index < params.node_count) {
        let parent = atomicLoad(&labels[index]);
        if (parent != 0xffffffffu && parent != atomicLoad(&labels[parent])) {
            atomicStore(&changed, 1u);
        }
    }
    if (index < params.edge_count && active_edges[index] != 0u) {
        let edge = edges[index];
        if (atomicLoad(&labels[edge.source]) != atomicLoad(&labels[edge.destination])) {
            atomicStore(&changed, 1u);
        }
    }
}

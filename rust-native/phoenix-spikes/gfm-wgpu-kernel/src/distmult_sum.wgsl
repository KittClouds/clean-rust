struct Params {
    nodes: u32,
    edges: u32,
    relation_count: u32,
    dim: u32,
    dispatch_width: u32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

@group(0) @binding(0) var<storage, read> offsets: array<u32>;
@group(0) @binding(1) var<storage, read> sources: array<u32>;
@group(0) @binding(2) var<storage, read> relation_ids: array<u32>;
@group(0) @binding(3) var<storage, read> input_state: array<f32>;
@group(0) @binding(4) var<storage, read> relation_state: array<f32>;
@group(0) @binding(5) var<storage, read> boundary: array<f32>;
@group(0) @binding(6) var<storage, read_write> output_state: array<f32>;
@group(0) @binding(7) var<storage, read> params: Params;

@compute @workgroup_size(128, 1, 1)
fn distmult_sum(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let destination = group.y * params.dispatch_width + group.x;
    if destination >= params.nodes {
        return;
    }
    let row_start = offsets[destination];
    let row_end = offsets[destination + 1u];
    var dimension = local.x;
    loop {
        if dimension >= params.dim {
            break;
        }
        let destination_value = destination * params.dim + dimension;
        var value = boundary[destination_value];
        var edge = row_start;
        loop {
            if edge >= row_end {
                break;
            }
            let source_value = sources[edge] * params.dim + dimension;
            let relation_value = relation_ids[edge] * params.dim + dimension;
            value = fma(input_state[source_value], relation_state[relation_value], value);
            edge = edge + 1u;
        }
        output_state[destination_value] = value;
        dimension = dimension + 128u;
    }
}

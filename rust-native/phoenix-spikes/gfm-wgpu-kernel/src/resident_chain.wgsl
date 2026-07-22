struct ChainParams {
    nodes: u32,
    edges: u32,
    relations: u32,
    dim: u32,
    layer: u32,
    dispatch_width: u32,
    score_dim: u32,
    entity_enabled: u32,
    dense_dispatch_height: u32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

struct TopKParams {
    items: u32,
    top_k: u32,
    dispatch_width: u32,
    _pad: u32,
}

@group(0) @binding(0) var<storage, read> csr_offsets: array<u32>;
@group(0) @binding(1) var<storage, read> csr_sources: array<u32>;
@group(0) @binding(2) var<storage, read> csr_relations: array<u32>;
@group(0) @binding(3) var<storage, read> aggregate_hidden: array<f32>;
@group(0) @binding(4) var<storage, read> layer_relations: array<f32>;
@group(0) @binding(5) var<storage, read> chain_boundary: array<f32>;
@group(0) @binding(6) var<storage, read_write> aggregate_output: array<f32>;
@group(0) @binding(7) var<storage, read> aggregate_params: ChainParams;

@compute @workgroup_size(128, 1, 1)
fn chain_distmult(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let destination = group.y * aggregate_params.dispatch_width + group.x;
    if destination >= aggregate_params.nodes {
        return;
    }
    let row_start = csr_offsets[destination];
    let row_end = csr_offsets[destination + 1u];
    let relation_layer = aggregate_params.layer * aggregate_params.relations * aggregate_params.dim;
    var dimension = local.x;
    loop {
        if dimension >= aggregate_params.dim {
            break;
        }
        let destination_value = destination * aggregate_params.dim + dimension;
        var value = chain_boundary[destination_value];
        var edge = row_start;
        loop {
            if edge >= row_end {
                break;
            }
            let source_value = csr_sources[edge] * aggregate_params.dim + dimension;
            let relation_value = relation_layer + csr_relations[edge] * aggregate_params.dim + dimension;
            value = fma(aggregate_hidden[source_value], layer_relations[relation_value], value);
            edge += 1u;
        }
        aggregate_output[destination_value] = value;
        dimension += 128u;
    }
}

var<workgroup> dense_old_tile: array<f32, 256>;
var<workgroup> dense_aggregate_tile: array<f32, 256>;
var<workgroup> dense_old_weight_tile: array<f32, 256>;
var<workgroup> dense_aggregate_weight_tile: array<f32, 256>;

@group(0) @binding(0) var<storage, read> dense_hidden: array<f32>;
@group(0) @binding(1) var<storage, read> dense_aggregate: array<f32>;
@group(0) @binding(2) var<storage, read> dense_old_weights: array<f32>;
@group(0) @binding(3) var<storage, read> dense_aggregate_weights: array<f32>;
@group(0) @binding(4) var<storage, read> dense_bias: array<f32>;
@group(0) @binding(5) var<storage, read_write> dense_output: array<f32>;
@group(0) @binding(6) var<storage, read> dense_params: ChainParams;

@compute @workgroup_size(16, 16, 1)
fn chain_dense_update(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let output_dimension = group.x * 16u + local.x;
    let node_tile = group.z * dense_params.dense_dispatch_height + group.y;
    let node = node_tile * 16u + local.y;
    let matrix_offset = dense_params.layer * dense_params.dim * dense_params.dim;
    var value = 0.0;
    if output_dimension < dense_params.dim {
        value = dense_bias[dense_params.layer * dense_params.dim + output_dimension];
    }
    var tile_start = 0u;
    loop {
        if tile_start >= dense_params.dim {
            break;
        }
        let input_dimension = tile_start + local.x;
        let tile_slot = local.y * 16u + local.x;
        if node < dense_params.nodes && input_dimension < dense_params.dim {
            let input_value = node * dense_params.dim + input_dimension;
            dense_old_tile[tile_slot] = dense_hidden[input_value];
            dense_aggregate_tile[tile_slot] = dense_aggregate[input_value];
        } else {
            dense_old_tile[tile_slot] = 0.0;
            dense_aggregate_tile[tile_slot] = 0.0;
        }
        let weight_input = tile_start + local.y;
        if output_dimension < dense_params.dim && weight_input < dense_params.dim {
            let weight = matrix_offset + output_dimension * dense_params.dim + weight_input;
            dense_old_weight_tile[tile_slot] = dense_old_weights[weight];
            dense_aggregate_weight_tile[tile_slot] = dense_aggregate_weights[weight];
        } else {
            dense_old_weight_tile[tile_slot] = 0.0;
            dense_aggregate_weight_tile[tile_slot] = 0.0;
        }
        workgroupBarrier();
        for (var axis = 0u; axis < 16u; axis += 1u) {
            value = fma(
                dense_old_tile[local.y * 16u + axis],
                dense_old_weight_tile[axis * 16u + local.x],
                value,
            );
            value = fma(
                dense_aggregate_tile[local.y * 16u + axis],
                dense_aggregate_weight_tile[axis * 16u + local.x],
                value,
            );
        }
        workgroupBarrier();
        tile_start += 16u;
    }
    if node < dense_params.nodes && output_dimension < dense_params.dim {
        dense_output[node * dense_params.dim + output_dimension] = value;
    }
}

var<workgroup> norm_sum: array<f32, 128>;

@group(0) @binding(0) var<storage, read> norm_hidden: array<f32>;
@group(0) @binding(1) var<storage, read> norm_update: array<f32>;
@group(0) @binding(2) var<storage, read> norm_scale: array<f32>;
@group(0) @binding(3) var<storage, read> norm_bias: array<f32>;
@group(0) @binding(4) var<storage, read_write> norm_output: array<f32>;
@group(0) @binding(5) var<storage, read> norm_params: ChainParams;

@compute @workgroup_size(128, 1, 1)
fn chain_norm_residual(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let node = group.y * norm_params.dispatch_width + group.x;
    if node >= norm_params.nodes {
        return;
    }
    var local_sum = 0.0;
    var dimension = local.x;
    loop {
        if dimension >= norm_params.dim { break; }
        local_sum += norm_update[node * norm_params.dim + dimension];
        dimension += 128u;
    }
    norm_sum[local.x] = local_sum;
    workgroupBarrier();
    reduce_norm_sum(local.x);
    let mean = norm_sum[0] / f32(norm_params.dim);
    workgroupBarrier();
    var variance_sum = 0.0;
    dimension = local.x;
    loop {
        if dimension >= norm_params.dim { break; }
        let centered = norm_update[node * norm_params.dim + dimension] - mean;
        variance_sum = fma(centered, centered, variance_sum);
        dimension += 128u;
    }
    norm_sum[local.x] = variance_sum;
    workgroupBarrier();
    reduce_norm_sum(local.x);
    let inverse_std = inverseSqrt(norm_sum[0] / f32(norm_params.dim) + 0.00001);
    dimension = local.x;
    loop {
        if dimension >= norm_params.dim { break; }
        let index = node * norm_params.dim + dimension;
        let parameter = norm_params.layer * norm_params.dim + dimension;
        let normalized = (norm_update[index] - mean) * inverse_std;
        let activated = max(fma(normalized, norm_scale[parameter], norm_bias[parameter]), 0.0);
        norm_output[index] = norm_hidden[index] + activated;
        dimension += 128u;
    }
}

@group(0) @binding(0) var<storage, read> score_hidden: array<f32>;
@group(0) @binding(1) var<storage, read> score_entity: array<f32>;
@group(0) @binding(2) var<storage, read> score_hidden_weight: array<f32>;
@group(0) @binding(3) var<storage, read> score_entity_weight: array<f32>;
@group(0) @binding(4) var<storage, read> score_query_term: array<f32>;
@group(0) @binding(5) var<storage, read> score_bias: array<f32>;
@group(0) @binding(6) var<storage, read_write> score_activation: array<f32>;
@group(0) @binding(7) var<storage, read> score_params: ChainParams;

@compute @workgroup_size(16, 16, 1)
fn chain_score_dense(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let output_dimension = group.x * 16u + local.x;
    let node_tile = group.z * score_params.dense_dispatch_height + group.y;
    let node = node_tile * 16u + local.y;
    if node >= score_params.nodes || output_dimension >= score_params.score_dim { return; }
    var value = score_query_term[output_dimension] + score_bias[output_dimension];
    let weight = output_dimension * score_params.dim;
    let row = node * score_params.dim;
    for (var axis = 0u; axis < score_params.dim; axis += 1u) {
        value = fma(score_hidden[row + axis], score_hidden_weight[weight + axis], value);
        if score_params.entity_enabled != 0u {
            value = fma(score_entity[row + axis], score_entity_weight[weight + axis], value);
        }
    }
    score_activation[node * score_params.score_dim + output_dimension] = max(value, 0.0);
}

var<workgroup> score_sum: array<f32, 128>;

@group(0) @binding(0) var<storage, read> logit_activation: array<f32>;
@group(0) @binding(1) var<storage, read> logit_weight: array<f32>;
@group(0) @binding(2) var<storage, read> logit_bias: array<f32>;
@group(0) @binding(3) var<storage, read_write> logits: array<f32>;
@group(0) @binding(4) var<storage, read> logit_params: ChainParams;

@compute @workgroup_size(128, 1, 1)
fn chain_score_logits(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let node = group.y * logit_params.dispatch_width + group.x;
    if node >= logit_params.nodes { return; }
    var value = 0.0;
    var dimension = local.x;
    loop {
        if dimension >= logit_params.score_dim { break; }
        value = fma(
            logit_activation[node * logit_params.score_dim + dimension],
            logit_weight[dimension],
            value,
        );
        dimension += 128u;
    }
    score_sum[local.x] = value;
    workgroupBarrier();
    reduce_score_sum(local.x);
    if local.x == 0u { logits[node] = score_sum[0] + logit_bias[0]; }
}

@group(0) @binding(0) var<storage, read> top_input_scores: array<f32>;
@group(0) @binding(1) var<storage, read> top_input_ids: array<u32>;
@group(0) @binding(2) var<storage, read_write> top_output_scores: array<f32>;
@group(0) @binding(3) var<storage, read_write> top_output_ids: array<u32>;
@group(0) @binding(4) var<storage, read> top_params: TopKParams;

var<workgroup> top_scores: array<f32, 256>;
var<workgroup> top_ids: array<u32, 256>;

@compute @workgroup_size(256, 1, 1)
fn chain_reduce_topk(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let block = group.y * top_params.dispatch_width + group.x;
    let input_index = block * 256u + local.x;
    if input_index < top_params.items {
        top_scores[local.x] = finite_score(top_input_scores[input_index]);
        top_ids[local.x] = top_input_ids[input_index];
    } else {
        top_scores[local.x] = bitcast<f32>(0xff800000u);
        top_ids[local.x] = 0xffffffffu;
    }
    workgroupBarrier();
    var width = 2u;
    loop {
        if width > 256u { break; }
        var stride = width / 2u;
        loop {
            if stride == 0u { break; }
            let partner = local.x ^ stride;
            if partner > local.x {
                let descending = (local.x & width) == 0u;
                let partner_better = better(
                    top_scores[partner], top_ids[partner], top_scores[local.x], top_ids[local.x],
                );
                let local_better = better(
                    top_scores[local.x], top_ids[local.x], top_scores[partner], top_ids[partner],
                );
                if (descending && partner_better) || (!descending && local_better) {
                    let saved_score = top_scores[local.x];
                    let saved_id = top_ids[local.x];
                    top_scores[local.x] = top_scores[partner];
                    top_ids[local.x] = top_ids[partner];
                    top_scores[partner] = saved_score;
                    top_ids[partner] = saved_id;
                }
            }
            workgroupBarrier();
            stride /= 2u;
        }
        width *= 2u;
    }
    if local.x < top_params.top_k {
        let output_index = block * top_params.top_k + local.x;
        top_output_scores[output_index] = top_scores[local.x];
        top_output_ids[output_index] = top_ids[local.x];
    }
}

fn reduce_norm_sum(lane: u32) {
    var width = 64u;
    loop {
        if width == 0u { break; }
        if lane < width { norm_sum[lane] += norm_sum[lane + width]; }
        workgroupBarrier();
        width /= 2u;
    }
}

fn reduce_score_sum(lane: u32) {
    var width = 64u;
    loop {
        if width == 0u { break; }
        if lane < width { score_sum[lane] += score_sum[lane + width]; }
        workgroupBarrier();
        width /= 2u;
    }
}

fn finite_score(value: f32) -> f32 {
    let magnitude = bitcast<u32>(value) & 0x7fffffffu;
    return select(value, bitcast<f32>(0xff800000u), magnitude >= 0x7f800000u);
}

fn better(left_score: f32, left_id: u32, right_score: f32, right_id: u32) -> bool {
    return left_score > right_score || (left_score == right_score && left_id < right_id);
}

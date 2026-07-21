const WORKGROUP_WIDTH: u32 = 128u;

struct Params {
    rows: u32,
    dimensions: u32,
    packed_words_per_row: u32,
    dispatch_width: u32,
}

@group(0) @binding(0) var<storage, read> input_values: array<f32>;
@group(0) @binding(1) var<storage, read_write> normalized_values: array<f32>;
@group(0) @binding(2) var<storage, read_write> quantized_words: array<u32>;
@group(0) @binding(3) var<storage, read_write> row_scales: array<f32>;
@group(0) @binding(4) var<storage, read> params: Params;

var<workgroup> norm_parts: array<f32, 128>;
var<workgroup> maximum_parts: array<f32, 128>;

fn quantized_byte(value: f32, scale: f32) -> u32 {
    let quantized = i32(round(clamp(value / scale, -127.0, 127.0)));
    return bitcast<u32>(quantized) & 0xffu;
}

@compute @workgroup_size(128)
fn normalize_quantize(
    @builtin(workgroup_id) workgroup: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let row = workgroup.x + workgroup.y * params.dispatch_width;
    if (row >= params.rows) {
        return;
    }
    let row_base = row * params.dimensions;
    var sum = 0.0;
    var maximum = 0.0;
    var dimension = local.x;
    while (dimension < params.dimensions) {
        let value = input_values[row_base + dimension];
        sum = sum + value * value;
        maximum = max(maximum, abs(value));
        dimension = dimension + WORKGROUP_WIDTH;
    }
    norm_parts[local.x] = sum;
    maximum_parts[local.x] = maximum;
    workgroupBarrier();

    var stride = WORKGROUP_WIDTH / 2u;
    while (stride > 0u) {
        if (local.x < stride) {
            norm_parts[local.x] = norm_parts[local.x] + norm_parts[local.x + stride];
            maximum_parts[local.x] = max(maximum_parts[local.x], maximum_parts[local.x + stride]);
        }
        workgroupBarrier();
        stride = stride / 2u;
    }
    let inverse_norm = inverseSqrt(norm_parts[0]);
    let scale = maximum_parts[0] * inverse_norm / 127.0;
    if (local.x == 0u) {
        row_scales[row] = scale;
    }

    dimension = local.x;
    while (dimension < params.dimensions) {
        normalized_values[row_base + dimension] = input_values[row_base + dimension] * inverse_norm;
        dimension = dimension + WORKGROUP_WIDTH;
    }
    var packed_index = local.x;
    while (packed_index < params.packed_words_per_row) {
        var word = 0u;
        var lane = 0u;
        while (lane < 4u) {
            let scalar_index = packed_index * 4u + lane;
            if (scalar_index < params.dimensions) {
                let normalized = input_values[row_base + scalar_index] * inverse_norm;
                word = word | (quantized_byte(normalized, scale) << (lane * 8u));
            }
            lane = lane + 1u;
        }
        quantized_words[row * params.packed_words_per_row + packed_index] = word;
        packed_index = packed_index + WORKGROUP_WIDTH;
    }
}

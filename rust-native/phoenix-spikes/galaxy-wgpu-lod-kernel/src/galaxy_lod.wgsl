struct SpatialParams {
    nodes: u32,
    tile_bits: u32,
    dispatch_groups_x: u32,
    _pad: u32,
}

struct Bounds {
    min_x: atomic<u32>,
    min_y: atomic<u32>,
    min_z: atomic<u32>,
    max_x: atomic<u32>,
    max_y: atomic<u32>,
    max_z: atomic<u32>,
}

struct U64Pair {
    lo: u32,
    hi: u32,
}

struct LodRange {
    start: u32,
    end: u32,
    tile_lo: u32,
    tile_hi: u32,
}

struct LodAggregate {
    tile_lo: u32,
    tile_hi: u32,
    node_start: u32,
    node_count: u32,
    centroid_x: f32,
    centroid_y: f32,
    centroid_z: f32,
    density: f32,
    min_x: f32,
    min_y: f32,
    min_z: f32,
    min_pad: f32,
    max_x: f32,
    max_y: f32,
    max_z: f32,
    max_pad: f32,
}

struct LodParams {
    nodes: u32,
    ranges: u32,
    dispatch_groups_x: u32,
    _pad: u32,
}

struct EdgeInput {
    source: u32,
    target_node: u32,
    weight_millis: u32,
    flags: u32,
}

struct EdgeParams {
    edges: u32,
    nodes: u32,
    dispatch_groups_x: u32,
    _pad: u32,
}

struct RawBundleKey {
    source_lod_node: u32,
    target_lod_node: u32,
    weight_millis: u32,
    flags: u32,
}

@group(0) @binding(0) var<storage, read_write> reset_bounds: Bounds;

@compute @workgroup_size(1)
fn reset_position_bounds() {
    let positive_max = ordered_bits(bitcast<f32>(0x7f7fffffu));
    let negative_max = ordered_bits(bitcast<f32>(0xff7fffffu));
    atomicStore(&reset_bounds.min_x, positive_max);
    atomicStore(&reset_bounds.min_y, positive_max);
    atomicStore(&reset_bounds.min_z, positive_max);
    atomicStore(&reset_bounds.max_x, negative_max);
    atomicStore(&reset_bounds.max_y, negative_max);
    atomicStore(&reset_bounds.max_z, negative_max);
}

@group(0) @binding(0) var<storage, read> bound_positions: array<f32>;
@group(0) @binding(1) var<storage, read_write> position_bounds: Bounds;
@group(0) @binding(2) var<storage, read> bound_params: SpatialParams;

@compute @workgroup_size(256)
fn accumulate_position_bounds(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let node = linear_invocation(group, local.x, bound_params.dispatch_groups_x);
    if node >= bound_params.nodes {
        return;
    }
    let offset = node * 3u;
    let x = finite_value(bound_positions[offset]);
    let y = finite_value(bound_positions[offset + 1u]);
    let z = finite_value(bound_positions[offset + 2u]);
    atomicMin(&position_bounds.min_x, ordered_bits(x));
    atomicMin(&position_bounds.min_y, ordered_bits(y));
    atomicMin(&position_bounds.min_z, ordered_bits(z));
    atomicMax(&position_bounds.max_x, ordered_bits(x));
    atomicMax(&position_bounds.max_y, ordered_bits(y));
    atomicMax(&position_bounds.max_z, ordered_bits(z));
}

@group(0) @binding(0) var<storage, read> morton_positions: array<f32>;
@group(0) @binding(1) var<storage, read_write> morton_bounds: Bounds;
@group(0) @binding(2) var<storage, read_write> morton_keys: array<U64Pair>;
@group(0) @binding(3) var<storage, read_write> node_tiles: array<U64Pair>;
@group(0) @binding(4) var<storage, read> morton_params: SpatialParams;

@compute @workgroup_size(256)
fn build_morton_keys(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let node = linear_invocation(group, local.x, morton_params.dispatch_groups_x);
    if node >= morton_params.nodes {
        return;
    }
    let minimum = vec3<f32>(
        ordered_float(atomicLoad(&morton_bounds.min_x)),
        ordered_float(atomicLoad(&morton_bounds.min_y)),
        ordered_float(atomicLoad(&morton_bounds.min_z)),
    );
    let maximum = vec3<f32>(
        ordered_float(atomicLoad(&morton_bounds.max_x)),
        ordered_float(atomicLoad(&morton_bounds.max_y)),
        ordered_float(atomicLoad(&morton_bounds.max_z)),
    );
    let offset = node * 3u;
    let position = vec3<f32>(
        finite_value(morton_positions[offset]),
        finite_value(morton_positions[offset + 1u]),
        finite_value(morton_positions[offset + 2u]),
    );
    var key = U64Pair(0u, 0u);
    key = or_pair(key, interleave_axis(quantize(position.x, minimum.x, maximum.x), 0u));
    key = or_pair(key, interleave_axis(quantize(position.y, minimum.y, maximum.y), 1u));
    key = or_pair(key, interleave_axis(quantize(position.z, minimum.z, maximum.z), 2u));
    morton_keys[node] = key;
    node_tiles[node] = shift_right_pair(key, 63u - morton_params.tile_bits * 3u);
}

var<workgroup> sum_x: array<f32, 256>;
var<workgroup> sum_y: array<f32, 256>;
var<workgroup> sum_z: array<f32, 256>;
var<workgroup> minimum_x: array<f32, 256>;
var<workgroup> minimum_y: array<f32, 256>;
var<workgroup> minimum_z: array<f32, 256>;
var<workgroup> maximum_x: array<f32, 256>;
var<workgroup> maximum_y: array<f32, 256>;
var<workgroup> maximum_z: array<f32, 256>;

@group(0) @binding(0) var<storage, read> lod_positions: array<f32>;
@group(0) @binding(1) var<storage, read> spatial_order: array<u32>;
@group(0) @binding(2) var<storage, read> lod_ranges: array<LodRange>;
@group(0) @binding(3) var<storage, read_write> lod_aggregates: array<LodAggregate>;
@group(0) @binding(4) var<storage, read_write> node_to_lod: array<u32>;
@group(0) @binding(5) var<storage, read> lod_params: LodParams;

@compute @workgroup_size(256)
fn aggregate_lod(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let range_index = group.y * lod_params.dispatch_groups_x + group.x;
    if range_index >= lod_params.ranges {
        return;
    }
    let range = lod_ranges[range_index];
    var sx = 0.0;
    var sy = 0.0;
    var sz = 0.0;
    var minx = bitcast<f32>(0x7f7fffffu);
    var miny = minx;
    var minz = minx;
    var maxx = bitcast<f32>(0xff7fffffu);
    var maxy = maxx;
    var maxz = maxx;
    var cursor = range.start + local.x;
    loop {
        if cursor >= range.end {
            break;
        }
        let node = spatial_order[cursor];
        let offset = node * 3u;
        let x = finite_value(lod_positions[offset]);
        let y = finite_value(lod_positions[offset + 1u]);
        let z = finite_value(lod_positions[offset + 2u]);
        sx += x;
        sy += y;
        sz += z;
        minx = min(minx, x);
        miny = min(miny, y);
        minz = min(minz, z);
        maxx = max(maxx, x);
        maxy = max(maxy, y);
        maxz = max(maxz, z);
        node_to_lod[node] = range_index;
        cursor += 256u;
    }
    sum_x[local.x] = sx;
    sum_y[local.x] = sy;
    sum_z[local.x] = sz;
    minimum_x[local.x] = minx;
    minimum_y[local.x] = miny;
    minimum_z[local.x] = minz;
    maximum_x[local.x] = maxx;
    maximum_y[local.x] = maxy;
    maximum_z[local.x] = maxz;
    workgroupBarrier();
    var width = 128u;
    loop {
        if width == 0u {
            break;
        }
        if local.x < width {
            sum_x[local.x] += sum_x[local.x + width];
            sum_y[local.x] += sum_y[local.x + width];
            sum_z[local.x] += sum_z[local.x + width];
            minimum_x[local.x] = min(minimum_x[local.x], minimum_x[local.x + width]);
            minimum_y[local.x] = min(minimum_y[local.x], minimum_y[local.x + width]);
            minimum_z[local.x] = min(minimum_z[local.x], minimum_z[local.x + width]);
            maximum_x[local.x] = max(maximum_x[local.x], maximum_x[local.x + width]);
            maximum_y[local.x] = max(maximum_y[local.x], maximum_y[local.x + width]);
            maximum_z[local.x] = max(maximum_z[local.x], maximum_z[local.x + width]);
        }
        workgroupBarrier();
        width = width / 2u;
    }
    if local.x == 0u {
        let count = range.end - range.start;
        let span = max(
            vec3<f32>(maximum_x[0] - minimum_x[0], maximum_y[0] - minimum_y[0], maximum_z[0] - minimum_z[0]),
            vec3<f32>(0.001),
        );
        let volume = max(span.x * span.y * span.z, 0.000001);
        lod_aggregates[range_index] = LodAggregate(
            range.tile_lo,
            range.tile_hi,
            range.start,
            count,
            sum_x[0] / f32(count),
            sum_y[0] / f32(count),
            sum_z[0] / f32(count),
            f32(count) / volume,
            minimum_x[0],
            minimum_y[0],
            minimum_z[0],
            0.0,
            maximum_x[0],
            maximum_y[0],
            maximum_z[0],
            0.0,
        );
    }
}

@group(0) @binding(0) var<storage, read> remap_edges: array<EdgeInput>;
@group(0) @binding(1) var<storage, read> remap_node_to_lod: array<u32>;
@group(0) @binding(2) var<storage, read_write> raw_bundle_keys: array<RawBundleKey>;
@group(0) @binding(3) var<storage, read> edge_params: EdgeParams;

@compute @workgroup_size(256)
fn remap_edge_bundles(
    @builtin(workgroup_id) group: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let edge_index = linear_invocation(group, local.x, edge_params.dispatch_groups_x);
    if edge_index >= edge_params.edges {
        return;
    }
    let edge = remap_edges[edge_index];
    let source = remap_node_to_lod[edge.source];
    let target_lod = remap_node_to_lod[edge.target_node];
    raw_bundle_keys[edge_index] = RawBundleKey(
        min(source, target_lod),
        max(source, target_lod),
        edge.weight_millis,
        edge.flags,
    );
}

fn linear_invocation(group: vec3<u32>, local_x: u32, groups_x: u32) -> u32 {
    return (group.y * groups_x + group.x) * 256u + local_x;
}

fn finite_value(value: f32) -> f32 {
    let magnitude = bitcast<u32>(value) & 0x7fffffffu;
    return select(value, 0.0, magnitude >= 0x7f800000u);
}

fn ordered_bits(value: f32) -> u32 {
    let bits = bitcast<u32>(value);
    return select(~bits, bits ^ 0x80000000u, (bits & 0x80000000u) == 0u);
}

fn ordered_float(value: u32) -> f32 {
    let bits = select(value ^ 0x80000000u, ~value, (value & 0x80000000u) == 0u);
    return bitcast<f32>(bits);
}

fn quantize(value: f32, minimum: f32, maximum: f32) -> u32 {
    let span = max(abs(maximum - minimum), bitcast<f32>(0x34000000u));
    let unit = clamp((value - minimum) / span, 0.0, 1.0);
    return u32(floor(unit * 2097151.0 + 0.5));
}

fn interleave_axis(value: u32, axis: u32) -> U64Pair {
    var result = U64Pair(0u, 0u);
    var bit = 0u;
    loop {
        if bit >= 21u {
            break;
        }
        if ((value >> bit) & 1u) != 0u {
            let target_bit = bit * 3u + axis;
            if target_bit < 32u {
                result.lo |= 1u << target_bit;
            } else {
                result.hi |= 1u << (target_bit - 32u);
            }
        }
        bit += 1u;
    }
    return result;
}

fn or_pair(left: U64Pair, right: U64Pair) -> U64Pair {
    return U64Pair(left.lo | right.lo, left.hi | right.hi);
}

fn shift_right_pair(value: U64Pair, amount: u32) -> U64Pair {
    if amount == 0u {
        return value;
    }
    if amount < 32u {
        return U64Pair((value.lo >> amount) | (value.hi << (32u - amount)), value.hi >> amount);
    }
    if amount < 64u {
        return U64Pair(value.hi >> (amount - 32u), 0u);
    }
    return U64Pair(0u, 0u);
}

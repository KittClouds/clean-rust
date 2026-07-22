use crate::{
    BundleRecord, EdgeInput, GalaxyGpuError, LodAggregate, LodOutput, LodRange, RawBundleKey,
    SpatialOutput, StageTiming,
};

pub fn cpu_spatial(positions: &[[f32; 3]], tile_bits: u8) -> Result<SpatialOutput, GalaxyGpuError> {
    validate_tile_bits(tile_bits)?;
    if positions.is_empty() {
        return Err(GalaxyGpuError::Input("positions are empty".to_owned()));
    }
    let (bounds_min, bounds_max) = position_bounds(positions);
    let morton_keys = positions
        .iter()
        .map(|position| morton_key(finite_position(*position), bounds_min, bounds_max))
        .collect::<Vec<_>>();
    let shift = 63 - u32::from(tile_bits) * 3;
    let node_tiles = morton_keys.iter().map(|key| key >> shift).collect();
    Ok(SpatialOutput {
        bounds_min,
        bounds_max,
        morton_keys,
        node_tiles,
        timing: StageTiming::default(),
    })
}

pub fn build_lod_ranges(
    keys: &[u64],
    order: &[u32],
    bits: u8,
) -> Result<Vec<LodRange>, GalaxyGpuError> {
    validate_tile_bits(bits)?;
    validate_order(keys.len(), order)?;
    let shift = 63 - u32::from(bits) * 3;
    let mut ranges = Vec::new();
    let mut cursor = 0usize;
    while cursor < order.len() {
        let start = cursor;
        let tile = keys[order[cursor] as usize] >> shift;
        cursor += 1;
        while cursor < order.len() && keys[order[cursor] as usize] >> shift == tile {
            cursor += 1;
        }
        ranges.push(LodRange {
            start: start as u32,
            end: cursor as u32,
            tile_lo: tile as u32,
            tile_hi: (tile >> 32) as u32,
        });
    }
    Ok(ranges)
}

pub fn cpu_lod(
    positions: &[[f32; 3]],
    order: &[u32],
    ranges: &[LodRange],
) -> Result<LodOutput, GalaxyGpuError> {
    validate_order(positions.len(), order)?;
    validate_ranges(order.len(), ranges)?;
    let mut node_to_lod = vec![0; positions.len()];
    let mut aggregates = Vec::with_capacity(ranges.len());
    for (lod, range) in ranges.iter().copied().enumerate() {
        let mut sum = [0f64; 3];
        let mut min = [f32::INFINITY; 3];
        let mut max = [f32::NEG_INFINITY; 3];
        for &node in &order[range.start as usize..range.end as usize] {
            let position = finite_position(positions[node as usize]);
            for axis in 0..3 {
                sum[axis] += f64::from(position[axis]);
                min[axis] = min[axis].min(position[axis]);
                max[axis] = max[axis].max(position[axis]);
            }
            node_to_lod[node as usize] = lod as u32;
        }
        let count = range.end - range.start;
        let volume = ((max[0] - min[0]).abs().max(0.001)
            * (max[1] - min[1]).abs().max(0.001)
            * (max[2] - min[2]).abs().max(0.001))
        .max(0.000_001);
        aggregates.push(LodAggregate {
            tile_lo: range.tile_lo,
            tile_hi: range.tile_hi,
            node_start: range.start,
            node_count: count,
            centroid: [
                (sum[0] / f64::from(count)) as f32,
                (sum[1] / f64::from(count)) as f32,
                (sum[2] / f64::from(count)) as f32,
            ],
            density: count as f32 / volume,
            min,
            min_pad: 0.0,
            max,
            max_pad: 0.0,
        });
    }
    Ok(LodOutput {
        aggregates,
        node_to_lod,
        timing: StageTiming::default(),
    })
}

pub fn cpu_remap_edges(
    edges: &[EdgeInput],
    node_to_lod: &[u32],
) -> Result<Vec<RawBundleKey>, GalaxyGpuError> {
    validate_edges(edges, node_to_lod.len())?;
    Ok(edges
        .iter()
        .map(|edge| {
            let source = node_to_lod[edge.source as usize];
            let target = node_to_lod[edge.target as usize];
            RawBundleKey {
                source_lod_node: source.min(target),
                target_lod_node: source.max(target),
                weight_millis: edge.weight_millis,
                flags: edge.flags,
            }
        })
        .collect())
}

pub fn reduce_bundle_keys(mut keys: Vec<RawBundleKey>) -> Vec<BundleRecord> {
    keys.sort_unstable_by_key(|key| (key.source_lod_node, key.target_lod_node));
    let mut bundles: Vec<BundleRecord> = Vec::new();
    for key in keys {
        if let Some(last) = bundles.last_mut()
            && (last.source_lod_node, last.target_lod_node)
                == (key.source_lod_node, key.target_lod_node)
        {
            last.edge_count = last.edge_count.saturating_add(1);
            last.weight_millis = last
                .weight_millis
                .saturating_add(u64::from(key.weight_millis));
            last.flags |= key.flags;
            continue;
        }
        bundles.push(BundleRecord {
            source_lod_node: key.source_lod_node,
            target_lod_node: key.target_lod_node,
            edge_count: 1,
            flags: key.flags,
            weight_millis: u64::from(key.weight_millis),
        });
    }
    bundles
}

pub(crate) fn validate_tile_bits(bits: u8) -> Result<(), GalaxyGpuError> {
    if !(1..=16).contains(&bits) {
        return Err(GalaxyGpuError::Input(
            "tile bits must be in 1..=16".to_owned(),
        ));
    }
    Ok(())
}

pub(crate) fn validate_order(nodes: usize, order: &[u32]) -> Result<(), GalaxyGpuError> {
    if order.len() != nodes {
        return Err(GalaxyGpuError::Input(
            "spatial order does not cover every node".to_owned(),
        ));
    }
    let mut seen = vec![false; nodes];
    for &node in order {
        let node = node as usize;
        if node >= nodes || std::mem::replace(&mut seen[node], true) {
            return Err(GalaxyGpuError::Input(
                "spatial order is not a node permutation".to_owned(),
            ));
        }
    }
    Ok(())
}

pub(crate) fn validate_ranges(nodes: usize, ranges: &[LodRange]) -> Result<(), GalaxyGpuError> {
    let mut cursor = 0u32;
    for range in ranges {
        if range.start != cursor || range.end <= range.start || range.end as usize > nodes {
            return Err(GalaxyGpuError::Input(
                "LOD ranges must be nonempty and contiguous".to_owned(),
            ));
        }
        cursor = range.end;
    }
    if cursor as usize != nodes {
        return Err(GalaxyGpuError::Input(
            "LOD ranges do not cover every ordered node".to_owned(),
        ));
    }
    Ok(())
}

pub(crate) fn validate_edges(edges: &[EdgeInput], nodes: usize) -> Result<(), GalaxyGpuError> {
    if edges
        .iter()
        .any(|edge| edge.source as usize >= nodes || edge.target as usize >= nodes)
    {
        return Err(GalaxyGpuError::Input(
            "edge endpoint exceeds node-to-LOD extent".to_owned(),
        ));
    }
    Ok(())
}

fn position_bounds(positions: &[[f32; 3]]) -> ([f32; 3], [f32; 3]) {
    let mut min = [f32::INFINITY; 3];
    let mut max = [f32::NEG_INFINITY; 3];
    for position in positions {
        let position = finite_position(*position);
        for axis in 0..3 {
            min[axis] = min[axis].min(position[axis]);
            max[axis] = max[axis].max(position[axis]);
        }
    }
    (min, max)
}

fn finite_position(mut position: [f32; 3]) -> [f32; 3] {
    for value in &mut position {
        if !value.is_finite() {
            *value = 0.0;
        }
    }
    position
}

fn morton_key(position: [f32; 3], min: [f32; 3], max: [f32; 3]) -> u64 {
    let quantize = |value: f32, axis: usize| {
        let span = (max[axis] - min[axis]).abs().max(f32::EPSILON);
        let unit = ((value - min[axis]) / span).clamp(0.0, 1.0);
        (unit * ((1u32 << 21) - 1) as f32).round() as u32
    };
    split_by_three(quantize(position[0], 0))
        | (split_by_three(quantize(position[1], 1)) << 1)
        | (split_by_three(quantize(position[2], 2)) << 2)
}

fn split_by_three(value: u32) -> u64 {
    let mut value = u64::from(value & 0x1f_ffff);
    value = (value | value << 32) & 0x001f_0000_0000_ffff;
    value = (value | value << 16) & 0x001f_0000_ff00_00ff;
    value = (value | value << 8) & 0x100f_00f0_0f00_f00f;
    value = (value | value << 4) & 0x10c3_0c30_c30c_30c3;
    value = (value | value << 2) & 0x1249_2492_4924_9249;
    value
}

use bytemuck::{Pod, Zeroable};

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Pod, Zeroable)]
pub struct EdgeInput {
    pub source: u32,
    pub target: u32,
    pub weight_millis: u32,
    pub flags: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Ord, PartialOrd, Pod, Zeroable)]
pub struct RawBundleKey {
    pub source_lod_node: u32,
    pub target_lod_node: u32,
    pub weight_millis: u32,
    pub flags: u32,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct BundleRecord {
    pub source_lod_node: u32,
    pub target_lod_node: u32,
    pub edge_count: u32,
    pub flags: u32,
    pub weight_millis: u64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Pod, Zeroable)]
pub struct LodRange {
    pub start: u32,
    pub end: u32,
    pub tile_lo: u32,
    pub tile_hi: u32,
}

impl LodRange {
    pub fn tile_id(self) -> u64 {
        u64::from(self.tile_lo) | (u64::from(self.tile_hi) << 32)
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Pod, Zeroable)]
pub struct LodAggregate {
    pub tile_lo: u32,
    pub tile_hi: u32,
    pub node_start: u32,
    pub node_count: u32,
    pub centroid: [f32; 3],
    pub density: f32,
    pub min: [f32; 3],
    pub min_pad: f32,
    pub max: [f32; 3],
    pub max_pad: f32,
}

impl LodAggregate {
    pub fn tile_id(self) -> u64 {
        u64::from(self.tile_lo) | (u64::from(self.tile_hi) << 32)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct SpatialOutput {
    pub bounds_min: [f32; 3],
    pub bounds_max: [f32; 3],
    pub morton_keys: Vec<u64>,
    pub node_tiles: Vec<u64>,
    pub timing: StageTiming,
}

#[derive(Clone, Debug, PartialEq)]
pub struct LodOutput {
    pub aggregates: Vec<LodAggregate>,
    pub node_to_lod: Vec<u32>,
    pub timing: StageTiming,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BundleKeyOutput {
    pub keys: Vec<RawBundleKey>,
    pub timing: StageTiming,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct StageTiming {
    pub prepare_micros: u64,
    pub dispatch_micros: u64,
    pub readback_micros: u64,
    pub gpu_bytes: u64,
}

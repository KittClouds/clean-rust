use serde::{Deserialize, Serialize};
use zerocopy::{AsBytes, FromBytes, FromZeroes};

pub const GALAXY_STORE_SCHEMA_VERSION: u16 = 1;
pub const GALAXY_PAGE_MAGIC: [u8; 8] = *b"PHXGGP01";
pub const GALAXY_PAGE_HEADER_BYTES: usize = 64;

#[repr(u16)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GalaxyManifoldKind {
    #[default]
    Hybrid = 1,
    Hopf = 2,
    Caps = 3,
    Transit = 4,
    Siegel = 5,
    Product = 6,
    Lorentz = 7,
}

impl GalaxyManifoldKind {
    pub fn code(self) -> u16 {
        self as u16
    }

    pub fn file_stem(self) -> &'static str {
        match self {
            Self::Hybrid => "hybrid",
            Self::Hopf => "hopf",
            Self::Caps => "caps",
            Self::Transit => "transit",
            Self::Siegel => "siegel",
            Self::Product => "product",
            Self::Lorentz => "lorentz",
        }
    }
}

#[repr(u16)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum GalaxyPageKind {
    #[default]
    Unknown = 0,
    IdIndex = 1,
    IdSlab = 2,
    LabelSlab = 3,
    NodeImportance = 4,
    NodeKind = 5,
    NodeFlags = 6,
    NodeLabelOffset = 7,
    NodeLabelLength = 8,
    EdgeSource = 9,
    EdgeTarget = 10,
    EdgeWeight = 11,
    EdgeKind = 12,
    EdgeFlags = 13,
    CsrOffsets = 14,
    CsrNeighbors = 15,
    PositionX = 16,
    PositionY = 17,
    PositionZ = 18,
    SpatialOrder = 19,
    SpatialKeys = 20,
    NodeTiles = 21,
    LodNodes = 22,
    EdgeBundles = 23,
    DeltaNodes = 24,
    DeltaTiles = 25,
    DeltaTileNodes = 26,
    DeltaAffectedTiles = 27,
    Tiles = 28,
    DeltaEdgeBundles = 29,
}

impl GalaxyPageKind {
    pub fn code(self) -> u16 {
        self as u16
    }
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyPageHeader {
    pub magic: [u8; 8],
    pub schema_version: u16,
    pub page_kind: u16,
    pub record_size: u32,
    pub record_count: u64,
    pub generation_hash: u64,
    pub content_hash: u64,
    pub manifold: u16,
    pub lod: u16,
    pub flags: u32,
    pub reserved: [u8; 16],
}

impl GalaxyPageHeader {
    pub fn new(
        page_kind: GalaxyPageKind,
        record_size: usize,
        record_count: usize,
        generation_hash: u64,
        content_hash: u64,
        manifold: Option<GalaxyManifoldKind>,
        lod: u16,
    ) -> Self {
        Self {
            magic: GALAXY_PAGE_MAGIC,
            schema_version: GALAXY_STORE_SCHEMA_VERSION,
            page_kind: page_kind.code(),
            record_size: u32::try_from(record_size).unwrap_or(u32::MAX),
            record_count: u64::try_from(record_count).unwrap_or(u64::MAX),
            generation_hash,
            content_hash,
            manifold: manifold.map_or(0, GalaxyManifoldKind::code),
            lod,
            flags: 0,
            reserved: [0; 16],
        }
    }
}

const _: [(); GALAXY_PAGE_HEADER_BYTES] = [(); std::mem::size_of::<GalaxyPageHeader>()];

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyStringRef {
    pub offset: u64,
    pub len: u32,
    pub hash32: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyCsrNeighbor {
    pub node: u32,
    pub edge: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyTileRecord {
    pub tile_id: u64,
    pub node_start: u64,
    pub node_count: u32,
    pub reserved: u32,
    pub min: [f32; 3],
    pub max: [f32; 3],
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyLodNodeRecord {
    pub tile_id: u64,
    pub node_start: u64,
    pub node_count: u32,
    pub importance_millis: u32,
    pub centroid: [f32; 3],
    pub density: f32,
    pub min: [f32; 3],
    pub max: [f32; 3],
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyEdgeBundleRecord {
    pub source_lod_node: u32,
    pub target_lod_node: u32,
    pub edge_count: u32,
    pub flags: u32,
    pub weight_millis: u64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyDeltaNodeRecord {
    pub morton_key: u64,
    pub tile_id: u64,
    pub node: u32,
    pub reserved: u32,
    pub position: [f32; 3],
    pub padding: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyAffectedTileRecord {
    pub tile_id: u64,
    pub lod: u16,
    pub reserved: [u8; 6],
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, AsBytes, FromBytes, FromZeroes)]
pub struct GalaxyDeltaEdgeBundleRecord {
    pub source_tile: u64,
    pub target_tile: u64,
    pub edge_count: u32,
    pub flags: u32,
    pub weight_millis: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyPageManifest {
    pub file: String,
    pub page_kind: u16,
    pub record_size: u32,
    pub record_count: u64,
    pub content_hash: u64,
    pub manifold: Option<GalaxyManifoldKind>,
    pub lod: u16,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyManifoldManifest {
    pub manifold: GalaxyManifoldKind,
    pub bounds_min: [f32; 3],
    pub bounds_max: [f32; 3],
    pub tile_bits: u8,
    pub lod_levels: u8,
    pub occupied_tiles: Vec<u32>,
    pub lod_node_counts: Vec<u32>,
    pub edge_bundle_counts: Vec<u32>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyStoreManifest {
    pub schema_version: u16,
    pub generation: String,
    pub generation_hash: u64,
    pub authority_hash: u64,
    pub node_count: u64,
    pub edge_count: u64,
    pub skipped_edges: u64,
    pub pages: Vec<GalaxyPageManifest>,
    pub manifolds: Vec<GalaxyManifoldManifest>,
}

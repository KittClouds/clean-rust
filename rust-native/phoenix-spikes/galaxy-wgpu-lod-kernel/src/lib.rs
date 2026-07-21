//! Isolated GPU preprocessing proof for Phoenix Galaxy LOD construction.
//!
//! Stable graph identities and topology never enter this crate. GPU output is
//! limited to presentation-space Morton/tile data, LOD aggregates, and raw
//! edge-bundle keys. CPU sorting and exact bundle reduction remain explicit.

mod cpu;
mod radix;
mod runtime;
mod types;

pub use cpu::{build_lod_ranges, cpu_lod, cpu_remap_edges, cpu_spatial, reduce_bundle_keys};
pub use radix::MortonRadixScratch;
pub use runtime::{
    AdapterReceipt, GalaxyGpuError, GalaxyGpuRuntime, ResidentLod, ResidentPositions,
};
pub use types::{
    BundleKeyOutput, BundleRecord, EdgeInput, LodAggregate, LodOutput, LodRange, RawBundleKey,
    SpatialOutput, StageTiming,
};

use crate::galaxy_store_format::{
    GalaxyCsrNeighbor, GalaxyPageHeader, GalaxyStringRef, GALAXY_PAGE_HEADER_BYTES,
};
use serde::{Deserialize, Serialize};
use std::mem::size_of;

pub const GALAXY_TEN_MILLION_NODES: u64 = 10_000_000;
pub const GALAXY_TEN_MILLION_EDGES: u64 = 10_000_000;

const FIXED_SHARED_PAGE_COUNT: u64 = 13;
const FIXED_MANIFOLD_PAGE_COUNT: u64 = 6;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyCapacityByteAccounting {
    pub node_count: u64,
    pub edge_count: u64,
    pub manifold_count: u16,
    pub fixed_shared_node_bytes_per_record: u64,
    pub fixed_shared_edge_bytes_per_record: u64,
    pub fixed_manifold_bytes_per_node: u64,
    pub fixed_shared_bytes: u64,
    pub fixed_manifold_bytes: u64,
    pub fixed_page_header_bytes: u64,
    pub fixed_total_bytes: u64,
    pub excludes_variable_slabs_and_lod: bool,
}

pub fn galaxy_capacity_byte_accounting(
    node_count: u64,
    edge_count: u64,
    manifold_count: u16,
) -> GalaxyCapacityByteAccounting {
    let node_bytes = fixed_shared_node_bytes_per_record();
    let edge_bytes = fixed_shared_edge_bytes_per_record();
    let manifold_bytes = fixed_manifold_bytes_per_node();
    let fixed_shared_bytes = node_count
        .saturating_mul(node_bytes)
        .saturating_add(edge_count.saturating_mul(edge_bytes))
        .saturating_add(size_of::<u64>() as u64);
    let fixed_manifold_bytes = node_count
        .saturating_mul(manifold_bytes)
        .saturating_mul(u64::from(manifold_count));
    let page_count = FIXED_SHARED_PAGE_COUNT
        .saturating_add(FIXED_MANIFOLD_PAGE_COUNT.saturating_mul(u64::from(manifold_count)));
    let fixed_page_header_bytes = page_count.saturating_mul(GALAXY_PAGE_HEADER_BYTES as u64);
    GalaxyCapacityByteAccounting {
        node_count,
        edge_count,
        manifold_count,
        fixed_shared_node_bytes_per_record: node_bytes,
        fixed_shared_edge_bytes_per_record: edge_bytes,
        fixed_manifold_bytes_per_node: manifold_bytes,
        fixed_shared_bytes,
        fixed_manifold_bytes,
        fixed_page_header_bytes,
        fixed_total_bytes: fixed_shared_bytes
            .saturating_add(fixed_manifold_bytes)
            .saturating_add(fixed_page_header_bytes),
        excludes_variable_slabs_and_lod: true,
    }
}

fn fixed_shared_node_bytes_per_record() -> u64 {
    (size_of::<GalaxyStringRef>()
        + size_of::<u32>()
        + size_of::<u16>()
        + size_of::<u16>()
        + size_of::<u32>()
        + size_of::<u32>()
        + size_of::<u64>()) as u64
}

fn fixed_shared_edge_bytes_per_record() -> u64 {
    (size_of::<u32>() * 3 + size_of::<u16>() * 2 + size_of::<GalaxyCsrNeighbor>() * 2) as u64
}

fn fixed_manifold_bytes_per_node() -> u64 {
    (size_of::<f32>() * 3 + size_of::<u32>() + size_of::<u64>() + size_of::<u32>()) as u64
}

const _: [(); GALAXY_PAGE_HEADER_BYTES] = [(); size_of::<GalaxyPageHeader>()];

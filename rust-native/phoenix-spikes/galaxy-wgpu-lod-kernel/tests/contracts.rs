use std::mem::size_of;

use galaxy_wgpu_lod_kernel::{
    EdgeInput, LodAggregate, LodRange, RawBundleKey, cpu_remap_edges, reduce_bundle_keys,
};

#[test]
fn gpu_records_have_fixed_width_layouts() {
    assert_eq!(size_of::<EdgeInput>(), 16);
    assert_eq!(size_of::<RawBundleKey>(), 16);
    assert_eq!(size_of::<LodRange>(), 16);
    assert_eq!(size_of::<LodAggregate>(), 64);
}

#[test]
fn cpu_bundle_reduction_is_canonical_and_saturating() {
    let mapping = [7, 2, 7];
    let edges = [
        EdgeInput {
            source: 0,
            target: 1,
            weight_millis: u32::MAX,
            flags: 0b01,
        },
        EdgeInput {
            source: 1,
            target: 2,
            weight_millis: 9,
            flags: 0b10,
        },
    ];
    let keys = cpu_remap_edges(&edges, &mapping).unwrap();
    let bundles = reduce_bundle_keys(keys);
    assert_eq!(bundles.len(), 1);
    assert_eq!(bundles[0].source_lod_node, 2);
    assert_eq!(bundles[0].target_lod_node, 7);
    assert_eq!(bundles[0].edge_count, 2);
    assert_eq!(bundles[0].flags, 0b11);
    assert_eq!(bundles[0].weight_millis, u64::from(u32::MAX) + 9);
}

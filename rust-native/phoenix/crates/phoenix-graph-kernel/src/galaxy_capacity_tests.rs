use crate::{galaxy_capacity_byte_accounting, GALAXY_TEN_MILLION_EDGES, GALAXY_TEN_MILLION_NODES};

#[test]
fn accounts_for_ten_million_fixed_records_without_materializing_them() {
    let one_manifold =
        galaxy_capacity_byte_accounting(GALAXY_TEN_MILLION_NODES, GALAXY_TEN_MILLION_EDGES, 1);

    assert_eq!(one_manifold.fixed_shared_node_bytes_per_record, 40);
    assert_eq!(one_manifold.fixed_shared_edge_bytes_per_record, 32);
    assert_eq!(one_manifold.fixed_manifold_bytes_per_node, 28);
    assert_eq!(one_manifold.fixed_shared_bytes, 720_000_008);
    assert_eq!(one_manifold.fixed_manifold_bytes, 280_000_000);
    assert!(one_manifold.fixed_total_bytes > 1_000_000_000);
    assert!(one_manifold.fixed_total_bytes < 1_000_010_000);
    assert!(one_manifold.excludes_variable_slabs_and_lod);
}

#[test]
fn shared_identity_and_topology_are_not_multiplied_across_manifolds() {
    let one =
        galaxy_capacity_byte_accounting(GALAXY_TEN_MILLION_NODES, GALAXY_TEN_MILLION_EDGES, 1);
    let seven =
        galaxy_capacity_byte_accounting(GALAXY_TEN_MILLION_NODES, GALAXY_TEN_MILLION_EDGES, 7);

    assert_eq!(seven.fixed_shared_bytes, one.fixed_shared_bytes);
    assert_eq!(
        seven.fixed_manifold_bytes,
        one.fixed_manifold_bytes.saturating_mul(7)
    );
    assert!(seven.fixed_total_bytes > 2_680_000_000);
    assert!(seven.fixed_total_bytes < 2_680_010_000);
}

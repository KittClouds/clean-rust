use crate::{
    write_galaxy_delta_overlay, write_galaxy_graph_store, GalaxyDeltaBuildInput,
    GalaxyEdgeBundleRecord, GalaxyEdgeRecord, GalaxyGraphPack, GalaxyGraphStore,
    GalaxyGraphStoreBuildOptions, GalaxyManifoldKind, GalaxyManifoldPositions, GalaxyNodeRecord,
    GalaxyPageKind, GalaxyStringRef, GalaxyTileRecord,
};
use std::path::PathBuf;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

struct TempTree(PathBuf);

impl TempTree {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        Self(std::env::temp_dir().join(format!(
            "phoenix-galaxy-store-{label}-{}-{nonce}",
            std::process::id()
        )))
    }

    fn join(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for TempTree {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn writes_and_reopens_mmap_soa_identity_and_csr_pages() {
    let pack = synthetic_pack(4, 4);
    let positions = grid_positions(4);
    let temp = TempTree::new("roundtrip");
    let root = temp.join("generation-1");
    let manifest = write_galaxy_graph_store(
        &pack,
        &[
            manifold(GalaxyManifoldKind::Hybrid, positions.clone()),
            manifold(GalaxyManifoldKind::Hopf, positions),
        ],
        &root,
        build_options("generation-1", 4, 3),
    )
    .expect("write base store");
    let store = GalaxyGraphStore::open(&root).expect("open mmap store");

    assert_eq!(manifest.node_count, 4);
    assert_eq!(manifest.edge_count, 4);
    assert_eq!(manifest.manifolds.len(), 2);
    let id_refs = store
        .page_for(GalaxyPageKind::IdIndex.code(), None, 0)
        .expect("id index")
        .records::<GalaxyStringRef>()
        .expect("id records");
    let id_slab = store
        .page_for(GalaxyPageKind::IdSlab.code(), None, 0)
        .expect("id slab")
        .payload();
    let first = id_refs[0];
    assert_eq!(
        std::str::from_utf8(
            &id_slab[first.offset as usize..first.offset as usize + first.len as usize]
        )
        .expect("id utf8"),
        "entity:0"
    );
    let offsets = store
        .page_for(GalaxyPageKind::CsrOffsets.code(), None, 0)
        .expect("csr offsets")
        .records::<u64>()
        .expect("offset records");
    assert_eq!(offsets.len(), pack.nodes.len() + 1);
    assert_eq!(
        *offsets.last().expect("last offset"),
        (pack.edges.len() * 2) as u64
    );
    let neighbors = store
        .page_for(GalaxyPageKind::CsrNeighbors.code(), None, 0)
        .expect("csr neighbors")
        .records::<crate::GalaxyCsrNeighbor>()
        .expect("neighbor records");
    assert_eq!(neighbors.len(), pack.edges.len() * 2);
}

#[test]
fn morton_tiles_preserve_exact_identity_and_build_lod_bundles() {
    let pack = synthetic_pack(1_024, 4_096);
    let positions = grid_positions(1_024);
    let temp = TempTree::new("lod");
    let root = temp.join("generation-1");
    let manifest = write_galaxy_graph_store(
        &pack,
        &[manifold(GalaxyManifoldKind::Siegel, positions)],
        &root,
        build_options("generation-1", 6, 4),
    )
    .expect("write tiled store");
    let store = GalaxyGraphStore::open(&root).expect("open tiled store");
    let order = store
        .page_for(
            GalaxyPageKind::SpatialOrder.code(),
            Some(GalaxyManifoldKind::Siegel),
            0,
        )
        .expect("spatial order")
        .records::<u32>()
        .expect("order records");
    let keys = store
        .page_for(
            GalaxyPageKind::SpatialKeys.code(),
            Some(GalaxyManifoldKind::Siegel),
            0,
        )
        .expect("spatial keys")
        .records::<u64>()
        .expect("key records");
    assert_eq!(order.len(), pack.nodes.len());
    let mut identities = order.to_vec();
    identities.sort_unstable();
    assert_eq!(identities, (0..pack.nodes.len() as u32).collect::<Vec<_>>());
    assert!(order
        .windows(2)
        .all(|pair| keys[pair[0] as usize] <= keys[pair[1] as usize]));

    let tiles = store
        .page_for(
            GalaxyPageKind::Tiles.code(),
            Some(GalaxyManifoldKind::Siegel),
            0,
        )
        .expect("tiles")
        .records::<GalaxyTileRecord>()
        .expect("tile records");
    assert_eq!(
        tiles
            .iter()
            .map(|tile| tile.node_count as usize)
            .sum::<usize>(),
        pack.nodes.len()
    );
    let manifold_manifest = &manifest.manifolds[0];
    assert_eq!(manifold_manifest.lod_node_counts.len(), 4);
    assert!(manifold_manifest
        .lod_node_counts
        .windows(2)
        .all(|pair| pair[1] <= pair[0]));
    for lod in 0..4 {
        let bundles = store
            .page_for(
                GalaxyPageKind::EdgeBundles.code(),
                Some(GalaxyManifoldKind::Siegel),
                lod,
            )
            .expect("lod bundles")
            .records::<GalaxyEdgeBundleRecord>()
            .expect("bundle records");
        assert_eq!(
            bundles
                .iter()
                .map(|bundle| bundle.edge_count as usize)
                .sum::<usize>(),
            pack.edges.len()
        );
    }
}

#[test]
fn immutable_generation_rejects_overwrite_and_position_mismatch() {
    let pack = synthetic_pack(8, 12);
    let temp = TempTree::new("immutable");
    let root = temp.join("generation-1");
    let options = build_options("generation-1", 4, 2);
    write_galaxy_graph_store(
        &pack,
        &[manifold(GalaxyManifoldKind::Hybrid, grid_positions(8))],
        &root,
        options.clone(),
    )
    .expect("first generation");
    assert!(write_galaxy_graph_store(
        &pack,
        &[manifold(GalaxyManifoldKind::Hybrid, grid_positions(8))],
        &root,
        options,
    )
    .is_err());
    assert!(write_galaxy_graph_store(
        &pack,
        &[manifold(GalaxyManifoldKind::Hybrid, grid_positions(7))],
        temp.join("bad-generation"),
        build_options("bad", 4, 2),
    )
    .is_err());
}

#[test]
fn delta_overlay_regenerates_only_affected_spatial_and_csr_ranges() {
    let pack = synthetic_pack(4_096, 8_192);
    let mut positions = grid_positions(4_096);
    let temp = TempTree::new("delta");
    let root = temp.join("generation-1");
    write_galaxy_graph_store(
        &pack,
        &[manifold(GalaxyManifoldKind::Hybrid, positions.clone())],
        &root,
        build_options("generation-1", 6, 4),
    )
    .expect("base generation");
    let store = GalaxyGraphStore::open(&root).expect("open base");
    positions[137] = positions[3_700];
    let delta_root = temp.join("delta-2");
    let delta = write_galaxy_delta_overlay(
        &store,
        &pack,
        GalaxyDeltaBuildInput {
            generation: "delta-2".to_owned(),
            changed_nodes: vec![137],
            changed_edges: Vec::new(),
            manifolds: vec![manifold(GalaxyManifoldKind::Hybrid, positions)],
        },
        &delta_root,
    )
    .expect("write delta");

    let summary = &delta.manifolds[0];
    assert_eq!(delta.changed_nodes, 1);
    assert_eq!(summary.affected_tiles.len(), 4);
    assert!(summary.affected_tiles[0] <= 2);
    assert!(summary.source_nodes_read < pack.nodes.len() as u64 / 8);
    assert!(summary.source_edges_read < pack.edges.len() as u64 / 4);
    assert!(summary.replacement_tile_nodes < pack.nodes.len() as u64 / 8);
    assert!(delta_root.join("hybrid-delta-tiles.ggp").exists());
    assert!(delta_root.join("hybrid-delta-bundles.ggp").exists());
}

#[test]
fn builds_twenty_thousand_node_native_store_within_debug_budget() {
    let pack = synthetic_pack(20_000, 40_000);
    let temp = TempTree::new("performance");
    let started = Instant::now();
    let manifest = write_galaxy_graph_store(
        &pack,
        &[manifold(GalaxyManifoldKind::Hybrid, grid_positions(20_000))],
        temp.join("generation-1"),
        build_options("generation-1", 7, 4),
    )
    .expect("performance generation");
    let elapsed = started.elapsed();

    assert_eq!(manifest.node_count, 20_000);
    assert_eq!(manifest.edge_count, 40_000);
    assert!(
        elapsed.as_secs_f32() < 8.0,
        "native store build took {elapsed:?}"
    );
}

fn build_options(generation: &str, tile_bits: u8, lod_levels: u8) -> GalaxyGraphStoreBuildOptions {
    GalaxyGraphStoreBuildOptions {
        generation: generation.to_owned(),
        authority_hash: 0xfeed_beef,
        tile_bits,
        lod_levels,
    }
}

fn manifold(manifold: GalaxyManifoldKind, positions: Vec<[f32; 3]>) -> GalaxyManifoldPositions {
    GalaxyManifoldPositions {
        manifold,
        positions,
    }
}

fn synthetic_pack(node_count: usize, edge_count: usize) -> GalaxyGraphPack {
    let mut entity_ids = Vec::with_capacity(node_count);
    let mut label_slab = Vec::with_capacity(node_count * 12);
    let mut nodes = Vec::with_capacity(node_count);
    for node in 0..node_count {
        let id = format!("entity:{node}");
        let label = format!("Entity {node}");
        let label_offset = label_slab.len();
        label_slab.extend_from_slice(label.as_bytes());
        entity_ids.push(id);
        nodes.push(GalaxyNodeRecord {
            entity_index: node as u32,
            label_offset: label_offset as u32,
            label_len: label.len() as u32,
            importance_millis: 1 + (node % 1_000) as u32,
            kind_code: 1 + (node % 9) as u16,
            flags: 0,
        });
    }
    let mut edges = Vec::with_capacity(edge_count);
    for edge in 0..edge_count {
        let source = edge % node_count;
        let mut target = (edge.wrapping_mul(17).wrapping_add(29)) % node_count;
        if target == source {
            target = (target + 1) % node_count;
        }
        let (source, target) = if source < target {
            (source, target)
        } else {
            (target, source)
        };
        edges.push(GalaxyEdgeRecord {
            source: source as u32,
            target: target as u32,
            weight_millis: 1 + (edge % 7) as u32,
            edge_kind: 1 + (edge % 5) as u16,
            flags: 0,
        });
    }
    GalaxyGraphPack {
        entity_ids,
        label_slab,
        nodes,
        edges,
        skipped_edges: 0,
    }
}

fn grid_positions(count: usize) -> Vec<[f32; 3]> {
    let side = (count as f64).cbrt().ceil() as usize;
    (0..count)
        .map(|node| {
            let x = node % side;
            let y = (node / side) % side;
            let z = node / (side * side);
            [x as f32, y as f32, z as f32]
        })
        .collect()
}

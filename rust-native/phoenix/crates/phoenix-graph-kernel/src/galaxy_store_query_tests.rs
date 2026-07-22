use crate::{
    write_galaxy_graph_store, GalaxyEdgeRecord, GalaxyGraphPack, GalaxyGraphStore,
    GalaxyGraphStoreBuildOptions, GalaxyManifoldKind, GalaxyManifoldPositions, GalaxyNodeRecord,
    GalaxyPageKind, GalaxyPathQuery, GalaxyRegionQuery, GalaxyTileRecord,
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
            "phoenix-galaxy-query-{label}-{}-{nonce}",
            std::process::id()
        )))
    }
}

impl Drop for TempTree {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn region_query_scans_only_candidate_tiles_and_returns_exact_ordinals() {
    let positions = vec![
        [-0.9, 0.0, 0.0],
        [-0.7, 0.0, 0.0],
        [-0.5, 0.0, 0.0],
        [-0.3, 0.0, 0.0],
        [0.3, 0.0, 0.0],
        [0.5, 0.0, 0.0],
        [0.7, 0.0, 0.0],
        [0.9, 0.0, 0.0],
    ];
    let (_temp, store) = build_store("region", chain_pack(positions.len()), positions);
    let tiles = store
        .page_for(
            GalaxyPageKind::Tiles.code(),
            Some(GalaxyManifoldKind::Hybrid),
            0,
        )
        .expect("tiles")
        .records::<GalaxyTileRecord>()
        .expect("tile records");
    let candidate_tile_ids = tiles.iter().map(|tile| tile.tile_id).collect();
    let result = store
        .query_screen_region(&GalaxyRegionQuery {
            manifold: GalaxyManifoldKind::Hybrid,
            candidate_tile_ids,
            view_projection: identity_matrix(),
            viewport: [100.0, 100.0],
            rect: [0.0, 40.0, 50.0, 60.0],
            max_candidates: 64,
            max_results: 64,
        })
        .expect("region query");

    assert_eq!(result.node_indices, vec![0, 1, 2, 3]);
    assert_eq!(result.scanned_nodes, 8);
    assert!(!result.truncated);
}

#[test]
fn bounded_path_returns_only_overlay_ordinals() {
    let positions = (0..16).map(|node| [node as f32 * 0.01, 0.0, 0.0]).collect();
    let (_temp, store) = build_store("path", chain_pack(16), positions);
    let result = store
        .query_bounded_path(&GalaxyPathQuery {
            source_node: 2,
            target_node: 9,
            max_visited: 64,
            max_path_edges: 32,
        })
        .expect("bounded path");

    assert!(result.found);
    assert_eq!(result.node_indices, (2..=9).collect::<Vec<_>>());
    assert_eq!(result.edge_indices, (2..9).collect::<Vec<_>>());
    assert!(result.visited_nodes <= 16);
}

#[test]
fn bounded_path_fails_closed_at_visit_and_overlay_limits() {
    let count = 1_024;
    let positions = (0..count)
        .map(|node| [node as f32 / count as f32, 0.0, 0.0])
        .collect();
    let (_temp, store) = build_store("bounded", chain_pack(count), positions);
    let visit_limited = store
        .query_bounded_path(&GalaxyPathQuery {
            source_node: 0,
            target_node: (count - 1) as u32,
            max_visited: 128,
            max_path_edges: 512,
        })
        .expect("visit-limited path");
    let overlay_limited = store
        .query_bounded_path(&GalaxyPathQuery {
            source_node: 0,
            target_node: 700,
            max_visited: 1_024,
            max_path_edges: 64,
        })
        .expect("overlay-limited path");

    assert!(!visit_limited.found);
    assert!(visit_limited.truncated);
    assert!(visit_limited.visited_nodes <= 128);
    assert!(!overlay_limited.found);
    assert!(overlay_limited.truncated);
    assert!(overlay_limited.node_indices.is_empty());
    assert!(overlay_limited.edge_indices.is_empty());
}

#[test]
fn native_path_query_keeps_large_store_work_bounded() {
    let count = 20_000;
    let positions = (0..count)
        .map(|node| [node as f32 / count as f32, 0.0, 0.0])
        .collect();
    let (_temp, store) = build_store("performance", chain_pack(count), positions);
    let started = Instant::now();
    let result = store
        .query_bounded_path(&GalaxyPathQuery {
            source_node: 0,
            target_node: (count - 1) as u32,
            max_visited: 4_096,
            max_path_edges: 512,
        })
        .expect("bounded large path");

    assert!(!result.found);
    assert!(result.truncated);
    assert!(result.visited_nodes <= 4_096);
    assert!(started.elapsed().as_millis() < 250);
}

fn build_store(
    label: &str,
    pack: GalaxyGraphPack,
    positions: Vec<[f32; 3]>,
) -> (TempTree, GalaxyGraphStore) {
    let temp = TempTree::new(label);
    write_galaxy_graph_store(
        &pack,
        &[GalaxyManifoldPositions {
            manifold: GalaxyManifoldKind::Hybrid,
            positions,
        }],
        &temp.0,
        GalaxyGraphStoreBuildOptions {
            generation: format!("generation-{label}"),
            authority_hash: 0xface_cafe,
            tile_bits: 4,
            lod_levels: 3,
        },
    )
    .expect("write store");
    let store = GalaxyGraphStore::open(&temp.0).expect("open store");
    (temp, store)
}

fn chain_pack(node_count: usize) -> GalaxyGraphPack {
    let mut label_slab = Vec::with_capacity(node_count * 8);
    let mut nodes = Vec::with_capacity(node_count);
    let entity_ids = (0..node_count)
        .map(|node| {
            let label = format!("Node {node}");
            let offset = label_slab.len();
            label_slab.extend_from_slice(label.as_bytes());
            nodes.push(GalaxyNodeRecord {
                entity_index: node as u32,
                label_offset: offset as u32,
                label_len: label.len() as u32,
                importance_millis: 1,
                kind_code: 1,
                flags: 0,
            });
            format!("node:{node}")
        })
        .collect();
    let edges = (0..node_count.saturating_sub(1))
        .map(|edge| GalaxyEdgeRecord {
            source: edge as u32,
            target: edge as u32 + 1,
            weight_millis: 1,
            edge_kind: 1,
            flags: 0,
        })
        .collect();
    GalaxyGraphPack {
        entity_ids,
        label_slab,
        nodes,
        edges,
        skipped_edges: 0,
    }
}

fn identity_matrix() -> [f32; 16] {
    [
        1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
    ]
}

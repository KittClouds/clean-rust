use crate::galaxy_store_build::{finite_position, morton_key, write_page, GalaxyManifoldPositions};
use crate::galaxy_store_format::{
    GalaxyAffectedTileRecord, GalaxyCsrNeighbor, GalaxyDeltaEdgeBundleRecord,
    GalaxyDeltaNodeRecord, GalaxyManifoldKind, GalaxyPageKind, GalaxyPageManifest,
    GalaxyTileRecord,
};
use crate::{GalaxyGraphPack, GalaxyGraphStore, GalaxyStoreError};
use hashbrown::{HashMap, HashSet};
use rustc_hash::FxHasher;
use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::hash::BuildHasherDefault;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use xxhash_rust::xxh3::Xxh3;
use zerocopy::AsBytes;

type FastBuildHasher = BuildHasherDefault<FxHasher>;
type FastMap<K, V> = HashMap<K, V, FastBuildHasher>;
type FastSet<T> = HashSet<T, FastBuildHasher>;

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyDeltaBuildInput {
    pub generation: String,
    pub changed_nodes: Vec<u32>,
    pub changed_edges: Vec<u32>,
    pub manifolds: Vec<GalaxyManifoldPositions>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyDeltaManifoldManifest {
    pub manifold: GalaxyManifoldKind,
    pub changed_nodes: u32,
    pub affected_tiles: Vec<u32>,
    pub replacement_tile_nodes: u64,
    pub replacement_edge_bundles: u64,
    pub source_nodes_read: u64,
    pub source_edges_read: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyDeltaManifest {
    pub schema_version: u16,
    pub generation: String,
    pub generation_hash: u64,
    pub base_generation_hash: u64,
    pub node_count: u64,
    pub edge_count: u64,
    pub changed_nodes: u64,
    pub changed_edges: u64,
    pub pages: Vec<GalaxyPageManifest>,
    pub manifolds: Vec<GalaxyDeltaManifoldManifest>,
}

pub fn write_galaxy_delta_overlay(
    base: &GalaxyGraphStore,
    updated_pack: &GalaxyGraphPack,
    input: GalaxyDeltaBuildInput,
    output: impl AsRef<Path>,
) -> Result<GalaxyDeltaManifest, GalaxyStoreError> {
    validate_delta(base, updated_pack, &input)?;
    let output = output.as_ref();
    if output.exists() {
        return Err(GalaxyStoreError::Invalid(format!(
            "immutable delta already exists: {}",
            output.display()
        )));
    }
    let generation_hash = delta_generation_hash(base, updated_pack, &input);
    let building = building_path(output, generation_hash);
    if building.exists() {
        return Err(GalaxyStoreError::Invalid(format!(
            "delta build path already exists: {}",
            building.display()
        )));
    }
    std::fs::create_dir_all(output.parent().unwrap_or_else(|| Path::new(".")))?;
    std::fs::create_dir(&building)?;
    let result = build_delta(base, updated_pack, input, &building, generation_hash);
    match result {
        Ok(manifest) => {
            std::fs::rename(&building, output)?;
            Ok(manifest)
        }
        Err(error) => {
            let _ = std::fs::remove_dir_all(&building);
            Err(error)
        }
    }
}

fn build_delta(
    base: &GalaxyGraphStore,
    updated_pack: &GalaxyGraphPack,
    input: GalaxyDeltaBuildInput,
    root: &Path,
    generation_hash: u64,
) -> Result<GalaxyDeltaManifest, GalaxyStoreError> {
    let changed_edges = sorted_unique(&input.changed_edges);
    let mut topology_nodes = input.changed_nodes.clone();
    for &edge in &changed_edges {
        if let Some(edge) = updated_pack.edges.get(edge as usize) {
            topology_nodes.push(edge.source);
            topology_nodes.push(edge.target);
        }
    }
    let changed_nodes = sorted_unique(&topology_nodes);
    let mut pages = Vec::with_capacity(input.manifolds.len() * 5);
    let mut manifold_manifests = Vec::with_capacity(input.manifolds.len());
    for manifold in &input.manifolds {
        manifold_manifests.push(write_manifold_delta(
            base,
            updated_pack,
            manifold,
            &changed_nodes,
            &changed_edges,
            root,
            generation_hash,
            &mut pages,
        )?);
    }
    let manifest = GalaxyDeltaManifest {
        schema_version: 1,
        generation: input.generation,
        generation_hash,
        base_generation_hash: base.manifest().generation_hash,
        node_count: updated_pack.nodes.len() as u64,
        edge_count: updated_pack.edges.len() as u64,
        changed_nodes: changed_nodes.len() as u64,
        changed_edges: changed_edges.len() as u64,
        pages,
        manifolds: manifold_manifests,
    };
    let mut file = create_new(root.join("delta-manifest.json"))?;
    file.write_all(&serde_json::to_vec_pretty(&manifest)?)?;
    file.flush()?;
    file.get_ref().sync_data()?;
    Ok(manifest)
}

#[allow(clippy::too_many_arguments)]
fn write_manifold_delta(
    base: &GalaxyGraphStore,
    updated_pack: &GalaxyGraphPack,
    input: &GalaxyManifoldPositions,
    changed_nodes: &[u32],
    changed_edges: &[u32],
    root: &Path,
    generation_hash: u64,
    pages: &mut Vec<GalaxyPageManifest>,
) -> Result<GalaxyDeltaManifoldManifest, GalaxyStoreError> {
    let base_manifest = base
        .manifest()
        .manifolds
        .iter()
        .find(|manifest| manifest.manifold == input.manifold)
        .ok_or_else(|| {
            GalaxyStoreError::Invalid(format!(
                "missing base {} manifold",
                input.manifold.file_stem()
            ))
        })?;
    let old_tiles_page =
        base.page_for(GalaxyPageKind::NodeTiles.code(), Some(input.manifold), 0)?;
    let old_keys_page =
        base.page_for(GalaxyPageKind::SpatialKeys.code(), Some(input.manifold), 0)?;
    let order_page = base.page_for(GalaxyPageKind::SpatialOrder.code(), Some(input.manifold), 0)?;
    let tiles_page = base.page_for(GalaxyPageKind::Tiles.code(), Some(input.manifold), 0)?;
    let offsets_page = base.page_for(GalaxyPageKind::CsrOffsets.code(), None, 0)?;
    let neighbors_page = base.page_for(GalaxyPageKind::CsrNeighbors.code(), None, 0)?;
    let old_tiles = old_tiles_page.records::<u64>()?;
    let old_keys = old_keys_page.records::<u64>()?;
    let order = order_page.records::<u32>()?;
    let tiles = tiles_page.records::<GalaxyTileRecord>()?;
    let offsets = offsets_page.records::<u64>()?;
    let neighbors = neighbors_page.records::<GalaxyCsrNeighbor>()?;

    let base_shift = 63 - u32::from(base_manifest.tile_bits) * 3;
    let mut replacements: FastMap<u32, (u64, u64)> =
        FastMap::with_capacity_and_hasher(changed_nodes.len(), FastBuildHasher::default());
    let mut affected: FastSet<u64> =
        FastSet::with_capacity_and_hasher(changed_nodes.len() * 2, FastBuildHasher::default());
    let mut delta_nodes = Vec::with_capacity(changed_nodes.len());
    for &node in changed_nodes {
        let position = finite_position(input.positions[node as usize]);
        let key = morton_key(position, base_manifest.bounds_min, base_manifest.bounds_max);
        let tile = key >> base_shift;
        replacements.insert(node, (key, tile));
        affected.insert(old_tiles[node as usize]);
        affected.insert(tile);
        delta_nodes.push(GalaxyDeltaNodeRecord {
            morton_key: key,
            tile_id: tile,
            node,
            reserved: 0,
            position,
            padding: 0,
        });
    }
    delta_nodes.sort_unstable_by_key(|node| node.node);

    let tile_by_id: FastMap<u64, GalaxyTileRecord> = tiles
        .iter()
        .copied()
        .map(|tile| (tile.tile_id, tile))
        .collect();
    let mut affected_ids = affected.iter().copied().collect::<Vec<_>>();
    affected_ids.sort_unstable();
    let mut delta_tiles = Vec::with_capacity(affected_ids.len());
    let mut delta_tile_nodes = Vec::new();
    let mut affected_node_set: FastSet<u32> = FastSet::with_capacity_and_hasher(
        affected_ids.len().saturating_mul(32),
        FastBuildHasher::default(),
    );
    let mut source_nodes_read = 0u64;
    for tile_id in &affected_ids {
        let start = delta_tile_nodes.len();
        if let Some(tile) = tile_by_id.get(tile_id) {
            let range_start = tile.node_start as usize;
            let range_end = range_start + tile.node_count as usize;
            source_nodes_read += tile.node_count as u64;
            for &node in &order[range_start..range_end] {
                if replacements
                    .get(&node)
                    .is_some_and(|(_, new_tile)| new_tile != tile_id)
                {
                    continue;
                }
                delta_tile_nodes.push(node);
            }
        }
        for (&node, &(_, new_tile)) in &replacements {
            if new_tile == *tile_id && !delta_tile_nodes[start..].contains(&node) {
                delta_tile_nodes.push(node);
            }
        }
        delta_tile_nodes[start..].sort_unstable_by_key(|node| {
            replacements
                .get(node)
                .map(|(key, _)| *key)
                .unwrap_or(old_keys[*node as usize])
        });
        let mut min = [f32::INFINITY; 3];
        let mut max = [f32::NEG_INFINITY; 3];
        for &node in &delta_tile_nodes[start..] {
            affected_node_set.insert(node);
            let position = finite_position(input.positions[node as usize]);
            for axis in 0..3 {
                min[axis] = min[axis].min(position[axis]);
                max[axis] = max[axis].max(position[axis]);
            }
        }
        if delta_tile_nodes.len() == start {
            min = [0.0; 3];
            max = [0.0; 3];
        }
        delta_tiles.push(GalaxyTileRecord {
            tile_id: *tile_id,
            node_start: start as u64,
            node_count: (delta_tile_nodes.len() - start) as u32,
            reserved: 0,
            min,
            max,
        });
    }

    let affected_lods = affected_lod_records(
        changed_nodes,
        &old_keys,
        &replacements,
        base_manifest.tile_bits,
        base_manifest.lod_levels,
    );
    let (delta_bundles, source_edges_read) = rebuild_edge_bundles(
        updated_pack,
        &old_tiles,
        &replacements,
        &affected_node_set,
        changed_edges,
        &offsets,
        &neighbors,
    );
    let stem = input.manifold.file_stem();
    write_page(
        root,
        &format!("{stem}-delta-nodes.ggp"),
        GalaxyPageKind::DeltaNodes,
        Some(input.manifold),
        0,
        generation_hash,
        &delta_nodes,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-delta-tiles.ggp"),
        GalaxyPageKind::DeltaTiles,
        Some(input.manifold),
        0,
        generation_hash,
        &delta_tiles,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-delta-tile-nodes.ggp"),
        GalaxyPageKind::DeltaTileNodes,
        Some(input.manifold),
        0,
        generation_hash,
        &delta_tile_nodes,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-delta-affected.ggp"),
        GalaxyPageKind::DeltaAffectedTiles,
        Some(input.manifold),
        0,
        generation_hash,
        &affected_lods,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-delta-bundles.ggp"),
        GalaxyPageKind::DeltaEdgeBundles,
        Some(input.manifold),
        0,
        generation_hash,
        &delta_bundles,
        pages,
    )?;

    let mut affected_counts = vec![0u32; base_manifest.lod_levels as usize];
    for record in &affected_lods {
        affected_counts[record.lod as usize] += 1;
    }
    Ok(GalaxyDeltaManifoldManifest {
        manifold: input.manifold,
        changed_nodes: changed_nodes.len() as u32,
        affected_tiles: affected_counts,
        replacement_tile_nodes: delta_tile_nodes.len() as u64,
        replacement_edge_bundles: delta_bundles.len() as u64,
        source_nodes_read,
        source_edges_read,
    })
}

fn affected_lod_records(
    changed_nodes: &[u32],
    old_keys: &[u64],
    replacements: &FastMap<u32, (u64, u64)>,
    tile_bits: u8,
    lod_levels: u8,
) -> Vec<GalaxyAffectedTileRecord> {
    let mut records = Vec::new();
    for lod in 0..lod_levels {
        let bits = tile_bits.saturating_sub(lod.saturating_mul(2)).max(1);
        let shift = 63 - u32::from(bits) * 3;
        let mut ids: FastSet<u64> =
            FastSet::with_capacity_and_hasher(changed_nodes.len() * 2, FastBuildHasher::default());
        for &node in changed_nodes {
            ids.insert(old_keys[node as usize] >> shift);
            ids.insert(replacements[&node].0 >> shift);
        }
        let mut ids = ids.into_iter().collect::<Vec<_>>();
        ids.sort_unstable();
        records.extend(ids.into_iter().map(|tile_id| GalaxyAffectedTileRecord {
            tile_id,
            lod: lod as u16,
            reserved: [0; 6],
        }));
    }
    records
}

#[allow(clippy::too_many_arguments)]
fn rebuild_edge_bundles(
    pack: &GalaxyGraphPack,
    old_tiles: &[u64],
    replacements: &FastMap<u32, (u64, u64)>,
    affected_nodes: &FastSet<u32>,
    changed_edges: &[u32],
    offsets: &[u64],
    neighbors: &[GalaxyCsrNeighbor],
) -> (Vec<GalaxyDeltaEdgeBundleRecord>, u64) {
    let mut edge_ids: FastSet<u32> =
        FastSet::with_capacity_and_hasher(affected_nodes.len() * 4, FastBuildHasher::default());
    for &node in affected_nodes {
        let start = offsets[node as usize] as usize;
        let end = offsets[node as usize + 1] as usize;
        for neighbor in &neighbors[start..end] {
            edge_ids.insert(neighbor.edge);
        }
    }
    edge_ids.extend(changed_edges.iter().copied());
    let source_edges_read = edge_ids.len() as u64;
    let mut aggregates: FastMap<(u64, u64), (u32, u64, u32)> =
        FastMap::with_capacity_and_hasher(edge_ids.len(), FastBuildHasher::default());
    for edge_id in edge_ids {
        let Some(edge) = pack.edges.get(edge_id as usize) else {
            continue;
        };
        let source_tile = replacements
            .get(&edge.source)
            .map(|(_, tile)| *tile)
            .unwrap_or(old_tiles[edge.source as usize]);
        let target_tile = replacements
            .get(&edge.target)
            .map(|(_, tile)| *tile)
            .unwrap_or(old_tiles[edge.target as usize]);
        let key = if source_tile <= target_tile {
            (source_tile, target_tile)
        } else {
            (target_tile, source_tile)
        };
        let entry = aggregates.entry(key).or_insert((0, 0, 0));
        entry.0 = entry.0.saturating_add(1);
        entry.1 = entry.1.saturating_add(u64::from(edge.weight_millis));
        entry.2 |= u32::from(edge.flags);
    }
    let mut bundles = aggregates
        .into_iter()
        .map(
            |((source_tile, target_tile), (edge_count, weight_millis, flags))| {
                GalaxyDeltaEdgeBundleRecord {
                    source_tile,
                    target_tile,
                    edge_count,
                    flags,
                    weight_millis,
                }
            },
        )
        .collect::<Vec<_>>();
    bundles.sort_unstable_by_key(|bundle| (bundle.source_tile, bundle.target_tile));
    (bundles, source_edges_read)
}

fn validate_delta(
    base: &GalaxyGraphStore,
    pack: &GalaxyGraphPack,
    input: &GalaxyDeltaBuildInput,
) -> Result<(), GalaxyStoreError> {
    if input.generation.trim().is_empty() {
        return Err(GalaxyStoreError::Invalid(
            "delta generation must be non-empty".to_owned(),
        ));
    }
    if pack.nodes.len() as u64 != base.manifest().node_count
        || pack.edges.len() as u64 != base.manifest().edge_count
    {
        return Err(GalaxyStoreError::Invalid(
            "delta overlays require stable base node and edge ordinals".to_owned(),
        ));
    }
    if input
        .changed_nodes
        .iter()
        .any(|node| *node as usize >= pack.nodes.len())
        || input
            .changed_edges
            .iter()
            .any(|edge| *edge as usize >= pack.edges.len())
    {
        return Err(GalaxyStoreError::Invalid(
            "delta ordinal out of range".to_owned(),
        ));
    }
    for manifold in &input.manifolds {
        if manifold.positions.len() != pack.nodes.len() {
            return Err(GalaxyStoreError::Invalid(format!(
                "delta {} position parity failed",
                manifold.manifold.file_stem()
            )));
        }
    }
    Ok(())
}

fn sorted_unique(values: &[u32]) -> Vec<u32> {
    let mut values = values.to_vec();
    values.sort_unstable();
    values.dedup();
    values
}

fn delta_generation_hash(
    base: &GalaxyGraphStore,
    pack: &GalaxyGraphPack,
    input: &GalaxyDeltaBuildInput,
) -> u64 {
    let mut hash = Xxh3::new();
    hash.update(&base.manifest().generation_hash.to_le_bytes());
    hash.update(input.generation.as_bytes());
    hash.update(pack.node_bytes());
    hash.update(pack.edge_bytes());
    hash.update(input.changed_nodes.as_bytes());
    hash.update(input.changed_edges.as_bytes());
    hash.digest()
}

fn building_path(output: &Path, generation_hash: u64) -> PathBuf {
    let file_name = output
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("galaxy-delta");
    output.with_file_name(format!(".{file_name}.{generation_hash:016x}.building"))
}

fn create_new(path: PathBuf) -> Result<BufWriter<File>, GalaxyStoreError> {
    Ok(BufWriter::new(
        OpenOptions::new().write(true).create_new(true).open(path)?,
    ))
}

use crate::galaxy_store_format::{
    GalaxyCsrNeighbor, GalaxyEdgeBundleRecord, GalaxyLodNodeRecord, GalaxyManifoldKind,
    GalaxyManifoldManifest, GalaxyPageHeader, GalaxyPageKind, GalaxyPageManifest,
    GalaxyStoreManifest, GalaxyStringRef, GalaxyTileRecord, GALAXY_STORE_SCHEMA_VERSION,
};
use crate::{GalaxyGraphPack, GalaxyStoreError};
use hashbrown::HashMap;
use rustc_hash::FxHasher;
use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::hash::BuildHasherDefault;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use xxhash_rust::xxh3::{xxh3_64, Xxh3};
use zerocopy::AsBytes;

type FastBuildHasher = BuildHasherDefault<FxHasher>;
type FastMap<K, V> = HashMap<K, V, FastBuildHasher>;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyManifoldPositions {
    pub manifold: GalaxyManifoldKind,
    pub positions: Vec<[f32; 3]>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyGraphStoreBuildOptions {
    pub generation: String,
    pub authority_hash: u64,
    pub tile_bits: u8,
    pub lod_levels: u8,
}

impl Default for GalaxyGraphStoreBuildOptions {
    fn default() -> Self {
        Self {
            generation: "galaxy-generation-1".to_owned(),
            authority_hash: 0,
            tile_bits: 6,
            lod_levels: 4,
        }
    }
}

pub fn write_galaxy_graph_store(
    pack: &GalaxyGraphPack,
    manifolds: &[GalaxyManifoldPositions],
    output: impl AsRef<Path>,
    options: GalaxyGraphStoreBuildOptions,
) -> Result<GalaxyStoreManifest, GalaxyStoreError> {
    validate_options(pack, manifolds, &options)?;
    let output = output.as_ref();
    if output.exists() {
        return Err(GalaxyStoreError::Invalid(format!(
            "immutable generation already exists: {}",
            output.display()
        )));
    }
    let parent = output.parent().unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent)?;
    let generation_hash = generation_hash(pack, &options);
    let building = building_path(output, generation_hash);
    if building.exists() {
        return Err(GalaxyStoreError::Invalid(format!(
            "generation build path already exists: {}",
            building.display()
        )));
    }
    std::fs::create_dir(&building)?;

    let build_result = build_generation(pack, manifolds, &building, options, generation_hash);
    match build_result {
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

fn build_generation(
    pack: &GalaxyGraphPack,
    manifolds: &[GalaxyManifoldPositions],
    root: &Path,
    options: GalaxyGraphStoreBuildOptions,
    generation_hash: u64,
) -> Result<GalaxyStoreManifest, GalaxyStoreError> {
    let mut pages = Vec::with_capacity(24 + manifolds.len() * 24);
    write_identity_pages(pack, root, generation_hash, &mut pages)?;
    write_node_pages(pack, root, generation_hash, &mut pages)?;
    write_edge_pages(pack, root, generation_hash, &mut pages)?;
    write_csr_pages(pack, root, generation_hash, &mut pages)?;

    let mut manifold_manifests = Vec::with_capacity(manifolds.len());
    for manifold in manifolds {
        manifold_manifests.push(write_manifold_pages(
            pack,
            manifold,
            root,
            generation_hash,
            options.tile_bits,
            options.lod_levels,
            &mut pages,
        )?);
    }

    let manifest = GalaxyStoreManifest {
        schema_version: GALAXY_STORE_SCHEMA_VERSION,
        generation: options.generation,
        generation_hash,
        authority_hash: options.authority_hash,
        node_count: pack.nodes.len() as u64,
        edge_count: pack.edges.len() as u64,
        skipped_edges: pack.skipped_edges as u64,
        pages,
        manifolds: manifold_manifests,
    };
    let bytes = serde_json::to_vec_pretty(&manifest)?;
    let mut file = create_new(root.join("manifest.json"))?;
    file.write_all(&bytes)?;
    file.flush()?;
    file.get_ref().sync_data()?;
    Ok(manifest)
}

fn validate_options(
    pack: &GalaxyGraphPack,
    manifolds: &[GalaxyManifoldPositions],
    options: &GalaxyGraphStoreBuildOptions,
) -> Result<(), GalaxyStoreError> {
    if options.generation.trim().is_empty() {
        return Err(GalaxyStoreError::Invalid(
            "generation must be non-empty".to_owned(),
        ));
    }
    if !(1..=16).contains(&options.tile_bits) || !(1..=8).contains(&options.lod_levels) {
        return Err(GalaxyStoreError::Invalid(
            "tile_bits must be 1..=16 and lod_levels must be 1..=8".to_owned(),
        ));
    }
    let mut seen = FastMap::with_capacity_and_hasher(manifolds.len(), FastBuildHasher::default());
    for manifold in manifolds {
        if manifold.positions.len() != pack.nodes.len() {
            return Err(GalaxyStoreError::Invalid(format!(
                "{} position count {} does not match node count {}",
                manifold.manifold.file_stem(),
                manifold.positions.len(),
                pack.nodes.len()
            )));
        }
        if seen.insert(manifold.manifold, ()).is_some() {
            return Err(GalaxyStoreError::Invalid(format!(
                "duplicate {} manifold",
                manifold.manifold.file_stem()
            )));
        }
    }
    Ok(())
}

fn write_identity_pages(
    pack: &GalaxyGraphPack,
    root: &Path,
    generation_hash: u64,
    pages: &mut Vec<GalaxyPageManifest>,
) -> Result<(), GalaxyStoreError> {
    let mut slab = Vec::with_capacity(pack.entity_ids.iter().map(String::len).sum());
    let mut refs = Vec::with_capacity(pack.entity_ids.len());
    for id in &pack.entity_ids {
        let offset = slab.len();
        slab.extend_from_slice(id.as_bytes());
        refs.push(GalaxyStringRef {
            offset: offset as u64,
            len: id.len() as u32,
            hash32: xxh3_64(id.as_bytes()) as u32,
        });
    }
    write_page(
        root,
        "id-index.ggp",
        GalaxyPageKind::IdIndex,
        None,
        0,
        generation_hash,
        &refs,
        pages,
    )?;
    write_page(
        root,
        "id-slab.ggp",
        GalaxyPageKind::IdSlab,
        None,
        0,
        generation_hash,
        &slab,
        pages,
    )?;
    write_page(
        root,
        "label-slab.ggp",
        GalaxyPageKind::LabelSlab,
        None,
        0,
        generation_hash,
        &pack.label_slab,
        pages,
    )
}

fn write_node_pages(
    pack: &GalaxyGraphPack,
    root: &Path,
    generation_hash: u64,
    pages: &mut Vec<GalaxyPageManifest>,
) -> Result<(), GalaxyStoreError> {
    let mut importance = Vec::with_capacity(pack.nodes.len());
    let mut kinds = Vec::with_capacity(pack.nodes.len());
    let mut flags = Vec::with_capacity(pack.nodes.len());
    let mut label_offsets = Vec::with_capacity(pack.nodes.len());
    let mut label_lengths = Vec::with_capacity(pack.nodes.len());
    for node in &pack.nodes {
        importance.push(node.importance_millis);
        kinds.push(node.kind_code);
        flags.push(node.flags);
        label_offsets.push(node.label_offset);
        label_lengths.push(node.label_len);
    }
    write_page(
        root,
        "node-importance.ggp",
        GalaxyPageKind::NodeImportance,
        None,
        0,
        generation_hash,
        &importance,
        pages,
    )?;
    write_page(
        root,
        "node-kind.ggp",
        GalaxyPageKind::NodeKind,
        None,
        0,
        generation_hash,
        &kinds,
        pages,
    )?;
    write_page(
        root,
        "node-flags.ggp",
        GalaxyPageKind::NodeFlags,
        None,
        0,
        generation_hash,
        &flags,
        pages,
    )?;
    write_page(
        root,
        "node-label-offset.ggp",
        GalaxyPageKind::NodeLabelOffset,
        None,
        0,
        generation_hash,
        &label_offsets,
        pages,
    )?;
    write_page(
        root,
        "node-label-length.ggp",
        GalaxyPageKind::NodeLabelLength,
        None,
        0,
        generation_hash,
        &label_lengths,
        pages,
    )
}

fn write_edge_pages(
    pack: &GalaxyGraphPack,
    root: &Path,
    generation_hash: u64,
    pages: &mut Vec<GalaxyPageManifest>,
) -> Result<(), GalaxyStoreError> {
    let mut source = Vec::with_capacity(pack.edges.len());
    let mut target = Vec::with_capacity(pack.edges.len());
    let mut weight = Vec::with_capacity(pack.edges.len());
    let mut kind = Vec::with_capacity(pack.edges.len());
    let mut flags = Vec::with_capacity(pack.edges.len());
    for edge in &pack.edges {
        source.push(edge.source);
        target.push(edge.target);
        weight.push(edge.weight_millis);
        kind.push(edge.edge_kind);
        flags.push(edge.flags);
    }
    write_page(
        root,
        "edge-source.ggp",
        GalaxyPageKind::EdgeSource,
        None,
        0,
        generation_hash,
        &source,
        pages,
    )?;
    write_page(
        root,
        "edge-target.ggp",
        GalaxyPageKind::EdgeTarget,
        None,
        0,
        generation_hash,
        &target,
        pages,
    )?;
    write_page(
        root,
        "edge-weight.ggp",
        GalaxyPageKind::EdgeWeight,
        None,
        0,
        generation_hash,
        &weight,
        pages,
    )?;
    write_page(
        root,
        "edge-kind.ggp",
        GalaxyPageKind::EdgeKind,
        None,
        0,
        generation_hash,
        &kind,
        pages,
    )?;
    write_page(
        root,
        "edge-flags.ggp",
        GalaxyPageKind::EdgeFlags,
        None,
        0,
        generation_hash,
        &flags,
        pages,
    )
}

fn write_csr_pages(
    pack: &GalaxyGraphPack,
    root: &Path,
    generation_hash: u64,
    pages: &mut Vec<GalaxyPageManifest>,
) -> Result<(), GalaxyStoreError> {
    let mut offsets = vec![0u64; pack.nodes.len() + 1];
    for edge in &pack.edges {
        offsets[edge.source as usize + 1] += 1;
        offsets[edge.target as usize + 1] += 1;
    }
    for index in 1..offsets.len() {
        offsets[index] += offsets[index - 1];
    }
    let mut cursor = offsets[..pack.nodes.len()].to_vec();
    let mut neighbors = vec![GalaxyCsrNeighbor::default(); pack.edges.len() * 2];
    for (edge_index, edge) in pack.edges.iter().enumerate() {
        let source_slot = cursor[edge.source as usize] as usize;
        neighbors[source_slot] = GalaxyCsrNeighbor {
            node: edge.target,
            edge: edge_index as u32,
        };
        cursor[edge.source as usize] += 1;
        let target_slot = cursor[edge.target as usize] as usize;
        neighbors[target_slot] = GalaxyCsrNeighbor {
            node: edge.source,
            edge: edge_index as u32,
        };
        cursor[edge.target as usize] += 1;
    }
    write_page(
        root,
        "csr-offsets.ggp",
        GalaxyPageKind::CsrOffsets,
        None,
        0,
        generation_hash,
        &offsets,
        pages,
    )?;
    write_page(
        root,
        "csr-neighbors.ggp",
        GalaxyPageKind::CsrNeighbors,
        None,
        0,
        generation_hash,
        &neighbors,
        pages,
    )
}

fn write_manifold_pages(
    pack: &GalaxyGraphPack,
    input: &GalaxyManifoldPositions,
    root: &Path,
    generation_hash: u64,
    tile_bits: u8,
    lod_levels: u8,
    pages: &mut Vec<GalaxyPageManifest>,
) -> Result<GalaxyManifoldManifest, GalaxyStoreError> {
    let stem = input.manifold.file_stem();
    let (bounds_min, bounds_max) = position_bounds(&input.positions);
    let mut x = Vec::with_capacity(input.positions.len());
    let mut y = Vec::with_capacity(input.positions.len());
    let mut z = Vec::with_capacity(input.positions.len());
    let mut keys = Vec::with_capacity(input.positions.len());
    for position in &input.positions {
        let position = finite_position(*position);
        x.push(position[0]);
        y.push(position[1]);
        z.push(position[2]);
        keys.push(morton_key(position, bounds_min, bounds_max));
    }
    let mut order: Vec<u32> = (0..input.positions.len() as u32).collect();
    order.sort_unstable_by_key(|node| (keys[*node as usize], *node));
    let mut node_tiles = vec![0u64; input.positions.len()];
    let base_shift = 63 - u32::from(tile_bits) * 3;
    for node in 0..input.positions.len() {
        node_tiles[node] = keys[node] >> base_shift;
    }
    write_page(
        root,
        &format!("{stem}-x.ggp"),
        GalaxyPageKind::PositionX,
        Some(input.manifold),
        0,
        generation_hash,
        &x,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-y.ggp"),
        GalaxyPageKind::PositionY,
        Some(input.manifold),
        0,
        generation_hash,
        &y,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-z.ggp"),
        GalaxyPageKind::PositionZ,
        Some(input.manifold),
        0,
        generation_hash,
        &z,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-order.ggp"),
        GalaxyPageKind::SpatialOrder,
        Some(input.manifold),
        0,
        generation_hash,
        &order,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-keys.ggp"),
        GalaxyPageKind::SpatialKeys,
        Some(input.manifold),
        0,
        generation_hash,
        &keys,
        pages,
    )?;
    write_page(
        root,
        &format!("{stem}-node-tiles.ggp"),
        GalaxyPageKind::NodeTiles,
        Some(input.manifold),
        0,
        generation_hash,
        &node_tiles,
        pages,
    )?;

    let mut occupied_tiles = Vec::with_capacity(lod_levels as usize);
    let mut lod_node_counts = Vec::with_capacity(lod_levels as usize);
    let mut edge_bundle_counts = Vec::with_capacity(lod_levels as usize);
    for lod in 0..lod_levels {
        let bits = tile_bits.saturating_sub(lod.saturating_mul(2)).max(1);
        let (lod_nodes, node_to_lod) = build_lod_nodes(pack, &input.positions, &keys, &order, bits);
        let bundles = build_edge_bundles(pack, &node_to_lod);
        if lod == 0 {
            let tiles = lod_nodes
                .iter()
                .map(|node| GalaxyTileRecord {
                    tile_id: node.tile_id,
                    node_start: node.node_start,
                    node_count: node.node_count,
                    reserved: 0,
                    min: node.min,
                    max: node.max,
                })
                .collect::<Vec<_>>();
            write_page(
                root,
                &format!("{stem}-tiles.ggp"),
                GalaxyPageKind::Tiles,
                Some(input.manifold),
                0,
                generation_hash,
                &tiles,
                pages,
            )?;
        }
        write_page(
            root,
            &format!("{stem}-lod-{lod}-nodes.ggp"),
            GalaxyPageKind::LodNodes,
            Some(input.manifold),
            lod as u16,
            generation_hash,
            &lod_nodes,
            pages,
        )?;
        write_page(
            root,
            &format!("{stem}-lod-{lod}-bundles.ggp"),
            GalaxyPageKind::EdgeBundles,
            Some(input.manifold),
            lod as u16,
            generation_hash,
            &bundles,
            pages,
        )?;
        occupied_tiles.push(lod_nodes.len() as u32);
        lod_node_counts.push(lod_nodes.len() as u32);
        edge_bundle_counts.push(bundles.len() as u32);
    }
    Ok(GalaxyManifoldManifest {
        manifold: input.manifold,
        bounds_min,
        bounds_max,
        tile_bits,
        lod_levels,
        occupied_tiles,
        lod_node_counts,
        edge_bundle_counts,
    })
}

fn build_lod_nodes(
    pack: &GalaxyGraphPack,
    positions: &[[f32; 3]],
    keys: &[u64],
    order: &[u32],
    bits: u8,
) -> (Vec<GalaxyLodNodeRecord>, Vec<u32>) {
    let shift = 63 - u32::from(bits) * 3;
    let mut lod_nodes = Vec::new();
    let mut node_to_lod = vec![0u32; positions.len()];
    let mut cursor = 0usize;
    while cursor < order.len() {
        let tile_id = keys[order[cursor] as usize] >> shift;
        let start = cursor;
        let mut sum = [0f64; 3];
        let mut min = [f32::INFINITY; 3];
        let mut max = [f32::NEG_INFINITY; 3];
        let mut importance = 0u64;
        while cursor < order.len() && keys[order[cursor] as usize] >> shift == tile_id {
            let node = order[cursor] as usize;
            let position = finite_position(positions[node]);
            for axis in 0..3 {
                sum[axis] += f64::from(position[axis]);
                min[axis] = min[axis].min(position[axis]);
                max[axis] = max[axis].max(position[axis]);
            }
            importance = importance.saturating_add(u64::from(pack.nodes[node].importance_millis));
            node_to_lod[node] = lod_nodes.len() as u32;
            cursor += 1;
        }
        let count = cursor - start;
        let volume = ((max[0] - min[0]).abs().max(0.001)
            * (max[1] - min[1]).abs().max(0.001)
            * (max[2] - min[2]).abs().max(0.001))
        .max(0.000_001);
        lod_nodes.push(GalaxyLodNodeRecord {
            tile_id,
            node_start: start as u64,
            node_count: count as u32,
            importance_millis: importance.min(u64::from(u32::MAX)) as u32,
            centroid: [
                (sum[0] / count as f64) as f32,
                (sum[1] / count as f64) as f32,
                (sum[2] / count as f64) as f32,
            ],
            density: count as f32 / volume,
            min,
            max,
        });
    }
    (lod_nodes, node_to_lod)
}

fn build_edge_bundles(pack: &GalaxyGraphPack, node_to_lod: &[u32]) -> Vec<GalaxyEdgeBundleRecord> {
    let mut aggregates: FastMap<(u32, u32), (u32, u64, u32)> =
        FastMap::with_capacity_and_hasher(pack.edges.len().min(65_536), FastBuildHasher::default());
    for edge in &pack.edges {
        let source = node_to_lod[edge.source as usize];
        let target = node_to_lod[edge.target as usize];
        let key = if source <= target {
            (source, target)
        } else {
            (target, source)
        };
        let entry = aggregates.entry(key).or_insert((0, 0, 0));
        entry.0 = entry.0.saturating_add(1);
        entry.1 = entry.1.saturating_add(u64::from(edge.weight_millis));
        entry.2 |= u32::from(edge.flags);
    }
    let mut bundles = aggregates
        .into_iter()
        .map(
            |((source_lod_node, target_lod_node), (edge_count, weight_millis, flags))| {
                GalaxyEdgeBundleRecord {
                    source_lod_node,
                    target_lod_node,
                    edge_count,
                    flags,
                    weight_millis,
                }
            },
        )
        .collect::<Vec<_>>();
    bundles.sort_unstable_by_key(|bundle| (bundle.source_lod_node, bundle.target_lod_node));
    bundles
}

pub(crate) fn morton_key(position: [f32; 3], min: [f32; 3], max: [f32; 3]) -> u64 {
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

pub(crate) fn position_bounds(positions: &[[f32; 3]]) -> ([f32; 3], [f32; 3]) {
    if positions.is_empty() {
        return ([0.0; 3], [0.0; 3]);
    }
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

pub(crate) fn finite_position(mut position: [f32; 3]) -> [f32; 3] {
    for value in &mut position {
        if !value.is_finite() {
            *value = 0.0;
        }
    }
    position
}

// Page metadata is kept explicit at the single serialization boundary so every mmap file
// receives the same generation, manifold, LOD, width, and content-hash contract.
#[allow(clippy::too_many_arguments)]
pub(crate) fn write_page<T: AsBytes>(
    root: &Path,
    file_name: &str,
    page_kind: GalaxyPageKind,
    manifold: Option<GalaxyManifoldKind>,
    lod: u16,
    generation_hash: u64,
    records: &[T],
    pages: &mut Vec<GalaxyPageManifest>,
) -> Result<(), GalaxyStoreError> {
    let payload = records.as_bytes();
    let content_hash = xxh3_64(payload);
    let header = GalaxyPageHeader::new(
        page_kind,
        std::mem::size_of::<T>(),
        records.len(),
        generation_hash,
        content_hash,
        manifold,
        lod,
    );
    let mut file = create_new(root.join(file_name))?;
    file.write_all(header.as_bytes())?;
    file.write_all(payload)?;
    file.flush()?;
    file.get_ref().sync_data()?;
    pages.push(GalaxyPageManifest {
        file: file_name.to_owned(),
        page_kind: page_kind.code(),
        record_size: std::mem::size_of::<T>() as u32,
        record_count: records.len() as u64,
        content_hash,
        manifold,
        lod,
    });
    Ok(())
}

fn generation_hash(pack: &GalaxyGraphPack, options: &GalaxyGraphStoreBuildOptions) -> u64 {
    let mut hasher = Xxh3::new();
    hasher.update(options.generation.as_bytes());
    hasher.update(&options.authority_hash.to_le_bytes());
    hasher.update(pack.node_bytes());
    hasher.update(pack.edge_bytes());
    hasher.digest()
}

fn building_path(output: &Path, generation_hash: u64) -> PathBuf {
    let file_name = output
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("galaxy-store");
    output.with_file_name(format!(".{file_name}.{generation_hash:016x}.building"))
}

fn create_new(path: PathBuf) -> Result<BufWriter<File>, GalaxyStoreError> {
    Ok(BufWriter::new(
        OpenOptions::new().write(true).create_new(true).open(path)?,
    ))
}

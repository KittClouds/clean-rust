use crate::{
    GalaxyCsrNeighbor, GalaxyGraphStore, GalaxyManifoldKind, GalaxyPageKind, GalaxyStoreError,
    GalaxyTileRecord,
};
use rustc_hash::FxHashMap;
use serde::{Deserialize, Serialize};

pub const GALAXY_REGION_RESULT_LIMIT: usize = 4_096;
pub const GALAXY_REGION_CANDIDATE_LIMIT: usize = 200_000;
pub const GALAXY_PATH_VISIT_LIMIT: usize = 4_096;
pub const GALAXY_PATH_EDGE_LIMIT: usize = 512;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyRegionQuery {
    pub manifold: GalaxyManifoldKind,
    pub candidate_tile_ids: Vec<u64>,
    pub view_projection: [f32; 16],
    pub viewport: [f32; 2],
    pub rect: [f32; 4],
    pub max_candidates: u32,
    pub max_results: u32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyRegionQueryResult {
    pub node_indices: Vec<u32>,
    pub scanned_nodes: u32,
    pub truncated: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyPathQuery {
    pub source_node: u32,
    pub target_node: u32,
    pub max_visited: u32,
    pub max_path_edges: u32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GalaxyPathQueryResult {
    pub node_indices: Vec<u32>,
    pub edge_indices: Vec<u32>,
    pub visited_nodes: u32,
    pub found: bool,
    pub truncated: bool,
}

impl GalaxyGraphStore {
    pub fn query_screen_region(
        &self,
        query: &GalaxyRegionQuery,
    ) -> Result<GalaxyRegionQueryResult, GalaxyStoreError> {
        if query.viewport[0] <= 0.0 || query.viewport[1] <= 0.0 {
            return Err(GalaxyStoreError::Invalid(
                "region query viewport must be positive".to_owned(),
            ));
        }
        let x = self
            .page_for(GalaxyPageKind::PositionX.code(), Some(query.manifold), 0)?
            .records::<f32>()?;
        let y = self
            .page_for(GalaxyPageKind::PositionY.code(), Some(query.manifold), 0)?
            .records::<f32>()?;
        let z = self
            .page_for(GalaxyPageKind::PositionZ.code(), Some(query.manifold), 0)?
            .records::<f32>()?;
        let order = self
            .page_for(GalaxyPageKind::SpatialOrder.code(), Some(query.manifold), 0)?
            .records::<u32>()?;
        let tiles = self
            .page_for(GalaxyPageKind::Tiles.code(), Some(query.manifold), 0)?
            .records::<GalaxyTileRecord>()?;
        let max_candidates = usize::try_from(query.max_candidates)
            .unwrap_or(usize::MAX)
            .min(GALAXY_REGION_CANDIDATE_LIMIT);
        let max_results = usize::try_from(query.max_results)
            .unwrap_or(usize::MAX)
            .min(GALAXY_REGION_RESULT_LIMIT);
        let mut result = GalaxyRegionQueryResult {
            node_indices: Vec::with_capacity(max_results.min(256)),
            ..GalaxyRegionQueryResult::default()
        };

        'tiles: for tile_id in query
            .candidate_tile_ids
            .iter()
            .copied()
            .take(GALAXY_REGION_RESULT_LIMIT)
        {
            let Ok(index) = tiles.binary_search_by_key(&tile_id, |tile| tile.tile_id) else {
                continue;
            };
            let tile = tiles[index];
            let start = usize::try_from(tile.node_start).unwrap_or(usize::MAX);
            let end = start
                .saturating_add(tile.node_count as usize)
                .min(order.len());
            for spatial in start..end {
                if result.scanned_nodes as usize >= max_candidates {
                    result.truncated = true;
                    break 'tiles;
                }
                result.scanned_nodes = result.scanned_nodes.saturating_add(1);
                let node = order[spatial] as usize;
                if node >= x.len() || node >= y.len() || node >= z.len() {
                    continue;
                }
                let Some([screen_x, screen_y]) = project_to_screen(
                    [x[node], y[node], z[node]],
                    query.view_projection,
                    query.viewport,
                ) else {
                    continue;
                };
                if screen_x < query.rect[0]
                    || screen_y < query.rect[1]
                    || screen_x > query.rect[2]
                    || screen_y > query.rect[3]
                {
                    continue;
                }
                if result.node_indices.len() >= max_results {
                    result.truncated = true;
                    break 'tiles;
                }
                result.node_indices.push(node as u32);
            }
        }
        Ok(result)
    }

    pub fn query_bounded_path(
        &self,
        query: &GalaxyPathQuery,
    ) -> Result<GalaxyPathQueryResult, GalaxyStoreError> {
        let node_count = self.manifest().node_count;
        if u64::from(query.source_node) >= node_count || u64::from(query.target_node) >= node_count
        {
            return Err(GalaxyStoreError::Invalid(
                "path query node ordinal is outside the generation".to_owned(),
            ));
        }
        let offsets = self
            .page_for(GalaxyPageKind::CsrOffsets.code(), None, 0)?
            .records::<u64>()?;
        let neighbors = self
            .page_for(GalaxyPageKind::CsrNeighbors.code(), None, 0)?
            .records::<GalaxyCsrNeighbor>()?;
        let max_visited = usize::try_from(query.max_visited)
            .unwrap_or(usize::MAX)
            .min(GALAXY_PATH_VISIT_LIMIT)
            .max(1);
        let max_path_edges = usize::try_from(query.max_path_edges)
            .unwrap_or(usize::MAX)
            .min(GALAXY_PATH_EDGE_LIMIT)
            .max(1);
        let mut queue = Vec::with_capacity(max_visited.min(256));
        let mut previous = FxHashMap::default();
        previous.reserve(max_visited.min(256));
        queue.push(query.source_node);
        previous.insert(query.source_node, (query.source_node, u32::MAX));
        let mut head = 0usize;

        while head < queue.len()
            && queue.len() <= max_visited
            && !previous.contains_key(&query.target_node)
        {
            let node = queue[head];
            head += 1;
            let start = offsets.get(node as usize).copied().unwrap_or(0) as usize;
            let end = offsets
                .get(node as usize + 1)
                .copied()
                .unwrap_or(start as u64) as usize;
            for neighbor in neighbors.get(start..end).unwrap_or_default() {
                if previous.contains_key(&neighbor.node) {
                    continue;
                }
                if previous.len() >= max_visited {
                    break;
                }
                previous.insert(neighbor.node, (node, neighbor.edge));
                queue.push(neighbor.node);
                if neighbor.node == query.target_node {
                    break;
                }
            }
        }

        let mut result = GalaxyPathQueryResult {
            visited_nodes: u32::try_from(previous.len()).unwrap_or(u32::MAX),
            ..GalaxyPathQueryResult::default()
        };
        if !previous.contains_key(&query.target_node) {
            result.node_indices = vec![query.source_node, query.target_node];
            result.truncated = previous.len() >= max_visited;
            return Ok(result);
        }

        let mut node = query.target_node;
        result.node_indices.push(node);
        while node != query.source_node {
            let Some(&(parent, edge)) = previous.get(&node) else {
                return Err(GalaxyStoreError::Invalid(
                    "bounded path predecessor chain is incomplete".to_owned(),
                ));
            };
            if result.edge_indices.len() >= max_path_edges {
                result.node_indices.clear();
                result.edge_indices.clear();
                result.truncated = true;
                return Ok(result);
            }
            result.edge_indices.push(edge);
            node = parent;
            result.node_indices.push(node);
        }
        result.node_indices.reverse();
        result.edge_indices.reverse();
        result.found = true;
        Ok(result)
    }
}

fn project_to_screen(point: [f32; 3], matrix: [f32; 16], viewport: [f32; 2]) -> Option<[f32; 2]> {
    let x = point[0];
    let y = point[1];
    let z = point[2];
    let clip_x = matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12];
    let clip_y = matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13];
    let clip_z = matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14];
    let clip_w = matrix[3] * x + matrix[7] * y + matrix[11] * z + matrix[15];
    if !clip_w.is_finite() || clip_w.abs() <= f32::EPSILON {
        return None;
    }
    let ndc_x = clip_x / clip_w;
    let ndc_y = clip_y / clip_w;
    let ndc_z = clip_z / clip_w;
    if !ndc_x.is_finite()
        || !ndc_y.is_finite()
        || !ndc_z.is_finite()
        || !(-1.0..=1.0).contains(&ndc_z)
    {
        return None;
    }
    Some([
        (ndc_x * 0.5 + 0.5) * viewport[0],
        (-ndc_y * 0.5 + 0.5) * viewport[1],
    ])
}

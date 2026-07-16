use std::cmp::Ordering;

use hashbrown::HashMap;
use phoenix_hyperbolic::{AnnMetric, HnswBuildParams, HyperbolicHnswBuilder};
use phoenix_store_native_core::SemanticNodeNeighbor;

use crate::semantic_graph_support::Prototype;

pub(crate) const EXACT_FALLBACK_MAX_TARGETS: usize = 64;
const MIN_ANN_SEARCH_WIDTH: usize = 32;
const ANN_SEARCH_OVERSAMPLE_MULTIPLIER: usize = 2;
const SPHERE_DISTANCE_FOR_DEGENERATE_EMPTY: f64 = std::f64::consts::FRAC_PI_2;
const SPHERE_EPS: f64 = 1e-12;

#[derive(Clone, Copy, Debug)]
pub(crate) struct EmbeddingRows<'a> {
    values: &'a [f32],
    rows: usize,
    dims: usize,
}

impl<'a> EmbeddingRows<'a> {
    pub(crate) fn from_flat(values: &'a [f32], rows: usize, dims: usize) -> Option<Self> {
        if rows == 0 {
            return values.is_empty().then_some(Self { values, rows, dims });
        }
        if dims == 0 || values.len() != rows.checked_mul(dims)? {
            return None;
        }
        Some(Self { values, rows, dims })
    }

    pub(crate) fn row(&self, index: usize) -> Option<&'a [f32]> {
        if index >= self.rows || self.dims == 0 {
            return None;
        }
        let start = index.checked_mul(self.dims)?;
        let end = start.checked_add(self.dims)?;
        self.values.get(start..end)
    }
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct SemanticNeighborHit {
    pub(crate) prototype_index: usize,
    pub(crate) distance: f64,
}

#[derive(Debug)]
struct CachedNeighborList {
    search_limit: usize,
    hits: Vec<SemanticNeighborHit>,
}

#[derive(Debug)]
struct AnnKindIndex {
    target_indices: Vec<usize>,
    index: HyperbolicHnswBuilder<AnnMetric>,
    dim: usize,
}

#[derive(Debug)]
pub(crate) struct SemanticTargetIndex {
    target_indices: Vec<usize>,
    ann: Option<AnnKindIndex>,
}

impl SemanticTargetIndex {
    pub(crate) fn new(target_indices: Vec<usize>, embeddings: EmbeddingRows<'_>) -> Self {
        let ann = build_kind_ann_index(&target_indices, embeddings);
        Self {
            target_indices,
            ann,
        }
    }

    pub(crate) fn query_neighbors(
        &self,
        source_index: usize,
        embeddings: EmbeddingRows<'_>,
        search_limit: usize,
    ) -> Vec<SemanticNeighborHit> {
        let Some(source_embedding) = embeddings.row(source_index) else {
            return Vec::new();
        };
        if let Some(index) = self.ann.as_ref() {
            if source_embedding.len() == index.dim {
                return build_neighbor_hits_from_ann(
                    source_index,
                    source_embedding,
                    index,
                    search_limit,
                );
            }
        }
        build_neighbor_hits_exact(
            source_index,
            &self.target_indices,
            source_embedding,
            embeddings,
            search_limit,
        )
    }

    #[cfg(test)]
    fn has_ann(&self) -> bool {
        self.ann.is_some()
    }
}

pub(crate) struct SemanticNeighborWorkspace<'a> {
    folder_id: Option<String>,
    folder_path: Option<String>,
    prototypes: &'a [Prototype],
    embeddings: EmbeddingRows<'a>,
    targets_by_kind: HashMap<&'static str, SemanticTargetIndex>,
    cache: HashMap<(usize, &'static str), CachedNeighborList>,
}

impl<'a> SemanticNeighborWorkspace<'a> {
    pub(crate) fn new(
        folder_id: Option<String>,
        folder_path: Option<String>,
        prototypes: &'a [Prototype],
        embeddings: EmbeddingRows<'a>,
    ) -> Self {
        let mut indices_by_kind = HashMap::<&'static str, Vec<usize>>::new();
        for (prototype_index, prototype) in prototypes.iter().enumerate() {
            indices_by_kind
                .entry(prototype.ann_kind)
                .or_default()
                .push(prototype_index);
        }
        let targets_by_kind = indices_by_kind
            .into_iter()
            .map(|(kind, indices)| (kind, SemanticTargetIndex::new(indices, embeddings)))
            .collect();
        Self {
            folder_id,
            folder_path,
            prototypes,
            embeddings,
            targets_by_kind,
            cache: HashMap::new(),
        }
    }

    pub(crate) fn query_semantic_node_neighbors(
        &mut self,
        source_index: usize,
        target_kind: &'static str,
        limit: usize,
        oversample: usize,
    ) -> Vec<SemanticNodeNeighbor> {
        if limit == 0 || target_kind.is_empty() {
            return Vec::new();
        }
        let search_limit = oversample.max(limit).max(1);
        let key = (source_index, target_kind);
        let needs_rebuild = self
            .cache
            .get(&key)
            .map(|cached| cached.search_limit < search_limit)
            .unwrap_or(true);
        if needs_rebuild {
            let cached = self.build_cached_neighbors(source_index, target_kind, search_limit);
            self.cache.insert(key, cached);
        }
        self.cache
            .get(&key)
            .map(|cached| {
                cached
                    .hits
                    .iter()
                    .take(limit)
                    .map(|hit| self.neighbor_from_hit(*hit))
                    .collect()
            })
            .unwrap_or_default()
    }

    fn build_cached_neighbors(
        &self,
        source_index: usize,
        target_kind: &'static str,
        search_limit: usize,
    ) -> CachedNeighborList {
        let Some(target_index) = self.targets_by_kind.get(target_kind) else {
            return CachedNeighborList {
                search_limit,
                hits: Vec::new(),
            };
        };
        let hits = target_index.query_neighbors(source_index, self.embeddings, search_limit);
        CachedNeighborList { search_limit, hits }
    }

    fn neighbor_from_hit(&self, hit: SemanticNeighborHit) -> SemanticNodeNeighbor {
        let prototype = &self.prototypes[hit.prototype_index];
        SemanticNodeNeighbor {
            node_id: prototype.node_id.clone(),
            node_kind: prototype.ann_kind.to_owned(),
            distance: hit.distance,
            document_id: prototype.document_id.clone(),
            note_id: prototype.note_id.clone(),
            narrative_id: prototype.narrative_id.clone(),
            folder_id: self.folder_id.clone(),
            folder_path: self.folder_path.clone(),
            evidence_refs: prototype.evidence_refs.clone(),
        }
    }

    #[cfg(test)]
    fn has_ann_index(&self, target_kind: &'static str) -> bool {
        self.targets_by_kind
            .get(target_kind)
            .map(SemanticTargetIndex::has_ann)
            .unwrap_or(false)
    }
}

fn build_kind_ann_index(indices: &[usize], embeddings: EmbeddingRows<'_>) -> Option<AnnKindIndex> {
    if indices.len() <= EXACT_FALLBACK_MAX_TARGETS {
        return None;
    }
    let first_index = *indices.first()?;
    let dim = embeddings.row(first_index)?.len();
    if dim == 0 {
        return None;
    }

    let metric = AnnMetric::default();
    let mut index = HyperbolicHnswBuilder::new(dim, metric, HnswBuildParams::default());
    let mut target_indices = Vec::with_capacity(indices.len());
    for &prototype_index in indices {
        let embedding = embeddings.row(prototype_index)?;
        if embedding.len() != dim {
            return None;
        }
        index.insert(embedding.to_vec());
        target_indices.push(prototype_index);
    }

    Some(AnnKindIndex {
        target_indices,
        index,
        dim,
    })
}

fn build_neighbor_hits_from_ann(
    source_index: usize,
    source_embedding: &[f32],
    index: &AnnKindIndex,
    search_limit: usize,
) -> Vec<SemanticNeighborHit> {
    if search_limit == 0 {
        return Vec::new();
    }
    let target_count = index.target_indices.len();
    let query_limit = search_limit
        .saturating_mul(ANN_SEARCH_OVERSAMPLE_MULTIPLIER)
        .saturating_add(1)
        .min(target_count)
        .max(1);
    let search_width = query_limit.max(MIN_ANN_SEARCH_WIDTH).min(target_count);
    let mut hits = index
        .index
        .search(source_embedding, query_limit, search_width)
        .into_iter()
        .filter_map(|candidate| {
            let prototype_index = *index.target_indices.get(candidate.id as usize)?;
            (prototype_index != source_index).then_some(SemanticNeighborHit {
                prototype_index,
                distance: candidate.dist as f64,
            })
        })
        .collect::<Vec<_>>();
    truncate_and_sort_hits(&mut hits, search_limit);
    hits
}

fn build_neighbor_hits_exact(
    source_index: usize,
    target_indices: &[usize],
    source_embedding: &[f32],
    embeddings: EmbeddingRows<'_>,
    search_limit: usize,
) -> Vec<SemanticNeighborHit> {
    if search_limit == 0 {
        return Vec::new();
    }
    let mut hits = Vec::<SemanticNeighborHit>::with_capacity(target_indices.len());
    for &target_index in target_indices {
        if target_index == source_index {
            continue;
        }
        let Some(target_embedding) = embeddings.row(target_index) else {
            continue;
        };
        hits.push(SemanticNeighborHit {
            prototype_index: target_index,
            distance: embedding_distance(source_embedding, target_embedding),
        });
    }
    truncate_and_sort_hits(&mut hits, search_limit);
    hits
}

fn truncate_and_sort_hits(hits: &mut Vec<SemanticNeighborHit>, search_limit: usize) {
    if hits.len() > search_limit {
        hits.select_nth_unstable_by(search_limit, compare_cached_hit);
        hits.truncate(search_limit);
    }
    hits.sort_unstable_by(compare_cached_hit);
}

fn compare_cached_hit(left: &SemanticNeighborHit, right: &SemanticNeighborHit) -> Ordering {
    left.distance
        .total_cmp(&right.distance)
        .then_with(|| left.prototype_index.cmp(&right.prototype_index))
}

pub(crate) fn embedding_distance(left: &[f32], right: &[f32]) -> f64 {
    let len = left.len().min(right.len());
    if len == 0 {
        return SPHERE_DISTANCE_FOR_DEGENERATE_EMPTY;
    }
    let mut dot0 = 0.0f64;
    let mut dot1 = 0.0f64;
    let mut dot2 = 0.0f64;
    let mut dot3 = 0.0f64;
    let mut left_norm0 = 0.0f64;
    let mut left_norm1 = 0.0f64;
    let mut left_norm2 = 0.0f64;
    let mut left_norm3 = 0.0f64;
    let mut right_norm0 = 0.0f64;
    let mut right_norm1 = 0.0f64;
    let mut right_norm2 = 0.0f64;
    let mut right_norm3 = 0.0f64;
    let mut finite = true;
    let mut index = 0usize;
    while index + 4 <= len {
        let left0 = left[index] as f64;
        let left1 = left[index + 1] as f64;
        let left2 = left[index + 2] as f64;
        let left3 = left[index + 3] as f64;
        let right0 = right[index] as f64;
        let right1 = right[index + 1] as f64;
        let right2 = right[index + 2] as f64;
        let right3 = right[index + 3] as f64;
        finite &= left0.is_finite()
            && left1.is_finite()
            && left2.is_finite()
            && left3.is_finite()
            && right0.is_finite()
            && right1.is_finite()
            && right2.is_finite()
            && right3.is_finite();
        dot0 += left0 * right0;
        dot1 += left1 * right1;
        dot2 += left2 * right2;
        dot3 += left3 * right3;
        left_norm0 += left0 * left0;
        left_norm1 += left1 * left1;
        left_norm2 += left2 * left2;
        left_norm3 += left3 * left3;
        right_norm0 += right0 * right0;
        right_norm1 += right1 * right1;
        right_norm2 += right2 * right2;
        right_norm3 += right3 * right3;
        index += 4;
    }
    let mut dot = dot0 + dot1 + dot2 + dot3;
    let mut left_norm_sq = left_norm0 + left_norm1 + left_norm2 + left_norm3;
    let mut right_norm_sq = right_norm0 + right_norm1 + right_norm2 + right_norm3;
    while index < len {
        let left_value = left[index] as f64;
        let right_value = right[index] as f64;
        finite &= left_value.is_finite() && right_value.is_finite();
        dot += left_value * right_value;
        left_norm_sq += left_value * left_value;
        right_norm_sq += right_value * right_value;
        index += 1;
    }
    if !finite {
        return SPHERE_DISTANCE_FOR_DEGENERATE_EMPTY;
    }

    let left_valid = left_norm_sq > SPHERE_EPS;
    let right_valid = right_norm_sq > SPHERE_EPS;
    let cosine = match (left_valid, right_valid) {
        (true, true) => dot / (left_norm_sq.sqrt() * right_norm_sq.sqrt()),
        (true, false) => left.first().copied().unwrap_or_default() as f64 / left_norm_sq.sqrt(),
        (false, true) => right.first().copied().unwrap_or_default() as f64 / right_norm_sq.sqrt(),
        (false, false) => 1.0,
    };
    cosine.clamp(-1.0, 1.0).acos()
}

#[cfg(test)]
mod tests {
    use phoenix_semantic_v2::{SemanticGraphNodeKind, SemanticGraphNodeRecord};

    use super::{EmbeddingRows, SemanticNeighborWorkspace, EXACT_FALLBACK_MAX_TARGETS};
    use crate::semantic_graph_support::{Prototype, CLAIM_KIND, STATE_KIND};

    fn prototype(
        node_id: &str,
        ann_kind: &'static str,
        node_kind: SemanticGraphNodeKind,
    ) -> Prototype {
        Prototype {
            node_id: node_id.to_owned(),
            ann_kind,
            node_kind,
            text_key: node_id.to_owned(),
            text: node_id.to_owned(),
            truth_plane: Some("world".to_owned()),
            document_id: Some("doc-1".to_owned()),
            note_id: Some("note-1".to_owned()),
            narrative_id: Some("nar-1".to_owned()),
            folder_id: Some("folder-a".to_owned()),
            folder_path: Some("/vault/folder-a".to_owned()),
            evidence_refs: vec![format!("evidence://{node_id}")],
            semantic_node: SemanticGraphNodeRecord {
                node_id: node_id.to_owned(),
                node_kind,
                document_id: Some("doc-1".to_owned()),
                narrative_id: Some("nar-1".to_owned()),
                text_key: node_id.to_owned(),
                text_hash: 1,
                truth_plane: Some("world".to_owned()),
                evidence_refs: Vec::new(),
            },
            slot_key: None,
            value_key: None,
            primary_entity_id: None,
            secondary_entity_id: None,
        }
    }

    #[test]
    fn workspace_skips_self_and_orders_hits_by_distance() {
        let prototypes = vec![
            prototype("graph::claim::1", CLAIM_KIND, SemanticGraphNodeKind::Claim),
            prototype("graph::claim::2", CLAIM_KIND, SemanticGraphNodeKind::Claim),
            prototype("graph::claim::3", CLAIM_KIND, SemanticGraphNodeKind::Claim),
        ];
        let embeddings = vec![0.0f32, 0.0, 0.1, 0.0, 0.9, 0.0];
        let embedding_rows = EmbeddingRows::from_flat(&embeddings, 3, 2).expect("embedding rows");
        let mut workspace = SemanticNeighborWorkspace::new(
            Some("folder-a".to_owned()),
            Some("/vault/folder-a".to_owned()),
            &prototypes,
            embedding_rows,
        );

        let hits = workspace.query_semantic_node_neighbors(0, CLAIM_KIND, 2, 2);

        assert_eq!(hits.len(), 2);
        assert_eq!(hits[0].node_id, "graph::claim::2");
        assert_eq!(hits[1].node_id, "graph::claim::3");
        assert_eq!(hits[0].folder_id.as_deref(), Some("folder-a"));
        assert_eq!(hits[0].folder_path.as_deref(), Some("/vault/folder-a"));
    }

    #[test]
    fn workspace_returns_empty_for_unknown_kind() {
        let prototypes = vec![prototype(
            "graph::state::1",
            STATE_KIND,
            SemanticGraphNodeKind::State,
        )];
        let embeddings = vec![0.0f32, 0.0];
        let embedding_rows = EmbeddingRows::from_flat(&embeddings, 1, 2).expect("embedding rows");
        let mut workspace = SemanticNeighborWorkspace::new(None, None, &prototypes, embedding_rows);

        let hits = workspace.query_semantic_node_neighbors(0, "", 4, 8);

        assert!(hits.is_empty());
    }

    #[test]
    fn workspace_uses_ann_for_large_kind_bucket() {
        let prototype_count = EXACT_FALLBACK_MAX_TARGETS + 8;
        let prototypes = (0..prototype_count)
            .map(|index| {
                prototype(
                    &format!("graph::claim::{index}"),
                    CLAIM_KIND,
                    SemanticGraphNodeKind::Claim,
                )
            })
            .collect::<Vec<_>>();
        let embeddings = (0..prototype_count)
            .map(|index| {
                let angle = index as f32 * 0.03125;
                vec![angle.cos(), angle.sin(), 0.01 * (index % 7) as f32, 0.25]
            })
            .collect::<Vec<_>>();
        let flat_embeddings = embeddings
            .iter()
            .flat_map(|row| row.iter().copied())
            .collect::<Vec<_>>();
        let embedding_rows =
            EmbeddingRows::from_flat(&flat_embeddings, prototype_count, 4).expect("embedding rows");
        let mut workspace = SemanticNeighborWorkspace::new(None, None, &prototypes, embedding_rows);

        let hits = workspace.query_semantic_node_neighbors(0, CLAIM_KIND, 4, 16);

        assert!(workspace.has_ann_index(CLAIM_KIND));
        assert_eq!(hits.len(), 4);
        assert!(hits.iter().all(|hit| hit.node_id != "graph::claim::0"));
    }
}

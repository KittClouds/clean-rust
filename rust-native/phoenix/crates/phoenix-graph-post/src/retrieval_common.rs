use phoenix_embed::{
    default_embedding_model_root, OrtTextEmbedConfig, OrtTextEmbedder, TextEmbeddingProfile,
};
use phoenix_graph::GraphBackendError;
use phoenix_graph_kernel::{
    bounded_walk_projected_graph, expand_snapshot_region, KernelEdge, KernelGraphSnapshot,
    KernelQuerySurface, KernelRegionProfile, KernelVertex, KernelViewRequest, KernelWalkBudget,
    KernelWalkScoring, KernelWalkSeed, KernelWalkSeedFamily,
};
#[cfg(test)]
use phoenix_graph_kernel::{
    KernelGraphLayer, KernelMutationBatch, KernelMutationScope, PhoenixGraphKernel,
};
#[cfg(test)]
use phoenix_semantic_v2::scope_storage_key;
use phoenix_store_native_core::{
    PhoenixLexicalQueryStore, PhoenixSemanticIndexStore, SemanticNodeNeighbor,
};
use phoenix_types::ScopeKey;
use rustc_hash::FxHashMap;
use std::cell::RefCell;
use std::sync::Arc;

use crate::api::GraphQueryError;
use crate::query_session::{ScopeQuerySession, SeedQueryCacheKey, SeedQuerySurface};
use crate::query_units::{build_query_unit_index, QueryUnitIndexCacheKey};
use crate::retrieval::{GraphRetrievedRegion, GraphRetrievedSeed};
use crate::runtime_telemetry::{
    measure_graph_runtime, record_embed_query_cache_hit, record_embed_query_cache_miss,
    record_region_build, record_region_input, record_seed_query_cache_hit,
    record_seed_query_cache_miss, record_seed_query_request, record_seed_query_stats,
    GraphRuntimeMetric,
};
use crate::semantic::ensure_ort_dylib_path;

thread_local! {
    static QUERY_EMBEDDER_CACHE: RefCell<QueryEmbedderCache> =
        RefCell::new(QueryEmbedderCache::default());
}

#[derive(Default)]
struct QueryEmbedderCache {
    attempted: bool,
    embedder: Option<OrtTextEmbedder>,
}

pub(crate) fn clear_query_embedder_cache() {
    QUERY_EMBEDDER_CACHE.with(|cell| {
        *cell.borrow_mut() = QueryEmbedderCache::default();
    });
}

pub(crate) fn retrieve_query_seeds<S>(
    store: &S,
    scope: &ScopeKey,
    query_text: &str,
    kinds: &[&str],
    seed_limit: usize,
    oversample: usize,
) -> Result<Vec<GraphRetrievedSeed>, GraphQueryError>
where
    S: PhoenixSemanticIndexStore,
{
    let _timer = measure_graph_runtime(GraphRuntimeMetric::RetrieveQuerySeeds);
    if query_text.trim().is_empty() {
        return Ok(Vec::new());
    }
    let kind_count = normalized_kind_count(kinds);
    record_seed_query_request(kind_count);
    let embedding = embed_query(query_text)?;
    let seed_limit = seed_limit.clamp(1, 24);
    let oversample = oversample.max(seed_limit).clamp(seed_limit, 96);
    let hits = store.query_semantic_node_neighbors_by_kinds(
        &embedding, scope, kinds, None, seed_limit, oversample,
    )?;
    record_seed_query_stats(kind_count, hits.len());
    Ok(finalize_seed_hits(hits, seed_limit))
}

pub(crate) fn retrieve_query_seeds_with_session<S>(
    store: &S,
    session: &ScopeQuerySession,
    query_text: &str,
    kinds: &[&str],
    seed_limit: usize,
    oversample: usize,
    surface: SeedQuerySurface,
    view_request: KernelViewRequest,
    view: &KernelQuerySurface,
) -> Result<Vec<GraphRetrievedSeed>, GraphQueryError>
where
    S: PhoenixLexicalQueryStore + PhoenixSemanticIndexStore,
{
    let _timer = measure_graph_runtime(GraphRuntimeMetric::RetrieveQuerySeeds);
    if query_text.trim().is_empty() {
        return Ok(Vec::new());
    }
    let seed_limit = seed_limit.clamp(1, 24);
    let oversample = oversample.max(seed_limit).clamp(seed_limit, 96);
    let kinds = normalized_kinds(kinds);
    record_seed_query_request(kinds.len());
    let cache_key = SeedQueryCacheKey {
        surface,
        valid_at: view_request.valid_at,
        recorded_at: view_request.recorded_at,
        include_candidate_graph: view_request.include_candidate_graph,
        kinds: kinds.clone(),
        seed_limit,
        oversample,
    };
    if let Some(cached) = session.cached_seed_surface(&cache_key) {
        record_seed_query_cache_hit();
        return Ok(cached);
    }
    record_seed_query_cache_miss();
    let kind_refs = kinds.iter().map(String::as_str).collect::<Vec<_>>();
    let semantic = retrieve_semantic_query_seeds_with_session(
        store,
        session,
        query_text,
        kind_refs.as_slice(),
        oversample,
    )?;
    let lexical = retrieve_lexical_query_seeds_with_session(
        store,
        session,
        query_text,
        kinds.as_slice(),
        oversample,
        view_request,
        view,
    );
    let seeds = fuse_seed_neighbors(&semantic, &lexical, seed_limit);
    record_seed_query_stats(kind_refs.len(), seeds.len());
    session.store_seed_surface(cache_key, &seeds);
    Ok(seeds)
}

pub(crate) fn build_region_from_snapshot(
    snapshot: &KernelGraphSnapshot,
    anchor_vertex_ids: Vec<String>,
    seeds: &[GraphRetrievedSeed],
    region_node_limit: usize,
    expansion_hops: usize,
    edge_allowed: fn(&KernelEdge) -> bool,
) -> (KernelGraphSnapshot, GraphRetrievedRegion) {
    let _timer = measure_graph_runtime(GraphRuntimeMetric::BuildRegionFromSnapshot);
    let seed_vertex_ids = seeds
        .iter()
        .filter(|seed| {
            snapshot
                .vertices
                .iter()
                .any(|vertex| vertex.id.0 == seed.node_id)
        })
        .map(|seed| seed.node_id.clone())
        .collect::<Vec<_>>();
    let expanded = expand_snapshot_region(
        snapshot,
        anchor_vertex_ids.as_slice(),
        seed_vertex_ids.as_slice(),
        region_node_limit,
        expansion_hops,
        edge_allowed,
    );
    let region = GraphRetrievedRegion::from_simple_expansion(anchor_vertex_ids, &expanded);
    record_region_build(
        region.vertex_count,
        region.asserted_edge_count,
        region.candidate_edge_count,
    );
    (expanded.snapshot, region)
}

pub(crate) fn graph_local_entity_slot_seeds(
    view: &KernelQuerySurface,
    entity_id: &str,
    slot_key: &str,
    seed_limit: usize,
) -> Vec<GraphRetrievedSeed> {
    let seed_limit = seed_limit.clamp(1, 24);
    let mut seeds = view
        .vertices()
        .iter()
        .filter(|vertex| vertex.entity_id.as_deref() == Some(entity_id))
        .filter_map(|vertex| {
            let score_millis = match vertex.kind.as_str() {
                "entity" => 1000,
                "state" if vertex_slot_key(vertex) == Some(slot_key) => 980,
                "claim" if vertex_slot_key(vertex) == Some(slot_key) => 940,
                "event" if vertex_slot_key(vertex) == Some(slot_key) => 900,
                _ => return None,
            };
            Some(GraphRetrievedSeed {
                node_id: vertex.id.0.clone(),
                node_kind: vertex.kind.clone(),
                score_millis,
                distance_millis: 1000_u32.saturating_sub(score_millis),
                document_id: vertex.document_id.clone(),
                narrative_id: None,
                evidence_refs: vec![format!("graph_vertex:{}", vertex.id.0)],
            })
        })
        .collect::<Vec<_>>();
    seeds.sort_by(|left, right| {
        right
            .score_millis
            .cmp(&left.score_millis)
            .then_with(|| left.node_id.cmp(&right.node_id))
    });
    seeds.dedup_by(|left, right| left.node_id == right.node_id);
    seeds.truncate(seed_limit);
    seeds
}

pub(crate) fn graph_local_target_seeds(
    view: &KernelQuerySurface,
    target_vertex_id: &str,
    seed_limit: usize,
) -> Vec<GraphRetrievedSeed> {
    let seed_limit = seed_limit.clamp(1, 24);
    let Some(target) = view.find_vertex(target_vertex_id) else {
        return Vec::new();
    };
    let mut seeds = Vec::new();
    push_graph_local_seed(&mut seeds, target, 1000);
    if let Some(entity_id) = target.entity_id.as_deref() {
        for vertex in view.vertices() {
            if vertex.kind == "entity" && vertex.entity_id.as_deref() == Some(entity_id) {
                push_graph_local_seed(&mut seeds, vertex, 980);
            }
        }
    }
    for edge in view.asserted_edges().iter().chain(view.candidate_edges()) {
        let neighbor_id = if edge.source_id.0 == target_vertex_id {
            edge.target_id.0.as_str()
        } else if edge.target_id.0 == target_vertex_id {
            edge.source_id.0.as_str()
        } else {
            continue;
        };
        if let Some(neighbor) = view.find_vertex(neighbor_id) {
            push_graph_local_seed(&mut seeds, neighbor, graph_local_edge_score(edge));
        }
    }
    seeds.sort_by(|left, right| {
        right
            .score_millis
            .cmp(&left.score_millis)
            .then_with(|| left.node_id.cmp(&right.node_id))
    });
    seeds.dedup_by(|left, right| left.node_id == right.node_id);
    seeds.truncate(seed_limit);
    seeds
}

#[allow(dead_code)]
pub(crate) fn build_region_from_view(
    view: &KernelQuerySurface,
    anchor_vertex_ids: Vec<String>,
    seeds: &[GraphRetrievedSeed],
    region_node_limit: usize,
    expansion_hops: usize,
    edge_allowed: fn(&KernelEdge) -> bool,
) -> (KernelGraphSnapshot, GraphRetrievedRegion) {
    build_region_from_view_profile(
        view,
        anchor_vertex_ids,
        seeds,
        region_node_limit,
        expansion_hops,
        edge_allowed,
        KernelRegionProfile::Generic,
    )
}

pub(crate) fn build_region_from_view_profile(
    view: &KernelQuerySurface,
    anchor_vertex_ids: Vec<String>,
    seeds: &[GraphRetrievedSeed],
    region_node_limit: usize,
    expansion_hops: usize,
    edge_allowed: fn(&KernelEdge) -> bool,
    profile: KernelRegionProfile,
) -> (KernelGraphSnapshot, GraphRetrievedRegion) {
    let _timer = measure_graph_runtime(GraphRuntimeMetric::BuildRegionFromView);
    record_region_input(
        view.vertices().len(),
        view.asserted_edges().len(),
        view.candidate_edges().len(),
        anchor_vertex_ids.len(),
        seeds.len(),
    );
    let seed_vertex_ids = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::FilterRegionSeeds);
        seeds
            .iter()
            .filter(|seed| view.find_vertex(seed.node_id.as_str()).is_some())
            .map(|seed| seed.node_id.clone())
            .collect::<Vec<_>>()
    };
    let walk_seeds = seed_vertex_ids
        .iter()
        .filter_map(|seed_vertex_id| {
            seeds
                .iter()
                .find(|seed| seed.node_id == *seed_vertex_id)
                .map(kernel_walk_seed_from_graph_seed)
        })
        .collect::<Vec<_>>();
    let pcst_compacted = true;
    let walk = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::ExpandRegionFromView);
        bounded_walk_projected_graph(
            view,
            anchor_vertex_ids.as_slice(),
            walk_seeds.as_slice(),
            KernelWalkBudget {
                max_nodes: region_node_limit,
                max_edges: region_node_limit.saturating_mul(4).max(64),
                max_depth: expansion_hops,
                max_per_family_fanout: 16,
                max_per_island_expansion: region_node_limit.max(8),
                profile,
                compact: pcst_compacted,
                ..KernelWalkBudget::default()
            },
            KernelWalkScoring::default(),
            edge_allowed,
        )
    };
    let region = {
        let _timer = measure_graph_runtime(GraphRuntimeMetric::AssembleRegionFromView);
        GraphRetrievedRegion::from_bounded_walk(anchor_vertex_ids, &walk, pcst_compacted)
    };
    record_region_build(
        region.vertex_count,
        region.asserted_edge_count,
        region.candidate_edge_count,
    );
    (walk.snapshot, region)
}

fn kernel_walk_seed_from_graph_seed(seed: &GraphRetrievedSeed) -> KernelWalkSeed {
    KernelWalkSeed {
        vertex_id: seed.node_id.clone(),
        family: KernelWalkSeedFamily::Graph,
        prize_millis: seed.score_millis,
        evidence_refs: seed.evidence_refs.clone(),
    }
}

#[cfg(test)]
pub(crate) fn kernel_from_snapshot(
    scope: &ScopeKey,
    snapshot: &KernelGraphSnapshot,
) -> Result<PhoenixGraphKernel, GraphBackendError> {
    let mut kernel = PhoenixGraphKernel::new();
    if !snapshot.vertices.is_empty() || !snapshot.asserted_edges.is_empty() {
        kernel.apply_kernel_batch(KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: format!("region:{}", scope_storage_key(scope)),
            },
            recorded_at: None,
            vertices: snapshot.vertices.clone(),
            edges: snapshot.asserted_edges.clone(),
        })?;
    }
    if !snapshot.candidate_edges.is_empty() {
        kernel.apply_kernel_batch(KernelMutationBatch {
            layer: KernelGraphLayer::Candidate,
            scope: KernelMutationScope::Candidate {
                scope_key: format!("region:{}", scope_storage_key(scope)),
            },
            recorded_at: None,
            vertices: Vec::new(),
            edges: snapshot.candidate_edges.clone(),
        })?;
    }
    Ok(kernel)
}

pub(crate) fn score_from_distance(distance: f64) -> u32 {
    ((1.0 / (1.0 + distance.max(0.0))) * 1000.0)
        .round()
        .clamp(0.0, 1000.0) as u32
}

pub(crate) fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

fn seed_from_neighbor(hit: SemanticNodeNeighbor) -> GraphRetrievedSeed {
    GraphRetrievedSeed {
        score_millis: score_from_distance(hit.distance),
        distance_millis: (hit.distance.max(0.0) * 1000.0).round() as u32,
        node_id: hit.node_id,
        node_kind: hit.node_kind,
        document_id: hit.document_id,
        narrative_id: hit.narrative_id,
        evidence_refs: hit.evidence_refs,
    }
}

fn finalize_seed_hits(
    hits: Vec<SemanticNodeNeighbor>,
    seed_limit: usize,
) -> Vec<GraphRetrievedSeed> {
    let mut best = FxHashMap::<String, GraphRetrievedSeed>::default();
    for hit in hits {
        let candidate = seed_from_neighbor(hit);
        match best.get(candidate.node_id.as_str()) {
            Some(existing) if existing.score_millis >= candidate.score_millis => {}
            _ => {
                best.insert(candidate.node_id.clone(), candidate);
            }
        }
    }
    let mut seeds = best.into_values().collect::<Vec<_>>();
    seeds.sort_by(|left, right| {
        right
            .score_millis
            .cmp(&left.score_millis)
            .then_with(|| left.node_id.cmp(&right.node_id))
    });
    seeds.truncate(seed_limit);
    seeds
}

fn retrieve_semantic_query_seeds_with_session<S>(
    store: &S,
    session: &ScopeQuerySession,
    query_text: &str,
    kinds: &[&str],
    limit: usize,
) -> Result<Vec<GraphRetrievedSeed>, GraphQueryError>
where
    S: PhoenixSemanticIndexStore,
{
    let embedding = embed_query_with_session(session, query_text)?;
    let hits = store.query_semantic_node_neighbors_by_kinds(
        &embedding,
        session.scope(),
        kinds,
        None,
        limit,
        limit,
    )?;
    Ok(finalize_seed_hits(hits, limit))
}

fn retrieve_lexical_query_seeds_with_session(
    store: &impl PhoenixLexicalQueryStore,
    session: &ScopeQuerySession,
    query_text: &str,
    kinds: &[String],
    limit: usize,
    view_request: KernelViewRequest,
    view: &KernelQuerySurface,
) -> Vec<GraphRetrievedSeed> {
    let lexical_kinds = lexical_index_kinds(kinds);
    if lexical_kinds.is_empty() {
        return Vec::new();
    }
    let cache_key = QueryUnitIndexCacheKey {
        valid_at: view_request.valid_at,
        recorded_at: view_request.recorded_at,
        include_candidate_graph: view_request.include_candidate_graph,
        kinds: lexical_kinds.clone(),
    };
    let index = if let Some(cached) = session.cached_query_unit_index(&cache_key) {
        cached
    } else {
        let built = load_persisted_chunk_lexical_index(store, session, &lexical_kinds)
            .or_else(|| build_query_unit_index(view, lexical_kinds.as_slice()));
        let Some(built) = built else {
            return Vec::new();
        };
        let built = Arc::new(built);
        session.store_query_unit_index(cache_key, built.clone());
        built
    };
    index.search(query_text, limit)
}

fn fuse_seed_neighbors(
    semantic: &[GraphRetrievedSeed],
    lexical: &[GraphRetrievedSeed],
    seed_limit: usize,
) -> Vec<GraphRetrievedSeed> {
    const RRF_K: f64 = 60.0;

    #[derive(Clone)]
    struct FusedSeed {
        seed: GraphRetrievedSeed,
        fused_score: f64,
    }

    let mut merged = FxHashMap::<String, FusedSeed>::default();
    for seeds in [semantic, lexical] {
        for (rank, seed) in seeds.iter().enumerate() {
            let contribution = 1.0 / (RRF_K + rank as f64 + 1.0);
            let entry = merged
                .entry(seed.node_id.clone())
                .or_insert_with(|| FusedSeed {
                    seed: seed.clone(),
                    fused_score: 0.0,
                });
            entry.fused_score += contribution;
            if entry.seed.score_millis < seed.score_millis {
                entry.seed.score_millis = seed.score_millis;
            }
            if entry.seed.distance_millis > seed.distance_millis {
                entry.seed.distance_millis = seed.distance_millis;
            }
            if entry.seed.document_id.is_none() {
                entry.seed.document_id = seed.document_id.clone();
            }
            if entry.seed.narrative_id.is_none() {
                entry.seed.narrative_id = seed.narrative_id.clone();
            }
            if entry.seed.node_kind.is_empty() {
                entry.seed.node_kind = seed.node_kind.clone();
            }
            entry
                .seed
                .evidence_refs
                .extend(seed.evidence_refs.iter().cloned());
        }
    }
    if merged.is_empty() {
        return Vec::new();
    }
    let max_score = merged
        .values()
        .map(|entry| entry.fused_score)
        .fold(0.0_f64, f64::max)
        .max(f64::EPSILON);
    let mut seeds = merged
        .into_values()
        .map(|mut entry| {
            entry.seed.evidence_refs.sort();
            entry.seed.evidence_refs.dedup();
            entry.seed.score_millis = ((entry.fused_score / max_score) * 1000.0)
                .round()
                .clamp(0.0, 1000.0) as u32;
            entry.seed.distance_millis = 1000_u32.saturating_sub(entry.seed.score_millis);
            entry.seed
        })
        .collect::<Vec<_>>();
    seeds.sort_by(|left, right| {
        right
            .score_millis
            .cmp(&left.score_millis)
            .then_with(|| left.distance_millis.cmp(&right.distance_millis))
            .then_with(|| left.node_id.cmp(&right.node_id))
    });
    seeds.truncate(seed_limit);
    seeds
}

fn normalized_kinds(kinds: &[&str]) -> Vec<String> {
    let mut kinds = kinds
        .iter()
        .copied()
        .filter(|kind| !kind.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    kinds.sort();
    kinds.dedup();
    kinds
}

fn normalized_kind_count(kinds: &[&str]) -> usize {
    normalized_kinds(kinds).len()
}

fn lexical_index_kinds(kinds: &[String]) -> Vec<String> {
    if kinds.iter().any(|kind| kind == "chunk") {
        return vec!["chunk".to_owned()];
    }
    kinds.to_vec()
}

fn load_persisted_chunk_lexical_index(
    store: &impl PhoenixLexicalQueryStore,
    session: &ScopeQuerySession,
    lexical_kinds: &[String],
) -> Option<crate::query_units::QueryUnitLexicalIndex> {
    if !should_use_persisted_scope_lexical_index(lexical_kinds) {
        return None;
    }
    store
        .load_scope_lexical_query_sidecar(session.scope())
        .ok()
        .flatten()
        .and_then(|sidecar| {
            crate::query_units::QueryUnitLexicalIndex::from_persisted_sidecar(&sidecar)
        })
}

fn should_use_persisted_scope_lexical_index(lexical_kinds: &[String]) -> bool {
    lexical_kinds.len() == 1 && lexical_kinds.first().is_some_and(|kind| kind == "chunk")
}

fn vertex_slot_key(vertex: &KernelVertex) -> Option<&str> {
    vertex
        .value
        .get("slotKey")
        .and_then(serde_json::Value::as_str)
        .or_else(|| {
            vertex
                .attributes
                .get("slotKey")
                .and_then(serde_json::Value::as_str)
        })
}

fn push_graph_local_seed(
    seeds: &mut Vec<GraphRetrievedSeed>,
    vertex: &KernelVertex,
    score_millis: u32,
) {
    if seeds.iter().any(|seed| seed.node_id == vertex.id.0) {
        return;
    }
    seeds.push(GraphRetrievedSeed {
        node_id: vertex.id.0.clone(),
        node_kind: vertex.kind.clone(),
        score_millis,
        distance_millis: 1000_u32.saturating_sub(score_millis),
        document_id: vertex.document_id.clone(),
        narrative_id: None,
        evidence_refs: vec![format!("graph_vertex:{}", vertex.id.0)],
    });
}

fn graph_local_edge_score(edge: &KernelEdge) -> u32 {
    match edge.edge_type.0.as_str() {
        "causal_link" => 970,
        "supported_by" | "canonicalized_as" => 950,
        "semantic::same_process" | "semantic::related_event" => 930,
        "semantic::missing_intermediate_cause" => 900,
        _ => 880,
    }
}

fn embed_query(query_text: &str) -> Result<Vec<f32>, GraphQueryError> {
    embed_queries(&[query_text.to_owned()]).and_then(|mut rows| {
        rows.pop().ok_or_else(|| {
            GraphQueryError::Kernel(GraphBackendError::Operation(
                "query embedder returned no vector".to_owned(),
            ))
        })
    })
}

fn embed_query_with_session(
    session: &ScopeQuerySession,
    query_text: &str,
) -> Result<Vec<f32>, GraphQueryError> {
    if let Some(cached) = session.cached_query_embedding(query_text) {
        record_embed_query_cache_hit();
        return Ok(cached);
    }
    record_embed_query_cache_miss(1);
    let embedding = embed_query(query_text)?;
    session.store_query_embedding(query_text, embedding.as_slice());
    Ok(embedding)
}

fn embed_queries(query_texts: &[String]) -> Result<Vec<Vec<f32>>, GraphQueryError> {
    let _timer = measure_graph_runtime(GraphRuntimeMetric::EmbedQuery);
    let query_refs = query_texts.iter().map(String::as_str).collect::<Vec<_>>();
    with_query_embedder(|embedder| {
        embedder
            .embed_texts(query_refs.as_slice())
            .map_err(|error| {
                GraphBackendError::Operation(format!("query embed inference failed: {error}"))
                    .into()
            })
    })
}

fn with_query_embedder<R>(
    f: impl FnOnce(&OrtTextEmbedder) -> Result<R, GraphQueryError>,
) -> Result<R, GraphQueryError> {
    QUERY_EMBEDDER_CACHE.with(|cell| {
        let mut cache = cell.borrow_mut();
        if !cache.attempted {
            let _timer = measure_graph_runtime(GraphRuntimeMetric::QueryEmbedderLoad);
            cache.attempted = true;
            let _ = ensure_ort_dylib_path();
            cache.embedder = Some(
                OrtTextEmbedder::load(&OrtTextEmbedConfig {
                    model_root: default_embedding_model_root(),
                    batch_size: 8,
                    max_length: 512,
                    profile: TextEmbeddingProfile::Native384,
                    prefix_passage: false,
                    pooling: Default::default(),
                    input_prefix: Default::default(),
                    batch_order: Default::default(),
                    execution_provider: Default::default(),
                })
                .map_err(|error| {
                    GraphBackendError::Operation(format!("query embed load failed: {error}"))
                })?,
            );
        }
        let embedder = cache.embedder.as_ref().ok_or_else(|| {
            GraphQueryError::Kernel(GraphBackendError::Operation(
                "query embedder was unavailable".to_owned(),
            ))
        })?;
        f(embedder)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seed(node_id: &str, node_kind: &str, score_millis: u32) -> GraphRetrievedSeed {
        GraphRetrievedSeed {
            node_id: node_id.to_owned(),
            node_kind: node_kind.to_owned(),
            score_millis,
            distance_millis: 1000_u32.saturating_sub(score_millis),
            document_id: Some("doc-1".to_owned()),
            narrative_id: None,
            evidence_refs: vec![format!("graph_vertex:{node_id}")],
        }
    }

    #[test]
    fn fused_seed_neighbors_merge_overlap_and_keep_unique_hits() {
        let semantic = vec![
            seed("graph::state::1", "state", 940),
            seed("graph::claim::1", "claim", 900),
        ];
        let lexical = vec![
            seed("graph::claim::1", "claim", 980),
            seed("graph::chunk::1", "chunk", 870),
        ];

        let fused = fuse_seed_neighbors(&semantic, &lexical, 8);
        let ids = fused
            .iter()
            .map(|seed| seed.node_id.as_str())
            .collect::<Vec<_>>();

        assert_eq!(
            ids,
            vec!["graph::claim::1", "graph::state::1", "graph::chunk::1"]
        );
        assert_eq!(fused[0].distance_millis, 0);
    }

    #[test]
    fn persisted_scope_lexical_index_is_chunk_only_for_now() {
        assert!(should_use_persisted_scope_lexical_index(&[
            "chunk".to_owned()
        ]));
        assert!(!should_use_persisted_scope_lexical_index(&[
            "state".to_owned()
        ]));
        assert!(!should_use_persisted_scope_lexical_index(&[
            "chunk".to_owned(),
            "state".to_owned()
        ]));
    }
}

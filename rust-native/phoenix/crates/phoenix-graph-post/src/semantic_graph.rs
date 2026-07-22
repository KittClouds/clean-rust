use hashbrown::{HashMap, HashSet};
use phoenix_graph_kernel::{
    KernelEdge, KernelEdgeType, KernelGraphLayer, KernelMutationBatch, KernelMutationScope,
    KernelProvenance, KernelRelationClass, KernelVertex, KernelVertexClass, KernelVertexId,
};
use phoenix_semantic_v2::{
    scope_storage_key, DocumentArchive, EventIdentityScopeSidecar, GraphDependencyManifest,
    GraphScopeSidecar, MemoryScopeSidecar, ScopeOrd, SemanticCandidateStatus, SemanticEdgeFamily,
    SemanticGraphCompilerSummary, SemanticGraphEdgeCandidate, SemanticGraphNodeKind,
    SemanticGraphScopeSidecar,
};
use phoenix_store_native_core::{
    NativeSemanticNodeVectorRecord, PhoenixArchiveStoreV2, PhoenixEventIdentityPatchStore,
    PhoenixGraphKernelStoreV2, PhoenixGraphLearningStore, PhoenixGraphPatchStore,
    PhoenixMemoryPatchStore, PhoenixSemanticGraphPatchStore, PhoenixSemanticIndexStore,
    SEMANTIC_MODEL_ID,
};
use phoenix_types::{ScopeKey, SessionId};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::BTreeMap;
use thiserror::Error;

use crate::promotion_lanes::append_semantic_phase5_promotion_commits;
use crate::semantic::SemanticEmbedConfig;
use crate::semantic_embedding_runtime::embed_texts_flat_cached;
use crate::semantic_graph_causal_gap::collect_missing_intermediate_cause_edges;
use crate::semantic_graph_contradiction::collect_contradictory_support_region_edges;
use crate::semantic_graph_event::collect_related_event_edges;
use crate::semantic_graph_lifecycle::{
    default_candidate_lifecycle_policy, retain_live_candidates, SemanticCandidateLifecycleStats,
};
use crate::semantic_graph_nli::{
    adjudicate_candidates_with_nli, needs_nli_review, SemanticNliConfig,
};
use crate::semantic_graph_process::collect_same_process_edges;
use crate::semantic_graph_soft::collect_same_slot_family_edges;
use crate::semantic_graph_support::{
    build_prototypes, family_label, neighbor_families, node_kind_label, resolve_family,
    status_label, truth_planes_compatible, Prototype, SEMANTIC_UNIT_PREFIX,
};
use crate::semantic_graph_workspace::{EmbeddingRows, SemanticNeighborWorkspace};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SemanticGraphConfig {
    pub embed: SemanticEmbedConfig,
    pub nli: Option<SemanticNliConfig>,
    pub neighbor_limit: usize,
    pub oversample: usize,
    pub min_score_millis: u32,
    pub index_node_vectors: bool,
    pub include_chunk_nodes: bool,
    pub include_event_nodes: bool,
}

impl Default for SemanticGraphConfig {
    fn default() -> Self {
        Self {
            embed: SemanticEmbedConfig::default(),
            nli: None,
            neighbor_limit: 3,
            oversample: 12,
            min_score_millis: 540,
            index_node_vectors: true,
            include_chunk_nodes: true,
            include_event_nodes: true,
        }
    }
}

#[derive(Debug, Error)]
pub enum SemanticGraphError {
    #[error(transparent)]
    Store(#[from] phoenix_store_native_core::StoreError),
    #[error(transparent)]
    Embed(#[from] crate::semantic::SemanticNeighborError),
    #[error(transparent)]
    Ort(#[from] phoenix_embed::OrtTextEmbedError),
    #[error("embedding batch shape mismatch: {0}")]
    EmbeddingShape(String),
    #[error(transparent)]
    Nli(#[from] phoenix_rel_post::NliError),
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticGraphReviewBatch {
    pub scope: ScopeKey,
    pub scope_key: String,
    pub scope_ord: ScopeOrd,
    pub session_id: Option<SessionId>,
    pub graph_generation: Option<u64>,
    pub memory_generation: Option<u64>,
    pub event_identity_generation: Option<u64>,
    pub embedding_cache_hits: usize,
    pub embedding_cache_misses: usize,
    pub sidecar: SemanticGraphScopeSidecar,
}

#[derive(Clone, Debug, PartialEq)]
struct SemanticGraphBuildResult {
    sidecar: SemanticGraphScopeSidecar,
    embedding_cache_hits: usize,
    embedding_cache_misses: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticGraphInputProfile {
    pub scope: ScopeKey,
    pub scope_key: String,
    pub node_count: usize,
    pub unique_text_count: usize,
    pub duplicate_text_count: usize,
    pub total_text_bytes: usize,
    pub max_text_bytes: usize,
    pub node_kind_counts: BTreeMap<String, usize>,
    pub unique_text_counts_by_kind: BTreeMap<String, usize>,
}

pub fn profile_semantic_graph_inputs_from_store<S>(
    store: &S,
    scope: &ScopeKey,
) -> Result<Option<SemanticGraphInputProfile>, SemanticGraphError>
where
    S: PhoenixArchiveStoreV2 + PhoenixMemoryPatchStore + PhoenixEventIdentityPatchStore,
{
    let archives = store.load_latest_document_archives(Some(scope))?;
    let memory_sidecar = store.load_memory_patch_sidecar(scope)?;
    let event_identity_sidecar = store.load_event_identity_patch_sidecar(scope)?;
    if archives.is_empty() && memory_sidecar.is_none() && event_identity_sidecar.is_none() {
        return Ok(None);
    }
    let scope_key = archives
        .first()
        .map(|archive| archive.manifest.scope_key.clone())
        .or_else(|| {
            memory_sidecar
                .as_ref()
                .map(|sidecar| scope_storage_key(&sidecar.scope))
        })
        .or_else(|| {
            event_identity_sidecar
                .as_ref()
                .map(|sidecar| scope_storage_key(&sidecar.scope))
        })
        .unwrap_or_else(|| scope_storage_key(scope));
    let prototypes = build_prototypes(
        &archives,
        event_identity_sidecar.as_ref(),
        memory_sidecar.as_ref(),
    );
    Ok(Some(profile_semantic_graph_inputs(
        scope,
        &scope_key,
        &prototypes,
    )))
}

fn profile_semantic_graph_inputs(
    scope: &ScopeKey,
    scope_key: &str,
    prototypes: &[Prototype],
) -> SemanticGraphInputProfile {
    let mut node_kind_counts = BTreeMap::<String, usize>::new();
    let mut seen_by_kind = HashSet::<(&'static str, u64)>::new();
    let mut unique_text_counts_by_kind = BTreeMap::<String, usize>::new();
    let mut seen_texts = HashSet::<u64>::new();
    let mut total_text_bytes = 0usize;
    let mut max_text_bytes = 0usize;
    for prototype in prototypes {
        let kind = node_kind_label(prototype.node_kind).to_owned();
        *node_kind_counts.entry(kind.clone()).or_default() += 1;
        let text_hash = prototype.semantic_node.text_hash;
        if seen_by_kind.insert((prototype.ann_kind, text_hash)) {
            *unique_text_counts_by_kind.entry(kind).or_default() += 1;
        }
        seen_texts.insert(text_hash);
        let text_bytes = prototype.text.len();
        total_text_bytes = total_text_bytes.saturating_add(text_bytes);
        max_text_bytes = max_text_bytes.max(text_bytes);
    }
    SemanticGraphInputProfile {
        scope: scope.clone(),
        scope_key: scope_key.to_owned(),
        node_count: prototypes.len(),
        unique_text_count: seen_texts.len(),
        duplicate_text_count: prototypes.len().saturating_sub(seen_texts.len()),
        total_text_bytes,
        max_text_bytes,
        node_kind_counts,
        unique_text_counts_by_kind,
    }
}

pub fn derive_semantic_graph_review_batch_from_store<S>(
    store: &S,
    scope: &ScopeKey,
    config: &SemanticGraphConfig,
    created_at: i64,
) -> Result<Option<SemanticGraphReviewBatch>, SemanticGraphError>
where
    S: PhoenixArchiveStoreV2
        + PhoenixGraphPatchStore
        + PhoenixMemoryPatchStore
        + PhoenixEventIdentityPatchStore
        + PhoenixSemanticIndexStore,
{
    let archives = store.load_latest_document_archives(Some(scope))?;
    let graph_sidecar = store.load_graph_patch_sidecar(scope)?;
    let memory_sidecar = store.load_memory_patch_sidecar(scope)?;
    let event_identity_sidecar = store.load_event_identity_patch_sidecar(scope)?;
    if archives.is_empty() && graph_sidecar.is_none() && memory_sidecar.is_none() {
        return Ok(None);
    }
    let scope_key = archives
        .first()
        .map(|archive| archive.manifest.scope_key.clone())
        .or_else(|| {
            graph_sidecar
                .as_ref()
                .map(|sidecar| sidecar.scope_key.clone())
        })
        .or_else(|| {
            memory_sidecar
                .as_ref()
                .map(|sidecar| sidecar.scope_key.clone())
        })
        .unwrap_or_else(|| scope_storage_key(scope));
    let scope_ord = archives
        .first()
        .map(|archive| archive.manifest.scope_ord)
        .or_else(|| graph_sidecar.as_ref().and_then(|sidecar| sidecar.scope_ord))
        .or_else(|| {
            memory_sidecar
                .as_ref()
                .and_then(|sidecar| sidecar.scope_ord)
        })
        .unwrap_or_default();
    let session_id = archives
        .iter()
        .find_map(|archive| archive.manifest.session_id.clone())
        .or_else(|| {
            graph_sidecar
                .as_ref()
                .and_then(|sidecar| sidecar.session_id.clone())
        })
        .or_else(|| {
            memory_sidecar
                .as_ref()
                .and_then(|sidecar| sidecar.session_id.clone())
        });
    let build = build_semantic_graph_sidecar_with_stats(
        store,
        scope,
        &scope_key,
        scope_ord,
        session_id.as_ref(),
        &archives,
        graph_sidecar.as_ref(),
        event_identity_sidecar.as_ref(),
        memory_sidecar.as_ref(),
        config,
        created_at,
    )?;
    Ok(Some(SemanticGraphReviewBatch {
        scope: scope.clone(),
        scope_key,
        scope_ord,
        session_id,
        graph_generation: graph_sidecar.as_ref().map(|sidecar| sidecar.generation),
        memory_generation: memory_sidecar.as_ref().map(|sidecar| sidecar.generation),
        event_identity_generation: event_identity_sidecar
            .as_ref()
            .map(|sidecar| sidecar.generation),
        embedding_cache_hits: build.embedding_cache_hits,
        embedding_cache_misses: build.embedding_cache_misses,
        sidecar: build.sidecar,
    }))
}

pub fn persist_semantic_graph_patch_sidecar<S>(
    store: &S,
    sidecar: &SemanticGraphScopeSidecar,
) -> Result<(), SemanticGraphError>
where
    S: PhoenixSemanticGraphPatchStore + PhoenixGraphKernelStoreV2 + PhoenixGraphLearningStore,
{
    append_semantic_phase5_promotion_commits(store, sidecar)?;
    store.persist_semantic_graph_patch_sidecar(sidecar)?;
    Ok(())
}

pub fn build_semantic_graph_sidecar<S>(
    store: &S,
    scope: &ScopeKey,
    scope_key: &str,
    scope_ord: ScopeOrd,
    session_id: Option<&SessionId>,
    archives: &[DocumentArchive],
    graph_sidecar: Option<&GraphScopeSidecar>,
    event_identity_sidecar: Option<&EventIdentityScopeSidecar>,
    memory_sidecar: Option<&MemoryScopeSidecar>,
    config: &SemanticGraphConfig,
    created_at: i64,
) -> Result<SemanticGraphScopeSidecar, SemanticGraphError>
where
    S: PhoenixSemanticIndexStore,
{
    Ok(build_semantic_graph_sidecar_with_stats(
        store,
        scope,
        scope_key,
        scope_ord,
        session_id,
        archives,
        graph_sidecar,
        event_identity_sidecar,
        memory_sidecar,
        config,
        created_at,
    )?
    .sidecar)
}

fn build_semantic_graph_sidecar_with_stats<S>(
    store: &S,
    scope: &ScopeKey,
    scope_key: &str,
    scope_ord: ScopeOrd,
    session_id: Option<&SessionId>,
    archives: &[DocumentArchive],
    graph_sidecar: Option<&GraphScopeSidecar>,
    event_identity_sidecar: Option<&EventIdentityScopeSidecar>,
    memory_sidecar: Option<&MemoryScopeSidecar>,
    config: &SemanticGraphConfig,
    created_at: i64,
) -> Result<SemanticGraphBuildResult, SemanticGraphError>
where
    S: PhoenixSemanticIndexStore,
{
    let dependency_manifest = semantic_dependency_manifest(
        graph_sidecar.map(|sidecar| sidecar.generation),
        memory_sidecar.map(|sidecar| sidecar.generation),
        event_identity_sidecar.map(|sidecar| sidecar.generation),
    );
    let lifecycle_policy = default_candidate_lifecycle_policy(config.min_score_millis);
    let mut prototypes = build_prototypes(archives, event_identity_sidecar, memory_sidecar);
    retain_configured_prototypes(&mut prototypes, config);
    let model_id = semantic_model_id(&config.embed);
    let embedding_dim = config.embed.profile.target_dim();
    let texts = prototypes
        .iter()
        .map(|prototype| prototype.text.as_str())
        .collect::<Vec<_>>();
    let (unique_texts, prototype_to_unique) = dedupe_embedding_texts(&texts);
    let unique_embeddings = embed_texts_flat_cached(&config.embed, &unique_texts)?;
    if unique_embeddings.rows != unique_texts.len() || unique_embeddings.dims != embedding_dim {
        return Err(SemanticGraphError::EmbeddingShape(format!(
            "expected {} rows x {} dims, got {} rows x {} dims",
            unique_texts.len(),
            embedding_dim,
            unique_embeddings.rows,
            unique_embeddings.dims
        )));
    }
    let expanded_embeddings =
        expand_embedding_rows(&unique_embeddings, &prototype_to_unique, embedding_dim)?;
    let embedding_rows =
        EmbeddingRows::from_flat(&expanded_embeddings, prototypes.len(), embedding_dim)
            .ok_or_else(|| {
                SemanticGraphError::EmbeddingShape(format!(
            "expanded embedding batch shape mismatch: expected {} rows x {} dims, got {} values",
            prototypes.len(),
            embedding_dim,
            expanded_embeddings.len()
        ))
            })?;
    let mut workspace = SemanticNeighborWorkspace::new(
        scope.folder_id.clone(),
        scope.folder_path.clone(),
        &prototypes,
        embedding_rows,
    );
    let mut candidates = collect_candidate_edges(
        &mut workspace,
        &prototypes,
        config.neighbor_limit.max(1),
        config.oversample.max(config.neighbor_limit.max(1)),
        config.min_score_millis,
    );
    candidates.extend(collect_same_slot_family_edges(
        &mut workspace,
        &prototypes,
        config.neighbor_limit.max(1),
        config.oversample.max(config.neighbor_limit.max(1)),
        config.min_score_millis,
    ));
    candidates.extend(collect_contradictory_support_region_edges(
        &prototypes,
        embedding_rows,
        memory_sidecar,
        config.neighbor_limit.max(1),
        config.oversample.max(config.neighbor_limit.max(1)),
        config.min_score_millis,
    ));
    candidates.extend(collect_same_process_edges(
        &mut workspace,
        &prototypes,
        config.neighbor_limit.max(1),
        config.oversample.max(config.neighbor_limit.max(1)),
        config.min_score_millis,
    ));
    candidates.extend(collect_related_event_edges(
        &mut workspace,
        &prototypes,
        config.neighbor_limit.max(1),
        config.oversample.max(config.neighbor_limit.max(1)),
        config.min_score_millis,
    ));
    candidates.extend(collect_missing_intermediate_cause_edges(
        &mut workspace,
        &prototypes,
        graph_sidecar,
        config.neighbor_limit.max(1),
        config.oversample.max(config.neighbor_limit.max(1)),
        config.min_score_millis,
    ));
    drop(workspace);
    if config.index_node_vectors {
        let rows = prototypes
            .iter()
            .zip(expanded_embeddings.chunks_exact(embedding_dim))
            .map(|(prototype, values)| NativeSemanticNodeVectorRecord {
                scope: scope.clone(),
                node_id: prototype.node_id.clone(),
                node_kind: prototype.ann_kind.to_owned(),
                document_id: prototype.document_id.clone(),
                note_id: prototype.note_id.clone(),
                narrative_id: prototype.narrative_id.clone(),
                folder_id: scope.folder_id.clone(),
                folder_path: scope.folder_path.clone(),
                values: values.to_vec(),
                evidence_refs: prototype.evidence_refs.clone(),
                updated_at: created_at,
            })
            .collect::<Vec<_>>();
        store.upsert_semantic_node_vectors_native_owned_for_model(model_id, rows)?;
        let mut warmed_kinds = prototypes
            .iter()
            .map(|prototype| prototype.ann_kind)
            .collect::<Vec<_>>();
        warmed_kinds.sort_unstable();
        warmed_kinds.dedup();
        for &kind in &warmed_kinds {
            store.warm_semantic_node_index_for_model(model_id, embedding_dim, scope, kind)?;
        }
        store.warm_semantic_node_indexes_for_model(
            model_id,
            embedding_dim,
            scope,
            &warmed_kinds,
        )?;
    }
    if candidates
        .iter()
        .any(|candidate| needs_nli_review(candidate.family))
    {
        if let Some(nli_config) = config.nli.as_ref() {
            let nli = nli_config.load_model()?;
            adjudicate_candidates_with_nli(&mut candidates, &prototypes, &nli, nli_config)?;
        }
    }
    let (mut candidates, lifecycle_stats) =
        retain_live_candidates(candidates, graph_sidecar, &lifecycle_policy);
    candidates.sort_by(|left, right| left.edge_id.cmp(&right.edge_id));
    let batch =
        compile_candidate_graph_batch(scope_key, &prototypes, &candidates, created_at, model_id);
    let summary = summarize(&prototypes, &candidates, &lifecycle_stats);
    Ok(SemanticGraphBuildResult {
        embedding_cache_hits: unique_embeddings.cache_hits,
        embedding_cache_misses: unique_embeddings.cache_misses,
        sidecar: SemanticGraphScopeSidecar {
            scope: scope.clone(),
            scope_key: scope_key.to_owned(),
            scope_ord: Some(scope_ord),
            session_id: session_id.cloned(),
            updated_at: created_at,
            generation: created_at as u64,
            model_id: model_id.to_owned(),
            embedding_profile: config.embed.profile.label().to_owned(),
            embedding_dim,
            dependency_manifest,
            candidate_lifecycle_policy: lifecycle_policy,
            candidate_nodes: prototypes
                .iter()
                .map(|prototype| prototype.semantic_node.clone())
                .collect(),
            candidate_edges: candidates,
            candidate_graph_batch: batch,
            graph_generation: dependency_manifest.graph_generation,
            memory_generation: dependency_manifest.memory_generation,
            event_identity_generation: dependency_manifest.event_identity_generation,
            summary,
        },
    })
}

pub(crate) fn retain_configured_prototypes(
    prototypes: &mut Vec<Prototype>,
    config: &SemanticGraphConfig,
) {
    if !config.include_chunk_nodes {
        prototypes.retain(|prototype| prototype.node_kind != SemanticGraphNodeKind::Chunk);
    }
    if !config.include_event_nodes {
        prototypes.retain(|prototype| prototype.node_kind != SemanticGraphNodeKind::Event);
    }
}

pub(crate) fn dedupe_embedding_texts<'a>(texts: &[&'a str]) -> (Vec<&'a str>, Vec<usize>) {
    let mut unique_texts = Vec::new();
    let mut unique_by_text = HashMap::<&'a str, usize>::new();
    let mut row_map = Vec::with_capacity(texts.len());
    for &text in texts {
        let index = match unique_by_text.get(text).copied() {
            Some(index) => index,
            None => {
                let index = unique_texts.len();
                unique_texts.push(text);
                unique_by_text.insert(text, index);
                index
            }
        };
        row_map.push(index);
    }
    (unique_texts, row_map)
}

fn expand_embedding_rows(
    unique_embeddings: &crate::semantic::SemanticEmbeddingBatch,
    prototype_to_unique: &[usize],
    embedding_dim: usize,
) -> Result<Vec<f32>, SemanticGraphError> {
    let mut values = Vec::with_capacity(prototype_to_unique.len().saturating_mul(embedding_dim));
    for &unique_index in prototype_to_unique {
        let start = unique_index.saturating_mul(embedding_dim);
        let end = start.saturating_add(embedding_dim);
        let Some(row) = unique_embeddings.values.get(start..end) else {
            return Err(SemanticGraphError::EmbeddingShape(format!(
                "missing deduped embedding row {unique_index}"
            )));
        };
        if row.len() != embedding_dim {
            return Err(SemanticGraphError::EmbeddingShape(format!(
                "deduped embedding row shape mismatch: expected {embedding_dim}, got {}",
                row.len()
            )));
        }
        values.extend_from_slice(row);
    }
    Ok(values)
}

fn semantic_model_id(config: &SemanticEmbedConfig) -> &str {
    let model_id = config.model_id.trim();
    if model_id.is_empty() {
        SEMANTIC_MODEL_ID
    } else {
        model_id
    }
}

fn collect_candidate_edges(
    workspace: &mut SemanticNeighborWorkspace<'_>,
    prototypes: &[Prototype],
    neighbor_limit: usize,
    oversample: usize,
    min_score_millis: u32,
) -> Vec<SemanticGraphEdgeCandidate> {
    let prototype_by_id = prototypes
        .iter()
        .map(|prototype| (prototype.node_id.as_str(), prototype))
        .collect::<HashMap<_, _>>();
    let mut seen = HashSet::new();
    let mut edges = Vec::new();
    for (source_index, prototype) in prototypes.iter().enumerate() {
        for (target_kind, family) in neighbor_families(prototype.node_kind) {
            if target_kind.is_empty() || family == SemanticEdgeFamily::Unknown {
                continue;
            }
            for hit in workspace.query_semantic_node_neighbors(
                source_index,
                target_kind,
                neighbor_limit,
                oversample,
            ) {
                let Some(target) = prototype_by_id.get(hit.node_id.as_str()) else {
                    continue;
                };
                if !truth_planes_compatible(
                    prototype.truth_plane.as_deref(),
                    target.truth_plane.as_deref(),
                ) {
                    continue;
                }
                let family = resolve_family(family, prototype, target);
                let score_millis = neighbor_score_millis(hit.distance);
                if score_millis < min_score_millis {
                    continue;
                }
                let dedupe = dedupe_key(family, prototype, target);
                if !seen.insert(dedupe) {
                    continue;
                }
                edges.push(SemanticGraphEdgeCandidate {
                    edge_id: format!(
                        "semantic:{}:{}:{}",
                        family_label(family),
                        prototype.node_id,
                        target.node_id
                    ),
                    family,
                    source_node_id: prototype.node_id.clone(),
                    source_kind: prototype.node_kind,
                    target_node_id: target.node_id.clone(),
                    target_kind: target.node_kind,
                    score_millis,
                    distance_millis: (hit.distance.max(0.0) * 1000.0).round() as u32,
                    candidate_status: SemanticCandidateStatus::Generated,
                    evidence_refs: merge_refs(&prototype.evidence_refs, &hit.evidence_refs),
                    model_evidence: vec![format!("ann:distance={:.4}", hit.distance)],
                    nli_support_millis: None,
                    nli_contradiction_millis: None,
                });
            }
        }
    }
    edges.sort_by(|left, right| left.edge_id.cmp(&right.edge_id));
    edges
}

pub(crate) fn compile_candidate_graph_batch(
    scope_key: &str,
    prototypes: &[Prototype],
    candidates: &[SemanticGraphEdgeCandidate],
    created_at: i64,
    model_id: &str,
) -> KernelMutationBatch {
    let prototype_by_id = prototypes
        .iter()
        .map(|prototype| (prototype.node_id.as_str(), prototype))
        .collect::<HashMap<_, _>>();
    let mut vertices = Vec::new();
    let mut seen_vertices = HashSet::new();
    let mut edges = Vec::with_capacity(candidates.len());
    for prototype in prototypes {
        if prototype.node_id.starts_with(SEMANTIC_UNIT_PREFIX)
            && seen_vertices.insert(prototype.node_id.as_str())
        {
            vertices.push(candidate_vertex(prototype, created_at, model_id));
        }
    }
    for candidate in candidates {
        if candidate.candidate_status == SemanticCandidateStatus::Rejected {
            continue;
        }
        let Some(source) = prototype_by_id.get(candidate.source_node_id.as_str()) else {
            continue;
        };
        let Some(target) = prototype_by_id.get(candidate.target_node_id.as_str()) else {
            continue;
        };
        for node_id in [&candidate.source_node_id, &candidate.target_node_id] {
            if seen_vertices.insert(node_id.as_str()) {
                if let Some(prototype) = prototype_by_id.get(node_id.as_str()) {
                    if matches!(
                        prototype.node_kind,
                        SemanticGraphNodeKind::Chunk | SemanticGraphNodeKind::Entity
                    ) {
                        vertices.push(candidate_vertex(prototype, created_at, model_id));
                    }
                }
            }
        }
        edges.push(KernelEdge {
            source_id: KernelVertexId(candidate.source_node_id.clone()),
            target_id: KernelVertexId(candidate.target_node_id.clone()),
            edge_type: KernelEdgeType(format!("semantic::{}", family_label(candidate.family))),
            relation_class: KernelRelationClass::Candidate,
            weight: candidate.score_millis as i64,
            attributes: json!({
                "family": family_label(candidate.family),
                "status": status_label(candidate.candidate_status),
                "scoreMillis": candidate.score_millis,
                "distanceMillis": candidate.distance_millis,
                "sourceKind": node_kind_label(candidate.source_kind),
                "targetKind": node_kind_label(candidate.target_kind),
                "nliSupportMillis": candidate.nli_support_millis,
                "nliContradictionMillis": candidate.nli_contradiction_millis,
            }),
            data: None,
            document_id: None,
            note_id: shared_option(source.note_id.as_deref(), target.note_id.as_deref()),
            narrative_id: shared_option(
                source.narrative_id.as_deref(),
                target.narrative_id.as_deref(),
            ),
            folder_id: shared_option(source.folder_id.as_deref(), target.folder_id.as_deref()),
            folder_path: shared_option(
                source.folder_path.as_deref(),
                target.folder_path.as_deref(),
            ),
            layer: KernelGraphLayer::Candidate,
            temporal: Default::default(),
            provenance: KernelProvenance {
                resolver: Some("semantic-graph".to_owned()),
                source: Some(model_id.to_owned()),
                confidence: Some(candidate.score_millis as f64 / 1000.0),
                evidence_refs: candidate.evidence_refs.clone(),
            },
            resolution_facet: None,
        });
    }
    KernelMutationBatch {
        layer: KernelGraphLayer::Candidate,
        scope: KernelMutationScope::Candidate {
            scope_key: scope_key.to_owned(),
        },
        recorded_at: Some(created_at),
        vertices,
        edges,
    }
}

fn candidate_vertex(prototype: &Prototype, created_at: i64, model_id: &str) -> KernelVertex {
    KernelVertex {
        id: KernelVertexId(prototype.node_id.clone()),
        kind: prototype.ann_kind.to_owned(),
        class: match prototype.node_kind {
            SemanticGraphNodeKind::Chunk => KernelVertexClass::Chunk,
            SemanticGraphNodeKind::Entity => KernelVertexClass::Entity,
            SemanticGraphNodeKind::State => KernelVertexClass::State,
            SemanticGraphNodeKind::Event => KernelVertexClass::Event,
            _ => KernelVertexClass::Generic,
        },
        labels: vec![prototype.text_key.clone()],
        weight: 1,
        value: json!({
            "textKey": prototype.text_key,
            "textHash": prototype.semantic_node.text_hash,
            "text": prototype.text,
        }),
        attributes: json!({"semanticCandidate": true}),
        temporal: phoenix_graph_kernel::KernelBiTemporal {
            recorded_at: Some(created_at),
            ..Default::default()
        },
        provenance: KernelProvenance {
            resolver: Some("semantic-graph".to_owned()),
            source: Some(model_id.to_owned()),
            confidence: Some(1.0),
            evidence_refs: prototype.evidence_refs.clone(),
        },
        entity_id: match prototype.node_kind {
            SemanticGraphNodeKind::Entity => {
                Some(prototype.node_id.trim_start_matches("entity::").to_owned())
            }
            SemanticGraphNodeKind::Claim
            | SemanticGraphNodeKind::State
            | SemanticGraphNodeKind::Event => prototype.primary_entity_id.clone(),
            _ => None,
        },
        search_chunk_id: None,
        document_id: prototype.document_id.clone(),
        note_id: prototype.note_id.clone(),
        narrative_id: prototype.narrative_id.clone(),
        folder_id: prototype.folder_id.clone(),
        folder_path: prototype.folder_path.clone(),
        chapter_id: None,
        chapters: Vec::new(),
        boundary_id: None,
        boundary_ordinal: None,
        boundary_kind: None,
        boundary_ordinals: Vec::new(),
        entity_facet: None,
        calendar_facet: None,
    }
}

fn shared_option(left: Option<&str>, right: Option<&str>) -> Option<String> {
    match (left, right) {
        (Some(left), Some(right)) if left == right => Some(left.to_owned()),
        _ => None,
    }
}

pub(crate) fn summarize(
    prototypes: &[Prototype],
    candidates: &[SemanticGraphEdgeCandidate],
    lifecycle_stats: &SemanticCandidateLifecycleStats,
) -> SemanticGraphCompilerSummary {
    let mut summary = SemanticGraphCompilerSummary {
        node_count: prototypes.len(),
        expired_count: lifecycle_stats.expired_count,
        rejected_count: lifecycle_stats.rejected_count,
        superseded_asserted_count: lifecycle_stats.superseded_asserted_count,
        ..Default::default()
    };
    for prototype in prototypes {
        *summary
            .node_kind_counts
            .entry(node_kind_label(prototype.node_kind).to_owned())
            .or_default() += 1;
    }
    for candidate in candidates {
        match candidate.candidate_status {
            SemanticCandidateStatus::Generated => summary.generated_count += 1,
            SemanticCandidateStatus::Deferred => summary.deferred_count += 1,
            SemanticCandidateStatus::ReviewedSupport => summary.reviewed_support_count += 1,
            SemanticCandidateStatus::ReviewedContradiction => {
                summary.reviewed_contradiction_count += 1
            }
            SemanticCandidateStatus::Rejected => {
                summary.rejected_count += 1;
                continue;
            }
        }
        summary.edge_count += 1;
        *summary
            .edge_family_counts
            .entry(family_label(candidate.family).to_owned())
            .or_default() += 1;
    }
    summary
}

fn semantic_dependency_manifest(
    graph_generation: Option<u64>,
    memory_generation: Option<u64>,
    event_identity_generation: Option<u64>,
) -> GraphDependencyManifest {
    GraphDependencyManifest {
        event_identity_generation,
        temporal_generation: None,
        causal_generation: None,
        memory_generation,
        graph_generation,
    }
}

fn dedupe_key(family: SemanticEdgeFamily, source: &Prototype, target: &Prototype) -> String {
    match family {
        SemanticEdgeFamily::ChunkNeighbor
        | SemanticEdgeFamily::ClaimSupport
        | SemanticEdgeFamily::ClaimContradiction
        | SemanticEdgeFamily::StateSupport
        | SemanticEdgeFamily::StateContradiction
        | SemanticEdgeFamily::ContradictorySupportRegion
        | SemanticEdgeFamily::SameProcess
        | SemanticEdgeFamily::RelatedEvent
        | SemanticEdgeFamily::EventNeighbor => {
            let (left, right) = if source.node_id <= target.node_id {
                (&source.node_id, &target.node_id)
            } else {
                (&target.node_id, &source.node_id)
            };
            format!("{}|{}|{}", family_label(family), left, right)
        }
        _ => format!(
            "{}|{}|{}",
            family_label(family),
            source.node_id,
            target.node_id
        ),
    }
}

fn neighbor_score_millis(distance: f64) -> u32 {
    ((1.0 / (1.0 + distance.max(0.0))) * 1000.0)
        .round()
        .clamp(0.0, 1000.0) as u32
}

fn merge_refs(left: &[String], right: &[String]) -> Vec<String> {
    let mut merged = left.iter().chain(right.iter()).cloned().collect::<Vec<_>>();
    merged.sort();
    merged.dedup();
    merged
}

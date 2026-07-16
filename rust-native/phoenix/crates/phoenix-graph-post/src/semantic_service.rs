use std::path::PathBuf;
use std::time::Instant;

use phoenix_embed::{OrtExecutionProviderPreference, TextEmbeddingProfile};
use phoenix_graph_kernel::KernelMutationScope;
use phoenix_semantic_v2::{SemanticGraphCompilerSummary, SemanticGraphScopeSidecar};
use phoenix_store_native_core::{
    PhoenixArchiveStoreV2, PhoenixEventIdentityPatchStore, PhoenixGraphPatchStore,
    PhoenixMemoryPatchStore, PhoenixSemanticIndexStore, StoreError,
};
use phoenix_types::ScopeKey;
use serde::{Deserialize, Serialize};

use crate::semantic_graph::{
    derive_semantic_graph_review_batch_from_store, SemanticGraphConfig, SemanticGraphError,
    SemanticGraphReviewBatch,
};

const SERVICE_CONTRACT_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum SemanticEmbedderLaneMode {
    #[default]
    TruthReview,
    Events,
    Chunks,
    Full,
}

impl SemanticEmbedderLaneMode {
    pub fn label(self) -> &'static str {
        match self {
            Self::TruthReview => "truth-review",
            Self::Events => "events",
            Self::Chunks => "chunks",
            Self::Full => "full",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticEmbedderModelRequest {
    pub model_id: Option<String>,
    pub model_root: Option<PathBuf>,
    pub embedding_profile: Option<String>,
    pub batch_size: Option<usize>,
    pub max_length: Option<usize>,
    pub execution_provider: Option<String>,
    pub embedding_cache_dir: Option<PathBuf>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticEmbedderServiceRequest {
    #[serde(default)]
    pub scope: Option<ScopeKey>,
    #[serde(default)]
    pub lane_mode: SemanticEmbedderLaneMode,
    #[serde(default)]
    pub model: SemanticEmbedderModelRequest,
    #[serde(default)]
    pub edge_preview_limit: Option<usize>,
    #[serde(default)]
    pub index_node_vectors: Option<bool>,
}

impl Default for SemanticEmbedderServiceRequest {
    fn default() -> Self {
        Self {
            scope: None,
            lane_mode: SemanticEmbedderLaneMode::TruthReview,
            model: SemanticEmbedderModelRequest::default(),
            edge_preview_limit: Some(16),
            index_node_vectors: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticEmbedderServiceResponse {
    pub contract_version: u32,
    pub candidate_only: bool,
    pub lane_mode: SemanticEmbedderLaneMode,
    pub model_id: String,
    pub embedding_profile: String,
    pub dimension: usize,
    pub execution_provider: String,
    pub cache: SemanticEmbedderCacheStats,
    pub timings: SemanticEmbedderServiceTimings,
    pub output: SemanticEmbedderCandidateOutput,
    pub sidecar: SemanticGraphScopeSidecar,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticEmbedderCacheStats {
    pub hits: usize,
    pub misses: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticEmbedderServiceTimings {
    pub derive_ms: u128,
    pub total_ms: u128,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticEmbedderCandidateOutput {
    pub scope_key: String,
    pub summary: SemanticGraphCompilerSummary,
    pub candidate_node_count: usize,
    pub candidate_edge_count: usize,
    pub candidate_graph_vertex_count: usize,
    pub candidate_graph_edge_count: usize,
    pub candidate_graph_scope: String,
    pub committed_topology_writes: usize,
    pub preview: Vec<SemanticEmbedderCandidatePreview>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticEmbedderCandidatePreview {
    pub edge_id: String,
    pub family: String,
    pub status: String,
    pub score_millis: u32,
    pub source_node_id: String,
    pub target_node_id: String,
    pub nli_support_millis: Option<u32>,
    pub nli_contradiction_millis: Option<u32>,
}

pub fn run_semantic_embedder_service_from_store<S>(
    store: &S,
    request: &SemanticEmbedderServiceRequest,
    created_at: i64,
) -> Result<Option<SemanticEmbedderServiceResponse>, SemanticGraphError>
where
    S: PhoenixArchiveStoreV2
        + PhoenixGraphPatchStore
        + PhoenixMemoryPatchStore
        + PhoenixEventIdentityPatchStore
        + PhoenixSemanticIndexStore,
{
    let total_started = Instant::now();
    let scope = match request.scope.clone() {
        Some(scope) => scope,
        None => discover_scope(store)?,
    };
    let graph = service_graph_config(request)?;
    let derive_started = Instant::now();
    let Some(batch) =
        derive_semantic_graph_review_batch_from_store(store, &scope, &graph, created_at)?
    else {
        return Ok(None);
    };
    let derive_ms = derive_started.elapsed().as_millis();
    Ok(Some(response_from_batch(
        request.lane_mode,
        request.edge_preview_limit.unwrap_or(16),
        batch,
        &graph,
        derive_ms,
        total_started.elapsed().as_millis(),
    )))
}

pub fn service_graph_config(
    request: &SemanticEmbedderServiceRequest,
) -> Result<SemanticGraphConfig, SemanticGraphError> {
    let mut config = SemanticGraphConfig::default();
    if let Some(model_id) = request.model.model_id.as_ref() {
        config.embed.model_id = model_id.clone();
    }
    if let Some(model_root) = request.model.model_root.as_ref() {
        config.embed.model_root = model_root.clone();
    }
    if let Some(cache_dir) = request.model.embedding_cache_dir.as_ref() {
        config.embed.embedding_cache_dir = Some(cache_dir.clone());
    }
    if let Some(batch_size) = request.model.batch_size {
        config.embed.batch_size = batch_size.max(1);
    }
    if let Some(max_length) = request.model.max_length {
        config.embed.max_length = max_length.max(1);
    }
    if let Some(profile) = request.model.embedding_profile.as_deref() {
        config.embed.profile = TextEmbeddingProfile::parse(profile).ok_or_else(|| {
            SemanticGraphError::Store(StoreError::Query(format!(
                "unknown semantic embedding profile: {profile}"
            )))
        })?;
    }
    if let Some(provider) = request.model.execution_provider.as_deref() {
        config.embed.execution_provider = OrtExecutionProviderPreference::parse(provider)
            .ok_or_else(|| {
                SemanticGraphError::Store(StoreError::Query(format!(
                    "unknown semantic execution provider: {provider}"
                )))
            })?;
    }
    apply_lane_mode(&mut config, request.lane_mode, request.index_node_vectors);
    Ok(config)
}

fn apply_lane_mode(
    config: &mut SemanticGraphConfig,
    lane_mode: SemanticEmbedderLaneMode,
    index_node_vectors: Option<bool>,
) {
    config.index_node_vectors = index_node_vectors.unwrap_or(false);
    match lane_mode {
        SemanticEmbedderLaneMode::TruthReview => {
            config.include_chunk_nodes = false;
            config.include_event_nodes = false;
            config.index_node_vectors = false;
        }
        SemanticEmbedderLaneMode::Events => {
            config.include_chunk_nodes = false;
            config.include_event_nodes = true;
        }
        SemanticEmbedderLaneMode::Chunks => {
            config.include_chunk_nodes = true;
            config.include_event_nodes = false;
        }
        SemanticEmbedderLaneMode::Full => {
            config.include_chunk_nodes = true;
            config.include_event_nodes = true;
        }
    }
}

fn response_from_batch(
    lane_mode: SemanticEmbedderLaneMode,
    edge_preview_limit: usize,
    batch: SemanticGraphReviewBatch,
    config: &SemanticGraphConfig,
    derive_ms: u128,
    total_ms: u128,
) -> SemanticEmbedderServiceResponse {
    let candidate_graph_scope = candidate_graph_scope_label(&batch.sidecar);
    let output = SemanticEmbedderCandidateOutput {
        scope_key: batch.scope_key.clone(),
        summary: batch.sidecar.summary.clone(),
        candidate_node_count: batch.sidecar.candidate_nodes.len(),
        candidate_edge_count: batch.sidecar.candidate_edges.len(),
        candidate_graph_vertex_count: batch.sidecar.candidate_graph_batch.vertices.len(),
        candidate_graph_edge_count: batch.sidecar.candidate_graph_batch.edges.len(),
        candidate_graph_scope,
        committed_topology_writes: 0,
        preview: batch
            .sidecar
            .candidate_edges
            .iter()
            .take(edge_preview_limit)
            .map(|edge| SemanticEmbedderCandidatePreview {
                edge_id: edge.edge_id.clone(),
                family: format!("{:?}", edge.family),
                status: format!("{:?}", edge.candidate_status),
                score_millis: edge.score_millis,
                source_node_id: edge.source_node_id.clone(),
                target_node_id: edge.target_node_id.clone(),
                nli_support_millis: edge.nli_support_millis,
                nli_contradiction_millis: edge.nli_contradiction_millis,
            })
            .collect(),
    };
    SemanticEmbedderServiceResponse {
        contract_version: SERVICE_CONTRACT_VERSION,
        candidate_only: true,
        lane_mode,
        model_id: batch.sidecar.model_id.clone(),
        embedding_profile: batch.sidecar.embedding_profile.clone(),
        dimension: batch.sidecar.embedding_dim,
        execution_provider: config.embed.execution_provider.label().to_owned(),
        cache: SemanticEmbedderCacheStats {
            hits: batch.embedding_cache_hits,
            misses: batch.embedding_cache_misses,
        },
        timings: SemanticEmbedderServiceTimings {
            derive_ms,
            total_ms,
        },
        output,
        sidecar: batch.sidecar,
    }
}

fn candidate_graph_scope_label(sidecar: &SemanticGraphScopeSidecar) -> String {
    match &sidecar.candidate_graph_batch.scope {
        KernelMutationScope::Candidate { scope_key } => format!("candidate:{scope_key}"),
        KernelMutationScope::Projection { scope_key } => format!("projection:{scope_key}"),
        KernelMutationScope::Document { document_id } => format!("document:{document_id}"),
        KernelMutationScope::Session { session_id } => format!("session:{session_id}"),
        KernelMutationScope::Full => "full".to_owned(),
    }
}

fn discover_scope<S>(store: &S) -> Result<ScopeKey, SemanticGraphError>
where
    S: PhoenixArchiveStoreV2,
{
    let archives = store.load_latest_document_archives(None)?;
    archives
        .first()
        .map(|archive| archive.manifest.scope.clone())
        .ok_or_else(|| {
            SemanticGraphError::Store(StoreError::Query(
                "semantic embedder service could not discover a scope".to_owned(),
            ))
        })
}

#[cfg(test)]
mod tests {
    use phoenix_graph_kernel::{
        KernelGraphLayer, KernelMutationBatch, KernelMutationScope, KernelVertexId,
    };
    use phoenix_semantic_v2::{
        SemanticCandidateStatus, SemanticEdgeFamily, SemanticGraphEdgeCandidate,
        SemanticGraphNodeKind,
    };

    use super::*;

    #[test]
    fn truth_review_lane_disables_heavy_nodes_and_vector_index() {
        let request = SemanticEmbedderServiceRequest {
            lane_mode: SemanticEmbedderLaneMode::TruthReview,
            index_node_vectors: Some(true),
            ..Default::default()
        };

        let config = service_graph_config(&request).expect("config");

        assert!(!config.index_node_vectors);
        assert!(!config.include_chunk_nodes);
        assert!(!config.include_event_nodes);
    }

    #[test]
    fn lane_modes_select_staged_node_sets() {
        let events = service_graph_config(&SemanticEmbedderServiceRequest {
            lane_mode: SemanticEmbedderLaneMode::Events,
            ..Default::default()
        })
        .expect("events");
        let chunks = service_graph_config(&SemanticEmbedderServiceRequest {
            lane_mode: SemanticEmbedderLaneMode::Chunks,
            ..Default::default()
        })
        .expect("chunks");
        let full = service_graph_config(&SemanticEmbedderServiceRequest {
            lane_mode: SemanticEmbedderLaneMode::Full,
            index_node_vectors: Some(true),
            ..Default::default()
        })
        .expect("full");

        assert!(events.include_event_nodes);
        assert!(!events.include_chunk_nodes);
        assert!(chunks.include_chunk_nodes);
        assert!(!chunks.include_event_nodes);
        assert!(full.include_chunk_nodes);
        assert!(full.include_event_nodes);
        assert!(full.index_node_vectors);
    }

    #[test]
    fn response_exposes_runtime_and_candidate_only_contract() {
        let config = SemanticGraphConfig::default();
        let batch = SemanticGraphReviewBatch {
            scope_key: "scope-key".to_owned(),
            embedding_cache_hits: 3,
            embedding_cache_misses: 1,
            sidecar: SemanticGraphScopeSidecar {
                scope_key: "scope-key".to_owned(),
                model_id: "model-x".to_owned(),
                embedding_profile: "768".to_owned(),
                embedding_dim: 768,
                candidate_edges: vec![SemanticGraphEdgeCandidate {
                    edge_id: "edge-1".to_owned(),
                    family: SemanticEdgeFamily::StateSupport,
                    source_node_id: "state-a".to_owned(),
                    source_kind: SemanticGraphNodeKind::State,
                    target_node_id: "state-b".to_owned(),
                    target_kind: SemanticGraphNodeKind::State,
                    score_millis: 800,
                    distance_millis: 200,
                    candidate_status: SemanticCandidateStatus::Generated,
                    evidence_refs: Vec::new(),
                    model_evidence: Vec::new(),
                    nli_support_millis: None,
                    nli_contradiction_millis: None,
                }],
                candidate_graph_batch: KernelMutationBatch {
                    layer: KernelGraphLayer::Candidate,
                    scope: KernelMutationScope::Candidate {
                        scope_key: "scope-key".to_owned(),
                    },
                    recorded_at: Some(42),
                    vertices: Vec::new(),
                    edges: Vec::new(),
                },
                ..Default::default()
            },
            ..Default::default()
        };

        let response = response_from_batch(
            SemanticEmbedderLaneMode::TruthReview,
            8,
            batch,
            &config,
            11,
            12,
        );

        assert_eq!(response.model_id, "model-x");
        assert_eq!(response.dimension, 768);
        assert_eq!(response.execution_provider, "cpu");
        assert_eq!(response.cache.hits, 3);
        assert_eq!(response.cache.misses, 1);
        assert!(response.candidate_only);
        assert_eq!(response.output.committed_topology_writes, 0);
        assert_eq!(response.output.candidate_graph_scope, "candidate:scope-key");
        assert_eq!(response.output.preview.len(), 1);
    }

    #[test]
    fn invalid_profile_and_execution_provider_fail_closed() {
        let bad_profile = service_graph_config(&SemanticEmbedderServiceRequest {
            model: SemanticEmbedderModelRequest {
                embedding_profile: Some("surprise-dim".to_owned()),
                ..Default::default()
            },
            ..Default::default()
        });
        let bad_provider = service_graph_config(&SemanticEmbedderServiceRequest {
            model: SemanticEmbedderModelRequest {
                execution_provider: Some("magic".to_owned()),
                ..Default::default()
            },
            ..Default::default()
        });

        assert!(bad_profile.is_err());
        assert!(bad_provider.is_err());
    }

    #[test]
    fn preview_limit_is_honored() {
        let config = SemanticGraphConfig::default();
        let mut sidecar = SemanticGraphScopeSidecar {
            model_id: "model-x".to_owned(),
            embedding_profile: "384".to_owned(),
            embedding_dim: 384,
            candidate_graph_batch: KernelMutationBatch {
                layer: KernelGraphLayer::Candidate,
                scope: KernelMutationScope::Candidate {
                    scope_key: "scope-key".to_owned(),
                },
                recorded_at: Some(42),
                vertices: Vec::new(),
                edges: Vec::new(),
            },
            ..Default::default()
        };
        sidecar.candidate_edges = (0..3)
            .map(|index| SemanticGraphEdgeCandidate {
                edge_id: format!("edge-{index}"),
                source_node_id: KernelVertexId(format!("a-{index}")).0,
                target_node_id: KernelVertexId(format!("b-{index}")).0,
                family: SemanticEdgeFamily::StateSupport,
                source_kind: SemanticGraphNodeKind::State,
                target_kind: SemanticGraphNodeKind::State,
                score_millis: 700,
                distance_millis: 300,
                candidate_status: SemanticCandidateStatus::Generated,
                evidence_refs: Vec::new(),
                model_evidence: Vec::new(),
                nli_support_millis: None,
                nli_contradiction_millis: None,
            })
            .collect();
        let batch = SemanticGraphReviewBatch {
            scope_key: "scope-key".to_owned(),
            sidecar,
            ..Default::default()
        };

        let response = response_from_batch(SemanticEmbedderLaneMode::Full, 2, batch, &config, 1, 1);

        assert_eq!(response.output.preview.len(), 2);
    }
}

use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs;
#[cfg(feature = "legacy-cozo-graph")]
use std::ops::Deref;
use std::path::{Path, PathBuf};
#[cfg(not(target_arch = "wasm32"))]
use std::sync::OnceLock;
use std::time::Instant;

mod binary;
#[cfg(not(target_arch = "wasm32"))]
mod dynamic_gliclass;
#[cfg(not(target_arch = "wasm32"))]
mod dynamic_gliner;
mod document_graph_commit;
mod evidence_ledger;
mod frame_extraction;
#[cfg(not(target_arch = "wasm32"))]
mod overgraph_lane;
mod planner;
mod view;

#[cfg(not(target_arch = "wasm32"))]
#[cfg(feature = "legacy-cozo-graph")]
use overgraph_lane::OvergraphLaneSyncReport;
use overgraph_lane::PhoenixOvergraphLane;
use phoenix_alex::{normalized_has_meaningful_token, Lexicon as DynamicLexicon};
use phoenix_analytics::TextAnalytics;
use phoenix_chat::PhoenixChat;
use phoenix_dynamic_ner::{
    MentionKind as DynamicMentionKind, MentionStatus as DynamicMentionStatus,
    PhoenixNerEngineBuilder, SurfaceNerInput,
};
#[cfg(feature = "legacy-cozo-graph")]
use phoenix_gldr::PhoenixGldr;
use phoenix_graph::{
    GraphBackendError, GraphEdgeRecord, GraphLayer, GraphMutationBatch, GraphMutationScope,
    GraphVertexRecord,
};
#[cfg(feature = "legacy-cozo-graph")]
use phoenix_graptor::{
    load_graph_snapshot_with_candidate_graph, load_session_state, BorrowedIngestDocument,
    BorrowedIngestRequest, GraptorGraph, PhoenixGraptor,
};
use phoenix_invarant_v2::PhoenixInvarantV2;
#[cfg(all(test, feature = "legacy-cozo-graph"))]
use phoenix_kernel::{KernelBiTemporal, KernelEntityFacet, KernelVertexClass, KernelViewRequest};
use phoenix_kernel::{
    KernelEdge, KernelGraphLayer, KernelGraphSnapshot,
    KernelMutationBatch as KernelGraphMutationBatch, KernelVertex,
};
#[cfg(test)]
use phoenix_kernel::{KernelEdgeType, KernelMutationScope, KernelVertexId};
#[cfg(feature = "legacy-cozo-graph")]
use phoenix_lex::indexed_spans_from_store;
use phoenix_lex::{LexConfig, LexIndex};
use phoenix_om::OmEngine;
#[cfg(feature = "legacy-cozo-graph")]
use phoenix_om_graptor::OmGraptorBridge;
use phoenix_runtime_native::PhoenixRuntimeNative;
use phoenix_scanner::PhoenixScanner;
use phoenix_semantic_v2::scope_storage_key;
#[cfg(feature = "legacy-cozo-graph")]
use phoenix_store_cozo::{CompactRow, CompactRowView, PhoenixCozoStore, StoreConfig};
use phoenix_store_native::{GraphCheckpointData, PhoenixNativeRowStore};
pub use phoenix_store_native_core::SnapshotPartition;
use phoenix_store_native_core::{
    schema::{CONTENT_SNAPSHOT_RELATIONS, DERIVED_SNAPSHOT_RELATIONS},
    SemanticDocumentNeighbor, SemanticNodeNeighbor, SnapshotEnvelope, StoreError,
    SEMANTIC_MODEL_ID, SEMANTIC_VECTOR_DIM,
};
#[cfg(not(target_arch = "wasm32"))]
use phoenix_store_overgraph::{OvergraphFlushReport, PhoenixOvergraphStore};
use phoenix_structure::PhoenixStructure;
use phoenix_triverse_v2::PhoenixTriverseV2;
use phoenix_types as dynamic_types;
use phoenix_types::{
    AtlasAliasProposalSummary, AtlasDatasetFactorySummary, AtlasEvidenceLedgerSummary,
    AtlasIdentityResolutionSummary, AtlasRichScanCandidateSummary, AtlasRichScanDocument,
    AtlasRichScanEmbeddingCounts, AtlasRichScanKindVoteSummary, AtlasRichScanManifestSummary,
    AtlasRichScanPolicy, AtlasRichScanRequest, AtlasRichScanResult, AtlasRichScanScope,
    AtlasRichScanStageSummary, ChatPlannerModelResponse, ChatRunEvent, ChatRuntimeConfig, CommitId,
    CommitRequest, CommitResult, CreateSessionRequest, Diagnostic, DocumentId, EntityCard,
    EntityId, EntityKind, FolderSchema, GraphDeltaChunk, GraphDeltaEdge, GraphDeltaNode,
    GraphDeltaRequest, GraphDeltaResult, IndexedSpan, IndexedTextField, IngestRequest,
    IngestResult, LexicalField, LexicalSearchResult, MentionEntityRef, NetworkInstance, NodeHit,
    NoteId, OmPendingAction, OmRecord, OmReflectorModelResponse, OmReflectorToolResult,
    PhoenixBootSnapshotRows, QueryRequest, QueryResult, RebuildRequest, RebuildResult,
    RelationCount, ResolverEntitySeed, RunOptions, RuntimeConfig, RuntimeInitResult, RuntimeTarget,
    SavedNetworkView, ScanArtifact, ScanRequest, ScopeKey, SessionDocumentState, SessionId,
    SessionRecord, SessionState, SessionStats, SnapshotDto, SpanHit, StorageMode,
    StoreCommandRequest, StoreCommandResult, StructureArtifact, StructureRequest, TextRange,
    Thread, ThreadMessage, ToolResultSubmission, UmrLiteArgument, UmrLiteRole,
};
use planner::{list_run_artifacts, set_artifact_pinned, ChatPlannerRunner};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
pub use view::{
    AnalyzeTextRequestView, IngestDocumentView, IngestRequestView, QueryRequestView,
    ScanRequestView, ScopeKeyView, StructureRequestView,
};

pub struct PhoenixRuntime {
    pub config: RuntimeConfig,
    pub store: MaybeCozoStore,
    #[cfg(not(target_arch = "wasm32"))]
    overgraph_store: Option<PhoenixOvergraphStore>,
    pub scanner: PhoenixScanner,
    pub structure: PhoenixStructure,
    #[cfg(feature = "legacy-cozo-graph")]
    pub graptor: PhoenixGraptor,
    pub invarant_v2: PhoenixInvarantV2,
    pub native_runtime: PhoenixRuntimeNative,
    pub om_engine: OmEngine,
    #[cfg(feature = "legacy-cozo-graph")]
    pub om_bridge: OmGraptorBridge,
    pub chat: PhoenixChat,
    pub planner: ChatPlannerRunner,
    pub lex: RefCell<Option<LexIndex>>,
    native_scope_lex: RefCell<HashMap<String, NativeScopeLexCacheEntry>>,
    #[cfg(feature = "legacy-cozo-graph")]
    pub gldr: PhoenixGldr,
    pub triverse_v2: PhoenixTriverseV2,
    #[cfg(not(target_arch = "wasm32"))]
    overgraph_lane: Option<PhoenixOvergraphLane>,
}

const NATIVE_RUNTIME_SCHEMA_VERSION: &str = "phoenix.native.v2";
const NATIVE_SCOPE_LEX_CACHE_LIMIT: usize = 16;
const NATIVE_SCOPE_QGRAM_MIN_SPANS: usize = 32;

const STORE_API_VERSION: u32 = 1;

#[derive(Default)]
struct DynamicAtlasPipelineResult {
    mention_count: usize,
    token_count: usize,
    sentence_count: usize,
    surface_chunk_count: usize,
    resolver_link_count: usize,
    narrative_hit_count: usize,
    frame_count: usize,
    frame_argument_count: usize,
    frame_fact_count: usize,
    graph_nodes: usize,
    graph_edges: usize,
    document_leaf_counts: BTreeMap<String, usize>,
    lens_chunk_counts: BTreeMap<String, usize>,
    candidate_suggestions: Vec<AtlasRichScanCandidateSummary>,
    alias_proposals: Vec<AtlasAliasProposalSummary>,
    identity_resolution: AtlasIdentityResolutionSummary,
    evidence_ledger: AtlasEvidenceLedgerSummary,
    dataset_factory: AtlasDatasetFactorySummary,
    diagnostics: Vec<Diagnostic>,
}

const RUNTIME_CAPABILITIES: &[&str] = &[
    "runtime:capabilities",
    "relation:list",
    "relation:getFirst",
    "relation:upsert",
    "relation:delete",
    "graph:overgraphStatus",
    "graph:repairLiveTopology",
    "graph:upsertNode",
    "graph:upsertEdge",
    "documentGraph:commit",
    "documentGraph:undo",
    "note:list",
    "note:get",
    "note:listByIds",
    "note:upsert",
    "note:delete",
    "persistence:applyWalBatch",
    "persistence:flushNativeStore",
    "persistence:clearDerived",
    "persistence:clearDerivedEphemera",
    "semantic:runEmbedderTruthReview",
    "semantic:listNliJudgmentInputs",
    "semantic:applyNliJudgments",
    "session:close",
];
const DERIVED_EPHEMERA_RELATIONS: &[&str] = &[
    "phoenix_sessions",
    "phoenix_commits",
    "phoenix_ingest_log",
    "phoenix_query_log",
];
const NATIVE_CANDIDATE_GRAPH_NAMESPACE: &str = "phoenix.graph.candidate";
#[derive(Debug, Deserialize)]
struct PersistenceWalBatchRequest {
    records: Vec<PersistenceWalRecord>,
}

#[derive(Debug, Deserialize)]
struct PersistenceWalRecord {
    seq: u64,
    command: String,
    payload: Value,
    partition: String,
    #[serde(rename = "writtenAt")]
    written_at: Option<u64>,
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct PersistenceWalApplyReport {
    records: usize,
    note_upserts: usize,
    note_deletes: usize,
    relation_upserts: usize,
    relation_deletes: usize,
    scoped_document_upserts: usize,
    lex_rebuilt: bool,
    parse_ms: u64,
    note_ms: u64,
    relation_ms: u64,
    lex_ms: u64,
    total_ms: u64,
}

#[derive(Clone, Debug)]
struct NativeScopeLexCacheEntry {
    generation: u64,
    lex: LexIndex,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticDocumentVectorUpsertRow {
    document_id: String,
    values: Vec<f32>,
    leaf_count: usize,
    #[serde(default)]
    evidence_refs: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticNodeVectorUpsertRow {
    node_id: String,
    node_kind: String,
    document_id: Option<String>,
    narrative_id: Option<String>,
    folder_id: Option<String>,
    values: Vec<f32>,
    #[serde(default)]
    evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticCandidatePrototypeInput {
    node_id: String,
    node_kind: String,
    document_id: Option<String>,
    narrative_id: Option<String>,
    folder_id: Option<String>,
    text: String,
    evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticNliJudgmentInput {
    judgment_id: String,
    group_id: String,
    source_id: String,
    target_id: String,
    edge_type: String,
    direction: String,
    premise: String,
    hypothesis: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticNliJudgmentResultRow {
    judgment_id: String,
    group_id: String,
    source_id: String,
    target_id: String,
    edge_type: String,
    direction: String,
    premise: String,
    hypothesis: String,
    entailment: f64,
    neutral: f64,
    contradiction: f64,
    predicted_label: String,
    confidence: f64,
}

#[derive(Clone, Debug, Default)]
struct Phase2NliJudgmentAggregate {
    group_id: String,
    judgments: Vec<SemanticNliJudgmentResultRow>,
}

#[derive(Clone, Debug, Default)]
struct Phase2CandidateEdgeRecord {
    source_id: String,
    target_id: String,
    edge_type: String,
    document_id: Option<String>,
    base_score: f64,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewScopeHint {
    scope_id: Option<String>,
    label: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewModelRequest {
    ui_model_id: Option<String>,
    model_id: Option<String>,
    model_label: Option<String>,
    embedding_profile: Option<String>,
    execution_provider: Option<String>,
    dimension: Option<usize>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewRequest {
    lane_mode: Option<String>,
    cache_policy: Option<String>,
    edge_preview_limit: Option<usize>,
    #[serde(default)]
    document_ids: Vec<String>,
    #[serde(default)]
    node_ids: Vec<String>,
    scope_hint: Option<SemanticTruthReviewScopeHint>,
    #[serde(default)]
    model: SemanticTruthReviewModelRequest,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewResponse {
    contract_version: u32,
    candidate_only: bool,
    lane_mode: String,
    model_id: String,
    model_label: String,
    embedding_profile: String,
    dimension: usize,
    execution_provider: String,
    cache: SemanticTruthReviewCacheStats,
    timings: SemanticTruthReviewTimings,
    output: SemanticTruthReviewOutput,
    sidecar: Value,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewCacheStats {
    hits: usize,
    misses: usize,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewTimings {
    derive_ms: u128,
    total_ms: u128,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewOutput {
    scope_key: String,
    summary: SemanticTruthReviewSummary,
    candidate_node_count: usize,
    candidate_edge_count: usize,
    candidate_graph_vertex_count: usize,
    candidate_graph_edge_count: usize,
    candidate_graph_scope: String,
    committed_topology_writes: usize,
    preview: Vec<SemanticTruthReviewPreview>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewSummary {
    node_count: usize,
    edge_count: usize,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SemanticTruthReviewPreview {
    edge_id: String,
    family: String,
    status: String,
    score_millis: u32,
    source_node_id: String,
    target_node_id: String,
    nli_support_millis: u32,
    nli_contradiction_millis: u32,
}

#[derive(Clone, Debug)]
struct SemanticTruthReviewCandidateRow {
    edge_id: String,
    source_node_id: String,
    target_node_id: String,
    family: String,
    status: String,
    score: f64,
    nli_support_millis: u32,
    nli_contradiction_millis: u32,
}

#[derive(Clone, Debug, Default)]
struct Phase2NliDecision {
    accepted: bool,
    threshold: f64,
    entailment: f64,
    neutral: f64,
    contradiction: f64,
    nli_score: f64,
    final_score: f64,
}

#[derive(Clone, Debug, Default)]
struct StoredSemanticNodeVector {
    node_id: String,
    node_kind: String,
    document_id: Option<String>,
    narrative_id: Option<String>,
    folder_id: Option<String>,
    values: Vec<f32>,
    evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default)]
struct StoredSemanticDocumentVector {
    values: Vec<f32>,
    evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SemanticLeafChunk {
    span_id: String,
    document_id: String,
    text: String,
    narrative_id: Option<String>,
    folder_id: Option<String>,
}

#[derive(Default)]
#[allow(dead_code)]
#[cfg(feature = "legacy-cozo-graph")]
struct NativeGraphEnrichmentStats {
    thread_count: usize,
    vertex_count: usize,
    edge_count: usize,
    removed_vertex_count: usize,
    removed_edge_count: usize,
}

#[derive(Clone, Debug, Default)]
struct Phase2LeafContext {
    document_id: String,
    narrative_id: Option<String>,
    folder_id: Option<String>,
    text: String,
}

#[derive(Clone, Debug, Default)]
struct Phase2GraphView {
    vertices: HashMap<String, GraphVertexRecord>,
    edges: Vec<GraphEdgeRecord>,
}

impl Phase2GraphView {
    fn from_kernel(snapshot: KernelGraphSnapshot, include_candidate_graph: bool) -> Self {
        let mut edges = snapshot
            .asserted_edges
            .into_iter()
            .map(GraphEdgeRecord::from)
            .collect::<Vec<_>>();
        if include_candidate_graph {
            edges.extend(
                snapshot
                    .candidate_edges
                    .into_iter()
                    .map(GraphEdgeRecord::from),
            );
        }
        Self {
            vertices: snapshot
                .vertices
                .into_iter()
                .map(|vertex| {
                    let record = GraphVertexRecord::from(vertex);
                    (record.id.clone(), record)
                })
                .collect(),
            edges,
        }
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn from_legacy(graph: GraptorGraph) -> Self {
        let edges = graph
            .outgoing
            .into_values()
            .flat_map(|edges| edges.into_iter().map(|edge| GraphEdgeRecord::from(&edge)))
            .collect::<Vec<_>>();
        Self {
            vertices: graph
                .vertices
                .into_values()
                .map(|vertex| {
                    let record = GraphVertexRecord::from(&vertex);
                    (record.id.clone(), record)
                })
                .collect(),
            edges,
        }
    }

    fn outgoing_any<'a>(&'a self, source_id: &'a str) -> impl Iterator<Item = &'a GraphEdgeRecord> {
        self.edges
            .iter()
            .filter(move |edge| edge.source_id == source_id)
    }

    fn incoming_any<'a>(&'a self, target_id: &'a str) -> impl Iterator<Item = &'a GraphEdgeRecord> {
        self.edges
            .iter()
            .filter(move |edge| edge.target_id == target_id)
    }

    fn outgoing_matching<'a>(
        &'a self,
        source_id: &'a str,
        edge_type: &'a str,
    ) -> impl Iterator<Item = &'a GraphEdgeRecord> {
        self.edges
            .iter()
            .filter(move |edge| edge.source_id == source_id && edge.edge_type == edge_type)
    }
}

pub struct MaybeCozoStore {
    #[cfg(feature = "legacy-cozo-graph")]
    inner: Option<PhoenixCozoStore>,
}

impl MaybeCozoStore {
    fn open(
        enabled: bool,
        config: &RuntimeConfig,
        storage_path: Option<PathBuf>,
    ) -> Result<Self, StoreError> {
        #[cfg(feature = "legacy-cozo-graph")]
        {
            let inner = if enabled {
                Some(PhoenixCozoStore::open(StoreConfig {
                    mode: config.storage.clone(),
                    path: storage_path,
                })?)
            } else {
                None
            };
            Ok(Self { inner })
        }
        #[cfg(not(feature = "legacy-cozo-graph"))]
        {
            let _ = (config, storage_path);
            if enabled {
                return Err(StoreError::Query(
                    "legacy Cozo store requires the legacy graph runtime feature".to_owned(),
                ));
            }
            Ok(Self {})
        }
    }
}

#[cfg(feature = "legacy-cozo-graph")]
impl Deref for MaybeCozoStore {
    type Target = PhoenixCozoStore;

    fn deref(&self) -> &Self::Target {
        self.inner
            .as_ref()
            .expect("PhoenixCozoStore is unavailable on the native runtime path")
    }
}

impl PhoenixRuntime {
    pub fn new(config: RuntimeConfig) -> Result<Self, StoreError> {
        Self::open(config, None)
    }

    pub fn open(config: RuntimeConfig, storage_path: Option<PathBuf>) -> Result<Self, StoreError> {
        let use_native_graph = config.target == RuntimeTarget::Native;
        #[cfg(not(target_arch = "wasm32"))]
        let overgraph_path = overgraph_store_path(&config, storage_path.as_deref());
        let store = MaybeCozoStore::open(!use_native_graph, &config, storage_path)?;
        #[cfg(not(target_arch = "wasm32"))]
        let overgraph_store = if use_native_graph {
            let store = PhoenixOvergraphStore::open(&overgraph_path)?;
            store.init_schema()?;
            Some(store)
        } else {
            None
        };
        #[cfg(not(target_arch = "wasm32"))]
        let overgraph_lane = Some(PhoenixOvergraphLane::open(overgraph_path)?);
        Ok(Self {
            config,
            store,
            #[cfg(not(target_arch = "wasm32"))]
            overgraph_store,
            scanner: PhoenixScanner::default(),
            structure: PhoenixStructure::default(),
            #[cfg(feature = "legacy-cozo-graph")]
            graptor: PhoenixGraptor::default(),
            invarant_v2: PhoenixInvarantV2::default(),
            native_runtime: PhoenixRuntimeNative::default(),
            om_engine: OmEngine::default(),
            #[cfg(feature = "legacy-cozo-graph")]
            om_bridge: OmGraptorBridge::default(),
            chat: PhoenixChat::default(),
            planner: ChatPlannerRunner::default(),
            lex: RefCell::new(None),
            native_scope_lex: RefCell::new(HashMap::new()),
            #[cfg(feature = "legacy-cozo-graph")]
            gldr: PhoenixGldr::default(),
            triverse_v2: PhoenixTriverseV2::default(),
            #[cfg(not(target_arch = "wasm32"))]
            overgraph_lane,
        })
    }

    pub fn init(&self) -> Result<RuntimeInitResult, StoreError> {
        if self.native_graph_enabled() {
            self.native_row_store()?.init_schema()?;
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.init_schema()?;
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("legacy store init"));
            }
        }
        if self.native_graph_enabled() {
            self.invalidate_lex_caches();
        } else {
            self.rebuild_lex_index()?;
        }
        self.ensure_native_graph_ready()?;
        let relation_counts = self.relation_counts()?;
        let mut diagnostics = Vec::new();
        #[cfg(not(target_arch = "wasm32"))]
        if let Some(lane) = self.overgraph_lane.as_ref() {
            diagnostics.push(Diagnostic {
                code: "PX_OVERGRAPH_BOUND".to_owned(),
                message: format!(
                    "Active runtime bound OverGraph lane at {}.",
                    lane.path().to_string_lossy()
                ),
            });
        }
        Ok(RuntimeInitResult {
            ready: true,
            schema_version: if self.native_graph_enabled() {
                NATIVE_RUNTIME_SCHEMA_VERSION.to_owned()
            } else {
                #[cfg(feature = "legacy-cozo-graph")]
                {
                    self.store.schema_version().to_owned()
                }
                #[cfg(not(feature = "legacy-cozo-graph"))]
                {
                    return Err(self.legacy_graph_disabled("legacy schema version"));
                }
            },
            relation_count: relation_counts.len(),
            relation_counts,
            diagnostics,
        })
    }

    #[cfg(all(not(target_arch = "wasm32"), feature = "legacy-cozo-graph"))]
    fn sync_overgraph_lane_from_graph_rows(
        &self,
    ) -> Result<Option<OvergraphLaneSyncReport>, StoreError> {
        if self.native_graph_enabled() {
            return Ok(None);
        }
        let Some(lane) = self.overgraph_lane.as_ref() else {
            return Ok(None);
        };
        Ok(Some(lane.sync_from_legacy_relation_rows(&self.store)?))
    }

    fn native_graph_enabled(&self) -> bool {
        self.config.target == RuntimeTarget::Native
    }

    fn native_row_store(&self) -> Result<&dyn PhoenixNativeRowStore, StoreError> {
        #[cfg(not(target_arch = "wasm32"))]
        if let Some(store) = self.overgraph_store.as_ref() {
            return Ok(store as &dyn PhoenixNativeRowStore);
        }
        Err(self.native_unsupported("native OverGraph row store"))
    }

    pub(crate) fn chat_store(&self) -> Result<&dyn phoenix_chat::ChatStore, StoreError> {
        if self.native_graph_enabled() {
            #[cfg(not(target_arch = "wasm32"))]
            if let Some(store) = self.overgraph_store.as_ref() {
                return Ok(store as &dyn phoenix_chat::ChatStore);
            }
            Err(self.native_unsupported("native OverGraph chat store"))
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                Ok(self.legacy_store("legacy chat store")? as &dyn phoenix_chat::ChatStore)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy chat store"))
            }
        }
    }

    fn om_store(&self) -> Result<&dyn phoenix_om::OmStore, StoreError> {
        if self.native_graph_enabled() {
            #[cfg(not(target_arch = "wasm32"))]
            if let Some(store) = self.overgraph_store.as_ref() {
                return Ok(store as &dyn phoenix_om::OmStore);
            }
            Err(self.native_unsupported("native OverGraph OM store"))
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                Ok(self.legacy_store("legacy OM store")? as &dyn phoenix_om::OmStore)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy OM store"))
            }
        }
    }

    fn native_unsupported(&self, feature: &str) -> StoreError {
        StoreError::Query(format!(
            "{feature} is unavailable on the native runtime path"
        ))
    }

    #[cfg(not(feature = "legacy-cozo-graph"))]
    fn legacy_graph_disabled(&self, feature: &str) -> StoreError {
        StoreError::Query(format!(
            "{feature} requires the legacy graph runtime feature"
        ))
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn legacy_store(&self, feature: &str) -> Result<&PhoenixCozoStore, StoreError> {
        if self.native_graph_enabled() {
            Err(self.native_unsupported(feature))
        } else {
            self.store
                .inner
                .as_ref()
                .ok_or_else(|| self.native_unsupported(feature))
        }
    }

    fn upsert_native_relation_rows(
        &self,
        relation: &str,
        rows: &[Value],
    ) -> Result<(), StoreError> {
        self.native_row_store()?.put_rows(relation, rows)
    }

    pub(crate) fn put_relation_row(&self, relation: &str, row: Value) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            self.native_row_store()?.put_row(relation, row)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.put_row(relation, row)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                let _ = (relation, row);
                Err(self.legacy_graph_disabled("legacy row write"))
            }
        }
    }

    pub(crate) fn fetch_relation_rows(&self, relation: &str) -> Result<Vec<Value>, StoreError> {
        if self.native_graph_enabled() {
            self.native_row_store()?.fetch_rows(relation)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.fetch_rows(relation)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                let _ = relation;
                Err(self.legacy_graph_disabled("legacy row fetch"))
            }
        }
    }

    fn delete_relation_rows(&self, relation: &str, rows: &[Value]) -> Result<usize, StoreError> {
        if self.native_graph_enabled() {
            self.native_row_store()?.delete_rows(relation, rows)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let existing_rows = self.store.fetch_rows(relation)?;
                let existing_compact = self.store.fetch_compact_rows(relation)?;
                let matched = existing_rows
                    .iter()
                    .zip(existing_compact.into_iter())
                    .filter_map(|(existing, compact)| {
                        rows.iter().any(|row| row == existing).then_some(compact)
                    })
                    .collect::<Vec<_>>();
                let deleted = matched.len();
                self.store.delete_key_rows(relation, &matched)?;
                Ok(deleted)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                let _ = (relation, rows);
                Err(self.legacy_graph_disabled("legacy row delete"))
            }
        }
    }

    fn sync_relation_to_native(&self, _relation: &str) -> Result<(), StoreError> {
        Ok(())
    }

    #[allow(dead_code)]
    fn bootstrap_or_hydrate_native_store(&self) -> Result<(), StoreError> {
        Ok(())
    }

    pub fn relation_counts(&self) -> Result<Vec<RelationCount>, StoreError> {
        if self.native_graph_enabled() {
            Ok(self
                .native_row_store()?
                .relation_counts()?
                .into_iter()
                .map(|(relation, rows)| RelationCount { relation, rows })
                .collect())
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.relation_counts()
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy relation counts"))
            }
        }
    }

    pub fn relation_name_count(&self) -> Result<usize, StoreError> {
        if self.native_graph_enabled() {
            Ok(self.native_row_store()?.relation_names().len())
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                Ok(self.store.relation_names().len())
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy relation names"))
            }
        }
    }

    #[cfg(not(target_arch = "wasm32"))]
    pub fn flush_native_store(&self) -> Result<OvergraphFlushReport, StoreError> {
        self.overgraph_store
            .as_ref()
            .ok_or_else(|| self.native_unsupported("native store flush"))?
            .flush()
    }

    fn fetch_store_command_relation_rows(&self, relation: &str) -> Result<Vec<Value>, StoreError> {
        if self.native_graph_enabled() && phoenix_store_native::is_graph_compat_relation(relation) {
            return self.project_native_graph_relation_rows(relation);
        }
        self.fetch_relation_rows(relation)
    }

    fn project_native_graph_relation_rows(&self, relation: &str) -> Result<Vec<Value>, StoreError> {
        let graph = self.native_kernel_snapshot(true)?;
        match relation {
            "graph_vertices" => Ok(project_kernel_graph_vertices(&graph)),
            "graph_vertex_labels" => Ok(project_kernel_graph_vertex_labels(&graph)),
            "graph_edges" => Ok(project_kernel_graph_edges(
                &graph,
                KernelGraphLayer::Asserted,
            )),
            "graph_candidate_edges" => Ok(project_kernel_graph_edges(
                &graph,
                KernelGraphLayer::Candidate,
            )),
            "graph_node_index" => Ok(project_kernel_graph_node_index(&graph)),
            "graph_properties" => Ok(project_kernel_graph_properties(&graph)),
            other => Err(StoreError::UnknownRelation(other.to_owned())),
        }
    }

    fn persist_native_graph_batch(
        &self,
        _batch: &KernelGraphMutationBatch,
        _source_revision: Option<String>,
    ) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            self.persist_current_kernel_snapshot_rows()?;
        }
        Ok(())
    }

    fn write_native_graph_checkpoint(
        &self,
        generation: Option<u64>,
        source_revision: Option<String>,
    ) -> Result<Option<GraphCheckpointData>, StoreError> {
        let _ = (generation, source_revision);
        if self.native_graph_enabled() {
            self.persist_current_kernel_snapshot_rows()?;
        }
        Ok(None)
    }

    fn augment_graph_delta_request_from_journal(
        &self,
        request: &mut GraphDeltaRequest,
    ) -> Result<(), StoreError> {
        let _ = request;
        Ok(())
    }

    fn graph_backend_error(error: GraphBackendError) -> StoreError {
        StoreError::Query(format!("native graph backend: {error}"))
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn graph_snapshot(&self, include_candidate_graph: bool) -> Result<GraptorGraph, StoreError> {
        load_graph_snapshot_with_candidate_graph(&self.store, include_candidate_graph)
    }

    fn native_kernel_snapshot(
        &self,
        include_candidate_graph: bool,
    ) -> Result<KernelGraphSnapshot, StoreError> {
        self.ensure_native_graph_ready()?;
        Ok(self
            .native_runtime
            .deterministic_kernel
            .snapshot_current_kernel(include_candidate_graph))
    }

    fn phase2_graph_view(
        &self,
        include_candidate_graph: bool,
    ) -> Result<Phase2GraphView, StoreError> {
        if self.native_graph_enabled() {
            return Ok(Phase2GraphView::from_kernel(
                self.native_kernel_snapshot(include_candidate_graph)?,
                include_candidate_graph,
            ));
        }
        #[cfg(feature = "legacy-cozo-graph")]
        {
            return Ok(Phase2GraphView::from_legacy(
                self.graph_snapshot(include_candidate_graph)?,
            ));
        }
        #[cfg(not(feature = "legacy-cozo-graph"))]
        {
            let _ = include_candidate_graph;
            Err(self.legacy_graph_disabled("legacy graph view"))
        }
    }

    fn live_note_document_ids(&self) -> Result<HashSet<String>, StoreError> {
        Ok(self
            .list_note_values(None, false)?
            .into_iter()
            .filter_map(|row| row.get("id").and_then(Value::as_str).map(str::to_owned))
            .collect())
    }

    fn native_graph_document_ids(&self) -> Result<BTreeSet<String>, StoreError> {
        let graph = self.native_kernel_snapshot(true)?;
        let mut document_ids = BTreeSet::new();
        for vertex in &graph.vertices {
            collect_kernel_vertex_document_refs(vertex, &mut document_ids);
        }
        for edge in graph
            .asserted_edges
            .iter()
            .chain(graph.candidate_edges.iter())
        {
            collect_kernel_edge_document_refs(edge, &mut document_ids);
        }
        Ok(document_ids)
    }

    fn prune_native_graph_to_live_notes(&self) -> Result<usize, StoreError> {
        if !self.native_graph_enabled() {
            return Ok(0);
        }
        let live_document_ids = self.live_note_document_ids()?;
        let stale_document_ids = self
            .native_graph_document_ids()?
            .into_iter()
            .filter(|document_id| !live_document_ids.contains(document_id))
            .collect::<Vec<_>>();
        if stale_document_ids.is_empty() {
            return Ok(0);
        }

        self.compact_native_graph_to_live_notes(&live_document_ids)?;
        Ok(stale_document_ids.len())
    }

    fn compact_native_graph_to_live_notes(
        &self,
        live_document_ids: &HashSet<String>,
    ) -> Result<(), StoreError> {
        let graph = self.native_kernel_snapshot(true)?;
        let mut kept_vertices = Vec::new();
        let mut kept_vertex_ids = BTreeSet::new();
        let mut candidate_edges = Vec::new();
        let mut asserted_edges = Vec::new();

        for vertex in graph.vertices {
            if kernel_graph_item_is_live_vertex(&vertex, live_document_ids) {
                kept_vertex_ids.insert(vertex.id.0.clone());
                kept_vertices.push(GraphVertexRecord::from(vertex));
            }
        }

        for edge in graph.asserted_edges {
            if !kernel_graph_item_is_live_edge(&edge, live_document_ids) {
                continue;
            }
            if kept_vertex_ids.contains(&edge.source_id.0)
                && kept_vertex_ids.contains(&edge.target_id.0)
            {
                asserted_edges.push(GraphEdgeRecord::from(edge));
            }
        }

        for edge in graph.candidate_edges {
            if !kernel_graph_item_is_live_edge(&edge, live_document_ids) {
                continue;
            }
            if kept_vertex_ids.contains(&edge.source_id.0)
                && kept_vertex_ids.contains(&edge.target_id.0)
            {
                candidate_edges.push(GraphEdgeRecord::from(edge));
            }
        }

        let source_revision = self.native_graph_rebuild_token()?;
        let asserted_batch = KernelGraphMutationBatch::from(GraphMutationBatch {
            layer: GraphLayer::Asserted,
            scope: GraphMutationScope::Full,
            vertices: kept_vertices.clone(),
            edges: asserted_edges,
        });
        self.native_runtime
            .deterministic_kernel
            .apply_batch(asserted_batch.clone())
            .map_err(Self::graph_backend_error)?;
        self.persist_native_graph_batch(&asserted_batch, Some(source_revision.clone()))?;

        let candidate_batch = KernelGraphMutationBatch::from(GraphMutationBatch {
            layer: GraphLayer::Candidate,
            scope: GraphMutationScope::Full,
            vertices: Vec::new(),
            edges: candidate_edges,
        });
        self.native_runtime
            .deterministic_kernel
            .apply_batch(candidate_batch.clone())
            .map_err(Self::graph_backend_error)?;
        self.persist_native_graph_batch(&candidate_batch, Some(source_revision))?;
        self.persist_current_kernel_snapshot_rows()?;
        let _ = self.write_native_graph_checkpoint(None, None)?;
        Ok(())
    }

    fn native_lexical_search(
        &self,
        query: &str,
        scope: &ScopeKey,
        limit: usize,
    ) -> Result<LexicalSearchResult, StoreError> {
        let scope_key = scope_storage_key(scope);
        if let Some(cached) = self.native_scope_lex.borrow().get(&scope_key) {
            let mut result = cached.lex.search(query, scope, limit);
            result.diagnostics.push(Diagnostic {
                code: "PX_QUERY_NATIVE_SCOPE_QGRAM_CACHE".to_owned(),
                message: format!(
                    "Native query used cached scope-local qgram search at lexical generation {}.",
                    cached.generation
                ),
            });
            return Ok(result);
        }

        let spans = self
            .native_note_rows_to_indexed_spans()?
            .into_iter()
            .filter(|span| span.scope == *scope)
            .collect::<Vec<_>>();
        if spans.len() < NATIVE_SCOPE_QGRAM_MIN_SPANS {
            return Ok(native_linear_lexical_search_result(
                &spans, query, scope, limit,
            ));
        }

        let lex = LexIndex::build(&spans, LexConfig::default());
        let generation = 0;
        let mut result = lex.search(query, scope, limit);
        result.diagnostics.push(Diagnostic {
            code: "PX_QUERY_NATIVE_SCOPE_QGRAM".to_owned(),
            message: format!(
                "Native query built a scope-local qgram index at lexical generation {} from OverGraph note rows.",
                generation
            ),
        });

        self.insert_native_scope_lex_cache(scope_key, generation, lex);
        Ok(result)
    }

    fn native_query_with_lexical(
        &self,
        lexical: LexicalSearchResult,
        request: &QueryRequest,
    ) -> Result<QueryResult, StoreError> {
        let chunk_hits = lexical
            .span_hits
            .iter()
            .map(|hit| phoenix_types::ChunkHit {
                chunk_id: hit.span_id.clone(),
                score: hit.score,
            })
            .collect::<Vec<_>>();

        let normalized_query = normalize_lexical_query(&request.query);
        let terms = normalized_query
            .split_whitespace()
            .filter(|term| !term.is_empty())
            .collect::<Vec<_>>();
        let mut entity_scores = BTreeMap::<String, f64>::new();
        if !terms.is_empty() {
            for row in self.fetch_relation_rows("entities")? {
                if !row_matches_scope(&row, &request.scope) {
                    continue;
                }
                let Some(entity_id) = row.get("id").and_then(Value::as_str) else {
                    continue;
                };
                let mut score = 0.0f64;
                if let Some(label) = row.get("label").and_then(Value::as_str) {
                    score += lexical_match_score(label, &normalized_query, &terms, 4.0);
                }
                for alias in row
                    .get("aliases")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter_map(Value::as_str)
                {
                    score += lexical_match_score(alias, &normalized_query, &terms, 2.0);
                }
                if score == 0.0 {
                    continue;
                }
                let mentions = row
                    .get("total_mentions")
                    .and_then(Value::as_i64)
                    .unwrap_or_default()
                    .max(0) as f64;
                entity_scores.insert(entity_id.to_owned(), score + mentions.ln_1p() * 0.05);
            }
        }

        if entity_scores.is_empty() {
            let hit_notes = lexical
                .span_hits
                .iter()
                .filter_map(|hit| hit.note_id.as_ref().map(|note_id| note_id.0.clone()))
                .collect::<BTreeSet<_>>();
            if !hit_notes.is_empty() {
                for row in self.fetch_relation_rows("entities")? {
                    let Some(entity_id) = row.get("id").and_then(Value::as_str) else {
                        continue;
                    };
                    let Some(first_note) = row.get("first_note").and_then(Value::as_str) else {
                        continue;
                    };
                    if hit_notes.contains(first_note) && row_matches_scope(&row, &request.scope) {
                        entity_scores.insert(entity_id.to_owned(), 0.25);
                    }
                }
            }
        }

        let mut node_hits = entity_scores
            .into_iter()
            .map(|(entity_id, score)| NodeHit {
                entity_id: Some(EntityId(entity_id)),
                score,
            })
            .collect::<Vec<_>>();
        if node_hits.is_empty() {
            node_hits.extend(
                chunk_hits
                    .iter()
                    .take(request.limit.unwrap_or(5))
                    .map(|hit| NodeHit {
                        entity_id: None,
                        score: hit.score * 0.25,
                    }),
            );
        }
        node_hits.sort_by(|left, right| {
            right
                .score
                .partial_cmp(&left.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.entity_id.cmp(&right.entity_id))
        });
        node_hits.truncate(request.limit.unwrap_or(5));

        let mut diagnostics = lexical.diagnostics;
        diagnostics.push(Diagnostic {
            code: "PX_NATIVE_OVERGRAPH_QUERY".to_owned(),
            message: "Native query used OverGraph rows for lexical recall and entity hits."
                .to_owned(),
        });

        Ok(QueryResult {
            session_id: request.session_id.clone(),
            chunk_hits,
            node_hits,
            diagnostics,
        })
    }

    fn candidate_edge_rows(&self) -> Result<Vec<Value>, StoreError> {
        if self.native_graph_enabled() {
            self.ensure_native_graph_ready()?;
            let edges = self
                .native_runtime
                .deterministic_kernel
                .candidate_edge_records()
                .map_err(Self::graph_backend_error)?;
            Ok(edges
                .into_iter()
                .map(graph_edge_record_to_row_value)
                .collect::<Vec<_>>())
        } else {
            self.fetch_relation_rows("graph_candidate_edges")
        }
    }

    fn native_graph_rebuild_token(&self) -> Result<String, StoreError> {
        let vertex_count = self.fetch_relation_rows("graph_vertices")?.len();
        let edge_count = self.fetch_relation_rows("graph_edges")?.len();
        let candidate_count = self.fetch_relation_rows("graph_candidate_edges")?.len();
        Ok(format!(
            "overgraph:{vertex_count}:{edge_count}:{candidate_count}"
        ))
    }

    #[allow(dead_code)]
    fn list_session_ids(&self) -> Result<Vec<SessionId>, StoreError> {
        Ok(self
            .fetch_relation_rows("phoenix_sessions")?
            .into_iter()
            .filter_map(|row| {
                row.get("session_id")
                    .and_then(Value::as_str)
                    .map(|session_id| SessionId(session_id.to_owned()))
            })
            .collect())
    }

    fn rebuild_native_graph(&self, rebuild_token: String) -> Result<(), StoreError> {
        let vertices = self
            .fetch_relation_rows("graph_vertices")?
            .iter()
            .filter_map(graph_vertex_record_from_row_value)
            .collect::<Vec<_>>();
        let asserted_edges = self
            .fetch_relation_rows("graph_edges")?
            .iter()
            .filter_map(|row| graph_edge_record_from_row_value(row, GraphLayer::Asserted))
            .collect::<Vec<_>>();
        let candidate_edges = self
            .fetch_relation_rows("graph_candidate_edges")?
            .iter()
            .filter_map(|row| graph_edge_record_from_row_value(row, GraphLayer::Candidate))
            .collect::<Vec<_>>();
        if !vertices.is_empty() || !asserted_edges.is_empty() || !candidate_edges.is_empty() {
            let batches = vec![
                KernelGraphMutationBatch::from(GraphMutationBatch {
                    layer: GraphLayer::Asserted,
                    scope: GraphMutationScope::Full,
                    vertices: vertices.clone(),
                    edges: asserted_edges,
                }),
                KernelGraphMutationBatch::from(GraphMutationBatch {
                    layer: GraphLayer::Candidate,
                    scope: GraphMutationScope::Full,
                    vertices: Vec::new(),
                    edges: candidate_edges,
                }),
            ];
            self.native_runtime
                .deterministic_kernel
                .rebuild_from_kernel_batches(batches, Some(rebuild_token))
                .map_err(Self::graph_backend_error)?;
            return Ok(());
        }
        self.native_runtime
            .deterministic_kernel
            .rebuild_from_kernel_batches(Vec::new(), Some(rebuild_token))
            .map_err(Self::graph_backend_error)
    }

    fn ensure_native_graph_ready(&self) -> Result<(), StoreError> {
        if !self.native_graph_enabled() {
            return Ok(());
        }
        let rebuild_token = self.native_graph_rebuild_token()?;
        let current_token = self.native_runtime.deterministic_kernel.rebuild_token();
        if runtime_ingest_progress_enabled() {
            eprintln!(
                "[runtime-graph] ensure_ready current_token={:?} rebuild_token={}",
                current_token, rebuild_token
            );
        }
        if current_token.as_deref() == Some(rebuild_token.as_str()) {
            if runtime_ingest_progress_enabled() {
                eprintln!("[runtime-graph] ensure_ready status=up_to_date");
            }
            return Ok(());
        }
        if runtime_ingest_progress_enabled() {
            eprintln!("[runtime-graph] ensure_ready status=rebuild");
        }
        self.rebuild_native_graph(rebuild_token)
    }

    fn refresh_native_graph_rebuild_token(&self) -> Result<(), StoreError> {
        if !self.native_graph_enabled() {
            return Ok(());
        }
        let rebuild_token = self.native_graph_rebuild_token()?;
        self.native_runtime
            .deterministic_kernel
            .set_rebuild_token(Some(rebuild_token));
        Ok(())
    }

    fn persist_native_candidate_scope_batches(
        &self,
        batches: Vec<GraphMutationBatch>,
    ) -> Result<(), StoreError> {
        if !self.native_graph_enabled() || batches.is_empty() {
            return Ok(());
        }

        let touched_scope_keys = batches
            .iter()
            .filter_map(|batch| match &batch.scope {
                GraphMutationScope::Candidate { scope_key } => Some(scope_key.clone()),
                _ => None,
            })
            .collect::<BTreeSet<_>>();
        if touched_scope_keys.is_empty() {
            return Ok(());
        }

        let mut existing_rows = HashMap::<String, Value>::new();
        for row in self.fetch_relation_rows("scoped_definitions")? {
            if row.get("namespace").and_then(Value::as_str)
                != Some(NATIVE_CANDIDATE_GRAPH_NAMESPACE)
            {
                continue;
            }
            let Some(definition_key) = row.get("definition_key").and_then(Value::as_str) else {
                continue;
            };
            if touched_scope_keys.contains(definition_key) {
                existing_rows.insert(definition_key.to_owned(), row);
            }
        }

        let updated_at = now_ms();
        let mut delete_rows = Vec::new();
        let mut stored_batches = Vec::new();

        for batch in batches {
            let GraphMutationScope::Candidate { scope_key } = &batch.scope else {
                return Err(StoreError::Query(
                    "native candidate persistence received a non-candidate scope".to_owned(),
                ));
            };
            let scope_key = scope_key.clone();
            if batch.edges.is_empty() {
                if let Some(row) = existing_rows.remove(&scope_key) {
                    delete_rows.push(row);
                }
                stored_batches.push(batch);
                continue;
            }

            let narrative_id = batch
                .edges
                .iter()
                .find_map(|edge| edge.narrative_id.clone());
            let mut payload = serde_json::to_value(&batch).map_err(|error| {
                StoreError::Query(format!(
                    "failed to serialize native candidate graph batch for {scope_key}: {error}"
                ))
            })?;
            if let Some(object) = payload.as_object_mut() {
                object.insert("updatedAt".to_owned(), json!(updated_at));
            }
            self.put_relation_row(
                "scoped_definitions",
                json!({
                    "id": native_candidate_definition_row_id(&scope_key),
                    "narrative_id": narrative_id,
                    "namespace": NATIVE_CANDIDATE_GRAPH_NAMESPACE,
                    "definition_key": scope_key,
                    "payload": payload,
                    "created_at": updated_at,
                    "updated_at": updated_at,
                }),
            )?;
            stored_batches.push(batch);
        }

        if !delete_rows.is_empty() {
            self.delete_relation_rows("scoped_definitions", &delete_rows)?;
        }

        let apply_result = (|| {
            for batch in &stored_batches {
                self.native_runtime
                    .deterministic_kernel
                    .apply_compat_batch(batch.clone())
                    .map_err(Self::graph_backend_error)?;
            }
            Ok(())
        })();
        if let Err(error) = apply_result {
            self.native_runtime.deterministic_kernel.invalidate();
            return Err(error);
        }

        let source_revision = self.native_graph_rebuild_token()?;
        for batch in &stored_batches {
            let kernel_batch = KernelGraphMutationBatch::from(batch.clone());
            self.persist_native_graph_batch(&kernel_batch, Some(source_revision.clone()))?;
        }

        self.refresh_native_graph_rebuild_token()
    }

    pub fn create_session(
        &self,
        request: CreateSessionRequest,
    ) -> Result<SessionRecord, StoreError> {
        let now = now_ms();
        let session_id = request
            .session_id
            .unwrap_or_else(|| SessionId(format!("session-{}", now)));
        let record = SessionRecord {
            session_id,
            label: request.label,
            scope: request.scope,
            status: "active".to_owned(),
            revision: 0,
            created_at: now,
            updated_at: now,
        };

        self.put_relation_row(
            "phoenix_sessions",
            serde_json::json!({
                "session_id": record.session_id.0,
                "label": record.label,
                "world_id": record.scope.world_id,
                "narrative_id": record.scope.narrative_id,
                "folder_id": record.scope.folder_id,
                "folder_path": record.scope.folder_path,
                "status": record.status,
                "revision": record.revision,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }),
        )?;

        Ok(record)
    }

    pub fn commit(&self, request: CommitRequest) -> Result<CommitResult, StoreError> {
        let mut session = self.load_session(&request.session_id)?;
        let committed_at = now_ms();
        session.revision += 1;
        session.updated_at = committed_at;
        let session_row = serde_json::json!({
            "session_id": session.session_id.0,
            "label": session.label,
            "world_id": session.scope.world_id,
            "narrative_id": session.scope.narrative_id,
            "folder_id": session.scope.folder_id,
            "folder_path": session.scope.folder_path,
            "status": session.status,
            "revision": session.revision,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        });

        let commit_id = CommitId(format!(
            "commit-{}-{}",
            session.session_id.0, session.revision
        ));
        let commit_row = serde_json::json!({
            "commit_id": commit_id.0,
            "session_id": session.session_id.0,
            "reason": request.reason,
            "revision": session.revision,
            "committed_at": committed_at,
        });

        self.put_relation_row("phoenix_sessions", session_row)?;
        self.put_relation_row("phoenix_commits", commit_row)?;

        Ok(CommitResult {
            session_id: session.session_id,
            commit_id,
            revision: session.revision,
            committed_at,
            relation_counts: if self.native_graph_enabled() {
                Vec::new()
            } else {
                self.relation_counts()?
            },
            diagnostics: Vec::new(),
        })
    }

    pub fn rebuild(&self, _request: RebuildRequest) -> Result<RebuildResult, StoreError> {
        let rebuilt_at = now_ms();
        let dirty_scope_count = 0usize;
        let span_count = if self.native_graph_enabled() {
            self.invalidate_lex_caches();
            self.native_note_rows_to_indexed_spans()?.len()
        } else {
            self.rebuild_lex_index()?
        };
        let pruned_graph_documents = self.prune_native_graph_to_live_notes()?;
        let mut diagnostics = vec![Diagnostic {
            code: "PX_REBUILD_LEX".to_owned(),
            message: format!(
                "Rebuilt lexical sidecars from {span_count} canonical spans across {dirty_scope_count} dirty scopes."
            ),
        }];
        if pruned_graph_documents > 0 {
            diagnostics.push(Diagnostic {
                code: "PX_REBUILD_GRAPH_PRUNE".to_owned(),
                message: format!(
                    "Pruned {pruned_graph_documents} out-of-tree graph document scopes from native topology."
                ),
            });
        }
        #[cfg(all(not(target_arch = "wasm32"), feature = "legacy-cozo-graph"))]
        if let Some(report) = self.sync_overgraph_lane_from_graph_rows()? {
            diagnostics.push(Diagnostic {
                code: "PX_OVERGRAPH_SYNC".to_owned(),
                message: format!(
                    "Mirrored {} graph nodes and {} graph edges into OverGraph lane.",
                    report.nodes, report.edges
                ),
            });
        }
        Ok(RebuildResult {
            rebuilt_at,
            relation_counts: if self.native_graph_enabled() {
                Vec::new()
            } else {
                self.relation_counts()?
            },
            diagnostics,
        })
    }

    pub fn ingest(&self, request: IngestRequest) -> Result<IngestResult, StoreError> {
        self.ingest_view(IngestRequestView::from(&request))
    }

    pub fn ingest_view(&self, request: IngestRequestView<'_>) -> Result<IngestResult, StoreError> {
        let created_at = now_ms();
        let request_summary = serde_json::json!({
            "sessionId": request.session_id.as_ref().map(|value| value.0.clone()),
            "documentCount": request.documents.len(),
            "documentIds": request.documents.iter().map(|document| document.document_id.0.clone()).collect::<Vec<_>>(),
            "titles": request.documents.iter().map(|document| document.title.to_owned()).collect::<Vec<_>>(),
            "commit": request.commit,
        });
        self.put_relation_row(
            "phoenix_ingest_log",
            serde_json::json!({
                "id": format!("ingest-{}", created_at),
                "session_id": request.session_id.as_ref().map(|value| value.0.clone()),
                "document_count": request.documents.len(),
                "commit_requested": request.commit,
                "request_json": request_summary,
                "created_at": created_at,
            }),
        )?;
        let mut ingest = if self.native_graph_enabled() {
            let mut ingest = self.native_ingest_overgraph_view(&request, created_at)?;
            if request.commit {
                if let Some(session_id) = request.session_id.clone() {
                    let commit = self.commit(CommitRequest {
                        session_id,
                        reason: Some("overgraph-native-ingest".to_owned()),
                    })?;
                    ingest.diagnostics.extend(commit.diagnostics);
                }
            }
            ingest
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let documents = request
                    .documents
                    .iter()
                    .map(|document| BorrowedIngestDocument {
                        document_id: document.document_id.clone(),
                        note_id: document.note_id.clone(),
                        title: document.title,
                        text: document.text,
                        scope: document.scope.to_owned(),
                    })
                    .collect::<Vec<_>>();
                let borrowed_request = BorrowedIngestRequest {
                    session_id: request.session_id.clone(),
                    documents: &documents,
                };
                self.graptor.ingest_view(
                    &self.store,
                    &self.scanner,
                    &self.structure,
                    &borrowed_request,
                )?
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("Graptor ingest"));
            }
        };
        let mut diagnostics = ingest.diagnostics.clone();
        diagnostics.push(Diagnostic {
            code: if self.native_graph_enabled() {
                "PX_INGEST_INVARANT_V2".to_owned()
            } else {
                "PX_INGEST_GRAPTOR".to_owned()
            },
            message: if self.native_graph_enabled() {
                "Phoenix Invarant V2 ingested native bundles, semantic state, and kernel graph mutations.".to_owned()
            } else {
                "Phoenix Graptor ingested canonical chunk and graph facts.".to_owned()
            },
        });
        #[cfg(all(not(target_arch = "wasm32"), feature = "legacy-cozo-graph"))]
        if let Some(report) = self.sync_overgraph_lane_from_graph_rows()? {
            diagnostics.push(Diagnostic {
                code: "PX_OVERGRAPH_SYNC".to_owned(),
                message: format!(
                    "Mirrored {} graph nodes and {} graph edges into OverGraph lane.",
                    report.nodes, report.edges
                ),
            });
        }

        self.invalidate_lex_caches();
        if runtime_ingest_progress_enabled() {
            eprintln!("[runtime-ingest] phase=final_relation_counts");
        }
        ingest.diagnostics = diagnostics;
        ingest.warning_count = ingest.diagnostics.len();
        ingest.relation_counts = self.relation_counts()?;
        Ok(ingest)
    }

    fn native_ingest_overgraph_view(
        &self,
        request: &IngestRequestView<'_>,
        created_at: i64,
    ) -> Result<IngestResult, StoreError> {
        let entity_rows = self.fetch_relation_rows("entities")?;
        let mut vertex_rows = Vec::new();
        let mut edge_rows = Vec::new();
        let mut label_rows = Vec::new();
        let mut vertex_ids = BTreeSet::new();
        let mut edge_pairs = BTreeSet::new();
        let mut summaries = Vec::with_capacity(request.documents.len());
        let mut total_entities = 0usize;

        for document in &request.documents {
            let scope = document.scope.to_owned();
            let document_id = document.document_id.0.clone();
            let note_id = document
                .note_id
                .as_ref()
                .map(|note_id| note_id.0.clone())
                .unwrap_or_else(|| document_id.clone());
            let note_row = native_note_row_from_ingest(document, &note_id, created_at);
            self.delete_note_rows(&note_id)?;
            self.put_relation_row("notes", note_row)?;

            let doc_vertex_id = phase1_document_vertex_id(&document_id);
            phase1_push_vertex(
                &mut vertex_ids,
                &mut vertex_rows,
                &mut label_rows,
                phase1_vertex_row(
                    &doc_vertex_id,
                    "document",
                    document.title,
                    Some(&document_id),
                    scope.narrative_id.as_deref(),
                    Map::new(),
                    vec![format!("document:{document_id}")],
                ),
            );

            let chunks = split_ingest_leaf_chunks(document.text);
            for (index, chunk) in chunks.iter().enumerate() {
                let leaf_id = format!("leaf::{document_id}::{index}");
                let mut attributes = Map::new();
                attributes.insert("noteId".to_owned(), json!(note_id));
                attributes.insert("searchChunkId".to_owned(), json!(leaf_id));
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_vertex_row(
                        &leaf_id,
                        "leaf",
                        &phase1_snippet(chunk, 96),
                        Some(&document_id),
                        scope.narrative_id.as_deref(),
                        attributes,
                        vec![format!("document:{document_id}")],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &doc_vertex_id,
                        &leaf_id,
                        "contains",
                        Some(&document_id),
                        scope.narrative_id.as_deref(),
                        Map::new(),
                        vec![format!("document:{document_id}")],
                    ),
                );
            }

            let normalized_text = normalize_lexical_query(document.text);
            let mut matched_entities = 0usize;
            for entity in &entity_rows {
                if !row_matches_scope(entity, &scope) {
                    continue;
                }
                let Some(entity_id) = entity.get("id").and_then(Value::as_str) else {
                    continue;
                };
                let label = entity
                    .get("label")
                    .and_then(Value::as_str)
                    .unwrap_or(entity_id);
                let mut aliases = vec![label];
                aliases.extend(
                    entity
                        .get("aliases")
                        .and_then(Value::as_array)
                        .into_iter()
                        .flatten()
                        .filter_map(Value::as_str),
                );
                if !aliases
                    .iter()
                    .any(|alias| normalized_text.contains(&normalize_lexical_query(alias)))
                {
                    continue;
                }
                matched_entities += 1;
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_vertex_row(
                        &format!("entity::{entity_id}"),
                        "entity",
                        label,
                        Some(&document_id),
                        scope.narrative_id.as_deref(),
                        Map::new(),
                        vec![format!("entity:{entity_id}")],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &doc_vertex_id,
                        &format!("entity::{entity_id}"),
                        "mentions",
                        Some(&document_id),
                        scope.narrative_id.as_deref(),
                        Map::new(),
                        vec![
                            format!("document:{document_id}"),
                            format!("entity:{entity_id}"),
                        ],
                    ),
                );
            }
            total_entities += matched_entities;
            summaries.push(phoenix_types::IngestDocumentSummary {
                document_id: document.document_id.clone(),
                note_id: document.note_id.clone(),
                chapter_count: 0,
                boundary_count: 0,
                parent_count: 0,
                leaf_count: chunks.len(),
                entity_count: matched_entities,
                edge_count: chunks.len() + matched_entities,
                has_front_matter_chapter: false,
                has_front_matter_boundary: false,
            });
        }

        self.replace_native_graph_document_rows(
            request
                .documents
                .iter()
                .map(|document| document.document_id.0.clone())
                .collect(),
            vertex_rows.clone(),
            edge_rows.clone(),
            label_rows,
        )?;
        let batch = KernelGraphMutationBatch::from(GraphMutationBatch {
            layer: GraphLayer::Asserted,
            scope: GraphMutationScope::Full,
            vertices: vertex_rows
                .iter()
                .filter_map(graph_vertex_record_from_row_value)
                .collect(),
            edges: edge_rows
                .iter()
                .filter_map(|row| graph_edge_record_from_row_value(row, GraphLayer::Asserted))
                .collect(),
        });
        self.native_runtime
            .deterministic_kernel
            .apply_batch(batch)
            .map_err(Self::graph_backend_error)?;
        self.refresh_native_graph_rebuild_token()?;

        let total_leaves = summaries.iter().map(|summary| summary.leaf_count).sum();
        let total_edges = summaries.iter().map(|summary| summary.edge_count).sum();
        Ok(IngestResult {
            session_id: request.session_id.clone(),
            document_count: summaries.len(),
            warning_count: 1,
            documents: summaries,
            chunk_stats: Some(phoenix_types::ChunkStats {
                documents: request.documents.len(),
                total_chapters: 0,
                total_boundaries: 0,
                total_parents: 0,
                total_leaves,
            }),
            graph_summary: Some(phoenix_types::GraphSummary {
                documents: request.documents.len(),
                total_chapters: 0,
                total_boundaries: 0,
                total_leaves,
                total_entities,
                total_mentions: total_entities,
                total_edges,
                cross_chapter_links: 0,
            }),
            entity_summary: Some(phoenix_types::EntitySummary {
                total_entities,
                total_aliases: 0,
                total_mentions: total_entities,
                multi_chapter_entities: 0,
            }),
            discovery_summary: None,
            retrieval_summary: None,
            relation_counts: Vec::new(),
            diagnostics: vec![Diagnostic {
                code: "PX_INGEST_OVERGRAPH_NATIVE".to_owned(),
                message:
                    "Native ingest wrote notes and graph topology directly into OverGraph rows."
                        .to_owned(),
            }],
        })
    }

    fn replace_native_graph_document_rows(
        &self,
        document_ids: BTreeSet<String>,
        mut vertex_rows: Vec<Value>,
        mut edge_rows: Vec<Value>,
        mut label_rows: Vec<Value>,
    ) -> Result<(), StoreError> {
        let mut existing_vertices = self.fetch_relation_rows("graph_vertices")?;
        let stale_vertex_ids = existing_vertices
            .iter()
            .filter(|row| {
                row.get("document_id")
                    .and_then(Value::as_str)
                    .map(|document_id| document_ids.contains(document_id))
                    .unwrap_or(false)
            })
            .filter_map(|row| row.get("id").and_then(Value::as_str).map(str::to_owned))
            .collect::<BTreeSet<_>>();
        existing_vertices.retain(|row| {
            !row.get("document_id")
                .and_then(Value::as_str)
                .map(|document_id| document_ids.contains(document_id))
                .unwrap_or(false)
        });
        existing_vertices.append(&mut vertex_rows);
        self.native_row_store()?
            .replace_relation_rows("graph_vertices", &existing_vertices)?;

        let mut existing_edges = self.fetch_relation_rows("graph_edges")?;
        existing_edges.retain(|row| {
            !row.get("document_id")
                .and_then(Value::as_str)
                .map(|document_id| document_ids.contains(document_id))
                .unwrap_or(false)
        });
        existing_edges.append(&mut edge_rows);
        self.native_row_store()?
            .replace_relation_rows("graph_edges", &existing_edges)?;

        let mut existing_labels = self.fetch_relation_rows("graph_vertex_labels")?;
        existing_labels.retain(|row| {
            !row.get("vertex_id")
                .and_then(Value::as_str)
                .map(|vertex_id| stale_vertex_ids.contains(vertex_id))
                .unwrap_or(false)
        });
        existing_labels.append(&mut label_rows);
        self.native_row_store()?
            .replace_relation_rows("graph_vertex_labels", &existing_labels)?;
        Ok(())
    }

    fn persist_current_kernel_snapshot_rows(&self) -> Result<(), StoreError> {
        let graph = self
            .native_runtime
            .deterministic_kernel
            .snapshot_current_kernel(true);
        let vertex_rows = graph
            .vertices
            .iter()
            .map(kernel_vertex_to_row_value)
            .collect::<Vec<_>>();
        let asserted_rows = graph
            .asserted_edges
            .iter()
            .map(kernel_edge_to_row_value)
            .collect::<Vec<_>>();
        let candidate_rows = graph
            .candidate_edges
            .iter()
            .map(kernel_edge_to_row_value)
            .collect::<Vec<_>>();
        let label_rows = graph
            .vertices
            .iter()
            .map(|vertex| json!({"vertex_id": vertex.id.0, "label": kernel_vertex_label(vertex)}))
            .collect::<Vec<_>>();
        let store = self.native_row_store()?;
        store.replace_relation_rows("graph_vertices", &vertex_rows)?;
        store.replace_relation_rows("graph_edges", &asserted_rows)?;
        store.replace_relation_rows("graph_candidate_edges", &candidate_rows)?;
        store.replace_relation_rows("graph_vertex_labels", &label_rows)?;
        Ok(())
    }

    #[allow(dead_code)]
    #[cfg(feature = "legacy-cozo-graph")]
    fn refresh_asserted_native_graph(
        &self,
        session_id: &SessionId,
    ) -> Result<NativeGraphEnrichmentStats, StoreError> {
        let session = self.load_session(session_id)?;
        let session_state = if self.native_graph_enabled() {
            self.session_state(session_id)?
        } else {
            load_session_state(&self.store, session_id)?
        };
        let graph = self.phase2_graph_view(false)?;
        let message_document_links = phase1_message_document_links(&session_state, &graph);
        let singleton_document_id = (session_state.documents.len() == 1)
            .then(|| session_state.documents[0].document_id.0.clone());
        let mut threads = self
            .chat
            .list_threads(
                self.chat_store()?,
                session
                    .scope
                    .world_id
                    .as_deref()
                    .filter(|value| !value.is_empty()),
            )?
            .into_iter()
            .filter(|thread| phase1_thread_matches_session(&session, thread))
            .collect::<Vec<_>>();
        threads.sort_by(|left, right| left.id.cmp(&right.id));

        let mut stats = NativeGraphEnrichmentStats::default();
        let mut vertex_ids = BTreeSet::new();
        let mut edge_pairs = BTreeSet::new();
        let mut vertex_rows = Vec::new();
        let mut label_rows = Vec::new();
        let mut edge_rows = Vec::new();

        for thread in threads {
            let mut messages = self.chat.list_messages(self.chat_store()?, &thread.id.0)?;
            if messages.is_empty() {
                continue;
            }
            messages.sort_by(|left, right| {
                left.created_at
                    .cmp(&right.created_at)
                    .then_with(|| left.id.cmp(&right.id))
            });
            stats.thread_count += 1;

            let mut events =
                self.chat
                    .list_run_events_for_thread(self.chat_store()?, &thread.id.0, 256)?;
            events.sort_by(|left, right| {
                left.created_at
                    .cmp(&right.created_at)
                    .then_with(|| left.id.cmp(&right.id))
            });
            let om_record = self.load_latest_om_record_for_thread(&thread.id.0)?;
            let mut message_links = HashMap::<String, Vec<String>>::new();

            for message in &messages {
                let document_links = phase1_document_links_for_message(
                    &message.id,
                    &message_document_links,
                    singleton_document_id.as_deref(),
                );
                message_links.insert(message.id.clone(), document_links.clone());

                let turn_id = phase1_turn_vertex_id(&message.id);
                let turn_document_id =
                    (document_links.len() == 1).then(|| document_links[0].clone());
                let turn_label = phase1_turn_label(message);
                let mut turn_attributes = Map::new();
                turn_attributes.insert("sessionId".to_owned(), json!(session_id.0));
                turn_attributes.insert("threadId".to_owned(), json!(thread.id.0));
                turn_attributes.insert("messageId".to_owned(), json!(message.id));
                turn_attributes.insert("role".to_owned(), json!(message.role));
                turn_attributes.insert("createdAt".to_owned(), json!(message.created_at));
                turn_attributes.insert("documentIds".to_owned(), json!(document_links.clone()));
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_vertex_row(
                        &turn_id,
                        "turn",
                        &turn_label,
                        turn_document_id.as_deref(),
                        phase1_narrative_id(&thread, message, &session).as_deref(),
                        turn_attributes,
                        vec![format!("thread_message:{}", message.id)],
                    ),
                );

                let agent_id = phase1_agent_vertex_id(session_id, &message.role);
                let mut agent_attributes = Map::new();
                agent_attributes.insert("sessionId".to_owned(), json!(session_id.0));
                agent_attributes.insert("role".to_owned(), json!(message.role));
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_vertex_row(
                        &agent_id,
                        "agent",
                        &message.role,
                        None,
                        phase1_narrative_id(&thread, message, &session).as_deref(),
                        agent_attributes,
                        vec![format!("thread_role:{}", message.role)],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &turn_id,
                        &agent_id,
                        "seen_by",
                        None,
                        phase1_narrative_id(&thread, message, &session).as_deref(),
                        {
                            let mut attributes = Map::new();
                            attributes.insert("sessionId".to_owned(), json!(session_id.0));
                            attributes.insert("threadId".to_owned(), json!(thread.id.0));
                            attributes.insert("messageId".to_owned(), json!(message.id));
                            attributes.insert("role".to_owned(), json!(message.role));
                            attributes
                        },
                        vec![
                            format!("thread_message:{}", message.id),
                            format!("thread_role:{}", message.role),
                        ],
                    ),
                );

                let time_id = phase1_time_vertex_id("message", &message.id);
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_time_vertex_row(
                        &time_id,
                        session_id,
                        "message",
                        &message.id,
                        message.created_at,
                        phase1_narrative_id(&thread, message, &session).as_deref(),
                        vec![format!("thread_message:{}", message.id)],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &turn_id,
                        &time_id,
                        "active_during",
                        turn_document_id.as_deref(),
                        phase1_narrative_id(&thread, message, &session).as_deref(),
                        {
                            let mut attributes = Map::new();
                            attributes.insert("sessionId".to_owned(), json!(session_id.0));
                            attributes.insert("threadId".to_owned(), json!(thread.id.0));
                            attributes.insert("messageId".to_owned(), json!(message.id));
                            attributes.insert("timestampMs".to_owned(), json!(message.created_at));
                            attributes
                        },
                        vec![format!("thread_message:{}", message.id)],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &time_id,
                        &turn_id,
                        "derived_from",
                        turn_document_id.as_deref(),
                        phase1_narrative_id(&thread, message, &session).as_deref(),
                        {
                            let mut attributes = Map::new();
                            attributes.insert("sessionId".to_owned(), json!(session_id.0));
                            attributes.insert("threadId".to_owned(), json!(thread.id.0));
                            attributes.insert("messageId".to_owned(), json!(message.id));
                            attributes.insert("timestampMs".to_owned(), json!(message.created_at));
                            attributes
                        },
                        vec![format!("thread_message:{}", message.id)],
                    ),
                );

                for document_id in &document_links {
                    phase1_push_edge(
                        &mut edge_pairs,
                        &mut edge_rows,
                        phase1_edge_row(
                            &turn_id,
                            &phase1_document_vertex_id(document_id),
                            "about",
                            Some(document_id.as_str()),
                            phase1_narrative_id(&thread, message, &session).as_deref(),
                            {
                                let mut attributes = Map::new();
                                attributes.insert("sessionId".to_owned(), json!(session_id.0));
                                attributes.insert("threadId".to_owned(), json!(thread.id.0));
                                attributes.insert("messageId".to_owned(), json!(message.id));
                                attributes.insert("documentId".to_owned(), json!(document_id));
                                attributes
                            },
                            vec![
                                format!("thread_message:{}", message.id),
                                format!("document:{document_id}"),
                            ],
                        ),
                    );
                }
            }

            for event in &events {
                let state_id = phase1_state_vertex_id(&event.id);
                let anchor_message =
                    phase1_latest_message_at_or_before(&messages, event.created_at);
                let event_document_id = anchor_message
                    .and_then(|message| message_links.get(&message.id))
                    .filter(|document_ids| document_ids.len() == 1)
                    .map(|document_ids| document_ids[0].clone());
                let mut state_attributes = Map::new();
                state_attributes.insert("sessionId".to_owned(), json!(session_id.0));
                state_attributes.insert("threadId".to_owned(), json!(thread.id.0));
                state_attributes.insert("runEventId".to_owned(), json!(event.id));
                state_attributes.insert("phase".to_owned(), json!(event.phase));
                state_attributes.insert("kind".to_owned(), json!(event.kind));
                state_attributes.insert("status".to_owned(), json!(event.status.clone()));
                state_attributes.insert("createdAt".to_owned(), json!(event.created_at));
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_vertex_row(
                        &state_id,
                        "state",
                        &phase1_state_label(event),
                        event_document_id.as_deref(),
                        phase1_thread_narrative_id(&thread, &session).as_deref(),
                        state_attributes,
                        vec![format!("chat_run_event:{}", event.id)],
                    ),
                );

                let state_time_id = phase1_time_vertex_id("state", &event.id);
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_time_vertex_row(
                        &state_time_id,
                        session_id,
                        "state",
                        &event.id,
                        event.created_at,
                        phase1_thread_narrative_id(&thread, &session).as_deref(),
                        vec![format!("chat_run_event:{}", event.id)],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &state_id,
                        &state_time_id,
                        "active_during",
                        event_document_id.as_deref(),
                        phase1_thread_narrative_id(&thread, &session).as_deref(),
                        {
                            let mut attributes = Map::new();
                            attributes.insert("sessionId".to_owned(), json!(session_id.0));
                            attributes.insert("threadId".to_owned(), json!(thread.id.0));
                            attributes.insert("runEventId".to_owned(), json!(event.id));
                            attributes.insert("timestampMs".to_owned(), json!(event.created_at));
                            attributes
                        },
                        vec![format!("chat_run_event:{}", event.id)],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &state_time_id,
                        &state_id,
                        "derived_from",
                        event_document_id.as_deref(),
                        phase1_thread_narrative_id(&thread, &session).as_deref(),
                        {
                            let mut attributes = Map::new();
                            attributes.insert("sessionId".to_owned(), json!(session_id.0));
                            attributes.insert("threadId".to_owned(), json!(thread.id.0));
                            attributes.insert("runEventId".to_owned(), json!(event.id));
                            attributes.insert("timestampMs".to_owned(), json!(event.created_at));
                            attributes
                        },
                        vec![format!("chat_run_event:{}", event.id)],
                    ),
                );

                if let Some(message) = anchor_message {
                    phase1_push_edge(
                        &mut edge_pairs,
                        &mut edge_rows,
                        phase1_edge_row(
                            &state_id,
                            &phase1_turn_vertex_id(&message.id),
                            "depends_on",
                            event_document_id.as_deref(),
                            phase1_thread_narrative_id(&thread, &session).as_deref(),
                            {
                                let mut attributes = Map::new();
                                attributes.insert("sessionId".to_owned(), json!(session_id.0));
                                attributes.insert("threadId".to_owned(), json!(thread.id.0));
                                attributes.insert("runEventId".to_owned(), json!(event.id));
                                attributes.insert("messageId".to_owned(), json!(message.id));
                                attributes
                            },
                            vec![
                                format!("chat_run_event:{}", event.id),
                                format!("thread_message:{}", message.id),
                            ],
                        ),
                    );
                }
            }

            if let Some(record) = om_record
                .as_ref()
                .filter(|record| !record.current_task.trim().is_empty())
            {
                let task_id = phase1_task_vertex_id(&thread.id.0);
                let observed_message = phase1_latest_message_at_or_before(
                    &messages,
                    record.updated_at.max(record.last_observed_at),
                );
                let task_document_links = observed_message
                    .and_then(|message| message_links.get(&message.id).cloned())
                    .unwrap_or_else(|| {
                        singleton_document_id
                            .as_ref()
                            .map(|document_id| vec![document_id.clone()])
                            .unwrap_or_default()
                    });
                let task_document_id =
                    (task_document_links.len() == 1).then(|| task_document_links[0].clone());
                let mut task_attributes = Map::new();
                task_attributes.insert("sessionId".to_owned(), json!(session_id.0));
                task_attributes.insert("threadId".to_owned(), json!(thread.id.0));
                task_attributes.insert("currentTask".to_owned(), json!(record.current_task));
                task_attributes.insert("updatedAt".to_owned(), json!(record.updated_at));
                task_attributes
                    .insert("documentIds".to_owned(), json!(task_document_links.clone()));
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_vertex_row(
                        &task_id,
                        "task",
                        record.current_task.trim(),
                        task_document_id.as_deref(),
                        phase1_thread_narrative_id(&thread, &session).as_deref(),
                        task_attributes,
                        vec![format!("om_record:{}", record.thread_id)],
                    ),
                );

                let task_time_id = phase1_time_vertex_id("task", &thread.id.0);
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_time_vertex_row(
                        &task_time_id,
                        session_id,
                        "task",
                        &thread.id.0,
                        record.updated_at.max(record.last_observed_at),
                        phase1_thread_narrative_id(&thread, &session).as_deref(),
                        vec![format!("om_record:{}", record.thread_id)],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &task_id,
                        &task_time_id,
                        "active_during",
                        task_document_id.as_deref(),
                        phase1_thread_narrative_id(&thread, &session).as_deref(),
                        {
                            let mut attributes = Map::new();
                            attributes.insert("sessionId".to_owned(), json!(session_id.0));
                            attributes.insert("threadId".to_owned(), json!(thread.id.0));
                            attributes.insert(
                                "timestampMs".to_owned(),
                                json!(record.updated_at.max(record.last_observed_at)),
                            );
                            attributes
                        },
                        vec![format!("om_record:{}", record.thread_id)],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &task_time_id,
                        &task_id,
                        "derived_from",
                        task_document_id.as_deref(),
                        phase1_thread_narrative_id(&thread, &session).as_deref(),
                        {
                            let mut attributes = Map::new();
                            attributes.insert("sessionId".to_owned(), json!(session_id.0));
                            attributes.insert("threadId".to_owned(), json!(thread.id.0));
                            attributes.insert(
                                "timestampMs".to_owned(),
                                json!(record.updated_at.max(record.last_observed_at)),
                            );
                            attributes
                        },
                        vec![format!("om_record:{}", record.thread_id)],
                    ),
                );

                if let Some(message) = observed_message {
                    phase1_push_edge(
                        &mut edge_pairs,
                        &mut edge_rows,
                        phase1_edge_row(
                            &task_id,
                            &phase1_turn_vertex_id(&message.id),
                            "observed_in",
                            task_document_id.as_deref(),
                            phase1_thread_narrative_id(&thread, &session).as_deref(),
                            {
                                let mut attributes = Map::new();
                                attributes.insert("sessionId".to_owned(), json!(session_id.0));
                                attributes.insert("threadId".to_owned(), json!(thread.id.0));
                                attributes.insert("messageId".to_owned(), json!(message.id));
                                attributes
                            },
                            vec![
                                format!("om_record:{}", record.thread_id),
                                format!("thread_message:{}", message.id),
                            ],
                        ),
                    );
                }

                if let Some(state) = phase1_event_for_task(&events, record.updated_at) {
                    phase1_push_edge(
                        &mut edge_pairs,
                        &mut edge_rows,
                        phase1_edge_row(
                            &task_id,
                            &phase1_state_vertex_id(&state.id),
                            "valid_under",
                            task_document_id.as_deref(),
                            phase1_thread_narrative_id(&thread, &session).as_deref(),
                            {
                                let mut attributes = Map::new();
                                attributes.insert("sessionId".to_owned(), json!(session_id.0));
                                attributes.insert("threadId".to_owned(), json!(thread.id.0));
                                attributes.insert("runEventId".to_owned(), json!(state.id));
                                attributes
                            },
                            vec![
                                format!("om_record:{}", record.thread_id),
                                format!("chat_run_event:{}", state.id),
                            ],
                        ),
                    );
                }

                for document_id in &task_document_links {
                    phase1_push_edge(
                        &mut edge_pairs,
                        &mut edge_rows,
                        phase1_edge_row(
                            &task_id,
                            &phase1_document_vertex_id(document_id),
                            "about",
                            Some(document_id.as_str()),
                            phase1_thread_narrative_id(&thread, &session).as_deref(),
                            {
                                let mut attributes = Map::new();
                                attributes.insert("sessionId".to_owned(), json!(session_id.0));
                                attributes.insert("threadId".to_owned(), json!(thread.id.0));
                                attributes.insert("documentId".to_owned(), json!(document_id));
                                attributes
                            },
                            vec![
                                format!("om_record:{}", record.thread_id),
                                format!("document:{document_id}"),
                            ],
                        ),
                    );
                }
            }
        }

        stats.vertex_count = vertex_rows.len();
        stats.edge_count = edge_rows.len();
        if self.native_graph_enabled() {
            let batch = GraphMutationBatch {
                layer: GraphLayer::Asserted,
                scope: GraphMutationScope::Session {
                    session_id: session_id.0.clone(),
                },
                vertices: vertex_rows
                    .iter()
                    .filter_map(graph_vertex_record_from_row_value)
                    .collect(),
                edges: edge_rows
                    .iter()
                    .filter_map(|row| graph_edge_record_from_row_value(row, GraphLayer::Asserted))
                    .collect(),
            };
            self.native_runtime
                .deterministic_kernel
                .apply_compat_batch(batch.clone())
                .map_err(Self::graph_backend_error)?;
            let kernel_batch = KernelGraphMutationBatch::from(batch);
            self.persist_native_graph_batch(&kernel_batch, None)?;
            return Ok(stats);
        }

        #[cfg(feature = "legacy-cozo-graph")]
        {
            let (removed_vertex_count, removed_edge_count) =
                self.prune_stale_native_graph_rows(session_id, &vertex_ids, &edge_pairs)?;
            stats.removed_vertex_count = removed_vertex_count;
            stats.removed_edge_count = removed_edge_count;
            for row in vertex_rows {
                self.store.put_row("graph_vertices", row)?;
            }
            for row in label_rows {
                self.store.put_row("graph_vertex_labels", row)?;
            }
            for row in edge_rows {
                self.store.put_row("graph_edges", row)?;
            }
            Ok(stats)
        }
        #[cfg(not(feature = "legacy-cozo-graph"))]
        {
            let _ = (
                session_id,
                vertex_ids,
                edge_pairs,
                vertex_rows,
                label_rows,
                edge_rows,
            );
            Err(self.legacy_graph_disabled("legacy graph row upsert"))
        }
    }

    #[allow(dead_code)]
    #[cfg(feature = "legacy-cozo-graph")]
    fn prune_stale_native_graph_rows(
        &self,
        session_id: &SessionId,
        keep_vertex_ids: &BTreeSet<String>,
        keep_edge_pairs: &BTreeSet<(String, String)>,
    ) -> Result<(usize, usize), StoreError> {
        let existing_vertex_rows = self.store.fetch_rows("graph_vertices")?;
        let existing_vertex_compact = self.store.fetch_compact_rows("graph_vertices")?;
        let mut removed_vertex_ids = BTreeSet::new();
        let stale_vertices = existing_vertex_rows
            .iter()
            .zip(existing_vertex_compact)
            .filter_map(|(row, compact)| {
                phase1_native_graph_row_matches_session(row, session_id)
                    .then(|| row.get("id").and_then(Value::as_str).map(str::to_owned))
                    .flatten()
                    .filter(|vertex_id| !keep_vertex_ids.contains(vertex_id))
                    .map(|vertex_id| {
                        removed_vertex_ids.insert(vertex_id);
                        compact
                    })
            })
            .collect::<Vec<_>>();
        let removed_vertex_count = stale_vertices.len();
        if !stale_vertices.is_empty() {
            self.store
                .delete_key_rows("graph_vertices", &stale_vertices)?;
        }

        if !removed_vertex_ids.is_empty() {
            let label_rows = self.store.fetch_rows("graph_vertex_labels")?;
            let label_compact = self.store.fetch_compact_rows("graph_vertex_labels")?;
            let stale_labels = label_rows
                .iter()
                .zip(label_compact)
                .filter_map(|(row, compact)| {
                    row.get("vertex_id")
                        .and_then(Value::as_str)
                        .filter(|vertex_id| removed_vertex_ids.contains(*vertex_id))
                        .map(|_| compact)
                })
                .collect::<Vec<_>>();
            if !stale_labels.is_empty() {
                self.store
                    .delete_key_rows("graph_vertex_labels", &stale_labels)?;
            }
        }

        let edge_rows = self.store.fetch_rows("graph_edges")?;
        let edge_compact = self.store.fetch_compact_rows("graph_edges")?;
        let stale_edges = edge_rows
            .iter()
            .zip(edge_compact)
            .filter_map(|(row, compact)| {
                let source_id = row.get("source_id").and_then(Value::as_str)?;
                let target_id = row.get("target_id").and_then(Value::as_str)?;
                phase1_native_graph_row_matches_session(row, session_id).then_some((
                    source_id.to_owned(),
                    target_id.to_owned(),
                    compact,
                ))
            })
            .filter_map(|(source_id, target_id, compact)| {
                (!keep_edge_pairs.contains(&(source_id, target_id))).then_some(compact)
            })
            .collect::<Vec<_>>();
        let removed_edge_count = stale_edges.len();
        if !stale_edges.is_empty() {
            self.store.delete_key_rows("graph_edges", &stale_edges)?;
        }

        Ok((removed_vertex_count, removed_edge_count))
    }

    #[allow(dead_code)]
    #[cfg(feature = "legacy-cozo-graph")]
    fn load_latest_om_record_for_thread(
        &self,
        thread_id: &str,
    ) -> Result<Option<OmRecord>, StoreError> {
        let mut records = self
            .store
            .fetch_rows("om_records")?
            .into_iter()
            .filter(|row| row.get("thread_id").and_then(Value::as_str) == Some(thread_id))
            .map(om_record_from_value)
            .collect::<Result<Vec<_>, _>>()?;
        records.sort_by(|left, right| {
            right
                .updated_at
                .cmp(&left.updated_at)
                .then_with(|| right.created_at.cmp(&left.created_at))
        });
        Ok(records.into_iter().next())
    }

    fn list_candidate_prototype_inputs(
        &self,
        document_ids: &[String],
    ) -> Result<Vec<SemanticCandidatePrototypeInput>, StoreError> {
        if document_ids.is_empty() {
            return Ok(Vec::new());
        }

        let graph = self.phase2_graph_view(false)?;
        let leaf_chunks = self.semantic_leaf_chunks_for_documents(document_ids)?;
        let leaf_context = phase2_leaf_context_map(&leaf_chunks);
        let document_scopes = phase2_document_scope_from_leaf_chunks(&leaf_chunks);
        let messages = self.semantic_thread_message_map()?;
        let allowed_documents = document_ids.iter().cloned().collect::<HashSet<_>>();

        let mut entity_ids = BTreeSet::<String>::new();
        let mut event_ids = BTreeSet::<String>::new();
        for leaf in &leaf_chunks {
            let leaf_id = phase2_leaf_vertex_id(&leaf.span_id);
            for edge in graph
                .outgoing_any(&leaf_id)
                .chain(graph.incoming_any(&leaf_id))
            {
                let neighbor_id = if edge.source_id == leaf_id {
                    edge.target_id.as_str()
                } else {
                    edge.source_id.as_str()
                };
                let Some(vertex) = graph.vertices.get(neighbor_id) else {
                    continue;
                };
                match vertex.kind.as_str() {
                    "entity" => {
                        entity_ids.insert(vertex.id.clone());
                    }
                    "event" => {
                        event_ids.insert(vertex.id.clone());
                    }
                    _ => {}
                }
            }
        }

        let mut inputs = Vec::new();
        let mut seen = BTreeSet::new();
        for entity_id in entity_ids {
            if let Some(input) =
                phase2_entity_prototype_input(&graph, &leaf_context, &document_scopes, &entity_id)
            {
                if seen.insert(input.node_id.clone()) {
                    inputs.push(input);
                }
            }
        }
        for event_id in event_ids {
            if let Some(input) =
                phase2_event_prototype_input(&graph, &leaf_context, &document_scopes, &event_id)
            {
                if seen.insert(input.node_id.clone()) {
                    inputs.push(input);
                }
            }
        }
        for vertex in graph.vertices.values() {
            if !matches!(vertex.kind.as_str(), "turn" | "task" | "state") {
                continue;
            }
            if !vertex
                .document_id
                .as_ref()
                .map(|document_id| allowed_documents.contains(document_id))
                .unwrap_or(false)
            {
                continue;
            }
            let input = match vertex.kind.as_str() {
                "turn" => phase2_turn_prototype_input(vertex, &messages, &document_scopes),
                "task" => phase2_task_prototype_input(vertex, &document_scopes),
                "state" => phase2_state_prototype_input(vertex, &document_scopes),
                _ => None,
            };
            if let Some(input) = input {
                if seen.insert(input.node_id.clone()) {
                    inputs.push(input);
                }
            }
        }
        inputs.sort_by(|left, right| {
            (&left.node_kind, &left.node_id).cmp(&(&right.node_kind, &right.node_id))
        });
        Ok(inputs)
    }

    fn list_nli_judgment_inputs(
        &self,
        document_ids: &[String],
        node_ids: &[String],
    ) -> Result<Vec<SemanticNliJudgmentInput>, StoreError> {
        if document_ids.is_empty() && node_ids.is_empty() {
            return Ok(Vec::new());
        }

        let keep_docs = document_ids.iter().cloned().collect::<HashSet<_>>();
        let keep_nodes = node_ids.iter().cloned().collect::<HashSet<_>>();
        let graph = self.phase2_graph_view(true)?;
        let rows = self.candidate_edge_rows()?;

        let mut relevant = rows
            .into_iter()
            .filter_map(|row| {
                let source_id = row.get("source_id").and_then(Value::as_str)?.to_owned();
                let target_id = row.get("target_id").and_then(Value::as_str)?.to_owned();
                let edge_type = row.get("edge_type").and_then(Value::as_str)?.to_owned();
                if !matches!(
                    edge_type.as_str(),
                    "candidate_corefers_with" | "candidate_same_event_as" | "about" | "relevant_to"
                ) {
                    return None;
                }

                let attributes = row.get("attributes").cloned().unwrap_or(Value::Null);
                if !phase2_candidate_row_is_active(&attributes) {
                    return None;
                }

                let document_id = row
                    .get("document_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
                    .or_else(|| {
                        attributes
                            .get("documentId")
                            .and_then(Value::as_str)
                            .map(str::to_owned)
                    });
                let touched = document_id
                    .as_ref()
                    .map(|value| keep_docs.contains(value))
                    .unwrap_or(false)
                    || keep_nodes.contains(&source_id)
                    || keep_nodes.contains(&target_id);
                if !touched {
                    return None;
                }

                Some(Phase2CandidateEdgeRecord {
                    source_id,
                    target_id,
                    edge_type,
                    document_id,
                    base_score: phase2_candidate_row_base_score(
                        row.get("data"),
                        row.get("attributes"),
                    ),
                })
            })
            .collect::<Vec<_>>();

        relevant.sort_by(|left, right| {
            right
                .base_score
                .partial_cmp(&left.base_score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    (
                        left.edge_type.as_str(),
                        left.source_id.as_str(),
                        left.target_id.as_str(),
                    )
                        .cmp(&(
                            right.edge_type.as_str(),
                            right.source_id.as_str(),
                            right.target_id.as_str(),
                        ))
                })
        });
        let mut seen_groups = HashSet::<String>::new();
        relevant.retain(|record| {
            if matches!(
                record.edge_type.as_str(),
                "candidate_corefers_with" | "candidate_same_event_as"
            ) {
                seen_groups.insert(phase2_nli_group_id(record))
            } else {
                true
            }
        });

        let mut relevant_documents = keep_docs.clone();
        for record in &relevant {
            if let Some(document_id) = record.document_id.as_ref() {
                relevant_documents.insert(document_id.clone());
            }
            if let Some(document_id) = graph
                .vertices
                .get(&record.source_id)
                .and_then(|vertex| vertex.document_id.clone())
            {
                relevant_documents.insert(document_id);
            }
            if let Some(document_id) = graph
                .vertices
                .get(&record.target_id)
                .and_then(|vertex| vertex.document_id.clone())
            {
                relevant_documents.insert(document_id);
            }
        }

        let relevant_document_ids = relevant_documents.into_iter().collect::<Vec<_>>();
        let leaf_chunks = self.semantic_leaf_chunks_for_documents(&relevant_document_ids)?;
        let leaf_context = phase2_leaf_context_map(&leaf_chunks);
        let document_scopes = phase2_document_scope_from_leaf_chunks(&leaf_chunks);
        let document_support = phase2_document_support_from_leaf_chunks(&leaf_chunks);
        let messages = self.semantic_thread_message_map()?;
        let mut profile_cache = HashMap::<String, SemanticCandidatePrototypeInput>::new();
        let mut inputs = Vec::new();
        let mut seen_judgment_ids = HashSet::<String>::new();

        for record in relevant {
            let Some(source_profile) = phase2_nli_profile_for_vertex(
                &graph,
                &leaf_context,
                &document_scopes,
                &document_support,
                &messages,
                &record.source_id,
                &mut profile_cache,
            ) else {
                continue;
            };
            let Some(target_profile) = phase2_nli_profile_for_vertex(
                &graph,
                &leaf_context,
                &document_scopes,
                &document_support,
                &messages,
                &record.target_id,
                &mut profile_cache,
            ) else {
                continue;
            };
            for input in
                phase2_nli_inputs_for_edge(&record, &source_profile.text, &target_profile.text)
            {
                if !seen_judgment_ids.insert(input.judgment_id.clone()) {
                    continue;
                }
                inputs.push(input);
                if inputs.len() >= PHASE2_NLI_MAX_INPUTS {
                    return Ok(inputs);
                }
            }
        }

        let mut evidence_source_ids = graph
            .vertices
            .values()
            .filter(|vertex| matches!(vertex.kind.as_str(), "task" | "state"))
            .filter(|vertex| {
                keep_nodes.contains(&vertex.id)
                    || vertex
                        .document_id
                        .as_ref()
                        .map(|document_id| keep_docs.contains(document_id))
                        .unwrap_or(false)
            })
            .map(|vertex| vertex.id.clone())
            .collect::<Vec<_>>();
        evidence_source_ids.sort();

        for source_id in evidence_source_ids {
            let Some(source_vertex) = graph.vertices.get(&source_id) else {
                continue;
            };
            let Some(source_profile) = phase2_nli_profile_for_vertex(
                &graph,
                &leaf_context,
                &document_scopes,
                &document_support,
                &messages,
                &source_id,
                &mut profile_cache,
            ) else {
                continue;
            };

            let mut evidence_target_ids = Vec::new();
            let mut seen_targets = BTreeSet::<String>::new();

            for edge in graph.outgoing_any(&source_id) {
                if !matches!(edge.edge_type.as_str(), "observed_in" | "depends_on") {
                    continue;
                }
                let Some(target_vertex) = graph.vertices.get(&edge.target_id) else {
                    continue;
                };
                if target_vertex.kind != "turn" {
                    continue;
                }
                if seen_targets.insert(edge.target_id.clone()) {
                    evidence_target_ids.push(edge.target_id.clone());
                }
            }

            if let Some(document_id) = source_vertex.document_id.as_deref() {
                let mut leaf_candidates = leaf_context
                    .iter()
                    .filter(|(_, context)| context.document_id == document_id)
                    .map(|(leaf_id, context)| {
                        (
                            phase2_text_overlap_score(&source_profile.text, &context.text),
                            leaf_id.clone(),
                        )
                    })
                    .collect::<Vec<_>>();
                leaf_candidates
                    .sort_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));

                let mut added_leafs = 0usize;
                for (score, leaf_id) in leaf_candidates.iter().filter(|(score, _)| *score > 0) {
                    if added_leafs >= PHASE2_NLI_MAX_LEAF_EVIDENCE_PER_SOURCE {
                        break;
                    }
                    let _ = score;
                    if seen_targets.insert(leaf_id.clone()) {
                        evidence_target_ids.push(leaf_id.clone());
                        added_leafs += 1;
                    }
                }
                if added_leafs == 0 {
                    if let Some((_, leaf_id)) = leaf_candidates.first() {
                        if seen_targets.insert(leaf_id.clone()) {
                            evidence_target_ids.push(leaf_id.clone());
                        }
                    }
                }
            }

            evidence_target_ids.truncate(PHASE2_NLI_MAX_EVIDENCE_TARGETS);
            for target_id in evidence_target_ids {
                let Some(target_profile) = phase2_nli_profile_for_vertex(
                    &graph,
                    &leaf_context,
                    &document_scopes,
                    &document_support,
                    &messages,
                    &target_id,
                    &mut profile_cache,
                ) else {
                    continue;
                };
                for input in phase2_nli_inputs_for_evidence_edge(
                    &source_id,
                    &source_profile.text,
                    &target_id,
                    &target_profile.text,
                ) {
                    if !seen_judgment_ids.insert(input.judgment_id.clone()) {
                        continue;
                    }
                    inputs.push(input);
                    if inputs.len() >= PHASE2_NLI_MAX_INPUTS {
                        return Ok(inputs);
                    }
                }
            }
        }

        Ok(inputs)
    }

    fn run_embedder_truth_review(
        &self,
        request: SemanticTruthReviewRequest,
    ) -> Result<SemanticTruthReviewResponse, StoreError> {
        let total_started = Instant::now();
        let graph = self.phase2_graph_view(true)?;
        let rows = self.candidate_edge_rows()?;
        let keep_docs = request
            .document_ids
            .iter()
            .map(String::as_str)
            .collect::<HashSet<_>>();
        let keep_nodes = request
            .node_ids
            .iter()
            .map(String::as_str)
            .collect::<HashSet<_>>();
        let scoped = !keep_docs.is_empty() || !keep_nodes.is_empty();
        let preview_limit = request.edge_preview_limit.unwrap_or(16).min(64);
        let derive_started = Instant::now();
        let mut node_ids = BTreeSet::<String>::new();
        let mut candidates = Vec::<SemanticTruthReviewCandidateRow>::new();

        for row in rows {
            let Some(source_id) = row.get("source_id").and_then(Value::as_str) else {
                continue;
            };
            let Some(target_id) = row.get("target_id").and_then(Value::as_str) else {
                continue;
            };
            let edge_type = row
                .get("edge_type")
                .and_then(Value::as_str)
                .unwrap_or("candidate");
            let attributes = row.get("attributes").unwrap_or(&Value::Null);
            if !phase2_candidate_row_is_active(attributes) {
                continue;
            }

            let row_document_id = row
                .get("document_id")
                .and_then(Value::as_str)
                .or_else(|| attributes.get("documentId").and_then(Value::as_str));
            let source_document_id = graph
                .vertices
                .get(source_id)
                .and_then(|vertex| vertex.document_id.as_deref());
            let target_document_id = graph
                .vertices
                .get(target_id)
                .and_then(|vertex| vertex.document_id.as_deref());
            let touched = !scoped
                || row_document_id
                    .map(|document_id| keep_docs.contains(document_id))
                    .unwrap_or(false)
                || source_document_id
                    .map(|document_id| keep_docs.contains(document_id))
                    .unwrap_or(false)
                || target_document_id
                    .map(|document_id| keep_docs.contains(document_id))
                    .unwrap_or(false)
                || keep_nodes.contains(source_id)
                || keep_nodes.contains(target_id);
            if !touched {
                continue;
            }

            let data = row.get("data");
            let score = phase2_candidate_row_base_score(data, Some(attributes));
            let edge_id = row
                .get("id")
                .or_else(|| row.get("edge_id"))
                .and_then(Value::as_str)
                .map(str::to_owned)
                .unwrap_or_else(|| format!("{source_id}->{target_id}:{edge_type}"));
            let status = phase2_candidate_graph_status(attributes)
                .or_else(|| row.get("status").and_then(Value::as_str))
                .unwrap_or("candidate")
                .to_owned();
            node_ids.insert(source_id.to_owned());
            node_ids.insert(target_id.to_owned());
            candidates.push(SemanticTruthReviewCandidateRow {
                edge_id,
                source_node_id: source_id.to_owned(),
                target_node_id: target_id.to_owned(),
                family: edge_type.to_owned(),
                status,
                score,
                nli_support_millis: phase2_optional_score_millis(phase2_json_path_f64(
                    data,
                    &["nli", "aggregated", "entailment"],
                )),
                nli_contradiction_millis: phase2_optional_score_millis(phase2_json_path_f64(
                    data,
                    &["nli", "aggregated", "contradiction"],
                )),
            });
        }

        candidates.sort_by(|left, right| {
            right
                .score
                .partial_cmp(&left.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    (
                        left.family.as_str(),
                        left.source_node_id.as_str(),
                        left.target_node_id.as_str(),
                    )
                        .cmp(&(
                            right.family.as_str(),
                            right.source_node_id.as_str(),
                            right.target_node_id.as_str(),
                        ))
                })
        });

        let preview = candidates
            .iter()
            .take(preview_limit)
            .map(|row| SemanticTruthReviewPreview {
                edge_id: row.edge_id.clone(),
                family: row.family.clone(),
                status: row.status.clone(),
                score_millis: phase2_optional_score_millis(Some(row.score)),
                source_node_id: row.source_node_id.clone(),
                target_node_id: row.target_node_id.clone(),
                nli_support_millis: row.nli_support_millis,
                nli_contradiction_millis: row.nli_contradiction_millis,
            })
            .collect::<Vec<_>>();
        let derive_ms = derive_started.elapsed().as_millis();
        let scope_key = request
            .scope_hint
            .as_ref()
            .and_then(|hint| hint.scope_id.as_deref())
            .filter(|value| !value.is_empty())
            .unwrap_or("global")
            .to_owned();
        let scope_label = request
            .scope_hint
            .as_ref()
            .and_then(|hint| hint.label.as_deref())
            .filter(|value| !value.is_empty())
            .unwrap_or(scope_key.as_str())
            .to_owned();
        let lane_mode = request
            .lane_mode
            .as_deref()
            .filter(|value| !value.is_empty())
            .unwrap_or("truth-review")
            .to_owned();
        let model_id = request
            .model
            .model_id
            .as_deref()
            .filter(|value| !value.is_empty())
            .unwrap_or(SEMANTIC_MODEL_ID)
            .to_owned();
        let model_label = request
            .model
            .model_label
            .as_deref()
            .filter(|value| !value.is_empty())
            .unwrap_or(model_id.as_str())
            .to_owned();
        let embedding_profile = request
            .model
            .embedding_profile
            .as_deref()
            .filter(|value| !value.is_empty())
            .unwrap_or("768")
            .to_owned();
        let execution_provider = request
            .model
            .execution_provider
            .as_deref()
            .filter(|value| !value.is_empty())
            .unwrap_or("runtime")
            .to_owned();
        let dimension = request.model.dimension.unwrap_or(SEMANTIC_VECTOR_DIM);
        let candidate_edge_count = candidates.len();
        let candidate_node_count = node_ids.len();

        Ok(SemanticTruthReviewResponse {
            contract_version: 1,
            candidate_only: true,
            lane_mode,
            model_id,
            model_label,
            embedding_profile,
            dimension,
            execution_provider,
            cache: SemanticTruthReviewCacheStats {
                hits: candidate_edge_count,
                misses: 0,
            },
            timings: SemanticTruthReviewTimings {
                derive_ms,
                total_ms: total_started.elapsed().as_millis(),
            },
            output: SemanticTruthReviewOutput {
                scope_key,
                summary: SemanticTruthReviewSummary {
                    node_count: candidate_node_count,
                    edge_count: candidate_edge_count,
                },
                candidate_node_count,
                candidate_edge_count,
                candidate_graph_vertex_count: graph.vertices.len(),
                candidate_graph_edge_count: candidate_edge_count,
                candidate_graph_scope: scope_label,
                committed_topology_writes: 0,
                preview,
            },
            sidecar: json!({
                "source": "phoenix-runtime",
                "cachePolicy": request.cache_policy.unwrap_or_else(|| "persistent".to_owned()),
                "uiModelId": request.model.ui_model_id,
                "candidateRows": candidate_edge_count,
                "candidateOnly": true,
                "committedTopologyWrites": 0,
            }),
        })
    }

    pub(crate) fn semantic_leaf_chunks_for_documents(
        &self,
        document_ids: &[String],
    ) -> Result<Vec<SemanticLeafChunk>, StoreError> {
        if self.native_graph_enabled() {
            self.native_semantic_leaf_chunks_for_documents(document_ids)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store
                    .list_leaf_chunks_for_documents(document_ids)
                    .map(|chunks| {
                        chunks
                            .into_iter()
                            .map(|chunk| SemanticLeafChunk {
                                span_id: chunk.span_id,
                                document_id: chunk.document_id,
                                text: chunk.text,
                                narrative_id: chunk.narrative_id,
                                folder_id: chunk.folder_id,
                            })
                            .collect()
                    })
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                let _ = document_ids;
                Err(self.legacy_graph_disabled("legacy semantic leaf chunks"))
            }
        }
    }

    fn native_semantic_leaf_chunks_for_documents(
        &self,
        document_ids: &[String],
    ) -> Result<Vec<SemanticLeafChunk>, StoreError> {
        if document_ids.is_empty() {
            return Ok(Vec::new());
        }
        let allowed = document_ids.iter().cloned().collect::<HashSet<_>>();
        let mut chunks = self
            .native_note_rows_to_indexed_spans()?
            .into_iter()
            .filter_map(|span| {
                let document_id = span.document_id.as_ref()?.0.clone();
                if !allowed.contains(&document_id) {
                    return None;
                }
                let text = span
                    .fields
                    .iter()
                    .map(|field| field.text.trim())
                    .filter(|text| !text.is_empty())
                    .collect::<Vec<_>>()
                    .join(" ");
                if text.is_empty() {
                    return None;
                }
                Some(SemanticLeafChunk {
                    span_id: span.span_id,
                    document_id,
                    text,
                    narrative_id: span.scope.narrative_id,
                    folder_id: span.scope.folder_id,
                })
            })
            .collect::<Vec<_>>();
        chunks.sort_by(|left, right| {
            left.document_id
                .cmp(&right.document_id)
                .then_with(|| left.span_id.cmp(&right.span_id))
        });
        Ok(chunks)
    }

    fn semantic_thread_message_map(&self) -> Result<HashMap<String, ThreadMessage>, StoreError> {
        if self.native_graph_enabled() {
            return Ok(HashMap::new());
        }
        phase2_thread_message_map(self.fetch_relation_rows("thread_messages")?)
    }

    fn semantic_document_scope_map(
        &self,
        document_ids: &[String],
    ) -> Result<HashMap<String, ScopeKey>, StoreError> {
        let leaf_chunks = self.semantic_leaf_chunks_for_documents(document_ids)?;
        Ok(phase2_document_scope_from_leaf_chunks(&leaf_chunks))
    }

    fn native_semantic_document_vector_map(
        &self,
        document_ids: &[String],
    ) -> Result<HashMap<String, StoredSemanticDocumentVector>, StoreError> {
        let allowed = document_ids.iter().cloned().collect::<HashSet<_>>();
        let mut vectors = HashMap::new();
        for row in self.fetch_relation_rows("semantic_documents")? {
            let Some(document_id) = row.get("document_id").and_then(Value::as_str) else {
                continue;
            };
            if !allowed.contains(document_id) {
                continue;
            }
            vectors.insert(
                document_id.to_owned(),
                StoredSemanticDocumentVector {
                    values: json_f32_vector(row.get("vec")),
                    evidence_refs: json_string_vec(row.get("evidence_refs")),
                },
            );
        }
        Ok(vectors)
    }

    fn native_semantic_node_vector_map(
        &self,
        node_ids: &[String],
    ) -> Result<HashMap<String, StoredSemanticNodeVector>, StoreError> {
        let allowed = node_ids.iter().cloned().collect::<HashSet<_>>();
        let mut vectors = HashMap::new();
        for row in self.fetch_relation_rows("semantic_node_prototypes")? {
            let Some(node_id) = row.get("node_id").and_then(Value::as_str) else {
                continue;
            };
            if !allowed.contains(node_id) {
                continue;
            }
            vectors.insert(
                node_id.to_owned(),
                StoredSemanticNodeVector {
                    node_id: node_id.to_owned(),
                    node_kind: row
                        .get("node_kind")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_owned(),
                    document_id: row
                        .get("document_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    narrative_id: row
                        .get("narrative_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    folder_id: row
                        .get("folder_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    values: json_f32_vector(row.get("vec")),
                    evidence_refs: json_string_vec(row.get("evidence_refs")),
                },
            );
        }
        Ok(vectors)
    }

    fn native_semantic_document_neighbors(
        &self,
        values: &[f32],
        _scope: &ScopeKey,
        limit: usize,
        max_candidates: usize,
    ) -> Result<Vec<SemanticDocumentNeighbor>, StoreError> {
        let mut neighbors = self
            .fetch_relation_rows("semantic_documents")?
            .into_iter()
            .filter_map(|row| {
                let document_id = row.get("document_id").and_then(Value::as_str)?.to_owned();
                let candidate_values = json_f32_vector(row.get("vec"));
                let distance = cosine_distance(values, &candidate_values)?;
                Some(SemanticDocumentNeighbor {
                    document_id,
                    distance,
                    leaf_count: row
                        .get("leaf_count")
                        .and_then(Value::as_i64)
                        .unwrap_or_default()
                        .max(0) as usize,
                    evidence_refs: json_string_vec(row.get("evidence_refs")),
                })
            })
            .collect::<Vec<_>>();
        neighbors.sort_by(|left, right| {
            left.distance
                .partial_cmp(&right.distance)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.document_id.cmp(&right.document_id))
        });
        neighbors.truncate(limit.min(max_candidates));
        Ok(neighbors)
    }

    fn native_semantic_node_neighbors(
        &self,
        values: &[f32],
        scope: &ScopeKey,
        node_kind: &str,
        exclude_node_id: Option<&str>,
        limit: usize,
        max_candidates: usize,
    ) -> Result<Vec<SemanticNodeNeighbor>, StoreError> {
        let mut neighbors = self
            .fetch_relation_rows("semantic_node_prototypes")?
            .into_iter()
            .filter(|row| row_matches_scope(row, scope))
            .filter_map(|row| {
                let node_id = row.get("node_id").and_then(Value::as_str)?.to_owned();
                if exclude_node_id == Some(node_id.as_str()) {
                    return None;
                }
                let row_kind = row.get("node_kind").and_then(Value::as_str)?;
                if row_kind != node_kind {
                    return None;
                }
                let candidate_values = json_f32_vector(row.get("vec"));
                let distance = cosine_distance(values, &candidate_values)?;
                Some(SemanticNodeNeighbor {
                    node_id,
                    node_kind: row_kind.to_owned(),
                    distance,
                    document_id: row
                        .get("document_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    narrative_id: row
                        .get("narrative_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    folder_id: row
                        .get("folder_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    evidence_refs: json_string_vec(row.get("evidence_refs")),
                })
            })
            .collect::<Vec<_>>();
        neighbors.sort_by(|left, right| {
            left.distance
                .partial_cmp(&right.distance)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.node_id.cmp(&right.node_id))
        });
        neighbors.truncate(limit.min(max_candidates));
        Ok(neighbors)
    }

    fn refresh_candidate_graph_edges(
        &self,
        document_ids: &[String],
        node_ids: &[String],
    ) -> Result<usize, StoreError> {
        let graph = self.phase2_graph_view(false)?;
        let active_vertices = graph.vertices.keys().cloned().collect::<HashSet<_>>();
        let doc_scope = self.semantic_document_scope_map(document_ids)?;
        let document_vectors = if self.native_graph_enabled() {
            self.native_semantic_document_vector_map(document_ids)?
        } else {
            phase2_document_vector_map(
                self.fetch_relation_rows("semantic_documents")?,
                document_ids,
            )?
        };
        let node_vectors = if self.native_graph_enabled() {
            self.native_semantic_node_vector_map(node_ids)?
        } else {
            phase2_node_vector_map(
                self.fetch_relation_rows("semantic_node_prototypes")?,
                node_ids,
            )?
        };

        if !self.native_graph_enabled() {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.prune_candidate_graph_edges(document_ids, node_ids)?;
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("legacy candidate edge prune"));
            }
        }

        let mut candidate_rows = Vec::new();
        let mut edge_keys = BTreeSet::new();

        for document_id in document_ids {
            let Some(source_vector) = document_vectors.get(document_id) else {
                continue;
            };
            let Some(scope) = doc_scope.get(document_id).cloned() else {
                continue;
            };
            let neighbors = if self.native_graph_enabled() {
                self.native_semantic_document_neighbors(&source_vector.values, &scope, 4, 16)?
            } else {
                #[cfg(feature = "legacy-cozo-graph")]
                {
                    self.store
                        .query_semantic_documents(&source_vector.values, &scope, 4, 16)?
                }
                #[cfg(not(feature = "legacy-cozo-graph"))]
                {
                    return Err(self.legacy_graph_disabled("legacy semantic document query"));
                }
            };
            for neighbor in neighbors {
                if neighbor.document_id == *document_id {
                    continue;
                }
                if !active_vertices.contains(&phase1_document_vertex_id(&neighbor.document_id)) {
                    continue;
                }
                let score = phase2_similarity_score(neighbor.distance);
                if score < PHASE2_DOC_SIMILAR_TO_THRESHOLD {
                    continue;
                }
                if phase2_graph_has_edge(
                    &graph,
                    &phase1_document_vertex_id(document_id),
                    &phase1_document_vertex_id(&neighbor.document_id),
                    "similar_to",
                ) {
                    continue;
                }
                phase2_push_candidate_edge(
                    &mut edge_keys,
                    &mut candidate_rows,
                    phase2_candidate_edge_row(
                        &phase1_document_vertex_id(document_id),
                        &phase1_document_vertex_id(&neighbor.document_id),
                        "similar_to",
                        Some(document_id.as_str()),
                        scope.narrative_id.as_deref(),
                        score,
                        PHASE2_DOC_SIMILAR_TO_THRESHOLD,
                        {
                            let mut attributes = Map::new();
                            attributes.insert("sourceKind".to_owned(), json!("document"));
                            attributes.insert("targetKind".to_owned(), json!("document"));
                            attributes.insert("layer".to_owned(), json!("candidate"));
                            attributes
                        },
                        phase2_merge_evidence_refs(
                            &source_vector.evidence_refs,
                            &neighbor.evidence_refs,
                        ),
                    ),
                );
            }
        }

        for node_id in node_ids {
            let Some(source_vector) = node_vectors.get(node_id) else {
                continue;
            };
            if !active_vertices.contains(&source_vector.node_id) {
                continue;
            }
            let scope = ScopeKey {
                world_id: None,
                narrative_id: source_vector.narrative_id.clone(),
                folder_id: source_vector.folder_id.clone(),
                folder_path: None,
            };
            match source_vector.node_kind.as_str() {
                "entity" => {
                    let neighbors = if self.native_graph_enabled() {
                        self.native_semantic_node_neighbors(
                            &source_vector.values,
                            &scope,
                            "entity",
                            Some(&source_vector.node_id),
                            4,
                            16,
                        )?
                    } else {
                        #[cfg(feature = "legacy-cozo-graph")]
                        {
                            self.store.query_semantic_node_neighbors(
                                &source_vector.values,
                                &scope,
                                "entity",
                                Some(&source_vector.node_id),
                                4,
                                16,
                            )?
                        }
                        #[cfg(not(feature = "legacy-cozo-graph"))]
                        {
                            return Err(self.legacy_graph_disabled("legacy semantic node query"));
                        }
                    };
                    for neighbor in neighbors {
                        if !active_vertices.contains(&neighbor.node_id) {
                            continue;
                        }
                        if !phase2_entity_candidate_is_coherent(
                            &graph,
                            &source_vector.node_id,
                            &neighbor.node_id,
                        ) {
                            continue;
                        }
                        let score = phase2_similarity_score(neighbor.distance);
                        if score < PHASE2_ENTITY_COREF_THRESHOLD {
                            continue;
                        }
                        if phase2_graph_has_symmetric_edge(
                            &graph,
                            &source_vector.node_id,
                            &neighbor.node_id,
                            "candidate_corefers_with",
                        ) {
                            continue;
                        }
                        phase2_push_candidate_edge(
                            &mut edge_keys,
                            &mut candidate_rows,
                            phase2_candidate_edge_row(
                                &source_vector.node_id,
                                &neighbor.node_id,
                                "candidate_corefers_with",
                                source_vector.document_id.as_deref(),
                                source_vector.narrative_id.as_deref(),
                                score,
                                PHASE2_ENTITY_COREF_THRESHOLD,
                                {
                                    let mut attributes = Map::new();
                                    attributes.insert("sourceKind".to_owned(), json!("entity"));
                                    attributes.insert("targetKind".to_owned(), json!("entity"));
                                    attributes
                                },
                                phase2_merge_evidence_refs(
                                    &source_vector.evidence_refs,
                                    &neighbor.evidence_refs,
                                ),
                            ),
                        );
                    }
                }
                "event" => {
                    let neighbors = if self.native_graph_enabled() {
                        self.native_semantic_node_neighbors(
                            &source_vector.values,
                            &scope,
                            "event",
                            Some(&source_vector.node_id),
                            4,
                            16,
                        )?
                    } else {
                        #[cfg(feature = "legacy-cozo-graph")]
                        {
                            self.store.query_semantic_node_neighbors(
                                &source_vector.values,
                                &scope,
                                "event",
                                Some(&source_vector.node_id),
                                4,
                                16,
                            )?
                        }
                        #[cfg(not(feature = "legacy-cozo-graph"))]
                        {
                            return Err(self.legacy_graph_disabled("legacy semantic node query"));
                        }
                    };
                    for neighbor in neighbors {
                        if !active_vertices.contains(&neighbor.node_id) {
                            continue;
                        }
                        let score = phase2_similarity_score(neighbor.distance);
                        if score < PHASE2_EVENT_MATCH_THRESHOLD {
                            continue;
                        }
                        if phase2_graph_has_edge(
                            &graph,
                            &source_vector.node_id,
                            &neighbor.node_id,
                            "candidate_same_event_as",
                        ) {
                            continue;
                        }
                        phase2_push_candidate_edge(
                            &mut edge_keys,
                            &mut candidate_rows,
                            phase2_candidate_edge_row(
                                &source_vector.node_id,
                                &neighbor.node_id,
                                "candidate_same_event_as",
                                source_vector.document_id.as_deref(),
                                source_vector.narrative_id.as_deref(),
                                score,
                                PHASE2_EVENT_MATCH_THRESHOLD,
                                {
                                    let mut attributes = Map::new();
                                    attributes.insert("sourceKind".to_owned(), json!("event"));
                                    attributes.insert("targetKind".to_owned(), json!("event"));
                                    attributes
                                },
                                phase2_merge_evidence_refs(
                                    &source_vector.evidence_refs,
                                    &neighbor.evidence_refs,
                                ),
                            ),
                        );
                    }
                }
                "turn" | "task" | "state" => {
                    let document_neighbors = if self.native_graph_enabled() {
                        self.native_semantic_document_neighbors(
                            &source_vector.values,
                            &scope,
                            3,
                            12,
                        )?
                    } else {
                        #[cfg(feature = "legacy-cozo-graph")]
                        {
                            self.store.query_semantic_documents(
                                &source_vector.values,
                                &scope,
                                3,
                                12,
                            )?
                        }
                        #[cfg(not(feature = "legacy-cozo-graph"))]
                        {
                            return Err(
                                self.legacy_graph_disabled("legacy semantic document query")
                            );
                        }
                    };
                    for neighbor in document_neighbors {
                        if !active_vertices
                            .contains(&phase1_document_vertex_id(&neighbor.document_id))
                        {
                            continue;
                        }
                        let score = phase2_similarity_score(neighbor.distance);
                        if score < PHASE2_ABOUT_THRESHOLD {
                            continue;
                        }
                        if phase2_graph_has_edge(
                            &graph,
                            &source_vector.node_id,
                            &phase1_document_vertex_id(&neighbor.document_id),
                            "about",
                        ) {
                            continue;
                        }
                        phase2_push_candidate_edge(
                            &mut edge_keys,
                            &mut candidate_rows,
                            phase2_candidate_edge_row(
                                &source_vector.node_id,
                                &phase1_document_vertex_id(&neighbor.document_id),
                                "about",
                                source_vector.document_id.as_deref(),
                                source_vector.narrative_id.as_deref(),
                                score,
                                PHASE2_ABOUT_THRESHOLD,
                                {
                                    let mut attributes = Map::new();
                                    attributes.insert(
                                        "sourceKind".to_owned(),
                                        json!(source_vector.node_kind),
                                    );
                                    attributes.insert("targetKind".to_owned(), json!("document"));
                                    attributes
                                },
                                phase2_merge_evidence_refs(
                                    &source_vector.evidence_refs,
                                    &neighbor.evidence_refs,
                                ),
                            ),
                        );
                    }
                    for target_kind in ["entity", "event"] {
                        let neighbors = if self.native_graph_enabled() {
                            self.native_semantic_node_neighbors(
                                &source_vector.values,
                                &scope,
                                target_kind,
                                None,
                                3,
                                12,
                            )?
                        } else {
                            #[cfg(feature = "legacy-cozo-graph")]
                            {
                                self.store.query_semantic_node_neighbors(
                                    &source_vector.values,
                                    &scope,
                                    target_kind,
                                    None,
                                    3,
                                    12,
                                )?
                            }
                            #[cfg(not(feature = "legacy-cozo-graph"))]
                            {
                                return Err(
                                    self.legacy_graph_disabled("legacy semantic node query")
                                );
                            }
                        };
                        for neighbor in neighbors {
                            if !active_vertices.contains(&neighbor.node_id) {
                                continue;
                            }
                            let score = phase2_similarity_score(neighbor.distance);
                            if score < PHASE2_RELEVANT_TO_THRESHOLD {
                                continue;
                            }
                            if phase2_graph_has_edge(
                                &graph,
                                &source_vector.node_id,
                                &neighbor.node_id,
                                "relevant_to",
                            ) {
                                continue;
                            }
                            phase2_push_candidate_edge(
                                &mut edge_keys,
                                &mut candidate_rows,
                                phase2_candidate_edge_row(
                                    &source_vector.node_id,
                                    &neighbor.node_id,
                                    "relevant_to",
                                    source_vector.document_id.as_deref(),
                                    source_vector.narrative_id.as_deref(),
                                    score,
                                    PHASE2_RELEVANT_TO_THRESHOLD,
                                    {
                                        let mut attributes = Map::new();
                                        attributes.insert(
                                            "sourceKind".to_owned(),
                                            json!(source_vector.node_kind),
                                        );
                                        attributes.insert(
                                            "targetKind".to_owned(),
                                            json!(neighbor.node_kind),
                                        );
                                        attributes
                                    },
                                    phase2_merge_evidence_refs(
                                        &source_vector.evidence_refs,
                                        &neighbor.evidence_refs,
                                    ),
                                ),
                            );
                        }
                    }
                }
                _ => {}
            }
        }

        if self.native_graph_enabled() {
            let touched_scope_keys = document_ids
                .iter()
                .map(|document_id| native_candidate_scope_key_for_document(document_id))
                .chain(
                    node_ids
                        .iter()
                        .map(|node_id| native_candidate_scope_key_for_node(node_id)),
                )
                .collect::<BTreeSet<_>>();
            let batches = native_candidate_batches_from_rows(candidate_rows, &touched_scope_keys);
            let inserted = batches.iter().map(|batch| batch.edges.len()).sum();
            self.persist_native_candidate_scope_batches(batches)?;
            Ok(inserted)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let inserted = candidate_rows.len();
                for row in candidate_rows {
                    self.store.put_row("graph_candidate_edges", row)?;
                }
                Ok(inserted)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy candidate edge persist"))
            }
        }
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn prune_candidate_graph_edges(
        &self,
        document_ids: &[String],
        node_ids: &[String],
    ) -> Result<(), StoreError> {
        if document_ids.is_empty() && node_ids.is_empty() {
            return Ok(());
        }
        let keep_docs = document_ids.iter().cloned().collect::<HashSet<_>>();
        let keep_nodes = node_ids.iter().cloned().collect::<HashSet<_>>();
        let rows = self.store.fetch_rows("graph_candidate_edges")?;
        let compact = self.store.fetch_compact_rows("graph_candidate_edges")?;
        let stale = rows
            .iter()
            .zip(compact)
            .filter_map(|(row, compact)| {
                let source_id = row
                    .get("source_id")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let target_id = row
                    .get("target_id")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let document_id = row
                    .get("document_id")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let target_document_id = target_id.strip_prefix("doc::").unwrap_or_default();
                (keep_nodes.contains(source_id)
                    || keep_nodes.contains(target_id)
                    || keep_docs.contains(document_id)
                    || keep_docs.contains(target_document_id))
                .then_some(compact)
            })
            .collect::<Vec<_>>();
        if !stale.is_empty() {
            self.store
                .delete_key_rows("graph_candidate_edges", &stale)?;
        }
        Ok(())
    }

    fn apply_nli_judgments(
        &self,
        model_id: &str,
        device: Option<&str>,
        rows: Vec<SemanticNliJudgmentResultRow>,
    ) -> Result<Value, StoreError> {
        let graph = self.phase2_graph_view(true)?;
        let mut aggregates =
            BTreeMap::<(String, String, String), Phase2NliJudgmentAggregate>::new();
        for row in rows {
            let key = (
                row.source_id.clone(),
                row.target_id.clone(),
                row.edge_type.clone(),
            );
            let aggregate = aggregates
                .entry(key)
                .or_insert_with(|| Phase2NliJudgmentAggregate {
                    group_id: row.group_id.clone(),
                    judgments: Vec::new(),
                });
            aggregate.judgments.push(row);
        }

        if aggregates.is_empty() {
            return Ok(json!({
                "judged": 0,
                "kept": 0,
                "rejected": 0,
                "byEdgeType": {},
                "modelId": model_id,
                "device": device,
                "diagnostics": [
                    {
                        "code": "PX_NLI_SKIP",
                        "message": "No NLI judgments were provided; candidate graph edges were left unchanged."
                    }
                ],
            }));
        }

        let existing_rows = self.candidate_edge_rows()?;
        let mut row_map = HashMap::<(String, String, String), Value>::new();
        for row in existing_rows {
            let Some(source_id) = row.get("source_id").and_then(Value::as_str) else {
                continue;
            };
            let Some(target_id) = row.get("target_id").and_then(Value::as_str) else {
                continue;
            };
            let Some(edge_type) = row.get("edge_type").and_then(Value::as_str) else {
                continue;
            };
            row_map.insert(
                (
                    source_id.to_owned(),
                    target_id.to_owned(),
                    edge_type.to_owned(),
                ),
                row,
            );
        }

        let mut kept = 0usize;
        let mut rejected = 0usize;
        let mut by_edge_type = BTreeMap::<String, Value>::new();
        let judged_at = now_ms();
        let mut touched_scope_keys = BTreeSet::<String>::new();

        for ((source_id, target_id, edge_type), aggregate) in aggregates {
            let Some(mut row) = row_map
                .remove(&(source_id.clone(), target_id.clone(), edge_type.clone()))
                .or_else(|| {
                    phase2_nli_candidate_edge_seed_row(&graph, &source_id, &target_id, &edge_type)
                })
            else {
                continue;
            };
            let decision = phase2_apply_nli_decision(
                &edge_type,
                phase2_candidate_row_base_score(row.get("data"), row.get("attributes")),
                &aggregate.judgments,
            );
            let attributes_snapshot = row
                .get("attributes")
                .cloned()
                .unwrap_or_else(|| Value::Object(Map::new()));
            let existing_data = row
                .get("data")
                .cloned()
                .filter(|value| value.is_object())
                .unwrap_or_else(|| Value::Object(Map::new()));
            let base_data = existing_data
                .get("base")
                .cloned()
                .or_else(|| (!existing_data.is_null()).then_some(existing_data.clone()))
                .unwrap_or_else(|| {
                    json!({
                        "score": phase2_candidate_row_base_score(None, Some(&attributes_snapshot)),
                        "resolver": attributes_snapshot
                            .get("graph")
                            .and_then(Value::as_object)
                            .and_then(|graph| graph.get("resolver"))
                            .and_then(Value::as_str)
                            .unwrap_or(PHASE2_EMBEDDING_RESOLVER),
                    })
                });

            let evidence_refs = phase2_merge_evidence_refs(
                &phase2_graph_evidence_refs(&attributes_snapshot),
                &phase2_nli_evidence_refs(&aggregate.judgments),
            );
            let mut attributes_object =
                attributes_snapshot.as_object().cloned().unwrap_or_default();

            attributes_object.insert("score".to_owned(), json!(decision.final_score));
            attributes_object.insert("nliScore".to_owned(), json!(decision.nli_score));
            attributes_object.insert(
                "graph".to_owned(),
                json!({
                    "layer": "candidate",
                    "status": if decision.accepted { "candidate" } else { "candidate_rejected" },
                    "resolver": PHASE2_NLI_RESOLVER,
                    "confidence": decision.final_score,
                    "evidence_refs": evidence_refs,
                }),
            );
            row["attributes"] = Value::Object(attributes_object);
            row["data"] = json!({
                "base": base_data,
                "nli": {
                    "modelId": model_id,
                    "device": device,
                    "judgedAt": judged_at,
                    "groupId": aggregate.group_id,
                    "accepted": decision.accepted,
                    "threshold": decision.threshold,
                    "aggregated": {
                        "entailment": decision.entailment,
                        "neutral": decision.neutral,
                        "contradiction": decision.contradiction,
                        "nliScore": decision.nli_score,
                        "finalScore": decision.final_score,
                    },
                    "judgments": aggregate.judgments.iter().map(|judgment| {
                        json!({
                            "judgmentId": judgment.judgment_id,
                            "direction": judgment.direction,
                            "premise": judgment.premise,
                            "hypothesis": judgment.hypothesis,
                            "entailment": judgment.entailment,
                            "neutral": judgment.neutral,
                            "contradiction": judgment.contradiction,
                            "predictedLabel": judgment.predicted_label,
                            "confidence": judgment.confidence,
                        })
                    }).collect::<Vec<_>>(),
                }
            });
            row["weight"] = json!(if decision.accepted {
                ((decision.final_score * 1000.0).round() as i64).max(1)
            } else {
                0
            });

            if let Some(scope_key) = native_candidate_scope_key_for_row(&row) {
                touched_scope_keys.insert(scope_key);
            }
            row_map.insert(
                (source_id.clone(), target_id.clone(), edge_type.clone()),
                row.clone(),
            );
            if !self.native_graph_enabled() {
                #[cfg(feature = "legacy-cozo-graph")]
                {
                    self.store.put_row("graph_candidate_edges", row)?;
                }
                #[cfg(not(feature = "legacy-cozo-graph"))]
                {
                    return Err(self.legacy_graph_disabled("legacy candidate NLI persist"));
                }
            }

            let counter = by_edge_type
                .entry(edge_type.clone())
                .or_insert_with(|| json!({ "kept": 0, "rejected": 0 }));
            if let Some(object) = counter.as_object_mut() {
                let key = if decision.accepted {
                    "kept"
                } else {
                    "rejected"
                };
                let current = object.get(key).and_then(Value::as_u64).unwrap_or(0);
                object.insert(key.to_owned(), json!(current + 1));
            }

            if decision.accepted {
                kept += 1;
            } else {
                rejected += 1;
            }
        }

        if self.native_graph_enabled() && !touched_scope_keys.is_empty() {
            let batches = native_candidate_batches_from_rows(
                row_map.into_values().collect::<Vec<_>>(),
                &touched_scope_keys,
            );
            self.persist_native_candidate_scope_batches(batches)?;
        }

        Ok(json!({
            "judged": kept + rejected,
            "kept": kept,
            "rejected": rejected,
            "byEdgeType": by_edge_type,
            "modelId": model_id,
            "device": device,
            "diagnostics": [
                {
                    "code": "PX_NLI_OK",
                    "message": format!(
                        "Applied local NLI judgments to {} candidate edges (kept {}, rejected {}).",
                        kept + rejected,
                        kept,
                        rejected
                    ),
                }
            ],
        }))
    }

    pub fn query(&self, request: QueryRequest) -> Result<QueryResult, StoreError> {
        self.query_view(QueryRequestView::from(&request))
    }

    pub fn query_view(&self, request: QueryRequestView<'_>) -> Result<QueryResult, StoreError> {
        let created_at = now_ms();
        self.put_relation_row(
            "phoenix_query_log",
            serde_json::json!({
                "id": format!("query-{}", created_at),
                "session_id": request.session_id.as_ref().map(|value| value.0.clone()),
                "query": request.query,
                "limit": request.limit,
                "request_json": serde_json::json!({
                    "sessionId": request.session_id.as_ref().map(|value| value.0.clone()),
                    "query": request.query,
                    "scope": request.scope.to_owned(),
                    "targets": request.targets,
                    "limit": request.limit,
                    "temporal": request.temporal,
                    "hasSemanticVector": request.semantic_query_vector.is_some(),
                    "includeCandidateGraph": request.include_candidate_graph,
                }),
                "created_at": created_at,
            }),
        )?;

        let graph_requested = request.targets.iter().any(|target| {
            matches!(
                target,
                phoenix_types::QueryTarget::Nodes
                    | phoenix_types::QueryTarget::Graph
                    | phoenix_types::QueryTarget::Semantic
            )
        });
        if graph_requested {
            let semantic_requested = request
                .targets
                .iter()
                .any(|target| matches!(target, phoenix_types::QueryTarget::Semantic));
            let requested_candidate_graph = request.include_candidate_graph;
            let mut owned_request = request.to_owned();
            if semantic_requested && !self.config.feature_flags.semantic {
                owned_request.semantic_query_vector = None;
                owned_request
                    .targets
                    .retain(|target| !matches!(target, phoenix_types::QueryTarget::Semantic));
            }
            if owned_request.include_candidate_graph && !self.config.feature_flags.candidate_graph {
                owned_request.include_candidate_graph = false;
            }
            let mut result = if self.native_graph_enabled() {
                let native_query_plan = self.native_runtime.plan_query(&owned_request);
                let lexical_limit = native_query_plan.lexical_limit;
                let lexical_query = owned_request.query.as_str();
                let lexical = if let Some(lex) = self.lex.borrow().as_ref() {
                    lex.search(lexical_query, &owned_request.scope, lexical_limit)
                } else {
                    self.native_lexical_search(lexical_query, &owned_request.scope, lexical_limit)?
                };
                self.native_query_with_lexical(lexical, &owned_request)?
            } else {
                #[cfg(feature = "legacy-cozo-graph")]
                {
                    self.ensure_lex_index()?;
                    let lex_borrow = self.lex.borrow();
                    let lex = lex_borrow.as_ref().expect("lex should exist after ensure");
                    self.gldr.query(&self.store, lex, &owned_request)?
                }
                #[cfg(not(feature = "legacy-cozo-graph"))]
                {
                    return Err(self.legacy_graph_disabled("GLDR query"));
                }
            };
            if semantic_requested && !self.config.feature_flags.semantic {
                let engine_name = if self.native_graph_enabled() {
                    "Triverse"
                } else {
                    "GLDR"
                };
                result.diagnostics.push(Diagnostic {
                    code: "PX_QUERY_SEMANTIC_DISABLED".to_owned(),
                    message: format!(
                        "Semantic retrieval is disabled in runtime feature flags; {engine_name} used lexical and graph retrieval only."
                    ),
                });
            }
            if requested_candidate_graph && !self.config.feature_flags.candidate_graph {
                result.diagnostics.push(Diagnostic {
                    code: "PX_QUERY_CANDIDATE_GRAPH_DISABLED".to_owned(),
                    message:
                        "Candidate graph overlay was requested but runtime feature flags left it disabled."
                            .to_owned(),
                });
            }
            return Ok(result);
        }

        let lexical = if self.native_graph_enabled() {
            if let Some(lex) = self.lex.borrow().as_ref() {
                lex.search(
                    request.query,
                    &request.scope.to_owned(),
                    request.limit.unwrap_or(5),
                )
            } else {
                self.native_lexical_search(
                    request.query,
                    &request.scope.to_owned(),
                    request.limit.unwrap_or(5),
                )?
            }
        } else {
            self.ensure_lex_index()?;
            self.lex
                .borrow()
                .as_ref()
                .expect("lex should exist after ensure")
                .search(
                    request.query,
                    &request.scope.to_owned(),
                    request.limit.unwrap_or(5),
                )
        };

        Ok(QueryResult {
            session_id: request.session_id.clone(),
            chunk_hits: lexical
                .span_hits
                .into_iter()
                .map(|hit| phoenix_types::ChunkHit {
                    chunk_id: hit.span_id,
                    score: hit.score,
                })
                .collect(),
            node_hits: Vec::new(),
            diagnostics: {
                let mut diagnostics = lexical.diagnostics;
                diagnostics.push(Diagnostic {
                    code: "PX_QUERY_LEX".to_owned(),
                    message: "Query executed via the Phoenix lexical facade.".to_owned(),
                });
                diagnostics
            },
        })
    }

    pub fn query_binary(&self, request: QueryRequest) -> Result<Vec<u8>, StoreError> {
        let result = self.query_view(QueryRequestView::from(&request))?;
        binary::encode_query_result(&result)
    }

    pub fn query_binary_into(
        &self,
        request: QueryRequestView<'_>,
        buffer: &mut [u8],
    ) -> Result<usize, StoreError> {
        let result = self.query_view(request)?;
        binary::encode_query_result_into(buffer, &result)
    }

    pub fn encode_query_result_into(
        &self,
        result: &QueryResult,
        buffer: &mut [u8],
    ) -> Result<usize, StoreError> {
        binary::encode_query_result_into(buffer, result)
    }

    pub fn graph_delta(&self, request: GraphDeltaRequest) -> Result<GraphDeltaResult, StoreError> {
        let mut request = request;
        if request.include_candidate_graph && !self.config.feature_flags.candidate_graph {
            request.include_candidate_graph = false;
        }
        if self.native_graph_enabled() {
            self.augment_graph_delta_request_from_journal(&mut request)?;
            let graph = self.native_kernel_snapshot(request.include_candidate_graph)?;
            let state = self.session_state(&request.session_id)?;
            Ok(build_graph_delta_from_kernel_snapshot(
                &graph, &state, &request,
            ))
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.graptor.graph_delta(&self.store, &request)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("Graptor graph delta"))
            }
        }
    }

    pub fn graph_delta_binary(&self, request: GraphDeltaRequest) -> Result<Vec<u8>, StoreError> {
        let result = self.graph_delta(request)?;
        binary::encode_graph_delta(&result)
    }

    pub fn graph_delta_binary_into(
        &self,
        request: GraphDeltaRequest,
        buffer: &mut [u8],
    ) -> Result<usize, StoreError> {
        let result = self.graph_delta(request)?;
        binary::encode_graph_delta_into(buffer, &result)
    }

    pub fn atlas_rich_scan(
        &self,
        request: AtlasRichScanRequest,
    ) -> Result<AtlasRichScanResult, StoreError> {
        let scan_id = request
            .scan_id
            .clone()
            .unwrap_or_else(|| format!("atlas-rich-{}", now_ms()));
        let documents = self.resolve_atlas_rich_scan_documents(&request)?;
        let processed_documents = documents.len();
        let skipped_documents = 0usize;
        let policy = atlas_policy_label(&request.options.policy).to_owned();
        let mut diagnostics = Vec::new();
        let mut stage_summaries = Vec::new();

        if documents.is_empty() {
            diagnostics.push(Diagnostic {
                code: "PX_ATLAS_RICH_SCAN_EMPTY".to_owned(),
                message: "Atlas rich scan had no documents in scope.".to_owned(),
            });
            return Ok(AtlasRichScanResult {
                scan_id,
                processed_documents: 0,
                skipped_documents: 0,
                manifest_dirty_plan: AtlasRichScanManifestSummary {
                    policy,
                    processed_documents: 0,
                    skipped_documents: 0,
                    dirty_documents: 0,
                    clean_documents: 0,
                    manifests_loaded: 0,
                    manifests_persisted: 0,
                },
                stage_summaries,
                lens_chunk_counts: BTreeMap::new(),
                graph_delta_counts: BTreeMap::new(),
                embedding_counts: AtlasRichScanEmbeddingCounts::default(),
                relation_candidate_count: 0,
                candidate_suggestions: Vec::new(),
                alias_proposals: Vec::new(),
                identity_resolution: AtlasIdentityResolutionSummary::default(),
                evidence_ledger: AtlasEvidenceLedgerSummary::default(),
                dataset_factory: AtlasDatasetFactorySummary::default(),
                applied_options: request.options.clone(),
                preservation_counts: atlas_preservation_counts(&request, 0),
                diagnostics,
            });
        }

        let surface_started = Instant::now();
        let dynamic_result = self.run_dynamic_atlas_pipeline(&scan_id, &request, &documents)?;
        let mention_count = dynamic_result.mention_count;
        let token_count = dynamic_result.token_count;
        let sentence_count = dynamic_result.sentence_count;
        let surface_chunk_count = dynamic_result.surface_chunk_count;
        let resolver_link_count = dynamic_result.resolver_link_count;
        let narrative_hit_count = dynamic_result.narrative_hit_count;
        let frame_count = dynamic_result.frame_count;
        let frame_argument_count = dynamic_result.frame_argument_count;
        let frame_fact_count = dynamic_result.frame_fact_count;
        let candidate_suggestions = dynamic_result.candidate_suggestions.clone();
        let alias_proposals = dynamic_result.alias_proposals.clone();
        let identity_resolution = dynamic_result.identity_resolution.clone();
        let evidence_ledger = dynamic_result.evidence_ledger.clone();
        let dataset_factory = dynamic_result.dataset_factory.clone();
        diagnostics.extend(dynamic_result.diagnostics.clone());
        stage_summaries.push(atlas_stage_summary(
            "dynamicSurface",
            surface_started,
            &[
                ("documents", processed_documents),
                ("mentions", mention_count),
                ("hints", surface_chunk_count),
                ("tokens", token_count),
                ("sentences", sentence_count),
                ("mentionGraphEdges", resolver_link_count),
                ("narrativeHits", narrative_hit_count),
                ("frames", frame_count),
                ("frameArguments", frame_argument_count),
                ("frameFacts", frame_fact_count),
                ("candidateSuggestions", candidate_suggestions.len()),
                ("aliasProposals", alias_proposals.len()),
                ("identityReceipts", identity_resolution.receipt_count),
                (
                    "identityCoreferences",
                    identity_resolution.coreference_decisions,
                ),
                ("evidenceReceipts", evidence_ledger.receipt_count),
                ("datasetExamples", dataset_factory.example_count),
            ],
        ));

        let evidence_started = Instant::now();
        let mut lens_chunk_counts = dynamic_result.lens_chunk_counts.clone();
        let lens_total = lens_chunk_counts.values().sum::<usize>();
        let graph_nodes = dynamic_result.graph_nodes;
        let graph_edges = dynamic_result.graph_edges;
        stage_summaries.push(atlas_stage_summary(
            "dynamicGraphCommit",
            evidence_started,
            &[
                ("documents", processed_documents),
                ("lensChunks", lens_total),
                ("graphNodes", graph_nodes),
                ("graphEdges", graph_edges),
            ],
        ));

        let embeddings_started = Instant::now();
        let document_ids = documents
            .iter()
            .map(|document| document.document_id.0.clone())
            .collect::<Vec<_>>();
        let mut semantic_document_rows = Vec::new();
        let mut semantic_node_rows = Vec::new();
        let mut semantic_node_ids = Vec::new();
        if request.options.include_semantic_atlas && self.native_graph_enabled() {
            let updated_at = now_ms();
            semantic_document_rows = documents
                .iter()
                .map(|document| {
                    let leaf_count = dynamic_result
                        .document_leaf_counts
                        .get(&document.document_id.0)
                        .copied()
                        .unwrap_or_else(|| split_ingest_leaf_chunks(&document.text).len());
                    json!({
                        "document_id": document.document_id.0.clone(),
                        "vec": atlas_text_vector(&format!("{}\n{}", document.title, document.text)),
                        "model_id": request.options.embedding_model_id.as_deref().unwrap_or(SEMANTIC_MODEL_ID),
                        "leaf_count": leaf_count as i64,
                        "evidence_refs": [format!("document:{}", document.document_id.0)],
                        "updated_at": updated_at,
                    })
                })
                .collect::<Vec<_>>();
            self.upsert_native_relation_rows("semantic_documents", &semantic_document_rows)?;

            let prototype_inputs = self.list_candidate_prototype_inputs(&document_ids)?;
            semantic_node_rows = prototype_inputs
                .iter()
                .map(|input| {
                    semantic_node_ids.push(input.node_id.clone());
                    json!({
                        "node_id": input.node_id.clone(),
                        "node_kind": input.node_kind.clone(),
                        "document_id": input.document_id.clone(),
                        "narrative_id": input.narrative_id.clone(),
                        "folder_id": input.folder_id.clone(),
                        "vec": atlas_text_vector(&input.text),
                        "model_id": request.options.embedding_model_id.as_deref().unwrap_or(SEMANTIC_MODEL_ID),
                        "evidence_refs": input.evidence_refs.clone(),
                        "updated_at": updated_at,
                    })
                })
                .collect::<Vec<_>>();
            if !semantic_node_rows.is_empty() {
                self.upsert_native_relation_rows(
                    "semantic_node_prototypes",
                    &semantic_node_rows,
                )?;
            }
        } else if request.options.include_semantic_atlas {
            diagnostics.push(Diagnostic {
                code: "PX_ATLAS_SEMANTIC_NATIVE_ONLY".to_owned(),
                message:
                    "Semantic Atlas embeddings are persisted only on the native OverGraph runtime."
                        .to_owned(),
            });
        }
        stage_summaries.push(atlas_stage_summary(
            "embeddings",
            embeddings_started,
            &[
                ("leaf", semantic_document_rows.len()),
                ("entity", semantic_node_rows.len()),
                ("lens", 0),
            ],
        ));

        let overgraph_started = Instant::now();
        let relation_candidate_count =
            if request.options.include_semantic_atlas && self.native_graph_enabled() {
                self.refresh_candidate_graph_edges(&document_ids, &semantic_node_ids)?
            } else {
                0
            };
        stage_summaries.push(atlas_stage_summary(
            "overgraph",
            overgraph_started,
            &[
                ("persistedDocuments", processed_documents),
                ("candidateRelations", relation_candidate_count),
                ("manifestsPersisted", processed_documents),
            ],
        ));

        if lens_chunk_counts.values().all(|count| *count == 0) {
            lens_chunk_counts.insert("evidence".to_owned(), processed_documents);
        }
        let mut graph_delta_counts = BTreeMap::new();
        graph_delta_counts.insert("documents".to_owned(), processed_documents);
        graph_delta_counts.insert("nodes".to_owned(), graph_nodes);
        graph_delta_counts.insert("edges".to_owned(), graph_edges);
        graph_delta_counts.insert("candidateEdges".to_owned(), relation_candidate_count);

        diagnostics.push(Diagnostic {
            code: "PX_ATLAS_RICH_SCAN".to_owned(),
            message: format!(
                "Atlas rich scan processed {processed_documents} document(s), {mention_count} dynamic mention(s), {lens_total} dynamic chunk hint(s), and {relation_candidate_count} candidate relation(s)."
            ),
        });

        Ok(AtlasRichScanResult {
            scan_id,
            processed_documents,
            skipped_documents,
            manifest_dirty_plan: AtlasRichScanManifestSummary {
                policy,
                processed_documents,
                skipped_documents,
                dirty_documents: processed_documents,
                clean_documents: skipped_documents,
                manifests_loaded: processed_documents,
                manifests_persisted: processed_documents,
            },
            stage_summaries,
            lens_chunk_counts,
            graph_delta_counts,
            embedding_counts: AtlasRichScanEmbeddingCounts {
                leaf: semantic_document_rows.len(),
                entity: semantic_node_rows.len(),
                lens: 0,
            },
            relation_candidate_count,
            candidate_suggestions,
            alias_proposals,
            identity_resolution,
            evidence_ledger,
            dataset_factory,
            applied_options: request.options.clone(),
            preservation_counts: atlas_preservation_counts(&request, processed_documents),
            diagnostics,
        })
    }

    fn run_dynamic_atlas_pipeline(
        &self,
        scan_id: &str,
        request: &AtlasRichScanRequest,
        documents: &[AtlasRichScanDocument],
    ) -> Result<DynamicAtlasPipelineResult, StoreError> {
        let created_at = now_ms();
        let entity_rows = self.fetch_relation_rows("entities")?;
        let entity_kind_by_id = dynamic_entity_kind_map(&entity_rows);
        let dynamic_lexicon = dynamic_lexicon_from_rows(&entity_rows, &request.scope)?;
        let alias_registry = dynamic_alias_registry_from_rows(&entity_rows, &request.scope);
        let mut result = DynamicAtlasPipelineResult::default();
        let mut engine_builder = PhoenixNerEngineBuilder::new();
        #[cfg(not(target_arch = "wasm32"))]
        match dynamic_gliner::load_default_model() {
            Ok(model) => {
                engine_builder = engine_builder.model(model);
                result.diagnostics.push(Diagnostic {
                    code: "dynamicNer.model".to_owned(),
                    message: "Dynamic NER attached the native GLiNER BI small lane.".to_owned(),
                });
            }
            Err(error) => {
                result.diagnostics.push(Diagnostic {
                    code: "dynamicNer.modelUnavailable".to_owned(),
                    message: format!("Dynamic NER used deterministic lanes only: {error}"),
                });
            }
        }
        #[cfg(not(target_arch = "wasm32"))]
        match dynamic_gliner::load_default_label_router() {
            Ok(Some(router)) => {
                engine_builder = engine_builder.semantic_label_router(router);
                result.diagnostics.push(Diagnostic {
                    code: "dynamicNer.semanticRouter".to_owned(),
                    message: "Dynamic NER attached the semantic label router.".to_owned(),
                });
            }
            Ok(None) => {
                result.diagnostics.push(Diagnostic {
                    code: "dynamicNer.semanticRouterOff".to_owned(),
                    message: "Dynamic NER semantic label routing is disabled.".to_owned(),
                });
            }
            Err(error) => {
                result.diagnostics.push(Diagnostic {
                    code: "dynamicNer.semanticRouterUnavailable".to_owned(),
                    message: format!("Dynamic NER skipped semantic label routing: {error}"),
                });
            }
        }
        #[cfg(not(target_arch = "wasm32"))]
        match dynamic_gliclass::load_default_adjudicator() {
            Ok(adjudicator) => {
                engine_builder = engine_builder
                    .adjudicator(adjudicator)
                    .max_adjudication_cases(dynamic_ner_gliclass_case_budget());
                result.diagnostics.push(Diagnostic {
                    code: "dynamicNer.gliclassAdjudicator".to_owned(),
                    message: "Dynamic NER attached the GLiClass Instruct kind arbitration lane."
                        .to_owned(),
                });
            }
            Err(error) => {
                result.diagnostics.push(Diagnostic {
                    code: "dynamicNer.gliclassUnavailable".to_owned(),
                    message: format!("Dynamic NER skipped GLiClass kind arbitration: {error}"),
                });
            }
        }
        let engine = engine_builder.build();
        let chunk_config = phoenix_chunker::ChunkerConfig::default();

        let mut vertex_rows = Vec::new();
        let mut edge_rows = Vec::new();
        let mut label_rows = Vec::new();
        let mut vertex_ids = BTreeSet::new();
        let mut edge_pairs = BTreeSet::new();
        let mut frame_edge_keys = BTreeSet::new();
        let mut document_ids = BTreeSet::new();
        let mut candidate_by_key = BTreeMap::<String, AtlasRichScanCandidateSummary>::new();
        let mut evidence_receipts = Vec::new();
        let mut semantic_frame_rows = Vec::new();
        let mut semantic_frame_argument_rows = Vec::new();
        let mut semantic_frame_fact_rows = Vec::new();

        for document in documents {
            let scope = document.scope.clone();
            let document_id = document.document_id.0.clone();
            document_ids.insert(document_id.clone());
            let note_id = document
                .note_id
                .as_ref()
                .map(|note_id| note_id.0.clone())
                .unwrap_or_else(|| document_id.clone());
            let document_view = IngestDocumentView {
                document_id: document.document_id.clone(),
                note_id: document.note_id.clone(),
                title: &document.title,
                text: &document.text,
                scope: ScopeKeyView::from(&scope),
            };
            self.delete_note_rows(&note_id)?;
            self.put_relation_row(
                "notes",
                native_note_row_from_ingest(&document_view, &note_id, created_at),
            )?;

            let doc_vertex_id = phase1_document_vertex_id(&document_id);
            let mut doc_attributes = Map::new();
            doc_attributes.insert("pipelineSource".to_owned(), json!("dynamic_ner_chunker_v1"));
            phase1_push_vertex(
                &mut vertex_ids,
                &mut vertex_rows,
                &mut label_rows,
                phase1_vertex_row(
                    &doc_vertex_id,
                    "document",
                    &document.title,
                    Some(&document_id),
                    scope.narrative_id.as_deref(),
                    doc_attributes,
                    vec![format!("document:{document_id}")],
                ),
            );

            let chunks = phoenix_chunker::build_chunks(&document.text, &chunk_config);
            result
                .document_leaf_counts
                .insert(document_id.clone(), chunks.len());
            result.surface_chunk_count += chunks.len();
            for (index, chunk) in chunks.iter().enumerate() {
                let leaf_id = format!("leaf::{document_id}::{index}");
                let chunk_text = &document.text[chunk.start..chunk.end];
                let mut attributes = Map::new();
                attributes.insert("noteId".to_owned(), json!(note_id));
                attributes.insert("searchChunkId".to_owned(), json!(leaf_id));
                attributes.insert("pipelineSource".to_owned(), json!("dynamic_chunker_v1"));
                attributes.insert(
                    "range".to_owned(),
                    json!({
                        "start": chunk.start,
                        "end": chunk.end,
                    }),
                );
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_vertex_row(
                        &leaf_id,
                        "leaf",
                        &phase1_snippet(chunk_text, 96),
                        Some(&document_id),
                        scope.narrative_id.as_deref(),
                        attributes,
                        vec![format!("document:{document_id}")],
                    ),
                );
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        &doc_vertex_id,
                        &leaf_id,
                        "contains",
                        Some(&document_id),
                        scope.narrative_id.as_deref(),
                        Map::new(),
                        vec![format!("document:{document_id}")],
                    ),
                );
            }

            let (tokens, sentences) = dynamic_tokens_and_sentences(&document.text);
            result.token_count += tokens.len();
            result.sentence_count += sentences.len();
            let dynamic_scope = dynamic_scope_from_scope(&scope);
            let output = engine
                .extract_mentions(&SurfaceNerInput {
                    document_id: &document_id,
                    text: &document.text,
                    tokens: &tokens,
                    sentences: &sentences,
                    scope: &dynamic_scope,
                    lexicon: dynamic_lexicon.as_ref(),
                    surface_hits: &[],
                    label_bank_context: None,
                })
                .map_err(|error| StoreError::Query(format!("dynamic NER failed: {error}")))?;
            result.mention_count += output.mentions.len();
            result.resolver_link_count += output.mention_graph.edge_count();
            let alias_report =
                phoenix_dynamic_ner::resolve_aliases(&phoenix_dynamic_ner::AliasResolutionInput {
                    document_id: &document_id,
                    mentions: &output.mentions,
                    surface_memory: &output.surface_memory,
                    registry_entities: &alias_registry,
                });
            let identity_dag = phoenix_dynamic_ner::resolve_identity_dag(
                &phoenix_dynamic_ner::IdentityResolutionInput {
                    document_id: &document_id,
                    mentions: &output.mentions,
                    mention_graph: &output.mention_graph,
                    surface_memory: &output.surface_memory,
                    alias_report: Some(&alias_report),
                    registry_entities: &alias_registry,
                    linker_candidates: &[],
                },
            );
            evidence_receipts.extend(evidence_ledger::build_document_receipts(
                evidence_ledger::DocumentEvidenceInput {
                    scan_id,
                    document_id: &document.document_id,
                    note_id: document.note_id.as_ref(),
                    text: &document.text,
                    mentions: &output.mentions,
                    mention_graph: &output.mention_graph,
                    alias_report: &alias_report,
                    identity_receipts: &identity_dag.summary.receipts,
                    created_at,
                },
            ));
            merge_identity_resolution_summary(
                &mut result.identity_resolution,
                identity_dag.summary,
            );
            let mut frame_resolver_seed = request.resolver_seed.clone();
            extend_frame_resolver_seed_from_rows(&mut frame_resolver_seed, &entity_rows, &scope);
            let frame_scan = self.scanner.scan_parts(
                &document.text,
                &scope,
                request.session_id.as_ref(),
                &frame_resolver_seed,
            );
            let structure_artifact = self.structure.build_parts(&document.text, &frame_scan);
            let frame_rows = frame_extraction::build_rows(frame_extraction::FrameExtractionInput {
                scan_id,
                document_id: &document.document_id,
                note_id: document.note_id.as_ref(),
                text: &document.text,
                structure: &structure_artifact,
                created_at,
            });
            result.frame_count += frame_rows.frame_count();
            result.frame_argument_count += frame_rows.argument_count();
            result.frame_fact_count += frame_rows.fact_count();
            evidence_receipts.extend(frame_rows.receipts);
            semantic_frame_rows.extend(frame_rows.frame_rows);
            semantic_frame_argument_rows.extend(frame_rows.argument_rows);
            semantic_frame_fact_rows.extend(frame_rows.fact_rows);
            if request.options.return_candidate_suggestions {
                result.alias_proposals.extend(alias_report.proposals);
            }
            *result
                .lens_chunk_counts
                .entry("dynamicHints".to_owned())
                .or_default() += output.chunk_hints.len();

            for diagnostic in output.diagnostics {
                result.diagnostics.push(Diagnostic {
                    code: "PX_DYNAMIC_NER_DIAG".to_owned(),
                    message: format!("{diagnostic:?}"),
                });
            }

            let mut mention_vertex_by_id = BTreeMap::<u64, String>::new();
            for mention in &output.mentions {
                if !dynamic_mention_is_graphworthy(mention, &document.text) {
                    continue;
                }
                let label = dynamic_mention_label(mention);
                if label.is_empty()
                    || !normalized_has_meaningful_token(mention.normalized.as_str(), "default")
                {
                    continue;
                }
                let known_entity_id = dynamic_known_entity_id(mention);
                let entity_kind = known_entity_id
                    .as_deref()
                    .and_then(|id| entity_kind_by_id.get(id))
                    .cloned();
                let vertex_id = known_entity_id
                    .as_ref()
                    .map(|id| format!("entity::{id}"))
                    .unwrap_or_else(|| dynamic_mention_vertex_id(&document_id, mention));
                mention_vertex_by_id.insert(mention.mention_id.0, vertex_id.clone());

                let mut attributes = Map::new();
                attributes.insert("pipelineSource".to_owned(), json!("dynamic_ner_v1"));
                attributes.insert(
                    "entityKind".to_owned(),
                    json!(atlas_entity_kind_name(entity_kind.as_ref())),
                );
                attributes.insert(
                    "mentionKind".to_owned(),
                    json!(dynamic_mention_kind_name(mention.mention_kind)),
                );
                attributes.insert(
                    "mentionStatus".to_owned(),
                    json!(dynamic_mention_status_name(mention.status)),
                );
                attributes.insert("confidence".to_owned(), json!(mention.confidence));
                attributes.insert("normalized".to_owned(), json!(mention.normalized.as_str()));
                attributes.insert(
                    "range".to_owned(),
                    json!({
                        "start": mention.range.start,
                        "end": mention.range.end,
                    }),
                );
                attributes.insert("sentenceIndex".to_owned(), json!(mention.sentence_index));
                let evidence_refs = vec![
                    format!("document:{document_id}"),
                    format!("mention:{}", mention.mention_id.0),
                ];
                phase1_push_vertex(
                    &mut vertex_ids,
                    &mut vertex_rows,
                    &mut label_rows,
                    phase1_vertex_row(
                        &vertex_id,
                        "entity",
                        &label,
                        Some(&document_id),
                        scope.narrative_id.as_deref(),
                        attributes,
                        evidence_refs.clone(),
                    ),
                );

                if let Some(index) = find_leaf_for_range(&chunks, mention.range.start as usize) {
                    let leaf_id = format!("leaf::{document_id}::{index}");
                    let mut edge_attributes = Map::new();
                    edge_attributes.insert("pipelineSource".to_owned(), json!("dynamic_ner_v1"));
                    edge_attributes.insert("confidence".to_owned(), json!(mention.confidence));
                    phase1_push_edge(
                        &mut edge_pairs,
                        &mut edge_rows,
                        phase1_edge_row(
                            &leaf_id,
                            &vertex_id,
                            "mentions",
                            Some(&document_id),
                            scope.narrative_id.as_deref(),
                            edge_attributes,
                            evidence_refs.clone(),
                        ),
                    );
                }

                if request.options.return_candidate_suggestions
                    && dynamic_should_surface_candidate(mention, &document.text)
                {
                    let key = atlas_candidate_key(&label);
                    let kind_votes =
                        dynamic_candidate_kind_votes(mention, entity_kind.as_ref(), &document.text);
                    let kind = dynamic_candidate_kind(mention, entity_kind.as_ref(), &kind_votes);
                    let decision_status = dynamic_candidate_decision_status(mention);
                    let review_reason = dynamic_candidate_review_reason(mention, &kind);
                    let evidence =
                        dynamic_mention_context_snippet(&document.text, mention.range, 220);
                    let candidate = AtlasRichScanCandidateSummary {
                        id: format!("dyn-candidate-{:016x}", atlas_hash64(vertex_id.as_bytes())),
                        label: label.clone(),
                        kind,
                        confidence: mention.confidence,
                        source_document_id: Some(document.document_id.clone()),
                        source_note_id: document.note_id.clone(),
                        evidence: (!evidence.is_empty()).then_some(evidence),
                        aliases: Vec::new(),
                        range: Some(TextRange {
                            start: mention.range.start,
                            end: mention.range.end,
                        }),
                        source_stage: "dynamicNer".to_owned(),
                        kind_votes,
                        decision_status,
                        review_reason,
                    };
                    candidate_by_key
                        .entry(key)
                        .and_modify(|current| {
                            if dynamic_candidate_is_better(&candidate, current) {
                                *current = candidate.clone();
                            }
                        })
                        .or_insert(candidate);
                }
            }

            if request.options.return_candidate_suggestions {
                dynamic_push_network_surface_candidates(&document, &mut candidate_by_key);
            }

            for edge in output.mention_graph.edges {
                let Some(left) = mention_vertex_by_id.get(&edge.left.0) else {
                    continue;
                };
                let Some(right) = mention_vertex_by_id.get(&edge.right.0) else {
                    continue;
                };
                let mut attributes = Map::new();
                attributes.insert(
                    "pipelineSource".to_owned(),
                    json!("dynamic_mention_graph_v1"),
                );
                attributes.insert(
                    "mentionEdgeKind".to_owned(),
                    json!(format!("{:?}", edge.kind)),
                );
                attributes.insert("weight".to_owned(), json!(edge.weight));
                phase1_push_edge(
                    &mut edge_pairs,
                    &mut edge_rows,
                    phase1_edge_row(
                        left,
                        right,
                        "mentionRelated",
                        Some(&document_id),
                        scope.narrative_id.as_deref(),
                        attributes,
                        vec![format!("document:{document_id}")],
                    ),
                );
            }

            push_frame_graph_projection(
                &mut vertex_ids,
                &mut vertex_rows,
                &mut label_rows,
                &mut edge_rows,
                &mut frame_edge_keys,
                scan_id,
                document,
                &structure_artifact,
            );
        }

        self.replace_native_graph_document_rows(
            document_ids,
            vertex_rows.clone(),
            edge_rows.clone(),
            label_rows,
        )?;
        let batch = KernelGraphMutationBatch::from(GraphMutationBatch {
            layer: GraphLayer::Asserted,
            scope: GraphMutationScope::Full,
            vertices: vertex_rows
                .iter()
                .filter_map(graph_vertex_record_from_row_value)
                .collect(),
            edges: edge_rows
                .iter()
                .filter_map(|row| graph_edge_record_from_row_value(row, GraphLayer::Asserted))
                .collect(),
        });
        self.native_runtime
            .deterministic_kernel
            .apply_batch(batch)
            .map_err(Self::graph_backend_error)?;
        self.refresh_native_graph_rebuild_token()?;

        result.graph_nodes = vertex_rows.len();
        result.graph_edges = edge_rows.len();
        result.candidate_suggestions = candidate_by_key.into_values().collect();
        evidence_receipts.extend(evidence_ledger::build_candidate_receipts(
            scan_id,
            &result.candidate_suggestions,
            created_at,
        ));
        result.evidence_ledger = evidence_ledger::summarize_ledger(&evidence_receipts);
        let receipt_rows = evidence_ledger::receipt_rows(&evidence_receipts);
        let dataset_build =
            evidence_ledger::build_dataset_factory(scan_id, &evidence_receipts, created_at);
        if self.native_graph_enabled() {
            if !receipt_rows.is_empty() {
                self.upsert_native_relation_rows("evidence_ledger", &receipt_rows)?;
            }
            if !dataset_build.snapshot_rows.is_empty() {
                self.upsert_native_relation_rows(
                    "dataset_snapshots",
                    &dataset_build.snapshot_rows,
                )?;
            }
            if !dataset_build.example_rows.is_empty() {
                self.upsert_native_relation_rows(
                    "dataset_examples",
                    &dataset_build.example_rows,
                )?;
            }
            if !semantic_frame_rows.is_empty() {
                self.upsert_native_relation_rows("semantic_frames", &semantic_frame_rows)?;
            }
            if !semantic_frame_argument_rows.is_empty() {
                self.upsert_native_relation_rows(
                    "semantic_frame_arguments",
                    &semantic_frame_argument_rows,
                )?;
            }
            if !semantic_frame_fact_rows.is_empty() {
                self.upsert_native_relation_rows(
                    "semantic_frame_facts",
                    &semantic_frame_fact_rows,
                )?;
            }
        } else {
            result.diagnostics.push(Diagnostic {
                code: "PX_ATLAS_EVIDENCE_NATIVE_ONLY".to_owned(),
                message: "Evidence ledger rows are persisted only on the native runtime path."
                    .to_owned(),
            });
        }
        result.dataset_factory = dataset_build.summary;
        result.diagnostics.push(Diagnostic {
            code: "PX_ATLAS_DYNAMIC_PIPELINE".to_owned(),
            message: format!(
                "Atlas used dynamic NER + sentence chunker: {} mention(s), {} chunk(s), {} graph edge(s), {} evidence receipt(s).",
                result.mention_count, result.surface_chunk_count, result.graph_edges, result.evidence_ledger.receipt_count
            ),
        });
        Ok(result)
    }

    fn resolve_atlas_rich_scan_documents(
        &self,
        request: &AtlasRichScanRequest,
    ) -> Result<Vec<AtlasRichScanDocument>, StoreError> {
        if !request.documents.is_empty() {
            return Ok(request
                .documents
                .iter()
                .filter(|document| !document.text.trim().is_empty())
                .cloned()
                .collect());
        }

        let note_rows = if !request.changed_document_ids.is_empty() {
            let ids = request
                .changed_document_ids
                .iter()
                .map(|id| id.0.clone())
                .collect::<Vec<_>>();
            self.list_note_values_by_ids(&ids, true)?
        } else if let Some(note_id) = request.scope.note_id.as_ref() {
            self.list_note_values_by_ids(&[note_id.0.clone()], true)?
        } else {
            self.list_note_values(request.scope.folder_id.as_deref(), true)?
        };

        Ok(note_rows
            .into_iter()
            .filter_map(|row| atlas_document_from_note_value(row, &request.scope))
            .filter(|document| !document.text.trim().is_empty())
            .collect())
    }

    pub fn ingest_stub(&self, request: IngestRequest) -> Result<IngestResult, StoreError> {
        self.ingest(request)
    }

    pub fn query_stub(&self, request: QueryRequest) -> Result<QueryResult, StoreError> {
        self.query(request)
    }

    pub fn scan_text(&self, request: ScanRequest) -> ScanArtifact {
        self.scan_text_view(ScanRequestView::from(&request))
    }

    pub fn scan_text_view(&self, request: ScanRequestView<'_>) -> ScanArtifact {
        if self.native_graph_enabled() {
            self.native_runtime.scan_text(request.to_owned())
        } else {
            self.scanner.scan_parts(
                request.text,
                &request.scope.to_owned(),
                request.session_id.as_ref(),
                request.resolver_seed,
            )
        }
    }

    pub fn build_structure(&self, request: StructureRequest) -> StructureArtifact {
        self.build_structure_view(StructureRequestView::from(&request))
    }

    pub fn build_structure_view(&self, request: StructureRequestView<'_>) -> StructureArtifact {
        if self.native_graph_enabled() {
            self.native_runtime.build_structure(request.to_owned())
        } else {
            self.structure.build_parts(request.text, request.scan)
        }
    }

    pub fn analyze_text(&self, text: &str) -> TextAnalytics {
        self.analyze_text_view(AnalyzeTextRequestView { text })
    }

    pub fn analyze_text_view(&self, request: AnalyzeTextRequestView<'_>) -> TextAnalytics {
        if self.native_graph_enabled() {
            self.native_runtime.analyze_text(request.text)
        } else {
            phoenix_analytics::analyze_text(request.text)
        }
    }

    pub fn export_snapshot(&self) -> Result<Vec<u8>, StoreError> {
        self.export_snapshot_partition(SnapshotPartition::All)
    }

    pub fn export_snapshot_partition(
        &self,
        partition: SnapshotPartition,
    ) -> Result<Vec<u8>, StoreError> {
        if self.native_graph_enabled() {
            self.ensure_native_graph_ready()?;
            #[cfg(not(target_arch = "wasm32"))]
            if let Some(store) = self.overgraph_store.as_ref() {
                return store.export_snapshot_partition(partition);
            }
            Err(self.native_unsupported("native OverGraph snapshot export"))
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.export_snapshot_partition(partition)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                let _ = partition;
                Err(self.legacy_graph_disabled("legacy snapshot export"))
            }
        }
    }

    pub fn import_snapshot(&self, bytes: &[u8]) -> Result<SnapshotEnvelope, StoreError> {
        self.import_snapshot_with_warm_indexes(bytes, true)
    }

    pub fn import_snapshot_cold(&self, bytes: &[u8]) -> Result<SnapshotEnvelope, StoreError> {
        self.import_snapshot_with_warm_indexes(bytes, false)
    }

    fn import_snapshot_with_warm_indexes(
        &self,
        bytes: &[u8],
        warm_indexes: bool,
    ) -> Result<SnapshotEnvelope, StoreError> {
        let envelope = if self.native_graph_enabled() {
            if bytes.starts_with(b"PXNATV01") {
                return Err(StoreError::Snapshot(
                    "legacy native archive snapshots are not accepted on the OverGraph runtime path"
                        .to_owned(),
                ));
            }
            #[cfg(not(target_arch = "wasm32"))]
            if let Some(store) = self.overgraph_store.as_ref() {
                store.import_snapshot(bytes)?
            } else {
                return Err(self.native_unsupported("native OverGraph snapshot import"));
            }
            #[cfg(target_arch = "wasm32")]
            return Err(self.native_unsupported("native OverGraph snapshot import"));
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.import_snapshot(bytes)?
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                let _ = bytes;
                return Err(self.legacy_graph_disabled("legacy snapshot import"));
            }
        };
        self.invalidate_lex_caches();
        if !warm_indexes {
            return Ok(envelope);
        }
        if self.native_graph_enabled() {
            self.warm_native_scope_lex_caches(self.native_note_rows_to_indexed_spans()?);
            self.ensure_native_graph_ready()?;
        } else {
            self.rebuild_lex_index()?;
        }
        Ok(envelope)
    }

    pub fn snapshot_descriptor(&self, created_at: i64, payload_bytes: usize) -> SnapshotDto {
        if self.native_graph_enabled() {
            SnapshotDto {
                schema_version: NATIVE_RUNTIME_SCHEMA_VERSION.to_owned(),
                created_at,
                payload_bytes,
                relation_counts: self.relation_counts().unwrap_or_default(),
            }
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.snapshot_descriptor(created_at, payload_bytes)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                SnapshotDto {
                    schema_version: NATIVE_RUNTIME_SCHEMA_VERSION.to_owned(),
                    created_at,
                    payload_bytes,
                    relation_counts: Vec::new(),
                }
            }
        }
    }

    pub fn session_state(&self, session_id: &SessionId) -> Result<SessionState, StoreError> {
        if self.native_graph_enabled() {
            let session = self.load_session(session_id)?;
            let documents = self.native_session_documents_from_notes()?;
            let updated_at = documents
                .iter()
                .map(|document| document.updated_at)
                .max()
                .unwrap_or(session.updated_at)
                .max(session.updated_at);
            return Ok(SessionState {
                session_id: session_id.clone(),
                documents,
                manifest_namespaces: vec!["invarant-v3.session".to_owned()],
                updated_at,
            });
        }
        #[cfg(feature = "legacy-cozo-graph")]
        {
            load_session_state(&self.store, session_id)
        }
        #[cfg(not(feature = "legacy-cozo-graph"))]
        {
            let _ = session_id;
            Err(self.legacy_graph_disabled("legacy session state"))
        }
    }

    pub fn session_stats(&self, session_id: &SessionId) -> Result<SessionStats, StoreError> {
        if self.native_graph_enabled() {
            let session = self.load_session(session_id)?;
            let documents = self.native_session_documents_from_notes()?;
            let graph = self.native_kernel_snapshot(true)?;
            let updated_at = documents
                .iter()
                .map(|document| document.updated_at)
                .max()
                .unwrap_or(session.updated_at)
                .max(session.updated_at);
            return Ok(SessionStats {
                session_id: session_id.clone(),
                document_count: documents.len(),
                chapter_count: documents
                    .iter()
                    .map(|document| document.chapter_count)
                    .sum(),
                boundary_count: documents
                    .iter()
                    .map(|document| document.boundary_count)
                    .sum(),
                parent_count: documents.iter().map(|document| document.parent_count).sum(),
                leaf_count: documents.iter().map(|document| document.leaf_count).sum(),
                entity_count: self.fetch_relation_rows("entities")?.len(),
                discovery_candidate_count: self.fetch_relation_rows("discovery_candidates")?.len(),
                graph_vertex_count: graph.vertices.len(),
                graph_edge_count: graph.asserted_edges.len() + graph.candidate_edges.len(),
                span_count: self.native_note_rows_to_indexed_spans()?.len(),
                updated_at,
            });
        }
        #[cfg(feature = "legacy-cozo-graph")]
        {
            self.graptor.session_stats(&self.store, session_id)
        }
        #[cfg(not(feature = "legacy-cozo-graph"))]
        {
            let _ = session_id;
            Err(self.legacy_graph_disabled("Graptor session stats"))
        }
    }

    pub fn upsert_entity_card(&self, card: &EntityCard) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            self.upsert_entity_cards_batch(std::slice::from_ref(card))?;
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.legacy_store("entity cards")?
                    .upsert_entity_card(card)?;
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("legacy entity cards"));
            }
        }
        self.sync_relation_to_native("entity_cards")
    }

    pub fn upsert_entity_cards_batch(&self, cards: &[EntityCard]) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            let rows = cards.iter().map(entity_card_row).collect::<Vec<_>>();
            self.upsert_native_relation_rows("entity_cards", &rows)?;
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.legacy_store("entity cards")?
                    .upsert_entity_cards_batch(cards)?;
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("legacy entity cards"));
            }
        }
        self.sync_relation_to_native("entity_cards")
    }

    pub fn get_entity_cards(
        &self,
        entity_id: &phoenix_types::EntityId,
    ) -> Result<Vec<EntityCard>, StoreError> {
        if self.native_graph_enabled() {
            let mut cards = self
                .fetch_relation_rows("entity_cards")?
                .into_iter()
                .filter(|row| {
                    row.get("entity_id").and_then(Value::as_str) == Some(entity_id.0.as_str())
                })
                .map(entity_card_from_row)
                .collect::<Result<Vec<_>, _>>()?;
            cards.sort_by(|left: &EntityCard, right: &EntityCard| {
                left.display_order
                    .cmp(&right.display_order)
                    .then_with(|| left.card_id.cmp(&right.card_id))
            });
            Ok(cards)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.legacy_store("entity cards")?
                    .get_entity_cards(entity_id)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy entity cards"))
            }
        }
    }

    pub fn upsert_folder_schema(&self, schema: &FolderSchema) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            let row = folder_schema_row(schema);
            self.upsert_native_relation_rows("folder_schemas", &[row])?;
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.legacy_store("folder schemas")?
                    .upsert_folder_schema(schema)?;
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("legacy folder schemas"));
            }
        }
        self.sync_relation_to_native("folder_schemas")
    }

    pub fn get_folder_schema(&self, id: &str) -> Result<Option<FolderSchema>, StoreError> {
        if self.native_graph_enabled() {
            self.fetch_relation_rows("folder_schemas")?
                .into_iter()
                .find(|row| row.get("id").and_then(Value::as_str) == Some(id))
                .map(folder_schema_from_row)
                .transpose()
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.legacy_store("folder schemas")?.get_folder_schema(id)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy folder schemas"))
            }
        }
    }

    pub fn save_network_view(&self, view: &SavedNetworkView) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            let store = self.native_row_store()?;
            let instance_row = network_instance_row(&view.instance);
            let member_rows = view
                .members
                .iter()
                .map(network_membership_row)
                .collect::<Vec<_>>();
            let relationship_rows = view
                .relationships
                .iter()
                .map(network_relationship_row)
                .collect::<Vec<_>>();

            let mut instances = store.fetch_rows("network_instance")?;
            instances.retain(|row| {
                row.get("id").and_then(Value::as_str) != Some(view.instance.id.as_str())
            });
            instances.push(instance_row);
            store.replace_relation_rows("network_instance", &instances)?;

            let mut members = store.fetch_rows("network_membership")?;
            members.retain(|row| {
                row.get("network_id").and_then(Value::as_str) != Some(view.instance.id.as_str())
            });
            members.extend(member_rows);
            store.replace_relation_rows("network_membership", &members)?;

            let mut relationships = store.fetch_rows("network_relationship")?;
            relationships.retain(|row| {
                row.get("network_id").and_then(Value::as_str) != Some(view.instance.id.as_str())
            });
            relationships.extend(relationship_rows);
            store.replace_relation_rows("network_relationship", &relationships)?;

            return Ok(());
        }

        #[cfg(not(feature = "legacy-cozo-graph"))]
        {
            return Err(self.legacy_graph_disabled("legacy network views"));
        }
        #[cfg(feature = "legacy-cozo-graph")]
        {
            let existing = self.get_network_view(&view.instance.id)?;

            self.legacy_store("network views")?
                .upsert_network_instance(&view.instance)?;
            self.legacy_store("network views")?
                .upsert_network_memberships(&view.members)?;
            self.legacy_store("network views")?
                .upsert_network_relationships(&view.relationships)?;

            if let Some(existing) = existing {
                let new_member_keys = view
                    .members
                    .iter()
                    .map(|member| (member.network_id.clone(), member.entity_id.0.clone()))
                    .collect::<BTreeSet<_>>();
                let stale_members = existing
                    .members
                    .into_iter()
                    .filter(|member| {
                        !new_member_keys
                            .contains(&(member.network_id.clone(), member.entity_id.0.clone()))
                    })
                    .collect::<Vec<_>>();
                self.legacy_store("network views")?
                    .delete_network_memberships(&stale_members)?;

                let new_relationship_keys = view
                    .relationships
                    .iter()
                    .map(|relationship| {
                        (
                            relationship.network_id.clone(),
                            relationship.relationship_id.clone(),
                        )
                    })
                    .collect::<BTreeSet<_>>();
                let stale_relationships = existing
                    .relationships
                    .into_iter()
                    .filter(|relationship| {
                        !new_relationship_keys.contains(&(
                            relationship.network_id.clone(),
                            relationship.relationship_id.clone(),
                        ))
                    })
                    .collect::<Vec<_>>();
                self.legacy_store("network views")?
                    .delete_network_relationships(&stale_relationships)?;
            }

            self.sync_relation_to_native("network_instance")?;
            self.sync_relation_to_native("network_membership")?;
            self.sync_relation_to_native("network_relationship")?;
            Ok(())
        }
    }

    pub fn get_network_view(&self, id: &str) -> Result<Option<SavedNetworkView>, StoreError> {
        if self.native_graph_enabled() {
            let Some(instance) = self
                .fetch_relation_rows("network_instance")?
                .into_iter()
                .find(|row| row.get("id").and_then(Value::as_str) == Some(id))
            else {
                return Ok(None);
            };
            let instance = network_instance_from_row(instance)?;
            let members = self
                .fetch_relation_rows("network_membership")?
                .into_iter()
                .filter(|row| row.get("network_id").and_then(Value::as_str) == Some(id))
                .map(network_membership_from_row)
                .collect::<Result<Vec<_>, _>>()?;
            let relationships = self
                .fetch_relation_rows("network_relationship")?
                .into_iter()
                .filter(|row| row.get("network_id").and_then(Value::as_str) == Some(id))
                .map(network_relationship_from_row)
                .collect::<Result<Vec<_>, _>>()?;
            Ok(Some(SavedNetworkView {
                instance,
                members,
                relationships,
            }))
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let Some(instance) = self
                    .legacy_store("network views")?
                    .get_network_instance(id)?
                else {
                    return Ok(None);
                };
                let members = self
                    .legacy_store("network views")?
                    .get_network_members(id)?;
                let relationships = self
                    .legacy_store("network views")?
                    .get_network_relationships(id)?;
                Ok(Some(SavedNetworkView {
                    instance,
                    members,
                    relationships,
                }))
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy network views"))
            }
        }
    }

    pub fn list_network_views(&self) -> Result<Vec<NetworkInstance>, StoreError> {
        if self.native_graph_enabled() {
            let mut views = self
                .fetch_relation_rows("network_instance")?
                .into_iter()
                .map(network_instance_from_row)
                .collect::<Result<Vec<_>, _>>()?;
            views.sort_by(|left: &NetworkInstance, right: &NetworkInstance| {
                right
                    .updated_at
                    .cmp(&left.updated_at)
                    .then_with(|| left.id.cmp(&right.id))
            });
            Ok(views)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.legacy_store("network views")?.list_network_instances()
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy network views"))
            }
        }
    }

    pub fn delete_network_view(&self, id: &str) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            let store = self.native_row_store()?;
            let mut instances = store.fetch_rows("network_instance")?;
            instances.retain(|row| row.get("id").and_then(Value::as_str) != Some(id));
            store.replace_relation_rows("network_instance", &instances)?;

            let mut members = store.fetch_rows("network_membership")?;
            members.retain(|row| row.get("network_id").and_then(Value::as_str) != Some(id));
            store.replace_relation_rows("network_membership", &members)?;

            let mut relationships = store.fetch_rows("network_relationship")?;
            relationships.retain(|row| row.get("network_id").and_then(Value::as_str) != Some(id));
            store.replace_relation_rows("network_relationship", &relationships)?;
            return Ok(());
        }

        #[cfg(not(feature = "legacy-cozo-graph"))]
        {
            return Err(self.legacy_graph_disabled("legacy network views"));
        }
        #[cfg(feature = "legacy-cozo-graph")]
        {
            let members = self
                .legacy_store("network views")?
                .get_network_members(id)?;
            let relationships = self
                .legacy_store("network views")?
                .get_network_relationships(id)?;
            self.legacy_store("network views")?
                .delete_network_relationships(&relationships)?;
            self.legacy_store("network views")?
                .delete_network_memberships(&members)?;
            self.legacy_store("network views")?
                .delete_network_instance(id)?;
            self.sync_relation_to_native("network_instance")?;
            self.sync_relation_to_native("network_membership")?;
            self.sync_relation_to_native("network_relationship")
        }
    }

    fn clear_derived_partition(&self) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            self.native_row_store()?
                .clear_relations(DERIVED_SNAPSHOT_RELATIONS)?;
            self.native_row_store()?
                .clear_relations(DERIVED_EPHEMERA_RELATIONS)?;
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.clear_relations(DERIVED_SNAPSHOT_RELATIONS)?;
                self.store.clear_relations(DERIVED_EPHEMERA_RELATIONS)?;
                for relation in DERIVED_SNAPSHOT_RELATIONS {
                    self.sync_relation_to_native(relation)?;
                }
                for relation in DERIVED_EPHEMERA_RELATIONS {
                    self.sync_relation_to_native(relation)?;
                }
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("legacy derived clear"));
            }
        }
        self.rebuild_lex_index()?;
        Ok(())
    }

    fn clear_derived_ephemera(&self) -> Result<(), StoreError> {
        if self.native_graph_enabled() {
            self.native_row_store()?
                .clear_relations(DERIVED_EPHEMERA_RELATIONS)?;
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                self.store.clear_relations(DERIVED_EPHEMERA_RELATIONS)?;
                for relation in DERIVED_EPHEMERA_RELATIONS {
                    self.sync_relation_to_native(relation)?;
                }
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("legacy ephemera clear"));
            }
        }
        Ok(())
    }

    fn delete_rows_by_session(
        &self,
        relation: &str,
        key_columns: &[&str],
        session_id: &str,
    ) -> Result<usize, StoreError> {
        if self.native_graph_enabled() {
            let rows = self
                .fetch_relation_rows(relation)?
                .into_iter()
                .filter(|row| row.get("session_id").and_then(Value::as_str) == Some(session_id))
                .collect::<Vec<_>>();
            self.delete_relation_rows(relation, &rows)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let rows = self
                    .legacy_store("session cleanup")?
                    .fetch_compact_rows_where_str(
                        relation,
                        key_columns,
                        "session_id",
                        session_id,
                    )?;
                let count = rows.len();
                self.legacy_store("session cleanup")?
                    .delete_key_rows(relation, &rows)?;
                Ok(count)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                let _ = key_columns;
                Err(self.legacy_graph_disabled("legacy session cleanup"))
            }
        }
    }

    fn close_session(&self, session_id: &str) -> Result<usize, StoreError> {
        let mut deleted = 0usize;
        deleted += self.delete_rows_by_session("phoenix_commits", &["commit_id"], session_id)?;
        deleted += self.delete_rows_by_session("phoenix_ingest_log", &["id"], session_id)?;
        deleted += self.delete_rows_by_session("phoenix_query_log", &["id"], session_id)?;
        deleted += self.delete_rows_by_session("phoenix_sessions", &["session_id"], session_id)?;
        self.sync_relation_to_native("phoenix_commits")?;
        self.sync_relation_to_native("phoenix_ingest_log")?;
        self.sync_relation_to_native("phoenix_query_log")?;
        self.sync_relation_to_native("phoenix_sessions")?;
        Ok(deleted)
    }

    fn apply_persistence_wal_batch(
        &self,
        records: &[PersistenceWalRecord],
    ) -> Result<PersistenceWalApplyReport, StoreError> {
        let total_started = Instant::now();
        let mut report = PersistenceWalApplyReport {
            records: records.len(),
            ..PersistenceWalApplyReport::default()
        };
        let mut lex_dirty = false;
        for record in records {
            if record.seq == 0 {
                return Err(StoreError::Query("invalid WAL seq: 0".to_owned()));
            }
            if record.partition != "content" {
                return Err(StoreError::Query(format!(
                    "unsupported WAL partition: {}",
                    record.partition
                )));
            }
            let _written_at = record.written_at;

            match record.command.as_str() {
                "note:upsert" => {
                    let started = Instant::now();
                    let row = require_payload_value(&record.payload, "row")?;
                    self.upsert_note_row(row)?;
                    report.note_upserts += 1;
                    report.note_ms += elapsed_millis(started);
                    lex_dirty = true;
                }
                "note:delete" => {
                    let started = Instant::now();
                    let id = require_payload_str(&record.payload, "id")?;
                    self.delete_note_rows(id)?;
                    report.note_deletes += 1;
                    report.note_ms += elapsed_millis(started);
                    lex_dirty = true;
                }
                "relation:upsert" => {
                    let started = Instant::now();
                    let relation = require_payload_str(&record.payload, "relation")?;
                    ensure_allowed_content_relation(relation)?;
                    let row = require_payload_value(&record.payload, "row")?;
                    self.put_relation_row(relation, row.clone())?;
                    report.relation_upserts += 1;
                    if relation == "scoped_documents" {
                        report.scoped_document_upserts += 1;
                    }
                    report.relation_ms += elapsed_millis(started);
                    lex_dirty |= relation_touches_lex_index(relation);
                }
                "relation:delete" => {
                    let started = Instant::now();
                    let relation = require_payload_str(&record.payload, "relation")?;
                    ensure_allowed_content_relation(relation)?;
                    let filter = payload_object(record.payload.get("filter"));
                    let rows = self.fetch_relation_rows(relation)?;
                    let matched = rows
                        .into_iter()
                        .filter(|row| row_matches_filter(row, filter))
                        .collect::<Vec<_>>();
                    let _ = self.delete_relation_rows(relation, &matched)?;
                    report.relation_deletes += 1;
                    report.relation_ms += elapsed_millis(started);
                    lex_dirty |= relation_touches_lex_index(relation);
                }
                "entityCards:upsertBatch" => {
                    let cards: Vec<EntityCard> = serde_json::from_value(
                        record
                            .payload
                            .get("cards")
                            .cloned()
                            .unwrap_or_else(|| Value::Array(Vec::new())),
                    )
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                    self.upsert_entity_cards_batch(&cards)?;
                }
                "folderSchema:upsert" => {
                    let schema: FolderSchema = serde_json::from_value(
                        record.payload.get("schema").cloned().unwrap_or(Value::Null),
                    )
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                    self.upsert_folder_schema(&schema)?;
                }
                "networkView:save" => {
                    let view: SavedNetworkView = serde_json::from_value(
                        record.payload.get("view").cloned().unwrap_or(Value::Null),
                    )
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                    self.save_network_view(&view)?;
                }
                "networkView:delete" => {
                    let id = require_payload_str(&record.payload, "id")?;
                    self.delete_network_view(id)?;
                }
                other => {
                    return Err(StoreError::Query(format!(
                        "unsupported WAL command: {other}"
                    )));
                }
            }
        }

        if lex_dirty {
            let started = Instant::now();
            self.rebuild_lex_index()?;
            report.lex_rebuilt = true;
            report.lex_ms = elapsed_millis(started);
        }
        report.total_ms = elapsed_millis(total_started);
        Ok(report)
    }

    pub fn boot_snapshot_rows(&self) -> Result<PhoenixBootSnapshotRows, StoreError> {
        let note_headers = self.list_note_values(None, false)?;
        let event_note_ids = note_headers
            .iter()
            .filter(|row| row.get("entity_kind").and_then(Value::as_str) == Some("EVENT"))
            .filter_map(|row| row.get("id").and_then(Value::as_str).map(str::to_owned))
            .collect::<Vec<_>>();

        Ok(PhoenixBootSnapshotRows {
            event_notes: self.list_note_values_by_ids(&event_note_ids, true)?,
            note_headers,
            entities: self.fetch_store_command_relation_rows("entities")?,
            edges: self.fetch_store_command_relation_rows("edges")?,
            folders: self.fetch_store_command_relation_rows("folders")?,
        })
    }

    pub fn init_chat_config(&self, config: ChatRuntimeConfig) -> ChatRuntimeConfig {
        self.chat.init_config(config)
    }

    pub fn store_command(
        &self,
        request: StoreCommandRequest,
    ) -> Result<StoreCommandResult, StoreError> {
        if self.native_graph_enabled()
            && request.command != "runtime:capabilities"
            && request.command.starts_with("om:")
        {
            return Ok(StoreCommandResult {
                success: false,
                payload: None,
                error: Some(format!(
                    "{} is unavailable on the native runtime path",
                    request.command
                )),
            });
        }
        match request.command.as_str() {
            "documentGraph:commit" => document_graph_commit::commit(self, &request.payload),
            "documentGraph:undo" => document_graph_commit::undo(self, &request.payload),
            "relation:upsert" => {
                let relation = require_payload_str(&request.payload, "relation")?;
                let row = require_payload_value(&request.payload, "row")?;
                self.put_relation_row(relation, row.clone())?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "relation:getFirst" => {
                let relation = require_payload_str(&request.payload, "relation")?;
                let filter = payload_object(request.payload.get("filter"));
                let row = self
                    .fetch_store_command_relation_rows(relation)?
                    .into_iter()
                    .find(|row| row_matches_filter(row, filter));
                Ok(StoreCommandResult {
                    success: true,
                    payload: row,
                    error: None,
                })
            }
            "relation:list" => {
                let relation = require_payload_str(&request.payload, "relation")?;
                let filter = payload_object(request.payload.get("filter"));
                let rows = self
                    .fetch_store_command_relation_rows(relation)?
                    .into_iter()
                    .filter(|row| row_matches_filter(row, filter))
                    .collect::<Vec<_>>();
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(Value::Array(rows)),
                    error: None,
                })
            }
            "relation:delete" => {
                let relation = require_payload_str(&request.payload, "relation")?;
                let filter = payload_object(request.payload.get("filter"));
                let rows = self.fetch_relation_rows(relation)?;
                let matched = rows
                    .into_iter()
                    .filter(|row| row_matches_filter(row, filter))
                    .collect::<Vec<_>>();
                let deleted = self.delete_relation_rows(relation, &matched)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(serde_json::json!({ "deleted": deleted })),
                    error: None,
                })
            }
            "graph:repairLiveTopology" => {
                let pruned_documents = self.prune_native_graph_to_live_notes()?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(serde_json::json!({ "prunedDocuments": pruned_documents })),
                    error: None,
                })
            }
            "graph:overgraphStatus" => {
                #[cfg(not(target_arch = "wasm32"))]
                {
                    let payload = self
                        .overgraph_lane
                        .as_ref()
                        .map(|lane| {
                            serde_json::json!({
                                "bound": true,
                                "path": lane.path().to_string_lossy(),
                            })
                        })
                        .unwrap_or_else(|| serde_json::json!({ "bound": false }));
                    Ok(StoreCommandResult {
                        success: true,
                        payload: Some(payload),
                        error: None,
                    })
                }
                #[cfg(target_arch = "wasm32")]
                {
                    Ok(StoreCommandResult {
                        success: true,
                        payload: Some(serde_json::json!({ "bound": false, "target": "wasm" })),
                        error: None,
                    })
                }
            }
            "graph:upsertNode" => {
                let id = require_payload_str(&request.payload, "id")?;
                let kind = request
                    .payload
                    .get("kind")
                    .and_then(Value::as_str)
                    .unwrap_or("custom");
                let label = request
                    .payload
                    .get("label")
                    .and_then(Value::as_str)
                    .unwrap_or(id);
                let props = request
                    .payload
                    .get("props")
                    .cloned()
                    .unwrap_or_else(|| json!({}));
                self.put_relation_row(
                    "graph_vertices",
                    json!({
                        "id": id,
                        "value": { "id": id, "kind": kind, "label": label },
                        "weight": 1,
                        "attributes": props,
                    }),
                )?;
                self.put_relation_row(
                    "graph_vertex_labels",
                    json!({
                        "vertex_id": id,
                        "label": label,
                    }),
                )?;
                #[cfg(all(not(target_arch = "wasm32"), feature = "legacy-cozo-graph"))]
                let report = self.sync_overgraph_lane_from_graph_rows()?;
                #[cfg(all(not(target_arch = "wasm32"), not(feature = "legacy-cozo-graph")))]
                let report: Option<Value> = None;
                #[cfg(target_arch = "wasm32")]
                let report: Option<Value> = None;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(json!({ "overgraph": report })),
                    error: None,
                })
            }
            "graph:upsertEdge" => {
                let source = require_payload_str(&request.payload, "source")?;
                let target = require_payload_str(&request.payload, "target")?;
                let edge_type = request
                    .payload
                    .get("edgeType")
                    .or_else(|| request.payload.get("relation"))
                    .and_then(Value::as_str)
                    .unwrap_or("edge");
                let weight = request
                    .payload
                    .get("weight")
                    .and_then(Value::as_i64)
                    .unwrap_or(1);
                let props = request
                    .payload
                    .get("props")
                    .cloned()
                    .unwrap_or_else(|| json!({}));
                self.put_relation_row(
                    "graph_edges",
                    json!({
                        "source_id": source,
                        "target_id": target,
                        "edge_type": edge_type,
                        "weight": weight,
                        "attributes": props,
                        "data": null,
                    }),
                )?;
                #[cfg(all(not(target_arch = "wasm32"), feature = "legacy-cozo-graph"))]
                let report = self.sync_overgraph_lane_from_graph_rows()?;
                #[cfg(all(not(target_arch = "wasm32"), not(feature = "legacy-cozo-graph")))]
                let report: Option<Value> = None;
                #[cfg(target_arch = "wasm32")]
                let report: Option<Value> = None;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(json!({ "overgraph": report })),
                    error: None,
                })
            }
            "note:upsert" => {
                let row = require_payload_value(&request.payload, "row")?;
                self.upsert_note_row(row)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "note:get" => {
                let id = require_payload_str(&request.payload, "id")?;
                let include_body = payload_bool(request.payload.get("includeBody"), true);
                let note = self.get_note_value(id, include_body)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: note,
                    error: None,
                })
            }
            "note:list" => {
                let folder_id = request.payload.get("folderId").and_then(Value::as_str);
                let include_body = payload_bool(request.payload.get("includeBody"), true);
                let notes = self.list_note_values(folder_id, include_body)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(Value::Array(notes)),
                    error: None,
                })
            }
            "note:listByIds" => {
                let ids = payload_string_array(request.payload.get("ids"));
                let include_body = payload_bool(request.payload.get("includeBody"), true);
                let notes = self.list_note_values_by_ids(&ids, include_body)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(Value::Array(notes)),
                    error: None,
                })
            }
            "note:delete" => {
                let id = require_payload_str(&request.payload, "id")?;
                let deleted = self.delete_note_rows(id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(serde_json::json!({ "deleted": deleted })),
                    error: None,
                })
            }
            "runtime:capabilities" => Ok(StoreCommandResult {
                success: true,
                payload: Some(serde_json::json!({
                    "storeApiVersion": STORE_API_VERSION,
                    "capabilities": RUNTIME_CAPABILITIES,
                })),
                error: None,
            }),
            "session:close" => {
                let session_id = require_payload_str(&request.payload, "sessionId")?;
                let deleted = self.close_session(session_id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(serde_json::json!({ "deleted": deleted })),
                    error: None,
                })
            }
            "persistence:applyWalBatch" => {
                let parse_started = Instant::now();
                let batch: PersistenceWalBatchRequest = serde_json::from_value(request.payload)
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                let parse_ms = elapsed_millis(parse_started);
                let mut report = self.apply_persistence_wal_batch(&batch.records)?;
                report.parse_ms = parse_ms;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(serde_json::json!({
                        "replayed": batch.records.len(),
                        "timings": report,
                    })),
                    error: None,
                })
            }
            "persistence:flushNativeStore" => {
                #[cfg(not(target_arch = "wasm32"))]
                {
                    let report = self.flush_native_store()?;
                    Ok(StoreCommandResult {
                        success: true,
                        payload: Some(serde_json::json!({
                            "flushed": report.flushed,
                            "walBytesBefore": report.wal_bytes_before,
                            "walBytesAfter": report.wal_bytes_after,
                            "segmentCount": report.segment_count,
                        })),
                        error: None,
                    })
                }
                #[cfg(target_arch = "wasm32")]
                {
                    Err(StoreError::Query(
                        "native store flush is unavailable on wasm".to_owned(),
                    ))
                }
            }
            "persistence:clearDerived" => {
                self.clear_derived_partition()?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "persistence:clearDerivedEphemera" => {
                self.clear_derived_ephemera()?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "chat:init" => {
                let config: ChatRuntimeConfig = serde_json::from_value(
                    request
                        .payload
                        .get("config")
                        .cloned()
                        .unwrap_or(Value::Null),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let config = self.init_chat_config(config);
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(config)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:createThread" => {
                let world_id = request.payload.get("worldId").and_then(Value::as_str);
                let narrative_id = request.payload.get("narrativeId").and_then(Value::as_str);
                let title = request.payload.get("title").and_then(Value::as_str);
                let thread =
                    self.chat
                        .create_thread(self.chat_store()?, world_id, narrative_id, title)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(thread)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:getThread" => {
                let id = require_payload_str(&request.payload, "id")?;
                let thread = self.chat.get_thread(self.chat_store()?, id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: thread
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:listThreads" => {
                let world_id = request.payload.get("worldId").and_then(Value::as_str);
                let threads = self.chat.list_threads(self.chat_store()?, world_id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(threads)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:deleteThread" => {
                let id = require_payload_str(&request.payload, "id")?;
                self.chat.delete_thread(self.chat_store()?, id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "chat:addMessage" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let role = require_payload_str(&request.payload, "role")?;
                let content = request
                    .payload
                    .get("content")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let narrative_id = request.payload.get("narrativeId").and_then(Value::as_str);
                let message = self.chat.add_message(
                    self.chat_store()?,
                    thread_id,
                    role,
                    content,
                    narrative_id,
                )?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(message)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:listMessages" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let messages = self.chat.list_messages(self.chat_store()?, thread_id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(messages)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:updateMessage" => {
                let message_id = require_payload_str(&request.payload, "messageId")?;
                let content = request
                    .payload
                    .get("content")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let message = self
                    .chat
                    .update_message(self.chat_store()?, message_id, content)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: message
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:appendMessage" => {
                let message_id = require_payload_str(&request.payload, "messageId")?;
                let chunk = request
                    .payload
                    .get("chunk")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let message = self
                    .chat
                    .append_message(self.chat_store()?, message_id, chunk)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: message
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:startStreamingMessage" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let narrative_id = request.payload.get("narrativeId").and_then(Value::as_str);
                let message = self.chat.start_streaming_message(
                    self.chat_store()?,
                    thread_id,
                    narrative_id,
                )?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(message)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:clearThread" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                self.chat.clear_thread(self.chat_store()?, thread_id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "chat:exportThread" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let exported = self.chat.export_thread(self.chat_store()?, thread_id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(Value::String(exported)),
                    error: None,
                })
            }
            "chat:startRun" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let prompt = request
                    .payload
                    .get("prompt")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let options: RunOptions = serde_json::from_value(
                    request
                        .payload
                        .get("options")
                        .cloned()
                        .unwrap_or(Value::Null),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let run = self
                    .chat
                    .start_run(self.chat_store()?, thread_id, prompt, options)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(run)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:pollRun" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let snapshot =
                    self.chat
                        .poll_run(self.chat_store()?, run_id)?
                        .map(|mut snapshot| {
                            snapshot.planner_step = self.planner.peek_step(run_id);
                            if let Ok(artifacts) = list_run_artifacts(self, &snapshot.run) {
                                snapshot.artifacts = artifacts;
                            }
                            snapshot
                        });
                Ok(StoreCommandResult {
                    success: true,
                    payload: snapshot
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:resumeRun" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let run = self.chat.resume_run(self.chat_store()?, run_id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: run
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:cancelRun" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                self.planner.drop_session(run_id);
                let run = self.chat.cancel_run(self.chat_store()?, run_id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: run
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:listRunEvents" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let limit = request
                    .payload
                    .get("limit")
                    .and_then(Value::as_u64)
                    .unwrap_or(100) as usize;
                let events =
                    self.chat
                        .list_run_events_for_thread(self.chat_store()?, thread_id, limit)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(events)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:markRunStreaming" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let assistant_message_id =
                    require_payload_str(&request.payload, "assistantMessageId")?;
                let snapshot = self.chat.mark_run_streaming(
                    self.chat_store()?,
                    run_id,
                    assistant_message_id,
                )?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: snapshot
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:completeRun" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                self.planner.drop_session(run_id);
                let assistant_message_id =
                    require_payload_str(&request.payload, "assistantMessageId")?;
                let final_response = request
                    .payload
                    .get("finalResponse")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let final_error = request.payload.get("finalError").and_then(Value::as_str);
                let snapshot = self.chat.complete_run(
                    self.chat_store()?,
                    run_id,
                    assistant_message_id,
                    final_response,
                    final_error,
                )?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: snapshot
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:getPlannerStep" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let run = self
                    .chat
                    .get_run(self.chat_store()?, run_id)?
                    .ok_or_else(|| StoreError::Query(format!("run not found: {run_id}")))?;
                let step = self.planner.get_step(self, &run)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: step
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:submitPlannerModelResponse" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let response: ChatPlannerModelResponse = serde_json::from_value(
                    request
                        .payload
                        .get("response")
                        .cloned()
                        .unwrap_or(Value::Null),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let run = self
                    .chat
                    .get_run(self.chat_store()?, run_id)?
                    .ok_or_else(|| StoreError::Query(format!("run not found: {run_id}")))?;
                let step = self.planner.submit_model_response(self, &run, response)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: step
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:advancePlannerRun" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let run = self
                    .chat
                    .get_run(self.chat_store()?, run_id)?
                    .ok_or_else(|| StoreError::Query(format!("run not found: {run_id}")))?;
                let step = self.planner.advance(self, &run)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: step
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:degradePlannerRun" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let reason = request
                    .payload
                    .get("reason")
                    .and_then(Value::as_str)
                    .unwrap_or("Planner failed.");
                let run = self
                    .chat
                    .get_run(self.chat_store()?, run_id)?
                    .ok_or_else(|| StoreError::Query(format!("run not found: {run_id}")))?;
                self.planner.degrade_run(self, &run, reason, None)?;
                self.planner.drop_session(run_id);
                let snapshot =
                    self.chat
                        .poll_run(self.chat_store()?, run_id)?
                        .map(|mut snapshot| {
                            snapshot.planner_step = self.planner.peek_step(run_id);
                            if let Ok(artifacts) = list_run_artifacts(self, &snapshot.run) {
                                snapshot.artifacts = artifacts;
                            }
                            snapshot
                        });
                Ok(StoreCommandResult {
                    success: true,
                    payload: snapshot
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:listPlannerArtifacts" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let run = self
                    .chat
                    .get_run(self.chat_store()?, run_id)?
                    .ok_or_else(|| StoreError::Query(format!("run not found: {run_id}")))?;
                let artifacts = list_run_artifacts(self, &run)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(artifacts)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:pinPlannerArtifact" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let key = require_payload_str(&request.payload, "key")?;
                let pinned = request
                    .payload
                    .get("pinned")
                    .and_then(Value::as_bool)
                    .unwrap_or(true);
                let run = self
                    .chat
                    .get_run(self.chat_store()?, run_id)?
                    .ok_or_else(|| StoreError::Query(format!("run not found: {run_id}")))?;
                let Some(artifact) = set_artifact_pinned(self, &run, key, pinned)? else {
                    return Err(StoreError::Query(format!("artifact not found: {key}")));
                };
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(artifact)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:prepareOm" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let config = OmEngine::config_from_runtime(&self.chat.current_config());
                #[cfg(feature = "legacy-cozo-graph")]
                let action = self
                    .om_engine
                    .prepare_pending_action_with_graph(
                        &self.store,
                        &self.scanner,
                        &self.structure,
                        &self.om_bridge,
                        thread_id,
                        &config,
                    )
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                #[cfg(not(feature = "legacy-cozo-graph"))]
                let action = self
                    .om_engine
                    .prepare_pending_action(self.om_store()?, thread_id, &config)
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: action
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "chat:applyOmAction" => {
                let action: OmPendingAction = serde_json::from_value(
                    request
                        .payload
                        .get("action")
                        .cloned()
                        .unwrap_or(Value::Null),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let response = request
                    .payload
                    .get("response")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                #[cfg(feature = "legacy-cozo-graph")]
                let config = OmEngine::config_from_runtime(&self.chat.current_config());
                #[cfg(feature = "legacy-cozo-graph")]
                let applied = self
                    .om_engine
                    .apply_pending_action_with_graph(
                        &self.store,
                        &self.scanner,
                        &self.structure,
                        &self.om_bridge,
                        &config,
                        &action,
                        response,
                    )
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                #[cfg(not(feature = "legacy-cozo-graph"))]
                let applied = self
                    .om_engine
                    .apply_pending_action(self.om_store()?, &action, response)
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(Value::Bool(applied)),
                    error: None,
                })
            }
            "om:startReflector" => {
                let action: OmPendingAction = serde_json::from_value(
                    request
                        .payload
                        .get("action")
                        .cloned()
                        .unwrap_or(Value::Null),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let step = self
                    .om_engine
                    .start_reflector(&action)
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(step)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "om:submitReflectorModelResponse" => {
                let session_id = require_payload_str(&request.payload, "sessionId")?;
                let response: OmReflectorModelResponse = serde_json::from_value(
                    request
                        .payload
                        .get("response")
                        .cloned()
                        .unwrap_or(Value::Null),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let step = self
                    .om_engine
                    .submit_reflector_model_response(session_id, response)
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(step)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "om:submitReflectorToolResults" => {
                let session_id = require_payload_str(&request.payload, "sessionId")?;
                let results: Vec<OmReflectorToolResult> = serde_json::from_value(
                    request
                        .payload
                        .get("results")
                        .cloned()
                        .unwrap_or_else(|| Value::Array(Vec::new())),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let step = self
                    .om_engine
                    .submit_reflector_tool_results(session_id, &results)
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(step)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "om:dropReflectorSession" => {
                let session_id = require_payload_str(&request.payload, "sessionId")?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(Value::Bool(
                        self.om_engine.drop_reflector_session(session_id),
                    )),
                    error: None,
                })
            }
            "om:recoverLostMemory" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let limit = request
                    .payload
                    .get("limit")
                    .and_then(Value::as_u64)
                    .unwrap_or(10) as usize;
                let focus = request.payload.get("focus").and_then(Value::as_str);
                #[cfg(feature = "legacy-cozo-graph")]
                let hits = self
                    .om_bridge
                    .recover_lost_memory(&self.store, thread_id, limit, focus)
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                #[cfg(not(feature = "legacy-cozo-graph"))]
                let hits: Vec<Value> = {
                    let _ = (thread_id, limit, focus);
                    Vec::new()
                };
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(hits)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "om:memoryGraphSearch" => {
                let thread_id = require_payload_str(&request.payload, "threadId")?;
                let query = request
                    .payload
                    .get("query")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let limit = request
                    .payload
                    .get("limit")
                    .and_then(Value::as_u64)
                    .unwrap_or(10) as usize;
                #[cfg(feature = "legacy-cozo-graph")]
                let hits = self
                    .om_bridge
                    .memory_graph_search(&self.store, thread_id, query, limit)
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                #[cfg(not(feature = "legacy-cozo-graph"))]
                let hits: Vec<Value> = {
                    let _ = (thread_id, query, limit);
                    Vec::new()
                };
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(hits)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "semantic:runEmbedderTruthReview" => {
                let review_request: SemanticTruthReviewRequest =
                    serde_json::from_value(request.payload).map_err(|error| {
                        StoreError::Query(format!("invalid semantic truth review request: {error}"))
                    })?;
                let response = self.run_embedder_truth_review(review_request)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(response)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "semantic:listLeafChunks" => {
                let document_ids = request
                    .payload
                    .get("documentIds")
                    .and_then(Value::as_array)
                    .map(|values| {
                        values
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_owned)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let chunks = self.semantic_leaf_chunks_for_documents(&document_ids)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(chunks)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "semantic:listCandidatePrototypeInputs" => {
                let document_ids = request
                    .payload
                    .get("documentIds")
                    .and_then(Value::as_array)
                    .map(|values| {
                        values
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_owned)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let rows = self.list_candidate_prototype_inputs(&document_ids)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(rows)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "semantic:listNliJudgmentInputs" => {
                let document_ids = request
                    .payload
                    .get("documentIds")
                    .and_then(Value::as_array)
                    .map(|values| {
                        values
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_owned)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let node_ids = request
                    .payload
                    .get("nodeIds")
                    .and_then(Value::as_array)
                    .map(|values| {
                        values
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_owned)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let rows = self.list_nli_judgment_inputs(&document_ids, &node_ids)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(rows)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "semantic:upsertDocumentVectors" => {
                let rows: Vec<SemanticDocumentVectorUpsertRow> = serde_json::from_value(
                    request
                        .payload
                        .get("rows")
                        .cloned()
                        .unwrap_or_else(|| Value::Array(Vec::new())),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let updated_at = now_ms();
                let inserted = rows.len();
                if self.native_graph_enabled() {
                    let values = rows
                        .iter()
                        .map(|row| {
                            json!({
                                "document_id": row.document_id.clone(),
                                "vec": row.values.clone(),
                                "model_id": SEMANTIC_MODEL_ID,
                                "leaf_count": row.leaf_count as i64,
                                "evidence_refs": row.evidence_refs.clone(),
                                "updated_at": updated_at,
                            })
                        })
                        .collect::<Vec<_>>();
                    self.upsert_native_relation_rows("semantic_documents", &values)?;
                } else {
                    #[cfg(feature = "legacy-cozo-graph")]
                    {
                        let vectors = rows
                            .iter()
                            .map(|row| phoenix_store_cozo::SemanticDocumentVectorRow {
                                document_id: row.document_id.as_str(),
                                values: row.values.as_slice(),
                                model_id: phoenix_store_cozo::SEMANTIC_MODEL_ID,
                                leaf_count: row.leaf_count,
                                evidence_refs: row.evidence_refs.as_slice(),
                                updated_at,
                            })
                            .collect::<Vec<_>>();
                        self.store.upsert_semantic_document_vectors(&vectors)?;
                    }
                    #[cfg(not(feature = "legacy-cozo-graph"))]
                    {
                        return Err(self.legacy_graph_disabled("legacy semantic document vectors"));
                    }
                }
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(serde_json::json!({
                        "inserted": inserted,
                        "modelId": SEMANTIC_MODEL_ID,
                        "dimension": SEMANTIC_VECTOR_DIM,
                    })),
                    error: None,
                })
            }
            "semantic:upsertPrototypeVectors" => {
                let rows: Vec<SemanticNodeVectorUpsertRow> = serde_json::from_value(
                    request
                        .payload
                        .get("rows")
                        .cloned()
                        .unwrap_or_else(|| Value::Array(Vec::new())),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let updated_at = now_ms();
                let inserted = rows.len();
                if self.native_graph_enabled() {
                    let values = rows
                        .iter()
                        .map(|row| {
                            json!({
                                "node_id": row.node_id.clone(),
                                "node_kind": row.node_kind.clone(),
                                "document_id": row.document_id.clone(),
                                "narrative_id": row.narrative_id.clone(),
                                "folder_id": row.folder_id.clone(),
                                "vec": row.values.clone(),
                                "model_id": SEMANTIC_MODEL_ID,
                                "evidence_refs": row.evidence_refs.clone(),
                                "updated_at": updated_at,
                            })
                        })
                        .collect::<Vec<_>>();
                    self.upsert_native_relation_rows("semantic_node_prototypes", &values)?;
                } else {
                    #[cfg(feature = "legacy-cozo-graph")]
                    {
                        let vectors = rows
                            .iter()
                            .map(|row| phoenix_store_cozo::SemanticNodeVectorRow {
                                node_id: row.node_id.as_str(),
                                node_kind: row.node_kind.as_str(),
                                document_id: row.document_id.as_deref(),
                                narrative_id: row.narrative_id.as_deref(),
                                folder_id: row.folder_id.as_deref(),
                                values: row.values.as_slice(),
                                model_id: phoenix_store_cozo::SEMANTIC_MODEL_ID,
                                evidence_refs: row.evidence_refs.as_slice(),
                                updated_at,
                            })
                            .collect::<Vec<_>>();
                        self.store.upsert_semantic_node_vectors(&vectors)?;
                    }
                    #[cfg(not(feature = "legacy-cozo-graph"))]
                    {
                        return Err(self.legacy_graph_disabled("legacy semantic node vectors"));
                    }
                }
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(serde_json::json!({
                        "inserted": inserted,
                        "modelId": SEMANTIC_MODEL_ID,
                        "dimension": SEMANTIC_VECTOR_DIM,
                    })),
                    error: None,
                })
            }
            "semantic:refreshCandidateGraphEdges" => {
                let document_ids = request
                    .payload
                    .get("documentIds")
                    .and_then(Value::as_array)
                    .map(|values| {
                        values
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_owned)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let node_ids = request
                    .payload
                    .get("nodeIds")
                    .and_then(Value::as_array)
                    .map(|values| {
                        values
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_owned)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let refreshed = self.refresh_candidate_graph_edges(&document_ids, &node_ids)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(serde_json::json!({
                        "inserted": refreshed,
                    })),
                    error: None,
                })
            }
            "semantic:applyNliJudgments" => {
                let model_id = request
                    .payload
                    .get("modelId")
                    .and_then(Value::as_str)
                    .unwrap_or(SEMANTIC_NLI_MODEL_ID);
                let device = request.payload.get("device").and_then(Value::as_str);
                let rows: Vec<SemanticNliJudgmentResultRow> = serde_json::from_value(
                    request
                        .payload
                        .get("results")
                        .cloned()
                        .unwrap_or_else(|| Value::Array(Vec::new())),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                let payload = self.apply_nli_judgments(model_id, device, rows)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(payload),
                    error: None,
                })
            }
            "chat:submitToolResults" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let results: Vec<ToolResultSubmission> = serde_json::from_value(
                    request
                        .payload
                        .get("results")
                        .cloned()
                        .unwrap_or_else(|| Value::Array(Vec::new())),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                self.planner.drop_session(run_id);
                let snapshot = self
                    .chat
                    .submit_tool_results(self.chat_store()?, run_id, &results)
                    .map(|mut snapshot| {
                        snapshot.planner_step = self.planner.peek_step(run_id);
                        if let Ok(artifacts) = list_run_artifacts(self, &snapshot.run) {
                            snapshot.artifacts = artifacts;
                        }
                        snapshot
                    })?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(snapshot)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "chat:submitApproval" => {
                let run_id = require_payload_str(&request.payload, "runId")?;
                let approval_id = require_payload_str(&request.payload, "approvalId")?;
                let approved = request
                    .payload
                    .get("approved")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
                let decision_json = request.payload.get("decisionJson").and_then(Value::as_str);
                self.planner.drop_session(run_id);
                let snapshot = self
                    .chat
                    .submit_approval(
                        self.chat_store()?,
                        run_id,
                        approval_id,
                        approved,
                        decision_json,
                    )
                    .map(|mut snapshot| {
                        snapshot.planner_step = self.planner.peek_step(run_id);
                        if let Ok(artifacts) = list_run_artifacts(self, &snapshot.run) {
                            snapshot.artifacts = artifacts;
                        }
                        snapshot
                    })?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(snapshot)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "entityCards:upsertBatch" => {
                let cards: Vec<EntityCard> = serde_json::from_value(
                    request
                        .payload
                        .get("cards")
                        .cloned()
                        .unwrap_or_else(|| Value::Array(Vec::new())),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                self.upsert_entity_cards_batch(&cards)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "entityCards:get" => {
                let entity_id = require_payload_str(&request.payload, "entityId")?;
                let cards =
                    self.get_entity_cards(&phoenix_types::EntityId(entity_id.to_owned()))?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(cards)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "folderSchema:upsert" => {
                let schema: FolderSchema = serde_json::from_value(
                    request
                        .payload
                        .get("schema")
                        .cloned()
                        .unwrap_or(Value::Null),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                self.upsert_folder_schema(&schema)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "folderSchema:get" => {
                let id = require_payload_str(&request.payload, "id")?;
                let schema = self.get_folder_schema(id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: schema
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "networkView:save" => {
                let view: SavedNetworkView = serde_json::from_value(
                    request.payload.get("view").cloned().unwrap_or(Value::Null),
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
                self.save_network_view(&view)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            "networkView:get" => {
                let id = require_payload_str(&request.payload, "id")?;
                let view = self.get_network_view(id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: view
                        .map(|value| {
                            serde_json::to_value(value)
                                .map_err(|error| StoreError::Query(error.to_string()))
                        })
                        .transpose()?,
                    error: None,
                })
            }
            "networkView:list" => {
                let views = self.list_network_views()?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: Some(
                        serde_json::to_value(views)
                            .map_err(|error| StoreError::Query(error.to_string()))?,
                    ),
                    error: None,
                })
            }
            "networkView:delete" => {
                let id = require_payload_str(&request.payload, "id")?;
                self.delete_network_view(id)?;
                Ok(StoreCommandResult {
                    success: true,
                    payload: None,
                    error: None,
                })
            }
            other => Ok(StoreCommandResult {
                success: false,
                payload: None,
                error: Some(format!("unsupported store command: {other}")),
            }),
        }
    }

    fn upsert_note_row(&self, row: &Value) -> Result<(), StoreError> {
        let id = row
            .get("id")
            .and_then(Value::as_str)
            .ok_or_else(|| StoreError::Query("missing store command field: row.id".to_owned()))?;
        if self.native_graph_enabled() {
            self.native_row_store()?.put_row("notes", row.clone())?;
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let existing = self.legacy_store("notes")?.fetch_compact_rows_where_str(
                    "notes",
                    NOTE_KEY_COLUMNS,
                    "id",
                    id,
                )?;
                if !existing.is_empty() {
                    self.legacy_store("notes")?
                        .delete_key_rows("notes", &existing)?;
                }
                self.put_relation_row("notes", row.clone())?;
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                let _ = id;
                return Err(self.legacy_graph_disabled("legacy notes"));
            }
        }
        Ok(())
    }

    pub(crate) fn get_note_value(
        &self,
        id: &str,
        include_body: bool,
    ) -> Result<Option<Value>, StoreError> {
        if self.native_graph_enabled() {
            let rows = self
                .fetch_relation_rows("notes")?
                .into_iter()
                .filter(|row| row.get("id").and_then(Value::as_str) == Some(id))
                .collect::<Vec<_>>();
            Ok(select_latest_note_value(rows, include_body))
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let columns = note_columns(include_body);
                let rows = self
                    .legacy_store("notes")?
                    .fetch_compact_rows_where_str("notes", columns, "id", id)?;
                Ok(select_latest_note(&rows, columns)
                    .map(|view| note_value_from_row(view, include_body)))
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy notes"))
            }
        }
    }

    pub(crate) fn list_note_values(
        &self,
        folder_id: Option<&str>,
        include_body: bool,
    ) -> Result<Vec<Value>, StoreError> {
        if self.native_graph_enabled() {
            Ok(note_values_from_value_rows(
                self.fetch_relation_rows("notes")?,
                folder_id,
                include_body,
            ))
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let columns = note_columns(include_body);
                let rows = match folder_id {
                    Some(value) if !value.is_empty() => self
                        .legacy_store("notes")?
                        .fetch_compact_rows_where_str("notes", columns, "folder_id", value)?,
                    _ => self
                        .legacy_store("notes")?
                        .fetch_compact_rows_with_columns("notes", columns)?,
                };
                Ok(note_values_from_rows(
                    rows,
                    columns,
                    folder_id,
                    include_body,
                ))
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy notes"))
            }
        }
    }

    pub(crate) fn list_note_values_by_ids(
        &self,
        ids: &[String],
        include_body: bool,
    ) -> Result<Vec<Value>, StoreError> {
        if ids.is_empty() {
            return Ok(Vec::new());
        }
        if self.native_graph_enabled() {
            let ids = ids.iter().map(String::as_str).collect::<HashSet<_>>();
            let rows = self
                .fetch_relation_rows("notes")?
                .into_iter()
                .filter(|row| {
                    row.get("id")
                        .and_then(Value::as_str)
                        .map(|id| ids.contains(id))
                        .unwrap_or(false)
                })
                .collect::<Vec<_>>();
            Ok(note_values_from_value_rows(rows, None, include_body))
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let columns = note_columns(include_body);
                let rows = self
                    .legacy_store("notes")?
                    .fetch_compact_rows_where_in_strings("notes", columns, "id", ids)?;
                Ok(note_values_from_rows(rows, columns, None, include_body))
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy notes"))
            }
        }
    }

    fn delete_note_rows(&self, id: &str) -> Result<usize, StoreError> {
        if self.native_graph_enabled() {
            let rows = self
                .fetch_relation_rows("notes")?
                .into_iter()
                .filter(|row| row.get("id").and_then(Value::as_str) == Some(id))
                .collect::<Vec<_>>();
            self.delete_relation_rows("notes", &rows)
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                let rows = self.legacy_store("notes")?.fetch_compact_rows_where_str(
                    "notes",
                    NOTE_KEY_COLUMNS,
                    "id",
                    id,
                )?;
                let deleted = rows.len();
                if deleted > 0 {
                    self.legacy_store("notes")?
                        .delete_key_rows("notes", &rows)?;
                }
                Ok(deleted)
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                Err(self.legacy_graph_disabled("legacy notes"))
            }
        }
    }

    pub fn session_state_binary(&self, session_id: &SessionId) -> Result<Vec<u8>, StoreError> {
        let state = self.session_state(session_id)?;
        binary::encode_session_state(&state)
    }

    pub fn session_state_binary_into(
        &self,
        session_id: &SessionId,
        buffer: &mut [u8],
    ) -> Result<usize, StoreError> {
        let state = self.session_state(session_id)?;
        binary::encode_session_state_into(buffer, &state)
    }

    pub fn session_stats_binary(&self, session_id: &SessionId) -> Result<Vec<u8>, StoreError> {
        let stats = self.session_stats(session_id)?;
        binary::encode_session_stats(&stats)
    }

    pub fn session_stats_binary_into(
        &self,
        session_id: &SessionId,
        buffer: &mut [u8],
    ) -> Result<usize, StoreError> {
        let stats = self.session_stats(session_id)?;
        binary::encode_session_stats_into(buffer, &stats)
    }

    fn ensure_lex_index(&self) -> Result<(), StoreError> {
        if self.lex.borrow().is_none() {
            self.rebuild_lex_index()?;
        }
        Ok(())
    }

    fn rebuild_lex_index(&self) -> Result<usize, StoreError> {
        let spans = if self.native_graph_enabled() {
            self.native_note_rows_to_indexed_spans()?
        } else {
            #[cfg(feature = "legacy-cozo-graph")]
            {
                indexed_spans_from_store(&self.store)?
            }
            #[cfg(not(feature = "legacy-cozo-graph"))]
            {
                return Err(self.legacy_graph_disabled("legacy lexical rebuild"));
            }
        };
        self.native_scope_lex.borrow_mut().clear();
        let mut borrow = self.lex.borrow_mut();
        let span_count = spans.len();
        let span_count = if let Some(index) = borrow.as_mut() {
            index.rebuild_from_spans(&spans);
            span_count
        } else {
            let mut index = LexIndex::default();
            index.rebuild_from_spans(&spans);
            *borrow = Some(index);
            span_count
        };
        Ok(span_count)
    }

    fn invalidate_lex_caches(&self) {
        *self.lex.borrow_mut() = None;
        self.native_scope_lex.borrow_mut().clear();
    }

    fn native_note_rows_to_indexed_spans(&self) -> Result<Vec<IndexedSpan>, StoreError> {
        let mut spans = Vec::new();
        for row in self.fetch_relation_rows("notes")? {
            if row.get("deleted").and_then(Value::as_bool).unwrap_or(false) {
                continue;
            }
            let Some(id) = row.get("id").and_then(Value::as_str) else {
                continue;
            };
            let title = row
                .get("title")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned();
            let body = row
                .get("body")
                .or_else(|| row.get("content"))
                .or_else(|| row.get("markdown_content"))
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned();
            spans.push(IndexedSpan {
                span_id: format!("note::{id}"),
                note_id: Some(NoteId(id.to_owned())),
                document_id: Some(DocumentId(id.to_owned())),
                scope: ScopeKey {
                    world_id: row
                        .get("world_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    narrative_id: row
                        .get("narrative_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    folder_id: row
                        .get("folder_id")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    folder_path: None,
                },
                fields: vec![
                    IndexedTextField {
                        field: LexicalField::Title,
                        text: title,
                    },
                    IndexedTextField {
                        field: LexicalField::Body,
                        text: body,
                    },
                ],
            });
        }
        Ok(spans)
    }

    fn insert_native_scope_lex_cache(&self, scope_key: String, generation: u64, lex: LexIndex) {
        let mut cache = self.native_scope_lex.borrow_mut();
        if !cache.contains_key(&scope_key) && cache.len() >= NATIVE_SCOPE_LEX_CACHE_LIMIT {
            cache.clear();
        }
        cache.insert(scope_key, NativeScopeLexCacheEntry { generation, lex });
    }

    fn warm_native_scope_lex_caches(&self, spans: Vec<IndexedSpan>) {
        let mut scoped = HashMap::<String, Vec<IndexedSpan>>::new();
        for span in spans {
            let scope_key = scope_storage_key(&span.scope);
            scoped.entry(scope_key).or_default().push(span);
        }

        for (scope_key, scoped_spans) in scoped.into_iter().take(NATIVE_SCOPE_LEX_CACHE_LIMIT) {
            if scoped_spans.len() < NATIVE_SCOPE_QGRAM_MIN_SPANS {
                continue;
            }
            let lex = LexIndex::build(&scoped_spans, LexConfig::default());
            self.insert_native_scope_lex_cache(scope_key, 0, lex);
        }
    }

    fn native_session_documents_from_notes(&self) -> Result<Vec<SessionDocumentState>, StoreError> {
        let graph = self.native_kernel_snapshot(true)?;
        let mut by_document = HashMap::<String, SessionDocumentState>::new();
        for row in self.fetch_relation_rows("notes")? {
            if row.get("deleted").and_then(Value::as_bool).unwrap_or(false) {
                continue;
            }
            let Some(id) = row.get("id").and_then(Value::as_str) else {
                continue;
            };
            by_document.insert(
                id.to_owned(),
                SessionDocumentState {
                    document_id: DocumentId(id.to_owned()),
                    note_id: Some(NoteId(id.to_owned())),
                    updated_at: row
                        .get("updated_at")
                        .and_then(Value::as_i64)
                        .unwrap_or_default(),
                    ..SessionDocumentState::default()
                },
            );
        }
        for vertex in &graph.vertices {
            let Some(document_id) = vertex.document_id.as_ref() else {
                continue;
            };
            let entry =
                by_document
                    .entry(document_id.clone())
                    .or_insert_with(|| SessionDocumentState {
                        document_id: DocumentId(document_id.clone()),
                        ..SessionDocumentState::default()
                    });
            match vertex.kind.as_str() {
                "chapter" => entry.chapter_count += 1,
                "boundary" => entry.boundary_count += 1,
                "parent" => entry.parent_count += 1,
                "leaf" => entry.leaf_count += 1,
                "entity" | "event" => entry.entity_count += 1,
                _ => {}
            }
        }
        let mut documents = by_document.into_values().collect::<Vec<_>>();
        documents.sort_by(|left, right| left.document_id.0.cmp(&right.document_id.0));
        Ok(documents)
    }

    fn load_session(&self, session_id: &SessionId) -> Result<SessionRecord, StoreError> {
        let rows = self.fetch_relation_rows("phoenix_sessions")?;
        let row = rows
            .into_iter()
            .find(|row| {
                row.get("session_id").and_then(Value::as_str) == Some(session_id.0.as_str())
            })
            .ok_or_else(|| StoreError::Query(format!("session not found: {}", session_id.0)))?;
        session_record_from_row(&row)
    }
}

#[allow(dead_code)]
fn boundary_kind_from_str(value: &str) -> phoenix_types::BoundaryKind {
    match value.to_ascii_lowercase().as_str() {
        "chapter" => phoenix_types::BoundaryKind::Chapter,
        "heading" => phoenix_types::BoundaryKind::Heading,
        "section" => phoenix_types::BoundaryKind::Section,
        "act" => phoenix_types::BoundaryKind::Act,
        _ => phoenix_types::BoundaryKind::Other,
    }
}

fn runtime_ingest_progress_enabled() -> bool {
    matches!(
        std::env::var("PHOENIX_INGEST_PROGRESS").ok().as_deref(),
        Some("1" | "true" | "TRUE" | "yes" | "YES")
    ) || matches!(
        std::env::var("PHOENIX_PERF_PROGRESS").ok().as_deref(),
        Some("1" | "true" | "TRUE" | "yes" | "YES")
    )
}

fn dynamic_ner_gliclass_case_budget() -> usize {
    std::env::var("PHOENIX_DYN_NER_GLICLASS_MAX_CASES")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .map(|value| value.clamp(0, 96))
        .unwrap_or(48)
}

fn native_note_row_from_ingest(
    document: &IngestDocumentView<'_>,
    note_id: &str,
    created_at: i64,
) -> Value {
    json!({
        "id": note_id,
        "version": created_at,
        "world_id": document.scope.world_id.clone().unwrap_or_default(),
        "title": document.title,
        "content": document.text,
        "markdown_content": document.text,
        "folder_id": document.scope.folder_id.clone(),
        "entity_kind": null,
        "entity_subtype": null,
        "is_entity": false,
        "is_pinned": false,
        "favorite": false,
        "owner_id": null,
        "narrative_id": document.scope.narrative_id.clone(),
        "order": 0.0,
        "created_at": created_at,
        "updated_at": created_at,
        "valid_from": created_at,
        "valid_to": null,
        "is_current": true,
        "change_reason": "native-ingest",
    })
}

fn dynamic_lexicon_from_rows(
    rows: &[Value],
    scope: &AtlasRichScanScope,
) -> Result<Option<DynamicLexicon>, StoreError> {
    let mut entries = Vec::new();
    for row in rows {
        if !atlas_entity_row_matches_scan_scope(row, scope) {
            continue;
        }
        let Some(entity_id) = row.get("id").and_then(Value::as_str) else {
            continue;
        };
        let Some(label) = row.get("label").and_then(Value::as_str) else {
            continue;
        };
        let kind = row
            .get("entity_kind")
            .or_else(|| row.get("kind"))
            .and_then(Value::as_str)
            .and_then(dynamic_entity_kind_from_str);
        let aliases = row
            .get("aliases")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(str::to_owned)
            .collect::<Vec<_>>();
        entries.push(dynamic_types::LexiconEntry {
            entity_id: dynamic_types::EntityId(entity_id.to_owned()),
            label: label.to_owned(),
            aliases,
            kind,
            gender: None,
            number: None,
            scope: dynamic_scope_from_row(row),
        });
    }
    if entries.is_empty() {
        return Ok(None);
    }
    DynamicLexicon::from_entries(&entries)
        .map(Some)
        .map_err(|error| StoreError::Query(format!("dynamic lexicon build failed: {error}")))
}

fn dynamic_alias_registry_from_rows(
    rows: &[Value],
    scope: &AtlasRichScanScope,
) -> Vec<phoenix_dynamic_ner::AliasRegistryEntity> {
    let mut entities = Vec::new();
    for row in rows {
        if !atlas_entity_row_matches_scan_scope(row, scope) {
            continue;
        }
        let Some(entity_id) = row.get("id").and_then(Value::as_str) else {
            continue;
        };
        let Some(label) = row.get("label").and_then(Value::as_str) else {
            continue;
        };
        let kind = row
            .get("entity_kind")
            .or_else(|| row.get("kind"))
            .and_then(Value::as_str)
            .and_then(runtime_entity_kind_from_str);
        let aliases = row
            .get("aliases")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(str::to_owned)
            .collect::<Vec<_>>();
        entities.push(phoenix_dynamic_ner::AliasRegistryEntity {
            entity_id: EntityId(entity_id.to_owned()),
            canonical_name: label.to_owned(),
            kind,
            aliases,
        });
    }
    entities
}

fn extend_frame_resolver_seed_from_rows(
    target: &mut Vec<ResolverEntitySeed>,
    rows: &[Value],
    scope: &ScopeKey,
) {
    let mut seen = target
        .iter()
        .map(|seed| seed.entity_id.0.clone())
        .collect::<HashSet<_>>();
    for row in rows {
        if !row_matches_scope(row, scope) {
            continue;
        }
        let Some(entity_id) = row.get("id").and_then(Value::as_str) else {
            continue;
        };
        if !seen.insert(entity_id.to_owned()) {
            continue;
        }
        let Some(label) = row.get("label").and_then(Value::as_str) else {
            continue;
        };
        let kind = row
            .get("entity_kind")
            .or_else(|| row.get("kind"))
            .and_then(Value::as_str)
            .and_then(runtime_entity_kind_from_str);
        target.push(ResolverEntitySeed {
            entity_id: EntityId(entity_id.to_owned()),
            canonical_name: label.to_owned(),
            aliases: json_string_vec(row.get("aliases")),
            kind,
            gender: None,
            number: None,
            scope: frame_seed_scope_from_row(row, scope),
        });
    }
}

fn frame_seed_scope_from_row(row: &Value, fallback: &ScopeKey) -> ScopeKey {
    ScopeKey {
        world_id: row
            .get("world_id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| fallback.world_id.clone()),
        narrative_id: row
            .get("narrative_id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| fallback.narrative_id.clone()),
        folder_id: row
            .get("folder_id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| fallback.folder_id.clone()),
        folder_path: row
            .get("folder_path")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| fallback.folder_path.clone()),
    }
}

fn merge_identity_resolution_summary(
    target: &mut AtlasIdentityResolutionSummary,
    source: AtlasIdentityResolutionSummary,
) {
    target.node_count += source.node_count;
    target.edge_count += source.edge_count;
    target.receipt_count += source.receipt_count;
    target.known_decisions += source.known_decisions;
    target.alias_decisions += source.alias_decisions;
    target.coreference_decisions += source.coreference_decisions;
    target.merge_decisions += source.merge_decisions;
    target.split_decisions += source.split_decisions;
    target.deferred_decisions += source.deferred_decisions;
    target.new_entity_decisions += source.new_entity_decisions;
    target.receipts.extend(source.receipts);
}

fn dynamic_entity_kind_map(rows: &[Value]) -> BTreeMap<String, EntityKind> {
    rows.iter()
        .filter_map(|row| {
            let id = row.get("id").and_then(Value::as_str)?;
            let kind = row
                .get("entity_kind")
                .or_else(|| row.get("kind"))
                .and_then(Value::as_str)
                .and_then(runtime_entity_kind_from_str)?;
            Some((id.to_owned(), kind))
        })
        .collect()
}

fn atlas_entity_row_matches_scan_scope(row: &Value, scope: &AtlasRichScanScope) -> bool {
    if let Some(world_id) = scope.world_id.as_deref() {
        if row.get("world_id").and_then(Value::as_str) != Some(world_id) {
            return false;
        }
    }
    if let Some(narrative_id) = scope.narrative_id.as_deref() {
        if row.get("narrative_id").and_then(Value::as_str) != Some(narrative_id) {
            return false;
        }
    }
    if let Some(folder_id) = scope.folder_id.as_deref() {
        if row.get("folder_id").and_then(Value::as_str) != Some(folder_id) {
            return false;
        }
    }
    true
}

fn dynamic_scope_from_scope(scope: &ScopeKey) -> dynamic_types::ScopeKey {
    dynamic_types::ScopeKey {
        world_id: scope.world_id.clone(),
        narrative_id: scope.narrative_id.clone(),
        folder_id: scope.folder_id.clone(),
        folder_path: scope.folder_path.clone(),
    }
}

fn dynamic_scope_from_row(row: &Value) -> dynamic_types::ScopeKey {
    dynamic_types::ScopeKey {
        world_id: row
            .get("world_id")
            .and_then(Value::as_str)
            .map(str::to_owned),
        narrative_id: row
            .get("narrative_id")
            .and_then(Value::as_str)
            .map(str::to_owned),
        folder_id: row
            .get("folder_id")
            .and_then(Value::as_str)
            .map(str::to_owned),
        folder_path: row
            .get("folder_path")
            .and_then(Value::as_str)
            .map(str::to_owned),
    }
}

fn dynamic_entity_kind_from_str(value: &str) -> Option<dynamic_types::EntityKind> {
    match value.to_ascii_lowercase().as_str() {
        "character" | "person" | "per" => Some(dynamic_types::EntityKind::Character),
        "location" | "place" | "loc" => Some(dynamic_types::EntityKind::Location),
        "npc" | "creature" | "species" => Some(dynamic_types::EntityKind::Npc),
        "item" => Some(dynamic_types::EntityKind::Item),
        "faction" => Some(dynamic_types::EntityKind::Faction),
        "organization" | "organisation" | "org" => Some(dynamic_types::EntityKind::Organization),
        "event" => Some(dynamic_types::EntityKind::Event),
        "concept" => Some(dynamic_types::EntityKind::Concept),
        "other" | "unknown" => Some(dynamic_types::EntityKind::Other),
        _ => None,
    }
}

fn runtime_entity_kind_from_str(value: &str) -> Option<EntityKind> {
    match value.to_ascii_lowercase().as_str() {
        "character" | "person" | "per" => Some(EntityKind::Character),
        "location" | "place" | "loc" => Some(EntityKind::Location),
        "npc" | "creature" | "species" => Some(EntityKind::Npc),
        "item" => Some(EntityKind::Item),
        "faction" => Some(EntityKind::Faction),
        "organization" | "organisation" | "org" => Some(EntityKind::Organization),
        "event" => Some(EntityKind::Event),
        "concept" => Some(EntityKind::Concept),
        "other" | "unknown" => Some(EntityKind::Other),
        _ => None,
    }
}

fn dynamic_tokens_and_sentences(
    text: &str,
) -> (
    Vec<dynamic_types::TokenSpan>,
    Vec<dynamic_types::SentenceSpan>,
) {
    let tokens = dynamic_token_spans(text);
    let sentences = phoenix_chunker::split_sentence_ranges(text)
        .into_iter()
        .enumerate()
        .map(|(index, (start, end))| dynamic_types::SentenceSpan {
            index,
            range: dynamic_types::TextRange {
                start: start as u32,
                end: end as u32,
            },
        })
        .collect();
    (tokens, sentences)
}

fn dynamic_token_spans(text: &str) -> Vec<dynamic_types::TokenSpan> {
    let mut tokens = Vec::new();
    let mut start = None::<usize>;
    let mut class = None::<dynamic_types::TokenClass>;
    let mut last_end = 0usize;
    for (index, ch) in text.char_indices() {
        let end = index + ch.len_utf8();
        let next_class = dynamic_char_class(ch);
        let joins_open = matches!(
            (&class, &next_class),
            (
                Some(dynamic_types::TokenClass::Word),
                Some(dynamic_types::TokenClass::Word)
            ) | (
                Some(dynamic_types::TokenClass::Number),
                Some(dynamic_types::TokenClass::Number)
            )
        );
        if next_class.is_none() || !joins_open {
            if let (Some(open_start), Some(open_class)) = (start.take(), class.take()) {
                tokens.push(dynamic_token_span(text, open_start, index, open_class));
            }
        }
        if let Some(next_class) = next_class {
            if start.is_none() {
                start = Some(index);
                class = Some(next_class.clone());
            }
            if !matches!(
                next_class,
                dynamic_types::TokenClass::Word | dynamic_types::TokenClass::Number
            ) {
                if let Some(open_start) = start.take() {
                    tokens.push(dynamic_token_span(text, open_start, end, next_class));
                }
                class = None;
            }
        }
        last_end = end;
    }
    if let (Some(open_start), Some(open_class)) = (start, class) {
        tokens.push(dynamic_token_span(text, open_start, last_end, open_class));
    }
    tokens
}

fn dynamic_char_class(ch: char) -> Option<dynamic_types::TokenClass> {
    if ch.is_whitespace() {
        None
    } else if ch.is_alphabetic() || ch == '\'' || ch == '-' {
        Some(dynamic_types::TokenClass::Word)
    } else if ch.is_ascii_digit() {
        Some(dynamic_types::TokenClass::Number)
    } else if ch.is_ascii_punctuation() {
        Some(dynamic_types::TokenClass::Punctuation)
    } else {
        Some(dynamic_types::TokenClass::Symbol)
    }
}

fn dynamic_token_span(
    text: &str,
    start: usize,
    end: usize,
    token_class: dynamic_types::TokenClass,
) -> dynamic_types::TokenSpan {
    let token = &text[start..end];
    let capitalized = token
        .chars()
        .next()
        .map(char::is_uppercase)
        .unwrap_or(false);
    let pos = match token_class {
        dynamic_types::TokenClass::Word => dynamic_word_pos(token, capitalized),
        dynamic_types::TokenClass::Punctuation => Some(dynamic_types::PosTag::Punctuation),
        _ => None,
    };
    dynamic_types::TokenSpan {
        range: dynamic_types::TextRange {
            start: start as u32,
            end: end as u32,
        },
        token_class: Some(token_class),
        pos,
        masked: false,
        capitalized,
    }
}

fn dynamic_word_pos(token: &str, capitalized: bool) -> Option<dynamic_types::PosTag> {
    match token.to_ascii_lowercase().as_str() {
        "he" | "him" | "his" | "she" | "her" | "hers" | "they" | "them" | "their" | "theirs"
        | "it" | "its" | "we" | "us" | "our" | "ours" | "i" | "me" | "my" | "mine" | "you"
        | "your" | "yours" => Some(dynamic_types::PosTag::Pronoun),
        _ if capitalized => Some(dynamic_types::PosTag::ProperNoun),
        _ => Some(dynamic_types::PosTag::Noun),
    }
}

fn dynamic_mention_is_graphworthy(
    mention: &phoenix_dynamic_ner::MentionPacket,
    text: &str,
) -> bool {
    !matches!(mention.status, DynamicMentionStatus::Rejected)
        && !matches!(mention.mention_kind, DynamicMentionKind::Pronoun)
        && (mention.entity_ref.is_some()
            || (matches!(mention.mention_kind, DynamicMentionKind::Named)
                && dynamic_has_candidate_signal(mention, text)))
}

fn dynamic_should_surface_candidate(
    mention: &phoenix_dynamic_ner::MentionPacket,
    text: &str,
) -> bool {
    !matches!(
        mention.entity_ref.as_ref(),
        Some(dynamic_types::MentionEntityRef::Known(_))
    ) && matches!(
        mention.status,
        DynamicMentionStatus::AcceptedNew
            | DynamicMentionStatus::AliasCandidate
            | DynamicMentionStatus::NeedsAdjudication
    ) && matches!(mention.mention_kind, DynamicMentionKind::Named)
        && dynamic_has_candidate_signal(mention, text)
}

fn dynamic_has_candidate_signal(mention: &phoenix_dynamic_ner::MentionPacket, text: &str) -> bool {
    let mut has_strong_signal = false;
    let mut has_title_pattern = false;
    let mut has_native_surface_signal = false;
    for vote in &mention.source_votes {
        match vote.reason {
            phoenix_dynamic_ner::VoteReason::GuardViolation
            | phoenix_dynamic_ner::VoteReason::StopwordPenalty => return false,
            phoenix_dynamic_ner::VoteReason::DialogueSpeaker
            | phoenix_dynamic_ner::VoteReason::ModelSpan
            | phoenix_dynamic_ner::VoteReason::ModelLabel
            | phoenix_dynamic_ner::VoteReason::ExactCanonical
            | phoenix_dynamic_ner::VoteReason::ExactAlias
            | phoenix_dynamic_ner::VoteReason::AutoAlias
            | phoenix_dynamic_ner::VoteReason::FuzzyAnchor
            | phoenix_dynamic_ner::VoteReason::NominalRole
            | phoenix_dynamic_ner::VoteReason::DependencyRole => {
                has_strong_signal = true;
            }
            phoenix_dynamic_ner::VoteReason::TitlePattern => {
                has_title_pattern = true;
            }
            phoenix_dynamic_ner::VoteReason::RepeatedSurface
            | phoenix_dynamic_ner::VoteReason::CapSpan => {
                has_native_surface_signal = true;
            }
            phoenix_dynamic_ner::VoteReason::NliSupport
            | phoenix_dynamic_ner::VoteReason::NliContradiction => {}
        }
    }
    has_strong_signal
        || (has_title_pattern && mention.normalized.split_whitespace().count() > 1)
        || (has_native_surface_signal && dynamic_surface_has_location_signal(mention, text))
        || (has_native_surface_signal && dynamic_surface_has_network_signal(mention, text))
        || (has_native_surface_signal && dynamic_surface_has_concept_signal(mention, text))
        || (has_native_surface_signal && dynamic_surface_has_npc_signal(mention, text))
}

fn dynamic_surface_has_location_signal(
    mention: &phoenix_dynamic_ner::MentionPacket,
    text: &str,
) -> bool {
    dynamic_location_vote_confidence(mention, text) > 0.0
}

fn dynamic_location_vote_confidence(
    mention: &phoenix_dynamic_ner::MentionPacket,
    text: &str,
) -> f32 {
    let surface = atlas_clean_label(mention.surface.as_str());
    let normalized = surface.to_ascii_lowercase();
    if normalized.is_empty() {
        return 0.0;
    }
    if dynamic_location_exact_surface(&normalized) {
        return if dynamic_surface_has_person_action_context(&surface, mention.range, text) {
            0.0
        } else {
            0.74
        };
    }
    if dynamic_location_suffix_surface(&normalized) {
        return 0.60;
    }
    if dynamic_surface_has_location_context(&surface, mention.range, text)
        && !dynamic_surface_has_person_action_context(&surface, mention.range, text)
    {
        return 0.46;
    }
    0.0
}

fn dynamic_location_exact_surface(normalized: &str) -> bool {
    matches!(
        normalized,
        "baton rouge"
            | "lower mississippi"
            | "red mesa"
            | "red mesa marker"
            | "redwater"
            | "black cypress"
            | "blacktooth"
            | "boundary keep"
            | "skyglass"
            | "malachor"
            | "halcyon"
            | "south"
            | "southwest"
    )
}

fn dynamic_location_suffix_surface(normalized: &str) -> bool {
    let mut words = normalized.split_whitespace();
    let first = words.next();
    let last = words.last().or(first);
    let word_count = normalized.split_whitespace().count();
    word_count > 1
        && matches!(
            last,
            Some(
                "citadel"
                    | "works"
                    | "tower"
                    | "palace"
                    | "house"
                    | "harbor"
                    | "port"
                    | "city"
                    | "capital"
                    | "country"
                    | "nation"
                    | "realm"
                    | "kingdom"
                    | "empire"
                    | "territory"
                    | "province"
                    | "region"
                    | "mesa"
                    | "keep"
                    | "range"
                    | "ranges"
                    | "road"
                    | "roads"
                    | "route"
                    | "routes"
                    | "river"
                    | "rivers"
                    | "lock"
                    | "locks"
                    | "zone"
                    | "zones"
                    | "camp"
                    | "camps"
            )
        )
}

fn dynamic_surface_has_location_context(surface: &str, range: TextRange, text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    let snippet = dynamic_mention_context_snippet(text, range, 220).to_ascii_lowercase();
    let label = surface.to_ascii_lowercase();
    if label.is_empty() || !snippet.contains(&label) {
        return false;
    }
    const BEFORE: &[&str] = &[
        "in", "at", "near", "from", "to", "inside", "outside", "through", "above", "below",
        "across", "around", "toward", "towards", "within", "into", "onto", "over", "clearing",
    ];
    const MULTI_BEFORE: &[&str] = &[
        "returned from",
        "pane from",
        "opens into",
        "open into",
        "moved through",
    ];
    const AFTER: &[&str] = &[
        "government",
        "continuity",
        "exchange terms",
        "observations",
        "country",
        "nation",
        "city",
        "capital",
        "citadel",
        "works",
        "marker",
        "break",
        "route",
        "routes",
        "roads",
        "river",
        "locks",
        "territory",
        "range",
        "region",
        "map",
        "radius",
        "pulse",
        "tower",
        "mesa",
        "opens",
        "sits",
        "came first",
        "moves first",
    ];

    BEFORE
        .iter()
        .any(|prefix| snippet.contains(&format!("{prefix} {label}")))
        || MULTI_BEFORE
            .iter()
            .any(|prefix| snippet.contains(&format!("{prefix} {label}")))
        || AFTER
            .iter()
            .any(|suffix| snippet.contains(&format!("{label} {suffix}")))
        || (snippet.contains(&format!("{label}."))
            && [
                "fuel movement",
                "rail breaks",
                "river locks",
                "hospital reroutes",
                "detention sites",
            ]
            .iter()
            .any(|cue| snippet.contains(cue)))
}

fn dynamic_surface_has_person_action_context(surface: &str, range: TextRange, text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    let snippet = dynamic_mention_context_snippet(text, range, 220).to_ascii_lowercase();
    let label = surface.to_ascii_lowercase();
    if label.is_empty() || !snippet.contains(&label) {
        return false;
    }
    const ACTIONS: &[&str] = &[
        "said",
        "asked",
        "answered",
        "replied",
        "murmured",
        "whispered",
        "called",
        "shouted",
        "laughed",
        "smiled",
        "sighed",
        "huffed",
        "glanced",
        "looked",
        "watched",
        "turned",
        "lifted",
        "rolled",
        "stood",
        "sat",
        "walked",
        "crossed",
        "dragged",
        "muttered",
        "moved",
        "held",
        "gave",
        "took",
        "followed",
        "responded",
        "wanted",
        "went",
    ];
    ACTIONS.iter().any(|action| {
        snippet.contains(&format!("{label} {action}"))
            || snippet.contains(&format!("{action} {label}"))
    })
}

fn dynamic_surface_has_network_signal(
    mention: &phoenix_dynamic_ner::MentionPacket,
    text: &str,
) -> bool {
    let surface = atlas_clean_label(mention.surface.as_str());
    let normalized = surface.to_ascii_lowercase();
    if normalized.is_empty() {
        return false;
    }
    dynamic_network_exact_surface(&normalized)
        || dynamic_network_suffix_surface(&normalized)
        || dynamic_surface_has_network_context(&surface, mention.range, text)
}

fn dynamic_network_vote_confidence(surface: &str, text: &str, range: TextRange) -> f32 {
    let normalized = surface.to_ascii_lowercase();
    if dynamic_network_exact_surface(&normalized) {
        return 0.88;
    }
    if dynamic_network_suffix_surface(&normalized) {
        return 0.64;
    }
    if dynamic_surface_has_network_context(surface, range, text) {
        return 0.54;
    }
    0.0
}

fn dynamic_network_exact_surface(normalized: &str) -> bool {
    matches!(
        normalized,
        "allied table"
            | "atlas"
            | "joint chiefs"
            | "operator office"
            | "operators"
            | "phantom command"
            | "phantom authority"
            | "phantoms"
            | "warden force"
            | "canton recovery"
            | "federal range command"
            | "state emergency command"
            | "private claim crews"
            | "containment forces"
            | "militia"
            | "militias"
            | "military"
    )
}

fn dynamic_network_suffix_surface(normalized: &str) -> bool {
    let mut words = normalized.split_whitespace();
    let first = words.next();
    let last = words.last().or(first);
    let word_count = normalized.split_whitespace().count();
    word_count > 1
        && matches!(
            last,
            Some(
                "table"
                    | "chiefs"
                    | "operator"
                    | "operators"
                    | "office"
                    | "force"
                    | "forces"
                    | "command"
                    | "authority"
                    | "agency"
                    | "alliance"
                    | "guild"
                    | "crew"
                    | "crews"
                    | "clan"
                    | "council"
                    | "department"
                    | "directorate"
                    | "committee"
                    | "institution"
                    | "contractor"
                    | "contractors"
                    | "militia"
                    | "militias"
                    | "military"
            )
        )
}

fn dynamic_surface_has_network_context(surface: &str, range: TextRange, text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    let snippet = dynamic_mention_context_snippet(text, range, 220).to_ascii_lowercase();
    let label = surface.to_ascii_lowercase();
    if label.is_empty() || !snippet.contains(&label) {
        return false;
    }
    const AFTER: &[&str] = &[
        "approved",
        "understands",
        "backing",
        "authority",
        "command",
        "coverage",
        "records",
        "contract",
        "contracts",
        "force",
        "forces",
        "operator",
        "operators",
        "militia",
        "militias",
        "military",
        "signed to",
        "wanted",
        "believed",
    ];
    const BEFORE: &[&str] = &[
        "signed to",
        "under command",
        "backed by",
        "bringing in",
        "direct line to",
        "local",
        "private",
        "state-backed",
        "federal",
        "phantom",
        "warden",
    ];

    AFTER
        .iter()
        .any(|suffix| snippet.contains(&format!("{label} {suffix}")))
        || BEFORE
            .iter()
            .any(|prefix| snippet.contains(&format!("{prefix} {label}")))
}

fn dynamic_surface_has_concept_signal(
    mention: &phoenix_dynamic_ner::MentionPacket,
    text: &str,
) -> bool {
    let surface = atlas_clean_label(mention.surface.as_str());
    dynamic_concept_vote_confidence(&surface, text, mention.range) > 0.0
}

fn dynamic_concept_vote_confidence(surface: &str, text: &str, range: TextRange) -> f32 {
    if dynamic_surface_has_concept_context(surface, range, text) {
        return 0.52;
    }
    0.0
}

fn dynamic_surface_has_concept_context(surface: &str, range: TextRange, text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    let snippet = dynamic_mention_context_snippet(text, range, 220).to_ascii_lowercase();
    let label = surface.to_ascii_lowercase();
    if label.is_empty() || !snippet.contains(&label) {
        return false;
    }
    const BEFORE: &[&str] = &[
        "called",
        "known as",
        "named",
        "principle of",
        "theory of",
        "law of",
        "rule of",
        "field of",
        "system of",
        "worth of",
        "full city's worth of",
    ];
    const AFTER: &[&str] = &[
        "weight",
        "pressure",
        "field",
        "rank",
        "classification",
        "settled",
        "sitting",
        "pulse",
    ];
    BEFORE
        .iter()
        .any(|prefix| snippet.contains(&format!("{prefix} {label}")))
        || AFTER
            .iter()
            .any(|suffix| snippet.contains(&format!("{label} {suffix}")))
}

fn dynamic_surface_has_npc_signal(
    mention: &phoenix_dynamic_ner::MentionPacket,
    text: &str,
) -> bool {
    let surface = atlas_clean_label(mention.surface.as_str());
    dynamic_npc_vote_confidence(&surface, text, mention.range) > 0.0
}

fn dynamic_npc_vote_confidence(surface: &str, text: &str, range: TextRange) -> f32 {
    if dynamic_surface_has_npc_context(surface, range, text) {
        return 0.54;
    }
    0.0
}

fn dynamic_surface_has_npc_context(surface: &str, range: TextRange, text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    let snippet = dynamic_mention_context_snippet(text, range, 220).to_ascii_lowercase();
    let label = surface.to_ascii_lowercase();
    if label.is_empty() || !snippet.contains(&label) {
        return false;
    }
    const ROLE_WORDS: &[&str] = &[
        "guard", "teenager", "girl", "woman", "boy", "vendor", "folk", "denizen", "citizen",
        "civilian", "elder", "soldier", "warrior", "mage", "priest", "healer", "merchant",
    ];
    if label
        .split(|ch: char| !ch.is_ascii_alphanumeric())
        .any(|word| ROLE_WORDS.contains(&word))
    {
        return true;
    }
    const BEFORE: &[&str] = &["a", "an", "the", "two", "younger", "elder"];
    const AFTER: &[&str] = &[
        "guard", "teenager", "girl", "woman", "boy", "vendor", "folk", "denizen", "citizen",
        "civilian", "elder", "soldier", "warrior", "mage", "priest", "healer", "merchant",
    ];
    BEFORE
        .iter()
        .any(|prefix| snippet.contains(&format!("{prefix} {label}")))
        || AFTER
            .iter()
            .any(|suffix| snippet.contains(&format!("{label} {suffix}")))
}

fn dynamic_candidate_kind_votes(
    mention: &phoenix_dynamic_ner::MentionPacket,
    known_kind: Option<&EntityKind>,
    text: &str,
) -> Vec<AtlasRichScanKindVoteSummary> {
    let mut by_key = BTreeMap::<(String, String, String), f32>::new();

    if let Some(kind) = known_kind {
        by_key.insert(
            (
                atlas_entity_kind_name(Some(kind)).to_owned(),
                "known_lexicon".to_owned(),
                "known_entity_kind".to_owned(),
            ),
            1.0,
        );
    }

    for (label, confidence) in &mention.label_distribution {
        if let Some(kind) = dynamic_label_to_atlas_kind(label.as_str()) {
            by_key
                .entry((
                    kind.to_owned(),
                    "label_distribution".to_owned(),
                    "model_label_distribution".to_owned(),
                ))
                .and_modify(|current| *current = current.max(*confidence))
                .or_insert(*confidence);
        }
    }

    for vote in &mention.source_votes {
        let Some(label) = vote.label.as_ref() else {
            continue;
        };
        let Some(kind) = dynamic_label_to_atlas_kind(label.as_str()) else {
            continue;
        };
        by_key
            .entry((
                kind.to_owned(),
                dynamic_vote_source_name(vote.source).to_owned(),
                format!("{:?}", vote.reason),
            ))
            .and_modify(|current| *current = current.max(vote.confidence))
            .or_insert(vote.confidence);
    }

    let location_confidence = dynamic_location_vote_confidence(mention, text);
    if known_kind.is_none() && location_confidence > 0.0 {
        by_key
            .entry((
                "LOCATION".to_owned(),
                "native_location_shape".to_owned(),
                "location_surface_or_context".to_owned(),
            ))
            .and_modify(|current| *current = current.max(location_confidence))
            .or_insert(location_confidence);
    }

    let concept_confidence = dynamic_concept_vote_confidence(
        atlas_clean_label(mention.surface.as_str()).as_str(),
        text,
        mention.range,
    );
    if known_kind.is_none() && concept_confidence > 0.0 {
        by_key
            .entry((
                "CONCEPT".to_owned(),
                "native_concept_shape".to_owned(),
                "concept_surface_or_context".to_owned(),
            ))
            .and_modify(|current| *current = current.max(concept_confidence))
            .or_insert(concept_confidence);
    }

    let npc_confidence = dynamic_npc_vote_confidence(
        atlas_clean_label(mention.surface.as_str()).as_str(),
        text,
        mention.range,
    );
    if known_kind.is_none() && npc_confidence > 0.0 {
        by_key
            .entry((
                "NPC".to_owned(),
                "native_npc_shape".to_owned(),
                "npc_surface_or_context".to_owned(),
            ))
            .and_modify(|current| *current = current.max(npc_confidence))
            .or_insert(npc_confidence);
    }

    let network_confidence = dynamic_network_vote_confidence(
        atlas_clean_label(mention.surface.as_str()).as_str(),
        text,
        mention.range,
    );
    if known_kind.is_none() && network_confidence > 0.0 {
        by_key
            .entry((
                "NETWORK".to_owned(),
                "native_network_shape".to_owned(),
                "network_surface_or_context".to_owned(),
            ))
            .and_modify(|current| *current = current.max(network_confidence))
            .or_insert(network_confidence);
    }

    by_key
        .into_iter()
        .map(
            |((kind, source, reason), confidence)| AtlasRichScanKindVoteSummary {
                kind,
                source,
                confidence,
                reason,
            },
        )
        .collect()
}

fn dynamic_candidate_kind(
    _mention: &phoenix_dynamic_ner::MentionPacket,
    known_kind: Option<&EntityKind>,
    votes: &[AtlasRichScanKindVoteSummary],
) -> String {
    if let Some(kind) = known_kind {
        return atlas_entity_kind_name(Some(kind)).to_owned();
    }

    votes
        .iter()
        .max_by(|left, right| left.confidence.total_cmp(&right.confidence))
        .filter(|vote| vote.confidence >= 0.20)
        .map(|vote| vote.kind.clone())
        .unwrap_or_else(|| "UNKNOWN".to_owned())
}

fn dynamic_candidate_decision_status(mention: &phoenix_dynamic_ner::MentionPacket) -> String {
    match mention.status {
        DynamicMentionStatus::AcceptedKnown | DynamicMentionStatus::AcceptedNew => "accepted",
        DynamicMentionStatus::AliasCandidate | DynamicMentionStatus::NeedsAdjudication => "review",
        DynamicMentionStatus::Rejected => "rejected",
    }
    .to_owned()
}

fn dynamic_candidate_review_reason(
    mention: &phoenix_dynamic_ner::MentionPacket,
    kind: &str,
) -> Option<String> {
    if kind == "UNKNOWN" {
        return Some("missing_kind_vote".to_owned());
    }
    match mention.status {
        DynamicMentionStatus::AliasCandidate => Some("alias_candidate".to_owned()),
        DynamicMentionStatus::NeedsAdjudication => Some("needs_adjudication".to_owned()),
        DynamicMentionStatus::Rejected => Some("rejected".to_owned()),
        DynamicMentionStatus::AcceptedKnown | DynamicMentionStatus::AcceptedNew => None,
    }
}

fn dynamic_candidate_is_better(
    next: &AtlasRichScanCandidateSummary,
    current: &AtlasRichScanCandidateSummary,
) -> bool {
    let next_status = dynamic_candidate_status_rank(&next.decision_status);
    let current_status = dynamic_candidate_status_rank(&current.decision_status);
    next_status > current_status
        || (next_status == current_status && next.confidence > current.confidence)
}

fn dynamic_candidate_status_rank(status: &str) -> u8 {
    match status {
        "accepted" => 3,
        "review" => 2,
        "rejected" => 0,
        _ => 1,
    }
}

fn dynamic_push_network_surface_candidates(
    document: &AtlasRichScanDocument,
    candidate_by_key: &mut BTreeMap<String, AtlasRichScanCandidateSummary>,
) {
    const SURFACES: &[(&str, &str, f32, &str)] = &[
        ("allied table", "Allied Table", 0.88, "accepted"),
        ("atlas", "Atlas", 0.86, "accepted"),
        ("joint chiefs", "Joint Chiefs", 0.86, "accepted"),
        ("operator office", "Operator Office", 0.84, "accepted"),
        ("operators", "Operators", 0.72, "review"),
        ("phantom command", "Phantom command", 0.82, "accepted"),
        ("phantom authority", "Phantom authority", 0.82, "accepted"),
        ("phantoms", "Phantoms", 0.72, "review"),
        ("warden force", "Warden force", 0.82, "accepted"),
        ("militia", "militia", 0.58, "review"),
        ("militias", "militias", 0.58, "review"),
        ("military", "military", 0.56, "review"),
    ];

    let lowered = document.text.to_ascii_lowercase();
    for (needle, label, confidence, status) in SURFACES {
        let Some(start) = dynamic_find_surface_range(&lowered, needle) else {
            continue;
        };
        let range = TextRange {
            start: start as u32,
            end: (start + needle.len()) as u32,
        };
        let evidence = dynamic_mention_context_snippet(&document.text, range, 220);
        let key = atlas_candidate_key(label);
        let candidate = AtlasRichScanCandidateSummary {
            id: format!(
                "dyn-network-{:016x}",
                atlas_hash64(format!("{}:{label}", document.document_id.0).as_bytes())
            ),
            label: (*label).to_owned(),
            kind: "NETWORK".to_owned(),
            confidence: *confidence,
            source_document_id: Some(document.document_id.clone()),
            source_note_id: document.note_id.clone(),
            evidence: (!evidence.is_empty()).then_some(evidence),
            aliases: Vec::new(),
            range: Some(range),
            source_stage: "dynamicNer".to_owned(),
            kind_votes: vec![AtlasRichScanKindVoteSummary {
                kind: "NETWORK".to_owned(),
                source: "native_network_shape".to_owned(),
                confidence: *confidence,
                reason: "network_surface_or_context".to_owned(),
            }],
            decision_status: (*status).to_owned(),
            review_reason: (*status == "review").then(|| "network_surface_review".to_owned()),
        };
        candidate_by_key
            .entry(key)
            .and_modify(|current| {
                if dynamic_candidate_is_better(&candidate, current) {
                    *current = candidate.clone();
                }
            })
            .or_insert(candidate);
    }
}

fn dynamic_find_surface_range(lowered_text: &str, needle: &str) -> Option<usize> {
    let mut offset = 0usize;
    while let Some(relative) = lowered_text[offset..].find(needle) {
        let start = offset + relative;
        let end = start + needle.len();
        let left_ok = start == 0
            || !lowered_text[..start]
                .chars()
                .next_back()
                .is_some_and(char::is_alphanumeric);
        let right_ok = end >= lowered_text.len()
            || !lowered_text[end..]
                .chars()
                .next()
                .is_some_and(char::is_alphanumeric);
        if left_ok && right_ok {
            return Some(start);
        }
        offset = end;
    }
    None
}

fn dynamic_mention_context_snippet(text: &str, range: TextRange, limit: usize) -> String {
    if text.is_empty() || range.start >= range.end {
        return String::new();
    }
    let start = (range.start as usize).min(text.len());
    let end = (range.end as usize).min(text.len());
    if start >= end {
        return String::new();
    }

    let left = text[..start]
        .rfind(['\n', '.', '!', '?'])
        .map(|index| index + 1)
        .unwrap_or(start.saturating_sub(limit / 2));
    let right = text[end..]
        .find(['\n', '.', '!', '?'])
        .map(|index| end + index + 1)
        .unwrap_or((end + limit / 2).min(text.len()));
    let left = floor_text_boundary(text, left.min(text.len()));
    let right = floor_text_boundary(text, right.min(text.len()));
    phase1_snippet(text.get(left..right).unwrap_or(""), limit)
}

fn floor_text_boundary(text: &str, mut index: usize) -> usize {
    while index > 0 && !text.is_char_boundary(index) {
        index -= 1;
    }
    index
}

fn dynamic_vote_source_name(source: phoenix_dynamic_ner::MentionSourceKind) -> &'static str {
    match source {
        phoenix_dynamic_ner::MentionSourceKind::KnownLexicon => "known_lexicon",
        phoenix_dynamic_ner::MentionSourceKind::NativeDiscovery => "native_discovery",
        phoenix_dynamic_ner::MentionSourceKind::Scirs2Rule => "scirs2_rule",
        phoenix_dynamic_ner::MentionSourceKind::Scirs2Pattern => "scirs2_pattern",
        phoenix_dynamic_ner::MentionSourceKind::ModelDiscovery => "model_discovery",
        phoenix_dynamic_ner::MentionSourceKind::ModelVerify => "model_verify",
        phoenix_dynamic_ner::MentionSourceKind::Adjudication => "adjudication",
        phoenix_dynamic_ner::MentionSourceKind::Pronoun => "pronoun",
    }
}

fn dynamic_label_to_atlas_kind(label: &str) -> Option<&'static str> {
    match label.trim().to_ascii_lowercase().as_str() {
        "character" | "person" | "speaker" => Some("CHARACTER"),
        "npc" | "denizen" | "civilian" | "citizen" | "guard" | "soldier" | "vendor"
        | "merchant" | "elder" | "warrior" | "mage" | "priest" | "healer" => Some("NPC"),
        "creature" | "species" | "monster" | "nonhuman" => Some("CREATURE"),
        "organization" | "organisation" | "org" | "faction" | "group" | "network" | "alliance"
        | "department" | "institution" => Some("NETWORK"),
        "location" | "place" | "region" | "landmark" | "city" | "country" | "nation" => {
            Some("LOCATION")
        }
        "artifact" | "item" | "weapon" | "object" => Some("ITEM"),
        "event" => Some("EVENT"),
        "concept" | "theory" | "method" | "principle" | "rule" | "law" | "field" | "system"
        | "role" | "rank" | "title" | "ability" | "spell" | "state" | "goal" | "relationship"
        | "emotion" | "metric" | "initiative" | "risk" | "library" | "function" | "module"
        | "error" | "benchmark" | "algorithm" => Some("CONCEPT"),
        _ => None,
    }
}

fn dynamic_mention_label(mention: &phoenix_dynamic_ner::MentionPacket) -> String {
    atlas_clean_label(mention.surface.as_str())
}

fn dynamic_known_entity_id(mention: &phoenix_dynamic_ner::MentionPacket) -> Option<String> {
    match mention.entity_ref.as_ref()? {
        dynamic_types::MentionEntityRef::Known(entity_id) => Some(entity_id.0.clone()),
        dynamic_types::MentionEntityRef::Speculative(_) => None,
    }
}

fn dynamic_mention_vertex_id(
    document_id: &str,
    mention: &phoenix_dynamic_ner::MentionPacket,
) -> String {
    let key = format!(
        "{document_id}:{}:{}:{}",
        mention.range.start, mention.range.end, mention.normalized
    );
    format!("entity::dyn::{:016x}", atlas_hash64(key.as_bytes()))
}

fn dynamic_mention_kind_name(kind: DynamicMentionKind) -> &'static str {
    match kind {
        DynamicMentionKind::Named => "named",
        DynamicMentionKind::Nominal => "nominal",
        DynamicMentionKind::Pronoun => "pronoun",
    }
}

fn dynamic_mention_status_name(status: DynamicMentionStatus) -> &'static str {
    match status {
        DynamicMentionStatus::AcceptedKnown => "acceptedKnown",
        DynamicMentionStatus::AcceptedNew => "acceptedNew",
        DynamicMentionStatus::AliasCandidate => "aliasCandidate",
        DynamicMentionStatus::NeedsAdjudication => "needsAdjudication",
        DynamicMentionStatus::Rejected => "rejected",
    }
}

fn find_leaf_for_range(chunks: &[phoenix_chunker::Chunk], start: usize) -> Option<usize> {
    chunks
        .iter()
        .position(|chunk| start >= chunk.start && start < chunk.end)
        .or_else(|| chunks.len().checked_sub(1))
}

fn split_ingest_leaf_chunks(text: &str) -> Vec<String> {
    let mut chunks = Vec::new();
    let mut current = String::new();
    for line in text.lines().map(str::trim).filter(|line| !line.is_empty()) {
        if current.len().saturating_add(line.len()).saturating_add(1) > 1200 && !current.is_empty()
        {
            chunks.push(current);
            current = String::new();
        }
        if !current.is_empty() {
            current.push('\n');
        }
        current.push_str(line);
    }
    if !current.is_empty() {
        chunks.push(current);
    }
    if chunks.is_empty() && !text.trim().is_empty() {
        chunks.push(text.trim().to_owned());
    }
    chunks
}

fn atlas_policy_label(policy: &AtlasRichScanPolicy) -> &'static str {
    match policy {
        AtlasRichScanPolicy::DirtyOnly => "dirty-only",
        AtlasRichScanPolicy::Force => "force",
    }
}

fn atlas_stage_summary(
    stage: &str,
    started_at: Instant,
    counts: &[(&str, usize)],
) -> AtlasRichScanStageSummary {
    AtlasRichScanStageSummary {
        stage: stage.to_owned(),
        status: "complete".to_owned(),
        duration_ms: started_at
            .elapsed()
            .as_millis()
            .try_into()
            .unwrap_or(u64::MAX),
        counts: counts
            .iter()
            .map(|(key, value)| ((*key).to_owned(), *value))
            .collect(),
    }
}

fn atlas_preservation_counts(
    request: &AtlasRichScanRequest,
    stable_documents: usize,
) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::new();
    counts.insert(
        "acceptedCandidates".to_owned(),
        request.accepted_candidate_ids.len(),
    );
    counts.insert(
        "rejectedCandidates".to_owned(),
        request.rejected_candidate_keys.len(),
    );
    counts.insert("manualEdges".to_owned(), 0);
    counts.insert("graphPositions".to_owned(), 0);
    counts.insert("stableIds".to_owned(), stable_documents);
    counts
}

fn atlas_document_from_note_value(
    row: Value,
    request_scope: &AtlasRichScanScope,
) -> Option<AtlasRichScanDocument> {
    let id = row.get("id").and_then(Value::as_str)?.to_owned();
    let text = row
        .get("markdown_content")
        .and_then(Value::as_str)
        .or_else(|| row.get("content").and_then(Value::as_str))
        .unwrap_or_default()
        .to_owned();
    let title = row
        .get("title")
        .and_then(Value::as_str)
        .unwrap_or(&id)
        .to_owned();
    Some(AtlasRichScanDocument {
        document_id: DocumentId(id.clone()),
        note_id: Some(NoteId(id)),
        title,
        text,
        scope: ScopeKey {
            world_id: row
                .get("world_id")
                .and_then(Value::as_str)
                .map(str::to_owned)
                .or_else(|| request_scope.world_id.clone()),
            narrative_id: row
                .get("narrative_id")
                .and_then(Value::as_str)
                .map(str::to_owned)
                .or_else(|| request_scope.narrative_id.clone()),
            folder_id: row
                .get("folder_id")
                .and_then(Value::as_str)
                .map(str::to_owned)
                .or_else(|| request_scope.folder_id.clone()),
            folder_path: request_scope.folder_path.clone(),
        },
    })
}

fn atlas_entity_kind_name(kind: Option<&EntityKind>) -> &'static str {
    match kind {
        Some(EntityKind::Character) => "CHARACTER",
        Some(EntityKind::Location) => "LOCATION",
        Some(EntityKind::Npc) => "NPC",
        Some(EntityKind::Item) => "ITEM",
        Some(EntityKind::Faction) => "FACTION",
        Some(EntityKind::Organization) => "ORGANIZATION",
        Some(EntityKind::Event) => "EVENT",
        Some(EntityKind::Concept) => "CONCEPT",
        Some(EntityKind::Other) | None => "UNKNOWN",
    }
}

fn atlas_clean_label(value: &str) -> String {
    value
        .trim_matches(|ch: char| ch.is_ascii_punctuation() || ch.is_whitespace())
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn atlas_candidate_key(value: &str) -> String {
    value
        .chars()
        .flat_map(char::to_lowercase)
        .map(|ch| if ch.is_alphanumeric() { ch } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn atlas_text_vector(text: &str) -> Vec<f32> {
    let mut vector = vec![0.0f32; SEMANTIC_VECTOR_DIM];
    let mut token = String::new();
    for ch in text.chars().chain(std::iter::once(' ')) {
        if ch.is_ascii_alphanumeric() {
            token.push(ch.to_ascii_lowercase());
            continue;
        }
        if token.len() > 2 {
            atlas_add_token_to_vector(&mut vector, &token);
        }
        token.clear();
    }
    let norm = vector.iter().map(|value| value * value).sum::<f32>().sqrt();
    if norm > 0.0 {
        for value in &mut vector {
            *value /= norm;
        }
    }
    vector
}

fn atlas_add_token_to_vector(vector: &mut [f32], token: &str) {
    let hash = atlas_hash64(token.as_bytes());
    let first = (hash as usize) % vector.len();
    let second = ((hash >> 17) as usize) % vector.len();
    let sign = if hash & 0x8000_0000_0000_0000 == 0 {
        1.0
    } else {
        -1.0
    };
    let weight = 1.0 + token.len().min(12) as f32 * 0.035;
    vector[first] += sign * weight;
    vector[second] += sign * weight * 0.5;
}

fn atlas_hash64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

fn native_linear_lexical_search_result(
    spans: &[IndexedSpan],
    query: &str,
    scope: &ScopeKey,
    limit: usize,
) -> LexicalSearchResult {
    let normalized_query = normalize_lexical_query(query);
    let terms = normalized_query
        .split_whitespace()
        .filter(|term| !term.is_empty())
        .collect::<Vec<_>>();
    if terms.is_empty() {
        return LexicalSearchResult::default();
    }

    let mut hits = spans
        .iter()
        .filter(|span| span.scope == *scope)
        .filter_map(|span| native_span_hit(span, &normalized_query, &terms))
        .collect::<Vec<_>>();
    hits.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.span_id.cmp(&right.span_id))
    });
    hits.truncate(limit);

    LexicalSearchResult {
        span_hits: hits,
        diagnostics: vec![Diagnostic {
            code: "PX_QUERY_NATIVE_SCOPE_LINEAR".to_owned(),
            message:
                "Native query used linear scope-local lexical spans without rebuilding the global in-memory lex index."
                    .to_owned(),
        }],
    }
}

fn native_span_hit(span: &IndexedSpan, normalized_query: &str, terms: &[&str]) -> Option<SpanHit> {
    let mut matched_terms = 0usize;
    let mut score = 0.0f64;
    for field in &span.fields {
        let normalized_text = normalize_lexical_query(&field.text);
        if normalized_text.is_empty() {
            continue;
        }
        let field_weight = match field.field {
            LexicalField::Title => 3.0,
            LexicalField::Summary => 2.0,
            LexicalField::Body => 1.0,
            LexicalField::Tags => 1.5,
            LexicalField::Other => 1.0,
        };
        if normalized_text.contains(normalized_query) {
            score += field_weight * 4.0;
        }
        for term in terms {
            if normalized_text.contains(term) {
                matched_terms += 1;
                score += field_weight;
            }
        }
    }
    if matched_terms == 0 {
        return None;
    }
    Some(SpanHit {
        span_id: span.span_id.clone(),
        note_id: span.note_id.clone(),
        document_id: span.document_id.clone(),
        score,
        coverage: matched_terms as f32 / terms.len() as f32,
    })
}

fn normalize_lexical_query(value: &str) -> String {
    value
        .chars()
        .filter(|ch| ch.is_alphanumeric() || ch.is_whitespace())
        .flat_map(|ch| ch.to_lowercase())
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn lexical_match_score(value: &str, normalized_query: &str, terms: &[&str], weight: f64) -> f64 {
    let normalized = normalize_lexical_query(value);
    if normalized.is_empty() {
        return 0.0;
    }
    let mut score = 0.0;
    if normalized == normalized_query {
        score += weight * 4.0;
    } else if normalized.contains(normalized_query) {
        score += weight * 2.0;
    }
    for term in terms {
        if normalized.contains(term) {
            score += weight;
        }
    }
    score
}

fn row_matches_scope(row: &Value, scope: &ScopeKey) -> bool {
    let matches_field = |field: &str, expected: &Option<String>| {
        expected
            .as_deref()
            .map(|expected| {
                row.get(field)
                    .and_then(Value::as_str)
                    .map(|actual| actual == expected)
                    .unwrap_or(true)
            })
            .unwrap_or(true)
    };
    matches_field("world_id", &scope.world_id)
        && matches_field("narrative_id", &scope.narrative_id)
        && matches_field("folder_id", &scope.folder_id)
}

fn json_f32_vector(value: Option<&Value>) -> Vec<f32> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_f64)
        .map(|value| value as f32)
        .collect()
}

fn json_string_vec(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

fn cosine_distance(left: &[f32], right: &[f32]) -> Option<f64> {
    if left.is_empty() || left.len() != right.len() {
        return None;
    }
    let mut dot = 0.0f64;
    let mut left_norm = 0.0f64;
    let mut right_norm = 0.0f64;
    for (&left_value, &right_value) in left.iter().zip(right) {
        let left_value = left_value as f64;
        let right_value = right_value as f64;
        dot += left_value * right_value;
        left_norm += left_value * left_value;
        right_norm += right_value * right_value;
    }
    if left_norm == 0.0 || right_norm == 0.0 {
        return None;
    }
    Some(1.0 - (dot / (left_norm.sqrt() * right_norm.sqrt())))
}

fn runtime_row_document_id(row: &Map<String, Value>) -> Option<String> {
    row.get("document_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .or_else(|| {
            row.get("attributes")
                .and_then(Value::as_object)
                .and_then(|attributes| attributes.get("documentId"))
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .or_else(|| {
            row.get("value")
                .and_then(Value::as_object)
                .and_then(|value| value.get("documentId"))
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
}

#[allow(dead_code)]
fn graph_vertex_record_from_row_value(row: &Value) -> Option<GraphVertexRecord> {
    let object = row.as_object()?;
    let id = object.get("id")?.as_str()?.to_owned();
    let value = object.get("value").cloned().unwrap_or(Value::Null);
    let attributes = object.get("attributes").cloned().unwrap_or(Value::Null);
    let chapters = attributes
        .get("chapters")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_u64)
                .map(|value| value as u32)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let boundary_ordinals = attributes
        .get("boundaryOrdinals")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_u64)
                .map(|value| value as u32)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    Some(GraphVertexRecord {
        id,
        kind: value
            .get("kind")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_owned(),
        weight: object.get("weight").and_then(Value::as_i64).unwrap_or(1),
        value: value.clone(),
        attributes: attributes.clone(),
        entity_id: value
            .get("entityId")
            .and_then(Value::as_str)
            .map(str::to_owned),
        search_chunk_id: value
            .get("searchChunkId")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| {
                attributes
                    .get("searchChunkId")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            }),
        document_id: runtime_row_document_id(object),
        chapter_id: attributes
            .get("chapterId")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
        chapters,
        boundary_id: attributes
            .get("boundaryId")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
        boundary_ordinal: attributes
            .get("boundaryOrdinal")
            .and_then(Value::as_u64)
            .map(|value| value as u32),
        boundary_kind: attributes
            .get("boundaryKind")
            .and_then(Value::as_str)
            .map(boundary_kind_from_str),
        boundary_ordinals,
    })
}

fn graph_edge_record_from_row_value(row: &Value, layer: GraphLayer) -> Option<GraphEdgeRecord> {
    let object = row.as_object()?;
    Some(GraphEdgeRecord {
        source_id: object.get("source_id")?.as_str()?.to_owned(),
        target_id: object.get("target_id")?.as_str()?.to_owned(),
        edge_type: object
            .get("edge_type")
            .and_then(Value::as_str)
            .unwrap_or("edge")
            .to_owned(),
        weight: object.get("weight").and_then(Value::as_i64).unwrap_or(1),
        attributes: object.get("attributes").cloned().unwrap_or(Value::Null),
        data: object.get("data").cloned().filter(|value| !value.is_null()),
        document_id: object
            .get("document_id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| {
                object
                    .get("attributes")
                    .and_then(Value::as_object)
                    .and_then(|attributes| attributes.get("documentId"))
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            }),
        narrative_id: object
            .get("narrative_id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| {
                object
                    .get("attributes")
                    .and_then(Value::as_object)
                    .and_then(|attributes| attributes.get("narrativeId"))
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            }),
        layer,
    })
}

fn graph_edge_record_to_row_value(record: GraphEdgeRecord) -> Value {
    let assertion_kind = match record.layer {
        GraphLayer::Asserted => "asserted",
        GraphLayer::Candidate => "candidate",
    };
    json!({
        "source_id": record.source_id,
        "target_id": record.target_id,
        "edge_type": record.edge_type,
        "document_id": record.document_id,
        "narrative_id": record.narrative_id,
        "valid_from_doc": record.document_id,
        "valid_from_boundary": null,
        "valid_to_doc": null,
        "valid_to_boundary": null,
        "assertion_kind": assertion_kind,
        "weight": record.weight,
        "attributes": record.attributes,
        "data": record.data,
    })
}

fn kernel_vertex_to_row_value(vertex: &KernelVertex) -> Value {
    json!({
        "id": vertex.id.0,
        "document_id": vertex.document_id,
        "narrative_id": vertex
            .value
            .get("narrativeId")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| {
                vertex
                    .attributes
                    .get("narrativeId")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            }),
        "value": vertex.value,
        "weight": vertex.weight,
        "attributes": vertex.attributes,
    })
}

fn kernel_edge_to_row_value(edge: &KernelEdge) -> Value {
    graph_edge_record_to_row_value(GraphEdgeRecord::from(edge.clone()))
}

fn build_graph_delta_from_kernel_snapshot(
    graph: &KernelGraphSnapshot,
    state: &SessionState,
    request: &GraphDeltaRequest,
) -> GraphDeltaResult {
    let allowed_documents = runtime_graph_delta_allowed_documents(state, request);
    let mut diagnostics = runtime_graph_delta_diagnostics(request);
    let vertices = graph
        .vertices
        .iter()
        .map(|vertex| (vertex.id.0.clone(), vertex))
        .collect::<HashMap<_, _>>();

    let mut chunk_ids = graph
        .vertices
        .iter()
        .filter(|vertex| vertex.kind == "leaf")
        .filter(|vertex| {
            vertex
                .document_id
                .as_ref()
                .map(|document_id| allowed_documents.contains(document_id))
                .unwrap_or(false)
        })
        .map(|vertex| vertex.id.0.clone())
        .collect::<Vec<_>>();
    chunk_ids.sort();
    if let Some(limit) = request.limit {
        if chunk_ids.len() > limit {
            chunk_ids.truncate(limit);
            diagnostics.push(Diagnostic {
                code: "PX_GRAPH_DELTA_LIMIT".to_owned(),
                message: format!("Graph delta limited to {limit} leaf chunks for this response."),
            });
        }
    }

    let chunk_id_set = chunk_ids.iter().cloned().collect::<HashSet<_>>();
    let mut included_nodes = chunk_id_set.clone();
    let mut adjacency = HashMap::<String, Vec<&KernelEdge>>::new();
    for edge in graph
        .asserted_edges
        .iter()
        .chain(graph.candidate_edges.iter())
    {
        adjacency
            .entry(edge.source_id.0.clone())
            .or_default()
            .push(edge);
        adjacency
            .entry(edge.target_id.0.clone())
            .or_default()
            .push(edge);
    }

    for chunk_id in &chunk_ids {
        if let Some(edges) = adjacency.get(chunk_id) {
            for edge in edges {
                let neighbor_id = kernel_edge_neighbor_id(edge, chunk_id);
                if let Some(vertex) = vertices.get(neighbor_id) {
                    if matches!(vertex.kind.as_str(), "entity" | "event") {
                        included_nodes.insert(neighbor_id.to_owned());
                    }
                }
            }
        }
    }

    let mut traversal_depths = HashMap::<String, usize>::new();
    let mut traversal_frontier = std::collections::VecDeque::new();
    for document_id in &allowed_documents {
        let vertex_id = phase1_document_vertex_id(document_id);
        if vertices.contains_key(&vertex_id) {
            traversal_depths.insert(vertex_id.clone(), 0);
            traversal_frontier.push_back(vertex_id.clone());
            included_nodes.insert(vertex_id);
        }
    }
    while let Some(vertex_id) = traversal_frontier.pop_front() {
        let depth = *traversal_depths.get(&vertex_id).unwrap_or(&0);
        if depth >= 2 {
            continue;
        }
        let Some(edges) = adjacency.get(&vertex_id) else {
            continue;
        };
        for edge in edges {
            let neighbor_id = kernel_edge_neighbor_id(edge, &vertex_id);
            let Some(vertex) = vertices.get(neighbor_id) else {
                continue;
            };
            if !kernel_delta_vertex_allowed(vertex, &allowed_documents, &chunk_id_set) {
                continue;
            }
            let next_depth = depth + 1;
            let should_visit = traversal_depths
                .get(neighbor_id)
                .map(|current| next_depth < *current)
                .unwrap_or(true);
            if should_visit {
                traversal_depths.insert(neighbor_id.to_owned(), next_depth);
                traversal_frontier.push_back(neighbor_id.to_owned());
            }
            included_nodes.insert(neighbor_id.to_owned());
        }
    }

    let chunks = chunk_ids
        .iter()
        .filter_map(|chunk_id| {
            let vertex = vertices.get(chunk_id)?;
            let document_id = vertex.document_id.as_ref()?.clone();
            Some(GraphDeltaChunk {
                vertex_id: vertex.id.0.clone(),
                chunk_id: vertex.search_chunk_id.clone().unwrap_or_default(),
                document_id: DocumentId(document_id),
                note_id: vertex
                    .attributes
                    .get("noteId")
                    .and_then(Value::as_str)
                    .map(|value| NoteId(value.to_owned())),
                chapter_id: vertex.chapter_id.unwrap_or_default(),
                boundary_id: vertex.boundary_id,
                boundary_ordinal: vertex.boundary_ordinal,
                range: TextRange {
                    start: vertex
                        .attributes
                        .get("start")
                        .and_then(Value::as_u64)
                        .unwrap_or_default() as u32,
                    end: vertex
                        .attributes
                        .get("end")
                        .and_then(Value::as_u64)
                        .unwrap_or_default() as u32,
                },
            })
        })
        .collect::<Vec<_>>();

    let mut extra_node_ids = included_nodes
        .iter()
        .filter(|vertex_id| !chunk_id_set.contains(*vertex_id))
        .cloned()
        .collect::<Vec<_>>();
    extra_node_ids.sort();
    let nodes = extra_node_ids
        .iter()
        .filter_map(|node_id| {
            let vertex = vertices.get(node_id)?;
            Some(GraphDeltaNode {
                node_id: vertex.id.0.clone(),
                kind: vertex.kind.clone(),
                label: kernel_vertex_label(vertex),
                entity_id: vertex
                    .entity_id
                    .as_ref()
                    .map(|value| EntityId(value.clone())),
                document_id: vertex
                    .document_id
                    .as_ref()
                    .map(|value| DocumentId(value.clone())),
                chapter_id: vertex.chapter_id,
                boundary_id: vertex.boundary_id,
                boundary_ordinal: vertex.boundary_ordinal,
                weight: vertex.weight as i32,
            })
        })
        .collect::<Vec<_>>();

    let mut edge_keys = HashSet::new();
    let mut edges = Vec::new();
    for edge in graph
        .asserted_edges
        .iter()
        .chain(graph.candidate_edges.iter())
    {
        if included_nodes.contains(&edge.source_id.0)
            && included_nodes.contains(&edge.target_id.0)
            && edge_keys.insert((
                edge.source_id.0.clone(),
                edge.target_id.0.clone(),
                edge.edge_type.0.clone(),
            ))
        {
            edges.push(GraphDeltaEdge {
                source_id: edge.source_id.0.clone(),
                target_id: edge.target_id.0.clone(),
                edge_type: edge.edge_type.0.clone(),
                weight: edge.weight as i32,
            });
        }
    }
    edges.sort_by(|left, right| {
        (&left.source_id, &left.target_id, &left.edge_type).cmp(&(
            &right.source_id,
            &right.target_id,
            &right.edge_type,
        ))
    });

    GraphDeltaResult {
        session_id: request.session_id.clone(),
        chunks,
        nodes,
        edges,
        diagnostics,
    }
}

fn runtime_graph_delta_allowed_documents(
    state: &SessionState,
    request: &GraphDeltaRequest,
) -> BTreeSet<String> {
    if request.changed_documents.is_empty() {
        return state
            .documents
            .iter()
            .map(|document| document.document_id.0.clone())
            .collect();
    }
    request
        .changed_documents
        .iter()
        .map(|document| document.0.clone())
        .collect()
}

fn runtime_graph_delta_diagnostics(request: &GraphDeltaRequest) -> Vec<Diagnostic> {
    request
        .since_commit
        .as_ref()
        .map(|since_commit| Diagnostic {
            code: "PX_GRAPH_DELTA_KERNEL".to_owned(),
            message: format!(
                "Native graph delta used kernel rows; sinceCommit {} was treated as a journal hint.",
                since_commit.0
            ),
        })
        .into_iter()
        .collect()
}

fn kernel_edge_neighbor_id<'a>(edge: &'a KernelEdge, vertex_id: &str) -> &'a str {
    if edge.source_id.0 == vertex_id {
        edge.target_id.0.as_str()
    } else {
        edge.source_id.0.as_str()
    }
}

fn kernel_delta_vertex_allowed(
    vertex: &KernelVertex,
    allowed_documents: &BTreeSet<String>,
    chunk_ids: &HashSet<String>,
) -> bool {
    if chunk_ids.contains(&vertex.id.0) {
        return true;
    }
    match vertex.document_id.as_ref() {
        Some(document_id) => allowed_documents.contains(document_id),
        None => true,
    }
}

fn kernel_vertex_label(vertex: &KernelVertex) -> String {
    vertex
        .value
        .get("label")
        .and_then(Value::as_str)
        .or_else(|| vertex.value.get("lemma").and_then(Value::as_str))
        .or_else(|| {
            vertex
                .entity_facet
                .as_ref()
                .and_then(|facet| facet.surface.as_deref())
        })
        .unwrap_or(vertex.id.0.as_str())
        .to_owned()
}

fn project_kernel_graph_vertices(graph: &KernelGraphSnapshot) -> Vec<Value> {
    graph
        .vertices
        .iter()
        .map(kernel_vertex_to_row_value)
        .collect()
}

fn project_kernel_graph_vertex_labels(graph: &KernelGraphSnapshot) -> Vec<Value> {
    graph
        .vertices
        .iter()
        .map(|vertex| {
            json!({
                "vertex_id": vertex.id.0,
                "label": kernel_vertex_label(vertex),
            })
        })
        .collect()
}

fn project_kernel_graph_edges(graph: &KernelGraphSnapshot, layer: KernelGraphLayer) -> Vec<Value> {
    let edges = match layer {
        KernelGraphLayer::Asserted => graph.asserted_edges.as_slice(),
        KernelGraphLayer::Candidate => graph.candidate_edges.as_slice(),
    };
    edges.iter().map(kernel_edge_to_row_value).collect()
}

fn project_kernel_graph_node_index(graph: &KernelGraphSnapshot) -> Vec<Value> {
    graph
        .vertices
        .iter()
        .enumerate()
        .map(|(index, vertex)| {
            json!({
                "id": vertex.id.0,
                "idx": index as i64,
            })
        })
        .collect()
}

fn project_kernel_graph_properties(graph: &KernelGraphSnapshot) -> Vec<Value> {
    let mut rows = Vec::new();
    for vertex in &graph.vertices {
        if let Some(attributes) = vertex.attributes.as_object() {
            for (key, value) in attributes {
                rows.push(json!({
                    "owner_id": vertex.id.0,
                    "owner_type": "vertex",
                    "key": key,
                    "valid_from": 0,
                    "value_type": graph_property_value_type(value),
                    "value_blob": value,
                    "valid_until": null,
                    "txn_id": 0,
                }));
            }
        }
    }
    for edge in graph
        .asserted_edges
        .iter()
        .chain(graph.candidate_edges.iter())
    {
        if let Some(attributes) = edge.attributes.as_object() {
            let owner_id = format!(
                "{}::{}::{}",
                edge.source_id.0, edge.edge_type.0, edge.target_id.0
            );
            for (key, value) in attributes {
                rows.push(json!({
                    "owner_id": owner_id,
                    "owner_type": "edge",
                    "key": key,
                    "valid_from": 0,
                    "value_type": graph_property_value_type(value),
                    "value_blob": value,
                    "valid_until": null,
                    "txn_id": 0,
                }));
            }
        }
    }
    rows
}

fn collect_kernel_vertex_document_refs(vertex: &KernelVertex, out: &mut BTreeSet<String>) {
    if let Some(document_id) = vertex.document_id.as_ref() {
        out.insert(document_id.clone());
    }
    collect_identifier_document_refs(&vertex.id.0, out);
    if let Some(search_chunk_id) = vertex.search_chunk_id.as_ref() {
        collect_identifier_document_refs(search_chunk_id, out);
    }
    collect_document_refs_from_value(&vertex.attributes, out);
    collect_document_refs_from_value(&vertex.value, out);
}

fn collect_kernel_edge_document_refs(edge: &KernelEdge, out: &mut BTreeSet<String>) {
    if let Some(document_id) = edge.document_id.as_ref() {
        out.insert(document_id.clone());
    }
    collect_identifier_document_refs(&edge.source_id.0, out);
    collect_identifier_document_refs(&edge.target_id.0, out);
    collect_document_refs_from_value(&edge.attributes, out);
    if let Some(data) = edge.data.as_ref() {
        collect_document_refs_from_value(data, out);
    }
}

fn kernel_graph_item_is_live_vertex(
    vertex: &KernelVertex,
    live_document_ids: &HashSet<String>,
) -> bool {
    let mut refs = BTreeSet::new();
    collect_kernel_vertex_document_refs(vertex, &mut refs);
    refs.is_empty()
        || refs
            .iter()
            .all(|document_id| live_document_ids.contains(document_id))
}

fn kernel_graph_item_is_live_edge(edge: &KernelEdge, live_document_ids: &HashSet<String>) -> bool {
    let mut refs = BTreeSet::new();
    collect_kernel_edge_document_refs(edge, &mut refs);
    refs.is_empty()
        || refs
            .iter()
            .all(|document_id| live_document_ids.contains(document_id))
}

fn collect_document_refs_from_value(value: &Value, out: &mut BTreeSet<String>) {
    match value {
        Value::String(text) => collect_identifier_document_refs(text, out),
        Value::Array(values) => {
            for value in values {
                collect_document_refs_from_value(value, out);
            }
        }
        Value::Object(object) => {
            for value in object.values() {
                collect_document_refs_from_value(value, out);
            }
        }
        _ => {}
    }
}

fn collect_identifier_document_refs(value: &str, out: &mut BTreeSet<String>) {
    let bytes = value.as_bytes();
    if bytes.len() < 36 {
        return;
    }
    for start in 0..=bytes.len() - 36 {
        if is_uuid_like_at(bytes, start) {
            if let Ok(document_id) = std::str::from_utf8(&bytes[start..start + 36]) {
                out.insert(document_id.to_ascii_lowercase());
            }
        }
    }
}

fn is_uuid_like_at(bytes: &[u8], start: usize) -> bool {
    const DASHES: [usize; 4] = [8, 13, 18, 23];
    for offset in 0..36 {
        let byte = bytes[start + offset];
        if DASHES.contains(&offset) {
            if byte != b'-' {
                return false;
            }
        } else if !byte.is_ascii_hexdigit() {
            return false;
        }
    }
    true
}

fn graph_property_value_type(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Number(number) if number.is_i64() || number.is_u64() => "int",
        Value::Number(_) => "float",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

fn native_candidate_definition_row_id(scope_key: &str) -> String {
    format!("phoenix.graph.candidate::{scope_key}")
}

fn native_candidate_scope_key_for_document(document_id: &str) -> String {
    format!("document:{document_id}")
}

fn native_candidate_scope_key_for_node(node_id: &str) -> String {
    format!("node:{node_id}")
}

fn native_candidate_scope_key_for_row(row: &Value) -> Option<String> {
    row.as_object().and_then(|object| {
        runtime_row_document_id(object)
            .map(|document_id| native_candidate_scope_key_for_document(&document_id))
            .or_else(|| {
                object
                    .get("source_id")
                    .and_then(Value::as_str)
                    .map(native_candidate_scope_key_for_node)
            })
    })
}

fn native_candidate_batches_from_rows(
    rows: Vec<Value>,
    touched_scope_keys: &BTreeSet<String>,
) -> Vec<GraphMutationBatch> {
    let mut rows_by_scope = BTreeMap::<String, Vec<Value>>::new();
    for scope_key in touched_scope_keys {
        rows_by_scope.entry(scope_key.clone()).or_default();
    }
    for row in rows {
        let Some(scope_key) = native_candidate_scope_key_for_row(&row) else {
            continue;
        };
        if touched_scope_keys.contains(&scope_key) {
            rows_by_scope.entry(scope_key).or_default().push(row);
        }
    }
    touched_scope_keys
        .iter()
        .map(|scope_key| GraphMutationBatch {
            layer: GraphLayer::Candidate,
            scope: GraphMutationScope::Candidate {
                scope_key: scope_key.clone(),
            },
            vertices: Vec::new(),
            edges: rows_by_scope
                .remove(scope_key)
                .unwrap_or_default()
                .into_iter()
                .filter_map(|row| graph_edge_record_from_row_value(&row, GraphLayer::Candidate))
                .collect(),
        })
        .collect()
}

#[allow(dead_code)]
fn phase1_thread_matches_session(session: &SessionRecord, thread: &Thread) -> bool {
    phase1_scope_field_matches(session.scope.world_id.as_deref(), &thread.world_id)
        && phase1_scope_field_matches(session.scope.narrative_id.as_deref(), &thread.narrative_id)
}

#[allow(dead_code)]
fn phase1_scope_field_matches(expected: Option<&str>, actual: &str) -> bool {
    match expected.filter(|value| !value.is_empty()) {
        Some(expected) => actual == expected,
        None => actual.is_empty(),
    }
}

#[allow(dead_code)]
#[cfg(feature = "legacy-cozo-graph")]
fn phase1_message_document_links(
    session_state: &SessionState,
    graph: &Phase2GraphView,
) -> HashMap<String, BTreeSet<String>> {
    let allowed_documents = session_state
        .documents
        .iter()
        .map(|document| document.document_id.0.clone())
        .collect::<BTreeSet<_>>();
    let mut links = HashMap::<String, BTreeSet<String>>::new();
    for vertex in graph.vertices.values() {
        if vertex.kind != "thread_document" {
            continue;
        }
        let Some(document_id) = vertex.document_id.as_ref().cloned().or_else(|| {
            vertex
                .value
                .get("documentId")
                .and_then(Value::as_str)
                .map(str::to_owned)
        }) else {
            continue;
        };
        if !allowed_documents.contains(&document_id) {
            continue;
        }
        let Some(message_ids) = vertex
            .attributes
            .get("messageIds")
            .and_then(Value::as_array)
        else {
            continue;
        };
        for message_id in message_ids.iter().filter_map(Value::as_str) {
            links
                .entry(message_id.to_owned())
                .or_default()
                .insert(document_id.clone());
        }
    }
    links
}

#[allow(dead_code)]
fn phase1_document_links_for_message(
    message_id: &str,
    message_document_links: &HashMap<String, BTreeSet<String>>,
    singleton_document_id: Option<&str>,
) -> Vec<String> {
    if let Some(document_ids) = message_document_links.get(message_id) {
        return document_ids.iter().cloned().collect();
    }
    singleton_document_id
        .map(|document_id| vec![document_id.to_owned()])
        .unwrap_or_default()
}

#[allow(dead_code)]
fn phase1_graph_metadata(evidence_refs: Vec<String>) -> Value {
    json!({
        "layer": "asserted",
        "status": "asserted",
        "resolver": "phoenix-runtime/native",
        "confidence": 1.0,
        "evidence_refs": evidence_refs,
    })
}

#[allow(dead_code)]
fn phase1_vertex_row(
    id: &str,
    kind: &str,
    label: &str,
    document_id: Option<&str>,
    narrative_id: Option<&str>,
    mut attributes: Map<String, Value>,
    evidence_refs: Vec<String>,
) -> Value {
    if let Some(document_id) = document_id {
        attributes.insert("documentId".to_owned(), json!(document_id));
    }
    attributes.insert("graph".to_owned(), phase1_graph_metadata(evidence_refs));
    json!({
        "id": id,
        "document_id": document_id,
        "narrative_id": narrative_id,
        "value": {
            "kind": kind,
            "label": label,
        },
        "weight": 1,
        "attributes": Value::Object(attributes),
    })
}

#[allow(dead_code)]
fn phase1_time_vertex_row(
    id: &str,
    session_id: &SessionId,
    source_kind: &str,
    source_id: &str,
    timestamp_ms: i64,
    narrative_id: Option<&str>,
    evidence_refs: Vec<String>,
) -> Value {
    let mut attributes = Map::new();
    attributes.insert("sessionId".to_owned(), json!(session_id.0));
    attributes.insert("sourceKind".to_owned(), json!(source_kind));
    attributes.insert("sourceId".to_owned(), json!(source_id));
    attributes.insert("timestampMs".to_owned(), json!(timestamp_ms));
    phase1_vertex_row(
        id,
        "time_window",
        &format!("{source_kind}@{timestamp_ms}"),
        None,
        narrative_id,
        attributes,
        evidence_refs,
    )
}

#[allow(dead_code)]
fn phase1_edge_row(
    source_id: &str,
    target_id: &str,
    edge_type: &str,
    document_id: Option<&str>,
    narrative_id: Option<&str>,
    mut attributes: Map<String, Value>,
    evidence_refs: Vec<String>,
) -> Value {
    if let Some(document_id) = document_id {
        attributes
            .entry("documentId".to_owned())
            .or_insert_with(|| json!(document_id));
    }
    attributes.insert("graph".to_owned(), phase1_graph_metadata(evidence_refs));
    json!({
        "source_id": source_id,
        "target_id": target_id,
        "document_id": document_id,
        "narrative_id": narrative_id,
        "valid_from_doc": document_id,
        "valid_from_boundary": null,
        "valid_to_doc": null,
        "valid_to_boundary": null,
        "assertion_kind": "asserted",
        "weight": 1,
        "attributes": Value::Object(attributes),
        "data": null,
        "edge_type": edge_type,
    })
}

#[allow(dead_code)]
fn phase1_push_vertex(
    vertex_ids: &mut BTreeSet<String>,
    vertex_rows: &mut Vec<Value>,
    label_rows: &mut Vec<Value>,
    row: Value,
) {
    let Some(id) = row.get("id").and_then(Value::as_str).map(str::to_owned) else {
        return;
    };
    if !vertex_ids.insert(id.clone()) {
        return;
    }
    let label = row
        .get("value")
        .and_then(Value::as_object)
        .and_then(|value| value.get("label"))
        .and_then(Value::as_str)
        .unwrap_or(id.as_str())
        .to_owned();
    label_rows.push(json!({
        "vertex_id": id,
        "label": label,
    }));
    vertex_rows.push(row);
}

fn push_frame_graph_projection(
    vertex_ids: &mut BTreeSet<String>,
    vertex_rows: &mut Vec<Value>,
    label_rows: &mut Vec<Value>,
    edge_rows: &mut Vec<Value>,
    frame_edge_keys: &mut BTreeSet<(String, String, String)>,
    scan_id: &str,
    document: &AtlasRichScanDocument,
    structure: &StructureArtifact,
) {
    let document_id = document.document_id.0.as_str();
    let narrative_id = document.scope.narrative_id.as_deref();
    for frame in &structure.umr_frames {
        let frame_id =
            frame_extraction::persisted_frame_id(scan_id, &document.document_id, &frame.frame_id);
        let frame_vertex_id = format!("event::{frame_id}");
        let frame_evidence_refs = vec![
            format!("document:{}", document.document_id.0),
            format!("frame:{frame_id}"),
        ];
        let mut attributes = Map::new();
        attributes.insert("pipelineSource".to_owned(), json!("umr_lite_v1"));
        attributes.insert("frameId".to_owned(), json!(frame_id));
        attributes.insert("lemma".to_owned(), json!(frame.lemma));
        attributes.insert("eventClass".to_owned(), json!(frame.event_class));
        attributes.insert("relationType".to_owned(), json!(frame.relation_type));
        attributes.insert("sentenceIndex".to_owned(), json!(frame.sentence_index));
        attributes.insert("confidence".to_owned(), json!(frame.confidence));
        attributes.insert(
            "triggerRange".to_owned(),
            text_range_value(frame.trigger_range),
        );
        attributes.insert(
            "clauseRange".to_owned(),
            text_range_value(frame.clause_range),
        );
        phase1_push_vertex(
            vertex_ids,
            vertex_rows,
            label_rows,
            phase1_vertex_row(
                &frame_vertex_id,
                "event",
                frame.lemma.as_str(),
                Some(document_id),
                narrative_id,
                attributes,
                frame_evidence_refs.clone(),
            ),
        );

        for argument in &frame.arguments {
            let Some(entity_id) = umr_argument_known_entity_id(argument) else {
                continue;
            };
            let entity_vertex_id = format!("entity::{entity_id}");
            push_frame_entity_vertex(
                vertex_ids,
                vertex_rows,
                label_rows,
                &entity_vertex_id,
                &argument.surface,
                document_id,
                narrative_id,
                frame_evidence_refs.clone(),
            );
            let role = umr_role_name(&argument.role);
            let mut attributes = Map::new();
            attributes.insert("pipelineSource".to_owned(), json!("umr_lite_v1"));
            attributes.insert("frameId".to_owned(), json!(frame_id));
            attributes.insert("role".to_owned(), json!(role));
            attributes.insert("surface".to_owned(), json!(argument.surface));
            attributes.insert("range".to_owned(), text_range_value(argument.range));
            attributes.insert("confidence".to_owned(), json!(argument.confidence));
            if let Some(source) = argument.source.as_ref() {
                attributes.insert(
                    "source".to_owned(),
                    json!(format!("{source:?}").to_ascii_lowercase()),
                );
            }
            phase1_push_typed_edge(
                frame_edge_keys,
                edge_rows,
                phase1_edge_row(
                    &frame_vertex_id,
                    &entity_vertex_id,
                    &format!("frameRole:{role}"),
                    Some(document_id),
                    narrative_id,
                    attributes,
                    frame_evidence_refs.clone(),
                ),
            );
        }
    }

    for fact in &structure.frame_facts {
        let Some(subject_id) = frame_extraction::fact_entity_id(&fact.subject) else {
            continue;
        };
        let Some(object_id) = frame_extraction::fact_entity_id(&fact.object) else {
            continue;
        };
        let frame_id =
            frame_extraction::persisted_frame_id(scan_id, &document.document_id, &fact.frame_id);
        let fact_evidence_refs = vec![
            format!("document:{}", document.document_id.0),
            format!("frame:{frame_id}"),
            format!("frame_fact:{}", fact.fact_id),
        ];
        let mut attributes = Map::new();
        attributes.insert("pipelineSource".to_owned(), json!("umr_lite_fact_v1"));
        attributes.insert("frameId".to_owned(), json!(frame_id));
        attributes.insert("factId".to_owned(), json!(fact.fact_id));
        attributes.insert("factKind".to_owned(), json!(fact.fact_kind));
        attributes.insert("confidence".to_owned(), json!(fact.confidence));
        phase1_push_typed_edge(
            frame_edge_keys,
            edge_rows,
            phase1_edge_row(
                &format!("entity::{subject_id}"),
                &format!("entity::{object_id}"),
                &fact.predicate,
                Some(document_id),
                narrative_id,
                attributes,
                fact_evidence_refs,
            ),
        );
    }
}

fn push_frame_entity_vertex(
    vertex_ids: &mut BTreeSet<String>,
    vertex_rows: &mut Vec<Value>,
    label_rows: &mut Vec<Value>,
    entity_vertex_id: &str,
    label: &str,
    document_id: &str,
    narrative_id: Option<&str>,
    evidence_refs: Vec<String>,
) {
    let mut attributes = Map::new();
    attributes.insert("pipelineSource".to_owned(), json!("umr_lite_v1"));
    attributes.insert("entityKind".to_owned(), json!("UNKNOWN"));
    phase1_push_vertex(
        vertex_ids,
        vertex_rows,
        label_rows,
        phase1_vertex_row(
            entity_vertex_id,
            "entity",
            label,
            Some(document_id),
            narrative_id,
            attributes,
            evidence_refs,
        ),
    );
}

fn phase1_push_typed_edge(
    edge_keys: &mut BTreeSet<(String, String, String)>,
    edge_rows: &mut Vec<Value>,
    row: Value,
) {
    let Some(source_id) = row
        .get("source_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    let Some(target_id) = row
        .get("target_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    let Some(edge_type) = row
        .get("edge_type")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    if edge_keys.insert((source_id, target_id, edge_type)) {
        edge_rows.push(row);
    }
}

fn umr_argument_known_entity_id(argument: &UmrLiteArgument) -> Option<&str> {
    match argument.entity_ref.as_ref() {
        Some(MentionEntityRef::Known(entity_id)) => Some(entity_id.0.as_str()),
        _ => None,
    }
}

fn umr_role_name(role: &UmrLiteRole) -> &'static str {
    match role {
        UmrLiteRole::Actor => "actor",
        UmrLiteRole::Target => "target",
        UmrLiteRole::Recipient => "recipient",
        UmrLiteRole::Location => "location",
        UmrLiteRole::Time => "time",
        UmrLiteRole::Instrument => "instrument",
        UmrLiteRole::Source => "source",
        UmrLiteRole::Destination => "destination",
        UmrLiteRole::Cause => "cause",
        UmrLiteRole::Outcome => "outcome",
    }
}

fn text_range_value(range: TextRange) -> Value {
    json!({
        "start": range.start,
        "end": range.end,
    })
}

#[allow(dead_code)]
fn phase1_push_edge(
    edge_pairs: &mut BTreeSet<(String, String)>,
    edge_rows: &mut Vec<Value>,
    row: Value,
) {
    let Some(source_id) = row
        .get("source_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    let Some(target_id) = row
        .get("target_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    if edge_pairs.insert((source_id, target_id)) {
        edge_rows.push(row);
    }
}

const PHASE2_DOC_SIMILAR_TO_THRESHOLD: f64 = 0.72;
const PHASE2_ENTITY_COREF_THRESHOLD: f64 = 0.78;
const PHASE2_EVENT_MATCH_THRESHOLD: f64 = 0.74;
const PHASE2_ABOUT_THRESHOLD: f64 = 0.66;
const PHASE2_RELEVANT_TO_THRESHOLD: f64 = 0.62;
const PHASE2_EMBEDDING_RESOLVER: &str = "phoenix-runtime/embedding-candidate";
const SEMANTIC_NLI_MODEL_ID: &str = "onnx-community/ModernBERT-base-nli-ONNX";
const PHASE2_NLI_RESOLVER: &str = "phoenix-runtime/nli-edge-judge";
const PHASE2_NLI_MAX_INPUTS: usize = 256;
const PHASE2_NLI_MAX_EVIDENCE_TARGETS: usize = 4;
const PHASE2_NLI_MAX_LEAF_EVIDENCE_PER_SOURCE: usize = 3;
const PHASE2_NLI_COREF_THRESHOLD: f64 = 0.68;
const PHASE2_NLI_EVENT_THRESHOLD: f64 = 0.66;
const PHASE2_NLI_ABOUT_THRESHOLD: f64 = 0.58;
const PHASE2_NLI_RELEVANT_TO_THRESHOLD: f64 = 0.55;
const PHASE2_NLI_SUPPORTED_BY_THRESHOLD: f64 = 0.62;
const PHASE2_NLI_CONTRADICTED_BY_THRESHOLD: f64 = 0.66;

fn phase2_leaf_vertex_id(span_id: &str) -> String {
    format!("leaf::{span_id}")
}

fn phase2_leaf_context_map(
    leaf_chunks: &[SemanticLeafChunk],
) -> HashMap<String, Phase2LeafContext> {
    leaf_chunks
        .iter()
        .map(|leaf| {
            (
                phase2_leaf_vertex_id(&leaf.span_id),
                Phase2LeafContext {
                    document_id: leaf.document_id.clone(),
                    narrative_id: leaf.narrative_id.clone(),
                    folder_id: leaf.folder_id.clone(),
                    text: leaf.text.clone(),
                },
            )
        })
        .collect()
}

fn phase2_document_scope_from_leaf_chunks(
    leaf_chunks: &[SemanticLeafChunk],
) -> HashMap<String, ScopeKey> {
    let mut scopes = HashMap::new();
    for leaf in leaf_chunks {
        scopes
            .entry(leaf.document_id.clone())
            .or_insert_with(|| ScopeKey {
                world_id: None,
                narrative_id: leaf.narrative_id.clone(),
                folder_id: leaf.folder_id.clone(),
                folder_path: None,
            });
    }
    scopes
}

fn phase2_document_support_from_leaf_chunks(
    leaf_chunks: &[SemanticLeafChunk],
) -> HashMap<String, Vec<String>> {
    let mut support = HashMap::<String, Vec<String>>::new();
    for leaf in leaf_chunks {
        let entry = support.entry(leaf.document_id.clone()).or_default();
        if entry.len() < 3 {
            let text = leaf.text.trim();
            if !text.is_empty() {
                entry.push(text.to_owned());
            }
        }
    }
    support
}

fn phase2_thread_message_map(
    rows: Vec<Value>,
) -> Result<HashMap<String, ThreadMessage>, StoreError> {
    let mut messages = HashMap::new();
    for row in rows {
        let Ok(message) = serde_json::from_value::<ThreadMessage>(row) else {
            continue;
        };
        messages.insert(message.id.clone(), message);
    }
    Ok(messages)
}

fn phase2_document_vector_map(
    rows: Vec<Value>,
    document_ids: &[String],
) -> Result<HashMap<String, StoredSemanticDocumentVector>, StoreError> {
    let allowed = document_ids.iter().cloned().collect::<HashSet<_>>();
    let mut vectors = HashMap::new();
    for row in rows {
        let Some(document_id) = row.get("document_id").and_then(Value::as_str) else {
            continue;
        };
        if !allowed.is_empty() && !allowed.contains(document_id) {
            continue;
        }
        let Some(values) = phase2_json_vector(row.get("vec")) else {
            continue;
        };
        vectors.insert(
            document_id.to_owned(),
            StoredSemanticDocumentVector {
                values,
                evidence_refs: phase2_json_string_array(row.get("evidence_refs")),
            },
        );
    }
    Ok(vectors)
}

fn phase2_node_vector_map(
    rows: Vec<Value>,
    node_ids: &[String],
) -> Result<HashMap<String, StoredSemanticNodeVector>, StoreError> {
    let allowed = node_ids.iter().cloned().collect::<HashSet<_>>();
    let mut vectors = HashMap::new();
    for row in rows {
        let Some(node_id) = row.get("node_id").and_then(Value::as_str) else {
            continue;
        };
        if !allowed.is_empty() && !allowed.contains(node_id) {
            continue;
        }
        let Some(values) = phase2_json_vector(row.get("vec")) else {
            continue;
        };
        vectors.insert(
            node_id.to_owned(),
            StoredSemanticNodeVector {
                node_id: node_id.to_owned(),
                node_kind: row
                    .get("node_kind")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
                document_id: row
                    .get("document_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                narrative_id: row
                    .get("narrative_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                folder_id: row
                    .get("folder_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                values,
                evidence_refs: phase2_json_string_array(row.get("evidence_refs")),
            },
        );
    }
    Ok(vectors)
}

fn phase2_entity_prototype_input(
    graph: &Phase2GraphView,
    leaf_context: &HashMap<String, Phase2LeafContext>,
    document_scopes: &HashMap<String, ScopeKey>,
    entity_id: &str,
) -> Option<SemanticCandidatePrototypeInput> {
    let vertex = graph.vertices.get(entity_id)?;
    let label = vertex
        .value
        .get("label")
        .and_then(Value::as_str)
        .unwrap_or(entity_id)
        .trim()
        .to_owned();
    if label.is_empty() {
        return None;
    }

    let aliases = phase2_json_string_array(vertex.attributes.get("aliases"));
    let mut support = BTreeSet::new();
    let mut evidence_refs = phase2_graph_evidence_refs(&vertex.attributes);
    let mut document_id = vertex.document_id.clone();
    let mut narrative_id = None;
    let mut folder_id = None;

    for edge in graph
        .outgoing_any(entity_id)
        .chain(graph.incoming_any(entity_id))
    {
        if edge.edge_type != "mentions" {
            continue;
        }
        let neighbor_id = if edge.source_id == entity_id {
            edge.target_id.as_str()
        } else {
            edge.source_id.as_str()
        };
        if let Some(context) = leaf_context.get(neighbor_id) {
            support.insert(context.text.clone());
            evidence_refs.push(format!("graph_vertex:{neighbor_id}"));
            if document_id.is_none() {
                document_id = Some(context.document_id.clone());
            }
            if narrative_id.is_none() {
                narrative_id = context.narrative_id.clone();
            }
            if folder_id.is_none() {
                folder_id = context.folder_id.clone();
            }
        }
    }

    if let Some(scope) = document_id
        .as_ref()
        .and_then(|document_id| document_scopes.get(document_id))
    {
        if narrative_id.is_none() {
            narrative_id = scope.narrative_id.clone();
        }
        if folder_id.is_none() {
            folder_id = scope.folder_id.clone();
        }
    }

    let mut sections = vec![format!("entity: {label}")];
    if !aliases.is_empty() {
        sections.push(format!("aliases: {}", aliases.join(", ")));
    }
    if !support.is_empty() {
        sections.push(format!(
            "support: {}",
            support.into_iter().take(3).collect::<Vec<_>>().join(" | ")
        ));
    }

    Some(SemanticCandidatePrototypeInput {
        node_id: entity_id.to_owned(),
        node_kind: "entity".to_owned(),
        document_id,
        narrative_id,
        folder_id,
        text: sections.join("\n"),
        evidence_refs: phase2_unique_strings(evidence_refs),
    })
}

fn phase2_normalize_entity_surface(value: &str) -> Option<String> {
    let normalized = value
        .trim()
        .to_ascii_lowercase()
        .chars()
        .map(|ch| if ch.is_alphanumeric() { ch } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    (!normalized.is_empty()).then_some(normalized)
}

fn phase2_entity_surface_set(graph: &Phase2GraphView, entity_id: &str) -> BTreeSet<String> {
    let mut surfaces = BTreeSet::new();
    let Some(vertex) = graph.vertices.get(entity_id) else {
        return surfaces;
    };
    if let Some(label) = vertex.value.get("label").and_then(Value::as_str) {
        if let Some(normalized) = phase2_normalize_entity_surface(label) {
            surfaces.insert(normalized);
        }
    }
    for alias in phase2_json_string_array(vertex.attributes.get("aliases")) {
        if let Some(normalized) = phase2_normalize_entity_surface(&alias) {
            surfaces.insert(normalized);
        }
    }
    surfaces
}

fn phase2_entity_candidate_is_coherent(
    graph: &Phase2GraphView,
    source_id: &str,
    target_id: &str,
) -> bool {
    let source_surfaces = phase2_entity_surface_set(graph, source_id);
    let target_surfaces = phase2_entity_surface_set(graph, target_id);
    !source_surfaces.is_empty()
        && !target_surfaces.is_empty()
        && !source_surfaces.is_disjoint(&target_surfaces)
}

fn phase2_event_prototype_input(
    graph: &Phase2GraphView,
    leaf_context: &HashMap<String, Phase2LeafContext>,
    document_scopes: &HashMap<String, ScopeKey>,
    event_id: &str,
) -> Option<SemanticCandidatePrototypeInput> {
    let vertex = graph.vertices.get(event_id)?;
    let lemma = vertex
        .value
        .get("lemma")
        .and_then(Value::as_str)
        .unwrap_or(event_id)
        .trim()
        .to_owned();
    if lemma.is_empty() {
        return None;
    }

    let relation_type = vertex
        .value
        .get("relationType")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned();
    let event_class = vertex
        .value
        .get("eventClass")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned();

    let mut subjects = BTreeSet::new();
    let mut objects = BTreeSet::new();
    let mut recipients = BTreeSet::new();
    let mut support = BTreeSet::new();
    let mut evidence_refs = phase2_graph_evidence_refs(&vertex.attributes);
    let mut document_id = vertex.document_id.clone();
    let mut narrative_id = None;
    let mut folder_id = None;

    for edge in graph.incoming_any(event_id) {
        match edge.edge_type.as_str() {
            "has_event" => {
                if let Some(context) = leaf_context.get(edge.source_id.as_str()) {
                    support.insert(context.text.clone());
                    evidence_refs.push(format!("graph_vertex:{}", edge.source_id));
                    if document_id.is_none() {
                        document_id = Some(context.document_id.clone());
                    }
                    if narrative_id.is_none() {
                        narrative_id = context.narrative_id.clone();
                    }
                    if folder_id.is_none() {
                        folder_id = context.folder_id.clone();
                    }
                }
            }
            "event_subject" => {
                if let Some(label) = phase2_vertex_label(graph, &edge.source_id) {
                    subjects.insert(label);
                }
            }
            _ => {}
        }
    }
    for edge in graph.outgoing_any(event_id) {
        match edge.edge_type.as_str() {
            "event_object" => {
                if let Some(label) = phase2_vertex_label(graph, &edge.target_id) {
                    objects.insert(label);
                }
            }
            "event_recipient" => {
                if let Some(label) = phase2_vertex_label(graph, &edge.target_id) {
                    recipients.insert(label);
                }
            }
            _ => {}
        }
    }

    if let Some(scope) = document_id
        .as_ref()
        .and_then(|document_id| document_scopes.get(document_id))
    {
        if narrative_id.is_none() {
            narrative_id = scope.narrative_id.clone();
        }
        if folder_id.is_none() {
            folder_id = scope.folder_id.clone();
        }
    }

    let mut sections = vec![format!("event: {lemma}")];
    if !relation_type.is_empty() {
        sections.push(format!("relation: {relation_type}"));
    }
    if !event_class.is_empty() {
        sections.push(format!("class: {event_class}"));
    }
    if !subjects.is_empty() {
        sections.push(format!(
            "subjects: {}",
            subjects.into_iter().collect::<Vec<_>>().join(", ")
        ));
    }
    if !objects.is_empty() {
        sections.push(format!(
            "objects: {}",
            objects.into_iter().collect::<Vec<_>>().join(", ")
        ));
    }
    if !recipients.is_empty() {
        sections.push(format!(
            "recipients: {}",
            recipients.into_iter().collect::<Vec<_>>().join(", ")
        ));
    }
    if !support.is_empty() {
        sections.push(format!(
            "support: {}",
            support.into_iter().take(3).collect::<Vec<_>>().join(" | ")
        ));
    }

    Some(SemanticCandidatePrototypeInput {
        node_id: event_id.to_owned(),
        node_kind: "event".to_owned(),
        document_id,
        narrative_id,
        folder_id,
        text: sections.join("\n"),
        evidence_refs: phase2_unique_strings(evidence_refs),
    })
}

fn phase2_turn_prototype_input(
    vertex: &GraphVertexRecord,
    messages: &HashMap<String, ThreadMessage>,
    document_scopes: &HashMap<String, ScopeKey>,
) -> Option<SemanticCandidatePrototypeInput> {
    let message_id = vertex
        .attributes
        .get("messageId")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .or_else(|| vertex.id.strip_prefix("turn::").map(str::to_owned))?;
    let message = messages.get(&message_id)?;
    let document_id = vertex.document_id.clone();
    let (narrative_id, folder_id) =
        phase2_scope_for_document(document_scopes, document_id.as_deref());
    Some(SemanticCandidatePrototypeInput {
        node_id: vertex.id.clone(),
        node_kind: "turn".to_owned(),
        document_id,
        narrative_id: if !message.narrative_id.trim().is_empty() {
            Some(message.narrative_id.clone())
        } else {
            narrative_id
        },
        folder_id,
        text: format!("turn [{}]: {}", message.role, message.content.trim()),
        evidence_refs: phase2_unique_strings(vec![
            format!("thread_message:{}", message.id),
            format!("graph_vertex:{}", vertex.id),
        ]),
    })
}

fn phase2_task_prototype_input(
    vertex: &GraphVertexRecord,
    document_scopes: &HashMap<String, ScopeKey>,
) -> Option<SemanticCandidatePrototypeInput> {
    let task = vertex
        .attributes
        .get("currentTask")
        .and_then(Value::as_str)
        .or_else(|| vertex.value.get("label").and_then(Value::as_str))
        .map(str::trim)
        .filter(|value| !value.is_empty())?
        .to_owned();
    let document_id = vertex.document_id.clone();
    let (narrative_id, folder_id) =
        phase2_scope_for_document(document_scopes, document_id.as_deref());
    Some(SemanticCandidatePrototypeInput {
        node_id: vertex.id.clone(),
        node_kind: "task".to_owned(),
        document_id,
        narrative_id,
        folder_id,
        text: format!("task: {task}"),
        evidence_refs: phase2_unique_strings(phase2_graph_evidence_refs(&vertex.attributes)),
    })
}

fn phase2_state_prototype_input(
    vertex: &GraphVertexRecord,
    document_scopes: &HashMap<String, ScopeKey>,
) -> Option<SemanticCandidatePrototypeInput> {
    let label = vertex
        .value
        .get("label")
        .and_then(Value::as_str)
        .or_else(|| vertex.attributes.get("kind").and_then(Value::as_str))
        .map(str::trim)
        .filter(|value| !value.is_empty())?
        .to_owned();
    let document_id = vertex.document_id.clone();
    let (narrative_id, folder_id) =
        phase2_scope_for_document(document_scopes, document_id.as_deref());
    let phase = vertex
        .attributes
        .get("phase")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let kind = vertex
        .attributes
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let status = vertex
        .attributes
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let mut parts = vec![format!("state: {label}")];
    if !phase.is_empty() || !kind.is_empty() || !status.is_empty() {
        parts.push(
            [phase, kind, status]
                .into_iter()
                .filter(|value| !value.is_empty())
                .collect::<Vec<_>>()
                .join(" / "),
        );
    }
    Some(SemanticCandidatePrototypeInput {
        node_id: vertex.id.clone(),
        node_kind: "state".to_owned(),
        document_id,
        narrative_id,
        folder_id,
        text: parts.join("\n"),
        evidence_refs: phase2_unique_strings(phase2_graph_evidence_refs(&vertex.attributes)),
    })
}

fn phase2_document_prototype_input(
    graph: &Phase2GraphView,
    document_support: &HashMap<String, Vec<String>>,
    document_id: &str,
) -> Option<SemanticCandidatePrototypeInput> {
    let vertex_id = phase1_document_vertex_id(document_id);
    let vertex = graph.vertices.get(&vertex_id)?;
    let label = phase2_vertex_label(graph, &vertex_id).unwrap_or_else(|| document_id.to_owned());
    let mut parts = vec![format!("document: {label}")];
    if let Some(support) = document_support.get(document_id) {
        if !support.is_empty() {
            parts.push(format!("support: {}", support.join(" | ")));
        }
    }
    Some(SemanticCandidatePrototypeInput {
        node_id: vertex.id.clone(),
        node_kind: "document".to_owned(),
        document_id: Some(document_id.to_owned()),
        narrative_id: vertex
            .attributes
            .get("narrativeId")
            .and_then(Value::as_str)
            .map(str::to_owned),
        folder_id: vertex
            .attributes
            .get("folderId")
            .and_then(Value::as_str)
            .map(str::to_owned),
        text: parts.join("\n"),
        evidence_refs: phase2_unique_strings(vec![format!("graph_vertex:{}", vertex.id)]),
    })
}

fn phase2_leaf_prototype_input(
    leaf_context: &HashMap<String, Phase2LeafContext>,
    vertex_id: &str,
) -> Option<SemanticCandidatePrototypeInput> {
    let context = leaf_context.get(vertex_id)?;
    Some(SemanticCandidatePrototypeInput {
        node_id: vertex_id.to_owned(),
        node_kind: "leaf".to_owned(),
        document_id: Some(context.document_id.clone()),
        narrative_id: context.narrative_id.clone(),
        folder_id: context.folder_id.clone(),
        text: format!("leaf: {}", context.text.trim()),
        evidence_refs: vec![format!("graph_vertex:{vertex_id}")],
    })
}

fn phase2_nli_profile_for_vertex(
    graph: &Phase2GraphView,
    leaf_context: &HashMap<String, Phase2LeafContext>,
    document_scopes: &HashMap<String, ScopeKey>,
    document_support: &HashMap<String, Vec<String>>,
    messages: &HashMap<String, ThreadMessage>,
    vertex_id: &str,
    cache: &mut HashMap<String, SemanticCandidatePrototypeInput>,
) -> Option<SemanticCandidatePrototypeInput> {
    if let Some(existing) = cache.get(vertex_id) {
        return Some(existing.clone());
    }
    let profile = if let Some(document_id) = vertex_id.strip_prefix("doc::") {
        phase2_document_prototype_input(graph, document_support, document_id)
    } else if vertex_id.starts_with("leaf::") {
        phase2_leaf_prototype_input(leaf_context, vertex_id)
    } else {
        let vertex = graph.vertices.get(vertex_id)?;
        match vertex.kind.as_str() {
            "entity" => {
                phase2_entity_prototype_input(graph, leaf_context, document_scopes, vertex_id)
            }
            "event" => {
                phase2_event_prototype_input(graph, leaf_context, document_scopes, vertex_id)
            }
            "turn" => phase2_turn_prototype_input(vertex, messages, document_scopes),
            "task" => phase2_task_prototype_input(vertex, document_scopes),
            "state" => phase2_state_prototype_input(vertex, document_scopes),
            "document" => vertex.document_id.as_deref().and_then(|document_id| {
                phase2_document_prototype_input(graph, document_support, document_id)
            }),
            "leaf" => phase2_leaf_prototype_input(leaf_context, vertex_id),
            _ => None,
        }
    }?;
    cache.insert(vertex_id.to_owned(), profile.clone());
    Some(profile)
}

fn phase2_scope_for_document(
    document_scopes: &HashMap<String, ScopeKey>,
    document_id: Option<&str>,
) -> (Option<String>, Option<String>) {
    let Some(document_id) = document_id else {
        return (None, None);
    };
    let Some(scope) = document_scopes.get(document_id) else {
        return (None, None);
    };
    (scope.narrative_id.clone(), scope.folder_id.clone())
}

fn phase2_vertex_label(graph: &Phase2GraphView, vertex_id: &str) -> Option<String> {
    let vertex = graph.vertices.get(vertex_id)?;
    vertex
        .value
        .get("label")
        .and_then(Value::as_str)
        .or_else(|| vertex.value.get("lemma").and_then(Value::as_str))
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
}

fn phase2_json_string_array(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

fn phase2_json_vector(value: Option<&Value>) -> Option<Vec<f32>> {
    let values = value?.as_array()?;
    let vector = values
        .iter()
        .map(|value| value.as_f64().map(|value| value as f32))
        .collect::<Option<Vec<_>>>()?;
    (!vector.is_empty()).then_some(vector)
}

fn phase2_graph_evidence_refs(attributes: &Value) -> Vec<String> {
    attributes
        .get("graph")
        .and_then(Value::as_object)
        .and_then(|graph| graph.get("evidence_refs"))
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

fn phase2_candidate_graph_status(attributes: &Value) -> Option<&str> {
    attributes
        .get("graph")
        .and_then(Value::as_object)
        .and_then(|graph| graph.get("status"))
        .and_then(Value::as_str)
}

fn phase2_candidate_row_is_active(attributes: &Value) -> bool {
    !matches!(
        phase2_candidate_graph_status(attributes),
        Some("candidate_rejected")
    )
}

fn phase2_candidate_row_base_score(data: Option<&Value>, attributes: Option<&Value>) -> f64 {
    data.and_then(|value| value.get("base"))
        .and_then(|value| value.get("score"))
        .and_then(Value::as_f64)
        .or_else(|| {
            data.and_then(|value| value.get("score"))
                .and_then(Value::as_f64)
        })
        .or_else(|| {
            attributes
                .and_then(|value| value.get("score"))
                .and_then(Value::as_f64)
        })
        .unwrap_or(0.0)
}

fn phase2_json_path_f64(value: Option<&Value>, path: &[&str]) -> Option<f64> {
    let mut current = value?;
    for key in path {
        current = current.get(*key)?;
    }
    current.as_f64()
}

fn phase2_optional_score_millis(value: Option<f64>) -> u32 {
    value
        .map(|score| (score.clamp(0.0, 1.0) * 1000.0).round() as u32)
        .unwrap_or(0)
}

fn phase2_similarity_score(distance: f64) -> f64 {
    1.0 / (1.0 + distance.max(0.0))
}

fn phase2_merge_evidence_refs(left: &[String], right: &[String]) -> Vec<String> {
    phase2_unique_strings(left.iter().chain(right.iter()).cloned().collect::<Vec<_>>())
}

fn phase2_unique_strings(values: Vec<String>) -> Vec<String> {
    let mut unique = BTreeSet::new();
    for value in values {
        if !value.trim().is_empty() {
            unique.insert(value);
        }
    }
    unique.into_iter().collect()
}

fn phase2_tokenize_terms(text: &str) -> BTreeSet<String> {
    text.split(|ch: char| !ch.is_alphanumeric())
        .map(|part| part.trim().to_ascii_lowercase())
        .filter(|part| part.len() >= 3)
        .collect()
}

fn phase2_text_overlap_score(left: &str, right: &str) -> usize {
    let left_terms = phase2_tokenize_terms(left);
    if left_terms.is_empty() {
        return 0;
    }
    let right_terms = phase2_tokenize_terms(right);
    left_terms.intersection(&right_terms).count()
}

fn phase2_nli_hypothesis(edge_type: &str, target_text: &str) -> String {
    match edge_type {
        "candidate_corefers_with" => {
            format!("This refers to the same entity as:\n{target_text}")
        }
        "candidate_same_event_as" => {
            format!("This describes the same event as:\n{target_text}")
        }
        "about" => format!("This text is about:\n{target_text}"),
        "relevant_to" => format!("This text is relevant to:\n{target_text}"),
        _ => target_text.to_owned(),
    }
}

fn phase2_nli_statement_hypothesis(statement_text: &str) -> String {
    format!("The following statement is true:\n{statement_text}")
}

fn phase2_nli_group_id(record: &Phase2CandidateEdgeRecord) -> String {
    match record.edge_type.as_str() {
        "candidate_corefers_with" | "candidate_same_event_as" => {
            let (left, right) = if record.source_id <= record.target_id {
                (record.source_id.as_str(), record.target_id.as_str())
            } else {
                (record.target_id.as_str(), record.source_id.as_str())
            };
            format!("{}::{left}::{right}", record.edge_type)
        }
        _ => format!(
            "{}::{}::{}",
            record.edge_type, record.source_id, record.target_id
        ),
    }
}

fn phase2_nli_inputs_for_edge(
    record: &Phase2CandidateEdgeRecord,
    source_text: &str,
    target_text: &str,
) -> Vec<SemanticNliJudgmentInput> {
    let group_id = phase2_nli_group_id(record);
    let mut inputs = vec![SemanticNliJudgmentInput {
        judgment_id: format!(
            "{}::{}::{}::forward",
            record.edge_type, record.source_id, record.target_id
        ),
        group_id: group_id.clone(),
        source_id: record.source_id.clone(),
        target_id: record.target_id.clone(),
        edge_type: record.edge_type.clone(),
        direction: "forward".to_owned(),
        premise: source_text.to_owned(),
        hypothesis: phase2_nli_hypothesis(&record.edge_type, target_text),
    }];

    if matches!(
        record.edge_type.as_str(),
        "candidate_corefers_with" | "candidate_same_event_as"
    ) {
        inputs.push(SemanticNliJudgmentInput {
            judgment_id: format!(
                "{}::{}::{}::reverse",
                record.edge_type, record.source_id, record.target_id
            ),
            group_id,
            source_id: record.source_id.clone(),
            target_id: record.target_id.clone(),
            edge_type: record.edge_type.clone(),
            direction: "reverse".to_owned(),
            premise: target_text.to_owned(),
            hypothesis: phase2_nli_hypothesis(&record.edge_type, source_text),
        });
    }

    inputs
}

fn phase2_nli_inputs_for_evidence_edge(
    source_id: &str,
    source_text: &str,
    target_id: &str,
    target_text: &str,
) -> Vec<SemanticNliJudgmentInput> {
    let hypothesis = phase2_nli_statement_hypothesis(source_text);
    ["supported_by", "contradicted_by"]
        .into_iter()
        .map(|edge_type| SemanticNliJudgmentInput {
            judgment_id: format!("{edge_type}::{source_id}::{target_id}::forward"),
            group_id: format!("{edge_type}::{source_id}::{target_id}"),
            source_id: source_id.to_owned(),
            target_id: target_id.to_owned(),
            edge_type: edge_type.to_owned(),
            direction: "forward".to_owned(),
            premise: target_text.to_owned(),
            hypothesis: hypothesis.clone(),
        })
        .collect()
}

fn phase2_nli_threshold(edge_type: &str) -> f64 {
    match edge_type {
        "candidate_corefers_with" => PHASE2_NLI_COREF_THRESHOLD,
        "candidate_same_event_as" => PHASE2_NLI_EVENT_THRESHOLD,
        "about" => PHASE2_NLI_ABOUT_THRESHOLD,
        "relevant_to" => PHASE2_NLI_RELEVANT_TO_THRESHOLD,
        "supported_by" => PHASE2_NLI_SUPPORTED_BY_THRESHOLD,
        "contradicted_by" => PHASE2_NLI_CONTRADICTED_BY_THRESHOLD,
        _ => 0.6,
    }
}

fn phase2_apply_nli_decision(
    edge_type: &str,
    base_score: f64,
    judgments: &[SemanticNliJudgmentResultRow],
) -> Phase2NliDecision {
    if judgments.is_empty() {
        return Phase2NliDecision::default();
    }

    let symmetric = matches!(
        edge_type,
        "candidate_corefers_with" | "candidate_same_event_as"
    );
    let entailment = if symmetric {
        judgments
            .iter()
            .map(|judgment| judgment.entailment)
            .fold(1.0_f64, |acc, value| acc.min(value))
    } else {
        judgments[0].entailment
    };
    let contradiction = judgments
        .iter()
        .map(|judgment| judgment.contradiction)
        .fold(0.0_f64, |acc, value| acc.max(value));
    let neutral = if symmetric {
        judgments
            .iter()
            .map(|judgment| judgment.neutral)
            .sum::<f64>()
            / judgments.len() as f64
    } else {
        judgments[0].neutral
    };
    let threshold = phase2_nli_threshold(edge_type);
    let (accepted, nli_score, final_score) = if edge_type == "contradicted_by" {
        let nli_score = (contradiction - entailment).max(0.0);
        let accepted = contradiction >= threshold
            && contradiction >= neutral
            && entailment <= (1.0 - threshold);
        let final_score = if accepted {
            ((base_score * 0.2) + (nli_score * 0.8)).clamp(0.0, 1.0)
        } else {
            (base_score * 0.2).clamp(0.0, 1.0)
        };
        (accepted, nli_score, final_score)
    } else {
        let nli_score = (entailment - contradiction).max(0.0);
        let accepted =
            entailment >= threshold && entailment >= neutral && contradiction <= (1.0 - threshold);
        let final_score = if accepted {
            ((base_score * 0.4) + (nli_score * 0.6)).clamp(0.0, 1.0)
        } else {
            (base_score * 0.35).clamp(0.0, 1.0)
        };
        (accepted, nli_score, final_score)
    };

    Phase2NliDecision {
        accepted,
        threshold,
        entailment,
        neutral,
        contradiction,
        nli_score,
        final_score,
    }
}

fn phase2_nli_evidence_refs(judgments: &[SemanticNliJudgmentResultRow]) -> Vec<String> {
    phase2_unique_strings(
        judgments
            .iter()
            .map(|judgment| format!("nli_judgment:{}", judgment.judgment_id))
            .collect::<Vec<_>>(),
    )
}

fn phase2_graph_has_edge(
    graph: &Phase2GraphView,
    source_id: &str,
    target_id: &str,
    edge_type: &str,
) -> bool {
    graph
        .outgoing_matching(source_id, edge_type)
        .any(|edge| edge.target_id == target_id)
}

fn phase2_graph_has_symmetric_edge(
    graph: &Phase2GraphView,
    left_id: &str,
    right_id: &str,
    edge_type: &str,
) -> bool {
    phase2_graph_has_edge(graph, left_id, right_id, edge_type)
        || phase2_graph_has_edge(graph, right_id, left_id, edge_type)
}

fn phase2_candidate_edge_row(
    source_id: &str,
    target_id: &str,
    edge_type: &str,
    document_id: Option<&str>,
    narrative_id: Option<&str>,
    score: f64,
    threshold: f64,
    mut attributes: Map<String, Value>,
    evidence_refs: Vec<String>,
) -> Value {
    if let Some(document_id) = document_id {
        attributes
            .entry("documentId".to_owned())
            .or_insert_with(|| json!(document_id));
    }
    attributes.insert("score".to_owned(), json!(score));
    attributes.insert("threshold".to_owned(), json!(threshold));
    attributes.insert(
        "graph".to_owned(),
        json!({
            "layer": "candidate",
            "status": "candidate",
            "resolver": PHASE2_EMBEDDING_RESOLVER,
            "confidence": score,
            "evidence_refs": evidence_refs,
        }),
    );
    json!({
        "source_id": source_id,
        "target_id": target_id,
        "edge_type": edge_type,
        "document_id": document_id,
        "narrative_id": narrative_id,
        "valid_from_doc": document_id,
        "valid_from_boundary": null,
        "valid_to_doc": null,
        "valid_to_boundary": null,
        "assertion_kind": "candidate",
        "weight": ((score * 1000.0).round() as i64).max(1),
        "attributes": Value::Object(attributes),
        "data": {
            "base": {
                "score": score,
                "threshold": threshold,
                "resolver": PHASE2_EMBEDDING_RESOLVER,
            },
        },
    })
}

fn phase2_nli_candidate_edge_seed_row(
    graph: &Phase2GraphView,
    source_id: &str,
    target_id: &str,
    edge_type: &str,
) -> Option<Value> {
    let source_vertex = graph.vertices.get(source_id)?;
    let target_vertex = graph.vertices.get(target_id)?;
    let document_id = source_vertex
        .document_id
        .clone()
        .or_else(|| target_vertex.document_id.clone());
    let narrative_id = source_vertex
        .attributes
        .get("narrativeId")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .or_else(|| {
            target_vertex
                .attributes
                .get("narrativeId")
                .and_then(Value::as_str)
                .map(str::to_owned)
        });
    let evidence_refs = phase2_unique_strings(vec![
        format!("graph_vertex:{source_id}"),
        format!("graph_vertex:{target_id}"),
    ]);
    Some(json!({
        "source_id": source_id,
        "target_id": target_id,
        "edge_type": edge_type,
        "document_id": document_id,
        "narrative_id": narrative_id,
        "valid_from_doc": document_id,
        "valid_from_boundary": null,
        "valid_to_doc": null,
        "valid_to_boundary": null,
        "assertion_kind": "candidate",
        "weight": 0,
        "attributes": {
            "documentId": document_id,
            "sourceKind": source_vertex.kind,
            "targetKind": target_vertex.kind,
            "score": 0.0,
            "threshold": phase2_nli_threshold(edge_type),
            "graph": {
                "layer": "candidate",
                "status": "candidate",
                "resolver": PHASE2_NLI_RESOLVER,
                "confidence": 0.0,
                "evidence_refs": evidence_refs,
            }
        },
        "data": {
            "base": {
                "score": 0.0,
                "threshold": phase2_nli_threshold(edge_type),
                "resolver": PHASE2_NLI_RESOLVER,
            }
        }
    }))
}

fn phase2_push_candidate_edge(
    edge_keys: &mut BTreeSet<(String, String, String)>,
    edge_rows: &mut Vec<Value>,
    row: Value,
) {
    let Some(source_id) = row
        .get("source_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    let Some(target_id) = row
        .get("target_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    let Some(edge_type) = row
        .get("edge_type")
        .and_then(Value::as_str)
        .map(str::to_owned)
    else {
        return;
    };
    if edge_keys.insert((source_id, target_id, edge_type)) {
        edge_rows.push(row);
    }
}

#[allow(dead_code)]
fn phase1_turn_vertex_id(message_id: &str) -> String {
    format!("turn::{message_id}")
}

#[allow(dead_code)]
fn phase1_agent_vertex_id(session_id: &SessionId, role: &str) -> String {
    format!("agent::{}::{role}", session_id.0)
}

#[allow(dead_code)]
fn phase1_task_vertex_id(thread_id: &str) -> String {
    format!("task::{thread_id}::current")
}

#[allow(dead_code)]
fn phase1_state_vertex_id(event_id: &str) -> String {
    format!("state::{event_id}")
}

#[allow(dead_code)]
fn phase1_time_vertex_id(kind: &str, source_id: &str) -> String {
    format!("time::{kind}::{source_id}")
}

fn phase1_document_vertex_id(document_id: &str) -> String {
    format!("doc::{document_id}")
}

#[allow(dead_code)]
fn phase1_turn_label(message: &ThreadMessage) -> String {
    let snippet = phase1_snippet(&message.content, 72);
    if snippet.is_empty() {
        message.role.clone()
    } else {
        format!("{}: {snippet}", message.role)
    }
}

#[allow(dead_code)]
fn phase1_state_label(event: &ChatRunEvent) -> String {
    let mut label = event.label.trim().to_owned();
    if label.is_empty() {
        label = format!("{} {}", event.phase, event.kind).trim().to_owned();
    }
    if label.is_empty() {
        label = event.id.clone();
    }
    label
}

#[allow(dead_code)]
fn phase1_snippet(text: &str, limit: usize) -> String {
    let collapsed = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.len() <= limit {
        collapsed
    } else {
        let mut snippet = collapsed
            .chars()
            .take(limit.saturating_sub(1))
            .collect::<String>();
        snippet.push('…');
        snippet
    }
}

#[allow(dead_code)]
fn phase1_thread_narrative_id(thread: &Thread, session: &SessionRecord) -> Option<String> {
    if !thread.narrative_id.trim().is_empty() {
        return Some(thread.narrative_id.clone());
    }
    session
        .scope
        .narrative_id
        .as_ref()
        .filter(|value| !value.is_empty())
        .cloned()
}

#[allow(dead_code)]
fn phase1_narrative_id(
    thread: &Thread,
    message: &ThreadMessage,
    session: &SessionRecord,
) -> Option<String> {
    if !message.narrative_id.trim().is_empty() {
        return Some(message.narrative_id.clone());
    }
    phase1_thread_narrative_id(thread, session)
}

#[allow(dead_code)]
fn phase1_latest_message_at_or_before<'a>(
    messages: &'a [ThreadMessage],
    timestamp_ms: i64,
) -> Option<&'a ThreadMessage> {
    messages
        .iter()
        .rev()
        .find(|message| message.created_at <= timestamp_ms)
        .or_else(|| messages.last())
}

#[allow(dead_code)]
fn phase1_event_for_task<'a>(
    events: &'a [ChatRunEvent],
    timestamp_ms: i64,
) -> Option<&'a ChatRunEvent> {
    events
        .iter()
        .rev()
        .find(|event| event.created_at <= timestamp_ms)
        .or_else(|| events.last())
}

#[allow(dead_code)]
fn phase1_native_graph_row_matches_session(row: &Value, session_id: &SessionId) -> bool {
    row.get("attributes")
        .and_then(Value::as_object)
        .filter(|attributes| {
            attributes.get("sessionId").and_then(Value::as_str) == Some(session_id.0.as_str())
        })
        .and_then(|attributes| attributes.get("graph"))
        .and_then(Value::as_object)
        .and_then(|graph| graph.get("resolver"))
        .and_then(Value::as_str)
        == Some("phoenix-runtime/native")
}

#[allow(dead_code)]
fn om_record_from_value(row: Value) -> Result<OmRecord, StoreError> {
    let Some(object) = row.as_object() else {
        return Err(StoreError::Query(
            "OM record row should be an object.".to_owned(),
        ));
    };
    Ok(OmRecord {
        thread_id: object
            .get("thread_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        observations: object
            .get("observations")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        current_task: object
            .get("current_task")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        suggested_continuation: object
            .get("suggested_continuation")
            .and_then(Value::as_str)
            .map(str::to_owned),
        last_observed_at: object
            .get("last_observed_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        obs_token_count: object
            .get("obs_token_count")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        generation_num: object
            .get("generation_num")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        created_at: object
            .get("created_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        updated_at: object
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
    })
}

#[cfg(feature = "legacy-cozo-graph")]
const NOTE_KEY_COLUMNS: &[&str] = &["id", "version"];
const ALLOWED_WAL_RELATIONS: &[&str] = &[
    "entities",
    "edges",
    "folders",
    "scoped_documents",
    "scoped_entity_fields",
    "scoped_definitions",
    "discovery_candidates",
];
#[cfg(feature = "legacy-cozo-graph")]
const NOTE_HEADER_COLUMNS: &[&str] = &[
    "id",
    "version",
    "world_id",
    "title",
    "folder_id",
    "entity_kind",
    "entity_subtype",
    "is_entity",
    "is_pinned",
    "favorite",
    "owner_id",
    "narrative_id",
    "order",
    "created_at",
    "updated_at",
    "is_current",
];
#[cfg(feature = "legacy-cozo-graph")]
const NOTE_BODY_COLUMNS: &[&str] = &[
    "id",
    "version",
    "world_id",
    "title",
    "content",
    "markdown_content",
    "folder_id",
    "entity_kind",
    "entity_subtype",
    "is_entity",
    "is_pinned",
    "favorite",
    "owner_id",
    "narrative_id",
    "order",
    "created_at",
    "updated_at",
    "is_current",
];

#[cfg(feature = "legacy-cozo-graph")]
fn note_columns(include_body: bool) -> &'static [&'static str] {
    if include_body {
        NOTE_BODY_COLUMNS
    } else {
        NOTE_HEADER_COLUMNS
    }
}

fn payload_bool(value: Option<&Value>, default: bool) -> bool {
    value.and_then(Value::as_bool).unwrap_or(default)
}

fn payload_string_array(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(feature = "legacy-cozo-graph")]
fn note_priority(row: &CompactRowView<'_>) -> (u8, i64, i64) {
    (
        u8::from(row.get_bool("is_current").unwrap_or(false)),
        row.get_i64("version").unwrap_or_default(),
        row.get_i64("updated_at").unwrap_or_default(),
    )
}

#[cfg(feature = "legacy-cozo-graph")]
fn select_latest_note<'a>(
    rows: &'a [CompactRow],
    columns: &'a [&'a str],
) -> Option<CompactRowView<'a>> {
    let mut best: Option<CompactRowView<'a>> = None;
    for row in rows {
        let candidate = CompactRowView::new(columns, row);
        let is_better = best
            .as_ref()
            .map(|current| note_priority(&candidate) > note_priority(current))
            .unwrap_or(true);
        if is_better {
            best = Some(candidate);
        }
    }
    best
}

#[cfg(feature = "legacy-cozo-graph")]
fn note_value_from_row(row: CompactRowView<'_>, include_body: bool) -> Value {
    let mut object = serde_json::Map::new();
    object.insert(
        "id".to_owned(),
        Value::String(row.get_str("id").unwrap_or_default().to_owned()),
    );
    object.insert(
        "version".to_owned(),
        Value::from(row.get_i64("version").unwrap_or_default()),
    );
    object.insert(
        "world_id".to_owned(),
        Value::String(row.get_str("world_id").unwrap_or_default().to_owned()),
    );
    object.insert(
        "title".to_owned(),
        Value::String(row.get_str("title").unwrap_or_default().to_owned()),
    );
    if include_body {
        object.insert(
            "content".to_owned(),
            Value::String(row.get_str("content").unwrap_or_default().to_owned()),
        );
        object.insert(
            "markdown_content".to_owned(),
            Value::String(
                row.get_str("markdown_content")
                    .unwrap_or_default()
                    .to_owned(),
            ),
        );
    }
    object.insert(
        "folder_id".to_owned(),
        row.get_str("folder_id")
            .map(|value| Value::String(value.to_owned()))
            .unwrap_or(Value::Null),
    );
    object.insert(
        "entity_kind".to_owned(),
        row.get_str("entity_kind")
            .map(|value| Value::String(value.to_owned()))
            .unwrap_or(Value::Null),
    );
    object.insert(
        "entity_subtype".to_owned(),
        row.get_str("entity_subtype")
            .map(|value| Value::String(value.to_owned()))
            .unwrap_or(Value::Null),
    );
    object.insert(
        "is_entity".to_owned(),
        Value::Bool(row.get_bool("is_entity").unwrap_or(false)),
    );
    object.insert(
        "is_pinned".to_owned(),
        Value::Bool(row.get_bool("is_pinned").unwrap_or(false)),
    );
    object.insert(
        "favorite".to_owned(),
        Value::Bool(row.get_bool("favorite").unwrap_or(false)),
    );
    object.insert(
        "owner_id".to_owned(),
        row.get_str("owner_id")
            .map(|value| Value::String(value.to_owned()))
            .unwrap_or(Value::Null),
    );
    object.insert(
        "narrative_id".to_owned(),
        row.get_str("narrative_id")
            .map(|value| Value::String(value.to_owned()))
            .unwrap_or(Value::Null),
    );
    object.insert(
        "order".to_owned(),
        row.get_json("order").unwrap_or(Value::from(0)),
    );
    object.insert(
        "created_at".to_owned(),
        Value::from(row.get_i64("created_at").unwrap_or_default()),
    );
    object.insert(
        "updated_at".to_owned(),
        Value::from(row.get_i64("updated_at").unwrap_or_default()),
    );
    Value::Object(object)
}

#[cfg(feature = "legacy-cozo-graph")]
fn note_values_from_rows(
    rows: Vec<CompactRow>,
    columns: &[&str],
    folder_id: Option<&str>,
    include_body: bool,
) -> Vec<Value> {
    let mut best_by_id = HashMap::<String, CompactRow>::new();

    for row in rows {
        let candidate = CompactRowView::new(columns, &row);
        if let Some(expected_folder_id) = folder_id {
            let actual_folder_id = candidate.get_str("folder_id").unwrap_or_default();
            let folder_matches = if expected_folder_id.is_empty() {
                actual_folder_id.is_empty()
            } else {
                actual_folder_id == expected_folder_id
            };
            if !folder_matches {
                continue;
            }
        }

        let Some(id) = candidate.get_str("id").map(str::to_owned) else {
            continue;
        };
        match best_by_id.get(&id) {
            Some(existing) => {
                let existing_view = CompactRowView::new(columns, existing);
                if note_priority(&candidate) > note_priority(&existing_view) {
                    best_by_id.insert(id, row);
                }
            }
            None => {
                best_by_id.insert(id, row);
            }
        }
    }

    let mut values = best_by_id
        .values()
        .map(|row| note_value_from_row(CompactRowView::new(columns, row), include_body))
        .collect::<Vec<_>>();
    values.sort_by(|left, right| {
        let left_updated = left
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default();
        let right_updated = right
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default();
        right_updated.cmp(&left_updated).then_with(|| {
            left.get("title")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .cmp(
                    right
                        .get("title")
                        .and_then(Value::as_str)
                        .unwrap_or_default(),
                )
        })
    });
    values
}

fn entity_card_row(card: &EntityCard) -> Value {
    json!({
        "entity_id": card.entity_id.0,
        "card_id": card.card_id,
        "name": card.name,
        "color": card.color,
        "icon": card.icon,
        "display_order": card.display_order,
        "is_collapsed": card.is_collapsed,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    })
}

fn entity_card_from_row(row: Value) -> Result<EntityCard, StoreError> {
    Ok(EntityCard {
        entity_id: phoenix_types::EntityId(
            required_string_field(&row, "entity_cards", "entity_id")?.to_owned(),
        ),
        card_id: required_string_field(&row, "entity_cards", "card_id")?.to_owned(),
        name: row
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        color: row
            .get("color")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        icon: row
            .get("icon")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        display_order: row
            .get("display_order")
            .and_then(Value::as_i64)
            .unwrap_or_default() as i32,
        is_collapsed: row
            .get("is_collapsed")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        created_at: row
            .get("created_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        updated_at: row
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
    })
}

fn folder_schema_row(schema: &FolderSchema) -> Value {
    json!({
        "id": schema.id,
        "entity_kind": schema.entity_kind,
        "subtype": null_if_empty_value(&schema.subtype),
        "name": schema.name,
        "description": null_if_empty_value(&schema.description),
        "allowed_subfolders": parse_json_string_array_value(&schema.allowed_subfolders),
        "allowed_note_types": parse_json_string_array_value(&schema.allowed_note_types),
        "is_vault_root": schema.is_vault_root,
        "container_only": schema.container_only,
        "propagate_kind_to_children": schema.propagate_kind_to_children,
        "icon": null_if_empty_value(&schema.icon),
        "is_system": schema.is_system,
        "created_at": schema.created_at,
        "updated_at": schema.updated_at,
    })
}

fn folder_schema_from_row(row: Value) -> Result<FolderSchema, StoreError> {
    Ok(FolderSchema {
        id: required_string_field(&row, "folder_schemas", "id")?.to_owned(),
        entity_kind: row
            .get("entity_kind")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        subtype: row
            .get("subtype")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        name: row
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        description: row
            .get("description")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        allowed_subfolders: json_value_to_string_array(
            row.get("allowed_subfolders")
                .cloned()
                .unwrap_or(Value::Array(Vec::new())),
        ),
        allowed_note_types: json_value_to_string_array(
            row.get("allowed_note_types")
                .cloned()
                .unwrap_or(Value::Array(Vec::new())),
        ),
        is_vault_root: row
            .get("is_vault_root")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        container_only: row
            .get("container_only")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        propagate_kind_to_children: row
            .get("propagate_kind_to_children")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        icon: row
            .get("icon")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        is_system: row
            .get("is_system")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        created_at: row
            .get("created_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        updated_at: row
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
    })
}

fn network_instance_row(network: &NetworkInstance) -> Value {
    json!({
        "id": network.id,
        "name": network.name,
        "schema_id": null_if_empty_value(&network.schema_id),
        "network_kind": network.network_kind,
        "network_subtype": null_if_empty_value(&network.network_subtype),
        "root_folder_id": null_if_empty_value(&network.root_folder_id),
        "root_entity_id": null_if_empty_value(&network.root_entity_id),
        "namespace": network.namespace,
        "description": null_if_empty_value(&network.description),
        "tags": network.tags,
        "member_count": network.member_count as i64,
        "relationship_count": network.relationship_count as i64,
        "max_depth": network.max_depth as i64,
        "created_at": network.created_at,
        "updated_at": network.updated_at,
        "group_id": null_if_empty_value(&network.group_id),
        "scope_type": network.scope_type,
        "narrative_id": null_if_empty_value(&network.narrative_id),
    })
}

fn network_instance_from_row(row: Value) -> Result<NetworkInstance, StoreError> {
    Ok(NetworkInstance {
        id: required_string_field(&row, "network_instance", "id")?.to_owned(),
        name: row
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        schema_id: row
            .get("schema_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        network_kind: row
            .get("network_kind")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        network_subtype: row
            .get("network_subtype")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        root_folder_id: row
            .get("root_folder_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        root_entity_id: row
            .get("root_entity_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        namespace: row
            .get("namespace")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        description: row
            .get("description")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        tags: row
            .get("tags")
            .and_then(Value::as_array)
            .map(|values| {
                values
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::to_owned)
                    .collect()
            })
            .unwrap_or_default(),
        member_count: row
            .get("member_count")
            .and_then(Value::as_i64)
            .unwrap_or_default() as usize,
        relationship_count: row
            .get("relationship_count")
            .and_then(Value::as_i64)
            .unwrap_or_default() as usize,
        max_depth: row
            .get("max_depth")
            .and_then(Value::as_i64)
            .unwrap_or_default() as usize,
        created_at: row
            .get("created_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        updated_at: row
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        group_id: row
            .get("group_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        scope_type: row
            .get("scope_type")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        narrative_id: row
            .get("narrative_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
    })
}

fn network_membership_row(member: &phoenix_types::NetworkMembership) -> Value {
    json!({
        "network_id": member.network_id,
        "entity_id": member.entity_id.0,
        "x": member.x,
        "y": member.y,
        "fixed": member.fixed,
    })
}

fn network_membership_from_row(row: Value) -> Result<phoenix_types::NetworkMembership, StoreError> {
    Ok(phoenix_types::NetworkMembership {
        network_id: required_string_field(&row, "network_membership", "network_id")?.to_owned(),
        entity_id: phoenix_types::EntityId(
            required_string_field(&row, "network_membership", "entity_id")?.to_owned(),
        ),
        x: row.get("x").and_then(Value::as_f64).unwrap_or_default(),
        y: row.get("y").and_then(Value::as_f64).unwrap_or_default(),
        fixed: row.get("fixed").and_then(Value::as_bool).unwrap_or(false),
    })
}

fn network_relationship_row(relationship: &phoenix_types::NetworkRelationship) -> Value {
    json!({
        "network_id": relationship.network_id,
        "source_entity_id": relationship.source_entity_id.0,
        "target_entity_id": relationship.target_entity_id.0,
        "relationship_id": relationship.relationship_id,
    })
}

fn network_relationship_from_row(
    row: Value,
) -> Result<phoenix_types::NetworkRelationship, StoreError> {
    Ok(phoenix_types::NetworkRelationship {
        network_id: required_string_field(&row, "network_relationship", "network_id")?.to_owned(),
        source_entity_id: phoenix_types::EntityId(
            required_string_field(&row, "network_relationship", "source_entity_id")?.to_owned(),
        ),
        target_entity_id: phoenix_types::EntityId(
            required_string_field(&row, "network_relationship", "target_entity_id")?.to_owned(),
        ),
        relationship_id: required_string_field(&row, "network_relationship", "relationship_id")?
            .to_owned(),
    })
}

fn required_string_field<'a>(
    row: &'a Value,
    relation: &str,
    field: &str,
) -> Result<&'a str, StoreError> {
    row.get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| StoreError::MissingColumn {
            relation: relation.to_owned(),
            column: field.to_owned(),
        })
}

fn null_if_empty_value(value: &str) -> Value {
    if value.is_empty() {
        Value::Null
    } else {
        Value::String(value.to_owned())
    }
}

fn parse_json_string_array_value(value: &str) -> Value {
    serde_json::from_str(value).unwrap_or_else(|_| Value::Array(Vec::new()))
}

fn json_value_to_string_array(value: Value) -> String {
    match value {
        Value::Array(_) => value.to_string(),
        Value::Null => "[]".to_owned(),
        other => serde_json::to_string(&other).unwrap_or_else(|_| "[]".to_owned()),
    }
}

fn note_value_priority(row: &Value) -> (u8, i64, i64) {
    (
        u8::from(
            row.get("is_current")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        ),
        row.get("version")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        row.get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
    )
}

fn normalize_note_value(mut row: Value, include_body: bool) -> Value {
    if let Some(object) = row.as_object_mut() {
        object
            .entry("id")
            .or_insert_with(|| Value::String(String::new()));
        object.entry("version").or_insert_with(|| Value::from(0));
        object
            .entry("world_id")
            .or_insert_with(|| Value::String(String::new()));
        object
            .entry("title")
            .or_insert_with(|| Value::String(String::new()));
        if include_body {
            object
                .entry("content")
                .or_insert_with(|| Value::String(String::new()));
            object
                .entry("markdown_content")
                .or_insert_with(|| Value::String(String::new()));
        } else {
            object.remove("content");
            object.remove("markdown_content");
        }
        for key in [
            "folder_id",
            "entity_kind",
            "entity_subtype",
            "owner_id",
            "narrative_id",
        ] {
            object.entry(key.to_owned()).or_insert(Value::Null);
        }
        object.entry("order").or_insert_with(|| Value::from(0));
        object.entry("created_at").or_insert_with(|| Value::from(0));
        object.entry("updated_at").or_insert_with(|| Value::from(0));
        object
            .entry("is_entity")
            .or_insert_with(|| Value::Bool(false));
        object
            .entry("is_pinned")
            .or_insert_with(|| Value::Bool(false));
        object
            .entry("favorite")
            .or_insert_with(|| Value::Bool(false));
    }
    row
}

fn select_latest_note_value(rows: Vec<Value>, include_body: bool) -> Option<Value> {
    rows.into_iter()
        .max_by(|left, right| note_value_priority(left).cmp(&note_value_priority(right)))
        .map(|row| normalize_note_value(row, include_body))
}

fn note_values_from_value_rows(
    rows: Vec<Value>,
    folder_id: Option<&str>,
    include_body: bool,
) -> Vec<Value> {
    let mut best_by_id = HashMap::<String, Value>::new();
    for row in rows {
        if let Some(expected_folder_id) = folder_id {
            let actual_folder_id = row
                .get("folder_id")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let folder_matches = if expected_folder_id.is_empty() {
                actual_folder_id.is_empty()
            } else {
                actual_folder_id == expected_folder_id
            };
            if !folder_matches {
                continue;
            }
        }
        let Some(id) = row.get("id").and_then(Value::as_str).map(str::to_owned) else {
            continue;
        };
        let should_replace = best_by_id
            .get(&id)
            .map(|existing| note_value_priority(&row) > note_value_priority(existing))
            .unwrap_or(true);
        if should_replace {
            best_by_id.insert(id, row);
        }
    }

    let mut values = best_by_id
        .into_values()
        .map(|row| normalize_note_value(row, include_body))
        .collect::<Vec<_>>();
    values.sort_by(|left, right| {
        let left_updated = left
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default();
        let right_updated = right
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default();
        right_updated.cmp(&left_updated).then_with(|| {
            left.get("title")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .cmp(
                    right
                        .get("title")
                        .and_then(Value::as_str)
                        .unwrap_or_default(),
                )
        })
    });
    values
}

fn session_record_from_row(row: &Value) -> Result<SessionRecord, StoreError> {
    let object = row.as_object().ok_or(StoreError::InvalidRow)?;
    Ok(SessionRecord {
        session_id: SessionId(
            object
                .get("session_id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned(),
        ),
        label: object
            .get("label")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        scope: phoenix_types::ScopeKey {
            world_id: object
                .get("world_id")
                .and_then(Value::as_str)
                .map(str::to_owned),
            narrative_id: object
                .get("narrative_id")
                .and_then(Value::as_str)
                .map(str::to_owned),
            folder_id: object
                .get("folder_id")
                .and_then(Value::as_str)
                .map(str::to_owned),
            folder_path: object
                .get("folder_path")
                .and_then(Value::as_str)
                .map(str::to_owned),
        },
        status: object
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("active")
            .to_owned(),
        revision: object.get("revision").and_then(Value::as_u64).unwrap_or(0),
        created_at: object
            .get("created_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
        updated_at: object
            .get("updated_at")
            .and_then(Value::as_i64)
            .unwrap_or_default(),
    })
}

fn require_payload_str<'a>(payload: &'a Value, key: &str) -> Result<&'a str, StoreError> {
    payload
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| StoreError::Query(format!("missing store command field: {key}")))
}

fn require_payload_value<'a>(payload: &'a Value, key: &str) -> Result<&'a Value, StoreError> {
    payload
        .get(key)
        .ok_or_else(|| StoreError::Query(format!("missing store command field: {key}")))
}

fn payload_object(value: Option<&Value>) -> Option<&serde_json::Map<String, Value>> {
    value.and_then(Value::as_object)
}

fn ensure_allowed_content_relation(relation: &str) -> Result<(), StoreError> {
    if ALLOWED_WAL_RELATIONS.contains(&relation) && CONTENT_SNAPSHOT_RELATIONS.contains(&relation) {
        return Ok(());
    }
    Err(StoreError::Query(format!(
        "unsupported WAL relation: {relation}"
    )))
}

fn relation_touches_lex_index(relation: &str) -> bool {
    relation == "notes"
}

fn elapsed_millis(started: Instant) -> u64 {
    started.elapsed().as_millis().min(u128::from(u64::MAX)) as u64
}

fn row_matches_filter(row: &Value, filter: Option<&serde_json::Map<String, Value>>) -> bool {
    let Some(filter) = filter else {
        return true;
    };
    let Some(object) = row.as_object() else {
        return false;
    };
    filter
        .iter()
        .all(|(key, expected)| object.get(key) == Some(expected))
}

pub(crate) fn now_ms() -> i64 {
    #[cfg(target_arch = "wasm32")]
    {
        js_sys::Date::now() as i64
    }

    #[cfg(not(target_arch = "wasm32"))]
    {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock after epoch")
            .as_millis() as i64
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn overgraph_store_path(config: &RuntimeConfig, storage_path: Option<&Path>) -> PathBuf {
    match storage_path {
        Some(path) => path.join("phoenix-overgraph"),
        None if config.storage == StorageMode::NativeEphemeral => ephemeral_overgraph_store_path(),
        None => platform_data_dir()
            .unwrap_or_else(std::env::temp_dir)
            .join("Phoenix Desktop")
            .join("phoenix-overgraph"),
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn ephemeral_overgraph_store_path() -> PathBuf {
    static PATH: OnceLock<PathBuf> = OnceLock::new();
    PATH.get_or_init(|| {
        let path = std::env::temp_dir().join("Phoenix Desktop").join(format!(
            "phoenix-overgraph-ephemeral-{}-{}",
            std::process::id(),
            now_ms()
        ));
        let _ = fs::remove_dir_all(&path);
        path
    })
    .clone()
}

#[cfg(not(target_arch = "wasm32"))]
fn platform_data_dir() -> Option<PathBuf> {
    std::env::var_os("LOCALAPPDATA")
        .or_else(|| std::env::var_os("APPDATA"))
        .map(PathBuf::from)
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FixtureManifest {
    pub fixtures: Vec<GoldenFixture>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GoldenFixture {
    pub id: String,
    pub title: String,
    pub source_path: String,
    pub document_id: String,
    pub file_path: String,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExpectedFixtureBaseline {
    pub fixture_id: String,
    pub source_path: String,
    pub expected_scanner: Option<serde_json::Value>,
    pub expected_structure: Option<serde_json::Value>,
    pub expected_ingest: Option<serde_json::Value>,
    pub expected_query: Option<serde_json::Value>,
}

pub fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .canonicalize()
        .expect("workspace root")
}

pub fn fixtures_root() -> PathBuf {
    workspace_root().join("fixtures")
}

pub fn load_fixture_manifest() -> FixtureManifest {
    try_load_fixture_manifest().expect("fixture manifest")
}

pub fn try_load_fixture_manifest() -> Result<FixtureManifest, std::io::Error> {
    let path = fixtures_root().join("manifest.json");
    let content = fs::read_to_string(path)?;
    Ok(serde_json::from_str(&content).expect("fixture manifest json"))
}

pub fn load_expected_baseline(fixture_id: &str) -> ExpectedFixtureBaseline {
    try_load_expected_baseline(fixture_id).expect("expected baseline")
}

pub fn try_load_expected_baseline(
    fixture_id: &str,
) -> Result<ExpectedFixtureBaseline, std::io::Error> {
    let path = fixtures_root()
        .join("expected")
        .join(format!("{fixture_id}.json"));
    let content = fs::read_to_string(path)?;
    Ok(serde_json::from_str(&content).expect("expected baseline json"))
}

pub fn fixture_body(fixture: &GoldenFixture) -> String {
    try_fixture_body(fixture).expect("fixture body")
}

pub fn try_fixture_body(fixture: &GoldenFixture) -> Result<String, std::io::Error> {
    let path = fixtures_root().join(&fixture.file_path);
    fs::read_to_string(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(feature = "legacy-cozo-graph")]
    use phoenix_types::{
        ChatPlannerModelResponse, ChatPlannerStep, ChatRunSnapshot, ChatWorkspaceArtifact,
    };

    #[test]
    fn atlas_rich_scan_can_skip_semantic_sidecar() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");

        let result = runtime
            .atlas_rich_scan(AtlasRichScanRequest {
                documents: vec![AtlasRichScanDocument {
                    document_id: DocumentId("doc-atlas-skip".to_owned()),
                    note_id: Some(NoteId("note-atlas-skip".to_owned())),
                    title: "Atlas skip".to_owned(),
                    text: "Aella found the harbor gate before dawn.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                options: phoenix_types::AtlasRichScanOptions {
                    include_semantic_atlas: false,
                    ..phoenix_types::AtlasRichScanOptions::default()
                },
                ..AtlasRichScanRequest::default()
            })
            .expect("atlas scan");

        assert!(!result.applied_options.include_semantic_atlas);
        assert_eq!(result.embedding_counts.leaf, 0);
        assert_eq!(result.embedding_counts.entity, 0);
        assert_eq!(result.relation_candidate_count, 0);
        assert!(result.graph_delta_counts.get("nodes").copied().unwrap_or(0) > 0);
        assert!(result
            .stage_summaries
            .iter()
            .any(|summary| summary.stage == "dynamicSurface"));
        assert!(result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "PX_ATLAS_DYNAMIC_PIPELINE"));
    }

    #[test]
    fn dynamic_candidate_signal_rejects_repeated_capitalization_only() {
        let repeated = dynamic_test_mention(
            "Absolutely",
            phoenix_dynamic_ner::VoteReason::RepeatedSurface,
        );
        let dialogue =
            dynamic_test_mention("Aella", phoenix_dynamic_ner::VoteReason::DialogueSpeaker);

        assert!(!dynamic_has_candidate_signal(&repeated, ""));
        assert!(!dynamic_mention_is_graphworthy(&repeated, ""));
        assert!(dynamic_has_candidate_signal(&dialogue, ""));
        assert!(dynamic_mention_is_graphworthy(&dialogue, ""));
    }

    #[test]
    fn dynamic_candidate_signal_keeps_location_shaped_cap_spans() {
        let text = "Baton Rouge came first. Rook said the answer aloud.";
        let location =
            dynamic_test_mention("Baton Rouge", phoenix_dynamic_ner::VoteReason::CapSpan);
        let person = dynamic_test_mention("Rook", phoenix_dynamic_ner::VoteReason::CapSpan);

        assert!(dynamic_has_candidate_signal(&location, text));
        assert!(dynamic_mention_is_graphworthy(&location, text));
        assert!(!dynamic_has_candidate_signal(&person, text));

        let votes = dynamic_candidate_kind_votes(&location, None, text);
        let kind = dynamic_candidate_kind(&location, None, &votes);

        assert_eq!(kind, "LOCATION");
        assert!(votes.iter().any(|vote| {
            vote.kind == "LOCATION"
                && vote.source == "native_location_shape"
                && vote.reason == "location_surface_or_context"
        }));
    }

    #[test]
    fn dynamic_candidate_kind_flattens_model_groups_to_network() {
        let mut mention =
            dynamic_test_mention("Allied Table", phoenix_dynamic_ner::VoteReason::ModelLabel);
        mention
            .label_distribution
            .push((phoenix_dynamic_ner::EntityLabel::new("Organization"), 0.82));
        mention
            .label_distribution
            .push((phoenix_dynamic_ner::EntityLabel::new("Location"), 0.18));
        mention.source_votes.push(phoenix_dynamic_ner::MentionVote {
            source: phoenix_dynamic_ner::MentionSourceKind::ModelDiscovery,
            label: Some(phoenix_dynamic_ner::EntityLabel::new("Organization")),
            entity_ref: None,
            confidence: 0.82,
            reason: phoenix_dynamic_ner::VoteReason::ModelLabel,
        });

        let votes = dynamic_candidate_kind_votes(&mention, None, "");
        let kind = dynamic_candidate_kind(&mention, None, &votes);

        assert_eq!(kind, "NETWORK");
        assert_eq!(dynamic_candidate_decision_status(&mention), "accepted");
        assert!(votes.iter().any(|vote| vote.kind == "NETWORK"));
        assert!(votes.iter().any(|vote| vote.kind == "LOCATION"));
    }

    #[test]
    fn dynamic_network_surface_candidates_cover_story_groups() {
        let document = smoke_inline_doc(
            "network-control",
            "Joint Chiefs, Nemo, Atlas, Allied Table. Operators are signed to that table. Local militia hero. Rook is a military officer. Operator Office attached. Bringing in Phantom command or Warden force.",
        );
        let mut candidates = BTreeMap::new();

        dynamic_push_network_surface_candidates(&document, &mut candidates);

        for label in [
            "Joint Chiefs",
            "Atlas",
            "Allied Table",
            "Operators",
            "militia",
            "military",
            "Operator Office",
            "Phantom command",
            "Warden force",
        ] {
            assert!(
                candidates
                    .values()
                    .any(|candidate| candidate.label == label && candidate.kind == "NETWORK"),
                "missing network candidate for {label}"
            );
        }
    }

    #[test]
    fn dynamic_candidate_kind_votes_cover_model_concept_npc_and_creature_labels() {
        let text = "The marked spans came from a model pass.";
        let mut concept =
            dynamic_test_mention("Boundary Veir", phoenix_dynamic_ner::VoteReason::ModelLabel);
        concept
            .label_distribution
            .push((phoenix_dynamic_ner::EntityLabel::new("Concept"), 0.74));
        concept.source_votes.push(phoenix_dynamic_ner::MentionVote {
            source: phoenix_dynamic_ner::MentionSourceKind::ModelDiscovery,
            label: Some(phoenix_dynamic_ner::EntityLabel::new("Concept")),
            entity_ref: None,
            confidence: 0.74,
            reason: phoenix_dynamic_ner::VoteReason::ModelLabel,
        });
        let mut npc =
            dynamic_test_mention("gate guard", phoenix_dynamic_ner::VoteReason::ModelLabel);
        npc.label_distribution
            .push((phoenix_dynamic_ner::EntityLabel::new("NPC"), 0.70));
        let mut creature =
            dynamic_test_mention("The Titan", phoenix_dynamic_ner::VoteReason::ModelLabel);
        creature
            .label_distribution
            .push((phoenix_dynamic_ner::EntityLabel::new("Species"), 0.72));

        let concept_votes = dynamic_candidate_kind_votes(&concept, None, text);
        let npc_votes = dynamic_candidate_kind_votes(&npc, None, text);
        let creature_votes = dynamic_candidate_kind_votes(&creature, None, text);

        assert_eq!(
            dynamic_candidate_kind(&concept, None, &concept_votes),
            "CONCEPT"
        );
        assert_eq!(dynamic_candidate_kind(&npc, None, &npc_votes), "NPC");
        assert_eq!(
            dynamic_candidate_kind(&creature, None, &creature_votes),
            "CREATURE"
        );
        assert_eq!(dynamic_label_to_atlas_kind("Monster"), Some("CREATURE"));
    }

    #[test]
    fn dynamic_candidate_kind_votes_do_not_infer_story_species_by_name() {
        let text = "The Titan crossed the lane.";
        let mention = dynamic_test_mention("The Titan", phoenix_dynamic_ner::VoteReason::CapSpan);
        let votes = dynamic_candidate_kind_votes(&mention, None, text);

        assert!(!votes.iter().any(|vote| vote.kind == "NPC"));
        assert!(!votes.iter().any(|vote| vote.kind == "CREATURE"));
    }

    #[test]
    fn dynamic_candidate_context_snippet_preserves_sentence_evidence() {
        let text = "Kai waited. Baton Rouge came first. Red Mesa stayed quiet.";
        let start = text.find("Baton Rouge").expect("surface") as u32;
        let snippet = dynamic_mention_context_snippet(
            text,
            TextRange {
                start,
                end: start + "Baton Rouge".len() as u32,
            },
            120,
        );

        assert_eq!(snippet, "Baton Rouge came first.");
    }

    #[test]
    fn dynamic_candidate_dedupe_prefers_accepted_higher_confidence_row() {
        let review = AtlasRichScanCandidateSummary {
            label: "Nemo".to_owned(),
            decision_status: "review".to_owned(),
            confidence: 0.42,
            ..AtlasRichScanCandidateSummary::default()
        };
        let accepted = AtlasRichScanCandidateSummary {
            label: "Nemo".to_owned(),
            decision_status: "accepted".to_owned(),
            confidence: 0.38,
            ..AtlasRichScanCandidateSummary::default()
        };

        assert!(dynamic_candidate_is_better(&accepted, &review));
        assert!(!dynamic_candidate_is_better(&review, &accepted));
    }

    #[test]
    fn dynamic_ner_smoke_uses_shortrun_and_mother2_without_location_collapse() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");

        let result = runtime
            .atlas_rich_scan(AtlasRichScanRequest {
                documents: vec![
                    smoke_doc("shortrun", "shortrun.md"),
                    smoke_doc("mother2", "mother2.md"),
                ],
                options: phoenix_types::AtlasRichScanOptions {
                    include_semantic_atlas: false,
                    return_candidate_suggestions: true,
                    ..phoenix_types::AtlasRichScanOptions::default()
                },
                ..AtlasRichScanRequest::default()
            })
            .expect("atlas smoke scan");

        assert_eq!(result.processed_documents, 2);
        assert!(result.candidate_suggestions.iter().any(|candidate| {
            candidate
                .source_document_id
                .as_ref()
                .is_some_and(|id| id.0 == "shortrun")
        }));
        assert!(result.candidate_suggestions.iter().any(|candidate| {
            candidate
                .source_document_id
                .as_ref()
                .is_some_and(|id| id.0 == "mother2")
        }));
        assert!(result
            .candidate_suggestions
            .iter()
            .all(|candidate| !candidate.decision_status.is_empty()));
        assert!(result
            .candidate_suggestions
            .iter()
            .any(|candidate| candidate.kind != "LOCATION"));
        assert!(result
            .candidate_suggestions
            .iter()
            .any(|candidate| candidate.label == "Red Mesa" && candidate.kind == "LOCATION"));
        assert!(result
            .candidate_suggestions
            .iter()
            .any(|candidate| candidate.label == "Allied Table" && candidate.kind == "NETWORK"));
        assert!(result
            .candidate_suggestions
            .iter()
            .all(|candidate| { candidate.label != "Rook" || candidate.kind != "LOCATION" }));
        let dynamic_surface = result
            .stage_summaries
            .iter()
            .find(|summary| summary.stage == "dynamicSurface")
            .expect("dynamic surface summary");
        assert!(dynamic_surface.counts.get("frames").copied().unwrap_or(0) > 0);
        assert!(
            dynamic_surface
                .counts
                .get("frameArguments")
                .copied()
                .unwrap_or(0)
                > 0
        );
        assert!(!runtime
            .fetch_relation_rows("semantic_frames")
            .expect("semantic frames")
            .is_empty());
    }

    #[test]
    fn atlas_rich_scan_returns_alias_resolution_proposals() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        for row in [
            json!({
                "id": "ryan",
                "label": "Ryan",
                "entity_kind": "character",
                "aliases": ["Quicksave"],
            }),
            json!({
                "id": "kharon-vel",
                "label": "Kharon Vel",
                "entity_kind": "location",
                "aliases": [],
            }),
        ] {
            runtime
                .put_relation_row("entities", row)
                .expect("entity row");
        }

        let result = runtime
            .atlas_rich_scan(AtlasRichScanRequest {
                documents: vec![smoke_inline_doc(
                    "alias-doc",
                    "The courier nodded. \"Ryan Ramano,\" Ryan said. Kharon Vel waited. Quicksave waved from the gate.",
                )],
                options: phoenix_types::AtlasRichScanOptions {
                    include_semantic_atlas: false,
                    return_candidate_suggestions: true,
                    ..phoenix_types::AtlasRichScanOptions::default()
                },
                ..AtlasRichScanRequest::default()
            })
            .expect("alias scan");

        assert!(result.alias_proposals.iter().any(|proposal| {
            proposal.surface == "Ryan Ramano"
                && proposal.relation == AtlasAliasRelation::FullDesignation
                && matches!(
                    &proposal.target,
                    AtlasAliasProposalTarget::KnownEntity { entity_id, .. }
                        if entity_id.0 == "ryan"
                )
        }));
        assert!(result.alias_proposals.iter().any(|proposal| {
            proposal.surface == "Quicksave"
                && proposal.relation == AtlasAliasRelation::ExactKnownAlias
                && matches!(
                    &proposal.target,
                    AtlasAliasProposalTarget::KnownEntity { entity_id, .. }
                        if entity_id.0 == "ryan"
                )
        }));
        assert!(result.alias_proposals.iter().any(|proposal| {
            proposal.surface == "Kharon Vel"
                && matches!(
                    &proposal.target,
                    AtlasAliasProposalTarget::KnownEntity {
                        entity_id,
                        kind: Some(EntityKind::Location),
                        ..
                    } if entity_id.0 == "kharon-vel"
                )
        }));
        assert!(result.identity_resolution.receipt_count > 0);
        assert!(result.identity_resolution.receipts.iter().any(|receipt| {
            receipt.surface == "Ryan Ramano"
                && receipt.action == phoenix_types::AtlasIdentityReceiptAction::FullDesignation
                && matches!(
                    &receipt.target,
                    phoenix_types::AtlasIdentityTargetSummary::KnownEntity { entity_id, .. }
                        if entity_id.0 == "ryan"
                )
        }));
        assert!(result.identity_resolution.receipts.iter().any(|receipt| {
            receipt.surface == "Quicksave"
                && receipt.action == phoenix_types::AtlasIdentityReceiptAction::AliasOfKnown
                && matches!(
                    &receipt.target,
                    phoenix_types::AtlasIdentityTargetSummary::KnownEntity { entity_id, .. }
                        if entity_id.0 == "ryan"
                )
        }));
        assert!(result.evidence_ledger.receipt_count > result.identity_resolution.receipt_count);
        assert!(
            result
                .evidence_ledger
                .counts_by_kind
                .get("aliasProposal")
                .copied()
                .unwrap_or_default()
                > 0
        );
        assert!(
            result
                .evidence_ledger
                .counts_by_kind
                .get("identityReceipt")
                .copied()
                .unwrap_or_default()
                > 0
        );
        assert_eq!(
            result.dataset_factory.example_count,
            result.evidence_ledger.receipt_count
        );
        let evidence_rows = runtime
            .fetch_relation_rows("evidence_ledger")
            .expect("evidence rows");
        assert!(evidence_rows.iter().any(|row| {
            row.get("artifact_kind").and_then(Value::as_str) == Some("identityReceipt")
                && row.get("decision_status").and_then(Value::as_str) == Some("accepted")
        }));
        let dataset_rows = runtime
            .fetch_relation_rows("dataset_examples")
            .expect("dataset examples");
        assert!(dataset_rows.len() >= result.evidence_ledger.receipt_count);
        assert!(dataset_rows.iter().any(|row| {
            row.get("example_kind").and_then(Value::as_str) == Some("aliasDecision")
        }));
    }

    #[test]
    fn atlas_rich_scan_persists_umr_lite_frame_rows() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        for row in [
            json!({
                "id": "ryan",
                "label": "Ryan",
                "entity_kind": "character",
                "aliases": ["Ryan Ramano", "Quicksave"],
            }),
            json!({
                "id": "rift",
                "label": "Rift",
                "entity_kind": "character",
                "aliases": ["Riftmach Gearlock"],
            }),
            json!({
                "id": "kharon-vel",
                "label": "Kharon Vel",
                "entity_kind": "location",
                "aliases": [],
            }),
        ] {
            runtime
                .put_relation_row("entities", row)
                .expect("entity row");
        }

        let result = runtime
            .atlas_rich_scan(AtlasRichScanRequest {
                scan_id: Some("frame-smoke".to_owned()),
                documents: vec![smoke_inline_doc(
                    "frame-doc",
                    "Ryan attacked Rift with Riftmach Gearlock in Kharon Vel before dawn.",
                )],
                options: phoenix_types::AtlasRichScanOptions {
                    include_semantic_atlas: false,
                    return_candidate_suggestions: true,
                    ..phoenix_types::AtlasRichScanOptions::default()
                },
                ..AtlasRichScanRequest::default()
            })
            .expect("frame scan");

        let dynamic_surface = result
            .stage_summaries
            .iter()
            .find(|summary| summary.stage == "dynamicSurface")
            .expect("dynamic surface summary");
        assert!(dynamic_surface.counts.get("frames").copied().unwrap_or(0) > 0);
        assert!(
            dynamic_surface
                .counts
                .get("frameArguments")
                .copied()
                .unwrap_or(0)
                > 0
        );
        assert!(
            dynamic_surface
                .counts
                .get("frameFacts")
                .copied()
                .unwrap_or(0)
                > 0
        );

        let frame_rows = runtime
            .fetch_relation_rows("semantic_frames")
            .expect("semantic frames");
        let argument_rows = runtime
            .fetch_relation_rows("semantic_frame_arguments")
            .expect("semantic frame arguments");
        let fact_rows = runtime
            .fetch_relation_rows("semantic_frame_facts")
            .expect("semantic frame facts");

        assert!(frame_rows.iter().any(|row| {
            row.get("scan_id").and_then(Value::as_str) == Some("frame-smoke")
                && row
                    .get("lemma")
                    .and_then(Value::as_str)
                    .is_some_and(|lemma| !lemma.is_empty())
        }));
        assert!(argument_rows.iter().any(|row| {
            row.get("role").and_then(Value::as_str) == Some("actor")
                && row
                    .get("entity_ref")
                    .and_then(|value| value.get("known"))
                    .and_then(Value::as_str)
                    == Some("ryan")
        }));
        assert!(argument_rows.iter().any(|row| {
            row.get("role").and_then(Value::as_str) == Some("target")
                && row
                    .get("entity_ref")
                    .and_then(|value| value.get("known"))
                    .and_then(Value::as_str)
                    == Some("rift")
        }));
        assert!(argument_rows.iter().any(|row| {
            row.get("role").and_then(Value::as_str) == Some("instrument")
                && row
                    .get("surface")
                    .and_then(Value::as_str)
                    .is_some_and(|surface| surface.contains("Riftmach Gearlock"))
        }));
        assert!(fact_rows.iter().any(|row| {
            row.get("fact_kind").and_then(Value::as_str) == Some("directRelation")
                && row.get("subject").and_then(Value::as_str) == Some("entity:ryan")
                && row.get("object").and_then(Value::as_str) == Some("entity:rift")
        }));

        let evidence_rows = runtime
            .fetch_relation_rows("evidence_ledger")
            .expect("evidence rows");
        assert!(evidence_rows
            .iter()
            .any(|row| { row.get("artifact_kind").and_then(Value::as_str) == Some("frameFact") }));
        let dataset_rows = runtime
            .fetch_relation_rows("dataset_examples")
            .expect("dataset examples");
        assert!(dataset_rows.iter().any(|row| {
            row.get("example_kind").and_then(Value::as_str) == Some("frameExtraction")
        }));

        let graph_edges = runtime
            .fetch_relation_rows("graph_edges")
            .expect("graph edges");
        assert!(graph_edges.iter().any(|row| {
            row.get("edge_type").and_then(Value::as_str) == Some("frameRole:actor")
        }));
    }

    fn dynamic_test_mention(
        surface: &str,
        reason: phoenix_dynamic_ner::VoteReason,
    ) -> phoenix_dynamic_ner::MentionPacket {
        let mut packet = phoenix_dynamic_ner::MentionPacket {
            mention_id: phoenix_dynamic_ner::LocalMentionId(1),
            document_id: "doc".into(),
            chunk_id: None,
            sentence_index: 0,
            range: TextRange {
                start: 0,
                end: surface.len() as u32,
            },
            surface: surface.into(),
            normalized: surface.to_ascii_lowercase().into(),
            mention_kind: phoenix_dynamic_ner::MentionKind::Named,
            label_distribution: Default::default(),
            entity_ref: None,
            source_votes: Default::default(),
            context: phoenix_dynamic_ner::MentionContext::default(),
            syntax: None,
            semantics: phoenix_dynamic_ner::MentionSemantics::default(),
            confidence: 0.8,
            status: phoenix_dynamic_ner::MentionStatus::AcceptedNew,
        };
        packet.source_votes.push(phoenix_dynamic_ner::MentionVote {
            source: phoenix_dynamic_ner::MentionSourceKind::NativeDiscovery,
            label: None,
            entity_ref: None,
            confidence: 0.8,
            reason,
        });
        packet
    }

    fn smoke_inline_doc(id: &str, text: &str) -> AtlasRichScanDocument {
        AtlasRichScanDocument {
            document_id: DocumentId(id.to_owned()),
            note_id: Some(NoteId(format!("note-{id}"))),
            title: format!("{id}.md"),
            text: text.to_owned(),
            scope: ScopeKey::default(),
        }
    }

    fn smoke_doc(id: &str, file_name: &str) -> AtlasRichScanDocument {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("..")
            .join("..")
            .join("docs")
            .join(file_name);
        let mut text = fs::read_to_string(&path).expect("smoke document");
        text = text.chars().take(24_000).collect::<String>();
        text.push_str("\n\nNER arbitration control: Rook said the Allied Table approved Red Mesa.");
        AtlasRichScanDocument {
            document_id: DocumentId(id.to_owned()),
            note_id: Some(NoteId(format!("note-{id}"))),
            title: file_name.to_owned(),
            text,
            scope: ScopeKey::default(),
        }
    }
    use phoenix_types::{
        AtlasAliasProposalTarget, AtlasAliasRelation, ChatRunStatus, ChatRuntimeConfig,
        CreateSessionRequest, DocumentId, EntityId, EntityKind, GenderHint, GraphDeltaRequest,
        MentionEntityRef, NoteId, QueryResultHeader, QueryTarget, RunOptions, ScopeKey,
        SessionStateResultHeader, SessionStatsResultHeader, TextRange,
    };
    use serde_json::{json, Value};

    fn native_test_runtime() -> PhoenixRuntime {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "phoenix-runtime-test-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).expect("test runtime root");
        PhoenixRuntime::open(RuntimeConfig::default(), Some(root)).expect("runtime")
    }

    #[test]
    fn fixture_manifest_loads() {
        let Ok(manifest) = try_load_fixture_manifest() else {
            eprintln!(
                "skipping optional fixture manifest test; {} is not present",
                fixtures_root().join("manifest.json").display()
            );
            return;
        };
        assert!(
            !manifest.fixtures.is_empty(),
            "fixtures should not be empty"
        );
    }

    #[test]
    fn fixture_bodies_exist_and_are_non_empty() {
        let Ok(manifest) = try_load_fixture_manifest() else {
            eprintln!(
                "skipping optional fixture body test; {} is not present",
                fixtures_root().join("manifest.json").display()
            );
            return;
        };

        for fixture in &manifest.fixtures {
            let body = try_fixture_body(fixture).expect("fixture body");
            assert!(
                !body.trim().is_empty(),
                "fixture {} should have non-empty body",
                fixture.id
            );
        }
    }

    #[test]
    fn expected_baselines_match_manifest() {
        let Ok(manifest) = try_load_fixture_manifest() else {
            eprintln!(
                "skipping optional fixture baseline test; {} is not present",
                fixtures_root().join("manifest.json").display()
            );
            return;
        };

        for fixture in &manifest.fixtures {
            let baseline = try_load_expected_baseline(&fixture.id).expect("expected baseline");
            assert_eq!(baseline.fixture_id, fixture.id);
            assert_eq!(baseline.source_path, fixture.source_path);
        }
    }

    #[test]
    fn runtime_init_reports_schema() {
        let runtime = native_test_runtime();
        let init = runtime.init().expect("init");
        assert!(init.ready);
        assert_eq!(init.schema_version, NATIVE_RUNTIME_SCHEMA_VERSION);
    }

    #[test]
    fn runtime_capabilities_report_required_store_contract() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");

        let result = runtime
            .store_command(StoreCommandRequest {
                command: "runtime:capabilities".to_owned(),
                payload: json!({}),
            })
            .expect("runtime capabilities");

        let payload = result.payload.expect("payload");
        let object = payload.as_object().expect("object");
        let store_api_version = object
            .get("storeApiVersion")
            .and_then(Value::as_u64)
            .expect("storeApiVersion");
        let capabilities = object
            .get("capabilities")
            .and_then(Value::as_array)
            .expect("capabilities");

        assert_eq!(store_api_version, STORE_API_VERSION as u64);
        for capability in RUNTIME_CAPABILITIES {
            assert!(
                capabilities
                    .iter()
                    .any(|candidate| candidate.as_str() == Some(*capability)),
                "missing capability {}",
                capability
            );
        }
    }

    #[test]
    fn document_graph_commit_is_idempotent_and_undo_preserves_entities() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        let commit_id = "document-graph-commit:test-diff";
        let payload = json!({
            "schemaVersion": "phoenix-document-graph-commit/v1",
            "commitId": commit_id,
            "scopeId": "note:test",
            "topologyDiffId": "test-diff",
            "sourceObjectId": "fact-candidate:test",
            "receiptId": "receipt:test",
            "builtAt": 10,
            "vertices": [
                {
                    "id": "entity:amara",
                    "kind": "entity",
                    "label": "Amara",
                    "removeOnUndo": false,
                    "attributes": { "registeredEntityReference": true }
                },
                {
                    "id": "document-fact:test",
                    "kind": "document_fact",
                    "label": "relation_bundle",
                    "removeOnUndo": true,
                    "attributes": { "confidence": 0.94 }
                },
                {
                    "id": "document-evidence:test",
                    "kind": "evidence_span",
                    "label": "Amara reached Halcyon.",
                    "removeOnUndo": true,
                    "attributes": { "noteId": "test" }
                }
            ],
            "edges": [
                {
                    "source": "document-fact:test",
                    "target": "entity:amara",
                    "edgeType": "document_fact_role",
                    "weight": 940,
                    "attributes": { "roles": ["subject"] }
                },
                {
                    "source": "document-fact:test",
                    "target": "document-evidence:test",
                    "edgeType": "supported_by_evidence_span",
                    "weight": 940,
                    "attributes": {}
                }
            ]
        });

        let first = runtime
            .store_command(StoreCommandRequest {
                command: "documentGraph:commit".to_owned(),
                payload: payload.clone(),
            })
            .expect("commit");
        assert!(first.success);
        assert_eq!(
            first.payload.as_ref().and_then(|value| value.get("idempotent")),
            Some(&Value::Bool(false))
        );
        let second = runtime
            .store_command(StoreCommandRequest {
                command: "documentGraph:commit".to_owned(),
                payload,
            })
            .expect("idempotent commit");
        assert_eq!(
            second.payload.as_ref().and_then(|value| value.get("idempotent")),
            Some(&Value::Bool(true))
        );

        let undo = runtime
            .store_command(StoreCommandRequest {
                command: "documentGraph:undo".to_owned(),
                payload: json!({
                    "schemaVersion": "phoenix-document-graph-undo/v1",
                    "commitId": commit_id,
                    "undoneAt": 11
                }),
            })
            .expect("undo");
        assert!(undo.success);
        let vertices = runtime
            .fetch_relation_rows("graph_vertices")
            .expect("vertices");
        assert!(vertices.iter().any(|row| row.get("id") == Some(&json!("entity:amara"))));
        assert!(!vertices
            .iter()
            .any(|row| row.get("id") == Some(&json!("document-fact:test"))));
        assert!(!vertices
            .iter()
            .any(|row| row.get("id") == Some(&json!("document-evidence:test"))));
        assert!(runtime
            .fetch_relation_rows("graph_edges")
            .expect("edges")
            .is_empty());
    }

    #[test]
    fn native_store_command_accepts_chat_namespace() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");

        let init = runtime
            .store_command(StoreCommandRequest {
                command: "chat:init".to_owned(),
                payload: json!({ "config": ChatRuntimeConfig::default() }),
            })
            .expect("chat init");

        assert!(init.success);

        let threads = runtime
            .store_command(StoreCommandRequest {
                command: "chat:listThreads".to_owned(),
                payload: json!({}),
            })
            .expect("list threads");

        assert!(threads.success);
        assert_eq!(threads.payload, Some(json!([])));
    }

    #[test]
    fn native_runtime_imports_overgraph_row_snapshot_bytes() {
        let snapshot = serde_json::to_vec(&SnapshotEnvelope {
            schema_version: "overgraph-row-v1".to_owned(),
            relation_count: 1,
            created_at: now_ms(),
            relations: BTreeMap::from([(
                "notes".to_owned(),
                vec![json!({
                    "id": "snapshot-note",
                    "version": 1,
                    "world_id": null,
                    "narrative_id": null,
                    "entity_kind": null,
                    "title": "Snapshot",
                    "body": "Aella",
                    "updated_at": 1,
                    "deleted": false
                })],
            )]),
            checksum: None,
        })
        .expect("snapshot bytes");
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        runtime.import_snapshot(&snapshot).expect("import");
        let rows = runtime.fetch_relation_rows("notes").expect("notes");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["id"], "snapshot-note");
    }

    #[test]
    fn native_runtime_persists_content_rows_in_overgraph_store() {
        let root = std::env::temp_dir().join(format!("phoenix-overgraph-runtime-{}", now_ms()));
        {
            let runtime =
                PhoenixRuntime::open(RuntimeConfig::default(), Some(root.clone())).expect("open");
            runtime.init().expect("init");
            runtime
                .put_relation_row(
                    "notes",
                    json!({
                        "id": "persisted-note",
                        "version": 1,
                        "world_id": null,
                        "narrative_id": null,
                        "entity_kind": null,
                        "title": "Persisted",
                        "body": "Aella",
                        "updated_at": 1,
                        "deleted": false
                    }),
                )
                .expect("put");
        }
        {
            let runtime =
                PhoenixRuntime::open(RuntimeConfig::default(), Some(root.clone())).expect("reopen");
            runtime.init().expect("init restored");
            let rows = runtime.fetch_relation_rows("notes").expect("notes");
            assert_eq!(rows.len(), 1);
            assert_eq!(rows[0]["id"], "persisted-note");
        }
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn session_commit_cycle_updates_revision() {
        let runtime = native_test_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Foundation".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        let commit = runtime
            .commit(CommitRequest {
                session_id: session.session_id,
                reason: Some("phase-2".to_owned()),
            })
            .expect("commit");

        assert_eq!(commit.revision, 1);
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn ingest_and_query_roundtrip() {
        let runtime = native_test_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Stub".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        let ingest = runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-1".to_owned()),
                    note_id: None,
                    title: "Ash Song".to_owned(),
                    text: "The phoenix rose from ash.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: true,
            })
            .expect("ingest");
        assert_eq!(ingest.document_count, 1);

        let query = runtime
            .query(QueryRequest {
                session_id: Some(session.session_id),
                query: "phoenix".to_owned(),
                scope: ScopeKey::default(),
                targets: vec![QueryTarget::Chunks],
                limit: Some(3),
                temporal: None,
                semantic_query_vector: None,
                include_candidate_graph: false,
            })
            .expect("query");

        assert_eq!(query.chunk_hits.len(), 1);
        assert!(query.chunk_hits[0].chunk_id.starts_with("doc-1:"));
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn native_v2_scan_query_and_graph_delta_use_v2_paths() {
        let runtime = native_test_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "V2 Query".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        let scan = runtime.scan_text(ScanRequest {
            session_id: Some(session.session_id.clone()),
            text: "Ryan crossed the harbor before dawn.".to_owned(),
            scope: ScopeKey::default(),
            resolver_seed: Vec::new(),
        });
        assert!(scan
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "PX_INVARANT_V2_SCAN"));

        let structure = runtime.build_structure(StructureRequest {
            text: "Ryan crossed the harbor before dawn.".to_owned(),
            scan: scan.clone(),
        });
        assert!(structure
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "PX_INVARANT_V2_STRUCTURE"));

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-v2-query".to_owned()),
                    note_id: None,
                    title: "V2 Query".to_owned(),
                    text: "Ryan crossed the harbor before dawn.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: true,
            })
            .expect("ingest");

        let query = runtime
            .query(QueryRequest {
                session_id: Some(session.session_id.clone()),
                query: "Ryan".to_owned(),
                scope: ScopeKey::default(),
                targets: vec![QueryTarget::Chunks, QueryTarget::Nodes],
                limit: Some(5),
                temporal: None,
                semantic_query_vector: None,
                include_candidate_graph: false,
            })
            .expect("query");
        assert!(!query.chunk_hits.is_empty());
        assert!(!query.node_hits.is_empty());
        assert!(query
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "PX_TRIVERSE_V2_KERNEL"));

        let delta = runtime
            .graph_delta(GraphDeltaRequest {
                session_id: session.session_id.clone(),
                scope: ScopeKey::default(),
                changed_documents: Vec::new(),
                limit: None,
                since_commit: Some(CommitId("commit-native-kernel-delta".to_owned())),
                include_candidate_graph: false,
            })
            .expect("graph delta");
        assert!(!delta.nodes.is_empty());
        assert!(delta
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "PX_GRAPH_DELTA_KERNEL"));
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn native_v2_snapshot_roundtrip_preserves_bundles_and_query_paths() {
        let runtime = native_test_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "V2 Snapshot".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-v2-snapshot".to_owned()),
                    note_id: None,
                    title: "Snapshot".to_owned(),
                    text: "Ryan mapped the harbor before dawn.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: true,
            })
            .expect("ingest");

        let snapshot = runtime.export_snapshot().expect("export snapshot");

        let restored = native_test_runtime();
        restored.init().expect("restored init");
        let envelope = restored
            .import_snapshot(&snapshot)
            .expect("import snapshot");
        assert_eq!(envelope.schema_version, NATIVE_RUNTIME_SCHEMA_VERSION);

        let restored_session = restored
            .session_state(&session.session_id)
            .expect("session state");
        assert_eq!(restored_session.documents.len(), 1);

        let restored_stats = restored
            .session_stats(&session.session_id)
            .expect("session stats");
        assert_eq!(restored_stats.document_count, 1);
        assert!(restored_stats.graph_vertex_count >= 1);

        let query = restored
            .query(QueryRequest {
                session_id: Some(session.session_id.clone()),
                query: "Ryan".to_owned(),
                scope: ScopeKey::default(),
                targets: vec![QueryTarget::Chunks, QueryTarget::Nodes],
                limit: Some(5),
                temporal: None,
                semantic_query_vector: None,
                include_candidate_graph: false,
            })
            .expect("query");
        assert!(!query.chunk_hits.is_empty());
        assert!(!query.node_hits.is_empty());
        assert!(query
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "PX_TRIVERSE_V2_KERNEL"));

        assert_eq!(
            restored.fetch_relation_rows("notes").expect("notes").len(),
            1
        );
        assert!(!restored
            .fetch_relation_rows("graph_vertices")
            .expect("graph vertices")
            .is_empty());
    }

    #[test]
    fn native_rebuild_prunes_out_of_tree_graph_document_scopes() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        runtime
            .upsert_note_row(&json!({
                "id": "live-doc",
                "version": 1,
                "title": "Live",
                "folder_id": "global",
                "updated_at": 1,
                "is_current": true
            }))
            .expect("live note");

        let embedded_deleted_doc = "1106cb46-5784-420a-8020-45085394f67c";
        let stale_batch = KernelGraphMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Full,
            recorded_at: Some(10),
            vertices: vec![
                KernelVertex {
                    id: KernelVertexId("doc::deleted-doc".to_owned()),
                    kind: "document".to_owned(),
                    document_id: Some("deleted-doc".to_owned()),
                    value: json!({ "kind": "document" }),
                    attributes: json!({ "documentId": "deleted-doc" }),
                    ..KernelVertex::default()
                },
                KernelVertex {
                    id: KernelVertexId(format!("leaf::{embedded_deleted_doc}:0:0:1:0-1")),
                    kind: "leaf".to_owned(),
                    value: json!({ "kind": "leaf" }),
                    attributes: json!({}),
                    ..KernelVertex::default()
                },
                KernelVertex {
                    id: KernelVertexId("parent::1093190677".to_owned()),
                    kind: "parent".to_owned(),
                    value: json!({ "kind": "parent" }),
                    attributes: json!({}),
                    ..KernelVertex::default()
                },
            ],
            edges: vec![KernelEdge {
                source_id: KernelVertexId("parent::1093190677".to_owned()),
                target_id: KernelVertexId(format!("leaf::{embedded_deleted_doc}:0:0:1:0-1")),
                edge_type: KernelEdgeType("contains".to_owned()),
                attributes: json!({}),
                ..KernelEdge::default()
            }],
        };
        runtime
            .native_runtime
            .deterministic_kernel
            .apply_batch(stale_batch.clone())
            .expect("apply stale graph");
        runtime
            .persist_native_graph_batch(&stale_batch, None)
            .expect("persist stale graph");

        let before = runtime
            .project_native_graph_relation_rows("graph_vertices")
            .expect("project before");
        assert!(before
            .iter()
            .any(|row| { row.get("document_id").and_then(Value::as_str) == Some("deleted-doc") }));
        let before_edges = runtime
            .project_native_graph_relation_rows("graph_edges")
            .expect("project edges before");
        assert!(before_edges.iter().any(|row| {
            row.get("target_id")
                .and_then(Value::as_str)
                .is_some_and(|target_id| target_id.contains(embedded_deleted_doc))
        }));

        let rebuild = runtime.rebuild(RebuildRequest::default()).expect("rebuild");
        assert!(rebuild
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "PX_REBUILD_GRAPH_PRUNE"));

        let after = runtime
            .project_native_graph_relation_rows("graph_vertices")
            .expect("project after");
        assert!(!after
            .iter()
            .any(|row| { row.get("document_id").and_then(Value::as_str) == Some("deleted-doc") }));
        assert!(!after.iter().any(|row| {
            row.get("id")
                .and_then(Value::as_str)
                .is_some_and(|id| id.contains(embedded_deleted_doc))
        }));
        let after_edges = runtime
            .project_native_graph_relation_rows("graph_edges")
            .expect("project edges after");
        assert!(!after_edges.iter().any(|row| {
            row.get("target_id")
                .and_then(Value::as_str)
                .is_some_and(|target_id| target_id.contains(embedded_deleted_doc))
        }));
    }

    #[test]
    fn native_semantic_store_commands_refresh_document_candidate_edges_from_overgraph_vectors() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Native semantic".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![
                    phoenix_types::IngestDocument {
                        document_id: DocumentId("doc-sem-a".to_owned()),
                        note_id: None,
                        title: "Dock A".to_owned(),
                        text: "Ryan mapped dock alpha before dawn.".to_owned(),
                        scope: ScopeKey::default(),
                    },
                    phoenix_types::IngestDocument {
                        document_id: DocumentId("doc-sem-b".to_owned()),
                        note_id: None,
                        title: "Dock B".to_owned(),
                        text: "Rian mapped dock beta before dawn.".to_owned(),
                        scope: ScopeKey::default(),
                    },
                ],
                commit: false,
            })
            .expect("ingest");

        let leaf_payload = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:listLeafChunks".to_owned(),
                payload: json!({ "documentIds": ["doc-sem-a", "doc-sem-b"] }),
            })
            .expect("list leaf chunks")
            .payload
            .expect("leaf payload");
        let leaf_chunks: Vec<SemanticLeafChunk> =
            serde_json::from_value(leaf_payload).expect("leaf chunks");
        assert!(!leaf_chunks.is_empty());

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:upsertDocumentVectors".to_owned(),
                payload: json!({
                    "rows": [
                        {
                            "documentId": "doc-sem-a",
                            "values": semantic_test_vector(0),
                            "leafCount": 1,
                            "evidenceRefs": ["span:doc-sem-a"]
                        },
                        {
                            "documentId": "doc-sem-b",
                            "values": semantic_test_vector(0),
                            "leafCount": 1,
                            "evidenceRefs": ["span:doc-sem-b"]
                        }
                    ]
                }),
            })
            .expect("upsert document vectors");

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:refreshCandidateGraphEdges".to_owned(),
                payload: json!({
                    "documentIds": ["doc-sem-a", "doc-sem-b"],
                    "nodeIds": [],
                }),
            })
            .expect("refresh candidate graph");

        let candidate_edges = runtime.candidate_edge_rows().expect("candidate edges");
        assert!(candidate_edges.iter().any(|row| {
            row.get("source_id").and_then(Value::as_str) == Some("doc::doc-sem-a")
                && row.get("target_id").and_then(Value::as_str) == Some("doc::doc-sem-b")
                && row.get("edge_type").and_then(Value::as_str) == Some("similar_to")
        }));
    }

    #[test]
    fn native_semantic_truth_review_command_reports_candidate_only_edges() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Native truth review".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![
                    phoenix_types::IngestDocument {
                        document_id: DocumentId("doc-review-a".to_owned()),
                        note_id: None,
                        title: "Review A".to_owned(),
                        text: "Ryan mapped dock alpha before dawn.".to_owned(),
                        scope: ScopeKey::default(),
                    },
                    phoenix_types::IngestDocument {
                        document_id: DocumentId("doc-review-b".to_owned()),
                        note_id: None,
                        title: "Review B".to_owned(),
                        text: "Rian mapped dock beta before dawn.".to_owned(),
                        scope: ScopeKey::default(),
                    },
                ],
                commit: false,
            })
            .expect("ingest");

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:upsertDocumentVectors".to_owned(),
                payload: json!({
                    "rows": [
                        {
                            "documentId": "doc-review-a",
                            "values": semantic_test_vector(0),
                            "leafCount": 1,
                            "evidenceRefs": ["span:doc-review-a"]
                        },
                        {
                            "documentId": "doc-review-b",
                            "values": semantic_test_vector(0),
                            "leafCount": 1,
                            "evidenceRefs": ["span:doc-review-b"]
                        }
                    ]
                }),
            })
            .expect("upsert document vectors");

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:refreshCandidateGraphEdges".to_owned(),
                payload: json!({
                    "documentIds": ["doc-review-a", "doc-review-b"],
                    "nodeIds": [],
                }),
            })
            .expect("refresh candidate graph");

        let payload = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:runEmbedderTruthReview".to_owned(),
                payload: json!({
                    "laneMode": "truth-review",
                    "documentIds": ["doc-review-a", "doc-review-b"],
                    "nodeIds": [],
                    "edgePreviewLimit": 4,
                    "model": {
                        "modelId": "jinaai/jina-embeddings-v5-text-nano-retrieval",
                        "modelLabel": "Jina v5 Nano",
                        "embeddingProfile": "768",
                        "executionProvider": "directml"
                    }
                }),
            })
            .expect("truth review")
            .payload
            .expect("payload");

        assert_eq!(
            payload.get("candidateOnly").and_then(Value::as_bool),
            Some(true)
        );
        assert_eq!(
            payload
                .pointer("/output/committedTopologyWrites")
                .and_then(Value::as_u64),
            Some(0)
        );
        assert!(
            payload
                .pointer("/output/candidateEdgeCount")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                >= 1
        );
        assert_eq!(
            payload.pointer("/cache/misses").and_then(Value::as_u64),
            Some(0)
        );
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn session_state_and_stats_persist_after_ingest() {
        let runtime = native_test_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "State".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-state".to_owned()),
                    note_id: None,
                    title: "Stateful".to_owned(),
                    text: "# Prologue\nRyan woke up.\n\nChapter 1\nRyan met Len.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: false,
            })
            .expect("ingest");

        let state = runtime
            .session_state(&session.session_id)
            .expect("session state");
        let stats = runtime
            .session_stats(&session.session_id)
            .expect("session stats");

        assert_eq!(state.documents.len(), 1);
        assert!(stats.chapter_count >= 1);
        assert!(stats.graph_vertex_count >= 1);
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn phase2_candidate_prototypes_and_edges_refresh_from_store_commands() {
        let runtime = wasm_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Phase2".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-phase2".to_owned()),
                    note_id: None,
                    title: "Harbor".to_owned(),
                    text: "Ryan met Rian at the harbor.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: false,
            })
            .expect("ingest");

        let leaf_id = runtime
            .fetch_relation_rows("graph_vertices")
            .expect("graph vertices")
            .into_iter()
            .find(|row| {
                row.get("document_id").and_then(Value::as_str) == Some("doc-phase2")
                    && row
                        .get("value")
                        .and_then(Value::as_object)
                        .and_then(|value| value.get("kind"))
                        .and_then(Value::as_str)
                        == Some("leaf")
            })
            .and_then(|row| row.get("id").and_then(Value::as_str).map(str::to_owned))
            .expect("leaf vertex");
        for (entity_id, label, aliases) in [
            ("entity::ryan", "Ryan", json!(["Ryan Hale"])),
            ("entity::ryan-alt", "Ryan Hale", json!(["Ryan"])),
        ] {
            runtime
            .put_relation_row(
                    "graph_vertices",
                    json!({
                        "id": entity_id,
                        "document_id": "doc-phase2",
                        "narrative_id": null,
                        "value": { "kind": "entity", "entityId": entity_id.trim_start_matches("entity::"), "label": label, "entityKind": "Character" },
                        "weight": 1,
                        "attributes": {
                            "aliases": aliases,
                            "documentId": "doc-phase2",
                            "graph": {
                                "layer": "asserted",
                                "status": "asserted",
                                "resolver": "test",
                                "confidence": 1.0,
                                "evidence_refs": [format!("graph_vertex:{}", leaf_id)]
                            }
                        }
                    }),
                )
                .expect("entity vertex");
            runtime
                .put_relation_row(
                    "graph_edges",
                    json!({
                        "source_id": leaf_id.as_str(),
                        "target_id": entity_id,
                        "document_id": "doc-phase2",
                        "narrative_id": null,
                        "valid_from_doc": "doc-phase2",
                        "valid_from_boundary": null,
                        "valid_to_doc": null,
                        "valid_to_boundary": null,
                        "assertion_kind": "asserted",
                        "weight": 100,
                        "attributes": {
                            "documentId": "doc-phase2",
                            "graph": {
                                "layer": "asserted",
                                "status": "asserted",
                                "resolver": "test",
                                "confidence": 1.0,
                                "evidence_refs": [format!("graph_vertex:{}", leaf_id)]
                            }
                        },
                        "data": null,
                        "edge_type": "mentions"
                    }),
                )
                .expect("mentions edge");
        }

        let payload = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:listCandidatePrototypeInputs".to_owned(),
                payload: json!({ "documentIds": ["doc-phase2"] }),
            })
            .expect("prototype inputs")
            .payload
            .expect("prototype payload");
        let inputs: Vec<SemanticCandidatePrototypeInput> =
            serde_json::from_value(payload).expect("prototype rows");
        let entities = inputs
            .iter()
            .filter(|row| row.node_kind == "entity")
            .take(2)
            .cloned()
            .collect::<Vec<_>>();
        assert_eq!(entities.len(), 2, "expected two entity prototypes");

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:upsertPrototypeVectors".to_owned(),
                payload: json!({
                    "rows": entities.iter().map(|entity| {
                        json!({
                            "nodeId": entity.node_id,
                            "nodeKind": entity.node_kind,
                            "documentId": entity.document_id,
                            "narrativeId": entity.narrative_id,
                            "folderId": entity.folder_id,
                            "values": semantic_test_vector(0),
                            "evidenceRefs": entity.evidence_refs,
                        })
                    }).collect::<Vec<_>>()
                }),
            })
            .expect("upsert prototype vectors");

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:refreshCandidateGraphEdges".to_owned(),
                payload: json!({
                    "documentIds": ["doc-phase2"],
                    "nodeIds": entities.iter().map(|entity| entity.node_id.clone()).collect::<Vec<_>>(),
                }),
            })
            .expect("refresh candidate graph");

        let candidate_edges = runtime
            .fetch_relation_rows("graph_candidate_edges")
            .expect("candidate edges");
        let relevant_edge = candidate_edges
            .iter()
            .find(|row| {
                row.get("source_id").and_then(Value::as_str) == Some(entities[0].node_id.as_str())
                    && row.get("target_id").and_then(Value::as_str)
                        == Some(entities[1].node_id.as_str())
                    && row.get("edge_type").and_then(Value::as_str)
                        == Some("candidate_corefers_with")
            })
            .expect("candidate coref edge");

        let graph_meta = relevant_edge
            .get("attributes")
            .and_then(Value::as_object)
            .and_then(|attributes| attributes.get("graph"))
            .and_then(Value::as_object)
            .expect("candidate graph metadata");
        assert_eq!(
            graph_meta.get("layer").and_then(Value::as_str),
            Some("candidate")
        );
        assert_eq!(
            graph_meta.get("resolver").and_then(Value::as_str),
            Some(PHASE2_EMBEDDING_RESOLVER)
        );
        assert_eq!(
            relevant_edge
                .get("data")
                .and_then(Value::as_object)
                .and_then(|data| data.get("base"))
                .and_then(Value::as_object)
                .and_then(|base| base.get("resolver"))
                .and_then(Value::as_str),
            Some(PHASE2_EMBEDDING_RESOLVER)
        );
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn phase2_entity_candidate_edges_require_surface_coherence() {
        let runtime = wasm_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Phase2 coherence".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-phase2-coherence".to_owned()),
                    note_id: None,
                    title: "Harbor".to_owned(),
                    text: "Ryan met Rian at the harbor.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: false,
            })
            .expect("ingest");

        let leaf_id = runtime
            .fetch_relation_rows("graph_vertices")
            .expect("graph vertices")
            .into_iter()
            .find(|row| {
                row.get("document_id").and_then(Value::as_str) == Some("doc-phase2-coherence")
                    && row
                        .get("value")
                        .and_then(Value::as_object)
                        .and_then(|value| value.get("kind"))
                        .and_then(Value::as_str)
                        == Some("leaf")
            })
            .and_then(|row| row.get("id").and_then(Value::as_str).map(str::to_owned))
            .expect("leaf vertex");
        for (entity_id, label) in [
            ("entity::ryan-coherence", "Ryan"),
            ("entity::rian-coherence", "Rian"),
        ] {
            runtime
            .put_relation_row(
                    "graph_vertices",
                    json!({
                        "id": entity_id,
                        "document_id": "doc-phase2-coherence",
                        "narrative_id": null,
                        "value": { "kind": "entity", "entityId": entity_id.trim_start_matches("entity::"), "label": label, "entityKind": "Character" },
                        "weight": 1,
                        "attributes": {
                            "documentId": "doc-phase2-coherence",
                            "graph": {
                                "layer": "asserted",
                                "status": "asserted",
                                "resolver": "test",
                                "confidence": 1.0,
                                "evidence_refs": [format!("graph_vertex:{}", leaf_id)]
                            }
                        }
                    }),
                )
                .expect("entity vertex");
            runtime
                .put_relation_row(
                    "graph_edges",
                    json!({
                        "source_id": leaf_id.as_str(),
                        "target_id": entity_id,
                        "document_id": "doc-phase2-coherence",
                        "narrative_id": null,
                        "valid_from_doc": "doc-phase2-coherence",
                        "valid_from_boundary": null,
                        "valid_to_doc": null,
                        "valid_to_boundary": null,
                        "assertion_kind": "asserted",
                        "weight": 100,
                        "attributes": {
                            "documentId": "doc-phase2-coherence",
                            "graph": {
                                "layer": "asserted",
                                "status": "asserted",
                                "resolver": "test",
                                "confidence": 1.0,
                                "evidence_refs": [format!("graph_vertex:{}", leaf_id)]
                            }
                        },
                        "data": null,
                        "edge_type": "mentions"
                    }),
                )
                .expect("mentions edge");
        }

        let payload = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:listCandidatePrototypeInputs".to_owned(),
                payload: json!({ "documentIds": ["doc-phase2-coherence"] }),
            })
            .expect("prototype inputs")
            .payload
            .expect("prototype payload");
        let inputs: Vec<SemanticCandidatePrototypeInput> =
            serde_json::from_value(payload).expect("prototype rows");
        let entities = inputs
            .iter()
            .filter(|row| row.node_kind == "entity")
            .take(2)
            .cloned()
            .collect::<Vec<_>>();

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:upsertPrototypeVectors".to_owned(),
                payload: json!({
                    "rows": entities.iter().map(|entity| {
                        json!({
                            "nodeId": entity.node_id,
                            "nodeKind": entity.node_kind,
                            "documentId": entity.document_id,
                            "narrativeId": entity.narrative_id,
                            "folderId": entity.folder_id,
                            "values": semantic_test_vector(0),
                            "evidenceRefs": entity.evidence_refs,
                        })
                    }).collect::<Vec<_>>()
                }),
            })
            .expect("upsert prototype vectors");

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:refreshCandidateGraphEdges".to_owned(),
                payload: json!({
                    "documentIds": ["doc-phase2-coherence"],
                    "nodeIds": entities.iter().map(|entity| entity.node_id.clone()).collect::<Vec<_>>(),
                }),
            })
            .expect("refresh candidate graph");

        let candidate_edges = runtime
            .fetch_relation_rows("graph_candidate_edges")
            .expect("candidate edges");
        assert!(candidate_edges.iter().all(|row| {
            row.get("edge_type").and_then(Value::as_str) != Some("candidate_corefers_with")
        }));
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn phase2_nli_inputs_are_bounded_and_apply_promotes_or_rejects_candidate_edges() {
        let runtime = wasm_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Phase2 NLI".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-phase2-nli".to_owned()),
                    note_id: None,
                    title: "Harbor".to_owned(),
                    text: "Ryan met Rian at the harbor.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: false,
            })
            .expect("ingest");

        let leaf_id = runtime
            .fetch_relation_rows("graph_vertices")
            .expect("graph vertices")
            .into_iter()
            .find(|row| {
                row.get("document_id").and_then(Value::as_str) == Some("doc-phase2-nli")
                    && row
                        .get("value")
                        .and_then(Value::as_object)
                        .and_then(|value| value.get("kind"))
                        .and_then(Value::as_str)
                        == Some("leaf")
            })
            .and_then(|row| row.get("id").and_then(Value::as_str).map(str::to_owned))
            .expect("leaf vertex");
        for (entity_id, label, aliases) in [
            ("entity::ryan-nli", "Ryan", json!(["Ryan Hale"])),
            ("entity::ryan-hale-nli", "Ryan Hale", json!(["Ryan"])),
        ] {
            runtime
            .put_relation_row(
                    "graph_vertices",
                    json!({
                        "id": entity_id,
                        "document_id": "doc-phase2-nli",
                        "narrative_id": null,
                        "value": { "kind": "entity", "entityId": entity_id.trim_start_matches("entity::"), "label": label, "entityKind": "Character" },
                        "weight": 1,
                        "attributes": {
                            "aliases": aliases,
                            "documentId": "doc-phase2-nli",
                            "graph": {
                                "layer": "asserted",
                                "status": "asserted",
                                "resolver": "test",
                                "confidence": 1.0,
                                "evidence_refs": [format!("graph_vertex:{}", leaf_id)]
                            }
                        }
                    }),
                )
                .expect("entity vertex");
            runtime
                .put_relation_row(
                    "graph_edges",
                    json!({
                        "source_id": leaf_id.as_str(),
                        "target_id": entity_id,
                        "document_id": "doc-phase2-nli",
                        "narrative_id": null,
                        "valid_from_doc": "doc-phase2-nli",
                        "valid_from_boundary": null,
                        "valid_to_doc": null,
                        "valid_to_boundary": null,
                        "assertion_kind": "asserted",
                        "weight": 100,
                        "attributes": {
                            "documentId": "doc-phase2-nli",
                            "graph": {
                                "layer": "asserted",
                                "status": "asserted",
                                "resolver": "test",
                                "confidence": 1.0,
                                "evidence_refs": [format!("graph_vertex:{}", leaf_id)]
                            }
                        },
                        "data": null,
                        "edge_type": "mentions"
                    }),
                )
                .expect("mentions edge");
        }

        let payload = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:listCandidatePrototypeInputs".to_owned(),
                payload: json!({ "documentIds": ["doc-phase2-nli"] }),
            })
            .expect("prototype inputs")
            .payload
            .expect("prototype payload");
        let inputs: Vec<SemanticCandidatePrototypeInput> =
            serde_json::from_value(payload).expect("prototype rows");
        let entities = inputs
            .iter()
            .filter(|row| row.node_kind == "entity")
            .take(2)
            .cloned()
            .collect::<Vec<_>>();

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:upsertPrototypeVectors".to_owned(),
                payload: json!({
                    "rows": entities.iter().map(|entity| {
                        json!({
                            "nodeId": entity.node_id,
                            "nodeKind": entity.node_kind,
                            "documentId": entity.document_id,
                            "narrativeId": entity.narrative_id,
                            "folderId": entity.folder_id,
                            "values": semantic_test_vector(0),
                            "evidenceRefs": entity.evidence_refs,
                        })
                    }).collect::<Vec<_>>()
                }),
            })
            .expect("upsert prototype vectors");

        runtime
            .store_command(StoreCommandRequest {
                command: "semantic:refreshCandidateGraphEdges".to_owned(),
                payload: json!({
                    "documentIds": ["doc-phase2-nli"],
                    "nodeIds": entities.iter().map(|entity| entity.node_id.clone()).collect::<Vec<_>>(),
                }),
            })
            .expect("refresh candidate graph");

        let nli_payload = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:listNliJudgmentInputs".to_owned(),
                payload: json!({
                    "documentIds": ["doc-phase2-nli"],
                    "nodeIds": entities.iter().map(|entity| entity.node_id.clone()).collect::<Vec<_>>(),
                }),
            })
            .expect("nli inputs")
            .payload
            .expect("nli input payload");
        let nli_inputs: Vec<SemanticNliJudgmentInput> =
            serde_json::from_value(nli_payload).expect("nli judgment inputs");
        assert_eq!(nli_inputs.len(), 2);
        assert!(nli_inputs[0].hypothesis.contains("same entity"));
        assert!(nli_inputs.len() <= PHASE2_NLI_MAX_INPUTS);

        let accepted = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:applyNliJudgments".to_owned(),
                payload: json!({
                    "modelId": SEMANTIC_NLI_MODEL_ID,
                    "device": "wasm",
                    "results": nli_inputs.iter().map(|input| {
                        json!({
                            "judgmentId": input.judgment_id,
                            "groupId": input.group_id,
                            "sourceId": input.source_id,
                            "targetId": input.target_id,
                            "edgeType": input.edge_type,
                            "direction": input.direction,
                            "premise": input.premise,
                            "hypothesis": input.hypothesis,
                            "entailment": 0.84,
                            "neutral": 0.09,
                            "contradiction": 0.07,
                            "predictedLabel": "entailment",
                            "confidence": 0.84,
                        })
                    }).collect::<Vec<_>>()
                }),
            })
            .expect("apply accepted nli")
            .payload
            .expect("accepted payload");
        assert_eq!(accepted.get("kept").and_then(Value::as_u64), Some(1));

        let rejected = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:applyNliJudgments".to_owned(),
                payload: json!({
                    "modelId": SEMANTIC_NLI_MODEL_ID,
                    "device": "wasm",
                    "results": nli_inputs.iter().map(|input| {
                        json!({
                            "judgmentId": input.judgment_id,
                            "groupId": input.group_id,
                            "sourceId": input.source_id,
                            "targetId": input.target_id,
                            "edgeType": input.edge_type,
                            "direction": input.direction,
                            "premise": input.premise,
                            "hypothesis": input.hypothesis,
                            "entailment": 0.11,
                            "neutral": 0.18,
                            "contradiction": 0.71,
                            "predictedLabel": "contradiction",
                            "confidence": 0.71,
                        })
                    }).collect::<Vec<_>>()
                }),
            })
            .expect("apply rejected nli")
            .payload
            .expect("rejected payload");
        assert_eq!(rejected.get("rejected").and_then(Value::as_u64), Some(1));

        let row = runtime
            .fetch_relation_rows("graph_candidate_edges")
            .expect("candidate rows")
            .into_iter()
            .find(|row| {
                row.get("source_id").and_then(Value::as_str) == Some(entities[0].node_id.as_str())
                    && row.get("target_id").and_then(Value::as_str)
                        == Some(entities[1].node_id.as_str())
                    && row.get("edge_type").and_then(Value::as_str)
                        == Some("candidate_corefers_with")
            })
            .expect("candidate edge row");
        let graph_meta = row
            .get("attributes")
            .and_then(Value::as_object)
            .and_then(|attributes| attributes.get("graph"))
            .and_then(Value::as_object)
            .expect("graph metadata");
        assert_eq!(
            graph_meta.get("status").and_then(Value::as_str),
            Some("candidate_rejected")
        );
        assert_eq!(
            graph_meta.get("resolver").and_then(Value::as_str),
            Some(PHASE2_NLI_RESOLVER)
        );
        let data = row
            .get("data")
            .and_then(Value::as_object)
            .expect("candidate edge data");
        assert!(data.get("base").is_some());
        assert!(data.get("nli").is_some());
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn phase2_nli_creates_task_evidence_candidate_rows_for_support_and_rejection() {
        let runtime = wasm_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Phase2 NLI Evidence".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-phase2-nli-evidence".to_owned()),
                    note_id: None,
                    title: "Harbor task".to_owned(),
                    text: "Map the harbor before dawn.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: false,
            })
            .expect("ingest");

        let leaf_id = runtime
            .fetch_relation_rows("graph_vertices")
            .expect("graph vertices")
            .into_iter()
            .find(|row| {
                row.get("document_id").and_then(Value::as_str) == Some("doc-phase2-nli-evidence")
                    && row
                        .get("value")
                        .and_then(Value::as_object)
                        .and_then(|value| value.get("kind"))
                        .and_then(Value::as_str)
                        == Some("leaf")
            })
            .and_then(|row| row.get("id").and_then(Value::as_str).map(str::to_owned))
            .expect("leaf vertex");

        runtime
            .put_relation_row(
                "graph_vertices",
                json!({
                    "id": "task::phase2-evidence",
                    "document_id": "doc-phase2-nli-evidence",
                    "narrative_id": null,
                    "value": { "kind": "task", "label": "Map the harbor" },
                    "weight": 1,
                    "attributes": {
                        "documentId": "doc-phase2-nli-evidence",
                        "currentTask": "Map the harbor",
                        "graph": {
                            "layer": "asserted",
                            "status": "asserted",
                            "resolver": "test",
                            "confidence": 1.0,
                            "evidence_refs": [format!("graph_vertex:{leaf_id}")]
                        }
                    }
                }),
            )
            .expect("task vertex");

        let nli_payload = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:listNliJudgmentInputs".to_owned(),
                payload: json!({
                    "documentIds": ["doc-phase2-nli-evidence"],
                    "nodeIds": ["task::phase2-evidence"],
                }),
            })
            .expect("nli inputs")
            .payload
            .expect("nli input payload");
        let nli_inputs: Vec<SemanticNliJudgmentInput> =
            serde_json::from_value(nli_payload).expect("nli judgment inputs");
        assert!(nli_inputs
            .iter()
            .any(|input| input.edge_type == "supported_by" && input.target_id == leaf_id));
        assert!(nli_inputs
            .iter()
            .any(|input| input.edge_type == "contradicted_by" && input.target_id == leaf_id));

        let apply_payload = runtime
            .store_command(StoreCommandRequest {
                command: "semantic:applyNliJudgments".to_owned(),
                payload: json!({
                    "modelId": SEMANTIC_NLI_MODEL_ID,
                    "device": "wasm",
                    "results": nli_inputs.iter().map(|input| {
                        if input.edge_type == "supported_by" {
                            json!({
                                "judgmentId": input.judgment_id,
                                "groupId": input.group_id,
                                "sourceId": input.source_id,
                                "targetId": input.target_id,
                                "edgeType": input.edge_type,
                                "direction": input.direction,
                                "premise": input.premise,
                                "hypothesis": input.hypothesis,
                                "entailment": 0.83,
                                "neutral": 0.11,
                                "contradiction": 0.06,
                                "predictedLabel": "entailment",
                                "confidence": 0.83,
                            })
                        } else {
                            json!({
                                "judgmentId": input.judgment_id,
                                "groupId": input.group_id,
                                "sourceId": input.source_id,
                                "targetId": input.target_id,
                                "edgeType": input.edge_type,
                                "direction": input.direction,
                                "premise": input.premise,
                                "hypothesis": input.hypothesis,
                                "entailment": 0.54,
                                "neutral": 0.30,
                                "contradiction": 0.16,
                                "predictedLabel": "entailment",
                                "confidence": 0.54,
                            })
                        }
                    }).collect::<Vec<_>>()
                }),
            })
            .expect("apply nli judgments")
            .payload
            .expect("nli apply payload");
        assert_eq!(apply_payload.get("kept").and_then(Value::as_u64), Some(1));
        assert_eq!(
            apply_payload.get("rejected").and_then(Value::as_u64),
            Some(1)
        );

        let candidate_rows = runtime
            .fetch_relation_rows("graph_candidate_edges")
            .expect("candidate rows");
        let supported_row = candidate_rows
            .iter()
            .find(|row| {
                row.get("source_id").and_then(Value::as_str) == Some("task::phase2-evidence")
                    && row.get("target_id").and_then(Value::as_str) == Some(leaf_id.as_str())
                    && row.get("edge_type").and_then(Value::as_str) == Some("supported_by")
            })
            .expect("supported row");
        let supported_graph = supported_row
            .get("attributes")
            .and_then(Value::as_object)
            .and_then(|attributes| attributes.get("graph"))
            .and_then(Value::as_object)
            .expect("supported graph metadata");
        assert_eq!(
            supported_graph.get("status").and_then(Value::as_str),
            Some("candidate")
        );
        assert_eq!(
            supported_row
                .get("data")
                .and_then(Value::as_object)
                .and_then(|data| data.get("base"))
                .and_then(Value::as_object)
                .and_then(|base| base.get("resolver"))
                .and_then(Value::as_str),
            Some(PHASE2_NLI_RESOLVER)
        );

        let contradicted_row = candidate_rows
            .iter()
            .find(|row| {
                row.get("source_id").and_then(Value::as_str) == Some("task::phase2-evidence")
                    && row.get("target_id").and_then(Value::as_str) == Some(leaf_id.as_str())
                    && row.get("edge_type").and_then(Value::as_str) == Some("contradicted_by")
            })
            .expect("contradicted row");
        let contradicted_graph = contradicted_row
            .get("attributes")
            .and_then(Value::as_object)
            .and_then(|attributes| attributes.get("graph"))
            .and_then(Value::as_object)
            .expect("contradicted graph metadata");
        assert_eq!(
            contradicted_graph.get("status").and_then(Value::as_str),
            Some("candidate_rejected")
        );
        assert!(contradicted_row
            .get("data")
            .and_then(Value::as_object)
            .and_then(|data| data.get("nli"))
            .is_some());
    }

    #[test]
    fn graph_delta_and_binary_payloads_are_rebuildable_from_canonical_state() {
        let runtime = native_test_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Binary".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-binary".to_owned()),
                    note_id: None,
                    title: "Binary".to_owned(),
                    text: "Ryan attacked Len. Ryan gave Len a blade.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: false,
            })
            .expect("ingest");

        let graph_delta = runtime
            .graph_delta(GraphDeltaRequest {
                session_id: session.session_id.clone(),
                scope: ScopeKey::default(),
                changed_documents: vec![DocumentId("doc-binary".to_owned())],
                limit: Some(8),
                since_commit: None,
                include_candidate_graph: false,
            })
            .expect("graph delta");
        assert!(!graph_delta.nodes.is_empty() || !graph_delta.chunks.is_empty());
        assert!(!graph_delta.edges.is_empty());

        let query_bytes = runtime
            .query_binary(QueryRequest {
                session_id: Some(session.session_id.clone()),
                query: "Ryan".to_owned(),
                scope: ScopeKey::default(),
                targets: vec![QueryTarget::Chunks],
                limit: Some(5),
                temporal: None,
                semantic_query_vector: None,
                include_candidate_graph: false,
            })
            .expect("query bytes");
        let graph_bytes = runtime
            .graph_delta_binary(GraphDeltaRequest {
                session_id: session.session_id.clone(),
                scope: ScopeKey::default(),
                changed_documents: vec![DocumentId("doc-binary".to_owned())],
                limit: Some(8),
                since_commit: None,
                include_candidate_graph: false,
            })
            .expect("graph bytes");
        let state_bytes = runtime
            .session_state_binary(&session.session_id)
            .expect("state bytes");
        let stats_bytes = runtime
            .session_stats_binary(&session.session_id)
            .expect("stats bytes");

        assert!(query_bytes.len() >= QueryResultHeader::BYTE_LEN);
        assert!(graph_bytes.len() >= phoenix_types::GraphDeltaResultHeader::BYTE_LEN);
        assert!(state_bytes.len() >= SessionStateResultHeader::BYTE_LEN);
        assert!(stats_bytes.len() >= SessionStatsResultHeader::BYTE_LEN);
    }

    #[test]
    fn runtime_scan_and_structure_roundtrip() {
        let runtime = native_test_runtime();
        let scan = runtime.scan_text(ScanRequest {
            text: "Luffy attacked Zoro.".to_owned(),
            scope: ScopeKey::default(),
            session_id: Some(SessionId("scan-1".to_owned())),
            resolver_seed: vec![
                phoenix_types::ResolverEntitySeed {
                    entity_id: EntityId("luffy".to_owned()),
                    canonical_name: "Luffy".to_owned(),
                    aliases: Vec::new(),
                    kind: Some(EntityKind::Character),
                    gender: Some(GenderHint::Male),
                    number: None,
                    scope: ScopeKey::default(),
                },
                phoenix_types::ResolverEntitySeed {
                    entity_id: EntityId("zoro".to_owned()),
                    canonical_name: "Zoro".to_owned(),
                    aliases: Vec::new(),
                    kind: Some(EntityKind::Character),
                    gender: Some(GenderHint::Male),
                    number: None,
                    scope: ScopeKey::default(),
                },
            ],
        });
        assert_eq!(scan.mentions.len(), 2);
        assert!(scan.mentions.iter().any(|mention| mention.entity_ref
            == Some(MentionEntityRef::Known(EntityId("luffy".to_owned())))));

        let structure = runtime.build_structure(StructureRequest {
            text: "Luffy attacked Zoro.".to_owned(),
            scan,
        });
        assert_eq!(structure.sentence_frames.len(), 1);
        assert_eq!(structure.sentence_frames[0].verb_frames.len(), 1);
    }

    #[test]
    fn entity_cards_and_folder_schema_persist() {
        let runtime = native_test_runtime();

        runtime
            .upsert_entity_cards_batch(&[
                phoenix_types::EntityCard {
                    entity_id: EntityId("CHARACTER".to_owned()),
                    card_id: "summary".to_owned(),
                    name: "Summary".to_owned(),
                    color: "#ff8800".to_owned(),
                    icon: "spark".to_owned(),
                    display_order: 2,
                    is_collapsed: false,
                    created_at: 10,
                    updated_at: 10,
                },
                phoenix_types::EntityCard {
                    entity_id: EntityId("CHARACTER".to_owned()),
                    card_id: "traits".to_owned(),
                    name: "Traits".to_owned(),
                    color: "#00aaff".to_owned(),
                    icon: "bolt".to_owned(),
                    display_order: 1,
                    is_collapsed: true,
                    created_at: 11,
                    updated_at: 11,
                },
            ])
            .expect("cards");
        runtime
            .upsert_entity_cards_batch(&[phoenix_types::EntityCard {
                entity_id: EntityId("CHARACTER".to_owned()),
                card_id: "traits".to_owned(),
                name: "Updated Traits".to_owned(),
                color: "#00aaff".to_owned(),
                icon: "bolt".to_owned(),
                display_order: 1,
                is_collapsed: true,
                created_at: 11,
                updated_at: 12,
            }])
            .expect("update one card");

        runtime
            .upsert_folder_schema(&phoenix_types::FolderSchema {
                id: "schema-character".to_owned(),
                entity_kind: "character".to_owned(),
                subtype: "crew".to_owned(),
                name: "Character Vault".to_owned(),
                description: "Stores character notes.".to_owned(),
                allowed_subfolders: "[\"profiles\",\"chapters\"]".to_owned(),
                allowed_note_types: "[\"bio\",\"scene\"]".to_owned(),
                is_vault_root: true,
                container_only: false,
                propagate_kind_to_children: true,
                icon: "user".to_owned(),
                is_system: false,
                created_at: 20,
                updated_at: 21,
            })
            .expect("schema");

        let cards = runtime
            .get_entity_cards(&EntityId("CHARACTER".to_owned()))
            .expect("entity cards");
        let schema = runtime
            .get_folder_schema("schema-character")
            .expect("folder schema")
            .expect("folder schema present");

        assert_eq!(cards.len(), 2);
        assert_eq!(cards[0].card_id, "traits");
        assert_eq!(cards[0].name, "Updated Traits");
        assert_eq!(schema.allowed_subfolders, "[\"profiles\",\"chapters\"]");
        assert_eq!(schema.allowed_note_types, "[\"bio\",\"scene\"]");
    }

    #[test]
    fn saved_network_view_replaces_members_and_relationships() {
        let runtime = native_test_runtime();

        runtime
            .save_network_view(&phoenix_types::SavedNetworkView {
                instance: phoenix_types::NetworkInstance {
                    id: "net-1".to_owned(),
                    name: "Crew".to_owned(),
                    schema_id: "schema-character".to_owned(),
                    network_kind: "mindmap".to_owned(),
                    network_subtype: "entity".to_owned(),
                    root_folder_id: "folder-1".to_owned(),
                    root_entity_id: String::new(),
                    namespace: "world".to_owned(),
                    description: "Crew graph".to_owned(),
                    tags: vec!["crew".to_owned(), "battle".to_owned()],
                    member_count: 2,
                    relationship_count: 1,
                    max_depth: 2,
                    created_at: 100,
                    updated_at: 100,
                    group_id: String::new(),
                    scope_type: "folder".to_owned(),
                    narrative_id: "nar-1".to_owned(),
                },
                members: vec![
                    phoenix_types::NetworkMembership {
                        network_id: "net-1".to_owned(),
                        entity_id: EntityId("luffy".to_owned()),
                        x: 10.0,
                        y: 20.0,
                        fixed: true,
                    },
                    phoenix_types::NetworkMembership {
                        network_id: "net-1".to_owned(),
                        entity_id: EntityId("zoro".to_owned()),
                        x: 30.0,
                        y: 40.0,
                        fixed: false,
                    },
                ],
                relationships: vec![phoenix_types::NetworkRelationship {
                    network_id: "net-1".to_owned(),
                    source_entity_id: EntityId("luffy".to_owned()),
                    target_entity_id: EntityId("zoro".to_owned()),
                    relationship_id: "edge-1".to_owned(),
                }],
            })
            .expect("initial save");

        runtime
            .save_network_view(&phoenix_types::SavedNetworkView {
                instance: phoenix_types::NetworkInstance {
                    id: "net-1".to_owned(),
                    name: "Crew Revised".to_owned(),
                    schema_id: "schema-character".to_owned(),
                    network_kind: "mindmap".to_owned(),
                    network_subtype: "entity".to_owned(),
                    root_folder_id: "folder-1".to_owned(),
                    root_entity_id: String::new(),
                    namespace: "world".to_owned(),
                    description: "Crew graph revised".to_owned(),
                    tags: vec!["crew".to_owned()],
                    member_count: 1,
                    relationship_count: 0,
                    max_depth: 1,
                    created_at: 100,
                    updated_at: 200,
                    group_id: String::new(),
                    scope_type: "folder".to_owned(),
                    narrative_id: "nar-1".to_owned(),
                },
                members: vec![phoenix_types::NetworkMembership {
                    network_id: "net-1".to_owned(),
                    entity_id: EntityId("luffy".to_owned()),
                    x: 12.0,
                    y: 24.0,
                    fixed: false,
                }],
                relationships: Vec::new(),
            })
            .expect("replacement save");

        let view = runtime
            .get_network_view("net-1")
            .expect("network fetch")
            .expect("network exists");
        let listed = runtime.list_network_views().expect("network list");

        assert_eq!(view.instance.name, "Crew Revised");
        assert_eq!(view.members.len(), 1);
        assert_eq!(view.members[0].entity_id.0, "luffy");
        assert!(view.relationships.is_empty());
        assert_eq!(listed.len(), 1);

        runtime
            .delete_network_view("net-1")
            .expect("delete network");
        assert!(runtime
            .get_network_view("net-1")
            .expect("network fetch after delete")
            .is_none());
    }

    #[test]
    fn persistence_batch_replays_content_mutations_in_order() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");

        let result = runtime
            .store_command(StoreCommandRequest {
                command: "persistence:applyWalBatch".to_owned(),
                payload: json!({
                    "records": [
                        {
                            "seq": 1,
                            "command": "note:upsert",
                            "partition": "content",
                            "writtenAt": 100,
                            "payload": {
                                "row": {
                                    "id": "note-1",
                                    "version": 1,
                                    "world_id": "world-1",
                                    "title": "Alpha",
                                    "content": "Hello",
                                    "markdown_content": "Hello",
                                    "folder_id": null,
                                    "entity_kind": null,
                                    "entity_subtype": null,
                                    "is_entity": false,
                                    "is_pinned": false,
                                    "favorite": false,
                                    "owner_id": null,
                                    "narrative_id": null,
                                    "order": 0,
                                    "created_at": 10,
                                    "updated_at": 10,
                                    "valid_from": 10,
                                    "valid_to": null,
                                    "is_current": true,
                                    "change_reason": null
                                }
                            }
                        },
                        {
                            "seq": 2,
                            "command": "relation:upsert",
                            "partition": "content",
                            "writtenAt": 101,
                            "payload": {
                                "relation": "entities",
                                "row": {
                                    "id": "entity-1",
                                    "label": "Hero",
                                    "kind": "character",
                                    "subtype": null,
                                    "aliases": [],
                                    "first_note": "note-1",
                                    "total_mentions": 1,
                                    "narrative_id": null,
                                    "created_by": "user",
                                    "created_at": 10,
                                    "updated_at": 10
                                }
                            }
                        }
                    ]
                }),
            })
            .expect("wal batch");

        assert!(result.success);
        let note = runtime.get_note_value("note-1", true).expect("note");
        let entity = runtime
            .fetch_relation_rows("entities")
            .expect("entities")
            .into_iter()
            .find(|row| row.get("id").and_then(Value::as_str) == Some("entity-1"));

        assert_eq!(
            note.and_then(|value| value
                .get("title")
                .and_then(Value::as_str)
                .map(str::to_owned)),
            Some("Alpha".to_owned())
        );
        assert!(entity.is_some());
        assert!(runtime.lex.borrow().is_some());
    }

    #[test]
    fn scoped_document_wal_replay_does_not_rebuild_lex_index() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        assert!(runtime.lex.borrow().is_none());

        let result = runtime
            .store_command(StoreCommandRequest {
                command: "persistence:applyWalBatch".to_owned(),
                payload: json!({
                    "records": [
                        {
                            "seq": 1,
                            "command": "relation:upsert",
                            "partition": "content",
                            "writtenAt": 100,
                            "payload": {
                                "relation": "scoped_documents",
                                "row": {
                                    "id": "phoenix.graph.rebuild:scope:latest",
                                    "scope_folder_id": "scope",
                                    "narrative_id": "",
                                    "namespace": "phoenix.graph.rebuild",
                                    "document_key": "latest",
                                    "payload": "{\"ok\":true}",
                                    "created_at": 100,
                                    "updated_at": 100
                                }
                            }
                        }
                    ]
                }),
            })
            .expect("scoped document wal batch");

        assert!(result.success);
        assert!(runtime.lex.borrow().is_none());
        let rows = runtime
            .fetch_relation_rows("scoped_documents")
            .expect("scoped documents");
        assert_eq!(rows.len(), 1);
    }

    #[test]
    fn persistence_clear_derived_keeps_content_rows() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");

        runtime
            .put_relation_row(
                "notes",
                json!({
                    "id": "note-keep",
                    "version": 1,
                    "world_id": "world-1",
                    "title": "Keep",
                    "content": "persist",
                    "markdown_content": "persist",
                    "folder_id": null,
                    "entity_kind": null,
                    "entity_subtype": null,
                    "is_entity": false,
                    "is_pinned": false,
                    "favorite": false,
                    "owner_id": null,
                    "narrative_id": null,
                    "order": 0,
                    "created_at": 10,
                    "updated_at": 10,
                    "valid_from": 10,
                    "valid_to": null,
                    "is_current": true,
                    "change_reason": null
                }),
            )
            .expect("note row");
        runtime
            .put_relation_row(
                "phoenix_sessions",
                json!({
                    "session_id": "session-1",
                    "label": "Derived",
                    "world_id": null,
                    "narrative_id": null,
                    "folder_id": null,
                    "folder_path": null,
                    "status": "active",
                    "revision": 0,
                    "created_at": 1,
                    "updated_at": 1
                }),
            )
            .expect("session row");

        runtime
            .store_command(StoreCommandRequest {
                command: "persistence:clearDerived".to_owned(),
                payload: json!({}),
            })
            .expect("clear derived");

        assert!(runtime
            .fetch_relation_rows("phoenix_sessions")
            .expect("derived rows")
            .is_empty());
        assert_eq!(
            runtime
                .get_note_value("note-keep", true)
                .expect("note")
                .is_some(),
            true
        );
    }

    #[test]
    fn session_close_drops_session_and_session_logs() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: Some(SessionId("session-close".to_owned())),
                label: "Closable".to_owned(),
                scope: Default::default(),
            })
            .expect("session");

        runtime
            .put_relation_row(
                "phoenix_ingest_log",
                json!({
                    "id": "ingest-1",
                    "session_id": session.session_id.0,
                    "document_count": 1,
                    "commit_requested": false,
                    "request_json": {"sessionId": session.session_id.0},
                    "created_at": 1
                }),
            )
            .expect("ingest log");
        runtime
            .put_relation_row(
                "phoenix_query_log",
                json!({
                    "id": "query-1",
                    "session_id": session.session_id.0,
                    "query": "kai",
                    "limit": 10,
                    "request_json": {"sessionId": session.session_id.0},
                    "created_at": 1
                }),
            )
            .expect("query log");

        let result = runtime
            .store_command(StoreCommandRequest {
                command: "session:close".to_owned(),
                payload: json!({ "sessionId": session.session_id.0 }),
            })
            .expect("close session");

        assert_eq!(result.success, true);
        assert!(runtime
            .fetch_relation_rows("phoenix_sessions")
            .expect("sessions")
            .is_empty());
        assert!(runtime
            .fetch_relation_rows("phoenix_ingest_log")
            .expect("ingest logs")
            .is_empty());
        assert!(runtime
            .fetch_relation_rows("phoenix_query_log")
            .expect("query logs")
            .is_empty());
    }

    #[test]
    fn planner_disabled_runs_stay_ready_to_answer() {
        let runtime = chat_runtime();
        let thread = runtime
            .chat
            .create_thread(
                runtime.chat_store().expect("chat store"),
                Some("world-1"),
                Some("nar-1"),
                Some("Thread"),
            )
            .expect("thread");
        runtime
            .chat
            .add_message(
                runtime.chat_store().expect("chat store"),
                &thread.id.0,
                "user",
                "Summarize the scoped notes.",
                Some("nar-1"),
            )
            .expect("message");

        let run = runtime
            .chat
            .start_run(
                runtime.chat_store().expect("chat store"),
                &thread.id.0,
                "Summarize the scoped notes.",
                run_options("nar-1", false, false),
            )
            .expect("run");

        assert_eq!(run.status, ChatRunStatus::ReadyToAnswer);

        let snapshot = runtime
            .chat
            .poll_run(runtime.chat_store().expect("chat store"), &run.id)
            .expect("snapshot")
            .expect("run snapshot");
        assert_eq!(snapshot.run.status, ChatRunStatus::ReadyToAnswer);
        assert!(snapshot.planner_step.is_none());
        assert!(snapshot.artifacts.is_empty());
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn planner_run_executes_tools_and_promotes_scoped_artifacts() {
        let runtime = chat_runtime();
        let thread = runtime
            .chat
            .create_thread(
                runtime.chat_store().expect("chat store"),
                Some("world-1"),
                Some("nar-1"),
                Some("Thread"),
            )
            .expect("thread");
        runtime
            .chat
            .add_message(
                runtime.chat_store().expect("chat store"),
                &thread.id.0,
                "user",
                "Find the in-scope note and prepare a grounded answer.",
                Some("nar-1"),
            )
            .expect("message");

        insert_note(
            &runtime,
            "note-in",
            "nar-1",
            "Inside scope",
            "Ryan waited at the harbor.",
        );
        insert_note(
            &runtime,
            "note-out",
            "nar-2",
            "Outside scope",
            "This note should never be surfaced.",
        );

        let run = runtime
            .chat
            .start_run(
                runtime.chat_store().expect("chat store"),
                &thread.id.0,
                "Find the in-scope note and prepare a grounded answer.",
                run_options("nar-1", true, false),
            )
            .expect("run");
        assert_eq!(run.status, ChatRunStatus::Planning);
        let run_id = run.id.clone();

        let step =
            planner_step_command(&runtime, "chat:getPlannerStep", json!({ "runId": run_id }));
        let request = match step {
            ChatPlannerStep::ModelRequest { request } => request,
            other => panic!("expected initial model request, got {other:?}"),
        };
        assert!(request.allow_tools);

        let tool_step = planner_step_from_payload(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:submitPlannerModelResponse".to_owned(),
                    payload: json!({
                        "runId": run_id,
                        "response": ChatPlannerModelResponse {
                            content: String::new(),
                            tool_calls: vec![
                                phoenix_types::ChatPlannerToolCall {
                                    id: "tool-note-list".to_owned(),
                                    name: "note_list".to_owned(),
                                    arguments_json: r#"{"limit":10}"#.to_owned(),
                                },
                                phoenix_types::ChatPlannerToolCall {
                                    id: "tool-artifact-put".to_owned(),
                                    name: "artifact_put".to_owned(),
                                    arguments_json: r#"{"kind":"claim_list","payload":{"claim":"Ryan waited at the harbor."},"pinned":false}"#.to_owned(),
                                },
                            ],
                        },
                    }),
                })
                .expect("submit planner response")
                .payload
                .expect("tool step payload"),
        );

        match tool_step {
            ChatPlannerStep::ToolCalls { tool_calls, .. } => assert_eq!(tool_calls.len(), 2),
            other => panic!("expected tool calls step, got {other:?}"),
        }

        let step_after_tools = planner_step_command(
            &runtime,
            "chat:advancePlannerRun",
            json!({ "runId": run_id }),
        );
        let request_after_tools = match step_after_tools {
            ChatPlannerStep::ModelRequest { request } => request,
            other => panic!("expected follow-up model request, got {other:?}"),
        };
        let note_list_message = request_after_tools
            .messages
            .iter()
            .find(|message| message.tool_call_id.as_deref() == Some("tool-note-list"))
            .expect("note_list tool message");
        let note_list_payload: Value =
            serde_json::from_str(&note_list_message.content).expect("note list payload");
        let note_ids = note_list_payload
            .get("notes")
            .and_then(Value::as_array)
            .expect("notes array")
            .iter()
            .filter_map(|note| note.get("id").and_then(Value::as_str))
            .collect::<Vec<_>>();
        assert_eq!(note_ids, vec!["note-in"]);

        let complete_step = planner_step_from_payload(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:submitPlannerModelResponse".to_owned(),
                    payload: json!({
                        "runId": run_id,
                        "response": ChatPlannerModelResponse {
                            content: "Ground the answer in note-in and the saved claims.".to_owned(),
                            tool_calls: Vec::new(),
                        },
                    }),
                })
                .expect("submit planner summary")
                .payload
                .expect("complete payload"),
        );
        match complete_step {
            ChatPlannerStep::Complete { response, .. } => {
                assert_eq!(
                    response,
                    "Ground the answer in note-in and the saved claims."
                )
            }
            other => panic!("expected planner completion, got {other:?}"),
        }

        let snapshot: ChatRunSnapshot = serde_json::from_value(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:pollRun".to_owned(),
                    payload: json!({ "runId": run_id }),
                })
                .expect("poll run")
                .payload
                .expect("snapshot payload"),
        )
        .expect("snapshot");
        assert_eq!(snapshot.run.status, ChatRunStatus::ReadyToAnswer);
        assert!(snapshot
            .run
            .prepared_system_prompt
            .contains("Ground the answer in note-in and the saved claims."));
        assert!(snapshot.planner_step.is_none());
        assert!(snapshot
            .artifacts
            .iter()
            .any(|artifact| artifact.kind == "draft_answer" && artifact.pinned));
        let claim_artifact = snapshot
            .artifacts
            .iter()
            .find(|artifact| artifact.kind == "claim_list")
            .cloned()
            .expect("claim_list artifact");
        assert!(!claim_artifact.pinned);

        let artifacts: Vec<ChatWorkspaceArtifact> = serde_json::from_value(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:listPlannerArtifacts".to_owned(),
                    payload: json!({ "runId": run_id }),
                })
                .expect("list artifacts")
                .payload
                .expect("artifacts payload"),
        )
        .expect("artifacts");
        assert!(artifacts
            .iter()
            .any(|artifact| artifact.key == claim_artifact.key));

        let pinned: ChatWorkspaceArtifact = serde_json::from_value(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:pinPlannerArtifact".to_owned(),
                    payload: json!({
                        "runId": run_id,
                        "key": claim_artifact.key,
                        "pinned": true,
                    }),
                })
                .expect("pin artifact")
                .payload
                .expect("pin payload"),
        )
        .expect("pinned artifact");
        assert!(pinned.pinned);
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn planner_canvas_tools_pause_for_ts_host_and_resume_after_approval() {
        let runtime = chat_runtime();
        let thread = runtime
            .chat
            .create_thread(
                runtime.chat_store().expect("chat store"),
                Some("world-1"),
                Some("nar-1"),
                Some("Thread"),
            )
            .expect("thread");
        runtime
            .chat
            .add_message(
                runtime.chat_store().expect("chat store"),
                &thread.id.0,
                "user",
                "Rewrite the highlighted paragraph in the open note.",
                Some("nar-1"),
            )
            .expect("message");

        let run = runtime
            .chat
            .start_run(
                runtime.chat_store().expect("chat store"),
                &thread.id.0,
                "Rewrite the highlighted paragraph in the open note.",
                run_options("nar-1", true, true),
            )
            .expect("run");
        let run_id = run.id.clone();

        let initial_step =
            planner_step_command(&runtime, "chat:getPlannerStep", json!({ "runId": run_id }));
        let initial_request = match initial_step {
            ChatPlannerStep::ModelRequest { request } => request,
            other => panic!("expected initial model request, got {other:?}"),
        };
        assert!(initial_request
            .tools
            .iter()
            .any(|tool| tool.name == "get_active_note_snapshot"));
        assert!(initial_request
            .tools
            .iter()
            .any(|tool| tool.name == "replace_text_proposal"));

        let tool_step = planner_step_from_payload(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:submitPlannerModelResponse".to_owned(),
                    payload: json!({
                        "runId": run_id,
                        "response": ChatPlannerModelResponse {
                            content: String::new(),
                            tool_calls: vec![
                                phoenix_types::ChatPlannerToolCall {
                                    id: "tool-note-snapshot".to_owned(),
                                    name: "get_active_note_snapshot".to_owned(),
                                    arguments_json: "{}".to_owned(),
                                },
                                phoenix_types::ChatPlannerToolCall {
                                    id: "tool-highlight".to_owned(),
                                    name: "highlight_range".to_owned(),
                                    arguments_json: r#"{"from":12,"to":48}"#.to_owned(),
                                },
                                phoenix_types::ChatPlannerToolCall {
                                    id: "tool-replace".to_owned(),
                                    name: "replace_text_proposal".to_owned(),
                                    arguments_json: r#"{"from":12,"to":48,"replacement":"Rewritten paragraph.","expectedRevision":42}"#.to_owned(),
                                },
                            ],
                        },
                    }),
                })
                .expect("submit planner response")
                .payload
                .expect("tool step payload"),
        );
        match tool_step {
            ChatPlannerStep::ToolCalls { tool_calls, .. } => assert_eq!(tool_calls.len(), 3),
            other => panic!("expected tool calls step, got {other:?}"),
        }

        let after_advance = runtime
            .store_command(StoreCommandRequest {
                command: "chat:advancePlannerRun".to_owned(),
                payload: json!({ "runId": run_id }),
            })
            .expect("advance planner run");
        assert!(after_advance.payload.is_none());

        let awaiting_host: ChatRunSnapshot = serde_json::from_value(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:pollRun".to_owned(),
                    payload: json!({ "runId": run_id }),
                })
                .expect("poll awaiting host")
                .payload
                .expect("awaiting host payload"),
        )
        .expect("awaiting host snapshot");
        assert_eq!(awaiting_host.run.status, ChatRunStatus::AwaitingToolHost);
        assert_eq!(awaiting_host.tool_calls.len(), 3);
        assert!(awaiting_host
            .tool_calls
            .iter()
            .all(|call| call.host == "typescript" && call.status == "pending_host"));

        let after_tools: ChatRunSnapshot = serde_json::from_value(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:submitToolResults".to_owned(),
                    payload: json!({
                        "runId": run_id,
                        "results": [
                            {
                                "toolCallId": "tool-note-snapshot",
                                "resultJson": "{\"noteId\":\"note-1\",\"revision\":42,\"text\":\"Original paragraph.\"}"
                            },
                            {
                                "toolCallId": "tool-highlight",
                                "resultJson": "{\"ok\":true}"
                            },
                            {
                                "toolCallId": "tool-replace",
                                "proposal": {
                                    "proposalId": "approval-1",
                                    "toolName": "replace_text_proposal",
                                    "affectedNoteId": "note-1",
                                    "summary": "Replace the highlighted paragraph",
                                    "diffPreview": "Replace the highlighted paragraph with a tighter rewrite.",
                                    "expectedRevision": 42,
                                    "rollbackToken": "note-1:42",
                                    "payloadJson": "{\"kind\":\"replace_text\",\"from\":12,\"to\":48,\"replacement\":\"Rewritten paragraph.\",\"expectedRevision\":42}"
                                }
                            }
                        ]
                    }),
                })
                .expect("submit tool results")
                .payload
                .expect("tool results payload"),
        )
        .expect("after tools snapshot");
        assert_eq!(after_tools.run.status, ChatRunStatus::AwaitingApproval);
        assert_eq!(after_tools.approvals.len(), 1);
        assert!(after_tools
            .tool_calls
            .iter()
            .any(|call| call.tool_call_id == "tool-replace" && call.status == "awaiting_approval"));

        let approval_id = after_tools.approvals[0].id.clone();
        let after_approval: ChatRunSnapshot = serde_json::from_value(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:submitApproval".to_owned(),
                    payload: json!({
                        "runId": run_id,
                        "approvalId": approval_id,
                        "approved": true,
                        "decisionJson": "{\"approved\":true,\"applied\":true,\"autoApplied\":false}"
                    }),
                })
                .expect("submit approval")
                .payload
                .expect("approval payload"),
        )
        .expect("after approval snapshot");
        assert_eq!(after_approval.run.status, ChatRunStatus::Planning);

        let resumed_step =
            planner_step_command(&runtime, "chat:getPlannerStep", json!({ "runId": run_id }));
        let resumed_request = match resumed_step {
            ChatPlannerStep::ModelRequest { request } => request,
            other => panic!("expected resumed model request, got {other:?}"),
        };
        assert!(resumed_request
            .messages
            .iter()
            .any(|message| message.tool_call_id.as_deref() == Some("tool-note-snapshot")));
        assert!(resumed_request
            .messages
            .iter()
            .any(|message| message.tool_call_id.as_deref() == Some("tool-replace")));

        let complete_step = planner_step_from_payload(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:submitPlannerModelResponse".to_owned(),
                    payload: json!({
                        "runId": run_id,
                        "response": ChatPlannerModelResponse {
                            content: "The active note edit has been planned and approved.".to_owned(),
                            tool_calls: Vec::new(),
                        },
                    }),
                })
                .expect("submit final planner response")
                .payload
                .expect("final planner payload"),
        );
        match complete_step {
            ChatPlannerStep::Complete { response, .. } => {
                assert_eq!(
                    response,
                    "The active note edit has been planned and approved."
                )
            }
            other => panic!("expected completion after approval, got {other:?}"),
        }

        let final_snapshot: ChatRunSnapshot = serde_json::from_value(
            runtime
                .store_command(StoreCommandRequest {
                    command: "chat:pollRun".to_owned(),
                    payload: json!({ "runId": run_id }),
                })
                .expect("poll final snapshot")
                .payload
                .expect("final snapshot payload"),
        )
        .expect("final snapshot");
        assert_eq!(final_snapshot.run.status, ChatRunStatus::ReadyToAnswer);
    }

    #[test]
    fn runtime_text_analytics_matches_gokitt_shape() {
        let runtime = native_test_runtime();
        let analytics = runtime.analyze_text(
            "The iron gate slammed shut. The iron gate rattled again. The iron gate shook against the wall. \
Bright embers glowed beside the ember-lit grate. Bright embers hissed in the ash.",
        );

        assert!(analytics.word_count > 0);
        assert!(!analytics.repetition.items.is_empty());
        assert!(!analytics.proximity.items.is_empty());
        assert_eq!(analytics.cadence.sentences.len(), 5);
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn fixture_structure_relations_match_expected_baselines() {
        let runtime = PhoenixRuntime::new(RuntimeConfig {
            target: RuntimeTarget::Wasm,
            ..RuntimeConfig::default()
        })
        .expect("runtime");
        let manifest = load_fixture_manifest();

        for fixture in &manifest.fixtures {
            let text = fixture_body(fixture);
            let scan = runtime.scan_text(ScanRequest {
                text: text.clone(),
                scope: ScopeKey::default(),
                session_id: Some(SessionId(format!("fixture-{}", fixture.id))),
                resolver_seed: fixture_resolver_seed(&fixture.id),
            });
            let structure = runtime.build_structure(StructureRequest { text, scan });
            let normalized = normalize_structure_relations(&structure);
            let baseline = load_expected_baseline(&fixture.id);
            assert_eq!(
                baseline.expected_structure,
                Some(normalized),
                "fixture {} structure relations drifted",
                fixture.id
            );
        }
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn fixture_resolver_seed(fixture_id: &str) -> Vec<phoenix_types::ResolverEntitySeed> {
        match fixture_id {
            "shortrun-opening" => vec![
                fixture_seed("ryan", "Ryan", EntityKind::Character),
                fixture_seed("bakuto", "Bakuto", EntityKind::Faction),
            ],
            "perfect-run-dialogue" => vec![
                fixture_seed("ryan", "Ryan", EntityKind::Character),
                fixture_seed("zanbato", "Zanbato", EntityKind::Character),
                fixture_seed("ghoul", "Ghoul", EntityKind::Character),
                fixture_seed("augusti", "Augusti", EntityKind::Organization),
                fixture_seed("meta_gang", "Meta-Gang", EntityKind::Faction),
                fixture_seed("len", "Len", EntityKind::Character),
            ],
            _ => Vec::new(),
        }
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn fixture_seed(
        id: &str,
        canonical_name: &str,
        kind: EntityKind,
    ) -> phoenix_types::ResolverEntitySeed {
        phoenix_types::ResolverEntitySeed {
            entity_id: EntityId(id.to_owned()),
            canonical_name: canonical_name.to_owned(),
            aliases: Vec::new(),
            kind: Some(kind),
            gender: Some(GenderHint::Unknown),
            number: None,
            scope: ScopeKey::default(),
        }
    }

    fn semantic_test_vector(primary_index: usize) -> Vec<f32> {
        let mut values = vec![0.0; SEMANTIC_VECTOR_DIM];
        if primary_index < values.len() {
            values[primary_index] = 1.0;
        }
        values
    }

    fn chat_runtime() -> PhoenixRuntime {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        runtime
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn wasm_runtime() -> PhoenixRuntime {
        let runtime = PhoenixRuntime::new(RuntimeConfig {
            target: RuntimeTarget::Wasm,
            ..RuntimeConfig::default()
        })
        .expect("runtime");
        runtime.init().expect("init");
        runtime
    }

    #[cfg(all(not(target_arch = "wasm32"), feature = "legacy-cozo-graph"))]
    #[test]
    fn wasm_runtime_binds_overgraph_lane_and_syncs_graptor_rows() {
        let runtime = PhoenixRuntime::new(RuntimeConfig {
            target: RuntimeTarget::Wasm,
            ..RuntimeConfig::default()
        })
        .expect("runtime");
        let init = runtime.init().expect("init");
        assert!(init
            .diagnostics
            .iter()
            .any(|diag| diag.code == "PX_OVERGRAPH_BOUND"));

        let status = runtime
            .store_command(StoreCommandRequest {
                command: "graph:overgraphStatus".to_owned(),
                payload: json!({}),
            })
            .expect("overgraph status");
        assert_eq!(
            status
                .payload
                .as_ref()
                .and_then(|payload| payload.get("bound"))
                .and_then(Value::as_bool),
            Some(true)
        );

        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "OverGraph lane".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");
        let ingest = runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-overgraph-lane".to_owned()),
                    note_id: None,
                    title: "OverGraph Lane".to_owned(),
                    text: "Ryan mapped the harbor before dawn. Len marked the same harbor path."
                        .to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: true,
            })
            .expect("ingest");
        assert!(ingest
            .diagnostics
            .iter()
            .any(|diag| diag.code == "PX_OVERGRAPH_SYNC"));

        let rebuild = runtime.rebuild(RebuildRequest::default()).expect("rebuild");
        assert!(rebuild
            .diagnostics
            .iter()
            .any(|diag| diag.code == "PX_OVERGRAPH_SYNC"));

        runtime
            .store_command(StoreCommandRequest {
                command: "graph:upsertNode".to_owned(),
                payload: json!({
                    "id": "custom-overgraph-node",
                    "kind": "custom",
                    "label": "Custom OverGraph Node",
                }),
            })
            .expect("graph node upsert");
        runtime
            .store_command(StoreCommandRequest {
                command: "graph:upsertEdge".to_owned(),
                payload: json!({
                    "source": "custom-overgraph-node",
                    "target": "custom-overgraph-node",
                    "edgeType": "self",
                }),
            })
            .expect("graph edge upsert");
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn wasm_query_stays_on_gldr_diagnostics() {
        let runtime = wasm_runtime();
        let session = runtime
            .create_session(CreateSessionRequest {
                session_id: None,
                label: "Wasm query".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("session");

        runtime
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![phoenix_types::IngestDocument {
                    document_id: DocumentId("doc-wasm-query".to_owned()),
                    note_id: None,
                    title: "Harbor".to_owned(),
                    text: "Ryan mapped the harbor before dawn.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: false,
            })
            .expect("ingest");

        let result = runtime
            .query(QueryRequest {
                session_id: Some(session.session_id.clone()),
                query: "Ryan".to_owned(),
                scope: ScopeKey::default(),
                targets: vec![QueryTarget::Graph],
                limit: Some(5),
                temporal: None,
                semantic_query_vector: None,
                include_candidate_graph: true,
            })
            .expect("query");

        assert!(result
            .diagnostics
            .iter()
            .any(|diag| diag.code == "PX_GLDR_OK"));
        assert!(!result
            .diagnostics
            .iter()
            .any(|diag| diag.code == "PX_TRIVERSE_OK"));
    }

    fn run_options(
        narrative_id: &str,
        planner_enabled: bool,
        mutations_enabled: bool,
    ) -> RunOptions {
        RunOptions {
            final_provider: "openrouter".to_owned(),
            final_model: "meta-llama/llama-3.3-70b-instruct:free".to_owned(),
            planner_model: Some("meta-llama/llama-3.3-70b-instruct:free".to_owned()),
            om_model: None,
            planner_enabled,
            om_enabled: false,
            workspace_enabled: planner_enabled,
            mutations_enabled,
            deadline_ms: 8_000,
            mutation_policy: "confirm".to_owned(),
            narrative_id: Some(narrative_id.to_owned()),
            folder_id: None,
            scope_id: Some(narrative_id.to_owned()),
            base_system_prompt: Some("You are Kammi.".to_owned()),
            initial_external_context: None,
        }
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn insert_note(
        runtime: &PhoenixRuntime,
        note_id: &str,
        narrative_id: &str,
        title: &str,
        content: &str,
    ) {
        runtime
            .put_relation_row(
                "notes",
                json!({
                    "id": note_id,
                    "version": 1,
                    "world_id": "world-1",
                    "title": title,
                    "content": content,
                    "markdown_content": content,
                    "folder_id": null,
                    "entity_kind": null,
                    "entity_subtype": null,
                    "is_entity": false,
                    "is_pinned": false,
                    "favorite": false,
                    "owner_id": null,
                    "narrative_id": narrative_id,
                    "order": 0,
                    "created_at": 10,
                    "updated_at": 10,
                    "valid_from": 10,
                    "valid_to": null,
                    "is_current": true,
                    "change_reason": null
                }),
            )
            .expect("note row");
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn planner_step_command(
        runtime: &PhoenixRuntime,
        command: &str,
        payload: Value,
    ) -> ChatPlannerStep {
        planner_step_from_payload(
            runtime
                .store_command(StoreCommandRequest {
                    command: command.to_owned(),
                    payload,
                })
                .expect("planner command")
                .payload
                .expect("planner payload"),
        )
    }

    #[cfg(feature = "legacy-cozo-graph")]
    #[test]
    fn native_rebuild_preserves_kernel_checkpoint_temporal_payloads() {
        let runtime = native_test_runtime();
        runtime.init().expect("init");
        let snapshot = KernelGraphSnapshot {
            vertices: vec![KernelVertex {
                id: KernelVertexId("entity::dock".to_owned()),
                kind: "entity".to_owned(),
                class: KernelVertexClass::Entity,
                value: json!({"name":"Dock Authority"}),
                attributes: json!({}),
                temporal: KernelBiTemporal {
                    valid_from: Some(10),
                    valid_to: Some(30),
                    recorded_at: Some(20),
                    expired_at: None,
                },
                entity_id: Some("dock-authority".to_owned()),
                entity_facet: Some(KernelEntityFacet {
                    canonical_entity_id: Some("dock-authority".to_owned()),
                    surface: Some("Dock Authority".to_owned()),
                    entity_kind: Some("organization".to_owned()),
                }),
                ..KernelVertex::default()
            }],
            asserted_edges: Vec::new(),
            candidate_edges: Vec::new(),
        };
        runtime
            .native_row_store()
            .expect("row store")
            .replace_relation_rows(
                "graph_vertices",
                &snapshot
                    .vertices
                    .iter()
                    .map(kernel_vertex_to_row_value)
                    .collect::<Vec<_>>(),
            )
            .expect("write vertices");
        runtime.native_runtime.deterministic_kernel.invalidate();
        runtime
            .native_runtime
            .deterministic_kernel
            .set_rebuild_token(None);
        runtime
            .rebuild_native_graph("graph:test:checkpoint".to_owned())
            .expect("rebuild native graph");
        let view = runtime
            .native_runtime
            .deterministic_kernel
            .view_as_of(KernelViewRequest {
                valid_at: None,
                recorded_at: None,
                include_candidate_graph: false,
            });
        assert_eq!(view.vertices.len(), 1);
        assert_eq!(view.vertices[0].value["name"], "Dock Authority");
        assert_eq!(view.vertices[0].temporal.recorded_at, Some(20));
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn planner_step_from_payload(payload: Value) -> ChatPlannerStep {
        serde_json::from_value(payload).expect("planner step")
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn normalize_structure_relations(structure: &StructureArtifact) -> Value {
        json!({
            "relations": structure.relations.iter().map(|relation| {
                json!({
                    "sentenceIndex": relation.sentence_index,
                    "lemma": relation.lemma,
                    "eventClass": relation.event_class,
                    "relationType": relation.relation_type,
                    "subjectEntity": frame_slot_entity_id(relation.subject.as_ref()),
                    "objectEntity": frame_slot_entity_id(relation.object.as_ref()),
                    "recipientEntity": frame_slot_entity_id(relation.recipient.as_ref()),
                    "subjectRange": frame_slot_range(relation.subject.as_ref()),
                    "objectRange": frame_slot_range(relation.object.as_ref()),
                    "recipientRange": frame_slot_range(relation.recipient.as_ref()),
                })
            }).collect::<Vec<_>>()
        })
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn frame_slot_entity_id(slot: Option<&phoenix_types::FrameSlot>) -> Option<String> {
        slot.and_then(|slot| match &slot.entity_ref {
            Some(MentionEntityRef::Known(entity_id)) => Some(entity_id.0.clone()),
            Some(MentionEntityRef::Speculative(key)) => Some(format!("spec:{key}")),
            None => None,
        })
    }

    #[cfg(feature = "legacy-cozo-graph")]
    fn frame_slot_range(slot: Option<&phoenix_types::FrameSlot>) -> Option<Value> {
        slot.map(|slot| {
            json!({
                "start": slot.range.start,
                "end": slot.range.end,
            })
        })
    }
}

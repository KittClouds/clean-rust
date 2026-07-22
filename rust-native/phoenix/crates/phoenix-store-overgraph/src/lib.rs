use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use lz4_flex::decompress_size_prepended;
use overgraph::{
    DatabaseEngine, DbOptions, EngineError, NodeInput, NodeRecord, PropValue, UpsertNodeOptions,
    WalSyncMode,
};
use phoenix_document_index::{
    document_index_shard_path, persist_document_index_shard, DocumentIndexShardRef,
    MmapDocumentIndex,
};
use phoenix_graph_kernel::GraphTruthCommit;
use phoenix_hyperbolic::hybrid_space::{HybridPoint, HybridSpaceConfig};
use phoenix_hyperbolic::{
    AnnMetric, Candidate as HnswCandidate, HnswBuildParams, HyperbolicDiskHnsw,
    HyperbolicHnswBuilder, PackedHnswGraph, PackedHnswMetadata,
};
use phoenix_kernel::{
    DeterministicKernel, KernelCheckpointData, KernelCheckpointMeta, KernelGraphLayer,
    KernelGraphSnapshot, KernelJournalEntry, KernelMutationBatch, KernelMutationScope,
};
use phoenix_semantic_v2::{
    scope_storage_key, AliasEntry, AliasPosting, CausalScopeSidecar, DirtyScopeRecord,
    DocumentArchive, DocumentManifest, DocumentOrd, DocumentOrdinalAssignment, DocumentRevisionRef,
    DocumentSegmentKind, ErScopePatchSidecar, EventIdentityScopeSidecar, GraphScopeSidecar,
    LexicalPostingsSegment, MemoryScopeSidecar, PreparedDocument, PreparedDocumentSegment,
    RelationMentionSeedScopeSidecar, RelationScopePatchSidecar, ScopeLexSidecar, ScopeOrd,
    SemanticGraphScopeSidecar, SessionArchive, SessionOrd, StateSchemaScopeSidecar,
    TemporalScopeSidecar,
};
use phoenix_store_native_core::{
    default_semantic_model_id, relation_spec, snapshot_relations_for_partition, AnnGenerationId,
    AnnIndexFamily, AnnIndexKey, AnnManifest, AnnPackedSegments, BundleHeader, BundleKey,
    BundleKind, ChunkManifest, GraphTruthCommitAppend, IngestMode,
    NativeSemanticDocumentVectorRecord, NativeSemanticLeafVectorRecord,
    NativeSemanticNodeVectorRecord, PhoenixArchiveStoreV2, PhoenixBundleStoreV2,
    PhoenixCausalPatchStore, PhoenixChunkManifestStore, PhoenixErPatchStore,
    PhoenixEventIdentityPatchStore, PhoenixGraphKernelStoreV2, PhoenixGraphPatchStore,
    PhoenixMemoryPatchStore, PhoenixNativeRowStore, PhoenixRelationMentionSeedStore,
    PhoenixRelationPatchStore, PhoenixSemanticGraphPatchStore, PhoenixSemanticIndexStore,
    PhoenixStateSchemaPatchStore, PhoenixTemporalPatchStore, PreparedDocumentPersistTelemetry,
    PreparedDocumentSegmentPersistTelemetry, PreparedIngestContext, SemanticDocumentNeighbor,
    SemanticIndexAuthorityReceipt, SemanticNeighbor, SemanticNodeNeighbor, SnapshotEnvelope,
    SnapshotPartition, StoreError, ALL_RELATIONS, SEMANTIC_MODEL_ID, SEMANTIC_VECTOR_DIM,
};
use phoenix_types::{IndexedSpan, IngestDocument, ScopeKey, SessionId};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::Value;

mod canonical_reward_producer;
#[cfg(test)]
mod canonical_reward_producer_tests;
mod discovery_source_cache;
mod graph_checkpoint_policy;
mod graph_kernel_replay_audit;
#[cfg(test)]
mod graph_kernel_replay_audit_tests;
mod graph_learning_origin;
mod graph_learning_persistence;
#[cfg(test)]
mod graph_learning_persistence_tests;
mod graph_topology;
mod graph_truth_persistence;
#[cfg(test)]
mod graph_truth_persistence_tests;
mod lexical_query;
mod native_decision_evidence_persistence;
mod native_decision_persistence;
#[cfg(test)]
mod native_decision_persistence_tests;
mod native_decision_reward_persistence;
mod native_decision_store_impl;
mod prepared_segment_payload;
mod scope_runtime;
pub use canonical_reward_producer::CanonicalRewardProducerReport;
use graph_checkpoint_policy::{
    KernelCheckpointDecision, KernelCheckpointPolicy, KernelCheckpointPolicyInput,
};
pub use graph_kernel_replay_audit::{KernelSnapshotReplayAudit, KernelSnapshotReplayTimings};
pub use graph_topology::{
    KernelTopologyCounts, KernelTopologyShortestPath, KernelTopologyVertexId,
};
pub use scope_runtime::ScopeRuntimeLoadTelemetry;

const TYPE_SCOPE_ORD: u32 = 1;
const TYPE_SESSION_ORD: u32 = 2;
const TYPE_DOCUMENT_ORD: u32 = 3;
const TYPE_COUNTER: u32 = 4;
const TYPE_DOCUMENT_MANIFEST: u32 = 5;
const TYPE_DOCUMENT_LATEST: u32 = 6;
const TYPE_DOCUMENT_SEGMENT: u32 = 7;
const TYPE_SESSION_ARCHIVE: u32 = 8;
const TYPE_SESSION_LATEST: u32 = 9;
const TYPE_SCOPE_SIDECAR: u32 = 10;
const TYPE_DIRTY_SCOPE: u32 = 11;
const TYPE_COMPAT_BUNDLE: u32 = 12;
const TYPE_KERNEL_CHECKPOINT: u32 = 13;
const TYPE_KERNEL_JOURNAL: u32 = 14;
const TYPE_KERNEL_COMMIT: u32 = 15;
const TYPE_KERNEL_STATE: u32 = 16;
const TYPE_ANN_SOURCE_LEAF: u32 = 17;
const TYPE_ANN_SOURCE_DOCUMENT: u32 = 18;
const TYPE_ANN_SOURCE_NODE: u32 = 19;
const TYPE_ANN_HEAD: u32 = 20;
const TYPE_ANN_DIRTY: u32 = 21;
const TYPE_ANN_GENERATION: u32 = 22;
const TYPE_ER_PATCH_SIDECAR: u32 = 23;
const TYPE_RELATION_PATCH_SIDECAR: u32 = 24;
const TYPE_MEMORY_PATCH_SIDECAR: u32 = 25;
const TYPE_RELATION_MENTION_SEED_SIDECAR: u32 = 26;
const TYPE_CAUSAL_PATCH_SIDECAR: u32 = 27;
const TYPE_TEMPORAL_PATCH_SIDECAR: u32 = 28;
const TYPE_EVENT_IDENTITY_PATCH_SIDECAR: u32 = 29;
const TYPE_STATE_SCHEMA_PATCH_SIDECAR: u32 = 30;
const TYPE_GRAPH_PATCH_SIDECAR: u32 = 31;
const TYPE_SEMANTIC_GRAPH_PATCH_SIDECAR: u32 = 32;
const TYPE_NATIVE_ROW: u32 = 33;
const TYPE_KERNEL_TOPOLOGY_VERTEX: u32 = 34;
const TYPE_CHUNK_MANIFEST: u32 = 35;
// Type 36 is reserved by graph_truth_persistence.
const TYPE_DOCUMENT_INDEX_SHARD: u32 = 37;
const TYPE_DOCUMENT_INDEX_LATEST: u32 = 38;
const EDGE_KERNEL_TOPOLOGY_ASSERTED: u32 = 1001;
const EDGE_KERNEL_TOPOLOGY_CANDIDATE: u32 = 1002;

const COUNTER_SCOPE: &str = "scope";
const COUNTER_SESSION: &str = "session";
const COUNTER_DOCUMENT: &str = "document";
const KERNEL_CHECKPOINT_KEY: &str = "current";
const KERNEL_STATE_KEY: &str = "state";

const PROP_ORD: &str = "ord";
const PROP_VALUE: &str = "value";
const PROP_SCOPE_KEY: &str = "scope_key";
const PROP_SCOPE_ORD: &str = "scope_ord";
const PROP_DOCUMENT_ID: &str = "document_id";
const PROP_DOCUMENT_ORD: &str = "document_ord";
const PROP_REVISION: &str = "revision";
const PROP_SESSION_ORD: &str = "session_ord";
const PROP_SESSION_ID: &str = "session_id";
const PROP_GENERATION: &str = "generation";
const PROP_JOURNAL_LEN: &str = "journal_len";
const PROP_JOURNAL_BYTES: &str = "journal_bytes";
const PROP_REPLAY_COST_US: &str = "replay_cost_us";
const PROP_SEQ: &str = "seq";
const PROP_SOURCE_REVISION: &str = "source_revision";
const PROP_DISCOVERY_SOURCE_CACHE_SCHEMA: &str = "discovery_source_cache_schema";
const PROP_CREATED_AT: &str = "created_at";
const PROP_UPDATED_AT: &str = "updated_at";
const PROP_KIND: &str = "kind";
const PROP_MODEL_ID: &str = "model_id";
const PROP_DIMENSION: &str = "dimension";
const PROP_ENTITY_KEY: &str = "entity_key";
const PROP_BYTE_LEN: &str = "byte_len";
const PROP_PAYLOAD: &str = "payload";
const PROP_PAYLOAD_PATH: &str = "payload_path";
const PROP_RECORD: &str = "record";
const PROP_COMMIT_ID: &str = "commit_id";
const PROP_DOCUMENT_VALUE_KEY: &str = "document_value_key";
const PROP_GENERATION_HINT: &str = "generation_hint";
const PROP_FAMILY: &str = "family";
const PROP_SEGMENTS: &str = "segments";
const PROP_SPAN_ID: &str = "span_id";
const PROP_NODE_ID: &str = "node_id";
const PROP_LEAF_COUNT: &str = "leaf_count";
const ANN_CACHE_DIR: &str = "semantic-ann";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
enum AnnPayload {
    Document {
        document_id: String,
        leaf_count: usize,
        evidence_refs: Vec<String>,
    },
    Leaf {
        span_id: String,
        document_id: String,
    },
    Node {
        node_id: String,
        node_kind: String,
        document_id: Option<String>,
        note_id: Option<String>,
        narrative_id: Option<String>,
        folder_id: Option<String>,
        folder_path: Option<String>,
        evidence_refs: Vec<String>,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AnnSourceLeafRecord {
    scope: ScopeKey,
    scope_key: String,
    #[serde(default = "default_semantic_model_id")]
    model_id: String,
    span_id: String,
    document_id: String,
    values: Vec<f32>,
    updated_at: i64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AnnSourceDocumentRecord {
    scope: ScopeKey,
    scope_key: String,
    #[serde(default = "default_semantic_model_id")]
    model_id: String,
    document_id: String,
    values: Vec<f32>,
    leaf_count: usize,
    evidence_refs: Vec<String>,
    updated_at: i64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AnnSourceNodeRecord {
    scope: ScopeKey,
    scope_key: String,
    #[serde(default = "default_semantic_model_id")]
    model_id: String,
    node_id: String,
    node_kind: String,
    document_id: Option<String>,
    note_id: Option<String>,
    narrative_id: Option<String>,
    folder_id: Option<String>,
    folder_path: Option<String>,
    values: Vec<f32>,
    evidence_refs: Vec<String>,
    updated_at: i64,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct AnnQueryCacheKey {
    index: AnnIndexKey,
    generation: AnnGenerationId,
}

struct CachedAnnQueryState {
    key: AnnQueryCacheKey,
    manifest: AnnManifest,
    payloads: Arc<[AnnPayload]>,
    index_handle: Arc<HyperbolicDiskHnsw<AnnMetric>>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct OvergraphTuning {
    pub memtable_flush_threshold: usize,
    pub memtable_hard_cap_bytes: usize,
    pub max_immutable_memtables: usize,
    pub compact_after_n_flushes: u32,
    pub wal_sync_mode: WalSyncMode,
    pub edge_uniqueness: bool,
    pub ingest_mode: IngestMode,
    pub kernel_checkpoint_hot_journal_bytes: usize,
    pub kernel_checkpoint_replay_cost_us: u64,
}

impl Default for OvergraphTuning {
    fn default() -> Self {
        Self {
            memtable_flush_threshold: 128 * 1024 * 1024,
            memtable_hard_cap_bytes: 512 * 1024 * 1024,
            max_immutable_memtables: 8,
            compact_after_n_flushes: 4,
            wal_sync_mode: WalSyncMode::default(),
            edge_uniqueness: false,
            ingest_mode: IngestMode::Safe,
            kernel_checkpoint_hot_journal_bytes: KernelCheckpointPolicy::default()
                .max_hot_journal_bytes,
            kernel_checkpoint_replay_cost_us: KernelCheckpointPolicy::default()
                .max_measured_replay_cost_us,
        }
    }
}

impl OvergraphTuning {
    fn from_env() -> Self {
        let mut tuning = Self::default();
        if let Some(value) = read_env_usize("PHOENIX_OVERGRAPH_MEMTABLE_FLUSH_THRESHOLD") {
            tuning.memtable_flush_threshold = value;
        }
        if let Some(value) = read_env_usize("PHOENIX_OVERGRAPH_MEMTABLE_HARD_CAP_BYTES") {
            tuning.memtable_hard_cap_bytes = value;
        }
        if let Some(value) = read_env_usize("PHOENIX_OVERGRAPH_MAX_IMMUTABLE_MEMTABLES") {
            tuning.max_immutable_memtables = value;
        }
        if let Some(value) = read_env_usize("PHOENIX_KERNEL_CHECKPOINT_HOT_JOURNAL_BYTES") {
            tuning.kernel_checkpoint_hot_journal_bytes = value;
        }
        if let Some(value) = read_env_u64("PHOENIX_KERNEL_CHECKPOINT_REPLAY_COST_US") {
            tuning.kernel_checkpoint_replay_cost_us = value;
        }
        if let Some(value) = read_env_u32("PHOENIX_OVERGRAPH_COMPACT_AFTER_N_FLUSHES") {
            tuning.compact_after_n_flushes = value;
        }
        if let Some(value) = std::env::var("PHOENIX_OVERGRAPH_INGEST_MODE").ok() {
            tuning.ingest_mode = match value.to_ascii_lowercase().as_str() {
                "bulk" | "bulkbuild" | "bulk_build" => IngestMode::BulkBuild,
                _ => IngestMode::Safe,
            };
        }
        if let Some(value) = std::env::var("PHOENIX_OVERGRAPH_WAL_SYNC").ok() {
            tuning.wal_sync_mode = match value.to_ascii_lowercase().as_str() {
                "immediate" => WalSyncMode::Immediate,
                _ => WalSyncMode::default(),
            };
        }
        tuning
    }

    fn db_options(&self) -> DbOptions {
        DbOptions {
            create_if_missing: true,
            memtable_flush_threshold: self.memtable_flush_threshold,
            edge_uniqueness: self.edge_uniqueness,
            dense_vector: None,
            compact_after_n_flushes: self.compact_after_n_flushes,
            wal_sync_mode: self.wal_sync_mode.clone(),
            memtable_hard_cap_bytes: self.memtable_hard_cap_bytes,
            max_immutable_memtables: self.max_immutable_memtables,
        }
    }
}

pub struct PhoenixOvergraphStore {
    path: PathBuf,
    tuning: OvergraphTuning,
    engine: Mutex<Option<DatabaseEngine>>,
    scope_runtime_document_cache: Mutex<Vec<Arc<scope_runtime::CachedScopeDocumentProjection>>>,
    scope_runtime_image_cache: Mutex<Vec<Arc<scope_runtime::CachedScopeRuntimeImage>>>,
    ann_query_state_cache: Mutex<HashMap<AnnQueryCacheKey, Arc<CachedAnnQueryState>>>,
    discovery_source_view_cache:
        Mutex<Option<(u64, Arc<phoenix_discovery_view::AssertedDiscoveryView>)>>,
    live_kernel_generation: AtomicU64,
    live_kernel_snapshot: Mutex<Option<KernelGraphSnapshot>>,
    graph_proposal_receipt_index: Mutex<graph_learning_persistence::GraphProposalReceiptIndex>,
    native_decision_receipt_index: Mutex<native_decision_persistence::NativeDecisionReceiptIndex>,
}

impl PhoenixOvergraphStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StoreError> {
        Self::open_with_tuning(path, OvergraphTuning::from_env())
    }

    pub fn open_with_tuning(
        path: impl AsRef<Path>,
        tuning: OvergraphTuning,
    ) -> Result<Self, StoreError> {
        let path = path.as_ref().to_path_buf();
        fs::create_dir_all(&path).map_err(|error| StoreError::Init(error.to_string()))?;
        let mut engine = DatabaseEngine::open(&path, &tuning.db_options())
            .map_err(|error| StoreError::Init(error.to_string()))?;
        if tuning.ingest_mode == IngestMode::BulkBuild {
            engine.ingest_mode();
        }
        Ok(Self {
            path,
            tuning,
            engine: Mutex::new(Some(engine)),
            scope_runtime_document_cache: Mutex::new(Vec::new()),
            scope_runtime_image_cache: Mutex::new(Vec::new()),
            ann_query_state_cache: Mutex::new(HashMap::new()),
            discovery_source_view_cache: Mutex::new(None),
            live_kernel_generation: AtomicU64::new(u64::MAX),
            live_kernel_snapshot: Mutex::new(None),
            graph_proposal_receipt_index: Mutex::new(Default::default()),
            native_decision_receipt_index: Mutex::new(Default::default()),
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn open_document_index_shard(
        &self,
        reference: &DocumentIndexShardRef,
    ) -> Result<MmapDocumentIndex, StoreError> {
        let path = document_index_shard_path(&self.path, reference)
            .map_err(|error| StoreError::Snapshot(error.to_string()))?;
        MmapDocumentIndex::open_verified(path, reference)
            .map_err(|error| StoreError::Snapshot(error.to_string()))
    }

    pub fn load_latest_document_index_ref(
        &self,
        scope_ord: ScopeOrd,
        document_ord: DocumentOrd,
    ) -> Result<Option<DocumentIndexShardRef>, StoreError> {
        self.with_engine(|engine| {
            engine
                .get_node_by_key(
                    TYPE_DOCUMENT_INDEX_LATEST,
                    &document_latest_key(scope_ord, document_ord),
                )
                .map_err(store_query_error)?
                .map(|node| decode_record_prop_required(&node, PROP_RECORD))
                .transpose()
        })
    }

    pub fn tuning(&self) -> &OvergraphTuning {
        &self.tuning
    }

    pub fn clear_retained_runtime_state(&self) {
        if let Ok(mut guard) = self.scope_runtime_document_cache.lock() {
            *guard = Vec::new();
        }
        if let Ok(mut guard) = self.scope_runtime_image_cache.lock() {
            *guard = Vec::new();
        }
        if let Ok(mut guard) = self.ann_query_state_cache.lock() {
            *guard = HashMap::new();
        }
        self.clear_discovery_source_cache();
        self.invalidate_live_kernel_snapshot();
    }

    pub fn publish_and_close(self) -> Result<(), StoreError> {
        let publish_compacted = self.tuning.ingest_mode == IngestMode::BulkBuild;
        let Some(mut engine) = self.take_engine()? else {
            return Ok(());
        };
        engine.flush().map_err(store_query_error)?;
        if publish_compacted {
            engine.end_ingest().map_err(store_query_error)?;
        }
        engine.close().map_err(store_query_error)
    }

    pub fn close_fast(self) -> Result<(), StoreError> {
        let Some(engine) = self.take_engine()? else {
            return Ok(());
        };
        engine.close_fast().map_err(store_query_error)
    }

    fn take_engine(&self) -> Result<Option<DatabaseEngine>, StoreError> {
        let mut guard = self
            .engine
            .lock()
            .map_err(|_| StoreError::Query("overgraph engine mutex poisoned".to_owned()))?;
        Ok(guard.take())
    }

    fn with_engine<T>(
        &self,
        f: impl FnOnce(&mut DatabaseEngine) -> Result<T, StoreError>,
    ) -> Result<T, StoreError> {
        let mut guard = self
            .engine
            .lock()
            .map_err(|_| StoreError::Query("overgraph engine mutex poisoned".to_owned()))?;
        let engine = guard
            .as_mut()
            .ok_or_else(|| StoreError::Query("overgraph engine already closed".to_owned()))?;
        f(engine)
    }

    fn batch_upsert_nodes_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        inputs: Vec<NodeInput>,
    ) -> Result<(), StoreError> {
        if inputs.is_empty() {
            return Ok(());
        }
        engine
            .batch_upsert_nodes(&inputs)
            .map_err(store_query_error)?;
        Ok(())
    }

    fn lookup_scope_ord_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<ScopeOrd>, StoreError> {
        let scope_key = scope_storage_key(scope);
        Ok(engine
            .get_node_by_key(TYPE_SCOPE_ORD, &scope_key)
            .map_err(store_query_error)?
            .map(|node| ScopeOrd(required_u64_prop(&node, PROP_ORD).unwrap_or_default())))
    }

    fn normalize_semantic_model_id(model_id: &str) -> String {
        let trimmed = model_id.trim();
        if trimmed.is_empty() {
            SEMANTIC_MODEL_ID.to_owned()
        } else {
            trimmed.to_owned()
        }
    }

    fn ann_index_key(
        scope_ord: ScopeOrd,
        family: AnnIndexFamily,
        kind: Option<String>,
        model_id: &str,
        dimension: usize,
    ) -> Result<AnnIndexKey, StoreError> {
        if dimension == 0 {
            return Err(StoreError::Query(format!(
                "semantic vector dimension mismatch for {}: expected positive dimension, got 0",
                ann_family_name(family)
            )));
        }
        Ok(AnnIndexKey {
            scope_ord,
            family,
            kind,
            model_id: Self::normalize_semantic_model_id(model_id),
            dimension,
        })
    }

    fn validate_semantic_vector_dim(
        values: &[f32],
        expected_dim: usize,
        label: &str,
    ) -> Result<(), StoreError> {
        if expected_dim == 0 || values.len() != expected_dim {
            return Err(StoreError::Query(format!(
                "semantic vector dimension mismatch for {label}: expected {}, got {}",
                expected_dim,
                values.len()
            )));
        }
        Ok(())
    }

    fn validate_semantic_vector(values: &[f32], label: &str) -> Result<(), StoreError> {
        Self::validate_semantic_vector_dim(values, SEMANTIC_VECTOR_DIM, label)
    }

    fn load_cached_ann_query_state(
        &self,
        key: &AnnQueryCacheKey,
    ) -> Option<Arc<CachedAnnQueryState>> {
        self.ann_query_state_cache
            .lock()
            .ok()
            .and_then(|guard| guard.get(key).cloned())
    }

    fn cache_ann_query_state(&self, state: Arc<CachedAnnQueryState>) -> Arc<CachedAnnQueryState> {
        let Ok(mut guard) = self.ann_query_state_cache.lock() else {
            return state;
        };
        if let Some(existing) = guard.get(&state.key).cloned() {
            return existing;
        }
        guard.retain(|key, _| key.index != state.key.index);
        guard.insert(state.key.clone(), state.clone());
        state
    }

    fn invalidate_ann_query_state(&self, index: &AnnIndexKey) {
        if let Ok(mut guard) = self.ann_query_state_cache.lock() {
            guard.retain(|key, _| key.index != *index);
        }
    }

    fn mark_ann_dirty_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
        dirty_at: i64,
    ) -> Result<(), StoreError> {
        self.invalidate_ann_query_state(index);
        engine
            .upsert_node(
                TYPE_ANN_DIRTY,
                &ann_index_storage_key(index),
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_ORD, PropValue::UInt(index.scope_ord.0)),
                        (
                            PROP_FAMILY,
                            PropValue::String(ann_family_name(index.family).to_owned()),
                        ),
                        (
                            PROP_KIND,
                            PropValue::String(index.kind.clone().unwrap_or_default()),
                        ),
                        (PROP_MODEL_ID, PropValue::String(index.model_id.clone())),
                        (PROP_DIMENSION, PropValue::UInt(index.dimension as u64)),
                        (PROP_UPDATED_AT, PropValue::Int(dirty_at)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn clear_ann_dirty_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
    ) -> Result<(), StoreError> {
        if let Some(node) = engine
            .get_node_by_key(TYPE_ANN_DIRTY, &ann_index_storage_key(index))
            .map_err(store_query_error)?
        {
            engine.delete_node(node.id).map_err(store_query_error)?;
        }
        Ok(())
    }

    fn persist_ann_generation_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
        vectors: &[Vec<f32>],
        payloads: &[AnnPayload],
        built_at: i64,
    ) -> Result<(), StoreError> {
        self.invalidate_ann_query_state(index);
        if vectors.is_empty() {
            if let Some(node) = engine
                .get_node_by_key(TYPE_ANN_HEAD, &ann_index_storage_key(index))
                .map_err(store_query_error)?
            {
                engine.delete_node(node.id).map_err(store_query_error)?;
            }
            self.clear_ann_dirty_with_engine(engine, index)?;
            return Ok(());
        }

        for (offset, vector) in vectors.iter().enumerate() {
            Self::validate_semantic_vector_dim(
                vector,
                index.dimension,
                &format!("ann source vector {offset}"),
            )?;
        }
        let metric = Self::ann_metric_for_index(index);
        let metric_label = metric.label();
        let depth = Self::ann_hybrid_depth_for_index(index);
        let mut builder =
            HyperbolicHnswBuilder::new(index.dimension, metric, HnswBuildParams::default());
        for vector in vectors {
            builder.insert(Self::project_ann_vector(
                index,
                metric_label,
                depth,
                vector,
            )?);
        }
        let packed = builder.into_packed();
        let generation = AnnGenerationId(
            engine
                .get_node_by_key(TYPE_ANN_HEAD, &ann_index_storage_key(index))
                .map_err(store_query_error)?
                .and_then(|node| optional_u64_prop(&node, PROP_GENERATION))
                .unwrap_or_default()
                + 1,
        );
        let manifest = AnnManifest {
            index: index.clone(),
            generation_id: generation,
            built_at,
            dimension: packed.metadata.dim(),
            model_id: index.model_id.clone(),
            count: packed.metadata.num_vectors(),
            entry_point: packed.metadata.entry_point(),
            max_level: packed.metadata.max_level(),
            m: HnswBuildParams::default().m,
            m0: HnswBuildParams::default().m0,
            ef_construction: HnswBuildParams::default().ef_construction,
            level_mult: HnswBuildParams::default().level_mult,
            metric: metric_label.to_owned(),
        };
        let segments = AnnPackedSegments {
            vectors: packed.vectors,
            levels: packed.levels,
            offsets: packed.offsets,
            adjacency: packed.adjacency,
        };
        let generation_key = ann_generation_storage_key(index, generation);
        engine
            .upsert_node(
                TYPE_ANN_GENERATION,
                &generation_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_ORD, PropValue::UInt(index.scope_ord.0)),
                        (
                            PROP_FAMILY,
                            PropValue::String(ann_family_name(index.family).to_owned()),
                        ),
                        (
                            PROP_KIND,
                            PropValue::String(index.kind.clone().unwrap_or_default()),
                        ),
                        (PROP_MODEL_ID, PropValue::String(index.model_id.clone())),
                        (PROP_DIMENSION, PropValue::UInt(index.dimension as u64)),
                        (PROP_GENERATION, PropValue::UInt(generation.0)),
                        (PROP_UPDATED_AT, PropValue::Int(built_at)),
                        (PROP_RECORD, PropValue::Bytes(encode_record(&manifest)?)),
                        (PROP_PAYLOAD, PropValue::Bytes(encode_archive(&payloads)?)),
                        (PROP_SEGMENTS, PropValue::Bytes(encode_archive(&segments)?)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        engine
            .upsert_node(
                TYPE_ANN_HEAD,
                &ann_index_storage_key(index),
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_ORD, PropValue::UInt(index.scope_ord.0)),
                        (
                            PROP_FAMILY,
                            PropValue::String(ann_family_name(index.family).to_owned()),
                        ),
                        (
                            PROP_KIND,
                            PropValue::String(index.kind.clone().unwrap_or_default()),
                        ),
                        (PROP_MODEL_ID, PropValue::String(index.model_id.clone())),
                        (PROP_DIMENSION, PropValue::UInt(index.dimension as u64)),
                        (PROP_GENERATION, PropValue::UInt(generation.0)),
                        (PROP_UPDATED_AT, PropValue::Int(built_at)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        self.write_ann_generation_cache_file(&manifest, &segments)?;
        self.clear_ann_dirty_with_engine(engine, index)?;
        Ok(())
    }

    fn rebuild_document_ann_index_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
        built_at: i64,
    ) -> Result<(), StoreError> {
        let mut records = engine
            .get_nodes_by_type(TYPE_ANN_SOURCE_DOCUMENT)
            .map_err(store_query_error)?
            .into_iter()
            .filter(|node| {
                optional_u64_prop(node, PROP_SCOPE_ORD) == Some(index.scope_ord.0)
                    && optional_string_prop(node, PROP_KIND).unwrap_or_default()
                        == index.kind.clone().unwrap_or_default()
            })
            .filter_map(|node| {
                decode_record_prop::<AnnSourceDocumentRecord>(&node, PROP_RECORD).transpose()
            })
            .collect::<Result<Vec<_>, _>>()?;
        records.retain(|record| {
            record.model_id == index.model_id && record.values.len() == index.dimension
        });
        records.sort_by(|left, right| left.document_id.cmp(&right.document_id));
        let vectors = records
            .iter()
            .map(|record| record.values.clone())
            .collect::<Vec<_>>();
        let payloads = records
            .iter()
            .map(|record| AnnPayload::Document {
                document_id: record.document_id.clone(),
                leaf_count: record.leaf_count,
                evidence_refs: record.evidence_refs.clone(),
            })
            .collect::<Vec<_>>();
        self.persist_ann_generation_with_engine(engine, index, &vectors, &payloads, built_at)
    }

    fn rebuild_leaf_ann_index_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
        built_at: i64,
    ) -> Result<(), StoreError> {
        let mut records = engine
            .get_nodes_by_type(TYPE_ANN_SOURCE_LEAF)
            .map_err(store_query_error)?
            .into_iter()
            .filter(|node| optional_u64_prop(node, PROP_SCOPE_ORD) == Some(index.scope_ord.0))
            .filter_map(|node| {
                decode_record_prop::<AnnSourceLeafRecord>(&node, PROP_RECORD).transpose()
            })
            .collect::<Result<Vec<_>, _>>()?;
        records.retain(|record| {
            record.model_id == index.model_id && record.values.len() == index.dimension
        });
        records.sort_by(|left, right| left.span_id.cmp(&right.span_id));
        let vectors = records
            .iter()
            .map(|record| record.values.clone())
            .collect::<Vec<_>>();
        let payloads = records
            .iter()
            .map(|record| AnnPayload::Leaf {
                span_id: record.span_id.clone(),
                document_id: record.document_id.clone(),
            })
            .collect::<Vec<_>>();
        self.persist_ann_generation_with_engine(engine, index, &vectors, &payloads, built_at)
    }

    fn rebuild_node_ann_index_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
        built_at: i64,
    ) -> Result<(), StoreError> {
        let mut records = engine
            .get_nodes_by_type(TYPE_ANN_SOURCE_NODE)
            .map_err(store_query_error)?
            .into_iter()
            .filter(|node| {
                optional_u64_prop(node, PROP_SCOPE_ORD) == Some(index.scope_ord.0)
                    && index.kind.as_deref().map_or(true, |kind| {
                        optional_string_prop(node, PROP_KIND).unwrap_or_default() == kind
                    })
            })
            .filter_map(|node| {
                decode_record_prop::<AnnSourceNodeRecord>(&node, PROP_RECORD).transpose()
            })
            .collect::<Result<Vec<_>, _>>()?;
        records.retain(|record| {
            record.model_id == index.model_id && record.values.len() == index.dimension
        });
        if index.kind.is_some() {
            if let Some(latest_updated_at) = records.iter().map(|record| record.updated_at).max() {
                records.retain(|record| record.updated_at == latest_updated_at);
            }
        } else {
            let mut latest_by_kind = BTreeMap::<String, i64>::new();
            for record in &records {
                latest_by_kind
                    .entry(record.node_kind.clone())
                    .and_modify(|current| *current = (*current).max(record.updated_at))
                    .or_insert(record.updated_at);
            }
            records.retain(|record| {
                latest_by_kind.get(record.node_kind.as_str()).copied() == Some(record.updated_at)
            });
        }
        records.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        let vectors = records
            .iter()
            .map(|record| record.values.clone())
            .collect::<Vec<_>>();
        let payloads = records
            .iter()
            .map(|record| AnnPayload::Node {
                node_id: record.node_id.clone(),
                node_kind: record.node_kind.clone(),
                document_id: record.document_id.clone(),
                note_id: record.note_id.clone(),
                narrative_id: record.narrative_id.clone(),
                folder_id: record.folder_id.clone(),
                folder_path: record.folder_path.clone(),
                evidence_refs: record.evidence_refs.clone(),
            })
            .collect::<Vec<_>>();
        self.persist_ann_generation_with_engine(engine, index, &vectors, &payloads, built_at)
    }

    fn ensure_ann_index_ready_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
    ) -> Result<(), StoreError> {
        let dirty = engine
            .get_node_by_key(TYPE_ANN_DIRTY, &ann_index_storage_key(index))
            .map_err(store_query_error)?
            .is_some();
        let stale_space = self
            .load_ann_generation_components_with_engine(engine, index)?
            .is_some_and(|(manifest, _, _)| {
                !Self::ann_manifest_uses_current_space(index, &manifest)
            });
        if !dirty && !stale_space {
            return Ok(());
        }
        let built_at = now_ms();
        match index.family {
            AnnIndexFamily::Document => {
                self.rebuild_document_ann_index_with_engine(engine, index, built_at)
            }
            AnnIndexFamily::Leaf => {
                self.rebuild_leaf_ann_index_with_engine(engine, index, built_at)
            }
            AnnIndexFamily::NodePrototype => {
                self.rebuild_node_ann_index_with_engine(engine, index, built_at)
            }
        }
    }

    #[inline]
    fn ann_metric_for_index(_index: &AnnIndexKey) -> AnnMetric {
        AnnMetric::hybrid_interior_default()
    }

    #[inline]
    fn ann_hybrid_depth_for_index(index: &AnnIndexKey) -> f32 {
        match index.family {
            AnnIndexFamily::Document => 0.75,
            AnnIndexFamily::Leaf => 1.5,
            AnnIndexFamily::NodePrototype => 2.0,
        }
    }

    #[inline]
    fn ann_manifest_uses_current_space(index: &AnnIndexKey, manifest: &AnnManifest) -> bool {
        manifest.dimension == index.dimension
            && manifest.model_id == index.model_id
            && manifest.metric == Self::ann_metric_for_index(index).label()
    }

    fn project_ann_vector(
        index: &AnnIndexKey,
        metric_label: &str,
        depth: f32,
        vector: &[f32],
    ) -> Result<Vec<f32>, StoreError> {
        Self::validate_semantic_vector_dim(vector, index.dimension, "ann vector")?;
        let metric = AnnMetric::from_label_or_default(metric_label);
        if metric.label() != AnnMetric::LABEL_HYBRID_INTERIOR {
            return Ok(vector.to_vec());
        }
        HybridPoint::from_embedding_and_depth(vector, depth, HybridSpaceConfig::default())
            .map(|point| point.poincare)
            .map_err(|error| {
                StoreError::Query(format!(
                    "failed to project {} ANN vector into hybrid space: {error}",
                    ann_family_name(index.family)
                ))
            })
    }

    fn project_ann_query_vector(
        manifest: &AnnManifest,
        query_vector: &[f32],
    ) -> Result<Vec<f32>, StoreError> {
        Self::project_ann_vector(
            &manifest.index,
            manifest.metric.as_str(),
            Self::ann_hybrid_depth_for_index(&manifest.index),
            query_vector,
        )
    }

    fn ann_cache_dir(&self) -> PathBuf {
        self.path.join(ANN_CACHE_DIR)
    }

    fn ann_cache_generation_path(
        &self,
        index: &AnnIndexKey,
        generation: AnnGenerationId,
    ) -> PathBuf {
        let kind = sanitize_ann_kind(index.kind.as_deref().unwrap_or("all"));
        let model = sanitize_ann_kind(index.model_id.as_str());
        self.ann_cache_dir().join(format!(
            "scope-{}-{}-{}-{}d-{}-g{}.bin",
            index.scope_ord.0,
            ann_family_name(index.family),
            kind,
            index.dimension,
            model,
            generation.0
        ))
    }

    fn write_ann_generation_cache_file(
        &self,
        manifest: &AnnManifest,
        segments: &AnnPackedSegments,
    ) -> Result<PathBuf, StoreError> {
        let cache_dir = self.ann_cache_dir();
        fs::create_dir_all(&cache_dir).map_err(|error| StoreError::Query(error.to_string()))?;
        let path = self.ann_cache_generation_path(&manifest.index, manifest.generation_id);
        if path.exists() {
            return Ok(path);
        }
        let graph = PackedHnswGraph {
            metadata: PackedHnswMetadata::new(
                manifest.dimension,
                manifest.count,
                manifest.max_level,
                manifest.entry_point,
                4,
            ),
            vectors: segments.vectors.clone(),
            levels: segments.levels.clone(),
            offsets: segments.offsets.clone(),
            adjacency: segments.adjacency.clone(),
        };
        graph
            .write_to_file(&path.to_string_lossy())
            .map_err(|error| StoreError::Query(error.to_string()))?;
        Ok(path)
    }

    pub fn load_ann_manifest(
        &self,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
    ) -> Result<Option<AnnManifest>, StoreError> {
        self.load_ann_manifest_for_model(
            SEMANTIC_MODEL_ID,
            SEMANTIC_VECTOR_DIM,
            scope,
            family,
            kind,
        )
    }

    pub fn load_ann_manifest_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
    ) -> Result<Option<AnnManifest>, StoreError> {
        Ok(self
            .load_ann_query_state_for_model(model_id, dimension, scope, family, kind)?
            .map(|state| state.manifest.clone()))
    }

    fn load_ann_query_state(
        &self,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
    ) -> Result<Option<Arc<CachedAnnQueryState>>, StoreError> {
        self.load_ann_query_state_for_model(
            SEMANTIC_MODEL_ID,
            SEMANTIC_VECTOR_DIM,
            scope,
            family,
            kind,
        )
    }

    fn load_ann_query_state_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
    ) -> Result<Option<Arc<CachedAnnQueryState>>, StoreError> {
        let Some(cache_key) = self
            .load_ann_query_generation_for_model(model_id, dimension, scope, family, kind, false)?
        else {
            return Ok(None);
        };
        if let Some(state) = self.load_cached_ann_query_state(&cache_key) {
            return Ok(Some(state));
        }
        match self.load_and_cache_ann_query_state_for_model(
            model_id, dimension, scope, family, kind, false,
        )? {
            Some(state) => Ok(Some(state)),
            None => Ok(None),
        }
    }

    fn load_and_cache_ann_query_state_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
        force_rebuild: bool,
    ) -> Result<Option<Arc<CachedAnnQueryState>>, StoreError> {
        let Some((index, manifest, payloads, cache_path)) = self
            .load_ann_query_components_for_model(
                model_id,
                dimension,
                scope,
                family,
                kind,
                force_rebuild,
            )?
        else {
            return Ok(None);
        };
        let cache_key = AnnQueryCacheKey {
            index,
            generation: manifest.generation_id,
        };
        if let Some(state) = self.load_cached_ann_query_state(&cache_key) {
            return Ok(Some(state));
        }
        match self.open_ann_disk_index(&manifest, &cache_path) {
            Ok(index_handle) => {
                let state = Arc::new(CachedAnnQueryState {
                    key: cache_key,
                    manifest,
                    payloads: Arc::<[AnnPayload]>::from(payloads),
                    index_handle: Arc::new(index_handle),
                });
                Ok(Some(self.cache_ann_query_state(state)))
            }
            Err(_) if !force_rebuild => self.load_and_cache_ann_query_state_for_model(
                model_id, dimension, scope, family, kind, true,
            ),
            Err(error) => Err(error),
        }
    }

    fn load_ann_query_generation_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
        force_rebuild: bool,
    ) -> Result<Option<AnnQueryCacheKey>, StoreError> {
        self.with_engine(|engine| {
            let Some(scope_ord) = self.lookup_scope_ord_with_engine(engine, scope)? else {
                return Ok(None);
            };
            let index = Self::ann_index_key(
                scope_ord,
                family,
                kind.map(str::to_owned),
                model_id,
                dimension,
            )?;
            if force_rebuild {
                self.rebuild_ann_index_with_engine(engine, &index, now_ms())?;
            } else {
                self.ensure_ann_index_ready_with_engine(engine, &index)?;
                if engine
                    .get_node_by_key(TYPE_ANN_HEAD, &ann_index_storage_key(&index))
                    .map_err(store_query_error)?
                    .is_none()
                {
                    self.rebuild_ann_index_with_engine(engine, &index, now_ms())?;
                }
            }
            let Some(head) = engine
                .get_node_by_key(TYPE_ANN_HEAD, &ann_index_storage_key(&index))
                .map_err(store_query_error)?
            else {
                return Ok(None);
            };
            let Some(generation) = optional_u64_prop(&head, PROP_GENERATION).map(AnnGenerationId)
            else {
                return Ok(None);
            };
            Ok(Some(AnnQueryCacheKey { index, generation }))
        })
    }

    fn load_ann_generation_components_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
    ) -> Result<Option<(AnnManifest, Vec<AnnPayload>, PathBuf)>, StoreError> {
        let Some(cache_key) = self.load_current_ann_query_generation_with_engine(engine, index)?
        else {
            return Ok(None);
        };
        self.load_ann_generation_components_for_key_with_engine(engine, &cache_key)
    }

    fn load_current_ann_query_generation_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
    ) -> Result<Option<AnnQueryCacheKey>, StoreError> {
        let Some(head) = engine
            .get_node_by_key(TYPE_ANN_HEAD, &ann_index_storage_key(index))
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let Some(generation) = optional_u64_prop(&head, PROP_GENERATION).map(AnnGenerationId)
        else {
            return Ok(None);
        };
        Ok(Some(AnnQueryCacheKey {
            index: index.clone(),
            generation,
        }))
    }

    fn load_ann_generation_components_for_key_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        cache_key: &AnnQueryCacheKey,
    ) -> Result<Option<(AnnManifest, Vec<AnnPayload>, PathBuf)>, StoreError> {
        let index = &cache_key.index;
        let generation = cache_key.generation;
        let Some(node) = engine
            .get_node_by_key(
                TYPE_ANN_GENERATION,
                &ann_generation_storage_key(index, generation),
            )
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let manifest: AnnManifest = decode_record_prop_required(&node, PROP_RECORD)?;
        let payloads: Vec<AnnPayload> = decode_archive(&required_bytes_prop(&node, PROP_PAYLOAD)?)?;
        if payloads.len() != manifest.count {
            return Err(StoreError::Query(format!(
                "semantic payload count mismatch for generation {}: expected {}, got {}",
                manifest.generation_id.0,
                manifest.count,
                payloads.len()
            )));
        }
        let cache_path = self.ann_cache_generation_path(&manifest.index, manifest.generation_id);
        if !cache_path.exists() {
            let segments: AnnPackedSegments =
                decode_archive(&required_bytes_prop(&node, PROP_SEGMENTS)?)?;
            self.write_ann_generation_cache_file(&manifest, &segments)?;
        }
        Ok(Some((manifest, payloads, cache_path)))
    }

    fn load_ann_query_components_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
        force_rebuild: bool,
    ) -> Result<Option<(AnnIndexKey, AnnManifest, Vec<AnnPayload>, PathBuf)>, StoreError> {
        self.with_engine(|engine| {
            let Some(scope_ord) = self.lookup_scope_ord_with_engine(engine, scope)? else {
                return Ok(None);
            };
            let index = Self::ann_index_key(
                scope_ord,
                family,
                kind.map(str::to_owned),
                model_id,
                dimension,
            )?;
            if force_rebuild {
                self.rebuild_ann_index_with_engine(engine, &index, now_ms())?;
            } else {
                self.ensure_ann_index_ready_with_engine(engine, &index)?;
            }
            Ok(self
                .load_ann_generation_components_with_engine(engine, &index)?
                .map(|(manifest, payloads, cache_path)| (index, manifest, payloads, cache_path)))
        })
    }

    fn open_ann_disk_index(
        &self,
        manifest: &AnnManifest,
        cache_path: &Path,
    ) -> Result<HyperbolicDiskHnsw<AnnMetric>, StoreError> {
        let metric = AnnMetric::from_label_or_default(manifest.metric.as_str());
        HyperbolicDiskHnsw::open(&cache_path.to_string_lossy(), metric)
            .map_err(|error| StoreError::Query(error.to_string()))
    }

    fn rebuild_ann_index_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        index: &AnnIndexKey,
        built_at: i64,
    ) -> Result<(), StoreError> {
        match index.family {
            AnnIndexFamily::Document => {
                self.rebuild_document_ann_index_with_engine(engine, index, built_at)
            }
            AnnIndexFamily::Leaf => {
                self.rebuild_leaf_ann_index_with_engine(engine, index, built_at)
            }
            AnnIndexFamily::NodePrototype => {
                self.rebuild_node_ann_index_with_engine(engine, index, built_at)
            }
        }
    }

    fn search_ann_payloads(
        &self,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
        query_vector: &[f32],
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<(HnswCandidate, AnnPayload)>, StoreError> {
        self.search_ann_payloads_for_model(
            SEMANTIC_MODEL_ID,
            SEMANTIC_VECTOR_DIM,
            scope,
            family,
            kind,
            query_vector,
            limit,
            oversample,
        )
    }

    fn search_ann_payloads_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        scope: &ScopeKey,
        family: AnnIndexFamily,
        kind: Option<&str>,
        query_vector: &[f32],
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<(HnswCandidate, AnnPayload)>, StoreError> {
        if limit == 0 {
            return Ok(Vec::new());
        }
        Self::validate_semantic_vector_dim(query_vector, dimension, "query")?;
        let Some(state) =
            self.load_ann_query_state_for_model(model_id, dimension, scope, family, kind)?
        else {
            return Ok(Vec::new());
        };
        let query_vector = Self::project_ann_query_vector(&state.manifest, query_vector)?;
        let search_limit = oversample.max(limit);
        Ok(state
            .index_handle
            .search(&query_vector, search_limit, search_limit.max(16))
            .into_iter()
            .filter_map(|candidate| {
                state
                    .payloads
                    .get(candidate.id as usize)
                    .cloned()
                    .map(|payload| (candidate, payload))
            })
            .collect())
    }

    fn cache_live_kernel_snapshot(&self, generation: u64, snapshot: KernelGraphSnapshot) {
        self.live_kernel_generation
            .store(generation, Ordering::Release);
        if let Ok(mut guard) = self.live_kernel_snapshot.lock() {
            *guard = Some(snapshot);
        }
    }

    fn invalidate_live_kernel_snapshot(&self) {
        self.live_kernel_generation
            .store(u64::MAX, Ordering::Release);
        if let Ok(mut guard) = self.live_kernel_snapshot.lock() {
            *guard = None;
        }
    }

    fn load_live_kernel_snapshot_with_engine(
        &self,
        engine: &mut DatabaseEngine,
    ) -> Result<KernelGraphSnapshot, StoreError> {
        let generation = self.kernel_current_generation_with_engine(engine)?;
        let cached_generation = self.live_kernel_generation.load(Ordering::Acquire);
        if cached_generation == generation {
            if let Ok(guard) = self.live_kernel_snapshot.lock() {
                if let Some(snapshot) = guard.as_ref() {
                    return Ok(snapshot.clone());
                }
            }
        }

        let replay_started = std::time::Instant::now();
        let kernel = DeterministicKernel::default();
        if let Some(checkpoint) = self.load_kernel_checkpoint_with_engine(engine)? {
            if checkpoint.meta.generation == generation
                && self.kernel_journal_len_with_engine(engine)? == 0
            {
                let snapshot = checkpoint.snapshot;
                self.cache_live_kernel_snapshot(generation, snapshot.clone());
                self.record_kernel_replay_cost_with_engine(engine, 0)?;
                return Ok(snapshot);
            }
            kernel
                .rebuild_from_kernel_batches(
                    vec![
                        KernelMutationBatch {
                            layer: KernelGraphLayer::Asserted,
                            scope: KernelMutationScope::Full,
                            recorded_at: None,
                            vertices: checkpoint.snapshot.vertices.clone(),
                            edges: checkpoint.snapshot.asserted_edges.clone(),
                        },
                        KernelMutationBatch {
                            layer: KernelGraphLayer::Candidate,
                            scope: KernelMutationScope::Full,
                            recorded_at: None,
                            vertices: Vec::new(),
                            edges: checkpoint.snapshot.candidate_edges.clone(),
                        },
                    ],
                    None,
                )
                .map_err(|error| StoreError::Query(error.to_string()))?;
            for entry in
                self.load_kernel_journal_after_with_engine(engine, checkpoint.meta.generation)?
            {
                if let Some(batch) = entry.batch {
                    kernel
                        .apply_batch(batch)
                        .map_err(|error| StoreError::Query(error.to_string()))?;
                }
            }
        } else {
            let batches = self
                .load_kernel_journal_after_with_engine(engine, 0)?
                .into_iter()
                .filter_map(|entry| entry.batch)
                .collect::<Vec<_>>();
            kernel
                .rebuild_from_kernel_batches(batches, None)
                .map_err(|error| StoreError::Query(error.to_string()))?;
        }

        let snapshot = kernel.snapshot().as_ref().clone();
        let replay_cost_us = replay_started.elapsed().as_micros() as u64;
        self.record_kernel_replay_cost_with_engine(engine, replay_cost_us)?;
        self.cache_live_kernel_snapshot(generation, snapshot.clone());
        Ok(snapshot)
    }

    fn ensure_scope_ord(
        &self,
        engine: &mut DatabaseEngine,
        scope_key: &str,
    ) -> Result<ScopeOrd, StoreError> {
        if let Some(node) = engine
            .get_node_by_key(TYPE_SCOPE_ORD, scope_key)
            .map_err(store_query_error)?
        {
            return Ok(ScopeOrd(required_u64_prop(&node, PROP_ORD)?));
        }

        let next = self.next_counter_value(engine, COUNTER_SCOPE, TYPE_SCOPE_ORD)? + 1;
        engine
            .upsert_node(
                TYPE_SCOPE_ORD,
                scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_ORD, PropValue::UInt(next)),
                        (PROP_SCOPE_KEY, PropValue::String(scope_key.to_owned())),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        self.set_counter_value(engine, COUNTER_SCOPE, next)?;
        Ok(ScopeOrd(next))
    }

    fn ensure_session_ord(
        &self,
        engine: &mut DatabaseEngine,
        session_id: &SessionId,
    ) -> Result<SessionOrd, StoreError> {
        if let Some(node) = engine
            .get_node_by_key(TYPE_SESSION_ORD, &session_id.0)
            .map_err(store_query_error)?
        {
            return Ok(SessionOrd(required_u64_prop(&node, PROP_ORD)?));
        }

        let next = self.next_counter_value(engine, COUNTER_SESSION, TYPE_SESSION_ORD)? + 1;
        engine
            .upsert_node(
                TYPE_SESSION_ORD,
                &session_id.0,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_ORD, PropValue::UInt(next)),
                        (PROP_SESSION_ID, PropValue::String(session_id.0.clone())),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        self.set_counter_value(engine, COUNTER_SESSION, next)?;
        Ok(SessionOrd(next))
    }

    fn ensure_document_ord(
        &self,
        engine: &mut DatabaseEngine,
        scope_key: &str,
        document_id: &str,
    ) -> Result<DocumentOrd, StoreError> {
        let value_key = document_value_key(scope_key, document_id);
        if let Some(node) = engine
            .get_node_by_key(TYPE_DOCUMENT_ORD, &value_key)
            .map_err(store_query_error)?
        {
            return Ok(DocumentOrd(required_u64_prop(&node, PROP_ORD)?));
        }

        let next = self.next_counter_value(engine, COUNTER_DOCUMENT, TYPE_DOCUMENT_ORD)? + 1;
        engine
            .upsert_node(
                TYPE_DOCUMENT_ORD,
                &value_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_ORD, PropValue::UInt(next)),
                        (PROP_SCOPE_KEY, PropValue::String(scope_key.to_owned())),
                        (PROP_DOCUMENT_ID, PropValue::String(document_id.to_owned())),
                        (
                            PROP_DOCUMENT_VALUE_KEY,
                            PropValue::String(value_key.clone()),
                        ),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        self.set_counter_value(engine, COUNTER_DOCUMENT, next)?;
        Ok(DocumentOrd(next))
    }

    fn next_counter_value(
        &self,
        engine: &mut DatabaseEngine,
        counter_key: &str,
        mapping_type: u32,
    ) -> Result<u64, StoreError> {
        if let Some(node) = engine
            .get_node_by_key(TYPE_COUNTER, counter_key)
            .map_err(store_query_error)?
        {
            return required_u64_prop(&node, PROP_VALUE);
        }

        let max_value = engine
            .get_nodes_by_type(mapping_type)
            .map_err(store_query_error)?
            .into_iter()
            .map(|node| optional_u64_prop(&node, PROP_ORD).unwrap_or_default())
            .max()
            .unwrap_or(0);
        self.set_counter_value(engine, counter_key, max_value)?;
        Ok(max_value)
    }

    fn set_counter_value(
        &self,
        engine: &mut DatabaseEngine,
        counter_key: &str,
        value: u64,
    ) -> Result<(), StoreError> {
        engine
            .upsert_node(
                TYPE_COUNTER,
                counter_key,
                UpsertNodeOptions {
                    props: btree_props([(PROP_VALUE, PropValue::UInt(value))]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn list_all_scopes_with_engine(
        &self,
        engine: &mut DatabaseEngine,
    ) -> Result<Vec<ScopeKey>, StoreError> {
        let mut scopes = engine
            .get_nodes_by_type(TYPE_SCOPE_ORD)
            .map_err(store_query_error)?
            .into_iter()
            .filter_map(|node| optional_string_prop(&node, PROP_SCOPE_KEY))
            .map(|scope_key| parse_scope_key(&scope_key))
            .collect::<Vec<_>>();
        scopes.sort_by_key(scope_storage_key);
        scopes.dedup_by(|left, right| scope_storage_key(left) == scope_storage_key(right));
        Ok(scopes)
    }

    fn load_document_manifest_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        document_ref: &DocumentRevisionRef,
    ) -> Result<Option<DocumentManifest>, StoreError> {
        let key = manifest_key(
            document_ref.scope_ord,
            document_ref.document_ord,
            document_ref.revision,
        );
        let Some(node) = engine
            .get_node_by_key(TYPE_DOCUMENT_MANIFEST, &key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        decode_record_prop(&node, PROP_RECORD)
    }

    fn load_latest_document_manifests_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: Option<&ScopeKey>,
    ) -> Result<Vec<DocumentManifest>, StoreError> {
        let scope_key = scope.map(scope_storage_key);
        let mut manifests = engine
            .get_nodes_by_type(TYPE_DOCUMENT_LATEST)
            .map_err(store_query_error)?
            .into_iter()
            .filter(|node| match scope_key.as_deref() {
                Some(expected) => {
                    optional_string_prop(node, PROP_SCOPE_KEY).as_deref() == Some(expected)
                }
                None => true,
            })
            .filter_map(|node| {
                decode_record_prop::<DocumentManifest>(&node, PROP_RECORD).transpose()
            })
            .collect::<Result<Vec<_>, _>>()?;
        manifests.sort_by(|left, right| left.document_id.cmp(&right.document_id));
        Ok(manifests)
    }

    fn load_latest_document_manifests_for_ords_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope_ord: ScopeOrd,
        document_ords: &[DocumentOrd],
    ) -> Result<Vec<DocumentManifest>, StoreError> {
        let mut manifests = Vec::<DocumentManifest>::new();
        for document_ord in document_ords {
            let latest_key = document_latest_key(scope_ord, *document_ord);
            let Some(node) = engine
                .get_node_by_key(TYPE_DOCUMENT_LATEST, &latest_key)
                .map_err(store_query_error)?
            else {
                continue;
            };
            if let Some(manifest) = decode_record_prop(&node, PROP_RECORD)? {
                manifests.push(manifest);
            }
        }
        manifests.sort_by(|left, right| left.document_id.cmp(&right.document_id));
        Ok(manifests)
    }

    fn load_document_manifest_by_bundle_key_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        key: &BundleKey,
    ) -> Result<Option<DocumentManifest>, StoreError> {
        let mut matches = engine
            .get_nodes_by_type(TYPE_DOCUMENT_MANIFEST)
            .map_err(store_query_error)?
            .into_iter()
            .filter_map(|node| {
                decode_record_prop::<DocumentManifest>(&node, PROP_RECORD).transpose()
            })
            .collect::<Result<Vec<_>, _>>()?
            .into_iter()
            .filter(|manifest| {
                manifest.scope_key == key.scope
                    && manifest.document_id == key.entity_key
                    && manifest.revision == key.revision
            })
            .collect::<Vec<_>>();
        matches.sort_by(|left, right| {
            left.scope_ord
                .0
                .cmp(&right.scope_ord.0)
                .then_with(|| left.document_ord.0.cmp(&right.document_ord.0))
        });
        Ok(matches.into_iter().next())
    }

    fn load_document_archive_from_manifest_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        manifest: &DocumentManifest,
    ) -> Result<DocumentArchive, StoreError> {
        let mut archive = DocumentArchive {
            manifest: manifest.clone(),
            ..Default::default()
        };
        let mut lexical = None::<LexicalPostingsSegment>;
        for segment_ref in &manifest.segment_refs {
            let key = segment_key(
                manifest.scope_ord,
                manifest.document_ord,
                manifest.revision,
                segment_ref.kind,
                segment_ref.ordinal,
            );
            let Some(node) = engine
                .get_node_by_key(TYPE_DOCUMENT_SEGMENT, &key)
                .map_err(store_query_error)?
            else {
                return Err(StoreError::Query(format!(
                    "missing segment {} for {}@{}",
                    key, manifest.document_id, manifest.revision
                )));
            };
            match segment_ref.kind {
                DocumentSegmentKind::StringArena => {
                    archive.tokens = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::SentenceTable => {
                    archive.sentences = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::MentionTable => {
                    archive.mentions = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::ResolverLinkTable => {
                    archive.resolver_links = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::ResolvedMentionTable => {
                    archive.resolved_mentions =
                        decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::AliasConfirmationTable => {
                    archive.alias_confirmations =
                        decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::CorefClusterTable => {
                    archive.coref_clusters = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::CausalSubstrateTable => {
                    archive.causal_substrate =
                        Some(decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::TemporalSubstrateTable => {
                    archive.temporal_substrate =
                        Some(decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::EventIdentitySubstrateTable => {
                    archive.event_identity_substrate =
                        Some(decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::ChunkTable => {
                    archive.chunks = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::EntityTable => {
                    archive.entities = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::RelationTable => {
                    archive.relations = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::EvidenceTable => {
                    archive.evidence_spans = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::LexicalPostings => {
                    lexical = Some(decode_segment_payload_from_node(&self.path, &node)?);
                }
                DocumentSegmentKind::NarrativeHitTable => {
                    archive.relation_candidates =
                        decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::GraphMutation => {
                    archive.graph_batch = decode_segment_payload_from_node(&self.path, &node)?;
                }
                DocumentSegmentKind::StructureRelations => {
                    archive.structure = Some(decode_segment_payload_from_node(&self.path, &node)?);
                }
                _ => {}
            }
        }
        if let Some(lexical) = lexical {
            archive.indexed_spans = lexical.spans;
        }
        Ok(archive)
    }

    fn load_native_session_archive_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        session_id: &SessionId,
    ) -> Result<Option<SessionArchive>, StoreError> {
        let Some(latest) = engine
            .get_node_by_key(TYPE_SESSION_LATEST, &session_id.0)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&latest, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_scope_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<ScopeLexSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_SCOPE_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_er_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<ErScopePatchSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_ER_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_relation_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<RelationScopePatchSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_RELATION_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_memory_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<MemoryScopeSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_MEMORY_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_graph_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<GraphScopeSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_GRAPH_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        match decode_archive(&payload) {
            Ok(sidecar) => Ok(Some(sidecar)),
            Err(_) => {
                engine.delete_node(node.id).map_err(store_query_error)?;
                Ok(None)
            }
        }
    }

    fn load_native_semantic_graph_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<SemanticGraphScopeSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_SEMANTIC_GRAPH_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_causal_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<CausalScopeSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_CAUSAL_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_temporal_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<TemporalScopeSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_TEMPORAL_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_event_identity_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<EventIdentityScopeSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_EVENT_IDENTITY_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_state_schema_patch_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<StateSchemaScopeSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_STATE_SCHEMA_PATCH_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_relation_mention_seed_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<Option<RelationMentionSeedScopeSidecar>, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(node) = engine
            .get_node_by_key(TYPE_RELATION_MENTION_SEED_SIDECAR, &scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        let payload = required_bytes_prop(&node, PROP_PAYLOAD)?;
        decode_archive(&payload).map(Some)
    }

    fn load_native_dirty_scope_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope_key: &str,
    ) -> Result<Option<DirtyScopeRecord>, StoreError> {
        let Some(node) = engine
            .get_node_by_key(TYPE_DIRTY_SCOPE, scope_key)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        decode_record_prop(&node, PROP_RECORD)
    }

    fn load_lexical_postings_from_manifest_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        manifest: &DocumentManifest,
    ) -> Result<LexicalPostingsSegment, StoreError> {
        let mut lexical = LexicalPostingsSegment::default();
        for segment_ref in manifest
            .segment_refs
            .iter()
            .filter(|segment_ref| segment_ref.kind == DocumentSegmentKind::LexicalPostings)
        {
            let key = segment_key(
                manifest.scope_ord,
                manifest.document_ord,
                manifest.revision,
                segment_ref.kind,
                segment_ref.ordinal,
            );
            let Some(node) = engine
                .get_node_by_key(TYPE_DOCUMENT_SEGMENT, &key)
                .map_err(store_query_error)?
            else {
                return Err(StoreError::Query(format!(
                    "missing lexical segment {} for {}@{}",
                    key, manifest.document_id, manifest.revision
                )));
            };
            let mut decoded: LexicalPostingsSegment =
                decode_segment_payload_from_node(&self.path, &node)?;
            lexical.spans.append(&mut decoded.spans);
            lexical.alias_entries.append(&mut decoded.alias_entries);
        }
        Ok(lexical)
    }

    fn materialize_scope_lexical_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
    ) -> Result<ScopeLexSidecar, StoreError> {
        let scope_key = scope_storage_key(scope);
        let Some(scope_ord) = engine
            .get_node_by_key(TYPE_SCOPE_ORD, &scope_key)
            .map_err(store_query_error)?
            .map(|node| ScopeOrd(optional_u64_prop(&node, PROP_ORD).unwrap_or_default()))
        else {
            return Ok(ScopeLexSidecar {
                scope: scope.clone(),
                scope_key,
                ..Default::default()
            });
        };
        let persisted = self.load_native_scope_sidecar_with_engine(engine, scope)?;
        let dirty = self.load_native_dirty_scope_with_engine(engine, &scope_key)?;
        if dirty.is_none() {
            if let Some(sidecar) = persisted {
                return Ok(sidecar);
            }
        }
        self.aggregate_scope_sidecar_with_engine(
            engine,
            scope,
            scope_ord,
            persisted,
            dirty.as_ref(),
        )
    }

    fn aggregate_scope_sidecar_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        scope: &ScopeKey,
        scope_ord: ScopeOrd,
        persisted: Option<ScopeLexSidecar>,
        dirty: Option<&DirtyScopeRecord>,
    ) -> Result<ScopeLexSidecar, StoreError> {
        let had_persisted = persisted.is_some();
        let scope_key = scope_storage_key(scope);
        let mut sidecar = persisted.unwrap_or_else(|| ScopeLexSidecar {
            scope: scope.clone(),
            scope_key: scope_key.clone(),
            scope_ord: Some(scope_ord),
            ..Default::default()
        });
        sidecar.scope = scope.clone();
        sidecar.scope_key = scope_key.clone();
        sidecar.scope_ord = Some(scope_ord);

        let mut generation = sidecar.generation;
        let dirty_manifests = if let Some(record) = dirty {
            if !had_persisted {
                let manifests =
                    self.load_latest_document_manifests_with_engine(engine, Some(scope))?;
                generation = generation.max(record.updated_at as u64);
                manifests
            } else {
                let manifests = self.load_latest_document_manifests_for_ords_with_engine(
                    engine,
                    record.scope_ord,
                    &record.document_ords,
                )?;
                let dirty_document_ids = manifests
                    .iter()
                    .map(|manifest| manifest.document_id.clone())
                    .collect::<BTreeSet<_>>();
                if !dirty_document_ids.is_empty() {
                    sidecar.spans.retain(|span| {
                        span.document_id
                            .as_ref()
                            .map(|document_id| !dirty_document_ids.contains(&document_id.0))
                            .unwrap_or(true)
                    });
                    sidecar
                        .document_ids
                        .retain(|document_id| !dirty_document_ids.contains(document_id));
                    sidecar.alias_entries =
                        filter_alias_entries(&sidecar.alias_entries, &dirty_document_ids);
                }
                generation = generation.max(record.updated_at as u64);
                manifests
            }
        } else {
            self.load_latest_document_manifests_with_engine(engine, Some(scope))?
        };

        let mut alias_entries = alias_entries_to_map(&sidecar.alias_entries);
        for manifest in &dirty_manifests {
            let lexical = self.load_lexical_postings_from_manifest_with_engine(engine, manifest)?;
            generation = generation.max(manifest.revision);
            sidecar.document_ids.push(manifest.document_id.clone());
            sidecar.spans.extend(lexical.spans);
            merge_alias_entries(&mut alias_entries, &lexical.alias_entries);
        }

        sidecar.document_ids.sort();
        sidecar.document_ids.dedup();
        sidecar
            .spans
            .sort_by(|left, right| left.span_id.cmp(&right.span_id));
        sidecar
            .spans
            .dedup_by(|left, right| left.span_id == right.span_id);
        sidecar.alias_entries = alias_entries_from_map(alias_entries);
        sidecar.entity_count = entity_count_from_alias_entries(&sidecar.alias_entries);
        sidecar.generated_at = now_ms();
        sidecar.generation = generation;
        Ok(sidecar)
    }

    fn persist_session_archive_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        archive: &SessionArchive,
        revision: u64,
    ) -> Result<(), StoreError> {
        let session_ord = match archive.session_ord {
            Some(session_ord) => session_ord,
            None => self.ensure_session_ord(engine, &archive.session_id)?,
        };
        let mut archived = archive.clone();
        archived.session_ord = Some(session_ord);
        let payload = encode_archive(&archived)?;
        let exact_key = session_archive_key(&archived.session_id, revision);
        engine
            .upsert_node(
                TYPE_SESSION_ARCHIVE,
                &exact_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (
                            PROP_SESSION_ID,
                            PropValue::String(archived.session_id.0.clone()),
                        ),
                        (PROP_SESSION_ORD, PropValue::UInt(session_ord.0)),
                        (PROP_REVISION, PropValue::UInt(revision)),
                        (PROP_UPDATED_AT, PropValue::Int(archived.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload.clone())),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        engine
            .upsert_node(
                TYPE_SESSION_LATEST,
                &archived.session_id.0,
                UpsertNodeOptions {
                    props: btree_props([
                        (
                            PROP_SESSION_ID,
                            PropValue::String(archived.session_id.0.clone()),
                        ),
                        (PROP_SESSION_ORD, PropValue::UInt(session_ord.0)),
                        (PROP_REVISION, PropValue::UInt(revision)),
                        (PROP_UPDATED_AT, PropValue::Int(archived.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_scope_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &ScopeLexSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_SCOPE_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_CREATED_AT, PropValue::Int(sidecar.generated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        self.invalidate_scope_lexical_query_cache(&sidecar.scope_key)?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn persist_er_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &ErScopePatchSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_ER_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_relation_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &RelationScopePatchSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_RELATION_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_relation_mention_seed_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &RelationMentionSeedScopeSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_RELATION_MENTION_SEED_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_memory_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &MemoryScopeSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_MEMORY_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_graph_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &GraphScopeSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_GRAPH_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_semantic_graph_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &SemanticGraphScopeSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_SEMANTIC_GRAPH_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_causal_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &CausalScopeSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_CAUSAL_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_temporal_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &TemporalScopeSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_TEMPORAL_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_event_identity_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &EventIdentityScopeSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_EVENT_IDENTITY_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn persist_state_schema_patch_sidecar_native_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        sidecar: &StateSchemaScopeSidecar,
    ) -> Result<(), StoreError> {
        let payload = encode_archive(sidecar)?;
        engine
            .upsert_node(
                TYPE_STATE_SCHEMA_PATCH_SIDECAR,
                &sidecar.scope_key,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(sidecar.scope_key.clone())),
                        (
                            PROP_SCOPE_ORD,
                            sidecar
                                .scope_ord
                                .map(|scope_ord| PropValue::UInt(scope_ord.0))
                                .unwrap_or(PropValue::Null),
                        ),
                        (
                            PROP_SESSION_ID,
                            sidecar
                                .session_id
                                .as_ref()
                                .map(|session_id| PropValue::String(session_id.0.clone()))
                                .unwrap_or(PropValue::Null),
                        ),
                        (PROP_REVISION, PropValue::UInt(sidecar.generation)),
                        (PROP_UPDATED_AT, PropValue::Int(sidecar.updated_at)),
                        (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                        (PROP_PAYLOAD, PropValue::Bytes(payload)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn list_native_bundle_headers_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        kind: BundleKind,
        scope: Option<&str>,
    ) -> Result<Vec<BundleHeader>, StoreError> {
        let mut headers = match kind {
            BundleKind::DocumentArchive => engine
                .get_nodes_by_type(TYPE_DOCUMENT_MANIFEST)
                .map_err(store_query_error)?
                .into_iter()
                .filter_map(|node| {
                    decode_record_prop::<DocumentManifest>(&node, PROP_RECORD).transpose()
                })
                .collect::<Result<Vec<_>, _>>()?
                .into_iter()
                .filter(|manifest| {
                    scope
                        .map(|value| value == manifest.scope_key)
                        .unwrap_or(true)
                })
                .map(|manifest| native_document_header_from_manifest(&manifest))
                .collect::<Vec<_>>(),
            BundleKind::SessionArchive => engine
                .get_nodes_by_type(TYPE_SESSION_ARCHIVE)
                .map_err(store_query_error)?
                .into_iter()
                .filter(|node| {
                    scope
                        .map(|value| {
                            optional_string_prop(node, PROP_SESSION_ID).as_deref() == Some(value)
                        })
                        .unwrap_or(true)
                })
                .map(native_session_header_from_node)
                .collect::<Result<Vec<_>, _>>()?,
            BundleKind::ScopeLexSidecar => engine
                .get_nodes_by_type(TYPE_SCOPE_SIDECAR)
                .map_err(store_query_error)?
                .into_iter()
                .filter(|node| {
                    scope
                        .map(|value| {
                            optional_string_prop(node, PROP_SCOPE_KEY).as_deref() == Some(value)
                        })
                        .unwrap_or(true)
                })
                .map(native_sidecar_header_from_node)
                .collect::<Result<Vec<_>, _>>()?,
        };
        headers.sort_by(|left, right| {
            left.key
                .scope
                .cmp(&right.key.scope)
                .then_with(|| left.key.entity_key.cmp(&right.key.entity_key))
                .then_with(|| left.key.revision.cmp(&right.key.revision))
        });
        Ok(headers)
    }

    fn list_compat_bundle_headers_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        kind: BundleKind,
        scope: Option<&str>,
    ) -> Result<Vec<BundleHeader>, StoreError> {
        let kind_name = bundle_kind_name(kind);
        let mut headers = engine
            .get_nodes_by_type(TYPE_COMPAT_BUNDLE)
            .map_err(store_query_error)?
            .into_iter()
            .filter(|node| optional_string_prop(node, PROP_KIND).as_deref() == Some(kind_name))
            .filter(|node| {
                scope
                    .map(|value| {
                        optional_string_prop(node, PROP_SCOPE_KEY).as_deref() == Some(value)
                    })
                    .unwrap_or(true)
            })
            .map(compat_header_from_node)
            .collect::<Result<Vec<_>, _>>()?;
        headers.sort_by(|left, right| {
            left.key
                .scope
                .cmp(&right.key.scope)
                .then_with(|| left.key.entity_key.cmp(&right.key.entity_key))
                .then_with(|| left.key.revision.cmp(&right.key.revision))
        });
        Ok(headers)
    }

    fn load_kernel_checkpoint_with_engine(
        &self,
        engine: &mut DatabaseEngine,
    ) -> Result<Option<KernelCheckpointData>, StoreError> {
        let Some(node) = engine
            .get_node_by_key(TYPE_KERNEL_CHECKPOINT, KERNEL_CHECKPOINT_KEY)
            .map_err(store_query_error)?
        else {
            return Ok(None);
        };
        decode_record_prop(&node, PROP_RECORD)
    }

    fn kernel_checkpoint_policy(&self) -> KernelCheckpointPolicy {
        KernelCheckpointPolicy {
            max_hot_journal_bytes: self.tuning.kernel_checkpoint_hot_journal_bytes,
            max_measured_replay_cost_us: self.tuning.kernel_checkpoint_replay_cost_us,
        }
    }

    fn kernel_current_generation_with_engine(
        &self,
        engine: &mut DatabaseEngine,
    ) -> Result<u64, StoreError> {
        let Some(node) = engine
            .get_node_by_key(TYPE_KERNEL_STATE, KERNEL_STATE_KEY)
            .map_err(store_query_error)?
        else {
            return Ok(0);
        };
        Ok(optional_u64_prop(&node, PROP_GENERATION).unwrap_or(0))
    }

    fn kernel_journal_len_with_engine(
        &self,
        engine: &mut DatabaseEngine,
    ) -> Result<usize, StoreError> {
        let Some(node) = engine
            .get_node_by_key(TYPE_KERNEL_STATE, KERNEL_STATE_KEY)
            .map_err(store_query_error)?
        else {
            return Ok(0);
        };
        Ok(optional_u64_prop(&node, PROP_JOURNAL_LEN).unwrap_or(0) as usize)
    }

    fn kernel_journal_bytes_with_engine(
        &self,
        engine: &mut DatabaseEngine,
    ) -> Result<usize, StoreError> {
        let Some(node) = engine
            .get_node_by_key(TYPE_KERNEL_STATE, KERNEL_STATE_KEY)
            .map_err(store_query_error)?
        else {
            return Ok(0);
        };
        Ok(optional_u64_prop(&node, PROP_JOURNAL_BYTES).unwrap_or(0) as usize)
    }

    fn kernel_replay_cost_us_with_engine(
        &self,
        engine: &mut DatabaseEngine,
    ) -> Result<u64, StoreError> {
        let Some(node) = engine
            .get_node_by_key(TYPE_KERNEL_STATE, KERNEL_STATE_KEY)
            .map_err(store_query_error)?
        else {
            return Ok(0);
        };
        Ok(optional_u64_prop(&node, PROP_REPLAY_COST_US).unwrap_or(0))
    }

    fn upsert_kernel_state_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        generation: u64,
        journal_len: usize,
        journal_bytes: usize,
        replay_cost_us: u64,
    ) -> Result<(), StoreError> {
        engine
            .upsert_node(
                TYPE_KERNEL_STATE,
                KERNEL_STATE_KEY,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_GENERATION, PropValue::UInt(generation)),
                        (PROP_JOURNAL_LEN, PropValue::UInt(journal_len as u64)),
                        (PROP_JOURNAL_BYTES, PropValue::UInt(journal_bytes as u64)),
                        (PROP_REPLAY_COST_US, PropValue::UInt(replay_cost_us)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        Ok(())
    }

    fn record_kernel_replay_cost_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        replay_cost_us: u64,
    ) -> Result<(), StoreError> {
        let generation = self.kernel_current_generation_with_engine(engine)?;
        let journal_len = self.kernel_journal_len_with_engine(engine)?;
        let journal_bytes = self.kernel_journal_bytes_with_engine(engine)?;
        if generation == 0 && journal_len == 0 && journal_bytes == 0 {
            return Ok(());
        }
        self.upsert_kernel_state_with_engine(
            engine,
            generation,
            journal_len,
            journal_bytes,
            replay_cost_us,
        )
    }

    fn maybe_checkpoint_kernel_journal_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        source_revision: &str,
    ) -> Result<KernelCheckpointDecision, StoreError> {
        let input = KernelCheckpointPolicyInput {
            hot_journal_bytes: self.kernel_journal_bytes_with_engine(engine)?,
            measured_replay_cost_us: self.kernel_replay_cost_us_with_engine(engine)?,
        };
        let decision = self.kernel_checkpoint_policy().decide(input);
        if decision == KernelCheckpointDecision::KeepJournalHot {
            return Ok(decision);
        }
        let generation = self.kernel_current_generation_with_engine(engine)?;
        if generation == 0 {
            return Ok(KernelCheckpointDecision::KeepJournalHot);
        }
        let snapshot = self.load_live_kernel_snapshot_with_engine(engine)?;
        self.write_kernel_checkpoint_with_engine(engine, generation, source_revision, &snapshot)?;
        Ok(decision)
    }

    fn write_kernel_checkpoint_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        generation: u64,
        source_revision: &str,
        snapshot: &KernelGraphSnapshot,
    ) -> Result<KernelCheckpointData, StoreError> {
        let discovery_source =
            self.prepare_discovery_source_cache(generation, source_revision, snapshot)?;
        let checkpoint = KernelCheckpointData {
            meta: KernelCheckpointMeta {
                checkpoint_id: format!("kernel-checkpoint-{generation}"),
                generation,
                source_revision: source_revision.to_owned(),
                created_at: now_ms(),
            },
            snapshot: snapshot.clone(),
        };
        engine
            .upsert_node(
                TYPE_KERNEL_CHECKPOINT,
                KERNEL_CHECKPOINT_KEY,
                UpsertNodeOptions {
                    props: btree_props([
                        (PROP_GENERATION, PropValue::UInt(generation)),
                        (
                            PROP_SOURCE_REVISION,
                            PropValue::String(source_revision.to_owned()),
                        ),
                        (
                            PROP_DISCOVERY_SOURCE_CACHE_SCHEMA,
                            PropValue::String(discovery_source_cache::CACHE_SCHEMA.to_owned()),
                        ),
                        (PROP_CREATED_AT, PropValue::Int(checkpoint.meta.created_at)),
                        (PROP_RECORD, PropValue::Bytes(encode_record(&checkpoint)?)),
                    ]),
                    ..Default::default()
                },
            )
            .map_err(store_query_error)?;
        self.compact_kernel_journal_with_engine(engine, generation)?;
        self.publish_kernel_topology_with_engine(engine, snapshot)?;
        self.install_discovery_source_cache(&discovery_source)?;
        self.cache_live_kernel_snapshot(generation, snapshot.clone());
        Ok(checkpoint)
    }

    fn load_kernel_journal_after_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        generation: u64,
    ) -> Result<Vec<KernelJournalEntry>, StoreError> {
        let mut entries = engine
            .get_nodes_by_type(TYPE_KERNEL_JOURNAL)
            .map_err(store_query_error)?
            .into_iter()
            .filter(|node| {
                optional_u64_prop(node, PROP_GENERATION).unwrap_or_default() > generation
            })
            .filter_map(|node| {
                decode_record_prop::<KernelJournalEntry>(&node, PROP_RECORD).transpose()
            })
            .collect::<Result<Vec<_>, _>>()?;
        entries.sort_by(|left, right| {
            left.generation
                .cmp(&right.generation)
                .then_with(|| left.created_at.cmp(&right.created_at))
        });
        for entry in &mut entries {
            graph_truth_persistence::hydrate_graph_truth_journal_entry(engine, entry)?;
        }
        Ok(entries)
    }

    fn compact_kernel_journal_with_engine(
        &self,
        engine: &mut DatabaseEngine,
        generation: u64,
    ) -> Result<(), StoreError> {
        let nodes = engine
            .get_nodes_by_type(TYPE_KERNEL_JOURNAL)
            .map_err(store_query_error)?;
        let mut remaining = 0usize;
        for node in nodes {
            let node_generation = optional_u64_prop(&node, PROP_GENERATION).unwrap_or_default();
            if node_generation <= generation {
                engine.delete_node(node.id).map_err(store_query_error)?;
            } else {
                remaining += 1;
            }
        }
        let current_generation = self
            .kernel_current_generation_with_engine(engine)?
            .max(generation);
        self.upsert_kernel_state_with_engine(engine, current_generation, remaining, 0, 0)
    }
}

impl PhoenixNativeRowStore for PhoenixOvergraphStore {
    fn init_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn relation_names(&self) -> Vec<&'static str> {
        ALL_RELATIONS.iter().map(|spec| spec.name).collect()
    }

    fn relation_counts(&self) -> Result<Vec<(String, usize)>, StoreError> {
        self.with_engine(|engine| {
            let mut counts = BTreeMap::<String, usize>::new();
            for node in engine
                .get_nodes_by_type(TYPE_NATIVE_ROW)
                .map_err(store_query_error)?
            {
                if let Some(relation) = optional_string_prop(&node, PROP_KIND) {
                    *counts.entry(relation).or_default() += 1;
                }
            }
            Ok(counts.into_iter().collect())
        })
    }

    fn fetch_rows(&self, relation: &str) -> Result<Vec<Value>, StoreError> {
        relation_spec(relation)?;
        self.with_engine(|engine| {
            let mut nodes = engine
                .get_nodes_by_type(TYPE_NATIVE_ROW)
                .map_err(store_query_error)?
                .into_iter()
                .filter(|node| optional_string_prop(node, PROP_KIND).as_deref() == Some(relation))
                .collect::<Vec<_>>();
            nodes.sort_by(|left, right| left.key.cmp(&right.key));
            nodes
                .into_iter()
                .map(|node| decode_record_prop_required::<Value>(&node, PROP_RECORD))
                .collect()
        })
    }

    fn put_row(&self, relation: &str, row: Value) -> Result<(), StoreError> {
        let key = native_row_storage_key(relation, &row)?;
        self.with_engine(|engine| {
            engine
                .upsert_node(
                    TYPE_NATIVE_ROW,
                    &key,
                    UpsertNodeOptions {
                        props: btree_props([
                            (PROP_KIND, PropValue::String(relation.to_owned())),
                            (PROP_UPDATED_AT, PropValue::Int(now_ms())),
                            (PROP_RECORD, PropValue::Bytes(encode_record(&row)?)),
                        ]),
                        ..Default::default()
                    },
                )
                .map_err(store_query_error)?;
            Ok(())
        })
    }

    fn put_rows(&self, relation: &str, rows: &[Value]) -> Result<(), StoreError> {
        if rows.is_empty() {
            relation_spec(relation)?;
            return Ok(());
        }
        let updated_at = now_ms();
        let mut inputs = Vec::with_capacity(rows.len());
        for row in rows {
            inputs.push(NodeInput {
                type_id: TYPE_NATIVE_ROW,
                key: native_row_storage_key(relation, row)?,
                props: btree_props([
                    (PROP_KIND, PropValue::String(relation.to_owned())),
                    (PROP_UPDATED_AT, PropValue::Int(updated_at)),
                    (PROP_RECORD, PropValue::Bytes(encode_record(row)?)),
                ]),
                weight: 1.0,
                dense_vector: None,
                sparse_vector: None,
            });
        }
        self.with_engine(|engine| self.batch_upsert_nodes_with_engine(engine, inputs))
    }

    fn replace_relation_rows(&self, relation: &str, rows: &[Value]) -> Result<(), StoreError> {
        self.clear_relations(&[relation])?;
        self.put_rows(relation, rows)
    }

    fn delete_rows(&self, relation: &str, rows: &[Value]) -> Result<usize, StoreError> {
        relation_spec(relation)?;
        if rows.is_empty() {
            return Ok(0);
        }
        let keys = rows
            .iter()
            .map(|row| native_row_storage_key(relation, row))
            .collect::<Result<BTreeSet<_>, _>>()?;
        self.with_engine(|engine| {
            let mut removed = 0;
            for key in keys {
                let Some(node) = engine
                    .get_node_by_key(TYPE_NATIVE_ROW, &key)
                    .map_err(store_query_error)?
                else {
                    continue;
                };
                engine.delete_node(node.id).map_err(store_query_error)?;
                removed += 1;
            }
            Ok(removed)
        })
    }

    fn clear_relations(&self, relations: &[&str]) -> Result<(), StoreError> {
        let targets = relations.iter().copied().collect::<BTreeSet<_>>();
        for relation in &targets {
            relation_spec(relation)?;
        }
        self.with_engine(|engine| {
            let nodes = engine
                .get_nodes_by_type(TYPE_NATIVE_ROW)
                .map_err(store_query_error)?;
            for node in nodes {
                if optional_string_prop(&node, PROP_KIND)
                    .as_deref()
                    .map(|relation| targets.contains(relation))
                    .unwrap_or(false)
                {
                    engine.delete_node(node.id).map_err(store_query_error)?;
                }
            }
            Ok(())
        })
    }

    fn export_snapshot_partition(
        &self,
        partition: SnapshotPartition,
    ) -> Result<Vec<u8>, StoreError> {
        let mut relations = BTreeMap::new();
        for relation in snapshot_relations_for_partition(partition) {
            let rows = self.fetch_rows(relation)?;
            if !rows.is_empty() {
                relations.insert((*relation).to_owned(), rows);
            }
        }
        let envelope = SnapshotEnvelope {
            schema_version: "overgraph-native-row-v1".to_owned(),
            relation_count: relations.len(),
            created_at: now_ms(),
            relations,
            checksum: None,
        };
        serde_json::to_vec(&envelope).map_err(|error| StoreError::Snapshot(error.to_string()))
    }

    fn import_snapshot(&self, bytes: &[u8]) -> Result<SnapshotEnvelope, StoreError> {
        let envelope = serde_json::from_slice::<SnapshotEnvelope>(bytes)
            .map_err(|error| StoreError::Snapshot(error.to_string()))?;
        for (relation, rows) in &envelope.relations {
            self.replace_relation_rows(relation, rows)?;
        }
        Ok(envelope)
    }
}

impl Drop for PhoenixOvergraphStore {
    fn drop(&mut self) {
        if let Ok(Some(engine)) = self.take_engine() {
            let _ = engine.close_fast();
        }
    }
}

impl PhoenixBundleStoreV2 for PhoenixOvergraphStore {
    fn init_bundle_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn put_bundle(&self, header: &BundleHeader, payload: &[u8]) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            engine
                .upsert_node(
                    TYPE_COMPAT_BUNDLE,
                    &bundle_storage_key(&header.key),
                    UpsertNodeOptions {
                        props: btree_props([
                            (
                                PROP_KIND,
                                PropValue::String(bundle_kind_name(header.key.kind).to_owned()),
                            ),
                            (PROP_SCOPE_KEY, PropValue::String(header.key.scope.clone())),
                            (
                                PROP_ENTITY_KEY,
                                PropValue::String(header.key.entity_key.clone()),
                            ),
                            (PROP_REVISION, PropValue::UInt(header.key.revision)),
                            (PROP_CREATED_AT, PropValue::Int(header.created_at)),
                            (PROP_BYTE_LEN, PropValue::UInt(payload.len() as u64)),
                            (PROP_PAYLOAD, PropValue::Bytes(payload.to_vec())),
                        ]),
                        ..Default::default()
                    },
                )
                .map_err(store_query_error)?;
            Ok(())
        })
    }

    fn get_bundle(&self, key: &BundleKey) -> Result<Option<Vec<u8>>, StoreError> {
        self.with_engine(|engine| {
            if let Some(node) = engine
                .get_node_by_key(TYPE_COMPAT_BUNDLE, &bundle_storage_key(key))
                .map_err(store_query_error)?
            {
                return Ok(Some(required_bytes_prop(&node, PROP_PAYLOAD)?));
            }
            match key.kind {
                BundleKind::DocumentArchive => {
                    let Some(manifest) =
                        self.load_document_manifest_by_bundle_key_with_engine(engine, key)?
                    else {
                        return Ok(None);
                    };
                    let archive =
                        self.load_document_archive_from_manifest_with_engine(engine, &manifest)?;
                    Ok(Some(encode_archive(&archive)?))
                }
                BundleKind::SessionArchive => {
                    let Some(node) = engine
                        .get_node_by_key(
                            TYPE_SESSION_ARCHIVE,
                            &session_archive_key_from_bundle(key),
                        )
                        .map_err(store_query_error)?
                    else {
                        return Ok(None);
                    };
                    Ok(Some(required_bytes_prop(&node, PROP_PAYLOAD)?))
                }
                BundleKind::ScopeLexSidecar => {
                    let Some(node) = engine
                        .get_node_by_key(TYPE_SCOPE_SIDECAR, &key.scope)
                        .map_err(store_query_error)?
                    else {
                        return Ok(None);
                    };
                    Ok(Some(required_bytes_prop(&node, PROP_PAYLOAD)?))
                }
            }
        })
    }

    fn get_bundle_header(&self, key: &BundleKey) -> Result<Option<BundleHeader>, StoreError> {
        self.with_engine(|engine| {
            if let Some(node) = engine
                .get_node_by_key(TYPE_COMPAT_BUNDLE, &bundle_storage_key(key))
                .map_err(store_query_error)?
            {
                return compat_header_from_node(node).map(Some);
            }
            match key.kind {
                BundleKind::DocumentArchive => {
                    let Some(manifest) =
                        self.load_document_manifest_by_bundle_key_with_engine(engine, key)?
                    else {
                        return Ok(None);
                    };
                    Ok(Some(native_document_header_from_manifest(&manifest)))
                }
                BundleKind::SessionArchive => Ok(engine
                    .get_node_by_key(TYPE_SESSION_ARCHIVE, &session_archive_key_from_bundle(key))
                    .map_err(store_query_error)?
                    .map(native_session_header_from_node)
                    .transpose()?),
                BundleKind::ScopeLexSidecar => Ok(engine
                    .get_node_by_key(TYPE_SCOPE_SIDECAR, &key.scope)
                    .map_err(store_query_error)?
                    .map(native_sidecar_header_from_node)
                    .transpose()?),
            }
        })
    }

    fn list_bundle_headers(
        &self,
        kind: BundleKind,
        scope: Option<&str>,
    ) -> Result<Vec<BundleHeader>, StoreError> {
        self.with_engine(|engine| {
            let mut by_storage_key = BTreeMap::<String, BundleHeader>::new();
            for header in self.list_native_bundle_headers_with_engine(engine, kind, scope)? {
                by_storage_key.insert(bundle_storage_key(&header.key), header);
            }
            for header in self.list_compat_bundle_headers_with_engine(engine, kind, scope)? {
                by_storage_key.insert(bundle_storage_key(&header.key), header);
            }
            Ok(by_storage_key.into_values().collect())
        })
    }

    fn delete_bundle(&self, key: &BundleKey) -> Result<bool, StoreError> {
        self.with_engine(|engine| {
            let Some(node) = engine
                .get_node_by_key(TYPE_COMPAT_BUNDLE, &bundle_storage_key(key))
                .map_err(store_query_error)?
            else {
                return Ok(false);
            };
            engine.delete_node(node.id).map_err(store_query_error)?;
            Ok(true)
        })
    }
}

impl PhoenixOvergraphStore {
    fn persist_prepared_documents_native_with_telemetry(
        &self,
        prepared: &[PreparedDocument],
        session_archive: Option<&SessionArchive>,
        touched_scopes: &[DirtyScopeRecord],
    ) -> Result<PreparedDocumentPersistTelemetry, StoreError> {
        let total_started = std::time::Instant::now();
        let mut telemetry = PreparedDocumentPersistTelemetry {
            document_count: prepared.len(),
            dirty_scope_count: touched_scopes.len(),
            ..PreparedDocumentPersistTelemetry::default()
        };
        for document in prepared {
            let Some(shard) = document.document_index_shard.as_ref() else {
                continue;
            };
            let started = std::time::Instant::now();
            let write = persist_document_index_shard(&self.path, shard)
                .map_err(|error| StoreError::Snapshot(error.to_string()))?;
            telemetry.document_index_shard_count += 1;
            telemetry.document_index_bytes += write.bytes;
            telemetry.document_index_write_us += started.elapsed().as_micros() as u64;
            if write.wrote {
                telemetry.document_index_shards_written += 1;
            } else {
                telemetry.document_index_shards_reused += 1;
            }
        }
        self.with_engine(|engine| {
            let mut batch = Vec::<NodeInput>::new();
            for document in prepared {
                let started = std::time::Instant::now();
                let manifest_key = manifest_key(
                    document.manifest.scope_ord,
                    document.manifest.document_ord,
                    document.manifest.revision,
                );
                let manifest_bytes = encode_record(&document.manifest)?;
                let segment_byte_len = document
                    .segments
                    .iter()
                    .map(|segment| segment.payload.len())
                    .sum::<usize>() as u64;
                let manifest_props = btree_props([
                    (
                        PROP_SCOPE_KEY,
                        PropValue::String(document.manifest.scope_key.clone()),
                    ),
                    (
                        PROP_SCOPE_ORD,
                        PropValue::UInt(document.manifest.scope_ord.0),
                    ),
                    (
                        PROP_DOCUMENT_ID,
                        PropValue::String(document.manifest.document_id.clone()),
                    ),
                    (
                        PROP_DOCUMENT_ORD,
                        PropValue::UInt(document.manifest.document_ord.0),
                    ),
                    (PROP_REVISION, PropValue::UInt(document.manifest.revision)),
                    (PROP_BYTE_LEN, PropValue::UInt(segment_byte_len)),
                    (
                        PROP_CREATED_AT,
                        PropValue::Int(document.manifest.created_at),
                    ),
                    (PROP_RECORD, PropValue::Bytes(manifest_bytes.clone())),
                ]);
                telemetry.manifest_record_bytes += manifest_bytes.len();
                telemetry.manifest_stored_bytes += manifest_bytes.len() * 2;
                batch.push(NodeInput {
                    type_id: TYPE_DOCUMENT_MANIFEST,
                    key: manifest_key,
                    props: manifest_props.clone(),
                    weight: 1.0,
                    dense_vector: None,
                    sparse_vector: None,
                });
                batch.push(NodeInput {
                    type_id: TYPE_DOCUMENT_LATEST,
                    key: document_latest_key(
                        document.manifest.scope_ord,
                        document.manifest.document_ord,
                    ),
                    props: manifest_props,
                    weight: 1.0,
                    dense_vector: None,
                    sparse_vector: None,
                });
                if let Some(shard) = document.document_index_shard.as_ref() {
                    let reference_bytes = encode_record(&shard.reference)?;
                    let reference_props = btree_props([
                        (
                            PROP_DOCUMENT_ID,
                            PropValue::String(document.manifest.document_id.clone()),
                        ),
                        (
                            PROP_SCOPE_ORD,
                            PropValue::UInt(document.manifest.scope_ord.0),
                        ),
                        (
                            PROP_DOCUMENT_ORD,
                            PropValue::UInt(document.manifest.document_ord.0),
                        ),
                        (PROP_REVISION, PropValue::UInt(document.manifest.revision)),
                        (PROP_BYTE_LEN, PropValue::UInt(shard.reference.byte_len)),
                        (PROP_RECORD, PropValue::Bytes(reference_bytes)),
                    ]);
                    batch.push(NodeInput {
                        type_id: TYPE_DOCUMENT_INDEX_SHARD,
                        key: shard.reference.content_hash.clone(),
                        props: reference_props.clone(),
                        weight: 1.0,
                        dense_vector: None,
                        sparse_vector: None,
                    });
                    batch.push(NodeInput {
                        type_id: TYPE_DOCUMENT_INDEX_LATEST,
                        key: document_latest_key(
                            document.manifest.scope_ord,
                            document.manifest.document_ord,
                        ),
                        props: reference_props,
                        weight: 1.0,
                        dense_vector: None,
                        sparse_vector: None,
                    });
                }
                telemetry.manifest_prepare_us += started.elapsed().as_micros() as u64;

                for segment in &document.segments {
                    let payload_write_started = std::time::Instant::now();
                    let payload_ref = prepared_segment_payload::write_segment_payload(
                        &self.path,
                        document.manifest.scope_ord.0,
                        document.manifest.document_ord.0,
                        document.manifest.revision,
                        segment.header.kind().as_u8(),
                        segment.header.ordinal,
                        &segment.payload,
                    )?;
                    let payload_write_us = payload_write_started.elapsed().as_micros() as u64;
                    let started = std::time::Instant::now();
                    let key = segment_key(
                        document.manifest.scope_ord,
                        document.manifest.document_ord,
                        document.manifest.revision,
                        segment.header.kind(),
                        segment.header.ordinal,
                    );
                    batch.push(NodeInput {
                        type_id: TYPE_DOCUMENT_SEGMENT,
                        key,
                        props: btree_props([
                            (
                                PROP_SCOPE_ORD,
                                PropValue::UInt(document.manifest.scope_ord.0),
                            ),
                            (
                                PROP_DOCUMENT_ORD,
                                PropValue::UInt(document.manifest.document_ord.0),
                            ),
                            (PROP_REVISION, PropValue::UInt(document.manifest.revision)),
                            (
                                PROP_KIND,
                                PropValue::String(
                                    segment_kind_name(segment.header.kind()).to_owned(),
                                ),
                            ),
                            (
                                PROP_GENERATION_HINT,
                                PropValue::UInt(segment.header.ordinal as u64),
                            ),
                            (PROP_BYTE_LEN, PropValue::UInt(segment.payload.len() as u64)),
                            (
                                PROP_PAYLOAD_PATH,
                                PropValue::String(payload_ref.relative_path.clone()),
                            ),
                        ]),
                        weight: 1.0,
                        dense_vector: None,
                        sparse_vector: None,
                    });
                    let prepare_us = started.elapsed().as_micros() as u64;
                    telemetry.segment_count += 1;
                    telemetry.segment_prepare_us += prepare_us;
                    telemetry.segment_payload_write_us += payload_write_us;
                    telemetry.segment_payload_bytes += segment.payload.len();
                    telemetry.segment_external_bytes += payload_ref.bytes;
                    telemetry.segment_uncompressed_bytes +=
                        segment.header.uncompressed_len as usize;
                    telemetry
                        .segments
                        .push(PreparedDocumentSegmentPersistTelemetry {
                            document_id: document.manifest.document_id.clone(),
                            kind: segment_kind_name(segment.header.kind()).to_owned(),
                            ordinal: segment.header.ordinal,
                            row_count: segment.header.row_count,
                            compressed_bytes: segment.payload.len(),
                            uncompressed_bytes: segment.header.uncompressed_len as usize,
                            prepare_us,
                            payload_write_us,
                            storage: "external".to_owned(),
                        });
                }
            }
            for dirty_scope in touched_scopes {
                let started = std::time::Instant::now();
                let record = encode_record(dirty_scope)?;
                telemetry.dirty_scope_record_bytes += record.len();
                batch.push(NodeInput {
                    type_id: TYPE_DIRTY_SCOPE,
                    key: dirty_scope.scope_key.clone(),
                    props: btree_props([
                        (
                            PROP_SCOPE_KEY,
                            PropValue::String(dirty_scope.scope_key.clone()),
                        ),
                        (PROP_SCOPE_ORD, PropValue::UInt(dirty_scope.scope_ord.0)),
                        (PROP_UPDATED_AT, PropValue::Int(dirty_scope.updated_at)),
                        (PROP_RECORD, PropValue::Bytes(record)),
                    ]),
                    weight: 1.0,
                    dense_vector: None,
                    sparse_vector: None,
                });
                telemetry.dirty_scope_prepare_us += started.elapsed().as_micros() as u64;
            }
            telemetry.node_count = batch.len();
            let started = std::time::Instant::now();
            self.batch_upsert_nodes_with_engine(engine, batch)?;
            telemetry.batch_upsert_us = started.elapsed().as_micros() as u64;
            if let Some(session_archive) = session_archive {
                let started = std::time::Instant::now();
                let revision = session_archive
                    .document_refs
                    .iter()
                    .map(|document| document.revision)
                    .max()
                    .unwrap_or(0);
                self.persist_session_archive_native_with_engine(engine, session_archive, revision)?;
                telemetry.session_archive_us = started.elapsed().as_micros() as u64;
            }
            Ok(())
        })?;
        let started = std::time::Instant::now();
        for dirty_scope in touched_scopes {
            self.invalidate_scope_runtime_caches(&dirty_scope.scope_key)?;
        }
        telemetry.cache_invalidate_us = started.elapsed().as_micros() as u64;
        telemetry.total_us = total_started.elapsed().as_micros() as u64;
        Ok(telemetry)
    }
}

impl PhoenixChunkManifestStore for PhoenixOvergraphStore {
    fn init_chunk_manifest_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_chunk_manifest(&self, manifest: &ChunkManifest) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            engine
                .upsert_node(
                    TYPE_CHUNK_MANIFEST,
                    &chunk_manifest_key(&manifest.document_id),
                    UpsertNodeOptions {
                        props: btree_props([
                            (
                                PROP_DOCUMENT_ID,
                                PropValue::String(manifest.document_id.clone()),
                            ),
                            (PROP_RECORD, PropValue::Bytes(encode_record(manifest)?)),
                        ]),
                        ..Default::default()
                    },
                )
                .map_err(store_query_error)?;
            Ok(())
        })
    }

    fn load_chunk_manifest(&self, document_id: &str) -> Result<Option<ChunkManifest>, StoreError> {
        self.with_engine(|engine| {
            engine
                .get_node_by_key(TYPE_CHUNK_MANIFEST, &chunk_manifest_key(document_id))
                .map_err(store_query_error)?
                .map(|node| decode_record_prop_required(&node, PROP_RECORD))
                .transpose()
        })
    }
}

impl PhoenixArchiveStoreV2 for PhoenixOvergraphStore {
    fn init_archive_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn ingest_mode(&self) -> IngestMode {
        self.tuning.ingest_mode
    }

    fn prepare_ingest_context(
        &self,
        session_id: Option<&SessionId>,
        documents: &[IngestDocument],
        revision: u64,
    ) -> Result<PreparedIngestContext, StoreError> {
        self.with_engine(|engine| {
            let session_ord = match session_id {
                Some(session_id) => Some(self.ensure_session_ord(engine, session_id)?),
                None => None,
            };
            let mut assignments = Vec::with_capacity(documents.len());
            for document in documents {
                let scope_key = scope_storage_key(&document.scope);
                let scope_ord = self.ensure_scope_ord(engine, &scope_key)?;
                let document_ord =
                    self.ensure_document_ord(engine, &scope_key, &document.document_id.0)?;
                assignments.push(DocumentOrdinalAssignment {
                    document_id: document.document_id.0.clone(),
                    scope: document.scope.clone(),
                    scope_key,
                    scope_ord,
                    document_ord,
                    revision: revision + 1,
                });
            }
            Ok(PreparedIngestContext {
                session_id: session_id.cloned(),
                session_ord,
                assignments,
                kernel_snapshot: Some(self.load_live_kernel_snapshot_with_engine(engine)?),
            })
        })
    }

    fn persist_prepared_documents(
        &self,
        prepared: &[PreparedDocument],
        session_archive: Option<&SessionArchive>,
        touched_scopes: &[DirtyScopeRecord],
        _created_at: i64,
    ) -> Result<(), StoreError> {
        self.persist_prepared_documents_native_with_telemetry(
            prepared,
            session_archive,
            touched_scopes,
        )
        .map(|_| ())
    }

    fn persist_prepared_documents_with_telemetry(
        &self,
        prepared: &[PreparedDocument],
        session_archive: Option<&SessionArchive>,
        touched_scopes: &[DirtyScopeRecord],
        _created_at: i64,
    ) -> Result<PreparedDocumentPersistTelemetry, StoreError> {
        self.persist_prepared_documents_native_with_telemetry(
            prepared,
            session_archive,
            touched_scopes,
        )
    }

    fn persist_session_archive(
        &self,
        archive: &SessionArchive,
        revision: u64,
        _created_at: i64,
    ) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_session_archive_native_with_engine(engine, archive, revision)
        })
    }

    fn load_latest_session_archive(
        &self,
        session_id: &SessionId,
    ) -> Result<Option<SessionArchive>, StoreError> {
        self.with_engine(|engine| {
            if let Some(archive) =
                self.load_native_session_archive_with_engine(engine, session_id)?
            {
                return Ok(Some(archive));
            }
            let header = self
                .list_compat_bundle_headers_with_engine(
                    engine,
                    BundleKind::SessionArchive,
                    Some(&session_id.0),
                )?
                .into_iter()
                .filter(|header| header.key.entity_key == session_id.0)
                .max_by_key(|header| header.key.revision);
            let Some(header) = header else {
                return Ok(None);
            };
            let Some(node) = engine
                .get_node_by_key(TYPE_COMPAT_BUNDLE, &bundle_storage_key(&header.key))
                .map_err(store_query_error)?
            else {
                return Ok(None);
            };
            decode_archive(&required_bytes_prop(&node, PROP_PAYLOAD)?).map(Some)
        })
    }

    fn load_latest_document_archives(
        &self,
        scope: Option<&ScopeKey>,
    ) -> Result<Vec<DocumentArchive>, StoreError> {
        self.with_engine(|engine| {
            let mut latest = BTreeMap::<String, (u64, DocumentArchive)>::new();
            for manifest in self.load_latest_document_manifests_with_engine(engine, scope)? {
                let archive =
                    self.load_document_archive_from_manifest_with_engine(engine, &manifest)?;
                latest.insert(
                    archive.manifest.document_id.clone(),
                    (archive.manifest.revision, archive),
                );
            }

            let scope_key = scope.map(scope_storage_key);
            let compat_headers = self.list_compat_bundle_headers_with_engine(
                engine,
                BundleKind::DocumentArchive,
                scope_key.as_deref(),
            )?;
            let mut compat_latest = BTreeMap::<String, BundleHeader>::new();
            for header in compat_headers {
                match compat_latest.get(&header.key.entity_key) {
                    Some(existing) if existing.key.revision >= header.key.revision => {}
                    _ => {
                        compat_latest.insert(header.key.entity_key.clone(), header);
                    }
                }
            }
            for header in compat_latest.into_values() {
                let Some(node) = engine
                    .get_node_by_key(TYPE_COMPAT_BUNDLE, &bundle_storage_key(&header.key))
                    .map_err(store_query_error)?
                else {
                    continue;
                };
                let archive: DocumentArchive =
                    decode_archive(&required_bytes_prop(&node, PROP_PAYLOAD)?)?;
                match latest.get(&archive.manifest.document_id) {
                    Some((revision, _)) if *revision >= archive.manifest.revision => {}
                    _ => {
                        latest.insert(
                            archive.manifest.document_id.clone(),
                            (archive.manifest.revision, archive),
                        );
                    }
                }
            }

            let mut values = latest
                .into_values()
                .map(|(_, archive)| archive)
                .collect::<Vec<_>>();
            values
                .sort_by(|left, right| left.manifest.document_id.cmp(&right.manifest.document_id));
            Ok(values)
        })
    }

    fn load_document_manifest(
        &self,
        document_ref: &DocumentRevisionRef,
    ) -> Result<Option<DocumentManifest>, StoreError> {
        self.with_engine(|engine| self.load_document_manifest_with_engine(engine, document_ref))
    }

    fn load_scope_sidecar(&self, scope: &ScopeKey) -> Result<Option<ScopeLexSidecar>, StoreError> {
        self.with_engine(|engine| {
            if let Some(sidecar) = self.load_native_scope_sidecar_with_engine(engine, scope)? {
                return Ok(Some(sidecar));
            }
            let scope_key = scope_storage_key(scope);
            let header = self
                .list_compat_bundle_headers_with_engine(
                    engine,
                    BundleKind::ScopeLexSidecar,
                    Some(&scope_key),
                )?
                .into_iter()
                .filter(|header| header.key.entity_key == scope_key)
                .max_by_key(|header| header.key.revision);
            let Some(header) = header else {
                return Ok(None);
            };
            let Some(node) = engine
                .get_node_by_key(TYPE_COMPAT_BUNDLE, &bundle_storage_key(&header.key))
                .map_err(store_query_error)?
            else {
                return Ok(None);
            };
            decode_archive(&required_bytes_prop(&node, PROP_PAYLOAD)?).map(Some)
        })
    }

    fn load_materialized_scope_lexical(
        &self,
        scope: &ScopeKey,
    ) -> Result<ScopeLexSidecar, StoreError> {
        self.with_engine(|engine| self.materialize_scope_lexical_with_engine(engine, scope))
    }

    fn load_lex_spans(&self, scope: Option<&ScopeKey>) -> Result<Vec<IndexedSpan>, StoreError> {
        self.with_engine(|engine| {
            if let Some(scope) = scope {
                return Ok(self
                    .materialize_scope_lexical_with_engine(engine, scope)?
                    .spans);
            }

            let mut spans = Vec::new();
            for scope in self.list_all_scopes_with_engine(engine)? {
                spans.extend(
                    self.materialize_scope_lexical_with_engine(engine, &scope)?
                        .spans,
                );
            }
            spans.sort_by(|left, right| left.span_id.cmp(&right.span_id));
            spans.dedup_by(|left, right| left.span_id == right.span_id);
            Ok(spans)
        })
    }

    fn lookup_alias_postings(
        &self,
        scope: &ScopeKey,
        normalized: &str,
    ) -> Result<Vec<AliasPosting>, StoreError> {
        let sidecar = self.load_materialized_scope_lexical(scope)?;
        Ok(sidecar
            .alias_entries
            .into_iter()
            .find(|entry| entry.normalized == normalized)
            .map(|entry| entry.postings)
            .unwrap_or_default())
    }

    fn rebuild_dirty_scope_sidecars(&self, created_at: i64) -> Result<usize, StoreError> {
        self.with_engine(|engine| {
            let mut dirty = engine
                .get_nodes_by_type(TYPE_DIRTY_SCOPE)
                .map_err(store_query_error)?
                .into_iter()
                .filter_map(|node| {
                    decode_record_prop::<DirtyScopeRecord>(&node, PROP_RECORD).transpose()
                })
                .collect::<Result<Vec<_>, _>>()?;
            dirty.sort_by(|left, right| left.scope_key.cmp(&right.scope_key));
            if dirty.is_empty() {
                return Ok(0);
            }
            for record in &dirty {
                let persisted =
                    self.load_native_scope_sidecar_with_engine(engine, &record.scope)?;
                let mut sidecar = self.aggregate_scope_sidecar_with_engine(
                    engine,
                    &record.scope,
                    record.scope_ord,
                    persisted,
                    Some(record),
                )?;
                sidecar.scope_ord = Some(record.scope_ord);
                sidecar.generated_at = created_at;
                sidecar.generation = sidecar.generation.max(record.updated_at as u64);
                self.persist_scope_sidecar_native_with_engine(engine, &sidecar)?;
                if let Some(node) = engine
                    .get_node_by_key(TYPE_DIRTY_SCOPE, &record.scope_key)
                    .map_err(store_query_error)?
                {
                    engine.delete_node(node.id).map_err(store_query_error)?;
                }
            }
            Ok(dirty.len())
        })
    }

    fn list_dirty_scopes(&self) -> Result<Vec<DirtyScopeRecord>, StoreError> {
        self.with_engine(|engine| {
            let mut values = engine
                .get_nodes_by_type(TYPE_DIRTY_SCOPE)
                .map_err(store_query_error)?
                .into_iter()
                .filter_map(|node| {
                    decode_record_prop::<DirtyScopeRecord>(&node, PROP_RECORD).transpose()
                })
                .collect::<Result<Vec<_>, _>>()?;
            values.sort_by(|left, right| left.scope_key.cmp(&right.scope_key));
            Ok(values)
        })
    }
}

impl PhoenixErPatchStore for PhoenixOvergraphStore {
    fn init_er_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_er_patch_sidecar(&self, sidecar: &ErScopePatchSidecar) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_er_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_er_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<ErScopePatchSidecar>, StoreError> {
        self.with_engine(|engine| self.load_native_er_patch_sidecar_with_engine(engine, scope))
    }
}

impl PhoenixRelationPatchStore for PhoenixOvergraphStore {
    fn init_relation_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_relation_patch_sidecar(
        &self,
        sidecar: &RelationScopePatchSidecar,
    ) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_relation_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_relation_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<RelationScopePatchSidecar>, StoreError> {
        self.with_engine(|engine| {
            self.load_native_relation_patch_sidecar_with_engine(engine, scope)
        })
    }
}

impl PhoenixMemoryPatchStore for PhoenixOvergraphStore {
    fn init_memory_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_memory_patch_sidecar(&self, sidecar: &MemoryScopeSidecar) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_memory_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_memory_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<MemoryScopeSidecar>, StoreError> {
        self.with_engine(|engine| self.load_native_memory_patch_sidecar_with_engine(engine, scope))
    }
}

impl PhoenixGraphPatchStore for PhoenixOvergraphStore {
    fn init_graph_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_graph_patch_sidecar(&self, sidecar: &GraphScopeSidecar) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_graph_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_graph_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<GraphScopeSidecar>, StoreError> {
        self.with_engine(|engine| self.load_native_graph_patch_sidecar_with_engine(engine, scope))
    }
}

impl PhoenixSemanticGraphPatchStore for PhoenixOvergraphStore {
    fn init_semantic_graph_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_semantic_graph_patch_sidecar(
        &self,
        sidecar: &SemanticGraphScopeSidecar,
    ) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_semantic_graph_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_semantic_graph_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<SemanticGraphScopeSidecar>, StoreError> {
        self.with_engine(|engine| {
            self.load_native_semantic_graph_patch_sidecar_with_engine(engine, scope)
        })
    }
}

impl PhoenixCausalPatchStore for PhoenixOvergraphStore {
    fn init_causal_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_causal_patch_sidecar(&self, sidecar: &CausalScopeSidecar) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_causal_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_causal_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<CausalScopeSidecar>, StoreError> {
        self.with_engine(|engine| self.load_native_causal_patch_sidecar_with_engine(engine, scope))
    }
}

impl PhoenixTemporalPatchStore for PhoenixOvergraphStore {
    fn init_temporal_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_temporal_patch_sidecar(
        &self,
        sidecar: &TemporalScopeSidecar,
    ) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_temporal_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_temporal_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<TemporalScopeSidecar>, StoreError> {
        self.with_engine(|engine| {
            self.load_native_temporal_patch_sidecar_with_engine(engine, scope)
        })
    }
}

impl PhoenixEventIdentityPatchStore for PhoenixOvergraphStore {
    fn init_event_identity_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_event_identity_patch_sidecar(
        &self,
        sidecar: &EventIdentityScopeSidecar,
    ) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_event_identity_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_event_identity_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<EventIdentityScopeSidecar>, StoreError> {
        self.with_engine(|engine| {
            self.load_native_event_identity_patch_sidecar_with_engine(engine, scope)
        })
    }
}

impl PhoenixStateSchemaPatchStore for PhoenixOvergraphStore {
    fn init_state_schema_patch_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_state_schema_patch_sidecar(
        &self,
        sidecar: &StateSchemaScopeSidecar,
    ) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_state_schema_patch_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_state_schema_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<StateSchemaScopeSidecar>, StoreError> {
        self.with_engine(|engine| {
            self.load_native_state_schema_patch_sidecar_with_engine(engine, scope)
        })
    }
}

impl PhoenixRelationMentionSeedStore for PhoenixOvergraphStore {
    fn init_relation_mention_seed_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn persist_relation_mention_seed_sidecar(
        &self,
        sidecar: &RelationMentionSeedScopeSidecar,
    ) -> Result<(), StoreError> {
        self.with_engine(|engine| {
            self.persist_relation_mention_seed_sidecar_native_with_engine(engine, sidecar)
        })?;
        self.invalidate_scope_runtime_image_cache(&sidecar.scope_key)?;
        Ok(())
    }

    fn load_relation_mention_seed_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<RelationMentionSeedScopeSidecar>, StoreError> {
        self.with_engine(|engine| {
            self.load_native_relation_mention_seed_sidecar_with_engine(engine, scope)
        })
    }
}

impl PhoenixSemanticIndexStore for PhoenixOvergraphStore {
    fn semantic_leaf_index_authority_for_model(
        &self,
        model_id: &str,
        model_version: &str,
        dimension: usize,
        scope: &ScopeKey,
    ) -> Result<Option<SemanticIndexAuthorityReceipt>, StoreError> {
        let model_version = model_version.trim();
        if model_version.is_empty() {
            return Err(StoreError::Query(
                "semantic index authority requires an encoder version".to_owned(),
            ));
        }
        let Some(manifest) = self.load_ann_manifest_for_model(
            model_id,
            dimension,
            scope,
            AnnIndexFamily::Leaf,
            None,
        )?
        else {
            return Ok(None);
        };
        let cache_path = self.ann_cache_generation_path(&manifest.index, manifest.generation_id);
        let manifest_bytes =
            serde_json::to_vec(&manifest).map_err(|error| StoreError::Query(error.to_string()))?;
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"phoenix-semantic-index-authority/v1\0");
        hasher.update(&manifest_bytes);
        hasher.update(model_version.as_bytes());
        hasher.update(&[0]);
        let mut file = std::fs::File::open(&cache_path)
            .map_err(|error| StoreError::Query(error.to_string()))?;
        let mut buffer = [0_u8; 64 * 1024];
        loop {
            let read = std::io::Read::read(&mut file, &mut buffer)
                .map_err(|error| StoreError::Query(error.to_string()))?;
            if read == 0 {
                break;
            }
            hasher.update(&buffer[..read]);
        }
        Ok(Some(SemanticIndexAuthorityReceipt {
            index_generation: manifest.generation_id.0,
            index_digest: hasher.finalize().to_hex().to_string(),
            model_id: manifest.model_id,
            model_version: model_version.to_owned(),
            dimension: manifest.dimension,
            metric: manifest.metric,
            payload_count: manifest.count,
        }))
    }

    fn upsert_semantic_leaf_vectors(
        &self,
        rows: &[NativeSemanticLeafVectorRecord],
    ) -> Result<(), StoreError> {
        self.upsert_semantic_leaf_vectors_for_model(SEMANTIC_MODEL_ID, rows)
    }

    fn upsert_semantic_leaf_vectors_for_model(
        &self,
        model_id: &str,
        rows: &[NativeSemanticLeafVectorRecord],
    ) -> Result<(), StoreError> {
        if rows.is_empty() {
            return Ok(());
        }
        let model_id = Self::normalize_semantic_model_id(model_id);
        self.with_engine(|engine| {
            let mut batch = Vec::with_capacity(rows.len());
            let mut affected = HashSet::new();
            let dirty_at = now_ms();
            for row in rows {
                let dimension = row.values.len();
                Self::validate_semantic_vector_dim(&row.values, dimension, &row.span_id)?;
                let scope_ord = self.ensure_scope_ord(engine, &scope_storage_key(&row.scope))?;
                let index = Self::ann_index_key(
                    scope_ord,
                    AnnIndexFamily::Leaf,
                    None,
                    &model_id,
                    dimension,
                )?;
                affected.insert(index);
                let record = AnnSourceLeafRecord {
                    scope: row.scope.clone(),
                    scope_key: scope_storage_key(&row.scope),
                    model_id: model_id.clone(),
                    span_id: row.span_id.clone(),
                    document_id: row.document_id.clone(),
                    values: row.values.clone(),
                    updated_at: row.updated_at,
                };
                batch.push(NodeInput {
                    type_id: TYPE_ANN_SOURCE_LEAF,
                    key: ann_source_row_key(
                        scope_ord,
                        AnnIndexFamily::Leaf,
                        None,
                        &model_id,
                        dimension,
                        &row.span_id,
                    ),
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(record.scope_key.clone())),
                        (PROP_SCOPE_ORD, PropValue::UInt(scope_ord.0)),
                        (PROP_MODEL_ID, PropValue::String(model_id.clone())),
                        (PROP_DIMENSION, PropValue::UInt(dimension as u64)),
                        (PROP_SPAN_ID, PropValue::String(row.span_id.clone())),
                        (PROP_DOCUMENT_ID, PropValue::String(row.document_id.clone())),
                        (PROP_UPDATED_AT, PropValue::Int(row.updated_at)),
                        (PROP_RECORD, PropValue::Bytes(encode_record(&record)?)),
                    ]),
                    weight: 1.0,
                    dense_vector: None,
                    sparse_vector: None,
                });
            }
            self.batch_upsert_nodes_with_engine(engine, batch)?;
            for index in affected {
                self.mark_ann_dirty_with_engine(engine, &index, dirty_at)?;
            }
            Ok(())
        })
    }

    fn upsert_semantic_document_vectors_native(
        &self,
        rows: &[NativeSemanticDocumentVectorRecord],
    ) -> Result<(), StoreError> {
        self.upsert_semantic_document_vectors_native_for_model(SEMANTIC_MODEL_ID, rows)
    }

    fn upsert_semantic_document_vectors_native_for_model(
        &self,
        model_id: &str,
        rows: &[NativeSemanticDocumentVectorRecord],
    ) -> Result<(), StoreError> {
        if rows.is_empty() {
            return Ok(());
        }
        let model_id = Self::normalize_semantic_model_id(model_id);
        self.with_engine(|engine| {
            let mut batch = Vec::with_capacity(rows.len());
            let mut affected = HashSet::new();
            let dirty_at = now_ms();
            for row in rows {
                let dimension = row.values.len();
                Self::validate_semantic_vector_dim(&row.values, dimension, &row.document_id)?;
                let scope_ord = self.ensure_scope_ord(engine, &scope_storage_key(&row.scope))?;
                let index = Self::ann_index_key(
                    scope_ord,
                    AnnIndexFamily::Document,
                    None,
                    &model_id,
                    dimension,
                )?;
                affected.insert(index);
                let record = AnnSourceDocumentRecord {
                    scope: row.scope.clone(),
                    scope_key: scope_storage_key(&row.scope),
                    model_id: model_id.clone(),
                    document_id: row.document_id.clone(),
                    values: row.values.clone(),
                    leaf_count: row.leaf_count,
                    evidence_refs: row.evidence_refs.clone(),
                    updated_at: row.updated_at,
                };
                batch.push(NodeInput {
                    type_id: TYPE_ANN_SOURCE_DOCUMENT,
                    key: ann_source_row_key(
                        scope_ord,
                        AnnIndexFamily::Document,
                        None,
                        &model_id,
                        dimension,
                        &row.document_id,
                    ),
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(record.scope_key.clone())),
                        (PROP_SCOPE_ORD, PropValue::UInt(scope_ord.0)),
                        (PROP_MODEL_ID, PropValue::String(model_id.clone())),
                        (PROP_DIMENSION, PropValue::UInt(dimension as u64)),
                        (PROP_DOCUMENT_ID, PropValue::String(row.document_id.clone())),
                        (PROP_LEAF_COUNT, PropValue::UInt(row.leaf_count as u64)),
                        (PROP_UPDATED_AT, PropValue::Int(row.updated_at)),
                        (PROP_RECORD, PropValue::Bytes(encode_record(&record)?)),
                    ]),
                    weight: 1.0,
                    dense_vector: None,
                    sparse_vector: None,
                });
            }
            self.batch_upsert_nodes_with_engine(engine, batch)?;
            for index in affected {
                self.mark_ann_dirty_with_engine(engine, &index, dirty_at)?;
            }
            Ok(())
        })
    }

    fn upsert_semantic_node_vectors_native(
        &self,
        rows: &[NativeSemanticNodeVectorRecord],
    ) -> Result<(), StoreError> {
        if rows.is_empty() {
            return Ok(());
        }
        self.upsert_semantic_node_vectors_native_for_model(SEMANTIC_MODEL_ID, rows)
    }

    fn upsert_semantic_node_vectors_native_for_model(
        &self,
        model_id: &str,
        rows: &[NativeSemanticNodeVectorRecord],
    ) -> Result<(), StoreError> {
        if rows.is_empty() {
            return Ok(());
        }
        self.upsert_semantic_node_vectors_native_owned_for_model(model_id, rows.to_vec())
    }

    fn upsert_semantic_node_vectors_native_owned(
        &self,
        rows: Vec<NativeSemanticNodeVectorRecord>,
    ) -> Result<(), StoreError> {
        self.upsert_semantic_node_vectors_native_owned_for_model(SEMANTIC_MODEL_ID, rows)
    }

    fn upsert_semantic_node_vectors_native_owned_for_model(
        &self,
        model_id: &str,
        rows: Vec<NativeSemanticNodeVectorRecord>,
    ) -> Result<(), StoreError> {
        if rows.is_empty() {
            return Ok(());
        }
        let model_id = Self::normalize_semantic_model_id(model_id);
        self.with_engine(|engine| {
            let mut batch = Vec::with_capacity(rows.len());
            let mut affected = HashSet::new();
            let dirty_at = now_ms();
            for row in rows {
                let dimension = row.values.len();
                Self::validate_semantic_vector_dim(&row.values, dimension, &row.node_id)?;
                let scope_ord = self.ensure_scope_ord(engine, &scope_storage_key(&row.scope))?;
                let scope_key = scope_storage_key(&row.scope);
                let NativeSemanticNodeVectorRecord {
                    scope,
                    node_id,
                    node_kind,
                    document_id,
                    note_id,
                    narrative_id,
                    folder_id,
                    folder_path,
                    values,
                    evidence_refs,
                    updated_at,
                } = row;
                let index = Self::ann_index_key(
                    scope_ord,
                    AnnIndexFamily::NodePrototype,
                    Some(node_kind.clone()),
                    &model_id,
                    dimension,
                )?;
                affected.insert(index.clone());
                affected.insert(Self::ann_index_key(
                    scope_ord,
                    AnnIndexFamily::NodePrototype,
                    None,
                    &model_id,
                    dimension,
                )?);
                let record = AnnSourceNodeRecord {
                    scope,
                    scope_key: scope_key.clone(),
                    model_id: model_id.clone(),
                    node_id: node_id.clone(),
                    node_kind: node_kind.clone(),
                    document_id,
                    note_id,
                    narrative_id,
                    folder_id,
                    folder_path,
                    values,
                    evidence_refs,
                    updated_at,
                };
                batch.push(NodeInput {
                    type_id: TYPE_ANN_SOURCE_NODE,
                    key: ann_source_row_key(
                        scope_ord,
                        AnnIndexFamily::NodePrototype,
                        Some(&node_kind),
                        &model_id,
                        dimension,
                        &node_id,
                    ),
                    props: btree_props([
                        (PROP_SCOPE_KEY, PropValue::String(scope_key)),
                        (PROP_SCOPE_ORD, PropValue::UInt(scope_ord.0)),
                        (PROP_MODEL_ID, PropValue::String(model_id.clone())),
                        (PROP_DIMENSION, PropValue::UInt(dimension as u64)),
                        (PROP_NODE_ID, PropValue::String(node_id)),
                        (PROP_KIND, PropValue::String(node_kind)),
                        (PROP_UPDATED_AT, PropValue::Int(updated_at)),
                        (PROP_RECORD, PropValue::Bytes(encode_record(&record)?)),
                    ]),
                    weight: 1.0,
                    dense_vector: None,
                    sparse_vector: None,
                });
            }
            self.batch_upsert_nodes_with_engine(engine, batch)?;
            for index in affected {
                self.mark_ann_dirty_with_engine(engine, &index, dirty_at)?;
            }
            Ok(())
        })
    }

    fn query_semantic_neighbors(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNeighbor>, StoreError> {
        Ok(self
            .search_ann_payloads(
                scope,
                AnnIndexFamily::Leaf,
                None,
                query_vector,
                limit,
                oversample,
            )?
            .into_iter()
            .filter_map(|(candidate, payload)| match payload {
                AnnPayload::Leaf { span_id, .. } => Some(SemanticNeighbor {
                    span_id,
                    distance: candidate.dist as f64,
                }),
                _ => None,
            })
            .take(limit)
            .collect())
    }

    fn query_semantic_documents(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticDocumentNeighbor>, StoreError> {
        Ok(self
            .search_ann_payloads(
                scope,
                AnnIndexFamily::Document,
                None,
                query_vector,
                limit,
                oversample,
            )?
            .into_iter()
            .filter_map(|(candidate, payload)| match payload {
                AnnPayload::Document {
                    document_id,
                    leaf_count,
                    evidence_refs,
                } => Some(SemanticDocumentNeighbor {
                    document_id,
                    distance: candidate.dist as f64,
                    leaf_count,
                    evidence_refs,
                }),
                _ => None,
            })
            .take(limit)
            .collect())
    }

    fn query_semantic_neighbors_in_documents(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        document_ids: &[String],
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNeighbor>, StoreError> {
        if limit == 0 || document_ids.is_empty() {
            return Ok(Vec::new());
        }
        let allowed = document_ids
            .iter()
            .map(String::as_str)
            .collect::<BTreeSet<_>>();
        let Some(state) = self.load_ann_query_state(scope, AnnIndexFamily::Leaf, None)? else {
            return Ok(Vec::new());
        };
        Self::validate_semantic_vector(query_vector, "query")?;
        let query_vector = Self::project_ann_query_vector(&state.manifest, query_vector)?;
        let mut search_k = oversample
            .max(limit)
            .max(8)
            .min(state.manifest.count.max(limit).max(1));
        let mut hits = Vec::new();
        while search_k <= state.manifest.count.max(limit) {
            hits.clear();
            for candidate in state
                .index_handle
                .search(&query_vector, search_k, search_k.max(16))
            {
                let Some(payload) = state.payloads.get(candidate.id as usize) else {
                    continue;
                };
                if let AnnPayload::Leaf {
                    span_id,
                    document_id,
                } = payload
                {
                    if allowed.contains(document_id.as_str()) {
                        hits.push(SemanticNeighbor {
                            span_id: span_id.clone(),
                            distance: candidate.dist as f64,
                        });
                        if hits.len() >= limit {
                            return Ok(hits);
                        }
                    }
                }
            }
            if search_k >= state.manifest.count {
                break;
            }
            search_k = (search_k * 2).min(state.manifest.count);
        }
        Ok(hits)
    }

    fn query_semantic_node_neighbors(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        kind: &str,
        exclude_node_id: Option<&str>,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNodeNeighbor>, StoreError> {
        Ok(self
            .search_ann_payloads(
                scope,
                AnnIndexFamily::NodePrototype,
                Some(kind),
                query_vector,
                limit.saturating_add(exclude_node_id.is_some() as usize),
                oversample.max(limit),
            )?
            .into_iter()
            .filter_map(|(candidate, payload)| match payload {
                AnnPayload::Node {
                    node_id,
                    node_kind,
                    document_id,
                    note_id,
                    narrative_id,
                    folder_id,
                    folder_path,
                    evidence_refs,
                } if exclude_node_id != Some(node_id.as_str()) => Some(SemanticNodeNeighbor {
                    node_id,
                    node_kind,
                    distance: candidate.dist as f64,
                    document_id,
                    note_id,
                    narrative_id,
                    folder_id,
                    folder_path,
                    evidence_refs,
                }),
                _ => None,
            })
            .take(limit)
            .collect())
    }

    fn query_semantic_node_neighbors_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        query_vector: &[f32],
        scope: &ScopeKey,
        kind: &str,
        exclude_node_id: Option<&str>,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNodeNeighbor>, StoreError> {
        Ok(self
            .search_ann_payloads_for_model(
                model_id,
                dimension,
                scope,
                AnnIndexFamily::NodePrototype,
                Some(kind),
                query_vector,
                limit.saturating_add(exclude_node_id.is_some() as usize),
                oversample.max(limit),
            )?
            .into_iter()
            .filter_map(|(candidate, payload)| match payload {
                AnnPayload::Node {
                    node_id,
                    node_kind,
                    document_id,
                    note_id,
                    narrative_id,
                    folder_id,
                    folder_path,
                    evidence_refs,
                } if exclude_node_id != Some(node_id.as_str()) => Some(SemanticNodeNeighbor {
                    node_id,
                    node_kind,
                    distance: candidate.dist as f64,
                    document_id,
                    note_id,
                    narrative_id,
                    folder_id,
                    folder_path,
                    evidence_refs,
                }),
                _ => None,
            })
            .take(limit)
            .collect())
    }

    fn query_semantic_node_neighbors_by_kinds(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        kinds: &[&str],
        exclude_node_id: Option<&str>,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNodeNeighbor>, StoreError> {
        let mut kinds = kinds
            .iter()
            .copied()
            .filter(|kind| !kind.is_empty())
            .collect::<Vec<_>>();
        kinds.sort_unstable();
        kinds.dedup();
        if limit == 0 || kinds.is_empty() {
            return Ok(Vec::new());
        }
        if kinds.len() == 1 {
            return self.query_semantic_node_neighbors(
                query_vector,
                scope,
                kinds[0],
                exclude_node_id,
                limit,
                oversample,
            );
        }

        Self::validate_semantic_vector(query_vector, "query")?;
        let Some(state) = self.load_ann_query_state(scope, AnnIndexFamily::NodePrototype, None)?
        else {
            return Ok(Vec::new());
        };
        let query_vector = Self::project_ann_query_vector(&state.manifest, query_vector)?;

        let allowed = kinds.iter().copied().collect::<BTreeSet<_>>();
        let target_hits = oversample.max(limit).max(1);
        let max_search = state.manifest.count.max(limit).max(1);
        let mut search_k = oversample.max(limit).max(1).max(16).min(max_search);

        loop {
            let mut hits = Vec::<SemanticNodeNeighbor>::new();
            for candidate in state
                .index_handle
                .search(&query_vector, search_k, search_k.max(16))
            {
                let Some(payload) = state.payloads.get(candidate.id as usize) else {
                    continue;
                };
                let AnnPayload::Node {
                    node_id,
                    node_kind,
                    document_id,
                    note_id,
                    narrative_id,
                    folder_id,
                    folder_path,
                    evidence_refs,
                } = payload
                else {
                    continue;
                };
                if exclude_node_id == Some(node_id.as_str())
                    || !allowed.contains(node_kind.as_str())
                {
                    continue;
                }
                hits.push(SemanticNodeNeighbor {
                    node_id: node_id.clone(),
                    node_kind: node_kind.clone(),
                    distance: candidate.dist as f64,
                    document_id: document_id.clone(),
                    note_id: note_id.clone(),
                    narrative_id: narrative_id.clone(),
                    folder_id: folder_id.clone(),
                    folder_path: folder_path.clone(),
                    evidence_refs: evidence_refs.clone(),
                });
                if hits.len() >= target_hits {
                    break;
                }
            }
            if hits.len() >= target_hits || search_k >= max_search {
                hits.sort_by(|left, right| {
                    left.distance
                        .total_cmp(&right.distance)
                        .then_with(|| left.node_id.cmp(&right.node_id))
                });
                return Ok(hits);
            }
            search_k = (search_k * 2).min(max_search);
        }
    }

    fn query_semantic_node_neighbors_by_kinds_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        query_vector: &[f32],
        scope: &ScopeKey,
        kinds: &[&str],
        exclude_node_id: Option<&str>,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNodeNeighbor>, StoreError> {
        let mut kinds = kinds
            .iter()
            .copied()
            .filter(|kind| !kind.is_empty())
            .collect::<Vec<_>>();
        kinds.sort_unstable();
        kinds.dedup();
        if limit == 0 || kinds.is_empty() {
            return Ok(Vec::new());
        }
        if kinds.len() == 1 {
            return self.query_semantic_node_neighbors_for_model(
                model_id,
                dimension,
                query_vector,
                scope,
                kinds[0],
                exclude_node_id,
                limit,
                oversample,
            );
        }

        Self::validate_semantic_vector_dim(query_vector, dimension, "query")?;
        let Some(state) = self.load_ann_query_state_for_model(
            model_id,
            dimension,
            scope,
            AnnIndexFamily::NodePrototype,
            None,
        )?
        else {
            return Ok(Vec::new());
        };
        let query_vector = Self::project_ann_query_vector(&state.manifest, query_vector)?;

        let allowed = kinds.iter().copied().collect::<BTreeSet<_>>();
        let target_hits = oversample.max(limit).max(1);
        let max_search = state.manifest.count.max(limit).max(1);
        let mut search_k = oversample.max(limit).max(1).max(16).min(max_search);

        loop {
            let mut hits = Vec::<SemanticNodeNeighbor>::new();
            for candidate in state
                .index_handle
                .search(&query_vector, search_k, search_k.max(16))
            {
                let Some(payload) = state.payloads.get(candidate.id as usize) else {
                    continue;
                };
                let AnnPayload::Node {
                    node_id,
                    node_kind,
                    document_id,
                    note_id,
                    narrative_id,
                    folder_id,
                    folder_path,
                    evidence_refs,
                } = payload
                else {
                    continue;
                };
                if exclude_node_id == Some(node_id.as_str())
                    || !allowed.contains(node_kind.as_str())
                {
                    continue;
                }
                hits.push(SemanticNodeNeighbor {
                    node_id: node_id.clone(),
                    node_kind: node_kind.clone(),
                    distance: candidate.dist as f64,
                    document_id: document_id.clone(),
                    note_id: note_id.clone(),
                    narrative_id: narrative_id.clone(),
                    folder_id: folder_id.clone(),
                    folder_path: folder_path.clone(),
                    evidence_refs: evidence_refs.clone(),
                });
                if hits.len() >= target_hits {
                    break;
                }
            }
            if hits.len() >= target_hits || search_k >= max_search {
                hits.sort_by(|left, right| {
                    left.distance
                        .total_cmp(&right.distance)
                        .then_with(|| left.node_id.cmp(&right.node_id))
                });
                return Ok(hits);
            }
            search_k = (search_k * 2).min(max_search);
        }
    }

    fn warm_semantic_node_index(&self, scope: &ScopeKey, kind: &str) -> Result<(), StoreError> {
        if kind.is_empty() {
            return Ok(());
        }
        let _ = self.load_ann_query_state(scope, AnnIndexFamily::NodePrototype, Some(kind))?;
        Ok(())
    }

    fn warm_semantic_node_index_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        scope: &ScopeKey,
        kind: &str,
    ) -> Result<(), StoreError> {
        if kind.is_empty() {
            return Ok(());
        }
        let _ = self.load_ann_query_state_for_model(
            model_id,
            dimension,
            scope,
            AnnIndexFamily::NodePrototype,
            Some(kind),
        )?;
        Ok(())
    }

    fn warm_semantic_node_indexes(
        &self,
        scope: &ScopeKey,
        kinds: &[&str],
    ) -> Result<(), StoreError> {
        let mut kinds = kinds
            .iter()
            .copied()
            .filter(|kind| !kind.is_empty())
            .collect::<Vec<_>>();
        kinds.sort_unstable();
        kinds.dedup();
        if kinds.is_empty() {
            return Ok(());
        }
        if kinds.len() == 1 {
            return self.warm_semantic_node_index(scope, kinds[0]);
        }
        let _ = self.load_ann_query_state(scope, AnnIndexFamily::NodePrototype, None)?;
        Ok(())
    }

    fn warm_semantic_node_indexes_for_model(
        &self,
        model_id: &str,
        dimension: usize,
        scope: &ScopeKey,
        kinds: &[&str],
    ) -> Result<(), StoreError> {
        let mut kinds = kinds
            .iter()
            .copied()
            .filter(|kind| !kind.is_empty())
            .collect::<Vec<_>>();
        kinds.sort_unstable();
        kinds.dedup();
        if kinds.is_empty() {
            return Ok(());
        }
        if kinds.len() == 1 {
            return self.warm_semantic_node_index_for_model(model_id, dimension, scope, kinds[0]);
        }
        let _ = self.load_ann_query_state_for_model(
            model_id,
            dimension,
            scope,
            AnnIndexFamily::NodePrototype,
            None,
        )?;
        Ok(())
    }

    fn load_semantic_document_vector_records(
        &self,
        document_ids: &[String],
    ) -> Result<Vec<NativeSemanticDocumentVectorRecord>, StoreError> {
        let allowed = document_ids
            .iter()
            .map(String::as_str)
            .collect::<BTreeSet<_>>();
        self.with_engine(|engine| {
            let mut records = Vec::new();
            for node in engine
                .get_nodes_by_type(TYPE_ANN_SOURCE_DOCUMENT)
                .map_err(store_query_error)?
            {
                if !allowed.is_empty()
                    && !allowed.contains(
                        optional_string_prop(&node, PROP_DOCUMENT_ID)
                            .unwrap_or_default()
                            .as_str(),
                    )
                {
                    continue;
                }
                let record: AnnSourceDocumentRecord =
                    decode_record_prop_required(&node, PROP_RECORD)?;
                records.push(NativeSemanticDocumentVectorRecord {
                    scope: record.scope,
                    document_id: record.document_id,
                    values: record.values,
                    leaf_count: record.leaf_count,
                    evidence_refs: record.evidence_refs,
                    updated_at: record.updated_at,
                });
            }
            Ok(records)
        })
    }

    fn load_semantic_node_vector_records(
        &self,
        node_ids: &[String],
    ) -> Result<Vec<NativeSemanticNodeVectorRecord>, StoreError> {
        let allowed = node_ids.iter().map(String::as_str).collect::<BTreeSet<_>>();
        self.with_engine(|engine| {
            let mut records = Vec::new();
            for node in engine
                .get_nodes_by_type(TYPE_ANN_SOURCE_NODE)
                .map_err(store_query_error)?
            {
                if !allowed.is_empty()
                    && !allowed.contains(
                        optional_string_prop(&node, PROP_NODE_ID)
                            .unwrap_or_default()
                            .as_str(),
                    )
                {
                    continue;
                }
                let record: AnnSourceNodeRecord = decode_record_prop_required(&node, PROP_RECORD)?;
                records.push(NativeSemanticNodeVectorRecord {
                    scope: record.scope,
                    node_id: record.node_id,
                    node_kind: record.node_kind,
                    document_id: record.document_id,
                    note_id: record.note_id,
                    narrative_id: record.narrative_id,
                    folder_id: record.folder_id,
                    folder_path: record.folder_path,
                    values: record.values,
                    evidence_refs: record.evidence_refs,
                    updated_at: record.updated_at,
                });
            }
            Ok(records)
        })
    }
}

impl PhoenixGraphKernelStoreV2 for PhoenixOvergraphStore {
    fn init_graph_kernel_schema(&self) -> Result<(), StoreError> {
        Ok(())
    }

    fn load_live_kernel_snapshot(&self) -> Result<KernelGraphSnapshot, StoreError> {
        self.with_engine(|engine| self.load_live_kernel_snapshot_with_engine(engine))
    }

    fn load_kernel_checkpoint(&self) -> Result<Option<KernelCheckpointData>, StoreError> {
        self.with_engine(|engine| self.load_kernel_checkpoint_with_engine(engine))
    }

    fn write_kernel_checkpoint(
        &self,
        generation: u64,
        source_revision: &str,
        snapshot: &KernelGraphSnapshot,
    ) -> Result<KernelCheckpointData, StoreError> {
        self.with_engine(|engine| {
            self.write_kernel_checkpoint_with_engine(engine, generation, source_revision, snapshot)
        })
    }

    fn load_kernel_journal_after(
        &self,
        generation: u64,
    ) -> Result<Vec<KernelJournalEntry>, StoreError> {
        self.with_engine(|engine| self.load_kernel_journal_after_with_engine(engine, generation))
    }

    fn append_graph_truth_commit(
        &self,
        commit: &GraphTruthCommit,
    ) -> Result<GraphTruthCommitAppend, StoreError> {
        let result = self.with_engine(|engine| {
            graph_truth_persistence::append_graph_truth_commit_with_engine(self, engine, commit)
        })?;
        if matches!(result, GraphTruthCommitAppend::Appended) {
            self.invalidate_live_kernel_snapshot();
        }
        self.live_kernel_generation
            .store(commit.header.generation, Ordering::Release);
        self.after_canonical_graph_truth_commit(commit, commit.header.committed_at)?;
        if matches!(result, GraphTruthCommitAppend::Appended) {
            let _ = self.with_engine(|engine| {
                self.maybe_checkpoint_kernel_journal_with_engine(
                    engine,
                    commit.header.source_generations[0].source_id.as_str(),
                )
            });
        }
        Ok(result)
    }

    fn load_graph_truth_commit(
        &self,
        commit_id: &str,
    ) -> Result<Option<GraphTruthCommit>, StoreError> {
        self.with_engine(|engine| {
            graph_truth_persistence::load_graph_truth_commit_with_engine(engine, commit_id)
        })
    }

    fn load_graph_truth_commits(&self) -> Result<Vec<GraphTruthCommit>, StoreError> {
        self.with_engine(graph_truth_persistence::load_graph_truth_commits_with_engine)
    }

    fn kernel_generation_for_commit(&self, commit_id: &str) -> Result<Option<u64>, StoreError> {
        self.with_engine(|engine| {
            graph_truth_persistence::kernel_generation_for_commit_with_engine(engine, commit_id)
        })
    }

    fn kernel_current_generation(&self) -> Result<u64, StoreError> {
        self.with_engine(|engine| self.kernel_current_generation_with_engine(engine))
    }

    fn kernel_journal_len(&self) -> Result<usize, StoreError> {
        self.with_engine(|engine| self.kernel_journal_len_with_engine(engine))
    }
}

fn store_query_error(error: EngineError) -> StoreError {
    StoreError::Query(error.to_string())
}

fn read_env_usize(name: &str) -> Option<usize> {
    std::env::var(name).ok()?.parse().ok()
}

fn read_env_u64(name: &str) -> Option<u64> {
    std::env::var(name).ok()?.parse().ok()
}

fn read_env_u32(name: &str) -> Option<u32> {
    std::env::var(name).ok()?.parse().ok()
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

fn encode_record<T: Serialize + ?Sized>(value: &T) -> Result<Vec<u8>, StoreError> {
    rmp_serde::to_vec_named(value).map_err(|error| StoreError::Query(error.to_string()))
}

fn decode_record<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, StoreError> {
    rmp_serde::from_slice(bytes).map_err(|error| StoreError::Query(error.to_string()))
}

fn encode_archive<T: Serialize + ?Sized>(value: &T) -> Result<Vec<u8>, StoreError> {
    Ok(lz4_flex::compress_prepend_size(&encode_record(value)?))
}

fn decode_archive<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, StoreError> {
    let payload =
        decompress_size_prepended(bytes).map_err(|error| StoreError::Query(error.to_string()))?;
    decode_record(&payload)
}

fn decode_segment_payload<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, StoreError> {
    let payload =
        decompress_size_prepended(bytes).map_err(|error| StoreError::Query(error.to_string()))?;
    decode_record(&payload)
}

fn decode_record_prop<T: DeserializeOwned>(
    node: &NodeRecord,
    key: &str,
) -> Result<Option<T>, StoreError> {
    let Some(bytes) = optional_bytes_prop(node, key) else {
        return Ok(None);
    };
    decode_record(&bytes).map(Some)
}

fn decode_record_prop_required<T: DeserializeOwned>(
    node: &NodeRecord,
    key: &str,
) -> Result<T, StoreError> {
    decode_record(&required_bytes_prop(node, key)?)
}

fn required_u64_prop(node: &NodeRecord, key: &str) -> Result<u64, StoreError> {
    optional_u64_prop(node, key).ok_or_else(|| {
        StoreError::Query(format!("missing u64 property '{key}' on node {}", node.key))
    })
}

fn required_bytes_prop(node: &NodeRecord, key: &str) -> Result<Vec<u8>, StoreError> {
    if key == PROP_PAYLOAD && node.key.starts_with("ann-source:") {
        if let Some(record) = optional_bytes_prop(node, PROP_RECORD) {
            return Ok(record);
        }
    }
    optional_bytes_prop(node, key).ok_or_else(|| {
        StoreError::Query(format!(
            "missing bytes property '{key}' on node {}",
            node.key
        ))
    })
}

fn optional_u64_prop(node: &NodeRecord, key: &str) -> Option<u64> {
    match node.props.get(key) {
        Some(PropValue::UInt(value)) => Some(*value),
        Some(PropValue::Int(value)) if *value >= 0 => Some(*value as u64),
        _ => None,
    }
}

fn optional_string_prop(node: &NodeRecord, key: &str) -> Option<String> {
    match node.props.get(key) {
        Some(PropValue::String(value)) => Some(value.clone()),
        _ => None,
    }
}

fn optional_string_prop_ref<'a>(node: &'a NodeRecord, key: &str) -> Option<&'a str> {
    match node.props.get(key) {
        Some(PropValue::String(value)) => Some(value.as_str()),
        _ => None,
    }
}

fn optional_bytes_prop(node: &NodeRecord, key: &str) -> Option<Vec<u8>> {
    match node.props.get(key) {
        Some(PropValue::Bytes(value)) => Some(value.clone()),
        _ => None,
    }
}

fn optional_bytes_prop_ref<'a>(node: &'a NodeRecord, key: &str) -> Option<&'a [u8]> {
    match node.props.get(key) {
        Some(PropValue::Bytes(value)) => Some(value.as_slice()),
        _ => None,
    }
}

fn with_segment_payload<T>(
    store_path: &Path,
    node: &NodeRecord,
    f: impl FnOnce(&[u8]) -> Result<T, StoreError>,
) -> Result<T, StoreError> {
    if let Some(payload) = optional_bytes_prop_ref(node, PROP_PAYLOAD) {
        return f(payload);
    }
    if let Some(relative_path) = optional_string_prop_ref(node, PROP_PAYLOAD_PATH) {
        return prepared_segment_payload::with_segment_payload(store_path, relative_path, f);
    }
    let segment: PreparedDocumentSegment = decode_record_prop_required(node, PROP_RECORD)?;
    f(&segment.payload)
}

fn decode_segment_payload_from_node<T: DeserializeOwned>(
    store_path: &Path,
    node: &NodeRecord,
) -> Result<T, StoreError> {
    with_segment_payload(store_path, node, decode_segment_payload)
}

fn btree_props<const N: usize>(pairs: [(&str, PropValue); N]) -> BTreeMap<String, PropValue> {
    pairs
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value))
        .collect()
}

fn native_row_storage_key(relation: &str, row: &Value) -> Result<String, StoreError> {
    let spec = relation_spec(relation)?;
    let row = row.as_object().ok_or(StoreError::InvalidRow)?;
    let mut key = String::with_capacity(32 + relation.len() * 2);
    key.push_str("native-row:");
    push_native_row_key_segment(&mut key, relation);
    let mut key_count = 0;
    for column in spec.key_columns() {
        let value = row
            .get(column.name)
            .ok_or_else(|| StoreError::MissingColumn {
                relation: relation.to_owned(),
                column: column.name.to_owned(),
            })?;
        push_native_row_key_segment(&mut key, &native_row_key_value(value)?);
        key_count += 1;
    }
    if key_count == 0 {
        return Err(StoreError::Query(format!(
            "relation '{relation}' has no key columns"
        )));
    }
    Ok(key)
}

fn native_row_key_value(value: &Value) -> Result<String, StoreError> {
    match value {
        Value::Null => Ok("null".to_owned()),
        Value::Bool(value) => Ok(value.to_string()),
        Value::Number(value) => Ok(value.to_string()),
        Value::String(value) => Ok(value.clone()),
        Value::Array(_) | Value::Object(_) => {
            serde_json::to_string(value).map_err(|error| StoreError::Query(error.to_string()))
        }
    }
}

fn push_native_row_key_segment(key: &mut String, value: &str) {
    key.push_str(&value.len().to_string());
    key.push(':');
    key.push_str(value);
    key.push(':');
}

fn ann_family_name(family: AnnIndexFamily) -> &'static str {
    match family {
        AnnIndexFamily::Document => "document",
        AnnIndexFamily::Leaf => "leaf",
        AnnIndexFamily::NodePrototype => "node",
    }
}

fn sanitize_ann_kind(kind: &str) -> String {
    let sanitized = kind
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '_'
            }
        })
        .collect::<String>();
    if sanitized.is_empty() {
        "all".to_owned()
    } else {
        sanitized
    }
}

fn ann_index_storage_key(index: &AnnIndexKey) -> String {
    format!(
        "ann-index:{}:{}:{}:{}:{}",
        index.scope_ord.0,
        ann_family_name(index.family),
        sanitize_ann_kind(index.kind.as_deref().unwrap_or("all")),
        sanitize_ann_kind(index.model_id.as_str()),
        index.dimension
    )
}

fn ann_generation_storage_key(index: &AnnIndexKey, generation: AnnGenerationId) -> String {
    format!("{}:g{}", ann_index_storage_key(index), generation.0)
}

fn ann_source_row_key(
    scope_ord: ScopeOrd,
    family: AnnIndexFamily,
    kind: Option<&str>,
    model_id: &str,
    dimension: usize,
    stable_id: &str,
) -> String {
    format!(
        "ann-source:{}:{}:{}:{}:{}:{}",
        scope_ord.0,
        ann_family_name(family),
        sanitize_ann_kind(kind.unwrap_or("all")),
        sanitize_ann_kind(model_id),
        dimension,
        stable_id
    )
}

fn bundle_kind_name(kind: BundleKind) -> &'static str {
    match kind {
        BundleKind::DocumentArchive => "document-archive",
        BundleKind::SessionArchive => "session-archive",
        BundleKind::ScopeLexSidecar => "scope-lex-sidecar",
    }
}

fn bundle_storage_key(key: &BundleKey) -> String {
    format!(
        "{}::{}::{}::{}",
        bundle_kind_name(key.kind),
        key.scope,
        key.entity_key,
        key.revision
    )
}

fn segment_kind_name(kind: DocumentSegmentKind) -> &'static str {
    match kind {
        DocumentSegmentKind::StringArena => "string-arena",
        DocumentSegmentKind::SentenceTable => "sentence-table",
        DocumentSegmentKind::BoundaryTable => "boundary-table",
        DocumentSegmentKind::ChunkTable => "chunk-table",
        DocumentSegmentKind::MentionTable => "mention-table",
        DocumentSegmentKind::ResolverLinkTable => "resolver-link-table",
        DocumentSegmentKind::NarrativeHitTable => "narrative-hit-table",
        DocumentSegmentKind::EntityTable => "entity-table",
        DocumentSegmentKind::RelationTable => "relation-table",
        DocumentSegmentKind::EvidenceTable => "evidence-table",
        DocumentSegmentKind::LexicalPostings => "lexical-postings",
        DocumentSegmentKind::GraphMutation => "graph-mutation",
        DocumentSegmentKind::StructureRelations => "structure-relations",
        DocumentSegmentKind::ResolvedMentionTable => "resolved-mention-table",
        DocumentSegmentKind::AliasConfirmationTable => "alias-confirmation-table",
        DocumentSegmentKind::CorefClusterTable => "coref-cluster-table",
        DocumentSegmentKind::CausalSubstrateTable => "causal-substrate-table",
        DocumentSegmentKind::TemporalSubstrateTable => "temporal-substrate-table",
        DocumentSegmentKind::EventIdentitySubstrateTable => "event-identity-substrate-table",
    }
}

fn document_value_key(scope_key: &str, document_id: &str) -> String {
    format!("{scope_key}\u{1f}{}", document_id)
}

fn chunk_manifest_key(document_id: &str) -> String {
    format!("chunk-manifest\u{1f}{document_id}")
}

fn manifest_key(scope_ord: ScopeOrd, document_ord: DocumentOrd, revision: u64) -> String {
    format!("manifest:{}:{}:{}", scope_ord.0, document_ord.0, revision)
}

fn document_latest_key(scope_ord: ScopeOrd, document_ord: DocumentOrd) -> String {
    format!("latest:{}:{}", scope_ord.0, document_ord.0)
}

fn segment_key(
    scope_ord: ScopeOrd,
    document_ord: DocumentOrd,
    revision: u64,
    kind: DocumentSegmentKind,
    ordinal: u32,
) -> String {
    format!(
        "segment:{}:{}:{}:{}:{}",
        scope_ord.0,
        document_ord.0,
        revision,
        kind.as_u8(),
        ordinal
    )
}

fn session_archive_key(session_id: &SessionId, revision: u64) -> String {
    format!("session:{}:{}", session_id.0, revision)
}

fn session_archive_key_from_bundle(key: &BundleKey) -> String {
    format!("session:{}:{}", key.entity_key, key.revision)
}

fn kernel_journal_key(generation: u64, seq: u64) -> String {
    format!("kernel-journal:{}:{}", generation, seq)
}

fn parse_scope_key(scope_key: &str) -> ScopeKey {
    let mut parts = scope_key.split("::");
    ScopeKey {
        world_id: parse_scope_component(parts.next()),
        narrative_id: parse_scope_component(parts.next()),
        folder_id: parse_scope_component(parts.next()),
        folder_path: parse_scope_component(parts.next()),
    }
}

fn parse_scope_component(value: Option<&str>) -> Option<String> {
    value
        .filter(|value| *value != "__global__")
        .map(str::to_owned)
}

fn native_document_header_from_manifest(manifest: &DocumentManifest) -> BundleHeader {
    BundleHeader {
        key: BundleKey {
            kind: BundleKind::DocumentArchive,
            scope: manifest.scope_key.clone(),
            entity_key: manifest.document_id.clone(),
            revision: manifest.revision,
        },
        byte_len: manifest
            .segment_refs
            .iter()
            .map(|segment_ref| segment_ref.byte_len as usize)
            .sum(),
        created_at: manifest.created_at,
    }
}

fn native_session_header_from_node(node: NodeRecord) -> Result<BundleHeader, StoreError> {
    Ok(BundleHeader {
        key: BundleKey {
            kind: BundleKind::SessionArchive,
            scope: optional_string_prop(&node, PROP_SESSION_ID).unwrap_or_default(),
            entity_key: optional_string_prop(&node, PROP_SESSION_ID).unwrap_or_default(),
            revision: required_u64_prop(&node, PROP_REVISION)?,
        },
        byte_len: required_u64_prop(&node, PROP_BYTE_LEN)? as usize,
        created_at: match node.props.get(PROP_UPDATED_AT) {
            Some(PropValue::Int(value)) => *value,
            _ => 0,
        },
    })
}

fn native_sidecar_header_from_node(node: NodeRecord) -> Result<BundleHeader, StoreError> {
    let scope_key = optional_string_prop(&node, PROP_SCOPE_KEY).unwrap_or_default();
    Ok(BundleHeader {
        key: BundleKey {
            kind: BundleKind::ScopeLexSidecar,
            scope: scope_key.clone(),
            entity_key: scope_key,
            revision: required_u64_prop(&node, PROP_REVISION)?,
        },
        byte_len: required_u64_prop(&node, PROP_BYTE_LEN)? as usize,
        created_at: match node.props.get(PROP_CREATED_AT) {
            Some(PropValue::Int(value)) => *value,
            _ => 0,
        },
    })
}

fn compat_header_from_node(node: NodeRecord) -> Result<BundleHeader, StoreError> {
    let kind = match optional_string_prop(&node, PROP_KIND).as_deref() {
        Some("document-archive") => BundleKind::DocumentArchive,
        Some("session-archive") => BundleKind::SessionArchive,
        Some("scope-lex-sidecar") => BundleKind::ScopeLexSidecar,
        _ => {
            return Err(StoreError::Query(format!(
                "unknown compat bundle kind for node {}",
                node.key
            )))
        }
    };
    Ok(BundleHeader {
        key: BundleKey {
            kind,
            scope: optional_string_prop(&node, PROP_SCOPE_KEY).unwrap_or_default(),
            entity_key: optional_string_prop(&node, PROP_ENTITY_KEY).unwrap_or_default(),
            revision: required_u64_prop(&node, PROP_REVISION)?,
        },
        byte_len: required_u64_prop(&node, PROP_BYTE_LEN)? as usize,
        created_at: match node.props.get(PROP_CREATED_AT) {
            Some(PropValue::Int(value)) => *value,
            _ => 0,
        },
    })
}

fn alias_entries_to_map(
    entries: &[AliasEntry],
) -> BTreeMap<String, BTreeMap<(String, String), usize>> {
    let mut merged = BTreeMap::<String, BTreeMap<(String, String), usize>>::new();
    merge_alias_entries(&mut merged, entries);
    merged
}

fn merge_alias_entries(
    merged: &mut BTreeMap<String, BTreeMap<(String, String), usize>>,
    entries: &[AliasEntry],
) {
    for entry in entries {
        let postings = merged.entry(entry.normalized.clone()).or_default();
        for posting in &entry.postings {
            postings
                .entry((posting.entity_id.clone(), posting.document_id.clone()))
                .and_modify(|count| *count += posting.mention_count)
                .or_insert(posting.mention_count);
        }
    }
}

fn alias_entries_from_map(
    alias_entries: BTreeMap<String, BTreeMap<(String, String), usize>>,
) -> Vec<AliasEntry> {
    alias_entries
        .into_iter()
        .map(|(normalized, postings)| AliasEntry {
            normalized,
            postings: postings
                .into_iter()
                .map(|((entity_id, document_id), mention_count)| AliasPosting {
                    entity_id,
                    document_id,
                    mention_count,
                })
                .collect(),
        })
        .collect()
}

fn filter_alias_entries(
    entries: &[AliasEntry],
    excluded_document_ids: &BTreeSet<String>,
) -> Vec<AliasEntry> {
    entries
        .iter()
        .filter_map(|entry| {
            let postings = entry
                .postings
                .iter()
                .filter(|posting| !excluded_document_ids.contains(&posting.document_id))
                .cloned()
                .collect::<Vec<_>>();
            (!postings.is_empty()).then(|| AliasEntry {
                normalized: entry.normalized.clone(),
                postings,
            })
        })
        .collect()
}

fn entity_count_from_alias_entries(entries: &[AliasEntry]) -> usize {
    entries
        .iter()
        .flat_map(|entry| {
            entry
                .postings
                .iter()
                .map(|posting| posting.entity_id.as_str())
        })
        .collect::<BTreeSet<_>>()
        .len()
}

#[cfg(test)]
mod scope_runtime_tests;

#[cfg(test)]
mod lexical_query_tests;

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_store_native_core::{ChunkLens, PhoenixChunkManifestStore};
    use serde_json::json;

    fn temp_store_path(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "phoenix-overgraph-{name}-{}-{}",
            std::process::id(),
            now_ms()
        ))
    }

    fn temp_store(name: &str) -> PhoenixOvergraphStore {
        let path = temp_store_path(name);
        let _ = fs::remove_dir_all(&path);
        PhoenixOvergraphStore::open(&path).expect("open overgraph store")
    }

    #[test]
    fn native_row_store_round_trips_chat_and_om_rows() {
        let store = temp_store("native-row-store");
        store.init_schema().expect("init schema");

        store
            .put_row(
                "threads",
                json!({
                    "id": "thread-a",
                    "world_id": null,
                    "narrative_id": null,
                    "title": "Before",
                    "created_at": 1,
                    "updated_at": 1
                }),
            )
            .expect("put thread");
        store
            .put_row(
                "threads",
                json!({
                    "id": "thread-a",
                    "world_id": null,
                    "narrative_id": null,
                    "title": "After",
                    "created_at": 1,
                    "updated_at": 2
                }),
            )
            .expect("upsert thread");
        store
            .put_rows(
                "om_graph_entities",
                &[json!({
                    "thread_id": "thread-a",
                    "document_id": "om-summary-thread-a",
                    "entity_id": "entity-a",
                    "label": "Entity A",
                    "aliases": ["A"],
                    "mention_count": 2,
                    "snippet": "Entity A appears.",
                    "created_at": 3
                })],
            )
            .expect("put om graph entities");

        let threads = store.fetch_rows("threads").expect("fetch threads");
        assert_eq!(threads.len(), 1);
        assert_eq!(
            threads[0].get("title").and_then(Value::as_str),
            Some("After")
        );
        assert_eq!(
            store
                .relation_counts()
                .expect("relation counts")
                .into_iter()
                .find(|(relation, _)| relation == "om_graph_entities")
                .map(|(_, count)| count),
            Some(1)
        );

        let snapshot = store
            .export_snapshot_partition(SnapshotPartition::Content)
            .expect("export content snapshot");
        let imported = temp_store("native-row-store-import");
        let envelope = imported
            .import_snapshot(&snapshot)
            .expect("import snapshot");
        assert!(envelope.relations.contains_key("threads"));
        assert_eq!(
            imported
                .fetch_rows("om_graph_entities")
                .expect("imported om graph entities")
                .len(),
            1
        );

        let removed = store
            .delete_rows("threads", &threads)
            .expect("delete thread rows");
        assert_eq!(removed, 1);
        assert!(store
            .fetch_rows("threads")
            .expect("fetch after delete")
            .is_empty());
    }

    fn semantic_test_vector(seed: usize) -> Vec<f32> {
        semantic_test_vector_dim(seed, SEMANTIC_VECTOR_DIM)
    }

    fn semantic_test_vector_dim(seed: usize, dim: usize) -> Vec<f32> {
        let mut values = vec![0.0; dim];
        values[seed % dim] = 1.0;
        values[(seed + 17) % dim] = 0.5;
        values
    }

    #[test]
    fn publish_and_close_flushes_memtable_to_segment() {
        let path = temp_store_path("publish-and-close");
        let _ = fs::remove_dir_all(&path);
        let store = PhoenixOvergraphStore::open(&path).expect("open overgraph store");
        store
            .with_engine(|engine| {
                engine
                    .upsert_node(
                        TYPE_COMPAT_BUNDLE,
                        "publish-close-test",
                        UpsertNodeOptions::default(),
                    )
                    .map_err(store_query_error)?;
                Ok(())
            })
            .expect("write test node");

        store.publish_and_close().expect("publish close store");

        let reopened = PhoenixOvergraphStore::open(&path).expect("reopen published store");
        let segment_count = reopened
            .with_engine(|engine| Ok(engine.segment_count()))
            .expect("read segment count");
        assert!(
            segment_count > 0,
            "publish close should materialize at least one segment"
        );
        reopened.close_fast().expect("close reopened store");
        let _ = fs::remove_dir_all(&path);
    }

    #[test]
    fn semantic_ann_generation_roundtrip_queries_from_mmap_cache() {
        let store = temp_store("semantic-ann");
        let scope = ScopeKey::default();

        store
            .upsert_semantic_leaf_vectors(&[
                NativeSemanticLeafVectorRecord {
                    scope: scope.clone(),
                    span_id: "span-a".to_owned(),
                    document_id: "doc-a".to_owned(),
                    values: semantic_test_vector(0),
                    updated_at: 1,
                },
                NativeSemanticLeafVectorRecord {
                    scope: scope.clone(),
                    span_id: "span-b".to_owned(),
                    document_id: "doc-b".to_owned(),
                    values: semantic_test_vector(1),
                    updated_at: 1,
                },
            ])
            .expect("upsert leaf vectors");
        store
            .upsert_semantic_document_vectors_native(&[
                NativeSemanticDocumentVectorRecord {
                    scope: scope.clone(),
                    document_id: "doc-a".to_owned(),
                    values: semantic_test_vector(0),
                    leaf_count: 1,
                    evidence_refs: vec!["span:span-a".to_owned()],
                    updated_at: 1,
                },
                NativeSemanticDocumentVectorRecord {
                    scope: scope.clone(),
                    document_id: "doc-b".to_owned(),
                    values: semantic_test_vector(1),
                    leaf_count: 1,
                    evidence_refs: vec!["span:span-b".to_owned()],
                    updated_at: 1,
                },
            ])
            .expect("upsert document vectors");
        store
            .upsert_semantic_node_vectors_native(&[
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::a".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-a".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(0),
                    evidence_refs: vec!["graph_vertex:entity::a".to_owned()],
                    updated_at: 1,
                },
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::b".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-b".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(1),
                    evidence_refs: vec!["graph_vertex:entity::b".to_owned()],
                    updated_at: 1,
                },
            ])
            .expect("upsert node vectors");

        let doc_hits = store
            .query_semantic_documents(&semantic_test_vector(0), &scope, 2, 8)
            .expect("document query");
        assert_eq!(
            doc_hits.first().map(|hit| hit.document_id.as_str()),
            Some("doc-a")
        );
        let state = store
            .load_ann_query_state(&scope, AnnIndexFamily::Document, None)
            .expect("ann query state")
            .expect("document ann state");
        assert_eq!(state.manifest.metric, AnnMetric::LABEL_HYBRID_INTERIOR);

        let leaf_hits = store
            .query_semantic_neighbors_in_documents(
                &semantic_test_vector(0),
                &scope,
                &["doc-a".to_owned()],
                2,
                8,
            )
            .expect("leaf query");
        assert_eq!(
            leaf_hits.first().map(|hit| hit.span_id.as_str()),
            Some("span-a")
        );
        let leaf_authority = store
            .semantic_leaf_index_authority_for_model(
                SEMANTIC_MODEL_ID,
                "test-encoder-v1",
                SEMANTIC_VECTOR_DIM,
                &scope,
            )
            .expect("read leaf authority")
            .expect("leaf authority exists");
        let repeated_authority = store
            .semantic_leaf_index_authority_for_model(
                SEMANTIC_MODEL_ID,
                "test-encoder-v1",
                SEMANTIC_VECTOR_DIM,
                &scope,
            )
            .expect("read repeated leaf authority")
            .expect("repeated leaf authority exists");
        let revised_encoder = store
            .semantic_leaf_index_authority_for_model(
                SEMANTIC_MODEL_ID,
                "test-encoder-v2",
                SEMANTIC_VECTOR_DIM,
                &scope,
            )
            .expect("read revised encoder authority")
            .expect("revised encoder authority exists");
        assert_eq!(leaf_authority, repeated_authority);
        assert_eq!(leaf_authority.payload_count, 2);
        assert_eq!(leaf_authority.index_digest.len(), 64);
        assert_ne!(leaf_authority.index_digest, revised_encoder.index_digest);

        let node_hits = store
            .query_semantic_node_neighbors(&semantic_test_vector(0), &scope, "entity", None, 2, 8)
            .expect("node query");
        assert_eq!(
            node_hits.first().map(|hit| hit.node_id.as_str()),
            Some("entity::a")
        );

        let scope_ord = store
            .with_engine(|engine| store.lookup_scope_ord_with_engine(engine, &scope))
            .expect("lookup scope")
            .expect("scope ord");
        let cache_path = store.ann_cache_generation_path(
            &AnnIndexKey {
                scope_ord,
                family: AnnIndexFamily::Document,
                kind: None,
                model_id: SEMANTIC_MODEL_ID.to_owned(),
                dimension: SEMANTIC_VECTOR_DIM,
            },
            AnnGenerationId(1),
        );
        assert!(cache_path.exists(), "expected ANN mmap cache file to exist");

        store
            .upsert_semantic_document_vectors_native(&[
                NativeSemanticDocumentVectorRecord {
                    scope: scope.clone(),
                    document_id: "doc-a".to_owned(),
                    values: semantic_test_vector(2),
                    leaf_count: 1,
                    evidence_refs: vec!["span:span-a".to_owned()],
                    updated_at: 2,
                },
                NativeSemanticDocumentVectorRecord {
                    scope: scope.clone(),
                    document_id: "doc-b".to_owned(),
                    values: semantic_test_vector(0),
                    leaf_count: 1,
                    evidence_refs: vec!["span:span-b".to_owned()],
                    updated_at: 2,
                },
            ])
            .expect("update document vectors");

        let updated_hits = store
            .query_semantic_documents(&semantic_test_vector(0), &scope, 2, 8)
            .expect("updated query");
        assert_eq!(
            updated_hits.first().map(|hit| hit.document_id.as_str()),
            Some("doc-b")
        );
    }

    #[test]
    fn semantic_ann_indexes_are_partitioned_by_model_and_dimension() {
        let store = temp_store("semantic-ann-model-space");
        let scope = ScopeKey::default();
        let model_id = "onnx-community/embeddinggemma-300m-ONNX";
        let alt_dim = 768;

        store
            .upsert_semantic_node_vectors_native(&[NativeSemanticNodeVectorRecord {
                scope: scope.clone(),
                node_id: "entity::legacy".to_owned(),
                node_kind: "entity".to_owned(),
                document_id: Some("doc-legacy".to_owned()),
                note_id: None,
                narrative_id: None,
                folder_id: None,
                folder_path: None,
                values: semantic_test_vector(0),
                evidence_refs: vec!["graph_vertex:entity::legacy".to_owned()],
                updated_at: 1,
            }])
            .expect("upsert legacy vector");
        store
            .upsert_semantic_node_vectors_native_for_model(
                model_id,
                &[NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::gemma".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-gemma".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector_dim(4, alt_dim),
                    evidence_refs: vec!["graph_vertex:entity::gemma".to_owned()],
                    updated_at: 2,
                }],
            )
            .expect("upsert alternate vector");

        store
            .warm_semantic_node_index_for_model(model_id, alt_dim, &scope, "entity")
            .expect("warm alternate model index");
        let manifest = store
            .load_ann_manifest_for_model(
                model_id,
                alt_dim,
                &scope,
                AnnIndexFamily::NodePrototype,
                Some("entity"),
            )
            .expect("load alternate manifest")
            .expect("alternate manifest");
        assert_eq!(manifest.model_id, model_id);
        assert_eq!(manifest.dimension, alt_dim);

        let alt_hits = store
            .query_semantic_node_neighbors_for_model(
                model_id,
                alt_dim,
                &semantic_test_vector_dim(4, alt_dim),
                &scope,
                "entity",
                None,
                1,
                4,
            )
            .expect("alternate query");
        assert_eq!(
            alt_hits.first().map(|hit| hit.node_id.as_str()),
            Some("entity::gemma")
        );

        let legacy_hits = store
            .query_semantic_node_neighbors(&semantic_test_vector(0), &scope, "entity", None, 1, 4)
            .expect("legacy query");
        assert_eq!(
            legacy_hits.first().map(|hit| hit.node_id.as_str()),
            Some("entity::legacy")
        );
    }

    #[test]
    fn ann_query_state_is_retained_until_generation_changes() {
        let store = temp_store("ann-query-state-retained");
        let scope = ScopeKey::default();

        store
            .upsert_semantic_node_vectors_native(&[
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::a".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-a".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(0),
                    evidence_refs: vec!["graph_vertex:entity::a".to_owned()],
                    updated_at: 1,
                },
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::b".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-b".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(1),
                    evidence_refs: vec!["graph_vertex:entity::b".to_owned()],
                    updated_at: 1,
                },
            ])
            .expect("upsert node vectors");

        let initial = store
            .load_ann_query_state(&scope, AnnIndexFamily::NodePrototype, Some("entity"))
            .expect("initial ann query state")
            .expect("initial ann query state present");
        let retained = store
            .load_ann_query_state(&scope, AnnIndexFamily::NodePrototype, Some("entity"))
            .expect("retained ann query state")
            .expect("retained ann query state present");
        assert!(
            std::sync::Arc::ptr_eq(&initial, &retained),
            "expected repeated query-state loads to reuse the same retained runtime"
        );

        store
            .upsert_semantic_node_vectors_native(&[
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::a".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-a".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(2),
                    evidence_refs: vec!["graph_vertex:entity::a".to_owned()],
                    updated_at: 2,
                },
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::b".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-b".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(0),
                    evidence_refs: vec!["graph_vertex:entity::b".to_owned()],
                    updated_at: 2,
                },
            ])
            .expect("update node vectors");

        let refreshed = store
            .load_ann_query_state(&scope, AnnIndexFamily::NodePrototype, Some("entity"))
            .expect("refreshed ann query state")
            .expect("refreshed ann query state present");
        assert!(
            !std::sync::Arc::ptr_eq(&initial, &refreshed),
            "expected a new retained runtime after the ANN generation changed"
        );
        assert!(
            refreshed.manifest.generation_id.0 > initial.manifest.generation_id.0,
            "expected ANN generation to advance after vector updates"
        );
    }

    #[test]
    fn semantic_node_multi_kind_query_uses_live_union_across_kind_generations() {
        let store = temp_store("semantic-node-multi-kind-union");
        let scope = ScopeKey::default();

        store
            .upsert_semantic_node_vectors_native(&[NativeSemanticNodeVectorRecord {
                scope: scope.clone(),
                node_id: "entity::a".to_owned(),
                node_kind: "entity".to_owned(),
                document_id: Some("doc-a".to_owned()),
                note_id: None,
                narrative_id: None,
                folder_id: None,
                folder_path: None,
                values: semantic_test_vector(0),
                evidence_refs: vec!["graph_vertex:entity::a".to_owned()],
                updated_at: 1,
            }])
            .expect("upsert entity vectors");
        store
            .upsert_semantic_node_vectors_native(&[NativeSemanticNodeVectorRecord {
                scope: scope.clone(),
                node_id: "claim::a".to_owned(),
                node_kind: "claim".to_owned(),
                document_id: Some("doc-b".to_owned()),
                note_id: None,
                narrative_id: None,
                folder_id: None,
                folder_path: None,
                values: semantic_test_vector(0),
                evidence_refs: vec!["graph_vertex:claim::a".to_owned()],
                updated_at: 2,
            }])
            .expect("upsert claim vectors");

        let hits = store
            .query_semantic_node_neighbors_by_kinds(
                &semantic_test_vector(0),
                &scope,
                &["entity", "claim"],
                None,
                4,
                8,
            )
            .expect("multi-kind query");
        let hit_ids = hits
            .iter()
            .map(|hit| hit.node_id.as_str())
            .collect::<Vec<_>>();

        assert!(hit_ids.contains(&"entity::a"));
        assert!(hit_ids.contains(&"claim::a"));

        let composite = store
            .load_ann_query_state(&scope, AnnIndexFamily::NodePrototype, None)
            .expect("composite ann query state")
            .expect("composite ann query state present");
        assert_eq!(composite.manifest.count, 2);
    }

    #[test]
    fn semantic_node_multi_kind_query_respects_union_oversample() {
        let store = temp_store("semantic-node-multi-kind-oversample");
        let scope = ScopeKey::default();
        let mut rows = Vec::new();
        for index in 0..6 {
            rows.push(NativeSemanticNodeVectorRecord {
                scope: scope.clone(),
                node_id: format!("entity::{index}"),
                node_kind: "entity".to_owned(),
                document_id: Some(format!("doc-entity-{index}")),
                note_id: None,
                narrative_id: None,
                folder_id: None,
                folder_path: None,
                values: semantic_test_vector(index),
                evidence_refs: vec![format!("graph_vertex:entity::{index}")],
                updated_at: 1,
            });
            rows.push(NativeSemanticNodeVectorRecord {
                scope: scope.clone(),
                node_id: format!("claim::{index}"),
                node_kind: "claim".to_owned(),
                document_id: Some(format!("doc-claim-{index}")),
                note_id: None,
                narrative_id: None,
                folder_id: None,
                folder_path: None,
                values: semantic_test_vector(index),
                evidence_refs: vec![format!("graph_vertex:claim::{index}")],
                updated_at: 1,
            });
        }
        store
            .upsert_semantic_node_vectors_native(rows.as_slice())
            .expect("upsert node vectors");

        let hits = store
            .query_semantic_node_neighbors_by_kinds(
                &semantic_test_vector(0),
                &scope,
                &["entity", "claim"],
                None,
                3,
                4,
            )
            .expect("multi-kind query");

        assert_eq!(hits.len(), 4);
    }

    #[test]
    fn semantic_node_multi_kind_query_globally_ranks_across_kinds() {
        let store = temp_store("semantic-node-multi-kind-ranking");
        let scope = ScopeKey::default();

        store
            .upsert_semantic_node_vectors_native(&[
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::nearest".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-entity-nearest".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(0),
                    evidence_refs: vec!["graph_vertex:entity::nearest".to_owned()],
                    updated_at: 1,
                },
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "entity::far".to_owned(),
                    node_kind: "entity".to_owned(),
                    document_id: Some("doc-entity-far".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(9),
                    evidence_refs: vec!["graph_vertex:entity::far".to_owned()],
                    updated_at: 1,
                },
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "claim::middle".to_owned(),
                    node_kind: "claim".to_owned(),
                    document_id: Some("doc-claim-middle".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(1),
                    evidence_refs: vec!["graph_vertex:claim::middle".to_owned()],
                    updated_at: 1,
                },
            ])
            .expect("upsert node vectors");

        let hits = store
            .query_semantic_node_neighbors_by_kinds(
                &semantic_test_vector(0),
                &scope,
                &["entity", "claim"],
                None,
                2,
                2,
            )
            .expect("multi-kind query");
        let hit_ids = hits
            .iter()
            .map(|hit| hit.node_id.as_str())
            .collect::<Vec<_>>();

        assert_eq!(hit_ids, vec!["entity::nearest", "claim::middle"]);
        assert!(hits[0].distance <= hits[1].distance);
    }

    #[test]
    fn ann_source_payload_reads_fall_back_to_record_bytes() {
        let record = AnnSourceNodeRecord {
            scope: ScopeKey::default(),
            scope_key: scope_storage_key(&ScopeKey::default()),
            model_id: SEMANTIC_MODEL_ID.to_owned(),
            node_id: "chunk::a".to_owned(),
            node_kind: "chunk".to_owned(),
            document_id: Some("doc-a".to_owned()),
            note_id: None,
            narrative_id: None,
            folder_id: None,
            folder_path: None,
            values: semantic_test_vector(0),
            evidence_refs: vec!["chunk:0".to_owned()],
            updated_at: 1,
        };
        let record_bytes = encode_record(&record).expect("encode record");
        let node = NodeRecord {
            id: 1,
            type_id: TYPE_ANN_SOURCE_NODE,
            key: "ann-source:1:node:chunk:chunk::a".to_owned(),
            props: btree_props([(PROP_RECORD, PropValue::Bytes(record_bytes.clone()))]),
            weight: 1.0,
            created_at: 0,
            updated_at: 0,
            last_write_seq: 0,
            dense_vector: None,
            sparse_vector: None,
        };

        let payload = required_bytes_prop(&node, PROP_PAYLOAD).expect("payload fallback");
        assert_eq!(payload, record_bytes);
    }

    #[test]
    fn semantic_node_ann_rebuild_prefers_latest_batch() {
        let store = temp_store("semantic-node-latest-batch");
        let scope = ScopeKey::default();

        store
            .upsert_semantic_node_vectors_native(&[
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "chunk::stale".to_owned(),
                    node_kind: "chunk".to_owned(),
                    document_id: Some("doc-a".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(1),
                    evidence_refs: vec!["chunk:stale".to_owned()],
                    updated_at: 1,
                },
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "chunk::fresh-a".to_owned(),
                    node_kind: "chunk".to_owned(),
                    document_id: Some("doc-b".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(0),
                    evidence_refs: vec!["chunk:fresh-a".to_owned()],
                    updated_at: 2,
                },
                NativeSemanticNodeVectorRecord {
                    scope: scope.clone(),
                    node_id: "chunk::fresh-b".to_owned(),
                    node_kind: "chunk".to_owned(),
                    document_id: Some("doc-c".to_owned()),
                    note_id: None,
                    narrative_id: None,
                    folder_id: None,
                    folder_path: None,
                    values: semantic_test_vector(2),
                    evidence_refs: vec!["chunk:fresh-b".to_owned()],
                    updated_at: 2,
                },
            ])
            .expect("upsert node vectors");

        let hits = store
            .query_semantic_node_neighbors(&semantic_test_vector(0), &scope, "chunk", None, 4, 8)
            .expect("query node neighbors");
        let hit_ids = hits
            .iter()
            .map(|hit| hit.node_id.as_str())
            .collect::<Vec<_>>();

        assert!(hit_ids.contains(&"chunk::fresh-a"));
        assert!(hit_ids.contains(&"chunk::fresh-b"));
        assert!(!hit_ids.contains(&"chunk::stale"));
    }

    #[test]
    fn corrupt_graph_sidecar_is_quarantined_on_load() {
        let store = temp_store("corrupt-graph-sidecar");
        let scope = ScopeKey::default();
        let scope_key = scope_storage_key(&scope);

        store
            .with_engine(|engine| {
                engine
                    .upsert_node(
                        TYPE_GRAPH_PATCH_SIDECAR,
                        &scope_key,
                        UpsertNodeOptions {
                            props: btree_props([
                                (PROP_SCOPE_KEY, PropValue::String(scope_key.clone())),
                                (PROP_SCOPE_ORD, PropValue::Null),
                                (PROP_SESSION_ID, PropValue::Null),
                                (PROP_REVISION, PropValue::UInt(1)),
                                (PROP_UPDATED_AT, PropValue::Int(1)),
                                (PROP_BYTE_LEN, PropValue::UInt(4)),
                                (PROP_PAYLOAD, PropValue::Bytes(vec![1, 2, 3, 4])),
                            ]),
                            ..Default::default()
                        },
                    )
                    .map_err(store_query_error)?;
                Ok(())
            })
            .expect("write corrupt sidecar");

        let loaded = store
            .load_graph_patch_sidecar(&scope)
            .expect("load sidecar");
        assert!(loaded.is_none(), "corrupt sidecar should be quarantined");

        let still_present = store
            .with_engine(|engine| {
                engine
                    .get_node_by_key(TYPE_GRAPH_PATCH_SIDECAR, &scope_key)
                    .map_err(store_query_error)
            })
            .expect("query node");
        assert!(
            still_present.is_none(),
            "corrupt sidecar node should be deleted"
        );
    }

    #[test]
    fn chunk_manifest_round_trips_through_overgraph() {
        let store = temp_store("chunk-manifest");
        let mut lens_chunk_hashes = HashMap::new();
        lens_chunk_hashes.insert(ChunkLens::Entity, vec![11, 22]);
        let manifest = ChunkManifest {
            document_id: "doc".to_owned(),
            document_hash: 100,
            base_chunk_hashes: vec![1, 2],
            lens_chunk_hashes,
            ner_config_hash: 3,
            chunker_config_hash: 4,
            graph_config_hash: 5,
        };
        store
            .persist_chunk_manifest(&manifest)
            .expect("persist manifest");
        let loaded = store
            .load_chunk_manifest("doc")
            .expect("load manifest")
            .expect("manifest exists");
        assert_eq!(loaded, manifest);
    }
}

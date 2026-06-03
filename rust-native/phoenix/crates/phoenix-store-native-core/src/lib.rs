pub use phoenix_chunker::ChunkLens;
use phoenix_graph::{GraphMutationBatch, GraptorGraph};
use phoenix_graph_kernel::{
    KernelCheckpointData, KernelGraphSnapshot, KernelJournalEntry, KernelMutationBatch,
};
use phoenix_semantic_v2::{
    AliasPosting, CausalScopeSidecar, DirtyScopeRecord, DocumentArchive, DocumentManifest,
    DocumentOrdinalAssignment, DocumentRevisionRef, ErScopePatchSidecar, EventIdentityScopeSidecar,
    GraphScopeSidecar, MemoryScopeSidecar, PreparedDocument, RelationMentionSeedScopeSidecar,
    RelationScopePatchSidecar, ScopeLexSidecar, ScopeOrd, SemanticGraphScopeSidecar,
    SessionArchive, SessionOrd, StateSchemaScopeSidecar, TemporalScopeSidecar,
};
use phoenix_types::{IndexedSpan, IngestDocument, ScopeKey, SessionId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeSet, HashMap};
use std::path::PathBuf;
use thiserror::Error;

pub mod schema;
mod scope_runtime;
pub use schema::{
    PhoenixColumnSpec, PhoenixColumnType, PhoenixRelationSpec, ALL_RELATIONS,
    CONTENT_SNAPSHOT_RELATIONS, DERIVED_SNAPSHOT_RELATIONS,
};
pub use scope_runtime::{
    ArchiveSegmentMask, PhoenixScopeRuntimeStore, ScopeImageSpec, ScopeRuntimeImage,
    ScopeRuntimeIndices, ScopeSidecarBundle, ScopeSidecarMask,
};

pub const SEMANTIC_VECTOR_DIM: usize = 384;
pub const SEMANTIC_MODEL_ID: &str = "MongoDB/mdbr-leaf-mt";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotEnvelope {
    pub schema_version: String,
    pub relation_count: usize,
    pub created_at: i64,
    pub relations: std::collections::BTreeMap<String, Vec<Value>>,
    pub checksum: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SnapshotPartition {
    All,
    Content,
    Derived,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticNeighbor {
    pub span_id: String,
    pub distance: f64,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticDocumentNeighbor {
    pub document_id: String,
    pub distance: f64,
    pub leaf_count: usize,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticNodeNeighbor {
    pub node_id: String,
    pub node_kind: String,
    pub distance: f64,
    pub document_id: Option<String>,
    pub note_id: Option<String>,
    pub narrative_id: Option<String>,
    pub folder_id: Option<String>,
    pub folder_path: Option<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ScopeLexicalQueryDoc {
    pub node_id: String,
    pub node_kind: String,
    pub document_id: Option<String>,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ScopeLexicalQuerySidecar {
    pub scope: ScopeKey,
    pub scope_key: String,
    pub generation: u64,
    pub generated_at: i64,
    pub index_path: PathBuf,
    #[serde(default)]
    pub docs: Vec<ScopeLexicalQueryDoc>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkManifest {
    pub document_id: String,
    pub document_hash: u64,
    pub base_chunk_hashes: Vec<u64>,
    pub lens_chunk_hashes: HashMap<ChunkLens, Vec<u64>>,
    pub ner_config_hash: u64,
    pub chunker_config_hash: u64,
    pub graph_config_hash: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChunkManifestDirtyPlan {
    pub document_id: String,
    pub base_changed_indexes: Vec<usize>,
    pub rebuild_hints: bool,
    pub rebuild_all_lenses: bool,
    pub rebuild_lenses: Vec<ChunkLens>,
    pub rebuild_graph_edges_only: bool,
    pub preserve_manual_edges: bool,
    pub preserve_accepted_candidates: bool,
    pub preserve_rejected_candidates: bool,
    pub preserve_graph_positions: bool,
    pub preserve_stable_entity_ids: bool,
    pub preserve_stable_chunk_ids: bool,
}

impl ChunkManifestDirtyPlan {
    pub fn is_clean(&self) -> bool {
        self.base_changed_indexes.is_empty()
            && !self.rebuild_hints
            && !self.rebuild_all_lenses
            && self.rebuild_lenses.is_empty()
            && !self.rebuild_graph_edges_only
    }
}

impl ChunkManifest {
    pub fn dirty_plan_against(&self, previous: Option<&ChunkManifest>) -> ChunkManifestDirtyPlan {
        let Some(previous) = previous else {
            return ChunkManifestDirtyPlan {
                document_id: self.document_id.clone(),
                base_changed_indexes: (0..self.base_chunk_hashes.len()).collect(),
                rebuild_hints: true,
                rebuild_all_lenses: true,
                rebuild_lenses: self.sorted_lenses(),
                rebuild_graph_edges_only: true,
                preserve_manual_edges: true,
                preserve_accepted_candidates: true,
                preserve_rejected_candidates: true,
                preserve_graph_positions: true,
                preserve_stable_entity_ids: true,
                preserve_stable_chunk_ids: false,
            };
        };

        let base_changed_indexes =
            changed_hash_indexes(&previous.base_chunk_hashes, &self.base_chunk_hashes);
        let ner_changed = previous.ner_config_hash != self.ner_config_hash;
        let chunker_changed = previous.chunker_config_hash != self.chunker_config_hash;
        let graph_changed = previous.graph_config_hash != self.graph_config_hash;
        let document_changed = previous.document_hash != self.document_hash;
        let mut rebuild_lenses = BTreeSet::new();
        for lens in previous
            .lens_chunk_hashes
            .keys()
            .chain(self.lens_chunk_hashes.keys())
        {
            if previous.lens_chunk_hashes.get(lens) != self.lens_chunk_hashes.get(lens) {
                rebuild_lenses.insert(*lens);
            }
        }
        if document_changed || chunker_changed || !base_changed_indexes.is_empty() {
            rebuild_lenses.extend(self.sorted_lenses());
        }

        ChunkManifestDirtyPlan {
            document_id: self.document_id.clone(),
            base_changed_indexes,
            rebuild_hints: ner_changed || document_changed,
            rebuild_all_lenses: chunker_changed || document_changed,
            rebuild_lenses: rebuild_lenses.into_iter().collect(),
            rebuild_graph_edges_only: graph_changed,
            preserve_manual_edges: true,
            preserve_accepted_candidates: true,
            preserve_rejected_candidates: true,
            preserve_graph_positions: true,
            preserve_stable_entity_ids: true,
            preserve_stable_chunk_ids: !document_changed && !chunker_changed,
        }
    }

    fn sorted_lenses(&self) -> Vec<ChunkLens> {
        let mut lenses = self.lens_chunk_hashes.keys().copied().collect::<Vec<_>>();
        lenses.sort_unstable();
        lenses
    }
}

fn changed_hash_indexes(previous: &[u64], current: &[u64]) -> Vec<usize> {
    let len = previous.len().max(current.len());
    (0..len)
        .filter(|index| previous.get(*index) != current.get(*index))
        .collect()
}

#[derive(Debug, Error)]
pub enum StoreError {
    #[error("unknown relation: {0}")]
    UnknownRelation(String),
    #[error("row must be a JSON object")]
    InvalidRow,
    #[error("missing required column '{column}' in relation '{relation}'")]
    MissingColumn { relation: String, column: String },
    #[error("native store init failed: {0}")]
    Init(String),
    #[error("native store schema failed: {0}")]
    Schema(String),
    #[error("native store query failed: {0}")]
    Query(String),
    #[error("snapshot decode failed: {0}")]
    Snapshot(String),
}

pub const NATIVE_COVERED_RELATIONS: &[&str] = &[
    "phoenix_schema_state",
    "phoenix_sessions",
    "phoenix_commits",
    "phoenix_ingest_log",
    "phoenix_query_log",
    "notes",
    "entities",
    "edges",
    "folders",
    "docid_map",
    "chunkid_map",
    "chunks",
    "raptor_nodes",
    "raptor_edges",
    "episodes",
    "spans",
    "wormholes",
    "span_mentions",
    "discovery_candidates",
    "blocks",
    "document_boundaries",
    "entity_cards",
    "folder_schemas",
    "scoped_documents",
    "scoped_entity_fields",
    "scoped_definitions",
    "network_instance",
    "network_membership",
    "network_relationship",
];

pub const NATIVE_GRAPH_COMPAT_RELATIONS: &[&str] = &[
    "graph_vertices",
    "graph_edges",
    "graph_candidate_edges",
    "graph_node_index",
    "graph_properties",
    "graph_vertex_labels",
];

pub const PHOENIX_GRAPH_CHECKPOINT_META: &[PhoenixColumnSpec] = &[
    PhoenixColumnSpec::new("checkpoint_id", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("generation", PhoenixColumnType::Int, false, false),
    PhoenixColumnSpec::new("source_revision", PhoenixColumnType::String, false, false),
    PhoenixColumnSpec::new("created_at", PhoenixColumnType::Int, false, false),
];

pub const PHOENIX_GRAPH_VERTEX_SNAPSHOT: &[PhoenixColumnSpec] = &[
    PhoenixColumnSpec::new("checkpoint_id", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("vertex_id", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("record_json", PhoenixColumnType::Json, false, false),
    PhoenixColumnSpec::new("created_at", PhoenixColumnType::Int, false, false),
];

pub const PHOENIX_GRAPH_EDGE_SNAPSHOT: &[PhoenixColumnSpec] = &[
    PhoenixColumnSpec::new("checkpoint_id", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("layer", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("source_id", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("target_id", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("edge_type", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("record_json", PhoenixColumnType::Json, false, false),
    PhoenixColumnSpec::new("created_at", PhoenixColumnType::Int, false, false),
];

pub const PHOENIX_GRAPH_DELTA_JOURNAL: &[PhoenixColumnSpec] = &[
    PhoenixColumnSpec::new("entry_id", PhoenixColumnType::String, false, true),
    PhoenixColumnSpec::new("generation", PhoenixColumnType::Int, false, false),
    PhoenixColumnSpec::new("source_revision", PhoenixColumnType::String, false, false),
    PhoenixColumnSpec::new("batch_json", PhoenixColumnType::Json, true, false),
    PhoenixColumnSpec::new("commit_id", PhoenixColumnType::String, true, false),
    PhoenixColumnSpec::new("created_at", PhoenixColumnType::Int, false, false),
];

pub const INTERNAL_RELATIONS: &[PhoenixRelationSpec] = &[
    PhoenixRelationSpec::new(
        "phoenix_graph_checkpoint_meta",
        PHOENIX_GRAPH_CHECKPOINT_META,
    ),
    PhoenixRelationSpec::new(
        "phoenix_graph_vertex_snapshot",
        PHOENIX_GRAPH_VERTEX_SNAPSHOT,
    ),
    PhoenixRelationSpec::new("phoenix_graph_edge_snapshot", PHOENIX_GRAPH_EDGE_SNAPSHOT),
    PhoenixRelationSpec::new("phoenix_graph_delta_journal", PHOENIX_GRAPH_DELTA_JOURNAL),
];

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScopedDocumentFilter<'a> {
    pub namespace: Option<&'a str>,
    pub narrative_id: Option<&'a str>,
    pub document_key: Option<&'a str>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScopedDefinitionFilter<'a> {
    pub namespace: Option<&'a str>,
    pub narrative_id: Option<&'a str>,
    pub definition_key: Option<&'a str>,
    pub definition_key_prefix: Option<&'a str>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCheckpointMeta {
    pub checkpoint_id: String,
    pub generation: u64,
    pub source_revision: String,
    pub created_at: i64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphCheckpointData {
    pub meta: GraphCheckpointMeta,
    pub asserted_batch: GraphMutationBatch,
    pub candidate_batch: GraphMutationBatch,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphJournalEntry {
    pub generation: u64,
    pub source_revision: String,
    pub batch: Option<GraphMutationBatch>,
    pub commit_id: Option<String>,
    pub created_at: i64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum BundleKind {
    #[default]
    DocumentArchive,
    SessionArchive,
    ScopeLexSidecar,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BundleKey {
    pub kind: BundleKind,
    pub scope: String,
    pub entity_key: String,
    pub revision: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BundleHeader {
    pub key: BundleKey,
    pub byte_len: usize,
    pub created_at: i64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum IngestMode {
    #[default]
    Safe,
    BulkBuild,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PreparedIngestContext {
    pub session_id: Option<SessionId>,
    pub session_ord: Option<SessionOrd>,
    #[serde(default)]
    pub assignments: Vec<DocumentOrdinalAssignment>,
    pub kernel_snapshot: Option<KernelGraphSnapshot>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AnnIndexFamily {
    Document,
    Leaf,
    NodePrototype,
}

#[derive(
    Clone, Copy, Debug, Default, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize,
)]
#[serde(transparent)]
pub struct AnnGenerationId(pub u64);

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AnnIndexKey {
    pub scope_ord: ScopeOrd,
    pub family: AnnIndexFamily,
    pub kind: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AnnManifest {
    pub index: AnnIndexKey,
    pub generation_id: AnnGenerationId,
    pub built_at: i64,
    pub dimension: usize,
    pub model_id: String,
    pub count: usize,
    pub entry_point: u32,
    pub max_level: u32,
    pub m: usize,
    pub m0: usize,
    pub ef_construction: usize,
    pub level_mult: f32,
    pub metric: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AnnPackedSegments {
    pub vectors: Vec<u8>,
    pub levels: Vec<u8>,
    pub offsets: Vec<u8>,
    pub adjacency: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeSemanticLeafVectorRecord {
    pub scope: ScopeKey,
    pub span_id: String,
    pub document_id: String,
    pub values: Vec<f32>,
    pub updated_at: i64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeSemanticDocumentVectorRecord {
    pub scope: ScopeKey,
    pub document_id: String,
    pub values: Vec<f32>,
    pub leaf_count: usize,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
    pub updated_at: i64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeSemanticNodeVectorRecord {
    pub scope: ScopeKey,
    pub node_id: String,
    pub node_kind: String,
    pub document_id: Option<String>,
    pub note_id: Option<String>,
    pub narrative_id: Option<String>,
    pub folder_id: Option<String>,
    pub folder_path: Option<String>,
    pub values: Vec<f32>,
    #[serde(default)]
    pub evidence_refs: Vec<String>,
    pub updated_at: i64,
}

pub trait PhoenixNativeRowStore {
    fn init_schema(&self) -> Result<(), StoreError>;
    fn relation_names(&self) -> Vec<&'static str>;
    fn relation_counts(&self) -> Result<Vec<(String, usize)>, StoreError>;
    fn fetch_rows(&self, relation: &str) -> Result<Vec<Value>, StoreError>;
    fn put_row(&self, relation: &str, row: Value) -> Result<(), StoreError>;
    fn put_rows(&self, relation: &str, rows: &[Value]) -> Result<(), StoreError>;
    fn replace_relation_rows(&self, relation: &str, rows: &[Value]) -> Result<(), StoreError>;
    fn delete_rows(&self, relation: &str, rows: &[Value]) -> Result<usize, StoreError>;
    fn clear_relations(&self, relations: &[&str]) -> Result<(), StoreError>;
    fn export_snapshot_partition(
        &self,
        partition: SnapshotPartition,
    ) -> Result<Vec<u8>, StoreError>;
    fn import_snapshot(&self, bytes: &[u8]) -> Result<SnapshotEnvelope, StoreError>;

    fn fetch_scoped_documents(
        &self,
        filter: ScopedDocumentFilter<'_>,
    ) -> Result<Vec<Value>, StoreError> {
        let mut rows = self.fetch_rows("scoped_documents")?;
        rows.retain(|row| matches_scoped_document_filter(row, &filter));
        Ok(rows)
    }

    fn fetch_scoped_definitions(
        &self,
        filter: ScopedDefinitionFilter<'_>,
    ) -> Result<Vec<Value>, StoreError> {
        let mut rows = self.fetch_rows("scoped_definitions")?;
        rows.retain(|row| matches_scoped_definition_filter(row, &filter));
        Ok(rows)
    }
}

pub trait PhoenixGraphDurabilityStore {
    fn load_graph_checkpoint(&self) -> Result<Option<GraphCheckpointData>, StoreError>;
    fn write_graph_checkpoint(
        &self,
        generation: u64,
        source_revision: &str,
        graph: &GraptorGraph,
    ) -> Result<GraphCheckpointData, StoreError>;
    fn load_graph_journal_after(
        &self,
        generation: u64,
    ) -> Result<Vec<GraphJournalEntry>, StoreError>;
    fn append_graph_batch(
        &self,
        generation: u64,
        source_revision: &str,
        batch: &GraphMutationBatch,
        created_at: i64,
    ) -> Result<(), StoreError>;
    fn append_commit_marker(
        &self,
        generation: u64,
        source_revision: &str,
        commit_id: &str,
        created_at: i64,
    ) -> Result<(), StoreError>;
    fn generation_for_commit(&self, commit_id: &str) -> Result<Option<u64>, StoreError>;
    fn current_generation(&self) -> Result<u64, StoreError>;
    fn journal_len(&self) -> Result<usize, StoreError>;
}

pub trait PhoenixBundleStoreV2 {
    fn init_bundle_schema(&self) -> Result<(), StoreError>;
    fn put_bundle(&self, header: &BundleHeader, payload: &[u8]) -> Result<(), StoreError>;
    fn get_bundle(&self, key: &BundleKey) -> Result<Option<Vec<u8>>, StoreError>;
    fn get_bundle_header(&self, key: &BundleKey) -> Result<Option<BundleHeader>, StoreError>;
    fn list_bundle_headers(
        &self,
        kind: BundleKind,
        scope: Option<&str>,
    ) -> Result<Vec<BundleHeader>, StoreError>;
    fn delete_bundle(&self, key: &BundleKey) -> Result<bool, StoreError>;
}

pub trait PhoenixChunkManifestStore {
    fn init_chunk_manifest_schema(&self) -> Result<(), StoreError>;
    fn persist_chunk_manifest(&self, manifest: &ChunkManifest) -> Result<(), StoreError>;
    fn load_chunk_manifest(&self, document_id: &str) -> Result<Option<ChunkManifest>, StoreError>;
    fn plan_chunk_manifest_update(
        &self,
        manifest: &ChunkManifest,
    ) -> Result<ChunkManifestDirtyPlan, StoreError> {
        let previous = self.load_chunk_manifest(&manifest.document_id)?;
        Ok(manifest.dirty_plan_against(previous.as_ref()))
    }
}

pub trait PhoenixArchiveStoreV2 {
    fn init_archive_schema(&self) -> Result<(), StoreError>;
    fn ingest_mode(&self) -> IngestMode;
    fn prepare_ingest_context(
        &self,
        session_id: Option<&SessionId>,
        documents: &[IngestDocument],
        revision: u64,
    ) -> Result<PreparedIngestContext, StoreError>;
    fn persist_prepared_documents(
        &self,
        prepared: &[PreparedDocument],
        session_archive: Option<&SessionArchive>,
        touched_scopes: &[DirtyScopeRecord],
        created_at: i64,
    ) -> Result<(), StoreError>;
    fn persist_session_archive(
        &self,
        archive: &SessionArchive,
        revision: u64,
        created_at: i64,
    ) -> Result<(), StoreError>;
    fn load_latest_session_archive(
        &self,
        session_id: &SessionId,
    ) -> Result<Option<SessionArchive>, StoreError>;
    fn load_latest_document_archives(
        &self,
        scope: Option<&ScopeKey>,
    ) -> Result<Vec<DocumentArchive>, StoreError>;
    fn load_document_manifest(
        &self,
        document_ref: &DocumentRevisionRef,
    ) -> Result<Option<DocumentManifest>, StoreError>;
    fn load_scope_sidecar(&self, scope: &ScopeKey) -> Result<Option<ScopeLexSidecar>, StoreError>;
    fn load_materialized_scope_lexical(
        &self,
        scope: &ScopeKey,
    ) -> Result<ScopeLexSidecar, StoreError>;
    fn load_lex_spans(&self, scope: Option<&ScopeKey>) -> Result<Vec<IndexedSpan>, StoreError>;
    fn lookup_alias_postings(
        &self,
        scope: &ScopeKey,
        normalized: &str,
    ) -> Result<Vec<AliasPosting>, StoreError>;
    fn rebuild_dirty_scope_sidecars(&self, created_at: i64) -> Result<usize, StoreError>;
    fn list_dirty_scopes(&self) -> Result<Vec<DirtyScopeRecord>, StoreError>;
}

pub trait PhoenixLexicalQueryStore {
    fn load_scope_lexical_query_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<ScopeLexicalQuerySidecar>, StoreError>;
}

pub trait PhoenixErPatchStore {
    fn init_er_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_er_patch_sidecar(&self, sidecar: &ErScopePatchSidecar) -> Result<(), StoreError>;
    fn load_er_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<ErScopePatchSidecar>, StoreError>;
}

pub trait PhoenixRelationPatchStore {
    fn init_relation_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_relation_patch_sidecar(
        &self,
        sidecar: &RelationScopePatchSidecar,
    ) -> Result<(), StoreError>;
    fn load_relation_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<RelationScopePatchSidecar>, StoreError>;
}

pub trait PhoenixMemoryPatchStore {
    fn init_memory_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_memory_patch_sidecar(&self, sidecar: &MemoryScopeSidecar) -> Result<(), StoreError>;
    fn load_memory_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<MemoryScopeSidecar>, StoreError>;
}

pub trait PhoenixGraphPatchStore {
    fn init_graph_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_graph_patch_sidecar(&self, sidecar: &GraphScopeSidecar) -> Result<(), StoreError>;
    fn load_graph_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<GraphScopeSidecar>, StoreError>;
}

pub trait PhoenixSemanticGraphPatchStore {
    fn init_semantic_graph_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_semantic_graph_patch_sidecar(
        &self,
        sidecar: &SemanticGraphScopeSidecar,
    ) -> Result<(), StoreError>;
    fn load_semantic_graph_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<SemanticGraphScopeSidecar>, StoreError>;
}

pub trait PhoenixCausalPatchStore {
    fn init_causal_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_causal_patch_sidecar(&self, sidecar: &CausalScopeSidecar) -> Result<(), StoreError>;
    fn load_causal_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<CausalScopeSidecar>, StoreError>;
}

pub trait PhoenixTemporalPatchStore {
    fn init_temporal_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_temporal_patch_sidecar(
        &self,
        sidecar: &TemporalScopeSidecar,
    ) -> Result<(), StoreError>;
    fn load_temporal_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<TemporalScopeSidecar>, StoreError>;
}

pub trait PhoenixEventIdentityPatchStore {
    fn init_event_identity_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_event_identity_patch_sidecar(
        &self,
        sidecar: &EventIdentityScopeSidecar,
    ) -> Result<(), StoreError>;
    fn load_event_identity_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<EventIdentityScopeSidecar>, StoreError>;
}

pub trait PhoenixStateSchemaPatchStore {
    fn init_state_schema_patch_schema(&self) -> Result<(), StoreError>;
    fn persist_state_schema_patch_sidecar(
        &self,
        sidecar: &StateSchemaScopeSidecar,
    ) -> Result<(), StoreError>;
    fn load_state_schema_patch_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<StateSchemaScopeSidecar>, StoreError>;
}

pub trait PhoenixRelationMentionSeedStore {
    fn init_relation_mention_seed_schema(&self) -> Result<(), StoreError>;
    fn persist_relation_mention_seed_sidecar(
        &self,
        sidecar: &RelationMentionSeedScopeSidecar,
    ) -> Result<(), StoreError>;
    fn load_relation_mention_seed_sidecar(
        &self,
        scope: &ScopeKey,
    ) -> Result<Option<RelationMentionSeedScopeSidecar>, StoreError>;
}

pub trait PhoenixSemanticIndexStore {
    fn semantic_model_id(&self) -> &'static str {
        SEMANTIC_MODEL_ID
    }

    fn semantic_vector_dim(&self) -> usize {
        SEMANTIC_VECTOR_DIM
    }

    fn upsert_semantic_leaf_vectors(
        &self,
        rows: &[NativeSemanticLeafVectorRecord],
    ) -> Result<(), StoreError>;
    fn upsert_semantic_document_vectors_native(
        &self,
        rows: &[NativeSemanticDocumentVectorRecord],
    ) -> Result<(), StoreError>;
    fn upsert_semantic_node_vectors_native(
        &self,
        rows: &[NativeSemanticNodeVectorRecord],
    ) -> Result<(), StoreError>;
    fn upsert_semantic_node_vectors_native_owned(
        &self,
        rows: Vec<NativeSemanticNodeVectorRecord>,
    ) -> Result<(), StoreError> {
        self.upsert_semantic_node_vectors_native(&rows)
    }
    fn query_semantic_neighbors(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNeighbor>, StoreError>;
    fn query_semantic_documents(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticDocumentNeighbor>, StoreError>;
    fn query_semantic_neighbors_in_documents(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        document_ids: &[String],
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNeighbor>, StoreError>;
    fn query_semantic_node_neighbors(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        kind: &str,
        exclude_node_id: Option<&str>,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNodeNeighbor>, StoreError>;
    /// Query semantic node neighbors across multiple kinds using one merged ranking.
    ///
    /// Implementations must return a single globally ranked result set across the
    /// unique non-empty `kinds`, with `limit`/`oversample` applying to that merged
    /// search surface. Returned neighbors must be ordered by ascending distance and
    /// should preserve up to `oversample.max(limit)` merged candidates when
    /// available. Concatenating per-kind top-k lists is not equivalent and is not
    /// a valid implementation of this contract.
    fn query_semantic_node_neighbors_by_kinds(
        &self,
        query_vector: &[f32],
        scope: &ScopeKey,
        kinds: &[&str],
        exclude_node_id: Option<&str>,
        limit: usize,
        oversample: usize,
    ) -> Result<Vec<SemanticNodeNeighbor>, StoreError>;
    fn warm_semantic_node_index(&self, scope: &ScopeKey, kind: &str) -> Result<(), StoreError>;
    fn warm_semantic_node_indexes(
        &self,
        scope: &ScopeKey,
        kinds: &[&str],
    ) -> Result<(), StoreError> {
        for kind in normalized_semantic_node_kinds(kinds) {
            self.warm_semantic_node_index(scope, kind)?;
        }
        Ok(())
    }
    fn load_semantic_document_vector_records(
        &self,
        document_ids: &[String],
    ) -> Result<Vec<NativeSemanticDocumentVectorRecord>, StoreError>;
    fn load_semantic_node_vector_records(
        &self,
        node_ids: &[String],
    ) -> Result<Vec<NativeSemanticNodeVectorRecord>, StoreError>;
}

fn normalized_semantic_node_kinds<'a>(kinds: &[&'a str]) -> Vec<&'a str> {
    let mut rows = kinds
        .iter()
        .copied()
        .filter(|kind| !kind.is_empty())
        .collect::<Vec<_>>();
    rows.sort_unstable();
    rows.dedup();
    rows
}

pub trait PhoenixDirectGraphStoreV2 {
    fn init_direct_graph_schema(&self) -> Result<(), StoreError>;
    fn load_direct_graph_checkpoint(&self) -> Result<Option<GraphCheckpointData>, StoreError>;
    fn write_direct_graph_checkpoint(
        &self,
        generation: u64,
        source_revision: &str,
        graph: &GraptorGraph,
    ) -> Result<GraphCheckpointData, StoreError>;
    fn load_direct_graph_journal_after(
        &self,
        generation: u64,
    ) -> Result<Vec<GraphJournalEntry>, StoreError>;
    fn append_direct_graph_batch(
        &self,
        generation: u64,
        source_revision: &str,
        batch: &GraphMutationBatch,
        created_at: i64,
    ) -> Result<(), StoreError>;
    fn append_direct_graph_commit_marker(
        &self,
        generation: u64,
        source_revision: &str,
        commit_id: &str,
        created_at: i64,
    ) -> Result<(), StoreError>;
    fn direct_graph_generation_for_commit(
        &self,
        commit_id: &str,
    ) -> Result<Option<u64>, StoreError>;
    fn direct_graph_current_generation(&self) -> Result<u64, StoreError>;
    fn direct_graph_journal_len(&self) -> Result<usize, StoreError>;
}

pub trait PhoenixGraphKernelStoreV2 {
    fn init_graph_kernel_schema(&self) -> Result<(), StoreError>;
    fn load_kernel_checkpoint(&self) -> Result<Option<KernelCheckpointData>, StoreError>;
    fn write_kernel_checkpoint(
        &self,
        generation: u64,
        source_revision: &str,
        snapshot: &KernelGraphSnapshot,
    ) -> Result<KernelCheckpointData, StoreError>;
    fn load_kernel_journal_after(
        &self,
        generation: u64,
    ) -> Result<Vec<KernelJournalEntry>, StoreError>;
    fn append_kernel_batch(
        &self,
        generation: u64,
        source_revision: &str,
        batch: &KernelMutationBatch,
        created_at: i64,
    ) -> Result<(), StoreError>;
    fn append_kernel_commit_marker(
        &self,
        generation: u64,
        source_revision: &str,
        commit_id: &str,
        created_at: i64,
    ) -> Result<(), StoreError>;
    fn kernel_generation_for_commit(&self, commit_id: &str) -> Result<Option<u64>, StoreError>;
    fn kernel_current_generation(&self) -> Result<u64, StoreError>;
    fn kernel_journal_len(&self) -> Result<usize, StoreError>;
}

pub trait PhoenixNativeStore: PhoenixNativeRowStore + PhoenixGraphDurabilityStore {}

impl<T> PhoenixNativeStore for T where T: PhoenixNativeRowStore + PhoenixGraphDurabilityStore {}

#[cfg(test)]
mod chunk_manifest_tests {
    use super::*;

    fn manifest(document_hash: u64) -> ChunkManifest {
        let mut lens_chunk_hashes = HashMap::new();
        lens_chunk_hashes.insert(ChunkLens::Entity, vec![10, 20]);
        lens_chunk_hashes.insert(ChunkLens::Relationship, vec![30]);
        ChunkManifest {
            document_id: "doc".to_owned(),
            document_hash,
            base_chunk_hashes: vec![1, 2, 3],
            lens_chunk_hashes,
            ner_config_hash: 4,
            chunker_config_hash: 5,
            graph_config_hash: 6,
        }
    }

    #[test]
    fn unchanged_manifest_is_clean_and_preserves_ids() {
        let current = manifest(100);
        let plan = current.dirty_plan_against(Some(&current));
        assert!(plan.is_clean());
        assert!(plan.preserve_manual_edges);
        assert!(plan.preserve_accepted_candidates);
        assert!(plan.preserve_rejected_candidates);
        assert!(plan.preserve_graph_positions);
        assert!(plan.preserve_stable_entity_ids);
        assert!(plan.preserve_stable_chunk_ids);
    }

    #[test]
    fn changed_base_chunk_rebuilds_hints_and_lenses() {
        let previous = manifest(100);
        let mut current = manifest(101);
        current.base_chunk_hashes[1] = 99;
        let plan = current.dirty_plan_against(Some(&previous));
        assert_eq!(plan.base_changed_indexes, vec![1]);
        assert!(plan.rebuild_hints);
        assert!(plan.rebuild_all_lenses);
        assert!(!plan.rebuild_lenses.is_empty());
        assert!(!plan.preserve_stable_chunk_ids);
    }

    #[test]
    fn config_changes_target_correct_layers() {
        let previous = manifest(100);
        let mut current = manifest(100);
        current.ner_config_hash = 44;
        let plan = current.dirty_plan_against(Some(&previous));
        assert!(plan.rebuild_hints);
        assert!(!plan.rebuild_all_lenses);
        assert!(plan.preserve_stable_chunk_ids);

        let mut current = manifest(100);
        current.graph_config_hash = 66;
        let plan = current.dirty_plan_against(Some(&previous));
        assert!(plan.rebuild_graph_edges_only);
        assert!(plan.rebuild_lenses.is_empty());
    }
}

pub fn relation_spec(relation: &str) -> Result<&'static PhoenixRelationSpec, StoreError> {
    ALL_RELATIONS
        .iter()
        .chain(INTERNAL_RELATIONS.iter())
        .find(|spec| spec.name == relation)
        .ok_or_else(|| StoreError::UnknownRelation(relation.to_owned()))
}

pub fn internal_relation_spec(relation: &str) -> Option<&'static PhoenixRelationSpec> {
    INTERNAL_RELATIONS.iter().find(|spec| spec.name == relation)
}

pub fn is_covered_relation(relation: &str) -> bool {
    NATIVE_COVERED_RELATIONS.contains(&relation)
}

pub fn is_graph_compat_relation(relation: &str) -> bool {
    NATIVE_GRAPH_COMPAT_RELATIONS.contains(&relation)
}

pub fn is_supported_relation(relation: &str) -> bool {
    is_covered_relation(relation) || internal_relation_spec(relation).is_some()
}

pub fn snapshot_relations_for_partition(partition: SnapshotPartition) -> &'static [&'static str] {
    match partition {
        SnapshotPartition::All => CONTENT_SNAPSHOT_RELATIONS,
        SnapshotPartition::Content => CONTENT_SNAPSHOT_RELATIONS,
        SnapshotPartition::Derived => DERIVED_SNAPSHOT_RELATIONS,
    }
}

pub fn matches_scoped_document_filter(row: &Value, filter: &ScopedDocumentFilter<'_>) -> bool {
    string_field_matches(row, "namespace", filter.namespace)
        && string_field_matches(row, "narrative_id", filter.narrative_id)
        && string_field_matches(row, "document_key", filter.document_key)
}

pub fn matches_scoped_definition_filter(row: &Value, filter: &ScopedDefinitionFilter<'_>) -> bool {
    string_field_matches(row, "namespace", filter.namespace)
        && string_field_matches(row, "narrative_id", filter.narrative_id)
        && string_field_matches(row, "definition_key", filter.definition_key)
        && string_prefix_field_matches(row, "definition_key", filter.definition_key_prefix)
}

fn string_field_matches(row: &Value, field: &str, expected: Option<&str>) -> bool {
    match expected {
        Some(expected) => row.get(field).and_then(Value::as_str) == Some(expected),
        None => true,
    }
}

fn string_prefix_field_matches(row: &Value, field: &str, expected_prefix: Option<&str>) -> bool {
    match expected_prefix {
        Some(expected_prefix) => row
            .get(field)
            .and_then(Value::as_str)
            .map(|value| value.starts_with(expected_prefix))
            .unwrap_or(false),
        None => true,
    }
}

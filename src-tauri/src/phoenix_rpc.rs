use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque};
use std::hash::{Hash, Hasher};
use std::io::{Read, Write};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use crate::graph_galaxy::{compile_scene, DesktopGalaxyScene, DesktopGalaxySceneRequest};
use crate::graph_scene_hierarchy::graph_rebuild_hierarchy_hint;
use crate::graph_scene_packet::{
    compile_packet, GraphScenePacket, GraphScenePacketEdgeInput, GraphScenePacketInput,
    GraphScenePacketNodeInput, GraphScenePacketRequest, GraphScenePacketSettings,
};
use crate::tts::{
    NativeQwenSpeakRequest, NativeSupertonicSpeakRequest, NativeTtsLoadRequest, NativeTtsService,
    NativeTtsSpeakRequest, NativeTtsStatus, NativeTtsSynthResult,
};
use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
use flate2::{read::GzDecoder, write::GzEncoder, Compression};
use phoenix_graph_rebuild::{
    build_atlas_packet, build_chunks, build_document_semantic_summary, build_snapshot_embedding_targets,
    classify_document_profiles, compile_legacy_snapshot, Chunk, ChunkerConfig,
    DocumentProfileRequest, DocumentSemanticRequest, GraphRebuildSnapshot,
};
use phoenix_hyperbolic::lorentz_tree::{
    HyperboloidPoint, LorentzForest, LorentzForestIndex, LorentzNode, LorentzQueryMode,
    LorentzScoreConfig, LorentzTree, LorentzTreeKind, LorentzTreeMembership, LorentzTreeQuery,
    MmapLorentzForestIndex,
};
use phoenix_hyperbolic::siegel_finsler::{run_siegel_finsler_kernel, SiegelKernelRunRequest};
use phoenix_native::{runtime_banner, PhoenixNativeHost, SnapshotPartition};
use phoenix_types::{
    AnalyzeTextRequest, AtlasRichScanRequest, CommitRequest, CreateSessionRequest,
    GraphDeltaRequest, IngestRequest, QueryRequest, RebuildRequest, RuntimeConfig,
    RuntimeInitRequest, RuntimeInitResult, RuntimeTarget, ScanRequest, SessionStateRequest,
    SessionStatsRequest, SnapshotPolicy, StorageMode, StoreCommandRequest,
};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DocumentChunkRequest {
    documents: Vec<DocumentChunkInput>,
    #[serde(default = "default_document_chunk_size")]
    chunk_size: usize,
    #[serde(default = "default_document_chunk_overlap")]
    overlap: usize,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DocumentChunkInput {
    note_id: String,
    text: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DocumentChunkOutput {
    note_id: String,
    chunks: Vec<DocumentChunkRange>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DocumentChunkRange {
    start: usize,
    end: usize,
    ordinal: usize,
}

fn default_document_chunk_size() -> usize {
    1_840
}

fn default_document_chunk_overlap() -> usize {
    256
}

fn utf16_offsets_for_chunks(text: &str, chunks: &[Chunk]) -> HashMap<usize, usize> {
    let endpoints = chunks
        .iter()
        .flat_map(|chunk| [chunk.start, chunk.end])
        .collect::<HashSet<_>>();
    let mut offsets = HashMap::with_capacity(endpoints.len());
    let mut utf16_offset = 0usize;
    for (byte_offset, character) in text.char_indices() {
        if endpoints.contains(&byte_offset) {
            offsets.insert(byte_offset, utf16_offset);
        }
        utf16_offset += character.len_utf16();
    }
    if endpoints.contains(&text.len()) {
        offsets.insert(text.len(), utf16_offset);
    }
    offsets
}

#[derive(Default)]
struct PhoenixDesktopState {
    host: PhoenixNativeHost,
    last_init: Option<RuntimeInitResult>,
}

#[derive(Clone, Default)]
pub struct PhoenixApiImpl {
    state: Arc<Mutex<PhoenixDesktopState>>,
    tts: NativeTtsService,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopFeatureFlags {
    pub scanner: bool,
    pub structure: bool,
    pub graptor: bool,
    pub gldr: bool,
    pub semantic: bool,
    pub candidate_graph: bool,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopInitRequest {
    pub force_reset: bool,
    pub storage_path: Option<String>,
    pub storage: Option<String>,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopRelationCount {
    pub relation: String,
    pub rows: u32,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopDiagnostic {
    pub code: String,
    pub message: String,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopRuntimeInfo {
    pub banner: String,
    pub target: String,
    pub ready: bool,
    pub storage: String,
    pub storage_path: Option<String>,
    pub feature_flags: DesktopFeatureFlags,
    pub schema_version: String,
    pub relation_count: u32,
    pub relation_counts: Vec<DesktopRelationCount>,
    pub diagnostics: Vec<DesktopDiagnostic>,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopSnapshotImportResult {
    pub schema_version: String,
    pub relation_count: u32,
    pub created_at: f64,
    pub relation_names: Vec<String>,
    pub checksum: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopManifoldSnapshotRequest {
    manifold: Option<String>,
    scope: Option<Value>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzForestBuildRequest {
    scope: Option<Value>,
    limit: Option<usize>,
    force: Option<bool>,
    include_snapshot: Option<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzForestQueryRequest {
    scope: Option<Value>,
    limit: Option<usize>,
    force: Option<bool>,
    query_vector: Option<Vec<f64>>,
    query_node_id: Option<String>,
    tree_kinds: Option<Vec<String>>,
    tree_ids: Option<Vec<String>>,
    target_level: Option<u32>,
    mode: Option<String>,
    top_k: Option<usize>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzForestCacheRequest {
    scope: Option<Value>,
    limit: Option<usize>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopManifoldCapabilities {
    ann: bool,
    anchors: bool,
    fibers: bool,
    phase: bool,
    cones: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopManifoldSnapshot {
    manifold: &'static str,
    geometry_version: &'static str,
    source_label: &'static str,
    capabilities: DesktopManifoldCapabilities,
    payload: DesktopManifoldPayload,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopManifoldPayload {
    nodes: Vec<DesktopManifoldNode>,
    edges: Vec<DesktopManifoldEdge>,
    source_label: &'static str,
    projection_source: &'static str,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    cells: Vec<DesktopIcoCell>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    charts: Vec<DesktopIcoChart>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    seams: Vec<DesktopIcoSeam>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    neighbor_rings: Vec<DesktopIcoNeighborRings>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    cone_traces: Vec<DesktopIcoConeTrace>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    cone_programs: Vec<DesktopConeProgramRecord>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pathlets: Vec<DesktopConePathletRecord>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    obstructions: Vec<DesktopConeObstructionRecord>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    cone_program_traces: Vec<DesktopConeProgramTraceRecord>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    anchor_projections: Vec<DesktopAnchorProjection>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    lorentz_trees: Vec<DesktopLorentzTreeRecord>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    lorentz_memberships: Vec<DesktopLorentzMembershipRecord>,
    #[serde(skip_serializing_if = "Option::is_none")]
    lorentz_cache: Option<DesktopLorentzCacheStatus>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopManifoldNode {
    id: String,
    label: String,
    source_type: String,
    vector: Vec<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    base_vector: Option<[f64; 3]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    cell_id: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    secondary_cell_ids: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    cell_distance: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    boundary_score: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    phase: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    fiber_kind: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    geometry_version: Option<&'static str>,
    document_id: Option<String>,
    narrative_id: Option<String>,
    folder_id: Option<String>,
    preview: String,
    kind: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopManifoldEdge {
    id: String,
    source_id: String,
    target_id: String,
    #[serde(rename = "type")]
    edge_type: String,
    confidence: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzCacheStatus {
    geometry_version: &'static str,
    cache_key: String,
    cache_path: String,
    exists: bool,
    byte_len: u64,
    mmap: bool,
    rebuilt: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzTreeRecord {
    tree_id: String,
    tree_kind: String,
    label: String,
    root_node_id: Option<String>,
    geometry_version: &'static str,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzMembershipRecord {
    tree_id: String,
    node_id: String,
    parent_node_id: Option<String>,
    level: u32,
    local_rank: u32,
    path_key: String,
    branch_weight: f32,
    confidence: f32,
    source_count: u32,
    geometry_version: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzForestSnapshot {
    nodes: Vec<DesktopManifoldNode>,
    edges: Vec<DesktopManifoldEdge>,
    trees: Vec<DesktopLorentzTreeRecord>,
    memberships: Vec<DesktopLorentzMembershipRecord>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzForestBuildResponse {
    geometry_version: &'static str,
    source_label: &'static str,
    cache: DesktopLorentzCacheStatus,
    node_count: usize,
    tree_count: usize,
    membership_count: usize,
    snapshot: Option<DesktopLorentzForestSnapshot>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzQueryHit {
    candidate_id: String,
    node_id: String,
    label: String,
    tree_id: Option<String>,
    tree_kind: Option<String>,
    path_key: Option<String>,
    score: f32,
    hyperbolic_distance: f32,
    geometry_similarity: f32,
    hierarchy_alignment: f32,
    confidence: f32,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLorentzForestQueryResponse {
    geometry_version: &'static str,
    cache: DesktopLorentzCacheStatus,
    query_point: [f32; 5],
    hits: Vec<DesktopLorentzQueryHit>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopIcoCell {
    cell_id: String,
    resolution: u32,
    parent_cell_id: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    children_cell_ids: Vec<String>,
    center_vector: [f64; 3],
    normal_vector: [f64; 3],
    neighbor_cell_ids: Vec<String>,
    area_weight: f64,
    density: f64,
    anchor_ids: Vec<String>,
    geometry_version: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopIcoChart {
    chart_id: String,
    center_cell_id: String,
    member_cell_ids: Vec<String>,
    resolution: u32,
    dominant_contexts: Vec<String>,
    anchor_count: u32,
    density: f64,
    boundary_cells: Vec<String>,
    geometry_version: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopIcoSeam {
    from_cell: String,
    to_cell: String,
    shared_edge: Vec<String>,
    normal_delta: f64,
    chart_a: String,
    chart_b: String,
    seam_cost: f64,
    compatibility_score: f64,
    obstruction_count: u32,
    geometry_version: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopIcoNeighborRings {
    cell_id: String,
    ring_1: Vec<String>,
    ring_2: Vec<String>,
    ring_3: Vec<String>,
    geometry_version: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopIcoConeTrace {
    cone_id: String,
    apex_cell: String,
    axis_vector: [f64; 3],
    aperture_cos: f64,
    max_ring: u32,
    accepted_cell_ids: Vec<String>,
    rejected_cell_ids: Vec<String>,
    steps: Vec<DesktopIcoConeTraceStep>,
    geometry_version: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopIcoConeTraceStep {
    cell_id: String,
    neighbor_ring: u32,
    axis_alignment: f64,
    aperture_threshold: f64,
    chart_stitch_score: f64,
    accepted: bool,
    reason: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopConeProgramOpRecord {
    op: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    lane: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    ids: Vec<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    required_ids: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    max_cost: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    limit: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    min_compatibility: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    require_evidence: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    strict: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pathlet_id: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    rank_by: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopConeProgramRecord {
    program_id: String,
    intent: String,
    seed_ids: Vec<String>,
    ops: Vec<DesktopConeProgramOpRecord>,
    geometry_version: &'static str,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopConePathletRecord {
    pathlet_id: String,
    lane: String,
    start_id: String,
    end_id: String,
    node_ids: Vec<String>,
    edge_ids: Vec<String>,
    support_score: f64,
    compression_score: f64,
    obstruction_ids: Vec<String>,
    geometry_version: &'static str,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopConeObstructionRecord {
    obstruction_id: String,
    kind: String,
    severity: f64,
    explanation: String,
    node_ids: Vec<String>,
    edge_ids: Vec<String>,
    chart_ids: Vec<String>,
    evidence_refs: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    lane: Option<String>,
    geometry_version: &'static str,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopConeProgramTraceRecord {
    trace_id: String,
    program_id: String,
    active_ids: Vec<String>,
    pathlet_ids: Vec<String>,
    obstruction_ids: Vec<String>,
    path_edge_ids: Vec<String>,
    explanations: Vec<String>,
    geometry_version: &'static str,
}

#[derive(Default)]
struct DesktopProductConeTraversal {
    programs: Vec<DesktopConeProgramRecord>,
    pathlets: Vec<DesktopConePathletRecord>,
    obstructions: Vec<DesktopConeObstructionRecord>,
    traces: Vec<DesktopConeProgramTraceRecord>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopAnchorProjection {
    anchor_id: String,
    primary_cell_id: String,
    secondary_cell_ids: Vec<String>,
    cell_distance: f64,
    boundary_score: f64,
    projection_version: &'static str,
    geometry_version: &'static str,
}

const HYBRID_GEOMETRY_VERSION: &str = "hybrid_semantic_v1";
const HOPF_GEOMETRY_VERSION: &str = "hopf_ico_r5_v1";
const HOPF_PROJECTION_VERSION: &str = "hopf_stereographic_v1";
const LORENTZ_GEOMETRY_VERSION: &str = "lorentz_h4_forest_v1";
const PRODUCT_GEOMETRY_VERSION: &str = "product_lorentz_hopf_v1";
const GRAPH_REBUILD_NAMESPACE: &str = "phoenix_graph_rebuild_v1";
const GRAPH_REBUILD_SNAPSHOT_DOCUMENT_KEY: &str = "snapshot";
const GRAPH_REBUILD_COMPRESSED_JSON_SCHEMA: &str =
    "phoenix-graph-rebuild-json-payload/gzip-base64/v1";
const GRAPH_REBUILD_COMPRESSED_SNAPSHOT_SCHEMA: &str =
    "phoenix-graph-rebuild-payload/gzip-base64/v1";
const HOPF_ICO_RESOLUTION: u32 = 5;
const HOPF_CHART_RESOLUTION: u32 = 3;
const HOPF_CONE_APERTURE_COS: f64 = 0.573_576_436_351_046;
const TAU_F64: f64 = std::f64::consts::PI * 2.0;

#[derive(Clone, Debug)]
struct IcoCellInternal {
    cell_id: String,
    resolution: u32,
    face: usize,
    local_index: usize,
    center: [f64; 3],
    vertex_keys: [String; 3],
    edge_keys: [String; 3],
    neighbor_cell_ids: Vec<String>,
    area_weight: f64,
}

#[derive(Clone, Debug)]
struct IcoTopology {
    resolution: u32,
    cells: Vec<IcoCellInternal>,
    by_id: HashMap<String, usize>,
}

#[derive(Clone, Debug)]
struct IcoProjection {
    primary_cell_id: String,
    secondary_cell_ids: Vec<String>,
    center_vector: [f64; 3],
    cell_distance: f64,
    boundary_score: f64,
}

#[derive(Clone, Debug)]
struct HopfAnchorAssignment {
    anchor_id: String,
    fiber_id: String,
    fiber_kind: String,
    cell_id: String,
    chart_id: String,
    secondary_cell_ids: Vec<String>,
    center_vector: [f64; 3],
    cell_distance: f64,
    boundary_score: f64,
    phase: f64,
}

#[derive(Default)]
struct ChartAccumulator {
    member_cell_ids: BTreeSet<String>,
    anchor_ids: Vec<String>,
    dominant_contexts: BTreeMap<String, u32>,
}

#[taurpc::procedures(path = "phoenix", export_to = "../src/app/generated/phoenix-taurpc.ts")]
pub trait PhoenixApi {
    async fn runtime_info() -> DesktopRuntimeInfo;
    async fn init_runtime(request: DesktopInitRequest) -> Result<DesktopRuntimeInfo, String>;
    async fn close_runtime() -> bool;
    async fn boot_snapshot_json() -> Result<String, String>;
    async fn compile_galaxy_scene(
        request: DesktopGalaxySceneRequest,
    ) -> Result<DesktopGalaxyScene, String>;
    async fn create_session_json(request_json: String) -> Result<String, String>;
    async fn ingest_json(request_json: String) -> Result<String, String>;
    async fn query_json(request_json: String) -> Result<String, String>;
    async fn commit_json(request_json: String) -> Result<String, String>;
    async fn rebuild_json(request_json: String) -> Result<String, String>;
    async fn scan_json(request_json: String) -> Result<String, String>;
    async fn atlas_rich_scan_json(request_json: String) -> Result<String, String>;
    async fn manifold_snapshot_json(request_json: String) -> Result<String, String>;
    async fn graph_scene_packet_json(request_json: String) -> Result<String, String>;
    async fn lorentz_forest_cache_json(request_json: String) -> Result<String, String>;
    async fn lorentz_forest_build_json(request_json: String) -> Result<String, String>;
    async fn lorentz_forest_query_json(request_json: String) -> Result<String, String>;
    async fn siegel_finsler_receipt_json(request_json: String) -> Result<String, String>;
    async fn build_structure_json(request_json: String) -> Result<String, String>;
    async fn analyze_text_json(request_json: String) -> Result<String, String>;
    async fn graph_delta_json(request_json: String) -> Result<String, String>;
    async fn session_state_json(request_json: String) -> Result<String, String>;
    async fn session_stats_json(request_json: String) -> Result<String, String>;
    async fn export_snapshot(partition: String) -> Result<Vec<u8>, String>;
    async fn import_snapshot(bytes: Vec<u8>) -> Result<DesktopSnapshotImportResult, String>;
    async fn store_command(command: String, payload_json: String) -> Result<String, String>;
    async fn tts_status() -> NativeTtsStatus;
    async fn tts_load(request: NativeTtsLoadRequest) -> Result<NativeTtsStatus, String>;
    async fn tts_speak(request: NativeTtsSpeakRequest) -> Result<NativeTtsSynthResult, String>;
    async fn tts_supertonic_speak(
        request: NativeSupertonicSpeakRequest,
    ) -> Result<NativeTtsSynthResult, String>;
    async fn tts_qwen_speak(
        request: NativeQwenSpeakRequest,
    ) -> Result<NativeTtsSynthResult, String>;
    async fn tts_unload() -> bool;
}

#[taurpc::resolvers]
impl PhoenixApi for PhoenixApiImpl {
    async fn runtime_info(self) -> DesktopRuntimeInfo {
        let guard = match self.state.lock() {
            Ok(guard) => guard,
            Err(_) => return desktop_runtime_info(None, None),
        };
        desktop_runtime_info(guard.host.config(), guard.last_init.as_ref())
    }

    async fn init_runtime(self, request: DesktopInitRequest) -> Result<DesktopRuntimeInfo, String> {
        let mut guard = self.lock_state()?;
        if request.force_reset {
            let _ = guard.host.close();
        }

        let init_request = build_init_request(&request);
        let result = guard
            .host
            .open(init_request)
            .map_err(|error| error.to_string())?;
        guard.last_init = Some(result.clone());
        Ok(desktop_runtime_info(
            guard.host.config(),
            guard.last_init.as_ref(),
        ))
    }

    async fn close_runtime(self) -> bool {
        match self.state.lock() {
            Ok(mut guard) => {
                guard.last_init = None;
                guard.host.close()
            }
            Err(_) => false,
        }
    }

    async fn boot_snapshot_json(self) -> Result<String, String> {
        let guard = self.lock_state()?;
        let snapshot = guard
            .host
            .boot_snapshot_rows()
            .map_err(|error| error.to_string())?;
        serialize_json(&snapshot)
    }

    async fn compile_galaxy_scene(
        self,
        request: DesktopGalaxySceneRequest,
    ) -> Result<DesktopGalaxyScene, String> {
        tokio::task::spawn_blocking(move || compile_scene(request))
            .await
            .map_err(|error| format!("native galaxy scene task failed: {error}"))
    }

    async fn create_session_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<CreateSessionRequest, _, _>(request_json, |host, request| {
            host.create_session(request)
        })
    }

    async fn ingest_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<IngestRequest, _, _>(request_json, |host, request| {
            host.ingest(request)
        })
    }

    async fn query_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<QueryRequest, _, _>(request_json, |host, request| host.query(request))
    }

    async fn commit_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<CommitRequest, _, _>(request_json, |host, request| {
            host.commit(request)
        })
    }

    async fn rebuild_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<RebuildRequest, _, _>(request_json, |host, request| {
            host.rebuild(request)
        })
    }

    async fn scan_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<ScanRequest, _, _>(request_json, |host, request| host.scan(request))
    }

    async fn atlas_rich_scan_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<AtlasRichScanRequest, _, _>(request_json, |host, request| {
            host.atlas_rich_scan(request)
        })
    }

    async fn manifold_snapshot_json(self, request_json: String) -> Result<String, String> {
        let request = parse_json::<DesktopManifoldSnapshotRequest>(&request_json)?;
        let guard = self.lock_state()?;
        let snapshot = build_manifold_snapshot(&guard.host, request)?;
        serialize_json(&snapshot)
    }

    async fn graph_scene_packet_json(self, request_json: String) -> Result<String, String> {
        let request = parse_json::<GraphScenePacketRequest>(&request_json)?;
        let guard = self.lock_state()?;
        let packet = build_graph_scene_packet(&guard.host, request)?;
        serialize_json(&packet)
    }

    async fn lorentz_forest_cache_json(self, request_json: String) -> Result<String, String> {
        let request = parse_json::<DesktopLorentzForestCacheRequest>(&request_json)?;
        let guard = self.lock_state()?;
        let cache = lorentz_cache_status(&guard.host, request.scope.as_ref(), request.limit)?;
        serialize_json(&cache)
    }

    async fn lorentz_forest_build_json(self, request_json: String) -> Result<String, String> {
        let request = parse_json::<DesktopLorentzForestBuildRequest>(&request_json)?;
        let guard = self.lock_state()?;
        let response = build_lorentz_forest_response(&guard.host, request)?;
        serialize_json(&response)
    }

    async fn lorentz_forest_query_json(self, request_json: String) -> Result<String, String> {
        let request = parse_json::<DesktopLorentzForestQueryRequest>(&request_json)?;
        let guard = self.lock_state()?;
        let response = query_lorentz_forest_response(&guard.host, request)?;
        serialize_json(&response)
    }

    async fn siegel_finsler_receipt_json(self, request_json: String) -> Result<String, String> {
        let request = parse_json::<SiegelKernelRunRequest>(&request_json)?;
        let receipt = run_siegel_finsler_kernel(&request);
        serialize_json(&receipt)
    }

    async fn build_structure_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<phoenix_types::StructureRequest, _, _>(
            request_json,
            |host, request| host.build_structure(request),
        )
    }

    async fn analyze_text_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<AnalyzeTextRequest, _, _>(request_json, |host, request| {
            host.analyze_text(request)
        })
    }

    async fn graph_delta_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<GraphDeltaRequest, _, _>(request_json, |host, request| {
            host.graph_delta(request)
        })
    }

    async fn session_state_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<SessionStateRequest, _, _>(request_json, |host, request| {
            host.session_state(request)
        })
    }

    async fn session_stats_json(self, request_json: String) -> Result<String, String> {
        self.with_host_json::<SessionStatsRequest, _, _>(request_json, |host, request| {
            host.session_stats(request)
        })
    }

    async fn export_snapshot(self, partition: String) -> Result<Vec<u8>, String> {
        let guard = self.lock_state()?;
        guard
            .host
            .export_snapshot_partition(parse_snapshot_partition(&partition)?)
            .map_err(|error| error.to_string())
    }

    async fn import_snapshot(self, bytes: Vec<u8>) -> Result<DesktopSnapshotImportResult, String> {
        let guard = self.lock_state()?;
        let envelope = guard
            .host
            .import_snapshot_cold(&bytes)
            .map_err(|error| error.to_string())?;
        let relation_names = envelope.relations.keys().cloned().collect::<Vec<_>>();
        Ok(DesktopSnapshotImportResult {
            schema_version: envelope.schema_version,
            relation_count: count_for_wire(envelope.relation_count),
            created_at: envelope.created_at as f64,
            relation_names,
            checksum: envelope.checksum,
        })
    }

    async fn store_command(self, command: String, payload_json: String) -> Result<String, String> {
        let payload: Value = if payload_json.trim().is_empty() {
            Value::Null
        } else {
            serde_json::from_str::<Value>(&payload_json)
                .map_err(|error| format!("invalid store command payload JSON: {error}"))?
        };

        if command == "graphRebuild:compileDualWrite" {
            let snapshot_value = payload.get("snapshot").cloned().unwrap_or(payload);
            let snapshot = serde_json::from_value::<GraphRebuildSnapshot>(snapshot_value)
                .map_err(|error| format!("invalid graph rebuild snapshot: {error}"))?;
            let fact_graph = compile_legacy_snapshot(&snapshot);
            let fact_graph_payload = compressed_json_payload(
                &fact_graph,
                "phoenix-graph-compiler-payload/gzip-base64/v1",
                fact_graph.schema_version.as_str(),
            )?;
            let embedding_targets = build_snapshot_embedding_targets(&snapshot);
            let mut atlas_snapshot = snapshot.clone();
            atlas_snapshot.embedding_targets = embedding_targets.clone();
            let atlas_packet = build_atlas_packet(&atlas_snapshot);
            return serialize_json(&json!({
                "success": true,
                "payload": {
                    "factGraphPayload": fact_graph_payload,
                    "atlasPacket": atlas_packet,
                    "embeddingTargetSource": "rust-graph-family-targets/v1",
                    "embeddingTargets": embedding_targets,
                },
                "error": null,
            }));
        }
        if command == "documentProfile:classify" {
            let request = serde_json::from_value::<DocumentProfileRequest>(payload)
                .map_err(|error| format!("invalid document profile request: {error}"))?;
            let summary = classify_document_profiles(&request);
            return serialize_json(&json!({
                "success": true,
                "payload": summary,
                "error": null,
            }));
        }
        if command == "documentChunk:build" {
            let request = serde_json::from_value::<DocumentChunkRequest>(payload)
                .map_err(|error| format!("invalid document chunk request: {error}"))?;
            let config = ChunkerConfig {
                chunk_size: request.chunk_size.max(256),
                overlap: request.overlap.min(request.chunk_size.saturating_sub(1)),
            };
            let documents = request
                .documents
                .into_iter()
                .map(|document| {
                    let chunks = build_chunks(&document.text, &config);
                    let offsets = utf16_offsets_for_chunks(&document.text, &chunks);
                    DocumentChunkOutput {
                        note_id: document.note_id,
                        chunks: chunks
                            .iter()
                            .enumerate()
                            .map(|(ordinal, chunk)| DocumentChunkRange {
                                start: offsets.get(&chunk.start).copied().unwrap_or_default(),
                                end: offsets.get(&chunk.end).copied().unwrap_or_default(),
                                ordinal,
                            })
                            .collect(),
                    }
                })
                .collect::<Vec<_>>();
            return serialize_json(&json!({
                "success": true,
                "payload": {
                    "schemaVersion": "phoenix-document-chunks/v1",
                    "source": "native_rust",
                    "documents": documents,
                },
                "error": null,
            }));
        }
        if command == "documentSemantic:build" {
            let request = serde_json::from_value::<DocumentSemanticRequest>(payload)
                .map_err(|error| format!("invalid document semantic request: {error}"))?;
            let summary = build_document_semantic_summary(&request);
            return serialize_json(&json!({
                "success": true,
                "payload": summary,
                "error": null,
            }));
        }

        let guard = self.lock_state()?;
        let result = guard
            .host
            .store_command(StoreCommandRequest { command, payload })
            .map_err(|error| error.to_string())?;
        serialize_json(&result)
    }

    async fn tts_status(self) -> NativeTtsStatus {
        self.tts.status()
    }

    async fn tts_load(self, request: NativeTtsLoadRequest) -> Result<NativeTtsStatus, String> {
        let mut tts = self.tts.clone();
        tokio::task::spawn_blocking(move || tts.load(request))
            .await
            .map_err(|error| format!("native TTS load task failed: {error}"))?
    }

    async fn tts_speak(
        self,
        request: NativeTtsSpeakRequest,
    ) -> Result<NativeTtsSynthResult, String> {
        let mut tts = self.tts.clone();
        tokio::task::spawn_blocking(move || tts.synthesize(request))
            .await
            .map_err(|error| format!("native TTS synth task failed: {error}"))?
    }

    async fn tts_supertonic_speak(
        self,
        request: NativeSupertonicSpeakRequest,
    ) -> Result<NativeTtsSynthResult, String> {
        let mut tts = self.tts.clone();
        tokio::task::spawn_blocking(move || tts.synthesize_supertonic(request))
            .await
            .map_err(|error| format!("native Supertonic synth task failed: {error}"))?
    }

    async fn tts_qwen_speak(
        self,
        request: NativeQwenSpeakRequest,
    ) -> Result<NativeTtsSynthResult, String> {
        let mut tts = self.tts.clone();
        tokio::task::spawn_blocking(move || tts.synthesize_qwen(request))
            .await
            .map_err(|error| format!("native Qwen TTS synth task failed: {error}"))?
    }

    async fn tts_unload(self) -> bool {
        let mut tts = self.tts.clone();
        tokio::task::spawn_blocking(move || tts.unload())
            .await
            .unwrap_or(false)
    }
}

impl PhoenixApiImpl {
    fn lock_state(&self) -> Result<std::sync::MutexGuard<'_, PhoenixDesktopState>, String> {
        self.state
            .lock()
            .map_err(|_| "phoenix desktop state lock poisoned".to_owned())
    }

    fn with_host_json<Request, Response, F>(
        &self,
        request_json: String,
        op: F,
    ) -> Result<String, String>
    where
        Request: DeserializeOwned,
        Response: Serialize,
        F: FnOnce(
            &PhoenixNativeHost,
            Request,
        ) -> Result<Response, phoenix_native::PhoenixNativeError>,
    {
        let request = parse_json::<Request>(&request_json)?;
        let guard = self.lock_state()?;
        let response = op(&guard.host, request).map_err(|error| error.to_string())?;
        serialize_json(&response)
    }
}

fn build_init_request(request: &DesktopInitRequest) -> RuntimeInitRequest {
    let storage = request
        .storage
        .as_deref()
        .and_then(parse_storage_mode)
        .unwrap_or_else(|| {
            if request.storage_path.is_some() {
                StorageMode::NativeLocal
            } else {
                StorageMode::NativeLocal
            }
        });

    RuntimeInitRequest {
        config: RuntimeConfig {
            target: desktop_runtime_target(),
            storage,
            snapshot_policy: SnapshotPolicy::Manual,
            feature_flags: phoenix_types::FeatureFlags {
                scanner: true,
                structure: true,
                graptor: false,
                gldr: false,
                semantic: true,
                candidate_graph: true,
            },
        },
        storage_path: request.storage_path.clone(),
        force_reset: request.force_reset,
    }
}

fn desktop_runtime_info(
    config: Option<&phoenix_native::PhoenixNativeConfig>,
    init_result: Option<&phoenix_types::RuntimeInitResult>,
) -> DesktopRuntimeInfo {
    let runtime = config
        .map(|config| config.runtime.clone())
        .unwrap_or_else(default_runtime_config);
    DesktopRuntimeInfo {
        banner: runtime_banner().to_owned(),
        target: runtime_target_name(runtime.target).to_owned(),
        ready: init_result.map(|result| result.ready).unwrap_or(false),
        storage: storage_mode_name(runtime.storage).to_owned(),
        storage_path: config
            .and_then(|config| config.storage_path.as_ref())
            .map(|path| path.to_string_lossy().into_owned()),
        feature_flags: DesktopFeatureFlags {
            scanner: runtime.feature_flags.scanner,
            structure: runtime.feature_flags.structure,
            graptor: runtime.feature_flags.graptor,
            gldr: runtime.feature_flags.gldr,
            semantic: runtime.feature_flags.semantic,
            candidate_graph: runtime.feature_flags.candidate_graph,
        },
        schema_version: init_result
            .map(|result| result.schema_version.clone())
            .unwrap_or_default(),
        relation_count: init_result
            .map(|result| count_for_wire(result.relation_count))
            .unwrap_or(0),
        relation_counts: init_result
            .map(|result| {
                result
                    .relation_counts
                    .iter()
                    .map(|relation| DesktopRelationCount {
                        relation: relation.relation.clone(),
                        rows: count_for_wire(relation.rows),
                    })
                    .collect()
            })
            .unwrap_or_default(),
        diagnostics: init_result
            .map(|result| {
                result
                    .diagnostics
                    .iter()
                    .map(|diagnostic| DesktopDiagnostic {
                        code: diagnostic.code.clone(),
                        message: diagnostic.message.clone(),
                    })
                    .collect()
            })
            .unwrap_or_default(),
    }
}

fn default_runtime_config() -> RuntimeConfig {
    RuntimeConfig {
        target: desktop_runtime_target(),
        storage: StorageMode::NativeLocal,
        snapshot_policy: SnapshotPolicy::Manual,
        feature_flags: phoenix_types::FeatureFlags {
            scanner: true,
            structure: true,
            graptor: false,
            gldr: false,
            semantic: true,
            candidate_graph: true,
        },
    }
}

fn desktop_runtime_target() -> RuntimeTarget {
    RuntimeTarget::Native
}

fn runtime_target_name(target: RuntimeTarget) -> &'static str {
    match target {
        RuntimeTarget::Native => "native",
        RuntimeTarget::Wasm => "wasm",
    }
}

fn parse_storage_mode(value: &str) -> Option<StorageMode> {
    match value {
        "nativeEphemeral" | "native_ephemeral" | "mem" => Some(StorageMode::NativeEphemeral),
        "native" | "nativeLocal" | "native_local" | "local" | "sqlite" => {
            Some(StorageMode::NativeLocal)
        }
        _ => None,
    }
}

fn storage_mode_name(mode: StorageMode) -> &'static str {
    match mode {
        StorageMode::NativeEphemeral => "nativeEphemeral",
        StorageMode::NativeLocal => "nativeLocal",
        _ => "legacyStorage",
    }
}

fn count_for_wire(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}

fn parse_snapshot_partition(value: &str) -> Result<SnapshotPartition, String> {
    match value {
        "all" => Ok(SnapshotPartition::All),
        "content" => Ok(SnapshotPartition::Content),
        "derived" => Ok(SnapshotPartition::Derived),
        other => Err(format!("unknown snapshot partition: {other}")),
    }
}

fn build_manifold_snapshot(
    host: &PhoenixNativeHost,
    request: DesktopManifoldSnapshotRequest,
) -> Result<DesktopManifoldSnapshot, String> {
    let manifold = request.manifold.as_deref().unwrap_or("hybrid");
    let is_hopf = manifold == "hopf";
    let is_lorentz = manifold == "lorentz";
    let is_product = manifold == "product";
    let scope = request.scope.as_ref();
    let limit = request.limit.unwrap_or(360).max(1);
    let document_rows = store_relation_rows(host, "semantic_documents")?;
    let node_rows = store_relation_rows(host, "semantic_node_prototypes")?;
    let candidate_rows = store_relation_rows(host, "graph_candidate_edges")?;
    let semantic =
        semantic_rows_to_payload(&document_rows, &node_rows, &candidate_rows, scope, limit);
    let payload = if is_hopf {
        semantic_payload_to_hopf_payload(&semantic)
    } else if is_lorentz {
        let build = ensure_lorentz_sidecar(host, scope, Some(limit), false)?;
        lorentz_index_to_payload(build.mmap.index(), build.cache)
    } else if is_product {
        let build = ensure_lorentz_sidecar(host, scope, Some(limit), false)?;
        product_index_to_payload(&semantic, build.mmap.index(), build.cache)
    } else {
        semantic
    };
    Ok(DesktopManifoldSnapshot {
        manifold: if is_hopf {
            "hopf"
        } else if is_lorentz {
            "lorentz"
        } else if is_product {
            "product"
        } else {
            "hybrid"
        },
        geometry_version: if is_hopf {
            HOPF_GEOMETRY_VERSION
        } else if is_lorentz {
            LORENTZ_GEOMETRY_VERSION
        } else if is_product {
            PRODUCT_GEOMETRY_VERSION
        } else {
            HYBRID_GEOMETRY_VERSION
        },
        source_label: if is_hopf {
            "native hopf anchors + fibers"
        } else if is_lorentz {
            "native lorentz h4 forest sidecar"
        } else if is_product {
            "native product Lorentz-Hopf atlas"
        } else {
            "native hybrid semantic atlas"
        },
        capabilities: DesktopManifoldCapabilities {
            ann: !is_lorentz || is_product,
            anchors: is_hopf || is_product,
            fibers: is_hopf || is_product,
            phase: is_hopf || is_product,
            cones: is_hopf || is_lorentz || is_product,
        },
        payload,
    })
}

fn build_graph_scene_packet(
    host: &PhoenixNativeHost,
    request: GraphScenePacketRequest,
) -> Result<GraphScenePacket, String> {
    let manifold = request
        .manifold
        .clone()
        .unwrap_or_else(|| "hybrid".to_owned());
    let layout_mode = request
        .layout_mode
        .clone()
        .unwrap_or_else(|| layout_mode_for_manifold(&manifold).to_owned());
    let source_mode = request
        .source_mode
        .clone()
        .unwrap_or_else(|| "embeddings".to_owned());
    let limit = request.limit.unwrap_or(4096).max(1);
    let settings = request.settings.unwrap_or_default();
    let requested_source = request.source.clone();

    if is_scoped_snapshot_packet_source(requested_source.as_deref()) {
        return Ok(compile_packet(
            graph_scene_packet_input_from_scoped_snapshot(
                host,
                request.scope.as_ref(),
                requested_source.unwrap_or_else(|| "scopedSnapshot".to_owned()),
                manifold,
                layout_mode,
                source_mode,
                limit,
                settings,
            )?,
        ));
    }

    if let Some(nodes) = request.nodes {
        let edges = request.edges.unwrap_or_default();
        return Ok(compile_packet(GraphScenePacketInput {
            source: request.source.unwrap_or_else(|| "inline".to_owned()),
            manifold,
            layout_mode,
            source_mode,
            source_label: "inline graph scene packet".to_owned(),
            limit,
            settings,
            nodes,
            edges,
        }));
    }

    let snapshot = build_manifold_snapshot(
        host,
        DesktopManifoldSnapshotRequest {
            manifold: Some(manifold.clone()),
            scope: request.scope,
            limit: Some(limit),
        },
    )?;
    let nodes = snapshot
        .payload
        .nodes
        .iter()
        .map(scene_packet_node_from_desktop)
        .collect::<Vec<_>>();
    let edges = snapshot
        .payload
        .edges
        .iter()
        .map(scene_packet_edge_from_desktop)
        .collect::<Vec<_>>();

    Ok(compile_packet(GraphScenePacketInput {
        source: request
            .source
            .unwrap_or_else(|| "manifoldSnapshot".to_owned()),
        manifold: snapshot.manifold.to_owned(),
        layout_mode,
        source_mode,
        source_label: snapshot.source_label.to_owned(),
        limit,
        settings,
        nodes,
        edges,
    }))
}

fn layout_mode_for_manifold(manifold: &str) -> &'static str {
    match manifold {
        "hopf" => "hopfProjection",
        "lorentz" => "lorentzTree",
        "product" => "productManifold",
        "siegel" => "siegelFinsler",
        _ => "hybridSpace",
    }
}

fn scene_packet_node_from_desktop(node: &DesktopManifoldNode) -> GraphScenePacketNodeInput {
    GraphScenePacketNodeInput {
        id: node.id.clone(),
        label: node.label.clone(),
        kind: node.kind.clone(),
        source_type: node.source_type.clone(),
        vector: node.vector.iter().map(|value| *value as f32).collect(),
        base_vector: node
            .base_vector
            .map(|value| [value[0] as f32, value[1] as f32, value[2] as f32]),
        total_mentions: None,
        hierarchy_hint: None,
    }
}

fn scene_packet_edge_from_desktop(edge: &DesktopManifoldEdge) -> GraphScenePacketEdgeInput {
    GraphScenePacketEdgeInput {
        id: edge.id.clone(),
        source_id: edge.source_id.clone(),
        target_id: edge.target_id.clone(),
        edge_type: edge.edge_type.clone(),
        confidence: edge.confidence as f32,
    }
}

fn is_scoped_snapshot_packet_source(source: Option<&str>) -> bool {
    matches!(
        source,
        Some("scopedSnapshot") | Some("graphRebuildSnapshot") | Some("scopedGraphRebuildSnapshot")
    )
}

fn graph_scene_packet_input_from_scoped_snapshot(
    host: &PhoenixNativeHost,
    scope: Option<&Value>,
    source: String,
    manifold: String,
    layout_mode: String,
    source_mode: String,
    limit: usize,
    settings: GraphScenePacketSettings,
) -> Result<GraphScenePacketInput, String> {
    let scope_id = scope
        .map(|value| str_field(value, "scope_id", "scopeId"))
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "graph scene packet scoped snapshot requires scope.scopeId".to_owned())?;
    let row = store_relation_first(
        host,
        "scoped_documents",
        json!({
            "scope_folder_id": scope_id,
            "namespace": GRAPH_REBUILD_NAMESPACE,
            "document_key": GRAPH_REBUILD_SNAPSHOT_DOCUMENT_KEY,
        }),
    )?
    .ok_or_else(|| format!("graph rebuild snapshot document missing for scope {scope_id}"))?;
    let payload = row
        .get("payload")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .unwrap_or_else(|| row.get("payload").map(Value::to_string).unwrap_or_default());
    if payload.is_empty() {
        return Err(format!(
            "graph rebuild snapshot document for scope {scope_id} had no payload"
        ));
    }
    let snapshot = decode_graph_rebuild_scoped_payload(&payload)?;
    graph_scene_packet_input_from_rebuild_snapshot_value(
        &snapshot,
        source,
        manifold,
        layout_mode,
        source_mode,
        limit,
        settings,
    )
}

fn graph_scene_packet_input_from_rebuild_snapshot_value(
    snapshot: &Value,
    source: String,
    manifold: String,
    layout_mode: String,
    source_mode: String,
    limit: usize,
    settings: GraphScenePacketSettings,
) -> Result<GraphScenePacketInput, String> {
    let nodes_value = snapshot
        .get("embeddingTargets")
        .and_then(Value::as_array)
        .ok_or_else(|| "graph rebuild snapshot payload missing embeddingTargets".to_owned())?;
    let mut target_ids = HashSet::with_capacity(nodes_value.len());
    let mut nodes = Vec::with_capacity(nodes_value.len());
    for (index, target) in nodes_value.iter().enumerate() {
        let id = str_field(target, "id", "id");
        if id.is_empty() {
            continue;
        }
        target_ids.insert(id.to_owned());
        let vector = stable_packet_vector(id, index);
        let kind = str_field(target, "kind", "kind");
        nodes.push(GraphScenePacketNodeInput {
            id: id.to_owned(),
            label: {
                let label = str_field(target, "label", "label");
                if label.is_empty() {
                    kind.to_owned()
                } else {
                    label.to_owned()
                }
            },
            kind: kind.to_owned(),
            source_type: graph_rebuild_packet_source_type(target).to_owned(),
            vector: vector.to_vec(),
            base_vector: Some(vector),
            total_mentions: Some(target_total_mentions(target)),
            hierarchy_hint: graph_rebuild_hierarchy_hint(target, index),
        });
    }

    let mut edges = Vec::new();
    if let Some(post_process) = snapshot.get("embeddingGraphPostProcess") {
        push_graph_rebuild_packet_edges(
            post_process.get("backboneEdges").and_then(Value::as_array),
            &target_ids,
            &mut edges,
        );
        push_graph_rebuild_packet_edges(
            post_process.get("bridgeEdges").and_then(Value::as_array),
            &target_ids,
            &mut edges,
        );
    }

    Ok(GraphScenePacketInput {
        source,
        manifold,
        layout_mode,
        source_mode,
        source_label: "scoped graph-rebuild snapshot".to_owned(),
        limit,
        settings,
        nodes,
        edges,
    })
}

fn push_graph_rebuild_packet_edges(
    rows: Option<&Vec<Value>>,
    target_ids: &HashSet<String>,
    out: &mut Vec<GraphScenePacketEdgeInput>,
) {
    let Some(rows) = rows else { return };
    out.reserve(rows.len());
    for row in rows {
        let source_id = str_field(row, "source_target_id", "sourceTargetId");
        let target_id = str_field(row, "target_target_id", "targetTargetId");
        if source_id.is_empty()
            || target_id.is_empty()
            || !target_ids.contains(source_id)
            || !target_ids.contains(target_id)
        {
            continue;
        }
        let id = str_field(row, "id", "id");
        let edge_type = str_field(row, "role", "role");
        out.push(GraphScenePacketEdgeInput {
            id: if id.is_empty() {
                format!("{source_id}:semantic-neighbor:{target_id}")
            } else {
                id.to_owned()
            },
            source_id: source_id.to_owned(),
            target_id: target_id.to_owned(),
            edge_type: if edge_type.is_empty() {
                "semantic-neighbor".to_owned()
            } else {
                edge_type.to_owned()
            },
            confidence: f32_field(row, "score").unwrap_or(0.5),
        });
    }
}

fn graph_rebuild_packet_source_type(target: &Value) -> &'static str {
    let lane = str_field(target, "lane", "lane");
    let role = str_field(target, "structural_role", "structuralRole");
    if role == "root" || lane == "document_spine" {
        "root"
    } else if lane == "chunk_spine" {
        "chunk"
    } else if lane == "entity_anchor" {
        "entity"
    } else if lane == "anchor_evidence" {
        "evidence"
    } else if lane == "event_identity" {
        "event"
    } else if lane == "temporal_fact" {
        "temporal"
    } else if lane == "causal_fact" {
        "causal"
    } else if lane == "memory_state" {
        "memory"
    } else if !role.is_empty() {
        "graph"
    } else {
        "target"
    }
}

fn target_total_mentions(target: &Value) -> u32 {
    let evidence = target
        .get("evidenceIds")
        .or_else(|| target.get("evidence_ids"))
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    let parents = target
        .get("parentIds")
        .or_else(|| target.get("parent_ids"))
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    count_for_wire(evidence.max(parents).max(1))
}

fn stable_packet_vector(id: &str, index: usize) -> [f32; 3] {
    let mut hash = 2_166_136_261_u32 ^ index as u32;
    for byte in id.bytes() {
        hash ^= byte as u32;
        hash = hash.wrapping_mul(16_777_619);
    }
    let x = ((hash & 0xff) as f32 / 127.5) - 1.0;
    let y = (((hash >> 8) & 0xff) as f32 / 127.5) - 1.0;
    let z = (((hash >> 16) & 0xff) as f32 / 127.5) - 1.0;
    let norm = (x * x + y * y + z * z).sqrt().max(1e-6);
    [x / norm, y / norm, z / norm]
}

fn decode_graph_rebuild_scoped_payload(payload: &str) -> Result<Value, String> {
    let parsed = serde_json::from_str::<Value>(payload)
        .map_err(|error| format!("invalid graph rebuild snapshot payload JSON: {error}"))?;
    let schema = parsed
        .get("schemaVersion")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if schema != GRAPH_REBUILD_COMPRESSED_JSON_SCHEMA
        && schema != GRAPH_REBUILD_COMPRESSED_SNAPSHOT_SCHEMA
    {
        return Ok(parsed);
    }
    let encoded = parsed
        .get("payload")
        .and_then(Value::as_str)
        .ok_or_else(|| "compressed graph rebuild snapshot payload missing payload".to_owned())?;
    let compressed = BASE64_STANDARD
        .decode(encoded)
        .map_err(|error| format!("invalid compressed graph rebuild snapshot base64: {error}"))?;
    let mut decoder = GzDecoder::new(compressed.as_slice());
    let mut decoded = String::new();
    decoder
        .read_to_string(&mut decoded)
        .map_err(|error| format!("failed to decompress graph rebuild snapshot payload: {error}"))?;
    serde_json::from_str::<Value>(&decoded)
        .map_err(|error| format!("invalid decompressed graph rebuild snapshot JSON: {error}"))
}

fn store_relation_first(
    host: &PhoenixNativeHost,
    relation: &str,
    filter: Value,
) -> Result<Option<Value>, String> {
    let result = host
        .store_command(StoreCommandRequest {
            command: "relation:getFirst".to_owned(),
            payload: json!({ "relation": relation, "filter": filter }),
        })
        .map_err(|error| error.to_string())?;
    let value = serde_json::to_value(result)
        .map_err(|error| format!("failed to encode relation row: {error}"))?;
    let success = value
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !success {
        let error = value
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("store command failed");
        return Err(format!("failed to load relation {relation}: {error}"));
    }
    Ok(value
        .get("payload")
        .cloned()
        .filter(|payload| !payload.is_null()))
}

fn f32_field(row: &Value, key: &str) -> Option<f32> {
    row.get(key)
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .map(|value| value as f32)
}

fn store_relation_rows(host: &PhoenixNativeHost, relation: &str) -> Result<Vec<Value>, String> {
    let result = host
        .store_command(StoreCommandRequest {
            command: "relation:list".to_owned(),
            payload: json!({ "relation": relation }),
        })
        .map_err(|error| error.to_string())?;
    let value = serde_json::to_value(result)
        .map_err(|error| format!("failed to encode relation rows: {error}"))?;
    let success = value
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !success {
        let error = value
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("store command failed");
        return Err(format!("failed to load relation {relation}: {error}"));
    }
    Ok(value
        .get("payload")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default())
}

fn semantic_rows_to_payload(
    document_rows: &[Value],
    node_rows: &[Value],
    candidate_rows: &[Value],
    scope: Option<&Value>,
    limit: usize,
) -> DesktopManifoldPayload {
    let note_filter = scope
        .map(|scope| str_field(scope, "note_id", "noteId"))
        .unwrap_or_default();
    let mut seen = HashSet::<String>::with_capacity(limit.saturating_mul(2));
    let mut nodes = Vec::<DesktopManifoldNode>::with_capacity(limit);
    for row in document_rows {
        if nodes.len() >= limit {
            break;
        }
        let document_id = str_field(row, "document_id", "documentId");
        if document_id.is_empty() || (!note_filter.is_empty() && document_id != note_filter) {
            continue;
        }
        let vector = vector_field(row, "vec");
        if vector.is_empty() {
            continue;
        }
        let id = format!("doc::{document_id}");
        seen.insert(id.clone());
        nodes.push(DesktopManifoldNode {
            id,
            label: format!(
                "Document {}",
                document_id.chars().take(8).collect::<String>()
            ),
            source_type: "leaf".to_owned(),
            vector,
            base_vector: None,
            cell_id: None,
            secondary_cell_ids: Vec::new(),
            cell_distance: None,
            boundary_score: None,
            phase: None,
            fiber_kind: None,
            geometry_version: None,
            document_id: Some(document_id.to_owned()),
            narrative_id: None,
            folder_id: None,
            preview: evidence_preview(row),
            kind: "CONCEPT".to_owned(),
        });
    }
    for row in node_rows {
        if nodes.len() >= limit {
            break;
        }
        let id = str_field(row, "node_id", "nodeId");
        let document_id = str_field(row, "document_id", "documentId");
        let narrative_id = str_field(row, "narrative_id", "narrativeId");
        let folder_id = str_field(row, "folder_id", "folderId");
        if id.is_empty()
            || !semantic_node_matches_scope(&document_id, &narrative_id, &folder_id, scope)
        {
            continue;
        }
        let vector = vector_field(row, "vec");
        if vector.is_empty() {
            continue;
        }
        let node_kind = str_field(row, "node_kind", "nodeKind");
        let node_kind = if node_kind.is_empty() {
            "entity"
        } else {
            node_kind
        };
        let source_type = if node_kind.contains("lens") {
            "lens"
        } else if node_kind.contains("entity") {
            "entity"
        } else {
            node_kind
        };
        seen.insert(id.to_owned());
        nodes.push(DesktopManifoldNode {
            id: id.to_owned(),
            label: semantic_node_label(id),
            source_type: source_type.to_owned(),
            vector,
            base_vector: None,
            cell_id: None,
            secondary_cell_ids: Vec::new(),
            cell_distance: None,
            boundary_score: None,
            phase: None,
            fiber_kind: None,
            geometry_version: None,
            document_id: optional_string(document_id),
            narrative_id: optional_string(narrative_id),
            folder_id: optional_string(folder_id),
            preview: evidence_preview(row),
            kind: if node_kind.contains("event") {
                "EVENT"
            } else {
                "CONCEPT"
            }
            .to_owned(),
        });
    }
    let mut edges = Vec::<DesktopManifoldEdge>::with_capacity(
        candidate_rows.len().min(limit.saturating_mul(4)),
    );
    for row in candidate_rows {
        let source_id = str_field(row, "source_id", "sourceId");
        let target_id = str_field(row, "target_id", "targetId");
        if source_id.is_empty()
            || target_id.is_empty()
            || !seen.contains(source_id)
            || !seen.contains(target_id)
        {
            continue;
        }
        let edge_type = str_field(row, "edge_type", "edgeType");
        let edge_type = if edge_type.is_empty() {
            "candidate_relation"
        } else {
            edge_type
        };
        edges.push(DesktopManifoldEdge {
            id: format!("{source_id}:{edge_type}:{target_id}"),
            source_id: source_id.to_owned(),
            target_id: target_id.to_owned(),
            edge_type: edge_type.to_owned(),
            confidence: candidate_confidence(row),
        });
    }
    DesktopManifoldPayload {
        nodes,
        edges,
        source_label: "native hybrid semantic atlas",
        projection_source: "real_snapshot_vectors",
        cells: Vec::new(),
        charts: Vec::new(),
        seams: Vec::new(),
        neighbor_rings: Vec::new(),
        cone_traces: Vec::new(),
        cone_programs: Vec::new(),
        pathlets: Vec::new(),
        obstructions: Vec::new(),
        cone_program_traces: Vec::new(),
        anchor_projections: Vec::new(),
        lorentz_trees: Vec::new(),
        lorentz_memberships: Vec::new(),
        lorentz_cache: None,
    }
}

fn semantic_payload_to_hopf_payload(semantic: &DesktopManifoldPayload) -> DesktopManifoldPayload {
    let mut nodes =
        Vec::<DesktopManifoldNode>::with_capacity(semantic.nodes.len().saturating_mul(2));
    let mut edges = Vec::<DesktopManifoldEdge>::with_capacity(
        semantic.edges.len().saturating_add(semantic.nodes.len()),
    );
    let mut id_to_fiber = HashMap::<String, String>::with_capacity(semantic.nodes.len());
    let topology = IcoTopology::new(HOPF_ICO_RESOLUTION);
    let chart_topology = IcoTopology::new(HOPF_CHART_RESOLUTION);
    let mut assignments = Vec::<HopfAnchorAssignment>::with_capacity(semantic.nodes.len());
    for (index, node) in semantic.nodes.iter().enumerate() {
        if node.id.is_empty() || node.vector.is_empty() {
            continue;
        }
        let fiber_kind = infer_hopf_fiber_kind(node);
        let anchor_id = format!("hopf:anchor:{}", node.id);
        let fiber_id = format!("hopf:fiber:{}:{fiber_kind}", node.id);
        let direction = project_vector_to_direction(&node.vector, &node.id);
        let projection = topology.project(&direction);
        let chart_projection = chart_topology.project(&direction);
        let phase = hopf_phase_for_kind(fiber_kind, &node.id, index);
        id_to_fiber.insert(node.id.clone(), fiber_id.clone());
        let anchor_label = if node.label.is_empty() {
            node.id.clone()
        } else {
            node.label.clone()
        };
        assignments.push(HopfAnchorAssignment {
            anchor_id: anchor_id.clone(),
            fiber_id: fiber_id.clone(),
            fiber_kind: fiber_kind.to_owned(),
            cell_id: projection.primary_cell_id.clone(),
            chart_id: chart_projection.primary_cell_id.clone(),
            secondary_cell_ids: projection.secondary_cell_ids.clone(),
            center_vector: projection.center_vector,
            cell_distance: projection.cell_distance,
            boundary_score: projection.boundary_score,
            phase,
        });
        nodes.push(DesktopManifoldNode {
            id: anchor_id.clone(),
            label: anchor_label.clone(),
            source_type: "hopf_anchor".to_owned(),
            vector: node.vector.clone(),
            base_vector: Some(projection.center_vector),
            cell_id: Some(projection.primary_cell_id.clone()),
            secondary_cell_ids: projection.secondary_cell_ids.clone(),
            cell_distance: Some(projection.cell_distance),
            boundary_score: Some(projection.boundary_score),
            phase: Some(0.0),
            fiber_kind: None,
            geometry_version: Some(HOPF_GEOMETRY_VERSION),
            document_id: node.document_id.clone(),
            narrative_id: node.narrative_id.clone(),
            folder_id: node.folder_id.clone(),
            preview: node.preview.clone(),
            kind: "HOPF_ANCHOR".to_owned(),
        });
        nodes.push(DesktopManifoldNode {
            id: fiber_id.clone(),
            label: format!("{} / {}", anchor_label, fiber_kind.replace('_', " ")),
            source_type: "hopf_fiber".to_owned(),
            vector: fiber_vector(&node.vector, fiber_kind, index),
            base_vector: Some(projection.center_vector),
            cell_id: Some(projection.primary_cell_id),
            secondary_cell_ids: projection.secondary_cell_ids,
            cell_distance: Some(projection.cell_distance),
            boundary_score: Some(projection.boundary_score),
            phase: Some(phase),
            fiber_kind: Some(fiber_kind.to_owned()),
            geometry_version: Some(HOPF_GEOMETRY_VERSION),
            document_id: node.document_id.clone(),
            narrative_id: node.narrative_id.clone(),
            folder_id: node.folder_id.clone(),
            preview: format!("{fiber_kind} context fiber"),
            kind: format!("HOPF_FIBER:{fiber_kind}"),
        });
        edges.push(DesktopManifoldEdge {
            id: format!("hopf:anchor-fiber:{}", node.id),
            source_id: anchor_id,
            target_id: fiber_id,
            edge_type: "hopf-anchor-fiber".to_owned(),
            confidence: 1.25,
        });
    }
    for edge in &semantic.edges {
        let Some(source_fiber) = id_to_fiber.get(edge.source_id.as_str()) else {
            continue;
        };
        let Some(target_fiber) = id_to_fiber.get(edge.target_id.as_str()) else {
            continue;
        };
        if source_fiber == target_fiber {
            continue;
        }
        let edge_type = if edge.edge_type.is_empty() {
            "semantic"
        } else {
            edge.edge_type.as_str()
        };
        edges.push(DesktopManifoldEdge {
            id: format!("hopf:fiber-edge:{}", edge.id),
            source_id: source_fiber.clone(),
            target_id: target_fiber.clone(),
            edge_type: format!("hopf-fiber-edge:{edge_type}"),
            confidence: edge.confidence,
        });
    }
    DesktopManifoldPayload {
        nodes,
        edges,
        source_label: "native hopf anchors + fibers",
        projection_source: "real_snapshot_vectors",
        cells: build_desktop_cells(&topology, &assignments),
        charts: build_desktop_charts(&topology, &chart_topology, &assignments),
        seams: build_desktop_seams(&topology, &assignments),
        neighbor_rings: build_desktop_neighbor_rings(&topology, &assignments),
        cone_traces: build_desktop_cone_traces(&topology, &assignments),
        cone_programs: Vec::new(),
        pathlets: Vec::new(),
        obstructions: Vec::new(),
        cone_program_traces: Vec::new(),
        anchor_projections: assignments
            .iter()
            .map(|assignment| DesktopAnchorProjection {
                anchor_id: assignment.anchor_id.clone(),
                primary_cell_id: assignment.cell_id.clone(),
                secondary_cell_ids: assignment.secondary_cell_ids.clone(),
                cell_distance: assignment.cell_distance,
                boundary_score: assignment.boundary_score,
                projection_version: HOPF_PROJECTION_VERSION,
                geometry_version: HOPF_GEOMETRY_VERSION,
            })
            .collect(),
        lorentz_trees: Vec::new(),
        lorentz_memberships: Vec::new(),
        lorentz_cache: None,
    }
}

struct LorentzSidecar {
    mmap: MmapLorentzForestIndex,
    cache: DesktopLorentzCacheStatus,
}

fn build_lorentz_forest_response(
    host: &PhoenixNativeHost,
    request: DesktopLorentzForestBuildRequest,
) -> Result<DesktopLorentzForestBuildResponse, String> {
    let sidecar = ensure_lorentz_sidecar(
        host,
        request.scope.as_ref(),
        request.limit,
        request.force.unwrap_or(false),
    )?;
    let index = sidecar.mmap.index();
    let snapshot = if request.include_snapshot.unwrap_or(false) {
        Some(lorentz_index_to_snapshot(index))
    } else {
        None
    };
    Ok(DesktopLorentzForestBuildResponse {
        geometry_version: LORENTZ_GEOMETRY_VERSION,
        source_label: "native lorentz h4 forest sidecar",
        cache: sidecar.cache,
        node_count: index.nodes.len(),
        tree_count: index.trees.len(),
        membership_count: index.memberships.len(),
        snapshot,
    })
}

fn query_lorentz_forest_response(
    host: &PhoenixNativeHost,
    request: DesktopLorentzForestQueryRequest,
) -> Result<DesktopLorentzForestQueryResponse, String> {
    let sidecar = ensure_lorentz_sidecar(
        host,
        request.scope.as_ref(),
        request.limit,
        request.force.unwrap_or(false),
    )?;
    let index = sidecar.mmap.index();
    let query_point = lorentz_query_point(index, &request)?;
    let mut query = LorentzTreeQuery::new(query_point).map_err(|error| error.to_string())?;
    if let Some(tree_ids) = request.tree_ids {
        query = query.with_tree_ids(tree_ids);
    }
    if let Some(tree_kinds) = request.tree_kinds {
        query = query.with_tree_kinds(
            tree_kinds
                .iter()
                .filter_map(|kind| parse_lorentz_tree_kind(kind))
                .collect(),
        );
    }
    if let Some(target_level) = request.target_level {
        query = query.with_target_level(target_level);
    }
    if let Some(mode) = request.mode.as_deref().and_then(parse_lorentz_query_mode) {
        query = query.with_mode(mode);
    }
    let top_k = request.top_k.unwrap_or(24).clamp(1, 512);
    let hits = sidecar
        .mmap
        .rank(&query, LorentzScoreConfig::default())
        .map_err(|error| error.to_string())?
        .into_iter()
        .take(top_k)
        .map(|score| lorentz_score_to_hit(index, score))
        .collect::<Vec<_>>();
    Ok(DesktopLorentzForestQueryResponse {
        geometry_version: LORENTZ_GEOMETRY_VERSION,
        cache: sidecar.cache,
        query_point: query_point.coords,
        hits,
    })
}

fn ensure_lorentz_sidecar(
    host: &PhoenixNativeHost,
    scope: Option<&Value>,
    limit: Option<usize>,
    force: bool,
) -> Result<LorentzSidecar, String> {
    let mut cache = lorentz_cache_status(host, scope, limit)?;
    if force || !cache.exists {
        let document_rows = store_relation_rows(host, "semantic_documents")?;
        let node_rows = store_relation_rows(host, "semantic_node_prototypes")?;
        let candidate_rows = store_relation_rows(host, "graph_candidate_edges")?;
        let semantic = semantic_rows_to_payload(
            &document_rows,
            &node_rows,
            &candidate_rows,
            scope,
            limit.unwrap_or(720).max(1),
        );
        let forest = semantic_payload_to_lorentz_forest(&semantic)?;
        let index = LorentzForestIndex::from_forest(&forest).map_err(|error| error.to_string())?;
        if let Some(parent) = PathBuf::from(&cache.cache_path).parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        MmapLorentzForestIndex::write_index_to_file(&index, &cache.cache_path)
            .map_err(|error| error.to_string())?;
        cache = lorentz_cache_status(host, scope, limit)?;
        cache.rebuilt = true;
    }
    let mmap =
        MmapLorentzForestIndex::open(&cache.cache_path).map_err(|error| error.to_string())?;
    cache.mmap = true;
    Ok(LorentzSidecar { mmap, cache })
}

fn lorentz_cache_status(
    host: &PhoenixNativeHost,
    scope: Option<&Value>,
    limit: Option<usize>,
) -> Result<DesktopLorentzCacheStatus, String> {
    let (cache_key, cache_path) = lorentz_cache_path(host, scope, limit)?;
    let metadata = std::fs::metadata(&cache_path).ok();
    Ok(DesktopLorentzCacheStatus {
        geometry_version: LORENTZ_GEOMETRY_VERSION,
        cache_key,
        cache_path: cache_path.to_string_lossy().into_owned(),
        exists: metadata.is_some(),
        byte_len: metadata.map(|meta| meta.len()).unwrap_or_default(),
        mmap: false,
        rebuilt: false,
    })
}

fn lorentz_cache_path(
    host: &PhoenixNativeHost,
    scope: Option<&Value>,
    limit: Option<usize>,
) -> Result<(String, PathBuf), String> {
    let scope_json = scope
        .map(|scope| scope.to_string())
        .unwrap_or_else(|| "global".to_owned());
    let effective_limit = limit.unwrap_or(720).max(1);
    let cache_key = format!(
        "scope-{:016x}-limit-{effective_limit}",
        stable_hash64(&scope_json)
    );
    let base = host
        .config()
        .and_then(|config| config.storage_path.as_ref())
        .cloned()
        .unwrap_or_else(|| std::env::temp_dir().join("phoenix-desktop"));
    Ok((
        cache_key.clone(),
        base.join("lorentz-forest")
            .join(format!("{LORENTZ_GEOMETRY_VERSION}-{cache_key}.bin")),
    ))
}

fn semantic_payload_to_lorentz_forest(
    semantic: &DesktopManifoldPayload,
) -> Result<LorentzForest, String> {
    let mut forest = LorentzForest::new();
    let mut semantic_ids = BTreeSet::<String>::new();
    for node in &semantic.nodes {
        if node.id.is_empty() || node.vector.is_empty() {
            continue;
        }
        let mut lorentz_node = LorentzNode::new(
            node.id.clone(),
            if node.label.is_empty() {
                node.id.clone()
            } else {
                node.label.clone()
            },
            lorentz_point_from_vector(&node.vector, &node.id)?,
        )
        .map_err(|error| error.to_string())?;
        lorentz_node.point_ref = optional_string(node.preview.as_str());
        forest
            .add_node(lorentz_node)
            .map_err(|error| error.to_string())?;
        semantic_ids.insert(node.id.clone());
    }

    let parent_maps = build_lorentz_parent_maps(semantic, &semantic_ids);
    for (tree_id, kind, label) in lorentz_tree_specs() {
        let root_id = format!("lorentz:root:{tree_id}");
        forest
            .add_node(
                LorentzNode::new(
                    root_id.clone(),
                    format!("{label} root"),
                    HyperboloidPoint::origin(),
                )
                .map_err(|error| error.to_string())?,
            )
            .map_err(|error| error.to_string())?;
        forest
            .add_tree(LorentzTree::new(tree_id, kind, label))
            .map_err(|error| error.to_string())?;
        forest
            .attach_root(tree_id, root_id.as_str())
            .map_err(|error| error.to_string())?;
        attach_lorentz_tree_memberships(
            &mut forest,
            tree_id,
            root_id.as_str(),
            &semantic_ids,
            parent_maps.get(&kind),
        )?;
    }
    forest.rebuild_indexes();
    Ok(forest)
}

fn build_lorentz_parent_maps(
    semantic: &DesktopManifoldPayload,
    semantic_ids: &BTreeSet<String>,
) -> BTreeMap<LorentzTreeKind, BTreeMap<String, String>> {
    let mut best = BTreeMap::<LorentzTreeKind, BTreeMap<String, (String, f64)>>::new();
    for node in &semantic.nodes {
        let Some(document_id) = node.document_id.as_ref() else {
            continue;
        };
        let doc_node_id = format!("doc::{document_id}");
        if semantic_ids.contains(&node.id)
            && semantic_ids.contains(&doc_node_id)
            && node.id != doc_node_id
        {
            best.entry(LorentzTreeKind::DocumentStructure)
                .or_default()
                .insert(node.id.clone(), (doc_node_id, 1.0));
        }
    }
    for edge in &semantic.edges {
        if edge.source_id == edge.target_id
            || !semantic_ids.contains(&edge.source_id)
            || !semantic_ids.contains(&edge.target_id)
        {
            continue;
        }
        let Some(kind) = lorentz_kind_for_edge_type(&edge.edge_type) else {
            continue;
        };
        let by_target = best.entry(kind).or_default();
        let replace = by_target
            .get(&edge.target_id)
            .map(|(parent, confidence)| {
                edge.confidence > *confidence
                    || (edge.confidence == *confidence && edge.source_id < *parent)
            })
            .unwrap_or(true);
        if replace {
            by_target.insert(
                edge.target_id.clone(),
                (edge.source_id.clone(), edge.confidence),
            );
        }
    }
    best.into_iter()
        .map(|(kind, map)| {
            (
                kind,
                map.into_iter()
                    .map(|(child, (parent, _))| (child, parent))
                    .collect(),
            )
        })
        .collect()
}

fn attach_lorentz_tree_memberships(
    forest: &mut LorentzForest,
    tree_id: &str,
    root_id: &str,
    semantic_ids: &BTreeSet<String>,
    parent_map: Option<&BTreeMap<String, String>>,
) -> Result<(), String> {
    let mut pending = semantic_ids.clone();
    let mut attached = BTreeSet::<String>::from([root_id.to_owned()]);
    while !pending.is_empty() {
        let mut progress = false;
        for node_id in pending.clone() {
            let parent_id = parent_map
                .and_then(|parents| parents.get(&node_id))
                .filter(|parent| semantic_ids.contains(parent.as_str()))
                .map(String::as_str)
                .unwrap_or(root_id);
            if parent_id == root_id || attached.contains(parent_id) {
                let rank = attached.len().min(u32::MAX as usize) as u32;
                forest
                    .attach_child(tree_id, parent_id, node_id.as_str(), rank)
                    .map_err(|error| error.to_string())?;
                pending.remove(&node_id);
                attached.insert(node_id);
                progress = true;
            }
        }
        if !progress {
            for node_id in pending.clone() {
                let rank = attached.len().min(u32::MAX as usize) as u32;
                forest
                    .attach_child(tree_id, root_id, node_id.as_str(), rank)
                    .map_err(|error| error.to_string())?;
                pending.remove(&node_id);
                attached.insert(node_id);
            }
        }
    }
    Ok(())
}

fn lorentz_index_to_payload(
    index: &LorentzForestIndex,
    cache: DesktopLorentzCacheStatus,
) -> DesktopManifoldPayload {
    let snapshot = lorentz_index_to_snapshot(index);
    DesktopManifoldPayload {
        nodes: snapshot.nodes,
        edges: snapshot.edges,
        source_label: "native lorentz h4 forest sidecar",
        projection_source: "real_snapshot_vectors",
        cells: Vec::new(),
        charts: Vec::new(),
        seams: Vec::new(),
        neighbor_rings: Vec::new(),
        cone_traces: Vec::new(),
        cone_programs: Vec::new(),
        pathlets: Vec::new(),
        obstructions: Vec::new(),
        cone_program_traces: Vec::new(),
        anchor_projections: Vec::new(),
        lorentz_trees: snapshot.trees,
        lorentz_memberships: snapshot.memberships,
        lorentz_cache: Some(cache),
    }
}

fn product_index_to_payload(
    semantic: &DesktopManifoldPayload,
    index: &LorentzForestIndex,
    cache: DesktopLorentzCacheStatus,
) -> DesktopManifoldPayload {
    let snapshot = lorentz_index_to_snapshot(index);
    let mut semantic_by_id = HashMap::<String, (&DesktopManifoldNode, usize)>::new();
    for (ord, node) in semantic.nodes.iter().enumerate() {
        semantic_by_id.insert(node.id.clone(), (node, ord));
    }
    let topology = IcoTopology::new(HOPF_ICO_RESOLUTION);
    let chart_topology = IcoTopology::new(HOPF_CHART_RESOLUTION);
    let mut assignments = Vec::<HopfAnchorAssignment>::new();
    let mut nodes = snapshot.nodes;
    for node in &mut nodes {
        let Some((semantic_node, index)) = semantic_by_id.get(node.id.as_str()) else {
            continue;
        };
        let fiber_kind = infer_hopf_fiber_kind(semantic_node);
        let direction = project_vector_to_direction(&semantic_node.vector, &semantic_node.id);
        let projection = topology.project(&direction);
        let chart_projection = chart_topology.project(&direction);
        let phase = hopf_phase_for_kind(fiber_kind, &semantic_node.id, *index);
        assignments.push(HopfAnchorAssignment {
            anchor_id: node.id.clone(),
            fiber_id: format!("product:fiber:{}:{fiber_kind}", node.id),
            fiber_kind: fiber_kind.to_owned(),
            cell_id: projection.primary_cell_id.clone(),
            chart_id: chart_projection.primary_cell_id,
            secondary_cell_ids: projection.secondary_cell_ids.clone(),
            center_vector: projection.center_vector,
            cell_distance: projection.cell_distance,
            boundary_score: projection.boundary_score,
            phase,
        });
        node.source_type = "product_node".to_owned();
        node.base_vector = Some(projection.center_vector);
        node.cell_id = Some(projection.primary_cell_id);
        node.secondary_cell_ids = projection.secondary_cell_ids;
        node.cell_distance = Some(projection.cell_distance);
        node.boundary_score = Some(projection.boundary_score);
        node.phase = Some(phase);
        node.fiber_kind = Some(fiber_kind.to_owned());
        node.geometry_version = Some(PRODUCT_GEOMETRY_VERSION);
        node.document_id = semantic_node.document_id.clone();
        node.narrative_id = semantic_node.narrative_id.clone();
        node.folder_id = semantic_node.folder_id.clone();
        node.preview = semantic_node.preview.clone();
        node.kind = format!("PRODUCT:{}", semantic_node.kind);
    }
    let edges = snapshot.edges;
    let traversal = build_desktop_product_cone_traversal(&nodes, &edges);
    DesktopManifoldPayload {
        nodes,
        edges,
        source_label: "native product Lorentz-Hopf atlas",
        projection_source: "real_snapshot_vectors",
        cells: build_desktop_cells(&topology, &assignments),
        charts: build_desktop_charts(&topology, &chart_topology, &assignments),
        seams: build_desktop_seams(&topology, &assignments),
        neighbor_rings: build_desktop_neighbor_rings(&topology, &assignments),
        cone_traces: build_desktop_cone_traces(&topology, &assignments),
        cone_programs: traversal.programs,
        pathlets: traversal.pathlets,
        obstructions: traversal.obstructions,
        cone_program_traces: traversal.traces,
        anchor_projections: assignments
            .iter()
            .map(|assignment| DesktopAnchorProjection {
                anchor_id: assignment.anchor_id.clone(),
                primary_cell_id: assignment.cell_id.clone(),
                secondary_cell_ids: assignment.secondary_cell_ids.clone(),
                cell_distance: assignment.cell_distance,
                boundary_score: assignment.boundary_score,
                projection_version: HOPF_PROJECTION_VERSION,
                geometry_version: PRODUCT_GEOMETRY_VERSION,
            })
            .collect(),
        lorentz_trees: snapshot.trees,
        lorentz_memberships: snapshot.memberships,
        lorentz_cache: Some(cache),
    }
}

fn build_desktop_product_cone_traversal(
    nodes: &[DesktopManifoldNode],
    edges: &[DesktopManifoldEdge],
) -> DesktopProductConeTraversal {
    let by_id = nodes
        .iter()
        .map(|node| (node.id.as_str(), node))
        .collect::<HashMap<_, _>>();
    let mut out = DesktopProductConeTraversal::default();
    for edge in edges.iter().take(512) {
        let Some(source) = by_id.get(edge.source_id.as_str()) else {
            continue;
        };
        let Some(target) = by_id.get(edge.target_id.as_str()) else {
            continue;
        };
        let source_lane = desktop_product_lane(source);
        let target_lane = desktop_product_lane(target);
        let lane = desktop_product_pathlet_lane(edge, &source_lane, &target_lane);
        let obstruction =
            desktop_product_edge_obstruction(edge, target, &source_lane, &target_lane);
        let obstruction_ids = obstruction
            .as_ref()
            .map(|obs| vec![obs.obstruction_id.clone()])
            .unwrap_or_default();
        if let Some(obs) = obstruction {
            out.obstructions.push(obs);
        }
        let support_score =
            desktop_product_support(edge, source, target, &source_lane, &target_lane);
        out.pathlets.push(DesktopConePathletRecord {
            pathlet_id: format!("pathlet:{}", normalize_contract_token(&edge.id)),
            lane,
            start_id: edge.source_id.clone(),
            end_id: edge.target_id.clone(),
            node_ids: vec![edge.source_id.clone(), edge.target_id.clone()],
            edge_ids: vec![edge.id.clone()],
            support_score,
            compression_score: (0.42 + support_score * 0.38).clamp(0.0, 1.0),
            obstruction_ids,
            geometry_version: PRODUCT_GEOMETRY_VERSION,
        });
    }
    out.programs = desktop_product_programs(&out.pathlets, &out.obstructions);
    out.traces = out
        .programs
        .iter()
        .map(|program| desktop_product_trace(program, &out.pathlets, &out.obstructions))
        .collect();
    out
}

fn desktop_product_edge_obstruction(
    edge: &DesktopManifoldEdge,
    target: &DesktopManifoldNode,
    source_lane: &str,
    target_lane: &str,
) -> Option<DesktopConeObstructionRecord> {
    if source_lane != target_lane && !desktop_product_legal_move(source_lane, target_lane) {
        return Some(desktop_product_obstruction(
            &format!("edge:{}:lane", edge.id),
            "LaneMismatch",
            0.74,
            target,
            &[edge.source_id.clone(), edge.target_id.clone()],
            &[edge.id.clone()],
            &format!("{source_lane} cannot stitch directly to {target_lane}."),
        ));
    }
    if edge.confidence < 0.24 {
        return Some(desktop_product_obstruction(
            &format!("edge:{}:evidence", edge.id),
            "EvidenceMissing",
            0.68,
            target,
            &[edge.source_id.clone(), edge.target_id.clone()],
            &[edge.id.clone()],
            "Low-evidence traversal candidate from native product index.",
        ));
    }
    if edge.edge_type.contains("bridge") && edge.confidence < 0.52 {
        return Some(desktop_product_obstruction(
            &format!("edge:{}:bridge", edge.id),
            "UnsupportedBridge",
            0.58,
            target,
            &[edge.source_id.clone(), edge.target_id.clone()],
            &[edge.id.clone()],
            "Bridge traversal needs stronger graph support before promotion.",
        ));
    }
    None
}

fn desktop_product_obstruction(
    id: &str,
    kind: &str,
    severity: f64,
    target: &DesktopManifoldNode,
    node_ids: &[String],
    edge_ids: &[String],
    explanation: &str,
) -> DesktopConeObstructionRecord {
    DesktopConeObstructionRecord {
        obstruction_id: format!("obstruction:{}", normalize_contract_token(id)),
        kind: kind.to_owned(),
        severity,
        explanation: explanation.to_owned(),
        node_ids: node_ids.to_vec(),
        edge_ids: edge_ids.to_vec(),
        chart_ids: target
            .cell_id
            .as_ref()
            .map(|cell| vec![format!("chart:{cell}")])
            .unwrap_or_default(),
        evidence_refs: Vec::new(),
        lane: Some(desktop_product_lane(target)),
        geometry_version: PRODUCT_GEOMETRY_VERSION,
    }
}

fn desktop_product_lane(node: &DesktopManifoldNode) -> String {
    let text = format!(
        "{} {} {} {}",
        node.kind, node.source_type, node.label, node.preview
    )
    .to_ascii_lowercase();
    if text.contains("evidence")
        || text.contains("source")
        || text.contains("document")
        || text.contains("chunk")
        || text.contains("anchor")
    {
        "evidence".to_owned()
    } else if text.contains("entity")
        || text.contains("identity")
        || text.contains("character")
        || text.contains("location")
    {
        "identity".to_owned()
    } else if text.contains("temporal") || text.contains("timeline") {
        "temporal".to_owned()
    } else if text.contains("causal") || text.contains("cause") {
        "causal".to_owned()
    } else if text.contains("event") || text.contains("scene") {
        "event".to_owned()
    } else if text.contains("bridge") || text.contains("backbone") {
        "bridge".to_owned()
    } else if text.contains("relation") || text.contains("fact") {
        "relationship".to_owned()
    } else {
        "semantic".to_owned()
    }
}

fn desktop_product_pathlet_lane(
    edge: &DesktopManifoldEdge,
    source_lane: &str,
    target_lane: &str,
) -> String {
    let edge_type = edge.edge_type.to_ascii_lowercase();
    if edge_type.contains("causal") || edge_type.contains("cause") {
        "causal".to_owned()
    } else if edge_type.contains("temporal")
        || edge_type.contains("before")
        || edge_type.contains("after")
    {
        "temporal".to_owned()
    } else if edge_type.contains("evidence")
        || edge_type.contains("anchor")
        || edge_type.contains("chunk")
    {
        "evidence".to_owned()
    } else if edge_type.contains("identity")
        || edge_type.contains("entity")
        || edge_type.contains("alias")
    {
        "identity".to_owned()
    } else if edge_type.contains("bridge") || edge_type.contains("backbone") {
        "bridge".to_owned()
    } else if target_lane != "semantic" {
        target_lane.to_owned()
    } else {
        source_lane.to_owned()
    }
}

fn desktop_product_support(
    edge: &DesktopManifoldEdge,
    _source: &DesktopManifoldNode,
    _target: &DesktopManifoldNode,
    source_lane: &str,
    target_lane: &str,
) -> f64 {
    let lane_bonus = if source_lane == target_lane {
        0.08
    } else if desktop_product_legal_move(source_lane, target_lane) {
        0.04
    } else {
        -0.16
    };
    (edge.confidence * 0.78 + lane_bonus).clamp(0.0, 1.0)
}

fn desktop_product_legal_move(source_lane: &str, target_lane: &str) -> bool {
    matches!(
        (source_lane, target_lane),
        ("evidence", "identity")
            | ("evidence", "relationship")
            | ("evidence", "temporal")
            | ("evidence", "causal")
            | ("identity", "relationship")
            | ("identity", "event")
            | ("identity", "temporal")
            | ("identity", "causal")
            | ("relationship", "evidence")
            | ("relationship", "identity")
            | ("relationship", "temporal")
            | ("relationship", "causal")
            | ("event", "temporal")
            | ("event", "causal")
            | ("temporal", "event")
            | ("temporal", "causal")
            | ("causal", "event")
            | ("causal", "temporal")
            | ("bridge", "identity")
            | ("bridge", "relationship")
            | ("bridge", "evidence")
            | ("semantic", "identity")
            | ("semantic", "relationship")
            | ("semantic", "evidence")
    )
}

fn desktop_product_programs(
    pathlets: &[DesktopConePathletRecord],
    obstructions: &[DesktopConeObstructionRecord],
) -> Vec<DesktopConeProgramRecord> {
    let seed_ids = unique_limited(pathlets.iter().map(|pathlet| pathlet.start_id.clone()), 12);
    let repair_ids = unique_limited(
        obstructions
            .iter()
            .flat_map(|obstruction| obstruction.node_ids.iter().cloned()),
        12,
    );
    let mut programs = Vec::new();
    if !seed_ids.is_empty() {
        programs.push(desktop_product_program(
            "product:trace-supported-routes",
            "trace",
            seed_ids.clone(),
            "evidence",
            false,
        ));
        programs.push(desktop_product_program(
            "product:validate-stitches",
            "validate",
            seed_ids,
            "relationship",
            true,
        ));
    }
    if !repair_ids.is_empty() {
        programs.push(desktop_product_program(
            "product:repair-obstructions",
            "repair",
            repair_ids,
            "bridge",
            true,
        ));
    }
    programs
}

fn desktop_product_program(
    program_id: &str,
    intent: &str,
    seed_ids: Vec<String>,
    lane: &str,
    require_evidence: bool,
) -> DesktopConeProgramRecord {
    DesktopConeProgramRecord {
        program_id: program_id.to_owned(),
        intent: intent.to_owned(),
        seed_ids: seed_ids.clone(),
        geometry_version: PRODUCT_GEOMETRY_VERSION,
        ops: vec![
            desktop_program_op(
                "seed",
                None,
                seed_ids,
                Vec::new(),
                None,
                None,
                None,
                None,
                None,
                Vec::new(),
            ),
            desktop_program_op(
                "followField",
                Some(lane),
                Vec::new(),
                Vec::new(),
                Some(if require_evidence { 0.72 } else { 0.92 }),
                Some(64),
                None,
                None,
                None,
                Vec::new(),
            ),
            desktop_program_op(
                "stitch",
                None,
                Vec::new(),
                Vec::new(),
                None,
                None,
                Some(if require_evidence { 0.58 } else { 0.42 }),
                Some(require_evidence),
                None,
                Vec::new(),
            ),
            desktop_program_op(
                "ground",
                None,
                Vec::new(),
                Vec::new(),
                None,
                None,
                None,
                None,
                Some(require_evidence),
                Vec::new(),
            ),
            desktop_program_op(
                "rerank",
                None,
                Vec::new(),
                Vec::new(),
                None,
                None,
                None,
                None,
                None,
                vec![
                    "support".to_owned(),
                    "stitchQuality".to_owned(),
                    "cost".to_owned(),
                ],
            ),
            desktop_program_op(
                "explain",
                None,
                Vec::new(),
                Vec::new(),
                None,
                Some(8),
                None,
                None,
                None,
                Vec::new(),
            ),
        ],
    }
}

#[allow(clippy::too_many_arguments)]
fn desktop_program_op(
    op: &str,
    lane: Option<&str>,
    ids: Vec<String>,
    required_ids: Vec<String>,
    max_cost: Option<f64>,
    limit: Option<u32>,
    min_compatibility: Option<f64>,
    require_evidence: Option<bool>,
    strict: Option<bool>,
    rank_by: Vec<String>,
) -> DesktopConeProgramOpRecord {
    DesktopConeProgramOpRecord {
        op: op.to_owned(),
        lane: lane.map(str::to_owned),
        ids,
        required_ids,
        max_cost,
        limit,
        min_compatibility,
        require_evidence,
        strict,
        pathlet_id: None,
        rank_by,
    }
}

fn desktop_product_trace(
    program: &DesktopConeProgramRecord,
    pathlets: &[DesktopConePathletRecord],
    obstructions: &[DesktopConeObstructionRecord],
) -> DesktopConeProgramTraceRecord {
    let lane = program
        .ops
        .iter()
        .find(|op| op.op == "followField")
        .and_then(|op| op.lane.as_deref())
        .unwrap_or_default();
    let selected = pathlets
        .iter()
        .filter(|pathlet| lane.is_empty() || pathlet.lane == lane || program.intent == "repair")
        .take(64)
        .collect::<Vec<_>>();
    let path_edge_ids = unique_limited(
        selected
            .iter()
            .flat_map(|pathlet| pathlet.edge_ids.iter().cloned()),
        128,
    );
    let pathlet_ids = selected
        .iter()
        .map(|pathlet| pathlet.pathlet_id.clone())
        .collect::<Vec<_>>();
    let active_ids = unique_limited(
        selected
            .iter()
            .flat_map(|pathlet| pathlet.node_ids.iter().cloned()),
        128,
    );
    let obstruction_ids = if program.intent == "repair" {
        unique_limited(
            obstructions.iter().map(|obs| obs.obstruction_id.clone()),
            128,
        )
    } else {
        unique_limited(
            selected
                .iter()
                .flat_map(|pathlet| pathlet.obstruction_ids.iter().cloned()),
            128,
        )
    };
    DesktopConeProgramTraceRecord {
        trace_id: format!("trace:{}", program.program_id),
        program_id: program.program_id.clone(),
        active_ids,
        pathlet_ids,
        obstruction_ids,
        path_edge_ids,
        explanations: vec![
            format!("{} pathlets traversed", selected.len()),
            format!("{} obstructions surfaced", obstructions.len()),
        ],
        geometry_version: PRODUCT_GEOMETRY_VERSION,
    }
}

fn unique_limited<I>(values: I, limit: usize) -> Vec<String>
where
    I: IntoIterator<Item = String>,
{
    let mut seen = HashSet::<String>::with_capacity(limit.saturating_mul(2));
    let mut out = Vec::<String>::with_capacity(limit);
    for value in values {
        if value.is_empty() || !seen.insert(value.clone()) {
            continue;
        }
        out.push(value);
        if out.len() >= limit {
            break;
        }
    }
    out
}

fn lorentz_index_to_snapshot(index: &LorentzForestIndex) -> DesktopLorentzForestSnapshot {
    let nodes = index.nodes.iter().map(lorentz_node_to_desktop).collect();
    let trees = index
        .trees
        .iter()
        .map(lorentz_tree_to_record)
        .collect::<Vec<_>>();
    let memberships = index
        .memberships
        .iter()
        .map(lorentz_membership_to_record)
        .collect::<Vec<_>>();
    let tree_kind_by_id = index
        .trees
        .iter()
        .map(|tree| (tree.tree_id.clone(), lorentz_kind_name(tree.tree_kind)))
        .collect::<BTreeMap<_, _>>();
    let edges = index
        .memberships
        .iter()
        .filter_map(|membership| {
            let parent_id = membership.parent_node_id.as_ref()?;
            Some(DesktopManifoldEdge {
                id: format!(
                    "lorentz:{}:{}:{}",
                    membership.tree_id, parent_id, membership.node_id
                ),
                source_id: parent_id.clone(),
                target_id: membership.node_id.clone(),
                edge_type: format!(
                    "lorentz-tree:{}",
                    tree_kind_by_id
                        .get(&membership.tree_id)
                        .copied()
                        .unwrap_or("unknown")
                ),
                confidence: membership.confidence as f64,
            })
        })
        .collect();
    DesktopLorentzForestSnapshot {
        nodes,
        edges,
        trees,
        memberships,
    }
}

fn lorentz_node_to_desktop(node: &LorentzNode) -> DesktopManifoldNode {
    let is_root = node.node_id.starts_with("lorentz:root:");
    DesktopManifoldNode {
        id: node.node_id.clone(),
        label: node.label.clone(),
        source_type: if is_root {
            "lorentz_root".to_owned()
        } else {
            "lorentz_node".to_owned()
        },
        vector: node.coords_f64(),
        base_vector: None,
        cell_id: None,
        secondary_cell_ids: Vec::new(),
        cell_distance: None,
        boundary_score: None,
        phase: None,
        fiber_kind: None,
        geometry_version: Some(LORENTZ_GEOMETRY_VERSION),
        document_id: None,
        narrative_id: None,
        folder_id: None,
        preview: node.point_ref.clone().unwrap_or_default(),
        kind: if is_root {
            "LORENTZ_ROOT".to_owned()
        } else {
            "LORENTZ_NODE".to_owned()
        },
    }
}

trait LorentzNodeDesktopExt {
    fn coords_f64(&self) -> Vec<f64>;
}

impl LorentzNodeDesktopExt for LorentzNode {
    fn coords_f64(&self) -> Vec<f64> {
        self.point
            .coords
            .iter()
            .map(|value| *value as f64)
            .collect()
    }
}

fn lorentz_tree_to_record(tree: &LorentzTree) -> DesktopLorentzTreeRecord {
    DesktopLorentzTreeRecord {
        tree_id: tree.tree_id.clone(),
        tree_kind: lorentz_kind_name(tree.tree_kind).to_owned(),
        label: tree.label.clone(),
        root_node_id: tree.root_node_id.clone(),
        geometry_version: LORENTZ_GEOMETRY_VERSION,
    }
}

fn lorentz_membership_to_record(
    membership: &LorentzTreeMembership,
) -> DesktopLorentzMembershipRecord {
    DesktopLorentzMembershipRecord {
        tree_id: membership.tree_id.clone(),
        node_id: membership.node_id.clone(),
        parent_node_id: membership.parent_node_id.clone(),
        level: membership.level,
        local_rank: membership.local_rank,
        path_key: membership.path_key.clone(),
        branch_weight: membership.branch_weight,
        confidence: membership.confidence,
        source_count: membership.source_count,
        geometry_version: LORENTZ_GEOMETRY_VERSION,
    }
}

fn lorentz_score_to_hit(
    index: &LorentzForestIndex,
    score: phoenix_hyperbolic::lorentz_tree::LorentzCandidateScore<String>,
) -> DesktopLorentzQueryHit {
    let label = index
        .nodes
        .iter()
        .find(|node| node.node_id == score.node_id)
        .map(|node| node.label.clone())
        .unwrap_or_else(|| score.node_id.clone());
    let path_key = score.tree_id.as_ref().and_then(|tree_id| {
        index
            .memberships
            .iter()
            .find(|membership| {
                membership.tree_id == *tree_id && membership.node_id == score.node_id
            })
            .map(|membership| membership.path_key.clone())
    });
    DesktopLorentzQueryHit {
        candidate_id: score.candidate_id,
        node_id: score.node_id,
        label,
        tree_id: score.tree_id,
        tree_kind: score
            .tree_kind
            .map(|kind| lorentz_kind_name(kind).to_owned()),
        path_key,
        score: score.score,
        hyperbolic_distance: score.hyperbolic_distance,
        geometry_similarity: score.geometry_similarity,
        hierarchy_alignment: score.hierarchy_alignment,
        confidence: score.confidence,
    }
}

fn lorentz_query_point(
    index: &LorentzForestIndex,
    request: &DesktopLorentzForestQueryRequest,
) -> Result<HyperboloidPoint, String> {
    if let Some(vector) = &request.query_vector {
        return lorentz_point_from_vector(vector, "query");
    }
    if let Some(node_id) = request.query_node_id.as_deref() {
        if let Some(node) = index.nodes.iter().find(|node| node.node_id == node_id) {
            return Ok(node.point);
        }
        return Err(format!("missing Lorentz query node id: {node_id}"));
    }
    Ok(HyperboloidPoint::origin())
}

fn lorentz_point_from_vector(vector: &[f64], salt: &str) -> Result<HyperboloidPoint, String> {
    let mut tangent = [0.0f32; 4];
    for (index, value) in vector.iter().enumerate() {
        if value.is_finite() {
            tangent[index % 4] += (*value as f32).clamp(-1.0, 1.0);
        }
    }
    if tangent.iter().all(|value| value.abs() <= 1e-6) {
        let hash = stable_hash64(salt);
        for (index, slot) in tangent.iter_mut().enumerate() {
            let byte = ((hash >> (index * 13)) & 0xff) as f32;
            *slot = (byte / 255.0 - 0.5) * 0.1;
        }
    }
    let norm = tangent
        .iter()
        .map(|value| value * value)
        .sum::<f32>()
        .sqrt();
    if norm > 3.0 {
        for value in &mut tangent {
            *value = (*value / norm) * 3.0;
        }
    }
    HyperboloidPoint::from_tangent(tangent, 0.8).map_err(|error| error.to_string())
}

fn lorentz_tree_specs() -> [(&'static str, LorentzTreeKind, &'static str); 5] {
    [
        ("identity", LorentzTreeKind::Identity, "Identity"),
        (
            "documentStructure",
            LorentzTreeKind::DocumentStructure,
            "Document Structure",
        ),
        ("causal", LorentzTreeKind::Causal, "Causal"),
        ("temporal", LorentzTreeKind::Temporal, "Temporal"),
        ("evidence", LorentzTreeKind::Evidence, "Evidence"),
    ]
}

fn lorentz_kind_for_edge_type(edge_type: &str) -> Option<LorentzTreeKind> {
    let normalized = edge_type.to_ascii_lowercase();
    if normalized.contains("causal") || normalized.contains("cause") {
        Some(LorentzTreeKind::Causal)
    } else if normalized.contains("temporal")
        || normalized.contains("before")
        || normalized.contains("after")
        || normalized.contains("sequence")
    {
        Some(LorentzTreeKind::Temporal)
    } else if normalized.contains("evidence")
        || normalized.contains("support")
        || normalized.contains("provenance")
        || normalized.contains("claim")
    {
        Some(LorentzTreeKind::Evidence)
    } else {
        None
    }
}

fn parse_lorentz_tree_kind(value: &str) -> Option<LorentzTreeKind> {
    match normalize_contract_token(value).as_str() {
        "identity" => Some(LorentzTreeKind::Identity),
        "relationship" => Some(LorentzTreeKind::Relationship),
        "location" => Some(LorentzTreeKind::Location),
        "event" => Some(LorentzTreeKind::Event),
        "temporal" => Some(LorentzTreeKind::Temporal),
        "causal" => Some(LorentzTreeKind::Causal),
        "mechanical" => Some(LorentzTreeKind::Mechanical),
        "emotional" => Some(LorentzTreeKind::Emotional),
        "political" => Some(LorentzTreeKind::Political),
        "evidence" => Some(LorentzTreeKind::Evidence),
        "provenance" => Some(LorentzTreeKind::Provenance),
        "contradiction" => Some(LorentzTreeKind::Contradiction),
        "abstraction" => Some(LorentzTreeKind::Abstraction),
        "species" => Some(LorentzTreeKind::Species),
        "powersystem" => Some(LorentzTreeKind::PowerSystem),
        "documentstructure" => Some(LorentzTreeKind::DocumentStructure),
        _ => None,
    }
}

fn parse_lorentz_query_mode(value: &str) -> Option<LorentzQueryMode> {
    match normalize_contract_token(value).as_str() {
        "anchorsearch" => Some(LorentzQueryMode::AnchorSearch),
        "directlookup" => Some(LorentzQueryMode::DirectLookup),
        "hierarchicalexpansion" => Some(LorentzQueryMode::HierarchicalExpansion),
        "crosshierarchysynthesis" => Some(LorentzQueryMode::CrossHierarchySynthesis),
        "contradiction" => Some(LorentzQueryMode::Contradiction),
        _ => None,
    }
}

fn lorentz_kind_name(kind: LorentzTreeKind) -> &'static str {
    match kind {
        LorentzTreeKind::Identity => "identity",
        LorentzTreeKind::Relationship => "relationship",
        LorentzTreeKind::Location => "location",
        LorentzTreeKind::Event => "event",
        LorentzTreeKind::Temporal => "temporal",
        LorentzTreeKind::Causal => "causal",
        LorentzTreeKind::Mechanical => "mechanical",
        LorentzTreeKind::Emotional => "emotional",
        LorentzTreeKind::Political => "political",
        LorentzTreeKind::Evidence => "evidence",
        LorentzTreeKind::Provenance => "provenance",
        LorentzTreeKind::Contradiction => "contradiction",
        LorentzTreeKind::Abstraction => "abstraction",
        LorentzTreeKind::Species => "species",
        LorentzTreeKind::PowerSystem => "powerSystem",
        LorentzTreeKind::DocumentStructure => "documentStructure",
    }
}

fn normalize_contract_token(value: &str) -> String {
    value
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn stable_hash64<T: Hash + ?Sized>(value: &T) -> u64 {
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    value.hash(&mut hasher);
    hasher.finish()
}

impl IcoTopology {
    fn new(resolution: u32) -> Self {
        let mut cells = generate_ico_cells(resolution);
        let mut by_id = HashMap::<String, usize>::with_capacity(cells.len());
        let mut edge_to_cells = HashMap::<String, Vec<usize>>::with_capacity(cells.len() * 3);
        for (index, cell) in cells.iter().enumerate() {
            by_id.insert(cell.cell_id.clone(), index);
            for edge_key in &cell.edge_keys {
                edge_to_cells
                    .entry(edge_key.clone())
                    .or_default()
                    .push(index);
            }
        }
        for indexes in edge_to_cells.values() {
            for left in indexes {
                for right in indexes {
                    if left != right {
                        let neighbor = cells[*right].cell_id.clone();
                        cells[*left].neighbor_cell_ids.push(neighbor);
                    }
                }
            }
        }
        for cell in &mut cells {
            cell.neighbor_cell_ids.sort();
            cell.neighbor_cell_ids.dedup();
        }
        Self {
            resolution,
            cells,
            by_id,
        }
    }

    fn cell(&self, cell_id: &str) -> Option<&IcoCellInternal> {
        self.by_id
            .get(cell_id)
            .and_then(|index| self.cells.get(*index))
    }

    fn project(&self, direction: &[f64; 3]) -> IcoProjection {
        let mut best_index = 0usize;
        let mut best_dot = f64::NEG_INFINITY;
        let mut second_index = 0usize;
        let mut second_dot = f64::NEG_INFINITY;
        for (index, cell) in self.cells.iter().enumerate() {
            let score = dot3(direction, &cell.center);
            if score > best_dot {
                second_dot = best_dot;
                second_index = best_index;
                best_dot = score;
                best_index = index;
            } else if score > second_dot {
                second_dot = score;
                second_index = index;
            }
        }
        let best = &self.cells[best_index];
        let second = &self.cells[second_index];
        let gap = (best_dot - second_dot).max(0.0);
        let boundary_score = (1.0 - gap * 96.0).clamp(0.0, 1.0);
        let secondary_cell_ids = if boundary_score > 0.55 {
            vec![second.cell_id.clone()]
        } else {
            Vec::new()
        };
        IcoProjection {
            primary_cell_id: best.cell_id.clone(),
            secondary_cell_ids,
            center_vector: best.center,
            cell_distance: best_dot.clamp(-1.0, 1.0).acos(),
            boundary_score,
        }
    }

    fn neighbor_rings(&self, start: &str, max_ring: u32) -> Vec<Vec<String>> {
        let mut rings = vec![Vec::<String>::new(); max_ring as usize];
        let mut seen = HashSet::<String>::new();
        let mut queue = VecDeque::<(String, u32)>::new();
        seen.insert(start.to_owned());
        queue.push_back((start.to_owned(), 0));
        while let Some((cell_id, depth)) = queue.pop_front() {
            if depth >= max_ring {
                continue;
            }
            let Some(cell) = self.cell(&cell_id) else {
                continue;
            };
            for neighbor in &cell.neighbor_cell_ids {
                if !seen.insert(neighbor.clone()) {
                    continue;
                }
                let next_depth = depth + 1;
                rings[(next_depth - 1) as usize].push(neighbor.clone());
                queue.push_back((neighbor.clone(), next_depth));
            }
        }
        for ring in &mut rings {
            ring.sort();
        }
        rings
    }
}

fn generate_ico_cells(resolution: u32) -> Vec<IcoCellInternal> {
    let vertices = ico_vertices();
    let faces = ico_faces();
    let subdivisions = 1usize << resolution;
    let mut cells = Vec::<IcoCellInternal>::with_capacity(20 * subdivisions * subdivisions);
    for (face_index, [a, b, c]) in faces.iter().copied().enumerate() {
        let mut local_index = 0usize;
        for i in 0..subdivisions {
            for j in 0..(subdivisions - i) {
                let p0 =
                    subdivision_vertex(vertices[a], vertices[b], vertices[c], subdivisions, i, j);
                let p1 = subdivision_vertex(
                    vertices[a],
                    vertices[b],
                    vertices[c],
                    subdivisions,
                    i + 1,
                    j,
                );
                let p2 = subdivision_vertex(
                    vertices[a],
                    vertices[b],
                    vertices[c],
                    subdivisions,
                    i,
                    j + 1,
                );
                cells.push(make_ico_cell(
                    resolution,
                    face_index,
                    local_index,
                    p0,
                    p1,
                    p2,
                ));
                local_index += 1;
                if i + j + 1 < subdivisions {
                    let p3 = subdivision_vertex(
                        vertices[a],
                        vertices[b],
                        vertices[c],
                        subdivisions,
                        i + 1,
                        j + 1,
                    );
                    cells.push(make_ico_cell(
                        resolution,
                        face_index,
                        local_index,
                        p1,
                        p3,
                        p2,
                    ));
                    local_index += 1;
                }
            }
        }
    }
    cells
}

fn make_ico_cell(
    resolution: u32,
    face: usize,
    local_index: usize,
    a: [f64; 3],
    b: [f64; 3],
    c: [f64; 3],
) -> IcoCellInternal {
    let k0 = vertex_key(&a);
    let k1 = vertex_key(&b);
    let k2 = vertex_key(&c);
    IcoCellInternal {
        cell_id: format!("ico:{resolution}:{face}:{local_index}"),
        resolution,
        face,
        local_index,
        center: normalize3([a[0] + b[0] + c[0], a[1] + b[1] + c[1], a[2] + b[2] + c[2]]),
        vertex_keys: [k0.clone(), k1.clone(), k2.clone()],
        edge_keys: [edge_key(&k0, &k1), edge_key(&k1, &k2), edge_key(&k2, &k0)],
        neighbor_cell_ids: Vec::new(),
        area_weight: triangle_area(a, b, c),
    }
}

fn ico_vertices() -> Vec<[f64; 3]> {
    let phi = (1.0 + 5.0_f64.sqrt()) * 0.5;
    [
        [-1.0, phi, 0.0],
        [1.0, phi, 0.0],
        [-1.0, -phi, 0.0],
        [1.0, -phi, 0.0],
        [0.0, -1.0, phi],
        [0.0, 1.0, phi],
        [0.0, -1.0, -phi],
        [0.0, 1.0, -phi],
        [phi, 0.0, -1.0],
        [phi, 0.0, 1.0],
        [-phi, 0.0, -1.0],
        [-phi, 0.0, 1.0],
    ]
    .into_iter()
    .map(normalize3)
    .collect()
}

fn ico_faces() -> [[usize; 3]; 20] {
    [
        [0, 11, 5],
        [0, 5, 1],
        [0, 1, 7],
        [0, 7, 10],
        [0, 10, 11],
        [1, 5, 9],
        [5, 11, 4],
        [11, 10, 2],
        [10, 7, 6],
        [7, 1, 8],
        [3, 9, 4],
        [3, 4, 2],
        [3, 2, 6],
        [3, 6, 8],
        [3, 8, 9],
        [4, 9, 5],
        [2, 4, 11],
        [6, 2, 10],
        [8, 6, 7],
        [9, 8, 1],
    ]
}

fn subdivision_vertex(
    a: [f64; 3],
    b: [f64; 3],
    c: [f64; 3],
    n: usize,
    i: usize,
    j: usize,
) -> [f64; 3] {
    let nf = n as f64;
    let bi = i as f64 / nf;
    let cj = j as f64 / nf;
    let aw = 1.0 - bi - cj;
    normalize3([
        a[0] * aw + b[0] * bi + c[0] * cj,
        a[1] * aw + b[1] * bi + c[1] * cj,
        a[2] * aw + b[2] * bi + c[2] * cj,
    ])
}

fn build_desktop_cells(
    topology: &IcoTopology,
    assignments: &[HopfAnchorAssignment],
) -> Vec<DesktopIcoCell> {
    let mut anchors_by_cell = BTreeMap::<String, Vec<String>>::new();
    for assignment in assignments {
        anchors_by_cell
            .entry(assignment.cell_id.clone())
            .or_default()
            .push(assignment.anchor_id.clone());
    }
    anchors_by_cell
        .into_iter()
        .filter_map(|(cell_id, anchor_ids)| {
            let cell = topology.cell(&cell_id)?;
            Some(DesktopIcoCell {
                cell_id: cell.cell_id.clone(),
                resolution: cell.resolution,
                parent_cell_id: parent_cell_id(cell),
                children_cell_ids: Vec::new(),
                center_vector: cell.center,
                normal_vector: cell.center,
                neighbor_cell_ids: cell.neighbor_cell_ids.clone(),
                area_weight: cell.area_weight,
                density: anchor_ids.len() as f64 / cell.area_weight.max(1e-9),
                anchor_ids,
                geometry_version: HOPF_GEOMETRY_VERSION,
            })
        })
        .collect()
}

fn build_desktop_charts(
    topology: &IcoTopology,
    chart_topology: &IcoTopology,
    assignments: &[HopfAnchorAssignment],
) -> Vec<DesktopIcoChart> {
    let mut accumulators = BTreeMap::<String, ChartAccumulator>::new();
    for assignment in assignments {
        let chart_id = chart_record_id(&assignment.chart_id);
        let entry = accumulators.entry(chart_id).or_default();
        entry.member_cell_ids.insert(assignment.cell_id.clone());
        entry.anchor_ids.push(assignment.anchor_id.clone());
        *entry
            .dominant_contexts
            .entry(assignment.fiber_kind.clone())
            .or_default() += 1;
    }
    accumulators
        .into_iter()
        .map(|(chart_id, accumulator)| {
            let center_cell_id = chart_id.trim_start_matches("chart:").to_owned();
            let member_cell_ids = accumulator.member_cell_ids.into_iter().collect::<Vec<_>>();
            let member_set = member_cell_ids.iter().cloned().collect::<HashSet<_>>();
            let boundary_cells = member_cell_ids
                .iter()
                .filter(|cell_id| {
                    topology
                        .cell(cell_id)
                        .map(|cell| {
                            cell.neighbor_cell_ids
                                .iter()
                                .any(|neighbor| !member_set.contains(neighbor))
                        })
                        .unwrap_or(false)
                })
                .cloned()
                .collect::<Vec<_>>();
            let dominant_contexts = sorted_contexts(accumulator.dominant_contexts);
            let chart_area = chart_topology
                .cell(&center_cell_id)
                .map(|cell| cell.area_weight)
                .unwrap_or(1.0);
            DesktopIcoChart {
                chart_id,
                center_cell_id,
                member_cell_ids,
                resolution: HOPF_CHART_RESOLUTION,
                dominant_contexts,
                anchor_count: count_for_wire(accumulator.anchor_ids.len()),
                density: accumulator.anchor_ids.len() as f64 / chart_area.max(1e-9),
                boundary_cells,
                geometry_version: HOPF_GEOMETRY_VERSION,
            }
        })
        .collect()
}

fn build_desktop_seams(
    topology: &IcoTopology,
    assignments: &[HopfAnchorAssignment],
) -> Vec<DesktopIcoSeam> {
    let cell_to_chart = cell_to_chart_map(assignments);
    let occupied = cell_to_chart.keys().cloned().collect::<BTreeSet<_>>();
    let mut seams = Vec::<DesktopIcoSeam>::new();
    for cell_id in &occupied {
        let Some(cell) = topology.cell(cell_id) else {
            continue;
        };
        for neighbor_id in &cell.neighbor_cell_ids {
            if cell_id >= neighbor_id || !occupied.contains(neighbor_id) {
                continue;
            }
            let Some(neighbor) = topology.cell(neighbor_id) else {
                continue;
            };
            let chart_a = cell_to_chart.get(cell_id).cloned().unwrap_or_default();
            let chart_b = cell_to_chart.get(neighbor_id).cloned().unwrap_or_default();
            let normal_delta = (1.0 - dot3(&cell.center, &neighbor.center)).max(0.0);
            let same_chart = chart_a == chart_b;
            let seam_cost = if same_chart {
                0.08
            } else {
                0.24 + normal_delta * 2.4
            };
            seams.push(DesktopIcoSeam {
                from_cell: cell_id.clone(),
                to_cell: neighbor_id.clone(),
                shared_edge: shared_edge_vertices(cell, neighbor),
                normal_delta,
                chart_a,
                chart_b,
                seam_cost,
                compatibility_score: (1.0 / (1.0 + seam_cost)).clamp(0.0, 1.0),
                obstruction_count: 0,
                geometry_version: HOPF_GEOMETRY_VERSION,
            });
        }
    }
    seams
}

fn build_desktop_neighbor_rings(
    topology: &IcoTopology,
    assignments: &[HopfAnchorAssignment],
) -> Vec<DesktopIcoNeighborRings> {
    assignments
        .iter()
        .map(|assignment| assignment.cell_id.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .map(|cell_id| {
            let rings = topology.neighbor_rings(&cell_id, 3);
            DesktopIcoNeighborRings {
                cell_id,
                ring_1: rings.get(0).cloned().unwrap_or_default(),
                ring_2: rings.get(1).cloned().unwrap_or_default(),
                ring_3: rings.get(2).cloned().unwrap_or_default(),
                geometry_version: HOPF_GEOMETRY_VERSION,
            }
        })
        .collect()
}

fn build_desktop_cone_traces(
    topology: &IcoTopology,
    assignments: &[HopfAnchorAssignment],
) -> Vec<DesktopIcoConeTrace> {
    if assignments.is_empty() {
        return Vec::new();
    }
    let cell_counts = cell_counts(assignments);
    let Some(apex_cell) = cell_counts
        .iter()
        .max_by(|left, right| left.1.cmp(right.1).then_with(|| right.0.cmp(left.0)))
        .map(|(cell_id, _)| cell_id.clone())
    else {
        return Vec::new();
    };
    let axis_vector = normalize3(assignments.iter().fold(
        [0.0, 0.0, 0.0],
        |mut acc, assignment| {
            acc[0] += assignment.center_vector[0];
            acc[1] += assignment.center_vector[1];
            acc[2] += assignment.center_vector[2];
            acc
        },
    ));
    let Some(apex) = topology.cell(&apex_cell) else {
        return Vec::new();
    };
    let cell_to_chart = cell_to_chart_map(assignments);
    let rings = topology.neighbor_rings(&apex_cell, 3);
    let occupied = cell_counts.keys().cloned().collect::<HashSet<_>>();
    let mut ring_by_cell = HashMap::<String, u32>::new();
    ring_by_cell.insert(apex_cell.clone(), 0);
    for (index, ring) in rings.iter().enumerate() {
        for cell_id in ring {
            if occupied.contains(cell_id) {
                ring_by_cell.insert(cell_id.clone(), (index + 1) as u32);
            }
        }
    }
    let apex_chart = cell_to_chart.get(&apex_cell).cloned().unwrap_or_default();
    let mut steps = ring_by_cell
        .into_iter()
        .filter_map(|(cell_id, ring)| {
            let cell = topology.cell(&cell_id)?;
            let direction = if ring == 0 {
                axis_vector
            } else {
                normalize3([
                    cell.center[0] - apex.center[0],
                    cell.center[1] - apex.center[1],
                    cell.center[2] - apex.center[2],
                ])
            };
            let axis_alignment = if ring == 0 {
                1.0
            } else {
                dot3(&axis_vector, &direction)
            };
            let accepted = ring == 0 || axis_alignment >= HOPF_CONE_APERTURE_COS;
            let chart = cell_to_chart.get(&cell_id).cloned().unwrap_or_default();
            let chart_stitch_score = if chart == apex_chart { 1.0 } else { 0.62 };
            Some(DesktopIcoConeTraceStep {
                cell_id,
                neighbor_ring: ring,
                axis_alignment,
                aperture_threshold: HOPF_CONE_APERTURE_COS,
                chart_stitch_score,
                accepted,
                reason: if accepted {
                    "inside aperture and ring budget".to_owned()
                } else {
                    "outside cone aperture".to_owned()
                },
            })
        })
        .collect::<Vec<_>>();
    steps.sort_by(|left, right| {
        left.neighbor_ring
            .cmp(&right.neighbor_ring)
            .then_with(|| left.cell_id.cmp(&right.cell_id))
    });
    let accepted_cell_ids = steps
        .iter()
        .filter(|step| step.accepted)
        .map(|step| step.cell_id.clone())
        .collect::<Vec<_>>();
    let rejected_cell_ids = steps
        .iter()
        .filter(|step| !step.accepted)
        .map(|step| step.cell_id.clone())
        .collect::<Vec<_>>();
    vec![DesktopIcoConeTrace {
        cone_id: format!("cone:{HOPF_GEOMETRY_VERSION}:{apex_cell}"),
        apex_cell,
        axis_vector,
        aperture_cos: HOPF_CONE_APERTURE_COS,
        max_ring: 3,
        accepted_cell_ids,
        rejected_cell_ids,
        steps,
        geometry_version: HOPF_GEOMETRY_VERSION,
    }]
}

fn cell_counts(assignments: &[HopfAnchorAssignment]) -> BTreeMap<String, u32> {
    let mut counts = BTreeMap::<String, u32>::new();
    for assignment in assignments {
        *counts.entry(assignment.cell_id.clone()).or_default() += 1;
    }
    counts
}

fn cell_to_chart_map(assignments: &[HopfAnchorAssignment]) -> HashMap<String, String> {
    assignments
        .iter()
        .map(|assignment| {
            (
                assignment.cell_id.clone(),
                chart_record_id(&assignment.chart_id),
            )
        })
        .collect()
}

fn chart_record_id(cell_id: &str) -> String {
    format!("chart:{cell_id}")
}

fn sorted_contexts(contexts: BTreeMap<String, u32>) -> Vec<String> {
    let mut items = contexts.into_iter().collect::<Vec<_>>();
    items.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    items.into_iter().map(|(context, _)| context).collect()
}

fn parent_cell_id(cell: &IcoCellInternal) -> Option<String> {
    (cell.resolution > 0).then(|| {
        format!(
            "ico:{}:{}:{}",
            cell.resolution - 1,
            cell.face,
            cell.local_index / 4
        )
    })
}

fn shared_edge_vertices(left: &IcoCellInternal, right: &IcoCellInternal) -> Vec<String> {
    let right_vertices = right.vertex_keys.iter().collect::<HashSet<_>>();
    left.vertex_keys
        .iter()
        .filter(|key| right_vertices.contains(*key))
        .cloned()
        .collect()
}

fn project_vector_to_direction(vector: &[f64], seed_token: &str) -> [f64; 3] {
    let phase = hash_unit(seed_token);
    let mut raw = [0.0, 0.0, 0.0];
    for (index, value) in vector.iter().copied().enumerate() {
        if !value.is_finite() {
            continue;
        }
        let n = (index + 1) as f64;
        raw[0] += value * (n * 12.9898 + phase * TAU_F64).sin();
        raw[1] += value * (n * 78.233 + phase * 3.883_222_077_450_933).cos();
        raw[2] += value * (n * 37.719 + phase * 2.399_963_229_728_653).sin();
    }
    let normalized = normalize3(raw);
    if norm3(&normalized) > 0.0 {
        normalized
    } else {
        stable_direction(seed_token)
    }
}

fn hopf_phase_for_kind(fiber_kind: &str, id: &str, index: usize) -> f64 {
    let base = match fiber_kind {
        "relationship" | "emotional" => 0.18,
        "location" => 0.30,
        "event" | "document_structure" => 0.41,
        "temporal" => 0.53,
        "causal" | "contradiction" => 0.64,
        "evidence" | "provenance" => 0.75,
        "political" => 0.84,
        "mechanical" | "power_system" => 0.92,
        _ => 0.08,
    };
    (base + (hash_unit(&format!("{fiber_kind}:{id}:{index}")) - 0.5) * 0.018).rem_euclid(1.0)
}

fn stable_direction(seed_token: &str) -> [f64; 3] {
    let seed = hash_unit(seed_token);
    let z = 1.0 - seed * 2.0;
    let radial = (1.0 - z * z).max(0.0).sqrt();
    let theta = seed * TAU_F64 * 1.618_033_988_75;
    [theta.cos() * radial, z, theta.sin() * radial]
}

fn hash_unit(token: &str) -> f64 {
    hash_u32(token) as f64 / u32::MAX as f64
}

fn hash_u32(token: &str) -> u32 {
    let mut hash = 2_166_136_261_u32;
    for byte in token.as_bytes() {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(16_777_619);
    }
    hash
}

fn vertex_key(vector: &[f64; 3]) -> String {
    format!(
        "{}:{}:{}",
        (vector[0] * 1_000_000_000.0).round() as i64,
        (vector[1] * 1_000_000_000.0).round() as i64,
        (vector[2] * 1_000_000_000.0).round() as i64,
    )
}

fn edge_key(left: &str, right: &str) -> String {
    if left <= right {
        format!("{left}|{right}")
    } else {
        format!("{right}|{left}")
    }
}

fn triangle_area(a: [f64; 3], b: [f64; 3], c: [f64; 3]) -> f64 {
    let ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    norm3(&cross3(&ab, &ac)) * 0.5
}

fn cross3(left: &[f64; 3], right: &[f64; 3]) -> [f64; 3] {
    [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]
}

fn dot3(left: &[f64; 3], right: &[f64; 3]) -> f64 {
    left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
}

fn norm3(vector: &[f64; 3]) -> f64 {
    dot3(vector, vector).sqrt()
}

fn normalize3(vector: [f64; 3]) -> [f64; 3] {
    let norm = norm3(&vector);
    if !norm.is_finite() || norm <= 1e-12 {
        [0.0, 1.0, 0.0]
    } else {
        [vector[0] / norm, vector[1] / norm, vector[2] / norm]
    }
}

fn semantic_node_matches_scope(
    document_id: &str,
    narrative_id: &str,
    folder_id: &str,
    scope: Option<&Value>,
) -> bool {
    let Some(scope) = scope else {
        return true;
    };
    let note_id = str_field(scope, "note_id", "noteId");
    if !note_id.is_empty() && document_id != note_id {
        return false;
    }
    let narrative = str_field(scope, "narrative_id", "narrativeId");
    if !narrative.is_empty() && narrative_id != narrative {
        return false;
    }
    let folder = str_field(scope, "folder_id", "folderId");
    if !folder.is_empty() && folder_id != folder {
        return false;
    }
    true
}

fn str_field<'a>(row: &'a Value, snake: &str, camel: &str) -> &'a str {
    row.get(snake)
        .or_else(|| row.get(camel))
        .and_then(Value::as_str)
        .unwrap_or_default()
}

fn optional_string(value: &str) -> Option<String> {
    (!value.is_empty()).then(|| value.to_owned())
}

fn vector_field(row: &Value, key: &str) -> Vec<f64> {
    row.get(key)
        .and_then(Value::as_array)
        .map(|values| values.iter().filter_map(Value::as_f64).collect())
        .unwrap_or_default()
}

fn evidence_preview(row: &Value) -> String {
    row.get("evidence_refs")
        .or_else(|| row.get("evidenceRefs"))
        .and_then(Value::as_array)
        .map(|refs| {
            refs.iter()
                .take(3)
                .map(|value| {
                    value
                        .as_str()
                        .map(str::to_owned)
                        .unwrap_or_else(|| value.to_string())
                })
                .collect::<Vec<_>>()
                .join(" · ")
        })
        .unwrap_or_default()
}

fn semantic_node_label(id: &str) -> String {
    let mut label = id
        .trim_start_matches("entity::")
        .trim_start_matches("event::")
        .trim_start_matches("doc::")
        .trim_start_matches("atlas:")
        .replace(['-', '_', ':'], " ")
        .trim()
        .to_owned();
    if label.len() > 48 {
        label.truncate(48);
    }
    if label.is_empty() {
        id.to_owned()
    } else {
        label
    }
}

fn candidate_confidence(row: &Value) -> f64 {
    let attributes = row.get("attributes").and_then(Value::as_object);
    let attr_score = attributes
        .and_then(|attrs| attrs.get("score"))
        .and_then(Value::as_f64);
    let graph_score = attributes
        .and_then(|attrs| attrs.get("graph"))
        .and_then(Value::as_object)
        .and_then(|graph| graph.get("confidence"))
        .and_then(Value::as_f64);
    attr_score
        .or(graph_score)
        .or_else(|| {
            row.get("weight")
                .and_then(Value::as_f64)
                .map(|weight| weight / 1000.0)
        })
        .filter(|score| score.is_finite() && *score > 0.0)
        .unwrap_or(0.35)
}

fn infer_hopf_fiber_kind(node: &DesktopManifoldNode) -> &'static str {
    let kind = node.kind.as_str();
    let source_type = node.source_type.as_str();
    let label = node.label.as_str();
    let preview = node.preview.as_str();
    if contains_any_ci(
        [kind, source_type, label, preview],
        &["caus", "because", "effect", "echo"],
    ) {
        "causal"
    } else if contains_any_ci(
        [kind, source_type, label, preview],
        &["time", "temporal", "timeline"],
    ) {
        "temporal"
    } else if contains_any_ci(
        [kind, source_type, label, preview],
        &["evidence", "leaf", "document", "log"],
    ) {
        "evidence"
    } else if contains_any_ci(
        [kind, source_type, label, preview],
        &["power", "veir", "domain"],
    ) {
        "power_system"
    } else if contains_any_ci([kind, source_type, label, preview], &["politic", "halcyon"]) {
        "political"
    } else if contains_any_ci(
        [kind, source_type, label, preview],
        &["location", "city", "tower"],
    ) {
        "location"
    } else {
        "identity"
    }
}

fn fiber_vector(values: &[f64], fiber_kind: &str, index: usize) -> Vec<f64> {
    let seed = hash_unit_parts(fiber_kind, index);
    let mut mixed = Vec::with_capacity(values.len());
    for (dim, value) in values.iter().enumerate() {
        let wobble = (((dim + 1) as f64) * 12.9898 + seed * std::f64::consts::TAU).sin() * 0.16;
        mixed.push(value * 0.88 + wobble);
    }
    normalize_f64(&mut mixed);
    mixed
}

fn contains_any_ci<const N: usize>(haystacks: [&str; N], needles: &[&str]) -> bool {
    haystacks.iter().any(|haystack| {
        needles
            .iter()
            .any(|needle| contains_ascii_case_insensitive(haystack, needle))
    })
}

fn contains_ascii_case_insensitive(haystack: &str, needle: &str) -> bool {
    if needle.is_empty() {
        return true;
    }
    haystack
        .as_bytes()
        .windows(needle.len())
        .any(|window| window.eq_ignore_ascii_case(needle.as_bytes()))
}

fn normalize_f64(values: &mut [f64]) {
    let norm = values.iter().map(|value| value * value).sum::<f64>().sqrt();
    if !norm.is_finite() || norm <= 1e-8 {
        values.fill(0.0);
        if let Some(first) = values.first_mut() {
            *first = 1.0;
        }
        return;
    }
    for value in values {
        *value /= norm;
    }
}

fn hash_unit_parts(kind: &str, index: usize) -> f64 {
    let mut hash = 2166136261u32;
    for byte in kind.as_bytes() {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(16777619);
    }
    for byte in index.to_le_bytes() {
        hash ^= u32::from(byte);
        hash = hash.wrapping_mul(16777619);
    }
    f64::from(hash) / f64::from(u32::MAX)
}

fn now_millis_for_snapshot() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}

fn parse_json<T: DeserializeOwned>(json: &str) -> Result<T, String> {
    serde_json::from_str(json).map_err(|error| format!("invalid Phoenix JSON payload: {error}"))
}

fn serialize_json<T: Serialize>(value: &T) -> Result<String, String> {
    serde_json::to_string(value)
        .map_err(|error| format!("failed to serialize Phoenix result: {error}"))
}

fn compressed_json_payload<T: Serialize>(
    value: &T,
    schema_version: &str,
    source_schema_version: &str,
) -> Result<Value, String> {
    let raw = serde_json::to_vec(value)
        .map_err(|error| format!("failed to serialize compressed Phoenix payload: {error}"))?;
    let mut encoder = GzEncoder::new(Vec::with_capacity(raw.len() / 4), Compression::fast());
    encoder
        .write_all(&raw)
        .map_err(|error| format!("failed to compress Phoenix payload: {error}"))?;
    let compressed = encoder
        .finish()
        .map_err(|error| format!("failed to finish Phoenix payload compression: {error}"))?;
    Ok(json!({
        "schemaVersion": schema_version,
        "sourceSchemaVersion": source_schema_version,
        "encoding": "gzip+base64",
        "rawBytes": raw.len(),
        "compressedBytes": compressed.len(),
        "payload": BASE64_STANDARD.encode(compressed),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktop_runtime_defaults_to_native_graph_lane() {
        let request = build_init_request(&DesktopInitRequest {
            force_reset: false,
            storage_path: None,
            storage: None,
        });

        assert_eq!(request.config.target, RuntimeTarget::Native);
        assert_eq!(request.config.storage, StorageMode::NativeLocal);
        assert!(!request.config.feature_flags.graptor);
        assert!(!request.config.feature_flags.gldr);
        assert!(request.config.feature_flags.candidate_graph);
    }

    #[test]
    fn desktop_runtime_info_reports_native_target_by_default() {
        let info = desktop_runtime_info(None, None);

        assert_eq!(info.target, "native");
        assert_eq!(info.storage, "nativeLocal");
        assert!(!info.feature_flags.graptor);
        assert!(!info.feature_flags.gldr);
    }

    #[test]
    fn native_chunk_offsets_are_utf16_safe_for_frontend_ranges() {
        let text = "A😀B. Café follows.";
        let chunks = vec![Chunk {
            start: "A😀".len(),
            end: text.len(),
        }];
        let offsets = utf16_offsets_for_chunks(text, &chunks);

        assert_eq!(offsets.get(&chunks[0].start), Some(&3));
        assert_eq!(offsets.get(&chunks[0].end), Some(&19));
    }

    #[test]
    fn hopf_ico_cell_ids_are_deterministic() {
        let first = IcoTopology::new(2);
        let second = IcoTopology::new(2);

        assert_eq!(first.cells.len(), 320);
        assert_eq!(first.cells.len(), second.cells.len());
        for (left, right) in first.cells.iter().zip(second.cells.iter()) {
            assert_eq!(left.cell_id, right.cell_id);
            assert_eq!(left.neighbor_cell_ids, right.neighbor_cell_ids);
        }
    }

    #[test]
    fn hopf_ico_neighbor_graph_is_symmetric() {
        let topology = IcoTopology::new(1);

        for cell in &topology.cells {
            for neighbor_id in &cell.neighbor_cell_ids {
                let neighbor = topology.cell(neighbor_id).expect("neighbor exists");
                assert!(neighbor.neighbor_cell_ids.contains(&cell.cell_id));
            }
        }
    }

    #[test]
    fn graph_rebuild_scoped_snapshot_payload_decodes_compressed_json() {
        let raw = json!({
            "schemaVersion": "phoenix-graph-rebuild/v1",
            "embeddingTargets": [],
        });
        let raw_json = serde_json::to_vec(&raw).unwrap();
        let mut encoder = GzEncoder::new(Vec::new(), Compression::fast());
        encoder.write_all(&raw_json).unwrap();
        let compressed = encoder.finish().unwrap();
        let envelope = json!({
            "schemaVersion": GRAPH_REBUILD_COMPRESSED_JSON_SCHEMA,
            "sourceSchemaVersion": "phoenix-graph-rebuild/v1",
            "encoding": "gzip+base64",
            "rawChars": raw_json.len(),
            "compressedBytes": compressed.len(),
            "payload": BASE64_STANDARD.encode(compressed),
        });

        let decoded = decode_graph_rebuild_scoped_payload(&envelope.to_string()).unwrap();

        assert_eq!(
            decoded.get("schemaVersion").and_then(Value::as_str),
            Some("phoenix-graph-rebuild/v1")
        );
    }

    #[test]
    fn graph_rebuild_scoped_snapshot_value_builds_packet_input() {
        let snapshot = json!({
            "schemaVersion": "phoenix-graph-rebuild/v1",
            "embeddingTargets": [
                {
                    "id": "embed:document:note-1",
                    "kind": "document",
                    "label": "Note 1",
                    "lane": "document_spine",
                    "evidenceIds": []
                },
                {
                    "id": "embed:chunk:note-1:0",
                    "kind": "chunk",
                    "label": "Chunk 1",
                    "lane": "chunk_spine",
                    "parentIds": ["embed:document:note-1"]
                },
                {
                    "id": "embed:event:event-a",
                    "kind": "event",
                    "sourceId": "event-a",
                    "label": "Cause event",
                    "lane": "event_identity",
                    "noteId": "note-1",
                    "chunkId": "note-1:0",
                    "parentIds": ["embed:chunk:note-1:0"]
                },
                {
                    "id": "embed:event:event-b",
                    "kind": "event",
                    "sourceId": "event-b",
                    "label": "Outcome event",
                    "lane": "event_identity",
                    "noteId": "note-1",
                    "chunkId": "note-1:0",
                    "parentIds": ["embed:chunk:note-1:0"]
                },
                {
                    "id": "embed:causalFact:cause-1",
                    "kind": "causalFact",
                    "sourceId": "cause-1",
                    "label": "causes_or_explains",
                    "lane": "causal_fact",
                    "noteId": "note-1",
                    "parentIds": [
                        "embed:structure-root:note-1:causal",
                        "embed:event:event-a",
                        "embed:event:event-b"
                    ]
                }
            ],
            "embeddingGraphPostProcess": {
                "backboneEdges": [
                    {
                        "id": "edge:1",
                        "sourceTargetId": "embed:document:note-1",
                        "targetTargetId": "embed:chunk:note-1:0",
                        "role": "hierarchy",
                        "score": 0.91
                    },
                    {
                        "id": "edge:dropped",
                        "sourceTargetId": "missing",
                        "targetTargetId": "embed:chunk:note-1:0",
                        "role": "hierarchy",
                        "score": 0.91
                    }
                ],
                "bridgeEdges": []
            }
        });

        let input = graph_scene_packet_input_from_rebuild_snapshot_value(
            &snapshot,
            "scopedSnapshot".to_owned(),
            "siegel".to_owned(),
            "siegelFinsler".to_owned(),
            "embeddings".to_owned(),
            4096,
            GraphScenePacketSettings::default(),
        )
        .unwrap();

        assert_eq!(input.nodes.len(), 5);
        assert_eq!(input.edges.len(), 1);
        assert_eq!(input.nodes[0].source_type, "root");
        assert_eq!(input.nodes[1].source_type, "chunk");
        let causal_hint = input.nodes[4]
            .hierarchy_hint
            .as_ref()
            .expect("causal hierarchy hint");
        assert_eq!(causal_hint.cap_id, "event:event-b:causal");
        assert_eq!(
            causal_hint.parent_node_id.as_deref(),
            Some("embed:event:event-b")
        );
        assert_eq!(causal_hint.shell_radius, 1.14);
    }
}

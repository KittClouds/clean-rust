use std::path::PathBuf;

use phoenix_analytics::TextAnalytics;
use phoenix_runtime::PhoenixRuntime;
pub use phoenix_runtime::SnapshotPartition;
use phoenix_store_native_core::{SnapshotEnvelope, StoreError};
use phoenix_types::{
    AnalyzeTextRequest, AtlasRichScanRequest, AtlasRichScanResult, CommitRequest, CommitResult,
    CreateSessionRequest, GraphDeltaRequest, GraphDeltaResult, IngestRequest, IngestResult,
    PhoenixBootSnapshotRows, QueryRequest, QueryResult, RebuildRequest, RebuildResult,
    RuntimeConfig, RuntimeInitRequest, RuntimeInitResult, ScanArtifact, ScanRequest, SessionRecord,
    SessionState, SessionStateRequest, SessionStats, SessionStatsRequest, StoreCommandRequest,
    StoreCommandResult, StructureArtifact, StructureRequest,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, thiserror::Error)]
pub enum PhoenixNativeError {
    #[error("native runtime is not open")]
    RuntimeNotOpen,
    #[error(transparent)]
    Store(#[from] StoreError),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PhoenixNativeConfig {
    pub runtime: RuntimeConfig,
    pub storage_path: Option<PathBuf>,
}

impl Default for PhoenixNativeConfig {
    fn default() -> Self {
        Self {
            runtime: RuntimeConfig::default(),
            storage_path: None,
        }
    }
}

impl PhoenixNativeConfig {
    pub fn from_init_request(request: &RuntimeInitRequest) -> Self {
        Self {
            runtime: request.config.clone(),
            storage_path: request.storage_path.clone().map(PathBuf::from),
        }
    }

    pub fn to_init_request(&self, force_reset: bool) -> RuntimeInitRequest {
        RuntimeInitRequest {
            config: self.runtime.clone(),
            storage_path: self
                .storage_path
                .as_ref()
                .map(|path| path.to_string_lossy().into_owned()),
            force_reset,
        }
    }
}

pub struct PhoenixNativeRuntime {
    config: PhoenixNativeConfig,
    runtime: PhoenixRuntime,
}

impl PhoenixNativeRuntime {
    pub fn open(config: PhoenixNativeConfig) -> Result<Self, StoreError> {
        let runtime = PhoenixRuntime::open(config.runtime.clone(), config.storage_path.clone())?;
        Ok(Self { config, runtime })
    }

    pub fn from_init_request(request: RuntimeInitRequest) -> Result<Self, StoreError> {
        Self::open(PhoenixNativeConfig::from_init_request(&request))
    }

    pub fn config(&self) -> &PhoenixNativeConfig {
        &self.config
    }

    pub fn runtime(&self) -> &PhoenixRuntime {
        &self.runtime
    }

    pub fn init(&self) -> Result<RuntimeInitResult, StoreError> {
        self.runtime.init()
    }

    pub fn create_session(
        &self,
        request: CreateSessionRequest,
    ) -> Result<SessionRecord, StoreError> {
        self.runtime.create_session(request)
    }

    pub fn ingest(&self, request: IngestRequest) -> Result<IngestResult, StoreError> {
        self.runtime.ingest(request)
    }

    pub fn query(&self, request: QueryRequest) -> Result<QueryResult, StoreError> {
        self.runtime.query(request)
    }

    pub fn commit(&self, request: CommitRequest) -> Result<CommitResult, StoreError> {
        self.runtime.commit(request)
    }

    pub fn rebuild(&self, request: RebuildRequest) -> Result<RebuildResult, StoreError> {
        self.runtime.rebuild(request)
    }

    pub fn scan(&self, request: ScanRequest) -> ScanArtifact {
        self.runtime.scan_text(request)
    }

    pub fn atlas_rich_scan(
        &self,
        request: AtlasRichScanRequest,
    ) -> Result<AtlasRichScanResult, StoreError> {
        self.runtime.atlas_rich_scan(request)
    }

    pub fn build_structure(&self, request: StructureRequest) -> StructureArtifact {
        self.runtime.build_structure(request)
    }

    pub fn analyze_text(&self, request: AnalyzeTextRequest) -> TextAnalytics {
        self.runtime.analyze_text(&request.text)
    }

    pub fn graph_delta(&self, request: GraphDeltaRequest) -> Result<GraphDeltaResult, StoreError> {
        self.runtime.graph_delta(request)
    }

    pub fn session_state(&self, request: SessionStateRequest) -> Result<SessionState, StoreError> {
        self.runtime.session_state(&request.session_id)
    }

    pub fn session_stats(&self, request: SessionStatsRequest) -> Result<SessionStats, StoreError> {
        self.runtime.session_stats(&request.session_id)
    }

    pub fn export_snapshot(&self) -> Result<Vec<u8>, StoreError> {
        self.runtime.export_snapshot()
    }

    pub fn export_snapshot_partition(
        &self,
        partition: SnapshotPartition,
    ) -> Result<Vec<u8>, StoreError> {
        self.runtime.export_snapshot_partition(partition)
    }

    pub fn import_snapshot(&self, bytes: &[u8]) -> Result<SnapshotEnvelope, StoreError> {
        self.runtime.import_snapshot(bytes)
    }

    pub fn import_snapshot_cold(&self, bytes: &[u8]) -> Result<SnapshotEnvelope, StoreError> {
        self.runtime.import_snapshot_cold(bytes)
    }

    pub fn store_command(
        &self,
        request: StoreCommandRequest,
    ) -> Result<StoreCommandResult, StoreError> {
        self.runtime.store_command(request)
    }

    pub fn boot_snapshot_rows(&self) -> Result<PhoenixBootSnapshotRows, StoreError> {
        self.runtime.boot_snapshot_rows()
    }
}

#[derive(Default)]
pub struct PhoenixNativeHost {
    runtime: Option<PhoenixNativeRuntime>,
}

impl PhoenixNativeHost {
    pub fn is_open(&self) -> bool {
        self.runtime.is_some()
    }

    pub fn config(&self) -> Option<&PhoenixNativeConfig> {
        self.runtime.as_ref().map(PhoenixNativeRuntime::config)
    }

    pub fn open(
        &mut self,
        request: RuntimeInitRequest,
    ) -> Result<RuntimeInitResult, PhoenixNativeError> {
        let runtime = PhoenixNativeRuntime::from_init_request(request)?;
        let result = runtime.init()?;
        self.runtime = Some(runtime);
        Ok(result)
    }

    pub fn open_default(&mut self) -> Result<RuntimeInitResult, PhoenixNativeError> {
        self.open(RuntimeInitRequest {
            config: RuntimeConfig::default(),
            storage_path: None,
            force_reset: false,
        })
    }

    pub fn close(&mut self) -> bool {
        self.runtime.take().is_some()
    }

    pub fn runtime(&self) -> Result<&PhoenixNativeRuntime, PhoenixNativeError> {
        self.runtime
            .as_ref()
            .ok_or(PhoenixNativeError::RuntimeNotOpen)
    }

    pub fn create_session(
        &self,
        request: CreateSessionRequest,
    ) -> Result<SessionRecord, PhoenixNativeError> {
        Ok(self.runtime()?.create_session(request)?)
    }

    pub fn ingest(&self, request: IngestRequest) -> Result<IngestResult, PhoenixNativeError> {
        Ok(self.runtime()?.ingest(request)?)
    }

    pub fn query(&self, request: QueryRequest) -> Result<QueryResult, PhoenixNativeError> {
        Ok(self.runtime()?.query(request)?)
    }

    pub fn commit(&self, request: CommitRequest) -> Result<CommitResult, PhoenixNativeError> {
        Ok(self.runtime()?.commit(request)?)
    }

    pub fn rebuild(&self, request: RebuildRequest) -> Result<RebuildResult, PhoenixNativeError> {
        Ok(self.runtime()?.rebuild(request)?)
    }

    pub fn scan(&self, request: ScanRequest) -> Result<ScanArtifact, PhoenixNativeError> {
        Ok(self.runtime()?.scan(request))
    }

    pub fn atlas_rich_scan(
        &self,
        request: AtlasRichScanRequest,
    ) -> Result<AtlasRichScanResult, PhoenixNativeError> {
        Ok(self.runtime()?.atlas_rich_scan(request)?)
    }

    pub fn build_structure(
        &self,
        request: StructureRequest,
    ) -> Result<StructureArtifact, PhoenixNativeError> {
        Ok(self.runtime()?.build_structure(request))
    }

    pub fn analyze_text(
        &self,
        request: AnalyzeTextRequest,
    ) -> Result<TextAnalytics, PhoenixNativeError> {
        Ok(self.runtime()?.analyze_text(request))
    }

    pub fn graph_delta(
        &self,
        request: GraphDeltaRequest,
    ) -> Result<GraphDeltaResult, PhoenixNativeError> {
        Ok(self.runtime()?.graph_delta(request)?)
    }

    pub fn session_state(
        &self,
        request: SessionStateRequest,
    ) -> Result<SessionState, PhoenixNativeError> {
        Ok(self.runtime()?.session_state(request)?)
    }

    pub fn session_stats(
        &self,
        request: SessionStatsRequest,
    ) -> Result<SessionStats, PhoenixNativeError> {
        Ok(self.runtime()?.session_stats(request)?)
    }

    pub fn export_snapshot(&self) -> Result<Vec<u8>, PhoenixNativeError> {
        Ok(self.runtime()?.export_snapshot()?)
    }

    pub fn export_snapshot_partition(
        &self,
        partition: SnapshotPartition,
    ) -> Result<Vec<u8>, PhoenixNativeError> {
        Ok(self.runtime()?.export_snapshot_partition(partition)?)
    }

    pub fn import_snapshot(&self, bytes: &[u8]) -> Result<SnapshotEnvelope, PhoenixNativeError> {
        Ok(self.runtime()?.import_snapshot(bytes)?)
    }

    pub fn import_snapshot_cold(
        &self,
        bytes: &[u8],
    ) -> Result<SnapshotEnvelope, PhoenixNativeError> {
        Ok(self.runtime()?.import_snapshot_cold(bytes)?)
    }

    pub fn store_command(
        &self,
        request: StoreCommandRequest,
    ) -> Result<StoreCommandResult, PhoenixNativeError> {
        Ok(self.runtime()?.store_command(request)?)
    }

    pub fn boot_snapshot_rows(&self) -> Result<PhoenixBootSnapshotRows, PhoenixNativeError> {
        Ok(self.runtime()?.boot_snapshot_rows()?)
    }
}

pub fn runtime_banner() -> &'static str {
    "phoenix-native foundation ready"
}

#[cfg(test)]
mod tests {
    use super::*;
    use phoenix_types::{
        CreateSessionRequest, GraphDeltaRequest, IngestDocument, IngestRequest, QueryRequest,
        QueryTarget, RuntimeTarget, ScopeKey, SessionId, StorageMode, StoreCommandRequest,
    };

    #[test]
    fn native_banner_is_stable() {
        assert_eq!(runtime_banner(), "phoenix-native foundation ready");
    }

    #[test]
    fn host_opens_default_runtime() {
        let mut host = PhoenixNativeHost::default();
        let result = host.open_default().expect("open default runtime");

        assert!(result.ready);
        assert!(host.is_open());
        assert_eq!(
            host.config().expect("config").runtime.target,
            RuntimeTarget::Native
        );
    }

    #[test]
    fn host_can_ingest_after_open() {
        let mut host = PhoenixNativeHost::default();
        host.open(RuntimeInitRequest {
            config: RuntimeConfig {
                target: RuntimeTarget::Native,
                storage: StorageMode::NativeEphemeral,
                ..RuntimeConfig::default()
            },
            storage_path: None,
            force_reset: false,
        })
        .expect("open runtime");

        let session = host
            .create_session(CreateSessionRequest {
                session_id: Some(SessionId("native-test-session".to_owned())),
                label: "Native host test".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("create session");

        let ingest = host
            .ingest(IngestRequest {
                session_id: Some(session.session_id.clone()),
                documents: vec![IngestDocument {
                    document_id: "doc-1".into(),
                    note_id: Some("note-1".into()),
                    title: "Doc".to_owned(),
                    text: "Ryan met Bakuto in the hall.".to_owned(),
                    scope: ScopeKey::default(),
                }],
                commit: false,
            })
            .expect("ingest");

        assert_eq!(ingest.document_count, 1);
    }

    #[test]
    fn host_boot_snapshot_rows_include_notes_and_entities() {
        let mut host = PhoenixNativeHost::default();
        host.open(RuntimeInitRequest {
            config: RuntimeConfig {
                target: RuntimeTarget::Native,
                storage: StorageMode::NativeEphemeral,
                ..RuntimeConfig::default()
            },
            storage_path: None,
            force_reset: false,
        })
        .expect("open runtime");

        host.store_command(StoreCommandRequest {
            command: "note:upsert".to_owned(),
            payload: serde_json::json!({
                "row": {
                    "id": "note-event",
                    "version": 1,
                    "world_id": "world",
                    "title": "Bellfall",
                    "content": "Aella reached the lantern tower.",
                    "markdown_content": "Aella reached the lantern tower.",
                    "folder_id": "folder-event",
                    "entity_kind": "EVENT",
                    "entity_subtype": null,
                    "is_entity": true,
                    "is_pinned": false,
                    "favorite": false,
                    "owner_id": null,
                    "narrative_id": "narrative",
                    "order": 0,
                    "created_at": 1,
                    "updated_at": 1,
                    "valid_from": 1,
                    "valid_to": null,
                    "is_current": true,
                    "change_reason": null
                }
            }),
        })
        .expect("upsert note");

        host.store_command(StoreCommandRequest {
            command: "relation:upsert".to_owned(),
            payload: serde_json::json!({
                "relation": "entities",
                "row": {
                    "id": "entity-aella",
                    "label": "Aella",
                    "kind": "CHARACTER",
                    "subtype": null,
                    "aliases": [],
                    "first_note": "note-event",
                    "total_mentions": 1,
                    "narrative_id": "narrative",
                    "created_by": "user",
                    "created_at": 1,
                    "updated_at": 1
                }
            }),
        })
        .expect("upsert entity");

        let snapshot = host.boot_snapshot_rows().expect("boot snapshot");

        assert_eq!(snapshot.note_headers.len(), 1);
        assert!(!snapshot.entities.is_empty());
        assert!(snapshot.edges.is_empty());
        assert!(snapshot
            .note_headers
            .iter()
            .any(|row| row.get("id").and_then(serde_json::Value::as_str) == Some("note-event")));
    }

    #[test]
    fn host_cold_import_preserves_lazy_query_and_graph_delta() {
        let mut host = PhoenixNativeHost::default();
        host.open(RuntimeInitRequest {
            config: RuntimeConfig {
                target: RuntimeTarget::Native,
                storage: StorageMode::NativeEphemeral,
                ..RuntimeConfig::default()
            },
            storage_path: None,
            force_reset: false,
        })
        .expect("open source runtime");

        let session = host
            .create_session(CreateSessionRequest {
                session_id: Some(SessionId("cold-import-session".to_owned())),
                label: "Cold Import".to_owned(),
                scope: ScopeKey::default(),
            })
            .expect("create session");
        host.ingest(IngestRequest {
            session_id: Some(session.session_id.clone()),
            documents: vec![IngestDocument {
                document_id: "cold-import-doc".into(),
                note_id: None,
                title: "Cold Import Doc".to_owned(),
                text: "Ryan mapped the harbor before dawn.".to_owned(),
                scope: ScopeKey::default(),
            }],
            commit: true,
        })
        .expect("ingest source");
        host.rebuild(RebuildRequest::default())
            .expect("rebuild source graph");
        let snapshot = host.export_snapshot().expect("export snapshot");

        let mut restored = PhoenixNativeHost::default();
        restored
            .open(RuntimeInitRequest {
                config: RuntimeConfig {
                    target: RuntimeTarget::Native,
                    storage: StorageMode::NativeEphemeral,
                    ..RuntimeConfig::default()
                },
                storage_path: None,
                force_reset: false,
            })
            .expect("open restored runtime");
        restored
            .import_snapshot_cold(&snapshot)
            .expect("cold import snapshot");

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
            .expect("lazy query after cold import");
        let delta = restored
            .graph_delta(GraphDeltaRequest {
                session_id: session.session_id,
                scope: ScopeKey::default(),
                changed_documents: Vec::new(),
                limit: None,
                since_commit: None,
                include_candidate_graph: false,
            })
            .expect("lazy graph delta after cold import");

        assert!(!query.chunk_hits.is_empty());
        assert!(!query.node_hits.is_empty());
        assert_eq!(delta.session_id.0, "cold-import-session");
    }
}

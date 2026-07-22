use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::graph_run_store::{
    atomic_json, load_immutable_artifact, load_manifest_for_scope, load_section,
    persist_immutable_artifact, scope_key, section_blob_exists, section_identity,
    DurableGraphRunManifest,
};

#[path = "graph_force_rebuild_v2_authority_packet.rs"]
mod authority_packet;

pub(crate) const CONTRACT_VERSION: &str = "phoenix-verified-force/v2";
pub(crate) const PATH_ID: &str = "native_verified_force_v2";
const REQUIRED_SECTIONS: [&str; 8] = [
    "bridge",
    "continuity",
    "governance",
    "hyperedges",
    "metadata",
    "promotion",
    "retrieval",
    "siegel",
];
const AUTHORITY_NAMESPACE: &str = "force-v2-authority-v1";
const MAX_CRITICAL_RESPONSE_BYTES: usize = 256 * 1024;

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceReplayDocumentV2 {
    pub note_id: String,
    pub sha256: String,
    pub js_code_unit_chars: u32,
    pub utf8_bytes: u32,
    pub version: Option<f64>,
    pub updated_at: Option<f64>,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceReplayModelV2 {
    pub dynamic_ner_id: String,
    pub embedding_model_id: String,
    pub embedding_dimension: String,
    pub nli_model_id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DurableForceReplayBindingV2 {
    pub schema_version: String,
    pub cohort_id: String,
    pub source_mode: String,
    pub dependency_identity: String,
    pub document_sha256: BTreeMap<String, String>,
    pub documents: Vec<DurableForceReplayDocumentBindingV2>,
    pub dynamic_ner_id: String,
    pub embedding_model_id: String,
    pub embedding_dimension: String,
    pub nli_model_id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DurableForceReplayDocumentBindingV2 {
    pub note_id: String,
    pub sha256: String,
    pub js_code_unit_chars: u32,
    pub utf8_bytes: u32,
    pub version: Option<f64>,
    pub updated_at: Option<f64>,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceRebuildV2ShadowRequest {
    pub contract_version: String,
    pub operation: String,
    pub source_mode: String,
    pub scope_id: String,
    pub cohort_id: String,
    pub scope_kind: String,
    pub dependency_identity: String,
    pub documents: Vec<DesktopForceReplayDocumentV2>,
    pub model: DesktopForceReplayModelV2,
    pub expected_snapshot_id: String,
    pub expected_authority_hash: String,
    pub expected_manifest_id: Option<String>,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceRebuildV2Request {
    pub contract_version: String,
    pub operation: String,
    pub source_mode: String,
    pub scope_id: String,
    pub cohort_id: String,
    pub scope_kind: String,
    pub dependency_identity: String,
    pub note_ids: Vec<String>,
    pub model: DesktopForceReplayModelV2,
    pub expected_snapshot_id: String,
    pub expected_authority_hash: String,
    pub expected_manifest_id: Option<String>,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceRebuildV2Error {
    pub code: String,
    pub message: String,
    pub retryable: bool,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceSectionV2 {
    pub name: String,
    pub identity: String,
    pub row_count: f64,
    pub raw_bytes: f64,
    pub compressed_bytes: f64,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceRebuildV2ShadowResult {
    pub schema_version: String,
    pub contract_version: String,
    pub path_id: String,
    pub fallback_count: u32,
    pub status: String,
    pub scope_id: String,
    pub snapshot_id: String,
    pub authority_hash: String,
    pub manifest_id: String,
    pub run_handle: String,
    pub analysis_source: String,
    pub analysis_kernel_micros: f64,
    pub verified_sections: Vec<DesktopForceSectionV2>,
    pub critical_response_bytes: f64,
    pub native_crossings: u32,
    pub source_body_reads: u32,
    pub source_utf8_bytes: f64,
    pub transported_source_bytes: f64,
    pub source_documents: Vec<DesktopForceReplayDocumentV2>,
    pub source_version_envelope_changed: bool,
    #[specta(type = serde_json::Value)]
    pub authority_packet: Option<serde_json::Value>,
    pub parent_span_id: String,
    pub span_id: String,
    pub error: Option<DesktopForceRebuildV2Error>,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceAuthorityPersistRequest {
    pub scope_id: String,
    pub snapshot_id: String,
    pub authority_hash: String,
    pub manifest_id: String,
    #[specta(type = serde_json::Value)]
    pub authority_packet: serde_json::Value,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopForceAuthorityPersistReceipt {
    pub schema_version: String,
    pub artifact_id: String,
    pub raw_bytes: f64,
    pub compressed_bytes: f64,
    pub encoded: bool,
    pub serializer_micros: f64,
    pub atomic_persist_micros: f64,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ForceAuthorityIndex {
    schema_version: String,
    scope_id: String,
    snapshot_id: String,
    authority_hash: String,
    manifest_id: String,
    artifact_id: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct DurableMetadataV2 {
    schema_version: String,
    source: String,
    no_topology_writes: bool,
    #[serde(default)]
    force_replay_binding: Option<DurableForceReplayBindingV2>,
    #[serde(default)]
    authority_hash: String,
}

pub(crate) fn binding_from_request(
    request: &DesktopForceRebuildV2ShadowRequest,
) -> DurableForceReplayBindingV2 {
    DurableForceReplayBindingV2 {
        schema_version: CONTRACT_VERSION.to_owned(),
        cohort_id: request.cohort_id.clone(),
        source_mode: request.source_mode.clone(),
        dependency_identity: request.dependency_identity.clone(),
        document_sha256: request
            .documents
            .iter()
            .map(|row| (row.note_id.clone(), row.sha256.clone()))
            .collect(),
        documents: request
            .documents
            .iter()
            .map(|row| DurableForceReplayDocumentBindingV2 {
                note_id: row.note_id.clone(),
                sha256: row.sha256.clone(),
                js_code_unit_chars: row.js_code_unit_chars,
                utf8_bytes: row.utf8_bytes,
                version: row.version,
                updated_at: row.updated_at,
            })
            .collect(),
        dynamic_ner_id: request.model.dynamic_ner_id.clone(),
        embedding_model_id: request.model.embedding_model_id.clone(),
        embedding_dimension: request.model.embedding_dimension.clone(),
        nli_model_id: request.model.nli_model_id.clone(),
    }
}

pub(crate) fn release_to_shadow_request(
    request: DesktopForceRebuildV2Request,
    documents: Vec<DesktopForceReplayDocumentV2>,
) -> DesktopForceRebuildV2ShadowRequest {
    DesktopForceRebuildV2ShadowRequest {
        contract_version: request.contract_version,
        operation: request.operation,
        source_mode: request.source_mode,
        scope_id: request.scope_id,
        cohort_id: request.cohort_id,
        scope_kind: request.scope_kind,
        dependency_identity: request.dependency_identity,
        documents,
        model: request.model,
        expected_snapshot_id: request.expected_snapshot_id,
        expected_authority_hash: request.expected_authority_hash,
        expected_manifest_id: request.expected_manifest_id,
    }
}

pub(crate) fn rejected_release(
    request: DesktopForceRebuildV2Request,
    code: &str,
    message: impl Into<String>,
) -> DesktopForceRebuildV2ShadowResult {
    let shadow = release_to_shadow_request(request, Vec::new());
    DesktopForceRebuildV2ShadowResult {
        schema_version: "phoenix-force-rebuild-v2-shadow-result/v1".to_owned(),
        contract_version: CONTRACT_VERSION.to_owned(),
        path_id: PATH_ID.to_owned(),
        fallback_count: 0,
        status: "rejected".to_owned(),
        scope_id: shadow.scope_id,
        snapshot_id: shadow.expected_snapshot_id,
        authority_hash: shadow.expected_authority_hash,
        manifest_id: String::new(),
        run_handle: String::new(),
        analysis_source: "none".to_owned(),
        analysis_kernel_micros: 0.0,
        verified_sections: Vec::new(),
        critical_response_bytes: 0.0,
        native_crossings: 1,
        source_body_reads: 0,
        source_utf8_bytes: 0.0,
        transported_source_bytes: 0.0,
        source_documents: shadow.documents,
        source_version_envelope_changed: false,
        authority_packet: None,
        parent_span_id: format!("{}:root", shadow.cohort_id),
        span_id: format!("{}:force-v2", shadow.cohort_id),
        error: Some(error(code, message)),
    }
}

pub(crate) fn verify_shadow(
    root: &Path,
    request: DesktopForceRebuildV2ShadowRequest,
) -> DesktopForceRebuildV2ShadowResult {
    let started = Instant::now();
    let span_id = format!("{}:force-v2", request.cohort_id);
    match verify(root, &request) {
        Ok((manifest, metadata, sections, authority_packet, source_version_envelope_changed)) => {
            let mut result = DesktopForceRebuildV2ShadowResult {
                schema_version: "phoenix-force-rebuild-v2-shadow-result/v1".to_owned(),
                contract_version: CONTRACT_VERSION.to_owned(),
                path_id: PATH_ID.to_owned(),
                fallback_count: 0,
                status: "durable_verified".to_owned(),
                scope_id: manifest.scope_id,
                snapshot_id: manifest.snapshot_id,
                authority_hash: metadata.authority_hash,
                manifest_id: manifest.manifest_id,
                run_handle: manifest.run_handle,
                analysis_source: "durable_verified".to_owned(),
                analysis_kernel_micros: 0.0,
                verified_sections: sections,
                critical_response_bytes: 0.0,
                native_crossings: 1,
                source_body_reads: 0,
                source_utf8_bytes: 0.0,
                transported_source_bytes: 0.0,
                source_documents: request.documents,
                source_version_envelope_changed,
                authority_packet: Some(authority_packet),
                parent_span_id: format!("{}:root", request.cohort_id),
                span_id,
                error: None,
            };
            result.critical_response_bytes =
                serde_json::to_vec(&result).map_or(0, |bytes| bytes.len()) as f64;
            if result.critical_response_bytes as usize > MAX_CRITICAL_RESPONSE_BYTES {
                result.status = "rejected".to_owned();
                result.analysis_source = "none".to_owned();
                result.authority_packet = None;
                result.error = Some(error(
                    "PHX_FORCE_V2_RESPONSE_TOO_LARGE",
                    "The compact native authority response exceeds 256 KiB.",
                ));
                result.critical_response_bytes =
                    serde_json::to_vec(&result).map_or(0, |bytes| bytes.len()) as f64;
            }
            result
        }
        Err(error) => DesktopForceRebuildV2ShadowResult {
            schema_version: "phoenix-force-rebuild-v2-shadow-result/v1".to_owned(),
            contract_version: CONTRACT_VERSION.to_owned(),
            path_id: PATH_ID.to_owned(),
            fallback_count: 0,
            status: "rejected".to_owned(),
            scope_id: request.scope_id,
            snapshot_id: request.expected_snapshot_id,
            authority_hash: request.expected_authority_hash,
            manifest_id: String::new(),
            run_handle: String::new(),
            analysis_source: "none".to_owned(),
            analysis_kernel_micros: started.elapsed().as_micros() as f64,
            verified_sections: Vec::new(),
            critical_response_bytes: 0.0,
            native_crossings: 1,
            source_body_reads: 0,
            source_utf8_bytes: 0.0,
            transported_source_bytes: 0.0,
            source_documents: request.documents,
            source_version_envelope_changed: false,
            authority_packet: None,
            parent_span_id: format!("{}:root", request.cohort_id),
            span_id,
            error: Some(error),
        },
    }
}

pub(crate) fn persist_authority_packet(
    root: &Path,
    request: DesktopForceAuthorityPersistRequest,
) -> Result<DesktopForceAuthorityPersistReceipt, String> {
    validate_authority_packet(&request)?;
    let serializer_started = Instant::now();
    let raw = serde_json::to_vec(&request.authority_packet)
        .map_err(|error| format!("serialize v2 authority packet: {error}"))?;
    if raw.len() > MAX_CRITICAL_RESPONSE_BYTES {
        return Err(format!(
            "PHX_FORCE_V2_AUTHORITY_PACKET_TOO_LARGE: {} bytes",
            raw.len()
        ));
    }
    let artifact_id = format!("b3-{}", blake3::hash(&raw).to_hex());
    let serializer_micros = serializer_started.elapsed().as_micros() as f64;
    let persist_started = Instant::now();
    let (_written_raw_bytes, compressed_bytes, encoded) = persist_immutable_artifact(
        root,
        AUTHORITY_NAMESPACE,
        &artifact_id,
        &request.authority_packet,
    )?;
    let index = ForceAuthorityIndex {
        schema_version: "phoenix-force-v2-authority-index/v1".to_owned(),
        scope_id: request.scope_id.clone(),
        snapshot_id: request.snapshot_id,
        authority_hash: request.authority_hash,
        manifest_id: request.manifest_id,
        artifact_id: artifact_id.clone(),
    };
    atomic_json(
        &root
            .join("force-v2-authority")
            .join("scopes")
            .join(format!("{}.json", scope_key(&request.scope_id))),
        &index,
    )?;
    Ok(DesktopForceAuthorityPersistReceipt {
        schema_version: "phoenix-force-v2-authority-persist/v1".to_owned(),
        artifact_id,
        raw_bytes: raw.len() as f64,
        compressed_bytes: compressed_bytes as f64,
        encoded,
        serializer_micros,
        atomic_persist_micros: persist_started.elapsed().as_micros() as f64,
    })
}

fn load_authority_packet(
    root: &Path,
    request: &DesktopForceRebuildV2ShadowRequest,
    manifest_id: &str,
    run_handle: &str,
) -> Result<serde_json::Value, DesktopForceRebuildV2Error> {
    let path = root
        .join("force-v2-authority")
        .join("scopes")
        .join(format!("{}.json", scope_key(&request.scope_id)));
    let bytes = std::fs::read(&path).map_err(|read| {
        error(
            "PHX_FORCE_V2_AUTHORITY_PACKET_MISSING",
            format!("{}: {read}", path.display()),
        )
    })?;
    let index: ForceAuthorityIndex = serde_json::from_slice(&bytes)
        .map_err(|decode| error("PHX_FORCE_V2_AUTHORITY_PACKET_INVALID", decode.to_string()))?;
    if index.scope_id != request.scope_id
        || index.snapshot_id != request.expected_snapshot_id
        || index.authority_hash != request.expected_authority_hash
        || index.manifest_id != manifest_id
    {
        return Err(error(
            "PHX_FORCE_V2_AUTHORITY_PACKET_MISMATCH",
            "Native authority packet index differs from the replay contract.",
        ));
    }
    let packet = load_immutable_artifact(root, AUTHORITY_NAMESPACE, &index.artifact_id)
        .map_err(|message| error("PHX_FORCE_V2_AUTHORITY_PACKET_INVALID", message))?
        .ok_or_else(|| {
            error(
                "PHX_FORCE_V2_AUTHORITY_PACKET_MISSING",
                "Native authority packet artifact is missing.",
            )
        })?;
    authority_packet::validate_compact_authority_packet(
        &packet,
        &request.scope_id,
        &request.expected_snapshot_id,
        &request.expected_authority_hash,
        manifest_id,
        Some(run_handle),
    )
    .map_err(|message| error("PHX_FORCE_V2_AUTHORITY_PACKET_INVALID", message))?;
    Ok(packet)
}

fn validate_authority_packet(request: &DesktopForceAuthorityPersistRequest) -> Result<(), String> {
    authority_packet::validate_compact_authority_packet(
        &request.authority_packet,
        &request.scope_id,
        &request.snapshot_id,
        &request.authority_hash,
        &request.manifest_id,
        None,
    )
}

fn verify(
    root: &Path,
    request: &DesktopForceRebuildV2ShadowRequest,
) -> Result<
    (
        DurableGraphRunManifest,
        DurableMetadataV2,
        Vec<DesktopForceSectionV2>,
        serde_json::Value,
        bool,
    ),
    DesktopForceRebuildV2Error,
> {
    guard_request(request)?;
    let manifest = load_manifest_for_scope(root, &request.scope_id)
        .map_err(|message| error("PHX_FORCE_V2_STORE_READ", message))?
        .ok_or_else(|| {
            error(
                "PHX_FORCE_V2_MANIFEST_MISSING",
                "No durable graph run exists for the requested scope.",
            )
        })?;
    if manifest.snapshot_id != request.expected_snapshot_id {
        return Err(error(
            "PHX_FORCE_V2_SNAPSHOT_MISMATCH",
            "Durable snapshot identity does not match the sealed UI authority.",
        ));
    }
    if request
        .expected_manifest_id
        .as_ref()
        .is_some_and(|id| id != &manifest.manifest_id)
    {
        return Err(error(
            "PHX_FORCE_V2_MANIFEST_MISMATCH",
            "Durable manifest identity changed since the replay contract was captured.",
        ));
    }
    let present = manifest
        .sections
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    if present != REQUIRED_SECTIONS.into_iter().collect() {
        return Err(error(
            "PHX_FORCE_V2_SECTION_SET_MISMATCH",
            "The durable graph run does not contain exactly eight verified sections.",
        ));
    }
    let mut sections = Vec::with_capacity(REQUIRED_SECTIONS.len());
    for name in REQUIRED_SECTIONS {
        let section = &manifest.sections[name];
        let valid_dependency_shape = if name == "metadata" {
            section.dependencies.len() == 2 && section.dependencies[1].starts_with("content:b3-")
        } else {
            section.dependencies.len() == 1
        };
        if section.encoding != "zstd+json"
            || !valid_dependency_shape
            || section_identity(&section.dependencies[0], name, &section.dependencies)
                != section.identity
            || !section_blob_exists(root, section)
        {
            return Err(error("PHX_FORCE_V2_SECTION_INVALID", format!("Durable section {name} failed identity, dependency, encoding, or blob validation.")));
        }
        sections.push(DesktopForceSectionV2 {
            name: name.to_owned(),
            identity: section.identity.clone(),
            row_count: section.row_count as f64,
            raw_bytes: section.raw_bytes as f64,
            compressed_bytes: section.compressed_bytes as f64,
        });
    }
    let metadata_section = &manifest.sections["metadata"];
    let metadata: DurableMetadataV2 = serde_json::from_slice(
        &load_section(root, metadata_section)
            .map_err(|message| error("PHX_FORCE_V2_METADATA_READ", message))?,
    )
    .map_err(|decode| error("PHX_FORCE_V2_METADATA_INVALID", decode.to_string()))?;
    if metadata.schema_version != "phoenix-graph-snapshot-analysis-native-output/v1"
        || metadata.source != "rust"
        || !metadata.no_topology_writes
    {
        return Err(error(
            "PHX_FORCE_V2_AUTHORITY_INVALID",
            "Durable analysis metadata is not native candidate-only authority.",
        ));
    }
    let expected = binding_from_request(request);
    let fields = replay_binding_mismatch_fields(metadata.force_replay_binding.as_ref(), &expected);
    if !fields.is_empty() {
        return Err(error(
            "PHX_FORCE_V2_REPLAY_BINDING_MISMATCH",
            format!(
                "Durable replay binding mismatch fields: {}.",
                fields.join(", ")
            ),
        ));
    }
    let source_version_envelope_changed =
        replay_binding_version_envelope_changed(metadata.force_replay_binding.as_ref(), &expected);
    if metadata.authority_hash != request.expected_authority_hash {
        return Err(error(
            "PHX_FORCE_V2_AUTHORITY_MISMATCH",
            "Durable authority hash does not match the sealed UI authority.",
        ));
    }
    let authority_packet =
        load_authority_packet(root, request, &manifest.manifest_id, &manifest.run_handle)?;
    Ok((
        manifest,
        metadata,
        sections,
        authority_packet,
        source_version_envelope_changed,
    ))
}

fn replay_binding_mismatch_fields(
    actual: Option<&DurableForceReplayBindingV2>,
    expected: &DurableForceReplayBindingV2,
) -> Vec<&'static str> {
    let Some(actual) = actual else {
        return vec!["forceReplayBinding.missing"];
    };
    let mut fields = Vec::new();
    if actual.schema_version != expected.schema_version {
        fields.push("schemaVersion");
    }
    if actual.cohort_id != expected.cohort_id {
        fields.push("cohortId");
    }
    if actual.source_mode != expected.source_mode {
        fields.push("sourceMode");
    }
    if actual.dependency_identity != expected.dependency_identity {
        fields.push("dependencyIdentity");
    }
    if actual.document_sha256 != expected.document_sha256 {
        fields.push("documentSha256");
    }
    if actual.documents.len() != expected.documents.len()
        || actual
            .documents
            .iter()
            .zip(&expected.documents)
            .any(|(actual, expected)| {
                actual.note_id != expected.note_id
                    || actual.sha256 != expected.sha256
                    || actual.js_code_unit_chars != expected.js_code_unit_chars
                    || actual.utf8_bytes != expected.utf8_bytes
            })
    {
        fields.push("documents");
    }
    if actual.dynamic_ner_id != expected.dynamic_ner_id {
        fields.push("dynamicNerId");
    }
    if actual.embedding_model_id != expected.embedding_model_id {
        fields.push("embeddingModelId");
    }
    if actual.embedding_dimension != expected.embedding_dimension {
        fields.push("embeddingDimension");
    }
    if actual.nli_model_id != expected.nli_model_id {
        fields.push("nliModelId");
    }
    fields
}

fn replay_binding_version_envelope_changed(
    actual: Option<&DurableForceReplayBindingV2>,
    expected: &DurableForceReplayBindingV2,
) -> bool {
    let Some(actual) = actual else { return false };
    actual.documents.len() == expected.documents.len()
        && actual
            .documents
            .iter()
            .zip(&expected.documents)
            .any(|(actual, expected)| {
                actual.version != expected.version || actual.updated_at != expected.updated_at
            })
}

fn guard_request(
    request: &DesktopForceRebuildV2ShadowRequest,
) -> Result<(), DesktopForceRebuildV2Error> {
    if request.contract_version != CONTRACT_VERSION {
        return Err(error(
            "PHX_FORCE_V2_CONTRACT_UNSUPPORTED",
            "The verified FORCE v2 contract version is required.",
        ));
    }
    if request.operation != "force" {
        return Err(error(
            "PHX_FORCE_V2_OPERATION_REQUIRED",
            "Only explicit FORCE is accepted by this contract.",
        ));
    }
    if request.source_mode != "scoped-note-store" {
        return Err(error(
            "PHX_FORCE_V2_SOURCE_MODE_REQUIRED",
            "The scoped native note store is required.",
        ));
    }
    if !matches!(
        request.scope_kind.as_str(),
        "note" | "multiNote" | "folder" | "narrative" | "global"
    ) {
        return Err(error(
            "PHX_FORCE_V2_SCOPE_KIND_INVALID",
            "The replay scope kind is not supported.",
        ));
    }
    if request.scope_id.is_empty()
        || request.documents.is_empty()
        || request.expected_snapshot_id.is_empty()
        || request.expected_authority_hash.is_empty()
        || request.dependency_identity.is_empty()
    {
        return Err(error(
            "PHX_FORCE_V2_REQUEST_INCOMPLETE",
            "Scope, source documents, snapshot, and authority identities are required.",
        ));
    }
    let mut ids = BTreeSet::new();
    if request.documents.iter().any(|row| {
        !ids.insert(row.note_id.as_str())
            || row.sha256.len() != 64
            || !row.sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
    }) {
        return Err(error(
            "PHX_FORCE_V2_DOCUMENT_IDENTITY_INVALID",
            "Document IDs must be unique and carry exact SHA-256 hashes.",
        ));
    }
    Ok(())
}

fn error(code: &str, message: impl Into<String>) -> DesktopForceRebuildV2Error {
    DesktopForceRebuildV2Error {
        code: code.to_owned(),
        message: message.into(),
        retryable: false,
    }
}

#[cfg(test)]
#[path = "graph_force_rebuild_v2_tests.rs"]
mod tests;

use super::*;

#[test]
fn rejects_non_force_and_invalid_document_hashes_without_fallback() {
    let root = tempfile::tempdir().unwrap();
    let mut request = fixture_request();
    request.operation = "delta".to_owned();
    let result = verify_shadow(root.path(), request);
    assert_eq!(result.status, "rejected");
    assert_eq!(result.fallback_count, 0);
    assert_eq!(
        result.error.unwrap().code,
        "PHX_FORCE_V2_OPERATION_REQUIRED"
    );

    let mut request = fixture_request();
    request.documents[0].sha256 = "not-a-hash".to_owned();
    let result = verify_shadow(root.path(), request);
    assert_eq!(
        result.error.unwrap().code,
        "PHX_FORCE_V2_DOCUMENT_IDENTITY_INVALID"
    );
}

#[test]
fn replay_binding_mismatch_names_exact_fields() {
    let expected = binding_from_request(&fixture_request());
    assert_eq!(
        replay_binding_mismatch_fields(None, &expected),
        vec!["forceReplayBinding.missing"]
    );
    let mut actual = expected.clone();
    actual.dependency_identity = "changed".to_owned();
    actual.nli_model_id = "changed".to_owned();
    assert_eq!(
        replay_binding_mismatch_fields(Some(&actual), &expected),
        vec!["dependencyIdentity", "nliModelId"],
    );

    let mut version_only = expected.clone();
    version_only.documents[0].version = Some(2.0);
    version_only.documents[0].updated_at = Some(3.0);
    assert!(replay_binding_mismatch_fields(Some(&version_only), &expected).is_empty());
    assert!(replay_binding_version_envelope_changed(
        Some(&version_only),
        &expected
    ));

    version_only.documents[0].sha256 = "b".repeat(64);
    assert_eq!(
        replay_binding_mismatch_fields(Some(&version_only), &expected),
        vec!["documents"]
    );
}

#[test]
fn missing_durable_authority_is_named_and_never_falls_back() {
    let root = tempfile::tempdir().unwrap();
    let result = verify_shadow(root.path(), fixture_request());
    assert_eq!(result.status, "rejected");
    assert_eq!(result.path_id, PATH_ID);
    assert_eq!(result.fallback_count, 0);
    assert_eq!(result.error.unwrap().code, "PHX_FORCE_V2_MANIFEST_MISSING");
}

#[test]
fn authority_packet_persistence_is_identity_bound_and_idempotent() {
    let root = tempfile::tempdir().unwrap();
    let packet = fixture_authority_packet();
    let request = DesktopForceAuthorityPersistRequest {
        scope_id: "global".to_owned(),
        snapshot_id: "snapshot-1".to_owned(),
        authority_hash: "authority".to_owned(),
        manifest_id: "manifest-1".to_owned(),
        authority_packet: packet.clone(),
    };
    let first = persist_authority_packet(root.path(), request.clone()).unwrap();
    let second = persist_authority_packet(root.path(), request).unwrap();
    assert!(first.encoded);
    assert!(!second.encoded);
    assert_eq!(first.artifact_id, second.artifact_id);
    assert_eq!(first.raw_bytes, second.raw_bytes);
    let loaded = load_authority_packet(root.path(), &fixture_request(), "manifest-1", "run-1")
        .unwrap_or_else(|error| panic!("authority packet load failed: {}", error.code));
    assert_eq!(loaded, packet);
}

#[test]
fn compact_authority_packet_rejects_counter_drift_and_legacy_arrays() {
    let mut packet = fixture_authority_packet();
    packet["counters"]["embeddingTargets"] = serde_json::json!(3);
    assert!(authority_packet::validate_compact_authority_packet(
        &packet,
        "global",
        "snapshot-1",
        "authority",
        "manifest-1",
        Some("run-1"),
    )
    .unwrap_err()
    .contains("counter drift"));

    let mut packet = fixture_authority_packet();
    packet["embeddingTargets"] = serde_json::json!([{ "id": "legacy-target" }]);
    assert!(authority_packet::validate_compact_authority_packet(
        &packet,
        "global",
        "snapshot-1",
        "authority",
        "manifest-1",
        Some("run-1"),
    )
    .unwrap_err()
    .contains("materialized legacy array"));
}

fn fixture_request() -> DesktopForceRebuildV2ShadowRequest {
    DesktopForceRebuildV2ShadowRequest {
        contract_version: CONTRACT_VERSION.to_owned(),
        operation: "force".to_owned(),
        source_mode: "scoped-note-store".to_owned(),
        scope_id: "global".to_owned(),
        cohort_id: "sha256:cohort".to_owned(),
        scope_kind: "global".to_owned(),
        dependency_identity: "sha256:dependencies".to_owned(),
        documents: vec![DesktopForceReplayDocumentV2 {
            note_id: "note-1".to_owned(),
            sha256: "a".repeat(64),
            js_code_unit_chars: 10,
            utf8_bytes: 10,
            version: Some(1.0),
            updated_at: None,
        }],
        model: DesktopForceReplayModelV2 {
            dynamic_ner_id: "dynamic_ner".to_owned(),
            embedding_model_id: "jina-v5-nano".to_owned(),
            embedding_dimension: "768d".to_owned(),
            nli_model_id: "modernbert-nli".to_owned(),
        },
        expected_snapshot_id: "snapshot-1".to_owned(),
        expected_authority_hash: "authority".to_owned(),
        expected_manifest_id: None,
    }
}

fn fixture_authority_packet() -> serde_json::Value {
    let counts = serde_json::json!({
        "notes": 1, "chunks": 1, "mentions": 0, "anchors": 1, "relationships": 0,
        "events": 0, "temporalEdges": 0, "causalEdges": 0, "memoryState": 0,
        "coreferenceRecoveries": 0, "nodes": 1, "edges": 0, "embeddingTargets": 2,
        "admittedEmbeddingTargets": 2, "packetObjects": 2, "packetTargets": 2,
        "packetParentLinks": 0, "packetFamilies": {},
    });
    serde_json::json!({
        "schemaVersion": "phoenix-graph-rebuild/v1",
        "id": "snapshot-1", "scopeId": "global", "scopeKind": "global",
        "source": "phoenix-graph-rebuild", "noteIds": ["note-1"], "builtAt": 1,
        "generationReceiptId": "generation-1", "generationDigestSha256": "sha256-digest",
        "authorityContract": {
            "schemaVersion": "phoenix-graph-snapshot-authority/v1",
            "authority": "graph_rebuild_live_contract", "snapshotId": "snapshot-1",
            "scopeId": "global", "contentHash": "authority", "counts": counts,
        },
        "contentManifest": { "snapshotId": "snapshot-1", "scopeId": "global", "refs": [] },
        "interactiveRunAuthority": {
            "snapshotId": "snapshot-1", "scopeId": "global",
            "durable": {
                "snapshotId": "snapshot-1", "scopeId": "global",
                "manifestId": "manifest-1", "runHandle": "run-1",
            },
        },
        "counters": {
            "notes": 1, "chunks": 1, "mentions": 0, "acceptedAnchors": 1,
            "relationships": 0, "events": 0, "temporalEdges": 0, "causalEdges": 0,
            "memoryState": 0, "coreferenceRecoveries": 0, "nodes": 1, "edges": 0,
            "embeddingTargets": 2, "documentSemanticLocalCoreferenceRecoveries": 0,
        },
        "evidenceTargetRegistry": {
            "sourceSnapshotId": "snapshot-1", "sourceScopeId": "global",
            "canonicalTargets": 2, "exposedTargets": 2, "chunks": 1,
            "typedGraphObjects": 1, "supportTargets": 0, "duplicateTargets": 0,
            "orphanTargets": 0, "identityHash": "fnv32-00000000",
        },
        "chunks": [], "mentions": [], "entityAnchors": [], "relationships": [],
        "events": [], "episodes": [], "temporalEdges": [], "causalEdges": [],
        "memoryState": [], "embeddingTargets": [], "embeddingVectors": [], "nodes": [],
        "edges": [], "projectionRefs": [], "resolutionSuggestions": [],
    })
}

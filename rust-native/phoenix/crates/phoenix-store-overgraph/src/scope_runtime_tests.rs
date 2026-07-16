use lz4_flex::compress_prepend_size;
use std::sync::Arc;

use phoenix_document_index::{build_document_index_shard, DocumentIndexInput};
use phoenix_semantic_v2::{
    scope_storage_key, DirtyScopeRecord, DocumentManifest, DocumentOrd, DocumentOrdinalAssignment,
    DocumentSegmentHeader, DocumentSegmentKind, DocumentSegmentRef, DocumentVersionId,
    ErScopePatchSidecar, EventIdentityScopeSidecar, MemoryScopeSidecar, PreparedDocument,
    PreparedDocumentSegment, RelationScopePatchSidecar, ScopeOrd, SemanticEntityRecord,
    SemanticRelationRecord,
};
use phoenix_store_native_core::{
    ArchiveSegmentMask, PhoenixArchiveStoreV2, PhoenixErPatchStore, PhoenixEventIdentityPatchStore,
    PhoenixMemoryPatchStore, PhoenixRelationPatchStore, PhoenixScopeRuntimeStore, ScopeImageSpec,
};
use phoenix_types::{
    EntityId, EntityKind, MentionEntityRef, MentionSource, MentionSpan, RelationCandidate,
    SentenceSpan, SessionDocumentState, TextRange,
};

use crate::*;

fn temp_store(name: &str) -> PhoenixOvergraphStore {
    let path = std::env::temp_dir().join(format!(
        "phoenix-overgraph-runtime-{name}-{}-{}",
        std::process::id(),
        now_ms()
    ));
    let _ = std::fs::remove_dir_all(&path);
    PhoenixOvergraphStore::open(&path).expect("open overgraph store")
}

fn pack_segment<T: serde::Serialize>(
    kind: DocumentSegmentKind,
    ordinal: u32,
    row_count: usize,
    value: &T,
) -> PreparedDocumentSegment {
    let record = encode_record(value).expect("encode segment record");
    let payload = compress_prepend_size(&record);
    PreparedDocumentSegment {
        header: DocumentSegmentHeader::new(
            kind,
            ordinal,
            row_count as u32,
            record.len(),
            payload.len(),
        ),
        payload,
    }
}

fn sample_document(
    scope: &phoenix_types::ScopeKey,
    scope_ord: ScopeOrd,
    document_ord: DocumentOrd,
    document_id: &str,
    created_at: i64,
) -> PreparedDocument {
    let sentences = vec![SentenceSpan {
        index: 0,
        range: TextRange { start: 0, end: 12 },
    }];
    let mentions = vec![MentionSpan {
        range: TextRange { start: 0, end: 5 },
        surface: "Alice".to_owned(),
        kind: Some(EntityKind::Character),
        entity_ref: Some(MentionEntityRef::Known(EntityId("entity:alice".to_owned()))),
        source: Some(MentionSource::Known),
        confidence: 0.99,
        sentence_index: 0,
    }];
    let resolved_mentions = vec![phoenix_semantic_v2::ResolvedMention {
        mention_id: phoenix_semantic_v2::MentionId("mention:alice".to_owned()),
        mention_index: 0,
        range: TextRange { start: 0, end: 5 },
        surface: "Alice".to_owned(),
        normalized: "alice".to_owned(),
        kind: Some(EntityKind::Character),
        entity_id: Some(EntityId("entity:alice".to_owned())),
        decision: phoenix_semantic_v2::ResolutionDecision {
            status: "resolved".to_owned(),
            confidence_millis: 990,
            margin_millis: 250,
        },
        candidates: Vec::new(),
    }];
    let chunks = vec![phoenix_semantic_v2::ChunkRecord {
        chunk_id: phoenix_semantic_v2::ChunkId("chunk:0".to_owned()),
        range: TextRange { start: 0, end: 12 },
        chapter_id: 1,
        boundary_label: None,
        text: "Alice helps".to_owned(),
    }];
    let entities = vec![SemanticEntityRecord {
        entity_id: EntityId("entity:alice".to_owned()),
        canonical_name: "Alice".to_owned(),
        aliases: vec!["Al".to_owned()],
        kind: Some(EntityKind::Character),
        mention_count: 1,
        chunk_ids: vec!["chunk:0".to_owned()],
    }];
    let relations = vec![SemanticRelationRecord {
        source_entity_id: EntityId("entity:alice".to_owned()),
        target_entity_id: EntityId("entity:bob".to_owned()),
        edge_type: "helps".to_owned(),
        sentence_index: 0,
        chunk_id: Some("chunk:0".to_owned()),
    }];
    let relation_candidates = vec![RelationCandidate {
        sentence_index: 0,
        verb_range: TextRange { start: 6, end: 11 },
        lemma: "help".to_owned(),
        event_class: "assist".to_owned(),
        relation_type: "helps".to_owned(),
        ..Default::default()
    }];

    let segments = vec![
        pack_segment(
            DocumentSegmentKind::SentenceTable,
            0,
            sentences.len(),
            &sentences,
        ),
        pack_segment(
            DocumentSegmentKind::MentionTable,
            1,
            mentions.len(),
            &mentions,
        ),
        pack_segment(
            DocumentSegmentKind::ResolvedMentionTable,
            2,
            resolved_mentions.len(),
            &resolved_mentions,
        ),
        pack_segment(DocumentSegmentKind::ChunkTable, 3, chunks.len(), &chunks),
        pack_segment(
            DocumentSegmentKind::EntityTable,
            4,
            entities.len(),
            &entities,
        ),
        pack_segment(
            DocumentSegmentKind::RelationTable,
            5,
            relations.len(),
            &relations,
        ),
        pack_segment(
            DocumentSegmentKind::NarrativeHitTable,
            6,
            relation_candidates.len(),
            &relation_candidates,
        ),
    ];
    let segment_refs = segments
        .iter()
        .map(|segment| DocumentSegmentRef {
            kind: segment.header.kind(),
            ordinal: segment.header.ordinal,
            row_count: segment.header.row_count,
            byte_len: segment.header.payload_len,
            uncompressed_len: segment.header.uncompressed_len,
        })
        .collect::<Vec<_>>();
    let scope_key = scope_storage_key(scope);
    let manifest = DocumentManifest {
        document_id: document_id.to_owned(),
        document_version_id: DocumentVersionId(format!("{document_id}:v1")),
        note_id: None,
        scope: scope.clone(),
        scope_key: scope_key.clone(),
        scope_ord,
        document_ord,
        revision: 1,
        title: format!("Title {document_id}"),
        text_len: 12,
        fingerprint: format!("fp:{document_id}"),
        config_hash: "cfg".to_owned(),
        session_id: None,
        document_summary: Default::default(),
        session_document: SessionDocumentState::default(),
        discovery_count: 0,
        mention_count: mentions.len(),
        span_count: 0,
        entity_count: entities.len(),
        alias_count: 1,
        graph_edge_count: 0,
        graph_vertex_count: 0,
        segment_refs,
        created_at,
        archive_version: 1,
    };

    PreparedDocument {
        assignment: DocumentOrdinalAssignment {
            document_id: document_id.to_owned(),
            scope: scope.clone(),
            scope_key,
            scope_ord,
            document_ord,
            revision: 1,
        },
        manifest,
        segments,
        document_index_shard: None,
        kernel_batch: Default::default(),
    }
}

#[test]
fn prepared_document_index_shards_publish_once_and_reuse_by_hash() {
    let store = temp_store("document-index-shard");
    store.init_archive_schema().expect("init archive schema");
    let scope = phoenix_types::ScopeKey::default();
    let scope_ord = ScopeOrd(6);
    let document_ord = DocumentOrd(1);
    let mut document = sample_document(&scope, scope_ord, document_ord, "doc-index", 10);
    document.document_index_shard = Some(
        build_document_index_shard(DocumentIndexInput {
            document_id: "doc-index",
            note_id: Some("note-index"),
            title: "Index",
            text: "# Index\n\nMapped paragraph.",
        })
        .expect("build document index"),
    );
    let dirty = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_storage_key(&scope),
        scope_ord,
        document_ords: vec![document_ord],
        updated_at: 10,
    };

    let first = store
        .persist_prepared_documents_with_telemetry(
            std::slice::from_ref(&document),
            None,
            std::slice::from_ref(&dirty),
            10,
        )
        .expect("first persist");
    assert_eq!(first.document_index_shard_count, 1);
    assert_eq!(first.document_index_shards_written, 1);
    assert_eq!(first.document_index_shards_reused, 0);

    let warm = store
        .persist_prepared_documents_with_telemetry(
            std::slice::from_ref(&document),
            None,
            std::slice::from_ref(&dirty),
            20,
        )
        .expect("warm persist");
    assert_eq!(warm.document_index_shards_written, 0);
    assert_eq!(warm.document_index_shards_reused, 1);
    let reference = store
        .load_latest_document_index_ref(scope_ord, document_ord)
        .expect("load latest ref")
        .expect("latest ref");
    let mapped = store
        .open_document_index_shard(&reference)
        .expect("mmap latest shard");
    assert_eq!(mapped.note_id().expect("note id"), Some("note-index"));
}

#[test]
fn scope_runtime_image_prefers_dirty_ords_and_masks_archive_segments() {
    let store = temp_store("masked-runtime-image");
    store.init_archive_schema().expect("init archive schema");

    let scope = phoenix_types::ScopeKey::default();
    let scope_ord = ScopeOrd(7);
    let dirty = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_storage_key(&scope),
        scope_ord,
        document_ords: vec![DocumentOrd(1)],
        updated_at: 77,
    };

    let docs = vec![
        sample_document(&scope, scope_ord, DocumentOrd(1), "doc-a", 10),
        sample_document(&scope, scope_ord, DocumentOrd(2), "doc-b", 11),
    ];
    store
        .persist_prepared_documents(&docs, None, std::slice::from_ref(&dirty), 77)
        .expect("persist prepared docs");

    let late = store
        .load_scope_runtime_image(&dirty, ScopeImageSpec::late_sidecars())
        .expect("load late runtime image");
    assert_eq!(late.manifests.len(), 1);
    assert_eq!(late.archives.len(), 1);
    assert_eq!(late.archives[0].manifest.document_id, "doc-a");
    assert_eq!(late.archives[0].entities.len(), 1);
    assert_eq!(late.archives[0].relations.len(), 1);
    assert!(late.archives[0].sentences.is_empty());
    assert!(late.archives[0].mentions.is_empty());
    assert!(late.archives[0].resolved_mentions.is_empty());
    assert!(late.archives[0].chunks.is_empty());
    assert!(late.archives[0].relation_candidates.is_empty());

    let post_ingest = store
        .load_scope_runtime_image(&dirty, ScopeImageSpec::post_ingest())
        .expect("load post-ingest runtime image");
    assert_eq!(post_ingest.archives.len(), 1);
    assert_eq!(post_ingest.archives[0].manifest.document_id, "doc-a");
    assert_eq!(post_ingest.archives[0].sentences.len(), 1);
    assert_eq!(post_ingest.archives[0].mentions.len(), 1);
    assert_eq!(post_ingest.archives[0].resolved_mentions.len(), 1);
    assert_eq!(post_ingest.archives[0].chunks.len(), 1);
    assert_eq!(post_ingest.archives[0].entities.len(), 1);
    assert_eq!(post_ingest.archives[0].relations.len(), 1);
    assert_eq!(post_ingest.archives[0].relation_candidates.len(), 1);
}

#[test]
fn prepared_document_segments_reopen_from_external_payloads() {
    let store = temp_store("external-segment-restart");
    store.init_archive_schema().expect("init archive schema");

    let scope = phoenix_types::ScopeKey::default();
    let scope_ord = ScopeOrd(17);
    let dirty = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_storage_key(&scope),
        scope_ord,
        document_ords: vec![DocumentOrd(3)],
        updated_at: 79,
    };
    let doc = sample_document(&scope, scope_ord, DocumentOrd(3), "doc-external", 12);
    let expected_segment_bytes = doc
        .segments
        .iter()
        .map(|segment| segment.payload.len())
        .sum::<usize>();
    let telemetry = store
        .persist_prepared_documents_with_telemetry(&[doc], None, std::slice::from_ref(&dirty), 79)
        .expect("persist external prepared document");
    assert_eq!(telemetry.segment_external_bytes, expected_segment_bytes);
    assert_eq!(telemetry.segment_inline_bytes, 0);
    assert!(telemetry
        .segments
        .iter()
        .all(|segment| segment.storage == "external"));

    let path = store.path.clone();
    drop(store);
    let reopened = PhoenixOvergraphStore::open(path).expect("reopen overgraph store");
    let archives = reopened
        .load_latest_document_archives(Some(&scope))
        .expect("load mmap-backed document archive");
    assert_eq!(archives.len(), 1);
    assert_eq!(archives[0].manifest.document_id, "doc-external");
    assert_eq!(archives[0].sentences.len(), 1);
    assert_eq!(archives[0].mentions.len(), 1);
    assert_eq!(archives[0].resolved_mentions.len(), 1);
    assert_eq!(archives[0].chunks.len(), 1);
    assert_eq!(archives[0].entities.len(), 1);
    assert_eq!(archives[0].relations.len(), 1);
    assert_eq!(archives[0].relation_candidates.len(), 1);
}

#[test]
fn scope_runtime_image_bundles_requested_sidecars() {
    let store = temp_store("runtime-sidecars");
    store.init_archive_schema().expect("init archive schema");
    store.init_er_patch_schema().expect("init er schema");
    store
        .init_relation_patch_schema()
        .expect("init relation schema");
    store
        .init_memory_patch_schema()
        .expect("init memory schema");
    store
        .init_event_identity_patch_schema()
        .expect("init event identity schema");

    let scope = phoenix_types::ScopeKey::default();
    let scope_key = scope_storage_key(&scope);
    let scope_ord = ScopeOrd(9);
    let dirty = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_key.clone(),
        scope_ord,
        document_ords: vec![DocumentOrd(1)],
        updated_at: 88,
    };
    let doc = sample_document(&scope, scope_ord, DocumentOrd(1), "doc-sidecar", 15);
    store
        .persist_prepared_documents(&[doc], None, std::slice::from_ref(&dirty), 88)
        .expect("persist prepared doc");

    store
        .persist_er_patch_sidecar(&ErScopePatchSidecar {
            scope: scope.clone(),
            scope_key: scope_key.clone(),
            scope_ord: Some(scope_ord),
            updated_at: 90,
            generation: 1,
            ..Default::default()
        })
        .expect("persist er sidecar");
    store
        .persist_relation_patch_sidecar(&RelationScopePatchSidecar {
            scope: scope.clone(),
            scope_key: scope_key.clone(),
            scope_ord: Some(scope_ord),
            updated_at: 91,
            generation: 2,
            ..Default::default()
        })
        .expect("persist relation sidecar");
    store
        .persist_memory_patch_sidecar(&MemoryScopeSidecar {
            scope: scope.clone(),
            scope_key: scope_key.clone(),
            scope_ord: Some(scope_ord),
            updated_at: 92,
            generation: 3,
            ..Default::default()
        })
        .expect("persist memory sidecar");
    store
        .persist_event_identity_patch_sidecar(&EventIdentityScopeSidecar {
            scope: scope.clone(),
            scope_key: scope_key.clone(),
            scope_ord: Some(scope_ord),
            updated_at: 93,
            generation: 4,
            ..Default::default()
        })
        .expect("persist event identity sidecar");

    let runtime = store
        .load_scope_runtime_image(&dirty, ScopeImageSpec::post_ingest())
        .expect("load runtime image");
    assert!(runtime.sidecars.er.is_some());
    assert!(runtime.sidecars.relation.is_some());
    assert!(runtime.sidecars.memory.is_some());
    assert!(runtime.sidecars.event_identity.is_some());
    assert!(runtime.sidecars.state_schema.is_none());
    assert!(runtime.sidecars.causal.is_none());
}

#[test]
fn scope_runtime_image_reuses_exact_cached_image() {
    let store = temp_store("runtime-image-cache-hit");
    store.init_archive_schema().expect("init archive schema");

    let scope = phoenix_types::ScopeKey::default();
    let scope_ord = ScopeOrd(13);
    let dirty = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_storage_key(&scope),
        scope_ord,
        document_ords: vec![DocumentOrd(1)],
        updated_at: 101,
    };
    let doc = sample_document(&scope, scope_ord, DocumentOrd(1), "doc-cache", 20);
    store
        .persist_prepared_documents(&[doc], None, std::slice::from_ref(&dirty), 101)
        .expect("persist prepared doc");

    let first = store
        .load_scope_runtime_image(&dirty, ScopeImageSpec::late_sidecars())
        .expect("load first image");
    let second = store
        .load_scope_runtime_image(&dirty, ScopeImageSpec::late_sidecars())
        .expect("load second image");

    assert!(Arc::ptr_eq(&first.archives, &second.archives));
    assert!(Arc::ptr_eq(&first.manifests, &second.manifests));
    assert!(Arc::ptr_eq(&first.sidecars, &second.sidecars));
    assert!(Arc::ptr_eq(&first.indices, &second.indices));
}

#[test]
fn scope_runtime_image_keeps_document_projection_hot_across_sidecar_updates() {
    let store = temp_store("runtime-document-cache");
    store.init_archive_schema().expect("init archive schema");
    store
        .init_relation_patch_schema()
        .expect("init relation patch schema");

    let scope = phoenix_types::ScopeKey::default();
    let scope_key = scope_storage_key(&scope);
    let scope_ord = ScopeOrd(14);
    let dirty = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_key.clone(),
        scope_ord,
        document_ords: vec![DocumentOrd(1)],
        updated_at: 111,
    };
    let doc = sample_document(&scope, scope_ord, DocumentOrd(1), "doc-hot", 21);
    store
        .persist_prepared_documents(&[doc], None, std::slice::from_ref(&dirty), 111)
        .expect("persist prepared doc");

    let rich = store
        .load_scope_runtime_image(&dirty, ScopeImageSpec::post_ingest())
        .expect("load rich image");

    store
        .persist_relation_patch_sidecar(&RelationScopePatchSidecar {
            scope: scope.clone(),
            scope_key,
            scope_ord: Some(scope_ord),
            updated_at: 112,
            generation: 1,
            ..Default::default()
        })
        .expect("persist relation sidecar");

    let lean = store
        .load_scope_runtime_image(&dirty, ScopeImageSpec::late_sidecars())
        .expect("load lean image");

    assert!(Arc::ptr_eq(&rich.archives, &lean.archives));
    assert!(Arc::ptr_eq(&rich.manifests, &lean.manifests));
    assert!(Arc::ptr_eq(&rich.indices, &lean.indices));
    assert!(lean.sidecars.relation.is_some());
}

#[test]
fn scope_runtime_image_for_scope_loads_the_full_scope_not_just_latest_dirty_slice() {
    let store = temp_store("runtime-full-scope");
    store.init_archive_schema().expect("init archive schema");

    let scope = phoenix_types::ScopeKey::default();
    let scope_ord = ScopeOrd(21);
    let runtime_spec =
        ScopeImageSpec::default().with_archive_segments(ArchiveSegmentMask::post_ingest_runtime());

    let dirty_b = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_storage_key(&scope),
        scope_ord,
        document_ords: vec![DocumentOrd(2)],
        updated_at: 201,
    };
    let doc_b = sample_document(&scope, scope_ord, DocumentOrd(2), "doc-b", 30);
    store
        .persist_prepared_documents(&[doc_b], None, std::slice::from_ref(&dirty_b), 201)
        .expect("persist doc b");

    let dirty_a = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_storage_key(&scope),
        scope_ord,
        document_ords: vec![DocumentOrd(1)],
        updated_at: 202,
    };
    let doc_a = sample_document(&scope, scope_ord, DocumentOrd(1), "doc-a", 31);
    store
        .persist_prepared_documents(&[doc_a], None, std::slice::from_ref(&dirty_a), 202)
        .expect("persist doc a");

    let dirty_only = store
        .load_scope_runtime_image(&dirty_a, runtime_spec)
        .expect("load dirty runtime");
    assert_eq!(dirty_only.archives.len(), 1);
    assert_eq!(dirty_only.archives[0].manifest.document_id, "doc-a");

    let full_scope = store
        .load_scope_runtime_image_for_scope(&scope, runtime_spec)
        .expect("load full scope runtime")
        .expect("full scope runtime image");
    let mut document_ids = full_scope
        .archives
        .iter()
        .map(|archive| archive.manifest.document_id.as_str())
        .collect::<Vec<_>>();
    document_ids.sort_unstable();

    assert_eq!(document_ids, vec!["doc-a", "doc-b"]);
}

#[test]
fn load_scope_runtime_images_returns_one_full_image_per_scope() {
    let store = temp_store("runtime-all-scopes");
    store.init_archive_schema().expect("init archive schema");

    let left_scope = phoenix_types::ScopeKey::default();
    let right_scope = phoenix_types::ScopeKey {
        world_id: Some("world-b".to_owned()),
        ..Default::default()
    };
    let runtime_spec =
        ScopeImageSpec::default().with_archive_segments(ArchiveSegmentMask::post_ingest_runtime());

    let left_dirty = DirtyScopeRecord {
        scope: left_scope.clone(),
        scope_key: scope_storage_key(&left_scope),
        scope_ord: ScopeOrd(31),
        document_ords: vec![DocumentOrd(1)],
        updated_at: 301,
    };
    let right_dirty = DirtyScopeRecord {
        scope: right_scope.clone(),
        scope_key: scope_storage_key(&right_scope),
        scope_ord: ScopeOrd(32),
        document_ords: vec![DocumentOrd(1)],
        updated_at: 302,
    };

    store
        .persist_prepared_documents(
            &[sample_document(
                &left_scope,
                ScopeOrd(31),
                DocumentOrd(1),
                "left-doc",
                40,
            )],
            None,
            std::slice::from_ref(&left_dirty),
            301,
        )
        .expect("persist left doc");
    store
        .persist_prepared_documents(
            &[sample_document(
                &right_scope,
                ScopeOrd(32),
                DocumentOrd(1),
                "right-doc",
                41,
            )],
            None,
            std::slice::from_ref(&right_dirty),
            302,
        )
        .expect("persist right doc");

    let images = store
        .load_scope_runtime_images(runtime_spec)
        .expect("load all scope runtime images");

    assert_eq!(images.len(), 2);
    assert!(images.iter().all(|image| image.archives.len() == 1));
}

#[test]
fn scope_runtime_image_for_scope_writes_document_projection_cache_file() {
    let store = temp_store("runtime-projection-cache-file");
    store.init_archive_schema().expect("init archive schema");

    let scope = phoenix_types::ScopeKey::default();
    let scope_ord = ScopeOrd(41);
    let dirty = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_storage_key(&scope),
        scope_ord,
        document_ords: vec![DocumentOrd(1)],
        updated_at: 401,
    };
    store
        .persist_prepared_documents(
            &[sample_document(
                &scope,
                scope_ord,
                DocumentOrd(1),
                "doc-cache-file",
                51,
            )],
            None,
            std::slice::from_ref(&dirty),
            401,
        )
        .expect("persist prepared doc");

    let spec = ScopeImageSpec::post_ingest();
    let image = store
        .load_scope_runtime_image_for_scope(&scope, spec)
        .expect("load full scope runtime")
        .expect("runtime image");
    let cache_path = store.document_projection_cache_path(&image.dirty, spec.archive_segments);

    assert!(
        cache_path.exists(),
        "expected document projection cache file"
    );
}

#[test]
fn scope_runtime_image_for_scope_writes_runtime_image_cache_file() {
    let store = temp_store("runtime-image-cache-file");
    store.init_archive_schema().expect("init archive schema");

    let scope = phoenix_types::ScopeKey::default();
    let scope_ord = ScopeOrd(42);
    let dirty = DirtyScopeRecord {
        scope: scope.clone(),
        scope_key: scope_storage_key(&scope),
        scope_ord,
        document_ords: vec![DocumentOrd(1)],
        updated_at: 402,
    };
    store
        .persist_prepared_documents(
            &[sample_document(
                &scope,
                scope_ord,
                DocumentOrd(1),
                "doc-runtime-cache",
                52,
            )],
            None,
            std::slice::from_ref(&dirty),
            402,
        )
        .expect("persist prepared doc");

    let spec = ScopeImageSpec::post_ingest();
    let image = store
        .load_scope_runtime_image_for_scope(&scope, spec)
        .expect("load full scope runtime")
        .expect("runtime image");
    let cache_path = store.scope_runtime_image_cache_path(&image.dirty, spec);

    assert!(cache_path.exists(), "expected runtime image cache file");
}

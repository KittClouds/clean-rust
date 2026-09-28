use std::sync::Arc;

use phoenix_semantic_v2::{
    scope_storage_key, AliasEntry, AliasPosting, DirtyScopeRecord, DocumentArchive,
    DocumentManifest, DocumentRevisionRef, ErAliasAddition, ErEntityLinkOverride,
    ErScopePatchSidecar, ErTypeOverride, ScopeLexSidecar, SemanticEntityRecord,
    SemanticRelationRecord, SessionArchive,
};
use phoenix_store_native_core::{ScopeRuntimeImage, ScopeRuntimeIndices, ScopeSidecarBundle};
use phoenix_types::{EntityId, EntityKind, ScopeKey, SessionId};

use crate::ScopeAnalysisContext;

#[test]
fn analysis_context_merges_entity_sidecars_once() {
    let runtime = ScopeRuntimeImage {
        dirty: DirtyScopeRecord {
            scope: ScopeKey::default(),
            scope_key: scope_storage_key(&ScopeKey::default()),
            ..Default::default()
        },
        manifests: Arc::from([]),
        archives: Arc::from([
            sample_archive("doc-a", "entity:hero"),
            sample_archive("doc-b", "entity:hero"),
        ]),
        sidecars: Arc::new(ScopeSidecarBundle {
            lexical: Some(ScopeLexSidecar {
                scope_key: scope_storage_key(&ScopeKey::default()),
                alias_entries: vec![AliasEntry {
                    normalized: "the hero".to_owned(),
                    postings: vec![AliasPosting {
                        entity_id: "entity:hero".to_owned(),
                        document_id: "doc-a".to_owned(),
                        mention_count: 1,
                    }],
                }],
                ..Default::default()
            }),
            er: Some(ErScopePatchSidecar {
                alias_additions: vec![ErAliasAddition {
                    case_id: "alias-case".to_owned(),
                    document_id: "doc-b".to_owned(),
                    entity_id: EntityId("entity:hero".to_owned()),
                    alias_surface: "champion".to_owned(),
                    normalized: "champion".to_owned(),
                    confidence_millis: 900,
                    created_at: 10,
                    mention_id: None,
                }],
                type_overrides: vec![ErTypeOverride {
                    case_id: "type-case".to_owned(),
                    document_id: "doc-b".to_owned(),
                    entity_id: EntityId("entity:hero".to_owned()),
                    kind: EntityKind::Character,
                    confidence_millis: 900,
                    created_at: 11,
                    mention_id: None,
                }],
                entity_links: vec![ErEntityLinkOverride {
                    case_id: "link-case".to_owned(),
                    document_id: "doc-b".to_owned(),
                    mention_id: None,
                    entity_id: EntityId("entity:hero".to_owned()),
                    confidence_millis: 800,
                    created_at: 12,
                }],
                ..Default::default()
            }),
            ..Default::default()
        }),
        indices: Arc::new(ScopeRuntimeIndices::default()),
        archive_segments: Default::default(),
        sidecar_mask: Default::default(),
    };
    let session = SessionArchive {
        session_id: SessionId("session-1".to_owned()),
        document_refs: vec![DocumentRevisionRef {
            document_id: "doc-a".to_owned(),
            scope: ScopeKey::default(),
            scope_ord: Default::default(),
            document_ord: Default::default(),
            revision: 1,
        }],
        ..Default::default()
    };

    let analysis = ScopeAnalysisContext::from_runtime_image(runtime, Some(&session));

    assert_eq!(analysis.document_refs.len(), 1);
    assert_eq!(analysis.entity_profiles.len(), 1);
    let profile = &analysis.entity_profiles[0];
    assert_eq!(profile.document_ids.len(), 2);
    assert_eq!(profile.linked_mention_count, 1);
    assert_eq!(profile.effective_kind, Some(EntityKind::Character));
    assert!(profile.aliases.iter().any(|value| value == "the hero"));
    assert!(profile.aliases.iter().any(|value| value == "champion"));
    assert!(profile
        .continuity_refs
        .iter()
        .any(|value| value == "er_link:link-case"));
}

#[test]
fn analysis_context_builds_relation_indices() {
    let mut archive = sample_archive("doc-a", "entity:left");
    archive.entities.push(SemanticEntityRecord {
        entity_id: EntityId("entity:right".to_owned()),
        canonical_name: "Right".to_owned(),
        aliases: Vec::new(),
        kind: Some(EntityKind::Character),
        mention_count: 1,
        chunk_ids: Vec::new(),
    });
    archive.relations.push(SemanticRelationRecord {
        source_entity_id: EntityId("entity:left".to_owned()),
        target_entity_id: EntityId("entity:right".to_owned()),
        edge_type: "ally_of".to_owned(),
        sentence_index: 0,
        chunk_id: Some("chunk-a".to_owned()),
    });

    let analysis = ScopeAnalysisContext::from_runtime_image(
        ScopeRuntimeImage {
            dirty: DirtyScopeRecord {
                scope: ScopeKey::default(),
                scope_key: scope_storage_key(&ScopeKey::default()),
                ..Default::default()
            },
            manifests: Arc::from([]),
            archives: Arc::from([archive]),
            sidecars: Arc::new(ScopeSidecarBundle::default()),
            indices: Arc::new(ScopeRuntimeIndices::default()),
            archive_segments: Default::default(),
            sidecar_mask: Default::default(),
        },
        None,
    );

    assert_eq!(analysis.persisted_relations.len(), 1);
    assert_eq!(analysis.continuity_hints.len(), 1);
    assert!(analysis
        .raw_archived_relation_keys
        .iter()
        .any(|key| key.edge_type == "ally_of"));
}

fn sample_archive(document_id: &str, entity_id: &str) -> DocumentArchive {
    DocumentArchive {
        manifest: DocumentManifest {
            document_id: document_id.to_owned(),
            scope_key: scope_storage_key(&ScopeKey::default()),
            created_at: 7,
            ..Default::default()
        },
        entities: vec![SemanticEntityRecord {
            entity_id: EntityId(entity_id.to_owned()),
            canonical_name: "Hero".to_owned(),
            aliases: vec!["hero".to_owned()],
            kind: Some(EntityKind::Npc),
            mention_count: 2,
            chunk_ids: vec!["chunk-a".to_owned()],
        }],
        ..Default::default()
    }
}

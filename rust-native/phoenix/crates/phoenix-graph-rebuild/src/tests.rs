use std::collections::BTreeMap;

use phoenix_alex::{AlexSnapshotId, PatternId, SurfaceHit, SurfaceHitKind};
use phoenix_chunker_native::{
    LensChunk, LensKind, LensMentionEdge, LensMentionEdgeKind, LensMentionGraph,
};
use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey, TextRange};
use serde::Deserialize;

use crate::{
    build_graph_rebuild_snapshot, build_snapshot_embedding_target_report,
    compile_dual_write_snapshot, compile_graph_snapshot, compile_legacy_snapshot_strict,
    verify_graph_compile_output, EvidenceAnchor, EvidenceBundleKind, EvidenceKind, FactLane,
    FactRole, GraphAtom, GraphAtomKind, GraphCalendarRegistryBridgeCounters,
    GraphCalendarRegistryBridgeSummary, GraphCalendarRegistryReceipt, GraphChunk,
    GraphCompileReceipts, GraphCompilerInput, GraphCompilerOutput, GraphDocumentCompilerHyperedge,
    GraphDocumentCompilerHyperedgeRole, GraphDocumentCompilerSummary, GraphDocumentConfidence,
    GraphDocumentEvidenceSpan, GraphDocumentSidecarSummary, GraphMention, GraphRebuildInput,
    GraphScopeKind, RelationFact,
};
const PARITY_FIXTURE: &str =
    include_str!("../../../../../src/app/graph-rebuild/fixtures/graph-rebuild-parity-smoke.json");
#[test]
fn builds_chunks_anchors_edges_and_embedding_targets() {
    let text = "Kai watched Hazel. Hazel answered Kai. Rift watched Kai.";
    let entities = vec![
        entry("e-kai", "Kai", &["Captain Kai"]),
        entry("e-hazel", "Hazel", &[]),
        entry("e-rift", "Rift", &[]),
    ];
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:one",
        note_id: "note-1",
        text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 3,
        built_at: Some(10),
    })
    .expect("snapshot");

    assert_eq!(snapshot.schema_version, "phoenix-graph-rebuild/v1");
    assert!(!snapshot.chunks.is_empty());
    assert_eq!(snapshot.counters.accepted_anchors, 6);
    assert_eq!(snapshot.counters.nodes, 3);
    assert_eq!(
        snapshot
            .edges
            .iter()
            .filter(|edge| edge.edge_type == "anchored-cooccurrence")
            .count(),
        3
    );
    assert!(snapshot.counters.edges >= 3);
    assert!(snapshot.counters.relationship_candidates >= 3);
    assert!(snapshot.counters.relationships >= 3);
    assert_eq!(
        snapshot.counters.accepted_relationships + snapshot.counters.review_relationships,
        snapshot.counters.relationships
    );
    assert!(snapshot.relationships.iter().any(
        |relationship| relationship.adjudication_source == "graph-rebuild-cooccurrence-policy"
    ));
    assert!(snapshot
        .relationships
        .iter()
        .any(|relationship| relationship.adjudication_source == "graph-rebuild-typed-cue-policy"));
    assert!(!snapshot.events.is_empty());
    assert!(snapshot.counters.embedding_targets >= snapshot.counters.chunks + 6 + 3);
}

#[test]
fn compiles_legacy_snapshot_into_fact_graph_with_receipts() {
    let text =
        "Kai approved the packet with Tempest because Nemo warned Kai. Tempest stood as Diamond.";
    let entities = vec![
        entry("e-kai", "Kai", &[]),
        entry("e-tempest", "Tempest", &[]),
        entry("e-nemo", "Nemo", &[]),
    ];
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:compiler",
        note_id: "note-compiler",
        text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 3,
        built_at: Some(33),
    })
    .expect("snapshot");

    let compiled = compile_legacy_snapshot_strict(&snapshot).expect("compiled graph");

    assert_eq!(compiled.schema_version, "phoenix-graph-compiler/v1");
    assert_eq!(compiled.receipts.counters.invariant_failures, 0);
    assert!(compiled
        .atoms
        .iter()
        .any(|atom| atom.kind == GraphAtomKind::Entity && atom.source_id == "e-kai"));
    assert!(compiled
        .facts
        .iter()
        .any(|fact| fact.lane == FactLane::RelationshipFact));
    assert!(compiled
        .bundles
        .iter()
        .any(|bundle| bundle.lane == FactLane::CooccurrenceWeak));
    assert!(compiled
        .bundles
        .iter()
        .all(|bundle| !bundle.group_key.is_empty()));
    assert!(compiled.bundles.iter().any(|bundle| matches!(
        bundle.bundle_kind,
        EvidenceBundleKind::Span | EvidenceBundleKind::Neighborhood
    )));
    assert!(!compiled
        .facts
        .iter()
        .any(|fact| fact.lane == FactLane::CooccurrenceWeak));
    assert!(compiled
        .projected_edges
        .iter()
        .filter(|edge| edge.projection_kind == "legacyBinary")
        .all(|edge| edge.source_fact_id.is_some() || edge.source_bundle_id.is_some()));
    assert!(compiled
        .receipts
        .roots
        .iter()
        .any(|root| root.lane == FactLane::AnchorEvidence && root.evidence_anchors > 0));
}

#[test]
fn dual_write_projects_legacy_ui_graph_from_fact_graph() {
    let text = "Kai watched Hazel. Hazel answered Kai. Rift watched Kai.";
    let entities = vec![
        entry("e-kai", "Kai", &["Captain Kai"]),
        entry("e-hazel", "Hazel", &[]),
        entry("e-rift", "Rift", &[]),
    ];
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:dual",
        note_id: "note-dual",
        text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 3,
        built_at: Some(44),
    })
    .expect("snapshot");

    let dual = compile_dual_write_snapshot(&snapshot);

    assert_eq!(dual.legacy_snapshot.id, snapshot.id);
    assert_eq!(dual.receipts, dual.fact_graph.receipts);
    assert!(!dual.fact_graph.bundles.is_empty());
    assert!(dual
        .projected_ui_graph
        .iter()
        .any(|edge| edge.edge_type == "anchored-cooccurrence"));
    assert!(dual
        .projected_ui_graph
        .iter()
        .all(|edge| !edge.evidence_anchor_ids.is_empty()));
}

#[test]
fn dual_write_preserves_calendar_registry_receipts_without_projecting_edges() {
    let text = "Kai watched Hazel.";
    let entities = vec![entry("e-kai", "Kai", &[]), entry("e-hazel", "Hazel", &[])];
    let mut snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:calendar",
        note_id: "note-calendar",
        text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 2,
        built_at: Some(45),
    })
    .expect("snapshot");
    snapshot.edges.clear();
    snapshot.calendar_registry_summary = Some(calendar_summary("note-calendar"));

    let dual = compile_dual_write_snapshot(&snapshot);

    assert!(dual.fact_graph.atoms.iter().any(|atom| {
        atom.kind == GraphAtomKind::TimeAnchor && atom.source_id == "calendar-anchor:event-1"
    }));
    assert!(dual.fact_graph.evidence_anchors.iter().any(|evidence| {
        evidence.kind == EvidenceKind::CalendarRegistry
            && evidence.source_id == "calendar-registry-receipt:event-1"
    }));
    assert!(dual.projected_ui_graph.is_empty());
    assert_eq!(dual.fact_graph.receipts.counters.invariant_failures, 0);
}

#[test]
fn dual_write_compiles_only_reviewed_document_situations_to_hyperedges() {
    let text = "Kai gave Hazel the key.";
    let entities = vec![entry("e-kai", "Kai", &[]), entry("e-hazel", "Hazel", &[])];
    let mut snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:document-situation",
        note_id: "note-situation",
        text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 2,
        built_at: Some(46),
    })
    .expect("snapshot");
    snapshot.document_sidecar_summary = Some(GraphDocumentSidecarSummary {
        evidence_spans: vec![GraphDocumentEvidenceSpan {
            id: "evidence:situation:1".into(),
            note_id: "note-situation".into(),
            unit_id: None,
            chunk_id: Some("note-situation:chunk:0".into()),
            start: 0,
            end: text.len() as u32,
            preview: None,
            confidence: GraphDocumentConfidence { score: 0.91 },
        }],
        ..GraphDocumentSidecarSummary::default()
    });
    snapshot.document_compiler_summary = Some(GraphDocumentCompilerSummary {
        hyperedges: vec![
            situation_hyperedge("h-good", "situation:good", Vec::new()),
            situation_hyperedge(
                "h-conflict",
                "situation:conflict",
                vec!["conflict:1".into()],
            ),
        ],
    });

    let dual = compile_dual_write_snapshot(&snapshot);
    let fact = dual
        .fact_graph
        .facts
        .iter()
        .find(|fact| fact.semantic_situation_id.as_deref() == Some("situation:good"))
        .expect("compiled semantic situation fact");

    assert_eq!(fact.predicate, "transfer_possession");
    assert_eq!(fact.semantic_frame.as_deref(), Some("transfer_possession"));
    assert_eq!(fact.factuality.as_deref(), Some("asserted"));
    assert!(dual
        .fact_graph
        .roles
        .iter()
        .any(|role| role.fact_id == fact.id
            && role.semantic_role.as_deref() == Some("actor")
            && role.slot_type.as_deref() == Some("participant")
            && role.resolved == Some(true)));
    assert!(!dual
        .fact_graph
        .facts
        .iter()
        .any(|fact| fact.semantic_situation_id.as_deref() == Some("situation:conflict")));
    assert_eq!(
        dual.fact_graph.receipts.counters.invariant_failures, 0,
        "{:?}",
        dual.fact_graph.receipts.invariant_failures
    );
}

#[test]
fn compiles_prepared_artifacts_without_legacy_rescan() {
    let note_ids = vec!["note-prepared".into()];
    let chunks = vec![GraphChunk {
        id: "chunk-prepared-1".into(),
        note_id: "note-prepared".into(),
        start: 0,
        end: 16,
        ordinal: 0,
        source: "prepared".into(),
    }];
    let mentions = vec![
        GraphMention {
            id: "1".into(),
            note_id: "note-prepared".into(),
            chunk_id: Some("chunk-prepared-1".into()),
            surface: "Aella".into(),
            source_start: 0,
            source_end: 5,
            source: "prepared-ner".into(),
            confidence: 0.95,
            entity_id: None,
            status: "accepted".into(),
        },
        GraphMention {
            id: "2".into(),
            note_id: "note-prepared".into(),
            chunk_id: Some("chunk-prepared-1".into()),
            surface: "Kai".into(),
            source_start: 10,
            source_end: 13,
            source: "prepared-ner".into(),
            confidence: 0.94,
            entity_id: None,
            status: "accepted".into(),
        },
    ];
    let surface_hits = vec![SurfaceHit {
        snapshot_id: AlexSnapshotId(7),
        pattern_id: PatternId(10_011),
        kind: SurfaceHitKind::RelationCue,
        source_range: TextRange { start: 6, end: 9 },
        normalized_range: TextRange { start: 0, end: 8 },
        surface: "met".into(),
        normalized: "approved".into(),
        confidence: 1.0,
    }];
    let mention_graph = LensMentionGraph {
        edges: vec![
            LensMentionEdge {
                left: 1,
                right: 2,
                kind: LensMentionEdgeKind::DependencyCoreArgument,
                weight: 0.91,
            },
            LensMentionEdge {
                left: 1,
                right: 2,
                kind: LensMentionEdgeKind::SameNormalizedSurface,
                weight: 0.77,
            },
        ],
    };
    let lens_frames = vec![LensChunk {
        id: "lens-relationship-prepared".into(),
        lens: LensKind::Relationship,
        start: 0,
        end: 16,
        base_chunk_start: 0,
        base_chunk_end: 1,
        sentence_start: 0,
        sentence_end: 1,
        mention_ids: vec![1, 2],
        surfaces: vec!["aella".into(), "kai".into()],
        trigger_terms: vec!["approved".into()],
        surface_hit_ids: vec!["cue-rel".into()],
        cue_hit_ids: vec!["cue-rel".into()],
        source_hint_ids: Vec::new(),
        content_hash: 42,
    }];

    let compiled = compile_graph_snapshot(GraphCompilerInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:prepared",
        built_at: 99,
        note_ids: &note_ids,
        chunks: &chunks,
        surface_hits: &surface_hits,
        mentions: &mentions,
        mention_graph: Some(&mention_graph),
        lens_frames: &lens_frames,
        entity_anchors: &[],
        nodes: &[],
        relationships: &[],
        events: &[],
        temporal_edges: &[],
        causal_edges: &[],
        memory_state: &[],
        calendar_registry: None,
        document_sidecar: None,
        document_compiler: None,
        legacy_edges: &[],
        bundle_compression: None,
        bundle_commitment: None,
    });

    assert_eq!(compiled.receipts.counters.invariant_failures, 0);
    assert!(compiled
        .evidence_anchors
        .iter()
        .any(|evidence| evidence.kind == EvidenceKind::CueHit));
    assert!(compiled
        .evidence_anchors
        .iter()
        .any(|evidence| evidence.kind == EvidenceKind::LensFrame));
    assert!(compiled
        .evidence_anchors
        .iter()
        .any(|evidence| evidence.kind == EvidenceKind::MentionGraphEdge));
    assert!(compiled
        .atoms
        .iter()
        .any(|atom| atom.kind == GraphAtomKind::DocumentRoot));
    assert!(compiled
        .atoms
        .iter()
        .any(|atom| atom.kind == GraphAtomKind::LaneRoot));
    assert!(compiled
        .atoms
        .iter()
        .any(|atom| atom.kind == GraphAtomKind::Frame));
    assert!(compiled
        .atoms
        .iter()
        .any(|atom| atom.kind == GraphAtomKind::RelationFact));
    assert!(compiled.roles.iter().any(|role| role.role == "leftMention"));
    assert!(compiled
        .roles
        .iter()
        .any(|role| role.role == "rightMention"));
    assert!(compiled
        .projected_edges
        .iter()
        .any(|edge| edge.projection_kind == "mentionGraph"));
    assert!(!compiled
        .facts
        .iter()
        .any(|fact| fact.lane == FactLane::CooccurrenceWeak));
    assert!(compiled.bundles.iter().any(|bundle| {
        bundle.bundle_kind == EvidenceBundleKind::ShadowIdentity
            && bundle.lane == FactLane::CooccurrenceWeak
    }));
    assert!(compiled
        .bundles
        .iter()
        .any(|bundle| bundle.bundle_kind == EvidenceBundleKind::Frame));
    assert!(compiled
        .projected_edges
        .iter()
        .any(|edge| edge.projection_kind == "mentionGraph" && edge.source_bundle_id.is_some()));
}

#[test]
fn rejects_roles_that_target_the_wrong_layer() {
    let output = GraphCompilerOutput {
        schema_version: "phoenix-graph-compiler/v1".into(),
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:bad-role".into(),
        built_at: 1,
        atoms: vec![GraphAtom {
            id: "atom:entity:e-kai".into(),
            kind: GraphAtomKind::Entity,
            source_id: "e-kai".into(),
            label: "Kai".into(),
            note_id: None,
            chunk_id: None,
            entity_id: Some(EntityId("e-kai".into())),
            evidence_ids: vec!["evidence:anchor:kai".into()],
        }],
        evidence_anchors: vec![EvidenceAnchor {
            id: "evidence:anchor:kai".into(),
            kind: EvidenceKind::SourceSpan,
            note_id: None,
            chunk_id: None,
            source_range: None,
            source_id: "anchor:kai".into(),
            confidence: 0.8,
        }],
        bundles: Vec::new(),
        facts: vec![RelationFact {
            id: "fact:bad-role".into(),
            lane: FactLane::RelationshipFact,
            predicate: "knows".into(),
            source_record_id: "rel:bad-role".into(),
            status: "accepted".into(),
            evidence_ids: vec!["evidence:anchor:kai".into()],
            confidence: 0.8,
            semantic_situation_id: None,
            semantic_frame: None,
            factuality: None,
            state_interval_ids: Vec::new(),
            event_ordering_ids: Vec::new(),
            temporal_conflict_ids: Vec::new(),
        }],
        roles: vec![
            FactRole {
                fact_id: "fact:bad-role".into(),
                role: "source".into(),
                atom_id: "atom:entity:e-kai".into(),
                confidence: 0.8,
                semantic_role: None,
                slot_type: None,
                required: None,
                resolved: None,
            },
            FactRole {
                fact_id: "fact:bad-role".into(),
                role: "target".into(),
                atom_id: "atom:entity:e-kai".into(),
                confidence: 0.8,
                semantic_role: None,
                slot_type: None,
                required: None,
                resolved: None,
            },
            FactRole {
                fact_id: "fact:bad-role".into(),
                role: "evidence".into(),
                atom_id: "atom:entity:e-kai".into(),
                confidence: 0.8,
                semantic_role: None,
                slot_type: None,
                required: None,
                resolved: None,
            },
        ],
        projected_edges: Vec::new(),
        receipts: GraphCompileReceipts::default(),
    };

    let receipts = verify_graph_compile_output(&output);
    assert!(receipts
        .invariant_failures
        .iter()
        .any(|failure| failure.contains("illegal target")));
}

#[test]
fn reports_empty_reasons_without_inventing_nodes() {
    let text = "No known names here.";
    let entities = vec![entry("e-kai", "Kai", &[])];
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:empty",
        note_id: "note-1",
        text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 0,
        built_at: Some(11),
    })
    .expect("snapshot");

    assert_eq!(snapshot.counters.accepted_anchors, 0);
    assert_eq!(snapshot.counters.nodes, 0);
    assert_eq!(snapshot.counters.edges, 0);
}

#[test]
fn matches_shared_frontend_structural_parity_fixture() {
    let fixture: ParityFixture = serde_json::from_str(PARITY_FIXTURE).expect("parity fixture json");
    let entities = fixture
        .entities
        .iter()
        .map(entry_from_fixture)
        .collect::<Vec<_>>();
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: fixture.scope_kind,
        scope_id: &fixture.scope_id,
        note_id: &fixture.note_id,
        text: &fixture.text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 0,
        built_at: Some(fixture.built_at),
    })
    .expect("snapshot");

    let digest = structural_digest(&snapshot);
    assert_eq!(digest.relationships, fixture.expected.relationships);
    assert_eq!(digest.event_count, fixture.expected.event_count);
    assert_eq!(
        digest.memory_state_count,
        fixture.expected.memory_state_count
    );
    assert_eq!(
        digest.embedding_target_kind_counts,
        fixture.native_embedding_target_kind_counts
    );
}

fn entry(id: &str, label: &str, aliases: &[&str]) -> LexiconEntry {
    LexiconEntry {
        entity_id: EntityId(id.to_owned()),
        label: label.to_owned(),
        aliases: aliases.iter().map(|alias| (*alias).to_owned()).collect(),
        kind: Some(EntityKind::Character),
        scope: ScopeKey::default(),
        ..LexiconEntry::default()
    }
}

fn entry_from_fixture(entity: &FixtureEntity) -> LexiconEntry {
    LexiconEntry {
        entity_id: EntityId(entity.id.clone()),
        label: entity.label.clone(),
        aliases: entity.aliases.clone(),
        kind: Some(parse_kind(&entity.kind)),
        scope: ScopeKey::default(),
        ..LexiconEntry::default()
    }
}

fn calendar_summary(note_id: &str) -> GraphCalendarRegistryBridgeSummary {
    GraphCalendarRegistryBridgeSummary {
        schema_version: "phoenix-calendar-registry-bridge/v1".into(),
        generated_at: 45,
        source_snapshot_id: "snapshot:calendar".into(),
        source_calendar_registry_id: "calendar-registry:test".into(),
        calendar_id: "calendar:test".into(),
        calendar_fingerprint: "calendar:fingerprint:test".into(),
        calendar_mode: "customOrdinal".into(),
        scope_kind: "note".into(),
        scope_id: "note:calendar".into(),
        receipts: vec![GraphCalendarRegistryReceipt {
            id: "calendar-registry-receipt:event-1".into(),
            calendar_anchor_id: "calendar-anchor:event-1".into(),
            source_kind: "user_calendar_event".into(),
            source_id: "event-1".into(),
            status: "accepted_temporal_receipt".into(),
            date_key: "cal:calendar:test|era:era-1|y:1|m:0|d:0".into(),
            normalized_value: "CAL:calendar:test:cal:calendar:test|era:era-1|y:1|m:0|d:0".into(),
            display_date: "Month 1 1, 1 CE".into(),
            ordinal: 0,
            end_ordinal: None,
            real_epoch_ms: None,
            real_interval_end_ms: None,
            source_note_ids: vec![note_id.into()],
            evidence_refs: vec!["calendar:event:event-1".into()],
            affected_graph_atoms: vec!["calendar-atom:calendar-anchor:event-1".into()],
            affected_graph_facts: Vec::new(),
            reversible: true,
            mutation_allowed: false,
            rationale: "calendar receipt fixture".into(),
        }],
        counters: GraphCalendarRegistryBridgeCounters {
            anchor_count: 1,
            receipt_count: 1,
            accepted_temporal_receipts: 1,
            custom_ordinal_receipts: 1,
            event_receipts: 1,
            ..GraphCalendarRegistryBridgeCounters::default()
        },
    }
}

fn situation_hyperedge(
    id: &str,
    situation_id: &str,
    temporal_conflict_ids: Vec<compact_str::CompactString>,
) -> GraphDocumentCompilerHyperedge {
    GraphDocumentCompilerHyperedge {
        id: id.into(),
        predicate: "transfer_possession".into(),
        trigger_predicate: Some("gave".into()),
        frame: Some("transfer_possession".into()),
        frame_family: Some("transfer".into()),
        situation_kind: Some("event".into()),
        factuality: Some("asserted".into()),
        speech_act: Some("assertive".into()),
        semantic_situation_id: Some(situation_id.into()),
        semantic_proposition_id: None,
        state_interval_ids: Vec::new(),
        event_ordering_ids: Vec::new(),
        temporal_conflict_ids,
        compilation_basis: Some("semantic_situation_frame".into()),
        roles: vec![
            document_hyperedge_role("role-actor", "actor", "e-kai", "entity", "Kai"),
            document_hyperedge_role("role-recipient", "recipient", "e-hazel", "entity", "Hazel"),
            document_hyperedge_role("role-theme", "theme", "key", "entity_mention", "the key"),
            document_hyperedge_role(
                "role-evidence",
                "evidence",
                "evidence:situation:1",
                "evidence_span",
                "evidence",
            ),
        ],
        evidence_span_ids: vec!["evidence:situation:1".into()],
        confidence: 0.91,
        status: "pending_commit".into(),
        provenance: None,
    }
}

#[test]
fn admitted_input_targets_bypass_native_candidate_expansion() {
    let entities = vec![entry("e-kai", "Kai", &[])];
    let mut snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:admission",
        note_id: "note-admission",
        text: "Kai approved the packet.",
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 1,
        built_at: Some(10),
    })
    .expect("snapshot");
    snapshot.embedding_targets.truncate(2);

    let report = build_snapshot_embedding_target_report(&snapshot);

    assert_eq!(report.targets.len(), 2);
    assert_eq!(
        report
            .originating_families
            .iter()
            .map(|row| row.targets)
            .sum::<usize>(),
        2
    );
}

fn document_hyperedge_role(
    id: &str,
    role: &str,
    target_id: &str,
    target_kind: &str,
    surface: &str,
) -> GraphDocumentCompilerHyperedgeRole {
    GraphDocumentCompilerHyperedgeRole {
        id: id.into(),
        role: role.into(),
        semantic_role: Some(role.into()),
        slot_type: Some(
            if role == "evidence" {
                "evidence"
            } else {
                "participant"
            }
            .into(),
        ),
        target_id: target_id.into(),
        target_kind: target_kind.into(),
        surface: Some(surface.into()),
        confidence: 0.9,
        required: Some(true),
        resolved: Some(target_kind == "entity" || target_kind == "evidence_span"),
    }
}

fn parse_kind(kind: &str) -> EntityKind {
    match kind.to_ascii_lowercase().as_str() {
        "location" => EntityKind::Location,
        "item" => EntityKind::Item,
        "faction" => EntityKind::Faction,
        "organization" => EntityKind::Organization,
        "event" => EntityKind::Event,
        "concept" => EntityKind::Concept,
        "npc" => EntityKind::Npc,
        _ => EntityKind::Character,
    }
}

fn structural_digest(snapshot: &crate::GraphRebuildSnapshot) -> StructuralDigest {
    let mut relationships = snapshot
        .relationships
        .iter()
        .map(|relationship| RelationshipDigest {
            id: relationship.id.to_string(),
            relation_type: relationship.relation_type.to_string(),
            status: relationship.status.to_string(),
        })
        .collect::<Vec<_>>();
    relationships.sort();

    StructuralDigest {
        relationships,
        event_count: snapshot.events.len(),
        memory_state_count: snapshot.memory_state.len(),
        embedding_target_kind_counts: kind_counts(snapshot),
    }
}

fn kind_counts(snapshot: &crate::GraphRebuildSnapshot) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::new();
    for target in &snapshot.embedding_targets {
        *counts.entry(target.kind.to_string()).or_default() += 1;
    }
    counts
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ParityFixture {
    note_id: String,
    scope_kind: GraphScopeKind,
    scope_id: String,
    built_at: u64,
    text: String,
    entities: Vec<FixtureEntity>,
    native_embedding_target_kind_counts: BTreeMap<String, usize>,
    expected: StructuralDigest,
}

#[derive(Debug, Deserialize)]
struct FixtureEntity {
    id: String,
    label: String,
    kind: String,
    aliases: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
struct StructuralDigest {
    relationships: Vec<RelationshipDigest>,
    event_count: usize,
    memory_state_count: usize,
    embedding_target_kind_counts: BTreeMap<String, usize>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "camelCase")]
struct RelationshipDigest {
    id: String,
    relation_type: String,
    status: String,
}

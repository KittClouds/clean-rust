use compact_str::CompactString;
use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};

use crate::{
    assert_memory_governance_candidate_only, build_graph_rebuild_snapshot,
    build_memory_governance_candidates, build_memory_governance_retrieval_preview,
    GraphAnchor, GraphChunk, GraphEpisode, GraphEvent, GraphMemoryGovernanceAction,
    GraphMemoryGovernanceCandidate, GraphMemoryGovernanceTargetKind, GraphMemoryState,
    GraphRebuildInput, GraphRelationship, GraphScopeKind, GraphTemporalEdge,
    MemoryGovernanceEngineInput, MemoryGovernanceRetrievalCandidate,
    MemoryGovernanceRetrievalPreviewInput, MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT,
};

#[test]
fn adversarial_contradiction_quarantines_local_state_conflict() {
    let kai = entity("kai");
    let mut fixture = GovernanceFixture::new(vec![chunk("chunk:0", 0)]);
    fixture.anchors = vec![
        anchor("anchor:kai:approved", &kai, "chunk:0"),
        anchor("anchor:kai:rejected", &kai, "chunk:0"),
    ];
    fixture.memory_state = vec![
        state("memory:approved", &kai, "decision_state", "approved", "anchor:kai:approved"),
        state("memory:rejected", &kai, "decision_state", "rejected", "anchor:kai:rejected"),
    ];

    let rows = run_governance(&fixture);
    let row = row_for(&rows, "chunk:0");

    assert_eq!(row.action, GraphMemoryGovernanceAction::Quarantine);
    assert_eq!(row.reason, "target_has_contradictory_memory_evidence");
    assert!(row.signals.contradiction_risk >= 0.50);
    assert_has_rationale(row, "audit:state_conflict");
    assert_candidate_only(&rows);
}

#[test]
fn adversarial_supersession_attenuates_only_the_older_state() {
    let kai = entity("kai");
    let mut fixture = GovernanceFixture::new(vec![chunk("chunk:old", 0), chunk("chunk:new", 1)]);
    fixture.anchors = vec![
        anchor("anchor:kai:old", &kai, "chunk:old"),
        anchor("anchor:kai:new", &kai, "chunk:new"),
    ];
    fixture.memory_state = vec![
        state("memory:old", &kai, "decision_state", "approved", "anchor:kai:old"),
        state("memory:new", &kai, "decision_state", "rejected", "anchor:kai:new"),
    ];

    let rows = run_governance(&fixture);
    let older = row_for(&rows, "chunk:old");
    let newer = row_for(&rows, "chunk:new");

    assert_eq!(older.action, GraphMemoryGovernanceAction::Attenuate);
    assert_eq!(older.reason, "target_superseded_by_later_memory_evidence");
    assert_eq!(older.signals.contradiction_risk, 0.0);
    assert!(older.signals.age >= 0.50);
    assert_has_rationale(older, "audit:state_supersession");
    assert_ne!(newer.action, GraphMemoryGovernanceAction::Attenuate);
    assert_candidate_only(&rows);
}

#[test]
fn adversarial_pinned_memory_survives_decay_and_quarantine_pressure() {
    let kai = entity("kai");
    let mut fixture = GovernanceFixture::new(vec![chunk("chunk:pinned", 0)]);
    fixture.anchors = vec![
        anchor("anchor:kai:pin", &kai, "chunk:pinned"),
        anchor("anchor:kai:approved", &kai, "chunk:pinned"),
        anchor("anchor:kai:rejected", &kai, "chunk:pinned"),
    ];
    fixture.memory_state = vec![
        state("memory:pin", &kai, "user_pinned", "true", "anchor:kai:pin"),
        state("memory:approved", &kai, "decision_state", "approved", "anchor:kai:approved"),
        state("memory:rejected", &kai, "decision_state", "rejected", "anchor:kai:rejected"),
    ];

    let rows = run_governance(&fixture);
    let row = row_for(&rows, "chunk:pinned");

    assert_eq!(row.action, GraphMemoryGovernanceAction::Retain);
    assert_eq!(row.reason, "target_user_pinned_memory");
    assert!(row.signals.user_pinned);
    assert_has_rationale(row, "audit:user_pinned");
    assert_candidate_only(&rows);
}

#[test]
fn adversarial_celebrity_dominance_quarantines_opaque_copresence() {
    let kai = entity("kai");
    let rift = entity("rift");
    let mut fixture = GovernanceFixture::new((0..5).map(|index| {
        chunk(&format!("chunk:{index}"), index)
    }).collect());
    for index in 0..5 {
        fixture.anchors.push(anchor(&format!("anchor:kai:{index}"), &kai, &format!("chunk:{index}")));
        fixture.anchors.push(anchor(&format!("anchor:rift:{index}"), &rift, &format!("chunk:{index}")));
    }

    let rows = run_governance(&fixture);
    let row = row_for(&rows, "chunk:3");

    assert_eq!(row.action, GraphMemoryGovernanceAction::Quarantine);
    assert_eq!(row.reason, "chunk_entity_salience_dominated_by_celebrity_surface");
    assert!(row.signals.evidence_strength <= 0.50);
    assert_has_rationale(row, "audit:celebrity_entity_dominance");
    assert_candidate_only(&rows);
}

#[test]
fn adversarial_weak_evidence_pressure_is_auditable() {
    let kai = entity("kai");
    let rift = entity("rift");
    let mut fixture = GovernanceFixture::new((0..4).map(|index| {
        chunk(&format!("weak:{index}"), index)
    }).collect());
    for index in 0..4 {
        fixture.anchors.push(anchor(&format!("anchor:kai:weak:{index}"), &kai, &format!("weak:{index}")));
        fixture.anchors.push(anchor(&format!("anchor:rift:weak:{index}"), &rift, &format!("weak:{index}")));
    }

    let rows = run_governance(&fixture);
    let row = row_for(&rows, "weak:0");

    assert_eq!(row.action, GraphMemoryGovernanceAction::Quarantine);
    assert!(row.rationale.iter().any(|value| value.as_str().starts_with("audit:weak_evidence:")));
    assert_eq!(row.evidence_ids.len(), 2);
    assert_candidate_only(&rows);
}

#[test]
fn adversarial_compression_dominance_is_report_only_and_score_capped() {
    let kai = entity("kai");
    let mut fixture = GovernanceFixture::new(vec![
        chunk("episode:chunk:0", 0),
        chunk("episode:chunk:1", 1),
        chunk("episode:chunk:2", 2),
    ]);
    for index in 0..3 {
        let event_id = format!("event:{index}");
        let chunk_id = format!("episode:chunk:{index}");
        let anchor_id = format!("anchor:kai:event:{index}");
        fixture.anchors.push(anchor(&anchor_id, &kai, &chunk_id));
        fixture.events.push(event(&event_id, &chunk_id, &[kai.clone()], &[&anchor_id]));
    }
    fixture.episodes.push(GraphEpisode {
        id: "episode:dominant".into(),
        note_id: "note:adversarial".into(),
        event_ids: vec!["event:0".into(), "event:1".into(), "event:2".into()],
        entity_ids: vec![kai],
        label: "Dominant episode".into(),
    });

    let rows = run_governance(&fixture);
    let episode = row_for(&rows, "episode:dominant");
    let retrieval = vec![retrieval("hit:episode", "episode:dominant", GraphMemoryGovernanceTargetKind::Episode, 0.97)];
    let preview = build_memory_governance_retrieval_preview(MemoryGovernanceRetrievalPreviewInput {
        retrieval_candidates: &retrieval,
        governance_candidates: &rows,
    });
    let preview_row = &preview.rows[0];

    assert_eq!(episode.action, GraphMemoryGovernanceAction::Compress);
    assert!(preview.no_topology_commit);
    assert!(preview_row.no_topology_commit);
    assert!(preview_row.adjusted_score <= 1.0);
    assert!(preview_row.score_delta <= 0.03);
}

#[test]
fn adversarial_negative_relation_stays_review_only() {
    let entities = vec![lexicon("e-kai", "Kai"), lexicon("e-hazel", "Hazel")];
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:negative-adversarial",
        note_id: "note-negative-adversarial",
        text: "Kai betrays Hazel.",
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 2,
        built_at: Some(17),
    })
    .expect("negative relation fixture");
    let row = snapshot.relationships.iter().find(|row| row.relation_type == "betrays").expect("review row");

    assert_eq!(row.status, "review");
    assert_eq!(row.adjudication_source, "graph-rebuild-negative-cue-review-policy");
    assert!(row.rationale.contains("requires confirmation"));
    assert!(snapshot.edges.iter().all(|edge| edge.edge_type != "betrays"));
}

#[derive(Default)]
struct GovernanceFixture {
    chunks: Vec<GraphChunk>,
    episodes: Vec<GraphEpisode>,
    anchors: Vec<GraphAnchor>,
    relationships: Vec<GraphRelationship>,
    events: Vec<GraphEvent>,
    temporal_edges: Vec<GraphTemporalEdge>,
    causal_edges: Vec<GraphTemporalEdge>,
    memory_state: Vec<GraphMemoryState>,
}

impl GovernanceFixture {
    fn new(chunks: Vec<GraphChunk>) -> Self {
        Self { chunks, ..Self::default() }
    }

    fn input(&self) -> MemoryGovernanceEngineInput<'_> {
        MemoryGovernanceEngineInput {
            chunks: &self.chunks,
            episodes: &self.episodes,
            anchors: &self.anchors,
            relationships: &self.relationships,
            events: &self.events,
            temporal_edges: &self.temporal_edges,
            causal_edges: &self.causal_edges,
            memory_state: &self.memory_state,
        }
    }
}

fn run_governance(fixture: &GovernanceFixture) -> Vec<GraphMemoryGovernanceCandidate> {
    build_memory_governance_candidates(fixture.input())
}

fn assert_candidate_only(rows: &[GraphMemoryGovernanceCandidate]) {
    assert_memory_governance_candidate_only(rows).expect("candidate-only governance rows");
    assert!(rows.iter().all(|row| row.no_topology_commit));
    assert!(rows.iter().all(|row| row.rationale.iter().any(|value| value == MEMORY_GOVERNANCE_NO_TOPOLOGY_COMMIT)));
}

fn row_for<'a>(rows: &'a [GraphMemoryGovernanceCandidate], target_id: &str) -> &'a GraphMemoryGovernanceCandidate {
    rows.iter().find(|row| row.target_id == target_id).expect("governance target")
}

fn assert_has_rationale(row: &GraphMemoryGovernanceCandidate, rationale: &str) {
    assert!(row.rationale.iter().any(|value| value == rationale), "{:?}", row.rationale);
}

fn chunk(id: &str, ordinal: u32) -> GraphChunk {
    GraphChunk {
        id: id.into(),
        note_id: "note:adversarial".into(),
        start: ordinal * 10,
        end: ordinal * 10 + 8,
        ordinal,
        source: "adversarial-fixture".into(),
    }
}

fn anchor(id: &str, entity_id: &EntityId, chunk_id: &str) -> GraphAnchor {
    GraphAnchor {
        id: id.into(),
        entity_id: entity_id.clone(),
        note_id: "note:adversarial".into(),
        chunk_id: Some(chunk_id.into()),
        surface: "entity".into(),
        source_start: 0,
        source_end: 6,
        source: "adversarial-fixture".into(),
        confidence: 1.0,
        generation: 1,
    }
}

fn state(id: &str, entity_id: &EntityId, key: &str, value: &str, evidence_id: &str) -> GraphMemoryState {
    GraphMemoryState {
        id: id.into(),
        entity_id: entity_id.clone(),
        note_id: Some("note:adversarial".into()),
        key: key.into(),
        value: value.into(),
        evidence_ids: vec![evidence_id.into()],
    }
}

fn event(id: &str, chunk_id: &str, entity_ids: &[EntityId], evidence_ids: &[&str]) -> GraphEvent {
    GraphEvent {
        id: id.into(),
        note_id: "note:adversarial".into(),
        chunk_id: Some(chunk_id.into()),
        label: "event".into(),
        entity_ids: entity_ids.to_vec(),
        evidence_anchor_ids: evidence_ids.iter().map(|value| CompactString::from(*value)).collect(),
        confidence: 0.82,
    }
}

fn retrieval(
    id: &str,
    target_id: &str,
    target_kind: GraphMemoryGovernanceTargetKind,
    score: f32,
) -> MemoryGovernanceRetrievalCandidate {
    MemoryGovernanceRetrievalCandidate {
        id: id.into(),
        target_id: target_id.into(),
        target_kind,
        score,
    }
}

fn entity(id: &str) -> EntityId {
    EntityId(format!("character:{id}"))
}

fn lexicon(id: &str, surface: &str) -> LexiconEntry {
    LexiconEntry {
        entity_id: EntityId(id.to_owned()),
        label: surface.to_owned(),
        aliases: Vec::new(),
        kind: Some(EntityKind::Character),
        scope: ScopeKey::default(),
        ..LexiconEntry::default()
    }
}

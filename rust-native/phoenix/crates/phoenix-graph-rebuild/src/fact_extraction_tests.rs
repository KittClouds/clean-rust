use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};

use crate::{build_graph_rebuild_snapshot, GraphRebuildInput, GraphScopeKind};

#[test]
fn emits_memory_state_and_graph_fact_targets() {
    let text =
        "Tempest stood as Diamond. Kai approved the packet with Tempest because Nemo warned Kai.";
    let entities = vec![
        entry("e-kai", "Kai"),
        entry("e-tempest", "Tempest"),
        entry("e-nemo", "Nemo"),
    ];
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "note:facts",
        note_id: "note-2",
        text,
        scope: ScopeKey::default(),
        entities: &entities,
        candidate_count: 3,
        built_at: Some(12),
    })
    .expect("snapshot");

    assert!(snapshot.counters.events > 0);
    assert!(snapshot.counters.memory_state > 0);
    assert!(snapshot
        .relationships
        .iter()
        .any(|relationship| relationship.relation_type == "approves_or_accepts"));
    assert!(snapshot
        .embedding_targets
        .iter()
        .any(|target| target.kind == "memoryState"));
}

fn entry(id: &str, surface: &str) -> LexiconEntry {
    LexiconEntry {
        entity_id: EntityId(id.to_owned()),
        label: surface.to_owned(),
        aliases: Vec::new(),
        kind: Some(EntityKind::Character),
        scope: ScopeKey::default(),
        ..LexiconEntry::default()
    }
}

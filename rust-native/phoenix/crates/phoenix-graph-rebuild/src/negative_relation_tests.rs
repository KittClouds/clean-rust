use phoenix_types::{EntityId, EntityKind, LexiconEntry, ScopeKey};

use crate::{build_graph_rebuild_snapshot, GraphRebuildInput, GraphScopeKind};

#[test]
fn emits_negative_relation_cues_as_review_only_candidates() {
    let cases = [
        ("opposes", "Kai opposes Hazel."),
        ("threatens", "Kai threatens Hazel."),
        ("betrays", "Kai betrays Hazel."),
        ("rejects", "Kai rejects Hazel."),
    ];

    for (relation_type, text) in cases {
        let entities = vec![entry("e-kai", "Kai"), entry("e-hazel", "Hazel")];
        let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
            scope_kind: GraphScopeKind::Note,
            scope_id: "note:negative-rel",
            note_id: "note-negative-rel",
            text,
            scope: ScopeKey::default(),
            entities: &entities,
            candidate_count: 2,
            built_at: Some(13),
        })
        .expect("snapshot");

        let row = snapshot
            .relationships
            .iter()
            .find(|relationship| relationship.relation_type == relation_type)
            .expect("negative relation review row");

        assert_eq!(row.status, "review");
        assert_eq!(
            row.adjudication_source,
            "graph-rebuild-negative-cue-review-policy"
        );
        assert!(row.rationale.contains("requires confirmation"));
        assert!(snapshot
            .edges
            .iter()
            .all(|edge| edge.edge_type != relation_type));
    }
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

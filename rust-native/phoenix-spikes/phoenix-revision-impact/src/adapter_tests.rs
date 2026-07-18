use phoenix_graph_rebuild::{
    build_document_semantic_summary, build_graph_rebuild_snapshot, build_story_continuity_contract,
    DocumentSemanticInput, DocumentSemanticRequest, GraphRebuildInput, GraphScopeKind,
    StoryContinuityDocument, StoryContinuityInput,
};
use phoenix_types::ScopeKey;

use super::*;
use crate::resolve_revision_identity;

fn contract(text: &str) -> StoryContinuityContract {
    let snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "revision-identity-fixture",
        note_id: "note:manuscript",
        text,
        scope: ScopeKey::default(),
        entities: &[],
        candidate_count: 0,
        built_at: Some(42),
    })
    .expect("graph snapshot");
    let semantic = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note:manuscript".to_owned(),
            text: text.to_owned(),
        }],
        entities: Vec::new(),
    });
    build_story_continuity_contract(StoryContinuityInput {
        snapshot: &snapshot,
        documents: &[StoryContinuityDocument {
            note_id: "note:manuscript".into(),
            text: text.to_owned(),
        }],
        semantic_summary: Some(&semantic),
        bridge_candidates: &[],
    })
}

fn long_scene(subject: &str, object: &str) -> String {
    [
        "opened", "crossed", "examined", "sealed", "measured", "guarded", "mapped", "left",
    ]
    .into_iter()
        .enumerate()
        .map(|(index, action)| {
            format!(
                "{subject} {action} the {object} at marker {index}. Hazel recorded the distinct action for the witnesses. "
            )
        })
        .collect()
}

#[test]
fn real_story_contract_survives_insertions_before_and_inside_scene() {
    let arrival = long_scene("Kai", "amber gate");
    let departure = long_scene("Kai", "northern gate");
    let original = format!("# Arrival\n{arrival}\n\n# Departure\n{departure}");
    let inserted_before = format!(
        "A preface that shifts every later source offset.\n\n# Arrival\n{arrival}\n\n# Departure\n{departure}"
    );
    let inserted_inside = format!(
        "# Arrival\n{arrival}\nA bell rang without changing the event.\n\n# Departure\n{departure}"
    );
    let original = story_continuity_identity_snapshot(1, &contract(&original));

    for edited in [inserted_before, inserted_inside] {
        let edited = story_continuity_identity_snapshot(2, &contract(&edited));
        let identity = resolve_revision_identity(&original, &edited).expect("identity");
        assert!(
            identity.scene_matches.len() + identity.splits.len() >= 2,
            "both source scenes must retain an explicit identity outcome: {identity:#?}"
        );
        assert!(
            identity.event_matches.len() >= 8,
            "event reconciliation must survive source offsets: {identity:#?}"
        );
    }
}

#[test]
fn real_story_contract_append_preserves_existing_scenes() {
    let arrival = long_scene("Kai", "amber gate");
    let departure = long_scene("Kai", "northern gate");
    let original = format!("# Arrival\n{arrival}\n\n# Departure\n{departure}");
    let appended = format!(
        "{original}\n\n# Return\n{}",
        long_scene("Hazel", "return passage")
    );
    let original = story_continuity_identity_snapshot(1, &contract(&original));
    let appended = story_continuity_identity_snapshot(2, &contract(&appended));
    let identity = resolve_revision_identity(&original, &appended).expect("identity");

    assert_eq!(
        identity.scene_matches.len(),
        2,
        "existing scenes must retain identity: {identity:#?}"
    );
    assert!(!identity.unmatched_current_ids.is_empty());
}

#[test]
fn real_duplicate_scene_candidates_do_not_silently_merge() {
    let repeated = long_scene("Kai", "repeated dream");
    let original = format!("# Dream\n{repeated}");
    let duplicated = format!("# Dream One\n{repeated}\n\n# Dream Two\n{repeated}");
    let original = story_continuity_identity_snapshot(1, &contract(&original));
    let duplicated = story_continuity_identity_snapshot(2, &contract(&duplicated));
    let identity = resolve_revision_identity(&original, &duplicated).expect("identity");

    assert!(identity.scene_matches.is_empty());
    assert!(
        !identity.ambiguous.is_empty() || !identity.splits.is_empty(),
        "duplicate evidence must remain explicit: {identity:#?}"
    );
}

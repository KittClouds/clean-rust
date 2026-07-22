use super::*;

fn fingerprint(value: &str) -> IdentityFingerprint {
    IdentityFingerprint::from_normalized_text(value)
}

#[allow(clippy::too_many_arguments)]
fn record(
    id: &str,
    kind: RevisionIdentityKind,
    document: &str,
    semantic: &str,
    anchors: &[&str],
    participants: &[&str],
    neighbors: &[&str],
    source_start: u32,
) -> RevisionIdentityRecord {
    RevisionIdentityRecord {
        stable_id: id.into(),
        kind,
        document_id: document.into(),
        semantic_fingerprint: fingerprint(semantic),
        evidence_anchor_fingerprints: anchors.iter().map(|value| fingerprint(value)).collect(),
        participant_entity_ids: participants
            .iter()
            .map(|value| EntityId::from(*value))
            .collect(),
        neighbor_event_fingerprints: neighbors.iter().map(|value| fingerprint(value)).collect(),
        source_start,
        source_end: source_start + 100,
    }
}

fn snapshot(revision: u64, records: Vec<RevisionIdentityRecord>) -> RevisionIdentitySnapshot {
    RevisionIdentitySnapshot { revision, records }
}

#[test]
fn inserted_text_before_and_inside_scene_preserves_identity() {
    let previous = snapshot(
        1,
        vec![record(
            "scene:old",
            RevisionIdentityKind::Scene,
            "document:chapter-4",
            "scene:kai-meets-hazel",
            &["anchor:first-line", "anchor:last-line"],
            &["entity:kai", "entity:hazel"],
            &["event:arrival", "event:warning"],
            100,
        )],
    );
    let current = snapshot(
        2,
        vec![record(
            "scene:new",
            RevisionIdentityKind::Scene,
            "document:chapter-4",
            "scene:kai-meets-hazel",
            &["anchor:first-line", "anchor:last-line"],
            &["entity:kai", "entity:hazel"],
            &["event:arrival", "event:warning"],
            4_100,
        )],
    );

    let identity = resolve_revision_identity(&previous, &current).expect("identity map");
    assert_eq!(identity.scene_matches.len(), 1);
    assert_eq!(identity.scene_matches[0].previous_id, "scene:old");
    assert_eq!(identity.scene_matches[0].current_id, "scene:new");
    assert_eq!(identity.scene_matches[0].basis.source_distance, 4_000);
}

#[test]
fn reworded_fact_with_same_semantics_preserves_identity() {
    let previous = snapshot(
        1,
        vec![record(
            "fact:old",
            RevisionIdentityKind::Fact,
            "document:chapter-3",
            "fact:kai-limit-two",
            &[],
            &["entity:kai"],
            &["event:training"],
            800,
        )],
    );
    let current = snapshot(
        2,
        vec![record(
            "fact:new",
            RevisionIdentityKind::Fact,
            "document:chapter-3",
            "fact:kai-limit-two",
            &[],
            &["entity:kai"],
            &["event:training"],
            850,
        )],
    );

    let identity = resolve_revision_identity(&previous, &current).expect("identity map");
    assert_eq!(identity.fact_matches.len(), 1);
    assert!(identity.fact_matches[0].basis.semantic_fingerprint_match);
}

#[test]
fn moved_reveal_matches_across_documents_with_anchor_and_semantics() {
    let previous = snapshot(
        1,
        vec![record(
            "event:reveal-old",
            RevisionIdentityKind::Event,
            "document:chapter-4",
            "event:silas-learns-kai",
            &["anchor:silas-learns-kai"],
            &["entity:silas", "entity:kai"],
            &["event:iriane-report"],
            1_000,
        )],
    );
    let current = snapshot(
        2,
        vec![record(
            "event:reveal-new",
            RevisionIdentityKind::Event,
            "document:chapter-12",
            "event:silas-learns-kai",
            &["anchor:silas-learns-kai"],
            &["entity:silas", "entity:kai"],
            &["event:iriane-report"],
            12_000,
        )],
    );

    let identity = resolve_revision_identity(&previous, &current).expect("identity map");
    assert_eq!(identity.event_matches.len(), 1);
    assert!(!identity.event_matches[0].basis.same_document);
}

#[test]
fn anchor_partitions_are_explicit_splits_and_merges() {
    let old_scene = record(
        "scene:combined",
        RevisionIdentityKind::Scene,
        "document:chapter-5",
        "scene:combined",
        &["anchor:a", "anchor:b"],
        &["entity:kai"],
        &[],
        100,
    );
    let split_a = record(
        "scene:a",
        RevisionIdentityKind::Scene,
        "document:chapter-5",
        "scene:a",
        &["anchor:a"],
        &["entity:kai"],
        &[],
        100,
    );
    let split_b = record(
        "scene:b",
        RevisionIdentityKind::Scene,
        "document:chapter-5",
        "scene:b",
        &["anchor:b"],
        &["entity:kai"],
        &[],
        300,
    );

    let split = resolve_revision_identity(
        &snapshot(1, vec![old_scene.clone()]),
        &snapshot(2, vec![split_b.clone(), split_a.clone()]),
    )
    .expect("split map");
    assert_eq!(split.splits.len(), 1);
    assert_eq!(
        split.splits[0].current_ids,
        vec![
            CompactString::from("scene:a"),
            CompactString::from("scene:b")
        ]
    );
    assert!(split.scene_matches.is_empty());

    let merge = resolve_revision_identity(
        &snapshot(2, vec![split_a, split_b]),
        &snapshot(3, vec![old_scene]),
    )
    .expect("merge map");
    assert_eq!(merge.merges.len(), 1);
    assert_eq!(
        merge.merges[0].previous_ids,
        vec![
            CompactString::from("scene:a"),
            CompactString::from("scene:b")
        ]
    );
    assert!(merge.scene_matches.is_empty());
}

#[test]
fn appended_scene_is_unmatched_without_churning_existing_identity() {
    let existing_old = record(
        "scene:old",
        RevisionIdentityKind::Scene,
        "document:chapter-1",
        "scene:arrival",
        &["anchor:arrival"],
        &["entity:kai"],
        &[],
        0,
    );
    let existing_new = record(
        "scene:new",
        RevisionIdentityKind::Scene,
        "document:chapter-1",
        "scene:arrival",
        &["anchor:arrival"],
        &["entity:kai"],
        &[],
        0,
    );
    let appended = record(
        "scene:appended",
        RevisionIdentityKind::Scene,
        "document:chapter-1",
        "scene:departure",
        &["anchor:departure"],
        &["entity:kai"],
        &[],
        5_000,
    );

    let identity = resolve_revision_identity(
        &snapshot(1, vec![existing_old]),
        &snapshot(2, vec![appended, existing_new]),
    )
    .expect("identity map");
    assert_eq!(identity.scene_matches.len(), 1);
    assert_eq!(
        identity.unmatched_current_ids,
        vec![CompactString::from("scene:appended")]
    );
}

#[test]
fn duplicate_semantic_candidates_remain_ambiguous() {
    let previous = record(
        "scene:old",
        RevisionIdentityKind::Scene,
        "document:chapter-2",
        "scene:repeated-dream",
        &["anchor:repeated-dream"],
        &["entity:kai"],
        &[],
        500,
    );
    let left = record(
        "scene:left",
        RevisionIdentityKind::Scene,
        "document:chapter-2",
        "scene:repeated-dream",
        &["anchor:repeated-dream"],
        &["entity:kai"],
        &[],
        500,
    );
    let right = record(
        "scene:right",
        RevisionIdentityKind::Scene,
        "document:chapter-2",
        "scene:repeated-dream",
        &["anchor:repeated-dream"],
        &["entity:kai"],
        &[],
        500,
    );

    let identity = resolve_revision_identity(
        &snapshot(1, vec![previous]),
        &snapshot(2, vec![right, left]),
    )
    .expect("identity map");
    assert!(identity.scene_matches.is_empty());
    assert_eq!(identity.ambiguous.len(), 1);
    assert_eq!(
        identity.ambiguous[0].candidate_ids,
        vec![
            CompactString::from("scene:left"),
            CompactString::from("scene:right")
        ]
    );
}

#[test]
fn input_order_and_reruns_do_not_change_identity_results() {
    let previous_records = vec![
        record(
            "fact:b",
            RevisionIdentityKind::Fact,
            "document:a",
            "fact:b",
            &["anchor:b"],
            &[],
            &[],
            200,
        ),
        record(
            "scene:a",
            RevisionIdentityKind::Scene,
            "document:a",
            "scene:a",
            &["anchor:a"],
            &[],
            &[],
            100,
        ),
    ];
    let current_records = vec![
        record(
            "scene:a2",
            RevisionIdentityKind::Scene,
            "document:a",
            "scene:a",
            &["anchor:a"],
            &[],
            &[],
            500,
        ),
        record(
            "fact:b2",
            RevisionIdentityKind::Fact,
            "document:a",
            "fact:b",
            &["anchor:b"],
            &[],
            &[],
            600,
        ),
    ];

    let first = resolve_revision_identity(
        &snapshot(1, previous_records.clone()),
        &snapshot(2, current_records.clone()),
    )
    .expect("first map");
    let second = resolve_revision_identity(
        &snapshot(1, previous_records.into_iter().rev().collect()),
        &snapshot(2, current_records.into_iter().rev().collect()),
    )
    .expect("second map");
    assert_eq!(first, second);
}

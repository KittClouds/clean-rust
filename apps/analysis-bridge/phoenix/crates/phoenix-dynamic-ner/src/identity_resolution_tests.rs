use compact_str::CompactString;
use phoenix_types::{
    AtlasIdentityReceiptAction, AtlasIdentityTargetSummary, EntityId, EntityKind, MentionEntityRef,
    TextRange,
};
use smallvec::SmallVec;

use crate::{
    resolve_aliases, resolve_identity_dag, AliasRegistryEntity, AliasResolutionInput, EntityLabel,
    IdentityLinkerCandidate, IdentityResolutionInput, MentionContext, MentionGraph, MentionKind,
    MentionPacket, MentionSemantics, MentionStatus, MentionSyntax,
};

#[test]
fn known_aliases_and_full_designations_resolve_to_saved_identity() {
    let registry = vec![registry(
        "ryan",
        "Ryan",
        EntityKind::Character,
        &["Quicksave"],
    )];
    let mentions = vec![
        mention(
            1,
            "Ryan",
            Some(MentionEntityRef::Known(EntityId("ryan".to_owned()))),
        ),
        mention(2, "Ryan Ramano", None),
        mention(3, "Quicksave", None),
    ];
    let dag = run_dag("doc", &mentions, &registry, &[]);

    assert!(
        dag.receipts.iter().any(|receipt| {
            receipt.action == AtlasIdentityReceiptAction::FullDesignation
                && receipt.surface == "Ryan Ramano"
                && target_id(&receipt.target) == Some("ryan")
        }),
        "{:#?}",
        dag.receipts
    );
    assert!(
        dag.receipts.iter().any(|receipt| {
            receipt.action == AtlasIdentityReceiptAction::AliasOfKnown
                && receipt.surface == "Quicksave"
                && target_id(&receipt.target) == Some("ryan")
        }),
        "{:#?}",
        dag.receipts
    );
    assert_eq!(dag.summary.alias_decisions, 2);
}

#[test]
fn first_token_expansion_handles_riftmach_as_rift_designation() {
    let registry = vec![registry("rift", "Rift", EntityKind::Character, &[])];
    let mentions = vec![mention(1, "Riftmach Gearlock", None)];
    let dag = run_dag("doc", &mentions, &registry, &[]);

    assert!(
        dag.receipts.iter().any(|receipt| {
            receipt.action == AtlasIdentityReceiptAction::FullDesignation
                && receipt.surface == "Riftmach Gearlock"
                && target_id(&receipt.target) == Some("rift")
        }),
        "{:#?}",
        dag.receipts
    );
}

#[test]
fn repeated_unsaved_surface_emits_run_local_merge_receipt() {
    let registry = Vec::new();
    let mentions = vec![
        mention(1, "Kharon Vel", None),
        mention(2, "Kharon Vel", None),
    ];
    let dag = run_dag("doc", &mentions, &registry, &[]);

    let merge = dag
        .receipts
        .iter()
        .find(|receipt| receipt.action == AtlasIdentityReceiptAction::MergeRunLocal)
        .expect("merge receipt");
    assert_eq!(merge.mention_ids.len(), 2);
    assert!(matches!(
        &merge.target,
        AtlasIdentityTargetSummary::RunLocalEntity { key, .. } if key == "kharon vel"
    ));
}

#[test]
fn same_surface_conflicting_known_refs_emit_split_receipt() {
    let registry = vec![
        registry("alex-library", "Alex", EntityKind::Concept, &[]),
        registry("alex-person", "Alex", EntityKind::Character, &[]),
    ];
    let mentions = vec![
        mention(
            1,
            "Alex",
            Some(MentionEntityRef::Known(EntityId("alex-library".to_owned()))),
        ),
        mention(
            2,
            "Alex",
            Some(MentionEntityRef::Known(EntityId("alex-person".to_owned()))),
        ),
    ];
    let dag = run_dag("doc", &mentions, &registry, &[]);

    let split = dag
        .receipts
        .iter()
        .find(|receipt| receipt.action == AtlasIdentityReceiptAction::Split)
        .expect("split receipt");
    assert_eq!(split.mention_ids.len(), 2);
    assert_eq!(dag.summary.split_decisions, 1);
}

#[test]
fn linker_candidate_can_rescue_non_lexical_alias() {
    let registry = vec![registry("ryan", "Ryan", EntityKind::Character, &[])];
    let mentions = vec![mention(1, "Quicksave", None)];
    let linker = vec![IdentityLinkerCandidate {
        mention_id: crate::LocalMentionId(1),
        entity_id: EntityId("ryan".to_owned()),
        canonical_name: "Ryan".to_owned(),
        kind: Some(EntityKind::Character),
        score: 0.93,
        evidence_note: "bi-encoder identity neighborhood".to_owned(),
    }];
    let dag = run_dag("doc", &mentions, &registry, &linker);

    assert!(
        dag.receipts.iter().any(|receipt| {
            receipt.action == AtlasIdentityReceiptAction::AliasOfKnown
                && receipt.surface == "Quicksave"
                && target_id(&receipt.target) == Some("ryan")
        }),
        "{:#?}",
        dag.receipts
    );
}

#[test]
fn close_linker_scores_defer_instead_of_guessing() {
    let registry = vec![
        registry("ryan", "Ryan", EntityKind::Character, &[]),
        registry("rayan", "Rayan", EntityKind::Character, &[]),
    ];
    let mentions = vec![mention(1, "Ryann", None)];
    let linker = vec![
        IdentityLinkerCandidate {
            mention_id: crate::LocalMentionId(1),
            entity_id: EntityId("ryan".to_owned()),
            canonical_name: "Ryan".to_owned(),
            kind: Some(EntityKind::Character),
            score: 0.82,
            evidence_note: "candidate one".to_owned(),
        },
        IdentityLinkerCandidate {
            mention_id: crate::LocalMentionId(1),
            entity_id: EntityId("rayan".to_owned()),
            canonical_name: "Rayan".to_owned(),
            kind: Some(EntityKind::Character),
            score: 0.78,
            evidence_note: "candidate two".to_owned(),
        },
    ];
    let dag = run_dag("doc", &mentions, &registry, &linker);

    assert!(dag
        .receipts
        .iter()
        .any(|receipt| receipt.action == AtlasIdentityReceiptAction::Defer));
}

#[test]
fn personal_pronoun_corefers_to_nearby_known_character() {
    let registry = vec![registry("ryan", "Ryan", EntityKind::Character, &[])];
    let mentions = vec![
        mention(
            1,
            "Ryan",
            Some(MentionEntityRef::Known(EntityId("ryan".to_owned()))),
        ),
        mention_kind(2, "he", MentionKind::Pronoun, None),
    ];
    let dag = run_dag("doc", &mentions, &registry, &[]);

    assert!(
        dag.receipts.iter().any(|receipt| {
            receipt.action == AtlasIdentityReceiptAction::Coreference
                && receipt.surface == "he"
                && target_id(&receipt.target) == Some("ryan")
        }),
        "{:#?}",
        dag.receipts
    );
    assert_eq!(dag.summary.coreference_decisions, 1);
}

#[test]
fn role_nominal_corefers_into_run_local_identity() {
    let registry = Vec::new();
    let mentions = vec![
        mention(1, "Tempest Barish", None),
        mention_kind(2, "captain", MentionKind::Nominal, None),
    ];
    let dag = run_dag("doc", &mentions, &registry, &[]);

    let coref = dag
        .receipts
        .iter()
        .find(|receipt| receipt.action == AtlasIdentityReceiptAction::Coreference)
        .unwrap_or_else(|| panic!("coreference receipt: {:#?}", dag.receipts));
    assert_eq!(coref.mention_ids.len(), 2);
    assert!(matches!(
        &coref.target,
        AtlasIdentityTargetSummary::RunLocalEntity { key, .. } if key == "tempest barish"
    ));
}

#[test]
fn unresolved_pronoun_defers_instead_of_becoming_entity() {
    let mentions = vec![mention_kind(1, "it", MentionKind::Pronoun, None)];
    let dag = run_dag("doc", &mentions, &[], &[]);

    assert!(dag
        .receipts
        .iter()
        .any(|receipt| receipt.action == AtlasIdentityReceiptAction::Defer));
    assert!(!dag
        .receipts
        .iter()
        .any(|receipt| receipt.action == AtlasIdentityReceiptAction::NewEntity));
}

#[test]
fn object_pronoun_corefers_to_recent_item_not_character() {
    let mentions = vec![
        mention_with_label(1, "Ryan", MentionKind::Named, "person", None),
        mention_with_label(2, "Riftmach Gearlock", MentionKind::Named, "item", None),
        mention_kind(3, "it", MentionKind::Pronoun, None),
    ];
    let dag = run_dag("doc", &mentions, &[], &[]);

    let coref = dag
        .receipts
        .iter()
        .find(|receipt| {
            receipt.action == AtlasIdentityReceiptAction::Coreference
                && receipt.mention_ids.iter().any(|id| id.0 == "3")
        })
        .unwrap_or_else(|| panic!("coreference receipt: {:#?}", dag.receipts));
    assert!(matches!(
        &coref.target,
        AtlasIdentityTargetSummary::RunLocalEntity { key, .. } if key == "riftmach gearlock"
    ));
}

#[test]
fn quoted_first_person_uses_dialogue_speaker_state() {
    let registry = vec![registry("ryan", "Ryan", EntityKind::Character, &[])];
    let mut ryan = mention(
        1,
        "Ryan",
        Some(MentionEntityRef::Known(EntityId("ryan".to_owned()))),
    );
    ryan.syntax = Some(MentionSyntax {
        is_subject: true,
        ..MentionSyntax::default()
    });
    let mut quoted_i = mention_kind(2, "I", MentionKind::Pronoun, None);
    quoted_i.semantics.is_quoted = true;
    quoted_i.context.paragraph_role = Some(CompactString::from("speaker:1"));
    let dag = run_dag("doc", &[ryan, quoted_i], &registry, &[]);

    assert!(
        dag.receipts.iter().any(|receipt| {
            receipt.action == AtlasIdentityReceiptAction::Coreference
                && receipt.surface == "I"
                && target_id(&receipt.target) == Some("ryan")
        }),
        "{:#?}",
        dag.receipts
    );
}

#[test]
fn ambiguous_pronoun_candidates_defer_with_receipt() {
    let mentions = vec![
        mention_with_label(1, "Ryan", MentionKind::Named, "person", None),
        mention_with_label(2, "Rift", MentionKind::Named, "person", None),
        mention_kind(3, "he", MentionKind::Pronoun, None),
    ];
    let dag = run_dag("doc", &mentions, &[], &[]);

    assert!(
        dag.receipts.iter().any(|receipt| {
            receipt.action == AtlasIdentityReceiptAction::Defer
                && receipt.surface == "he"
                && receipt
                    .rationale
                    .contains("document coreference was ambiguous")
        }),
        "{:#?}",
        dag.receipts
    );
    assert!(!dag.receipts.iter().any(|receipt| {
        receipt.action == AtlasIdentityReceiptAction::Coreference && receipt.surface == "he"
    }));
}

fn run_dag(
    document_id: &str,
    mentions: &[MentionPacket],
    registry: &[AliasRegistryEntity],
    linker: &[IdentityLinkerCandidate],
) -> crate::IdentityResolutionDag {
    let surface_memory = crate::SurfaceMemoryReport::build(mentions);
    let alias_report = resolve_aliases(&AliasResolutionInput {
        document_id,
        mentions,
        surface_memory: &surface_memory,
        registry_entities: registry,
    });
    resolve_identity_dag(&IdentityResolutionInput {
        document_id,
        mentions,
        mention_graph: &MentionGraph::default(),
        surface_memory: &surface_memory,
        alias_report: Some(&alias_report),
        registry_entities: registry,
        linker_candidates: linker,
    })
}

fn registry(
    id: &str,
    canonical_name: &str,
    kind: EntityKind,
    aliases: &[&str],
) -> AliasRegistryEntity {
    AliasRegistryEntity {
        entity_id: EntityId(id.to_owned()),
        canonical_name: canonical_name.to_owned(),
        kind: Some(kind),
        aliases: aliases.iter().map(|alias| (*alias).to_owned()).collect(),
    }
}

fn mention(id: u64, surface: &str, entity_ref: Option<MentionEntityRef>) -> MentionPacket {
    mention_kind(id, surface, MentionKind::Named, entity_ref)
}

fn mention_kind(
    id: u64,
    surface: &str,
    mention_kind: MentionKind,
    entity_ref: Option<MentionEntityRef>,
) -> MentionPacket {
    mention_with_label(id, surface, mention_kind, "person", entity_ref)
}

fn mention_with_label(
    id: u64,
    surface: &str,
    mention_kind: MentionKind,
    label: &str,
    entity_ref: Option<MentionEntityRef>,
) -> MentionPacket {
    let mut label_distribution = SmallVec::new();
    label_distribution.push((EntityLabel::new(label), 0.82));
    MentionPacket {
        mention_id: crate::LocalMentionId(id),
        document_id: CompactString::from("doc"),
        chunk_id: None,
        sentence_index: id as u32,
        range: TextRange {
            start: (id * 10) as u32,
            end: (id * 10 + surface.len() as u64) as u32,
        },
        surface: CompactString::from(surface),
        normalized: CompactString::from(surface.to_ascii_lowercase()),
        mention_kind,
        label_distribution,
        entity_ref,
        source_votes: SmallVec::new(),
        context: MentionContext::default(),
        syntax: None,
        semantics: MentionSemantics::default(),
        confidence: 0.86,
        status: MentionStatus::AcceptedNew,
    }
}

fn target_id(target: &AtlasIdentityTargetSummary) -> Option<&str> {
    match target {
        AtlasIdentityTargetSummary::KnownEntity { entity_id, .. } => Some(entity_id.0.as_str()),
        _ => None,
    }
}

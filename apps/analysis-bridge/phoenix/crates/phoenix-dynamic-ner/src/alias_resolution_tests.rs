use compact_str::CompactString;
use phoenix_types::{
    AtlasAliasProposalDecision, AtlasAliasProposalTarget, AtlasAliasRelation, EntityId, EntityKind,
    MentionEntityRef, TextRange,
};
use smallvec::smallvec;

use crate::{
    resolve_aliases, AliasRegistryEntity, AliasResolutionInput, MentionKind, MentionPacket,
    MentionStatus, SurfaceMemoryReport,
};

#[test]
fn registered_short_name_gets_full_designation_proposal() {
    let mentions = vec![packet(
        1,
        "Ryan Ramano",
        "person",
        MentionStatus::AcceptedNew,
    )];
    let report = resolve_aliases(&AliasResolutionInput {
        document_id: "doc",
        mentions: &mentions,
        surface_memory: &SurfaceMemoryReport::build(&mentions),
        registry_entities: &[entity("ryan", "Ryan", EntityKind::Character, &[])],
    });
    assert_eq!(report.proposals.len(), 1);
    assert_eq!(
        report.proposals[0].relation,
        AtlasAliasRelation::FullDesignation
    );
    assert_eq!(
        report.proposals[0].decision,
        AtlasAliasProposalDecision::Propose
    );
}

#[test]
fn riftmach_can_expand_rift_by_prefix() {
    let mentions = vec![packet(
        2,
        "Riftmach Gearlock",
        "person",
        MentionStatus::AcceptedNew,
    )];
    let report = resolve_aliases(&AliasResolutionInput {
        document_id: "doc",
        mentions: &mentions,
        surface_memory: &SurfaceMemoryReport::build(&mentions),
        registry_entities: &[entity("rift", "Rift", EntityKind::Character, &[])],
    });
    assert_eq!(
        report.proposals[0].relation,
        AtlasAliasRelation::FullDesignation
    );
}

#[test]
fn spelling_variant_stays_a_reviewable_alias_question() {
    let mentions = vec![packet(
        3,
        "Rayan Ramano",
        "person",
        MentionStatus::AcceptedNew,
    )];
    let report = resolve_aliases(&AliasResolutionInput {
        document_id: "doc",
        mentions: &mentions,
        surface_memory: &SurfaceMemoryReport::build(&mentions),
        registry_entities: &[entity(
            "ryan",
            "Ryan",
            EntityKind::Character,
            &["Ryan Ramano"],
        )],
    });
    assert_eq!(
        report.proposals[0].relation,
        AtlasAliasRelation::SpellingVariant
    );
    assert_eq!(
        report.proposals[0].decision,
        AtlasAliasProposalDecision::Propose
    );
}

#[test]
fn kind_conflict_defers_location_target() {
    let mentions = vec![packet(
        4,
        "Kharon Vel",
        "person",
        MentionStatus::AcceptedNew,
    )];
    let report = resolve_aliases(&AliasResolutionInput {
        document_id: "doc",
        mentions: &mentions,
        surface_memory: &SurfaceMemoryReport::build(&mentions),
        registry_entities: &[entity(
            "kharon-vel",
            "Kharon Vel",
            EntityKind::Location,
            &[],
        )],
    });
    assert_eq!(
        report.proposals[0].relation,
        AtlasAliasRelation::TypeConflict
    );
    assert_eq!(
        report.proposals[0].decision,
        AtlasAliasProposalDecision::Defer
    );
}

#[test]
fn run_local_short_surface_can_receive_long_designation() {
    let mentions = vec![
        packet(5, "Tempest", "person", MentionStatus::AcceptedNew),
        packet(6, "Tempest Barish", "person", MentionStatus::AcceptedNew),
    ];
    let report = resolve_aliases(&AliasResolutionInput {
        document_id: "doc",
        mentions: &mentions,
        surface_memory: &SurfaceMemoryReport::build(&mentions),
        registry_entities: &[],
    });
    assert!(report.proposals.iter().any(|proposal| {
        proposal.surface == "Tempest Barish"
            && proposal.relation == AtlasAliasRelation::FullDesignation
            && matches!(
                proposal.target,
                AtlasAliasProposalTarget::RunLocalSurface { .. }
            )
    }));
}

#[test]
fn linked_mention_can_offer_unsaved_surface() {
    let mut mention = packet(7, "Quicksave", "person", MentionStatus::AliasCandidate);
    mention.entity_ref = Some(MentionEntityRef::Known(EntityId("ryan".to_owned())));
    let mentions = vec![mention];
    let report = resolve_aliases(&AliasResolutionInput {
        document_id: "doc",
        mentions: &mentions,
        surface_memory: &SurfaceMemoryReport::build(&mentions),
        registry_entities: &[entity("ryan", "Ryan", EntityKind::Character, &[])],
    });
    assert_eq!(report.proposals[0].target, known_target("ryan", "Ryan"));
    assert_eq!(
        report.proposals[0].decision,
        AtlasAliasProposalDecision::Propose
    );
}

#[test]
fn ambiguous_close_targets_defer() {
    let mentions = vec![packet(
        8,
        "Ryan Stone",
        "person",
        MentionStatus::AcceptedNew,
    )];
    let report = resolve_aliases(&AliasResolutionInput {
        document_id: "doc",
        mentions: &mentions,
        surface_memory: &SurfaceMemoryReport::build(&mentions),
        registry_entities: &[
            entity("ryan", "Ryan", EntityKind::Character, &[]),
            entity("stone", "Stone", EntityKind::Character, &[]),
        ],
    });
    assert_eq!(report.proposals[0].relation, AtlasAliasRelation::Ambiguous);
    assert_eq!(
        report.proposals[0].decision,
        AtlasAliasProposalDecision::Defer
    );
}

#[test]
fn accepted_new_without_alias_candidate_stays_new_entity() {
    let mentions = vec![packet(9, "Maela", "person", MentionStatus::AcceptedNew)];
    let report = resolve_aliases(&AliasResolutionInput {
        document_id: "doc",
        mentions: &mentions,
        surface_memory: &SurfaceMemoryReport::build(&mentions),
        registry_entities: &[],
    });
    assert_eq!(report.proposals[0].relation, AtlasAliasRelation::NewEntity);
}

fn entity(id: &str, label: &str, kind: EntityKind, aliases: &[&str]) -> AliasRegistryEntity {
    AliasRegistryEntity {
        entity_id: EntityId(id.to_owned()),
        canonical_name: label.to_owned(),
        kind: Some(kind),
        aliases: aliases.iter().map(|alias| (*alias).to_owned()).collect(),
    }
}

fn known_target(id: &str, label: &str) -> AtlasAliasProposalTarget {
    AtlasAliasProposalTarget::KnownEntity {
        entity_id: EntityId(id.to_owned()),
        canonical_name: label.to_owned(),
        kind: Some(EntityKind::Character),
    }
}

fn packet(start: u32, surface: &str, label: &str, status: MentionStatus) -> MentionPacket {
    MentionPacket {
        mention_id: crate::types::LocalMentionId(u64::from(start)),
        document_id: CompactString::from("doc"),
        chunk_id: None,
        sentence_index: 0,
        range: TextRange {
            start,
            end: start + surface.len() as u32,
        },
        surface: CompactString::from(surface),
        normalized: CompactString::from(surface.to_ascii_lowercase()),
        mention_kind: MentionKind::Named,
        label_distribution: smallvec![(crate::types::EntityLabel::new(label), 0.93)],
        entity_ref: None::<MentionEntityRef>,
        source_votes: smallvec![],
        context: crate::types::MentionContext::default(),
        syntax: None,
        semantics: crate::types::MentionSemantics::default(),
        confidence: 0.82,
        status,
    }
}

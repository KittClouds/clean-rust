use super::{
    build_document_semantic_summary, DocumentSemanticEntity, DocumentSemanticInput,
    DocumentSemanticRequest,
};

#[test]
fn builds_reviewable_semantic_rows_with_utf16_offsets() {
    let text = "If Hazel returns, Kai might not tell Rift, \"do not leave\"";
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note-1".to_owned(),
            text: text.to_owned(),
        }],
        entities: vec![DocumentSemanticEntity {
            id: "entity-kai".to_owned(),
            label: "Kai".to_owned(),
            aliases: Vec::new(),
            kind: "character".to_owned(),
        }],
    });
    assert_eq!(summary.schema_version, "phoenix-document-semantics/v1");
    assert!(!summary.documents[0].propositions.is_empty());
    assert!(summary.counters.attributed > 0);
    assert!(summary.counters.quoted > 0);
    assert!(summary.counters.factuality_annotations > 0);
    assert!(summary.counters.scoped_factuality > 0);
    assert!(summary.counters.quoted_factuality > 0);
    assert!(summary.counters.speech_or_belief_frames > 0);
    assert!(summary.documents[0].propositions.iter().any(|row| {
        row.factuality.negated
            && row.factuality.modal
            && row.factuality.conditional
            && row.factuality.factuality == "conditional"
    }));
    assert!(summary.documents[0]
        .propositions
        .iter()
        .any(|row| row.speech_or_belief_frame.is_some()));
    assert!(summary.documents[0]
        .propositions
        .iter()
        .flat_map(|row| &row.arguments)
        .any(|argument| argument.entity_id.as_deref() == Some("entity-kai")));
}

#[test]
fn emits_role_precision_without_dropping_unresolved_surfaces() {
    let text = "Kai gave Hazel the key in New Rome.";
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note-roles".to_owned(),
            text: text.to_owned(),
        }],
        entities: vec![
            DocumentSemanticEntity {
                id: "entity-kai".to_owned(),
                label: "Kai".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
            DocumentSemanticEntity {
                id: "entity-hazel".to_owned(),
                label: "Hazel".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
            DocumentSemanticEntity {
                id: "entity-rome".to_owned(),
                label: "New Rome".to_owned(),
                aliases: Vec::new(),
                kind: "location".to_owned(),
            },
        ],
    });
    let gave = summary.documents[0]
        .propositions
        .iter()
        .find(|row| row.predicate == "give")
        .expect("give proposition");
    assert_eq!(gave.frame.frame, "transfer_possession");
    assert_eq!(gave.frame.family, "transfer");
    assert_eq!(gave.frame.source, "lexical_table");
    assert!(gave.frame.confidence_millis >= 800);
    assert!(gave
        .frame
        .expected_roles
        .iter()
        .any(|role| role == "recipient"));
    assert!(gave.frame.matched_roles.iter().any(|role| role == "actor"));

    let arguments = summary.documents[0]
        .propositions
        .iter()
        .flat_map(|row| &row.arguments)
        .collect::<Vec<_>>();
    let kai = arguments
        .iter()
        .find(|argument| argument.surface == "Kai")
        .expect("Kai role");
    assert_eq!(kai.syntactic_role, "subject");
    assert_eq!(kai.semantic_role, "actor");
    assert!(kai.role_confidence_millis >= 800);

    let unresolved_location = arguments
        .iter()
        .find(|argument| argument.surface == "in New Rome")
        .expect("unresolved location surface");
    assert_eq!(unresolved_location.syntactic_role, "location");
    assert_eq!(unresolved_location.semantic_role, "location");
    assert!(unresolved_location.entity_id.is_none());
    assert!(unresolved_location
        .role_failure_reasons
        .iter()
        .any(|reason| reason == "unresolved_entity"));
    assert!(summary.counters.role_annotations >= arguments.len());
    assert!(summary.counters.unresolved_role_surfaces > 0);
    assert!(summary.counters.frame_annotations > 0);
    assert!(summary.counters.lexical_frame_matches > 0);
}

#[test]
fn recovers_document_level_arguments_as_explicit_rows() {
    let text = "Kai opened the door. Walked inside. Hazel entered. Kai saw her. Hazel said, \"Stay here.\" \"Do not move.\"";
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note-recovery".to_owned(),
            text: text.to_owned(),
        }],
        entities: vec![
            DocumentSemanticEntity {
                id: "entity-kai".to_owned(),
                label: "Kai".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
            DocumentSemanticEntity {
                id: "entity-hazel".to_owned(),
                label: "Hazel".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
        ],
    });
    let rows = &summary.documents[0].propositions;
    assert!(summary.counters.document_argument_recoveries > 0);
    assert!(summary.counters.omitted_subject_recoveries > 0);
    assert!(summary.counters.quote_speaker_recoveries > 0);
    assert!(rows.iter().any(|row| {
        row.document_argument_recoveries.iter().any(|argument| {
            argument.kind == "omitted_subject"
                && argument.semantic_role == "actor"
                && argument.entity_id.as_deref() == Some("entity-kai")
        })
    }));
    assert!(rows.iter().any(|row| {
        row.document_argument_recoveries.iter().any(|argument| {
            argument.kind == "quote_speaker_carryover"
                && argument.entity_id.as_deref() == Some("entity-hazel")
        })
    }));
}

#[test]
fn keeps_participle_modifiers_ledger_only_but_reviews_finite_frames() {
    let text =
        "Arriving in New Rome, Kai found sponsored heroes and superpowered criminals. Kai warned Hazel.";
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note-precision".to_owned(),
            text: text.to_owned(),
        }],
        entities: vec![
            DocumentSemanticEntity {
                id: "entity-kai".to_owned(),
                label: "Kai".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
            DocumentSemanticEntity {
                id: "entity-hazel".to_owned(),
                label: "Hazel".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
        ],
    });
    let rows = &summary.documents[0].propositions;
    let sponsored = rows
        .iter()
        .find(|row| row.predicate == "sponsored")
        .expect("sponsored modifier row");
    assert_eq!(sponsored.predicate_quality, "participle_modifier");
    assert_eq!(sponsored.review_state, "ledger_only");
    assert!(rows
        .iter()
        .any(|row| { row.predicate == "warned" && row.review_state == "proposed" }));
    assert!(summary.counters.ledger_only > 0);
    assert!(summary.counters.reviewable > 0);
}

#[test]
fn keeps_perfect_tense_actions_out_of_modifier_bucket() {
    let text = "Ryan had already caused two traffic accidents. Kai has saved Hazel.";
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note-perfect".to_owned(),
            text: text.to_owned(),
        }],
        entities: vec![
            DocumentSemanticEntity {
                id: "entity-ryan".to_owned(),
                label: "Ryan".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
            DocumentSemanticEntity {
                id: "entity-kai".to_owned(),
                label: "Kai".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
            DocumentSemanticEntity {
                id: "entity-hazel".to_owned(),
                label: "Hazel".to_owned(),
                aliases: Vec::new(),
                kind: "character".to_owned(),
            },
        ],
    });
    let rows = &summary.documents[0].propositions;
    for predicate in ["caused", "saved"] {
        let row = rows
            .iter()
            .find(|row| row.predicate == predicate)
            .unwrap_or_else(|| panic!("{predicate} action row"));
        assert_ne!(row.predicate_quality, "participle_modifier");
        assert!(row
            .quality_reasons
            .iter()
            .any(|reason| reason == "perfect_auxiliary_context"));
    }
}

#[test]
fn builds_temporal_continuity_without_committing_scoped_world_state() {
    let text = "Kai remained awake. Kai was still awake. Then Kai was not awake. Kai entered the room. Later Kai entered the room again. Kai might leave.";
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note-temporal".to_owned(),
            text: text.to_owned(),
        }],
        entities: vec![DocumentSemanticEntity {
            id: "entity-kai".to_owned(),
            label: "Kai".to_owned(),
            aliases: Vec::new(),
            kind: "character".to_owned(),
        }],
    });
    let document = &summary.documents[0];
    assert!(!document.situations.is_empty());
    assert!(document
        .situations
        .iter()
        .any(|row| row.recurrence_of_situation_id.is_some()));
    assert!(document
        .situations
        .iter()
        .any(|row| row.predicate == "leave" && !row.world_state_eligible));
    assert!(document
        .state_intervals
        .iter()
        .any(|row| row.persists || row.status == "superseded" || row.status == "terminated"));
    assert!(document
        .event_orderings
        .iter()
        .any(|row| row.source == "explicit_cue" || row.relation == "recurs_after"));
    assert!(summary.counters.situation_instances > 0);
    assert!(summary.counters.event_orderings > 0);
    assert!(summary.counters.world_state_ineligible_situations > 0);
}

#[test]
fn flags_unresolved_state_polarity_transitions() {
    let summary = build_document_semantic_summary(&DocumentSemanticRequest {
        documents: vec![DocumentSemanticInput {
            note_id: "note-state-conflict".to_owned(),
            text: "Kai remained awake. Kai never remained awake.".to_owned(),
        }],
        entities: vec![DocumentSemanticEntity {
            id: "entity-kai".to_owned(),
            label: "Kai".to_owned(),
            aliases: Vec::new(),
            kind: "character".to_owned(),
        }],
    });
    assert!(summary.documents[0]
        .temporal_conflicts
        .iter()
        .any(|row| row.kind == "unresolved_state_transition"));
    assert!(summary.counters.temporal_conflicts > 0);
}

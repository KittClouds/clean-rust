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
    assert!(summary.documents[0]
        .propositions
        .iter()
        .flat_map(|row| &row.arguments)
        .any(|argument| argument.entity_id.as_deref() == Some("entity-kai")));
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

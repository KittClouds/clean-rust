#![deny(unsafe_op_in_unsafe_fn)]

pub mod adapters;
pub mod candidates;
pub mod structured;
pub mod synthetic;
pub mod types;
pub mod validate;

pub use types::{CanonicalEpisode, ContractStatus};

#[cfg(test)]
mod tests {
    use crate::adapters::{clinc_oos, docred, go_emotions, multitask_classification};
    use crate::candidates::{
        CandidateIntervention, apply_candidate_intervention, security_runtime_schema,
    };
    use crate::structured::{StructuredRenderer, structured_span_relation_episode};
    use crate::types::{ProbabilitySource, QueryView, TargetPayload};
    use crate::validate::validate_episode;

    #[test]
    fn structured_renderers_validate_and_preserve_relation_semantics() {
        let first = structured_span_relation_episode(StructuredRenderer::MaraFirst)
            .expect("first renderer");
        let second = structured_span_relation_episode(StructuredRenderer::OrionFirst)
            .expect("second renderer");
        validate_episode(&first).expect("first validation");
        validate_episode(&second).expect("second validation");
        assert_eq!(
            first
                .state
                .structured_state
                .as_ref()
                .unwrap()
                .semantic_relations,
            second
                .state
                .structured_state
                .as_ref()
                .unwrap()
                .semantic_relations
        );
        assert_eq!(
            first.identity.semantic_fingerprint,
            second.identity.semantic_fingerprint
        );
        assert!(
            first
                .queries
                .iter()
                .any(|query| query.view == QueryView::SpanType)
        );
        assert!(
            first
                .queries
                .iter()
                .any(|query| query.view == QueryView::Relation)
        );
    }

    #[test]
    fn opaque_candidate_id_substitution_updates_set_membership() {
        let schema =
            security_runtime_schema(crate::types::PresentationProfile::OpaqueIdPlusDefinition);
        let child = apply_candidate_intervention(
            &schema,
            &CandidateIntervention::OpaqueIdSubstitution {
                semantic_id: "credential_compromise".to_string(),
                new_opaque_id: "X01".to_string(),
            },
        )
        .expect("substitution");
        assert!(
            child.candidate_sets[0]
                .candidate_ids
                .iter()
                .any(|id| id == "X01")
        );
        assert!(
            !child.candidate_sets[0]
                .candidate_ids
                .iter()
                .any(|id| id == "A17")
        );
    }

    #[test]
    fn semantic_fingerprint_ignores_candidate_presentation_order() {
        let episode =
            structured_span_relation_episode(StructuredRenderer::MaraFirst).expect("episode");
        let mut reordered = episode.clone();
        reordered.runtime_schema.candidates.reverse();
        for candidate_set in &mut reordered.runtime_schema.candidate_sets {
            candidate_set.candidate_ids.reverse();
        }
        let reordered_hash = blake3::hash(
            &reordered
                .semantic_content_bytes()
                .expect("semantic projection"),
        );
        assert_eq!(
            episode.identity.semantic_fingerprint,
            reordered_hash.to_hex().to_string()
        );
    }

    #[test]
    fn hard_label_adapter_does_not_mint_probability() {
        let input = serde_json::json!({"text":"A new device appeared.","instructions":"Choose.","choices":{"compromise":"Unauthorized access","benign":"Ordinary activity"}}).to_string();
        let episode = multitask_classification::normalize_row(
            &serde_json::json!({"input":input,"label":[1.0,0.0]}),
            "test-row",
            "rev",
            "train",
        )
        .expect("normalize");
        validate_episode(&episode).expect("validate");
        let target = &episode.gold_targets[0];
        assert_eq!(
            target.probability_source.probability_source,
            ProbabilitySource::HardLabel
        );
        assert!(matches!(
            &target.target,
            TargetPayload::Choice {
                distribution: None,
                other_probability: None,
                ..
            }
        ));
    }

    #[test]
    fn oos_is_explicit_abstention_and_not_closed_choice() {
        let inventory = vec!["book_flight".to_string(), "oos".to_string()];
        let episode = clinc_oos::normalize_row(
            &serde_json::json!({"text":"unsupported request","intent":"oos"}),
            "oos-row",
            "rev",
            "oos",
            &inventory,
        )
        .expect("normalize");
        validate_episode(&episode).expect("validate");
        assert!(matches!(episode.queries[0].view, QueryView::Abstain));
        assert!(matches!(
            &episode.gold_targets[0].target,
            TargetPayload::Abstention {
                abstain: Some(true),
                ..
            }
        ));
    }

    #[test]
    fn raw_rater_rows_reconstruct_empirical_distribution() {
        let mut rows = Vec::new();
        for (rater, emotion) in [(1_i64, "joy"), (2, "joy"), (3, "surprise")] {
            let mut row = serde_json::Map::new();
            row.insert("id".to_string(), serde_json::json!("item"));
            row.insert("rater_id".to_string(), serde_json::json!(rater));
            row.insert("text".to_string(), serde_json::json!("It worked."));
            for candidate in go_emotions::EMOTIONS {
                row.insert(
                    (*candidate).to_string(),
                    serde_json::json!(if *candidate == emotion { 1 } else { 0 }),
                );
            }
            rows.push(serde_json::Value::Object(row));
        }
        let episodes = go_emotions::normalize_group(&rows, "rev", "train").expect("normalize");
        validate_episode(&episodes[0]).expect("validate");
        assert_eq!(
            episodes[0].gold_targets[0]
                .probability_source
                .annotator_count,
            Some(3)
        );
    }

    #[test]
    fn relation_adapter_preserves_positive_only_semantics() {
        let episode = docred::normalize_row(&serde_json::json!({"sents":[["A","gave","B","to","C","."]],"vertexSet":[[{"name":"A","sent_id":0,"pos":[0,1],"type":"PERSON"}],[{"name":"B","sent_id":0,"pos":[2,3],"type":"OBJECT"}],[{"name":"C","sent_id":0,"pos":[4,5],"type":"PERSON"}]],"labels":[{"h":1,"t":2,"r":1,"relation_text":"transferred_to","evidence":[0]}]}), "row", "rev", "train_annotated").expect("normalize");
        validate_episode(&episode).expect("validate");
        assert!(
            matches!(&episode.gold_targets[0].target, TargetPayload::Relation { relations } if relations[0].polarity == crate::types::RelationPolarity::Holds)
        );
        assert_eq!(
            episode.gold_targets[0]
                .probability_source
                .probability_source,
            ProbabilitySource::NoProbability
        );
    }
}

#![recursion_limit = "256"]

pub mod identity;
pub mod population;
pub mod render;
pub mod schema;
pub mod support;
pub mod writer;

pub use population::{
    PopulationPaths, PopulationPermit, PopulationPlan, prepare_population,
    verify_population_stage_authorization,
};
pub use schema::{GeneratedQuartet, PopulationReceipt};
pub use writer::{WrittenPopulation, write_population};

#[cfg(test)]
mod schema_tests {
    use super::schema::{FitEligibility, ModelInputRow, RowManifestEntry, TerminalLabel};
    use serde_json::Value;

    #[test]
    fn feature_inputs_and_row_manifest_are_label_free() {
        let input = serde_json::to_value(ModelInputRow {
            row_id: format!("{}:00:00", "a".repeat(64)),
            quartet_id: "a".repeat(64),
            variant_id: "A".into(),
            input_text: "synthetic input".into(),
        })
        .unwrap();
        let manifest = serde_json::to_value(RowManifestEntry {
            row_index: 0,
            row_id: format!("{}:00:00", "a".repeat(64)),
            quartet_id: "a".repeat(64),
            variant_id: "A".into(),
            surface_id: "PRIMARY_SEEN".into(),
            truth_partition: "PRIMARY_TERMINAL".into(),
        })
        .unwrap();
        for forbidden in [
            "context_term_id",
            "entity_term_id",
            "relation_id",
            "state_id",
            "exact_target",
            "target_candidate_identity",
            "candidate_identity_order",
            "score_strata",
        ] {
            assert!(input.get(forbidden).is_none());
            assert!(manifest.get(forbidden).is_none());
        }
        assert_eq!(manifest["truth_partition"], "PRIMARY_TERMINAL");
        assert_eq!(manifest["surface_id"], "PRIMARY_SEEN");
        let _: Value = input;
    }

    #[test]
    fn primary_truth_and_template_joint_truth_remain_separate_from_feature_manifest() {
        let label = |joint_template_lexical| TerminalLabel {
            row_id: format!("{}:01:00", "b".repeat(64)),
            quartet_id: "b".repeat(64),
            variant_id: "A".into(),
            context_term_id: 16,
            entity_term_id: 20,
            relation_id: 1,
            state_id: 2,
            exact_target: 1,
            target_candidate_identity: 2,
            candidate_identity_order: [0, 2, 1],
            both_terms_train_side: false,
            fit_eligibility: FitEligibility {
                context_identity: true,
                entity_identity: true,
                relation_identity: false,
                observed_state: false,
                exact_target: false,
            },
            score_strata: "BOTH_NOVEL".into(),
            joint_template_lexical,
        };
        let primary_value = serde_json::to_value(label(None)).unwrap();
        let escrow_value = serde_json::to_value(label(Some(true))).unwrap();
        let escrow_manifest = serde_json::to_value(RowManifestEntry {
            row_index: 4,
            row_id: format!("{}:01:00", "b".repeat(64)),
            quartet_id: "b".repeat(64),
            variant_id: "A".into(),
            surface_id: "HELDOUT_TEMPLATE".into(),
            truth_partition: "TEMPLATE_ESCROW".into(),
        })
        .unwrap();

        assert!(primary_value.get("joint_template_lexical").is_none());
        assert_eq!(escrow_value["joint_template_lexical"], true);
        assert_eq!(escrow_manifest["truth_partition"], "TEMPLATE_ESCROW");
        assert_eq!(escrow_manifest["surface_id"], "HELDOUT_TEMPLATE");
        for forbidden in [
            "score_strata",
            "context_term_id",
            "state_id",
            "exact_target",
        ] {
            assert!(escrow_manifest.get(forbidden).is_none());
        }
    }
}

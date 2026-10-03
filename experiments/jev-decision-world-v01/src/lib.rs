#![deny(unsafe_op_in_unsafe_fn)]

mod exact;
mod families;
mod generate;
mod types;
mod validate;

pub use exact::{ExactPosterior, solve_exact};
pub use families::{all_templates, template_by_id};
pub use generate::{
    GenerationConfig, generate_episode, generate_pilot_report, observation_perturbation,
    surface_perturbation, verify_perturbation_pair, world_perturbation,
};
pub use types::*;
pub use validate::{ValidationReport, validate_episode, validate_jsonl};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_v0_templates_generate_and_validate() {
        let config = GenerationConfig {
            seed: 42,
            count: 1,
            visibility_probability: 1.0,
        };
        for template in all_templates() {
            let episode = generate_episode(&template, 0, &config).expect("episode generation");
            validate_episode(&episode, &template).expect("episode validation");
            assert_eq!(episode.gold_targets.len(), 6);
            assert_eq!(episode.renderings.len(), 3);
        }
    }

    #[test]
    fn generation_is_reproducible() {
        let template = template_by_id("system_diagnosis_v1").expect("system template");
        let config = GenerationConfig {
            seed: 9,
            count: 1,
            visibility_probability: 0.8,
        };
        let first = generate_episode(&template, 17, &config).expect("first episode");
        let second = generate_episode(&template, 17, &config).expect("second episode");
        assert_eq!(
            serde_json::to_vec(&first).unwrap(),
            serde_json::to_vec(&second).unwrap()
        );
    }

    #[test]
    fn closed_and_open_choice_keep_distinct_normalization() {
        let template = template_by_id("system_diagnosis_v1").expect("system template");
        let config = GenerationConfig {
            seed: 11,
            count: 1,
            visibility_probability: 1.0,
        };
        let episode = generate_episode(&template, 0, &config).expect("episode");
        let closed = &episode.gold_targets[2].value;
        let open = &episode.gold_targets[3].value;
        match (closed, open) {
            (
                GoldValue::Choice {
                    probabilities: closed,
                    other_probability: closed_other,
                    ..
                },
                GoldValue::Choice {
                    probabilities: open,
                    other_probability: open_other,
                    ..
                },
            ) => {
                assert!((*closed_other).abs() < 1e-9);
                assert!(
                    (closed.iter().map(|item| item.probability).sum::<f64>() - 1.0).abs() < 1e-9
                );
                assert!((*open_other) > 0.0);
                assert!(
                    (open.iter().map(|item| item.probability).sum::<f64>() + *open_other - 1.0)
                        .abs()
                        < 1e-9
                );
            }
            _ => panic!("expected choice targets"),
        }
    }

    #[test]
    fn surface_perturbation_is_strictly_invariant() {
        let template = template_by_id("support_routing_v1").expect("support template");
        let config = GenerationConfig {
            seed: 13,
            count: 1,
            visibility_probability: 1.0,
        };
        let parent = generate_episode(&template, 3, &config).expect("parent");
        let child =
            surface_perturbation(&parent, &template, RenderFormat::Json).expect("surface child");
        verify_perturbation_pair(&parent, &child, &template).expect("surface verification");
        assert_ne!(parent.renderings[0].text, child.renderings[0].text);
    }

    #[test]
    fn observation_perturbation_recomputes_from_less_evidence() {
        let template = template_by_id("network_incident_v1").expect("network template");
        let config = GenerationConfig {
            seed: 15,
            count: 1,
            visibility_probability: 1.0,
        };
        let parent = generate_episode(&template, 4, &config).expect("parent");
        let fact_id = parent
            .evidence_state
            .facts
            .iter()
            .find(|fact| matches!(fact.visibility, Visibility::Visible))
            .expect("at least one visible fact")
            .fact_id
            .clone();
        let child =
            observation_perturbation(&parent, &template, &fact_id).expect("observation child");
        assert!(
            child
                .evidence_state
                .missing_fact_ids
                .iter()
                .any(|id| id == &fact_id)
        );
        assert_ne!(
            parent.provenance.semantic_fingerprint,
            child.provenance.semantic_fingerprint
        );
        validate_episode(&child, &template).expect("observation child validation");
    }

    #[test]
    fn world_intervention_changes_sampled_world_under_do() {
        let template = template_by_id("system_diagnosis_v1").expect("system template");
        let config = GenerationConfig {
            seed: 16,
            count: 1,
            visibility_probability: 1.0,
        };
        let parent = generate_episode(&template, 5, &config).expect("parent");
        let child = world_perturbation(&parent, &template, "root_cause", 1).expect("world child");
        assert_eq!(child.sampled_world[0], 1);
        assert_eq!(
            child.perturbation_links[0].class,
            PerturbationClass::WorldIntervention
        );
        validate_episode(&child, &template).expect("world child validation");
    }

    #[test]
    fn mmap_jsonl_validator_accepts_generated_records() {
        let template = template_by_id("system_diagnosis_v1").expect("system template");
        let config = GenerationConfig {
            seed: 17,
            count: 1,
            visibility_probability: 0.8,
        };
        let episode = generate_episode(&template, 6, &config).expect("episode");
        let path = std::env::temp_dir().join(format!(
            "jev-decision-world-v01-{}-{}.jsonl",
            std::process::id(),
            config.seed
        ));
        std::fs::write(
            &path,
            format!("{}\n", serde_json::to_string(&episode).unwrap()),
        )
        .expect("write test JSONL");
        let report = validate_jsonl(&path, &[template]).expect("validate test JSONL");
        std::fs::remove_file(&path).expect("remove test JSONL");
        assert_eq!(report.episodes, 1);
        assert_eq!(report.failed, 0);
    }
}

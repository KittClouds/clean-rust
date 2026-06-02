use std::env;
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};

use phoenix_dynamic_ner::{
    AdjudicationCase, AdjudicationDecision, AdjudicationError, DecisionKind, EntityLabel,
    MentionAdjudicator,
};
use phoenix_rel_post::{
    GliclassClassificationType, GliclassInstructLabel, GliclassInstructModel,
    GliclassInstructPredictOptions,
};

static GLICLASS_MODEL: OnceLock<Result<Arc<GliclassInstructModel>, String>> = OnceLock::new();

pub fn load_default_adjudicator() -> Result<Box<dyn MentionAdjudicator + Send + Sync>, String> {
    if env_flag("PHOENIX_DYN_NER_GLICLASS_DISABLED") {
        return Err("PHOENIX_DYN_NER_GLICLASS_DISABLED is set".to_owned());
    }
    let model = GLICLASS_MODEL
        .get_or_init(|| {
            let root = find_default_model_root().ok_or_else(|| {
                "missing PHOENIX_GLICLASS_INSTRUCT_MODEL_ROOT and no gliclass-instruct-onnx-v2 directory found"
                    .to_owned()
            })?;
            GliclassInstructModel::load(&root)
                .map(Arc::new)
                .map_err(|error| format!("failed to load {}: {error}", root.display()))
        })
        .as_ref()
        .map_err(Clone::clone)?;

    Ok(Box::new(RuntimeGliclassAdjudicator {
        model: Arc::clone(model),
        min_score: env_f32("PHOENIX_DYN_NER_GLICLASS_MIN_SCORE", 0.40),
        min_margin: env_f32("PHOENIX_DYN_NER_GLICLASS_MIN_MARGIN", 0.12),
    }))
}

struct RuntimeGliclassAdjudicator {
    model: Arc<GliclassInstructModel>,
    min_score: f32,
    min_margin: f32,
}

impl MentionAdjudicator for RuntimeGliclassAdjudicator {
    fn adjudicate(
        &self,
        cases: &[AdjudicationCase],
    ) -> Result<Vec<AdjudicationDecision>, AdjudicationError> {
        let mut decisions = Vec::with_capacity(cases.len());
        for case in cases {
            let labels = kind_hypotheses();
            let text = marked_text(case);
            let prediction = self
                .model
                .predict_structured(
                    &text,
                    &labels,
                    &GliclassInstructPredictOptions {
                        classification_type: GliclassClassificationType::SingleLabel,
                        threshold: 0.0,
                        prompt: Some(kind_prompt(case)),
                        examples: Vec::new(),
                    },
                )
                .map_err(|error| AdjudicationError::Failed(error.to_string()))?;
            let Some(top) = prediction.all_scores.first() else {
                decisions.push(needs_more(case, 0.0));
                continue;
            };
            let runner_up = prediction
                .all_scores
                .get(1)
                .map(|score| score.score)
                .unwrap_or(0.0);
            let margin = top.score - runner_up;
            let Some(label) = label_for_hypothesis(&top.label) else {
                decisions.push(needs_more(case, top.score));
                continue;
            };
            if top.score < self.min_score || margin < self.min_margin {
                decisions.push(needs_more(case, top.score));
                continue;
            }
            decisions.push(AdjudicationDecision {
                mention_id: case.mention_id,
                decision: DecisionKind::Relabel,
                confidence: calibrated_confidence(top.score, margin),
                chosen_label: Some(EntityLabel::new(label)),
                chosen_entity: None,
                modality: None,
                polarity: None,
            });
        }
        Ok(decisions)
    }
}

fn kind_hypotheses() -> Vec<GliclassInstructLabel> {
    KIND_HYPOTHESES
        .iter()
        .map(|(_, hypothesis, description)| GliclassInstructLabel {
            label: (*hypothesis).to_owned(),
            description: Some((*description).to_owned()),
        })
        .collect()
}

fn marked_text(case: &AdjudicationCase) -> String {
    let sentence = case.sentence_text.trim();
    if sentence.is_empty() {
        format!("The exact marked mention is '{}'.", case.surface)
    } else {
        format!(
            "Sentence: {sentence}\nThe exact marked mention is '{}'.",
            case.surface
        )
    }
}

fn kind_prompt(case: &AdjudicationCase) -> String {
    format!(
        "Classify the exact marked mention, not the whole sentence. Marked mention: '{}'. Prefer person for named individual speakers or actors, organization for factions or institutions, location for named places, concept for abstract world rules, and creature for species or nonhuman denizens.",
        case.surface
    )
}

fn label_for_hypothesis(hypothesis: &str) -> Option<&'static str> {
    KIND_HYPOTHESES
        .iter()
        .find_map(|(label, candidate, _)| (*candidate == hypothesis).then_some(*label))
}

fn needs_more(case: &AdjudicationCase, confidence: f32) -> AdjudicationDecision {
    AdjudicationDecision {
        mention_id: case.mention_id,
        decision: DecisionKind::NeedsMore,
        confidence,
        chosen_label: None,
        chosen_entity: None,
        modality: None,
        polarity: None,
    }
}

fn calibrated_confidence(score: f32, margin: f32) -> f32 {
    (0.68 + score.clamp(0.0, 1.0) * 0.24 + margin.clamp(0.0, 1.0) * 0.20).clamp(0.68, 0.92)
}

fn find_default_model_root() -> Option<PathBuf> {
    if let Some(root) = env::var_os("PHOENIX_GLICLASS_INSTRUCT_MODEL_ROOT").map(PathBuf::from) {
        if looks_like_gliclass_instruct_root(&root) {
            return Some(root);
        }
    }

    let cwd = env::current_dir().ok()?;
    for base in cwd.ancestors().take(6) {
        for name in ["gliclass-instruct-onnx-v2", "gliclass-instruct-onnx"] {
            let candidate = base.join(name);
            if looks_like_gliclass_instruct_root(&candidate) {
                return Some(candidate);
            }
        }
    }
    None
}

fn looks_like_gliclass_instruct_root(path: &Path) -> bool {
    path.is_dir()
        && path.join("gliclass_config.json").is_file()
        && path.join("tokenizer.json").is_file()
}

fn env_f32(name: &str, default: f32) -> f32 {
    env::var(name)
        .ok()
        .and_then(|value| value.parse::<f32>().ok())
        .filter(|value| value.is_finite() && *value >= 0.0 && *value <= 1.0)
        .unwrap_or(default)
}

fn env_flag(name: &str) -> bool {
    matches!(
        env::var(name).ok().as_deref(),
        Some("1" | "true" | "TRUE" | "yes" | "YES")
    )
}

const KIND_HYPOTHESES: &[(&str, &str, &str)] = &[
    (
        "Character",
        "The marked mention is a person.",
        "A named human, character, speaker, or individual actor.",
    ),
    (
        "Organization",
        "The marked mention is an organization.",
        "A named faction, institution, company, guild, table, council, or group.",
    ),
    (
        "Location",
        "The marked mention is a location.",
        "A named place, city, region, country, base, landmark, or territory.",
    ),
    (
        "Event",
        "The marked mention is an event.",
        "A named incident, battle, meeting, process, or happening.",
    ),
    (
        "Artifact",
        "The marked mention is an artifact.",
        "A named object, item, device, document, weapon, or created thing.",
    ),
    (
        "Concept",
        "The marked mention is a concept.",
        "An abstract idea, world rule, rank, force, field, classification, or metaphysical system.",
    ),
    (
        "Creature",
        "The marked mention is a creature or species.",
        "A nonhuman species, monster, fantasy creature, or generic denizen group.",
    ),
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confidence_lifts_clear_kind_votes() {
        assert!(calibrated_confidence(0.92, 0.70) > calibrated_confidence(0.42, 0.13));
        assert!(calibrated_confidence(0.42, 0.13) >= 0.68);
    }

    #[test]
    fn hypothesis_labels_map_to_runtime_labels() {
        assert_eq!(
            label_for_hypothesis("The marked mention is a person."),
            Some("Character")
        );
        assert_eq!(
            label_for_hypothesis("The marked mention is a location."),
            Some("Location")
        );
        assert_eq!(
            label_for_hypothesis("The marked mention is a concept."),
            Some("Concept")
        );
        assert_eq!(
            label_for_hypothesis("The marked mention is a creature or species."),
            Some("Creature")
        );
    }
}

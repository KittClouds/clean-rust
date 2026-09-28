use std::collections::BTreeMap;
use std::path::Path;

use crate::gliner_x::{GlinerXModel, GlinerXPrediction};

#[derive(Clone, Debug, PartialEq)]
pub struct RelationSeededSpan {
    pub input_id: String,
    pub surface: String,
    pub label: String,
    pub probability: f32,
    pub span_start: usize,
    pub span_end: usize,
}

pub struct RelationMentionSeeder {
    model: GlinerXModel,
    threshold: f32,
}

impl RelationMentionSeeder {
    pub fn load(model_root: &Path, threshold: f32) -> Result<Self, String> {
        let model = GlinerXModel::load(model_root, threshold).map_err(|error| error.to_string())?;
        Ok(Self { model, threshold })
    }

    pub fn seed_chunk_mentions(
        &self,
        inputs: &[(String, String)],
    ) -> Result<Vec<RelationSeededSpan>, String> {
        if inputs.is_empty() {
            return Ok(Vec::new());
        }
        let labels = relation_seed_labels();
        let mut seeded = Vec::new();
        let texts = inputs
            .iter()
            .map(|(_, text)| text.as_str())
            .collect::<Vec<_>>();
        let predictions = self
            .model
            .predict_texts(&texts, &labels)
            .map_err(|error| error.to_string())?;
        let mut by_sequence = BTreeMap::<usize, Vec<GlinerXPrediction>>::new();
        for prediction in predictions {
            by_sequence
                .entry(prediction.sequence)
                .or_default()
                .push(prediction);
        }
        for (sequence, spans) in by_sequence {
            let Some((input_id, _)) = inputs.get(sequence) else {
                continue;
            };
            for span in filter_seed_sequence(spans, self.threshold) {
                seeded.push(RelationSeededSpan {
                    input_id: input_id.clone(),
                    surface: span.text.trim().to_owned(),
                    label: span.label,
                    probability: span.score,
                    span_start: span.span_start,
                    span_end: span.span_end,
                });
            }
        }
        Ok(seeded)
    }
}

fn relation_seed_labels() -> Vec<&'static str> {
    vec!["person", "organization", "location"]
}

fn filter_seed_sequence(
    sequence: Vec<GlinerXPrediction>,
    threshold: f32,
) -> Vec<GlinerXPrediction> {
    let mut best_by_surface = BTreeMap::<String, GlinerXPrediction>::new();
    for span in sequence {
        if !relation_seed_span_allowed(&span, threshold) {
            continue;
        }
        let key = normalize_surface(&span.text);
        match best_by_surface.get(&key) {
            Some(current) if !prefer_seed_span(&span, current) => {}
            _ => {
                best_by_surface.insert(key, span);
            }
        }
    }
    best_by_surface.into_values().collect()
}

fn relation_seed_span_allowed(span: &GlinerXPrediction, threshold: f32) -> bool {
    if span.score < threshold {
        return false;
    }
    let surface = span.text.trim();
    if surface.is_empty() || is_structural_surface(surface) || is_generic_relation_surface(surface)
    {
        return false;
    }
    if !surface.chars().any(|value| value.is_alphabetic()) {
        return false;
    }
    match span.label.as_str() {
        "person" | "organization" => true,
        "location" => surface.split_whitespace().count() >= 2 || span.score >= threshold.max(0.8),
        _ => false,
    }
}

fn prefer_seed_span(candidate: &GlinerXPrediction, current: &GlinerXPrediction) -> bool {
    let probability_gap = candidate.score - current.score;
    if probability_gap.abs() >= 0.05 {
        return probability_gap > 0.0;
    }
    let candidate_priority = label_priority(&candidate.label);
    let current_priority = label_priority(&current.label);
    if candidate_priority != current_priority {
        return candidate_priority > current_priority;
    }
    if candidate.text.len() != current.text.len() {
        return candidate.text.len() > current.text.len();
    }
    candidate.score > current.score
}

fn label_priority(label: &str) -> i32 {
    match label {
        "person" => 3,
        "organization" => 2,
        "location" => 1,
        _ => 0,
    }
}

fn normalize_surface(surface: &str) -> String {
    let mut out = String::with_capacity(surface.len());
    let mut previous_space = false;
    for ch in surface.chars() {
        if ch.is_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            previous_space = false;
        } else if ch.is_whitespace() && !previous_space && !out.is_empty() {
            out.push(' ');
            previous_space = true;
        }
    }
    out.trim().to_owned()
}

fn is_structural_surface(surface: &str) -> bool {
    let trimmed = surface.trim();
    trimmed.starts_with('#')
        || trimmed.eq_ignore_ascii_case("table of contents")
        || trimmed.to_ascii_lowercase().starts_with("chapter ")
}

fn is_generic_relation_surface(surface: &str) -> bool {
    matches!(
        normalize_surface(surface).as_str(),
        "hero"
            | "heroes"
            | "villain"
            | "villains"
            | "monster"
            | "monsters"
            | "criminal"
            | "criminals"
            | "city"
            | "town"
            | "team"
            | "group"
            | "member"
            | "members"
            | "people"
            | "person"
            | "security"
            | "driving"
            | "chapter"
            | "genius"
            | "guard"
            | "guards"
            | "officer"
            | "officers"
            | "doctor"
            | "chief"
            | "teacher"
            | "father"
            | "mother"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seed_filter_keeps_best_named_surface() {
        let spans = vec![
            pred("New Rome", "location", 0.72),
            pred("New Rome", "organization", 0.71),
            pred("guard", "person", 0.99),
        ];
        let filtered = filter_seed_sequence(spans, 0.55);
        assert_eq!(filtered.len(), 1);
        assert_eq!(filtered[0].label, "organization");
        assert_eq!(filtered[0].text, "New Rome");
    }

    fn pred(text: &str, label: &str, score: f32) -> GlinerXPrediction {
        GlinerXPrediction {
            sequence: 0,
            text: text.to_owned(),
            label: label.to_owned(),
            score,
            span_start: 0,
            span_end: text.len(),
        }
    }
}

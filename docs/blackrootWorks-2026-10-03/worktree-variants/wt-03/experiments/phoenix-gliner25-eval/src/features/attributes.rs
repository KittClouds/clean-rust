use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Result, bail};
use gliner25_rs::overlap::OverlapPolicy;
use gliner25_rs::processor::{SchemaTask, TaskType};
use gliner25_rs::runtime::{sigmoid, softmax};
use serde::{Deserialize, Serialize};

use super::{FeatureEngine, RawMention};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AttributeGroupSpec {
    pub name: String,
    pub labels: Vec<String>,
    #[serde(default)]
    pub applies_to: Option<Vec<String>>,
    #[serde(default)]
    pub multi_label: bool,
    #[serde(default = "default_attribute_threshold")]
    pub threshold: f32,
    #[serde(default)]
    pub qualify_labels: bool,
}

fn default_attribute_threshold() -> f32 {
    0.5
}

#[derive(Debug, Clone, Serialize)]
pub struct AttributeValue {
    pub label: String,
    pub confidence: f32,
}

#[derive(Debug, Clone, Serialize)]
#[serde(untagged)]
pub enum AttributeAssignment {
    Single(AttributeValue),
    Multi(Vec<AttributeValue>),
}

#[derive(Debug, Clone, Serialize)]
pub struct AttributedMention {
    #[serde(flatten)]
    pub mention: RawMention,
    #[serde(flatten)]
    pub attributes: BTreeMap<String, AttributeAssignment>,
}

impl FeatureEngine {
    pub fn extract_attributed(
        &mut self,
        text: &str,
        entity_labels: &[String],
        groups: &[AttributeGroupSpec],
        entity_threshold: f32,
    ) -> Result<Vec<AttributedMention>> {
        validate_groups(entity_labels, groups)?;
        let mut prompt_labels = entity_labels.to_vec();
        let mut attribute_prompts = BTreeSet::new();
        for group in groups {
            for label in &group.labels {
                attribute_prompts.insert(model_label(group, label));
            }
        }
        prompt_labels.extend(attribute_prompts);
        let trace = self.trace(text, &[SchemaTask::Entities(prompt_labels)])?;
        let mentions =
            self.decode_mentions(&trace, entity_threshold, entity_labels, OverlapPolicy::Flat);
        if mentions.is_empty() {
            return Ok(Vec::new());
        }

        let spans: Vec<(usize, usize)> = mentions
            .iter()
            .map(|item| (item.word_start, item.word_end))
            .collect();
        let mut ordered_prompts = Vec::new();
        let mut prompt_to_row = BTreeMap::new();
        for group in groups {
            for label in &group.labels {
                let prompt = model_label(group, label);
                if !prompt_to_row.contains_key(&prompt) {
                    let query = trace
                        .query_id(TaskType::Entities, "entities", &prompt)
                        .ok_or_else(|| anyhow::anyhow!("missing attribute query {prompt:?}"))?;
                    prompt_to_row.insert(prompt.clone(), ordered_prompts.len());
                    ordered_prompts.push(query);
                }
            }
        }
        let logits = self.explicit_logits(&trace, &ordered_prompts, &spans)?;
        let width = spans.len();
        let mut output = Vec::with_capacity(mentions.len());
        for (column, mention) in mentions.into_iter().enumerate() {
            let mut attributes = BTreeMap::new();
            for group in groups {
                if group
                    .applies_to
                    .as_ref()
                    .is_some_and(|labels| !labels.iter().any(|label| label == &mention.field))
                {
                    continue;
                }
                let values: Vec<f32> = group
                    .labels
                    .iter()
                    .map(|label| {
                        let row = prompt_to_row[&model_label(group, label)];
                        logits[row * width + column]
                    })
                    .collect();
                if group.multi_label {
                    let selected = group
                        .labels
                        .iter()
                        .zip(values)
                        .filter_map(|(label, logit)| {
                            let confidence = sigmoid(logit);
                            (confidence >= group.threshold).then(|| AttributeValue {
                                label: label.clone(),
                                confidence,
                            })
                        })
                        .collect();
                    attributes.insert(group.name.clone(), AttributeAssignment::Multi(selected));
                } else {
                    let probabilities = softmax(&values);
                    let best = probabilities
                        .iter()
                        .enumerate()
                        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(std::cmp::Ordering::Equal))
                        .map(|(index, _)| index)
                        .unwrap_or(0);
                    attributes.insert(
                        group.name.clone(),
                        AttributeAssignment::Single(AttributeValue {
                            label: group.labels[best].clone(),
                            confidence: probabilities[best],
                        }),
                    );
                }
            }
            output.push(AttributedMention {
                mention,
                attributes,
            });
        }
        Ok(output)
    }
}

fn model_label(group: &AttributeGroupSpec, label: &str) -> String {
    if group.qualify_labels {
        format!("{}: {label}", group.name)
    } else {
        label.to_owned()
    }
}

fn validate_groups(entity_labels: &[String], groups: &[AttributeGroupSpec]) -> Result<()> {
    let mut names = BTreeSet::new();
    let mut prompts = BTreeSet::new();
    for group in groups {
        if group.name.trim().is_empty() || group.labels.is_empty() {
            bail!("attribute groups require a name and at least one label");
        }
        if !names.insert(group.name.clone()) {
            bail!("duplicate attribute group {}", group.name);
        }
        for label in &group.labels {
            let prompt = model_label(group, label);
            if entity_labels.iter().any(|entity| entity == &prompt) {
                bail!("attribute prompt {prompt:?} collides with an entity label");
            }
            if !prompts.insert(prompt.clone()) {
                bail!("duplicate attribute prompt {prompt:?}");
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qualified_labels_are_collision_safe() {
        let groups = vec![AttributeGroupSpec {
            name: "sentiment".into(),
            labels: vec!["product".into()],
            applies_to: None,
            multi_label: false,
            threshold: 0.5,
            qualify_labels: true,
        }];
        assert!(validate_groups(&["product".into()], &groups).is_ok());
        assert_eq!(model_label(&groups[0], "product"), "sentiment: product");
    }
}

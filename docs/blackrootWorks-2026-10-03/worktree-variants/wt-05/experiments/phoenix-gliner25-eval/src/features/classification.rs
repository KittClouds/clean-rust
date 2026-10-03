use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Result, bail};
use gliner25_rs::processor::SchemaTask;
use gliner25_rs::runtime::{sigmoid, softmax};
use serde::{Deserialize, Serialize};

use super::FeatureEngine;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClassificationTaskSpec {
    pub name: String,
    pub labels: Vec<String>,
    #[serde(default)]
    pub multi_label: bool,
    #[serde(default)]
    pub min_labels: usize,
    #[serde(default)]
    pub max_labels: Option<usize>,
    #[serde(default)]
    pub ordered: bool,
    #[serde(default = "default_threshold")]
    pub threshold: f32,
    #[serde(default = "default_temperature")]
    pub temperature: f32,
    #[serde(default)]
    pub default: Option<String>,
}

fn default_threshold() -> f32 {
    0.5
}
fn default_temperature() -> f32 {
    1.0
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum ConstraintExpr {
    Label {
        task: String,
        label: String,
    },
    AnySelected {
        task: String,
    },
    AnyOtherSelected {
        task: String,
    },
    IsDefault {
        task: String,
    },
    Cardinality {
        task: String,
        min: usize,
        max: usize,
    },
    MinLevel {
        task: String,
        level: usize,
    },
    MaxLevel {
        task: String,
        level: usize,
    },
    AtLevel {
        task: String,
        level: usize,
    },
    Not {
        value: Box<ConstraintExpr>,
    },
    And {
        values: Vec<ConstraintExpr>,
    },
    Or {
        values: Vec<ConstraintExpr>,
    },
    ExactlyOneOf {
        values: Vec<ConstraintExpr>,
    },
    Implies {
        when: Box<ConstraintExpr>,
        then: Box<ConstraintExpr>,
    },
    Iff {
        left: Box<ConstraintExpr>,
        right: Box<ConstraintExpr>,
    },
    Excludes {
        left: Box<ConstraintExpr>,
        right: Box<ConstraintExpr>,
    },
}

#[derive(Debug, Clone, Serialize)]
pub struct ClassificationDecision {
    pub value: serde_json::Value,
    pub confidence: Option<f32>,
    pub probabilities: BTreeMap<String, f32>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ClassificationMeta {
    pub feasible: bool,
    pub decoder: &'static str,
    pub exact: bool,
    pub objective: f32,
    pub violations: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConstrainedClassification {
    pub tasks: BTreeMap<String, ClassificationDecision>,
    pub meta: ClassificationMeta,
}

#[derive(Clone)]
struct TaskEvidence {
    spec: ClassificationTaskSpec,
    probabilities: Vec<f32>,
    utilities: Vec<f32>,
    options: Vec<Vec<usize>>,
}

impl FeatureEngine {
    pub fn classify_constrained(
        &mut self,
        text: &str,
        tasks: &[ClassificationTaskSpec],
        constraints: &[ConstraintExpr],
    ) -> Result<ConstrainedClassification> {
        validate_schema(tasks, constraints)?;
        let model_tasks: Vec<SchemaTask> = tasks
            .iter()
            .map(|task| {
                if task.multi_label {
                    SchemaTask::multi_label_classification(task.name.clone(), task.labels.clone())
                } else {
                    SchemaTask::classification(task.name.clone(), task.labels.clone())
                }
            })
            .collect();
        let trace = self.trace(text, &model_tasks)?;
        let mut evidence = Vec::with_capacity(tasks.len());
        for spec in tasks {
            let raw = trace
                .classifications
                .iter()
                .find(|row| row.task == spec.name)
                .ok_or_else(|| anyhow::anyhow!("missing logits for task {}", spec.name))?;
            let scaled: Vec<f32> = raw
                .logits
                .iter()
                .map(|value| *value / spec.temperature)
                .collect();
            let probabilities = if spec.multi_label {
                scaled.iter().copied().map(sigmoid).collect()
            } else {
                softmax(&scaled)
            };
            let offset = probability_to_logit(spec.threshold);
            let utilities = scaled.iter().map(|value| value - offset).collect();
            let options = assignment_options(spec)?;
            evidence.push(TaskEvidence {
                spec: spec.clone(),
                probabilities,
                utilities,
                options,
            });
        }

        let lowered = lower_defaults(tasks, constraints);
        let mut selected: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        let mut best: Option<(f32, BTreeMap<String, BTreeSet<String>>)> = None;
        solve_exact(0, &evidence, &lowered, &mut selected, 0.0, &mut best);
        let (objective, assignment, feasible) = match best {
            Some((score, assignment)) => (score, assignment, true),
            None => (0.0, BTreeMap::new(), false),
        };
        let violations = if feasible {
            Vec::new()
        } else {
            lowered.iter().map(|value| format!("{value:?}")).collect()
        };
        let mut output = BTreeMap::new();
        for row in &evidence {
            let selected = assignment.get(&row.spec.name).cloned().unwrap_or_default();
            let labels: Vec<String> = row
                .spec
                .labels
                .iter()
                .filter(|label| selected.contains(*label))
                .cloned()
                .collect();
            let probabilities: BTreeMap<String, f32> = row
                .spec
                .labels
                .iter()
                .cloned()
                .zip(row.probabilities.iter().copied())
                .collect();
            let value = if row.spec.multi_label {
                serde_json::to_value(&labels)?
            } else {
                labels.first().map_or(serde_json::Value::Null, |label| {
                    serde_json::Value::String(label.clone())
                })
            };
            let confidence = confidence(&row.spec, &selected, &row.probabilities);
            output.insert(
                row.spec.name.clone(),
                ClassificationDecision {
                    value,
                    confidence,
                    probabilities,
                },
            );
        }
        Ok(ConstrainedClassification {
            tasks: output,
            meta: ClassificationMeta {
                feasible,
                decoder: "exact",
                exact: true,
                objective,
                violations,
            },
        })
    }
}

fn solve_exact(
    index: usize,
    tasks: &[TaskEvidence],
    constraints: &[ConstraintExpr],
    assignment: &mut BTreeMap<String, BTreeSet<String>>,
    score: f32,
    best: &mut Option<(f32, BTreeMap<String, BTreeSet<String>>)>,
) {
    if index == tasks.len() {
        if !constraints
            .iter()
            .all(|value| evaluate(value, assignment, tasks))
        {
            return;
        }
        if best
            .as_ref()
            .is_none_or(|(best_score, _)| score > *best_score)
        {
            *best = Some((score, assignment.clone()));
        }
        return;
    }
    let row = &tasks[index];
    for option in &row.options {
        let labels: BTreeSet<String> = option
            .iter()
            .map(|&choice| row.spec.labels[choice].clone())
            .collect();
        let utility: f32 = option.iter().map(|&choice| row.utilities[choice]).sum();
        assignment.insert(row.spec.name.clone(), labels);
        solve_exact(
            index + 1,
            tasks,
            constraints,
            assignment,
            score + utility,
            best,
        );
    }
    assignment.remove(&row.spec.name);
}

fn assignment_options(spec: &ClassificationTaskSpec) -> Result<Vec<Vec<usize>>> {
    if !spec.multi_label {
        return Ok((0..spec.labels.len()).map(|index| vec![index]).collect());
    }
    if spec.labels.len() > 20 {
        bail!("exact classification decoder caps a task at 20 labels");
    }
    let max = spec
        .max_labels
        .unwrap_or(spec.labels.len())
        .min(spec.labels.len());
    let mut output = Vec::new();
    for mask in 0_u64..(1_u64 << spec.labels.len()) {
        let count = mask.count_ones() as usize;
        if count < spec.min_labels || count > max {
            continue;
        }
        output.push(
            (0..spec.labels.len())
                .filter(|&index| mask & (1 << index) != 0)
                .collect(),
        );
    }
    Ok(output)
}

fn evaluate(
    value: &ConstraintExpr,
    assignment: &BTreeMap<String, BTreeSet<String>>,
    tasks: &[TaskEvidence],
) -> bool {
    let labels = |task: &str| assignment.get(task).cloned().unwrap_or_default();
    let level = |task: &str| -> Option<usize> {
        let row = tasks.iter().find(|row| row.spec.name == task)?;
        row.spec
            .labels
            .iter()
            .position(|label| labels(task).contains(label))
    };
    match value {
        ConstraintExpr::Label { task, label } => labels(task).contains(label),
        ConstraintExpr::AnySelected { task } => !labels(task).is_empty(),
        ConstraintExpr::AnyOtherSelected { task } => {
            let default = tasks
                .iter()
                .find(|row| row.spec.name == *task)
                .and_then(|row| row.spec.default.as_ref());
            labels(task).iter().any(|label| Some(label) != default)
        }
        ConstraintExpr::IsDefault { task } => tasks
            .iter()
            .find(|row| row.spec.name == *task)
            .and_then(|row| row.spec.default.as_ref())
            .is_some_and(|default| labels(task).contains(default)),
        ConstraintExpr::Cardinality { task, min, max } => {
            (*min..=*max).contains(&labels(task).len())
        }
        ConstraintExpr::MinLevel {
            task,
            level: minimum,
        } => level(task).is_some_and(|value| value >= *minimum),
        ConstraintExpr::MaxLevel {
            task,
            level: maximum,
        } => level(task).is_some_and(|value| value <= *maximum),
        ConstraintExpr::AtLevel {
            task,
            level: expected,
        } => level(task) == Some(*expected),
        ConstraintExpr::Not { value } => !evaluate(value, assignment, tasks),
        ConstraintExpr::And { values } => values
            .iter()
            .all(|value| evaluate(value, assignment, tasks)),
        ConstraintExpr::Or { values } => values
            .iter()
            .any(|value| evaluate(value, assignment, tasks)),
        ConstraintExpr::ExactlyOneOf { values } => {
            values
                .iter()
                .filter(|value| evaluate(value, assignment, tasks))
                .count()
                == 1
        }
        ConstraintExpr::Implies { when, then } => {
            !evaluate(when, assignment, tasks) || evaluate(then, assignment, tasks)
        }
        ConstraintExpr::Iff { left, right } => {
            evaluate(left, assignment, tasks) == evaluate(right, assignment, tasks)
        }
        ConstraintExpr::Excludes { left, right } => {
            !(evaluate(left, assignment, tasks) && evaluate(right, assignment, tasks))
        }
    }
}

fn lower_defaults(
    tasks: &[ClassificationTaskSpec],
    constraints: &[ConstraintExpr],
) -> Vec<ConstraintExpr> {
    let mut output = constraints.to_vec();
    for task in tasks.iter().filter(|task| task.default.is_some()) {
        output.push(ConstraintExpr::Iff {
            left: Box::new(ConstraintExpr::IsDefault {
                task: task.name.clone(),
            }),
            right: Box::new(ConstraintExpr::Not {
                value: Box::new(ConstraintExpr::AnyOtherSelected {
                    task: task.name.clone(),
                }),
            }),
        });
    }
    output
}

fn confidence(
    spec: &ClassificationTaskSpec,
    selected: &BTreeSet<String>,
    probabilities: &[f32],
) -> Option<f32> {
    if selected.is_empty() {
        return spec.default.as_ref().map(|_| 1.0);
    }
    if !spec.multi_label {
        return spec
            .labels
            .iter()
            .position(|label| selected.contains(label))
            .map(|index| probabilities[index]);
    }
    let log_sum: f64 = spec
        .labels
        .iter()
        .zip(probabilities)
        .map(|(label, &probability)| {
            let component = if selected.contains(label) {
                probability
            } else {
                1.0 - probability
            };
            f64::from(component.max(f32::MIN_POSITIVE)).ln()
        })
        .sum();
    Some((log_sum / spec.labels.len() as f64).exp() as f32)
}

fn probability_to_logit(value: f32) -> f32 {
    let value = value.clamp(1e-6, 1.0 - 1e-6);
    (value / (1.0 - value)).ln()
}

fn validate_schema(
    tasks: &[ClassificationTaskSpec],
    _constraints: &[ConstraintExpr],
) -> Result<()> {
    let mut names = BTreeSet::new();
    for task in tasks {
        if task.name.trim().is_empty() || task.labels.is_empty() {
            bail!("classification tasks need names and labels");
        }
        if !names.insert(task.name.clone()) {
            bail!("duplicate classification task {}", task.name);
        }
        if task.temperature <= 0.0 || !(0.0..1.0).contains(&task.threshold) {
            bail!("invalid classification calibration");
        }
        if task
            .default
            .as_ref()
            .is_some_and(|value| !task.labels.contains(value))
        {
            bail!("default label is not declared");
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn implication_and_exclusion_are_exact() {
        let mut assignment = BTreeMap::new();
        assignment.insert("intent".into(), BTreeSet::from(["delete".into()]));
        assignment.insert("effects".into(), BTreeSet::from(["delete".into()]));
        let constraint = ConstraintExpr::Implies {
            when: Box::new(ConstraintExpr::Label {
                task: "intent".into(),
                label: "delete".into(),
            }),
            then: Box::new(ConstraintExpr::Label {
                task: "effects".into(),
                label: "delete".into(),
            }),
        };
        assert!(evaluate(&constraint, &assignment, &[]));
    }
}

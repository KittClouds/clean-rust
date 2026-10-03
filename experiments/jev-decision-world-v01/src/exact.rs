use anyhow::{Context, Result, bail};

use crate::types::{
    ChoiceMode, EvidenceState, GoldTarget, GoldValue, Query, SolverMethod, SolverReceipt,
    WorldTemplate,
};

#[derive(Clone, Debug, PartialEq)]
pub struct ExactPosterior {
    pub evidence_probability: f64,
    pub marginals: Vec<Vec<f64>>,
}

pub fn solve_exact(template: &WorldTemplate, evidence: &EvidenceState) -> Result<ExactPosterior> {
    crate::validate::validate_template(template)?;

    let mut posterior = ExactPosterior {
        evidence_probability: 0.0,
        marginals: template
            .variables
            .iter()
            .map(|variable| vec![0.0; variable.domain.len()])
            .collect(),
    };
    let mut assignment = vec![0_u8; template.variables.len()];
    enumerate_assignments(template, evidence, 0, &mut assignment, &mut posterior)?;

    if !posterior.evidence_probability.is_finite() || posterior.evidence_probability <= 0.0 {
        bail!("evidence has zero or non-finite probability");
    }
    for marginal in &mut posterior.marginals {
        for probability in marginal {
            *probability /= posterior.evidence_probability;
        }
    }
    Ok(posterior)
}

fn enumerate_assignments(
    template: &WorldTemplate,
    evidence: &EvidenceState,
    variable_index: usize,
    assignment: &mut [u8],
    posterior: &mut ExactPosterior,
) -> Result<()> {
    if variable_index == template.variables.len() {
        if !constraints_hold(template, assignment) {
            return Ok(());
        }
        let prior = assignment_probability(template, assignment)?;
        let likelihood = evidence_likelihood(template, evidence, assignment)?;
        let weight = prior * likelihood;
        if weight <= 0.0 {
            return Ok(());
        }
        posterior.evidence_probability += weight;
        for (index, value) in assignment.iter().copied().enumerate() {
            posterior.marginals[index][value as usize] += weight;
        }
        return Ok(());
    }

    let domain_len = template.variables[variable_index].domain.len();
    for value in 0..domain_len {
        assignment[variable_index] = u8::try_from(value).with_context(|| {
            format!(
                "domain for {} exceeds u8",
                template.variables[variable_index].id
            )
        })?;
        enumerate_assignments(
            template,
            evidence,
            variable_index + 1,
            assignment,
            posterior,
        )?;
    }
    Ok(())
}

fn constraints_hold(template: &WorldTemplate, assignment: &[u8]) -> bool {
    template.constraints.iter().all(|constraint| {
        let Some(if_index) = template.variable_index(&constraint.if_variable) else {
            return false;
        };
        let Some(then_index) = template.variable_index(&constraint.then_variable) else {
            return false;
        };
        assignment[if_index] != constraint.if_value
            || assignment[then_index] == constraint.then_value
    })
}

fn assignment_probability(template: &WorldTemplate, assignment: &[u8]) -> Result<f64> {
    let mut probability = 1.0;
    for mechanism in &template.mechanisms {
        let target_index = template
            .variable_index(&mechanism.target)
            .context("mechanism target disappeared after validation")?;
        let target_domain_len = template.variables[target_index].domain.len();
        let row = parent_row(template, mechanism, assignment)?;
        let table_index = row * target_domain_len + assignment[target_index] as usize;
        probability *= mechanism.table[table_index];
    }
    Ok(probability)
}

fn parent_row(
    template: &WorldTemplate,
    mechanism: &crate::types::Mechanism,
    assignment: &[u8],
) -> Result<usize> {
    let mut row = 0_usize;
    let mut stride = 1_usize;
    for parent in mechanism.parents.iter().rev() {
        let parent_index = template
            .variable_index(parent)
            .context("mechanism parent disappeared after validation")?;
        row += assignment[parent_index] as usize * stride;
        stride *= template.variables[parent_index].domain.len();
    }
    Ok(row)
}

fn evidence_likelihood(
    template: &WorldTemplate,
    evidence: &EvidenceState,
    assignment: &[u8],
) -> Result<f64> {
    let mut likelihood = 1.0;
    for fact in &evidence.facts {
        if !matches!(fact.visibility, crate::types::Visibility::Visible) {
            continue;
        }
        let Some(observed_value) = fact.observed_value else {
            bail!("visible evidence {} has no observed value", fact.fact_id);
        };
        let channel = template
            .channel(&fact.channel_id)
            .with_context(|| format!("missing observation channel {}", fact.channel_id))?;
        let source_index = template
            .variable_index(&fact.source_variable)
            .context("evidence source disappeared after validation")?;
        let observed_domain_len = channel.observed_domain.len();
        let source_domain_len = template.variables[source_index].domain.len();
        let source_value = assignment[source_index] as usize;
        let observed_value = observed_value as usize;
        if source_value >= source_domain_len || observed_value >= observed_domain_len {
            bail!("evidence value is outside its channel domain");
        }
        likelihood *= channel.likelihood_table[source_value * observed_domain_len + observed_value];
    }
    Ok(likelihood)
}

pub fn targets_from_queries(
    template: &WorldTemplate,
    evidence: &EvidenceState,
    queries: &[Query],
    seed: u64,
) -> Result<Vec<GoldTarget>> {
    let posterior = solve_exact(template, evidence)?;
    let conditioning_evidence = evidence.visible_fact_ids.clone();
    queries
        .iter()
        .map(|query| {
            let variable_index = template
                .variable_index(query.variable())
                .with_context(|| format!("query {} references unknown variable", query.id()))?;
            let distribution = &posterior.marginals[variable_index];
            let solver = SolverReceipt {
                method: SolverMethod::ExactEnumeration,
                template_id: template.template_id.clone(),
                conditioning_evidence: conditioning_evidence.clone(),
                approximation: false,
                seed,
            };
            let value = match query {
                Query::Proposition { value, .. } => {
                    let true_probability = probability_at(distribution, *value)?;
                    GoldValue::Proposition {
                        true_probability,
                        false_probability: 1.0 - true_probability,
                    }
                }
                Query::Applicability { value, .. } => GoldValue::IndependentApplicability {
                    probability: probability_at(distribution, *value)?,
                },
                Query::Choice {
                    candidate_values,
                    mode,
                    ..
                } => choice_target(distribution, candidate_values, mode.clone())?,
                Query::Ordinal { .. } => GoldValue::Ordinal {
                    distribution: distribution.clone(),
                    expected_value: expected_ordinal_value(template, variable_index, distribution),
                    entropy: entropy(distribution),
                },
                Query::Abstain {
                    entropy_threshold, ..
                } => {
                    let target_entropy = entropy(distribution);
                    let max_entropy = (distribution.len() as f64).ln();
                    let answerability = if max_entropy > 0.0 {
                        1.0 - target_entropy / max_entropy
                    } else {
                        1.0
                    };
                    GoldValue::Abstention {
                        posterior: distribution.clone(),
                        entropy: target_entropy,
                        answerability,
                        abstain_recommended: target_entropy >= *entropy_threshold,
                    }
                }
            };
            Ok(GoldTarget {
                query_id: query.id().to_string(),
                value,
                solver,
            })
        })
        .collect()
}

fn probability_at(distribution: &[f64], value: u8) -> Result<f64> {
    distribution
        .get(value as usize)
        .copied()
        .context("query value is outside variable domain")
}

fn choice_target(
    distribution: &[f64],
    candidate_values: &[u8],
    mode: ChoiceMode,
) -> Result<GoldValue> {
    if candidate_values.is_empty() {
        bail!("choice query has no candidates");
    }
    let mut mass = 0.0;
    let mut probabilities = Vec::with_capacity(candidate_values.len());
    for value in candidate_values {
        let probability = probability_at(distribution, *value)?;
        mass += probability;
        probabilities.push((*value, probability));
    }
    if mass <= 0.0 {
        bail!("choice candidate set has zero posterior mass");
    }
    let probabilities = probabilities
        .into_iter()
        .map(|(value, probability)| crate::types::NamedProbability {
            value,
            probability: match mode {
                ChoiceMode::ClosedWorld => probability / mass,
                ChoiceMode::OpenWorld => probability,
            },
        })
        .collect();
    Ok(GoldValue::Choice {
        mode: mode.clone(),
        probabilities,
        other_probability: match mode {
            ChoiceMode::ClosedWorld => 0.0,
            ChoiceMode::OpenWorld => (1.0 - mass).max(0.0),
        },
    })
}

fn expected_ordinal_value(
    template: &WorldTemplate,
    variable_index: usize,
    distribution: &[f64],
) -> f64 {
    distribution
        .iter()
        .enumerate()
        .map(|(index, probability)| {
            template.variables[variable_index]
                .domain
                .get(index)
                .and_then(|value| value.parse::<f64>().ok())
                .unwrap_or(index as f64 + 1.0)
                * probability
        })
        .sum()
}

pub fn entropy(distribution: &[f64]) -> f64 {
    distribution
        .iter()
        .filter(|probability| **probability > 0.0)
        .map(|probability| -probability * probability.ln())
        .sum()
}

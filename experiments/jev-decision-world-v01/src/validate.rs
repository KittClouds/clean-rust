use std::collections::{BTreeSet, HashMap};
use std::path::Path;

use anyhow::{Context, Result, ensure};
use hashbrown::HashMap as FastHashMap;
use memchr::memchr_iter;
use memmap2::MmapOptions;
use serde::de::DeserializeOwned;

use crate::exact::{entropy, targets_from_queries};
use crate::types::{
    AuthorityClass, CONTRACT, ChoiceMode, Episode, EvidenceFact, GoldValue, Query, RenderFormat,
    SolverMethod, Visibility, WorldTemplate,
};

const PROBABILITY_EPSILON: f64 = 1.0e-9;

#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize, PartialEq)]
pub struct ValidationReport {
    pub episodes: usize,
    pub failed: usize,
    pub errors: Vec<String>,
}

pub(crate) fn validate_template(template: &WorldTemplate) -> Result<()> {
    ensure!(
        !template.family_id.is_empty(),
        "template family_id is empty"
    );
    ensure!(!template.template_id.is_empty(), "template_id is empty");
    ensure!(template.version > 0, "template version must be positive");
    ensure!(!template.variables.is_empty(), "template has no variables");

    let mut variables = FastHashMap::with_capacity(template.variables.len());
    for (index, variable) in template.variables.iter().enumerate() {
        ensure!(!variable.id.is_empty(), "variable {index} has empty id");
        ensure!(
            !variable.domain.is_empty(),
            "variable {} has empty domain",
            variable.id
        );
        ensure!(
            variable.domain.len() <= usize::from(u8::MAX) + 1,
            "variable {} has more than 256 values",
            variable.id
        );
        ensure!(
            variable.domain.iter().all(|value| !value.is_empty()),
            "variable {} has an empty domain value",
            variable.id
        );
        let previous = variables.insert(variable.id.as_str(), index);
        ensure!(previous.is_none(), "duplicate variable {}", variable.id);
    }

    let mut mechanisms = FastHashMap::with_capacity(template.mechanisms.len());
    for mechanism in &template.mechanisms {
        let target_index = *variables
            .get(mechanism.target.as_str())
            .with_context(|| format!("mechanism targets unknown variable {}", mechanism.target))?;
        ensure!(
            mechanisms
                .insert(mechanism.target.as_str(), mechanism)
                .is_none(),
            "duplicate mechanism for {}",
            mechanism.target
        );
        let mut parents = BTreeSet::new();
        let mut parent_cardinality = 1_usize;
        for parent in &mechanism.parents {
            ensure!(parents.insert(parent), "duplicate parent {}", parent);
            let parent_index = *variables.get(parent.as_str()).with_context(|| {
                format!("mechanism {} has unknown parent {parent}", mechanism.target)
            })?;
            parent_cardinality = parent_cardinality
                .checked_mul(template.variables[parent_index].domain.len())
                .context("parent cardinality overflow")?;
        }
        let expected_len = parent_cardinality
            .checked_mul(template.variables[target_index].domain.len())
            .context("mechanism table length overflow")?;
        ensure!(
            mechanism.table.len() == expected_len,
            "mechanism {} has table length {}, expected {}",
            mechanism.target,
            mechanism.table.len(),
            expected_len
        );
        validate_probability_rows(
            &mechanism.table,
            template.variables[target_index].domain.len(),
            &format!("mechanism {}", mechanism.target),
        )?;
    }
    ensure!(
        mechanisms.len() == template.variables.len(),
        "every v0 variable must have exactly one generating mechanism"
    );

    validate_dag(template, &variables)?;

    for constraint in &template.constraints {
        validate_value(
            &variables,
            template,
            &constraint.if_variable,
            constraint.if_value,
        )?;
        validate_value(
            &variables,
            template,
            &constraint.then_variable,
            constraint.then_value,
        )?;
    }

    let mut channels = FastHashMap::with_capacity(template.observation_channels.len());
    for channel in &template.observation_channels {
        let source_index = *variables
            .get(channel.source_variable.as_str())
            .with_context(|| format!("channel {} has unknown source", channel.id))?;
        ensure!(
            !channel.observed_domain.is_empty(),
            "channel {} has empty observed domain",
            channel.id
        );
        let expected_len = template.variables[source_index]
            .domain
            .len()
            .checked_mul(channel.observed_domain.len())
            .context("observation table length overflow")?;
        ensure!(
            channel.likelihood_table.len() == expected_len,
            "channel {} has table length {}, expected {}",
            channel.id,
            channel.likelihood_table.len(),
            expected_len
        );
        validate_probability_rows(
            &channel.likelihood_table,
            channel.observed_domain.len(),
            &format!("channel {}", channel.id),
        )?;
        ensure!(
            (0.0..=1.0).contains(&channel.default_visibility_probability),
            "channel {} visibility probability is outside [0, 1]",
            channel.id
        );
        ensure!(
            channels.insert(channel.id.as_str(), channel).is_none(),
            "duplicate observation channel {}",
            channel.id
        );
    }

    let mut derived = FastHashMap::with_capacity(template.derived_variables.len());
    for variable in &template.derived_variables {
        let source_index = *variables
            .get(variable.source_variable.as_str())
            .with_context(|| format!("derived variable {} has unknown source", variable.id))?;
        ensure!(
            variable.mapping.len() == template.variables[source_index].domain.len(),
            "derived variable {} has invalid mapping length",
            variable.id
        );
        ensure!(
            derived.insert(variable.id.as_str(), variable).is_none(),
            "duplicate derived variable {}",
            variable.id
        );
    }
    Ok(())
}

fn validate_probability_rows(table: &[f64], row_width: usize, label: &str) -> Result<()> {
    ensure!(row_width > 0, "{label} has zero-width rows");
    for (row_index, row) in table.chunks_exact(row_width).enumerate() {
        let mut sum = 0.0;
        for probability in row {
            ensure!(
                probability.is_finite() && *probability >= 0.0,
                "{label} row {row_index} has invalid probability"
            );
            sum += probability;
        }
        ensure!(
            (sum - 1.0).abs() <= PROBABILITY_EPSILON,
            "{label} row {row_index} sums to {sum}, expected 1"
        );
    }
    Ok(())
}

fn validate_dag(template: &WorldTemplate, variables: &FastHashMap<&str, usize>) -> Result<()> {
    let mut state = vec![0_u8; template.variables.len()];
    for index in 0..template.variables.len() {
        visit_dag(template, variables, index, &mut state)?;
    }
    Ok(())
}

fn visit_dag(
    template: &WorldTemplate,
    variables: &FastHashMap<&str, usize>,
    index: usize,
    state: &mut [u8],
) -> Result<()> {
    if state[index] == 2 {
        return Ok(());
    }
    ensure!(
        state[index] != 1,
        "mechanism graph contains a directed cycle at {}",
        template.variables[index].id
    );
    state[index] = 1;
    let mechanism = template
        .mechanism(&template.variables[index].id)
        .context("validated mechanism disappeared")?;
    for parent in &mechanism.parents {
        let parent_index = *variables
            .get(parent.as_str())
            .context("validated parent disappeared")?;
        visit_dag(template, variables, parent_index, state)?;
    }
    state[index] = 2;
    Ok(())
}

fn validate_value(
    variables: &FastHashMap<&str, usize>,
    template: &WorldTemplate,
    variable: &str,
    value: u8,
) -> Result<()> {
    let index = *variables
        .get(variable)
        .with_context(|| format!("unknown variable {variable}"))?;
    ensure!(
        usize::from(value) < template.variables[index].domain.len(),
        "value {value} is outside variable {variable}"
    );
    Ok(())
}

pub fn validate_episode(episode: &Episode, template: &WorldTemplate) -> Result<()> {
    validate_template(template)?;
    ensure!(
        episode.contract == CONTRACT,
        "episode has unexpected contract"
    );
    ensure!(
        episode.authority == AuthorityClass::SyntheticControl,
        "v0 generator only accepts synthetic_control authority"
    );
    ensure!(
        episode.template.family_id == template.family_id,
        "episode/template family mismatch"
    );
    ensure!(
        episode.template.template_id == template.template_id,
        "episode/template id mismatch"
    );
    ensure!(
        episode.template.version == template.version,
        "episode/template version mismatch"
    );
    ensure!(
        episode.sampled_world.len() == template.variables.len(),
        "sampled world has wrong length"
    );
    for (index, value) in episode.sampled_world.iter().copied().enumerate() {
        ensure!(
            usize::from(value) < template.variables[index].domain.len(),
            "sampled world value outside domain"
        );
    }

    let mut fact_ids = FastHashMap::with_capacity(episode.evidence_state.facts.len());
    let mut visible_ids = Vec::new();
    let mut missing_ids = Vec::new();
    for fact in &episode.evidence_state.facts {
        validate_fact(template, fact)?;
        ensure!(
            fact.true_value
                == episode.sampled_world[template.variable_index(&fact.source_variable).unwrap()],
            "evidence true value disagrees with sampled world"
        );
        ensure!(
            fact_ids.insert(fact.fact_id.as_str(), fact).is_none(),
            "duplicate evidence fact {}",
            fact.fact_id
        );
        match fact.visibility {
            Visibility::Visible => {
                ensure!(
                    fact.observed_value.is_some(),
                    "visible fact {} has no observed value",
                    fact.fact_id
                );
                visible_ids.push(fact.fact_id.clone());
            }
            Visibility::Hidden => {
                ensure!(
                    fact.observed_value.is_none(),
                    "hidden fact {} leaks observed value",
                    fact.fact_id
                );
                missing_ids.push(fact.fact_id.clone());
            }
        }
    }
    ensure!(
        visible_ids == episode.evidence_state.visible_fact_ids,
        "visible_fact_ids must equal visible facts in stable order"
    );
    ensure!(
        missing_ids == episode.evidence_state.missing_fact_ids,
        "missing_fact_ids must equal hidden facts in stable order"
    );

    validate_queries(template, &episode.queries)?;
    ensure!(
        episode.gold_targets.len() == episode.queries.len(),
        "gold/query count mismatch"
    );
    let expected = targets_from_queries(
        template,
        &episode.evidence_state,
        &episode.queries,
        episode.provenance.seed,
    )?;
    for (actual, expected) in episode.gold_targets.iter().zip(expected.iter()) {
        ensure!(
            actual.query_id == expected.query_id,
            "gold query ordering/id mismatch"
        );
        validate_gold(&actual.value)?;
        ensure!(
            gold_close(&actual.value, &expected.value),
            "gold target {} does not match exact solver",
            actual.query_id
        );
        ensure!(
            actual.solver.method == SolverMethod::ExactEnumeration,
            "only exact solver is valid in v0"
        );
        ensure!(
            actual.solver.template_id == template.template_id,
            "gold solver template mismatch"
        );
        ensure!(
            actual.solver.conditioning_evidence == episode.evidence_state.visible_fact_ids,
            "gold conditioning evidence mismatch"
        );
        ensure!(
            !actual.solver.approximation,
            "exact solver cannot be marked approximate"
        );
    }
    validate_renderings(&episode.renderings, &fact_ids)?;
    Ok(())
}

fn validate_fact(template: &WorldTemplate, fact: &EvidenceFact) -> Result<()> {
    let source_index = template
        .variable_index(&fact.source_variable)
        .with_context(|| format!("fact {} has unknown source", fact.fact_id))?;
    ensure!(
        usize::from(fact.true_value) < template.variables[source_index].domain.len(),
        "fact true value outside source domain"
    );
    let channel = template
        .channel(&fact.channel_id)
        .with_context(|| format!("fact {} has unknown channel", fact.fact_id))?;
    ensure!(
        channel.source_variable == fact.source_variable,
        "fact/channel source mismatch"
    );
    if let Some(value) = fact.observed_value {
        ensure!(
            usize::from(value) < channel.observed_domain.len(),
            "fact observed value outside channel domain"
        );
    }
    Ok(())
}

fn validate_queries(template: &WorldTemplate, queries: &[Query]) -> Result<()> {
    let mut ids = BTreeSet::new();
    for query in queries {
        ensure!(ids.insert(query.id()), "duplicate query id {}", query.id());
        let variable = template
            .variable(query.variable())
            .with_context(|| format!("query {} has unknown variable", query.id()))?;
        match query {
            Query::Proposition { value, .. } | Query::Applicability { value, .. } => ensure!(
                usize::from(*value) < variable.domain.len(),
                "query {} value outside domain",
                query.id()
            ),
            Query::Choice {
                candidate_values, ..
            } => {
                ensure!(
                    !candidate_values.is_empty(),
                    "choice query {} has no candidates",
                    query.id()
                );
                let mut candidates = BTreeSet::new();
                for value in candidate_values {
                    ensure!(
                        usize::from(*value) < variable.domain.len(),
                        "choice query {} value outside domain",
                        query.id()
                    );
                    ensure!(
                        candidates.insert(value),
                        "choice query {} repeats a candidate",
                        query.id()
                    );
                }
            }
            Query::Ordinal { .. } => ensure!(
                variable.ordered,
                "ordinal query {} targets unordered variable",
                query.id()
            ),
            Query::Abstain {
                entropy_threshold, ..
            } => ensure!(
                entropy_threshold.is_finite() && *entropy_threshold >= 0.0,
                "abstention threshold invalid for {}",
                query.id()
            ),
        }
    }
    Ok(())
}

fn validate_gold(value: &GoldValue) -> Result<()> {
    match value {
        GoldValue::Proposition {
            true_probability,
            false_probability,
        } => {
            validate_probability(*true_probability)?;
            validate_probability(*false_probability)?;
            ensure!(
                (*true_probability + *false_probability - 1.0).abs() <= PROBABILITY_EPSILON,
                "proposition probabilities do not normalize"
            );
        }
        GoldValue::IndependentApplicability { probability } => validate_probability(*probability)?,
        GoldValue::Choice {
            probabilities,
            other_probability,
            mode,
        } => {
            let mut sum = *other_probability;
            let mut values = BTreeSet::new();
            for probability in probabilities {
                ensure!(
                    values.insert(probability.value),
                    "choice gold repeats a value"
                );
                validate_probability(probability.probability)?;
                sum += probability.probability;
            }
            validate_probability(*other_probability)?;
            if matches!(mode, ChoiceMode::ClosedWorld) {
                ensure!(
                    (*other_probability).abs() <= PROBABILITY_EPSILON
                        && (sum - 1.0).abs() <= PROBABILITY_EPSILON,
                    "closed-world choice does not normalize"
                );
            } else {
                ensure!(
                    (sum - 1.0).abs() <= PROBABILITY_EPSILON,
                    "open-world choice plus other does not normalize"
                );
            }
        }
        GoldValue::Ordinal {
            distribution,
            expected_value,
            entropy: target_entropy,
        } => {
            validate_distribution(distribution)?;
            ensure!(
                expected_value.is_finite() && target_entropy.is_finite() && *target_entropy >= 0.0,
                "ordinal summary invalid"
            );
            ensure!(
                (entropy(distribution) - *target_entropy).abs() <= PROBABILITY_EPSILON,
                "ordinal entropy mismatch"
            );
        }
        GoldValue::Abstention {
            posterior,
            entropy: target_entropy,
            answerability,
            ..
        } => {
            validate_distribution(posterior)?;
            ensure!(
                answerability.is_finite() && (0.0..=1.0).contains(answerability),
                "abstention answerability outside [0,1]"
            );
            ensure!(
                (entropy(posterior) - *target_entropy).abs() <= PROBABILITY_EPSILON,
                "abstention entropy mismatch"
            );
        }
    }
    Ok(())
}

fn validate_probability(probability: f64) -> Result<()> {
    ensure!(
        probability.is_finite() && (0.0..=1.0).contains(&probability),
        "probability outside [0,1]"
    );
    Ok(())
}

fn validate_distribution(distribution: &[f64]) -> Result<()> {
    ensure!(!distribution.is_empty(), "distribution is empty");
    let mut sum = 0.0;
    for probability in distribution {
        validate_probability(*probability)?;
        sum += probability;
    }
    ensure!(
        (sum - 1.0).abs() <= PROBABILITY_EPSILON,
        "distribution sums to {sum}"
    );
    Ok(())
}

fn gold_close(left: &GoldValue, right: &GoldValue) -> bool {
    match (left, right) {
        (
            GoldValue::Proposition {
                true_probability: lt,
                false_probability: lf,
            },
            GoldValue::Proposition {
                true_probability: rt,
                false_probability: rf,
            },
        ) => approx(*lt, *rt) && approx(*lf, *rf),
        (
            GoldValue::IndependentApplicability { probability: left },
            GoldValue::IndependentApplicability { probability: right },
        ) => approx(*left, *right),
        (
            GoldValue::Choice {
                mode: lm,
                probabilities: lp,
                other_probability: lo,
            },
            GoldValue::Choice {
                mode: rm,
                probabilities: rp,
                other_probability: ro,
            },
        ) => {
            lm == rm
                && approx(*lo, *ro)
                && lp.len() == rp.len()
                && lp.iter().zip(rp).all(|(left, right)| {
                    left.value == right.value && approx(left.probability, right.probability)
                })
        }
        (
            GoldValue::Ordinal {
                distribution: ld,
                expected_value: le,
                entropy: lh,
            },
            GoldValue::Ordinal {
                distribution: rd,
                expected_value: re,
                entropy: rh,
            },
        ) => vectors_close(ld, rd) && approx(*le, *re) && approx(*lh, *rh),
        (
            GoldValue::Abstention {
                posterior: lp,
                entropy: lh,
                answerability: la,
                abstain_recommended: lr,
            },
            GoldValue::Abstention {
                posterior: rp,
                entropy: rh,
                answerability: ra,
                abstain_recommended: rr,
            },
        ) => vectors_close(lp, rp) && approx(*lh, *rh) && approx(*la, *ra) && lr == rr,
        _ => false,
    }
}

fn vectors_close(left: &[f64], right: &[f64]) -> bool {
    left.len() == right.len()
        && left
            .iter()
            .zip(right)
            .all(|(left, right)| approx(*left, *right))
}

fn approx(left: f64, right: f64) -> bool {
    (left - right).abs() <= 5.0e-9
}

fn validate_renderings(
    renderings: &[crate::types::Rendering],
    facts: &FastHashMap<&str, &EvidenceFact>,
) -> Result<()> {
    for rendering in renderings {
        ensure!(!rendering.text.is_empty(), "rendering text is empty");
        for fact_id in &rendering.source_fact_ids {
            let fact = facts
                .get(fact_id.as_str())
                .with_context(|| format!("rendering references unknown fact {fact_id}"))?;
            ensure!(
                matches!(fact.visibility, Visibility::Visible),
                "rendering leaks hidden fact {fact_id}"
            );
        }
        match rendering.format {
            RenderFormat::Json | RenderFormat::Log | RenderFormat::Prose => {}
        }
    }
    Ok(())
}

pub fn validate_jsonl(path: &Path, templates: &[WorldTemplate]) -> Result<ValidationReport> {
    let file = std::fs::File::open(path).with_context(|| format!("opening {}", path.display()))?;
    // The file is opened read-only and the mapping is never mutated or retained beyond this call.
    let mapped = unsafe { MmapOptions::new().map(&file) }
        .with_context(|| format!("mapping {}", path.display()))?;
    let mut by_id = HashMap::with_capacity(templates.len());
    for template in templates {
        validate_template(template)?;
        by_id.insert(template.template_id.as_str(), template);
    }
    let mut report = ValidationReport::default();
    let mut line_start = 0_usize;
    for (line_index, line_end) in memchr_iter(b'\n', &mapped)
        .chain(std::iter::once(mapped.len()))
        .enumerate()
    {
        let line = &mapped[line_start..line_end.min(mapped.len())];
        let line = trim_jsonl_line(line);
        if line.is_empty() {
            line_start = line_end.saturating_add(1);
            continue;
        }
        report.episodes += 1;
        match parse_json::<Episode>(line).and_then(|episode| {
            let template = by_id
                .get(episode.template.template_id.as_str())
                .context("unknown episode template")?;
            validate_episode(&episode, template)
        }) {
            Ok(()) => {}
            Err(error) => {
                report.failed += 1;
                if report.errors.len() < 32 {
                    report
                        .errors
                        .push(format!("line {}: {error:#}", line_index + 1));
                }
            }
        }
        line_start = line_end.saturating_add(1);
    }
    Ok(report)
}

fn trim_jsonl_line(line: &[u8]) -> &[u8] {
    let mut start = 0;
    let mut end = line.len();
    while start < end && matches!(line[start], b' ' | b'\t' | b'\r' | b'\n') {
        start += 1;
    }
    while end > start && matches!(line[end - 1], b' ' | b'\t' | b'\r' | b'\n') {
        end -= 1;
    }
    &line[start..end]
}

fn parse_json<T: DeserializeOwned>(bytes: &[u8]) -> Result<T> {
    serde_json::from_slice(bytes).context("invalid JSONL episode")
}

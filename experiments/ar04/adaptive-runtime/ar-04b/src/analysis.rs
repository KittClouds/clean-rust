use std::collections::BTreeMap;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

use crate::protocol::{
    self, Candidate, FrozenState, ReferenceScore, SentinelMethod, SentinelScore, TIE_EPSILON,
};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct ComparisonKey {
    source: u8,
    panel_size: u16,
}

impl ComparisonKey {
    fn name(self) -> &'static str {
        match self.source {
            0 => "training_exact",
            1 => "sentinel_exact",
            _ => "sentinel_taylor",
        }
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct Metrics {
    spearman: Option<f64>,
    pairwise_agreement: Option<f64>,
    pair_count: f64,
    tied_source_pairs: f64,
    tied_reference_pairs: f64,
    top1_agreement: f64,
    candidate_regret: f64,
}

#[derive(Clone, Copy)]
struct MetricRecord {
    state_id: usize,
    cell_id: usize,
    dataset_id: usize,
    initialization_id: usize,
    panel_id: i16,
    key: ComparisonKey,
    metrics: Metrics,
}

#[derive(Clone, Copy)]
struct CellMetric {
    dataset_id: usize,
    initialization_id: usize,
    key: ComparisonKey,
    metrics: Metrics,
}

type CellStateMetrics = Vec<(usize, usize, Metrics)>;
type FidelityKey = (usize, u8, u16);
type ExactTaylorScores = (Vec<f64>, Vec<f64>);

#[derive(Clone, Copy, Default)]
struct Fidelity {
    rmse: f64,
    mae: f64,
    spearman: Option<f64>,
    pairwise_agreement: Option<f64>,
}

pub fn analyze(
    output_dir: &Path,
    states: &[FrozenState],
    candidates: &[Vec<Candidate>],
    references: &[ReferenceScore],
    sentinels: &[SentinelScore],
) -> io::Result<()> {
    let reference_by_state = group_references(references, states, candidates)?;
    let sentinel_groups = group_sentinels(sentinels, states, candidates)?;
    let mut records = Vec::with_capacity(states.len() * 41);

    for state in states {
        let reference = &reference_by_state[state.state_id];
        let training: Vec<_> = references
            .iter()
            .filter(|row| row.state_id == state.state_id)
            .map(|row| row.training_utility)
            .collect();
        records.push(MetricRecord {
            state_id: state.state_id,
            cell_id: state.cell_id,
            dataset_id: state.dataset_id,
            initialization_id: state.initialization_id,
            panel_id: -1,
            key: ComparisonKey {
                source: 0,
                panel_size: 96,
            },
            metrics: compare(&training, reference),
        });

        for ((state_id, panel_id, panel_size, method), scores) in &sentinel_groups {
            if *state_id != state.state_id {
                continue;
            }
            records.push(MetricRecord {
                state_id: state.state_id,
                cell_id: state.cell_id,
                dataset_id: state.dataset_id,
                initialization_id: state.initialization_id,
                panel_id: i16::from(*panel_id),
                key: ComparisonKey {
                    source: match method {
                        SentinelMethod::Exact => 1,
                        SentinelMethod::Taylor => 2,
                    },
                    panel_size: *panel_size,
                },
                metrics: compare(scores, reference),
            });
        }
    }

    write_metric_rows(output_dir, &records)?;
    let cell_metrics = aggregate_cells(&records);
    write_ranking_report(output_dir, &cell_metrics)?;
    write_fidelity_report(output_dir, states, candidates, sentinels)?;
    Ok(())
}

fn group_references(
    rows: &[ReferenceScore],
    states: &[FrozenState],
    candidates: &[Vec<Candidate>],
) -> io::Result<Vec<Vec<f64>>> {
    let mut grouped = vec![vec![f64::NAN; 0]; states.len()];
    for state in states {
        grouped[state.state_id] = vec![f64::NAN; candidates[state.state_id].len()];
    }
    for row in rows {
        let Some(value) = grouped
            .get_mut(row.state_id)
            .and_then(|scores| scores.get_mut(usize::from(row.action_id)))
        else {
            return Err(io::Error::other("reference score action identity invalid"));
        };
        if value.is_finite() {
            return Err(io::Error::other("duplicate reference action score"));
        }
        *value = row.measurement_utility;
    }
    if grouped.iter().flatten().any(|value| !value.is_finite()) {
        return Err(io::Error::other("missing final-measurement action score"));
    }
    Ok(grouped)
}

type SentinelKey = (usize, u8, u16, SentinelMethod);

fn group_sentinels(
    rows: &[SentinelScore],
    states: &[FrozenState],
    candidates: &[Vec<Candidate>],
) -> io::Result<BTreeMap<SentinelKey, Vec<f64>>> {
    let mut grouped = BTreeMap::new();
    for row in rows {
        let key = (row.state_id, row.panel_id, row.sample_count, row.method);
        let values = grouped
            .entry(key)
            .or_insert_with(|| vec![f64::NAN; candidates[row.state_id].len()]);
        let Some(value) = values.get_mut(usize::from(row.action_id)) else {
            return Err(io::Error::other("sentinel action identity invalid"));
        };
        if value.is_finite() {
            return Err(io::Error::other("duplicate sentinel action score"));
        }
        *value = row.utility;
    }
    for ((state_id, _, _, _), values) in &grouped {
        if *state_id >= states.len() || values.iter().any(|value| !value.is_finite()) {
            return Err(io::Error::other("missing or invalid sentinel action score"));
        }
    }
    let expected_groups = states.len() * protocol::PANEL_COUNT * protocol::PANEL_SIZES.len() * 2;
    if grouped.len() != expected_groups {
        return Err(io::Error::other(format!(
            "sentinel score group count {}, expected {expected_groups}",
            grouped.len()
        )));
    }
    Ok(grouped)
}

fn compare(scores: &[f64], reference: &[f64]) -> Metrics {
    assert_eq!(scores.len(), reference.len());
    let spearman = spearman(scores, reference);
    let mut pair_count = 0;
    let mut concordant = 0;
    let mut tied_source_pairs = 0;
    let mut tied_reference_pairs = 0;
    for left in 0..scores.len() {
        for right in (left + 1)..scores.len() {
            let score_order = sign_with_tolerance(scores[left] - scores[right]);
            let reference_order = sign_with_tolerance(reference[left] - reference[right]);
            tied_source_pairs += usize::from(score_order == 0);
            tied_reference_pairs += usize::from(reference_order == 0);
            if score_order != 0 && reference_order != 0 {
                pair_count += 1;
                concordant += usize::from(score_order == reference_order);
            }
        }
    }
    let selected = argmax(scores);
    let best_reference = reference.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    Metrics {
        spearman,
        pairwise_agreement: (pair_count > 0).then_some(concordant as f64 / pair_count as f64),
        pair_count: pair_count as f64,
        tied_source_pairs: tied_source_pairs as f64,
        tied_reference_pairs: tied_reference_pairs as f64,
        top1_agreement: f64::from(selected == argmax(reference)),
        candidate_regret: best_reference - reference[selected],
    }
}

fn aggregate_cells(records: &[MetricRecord]) -> Vec<CellMetric> {
    let mut by_state: BTreeMap<(usize, ComparisonKey), Vec<Metrics>> = BTreeMap::new();
    for row in records {
        by_state
            .entry((row.state_id, row.key))
            .or_default()
            .push(row.metrics);
    }
    let mut by_cell: BTreeMap<(usize, ComparisonKey), CellStateMetrics> = BTreeMap::new();
    for ((state_id, key), values) in by_state {
        let row = records
            .iter()
            .find(|row| row.state_id == state_id && row.key == key)
            .expect("state metric provenance exists");
        by_cell.entry((row.cell_id, key)).or_default().push((
            row.dataset_id,
            row.initialization_id,
            average_metrics(&values),
        ));
    }
    by_cell
        .into_iter()
        .map(|((_cell_id, key), states)| {
            let first = states.first().expect("crossed cell has frozen states");
            CellMetric {
                dataset_id: first.0,
                initialization_id: first.1,
                key,
                metrics: average_metrics(&states.iter().map(|row| row.2).collect::<Vec<_>>()),
            }
        })
        .collect()
}

fn write_metric_rows(output_dir: &Path, rows: &[MetricRecord]) -> io::Result<()> {
    let mut output = BufWriter::new(File::create(output_dir.join("ranking-metrics.csv"))?);
    writeln!(
        output,
        "state_id,cell_id,dataset_id,initialization_id,panel_id,source,panel_size,spearman,pairwise_agreement,compared_pairs,tied_source_pairs,tied_reference_pairs,top1_agreement,candidate_set_regret"
    )?;
    for row in rows {
        writeln!(
            output,
            "{},{},{},{},{},{},{},{},{},{:.2},{:.2},{:.2},{:.1},{:.12e}",
            row.state_id,
            row.cell_id,
            row.dataset_id,
            row.initialization_id,
            row.panel_id,
            row.key.name(),
            row.key.panel_size,
            option_number(row.metrics.spearman),
            option_number(row.metrics.pairwise_agreement),
            row.metrics.pair_count,
            row.metrics.tied_source_pairs,
            row.metrics.tied_reference_pairs,
            row.metrics.top1_agreement,
            row.metrics.candidate_regret
        )?;
    }
    output.flush()
}

fn write_ranking_report(output_dir: &Path, cells: &[CellMetric]) -> io::Result<()> {
    let mut grouped: BTreeMap<ComparisonKey, Vec<CellMetric>> = BTreeMap::new();
    for cell in cells {
        grouped.entry(cell.key).or_default().push(*cell);
    }
    let mut output = BufWriter::new(File::create(
        output_dir.join("immediate-vs-generalization-ranking.json"),
    )?);
    writeln!(
        output,
        "{{\n  \"reference\": \"exact immediate utility on untouched final-measurement set; empirical reference only\",\n  \"aggregation\": \"average panel replicates within state, stages within crossed cell, then equal-weight crossed cells\",\n  \"comparisons\": ["
    )?;
    for (key_index, (key, rows)) in grouped.iter().enumerate() {
        let all = average_metrics(&rows.iter().map(|row| row.metrics).collect::<Vec<_>>());
        writeln!(
            output,
            "    {{\"source\":\"{}\",\"panel_size\":{},\"cell_count\":{},",
            key.name(),
            key.panel_size,
            rows.len()
        )?;
        write!(output, "      \"equal_cell_mean\":")?;
        write_metrics_json(&mut output, all)?;
        writeln!(output, ",\n      \"dataset_marginals\":[")?;
        for dataset_id in 0..protocol::DATASET_COUNT {
            let selected: Vec<_> = rows
                .iter()
                .filter(|row| row.dataset_id == dataset_id)
                .map(|row| row.metrics)
                .collect();
            write!(
                output,
                "        {{\"dataset_id\":{dataset_id},\"cell_count\":{},\"metrics\":",
                selected.len()
            )?;
            write_metrics_json(&mut output, average_metrics(&selected))?;
            writeln!(
                output,
                "}}{}",
                if dataset_id + 1 == protocol::DATASET_COUNT {
                    ""
                } else {
                    ","
                }
            )?;
        }
        writeln!(output, "      ],\n      \"initialization_marginals\":[")?;
        for initialization_id in 0..protocol::INITIALIZATION_COUNT {
            let selected: Vec<_> = rows
                .iter()
                .filter(|row| row.initialization_id == initialization_id)
                .map(|row| row.metrics)
                .collect();
            write!(
                output,
                "        {{\"initialization_id\":{initialization_id},\"cell_count\":{},\"metrics\":",
                selected.len()
            )?;
            write_metrics_json(&mut output, average_metrics(&selected))?;
            writeln!(
                output,
                "}}{}",
                if initialization_id + 1 == protocol::INITIALIZATION_COUNT {
                    ""
                } else {
                    ","
                }
            )?;
        }
        writeln!(
            output,
            "      ]}}{}",
            if key_index + 1 == grouped.len() {
                ""
            } else {
                ","
            }
        )?;
    }
    writeln!(output, "  ]\n}}")?;
    output.flush()
}

fn write_fidelity_report(
    output_dir: &Path,
    states: &[FrozenState],
    candidates: &[Vec<Candidate>],
    rows: &[SentinelScore],
) -> io::Result<()> {
    let mut groups: BTreeMap<FidelityKey, ExactTaylorScores> = BTreeMap::new();
    for row in rows {
        let entry = groups
            .entry((row.state_id, row.panel_id, row.sample_count))
            .or_insert_with(|| {
                let len = candidates[row.state_id].len();
                (vec![f64::NAN; len], vec![f64::NAN; len])
            });
        let slot = usize::from(row.action_id);
        match row.method {
            SentinelMethod::Exact => entry.0[slot] = row.utility,
            SentinelMethod::Taylor => entry.1[slot] = row.utility,
        }
    }
    let mut by_key: BTreeMap<u16, Vec<Fidelity>> = BTreeMap::new();
    for ((state_id, _, panel_size), (exact, taylor)) in groups {
        if exact.iter().chain(&taylor).any(|value| !value.is_finite()) {
            return Err(io::Error::other(
                "incomplete exact/Taylor paired sentinel scores",
            ));
        }
        let error = exact
            .iter()
            .zip(&taylor)
            .map(|(left, right)| (left - right).powi(2))
            .sum::<f64>()
            / exact.len() as f64;
        let absolute = exact
            .iter()
            .zip(&taylor)
            .map(|(left, right)| (left - right).abs())
            .sum::<f64>()
            / exact.len() as f64;
        let _state = &states[state_id];
        by_key.entry(panel_size).or_default().push(Fidelity {
            rmse: error.sqrt(),
            mae: absolute,
            spearman: spearman(&exact, &taylor),
            pairwise_agreement: pairwise_agreement(&exact, &taylor).0,
        });
    }
    let mut output = BufWriter::new(File::create(output_dir.join("taylor-fidelity.json"))?);
    writeln!(
        output,
        "{{\n  \"comparison\": \"first-order sentinel utility versus exact utility on identical examples\",\n  \"aggregation\": \"equal state-panel summaries in this balanced crossed design; panel measurements nested within crossed cells\",\n  \"panel_sizes\": ["
    )?;
    for (index, (panel_size, values)) in by_key.iter().enumerate() {
        let rmse = mean(&values.iter().map(|value| value.rmse).collect::<Vec<_>>());
        let mae = mean(&values.iter().map(|value| value.mae).collect::<Vec<_>>());
        let correlations: Vec<_> = values.iter().filter_map(|value| value.spearman).collect();
        let pairwise: Vec<_> = values
            .iter()
            .filter_map(|value| value.pairwise_agreement)
            .collect();
        writeln!(
            output,
            "    {{\"n\":{},\"state_panel_count\":{},\"mean_rmse\":{:.12e},\"mean_mae\":{:.12e},\"mean_spearman\":{},\"mean_pairwise_agreement\":{}}}{}",
            panel_size,
            values.len(),
            rmse,
            mae,
            option_number((!correlations.is_empty()).then(|| mean(&correlations))),
            option_number((!pairwise.is_empty()).then(|| mean(&pairwise))),
            if index + 1 == by_key.len() { "" } else { "," }
        )?;
    }
    writeln!(output, "  ]\n}}")?;
    output.flush()
}

fn average_metrics(values: &[Metrics]) -> Metrics {
    let spearman: Vec<_> = values.iter().filter_map(|row| row.spearman).collect();
    let pairwise: Vec<_> = values
        .iter()
        .filter_map(|row| row.pairwise_agreement)
        .collect();
    Metrics {
        spearman: (!spearman.is_empty()).then(|| mean(&spearman)),
        pairwise_agreement: (!pairwise.is_empty()).then(|| mean(&pairwise)),
        pair_count: mean(&values.iter().map(|row| row.pair_count).collect::<Vec<_>>()),
        tied_source_pairs: mean(
            &values
                .iter()
                .map(|row| row.tied_source_pairs)
                .collect::<Vec<_>>(),
        ),
        tied_reference_pairs: mean(
            &values
                .iter()
                .map(|row| row.tied_reference_pairs)
                .collect::<Vec<_>>(),
        ),
        top1_agreement: mean(
            &values
                .iter()
                .map(|row| row.top1_agreement)
                .collect::<Vec<_>>(),
        ),
        candidate_regret: mean(
            &values
                .iter()
                .map(|row| row.candidate_regret)
                .collect::<Vec<_>>(),
        ),
    }
}

fn write_metrics_json(output: &mut impl Write, metrics: Metrics) -> io::Result<()> {
    write!(
        output,
        "{{\"mean_spearman\":{},\"mean_pairwise_agreement\":{},\"mean_compared_pairs\":{},\"mean_tied_source_pairs\":{},\"mean_tied_reference_pairs\":{},\"top1_agreement\":{:.8},\"mean_candidate_set_regret\":{:.12e}}}",
        option_number(metrics.spearman),
        option_number(metrics.pairwise_agreement),
        metrics.pair_count,
        metrics.tied_source_pairs,
        metrics.tied_reference_pairs,
        metrics.top1_agreement,
        metrics.candidate_regret
    )
}

fn spearman(left: &[f64], right: &[f64]) -> Option<f64> {
    if left.len() != right.len() || left.len() < 2 {
        return None;
    }
    let left_ranks = average_ranks(left);
    let right_ranks = average_ranks(right);
    pearson(&left_ranks, &right_ranks)
}

fn average_ranks(values: &[f64]) -> Vec<f64> {
    let mut order: Vec<_> = (0..values.len()).collect();
    order.sort_by(|left, right| values[*left].total_cmp(&values[*right]));
    let mut ranks = vec![0.0; values.len()];
    let mut start = 0;
    while start < order.len() {
        let mut end = start + 1;
        while end < order.len() && (values[order[end]] - values[order[start]]).abs() <= TIE_EPSILON
        {
            end += 1;
        }
        let rank = ((start + 1 + end) as f64) / 2.0;
        for &index in &order[start..end] {
            ranks[index] = rank;
        }
        start = end;
    }
    ranks
}

fn pearson(left: &[f64], right: &[f64]) -> Option<f64> {
    if left.len() != right.len() || left.len() < 2 {
        return None;
    }
    let left_mean = mean(left);
    let right_mean = mean(right);
    let mut covariance = 0.0;
    let mut left_variance = 0.0;
    let mut right_variance = 0.0;
    for (&x, &y) in left.iter().zip(right) {
        let dx = x - left_mean;
        let dy = y - right_mean;
        covariance += dx * dy;
        left_variance += dx * dx;
        right_variance += dy * dy;
    }
    (left_variance > 0.0 && right_variance > 0.0)
        .then_some(covariance / (left_variance * right_variance).sqrt())
}

fn pairwise_agreement(left: &[f64], right: &[f64]) -> (Option<f64>, usize) {
    let mut compared = 0;
    let mut agreed = 0;
    for i in 0..left.len() {
        for j in (i + 1)..left.len() {
            let left_sign = sign_with_tolerance(left[i] - left[j]);
            let right_sign = sign_with_tolerance(right[i] - right[j]);
            if left_sign != 0 && right_sign != 0 {
                compared += 1;
                agreed += usize::from(left_sign == right_sign);
            }
        }
    }
    (
        (compared > 0).then_some(agreed as f64 / compared as f64),
        compared,
    )
}

fn sign_with_tolerance(value: f64) -> i8 {
    if value.abs() <= TIE_EPSILON {
        0
    } else if value > 0.0 {
        1
    } else {
        -1
    }
}

fn argmax(values: &[f64]) -> usize {
    values
        .iter()
        .enumerate()
        .fold((0, f64::NEG_INFINITY), |best, (index, value)| {
            if *value > best.1 {
                (index, *value)
            } else {
                best
            }
        })
        .0
}

fn mean(values: &[f64]) -> f64 {
    values.iter().sum::<f64>() / values.len().max(1) as f64
}

fn option_number(value: Option<f64>) -> String {
    value.map_or_else(|| "null".to_owned(), |number| format!("{number:.12e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn average_rank_handles_ties_with_midpoints() {
        assert_eq!(
            average_ranks(&[1.0, 2.0, 2.0, 4.0]),
            vec![1.0, 2.5, 2.5, 4.0]
        );
    }

    #[test]
    fn pairwise_agreement_excludes_ties_on_either_side() {
        let (agreement, compared) = pairwise_agreement(&[1.0, 1.0, 3.0], &[4.0, 2.0, 1.0]);
        assert_eq!(compared, 2);
        assert_eq!(agreement, Some(0.0));
    }

    #[test]
    fn exact_reference_has_zero_regret_and_full_top_one() {
        let metrics = compare(&[0.1, -0.2, 0.3], &[0.1, -0.2, 0.3]);
        assert_eq!(metrics.spearman, Some(1.0));
        assert_eq!(metrics.pairwise_agreement, Some(1.0));
        assert_eq!(metrics.top1_agreement, 1.0);
        assert_eq!(metrics.candidate_regret, 0.0);
    }
}

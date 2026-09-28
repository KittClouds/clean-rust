use std::collections::BTreeMap;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

use crate::protocol::{ActionCandidate, HORIZONS, StateRecord, TIE_EPSILON};

type QuartileSpreadRow = (usize, usize, f64, f64, f64, f64);
type ActionFeature = (&'static str, fn(&ActionCandidate) -> Option<f64>);

#[derive(Clone, Copy, Debug)]
pub struct ActionOutcome {
    pub state_id: usize,
    pub cell_id: usize,
    pub dataset_id: usize,
    pub initialization_id: usize,
    pub stage: usize,
    pub continuation_id: usize,
    pub continuation_seed: u64,
    pub action_id: u16,
    pub horizon: usize,
    pub u0_train: f64,
    pub u0_heldout: f64,
    pub q_h: f64,
    pub delta_q_h: f64,
    pub noop_loss: f64,
    pub action_loss: f64,
    pub state_fingerprint: u64,
    pub continuation_fingerprint: u64,
    pub noop_fingerprint: u64,
    pub action_fingerprint: u64,
}

#[derive(Clone, Copy, Debug)]
pub struct ActionValueSummary {
    pub state_id: usize,
    pub cell_id: usize,
    pub dataset_id: usize,
    pub initialization_id: usize,
    pub stage: usize,
    pub action: ActionCandidate,
    pub horizon: usize,
    pub continuation_count: usize,
    pub mean_q: f64,
    pub sd_q: f64,
    pub mean_delta_q: f64,
    pub sd_delta_q: f64,
    pub mean_noop_loss: f64,
    pub mean_action_loss: f64,
}

#[derive(Clone, Copy, Debug, Default)]
struct RankingMetrics {
    spearman: Option<f64>,
    top1_agreement: f64,
    pairwise_agreement: f64,
    pairwise_count: usize,
    tied_pairs: usize,
    immediate_top_ties: usize,
    future_top_ties: usize,
    immediate_winner_regret: f64,
}

#[derive(Clone, Copy, Debug)]
struct RankingRecord {
    horizon: usize,
    source: &'static str,
    group_kind: &'static str,
    group_id: Option<usize>,
    state_count: usize,
    mean_spearman: Option<f64>,
    mean_top1: f64,
    mean_pairwise: f64,
    mean_regret: f64,
    mean_pairwise_count: f64,
    mean_tied_pairs: f64,
    mean_immediate_top_ties: f64,
    mean_future_top_ties: f64,
}

pub fn analyze(
    output_dir: &Path,
    states: &[StateRecord],
    action_sets: &[Vec<ActionCandidate>],
    outcomes: &[ActionOutcome],
) -> io::Result<()> {
    let summaries = summarize_actions(states, action_sets, outcomes);
    write_action_summaries(output_dir, &summaries)?;
    let ranking = ranking_records(states, &summaries);
    write_ranking_report(output_dir, &ranking)?;
    write_horizon_report(output_dir, &ranking)?;
    write_sensitivity_report(output_dir, &summaries)?;
    write_noop_report(output_dir, states, outcomes)?;
    write_geometry_report(output_dir, states, &summaries)?;
    Ok(())
}

fn summarize_actions(
    states: &[StateRecord],
    action_sets: &[Vec<ActionCandidate>],
    outcomes: &[ActionOutcome],
) -> Vec<ActionValueSummary> {
    let mut grouped: BTreeMap<(usize, usize, u16), Vec<ActionOutcome>> = BTreeMap::new();
    for outcome in outcomes {
        grouped
            .entry((outcome.state_id, outcome.horizon, outcome.action_id))
            .or_default()
            .push(*outcome);
    }
    let mut summaries = Vec::with_capacity(grouped.len());
    for ((state_id, horizon, action_id), rows) in grouped {
        let state = &states[state_id];
        if state.valid_continuations < crate::protocol::MIN_VALID_CONTINUATIONS {
            continue;
        }
        let action = action_sets[state_id][usize::from(action_id)];
        let q: Vec<_> = rows.iter().map(|row| row.q_h).collect();
        let delta_q: Vec<_> = rows.iter().map(|row| row.delta_q_h).collect();
        let no_op: Vec<_> = rows.iter().map(|row| row.noop_loss).collect();
        let action_loss: Vec<_> = rows.iter().map(|row| row.action_loss).collect();
        summaries.push(ActionValueSummary {
            state_id,
            cell_id: state.cell_id,
            dataset_id: state.dataset_id,
            initialization_id: state.initialization_id,
            stage: state.stage,
            action,
            horizon,
            continuation_count: rows.len(),
            mean_q: mean(&q),
            sd_q: sample_sd(&q),
            mean_delta_q: mean(&delta_q),
            sd_delta_q: sample_sd(&delta_q),
            mean_noop_loss: mean(&no_op),
            mean_action_loss: mean(&action_loss),
        });
    }
    summaries
}

fn ranking_records(states: &[StateRecord], summaries: &[ActionValueSummary]) -> Vec<RankingRecord> {
    let mut by_state_horizon: BTreeMap<(usize, usize), Vec<ActionValueSummary>> = BTreeMap::new();
    for summary in summaries {
        by_state_horizon
            .entry((summary.state_id, summary.horizon))
            .or_default()
            .push(*summary);
    }
    let mut metrics: BTreeMap<(usize, &'static str, usize), Vec<RankingMetrics>> = BTreeMap::new();
    for ((state_id, horizon), points) in by_state_horizon {
        for source in ["u0_train", "u0_heldout"] {
            let x: Vec<_> = points
                .iter()
                .map(|point| {
                    if source == "u0_train" {
                        point.action.immediate_train_utility
                    } else {
                        point.action.immediate_heldout_utility
                    }
                })
                .collect();
            let y: Vec<_> = points.iter().map(|point| point.mean_delta_q).collect();
            let value = ranking_metrics(&x, &y);
            metrics
                .entry((horizon, source, state_id))
                .or_default()
                .push(value);
        }
    }

    let mut records = Vec::new();
    for horizon in HORIZONS {
        for source in ["u0_train", "u0_heldout"] {
            let state_metrics: Vec<_> = states
                .iter()
                .filter_map(|state| {
                    metrics
                        .get(&(horizon, source, state.state_id))
                        .and_then(|values| values.first().copied())
                        .map(|value| (state, value))
                })
                .collect();
            records.push(aggregate_ranking(
                horizon,
                source,
                "all_states",
                None,
                &state_metrics,
            ));
            for cell in 0..crate::protocol::CELL_COUNT {
                let group: Vec<_> = state_metrics
                    .iter()
                    .copied()
                    .filter(|(state, _)| state.cell_id == cell)
                    .collect();
                records.push(aggregate_ranking(
                    horizon,
                    source,
                    "cell",
                    Some(cell),
                    &group,
                ));
            }
            for stage in crate::protocol::STATE_STAGES {
                let group: Vec<_> = state_metrics
                    .iter()
                    .copied()
                    .filter(|(state, _)| state.stage == stage)
                    .collect();
                records.push(aggregate_ranking(
                    horizon,
                    source,
                    "stage",
                    Some(stage),
                    &group,
                ));
            }
            for dataset in 0..crate::protocol::DATASET_COUNT {
                let group: Vec<_> = state_metrics
                    .iter()
                    .copied()
                    .filter(|(state, _)| state.dataset_id == dataset)
                    .collect();
                records.push(aggregate_ranking(
                    horizon,
                    source,
                    "dataset",
                    Some(dataset),
                    &group,
                ));
            }
            for initialization in 0..crate::protocol::INITIALIZATION_COUNT {
                let group: Vec<_> = state_metrics
                    .iter()
                    .copied()
                    .filter(|(state, _)| state.initialization_id == initialization)
                    .collect();
                records.push(aggregate_ranking(
                    horizon,
                    source,
                    "initialization",
                    Some(initialization),
                    &group,
                ));
            }
        }
    }
    records
}

fn aggregate_ranking(
    horizon: usize,
    source: &'static str,
    group_kind: &'static str,
    group_id: Option<usize>,
    rows: &[(&StateRecord, RankingMetrics)],
) -> RankingRecord {
    let spearman: Vec<_> = rows.iter().filter_map(|(_, row)| row.spearman).collect();
    RankingRecord {
        horizon,
        source,
        group_kind,
        group_id,
        state_count: rows.len(),
        mean_spearman: (!spearman.is_empty()).then(|| mean(&spearman)),
        mean_top1: rows.iter().map(|(_, row)| row.top1_agreement).sum::<f64>()
            / rows.len().max(1) as f64,
        mean_pairwise: rows
            .iter()
            .map(|(_, row)| row.pairwise_agreement)
            .sum::<f64>()
            / rows.len().max(1) as f64,
        mean_regret: rows
            .iter()
            .map(|(_, row)| row.immediate_winner_regret)
            .sum::<f64>()
            / rows.len().max(1) as f64,
        mean_pairwise_count: rows
            .iter()
            .map(|(_, row)| row.pairwise_count as f64)
            .sum::<f64>()
            / rows.len().max(1) as f64,
        mean_tied_pairs: rows
            .iter()
            .map(|(_, row)| row.tied_pairs as f64)
            .sum::<f64>()
            / rows.len().max(1) as f64,
        mean_immediate_top_ties: rows
            .iter()
            .map(|(_, row)| row.immediate_top_ties as f64)
            .sum::<f64>()
            / rows.len().max(1) as f64,
        mean_future_top_ties: rows
            .iter()
            .map(|(_, row)| row.future_top_ties as f64)
            .sum::<f64>()
            / rows.len().max(1) as f64,
    }
}

fn ranking_metrics(immediate: &[f64], future: &[f64]) -> RankingMetrics {
    assert_eq!(immediate.len(), future.len());
    if immediate.is_empty() {
        return RankingMetrics::default();
    }
    let future_best = winner(future);
    let immediate_best = winner(immediate);
    let max_future = future[future_best];
    let mut concordant = 0_usize;
    let mut pair_count = 0_usize;
    let mut tied_pairs = 0_usize;
    for left in 0..immediate.len() {
        for right in left + 1..immediate.len() {
            let x = sign_with_tolerance(immediate[left] - immediate[right]);
            let y = sign_with_tolerance(future[left] - future[right]);
            if x == 0 || y == 0 {
                tied_pairs += 1;
                continue;
            }
            pair_count += 1;
            if x == y {
                concordant += 1;
            }
        }
    }
    RankingMetrics {
        spearman: spearman(immediate, future),
        top1_agreement: if immediate_best == future_best {
            1.0
        } else {
            0.0
        },
        pairwise_agreement: if pair_count == 0 {
            0.0
        } else {
            concordant as f64 / pair_count as f64
        },
        pairwise_count: pair_count,
        tied_pairs,
        immediate_top_ties: top_tie_count(immediate),
        future_top_ties: top_tie_count(future),
        immediate_winner_regret: (max_future - future[immediate_best]).max(0.0),
    }
}

fn winner(values: &[f64]) -> usize {
    values
        .iter()
        .enumerate()
        .max_by(|left, right| left.1.total_cmp(right.1).then_with(|| right.0.cmp(&left.0)))
        .map_or(0, |(index, _)| index)
}

fn top_tie_count(values: &[f64]) -> usize {
    let best = values.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    values
        .iter()
        .filter(|value| (best - **value).abs() <= TIE_EPSILON)
        .count()
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

fn spearman(left: &[f64], right: &[f64]) -> Option<f64> {
    if left.len() < 2 || left.len() != right.len() {
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
        let mean_rank = (start + 1 + end) as f64 / 2.0;
        for index in start..end {
            ranks[order[index]] = mean_rank;
        }
        start = end;
    }
    ranks
}

fn pearson(left: &[f64], right: &[f64]) -> Option<f64> {
    if left.len() < 2 || left.len() != right.len() {
        return None;
    }
    let left_mean = mean(left);
    let right_mean = mean(right);
    let mut covariance = 0.0;
    let mut left_variance = 0.0;
    let mut right_variance = 0.0;
    for (&x, &y) in left.iter().zip(right) {
        covariance += (x - left_mean) * (y - right_mean);
        left_variance += (x - left_mean).powi(2);
        right_variance += (y - right_mean).powi(2);
    }
    let denominator = (left_variance * right_variance).sqrt();
    (denominator > 0.0).then_some(covariance / denominator)
}

fn write_action_summaries(output_dir: &Path, summaries: &[ActionValueSummary]) -> io::Result<()> {
    let file = File::create(output_dir.join("action-value-summary.csv"))?;
    let mut out = BufWriter::new(file);
    writeln!(
        out,
        "state_id,cell_id,dataset_id,initialization_id,stage,action_id,block_id,left_parameter,right_parameter,left_layer,right_layer,left_delta,right_delta,left_rank,right_rank,u0_train,u0_heldout,taylor_train,taylor_heldout,output_taylor_train,output_taylor_heldout,projected_within_utility_variance,horizon,continuation_count,mean_q,sd_q,mean_delta_q,sd_delta_q,mean_noop_loss,mean_action_loss"
    )?;
    for row in summaries {
        let action = row.action;
        writeln!(
            out,
            "{},{},{},{},{},{},{},{},{},{},{},{:.9},{:.9},{},{},{:.12e},{:.12e},{:.12e},{:.12e},{},{},{:.12e},{},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e}",
            row.state_id,
            row.cell_id,
            row.dataset_id,
            row.initialization_id,
            row.stage,
            action.action_id,
            action.block_id,
            action.left_parameter,
            action.right_parameter,
            crate::protocol::parameter_layer(usize::from(action.left_parameter)),
            crate::protocol::parameter_layer(usize::from(action.right_parameter)),
            action.left_delta,
            action.right_delta,
            action.left_rank,
            action.right_rank,
            action.immediate_train_utility,
            action.immediate_heldout_utility,
            action.taylor_train_utility,
            action.taylor_heldout_utility,
            optional_number(action.output_taylor_train_utility),
            optional_number(action.output_taylor_heldout_utility),
            action.projected_within_utility_variance,
            row.horizon,
            row.continuation_count,
            row.mean_q,
            row.sd_q,
            row.mean_delta_q,
            row.sd_delta_q,
            row.mean_noop_loss,
            row.mean_action_loss
        )?;
    }
    out.flush()
}

fn write_ranking_report(output_dir: &Path, rows: &[RankingRecord]) -> io::Result<()> {
    let file = File::create(output_dir.join("immediate-vs-future-ranking.json"))?;
    let mut out = BufWriter::new(file);
    writeln!(
        out,
        "{{\n  \"rank_target\": \"mean no-op-relative held-out value across common continuations\",\n  \"immediate_sources\": [\"u0_train\", \"u0_heldout\"],\n  \"tie_epsilon\": {TIE_EPSILON:.1e},\n  \"aggregation\": \"equal-weight state summaries; actions/continuations/checkpoints are nested\",\n  \"records\": ["
    )?;
    write_ranking_records(&mut out, rows)?;
    writeln!(out, "  ]\n}}")?;
    out.flush()
}

fn write_horizon_report(output_dir: &Path, rows: &[RankingRecord]) -> io::Result<()> {
    let file = File::create(output_dir.join("horizon-decay.json"))?;
    let mut out = BufWriter::new(file);
    writeln!(
        out,
        "{{\n  \"primary_immediate_source\": \"u0_train\",\n  \"records\": ["
    )?;
    let selected: Vec<_> = rows
        .iter()
        .filter(|row| row.source == "u0_train" && row.group_kind == "stage")
        .collect();
    for (index, row) in selected.iter().enumerate() {
        write!(
            out,
            "    {{\"horizon\":{},\"stage\":{},\"state_count\":{},\"mean_spearman\":{},\"mean_top1_agreement\":{:.9},\"mean_pairwise_agreement\":{:.9},\"mean_immediate_winner_regret\":{:.12e}}}",
            row.horizon,
            row.group_id.unwrap_or(0),
            row.state_count,
            optional_number(row.mean_spearman),
            row.mean_top1,
            row.mean_pairwise,
            row.mean_regret
        )?;
        if index + 1 != selected.len() {
            writeln!(out, ",")?;
        } else {
            writeln!(out)?;
        }
    }
    writeln!(out, "  ]\n}}")?;
    out.flush()
}

fn write_ranking_records(out: &mut impl Write, rows: &[RankingRecord]) -> io::Result<()> {
    for (index, row) in rows.iter().enumerate() {
        write!(
            out,
            "    {{\"horizon\":{},\"immediate_source\":\"{}\",\"group_kind\":\"{}\",\"group_id\":{},\"state_count\":{},\"mean_spearman\":{},\"mean_top1_agreement\":{:.9},\"mean_pairwise_agreement\":{:.9},\"mean_candidate_set_regret\":{:.12e},\"mean_comparable_pairs_per_state\":{:.2},\"mean_tied_pairs_per_state\":{:.2},\"mean_immediate_top_ties\":{:.2},\"mean_future_top_ties\":{:.2}}}",
            row.horizon,
            row.source,
            row.group_kind,
            row.group_id
                .map_or_else(|| "null".to_owned(), |id| id.to_string()),
            row.state_count,
            optional_number(row.mean_spearman),
            row.mean_top1,
            row.mean_pairwise,
            row.mean_regret,
            row.mean_pairwise_count,
            row.mean_tied_pairs,
            row.mean_immediate_top_ties,
            row.mean_future_top_ties
        )?;
        if index + 1 != rows.len() {
            writeln!(out, ",")?;
        } else {
            writeln!(out)?;
        }
    }
    Ok(())
}

fn write_sensitivity_report(output_dir: &Path, summaries: &[ActionValueSummary]) -> io::Result<()> {
    let file = File::create(output_dir.join("continuation-sensitivity.json"))?;
    let mut out = BufWriter::new(file);
    writeln!(
        out,
        "{{\n  \"estimand\": \"sample standard deviation of paired DeltaQ_H across valid common continuations for each state-action\",\n  \"records\": ["
    )?;
    let mut rows = Vec::new();
    for horizon in HORIZONS {
        let values: Vec<_> = summaries
            .iter()
            .filter(|row| row.horizon == horizon)
            .map(|row| row.sd_delta_q)
            .collect();
        if !values.is_empty() {
            rows.push((horizon, values));
        }
    }
    for (index, (horizon, values)) in rows.iter().enumerate() {
        let mut sorted = values.clone();
        sorted.sort_by(f64::total_cmp);
        writeln!(
            out,
            "    {{\"horizon\":{},\"state_action_count\":{},\"mean_sigma_delta_q\":{:.12e},\"median_sigma_delta_q\":{:.12e},\"p90_sigma_delta_q\":{:.12e},\"mean_action_mean_delta_q\":{:.12e},\"mean_q_sd\":{:.12e}}}{}",
            horizon,
            values.len(),
            mean(values),
            quantile_sorted(&sorted, 0.50),
            quantile_sorted(&sorted, 0.90),
            summaries
                .iter()
                .filter(|row| row.horizon == *horizon)
                .map(|row| row.mean_delta_q)
                .sum::<f64>()
                / values.len() as f64,
            summaries
                .iter()
                .filter(|row| row.horizon == *horizon)
                .map(|row| row.sd_q)
                .sum::<f64>()
                / values.len() as f64,
            if index + 1 == rows.len() { "" } else { "," }
        )?;
    }
    writeln!(out, "  ],\n  \"within_immediate_utility_quartiles\": [")?;
    let mut by_state_horizon: BTreeMap<(usize, usize), Vec<&ActionValueSummary>> = BTreeMap::new();
    for summary in summaries {
        by_state_horizon
            .entry((summary.state_id, summary.horizon))
            .or_default()
            .push(summary);
    }
    let mut quartile_records: BTreeMap<(usize, usize), Vec<QuartileSpreadRow>> = BTreeMap::new();
    for ((state_id, horizon), mut points) in by_state_horizon {
        points.sort_by(|left, right| {
            left.action
                .immediate_train_utility
                .total_cmp(&right.action.immediate_train_utility)
                .then_with(|| left.action.action_id.cmp(&right.action.action_id))
        });
        for quartile in 0..4 {
            let count = points.len();
            let members: Vec<_> = points
                .iter()
                .enumerate()
                .filter_map(|(rank, point)| ((rank * 4 / count) == quartile).then_some(*point))
                .collect();
            if members.len() < 2 {
                continue;
            }
            let mean_values: Vec<_> = members.iter().map(|row| row.mean_delta_q).collect();
            let sensitivity_values: Vec<_> = members.iter().map(|row| row.sd_delta_q).collect();
            let immediate_values: Vec<_> = members
                .iter()
                .map(|row| row.action.immediate_train_utility)
                .collect();
            quartile_records
                .entry((horizon, quartile + 1))
                .or_default()
                .push((
                    state_id,
                    members.len(),
                    sample_sd(&mean_values),
                    range(&mean_values),
                    sample_sd(&sensitivity_values),
                    range(&immediate_values),
                ));
        }
    }
    let mut first = true;
    for horizon in HORIZONS {
        for quartile in 1..=4 {
            let Some(states) = quartile_records.get(&(horizon, quartile)) else {
                continue;
            };
            if !first {
                writeln!(out, ",")?;
            }
            first = false;
            let mean_spread: Vec<_> = states.iter().map(|row| row.2).collect();
            let mean_range: Vec<_> = states.iter().map(|row| row.3).collect();
            let sigma_spread: Vec<_> = states.iter().map(|row| row.4).collect();
            let immediate_width: Vec<_> = states.iter().map(|row| row.5).collect();
            let mut sorted_mean_spread = mean_spread.clone();
            sorted_mean_spread.sort_by(f64::total_cmp);
            let mut sorted_sigma_spread = sigma_spread.clone();
            sorted_sigma_spread.sort_by(f64::total_cmp);
            write!(
                out,
                "    {{\"horizon\":{},\"immediate_train_utility_quartile\":{},\"state_count\":{},\"mean_actions_per_state\":{:.6},\"mean_immediate_utility_width\":{:.12e},\"mean_within_state_sd_of_mean_delta_q\":{:.12e},\"median_within_state_sd_of_mean_delta_q\":{:.12e},\"mean_within_state_range_of_mean_delta_q\":{:.12e},\"mean_within_state_sd_of_sigma_delta_q\":{:.12e},\"median_within_state_sd_of_sigma_delta_q\":{:.12e}}}",
                horizon,
                quartile,
                states.len(),
                states.iter().map(|row| row.1 as f64).sum::<f64>() / states.len() as f64,
                mean(&immediate_width),
                mean(&mean_spread),
                quantile_sorted(&sorted_mean_spread, 0.50),
                mean(&mean_range),
                mean(&sigma_spread),
                quantile_sorted(&sorted_sigma_spread, 0.50),
            )?;
        }
    }
    writeln!(out, "\n  ]\n}}")?;
    out.flush()
}

fn write_noop_report(
    output_dir: &Path,
    states: &[StateRecord],
    outcomes: &[ActionOutcome],
) -> io::Result<()> {
    let file = File::create(output_dir.join("action-effect-vs-noop.json"))?;
    let mut out = BufWriter::new(file);
    writeln!(
        out,
        "{{\n  \"primary_effect\": \"held-out loss(noop continuation) minus held-out loss(candidate continuation)\",\n  \"records\": ["
    )?;
    for (index, horizon) in HORIZONS.iter().enumerate() {
        let rows: Vec<_> = outcomes
            .iter()
            .filter(|row| row.horizon == *horizon)
            .collect();
        let mut unique_paths = BTreeMap::new();
        for row in &rows {
            unique_paths
                .entry((row.state_id, row.continuation_id))
                .or_insert(*row);
        }
        let q: Vec<_> = rows.iter().map(|row| row.q_h).collect();
        let effect: Vec<_> = rows.iter().map(|row| row.delta_q_h).collect();
        let baseline: Vec<_> = unique_paths
            .iter()
            .map(|((state_id, _), _)| states[*state_id].heldout_loss)
            .collect();
        let noop_change: Vec<_> = unique_paths
            .iter()
            .map(|((state_id, _), row)| row.noop_loss - states[*state_id].heldout_loss)
            .collect();
        let identity_error = rows
            .iter()
            .map(|row| {
                (row.q_h - row.delta_q_h - (states[row.state_id].heldout_loss - row.noop_loss))
                    .abs()
            })
            .fold(0.0_f64, f64::max);
        write!(
            out,
            "    {{\"horizon\":{},\"action_continuation_row_count\":{},\"unique_state_continuation_count\":{},\"mean_baseline_heldout_loss\":{:.12e},\"mean_noop_trajectory_loss_change\":{:.12e},\"mean_absolute_q_over_action_rows\":{:.12e},\"mean_action_effect_delta_q_over_action_rows\":{:.12e},\"sd_action_effect_rows\":{:.12e},\"max_q_decomposition_error\":{:.3e}}}{}",
            horizon,
            rows.len(),
            unique_paths.len(),
            mean(&baseline),
            mean(&noop_change),
            mean(&q),
            mean(&effect),
            sample_sd(&effect),
            identity_error,
            if index + 1 == HORIZONS.len() { "" } else { "," }
        )?;
    }
    writeln!(out, "  ]\n}}")?;
    out.flush()
}

fn write_geometry_report(
    output_dir: &Path,
    states: &[StateRecord],
    summaries: &[ActionValueSummary],
) -> io::Result<()> {
    let file = File::create(output_dir.join("existing-geometry-associations.json"))?;
    let mut out = BufWriter::new(file);
    writeln!(
        out,
        "{{\n  \"status\": \"diagnostic associations only; no predictor or controller fit\",\n  \"within_state_action_spearman\": ["
    )?;
    let feature_fns: [ActionFeature; 7] = [
        ("u0_train", |action| Some(action.immediate_train_utility)),
        ("u0_heldout_measurement_only", |action| {
            Some(action.immediate_heldout_utility)
        }),
        ("full_gradient_taylor_train", |action| {
            Some(action.taylor_train_utility)
        }),
        ("full_gradient_taylor_heldout", |action| {
            Some(action.taylor_heldout_utility)
        }),
        ("projected_stratum_within_utility_variance", |action| {
            Some(action.projected_within_utility_variance)
        }),
        ("action_l1_magnitude", |action| {
            Some(f64::from(
                action.left_delta.abs() + action.right_delta.abs(),
            ))
        }),
        ("output_layer_taylor_train", |action| {
            action.output_taylor_train_utility
        }),
    ];
    let mut records = Vec::new();
    for horizon in HORIZONS {
        let mut by_state: BTreeMap<usize, Vec<ActionValueSummary>> = BTreeMap::new();
        for summary in summaries.iter().filter(|row| row.horizon == horizon) {
            by_state.entry(summary.state_id).or_default().push(*summary);
        }
        for (feature_name, feature) in feature_fns {
            let mut mu_corr = Vec::new();
            let mut sigma_corr = Vec::new();
            for points in by_state.values() {
                let pairs: Vec<_> = points
                    .iter()
                    .filter_map(|point| {
                        feature(&point.action)
                            .map(|value| (value, point.mean_delta_q, point.sd_delta_q))
                    })
                    .collect();
                if pairs.len() >= 3 {
                    let x: Vec<_> = pairs.iter().map(|row| row.0).collect();
                    let y: Vec<_> = pairs.iter().map(|row| row.1).collect();
                    let z: Vec<_> = pairs.iter().map(|row| row.2).collect();
                    if let Some(value) = spearman(&x, &y) {
                        mu_corr.push(value);
                    }
                    if let Some(value) = spearman(&x, &z) {
                        sigma_corr.push(value);
                    }
                }
            }
            records.push((horizon, feature_name, mu_corr, sigma_corr));
        }
    }
    for (index, (horizon, feature, mu, sigma)) in records.iter().enumerate() {
        writeln!(
            out,
            "    {{\"horizon\":{},\"feature\":\"{}\",\"state_count_mu\":{},\"mean_state_spearman_mu\":{},\"state_count_sigma\":{},\"mean_state_spearman_sigma\":{}}}{}",
            horizon,
            feature,
            mu.len(),
            optional_number((!mu.is_empty()).then(|| mean(mu))),
            sigma.len(),
            optional_number((!sigma.is_empty()).then(|| mean(sigma))),
            if index + 1 == records.len() { "" } else { "," }
        )?;
    }
    writeln!(out, "  ],\n  \"state_level_associations\": [")?;
    let mut state_records = Vec::new();
    for horizon in HORIZONS {
        for feature in [
            "stage",
            "training_loss",
            "parameter_rms",
            "active_hidden_fraction",
        ] {
            let mut x = Vec::new();
            let mut mu = Vec::new();
            let mut sigma = Vec::new();
            for state in states {
                let points: Vec<_> = summaries
                    .iter()
                    .filter(|row| row.state_id == state.state_id && row.horizon == horizon)
                    .collect();
                if points.is_empty() {
                    continue;
                }
                let feature_value = match feature {
                    "stage" => state.stage as f64,
                    "training_loss" => state.training_loss,
                    "parameter_rms" => state.parameter_rms,
                    _ => state.active_hidden_fraction,
                };
                x.push(feature_value);
                mu.push(
                    points.iter().map(|point| point.mean_delta_q).sum::<f64>()
                        / points.len() as f64,
                );
                sigma.push(
                    points.iter().map(|point| point.sd_delta_q).sum::<f64>() / points.len() as f64,
                );
            }
            state_records.push((
                horizon,
                feature,
                pearson(&x, &mu),
                pearson(&x, &sigma),
                x.len(),
            ));
        }
    }
    for (index, (horizon, feature, mu, sigma, count)) in state_records.iter().enumerate() {
        writeln!(
            out,
            "    {{\"horizon\":{},\"feature\":\"{}\",\"state_count\":{},\"pearson_state_mean_delta_q\":{},\"pearson_state_mean_sigma\":{}}}{}",
            horizon,
            feature,
            count,
            optional_number(*mu),
            optional_number(*sigma),
            if index + 1 == state_records.len() {
                ""
            } else {
                ","
            }
        )?;
    }
    writeln!(out, "  ],\n  \"action_layer_pair_means\": [")?;
    let mut layer_groups: BTreeMap<(usize, &'static str, &'static str), (usize, f64, f64)> =
        BTreeMap::new();
    for row in summaries {
        let left = crate::protocol::parameter_layer(usize::from(row.action.left_parameter));
        let right = crate::protocol::parameter_layer(usize::from(row.action.right_parameter));
        let group = layer_groups.entry((row.horizon, left, right)).or_default();
        group.0 += 1;
        group.1 += row.mean_delta_q;
        group.2 += row.sd_delta_q;
    }
    for (index, ((horizon, left, right), (count, total_mu, total_sigma))) in
        layer_groups.iter().enumerate()
    {
        write!(
            out,
            "    {{\"horizon\":{},\"left_parameter_layer\":\"{}\",\"right_parameter_layer\":\"{}\",\"state_action_count\":{},\"mean_delta_q\":{:.12e},\"mean_sigma_delta_q\":{:.12e}}}{}",
            horizon,
            left,
            right,
            count,
            total_mu / *count as f64,
            total_sigma / *count as f64,
            if index + 1 == layer_groups.len() {
                ""
            } else {
                ","
            }
        )?;
        writeln!(out)?;
    }
    writeln!(out, "  ]\n}}")?;
    out.flush()
}

fn mean(values: &[f64]) -> f64 {
    values.iter().sum::<f64>() / values.len().max(1) as f64
}

fn range(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let (minimum, maximum) = values.iter().fold(
        (f64::INFINITY, f64::NEG_INFINITY),
        |(minimum, maximum), value| (minimum.min(*value), maximum.max(*value)),
    );
    maximum - minimum
}

fn sample_sd(values: &[f64]) -> f64 {
    if values.len() < 2 {
        return 0.0;
    }
    let average = mean(values);
    (values
        .iter()
        .map(|value| (value - average).powi(2))
        .sum::<f64>()
        / (values.len() - 1) as f64)
        .sqrt()
}

fn quantile_sorted(sorted: &[f64], quantile: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let position = quantile * (sorted.len() - 1) as f64;
    let lower = position.floor() as usize;
    let upper = position.ceil() as usize;
    sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower as f64)
}

fn optional_number(value: Option<f64>) -> String {
    value.map_or_else(|| "null".to_owned(), |number| format!("{number:.12e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ranking_metrics_are_order_sensitive_and_ties_are_reported() {
        let metrics = ranking_metrics(&[1.0, 2.0, 2.0, 4.0], &[4.0, 2.0, 2.0, 1.0]);
        assert!(metrics.spearman.unwrap() < -0.9);
        assert_eq!(metrics.top1_agreement, 0.0);
        assert!(metrics.tied_pairs > 0);
        assert!(metrics.immediate_winner_regret > 0.0);
    }

    #[test]
    fn paired_q_decomposition_is_exact_by_definition() {
        let base: f64 = 2.0;
        let noop: f64 = 1.8;
        let action: f64 = 1.7;
        let q = base - action;
        let delta_q = noop - action;
        assert!((q - delta_q - (base - noop)).abs() < f64::EPSILON);
    }

    #[test]
    fn rank_metrics_do_not_claim_correlation_for_constant_vectors() {
        assert_eq!(spearman(&[1.0, 1.0, 1.0], &[2.0, 2.0, 2.0]), None);
    }

    #[test]
    fn model_parameter_count_remains_the_frozen_substrate() {
        assert_eq!(crate::model::PARAMS, 171);
        assert_eq!(HORIZONS, [0, 8, 32, 128]);
    }
}

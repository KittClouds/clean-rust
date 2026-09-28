use super::*;
use hashbrown::HashMap;
use std::fs::File;
use std::io::{self, BufRead, BufReader, BufWriter, Write};

struct PanelObservation {
    candidate_count: usize,
    squared_rmse_sum: f64,
    panel_count: usize,
    panel_seen: [bool; PANEL_REPLICATES],
}

impl Default for PanelObservation {
    fn default() -> Self {
        Self {
            candidate_count: 0,
            squared_rmse_sum: 0.0,
            panel_count: 0,
            panel_seen: [false; PANEL_REPLICATES],
        }
    }
}

#[derive(Clone, Copy)]
struct Checkpoint {
    train_loss: f32,
    validation_loss: f32,
    fingerprint: u64,
}

#[derive(Default)]
struct VarianceTotals {
    predicted_variance_sum: f64,
    component_variance_sum: f64,
    candidate_count: usize,
    observed_rmse_square_sum: f64,
    observed_panel_count: usize,
    state_count: usize,
}

const VARIANCE_METHODS: [&str; 4] = [
    "iid_with_replacement",
    "iid_without_replacement",
    "cell_stratified_wor",
    "margin_stratified_wor",
];

/// Reconstructs frozen R2 candidate utility vectors and computes exact
/// finite-population estimator variances without running training or sampling.
pub fn run_r2_variance_audit(
    samples: &[Sample],
    source_artifacts: impl AsRef<Path>,
    output_dir: impl AsRef<Path>,
) -> io::Result<usize> {
    if samples.len() != TOTAL_SAMPLES {
        return Err(invalid_data("AR-02A-R2 variance dataset length mismatch"));
    }
    let source_artifacts = source_artifacts.as_ref();
    let observed = read_panel_observations(source_artifacts.join("r2-panel-audit.csv"))?;
    let checkpoints = read_checkpoints(source_artifacts.join("r2-replay-checkpoints.csv"))?;
    let output_dir = output_dir.as_ref();
    std::fs::create_dir_all(output_dir)?;

    let train = &samples[..TRAIN_SAMPLES];
    let cell_ids = std::array::from_fn(|index| (index / TRAIN_PER_CELL) as u8);
    let margins = build_margin_strata(train);
    let cell_index = StrataIndex::new(&cell_ids, CELLS);
    let margin_index = StrataIndex::new(&margins.ids, MARGIN_STRATA);
    let placebo_indices = std::array::from_fn(|partition| {
        let ids = placebo_strata(partition as u64);
        StrataIndex::new(&ids, CELLS)
    });

    let state_path = output_dir.join("r2-variance-states.csv");
    let mut states = BufWriter::new(File::create(state_path)?);
    writeln!(
        states,
        "seed,snapshot_step,method,candidates,panels,predicted_variance,predicted_rmse,observed_panel_rmse,variance_component"
    )?;
    let mut totals: HashMap<String, VarianceTotals> = HashMap::new();
    let mut state_count = 0;

    for seed in R1_SEEDS {
        for snapshot in replay_reference_trajectory(train, seed) {
            let key = (seed, snapshot.step);
            let checkpoint = checkpoints
                .get(&key)
                .ok_or_else(|| invalid_data("missing frozen R2 replay checkpoint"))?;
            validate_checkpoint(snapshot, train, samples, checkpoint)?;

            let evidence_round = snapshot.step / COMMITS_PER_EVIDENCE;
            let proposal_ids = batch_indices(seed, evidence_round, PROPOSAL_STREAM);
            let proposal = indexed_samples(train, &proposal_ids);
            let (groups, group_count) = partition(snapshot.step % PARAMS);
            let candidates =
                shortlist_candidates(&snapshot.model, train, &proposal, &groups, group_count);
            if candidates.is_empty() {
                return Err(invalid_data("reconstructed R2 candidate set is empty"));
            }

            let mut kinds = vec![
                PanelKind::IidWithReplacement,
                PanelKind::IidWithoutReplacement,
                PanelKind::CellWithoutReplacement,
                PanelKind::MarginWithoutReplacement,
            ];
            kinds.extend(
                (0..PLACEBO_PARTITIONS).map(|id| PanelKind::PlaceboWithoutReplacement(id as u8)),
            );
            for kind in kinds {
                let method = kind.name();
                let panel = observed
                    .get(&(seed, snapshot.step, method.clone()))
                    .ok_or_else(|| invalid_data("missing frozen R2 panel observations"))?;
                if panel.candidate_count != candidates.len()
                    || panel.panel_count != PANEL_REPLICATES
                {
                    return Err(invalid_data(
                        "R2 panel cardinality changed during reconstruction",
                    ));
                }

                let mut predicted_variance_sum = 0.0;
                let mut component_variance_sum = 0.0;
                for candidate in &candidates {
                    let utility_mean =
                        candidate.per_example_utility.iter().sum::<f32>() / TRAIN_SAMPLES as f32;
                    if (utility_mean - candidate.exact_utility).abs() > 1.0e-7 {
                        return Err(invalid_data("reconstructed candidate utility mismatch"));
                    }
                    let (variance, component) = estimator_variance(
                        &candidate.per_example_utility,
                        kind,
                        &cell_index,
                        &margin_index,
                        &placebo_indices,
                    )?;
                    predicted_variance_sum += variance;
                    component_variance_sum += component;
                }

                let candidate_count = candidates.len();
                let predicted_variance = predicted_variance_sum / candidate_count as f64;
                let predicted_rmse = predicted_variance.sqrt();
                let observed_panel_rmse =
                    (panel.squared_rmse_sum / panel.panel_count as f64).sqrt();
                let component_variance = component_variance_sum / candidate_count as f64;
                writeln!(
                    states,
                    "{seed:016x},{},{method},{candidate_count},{},{predicted_variance:.12e},{predicted_rmse:.12e},{observed_panel_rmse:.12e},{component_variance:.12e}",
                    snapshot.step, panel.panel_count
                )?;

                let total = totals.entry(method).or_default();
                total.predicted_variance_sum += predicted_variance_sum;
                total.component_variance_sum += component_variance_sum;
                total.candidate_count += candidate_count;
                total.observed_rmse_square_sum += panel.squared_rmse_sum;
                total.observed_panel_count += panel.panel_count;
                total.state_count += 1;
            }
            state_count += 1;
        }
    }
    states.flush()?;

    let summary_path = output_dir.join("r2-variance-summary.csv");
    let mut summary = BufWriter::new(File::create(summary_path)?);
    writeln!(
        summary,
        "method,states,candidates,panels,predicted_rmse,observed_panel_rmse,mean_component_variance"
    )?;
    for method in method_names() {
        let Some(total) = totals.get(&method) else {
            return Err(invalid_data("variance summary missing a construction"));
        };
        writeln!(
            summary,
            "{method},{},{},{},{:.12e},{:.12e},{:.12e}",
            total.state_count,
            total.candidate_count,
            total.observed_panel_count,
            (total.predicted_variance_sum / total.candidate_count as f64).sqrt(),
            (total.observed_rmse_square_sum / total.observed_panel_count as f64).sqrt(),
            total.component_variance_sum / total.candidate_count as f64
        )?;
    }
    summary.flush()?;
    Ok(state_count * method_names().len())
}

fn estimator_variance(
    utility: &[f32; TRAIN_SAMPLES],
    kind: PanelKind,
    cells: &StrataIndex,
    margins: &StrataIndex,
    placebos: &[StrataIndex; PLACEBO_PARTITIONS],
) -> io::Result<(f64, f64)> {
    match kind {
        PanelKind::IidWithReplacement => {
            let mean =
                utility.iter().map(|&value| f64::from(value)).sum::<f64>() / TRAIN_SAMPLES as f64;
            let variance = utility
                .iter()
                .map(|&value| (f64::from(value) - mean).powi(2))
                .sum::<f64>()
                / TRAIN_SAMPLES as f64;
            Ok((variance / R2_SAMPLE_COUNT as f64, variance))
        }
        PanelKind::IidWithoutReplacement => {
            let variance = sample_variance(utility.iter().copied());
            Ok((
                (1.0 - R2_SAMPLE_COUNT as f64 / TRAIN_SAMPLES as f64) * variance
                    / R2_SAMPLE_COUNT as f64,
                variance,
            ))
        }
        PanelKind::CellWithoutReplacement => stratified_variance(utility, cells),
        PanelKind::MarginWithoutReplacement => stratified_variance(utility, margins),
        PanelKind::PlaceboWithoutReplacement(id) => {
            let index = placebos
                .get(usize::from(id))
                .ok_or_else(|| invalid_data("unknown placebo partition"))?;
            stratified_variance(utility, index)
        }
    }
}

fn stratified_variance(
    utility: &[f32; TRAIN_SAMPLES],
    strata: &StrataIndex,
) -> io::Result<(f64, f64)> {
    let stratum_count = strata.lengths.iter().filter(|&&length| length > 0).count();
    if stratum_count == 0 {
        return Err(invalid_data("empty stratified estimator"));
    }
    let mut estimator = 0.0;
    let mut component = 0.0;
    let mut sample_count = 0;
    for group in 0..stratum_count {
        let population_count = strata.lengths[group];
        let sample_count_for_group = SAMPLES_PER_STRATUM;
        if population_count <= sample_count_for_group {
            return Err(invalid_data("invalid finite-population stratum size"));
        }
        let indices = &strata.indices[group][..population_count];
        let variance = sample_variance(indices.iter().map(|&index| utility[index]));
        let weight = population_count as f64 / TRAIN_SAMPLES as f64;
        component += weight * variance;
        estimator += weight.powi(2)
            * (1.0 - sample_count_for_group as f64 / population_count as f64)
            * variance
            / sample_count_for_group as f64;
        sample_count += sample_count_for_group;
    }
    if sample_count != R2_SAMPLE_COUNT {
        return Err(invalid_data(
            "strata do not match the frozen verifier quota",
        ));
    }
    Ok((estimator, component))
}

fn sample_variance(values: impl Iterator<Item = f32> + Clone) -> f64 {
    let count = values.clone().count();
    let mean = values.clone().map(f64::from).sum::<f64>() / count as f64;
    values
        .map(f64::from)
        .map(|value| (value - mean).powi(2))
        .sum::<f64>()
        / (count - 1) as f64
}

fn read_panel_observations(
    path: impl AsRef<Path>,
) -> io::Result<HashMap<(u64, usize, String), PanelObservation>> {
    let mut lines = BufReader::new(File::open(path)?).lines();
    let header = lines
        .next()
        .transpose()?
        .ok_or_else(|| invalid_data("empty R2 panel artifact"))?;
    if !header.starts_with("seed,snapshot_step,method,panel,candidate_count,utility_rmse,") {
        return Err(invalid_data("unexpected R2 panel schema"));
    }
    let mut rows = HashMap::new();
    for line in lines {
        let line = line?;
        let fields: Vec<_> = line.split(',').collect();
        if fields.len() != 23 {
            return Err(invalid_data("malformed R2 panel row"));
        }
        let seed = u64::from_str_radix(fields[0], 16).map_err(parse_error)?;
        let step = fields[1].parse::<usize>().map_err(parse_error)?;
        let method = fields[2].to_owned();
        let panel_id = fields[3].parse::<usize>().map_err(parse_error)?;
        let candidate_count = fields[4].parse::<usize>().map_err(parse_error)?;
        let rmse = fields[5].parse::<f64>().map_err(parse_error)?;
        let row = rows
            .entry((seed, step, method))
            .or_insert_with(|| PanelObservation {
                candidate_count,
                ..PanelObservation::default()
            });
        if row.candidate_count != candidate_count || panel_id >= PANEL_REPLICATES {
            return Err(invalid_data("inconsistent R2 panel cardinality"));
        }
        if std::mem::replace(&mut row.panel_seen[panel_id], true) {
            return Err(invalid_data("duplicate R2 panel row"));
        }
        row.squared_rmse_sum += rmse * rmse;
        row.panel_count += 1;
    }
    Ok(rows)
}

fn read_checkpoints(path: impl AsRef<Path>) -> io::Result<HashMap<(u64, usize), Checkpoint>> {
    let mut lines = BufReader::new(File::open(path)?).lines();
    let header = lines
        .next()
        .transpose()?
        .ok_or_else(|| invalid_data("empty R2 checkpoint artifact"))?;
    if header != "seed,step,train_loss,validation_loss,parameter_fingerprint" {
        return Err(invalid_data("unexpected R2 checkpoint schema"));
    }
    let mut checkpoints = HashMap::new();
    for line in lines {
        let line = line?;
        let fields: Vec<_> = line.split(',').collect();
        if fields.len() != 5 {
            return Err(invalid_data("malformed R2 checkpoint row"));
        }
        let seed = u64::from_str_radix(fields[0], 16).map_err(parse_error)?;
        let step = fields[1].parse::<usize>().map_err(parse_error)?;
        let checkpoint = Checkpoint {
            train_loss: fields[2].parse().map_err(parse_error)?,
            validation_loss: fields[3].parse().map_err(parse_error)?,
            fingerprint: u64::from_str_radix(fields[4], 16).map_err(parse_error)?,
        };
        if checkpoints.insert((seed, step), checkpoint).is_some() {
            return Err(invalid_data("duplicate R2 checkpoint"));
        }
    }
    Ok(checkpoints)
}

fn validate_checkpoint(
    snapshot: ReplaySnapshot,
    train: &[Sample],
    samples: &[Sample],
    expected: &Checkpoint,
) -> io::Result<()> {
    let validation = &samples[TRAIN_SAMPLES..];
    let actual_train = snapshot.model.loss(train);
    let actual_validation = snapshot.model.loss(validation);
    if (actual_train - expected.train_loss).abs() > 5.1e-7
        || (actual_validation - expected.validation_loss).abs() > 5.1e-7
        || parameter_fingerprint(&snapshot.model) != expected.fingerprint
    {
        return Err(invalid_data(
            "reconstructed state does not match R2 receipt",
        ));
    }
    Ok(())
}

fn method_names() -> Vec<String> {
    let mut names: Vec<String> = VARIANCE_METHODS
        .iter()
        .map(|name| (*name).to_owned())
        .collect();
    names.extend((0..PLACEBO_PARTITIONS).map(|id| format!("hash_placebo_{id:02}")));
    names
}

fn parse_error(error: impl std::fmt::Display) -> io::Error {
    invalid_data(format!("invalid R2 artifact value: {error}"))
}

fn invalid_data(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equal_cell_finite_population_variance_matches_closed_form() {
        let utilities = std::array::from_fn(|index| (index % TRAIN_PER_CELL) as f32);
        let ids = std::array::from_fn(|index| (index / TRAIN_PER_CELL) as u8);
        let cells = StrataIndex::new(&ids, CELLS);
        let (variance, component) = stratified_variance(&utilities, &cells).unwrap();
        assert!((variance - 0.0625).abs() < 1.0e-12);
        assert!((component - 6.0).abs() < 1.0e-12);
    }
}

use super::*;

use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::time::Instant;

mod matching;
mod output;
use matching::*;
use output::{
    write_crossover_rows, write_headers, write_match_row, write_path_rows, write_report,
    write_seed_summaries, write_unmatched_rows,
};

const D_MAGNITUDE_TOLERANCE_UNITS: f64 = 1.0;
const ACTION_UNITS: [i16; ACTION_VALUES.len()] = [0, -4, 4, -2, 2, -1, 1];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum MatchDomain {
    ExactVector,
    MagnitudeOnly,
}

impl MatchDomain {
    const ALL: [Self; 2] = [Self::ExactVector, Self::MagnitudeOnly];

    const fn as_str(self) -> &'static str {
        match self {
            Self::ExactVector => "D1_EXACT_VECTOR",
            Self::MagnitudeOnly => "D2_MAGNITUDE_ONLY",
        }
    }

    const fn salt(self) -> u64 {
        match self {
            Self::ExactVector => 0x4431_4558_4143_5400,
            Self::MagnitudeOnly => 0x4432_4d41_474e_4954,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum PairKind {
    SelectedControl,
    ControlControl,
}

impl PairKind {
    const ALL: [Self; 2] = [Self::SelectedControl, Self::ControlControl];

    const fn as_str(self) -> &'static str {
        match self {
            Self::SelectedControl => "G_C1",
            Self::ControlControl => "C1_C2",
        }
    }
}

#[derive(Clone, Copy)]
struct CandidateProgram {
    program: Program,
    utility: f32,
    ordinal: usize,
}

#[derive(Clone, Copy)]
struct TripletMatch {
    control_1: MatchedProgram,
    control_2: CandidateProgram,
    vector_residual_units: [i16; 2],
    magnitude_error_units: f64,
}

#[derive(Clone, Copy)]
struct PlannedSnapshot {
    seed: u64,
    snapshot: Snapshot,
    selected: Option<Program>,
    selected_utility: f32,
    controls: [Option<MatchedProgram>; MATCH_COUNT],
    triplets: [Option<TripletMatch>; MatchDomain::ALL.len() * MATCH_COUNT],
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SourceConditioningReport {
    pub seeds: usize,
    pub snapshots: usize,
    pub pair_snapshots: usize,
    pub matched_selected_control_controls: usize,
    pub exact_vector_triplets: usize,
    pub magnitude_only_triplets: usize,
    pub generated_source_paths: usize,
    pub invalid_source_paths: usize,
    pub invalid_replays: usize,
    pub complete_selected_control: usize,
    pub complete_control_control: usize,
    pub divergent_selected_control: usize,
    pub divergent_control_control: usize,
    pub max_telescoping_residual: f64,
    pub max_source_identity_residual: f64,
    pub max_parameter_distance_drift: f64,
    pub elapsed_seconds: f64,
}

#[derive(Clone, Copy, Debug, Default)]
struct PathDifference {
    differing_commits: usize,
    first_difference: usize,
    cumulative_action_l1: f64,
    net_displacement_l1: f64,
}

#[derive(Clone, Copy)]
struct PairOutcome {
    seed: u64,
    domain: MatchDomain,
    slot: usize,
    pair_kind: PairKind,
    complete: bool,
    divergent: bool,
    delta_a: f64,
    delta_ancestor: f64,
    delta_b: f64,
    interaction: f64,
    ancestor_order: bool,
    path_difference: PathDifference,
}

#[derive(Clone, Copy, Debug, Default)]
struct Summary {
    matched: usize,
    complete: usize,
    censored: usize,
    divergent: usize,
    interaction_all: f64,
    interaction_active: f64,
    delta_a: f64,
    delta_ancestor: f64,
    delta_b: f64,
    ancestor_order: usize,
    differing_all: f64,
    differing_active: f64,
    action_l1_all: f64,
    action_l1_active: f64,
    net_l1_all: f64,
    net_l1_active: f64,
}

pub fn run_source_conditioning_null(
    samples: &[Sample],
    output_dir: impl AsRef<Path>,
    seeds: &[u64],
    artifact_stem: &str,
) -> io::Result<SourceConditioningReport> {
    let started = Instant::now();
    validate_run_inputs(samples, seeds, artifact_stem)?;
    let output_dir = output_dir.as_ref();
    std::fs::create_dir_all(output_dir)?;
    let train = &samples[..TRAIN_SAMPLES];
    let (class_index, cell_index, margin_index) = verifier_indices(train);

    let mut plans = Vec::with_capacity(seeds.len() * SNAPSHOT_STEPS.len());
    for &seed in seeds {
        for snapshot in
            replay_cell_trajectory(train, seed, &class_index, &cell_index, &margin_index)
        {
            let selection = select_cell_program(
                &snapshot.model,
                train,
                seed,
                snapshot.step,
                &class_index,
                &cell_index,
                &margin_index,
            );
            let selected = selection.program.filter(|program| program.len == 2);
            let selected_utility = selected.map_or(0.0, |program| {
                exact_program_value(&snapshot.model, train, snapshot.model.loss(train), program)
            });
            let controls = selected.map_or([None; MATCH_COUNT], |program| {
                matched_same_block_controls(
                    &snapshot.model,
                    train,
                    selection.group,
                    program,
                    selected_utility,
                    seed,
                    snapshot.step,
                )
            });
            let mut triplets = [None; MatchDomain::ALL.len() * MATCH_COUNT];
            if let Some(program) = selected {
                let candidates = all_legal_programs(&snapshot.model, train, selection.group);
                for (domain_index, domain) in MatchDomain::ALL.into_iter().enumerate() {
                    for (slot, control) in controls.iter().copied().enumerate() {
                        let Some(control) = control else {
                            continue;
                        };
                        triplets[domain_index * MATCH_COUNT + slot] = find_control_counterpart(
                            program,
                            selected_utility,
                            control,
                            &candidates,
                            domain,
                            seed,
                            snapshot.step,
                            slot,
                        );
                    }
                }
            }
            plans.push(PlannedSnapshot {
                seed,
                snapshot,
                selected,
                selected_utility,
                controls,
                triplets,
            });
        }
    }

    let exact_matches = plans
        .iter()
        .map(|plan| {
            plan.triplets[..MATCH_COUNT]
                .iter()
                .filter(|row| row.is_some())
                .count()
        })
        .sum::<usize>();
    let magnitude_matches = plans
        .iter()
        .map(|plan| {
            plan.triplets[MATCH_COUNT..]
                .iter()
                .filter(|row| row.is_some())
                .count()
        })
        .sum::<usize>();
    eprintln!(
        "AR-02D preflight: {} checkpoints, {} selected/control matches, {} D1 exact-vector triplets, {} D2 magnitude-only triplets",
        plans.len(),
        plans
            .iter()
            .map(|plan| plan.controls.iter().flatten().count())
            .sum::<usize>(),
        exact_matches,
        magnitude_matches
    );

    let mut matches = BufWriter::new(File::create(
        output_dir.join(format!("{artifact_stem}-matches.csv")),
    )?);
    let mut paths = BufWriter::new(File::create(
        output_dir.join(format!("{artifact_stem}-paths.csv")),
    )?);
    let mut crossovers = BufWriter::new(File::create(
        output_dir.join(format!("{artifact_stem}-crossovers.csv")),
    )?);
    let mut checkpoints = BufWriter::new(File::create(
        output_dir.join(format!("{artifact_stem}-checkpoints.csv")),
    )?);
    write_headers(&mut matches, &mut paths, &mut crossovers, &mut checkpoints)?;

    let mut report = SourceConditioningReport {
        seeds: seeds.len(),
        snapshots: plans.len(),
        ..SourceConditioningReport::default()
    };
    let mut outcomes = Vec::with_capacity(plans.len() * 12);
    for plan in &plans {
        let Some(selected) = plan.selected else {
            write_unmatched_rows(&mut matches, plan, "NO_SELECTED_PAIR")?;
            continue;
        };
        report.pair_snapshots += 1;
        report.matched_selected_control_controls += plan.controls.iter().flatten().count();
        writeln!(
            checkpoints,
            "{:016x},{},{:.9},{:016x},{},{},{:.9},{:.9},{:.9}",
            plan.seed,
            plan.snapshot.step,
            plan.snapshot.model.loss(train),
            parameter_fingerprint(&plan.snapshot.model),
            selected.left,
            selected.right,
            selected.deltas[0],
            selected.deltas[1],
            plan.selected_utility
        )?;

        let mut unique_control_pairs: Vec<(MatchDomain, usize, usize)> = Vec::new();
        let mut needed_paths = vec![false; ACTION_VALUES.len() * ACTION_VALUES.len()];
        needed_paths[program_ordinal(selected)] = true;
        for triplet in plan.triplets.iter().flatten() {
            needed_paths[program_ordinal(triplet.control_1.program)] = true;
            needed_paths[triplet.control_2.ordinal] = true;
        }
        let cache = generate_path_cache(
            plan,
            train,
            &class_index,
            &cell_index,
            &margin_index,
            &needed_paths,
            &mut paths,
            &mut report,
        )?;
        let selected_id = program_ordinal(selected) as i16;
        let ancestor_id = -1;
        let ancestor_path = cached_path(&cache, ancestor_id)?;
        for (domain_index, domain) in MatchDomain::ALL.into_iter().enumerate() {
            for slot in 0..MATCH_COUNT {
                let triplet_index = domain_index * MATCH_COUNT + slot;
                let triplet = plan.triplets[triplet_index];
                let control_1 = plan.controls[slot];
                let duplicate_control_pair = triplet.is_some_and(|matched| {
                    let left = program_ordinal(matched.control_1.program);
                    let right = matched.control_2.ordinal;
                    unique_control_pairs
                        .iter()
                        .any(|(seen_domain, seen_left, seen_right)| {
                            *seen_domain == domain
                                && ((*seen_left == left && *seen_right == right)
                                    || (*seen_left == right && *seen_right == left))
                        })
                });
                write_match_row(
                    &mut matches,
                    plan,
                    domain,
                    slot,
                    control_1,
                    triplet,
                    duplicate_control_pair,
                )?;
                let Some(triplet) = triplet else {
                    continue;
                };
                match domain {
                    MatchDomain::ExactVector => report.exact_vector_triplets += 1,
                    MatchDomain::MagnitudeOnly => report.magnitude_only_triplets += 1,
                }

                let left = program_ordinal(triplet.control_1.program);
                let right = triplet.control_2.ordinal;
                if !duplicate_control_pair {
                    unique_control_pairs.push((domain, left, right));
                }
                let c1_id = program_ordinal(triplet.control_1.program) as i16;
                let c2_id = triplet.control_2.ordinal as i16;
                let control_1_path = cached_path(&cache, c1_id)?;
                let control_2_path = cached_path(&cache, c2_id)?;
                let gc = evaluate_pair(
                    plan,
                    domain,
                    slot,
                    PairKind::SelectedControl,
                    selected,
                    triplet.control_1.program,
                    selected_id,
                    c1_id,
                    cached_path(&cache, selected_id)?,
                    ancestor_path,
                    control_1_path,
                    train,
                    &mut crossovers,
                    &mut report,
                )?;
                outcomes.push(gc);
                if duplicate_control_pair {
                    continue;
                }
                let cc = evaluate_pair(
                    plan,
                    domain,
                    slot,
                    PairKind::ControlControl,
                    triplet.control_1.program,
                    triplet.control_2.program,
                    c1_id,
                    c2_id,
                    control_1_path,
                    ancestor_path,
                    control_2_path,
                    train,
                    &mut crossovers,
                    &mut report,
                )?;
                outcomes.push(cc);
            }
        }
        eprintln!(
            "AR-02D seed {:016x}: processed frozen checkpoint {}",
            plan.seed, plan.snapshot.step
        );
    }
    for writer in [&mut matches, &mut paths, &mut crossovers, &mut checkpoints] {
        writer.flush()?;
    }
    write_seed_summaries(
        output_dir.join(format!("{artifact_stem}-seeds.csv")),
        seeds,
        &outcomes,
    )?;
    output::write_paired_summaries(
        output_dir.join(format!("{artifact_stem}-paired.csv")),
        seeds,
        &outcomes,
    )?;
    report.elapsed_seconds = started.elapsed().as_secs_f64();
    write_report(
        output_dir.join(format!("{artifact_stem}-report.json")),
        report,
        exact_matches,
        magnitude_matches,
    )?;
    Ok(report)
}

fn validate_run_inputs(samples: &[Sample], seeds: &[u64], stem: &str) -> io::Result<()> {
    if samples.len() != TOTAL_SAMPLES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "AR-02D dataset length mismatch",
        ));
    }
    if seeds.is_empty()
        || seeds
            .iter()
            .enumerate()
            .any(|(index, seed)| seeds[..index].contains(seed))
        || stem.is_empty()
        || !stem
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "AR-02D seed list or artifact stem is invalid",
        ));
    }
    Ok(())
}

fn generate_path_cache(
    plan: &PlannedSnapshot,
    train: &[Sample],
    class_index: &StrataIndex,
    cell_index: &StrataIndex,
    margin_index: &StrataIndex,
    needed: &[bool],
    paths_writer: &mut impl Write,
    report: &mut SourceConditioningReport,
) -> io::Result<Vec<Option<FrozenPath>>> {
    let program_count = ACTION_VALUES.len() * ACTION_VALUES.len();
    let mut cache = (0..=program_count).map(|_| None).collect::<Vec<_>>();
    let selected = plan
        .selected
        .expect("cache requested only for selected snapshots");
    let group = Group {
        left: selected.left,
        right: selected.right,
        len: 2,
    };
    for ordinal in 0..program_count {
        if !needed[ordinal] {
            continue;
        }
        let program = program_from_ordinal(group, ordinal);
        let mut source = plan.snapshot.model;
        apply_checked(&mut source, program).map_err(|_| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "matched AR-02D source is illegal",
            )
        })?;
        let path = generate_frozen_path(
            source,
            train,
            plan.seed,
            plan.snapshot.step,
            class_index,
            cell_index,
            margin_index,
        );
        record_generated_path(paths_writer, plan, ordinal as i16, "ACTION", &path)?;
        report.generated_source_paths += 1;
        report.invalid_source_paths += usize::from(path.invalid_source_step != 0);
        cache[ordinal] = Some(path);
    }

    let ancestor = generate_frozen_path(
        plan.snapshot.model,
        train,
        plan.seed,
        plan.snapshot.step,
        class_index,
        cell_index,
        margin_index,
    );
    record_generated_path(paths_writer, plan, -1, "ANCESTOR", &ancestor)?;
    report.generated_source_paths += 1;
    report.invalid_source_paths += usize::from(ancestor.invalid_source_step != 0);
    cache[program_count] = Some(ancestor);
    Ok(cache)
}

fn record_generated_path(
    writer: &mut impl Write,
    plan: &PlannedSnapshot,
    source_id: i16,
    source_kind: &str,
    path: &FrozenPath,
) -> io::Result<()> {
    write_path_rows(writer, plan, source_id, source_kind, path)
}

fn cached_path(cache: &[Option<FrozenPath>], id: i16) -> io::Result<&FrozenPath> {
    let index = if id < 0 {
        cache.len().checked_sub(1)
    } else {
        Some(id as usize)
    };
    index
        .and_then(|index| cache.get(index))
        .and_then(Option::as_ref)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "AR-02D path cache miss"))
}

#[allow(clippy::too_many_arguments)]
fn evaluate_pair(
    plan: &PlannedSnapshot,
    domain: MatchDomain,
    slot: usize,
    pair_kind: PairKind,
    program_a: Program,
    program_b: Program,
    program_a_id: i16,
    program_b_id: i16,
    path_a: &FrozenPath,
    path_ancestor: &FrozenPath,
    path_b: &FrozenPath,
    train: &[Sample],
    writer: &mut impl Write,
    report: &mut SourceConditioningReport,
) -> io::Result<PairOutcome> {
    let replay_a = replay_path(plan.snapshot.model, program_a, program_b, path_a, train);
    let replay_ancestor = replay_path(
        plan.snapshot.model,
        program_a,
        program_b,
        path_ancestor,
        train,
    );
    let replay_b = replay_path(plan.snapshot.model, program_a, program_b, path_b, train);
    let difference = path_difference(path_a, path_b);
    report.invalid_replays += usize::from(replay_a.invalid_step != 0)
        + usize::from(replay_ancestor.invalid_step != 0)
        + usize::from(replay_b.invalid_step != 0);
    report.max_telescoping_residual = report
        .max_telescoping_residual
        .max(replay_a.telescoping_residual.abs())
        .max(replay_ancestor.telescoping_residual.abs())
        .max(replay_b.telescoping_residual.abs());
    report.max_parameter_distance_drift = report
        .max_parameter_distance_drift
        .max(replay_a.max_distance_drift)
        .max(replay_ancestor.max_distance_drift)
        .max(replay_b.max_distance_drift);

    let mut h64 = None;
    for (horizon_index, &horizon) in HORIZONS.iter().enumerate() {
        let point_a = replay_a.points[horizon_index];
        let point_ancestor = replay_ancestor.points[horizon_index];
        let point_b = replay_b.points[horizon_index];
        let values = match (point_a, point_ancestor, point_b) {
            (Some(a), Some(ancestor), Some(b)) => {
                let interaction = a.gap - b.gap;
                let identity = interaction
                    - ((replay_a.points[0].expect("initial point").gap
                        - replay_b.points[0].expect("initial point").gap)
                        + (a.cumulative_mixed - b.cumulative_mixed));
                report.max_source_identity_residual =
                    report.max_source_identity_residual.max(identity.abs());
                Some((a.gap, ancestor.gap, b.gap, interaction, identity.abs()))
            }
            _ => None,
        };
        write_crossover_rows(
            writer,
            plan,
            domain,
            slot,
            pair_kind,
            horizon,
            program_a_id,
            program_b_id,
            values,
            point_a,
            point_ancestor,
            point_b,
            difference,
            replay_a.invalid_step,
            replay_ancestor.invalid_step,
            replay_b.invalid_step,
        )?;
        if horizon == 64 {
            h64 = values;
        }
    }

    if report.max_telescoping_residual > LOSS_TOLERANCE
        || report.max_source_identity_residual > LOSS_TOLERANCE
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "AR-02D mixed-difference identity exceeded tolerance at seed {:016x}, step {}, domain {}",
                plan.seed,
                plan.snapshot.step,
                domain.as_str()
            ),
        ));
    }
    let complete = [path_a, path_ancestor, path_b]
        .into_iter()
        .all(|path| path.invalid_source_step == 0 && path.programs.len() == FUTURE_COMMITS)
        && [&replay_a, &replay_ancestor, &replay_b]
            .into_iter()
            .all(|replay| replay.invalid_step == 0 && replay.points[HORIZONS.len() - 1].is_some());
    if complete {
        match pair_kind {
            PairKind::SelectedControl => report.complete_selected_control += 1,
            PairKind::ControlControl => report.complete_control_control += 1,
        }
        if difference.differing_commits > 0 {
            match pair_kind {
                PairKind::SelectedControl => report.divergent_selected_control += 1,
                PairKind::ControlControl => report.divergent_control_control += 1,
            }
        }
    }
    let Some((delta_a, delta_ancestor, delta_b, interaction, _)) = h64 else {
        return Ok(PairOutcome {
            seed: plan.seed,
            domain,
            slot,
            pair_kind,
            complete: false,
            divergent: difference.differing_commits > 0,
            delta_a: 0.0,
            delta_ancestor: 0.0,
            delta_b: 0.0,
            interaction: 0.0,
            ancestor_order: false,
            path_difference: difference,
        });
    };
    Ok(PairOutcome {
        seed: plan.seed,
        domain,
        slot,
        pair_kind,
        complete,
        divergent: difference.differing_commits > 0,
        delta_a,
        delta_ancestor,
        delta_b,
        interaction,
        ancestor_order: delta_a < delta_ancestor && delta_ancestor < delta_b,
        path_difference: difference,
    })
}

fn path_difference(left: &FrozenPath, right: &FrozenPath) -> PathDifference {
    let mut result = PathDifference::default();
    let mut net_difference = [0.0_f64; PARAMS];
    for step in 0..FUTURE_COMMITS {
        let left_program = left.programs.get(step).copied().flatten();
        let right_program = right.programs.get(step).copied().flatten();
        let left_vector = dense_program_vector(left_program);
        let right_vector = dense_program_vector(right_program);
        let mut step_l1 = 0.0;
        for parameter in 0..PARAMS {
            let delta = left_vector[parameter] - right_vector[parameter];
            step_l1 += delta.abs();
            net_difference[parameter] += delta;
        }
        result.cumulative_action_l1 += step_l1;
        if step_l1 > 1.0e-9 {
            result.differing_commits += 1;
            if result.first_difference == 0 {
                result.first_difference = step + 1;
            }
        }
    }
    result.net_displacement_l1 = net_difference.iter().map(|value| value.abs()).sum();
    result
}

fn dense_program_vector(program: Option<Program>) -> [f64; PARAMS] {
    let mut vector = [0.0; PARAMS];
    if let Some(program) = program {
        if program.len > 0 {
            vector[program.left] += f64::from(program.deltas[0]);
        }
        if program.len == 2 {
            vector[program.right] += f64::from(program.deltas[1]);
        }
    }
    vector
}

#[cfg(test)]
mod tests;

use super::*;
use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::Path;

fn write_horizon_header(writer: &mut impl Write) -> io::Result<()> {
    writeln!(
        writer,
        "comparison_id,seed,control_slot,snapshot_commit,pair_left,pair_right,horizon,delta_under_PG,delta_under_PC,source_interaction,j_sum_PG,j_sum_PC,distance_under_PG,distance_under_PC,PG_complete,PC_complete"
    )
}

fn write_horizons(writer: &mut impl Write, comparison: Comparison) -> io::Result<()> {
    for horizon in HORIZONS {
        let pg = comparison.path_g3.points[point_index(horizon).expect("frozen horizon")];
        let pc = comparison.path_control.points[point_index(horizon).expect("frozen horizon")];
        let delta_g = pg.gap;
        let delta_c = pc.gap;
        let source_interaction = delta_g.zip(delta_c).map(|(g, c)| g - c);
        writeln!(
            writer,
            "{},{:016x},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
            comparison.id,
            comparison.seed,
            comparison.control_slot,
            comparison.snapshot.global_commit,
            comparison.snapshot.group.left,
            comparison.snapshot.group.right,
            horizon,
            optional_float(delta_g),
            optional_float(delta_c),
            optional_float(source_interaction),
            optional_float(pg.cumulative_j),
            optional_float(pc.cumulative_j),
            optional_float(pg.parameter_distance),
            optional_float(pc.parameter_distance),
            u8::from(comparison.path_g3.complete),
            u8::from(comparison.path_control.complete),
        )?;
    }
    Ok(())
}

fn write_comparison_header(writer: &mut impl Write) -> io::Result<()> {
    writeln!(
        writer,
        "comparison_id,seed,control_slot,snapshot_commit,pair_left,pair_right,g3_program_left,g3_program_right,g3_delta_left,g3_delta_right,control_program_left,control_program_right,control_delta_left,control_delta_right,g3_utility,control_utility,utility_match_gap,initial_loss_gap,delta_under_PG_h64,delta_under_PC_h64,source_interaction_h64,j_sum_PG_observed,j_sum_PC_observed,parameter_distance_initial,parameter_distance_PG_h64,parameter_distance_PC_h64,PG_generated_commits,PC_generated_commits,PG_replayed_commits,PC_replayed_commits,PG_complete,PC_complete,PG_invalid_source_step,PC_invalid_source_step,PG_invalid_replay_step,PC_invalid_replay_step,PG_telescoping_residual,PC_telescoping_residual"
    )
}

fn write_comparison(writer: &mut impl Write, comparison: Comparison) -> io::Result<()> {
    let snapshot = comparison.snapshot;
    let control = comparison.control;
    let pg64 = comparison.path_g3.points[HORIZONS.len() - 1];
    let pc64 = comparison.path_control.points[HORIZONS.len() - 1];
    let (_, g3_right) = program_indices(snapshot.g3_program);
    let (control_left, control_right) = program_indices(control.program);
    writeln!(
        writer,
        "{id},{seed:016x},{slot},{snapshot_commit},{pair_left},{pair_right},{g3_program_left},{g3_program_right},{g3_delta_left:.8},{g3_delta_right:.8},{control_program_left},{control_program_right},{control_delta_left:.8},{control_delta_right:.8},{g3_utility:.12e},{control_utility:.12e},{utility_match_gap:.12e},{initial_gap:.12e},{delta_pg},{delta_pc},{source_interaction},{j_pg:.12e},{j_pc:.12e},{distance_initial:.12e},{distance_pg},{distance_pc},{pg_generated},{pc_generated},{pg_replayed},{pc_replayed},{pg_complete},{pc_complete},{pg_source_invalid},{pc_source_invalid},{pg_replay_invalid},{pc_replay_invalid},{pg_residual:.12e},{pc_residual:.12e}",
        id = comparison.id,
        seed = comparison.seed,
        slot = comparison.control_slot,
        snapshot_commit = snapshot.global_commit,
        pair_left = snapshot.group.left,
        pair_right = snapshot.group.right,
        g3_program_left = snapshot.g3_program.left,
        g3_program_right = g3_right,
        g3_delta_left = snapshot.g3_program.deltas[0],
        g3_delta_right = snapshot.g3_program.deltas[1],
        control_program_left = control_left,
        control_program_right = control_right,
        control_delta_left = control.program.deltas[0],
        control_delta_right = control.program.deltas[1],
        g3_utility = snapshot.g3_utility,
        control_utility = control.utility,
        utility_match_gap = (snapshot.g3_utility - control.utility).abs(),
        initial_gap = comparison.path_g3.initial_gap,
        delta_pg = optional_float(pg64.gap),
        delta_pc = optional_float(pc64.gap),
        source_interaction = optional_float(pg64.gap.zip(pc64.gap).map(|(g, c)| g - c)),
        j_pg = comparison.path_g3.cumulative_j,
        j_pc = comparison.path_control.cumulative_j,
        distance_initial = comparison.path_g3.parameter_distance_initial,
        distance_pg = optional_float(pg64.parameter_distance),
        distance_pc = optional_float(pc64.parameter_distance),
        pg_generated = comparison.path_g3.generated_commits,
        pc_generated = comparison.path_control.generated_commits,
        pg_replayed = comparison.path_g3.replayed_commits,
        pc_replayed = comparison.path_control.replayed_commits,
        pg_complete = u8::from(comparison.path_g3.complete),
        pc_complete = u8::from(comparison.path_control.complete),
        pg_source_invalid = step_value(comparison.path_g3.invalid_source_step),
        pc_source_invalid = step_value(comparison.path_control.invalid_source_step),
        pg_replay_invalid = step_value(comparison.path_g3.invalid_replay_step),
        pc_replay_invalid = step_value(comparison.path_control.invalid_replay_step),
        pg_residual = comparison.path_g3.telescoping_residual,
        pc_residual = comparison.path_control.telescoping_residual,
    )
}

fn program_indices(program: Program) -> (i64, i64) {
    (
        program.left as i64,
        if program.len == 2 {
            program.right as i64
        } else {
            -1
        },
    )
}

fn optional_float(value: Option<f64>) -> String {
    value.map_or_else(String::new, |value| format!("{value:.12e}"))
}

fn step_value(value: usize) -> i64 {
    if value == 0 { -1 } else { value as i64 }
}

fn aggregate_horizons(comparisons: &[Comparison]) -> [HorizonAggregate; HORIZONS.len()] {
    let mut output = [HorizonAggregate::default(); HORIZONS.len()];
    for comparison in comparisons {
        for (index, horizon) in HORIZONS.iter().copied().enumerate() {
            let pg = comparison.path_g3.points[index];
            let pc = comparison.path_control.points[index];
            let (
                Some(delta_g),
                Some(j_g),
                Some(distance_g),
                Some(delta_c),
                Some(j_c),
                Some(distance_c),
            ) = (
                pg.gap,
                pg.cumulative_j,
                pg.parameter_distance,
                pc.gap,
                pc.cumulative_j,
                pc.parameter_distance,
            )
            else {
                continue;
            };
            let aggregate = &mut output[index];
            aggregate.count += 1;
            aggregate.delta_g_sum += delta_g;
            aggregate.delta_c_sum += delta_c;
            aggregate.source_interaction_sum += delta_g - delta_c;
            aggregate.j_g_sum += j_g;
            aggregate.j_c_sum += j_c;
            aggregate.distance_g_sum += distance_g;
            aggregate.distance_c_sum += distance_c;
            debug_assert_eq!(pg.horizon, horizon);
            debug_assert_eq!(pc.horizon, horizon);
        }
    }
    output
}

fn write_runs(writer: &mut impl Write, comparisons: &[Comparison]) -> io::Result<()> {
    writeln!(
        writer,
        "seed,horizon,paired_comparisons,mean_delta_under_PG,mean_delta_under_PC,mean_source_interaction,mean_cumulative_J_PG,mean_cumulative_J_PC,mean_parameter_distance_PG,mean_parameter_distance_PC"
    )?;
    for seed in std::iter::once(None).chain(SEEDS.into_iter().map(Some)) {
        let selected: Vec<_> = comparisons
            .iter()
            .copied()
            .filter(|comparison| seed.is_none_or(|value| comparison.seed == value))
            .collect();
        let aggregates = aggregate_horizons(&selected);
        let seed_label = seed.map_or_else(|| "all".to_owned(), |value| format!("{value:016x}"));
        for (horizon, aggregate) in HORIZONS.iter().copied().zip(aggregates) {
            let divisor = aggregate.count.max(1) as f64;
            writeln!(
                writer,
                "{seed_label},{horizon},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e}",
                aggregate.count,
                aggregate.delta_g_sum / divisor,
                aggregate.delta_c_sum / divisor,
                aggregate.source_interaction_sum / divisor,
                aggregate.j_g_sum / divisor,
                aggregate.j_c_sum / divisor,
                aggregate.distance_g_sum / divisor,
                aggregate.distance_c_sum / divisor,
            )?;
        }
    }
    Ok(())
}

fn write_report(writer: &mut impl Write, report: QReport) -> io::Result<()> {
    writeln!(writer, "{{")?;
    writeln!(writer, "  \"schema\": \"adaptive-runtime-ar-01q/v1\",")?;
    writeln!(
        writer,
        "  \"scope\": \"engineering-only; toy-scale; no biological correspondence; no general optimizer claim\","
    )?;
    writeln!(
        writer,
        "  \"protocol\": \"For each eligible AR-01P N2 same-block control, generate P_G from the G3 post-program state and P_C from the matched-control post-program state, using identical family-0 evidence seed and phase-0 pair schedule. Freeze each 63-program path, then replay each path into both initial branches without replanning. Stop at the first bounds-invalid action without clamp or replacement. J is the exact per-step change in the full-training-loss branch gap.\","
    )?;
    writeln!(writer, "  \"path_horizons\": [1, 2, 4, 8, 16, 32, 64],")?;
    writeln!(writer, "  \"seeds\": {},", report.seeds)?;
    writeln!(writer, "  \"snapshots\": {},", report.snapshots)?;
    writeln!(
        writer,
        "  \"matched_controls\": {},",
        report.matched_controls
    )?;
    writeln!(writer, "  \"comparisons\": {},", report.comparisons)?;
    writeln!(writer, "  \"generated_paths\": {},", report.generated_paths)?;
    writeln!(
        writer,
        "  \"invalid_source_paths\": {},",
        report.invalid_source_paths
    )?;
    writeln!(
        writer,
        "  \"invalid_replay_paths\": {},",
        report.invalid_replay_paths
    )?;
    writeln!(
        writer,
        "  \"invalid_replay_PG_paths\": {},",
        report.invalid_replay_g3_paths
    )?;
    writeln!(
        writer,
        "  \"invalid_replay_PC_paths\": {},",
        report.invalid_replay_control_paths
    )?;
    writeln!(
        writer,
        "  \"future_commits_replayed\": {},",
        report.future_commits_replayed
    )?;
    writeln!(writer, "  \"path_events\": {},", report.path_events)?;
    writeln!(
        writer,
        "  \"complete_h64_crossovers\": {},",
        report.complete_h64_crossovers
    )?;
    writeln!(
        writer,
        "  \"max_telescoping_residual\": {:.12e},",
        report.max_telescoping_residual
    )?;
    writeln!(
        writer,
        "  \"max_source_interaction_identity_residual\": {:.12e},",
        report.max_source_interaction_identity_residual
    )?;
    writeln!(
        writer,
        "  \"max_parameter_distance_drift\": {:.12e},",
        report.max_parameter_distance_drift
    )?;
    writeln!(
        writer,
        "  \"mean_delta_G_under_PG_h1\": {:.12e},",
        report.mean_delta_g_at_1
    )?;
    writeln!(
        writer,
        "  \"mean_delta_G_under_PG_h64_complete_pairs\": {:.12e},",
        report.mean_delta_g_at_64
    )?;
    writeln!(
        writer,
        "  \"mean_delta_G_under_PC_h1\": {:.12e},",
        report.mean_delta_c_at_1
    )?;
    writeln!(
        writer,
        "  \"mean_delta_G_under_PC_h64_complete_pairs\": {:.12e},",
        report.mean_delta_c_at_64
    )?;
    writeln!(
        writer,
        "  \"mean_source_interaction_h64_complete_pairs\": {:.12e},",
        report.mean_source_interaction_at_64
    )?;
    writeln!(
        writer,
        "  \"g3_favored_under_both_paths_h64\": {},",
        report.g3_favored_under_both_paths
    )?;
    writeln!(
        writer,
        "  \"source_aligned_h64\": {},",
        report.source_aligned_at_64
    )?;
    writeln!(
        writer,
        "  \"g3_path_only_favors_g3_h64\": {},",
        report.g3_path_only_favors_g3
    )?;
    writeln!(
        writer,
        "  \"control_path_only_favors_g3_h64\": {},",
        report.control_path_only_favors_g3
    )?;
    writeln!(
        writer,
        "  \"control_favored_under_both_paths_h64\": {},",
        report.control_favored_under_both_paths
    )?;
    writeln!(
        writer,
        "  \"neutral_or_tied_h64\": {}",
        report.neutral_or_tied_at_64
    )?;
    writeln!(writer, "}}")
}

fn summarize(comparisons: &[Comparison], mut report: QReport) -> QReport {
    let aggregates = aggregate_horizons(comparisons);
    let first = aggregates[0];
    let last = aggregates[HORIZONS.len() - 1];
    report.complete_h64_crossovers = last.count;
    report.mean_delta_g_at_1 = first.delta_g_sum / first.count.max(1) as f64;
    report.mean_delta_g_at_64 = last.delta_g_sum / last.count.max(1) as f64;
    report.mean_delta_c_at_1 = first.delta_c_sum / first.count.max(1) as f64;
    report.mean_delta_c_at_64 = last.delta_c_sum / last.count.max(1) as f64;
    report.mean_source_interaction_at_64 = last.source_interaction_sum / last.count.max(1) as f64;
    for comparison in comparisons {
        let pg = comparison.path_g3.points[HORIZONS.len() - 1].gap;
        let pc = comparison.path_control.points[HORIZONS.len() - 1].gap;
        if let (Some(delta_g), Some(delta_c)) = (pg, pc) {
            if delta_g < 0.0 && delta_c < 0.0 {
                report.g3_favored_under_both_paths += 1;
            }
            if delta_g < 0.0 && delta_c > 0.0 {
                report.source_aligned_at_64 += 1;
            }
            if delta_g < 0.0 && delta_c == 0.0 {
                report.g3_path_only_favors_g3 += 1;
            }
            if delta_g > 0.0 && delta_c < 0.0 {
                report.control_path_only_favors_g3 += 1;
            }
            if delta_g > 0.0 && delta_c > 0.0 {
                report.control_favored_under_both_paths += 1;
            }
            if delta_g == 0.0 || delta_c == 0.0 {
                report.neutral_or_tied_at_64 += 1;
            }
        }
    }
    report
}

pub fn run_path_source_crossover(
    samples: &[Sample],
    artifacts: impl AsRef<Path>,
) -> io::Result<QReport> {
    if samples.len() != TOTAL_SAMPLES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "AR-01Q dataset length mismatch",
        ));
    }
    let artifacts = artifacts.as_ref();
    fs::create_dir_all(artifacts)?;
    let train = &samples[..TRAIN_SAMPLES];
    let mut path_writer = BufWriter::new(File::create(artifacts.join("ar-01q-path.csv"))?);
    let mut horizon_writer = BufWriter::new(File::create(artifacts.join("ar-01q-horizons.csv"))?);
    let mut comparison_writer =
        BufWriter::new(File::create(artifacts.join("ar-01q-comparisons.csv"))?);
    write_path_header(&mut path_writer)?;
    write_horizon_header(&mut horizon_writer)?;
    write_comparison_header(&mut comparison_writer)?;

    let mut comparisons = Vec::new();
    let mut report = QReport {
        seeds: SEEDS.len(),
        ..QReport::default()
    };
    let mut comparison_id = 0_u64;
    for seed in SEEDS {
        let snapshots = collect_snapshots(train, seed);
        report.snapshots += snapshots.len();
        let eligible_controls = snapshots
            .iter()
            .map(|snapshot| snapshot.controls.iter().flatten().count())
            .sum::<usize>();
        report.matched_controls += eligible_controls;
        eprintln!(
            "AR-01Q seed {seed:016x}: {} snapshots, {eligible_controls} N2 controls; preparing path-source crossover",
            snapshots.len()
        );

        for (snapshot_index, snapshot) in snapshots.into_iter().enumerate() {
            let mut g3_source = snapshot.model;
            commit(&mut g3_source, snapshot.g3_program);
            let path_g3 = generate_frozen_path(g3_source, train, seed, snapshot.global_commit);
            report.generated_paths += 1;
            report.invalid_source_paths += usize::from(path_g3.invalid_source_step != 0);

            for (control_slot, maybe_control) in snapshot.controls.into_iter().enumerate() {
                let Some(control) = maybe_control else {
                    continue;
                };
                let mut control_source = snapshot.model;
                if program_illegal_parameter(&control_source, Some(control.program)).is_some()
                    || program_illegal_parameter(&snapshot.model, Some(snapshot.g3_program))
                        .is_some()
                {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "AR-01Q initial matched program violates bounds",
                    ));
                }
                commit(&mut control_source, control.program);
                let path_control =
                    generate_frozen_path(control_source, train, seed, snapshot.global_commit);
                report.generated_paths += 1;
                report.invalid_source_paths += usize::from(path_control.invalid_source_step != 0);

                comparison_id += 1;
                let g3_result = replay_frozen_path(
                    &mut path_writer,
                    comparison_id,
                    seed,
                    PathSource::G3,
                    control_slot,
                    snapshot,
                    control,
                    &path_g3,
                    train,
                )?;
                let control_result = replay_frozen_path(
                    &mut path_writer,
                    comparison_id,
                    seed,
                    PathSource::Control,
                    control_slot,
                    snapshot,
                    control,
                    &path_control,
                    train,
                )?;
                report.path_events += 2
                    + g3_result.replayed_commits
                    + control_result.replayed_commits
                    + usize::from(g3_result.invalid_replay_step != 0)
                    + usize::from(control_result.invalid_replay_step != 0);
                report.future_commits_replayed +=
                    g3_result.replayed_commits + control_result.replayed_commits;
                report.invalid_replay_paths += usize::from(g3_result.invalid_replay_step != 0)
                    + usize::from(control_result.invalid_replay_step != 0);
                report.invalid_replay_g3_paths += usize::from(g3_result.invalid_replay_step != 0);
                report.invalid_replay_control_paths +=
                    usize::from(control_result.invalid_replay_step != 0);
                report.max_telescoping_residual = report
                    .max_telescoping_residual
                    .max(g3_result.telescoping_residual.abs())
                    .max(control_result.telescoping_residual.abs());
                report.max_parameter_distance_drift = report
                    .max_parameter_distance_drift
                    .max(g3_result.max_parameter_distance_drift)
                    .max(control_result.max_parameter_distance_drift);

                let mut max_source_identity_residual = 0.0_f64;
                for index in 0..HORIZONS.len() {
                    if let (Some(gap_g), Some(j_g), Some(gap_c), Some(j_c)) = (
                        g3_result.points[index].gap,
                        g3_result.points[index].cumulative_j,
                        control_result.points[index].gap,
                        control_result.points[index].cumulative_j,
                    ) {
                        max_source_identity_residual =
                            max_source_identity_residual.max(((gap_g - gap_c) - (j_g - j_c)).abs());
                    }
                }
                report.max_source_interaction_identity_residual = report
                    .max_source_interaction_identity_residual
                    .max(max_source_identity_residual);
                if g3_result.telescoping_residual.abs() > LOSS_TOLERANCE
                    || control_result.telescoping_residual.abs() > LOSS_TOLERANCE
                    || max_source_identity_residual > LOSS_TOLERANCE
                {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        format!(
                            "AR-01Q mixed-difference identity exceeded tolerance at comparison {comparison_id}"
                        ),
                    ));
                }

                let comparison = Comparison {
                    id: comparison_id,
                    seed,
                    control_slot,
                    snapshot,
                    control,
                    path_g3: g3_result,
                    path_control: control_result,
                };
                write_horizons(&mut horizon_writer, comparison)?;
                write_comparison(&mut comparison_writer, comparison)?;
                comparisons.push(comparison);
            }
            if (snapshot_index + 1).is_multiple_of(16) {
                eprintln!(
                    "AR-01Q seed {seed:016x}: processed {}/{} snapshots; {} crossovers",
                    snapshot_index + 1,
                    TOTAL_COMMITS / SAME_BLOCK_EVERY,
                    comparison_id
                );
            }
        }
    }

    path_writer.flush()?;
    horizon_writer.flush()?;
    comparison_writer.flush()?;
    report.comparisons = comparisons.len();
    report = summarize(&comparisons, report);

    let mut runs_writer = BufWriter::new(File::create(artifacts.join("ar-01q-runs.csv"))?);
    write_runs(&mut runs_writer, &comparisons)?;
    runs_writer.flush()?;
    let mut report_writer = BufWriter::new(File::create(artifacts.join("ar-01q-report.json"))?);
    write_report(&mut report_writer, report)?;
    report_writer.flush()?;
    Ok(report)
}

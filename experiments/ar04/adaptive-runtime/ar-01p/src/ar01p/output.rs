use super::*;
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::Path;

fn write_comparison_header(writer: &mut impl Write) -> io::Result<()> {
    writeln!(
        writer,
        "id,seed,stream,control_slot,snapshot_commit,pair_left,pair_right,g3_delta_left,g3_delta_right,control_delta_left,control_delta_right,g3_immediate_utility,control_immediate_utility,utility_gap,initial_gap,final_gap,cumulative_j,positive_j,negative_j,max_abs_j,top1_favorable_share,top5_favorable_share,top10_favorable_share,reversal_horizon,valid_future_commits,invalid_future_step,invalid_parameter,telescoping_residual,max_event_decomposition_residual"
    )
}

fn write_comparison(
    writer: &mut impl Write,
    summary: &ComparisonSummary,
    snapshot: Snapshot,
    control: MatchedControl,
) -> io::Result<()> {
    writeln!(
        writer,
        "{},{:016x},{},{},{},{},{},{:.6},{:.6},{:.6},{:.6},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.8},{:.8},{:.8},{},{},{},{},{:.12e},{:.12e}",
        summary.id,
        summary.seed,
        summary.stream.label(),
        summary.control_slot,
        summary.global_commit,
        summary.group_left,
        summary.group_right,
        summary.initial_delta_left,
        summary.initial_delta_right,
        summary.control_delta_left,
        summary.control_delta_right,
        snapshot.g3_utility,
        control.utility,
        (snapshot.g3_utility - control.utility).abs(),
        summary.initial_gap,
        summary.final_gap,
        summary.cumulative_j,
        summary.positive_j,
        summary.negative_j,
        summary.max_abs_j,
        summary.top1_favorable_share,
        summary.top5_favorable_share,
        summary.top10_favorable_share,
        summary.reversal_horizon,
        summary.valid_future_commits,
        summary.invalid_future_step,
        if summary.invalid_parameter == usize::MAX {
            -1_i64
        } else {
            summary.invalid_parameter as i64
        },
        summary.telescoping_residual,
        summary.max_event_decomposition_residual,
    )
}

fn write_structure(
    writer: &mut impl Write,
    values: &BTreeMap<(u64, u8, u8, u8), Aggregate>,
) -> io::Result<()> {
    writeln!(
        writer,
        "seed,stream,control_slot,action_relation,events,sum_j,mean_j,sum_abs_j,positive_j,negative_j"
    )?;
    for (&(seed, stream, slot, relation), aggregate) in values {
        let relation = match relation {
            0 => ActionRelation::NoOp,
            1 => ActionRelation::DirectOverlap,
            2 => ActionRelation::SameHiddenUnit,
            3 => ActionRelation::AdjacentLayer,
            4 => ActionRelation::SameLayerUnrelated,
            _ => ActionRelation::StructuralRemote,
        };
        writeln!(
            writer,
            "{seed:016x},{},{slot},{},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e}",
            if stream == Stream::L0 as u8 {
                Stream::L0.label()
            } else {
                Stream::L2.label()
            },
            relation.label(),
            aggregate.events,
            aggregate.sum_j,
            aggregate.sum_j / aggregate.events.max(1) as f64,
            aggregate.sum_abs_j,
            aggregate.positive_j,
            aggregate.negative_j,
        )?;
    }
    Ok(())
}

fn write_geometry(
    writer: &mut impl Write,
    values: &BTreeMap<(u64, u8, u8, u8, u8), Aggregate>,
) -> io::Result<()> {
    writeln!(
        writer,
        "seed,stream,control_slot,axis,bin,events,sum_event_mean_j,mean_event_mean_j,sum_abs_event_mean_j"
    )?;
    for (&(seed, stream, slot, axis, bin), aggregate) in values {
        let (axis, label) = if axis == 0 {
            ("class", format!("class_{bin}"))
        } else {
            ("geometry_stratum", format!("stratum_{bin}"))
        };
        writeln!(
            writer,
            "{seed:016x},{},{slot},{axis},{label},{},{:.12e},{:.12e},{:.12e}",
            if stream == Stream::L0 as u8 {
                Stream::L0.label()
            } else {
                Stream::L2.label()
            },
            aggregate.events,
            aggregate.sum_j,
            aggregate.sum_j / aggregate.events.max(1) as f64,
            aggregate.sum_abs_j,
        )?;
    }
    Ok(())
}

fn write_masks(writer: &mut impl Write, events: &mut [MaskEvent]) -> io::Result<()> {
    events.sort_by(|left, right| right.abs_j.total_cmp(&left.abs_j));
    let top_count = events.len().div_ceil(10);
    writeln!(
        writer,
        "magnitude_group,events,mean_abs_j,mean_relu_mask_diff_before,mean_relu_mask_diff_after,mean_newly_different_examples,mean_resolved_examples,none,new,expanding,contracting,turnover,stable_difference"
    )?;
    for (label, slice) in [
        ("top_decile", &events[..top_count]),
        ("remaining", &events[top_count..]),
    ] {
        if slice.is_empty() {
            continue;
        }
        let n = slice.len() as f64;
        let abs_j = slice.iter().map(|event| event.abs_j).sum::<f64>() / n;
        let before = slice
            .iter()
            .map(|event| f64::from(event.diff_before))
            .sum::<f64>()
            / n;
        let after = slice
            .iter()
            .map(|event| f64::from(event.diff_after))
            .sum::<f64>()
            / n;
        let newly = slice
            .iter()
            .map(|event| f64::from(event.newly_different))
            .sum::<f64>()
            / n;
        let resolved = slice
            .iter()
            .map(|event| f64::from(event.resolved))
            .sum::<f64>()
            / n;
        let mut transitions = [0usize; 6];
        for event in slice {
            transitions[event.transition as usize] += 1;
        }
        writeln!(
            writer,
            "{label},{},{abs_j:.12e},{before:.6},{after:.6},{newly:.6},{resolved:.6},{},{},{},{},{},{}",
            slice.len(),
            transitions[MaskTransition::None as usize],
            transitions[MaskTransition::New as usize],
            transitions[MaskTransition::Expanding as usize],
            transitions[MaskTransition::Contracting as usize],
            transitions[MaskTransition::Turnover as usize],
            transitions[MaskTransition::Stable as usize],
        )?;
    }
    Ok(())
}

fn stream_stats(summaries: &[ComparisonSummary], stream: Stream) -> (usize, usize, f64, f64, f64) {
    let selected: Vec<_> = summaries
        .iter()
        .filter(|row| row.stream == stream)
        .collect();
    let count = selected.len();
    let reversals = selected
        .iter()
        .filter(|row| row.reversal_horizon != 0)
        .count();
    let mean_final = selected.iter().map(|row| row.final_gap).sum::<f64>() / count.max(1) as f64;
    let mean_j = selected.iter().map(|row| row.cumulative_j).sum::<f64>() / count.max(1) as f64;
    let mean_residual = selected
        .iter()
        .map(|row| row.telescoping_residual.abs())
        .sum::<f64>()
        / count.max(1) as f64;
    (count, reversals, mean_final, mean_j, mean_residual)
}

fn write_runs(writer: &mut impl Write, summaries: &[ComparisonSummary]) -> io::Result<()> {
    writeln!(
        writer,
        "stream,comparisons,reversals,reversal_rate,mean_initial_gap,mean_final_gap,mean_cumulative_j,mean_abs_telescoping_residual"
    )?;
    for stream in [Stream::L0, Stream::L2] {
        let rows: Vec<_> = summaries
            .iter()
            .filter(|row| row.stream == stream)
            .collect();
        let count = rows.len();
        let mean_initial =
            rows.iter().map(|row| row.initial_gap).sum::<f64>() / count.max(1) as f64;
        let (count, reversals, mean_final, mean_j, mean_residual) = stream_stats(summaries, stream);
        writeln!(
            writer,
            "{},{count},{reversals},{:.8},{mean_initial:.12e},{mean_final:.12e},{mean_j:.12e},{mean_residual:.12e}",
            stream.label(),
            reversals as f64 / count.max(1) as f64,
        )?;
    }
    Ok(())
}

fn write_report(writer: &mut impl Write, report: PReport) -> io::Result<()> {
    writeln!(
        writer,
        "{{\n  \"schema\": \"adaptive-runtime-ar-01p/v1\",\n  \"scope\": \"engineering-only; toy-scale; no biological correspondence; no general optimizer claim\",\n  \"protocol\": \"For each N2 same-block matched pair, apply the G3/control initial programs, then replay identical frozen common actions. L0 is the unbranched original G3 stream; L2 is generated from the G3 post-initial state under phase 17. Per-event J is the exact full-train loss-gap increment; class and 8 geometry-stratum means use per-example four-state mixed differences. ReLU masks encode post-activation positivity in both hidden layers. Invalid frozen actions stop a path without replacement.\",\n  \"seeds\": {},\n  \"snapshots\": {},\n  \"matched_controls\": {},\n  \"comparisons\": {},\n  \"path_events\": {},\n  \"invalid_paths\": {},\n  \"loss_identity_tolerance\": {:.3e},\n  \"max_telescoping_residual\": {:.12e},\n  \"max_event_decomposition_residual\": {:.12e},\n  \"L0_mean_final_gap\": {:.12e},\n  \"L2_mean_final_gap\": {:.12e},\n  \"L0_reversal_rate\": {:.8},\n  \"L2_reversal_rate\": {:.8}\n}}",
        report.seeds,
        report.snapshots,
        report.matched_controls,
        report.comparisons,
        report.path_events,
        report.invalid_paths,
        LOSS_TOLERANCE,
        report.max_telescoping_residual,
        report.max_event_decomposition_residual,
        report.l0_mean_final_gap,
        report.l2_mean_final_gap,
        report.l0_reversal_rate,
        report.l2_reversal_rate,
    )
}

pub fn run_mixed_difference_ledger(
    samples: &[Sample],
    artifacts: impl AsRef<Path>,
) -> io::Result<PReport> {
    if samples.len() != TOTAL_SAMPLES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "AR-01P dataset length mismatch",
        ));
    }
    let artifacts = artifacts.as_ref();
    fs::create_dir_all(artifacts)?;
    let train = &samples[..TRAIN_SAMPLES];
    let mut path_writer = BufWriter::new(File::create(artifacts.join("ar-01p-path.csv"))?);
    let mut comparison_writer =
        BufWriter::new(File::create(artifacts.join("ar-01p-comparisons.csv"))?);
    writeln!(
        path_writer,
        "seed,comparison_id,stream,control_slot,snapshot_commit,horizon,pair_left,pair_right,action_left,action_right,action_delta_left,action_delta_right,d_before,d_after,j_exact,j_per_example_mean,event_decomposition_residual,class0_mean_j,class1_mean_j,class2_mean_j,stratum0_mean_j,stratum1_mean_j,stratum2_mean_j,stratum3_mean_j,stratum4_mean_j,stratum5_mean_j,stratum6_mean_j,stratum7_mean_j,relu_diff_before,relu_diff_after,relu_newly_different,relu_resolved,action_relation,relu_transition"
    )?;
    write_comparison_header(&mut comparison_writer)?;
    let mut summaries = Vec::new();
    let mut structure = BTreeMap::new();
    let mut geometry = BTreeMap::new();
    let mut masks = Vec::new();
    let mut snapshots_total = 0;
    let mut matched_total = 0;
    let mut comparison_id = 0_u64;
    for seed in SEEDS {
        let (snapshots, base_programs, _) = base_snapshots(train, seed, true);
        let seed_snapshot_count = snapshots.len();
        snapshots_total += snapshots.len();
        matched_total += snapshots
            .iter()
            .map(|snapshot| snapshot.controls.iter().flatten().count())
            .sum::<usize>();
        eprintln!(
            "AR-01P seed {seed:016x}: {} selected-pair snapshots, {} matched controls; tracing L0/L2",
            snapshots.len(),
            snapshots
                .iter()
                .map(|snapshot| snapshot.controls.iter().flatten().count())
                .sum::<usize>()
        );
        for (snapshot_index, snapshot) in snapshots.into_iter().enumerate() {
            let l0_start = snapshot.global_commit + 1;
            let l0_end = l0_start + FUTURE_COMMITS;
            let l0 = &base_programs[l0_start..l0_end];
            let l2 = shifted_frozen_stream(snapshot, train, seed);
            for (slot, maybe_control) in snapshot.controls.into_iter().enumerate() {
                let Some(control) = maybe_control else {
                    continue;
                };
                for (kind, frozen) in [(Stream::L0, l0), (Stream::L2, l2.as_slice())] {
                    comparison_id += 1;
                    let summary = compare_path(
                        &mut path_writer,
                        comparison_id,
                        seed,
                        snapshot,
                        slot,
                        control,
                        kind,
                        frozen,
                        train,
                        &mut structure,
                        &mut geometry,
                        &mut masks,
                    )?;
                    if summary.telescoping_residual.abs() > LOSS_TOLERANCE
                        || summary.max_event_decomposition_residual > LOSS_TOLERANCE
                    {
                        return Err(io::Error::new(
                            io::ErrorKind::InvalidData,
                            format!(
                                "AR-01P identity residual exceeded tolerance for comparison {}",
                                summary.id
                            ),
                        ));
                    }
                    write_comparison(&mut comparison_writer, &summary, snapshot, control)?;
                    summaries.push(summary);
                }
            }
            if (snapshot_index + 1).is_multiple_of(24) {
                eprintln!(
                    "AR-01P seed {seed:016x}: traced {}/{} snapshots",
                    snapshot_index + 1,
                    seed_snapshot_count
                );
            }
        }
    }
    path_writer.flush()?;
    comparison_writer.flush()?;
    let mut structure_writer =
        BufWriter::new(File::create(artifacts.join("ar-01p-structure.csv"))?);
    write_structure(&mut structure_writer, &structure)?;
    structure_writer.flush()?;
    let mut geometry_writer = BufWriter::new(File::create(artifacts.join("ar-01p-geometry.csv"))?);
    write_geometry(&mut geometry_writer, &geometry)?;
    geometry_writer.flush()?;
    let mut mask_writer = BufWriter::new(File::create(artifacts.join("ar-01p-mask.csv"))?);
    write_masks(&mut mask_writer, &mut masks)?;
    mask_writer.flush()?;
    let (l0_count, l0_reversals, l0_mean, _, _) = stream_stats(&summaries, Stream::L0);
    let (l2_count, l2_reversals, l2_mean, _, _) = stream_stats(&summaries, Stream::L2);
    let report = PReport {
        seeds: SEEDS.len(),
        snapshots: snapshots_total,
        matched_controls: matched_total,
        comparisons: summaries.len(),
        path_events: summaries.iter().map(|row| row.valid_future_commits).sum(),
        invalid_paths: summaries
            .iter()
            .filter(|row| row.invalid_future_step != 0)
            .count(),
        max_telescoping_residual: summaries
            .iter()
            .map(|row| row.telescoping_residual.abs())
            .fold(0.0, f64::max),
        max_event_decomposition_residual: summaries
            .iter()
            .map(|row| row.max_event_decomposition_residual)
            .fold(0.0, f64::max),
        l0_mean_final_gap: l0_mean,
        l2_mean_final_gap: l2_mean,
        l0_reversal_rate: l0_reversals as f64 / l0_count.max(1) as f64,
        l2_reversal_rate: l2_reversals as f64 / l2_count.max(1) as f64,
    };
    let mut runs_writer = BufWriter::new(File::create(artifacts.join("ar-01p-runs.csv"))?);
    write_runs(&mut runs_writer, &summaries)?;
    runs_writer.flush()?;
    let mut report_writer = BufWriter::new(File::create(artifacts.join("ar-01p-report.json"))?);
    write_report(&mut report_writer, report)?;
    report_writer.flush()?;
    Ok(report)
}

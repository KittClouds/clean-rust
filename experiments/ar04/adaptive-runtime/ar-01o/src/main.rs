use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_01o::{
    MappedDataset, OComparison, OPEN_LOOP_HORIZONS, OSeedSummary, open_loop_diagnostic_all,
    write_dataset,
};

#[derive(Clone, Copy, Debug, Default)]
struct RunStats {
    comparisons: usize,
    valid: usize,
    invalid_by_horizon: usize,
    mean_delta: f64,
    g3_better_rate: f64,
    first_divergences: usize,
    block_divergences: usize,
    program_divergences: usize,
    mean_first_divergence: f64,
    mean_g3_margin: f64,
    mean_control_margin: f64,
}

fn mode_name(mode: u8) -> &'static str {
    match mode {
        0 => "O1-closed-loop",
        1 => "O2-frozen-base-open-loop",
        _ => "unknown",
    }
}

fn stream_name(comparison: &OComparison) -> &'static str {
    if comparison.mode == 1 {
        return "frozen-base-original-stream";
    }
    match (comparison.family, comparison.replicate) {
        (0, 0) => "L0-original",
        (2, 0) => "L2-shifted-17",
        (2, 1) => "L2-shifted-36",
        _ => "unknown",
    }
}

fn rate(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
}

fn comparison_group(
    results: &[OSeedSummary],
    mode: u8,
    family: u8,
    replicate: usize,
    slot: u8,
) -> Vec<&OComparison> {
    results
        .iter()
        .flat_map(|result| result.comparisons.iter())
        .filter(|comparison| {
            comparison.mode == mode
                && comparison.family == family
                && comparison.replicate == replicate
                && comparison.control_slot == slot
        })
        .collect()
}

fn summarize(rows: &[&OComparison], horizon_index: usize) -> RunStats {
    let valid: Vec<_> = rows
        .iter()
        .filter_map(|comparison| {
            let horizon = comparison.horizons[horizon_index];
            horizon.valid.then_some((**comparison, horizon))
        })
        .collect();
    let divergence_rows: Vec<_> = rows
        .iter()
        .filter(|comparison| comparison.first_divergence_step > 0)
        .collect();
    RunStats {
        comparisons: rows.len(),
        valid: valid.len(),
        invalid_by_horizon: rows
            .iter()
            .filter(|comparison| {
                comparison.invalid_from_step > 0
                    && comparison.invalid_from_step <= OPEN_LOOP_HORIZONS[horizon_index]
            })
            .count(),
        mean_delta: valid
            .iter()
            .map(|(_, horizon)| f64::from(horizon.delta_train_loss))
            .sum::<f64>()
            / valid.len().max(1) as f64,
        g3_better_rate: rate(
            valid
                .iter()
                .filter(|(_, horizon)| horizon.delta_train_loss < -1.0e-7)
                .count(),
            valid.len(),
        ),
        first_divergences: divergence_rows.len(),
        block_divergences: divergence_rows
            .iter()
            .filter(|comparison| comparison.divergence_kind == 1)
            .count(),
        program_divergences: divergence_rows
            .iter()
            .filter(|comparison| comparison.divergence_kind == 2)
            .count(),
        mean_first_divergence: divergence_rows
            .iter()
            .map(|comparison| comparison.first_divergence_step as f64)
            .sum::<f64>()
            / divergence_rows.len().max(1) as f64,
        mean_g3_margin: divergence_rows
            .iter()
            .map(|comparison| f64::from(comparison.g3_margin_at_divergence))
            .sum::<f64>()
            / divergence_rows.len().max(1) as f64,
        mean_control_margin: divergence_rows
            .iter()
            .map(|comparison| f64::from(comparison.control_margin_at_divergence))
            .sum::<f64>()
            / divergence_rows.len().max(1) as f64,
    }
}

fn render_runs(results: &[OSeedSummary]) -> String {
    let mut out = String::from(
        "mode,stream,control_slot,horizon,comparisons,valid,invalid_by_horizon,mean_delta_train,g3_better_rate,first_divergences,block_divergences,program_divergences,mean_first_divergence_step,mean_g3_margin_at_divergence,mean_control_margin_at_divergence\n",
    );
    let groups = [(0, 0, 0), (0, 2, 0), (0, 2, 1), (1, 3, 0)];
    for (mode, family, replicate) in groups {
        for slot in 0..2_u8 {
            let rows = comparison_group(results, mode, family, replicate, slot);
            let stream = rows.first().map_or(
                if mode == 1 {
                    "frozen-base-original-stream"
                } else {
                    match (family, replicate) {
                        (0, 0) => "L0-original",
                        (2, 0) => "L2-shifted-17",
                        (2, 1) => "L2-shifted-36",
                        _ => "unknown",
                    }
                },
                |comparison| stream_name(comparison),
            );
            for (horizon_index, horizon) in OPEN_LOOP_HORIZONS.iter().enumerate() {
                let stats = summarize(&rows, horizon_index);
                writeln!(
                    out,
                    "{},{},control_{},{},{},{},{},{:.9},{:.6},{},{},{},{:.3},{:.9},{:.9}",
                    mode_name(mode),
                    stream,
                    if slot == 0 { 'a' } else { 'b' },
                    horizon,
                    stats.comparisons,
                    stats.valid,
                    stats.invalid_by_horizon,
                    stats.mean_delta,
                    stats.g3_better_rate,
                    stats.first_divergences,
                    stats.block_divergences,
                    stats.program_divergences,
                    stats.mean_first_divergence,
                    stats.mean_g3_margin,
                    stats.mean_control_margin,
                )
                .expect("String cannot fail");
            }
        }
    }
    out
}

fn render_snapshots(results: &[OSeedSummary]) -> String {
    let mut out = String::from(
        "seed,mode,stream,control_slot,global_commit,group_left,group_right,g3_delta_left,g3_delta_right,control_delta_left,control_delta_right,immediate_utility_gap,revisit_left_offset,revisit_right_offset,first_divergence_step,divergence_kind,g3_margin_at_divergence,control_margin_at_divergence,invalid_from_step,invalid_parameter,horizon,valid,g3_train_loss,control_train_loss,delta_train_loss,g3_validation_loss,control_validation_loss,parameter_distance\n",
    );
    for result in results {
        for comparison in &result.comparisons {
            for horizon in comparison.horizons {
                writeln!(
                    out,
                    "{:016x},{},{},control_{},{},{},{},{:.5},{:.5},{:.5},{:.5},{:.9},{},{},{},{},{:.9},{:.9},{},{},{},{},{:.9},{:.9},{:.9},{:.9},{:.9},{:.9}",
                    result.seed,
                    mode_name(comparison.mode),
                    stream_name(comparison),
                    if comparison.control_slot == 0 { 'a' } else { 'b' },
                    comparison.global_commit,
                    comparison.group_left,
                    comparison.group_right,
                    comparison.g3_delta_left,
                    comparison.g3_delta_right,
                    comparison.control_delta_left,
                    comparison.control_delta_right,
                    comparison.immediate_utility_gap,
                    comparison.revisit_left_offset,
                    comparison.revisit_right_offset,
                    comparison.first_divergence_step,
                    comparison.divergence_kind,
                    comparison.g3_margin_at_divergence,
                    comparison.control_margin_at_divergence,
                    comparison.invalid_from_step,
                    if comparison.invalid_parameter == usize::MAX { -1_i64 } else { comparison.invalid_parameter as i64 },
                    horizon.horizon,
                    horizon.valid,
                    horizon.g3_train_loss,
                    horizon.control_train_loss,
                    horizon.delta_train_loss,
                    horizon.g3_validation_loss,
                    horizon.control_validation_loss,
                    horizon.parameter_distance,
                )
                .expect("String cannot fail");
            }
        }
    }
    out
}

fn render_report(results: &[OSeedSummary]) -> String {
    let runs = render_runs(results);
    let mut out = String::from(
        "{\n  \"schema\": \"adaptive-runtime-ar-01o/v1\",\n  \"scope\": \"engineering-only\",\n  \"task\": \"three-class-spiral\",\n  \"protocol\": \"N2 same-block matched controls; O1 branch-specific closed-loop continuation reproduces L0 and L2 schedule phases 17/36; O2 applies the identical future committed-program sequence recorded from the unbranched original G3 base trajectory; O2 shadow selections are diagnostic only; frozen programs that violate either branch bounds invalidate the paired continuation from that step; no replacement action is used\",\n  \"seeds\": [\n",
    );
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(
            out,
            "    {{\"seed\":\"{:016x}\",\"final_train_loss\":{:.8},\"final_validation_loss\":{:.8},\"final_train_accuracy\":{:.6},\"final_validation_accuracy\":{:.6},\"selected_pair_snapshots\":{},\"matched_control_a\":{},\"matched_control_b\":{},\"comparisons\":{}}}",
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            result.selected_pair_snapshots,
            result.matched_control_a,
            result.matched_control_b,
            result.comparisons.len(),
        )
        .expect("String cannot fail");
    }
    out.push_str("\n  ],\n  \"summary_csv\": \"");
    for line in runs.lines().skip(1) {
        out.push_str(line);
        out.push_str("\\n");
    }
    out.push_str("\"\n}\n");
    out
}

fn main() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts = root.join("artifacts");
    fs::create_dir_all(&artifacts).expect("create artifacts directory");
    let dataset_path = artifacts.join("spiral-dataset.bin");
    write_dataset(&dataset_path).expect("write deterministic dataset");
    let dataset = MappedDataset::open(&dataset_path).expect("map deterministic dataset");
    let results = open_loop_diagnostic_all(dataset.samples());

    fs::write(
        artifacts.join("ar-01o-report.json"),
        render_report(&results),
    )
    .expect("write O report");
    fs::write(artifacts.join("ar-01o-runs.csv"), render_runs(&results))
        .expect("write O run summaries");
    fs::write(
        artifacts.join("ar-01o-snapshots.csv"),
        render_snapshots(&results),
    )
    .expect("write O snapshots");
    println!(
        "AR-01O complete: {} seed summaries, {} paired comparisons; artifacts at {}",
        results.len(),
        results
            .iter()
            .map(|result| result.comparisons.len())
            .sum::<usize>(),
        artifacts.display()
    );
}

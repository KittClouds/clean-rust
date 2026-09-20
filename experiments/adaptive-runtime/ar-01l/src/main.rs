use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_01l::{
    CONTINUATION_HORIZONS, CONTINUATION_SNAPSHOTS, CONTINUATION_STREAMS, ContinuationHorizon,
    ContinuationSnapshot, ContinuationSummary, MappedDataset, TOTAL_COMMITS,
    continuation_robustness_all, write_dataset,
};

#[derive(Clone, Copy, Debug, Default)]
struct PairClass {
    initial_control_better: bool,
    first_reversal_horizon: usize,
    persistent: bool,
    transient: bool,
    none: bool,
}

#[derive(Clone, Copy, Debug, Default)]
struct StreamStats {
    rows: usize,
    matched: usize,
    initial_control_better: usize,
    mean_delta: f64,
    g3_better_rate: f64,
    reversal_rate: f64,
    mean_distance: f64,
    persistent: usize,
    transient: usize,
    none: usize,
}

fn family_name(family: u8) -> &'static str {
    match family {
        0 => "L0-original",
        1 => "L1-new-evidence",
        2 => "L2-shifted-schedule",
        3 => "L3-new-evidence-and-schedule",
        _ => "unknown",
    }
}

fn control_present(snapshot: &ContinuationSnapshot, slot: usize) -> bool {
    if slot == 0 {
        snapshot.control_a.present
    } else {
        snapshot.control_b.present
    }
}

fn control_utility(snapshot: &ContinuationSnapshot, slot: usize) -> f32 {
    if slot == 0 {
        snapshot.control_a.utility
    } else {
        snapshot.control_b.utility
    }
}

fn delta(horizon: &ContinuationHorizon, slot: usize) -> f32 {
    if slot == 0 {
        horizon.g3_vs_control_a_train_delta
    } else {
        horizon.g3_vs_control_b_train_delta
    }
}

fn distance(horizon: &ContinuationHorizon, slot: usize) -> f32 {
    if slot == 0 {
        horizon.g3_control_a_parameter_distance
    } else {
        horizon.g3_control_b_parameter_distance
    }
}

fn class(snapshot: &ContinuationSnapshot, slot: usize) -> PairClass {
    if !control_present(snapshot, slot) {
        return PairClass::default();
    }
    let initial_control_better = control_utility(snapshot, slot) > snapshot.g3_utility + 1.0e-7;
    if !initial_control_better {
        return PairClass::default();
    }
    let first_reversal_horizon = snapshot
        .horizons
        .iter()
        .find(|horizon| delta(horizon, slot) < -1.0e-7)
        .map_or(0, |horizon| horizon.horizon);
    let persistent = first_reversal_horizon > 0
        && snapshot
            .horizons
            .iter()
            .filter(|horizon| horizon.horizon >= first_reversal_horizon)
            .all(|horizon| delta(horizon, slot) < -1.0e-7);
    PairClass {
        initial_control_better,
        first_reversal_horizon,
        persistent,
        transient: first_reversal_horizon > 0 && !persistent,
        none: first_reversal_horizon == 0,
    }
}

fn mean(values: impl Iterator<Item = f32>, count: usize) -> f64 {
    if count == 0 {
        0.0
    } else {
        values.map(f64::from).sum::<f64>() / count as f64
    }
}

fn rate(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
}

fn summarize(
    results: &[ContinuationSummary],
    family: u8,
    slot: usize,
    horizon_index: usize,
) -> StreamStats {
    let rows: Vec<&ContinuationSnapshot> = results
        .iter()
        .flat_map(|result| result.snapshots.iter())
        .filter(|snapshot| snapshot.family == family && control_present(snapshot, slot))
        .collect();
    let initial_control_better = rows
        .iter()
        .filter(|snapshot| class(snapshot, slot).initial_control_better)
        .count();
    let persistent = rows
        .iter()
        .filter(|snapshot| class(snapshot, slot).persistent)
        .count();
    let transient = rows
        .iter()
        .filter(|snapshot| class(snapshot, slot).transient)
        .count();
    let none = rows
        .iter()
        .filter(|snapshot| class(snapshot, slot).none)
        .count();
    StreamStats {
        rows: results
            .iter()
            .flat_map(|result| result.snapshots.iter())
            .filter(|snapshot| snapshot.family == family)
            .count(),
        matched: rows.len(),
        initial_control_better,
        mean_delta: mean(
            rows.iter()
                .map(|snapshot| delta(&snapshot.horizons[horizon_index], slot)),
            rows.len(),
        ),
        g3_better_rate: rate(
            rows.iter()
                .filter(|snapshot| delta(&snapshot.horizons[horizon_index], slot) < -1.0e-7)
                .count(),
            rows.len(),
        ),
        reversal_rate: rate(
            rows.iter()
                .filter(|snapshot| {
                    class(snapshot, slot).initial_control_better
                        && delta(&snapshot.horizons[horizon_index], slot) < -1.0e-7
                })
                .count(),
            initial_control_better,
        ),
        mean_distance: mean(
            rows.iter()
                .map(|snapshot| distance(&snapshot.horizons[horizon_index], slot)),
            rows.len(),
        ),
        persistent,
        transient,
        none,
    }
}

fn render_horizon(horizon: &ContinuationHorizon) -> String {
    format!(
        "{{\"horizon\":{},\"g3_train_loss\":{:.8},\"control_a_train_loss\":{:.8},\"control_b_train_loss\":{:.8},\"g3_validation_loss\":{:.8},\"control_a_validation_loss\":{:.8},\"control_b_validation_loss\":{:.8},\"g3_vs_control_a_train_delta\":{:.8},\"g3_vs_control_b_train_delta\":{:.8},\"g3_control_a_parameter_distance\":{:.8},\"g3_control_b_parameter_distance\":{:.8}}}",
        horizon.horizon,
        horizon.g3_train_loss,
        horizon.control_a_train_loss,
        horizon.control_b_train_loss,
        horizon.g3_validation_loss,
        horizon.control_a_validation_loss,
        horizon.control_b_validation_loss,
        horizon.g3_vs_control_a_train_delta,
        horizon.g3_vs_control_b_train_delta,
        horizon.g3_control_a_parameter_distance,
        horizon.g3_control_b_parameter_distance,
    )
}

fn render_snapshot(snapshot: &ContinuationSnapshot) -> String {
    format!(
        "{{\"family\":{},\"replicate\":{},\"global_commit\":{},\"g3_utility\":{:.8},\"g3_regret\":{:.8},\"control_a_utility\":{:.8},\"control_a_regret_gap\":{:.8},\"control_b_utility\":{:.8},\"control_b_regret_gap\":{:.8},\"control_a_present\":{},\"control_b_present\":{},\"horizons\":[{}]}}",
        snapshot.family,
        snapshot.replicate,
        snapshot.global_commit,
        snapshot.g3_utility,
        snapshot.g3_regret,
        snapshot.control_a.utility,
        snapshot.control_a.regret_gap,
        snapshot.control_b.utility,
        snapshot.control_b.regret_gap,
        snapshot.control_a.present,
        snapshot.control_b.present,
        snapshot
            .horizons
            .iter()
            .map(render_horizon)
            .collect::<Vec<_>>()
            .join(","),
    )
}

fn render_runs(results: &[ContinuationSummary]) -> String {
    let mut out = String::from(
        "family,control_slot,horizon,rows,matched,initial_control_better,mean_delta,g3_better_rate,reversal_rate,mean_parameter_distance,persistent_reversal,transient_reversal,no_reversal\n",
    );
    for family in 0..=3 {
        for slot in 0..2 {
            for (index, horizon) in CONTINUATION_HORIZONS.iter().enumerate() {
                let stats = summarize(results, family, slot, index);
                writeln!(
                    out,
                    "{},control_{},{},{},{},{},{:.8},{:.8},{:.8},{:.8},{},{},{}",
                    family_name(family),
                    if slot == 0 { 'a' } else { 'b' },
                    horizon,
                    stats.rows,
                    stats.matched,
                    stats.initial_control_better,
                    stats.mean_delta,
                    stats.g3_better_rate,
                    stats.reversal_rate,
                    stats.mean_distance,
                    stats.persistent,
                    stats.transient,
                    stats.none,
                )
                .expect("String cannot fail");
            }
        }
    }
    out
}

fn render_snapshots(results: &[ContinuationSummary]) -> String {
    let mut out = String::from(
        "seed,family,replicate,global_commit,control_slot,matched,g3_utility,g3_regret,control_utility,regret_gap,initial_control_better,first_reversal_horizon,persistent_reversal,transient_reversal,no_reversal,horizon,g3_train_loss,control_train_loss,g3_vs_control_train_delta,g3_validation_loss,control_validation_loss,g3_control_parameter_distance\n",
    );
    for result in results {
        for snapshot in &result.snapshots {
            for slot in 0..2 {
                let info = if slot == 0 {
                    snapshot.control_a
                } else {
                    snapshot.control_b
                };
                let classification = class(snapshot, slot);
                for horizon in &snapshot.horizons {
                    let control_train_loss = if slot == 0 {
                        horizon.control_a_train_loss
                    } else {
                        horizon.control_b_train_loss
                    };
                    let control_validation_loss = if slot == 0 {
                        horizon.control_a_validation_loss
                    } else {
                        horizon.control_b_validation_loss
                    };
                    writeln!(
                        out,
                        "{:016x},{},{},{},control_{},{},{:.8},{:.8},{:.8},{:.8},{},{},{},{},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8}",
                        result.seed,
                        family_name(snapshot.family),
                        snapshot.replicate,
                        snapshot.global_commit,
                        if slot == 0 { 'a' } else { 'b' },
                        info.present,
                        snapshot.g3_utility,
                        snapshot.g3_regret,
                        info.utility,
                        info.regret_gap,
                        classification.initial_control_better,
                        classification.first_reversal_horizon,
                        classification.persistent,
                        classification.transient,
                        classification.none,
                        horizon.horizon,
                        horizon.g3_train_loss,
                        control_train_loss,
                        if slot == 0 {
                            horizon.g3_vs_control_a_train_delta
                        } else {
                            horizon.g3_vs_control_b_train_delta
                        },
                        horizon.g3_validation_loss,
                        control_validation_loss,
                        if slot == 0 {
                            horizon.g3_control_a_parameter_distance
                        } else {
                            horizon.g3_control_b_parameter_distance
                        },
                    )
                    .expect("String cannot fail");
                }
            }
        }
    }
    out
}

fn render_report(results: &[ContinuationSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 300_000 + 1_000);
    out.push_str(
        "{\n  \"schema\": \"adaptive-runtime-ar-01l/v1\",\n  \"scope\": \"engineering-only\",\n  \"task\": \"three-class-spiral\",\n  \"protocol\": \"diagnostic-only continuation robustness audit using K matched-regret controls; L0 original stream; L1 new evidence with original schedule; L2 shifted schedule with original evidence; L3 new evidence and shifted schedule; two deterministic replicates for L1-L3; identical future within each paired continuation\",\n  \"results\": [\n",
    );
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        let summaries = (0..=3)
            .flat_map(|family| {
                (0..2).flat_map(move |slot| {
                    (0..CONTINUATION_HORIZONS.len()).map(move |horizon| {
                        let stats = summarize(std::slice::from_ref(result), family, slot, horizon);
                        format!(
                            "{{\"family\":\"{}\",\"control_slot\":\"{}\",\"horizon\":{},\"rows\":{},\"matched\":{},\"initial_control_better\":{},\"mean_delta\":{:.8},\"g3_better_rate\":{:.8},\"reversal_rate\":{:.8},\"mean_parameter_distance\":{:.8},\"persistent_reversal\":{},\"transient_reversal\":{},\"no_reversal\":{}}}",
                            family_name(family),
                            if slot == 0 { "a" } else { "b" },
                            CONTINUATION_HORIZONS[horizon],
                            stats.rows,
                            stats.matched,
                            stats.initial_control_better,
                            stats.mean_delta,
                            stats.g3_better_rate,
                            stats.reversal_rate,
                            stats.mean_distance,
                            stats.persistent,
                            stats.transient,
                            stats.none,
                        )
                    })
                })
            })
            .collect::<Vec<_>>();
        write!(
            out,
            "    {{\"seed\":{},\"final_train_loss\":{:.8},\"final_validation_loss\":{:.8},\"final_train_accuracy\":{:.8},\"final_validation_accuracy\":{:.8},\"summaries\":[{}],\"snapshots\":[{}]}}",
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            summaries.join(","),
            result
                .snapshots
                .iter()
                .map(render_snapshot)
                .collect::<Vec<_>>()
                .join(","),
        )
        .expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("spiral-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = continuation_robustness_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-01l-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-01l-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-01l-snapshots.csv"),
        render_snapshots(&results),
    )?;
    println!("AR-01L — continuation robustness");
    println!(
        "trajectory: G3 stratified-64, K matched controls, {} commits, {} snapshots/seed, {} continuation streams",
        TOTAL_COMMITS, CONTINUATION_SNAPSHOTS, CONTINUATION_STREAMS
    );
    println!(
        "dataset: {} samples (read-only mmap)",
        dataset.samples().len()
    );
    for family in 0..=3 {
        for slot in 0..2 {
            let stats = summarize(&results, family, slot, CONTINUATION_HORIZONS.len() - 1);
            println!(
                "{} control_{} h=64: rows={} matched={} initial_control_better={} mean_delta={:.6} G3_better={:.1}% reversal={:.1}% persistent={} transient={} none={}",
                family_name(family),
                if slot == 0 { 'a' } else { 'b' },
                stats.rows,
                stats.matched,
                stats.initial_control_better,
                stats.mean_delta,
                stats.g3_better_rate * 100.0,
                stats.reversal_rate * 100.0,
                stats.persistent,
                stats.transient,
                stats.none,
            );
        }
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

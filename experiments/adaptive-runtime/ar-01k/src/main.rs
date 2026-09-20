use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_01k::{
    MATCHED_HORIZONS, MATCHED_SNAPSHOTS, MappedDataset, MatchedControlInfo, MatchedHorizon,
    MatchedSnapshot, MatchedSummary, TOTAL_COMMITS, matched_control_all, write_dataset,
};

#[derive(Clone, Copy, Debug, Default)]
struct PairClassification {
    initial_control_better: bool,
    first_reversal_horizon: usize,
    persistent_reversal: bool,
    transient_reversal: bool,
    no_reversal: bool,
}

#[derive(Clone, Copy, Debug, Default)]
struct ControlHorizonStats {
    matched: usize,
    initial_control_better: usize,
    mean_delta: f64,
    g3_better_rate: f64,
    reversal_rate: f64,
    mean_parameter_distance: f64,
    mean_g3_train_loss: f64,
    mean_control_train_loss: f64,
    mean_g3_validation_loss: f64,
    mean_control_validation_loss: f64,
}

#[derive(Clone, Copy, Debug, Default)]
struct ControlStats {
    matched_snapshots: usize,
    initial_control_better: usize,
    initial_g3_better: usize,
    mean_regret_gap: f64,
    persistent_reversal: usize,
    transient_reversal: usize,
    no_reversal: usize,
    horizons: [ControlHorizonStats; 7],
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

fn control_info(snapshot: &MatchedSnapshot, slot: usize) -> MatchedControlInfo {
    if slot == 0 {
        snapshot.control_a
    } else {
        snapshot.control_b
    }
}

fn control_delta(horizon: &MatchedHorizon, slot: usize) -> f32 {
    if slot == 0 {
        horizon.g3_vs_control_a_train_delta
    } else {
        horizon.g3_vs_control_b_train_delta
    }
}

fn control_parameter_distance(horizon: &MatchedHorizon, slot: usize) -> f32 {
    if slot == 0 {
        horizon.g3_control_a_parameter_distance
    } else {
        horizon.g3_control_b_parameter_distance
    }
}

fn control_train_loss(horizon: &MatchedHorizon, slot: usize) -> f32 {
    if slot == 0 {
        horizon.control_a_train_loss
    } else {
        horizon.control_b_train_loss
    }
}

fn control_validation_loss(horizon: &MatchedHorizon, slot: usize) -> f32 {
    if slot == 0 {
        horizon.control_a_validation_loss
    } else {
        horizon.control_b_validation_loss
    }
}

fn classify(snapshot: &MatchedSnapshot, slot: usize) -> PairClassification {
    let info = control_info(snapshot, slot);
    if !info.present {
        return PairClassification::default();
    }
    let initial_control_better = info.utility > snapshot.g3_utility + 1.0e-7;
    if !initial_control_better {
        return PairClassification {
            initial_control_better,
            ..PairClassification::default()
        };
    }
    let first_reversal_horizon = snapshot
        .horizons
        .iter()
        .find(|horizon| control_delta(horizon, slot) < -1.0e-7)
        .map_or(0, |horizon| horizon.horizon);
    let persistent_reversal = first_reversal_horizon > 0
        && snapshot
            .horizons
            .iter()
            .filter(|horizon| horizon.horizon >= first_reversal_horizon)
            .all(|horizon| control_delta(horizon, slot) < -1.0e-7);
    let transient_reversal = first_reversal_horizon > 0 && !persistent_reversal;
    PairClassification {
        initial_control_better,
        first_reversal_horizon,
        persistent_reversal,
        transient_reversal,
        no_reversal: first_reversal_horizon == 0,
    }
}

fn summarize_control(result: &MatchedSummary, slot: usize) -> ControlStats {
    let matched: Vec<&MatchedSnapshot> = result
        .snapshots
        .iter()
        .filter(|snapshot| control_info(snapshot, slot).present)
        .collect();
    let mut stats = ControlStats {
        matched_snapshots: matched.len(),
        ..ControlStats::default()
    };
    for snapshot in &matched {
        let info = control_info(snapshot, slot);
        stats.mean_regret_gap += f64::from(info.regret_gap);
        let classification = classify(snapshot, slot);
        stats.initial_control_better += usize::from(classification.initial_control_better);
        stats.initial_g3_better += usize::from(info.utility + 1.0e-7 < snapshot.g3_utility);
        stats.persistent_reversal += usize::from(classification.persistent_reversal);
        stats.transient_reversal += usize::from(classification.transient_reversal);
        stats.no_reversal += usize::from(classification.no_reversal);
    }
    if stats.matched_snapshots > 0 {
        stats.mean_regret_gap /= stats.matched_snapshots as f64;
    }
    for (index, _) in MATCHED_HORIZONS.iter().enumerate() {
        let initial_control_better = matched
            .iter()
            .filter(|snapshot| classify(snapshot, slot).initial_control_better)
            .count();
        stats.horizons[index] = ControlHorizonStats {
            matched: matched.len(),
            initial_control_better,
            mean_delta: mean(
                matched
                    .iter()
                    .map(|snapshot| control_delta(&snapshot.horizons[index], slot)),
                matched.len(),
            ),
            g3_better_rate: rate(
                matched
                    .iter()
                    .filter(|snapshot| control_delta(&snapshot.horizons[index], slot) < -1.0e-7)
                    .count(),
                matched.len(),
            ),
            reversal_rate: rate(
                matched
                    .iter()
                    .filter(|snapshot| {
                        classify(snapshot, slot).initial_control_better
                            && control_delta(&snapshot.horizons[index], slot) < -1.0e-7
                    })
                    .count(),
                initial_control_better,
            ),
            mean_parameter_distance: mean(
                matched
                    .iter()
                    .map(|snapshot| control_parameter_distance(&snapshot.horizons[index], slot)),
                matched.len(),
            ),
            mean_g3_train_loss: mean(
                matched
                    .iter()
                    .map(|snapshot| snapshot.horizons[index].g3_train_loss),
                matched.len(),
            ),
            mean_control_train_loss: mean(
                matched
                    .iter()
                    .map(|snapshot| control_train_loss(&snapshot.horizons[index], slot)),
                matched.len(),
            ),
            mean_g3_validation_loss: mean(
                matched
                    .iter()
                    .map(|snapshot| snapshot.horizons[index].g3_validation_loss),
                matched.len(),
            ),
            mean_control_validation_loss: mean(
                matched
                    .iter()
                    .map(|snapshot| control_validation_loss(&snapshot.horizons[index], slot)),
                matched.len(),
            ),
        };
    }
    stats
}

fn render_control_info(info: MatchedControlInfo) -> String {
    format!(
        "{{\"present\":{},\"utility\":{:.8},\"regret\":{:.8},\"stratum\":{},\"regret_gap\":{:.8}}}",
        info.present, info.utility, info.regret, info.stratum, info.regret_gap
    )
}

fn render_classification(classification: PairClassification) -> String {
    format!(
        "{{\"initial_control_better\":{},\"first_reversal_horizon\":{},\"persistent_reversal\":{},\"transient_reversal\":{},\"no_reversal\":{}}}",
        classification.initial_control_better,
        classification.first_reversal_horizon,
        classification.persistent_reversal,
        classification.transient_reversal,
        classification.no_reversal,
    )
}

fn render_horizon(horizon: &MatchedHorizon) -> String {
    format!(
        "{{\"horizon\":{},\"g3_train_loss\":{:.8},\"greedy_train_loss\":{:.8},\"control_a_train_loss\":{:.8},\"control_b_train_loss\":{:.8},\"g3_validation_loss\":{:.8},\"greedy_validation_loss\":{:.8},\"control_a_validation_loss\":{:.8},\"control_b_validation_loss\":{:.8},\"g3_vs_greedy_train_delta\":{:.8},\"g3_vs_control_a_train_delta\":{:.8},\"g3_vs_control_b_train_delta\":{:.8},\"g3_greedy_parameter_distance\":{:.8},\"g3_control_a_parameter_distance\":{:.8},\"g3_control_b_parameter_distance\":{:.8}}}",
        horizon.horizon,
        horizon.g3_train_loss,
        horizon.greedy_train_loss,
        horizon.control_a_train_loss,
        horizon.control_b_train_loss,
        horizon.g3_validation_loss,
        horizon.greedy_validation_loss,
        horizon.control_a_validation_loss,
        horizon.control_b_validation_loss,
        horizon.g3_vs_greedy_train_delta,
        horizon.g3_vs_control_a_train_delta,
        horizon.g3_vs_control_b_train_delta,
        horizon.g3_greedy_parameter_distance,
        horizon.g3_control_a_parameter_distance,
        horizon.g3_control_b_parameter_distance,
    )
}

fn render_snapshot(snapshot: &MatchedSnapshot) -> String {
    format!(
        "{{\"global_commit\":{},\"selected_present\":{},\"g3_utility\":{:.8},\"g3_regret\":{:.8},\"greedy_utility\":{:.8},\"greedy_regret\":{:.8},\"g3_stratum\":{},\"control_a\":{},\"control_b\":{},\"control_a_classification\":{},\"control_b_classification\":{},\"horizons\":[{}]}}",
        snapshot.global_commit,
        snapshot.selected_present,
        snapshot.g3_utility,
        snapshot.g3_regret,
        snapshot.greedy_utility,
        snapshot.greedy_regret,
        snapshot.g3_stratum,
        render_control_info(snapshot.control_a),
        render_control_info(snapshot.control_b),
        render_classification(classify(snapshot, 0)),
        render_classification(classify(snapshot, 1)),
        snapshot
            .horizons
            .iter()
            .map(render_horizon)
            .collect::<Vec<_>>()
            .join(","),
    )
}

fn render_horizon_stats(stats: ControlHorizonStats) -> String {
    format!(
        "{{\"matched\":{},\"initial_control_better\":{},\"mean_delta\":{:.8},\"g3_better_rate\":{:.8},\"reversal_rate\":{:.8},\"mean_parameter_distance\":{:.8},\"mean_g3_train_loss\":{:.8},\"mean_control_train_loss\":{:.8},\"mean_g3_validation_loss\":{:.8},\"mean_control_validation_loss\":{:.8}}}",
        stats.matched,
        stats.initial_control_better,
        stats.mean_delta,
        stats.g3_better_rate,
        stats.reversal_rate,
        stats.mean_parameter_distance,
        stats.mean_g3_train_loss,
        stats.mean_control_train_loss,
        stats.mean_g3_validation_loss,
        stats.mean_control_validation_loss,
    )
}

fn render_control_stats(stats: ControlStats) -> String {
    format!(
        "{{\"matched_snapshots\":{},\"initial_control_better\":{},\"initial_g3_better\":{},\"mean_regret_gap\":{:.8},\"persistent_reversal\":{},\"transient_reversal\":{},\"no_reversal\":{},\"horizons\":[{}]}}",
        stats.matched_snapshots,
        stats.initial_control_better,
        stats.initial_g3_better,
        stats.mean_regret_gap,
        stats.persistent_reversal,
        stats.transient_reversal,
        stats.no_reversal,
        stats
            .horizons
            .iter()
            .copied()
            .map(render_horizon_stats)
            .collect::<Vec<_>>()
            .join(","),
    )
}

fn render_report(results: &[MatchedSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 90_000 + 1_000);
    out.push_str(
        "{\n  \"schema\": \"adaptive-runtime-ar-01k/v1\",\n  \"scope\": \"engineering-only\",\n  \"task\": \"three-class-spiral\",\n  \"protocol\": \"diagnostic-only matched-regret counterfactual audit; fixed G3 stratified-64 trajectory; same K2 candidate universe; two deterministic controls selected from the same utility-regret stratum within 5e-5 regret tolerance; identical future G3 stream; horizons 1,2,4,8,16,32,64; no counterfactual branch affects training\",\n  \"results\": [\n",
    );
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(
            out,
            "    {{\"seed\":{},\"final_train_loss\":{:.8},\"final_validation_loss\":{:.8},\"final_train_accuracy\":{:.8},\"final_validation_accuracy\":{:.8},\"control_a_summary\":{},\"control_b_summary\":{},\"snapshots\":[{}]}}",
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            render_control_stats(summarize_control(result, 0)),
            render_control_stats(summarize_control(result, 1)),
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

fn render_runs(results: &[MatchedSummary]) -> String {
    let mut out = String::from(
        "seed,control_slot,final_train_loss,final_validation_loss,final_train_accuracy,final_validation_accuracy,matched_snapshots,initial_control_better,initial_g3_better,mean_regret_gap,persistent_reversal,transient_reversal,no_reversal,horizon,matched,horizon_initial_control_better,mean_delta,g3_better_rate,reversal_rate,mean_parameter_distance,mean_g3_train_loss,mean_control_train_loss,mean_g3_validation_loss,mean_control_validation_loss\n",
    );
    for result in results {
        for slot in 0..2 {
            let summary = summarize_control(result, slot);
            for (index, horizon) in MATCHED_HORIZONS.iter().enumerate() {
                let stats = summary.horizons[index];
                writeln!(
                    out,
                    "{:016x},control_{},{:.8},{:.8},{:.8},{:.8},{},{},{},{:.8},{},{},{},{},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8}",
                    result.seed,
                    if slot == 0 { 'a' } else { 'b' },
                    result.final_train_loss,
                    result.final_validation_loss,
                    result.final_train_accuracy,
                    result.final_validation_accuracy,
                    summary.matched_snapshots,
                    summary.initial_control_better,
                    summary.initial_g3_better,
                    summary.mean_regret_gap,
                    summary.persistent_reversal,
                    summary.transient_reversal,
                    summary.no_reversal,
                    horizon,
                    stats.matched,
                    stats.initial_control_better,
                    stats.mean_delta,
                    stats.g3_better_rate,
                    stats.reversal_rate,
                    stats.mean_parameter_distance,
                    stats.mean_g3_train_loss,
                    stats.mean_control_train_loss,
                    stats.mean_g3_validation_loss,
                    stats.mean_control_validation_loss,
                )
                .expect("String cannot fail");
            }
        }
    }
    out
}

fn render_snapshots(results: &[MatchedSummary]) -> String {
    let mut out = String::from(
        "seed,global_commit,control_slot,matched,g3_stratum,g3_utility,g3_regret,control_utility,control_regret,regret_gap,initial_control_better,first_reversal_horizon,persistent_reversal,transient_reversal,no_reversal,horizon,g3_train_loss,control_train_loss,g3_vs_control_train_delta,g3_validation_loss,control_validation_loss,g3_control_parameter_distance,g3_vs_greedy_train_delta\n",
    );
    for result in results {
        for snapshot in &result.snapshots {
            for slot in 0..2 {
                let info = control_info(snapshot, slot);
                let classification = classify(snapshot, slot);
                for horizon in &snapshot.horizons {
                    writeln!(
                        out,
                        "{:016x},{},control_{},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{},{},{},{},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8}",
                        result.seed,
                        snapshot.global_commit,
                        if slot == 0 { 'a' } else { 'b' },
                        info.present,
                        snapshot.g3_stratum,
                        snapshot.g3_utility,
                        snapshot.g3_regret,
                        info.utility,
                        info.regret,
                        info.regret_gap,
                        classification.initial_control_better,
                        classification.first_reversal_horizon,
                        classification.persistent_reversal,
                        classification.transient_reversal,
                        classification.no_reversal,
                        horizon.horizon,
                        horizon.g3_train_loss,
                        control_train_loss(horizon, slot),
                        control_delta(horizon, slot),
                        horizon.g3_validation_loss,
                        control_validation_loss(horizon, slot),
                        control_parameter_distance(horizon, slot),
                        horizon.g3_vs_greedy_train_delta,
                    )
                    .expect("String cannot fail");
                }
            }
        }
    }
    out
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("spiral-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = matched_control_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-01k-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-01k-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-01k-snapshots.csv"),
        render_snapshots(&results),
    )?;
    println!("AR-01K — matched-regret counterfactual control");
    println!(
        "trajectory: G3 stratified-64, K2, {} commits, {} snapshots/seed",
        TOTAL_COMMITS, MATCHED_SNAPSHOTS
    );
    println!(
        "controls: two deterministic same-stratum candidates within {:.1e} immediate-regret tolerance; horizons {:?}",
        adaptive_runtime_ar_01k::MATCHED_REGRET_TOLERANCE,
        MATCHED_HORIZONS
    );
    println!(
        "dataset: {} samples (read-only mmap)",
        dataset.samples().len()
    );
    for result in &results {
        println!(
            "seed={:016x}: val_loss={:.6} val_acc={:.1}%",
            result.seed,
            result.final_validation_loss,
            result.final_validation_accuracy * 100.0,
        );
        for slot in 0..2 {
            let summary = summarize_control(result, slot);
            println!(
                "  control_{}: matched={} initial_control_better={} persistent={} transient={} no_reversal={} mean_regret_gap={:.6}",
                if slot == 0 { 'a' } else { 'b' },
                summary.matched_snapshots,
                summary.initial_control_better,
                summary.persistent_reversal,
                summary.transient_reversal,
                summary.no_reversal,
                summary.mean_regret_gap,
            );
            for (index, horizon) in MATCHED_HORIZONS.iter().enumerate() {
                let stats = summary.horizons[index];
                println!(
                    "    h={horizon}: mean_delta={:.6} G3_better={:.1}% reversal={:.1}% distance={:.6}",
                    stats.mean_delta,
                    stats.g3_better_rate * 100.0,
                    stats.reversal_rate * 100.0,
                    stats.mean_parameter_distance,
                );
            }
        }
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_01j::{
    COUNTERFACTUAL_HORIZONS, COUNTERFACTUAL_SNAPSHOTS, CounterfactualHorizon,
    CounterfactualSnapshot, CounterfactualSummary, MappedDataset, TOTAL_COMMITS,
    counterfactual_all, write_dataset,
};

#[derive(Clone, Copy, Debug, Default)]
struct HorizonStats {
    snapshots: usize,
    initial_inferior: usize,
    mean_delta_train_loss: f64,
    g3_better_rate: f64,
    reversal_rate: f64,
    mean_delta_best_opportunity: f64,
    g3_opportunity_better_rate: f64,
    mean_g3_train_loss: f64,
    mean_greedy_train_loss: f64,
    mean_g3_validation_loss: f64,
    mean_greedy_validation_loss: f64,
    mean_g3_best_opportunity: f64,
    mean_greedy_best_opportunity: f64,
    mean_g3_positive_blocks: f64,
    mean_greedy_positive_blocks: f64,
    mean_g3_harmful_blocks: f64,
    mean_greedy_harmful_blocks: f64,
    mean_g3_positive_utility: f64,
    mean_greedy_positive_utility: f64,
    mean_g3_median_positive_utility: f64,
    mean_greedy_median_positive_utility: f64,
}

fn mean(values: impl Iterator<Item = f32>, count: usize) -> f64 {
    if count == 0 {
        0.0
    } else {
        values.map(f64::from).sum::<f64>() / count as f64
    }
}

fn rate(values: impl Iterator<Item = bool>, count: usize) -> f64 {
    if count == 0 {
        0.0
    } else {
        values.filter(|value| *value).count() as f64 / count as f64
    }
}

fn summarize_horizon(result: &CounterfactualSummary, horizon_index: usize) -> HorizonStats {
    let rows: Vec<&CounterfactualSnapshot> = result
        .snapshots
        .iter()
        .filter(|snapshot| snapshot.selected_present)
        .collect();
    let values: Vec<&CounterfactualHorizon> = rows
        .iter()
        .map(|snapshot| &snapshot.horizons[horizon_index])
        .collect();
    let count = values.len();
    let initial_inferior = rows
        .iter()
        .filter(|snapshot| snapshot.initial_regret > 1.0e-7)
        .count();
    let initial_inferior_values = values
        .iter()
        .zip(rows.iter())
        .filter(|(_, snapshot)| snapshot.initial_regret > 1.0e-7)
        .map(|(horizon, _)| horizon.delta_train_loss);
    HorizonStats {
        snapshots: count,
        initial_inferior,
        mean_delta_train_loss: mean(values.iter().map(|horizon| horizon.delta_train_loss), count),
        g3_better_rate: rate(
            values
                .iter()
                .map(|horizon| horizon.delta_train_loss < -1.0e-7),
            count,
        ),
        reversal_rate: rate(
            initial_inferior_values.map(|delta| delta < -1.0e-7),
            initial_inferior,
        ),
        mean_delta_best_opportunity: mean(
            values.iter().map(|horizon| horizon.delta_best_opportunity),
            count,
        ),
        g3_opportunity_better_rate: rate(
            values
                .iter()
                .map(|horizon| horizon.delta_best_opportunity > 1.0e-7),
            count,
        ),
        mean_g3_train_loss: mean(values.iter().map(|horizon| horizon.g3_train_loss), count),
        mean_greedy_train_loss: mean(
            values.iter().map(|horizon| horizon.greedy_train_loss),
            count,
        ),
        mean_g3_validation_loss: mean(
            values.iter().map(|horizon| horizon.g3_validation_loss),
            count,
        ),
        mean_greedy_validation_loss: mean(
            values.iter().map(|horizon| horizon.greedy_validation_loss),
            count,
        ),
        mean_g3_best_opportunity: mean(
            values.iter().map(|horizon| horizon.g3_best_opportunity),
            count,
        ),
        mean_greedy_best_opportunity: mean(
            values.iter().map(|horizon| horizon.greedy_best_opportunity),
            count,
        ),
        mean_g3_positive_blocks: mean(
            values
                .iter()
                .map(|horizon| horizon.g3_positive_blocks as f32),
            count,
        ),
        mean_greedy_positive_blocks: mean(
            values
                .iter()
                .map(|horizon| horizon.greedy_positive_blocks as f32),
            count,
        ),
        mean_g3_harmful_blocks: mean(
            values
                .iter()
                .map(|horizon| horizon.g3_harmful_blocks as f32),
            count,
        ),
        mean_greedy_harmful_blocks: mean(
            values
                .iter()
                .map(|horizon| horizon.greedy_harmful_blocks as f32),
            count,
        ),
        mean_g3_positive_utility: mean(
            values
                .iter()
                .map(|horizon| horizon.g3_mean_positive_utility),
            count,
        ),
        mean_greedy_positive_utility: mean(
            values
                .iter()
                .map(|horizon| horizon.greedy_mean_positive_utility),
            count,
        ),
        mean_g3_median_positive_utility: mean(
            values
                .iter()
                .map(|horizon| horizon.g3_median_positive_utility),
            count,
        ),
        mean_greedy_median_positive_utility: mean(
            values
                .iter()
                .map(|horizon| horizon.greedy_median_positive_utility),
            count,
        ),
    }
}

fn render_horizon_stats(stats: HorizonStats) -> String {
    format!(
        "{{\"snapshots\":{},\"initial_inferior\":{},\"mean_delta_train_loss\":{:.8},\"g3_better_rate\":{:.8},\"reversal_rate\":{:.8},\"mean_delta_best_opportunity\":{:.8},\"g3_opportunity_better_rate\":{:.8},\"mean_g3_train_loss\":{:.8},\"mean_greedy_train_loss\":{:.8},\"mean_g3_validation_loss\":{:.8},\"mean_greedy_validation_loss\":{:.8},\"mean_g3_best_opportunity\":{:.8},\"mean_greedy_best_opportunity\":{:.8},\"mean_g3_positive_blocks\":{:.8},\"mean_greedy_positive_blocks\":{:.8},\"mean_g3_harmful_blocks\":{:.8},\"mean_greedy_harmful_blocks\":{:.8},\"mean_g3_positive_utility\":{:.8},\"mean_greedy_positive_utility\":{:.8},\"mean_g3_median_positive_utility\":{:.8},\"mean_greedy_median_positive_utility\":{:.8}}}",
        stats.snapshots,
        stats.initial_inferior,
        stats.mean_delta_train_loss,
        stats.g3_better_rate,
        stats.reversal_rate,
        stats.mean_delta_best_opportunity,
        stats.g3_opportunity_better_rate,
        stats.mean_g3_train_loss,
        stats.mean_greedy_train_loss,
        stats.mean_g3_validation_loss,
        stats.mean_greedy_validation_loss,
        stats.mean_g3_best_opportunity,
        stats.mean_greedy_best_opportunity,
        stats.mean_g3_positive_blocks,
        stats.mean_greedy_positive_blocks,
        stats.mean_g3_harmful_blocks,
        stats.mean_greedy_harmful_blocks,
        stats.mean_g3_positive_utility,
        stats.mean_greedy_positive_utility,
        stats.mean_g3_median_positive_utility,
        stats.mean_greedy_median_positive_utility,
    )
}

fn render_horizon(horizon: &CounterfactualHorizon) -> String {
    format!(
        "{{\"horizon\":{},\"g3_train_loss\":{:.8},\"greedy_train_loss\":{:.8},\"delta_train_loss\":{:.8},\"g3_validation_loss\":{:.8},\"greedy_validation_loss\":{:.8},\"g3_best_opportunity\":{:.8},\"greedy_best_opportunity\":{:.8},\"delta_best_opportunity\":{:.8},\"g3_positive_blocks\":{},\"greedy_positive_blocks\":{},\"g3_harmful_blocks\":{},\"greedy_harmful_blocks\":{},\"g3_mean_positive_utility\":{:.8},\"greedy_mean_positive_utility\":{:.8},\"g3_median_positive_utility\":{:.8},\"greedy_median_positive_utility\":{:.8}}}",
        horizon.horizon,
        horizon.g3_train_loss,
        horizon.greedy_train_loss,
        horizon.delta_train_loss,
        horizon.g3_validation_loss,
        horizon.greedy_validation_loss,
        horizon.g3_best_opportunity,
        horizon.greedy_best_opportunity,
        horizon.delta_best_opportunity,
        horizon.g3_positive_blocks,
        horizon.greedy_positive_blocks,
        horizon.g3_harmful_blocks,
        horizon.greedy_harmful_blocks,
        horizon.g3_mean_positive_utility,
        horizon.greedy_mean_positive_utility,
        horizon.g3_median_positive_utility,
        horizon.greedy_median_positive_utility,
    )
}

fn render_snapshot(snapshot: &CounterfactualSnapshot) -> String {
    format!(
        "{{\"global_commit\":{},\"selected_present\":{},\"g3_initial_utility\":{:.8},\"greedy_initial_utility\":{:.8},\"initial_regret\":{:.8},\"g3_initial_harmful\":{},\"horizons\":[{}]}}",
        snapshot.global_commit,
        snapshot.selected_present,
        snapshot.g3_initial_utility,
        snapshot.greedy_initial_utility,
        snapshot.initial_regret,
        snapshot.g3_initial_harmful,
        snapshot
            .horizons
            .iter()
            .map(render_horizon)
            .collect::<Vec<_>>()
            .join(","),
    )
}

fn render_report(results: &[CounterfactualSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 50_000 + 1_000);
    out.push_str(
        "{\n  \"schema\": \"adaptive-runtime-ar-01j/v1\",\n  \"scope\": \"engineering-only\",\n  \"task\": \"three-class-spiral\",\n  \"protocol\": \"diagnostic-only short-horizon counterfactual audit of fixed G3 stratified-64 trajectories; K2 shortlist; full-96 immediate-best first action; identical deterministic future G3 stream; horizons 1,2,4,8,16,32,64 commits; no counterfactual branch affects training\",\n  \"results\": [\n",
    );
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        let summaries = COUNTERFACTUAL_HORIZONS
            .iter()
            .enumerate()
            .map(|(index, _)| render_horizon_stats(summarize_horizon(result, index)))
            .collect::<Vec<_>>();
        write!(
            out,
            "    {{\"seed\":{},\"final_train_loss\":{:.8},\"final_validation_loss\":{:.8},\"final_train_accuracy\":{:.8},\"final_validation_accuracy\":{:.8},\"horizons\":[{}],\"snapshots\":[{}]}}",
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

fn render_runs(results: &[CounterfactualSummary]) -> String {
    let mut out = String::from(
        "seed,final_train_loss,final_validation_loss,final_train_accuracy,final_validation_accuracy,horizon,snapshots,initial_inferior,mean_delta_train_loss,g3_better_rate,reversal_rate,mean_delta_best_opportunity,g3_opportunity_better_rate,mean_g3_train_loss,mean_greedy_train_loss,mean_g3_validation_loss,mean_greedy_validation_loss,mean_g3_best_opportunity,mean_greedy_best_opportunity,mean_g3_positive_blocks,mean_greedy_positive_blocks,mean_g3_harmful_blocks,mean_greedy_harmful_blocks,mean_g3_positive_utility,mean_greedy_positive_utility,mean_g3_median_positive_utility,mean_greedy_median_positive_utility\n",
    );
    for result in results {
        for (index, horizon) in COUNTERFACTUAL_HORIZONS.iter().enumerate() {
            let stats = summarize_horizon(result, index);
            writeln!(
                out,
                "{:016x},{:.8},{:.8},{:.8},{:.8},{},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8}",
                result.seed,
                result.final_train_loss,
                result.final_validation_loss,
                result.final_train_accuracy,
                result.final_validation_accuracy,
                horizon,
                stats.snapshots,
                stats.initial_inferior,
                stats.mean_delta_train_loss,
                stats.g3_better_rate,
                stats.reversal_rate,
                stats.mean_delta_best_opportunity,
                stats.g3_opportunity_better_rate,
                stats.mean_g3_train_loss,
                stats.mean_greedy_train_loss,
                stats.mean_g3_validation_loss,
                stats.mean_greedy_validation_loss,
                stats.mean_g3_best_opportunity,
                stats.mean_greedy_best_opportunity,
                stats.mean_g3_positive_blocks,
                stats.mean_greedy_positive_blocks,
                stats.mean_g3_harmful_blocks,
                stats.mean_greedy_harmful_blocks,
                stats.mean_g3_positive_utility,
                stats.mean_greedy_positive_utility,
                stats.mean_g3_median_positive_utility,
                stats.mean_greedy_median_positive_utility,
            )
            .expect("String cannot fail");
        }
    }
    out
}

fn render_snapshots(results: &[CounterfactualSummary]) -> String {
    let mut out = String::from(
        "seed,global_commit,selected_present,g3_initial_utility,greedy_initial_utility,initial_regret,g3_initial_harmful,horizon,g3_train_loss,greedy_train_loss,delta_train_loss,g3_validation_loss,greedy_validation_loss,g3_best_opportunity,greedy_best_opportunity,delta_best_opportunity,g3_positive_blocks,greedy_positive_blocks,g3_harmful_blocks,greedy_harmful_blocks,g3_mean_positive_utility,greedy_mean_positive_utility,g3_median_positive_utility,greedy_median_positive_utility\n",
    );
    for result in results {
        for snapshot in &result.snapshots {
            for horizon in &snapshot.horizons {
                writeln!(
                    out,
                    "{:016x},{},{},{:.8},{:.8},{:.8},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{},{},{},{},{:.8},{:.8},{:.8},{:.8}",
                    result.seed,
                    snapshot.global_commit,
                    snapshot.selected_present,
                    snapshot.g3_initial_utility,
                    snapshot.greedy_initial_utility,
                    snapshot.initial_regret,
                    snapshot.g3_initial_harmful,
                    horizon.horizon,
                    horizon.g3_train_loss,
                    horizon.greedy_train_loss,
                    horizon.delta_train_loss,
                    horizon.g3_validation_loss,
                    horizon.greedy_validation_loss,
                    horizon.g3_best_opportunity,
                    horizon.greedy_best_opportunity,
                    horizon.delta_best_opportunity,
                    horizon.g3_positive_blocks,
                    horizon.greedy_positive_blocks,
                    horizon.g3_harmful_blocks,
                    horizon.greedy_harmful_blocks,
                    horizon.g3_mean_positive_utility,
                    horizon.greedy_mean_positive_utility,
                    horizon.g3_median_positive_utility,
                    horizon.greedy_median_positive_utility,
                )
                .expect("String cannot fail");
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
    let results = counterfactual_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-01j-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-01j-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-01j-snapshots.csv"),
        render_snapshots(&results),
    )?;
    println!("AR-01J — short-horizon counterfactual value");
    println!(
        "trajectory: G3 stratified-64, K2, {} commits, {} snapshots/seed",
        TOTAL_COMMITS, COUNTERFACTUAL_SNAPSHOTS
    );
    println!(
        "counterfactual horizons: {:?}; branches: G3-selected first action vs full-96 immediate-best first action, then identical G3 stream",
        COUNTERFACTUAL_HORIZONS
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
        for (index, horizon) in COUNTERFACTUAL_HORIZONS.iter().enumerate() {
            let stats = summarize_horizon(result, index);
            println!(
                "  h={horizon}: mean_delta={:.6} G3_better={:.1}% reversal={:.1}% opp_delta={:.6} opp_better={:.1}%",
                stats.mean_delta_train_loss,
                stats.g3_better_rate * 100.0,
                stats.reversal_rate * 100.0,
                stats.mean_delta_best_opportunity,
                stats.g3_opportunity_better_rate * 100.0,
            );
        }
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

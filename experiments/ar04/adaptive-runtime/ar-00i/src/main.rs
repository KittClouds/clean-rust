use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00i::{CurvePoint, RunSummary, ShadowSummary, run_all, shadow_audit};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    let shadow = shadow_audit(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00i-report.json"),
        render_report(&results, &shadow),
    )?;
    fs::write(artifact_dir.join("ar-00i-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-00i-curves.csv"),
        render_curves(&results),
    )?;
    fs::write(
        artifact_dir.join("ar-00i-shadow.csv"),
        render_shadow(&shadow),
    )?;
    println!("AR-00I — Approximate Interaction Residual");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        let t = result.telemetry;
        println!(
            "{} seed={:016x}: loss={:.8} accuracy={:.2}% evals={} pair_events={} predicted={:.6} realized={:.6}",
            result.arm.label(),
            result.seed,
            result.final_loss,
            result.final_accuracy * 100.0,
            t.utility_evaluations,
            t.pair_events,
            t.predicted_utility,
            t.realized_utility
        );
    }
    println!("shadow rows: {}", shadow.len());
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[RunSummary], shadow: &[ShadowSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 500 + shadow.len() * 300 + 500);
    out.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00i/v1\",\n  \"scope\": \"engineering-only\",\n  \"width\": 2,\n  \"epochs\": 3000,\n  \"results\": [\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(out, "    {{\"arm\":\"{}\",\"seed\":{},\"final_loss\":{:.8},\"final_accuracy\":{:.8},\"final_mse\":{:.8},\"selected_primitives\":{},\"programs\":{},\"utility_evaluations\":{},\"pair_events\":{},\"ever_covered_fraction\":{:.8},\"time_to_full_coverage\":{}}}", result.arm.label(), result.seed, result.final_loss, result.final_accuracy, result.final_mse, result.telemetry.selected_primitives, result.telemetry.programs, result.telemetry.utility_evaluations, result.telemetry.pair_events, result.coverage.ever_covered_fraction, result.coverage.time_to_full_coverage.map_or_else(|| "null".to_string(), |v| v.to_string())).expect("String cannot fail");
    }
    out.push_str("\n  ],\n  \"shadow\": [\n");
    for (index, item) in shadow.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(out, "    {{\"arm\":\"{}\",\"seed\":{},\"groups\":{},\"top_choice_agreement\":{:.8},\"improving_fraction\":{:.8},\"mean_exact_regret\":{:.8},\"max_exact_regret\":{:.8},\"utility_evaluations\":{}}}", item.arm.label(), item.seed, item.groups, item.top_choice_agreement, item.improving_fraction, item.mean_exact_regret, item.max_exact_regret, item.utility_evaluations).expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

fn render_runs(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 240 + 300);
    out.push_str("arm,seed,final_loss,final_accuracy,final_mse,selected_primitives,programs,utility_evaluations,pair_events,ever_covered_fraction,time_to_full_coverage\n");
    for result in results {
        writeln!(
            out,
            "{},{:016x},{:.8},{:.8},{:.8},{},{},{},{},{:.8},{}",
            result.arm.label(),
            result.seed,
            result.final_loss,
            result.final_accuracy,
            result.final_mse,
            result.telemetry.selected_primitives,
            result.telemetry.programs,
            result.telemetry.utility_evaluations,
            result.telemetry.pair_events,
            result.coverage.ever_covered_fraction,
            result
                .coverage
                .time_to_full_coverage
                .map_or_else(String::new, |v| v.to_string())
        )
        .expect("String cannot fail");
    }
    out
}

fn render_curves(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 3_000 * 100);
    out.push_str("arm,seed,epoch,loss_before,loss_after,accuracy_after,selected_primitives,programs,utility_evaluations\n");
    for result in results {
        for point in &result.curve {
            write_curve(&mut out, result, point);
        }
    }
    out
}

fn write_curve(out: &mut String, result: &RunSummary, point: &CurvePoint) {
    writeln!(
        out,
        "{},{:016x},{},{:.8},{:.8},{:.8},{},{},{}",
        result.arm.label(),
        result.seed,
        point.epoch,
        point.loss_before,
        point.loss_after,
        point.accuracy_after,
        point.selected_primitives,
        point.programs,
        point.utility_evaluations
    )
    .expect("String cannot fail");
}

fn render_shadow(shadow: &[ShadowSummary]) -> String {
    let mut out = String::with_capacity(shadow.len() * 220 + 300);
    out.push_str("arm,seed,groups,top_choice_agreement,improving_fraction,mean_exact_regret,max_exact_regret,utility_evaluations\n");
    for item in shadow {
        writeln!(
            out,
            "{},{:016x},{},{:.8},{:.8},{:.8},{:.8},{}",
            item.arm.label(),
            item.seed,
            item.groups,
            item.top_choice_agreement,
            item.improving_fraction,
            item.mean_exact_regret,
            item.max_exact_regret,
            item.utility_evaluations
        )
        .expect("String cannot fail");
    }
    out
}

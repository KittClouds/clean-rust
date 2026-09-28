use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00j::{
    CurvePoint, OnPolicySummary, RunSummary, on_policy_audit_all, run_all,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    let on_policy = on_policy_audit_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00j-report.json"),
        render_report(&results, &on_policy),
    )?;
    fs::write(artifact_dir.join("ar-00j-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-00j-curves.csv"),
        render_curves(&results),
    )?;
    fs::write(
        artifact_dir.join("ar-00j-on-policy.csv"),
        render_on_policy(&on_policy),
    )?;
    println!("AR-00J — On-Policy Fidelity");
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
    println!("on-policy rows: {}", on_policy.len());
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[RunSummary], on_policy: &[OnPolicySummary]) -> String {
    let mut out = String::with_capacity(results.len() * 500 + on_policy.len() * 600 + 500);
    out.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00j/v1\",\n  \"scope\": \"engineering-only\",\n  \"width\": 2,\n  \"epochs\": 3000,\n  \"results\": [\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(out, "    {{\"arm\":\"{}\",\"seed\":{},\"final_loss\":{:.8},\"final_accuracy\":{:.8},\"final_mse\":{:.8},\"selected_primitives\":{},\"programs\":{},\"utility_evaluations\":{},\"pair_events\":{},\"ever_covered_fraction\":{:.8},\"time_to_full_coverage\":{}}}", result.arm.label(), result.seed, result.final_loss, result.final_accuracy, result.final_mse, result.telemetry.selected_primitives, result.telemetry.programs, result.telemetry.utility_evaluations, result.telemetry.pair_events, result.coverage.ever_covered_fraction, result.coverage.time_to_full_coverage.map_or_else(|| "null".to_string(), |v| v.to_string())).expect("String cannot fail");
    }
    out.push_str("\n  ],\n  \"on_policy\": [\n");
    for (index, item) in on_policy.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(out, "    {{\"arm\":\"{}\",\"seed\":{},\"groups\":{},\"ranked_groups\":{},\"top_choice_agreement\":{:.8},\"improving_fraction\":{:.8},\"mean_exact_regret\":{:.8},\"max_exact_regret\":{:.8},\"mean_selected_exact_rank\":{:.8},\"utility_correlation\":{:.8},\"utility_bias\":{:.8},\"utility_mae\":{:.8},\"sign_error_fraction\":{:.8},\"cross_block_order_accuracy\":{:.8},\"first_choice_divergence_epoch\":{},\"first_large_regret_epoch\":{},\"final_loss_gap\":{:.8},\"final_parameter_l2\":{:.8},\"cumulative_exact_regret\":{:.8}}}", item.arm.label(), item.seed, item.groups, item.ranked_groups, item.top_choice_agreement, item.improving_fraction, item.mean_exact_regret, item.max_exact_regret, item.mean_selected_exact_rank, item.utility_correlation, item.utility_bias, item.utility_mae, item.sign_error_fraction, item.cross_block_order_accuracy, item.first_choice_divergence_epoch.map_or_else(|| "null".to_string(), |v| v.to_string()), item.first_large_regret_epoch.map_or_else(|| "null".to_string(), |v| v.to_string()), item.final_loss_gap, item.final_parameter_l2, item.cumulative_exact_regret).expect("String cannot fail");
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

fn render_on_policy(on_policy: &[OnPolicySummary]) -> String {
    let mut out = String::with_capacity(on_policy.len() * 560 + 500);
    out.push_str("arm,seed,groups,ranked_groups,top_choice_agreement,improving_fraction,mean_exact_regret,max_exact_regret,mean_selected_exact_rank,utility_correlation,utility_bias,utility_mae,sign_error_fraction,cross_block_order_accuracy,first_choice_divergence_epoch,first_large_regret_epoch,final_loss_gap,final_parameter_l2,cumulative_exact_regret\n");
    for item in on_policy {
        writeln!(out, "{},{:016x},{},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{},{},{:.8},{:.8},{:.8}", item.arm.label(), item.seed, item.groups, item.ranked_groups, item.top_choice_agreement, item.improving_fraction, item.mean_exact_regret, item.max_exact_regret, item.mean_selected_exact_rank, item.utility_correlation, item.utility_bias, item.utility_mae, item.sign_error_fraction, item.cross_block_order_accuracy, item.first_choice_divergence_epoch.map_or_else(String::new, |v| v.to_string()), item.first_large_regret_epoch.map_or_else(String::new, |v| v.to_string()), item.final_loss_gap, item.final_parameter_l2, item.cumulative_exact_regret).expect("String cannot fail");
    }
    out
}

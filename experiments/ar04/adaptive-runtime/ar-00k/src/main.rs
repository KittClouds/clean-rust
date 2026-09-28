use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00k::{AuditSummary, CurvePoint, RunSummary, audit_all, run_all};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    let audit = audit_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00k-report.json"),
        render_report(&results, &audit),
    )?;
    fs::write(artifact_dir.join("ar-00k-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-00k-curves.csv"),
        render_curves(&results),
    )?;
    fs::write(artifact_dir.join("ar-00k-audit.csv"), render_audit(&audit))?;
    println!("AR-00K — Minimal Exact Beam");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        let t = result.telemetry;
        println!(
            "{} seed={:016x}: loss={:.8} accuracy={:.2}% proposal={} compound={} total={} pair_events={}",
            result.arm.label(),
            result.seed,
            result.final_loss,
            result.final_accuracy * 100.0,
            t.proposal_evaluations,
            t.compound_evaluations,
            t.utility_evaluations,
            t.pair_events,
        );
    }
    println!("audit rows: {}", audit.len());
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[RunSummary], audit: &[AuditSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 700 + audit.len() * 650 + 1_000);
    out.push_str(
        "{\n  \"schema\": \"adaptive-runtime-ar-00k/v1\",\n  \"scope\": \"engineering-only\",\n  \"width\": 2,\n  \"protocol\": \"K0 exhaustive 11x11; K1-K5 top-k x top-k exact verification; three frozen seeds\",\n  \"results\": [\n",
    );
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(
            out,
            "    {{\"arm\":\"{}\",\"seed\":{},\"final_loss\":{:.8},\"final_accuracy\":{:.8},\"final_mse\":{:.8},\"selected_primitives\":{},\"programs\":{},\"proposal_evaluations\":{},\"compound_evaluations\":{},\"utility_evaluations\":{},\"pair_events\":{},\"ever_covered_fraction\":{:.8},\"time_to_full_coverage\":{}}}",
            result.arm.label(), result.seed, result.final_loss, result.final_accuracy,
            result.final_mse, result.telemetry.selected_primitives, result.telemetry.programs,
            result.telemetry.proposal_evaluations, result.telemetry.compound_evaluations,
            result.telemetry.utility_evaluations, result.telemetry.pair_events,
            result.coverage.ever_covered_fraction,
            result.coverage.time_to_full_coverage.map_or_else(|| "null".to_string(), |v| v.to_string()),
        ).expect("String cannot fail");
    }
    out.push_str("\n  ],\n  \"audit\": [\n");
    for (index, item) in audit.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(
            out,
            "    {{\"arm\":\"{}\",\"seed\":{},\"groups\":{},\"top_compound_agreement\":{:.8},\"shortlist_recall\":{:.8},\"mean_exact_regret\":{:.8},\"max_exact_regret\":{:.8},\"cumulative_exact_regret\":{:.8},\"mean_block_value_error\":{:.8},\"cross_block_order_accuracy\":{:.8},\"inversion_count\":{},\"margin_weighted_order_regret\":{:.8},\"near_tie_inversion_fraction\":{:.8},\"shortlist_failures\":{},\"scheduler_failures\":{},\"first_divergence_epoch\":{}}}",
            item.arm.label(), item.seed, item.groups, item.top_compound_agreement,
            item.shortlist_recall, item.mean_exact_regret, item.max_exact_regret,
            item.cumulative_exact_regret, item.mean_block_value_error,
            item.cross_block_order_accuracy, item.inversion_count,
            item.margin_weighted_order_regret, item.near_tie_inversion_fraction,
            item.shortlist_failures, item.scheduler_failures,
            item.first_divergence_epoch.map_or_else(|| "null".to_string(), |v| v.to_string()),
        ).expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

fn render_runs(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 300 + 400);
    out.push_str("arm,seed,final_loss,final_accuracy,final_mse,selected_primitives,programs,proposal_evaluations,compound_evaluations,utility_evaluations,pair_events,ever_covered_fraction,time_to_full_coverage\n");
    for result in results {
        writeln!(
            out,
            "{},{:016x},{:.8},{:.8},{:.8},{},{},{},{},{},{},{:.8},{}",
            result.arm.label(),
            result.seed,
            result.final_loss,
            result.final_accuracy,
            result.final_mse,
            result.telemetry.selected_primitives,
            result.telemetry.programs,
            result.telemetry.proposal_evaluations,
            result.telemetry.compound_evaluations,
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
    let mut out = String::with_capacity(results.len() * 3_000 * 120);
    out.push_str("arm,seed,epoch,loss_before,loss_after,accuracy_after,selected_primitives,programs,proposal_evaluations,compound_evaluations,utility_evaluations\n");
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
        "{},{:016x},{},{:.8},{:.8},{:.8},{},{},{},{},{}",
        result.arm.label(),
        result.seed,
        point.epoch,
        point.loss_before,
        point.loss_after,
        point.accuracy_after,
        point.selected_primitives,
        point.programs,
        point.proposal_evaluations,
        point.compound_evaluations,
        point.utility_evaluations
    )
    .expect("String cannot fail");
}

fn render_audit(audit: &[AuditSummary]) -> String {
    let mut out = String::with_capacity(audit.len() * 360 + 300);
    out.push_str("arm,seed,groups,top_compound_agreement,shortlist_recall,mean_exact_regret,max_exact_regret,cumulative_exact_regret,mean_block_value_error,cross_block_order_accuracy,inversion_count,margin_weighted_order_regret,near_tie_inversion_fraction,shortlist_failures,scheduler_failures,first_divergence_epoch\n");
    for item in audit {
        writeln!(
            out,
            "{},{:016x},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{},{:.8},{:.8},{},{},{}",
            item.arm.label(),
            item.seed,
            item.groups,
            item.top_compound_agreement,
            item.shortlist_recall,
            item.mean_exact_regret,
            item.max_exact_regret,
            item.cumulative_exact_regret,
            item.mean_block_value_error,
            item.cross_block_order_accuracy,
            item.inversion_count,
            item.margin_weighted_order_regret,
            item.near_tie_inversion_fraction,
            item.shortlist_failures,
            item.scheduler_failures,
            item.first_divergence_epoch
                .map_or_else(String::new, |v| v.to_string())
        )
        .expect("String cannot fail");
    }
    out
}

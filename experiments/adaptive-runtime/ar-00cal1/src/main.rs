use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00cal1::{CalibrationReport, calibration_audit_all};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let report = calibration_audit_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00cal1-opportunities.csv"),
        render_opportunities(&report),
    )?;
    fs::write(
        artifact_dir.join("ar-00cal1-summary.csv"),
        render_summary(&report),
    )?;
    fs::write(
        artifact_dir.join("ar-00cal1-report.json"),
        render_json(&report),
    )?;
    println!("AR-00J-CAL1 — Cross-block Calibration Audit");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for summary in &report.summaries {
        println!(
            "{} seed={:016x}: corr={:.5} alpha={:.5} beta={:.6} order={:.3} inversions={} weighted_regret={:.6} first_inversion={:?}",
            summary.arm.label(),
            summary.seed,
            summary.correlation,
            summary.alpha,
            summary.beta,
            summary.cross_block_order_accuracy,
            summary.inversion_count,
            summary.margin_weighted_inversion_regret,
            summary.first_inversion_epoch
        );
    }
    println!("opportunity rows: {}", report.rows.len());
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_opportunities(report: &CalibrationReport) -> String {
    let mut out = String::with_capacity(report.rows.len() * 180 + 300);
    out.push_str("arm,seed,epoch,left,right,exact_block_value,approximate_block_value,selected_actual_value,exact_regret\n");
    for row in &report.rows {
        writeln!(
            out,
            "{},{:016x},{},{},{},{:.8},{:.8},{:.8},{:.8}",
            row.arm.label(),
            row.seed,
            row.epoch,
            row.left,
            row.right,
            row.exact_block_value,
            row.approximate_block_value,
            row.selected_actual_value,
            row.exact_regret
        )
        .expect("String cannot fail");
    }
    out
}

fn render_summary(report: &CalibrationReport) -> String {
    let mut out = String::with_capacity(report.summaries.len() * 300 + 400);
    out.push_str("arm,seed,rows,alpha,beta,correlation,bias,mae,mean_relative_error,cross_block_order_accuracy,inversion_count,margin_weighted_inversion_regret,near_tie_inversion_fraction,first_inversion_epoch\n");
    for item in &report.summaries {
        writeln!(
            out,
            "{},{:016x},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{},{:.8},{:.8},{}",
            item.arm.label(),
            item.seed,
            item.rows,
            item.alpha,
            item.beta,
            item.correlation,
            item.bias,
            item.mae,
            item.mean_relative_error,
            item.cross_block_order_accuracy,
            item.inversion_count,
            item.margin_weighted_inversion_regret,
            item.near_tie_inversion_fraction,
            item.first_inversion_epoch
                .map_or_else(String::new, |v| v.to_string())
        )
        .expect("String cannot fail");
    }
    out
}

fn render_json(report: &CalibrationReport) -> String {
    let mut out = String::with_capacity(report.summaries.len() * 440 + 300);
    out.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00cal1/v1\",\n  \"scope\": \"engineering-only\",\n  \"width\": 2,\n  \"summaries\": [\n");
    for (index, item) in report.summaries.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(out, "    {{\"arm\":\"{}\",\"seed\":{},\"rows\":{},\"alpha\":{:.8},\"beta\":{:.8},\"correlation\":{:.8},\"bias\":{:.8},\"mae\":{:.8},\"mean_relative_error\":{:.8},\"cross_block_order_accuracy\":{:.8},\"inversion_count\":{},\"margin_weighted_inversion_regret\":{:.8},\"near_tie_inversion_fraction\":{:.8},\"first_inversion_epoch\":{}}}", item.arm.label(), item.seed, item.rows, item.alpha, item.beta, item.correlation, item.bias, item.mae, item.mean_relative_error, item.cross_block_order_accuracy, item.inversion_count, item.margin_weighted_inversion_regret, item.near_tie_inversion_fraction, item.first_inversion_epoch.map_or_else(|| "null".to_string(), |v| v.to_string())).expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

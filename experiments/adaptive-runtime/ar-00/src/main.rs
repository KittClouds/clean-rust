use std::{collections::BTreeMap, fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, RunResult, run_adamw, run_interposed, write_dataset};
use hashbrown::HashMap;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    let report_path = artifact_dir.join("ar-00-report.json");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let samples = dataset.samples();
    let baseline = run_adamw(samples, 3_000);
    let interposed = run_interposed(samples, 3_000);
    let report = render_report(&baseline, &interposed);
    fs::write(&report_path, report)?;

    println!("AR-00 — Optimizer Interposer");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    print_result("AdamW baseline", baseline);
    print_result("Action runtime", interposed);
    println!("report: {}", report_path.display());
    Ok(())
}

fn print_result(label: &str, result: RunResult) {
    println!(
        "{label}: loss={:.6} accuracy={:.2}% mse={:.6} selected={} no_op={} blocked={}",
        result.final_loss,
        result.final_accuracy * 100.0,
        result.final_mse,
        result.action_stats.selected,
        result.action_stats.no_op,
        result.action_stats.blocked,
    );
}

fn render_report(baseline: &RunResult, interposed: &RunResult) -> String {
    let mut metrics = HashMap::new();
    metrics.insert("baseline_loss", baseline.final_loss);
    metrics.insert("interposed_loss", interposed.final_loss);
    metrics.insert("baseline_accuracy", baseline.final_accuracy);
    metrics.insert("interposed_accuracy", interposed.final_accuracy);

    let mut ordered = BTreeMap::new();
    for (key, value) in metrics {
        ordered.insert(key, value);
    }

    let mut report = String::with_capacity(1024);
    report.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00/v1\",\n");
    report.push_str("  \"scope\": \"engineering-only\",\n");
    report.push_str("  \"task\": \"xor-four-point-mlp\",\n");
    report.push_str("  \"metrics\": {");
    for (index, (key, value)) in ordered.iter().enumerate() {
        if index > 0 {
            report.push(',');
        }
        write!(report, "\n    \"{key}\": {value:.8}").expect("String cannot fail");
    }
    report.push_str("\n  },\n  \"arms\": {\n");
    write_arm(&mut report, "adamw_baseline", baseline);
    report.push_str(",\n");
    write_arm(&mut report, "action_runtime", interposed);
    report.push_str("\n  }\n}\n");
    report
}

fn write_arm(report: &mut String, name: &str, result: &RunResult) {
    write!(
        report,
        "    \"{name}\": {{\n      \"epochs\": {},\n      \"final_loss\": {:.8},\n      \"final_accuracy\": {:.8},\n      \"final_mse\": {:.8},\n      \"selected_actions\": {},\n      \"no_op_actions\": {},\n      \"blocked_actions\": {}\n    }}",
        result.epochs,
        result.final_loss,
        result.final_accuracy,
        result.final_mse,
        result.action_stats.selected,
        result.action_stats.no_op,
        result.action_stats.blocked,
    )
    .expect("String cannot fail");
}

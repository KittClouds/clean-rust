use std::{collections::BTreeMap, fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00d::{EPOCHS, ResultSummary, run_all};
use hashbrown::HashMap;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00d-report.json"),
        render_report(&results),
    )?;
    fs::write(
        artifact_dir.join("ar-00d-curves.csv"),
        render_curves(&results),
    )?;
    println!("AR-00D — Commit Granularity");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        let t = result.telemetry;
        println!(
            "{}: loss={:.8} accuracy={:.2}% selected={} batches={} predicted={:.6} realized={:.6} comp_error={:.6}",
            result.policy.label(),
            result.final_loss,
            result.final_accuracy * 100.0,
            t.selected,
            t.batches,
            t.predicted_utility,
            t.realized_utility,
            t.composition_error,
        );
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[ResultSummary; 6]) -> String {
    let mut losses = HashMap::new();
    let mut accuracies = HashMap::new();
    for result in results {
        losses.insert(result.policy.label(), result.final_loss);
        accuracies.insert(result.policy.label(), result.final_accuracy);
    }
    let ordered_losses: BTreeMap<_, _> = losses.into_iter().collect();
    let ordered_accuracies: BTreeMap<_, _> = accuracies.into_iter().collect();
    let mut report = String::with_capacity(20_000);
    report.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00d/v1\",\n");
    report.push_str("  \"scope\": \"engineering-only\",\n");
    report.push_str("  \"frozen_from\": \"adaptive-runtime-ar-00c/v1\",\n");
    report.push_str("  \"epochs\": 3000,\n  \"max_actions_per_epoch\": 17,\n");
    report.push_str("  \"action_magnitudes\": [0.02, 0.01, 0.005, 0.0025, 0.00125],\n");
    report.push_str("  \"final_loss_by_policy\": ");
    write_metrics(&mut report, &ordered_losses);
    report.push_str(",\n  \"final_accuracy_by_policy\": ");
    write_metrics(&mut report, &ordered_accuracies);
    report.push_str(",\n  \"policies\": {\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            report.push_str(",\n");
        }
        write_policy(&mut report, result);
    }
    report.push_str("\n  }\n}\n");
    report
}

fn write_metrics(report: &mut String, values: &BTreeMap<&'static str, f32>) {
    report.push('{');
    for (index, (label, value)) in values.iter().enumerate() {
        if index > 0 {
            report.push(',');
        }
        write!(report, "\n    \"{label}\": {value:.8}").expect("String cannot fail");
    }
    report.push_str("\n  }");
}

fn write_policy(report: &mut String, result: &ResultSummary) {
    let t = result.telemetry;
    write!(
        report,
        "    \"{}\": {{\n      \"final_loss\": {:.8},\n      \"final_accuracy\": {:.8},\n      \"final_mse\": {:.8},\n      \"selected\": {},\n      \"no_op\": {},\n      \"blocked\": {},\n      \"batches\": {},\n      \"refreshes\": {},\n      \"utility_evaluations\": {},\n      \"predicted_utility\": {:.8},\n      \"realized_utility\": {:.8},\n      \"composition_error\": {:.8},\n      \"absolute_composition_error\": {:.8},\n      \"final_probabilities\": ",
        result.policy.label(),
        result.final_loss,
        result.final_accuracy,
        result.final_mse,
        t.selected,
        t.no_op,
        t.blocked,
        t.batches,
        t.refreshes,
        t.utility_evaluations,
        t.predicted_utility,
        t.realized_utility,
        t.composition_error,
        t.absolute_composition_error,
    )
    .expect("String cannot fail");
    write_array(report, result.final_probabilities);
    report.push_str(",\n      \"final_logits\": ");
    write_array(report, result.final_logits);
    report.push_str(",\n      \"final_margins\": ");
    write_array(report, result.final_margins);
    report.push_str("\n    }");
}

fn write_array(report: &mut String, values: [f32; 4]) {
    report.push('[');
    for (index, value) in values.iter().enumerate() {
        if index > 0 {
            report.push_str(", ");
        }
        write!(report, "{value:.8}").expect("String cannot fail");
    }
    report.push(']');
}

fn render_curves(results: &[ResultSummary; 6]) -> String {
    let mut csv = String::with_capacity(results.len() * EPOCHS * 180);
    csv.push_str("policy,epoch,loss_before,loss_after,accuracy_after,selected,batches,predicted_utility,realized_utility,composition_error,absolute_composition_error\n");
    for result in results {
        for point in &result.curve {
            writeln!(
                csv,
                "{},{},{:.8},{:.8},{:.8},{},{},{:.8},{:.8},{:.8},{:.8}",
                result.policy.label(),
                point.epoch,
                point.loss_before,
                point.loss_after,
                point.accuracy_after,
                point.selected,
                point.batches,
                point.predicted_utility,
                point.realized_utility,
                point.composition_error,
                point.absolute_composition_error,
            )
            .expect("String cannot fail");
        }
    }
    csv
}

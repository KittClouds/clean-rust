use std::{collections::BTreeMap, fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00a::{GranularityResult, run_all};
use hashbrown::HashMap;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00a-report.json"),
        render_report(&results),
    )?;
    fs::write(
        artifact_dir.join("ar-00a-curves.csv"),
        render_curves(&results),
    )?;

    println!("AR-00A — Action Granularity");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        print_result(result);
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn print_result(result: &GranularityResult) {
    let telemetry = result.telemetry;
    println!(
        "{}: loss={:.8} accuracy={:.2}% mse={:.8} selected={} no_op={} blocked={} min_step={:.5} reversals={}",
        result.arm.label(),
        result.final_loss,
        result.final_accuracy * 100.0,
        result.final_mse,
        telemetry.selected,
        telemetry.no_op,
        telemetry.blocked,
        telemetry.min_selected_magnitude,
        telemetry.sign_reversals,
    );
}

fn render_report(results: &[GranularityResult; 5]) -> String {
    let mut loss_by_arm = HashMap::new();
    let mut accuracy_by_arm = HashMap::new();
    for result in results {
        loss_by_arm.insert(result.arm.label(), result.final_loss);
        accuracy_by_arm.insert(result.arm.label(), result.final_accuracy);
    }
    let ordered_loss = ordered_metrics(loss_by_arm);
    let ordered_accuracy = ordered_metrics(accuracy_by_arm);

    let mut report = String::with_capacity(12_000);
    report.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00a/v1\",\n");
    report.push_str("  \"scope\": \"engineering-only\",\n");
    report.push_str("  \"frozen_from\": \"adaptive-runtime-ar-00/v1\",\n");
    report.push_str("  \"epochs\": 3000,\n  \"action_step\": 0.02,\n");
    report.push_str("  \"bounds\": [-3.0, 3.0],\n");
    report.push_str("  \"final_loss_by_arm\": ");
    write_metrics(&mut report, &ordered_loss);
    report.push_str(",\n  \"final_accuracy_by_arm\": ");
    write_metrics(&mut report, &ordered_accuracy);
    report.push_str(",\n  \"arms\": {\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            report.push_str(",\n");
        }
        write_arm(&mut report, result);
    }
    report.push_str("\n  }\n}\n");
    report
}

fn ordered_metrics(values: HashMap<&'static str, f32>) -> BTreeMap<&'static str, f32> {
    values.into_iter().collect()
}

fn write_metrics(report: &mut String, values: &BTreeMap<&'static str, f32>) {
    report.push('{');
    for (index, (arm, value)) in values.iter().enumerate() {
        if index > 0 {
            report.push(',');
        }
        write!(report, "\n    \"{arm}\": {value:.8}").expect("String cannot fail");
    }
    report.push_str("\n  }");
}

fn write_arm(report: &mut String, result: &GranularityResult) {
    let telemetry = result.telemetry;
    write!(
        report,
        "    \"{}\": {{\n      \"final_loss\": {:.8},\n      \"final_accuracy\": {:.8},\n      \"final_mse\": {:.8},\n      \"selected\": {},\n      \"no_op\": {},\n      \"blocked\": {},\n      \"selected_positive\": {},\n      \"selected_negative\": {},\n      \"sign_reversals\": {},\n      \"both_sign_available\": {},\n      \"one_sign_available\": {},\n      \"no_legal_move\": {},\n      \"min_selected_magnitude\": {:.8},\n      \"selected_by_level\": [",
        result.arm.label(),
        result.final_loss,
        result.final_accuracy,
        result.final_mse,
        telemetry.selected,
        telemetry.no_op,
        telemetry.blocked,
        telemetry.selected_positive,
        telemetry.selected_negative,
        telemetry.sign_reversals,
        telemetry.both_sign_available,
        telemetry.one_sign_available,
        telemetry.no_legal_move,
        telemetry.min_selected_magnitude,
    )
    .expect("String cannot fail");
    for (index, value) in telemetry.selected_by_level.iter().enumerate() {
        if index > 0 {
            report.push_str(", ");
        }
        write!(report, "{value}").expect("String cannot fail");
    }
    report.push_str("],\n      \"final_probabilities\": ");
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

fn render_curves(results: &[GranularityResult; 5]) -> String {
    let mut csv = String::with_capacity(results.len() * 3_000 * 180);
    csv.push_str("arm,epoch,loss_before,loss_after,accuracy_after,selected,no_op,blocked,min_selected_magnitude,sign_reversals,both_sign_available,one_sign_available,no_legal_move\n");
    for result in results {
        for point in &result.curve {
            writeln!(
                csv,
                "{},{},{:.8},{:.8},{:.8},{},{},{},{:.8},{},{},{},{}",
                result.arm.label(),
                point.epoch,
                point.loss_before,
                point.loss_after,
                point.accuracy_after,
                point.selected,
                point.no_op,
                point.blocked,
                point.min_selected_magnitude,
                point.sign_reversals,
                point.both_sign_available,
                point.one_sign_available,
                point.no_legal_move,
            )
            .expect("String cannot fail");
        }
    }
    csv
}

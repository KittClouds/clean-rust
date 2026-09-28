use std::{collections::BTreeMap, fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00c::{
    ChoiceComparison, EPOCHS, UtilityArm, UtilityResult, compare_choices, run_all,
};
use hashbrown::HashMap;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00c-report.json"),
        render_report(&results),
    )?;
    fs::write(
        artifact_dir.join("ar-00c-curves.csv"),
        render_curves(&results),
    )?;

    println!("AR-00C — Finite-Effect Utility");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        let comparison = if result.arm == UtilityArm::C3Oracle {
            None
        } else {
            Some(compare_choices(result, &results[3]))
        };
        print_result(result, comparison);
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn print_result(result: &UtilityResult, comparison: Option<ChoiceComparison>) {
    let telemetry = result.telemetry;
    println!(
        "{}: loss={:.8} accuracy={:.2}% selected={} no_op={} blocked={} min_step={:.5} predicted={:.6} realized={:.6} comp_error={:.6}",
        result.arm.label(),
        result.final_loss,
        result.final_accuracy * 100.0,
        telemetry.selected,
        telemetry.no_op,
        telemetry.blocked,
        telemetry.min_selected_magnitude,
        telemetry.predicted_utility,
        telemetry.realized_utility,
        telemetry.composition_error,
    );
    if let Some(comparison) = comparison {
        println!(
            "  vs C3: exact={:.2}% sign={:.2}% magnitude={:.2}%",
            comparison.exact_fraction * 100.0,
            comparison.sign_fraction * 100.0,
            comparison.magnitude_fraction * 100.0,
        );
    }
}

fn render_report(results: &[UtilityResult; 4]) -> String {
    let mut losses = HashMap::new();
    let mut accuracies = HashMap::new();
    for result in results {
        losses.insert(result.arm.label(), result.final_loss);
        accuracies.insert(result.arm.label(), result.final_accuracy);
    }
    let ordered_losses: BTreeMap<_, _> = losses.into_iter().collect();
    let ordered_accuracies: BTreeMap<_, _> = accuracies.into_iter().collect();
    let oracle = &results[3];

    let mut report = String::with_capacity(20_000);
    report.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00c/v1\",\n");
    report.push_str("  \"scope\": \"engineering-only\",\n");
    report.push_str("  \"frozen_from\": \"adaptive-runtime-ar-00/v1\",\n");
    report.push_str("  \"epochs\": 3000,\n  \"action_step\": 0.02,\n");
    report.push_str("  \"bounds\": [-3.0, 3.0],\n");
    report.push_str("  \"action_magnitudes\": [0.02, 0.01, 0.005, 0.0025, 0.00125],\n");
    report.push_str("  \"final_loss_by_arm\": ");
    write_metrics(&mut report, &ordered_losses);
    report.push_str(",\n  \"final_accuracy_by_arm\": ");
    write_metrics(&mut report, &ordered_accuracies);
    report.push_str(",\n  \"arms\": {\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            report.push_str(",\n");
        }
        let comparison = if result.arm == UtilityArm::C3Oracle {
            None
        } else {
            Some(compare_choices(result, oracle))
        };
        write_arm(&mut report, result, comparison);
    }
    report.push_str("\n  }\n}\n");
    report
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

fn write_arm(report: &mut String, result: &UtilityResult, comparison: Option<ChoiceComparison>) {
    let telemetry = result.telemetry;
    write!(
        report,
        "    \"{}\": {{\n      \"final_loss\": {:.8},\n      \"final_accuracy\": {:.8},\n      \"final_mse\": {:.8},\n      \"selected\": {},\n      \"no_op\": {},\n      \"blocked\": {},\n      \"selected_positive\": {},\n      \"selected_negative\": {},\n      \"sign_reversals\": {},\n      \"min_selected_magnitude\": {:.8},\n      \"selected_by_level\": [",
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
        telemetry.min_selected_magnitude,
    )
    .expect("String cannot fail");
    for (index, value) in telemetry.selected_by_level.iter().enumerate() {
        if index > 0 {
            report.push_str(", ");
        }
        write!(report, "{value}").expect("String cannot fail");
    }
    report.push_str("],\n      \"predicted_utility\": ");
    write!(report, "{:.8}", telemetry.predicted_utility).expect("String cannot fail");
    report.push_str(",\n      \"realized_utility\": ");
    write!(report, "{:.8}", telemetry.realized_utility).expect("String cannot fail");
    report.push_str(",\n      \"composition_error\": ");
    write!(report, "{:.8}", telemetry.composition_error).expect("String cannot fail");
    report.push_str(",\n      \"absolute_composition_error\": ");
    write!(report, "{:.8}", telemetry.absolute_composition_error).expect("String cannot fail");
    report.push_str(",\n      \"final_probabilities\": ");
    write_array(report, result.final_probabilities);
    report.push_str(",\n      \"final_logits\": ");
    write_array(report, result.final_logits);
    report.push_str(",\n      \"final_margins\": ");
    write_array(report, result.final_margins);
    if let Some(comparison) = comparison {
        report.push_str(",\n      \"vs_c3_choice_agreement\": {");
        write!(
            report,
            "\n        \"exact\": {:.8},\n        \"sign\": {:.8},\n        \"magnitude\": {:.8}\n      }}",
            comparison.exact_fraction,
            comparison.sign_fraction,
            comparison.magnitude_fraction,
        )
        .expect("String cannot fail");
    }
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

fn render_curves(results: &[UtilityResult; 4]) -> String {
    let mut csv = String::with_capacity(results.len() * EPOCHS * 180);
    csv.push_str("arm,epoch,loss_before,loss_after,accuracy_after,selected,no_op,blocked,min_selected_magnitude,predicted_utility,realized_utility,composition_error,absolute_composition_error\n");
    for result in results {
        for point in &result.curve {
            writeln!(
                csv,
                "{},{},{:.8},{:.8},{:.8},{},{},{},{:.8},{:.8},{:.8},{:.8},{:.8}",
                result.arm.label(),
                point.epoch,
                point.loss_before,
                point.loss_after,
                point.accuracy_after,
                point.selected,
                point.no_op,
                point.blocked,
                point.min_selected_magnitude,
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

use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00e::{
    CurvePoint, EPOCHS, PRIMITIVE_BUDGET, Policy, ResultSummary, run_all,
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
        artifact_dir.join("ar-00e-report.json"),
        render_report(&results),
    )?;
    fs::write(
        artifact_dir.join("ar-00e-curves.csv"),
        render_curves(&results),
    )?;
    let mut loss_by_policy = HashMap::new();
    for result in &results {
        loss_by_policy.insert(result.policy.label(), result.final_loss);
    }
    println!("AR-00E — Structural Action Groups");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        let telemetry = result.telemetry;
        println!(
            "{}: loss={:.8} accuracy={:.2}% primitives={} programs={} pairs={} groups={} evals={} predicted={:.6} realized={:.6}",
            result.policy.label(),
            result.final_loss,
            result.final_accuracy * 100.0,
            telemetry.selected_primitives,
            telemetry.programs,
            telemetry.pair_programs,
            telemetry.group_programs,
            telemetry.utility_evaluations,
            telemetry.predicted_utility,
            telemetry.realized_utility,
        );
    }
    println!("loss map entries: {}", loss_by_policy.len());
    println!("budget: {} primitive actions per epoch", PRIMITIVE_BUDGET);
    println!("epochs: {}", EPOCHS);
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[ResultSummary; 4]) -> String {
    let mut output = String::with_capacity(30_000);
    output.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00e/v1\",\n");
    output.push_str("  \"scope\": \"engineering-only\",\n");
    output.push_str(
        "  \"frozen_from\": [\"adaptive-runtime-ar-00d/v1\", \"adaptive-runtime-int2/v1\"],\n",
    );
    output.push_str("  \"epochs\": 3000,\n  \"primitive_budget_per_epoch\": 17,\n");
    output.push_str("  \"policies\": [\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            output.push_str(",\n");
        }
        write_policy(&mut output, result);
    }
    output.push_str("\n  ]\n}\n");
    output
}

fn write_policy(output: &mut String, result: &ResultSummary) {
    let telemetry = result.telemetry;
    write!(
        output,
        "    {{\"policy\": \"{}\", \"final_loss\": {:.8}, \"final_accuracy\": {:.8}, \"final_mse\": {:.8}, \"selected_primitives\": {}, \"programs\": {}, \"pair_programs\": {}, \"group_programs\": {}, \"utility_evaluations\": {}, \"predicted_utility\": {:.8}, \"realized_utility\": {:.8}, \"final_probabilities\": ",
        result.policy.label(),
        result.final_loss,
        result.final_accuracy,
        result.final_mse,
        telemetry.selected_primitives,
        telemetry.programs,
        telemetry.pair_programs,
        telemetry.group_programs,
        telemetry.utility_evaluations,
        telemetry.predicted_utility,
        telemetry.realized_utility,
    )
    .expect("String cannot fail");
    write_array(output, result.final_probabilities);
    output.push_str(", \"final_logits\": ");
    write_array(output, result.final_logits);
    output.push_str(", \"final_margins\": ");
    write_array(output, result.final_margins);
    output.push('}');
}

fn write_array(output: &mut String, values: [f32; 4]) {
    output.push('[');
    for (index, value) in values.iter().enumerate() {
        if index > 0 {
            output.push_str(", ");
        }
        write!(output, "{value:.8}").expect("String cannot fail");
    }
    output.push(']');
}

fn render_curves(results: &[ResultSummary; 4]) -> String {
    let mut output = String::with_capacity(results.len() * EPOCHS * 180);
    output.push_str("policy,epoch,loss_before,loss_after,accuracy_after,selected_primitives,programs,pair_programs,group_programs,utility_evaluations,predicted_utility,realized_utility\n");
    for result in results {
        for point in &result.curve {
            write_curve_point(&mut output, result.policy, point);
        }
    }
    output
}

fn write_curve_point(output: &mut String, policy: Policy, point: &CurvePoint) {
    writeln!(
        output,
        "{},{},{:.8},{:.8},{:.8},{},{},{},{},{},{:.8},{:.8}",
        policy.label(),
        point.epoch,
        point.loss_before,
        point.loss_after,
        point.accuracy_after,
        point.selected_primitives,
        point.programs,
        point.pair_programs,
        point.group_programs,
        point.utility_evaluations,
        point.predicted_utility,
        point.realized_utility,
    )
    .expect("String cannot fail");
}

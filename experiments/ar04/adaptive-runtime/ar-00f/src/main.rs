use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00f::{CurvePoint, RunKind, RunSummary, run_all};
use hashbrown::HashMap;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00f-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-00f-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-00f-curves.csv"),
        render_curves(&results),
    )?;
    let mut by_label = HashMap::new();
    for result in &results {
        by_label.insert((result.kind.label(), result.variant), result.final_loss);
    }
    println!("AR-00F — Grouping Causality");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        let telemetry = result.telemetry;
        println!(
            "{}[{}]: loss={:.8} accuracy={:.2}% primitives={} programs={} evals={} objective={}",
            result.kind.label(),
            result.variant,
            result.final_loss,
            result.final_accuracy * 100.0,
            telemetry.selected_primitives,
            telemetry.programs,
            telemetry.utility_evaluations,
            result
                .partition_objective
                .map_or_else(|| "-".to_string(), |value| format!("{value:.8}")),
        );
    }
    println!("runs: {}", by_label.len());
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[RunSummary]) -> String {
    let mut output = String::with_capacity(results.len() * 340);
    output.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00f/v1\",\n  \"scope\": \"engineering-only\",\n  \"epochs\": 3000,\n  \"primitive_budget_per_epoch\": 17,\n  \"results\": [\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            output.push_str(",\n");
        }
        let telemetry = result.telemetry;
        write!(
            output,
            "    {{\"kind\": \"{}\", \"variant\": {}, \"final_loss\": {:.8}, \"final_accuracy\": {:.8}, \"final_mse\": {:.8}, \"selected_primitives\": {}, \"programs\": {}, \"utility_evaluations\": {}, \"predicted_utility\": {:.8}, \"realized_utility\": {:.8}, \"partition_objective\": {} }}",
            result.kind.label(),
            result.variant,
            result.final_loss,
            result.final_accuracy,
            result.final_mse,
            telemetry.selected_primitives,
            telemetry.programs,
            telemetry.utility_evaluations,
            telemetry.predicted_utility,
            telemetry.realized_utility,
            result.partition_objective.map_or_else(|| "null".to_string(), |value| format!("{value:.8}")),
        ).expect("String cannot fail");
    }
    output.push_str("\n  ]\n}\n");
    output
}

fn render_runs(results: &[RunSummary]) -> String {
    let mut output = String::with_capacity(results.len() * 220);
    output.push_str("kind,variant,final_loss,final_accuracy,final_mse,selected_primitives,programs,utility_evaluations,predicted_utility,realized_utility,partition_objective\n");
    for result in results {
        let telemetry = result.telemetry;
        writeln!(
            output,
            "{},{},{:.8},{:.8},{:.8},{},{},{},{:.8},{:.8},{}",
            result.kind.label(),
            result.variant,
            result.final_loss,
            result.final_accuracy,
            result.final_mse,
            telemetry.selected_primitives,
            telemetry.programs,
            telemetry.utility_evaluations,
            telemetry.predicted_utility,
            telemetry.realized_utility,
            result
                .partition_objective
                .map_or_else(|| String::from(""), |value| format!("{value:.8}")),
        )
        .expect("String cannot fail");
    }
    output
}

fn render_curves(results: &[RunSummary]) -> String {
    let mut output = String::with_capacity(results.len() * 3_000 * 120);
    output.push_str("kind,variant,epoch,loss_before,loss_after,accuracy_after,selected_primitives,programs,utility_evaluations\n");
    for result in results {
        for point in &result.curve {
            write_curve(&mut output, result.kind, result.variant, point);
        }
    }
    output
}

fn write_curve(output: &mut String, kind: RunKind, variant: usize, point: &CurvePoint) {
    writeln!(
        output,
        "{},{},{},{:.8},{:.8},{:.8},{},{},{}",
        kind.label(),
        variant,
        point.epoch,
        point.loss_before,
        point.loss_after,
        point.accuracy_after,
        point.selected_primitives,
        point.programs,
        point.utility_evaluations,
    )
    .expect("String cannot fail");
}

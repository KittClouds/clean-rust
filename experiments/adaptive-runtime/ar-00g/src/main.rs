use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00g::{CurvePoint, Policy, RunSummary, run_all};
use hashbrown::HashMap;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00g-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-00g-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-00g-curves.csv"),
        render_curves(&results),
    )?;
    fs::write(
        artifact_dir.join("ar-00g-coverage.csv"),
        render_coverage(&results),
    )?;
    let mut loss_map = HashMap::new();
    for result in &results {
        loss_map.insert(result.policy.label(), result.final_loss);
    }
    println!("AR-00G — Temporal Coverage");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        let telemetry = result.telemetry;
        let coverage = result.coverage;
        println!(
            "{}: loss={:.8} accuracy={:.2}% primitives={} programs={} evals={} coverage={:.2}% min={} max={} entropy={:.4} hot={}/{} full_at={:?}",
            result.policy.label(),
            result.final_loss,
            result.final_accuracy * 100.0,
            telemetry.selected_primitives,
            telemetry.programs,
            telemetry.utility_evaluations,
            coverage.ever_covered_fraction * 100.0,
            coverage.min_pair_coverage,
            coverage.max_pair_coverage,
            coverage.coverage_entropy,
            coverage.frozen_hot_pairs_covered,
            coverage.frozen_hot_pairs,
            coverage.time_to_full_coverage,
        );
    }
    println!("loss entries: {}", loss_map.len());
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[RunSummary; 6]) -> String {
    let mut output = String::with_capacity(20_000);
    output.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00g/v1\",\n  \"scope\": \"engineering-only\",\n  \"epochs\": 3000,\n  \"primitive_budget_per_epoch\": 17,\n  \"refresh_epochs\": 100,\n  \"results\": [\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            output.push_str(",\n");
        }
        let telemetry = result.telemetry;
        let coverage = result.coverage;
        write!(
            output,
            "    {{\"policy\": \"{}\", \"final_loss\": {:.8}, \"final_accuracy\": {:.8}, \"final_mse\": {:.8}, \"selected_primitives\": {}, \"programs\": {}, \"utility_evaluations\": {}, \"ever_covered_fraction\": {:.8}, \"min_pair_coverage\": {}, \"max_pair_coverage\": {}, \"mean_pair_coverage\": {:.8}, \"coverage_entropy\": {:.8}, \"time_to_full_coverage\": {}, \"frozen_hot_pairs_covered\": {}, \"frozen_hot_pairs\": {}}}",
            result.policy.label(), result.final_loss, result.final_accuracy, result.final_mse,
            telemetry.selected_primitives, telemetry.programs, telemetry.utility_evaluations,
            coverage.ever_covered_fraction, coverage.min_pair_coverage, coverage.max_pair_coverage,
            coverage.mean_pair_coverage, coverage.coverage_entropy,
            coverage.time_to_full_coverage.map_or_else(|| "null".to_string(), |value| value.to_string()),
            coverage.frozen_hot_pairs_covered, coverage.frozen_hot_pairs,
        ).expect("String cannot fail");
    }
    output.push_str("\n  ]\n}\n");
    output
}

fn render_runs(results: &[RunSummary; 6]) -> String {
    let mut output = String::with_capacity(8_000);
    output.push_str("policy,final_loss,final_accuracy,final_mse,selected_primitives,programs,utility_evaluations,ever_covered_fraction,min_pair_coverage,max_pair_coverage,mean_pair_coverage,coverage_entropy,time_to_full_coverage,frozen_hot_pairs_covered,frozen_hot_pairs\n");
    for result in results {
        let telemetry = result.telemetry;
        let coverage = result.coverage;
        writeln!(
            output,
            "{},{:.8},{:.8},{:.8},{},{},{},{:.8},{},{},{:.8},{:.8},{},{},{}",
            result.policy.label(),
            result.final_loss,
            result.final_accuracy,
            result.final_mse,
            telemetry.selected_primitives,
            telemetry.programs,
            telemetry.utility_evaluations,
            coverage.ever_covered_fraction,
            coverage.min_pair_coverage,
            coverage.max_pair_coverage,
            coverage.mean_pair_coverage,
            coverage.coverage_entropy,
            coverage
                .time_to_full_coverage
                .map_or_else(String::new, |value| value.to_string()),
            coverage.frozen_hot_pairs_covered,
            coverage.frozen_hot_pairs,
        )
        .expect("String cannot fail");
    }
    output
}

fn render_curves(results: &[RunSummary; 6]) -> String {
    let mut output = String::with_capacity(results.len() * 3_000 * 120);
    output.push_str("policy,epoch,loss_before,loss_after,accuracy_after,selected_primitives,programs,utility_evaluations\n");
    for result in results {
        for point in &result.curve {
            write_curve(&mut output, result.policy, point);
        }
    }
    output
}

fn write_curve(output: &mut String, policy: Policy, point: &CurvePoint) {
    writeln!(
        output,
        "{},{},{:.8},{:.8},{:.8},{},{},{}",
        policy.label(),
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

fn render_coverage(results: &[RunSummary; 6]) -> String {
    let mut output = String::with_capacity(results.len() * 136 * 28);
    output.push_str("policy,first,second,joint_evaluations\n");
    for result in results {
        for first in 0..17 {
            for second in first + 1..17 {
                writeln!(
                    output,
                    "{},{},{},{}",
                    result.policy.label(),
                    first,
                    second,
                    result.coverage_matrix[first][second],
                )
                .expect("String cannot fail");
            }
        }
    }
    output
}

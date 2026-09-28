use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00h::{CurvePoint, RunSummary, run_all};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-00h-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-00h-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-00h-curves.csv"),
        render_curves(&results),
    )?;
    fs::write(
        artifact_dir.join("ar-00h-coverage.csv"),
        render_coverage(&results),
    )?;
    println!("AR-00H — Dynamic Planning Width");
    println!("dataset: {} samples (read-only mmap)", dataset.len());
    for result in &results {
        let t = result.telemetry;
        let c = result.coverage;
        println!(
            "{} width={} seed={:016x}: loss={:.8} accuracy={:.2}% epochs={} evals={} pairs={} coverage={:.2}% pair/eval={:.6} full_at={:?} budget_exhausted={}",
            result.mode.label(),
            result.width,
            result.seed,
            result.final_loss,
            result.final_accuracy * 100.0,
            t.completed_epochs,
            t.utility_evaluations,
            c.pair_events,
            c.ever_covered_fraction * 100.0,
            c.pair_events_per_evaluation,
            c.time_to_full_coverage,
            t.budget_exhausted,
        );
    }
    println!("runs: {}", results.len());
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 420 + 300);
    out.push_str("{\n  \"schema\": \"adaptive-runtime-ar-00h/v1\",\n  \"scope\": \"engineering-only\",\n  \"epochs\": 3000,\n  \"evaluation_budget\": 10000000,\n  \"pair_event_budget\": 4096,\n  \"results\": [\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        let t = result.telemetry;
        let c = result.coverage;
        write!(out, "    {{\"mode\":\"{}\",\"width\":{},\"seed\":{},\"final_loss\":{:.8},\"final_accuracy\":{:.8},\"final_mse\":{:.8},\"completed_epochs\":{},\"budget_exhausted\":{},\"selected_primitives\":{},\"programs\":{},\"utility_evaluations\":{},\"ever_covered_fraction\":{:.8},\"min_pair_coverage\":{},\"max_pair_coverage\":{},\"planning_steps\":{},\"pair_events\":{},\"pair_events_per_step\":{:.8},\"pair_events_per_evaluation\":{:.8},\"time_to_full_coverage\":{}}}", result.mode.label(), result.width, result.seed, result.final_loss, result.final_accuracy, result.final_mse, t.completed_epochs, t.budget_exhausted, t.selected_primitives, t.programs, t.utility_evaluations, c.ever_covered_fraction, c.min_pair_coverage, c.max_pair_coverage, c.planning_steps, c.pair_events, c.pair_events_per_step, c.pair_events_per_evaluation, c.time_to_full_coverage.map_or_else(|| "null".to_string(), |v| v.to_string())).expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

fn render_runs(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 260 + 500);
    out.push_str("mode,width,seed,final_loss,final_accuracy,final_mse,completed_epochs,budget_exhausted,selected_primitives,programs,utility_evaluations,ever_covered_fraction,min_pair_coverage,max_pair_coverage,planning_steps,pair_events,pair_events_per_step,pair_events_per_evaluation,time_to_full_coverage\n");
    for result in results {
        let t = result.telemetry;
        let c = result.coverage;
        writeln!(
            out,
            "{},{},{:016x},{:.8},{:.8},{:.8},{},{},{},{},{},{:.8},{},{},{},{},{:.8},{:.8},{}",
            result.mode.label(),
            result.width,
            result.seed,
            result.final_loss,
            result.final_accuracy,
            result.final_mse,
            t.completed_epochs,
            t.budget_exhausted,
            t.selected_primitives,
            t.programs,
            t.utility_evaluations,
            c.ever_covered_fraction,
            c.min_pair_coverage,
            c.max_pair_coverage,
            c.planning_steps,
            c.pair_events,
            c.pair_events_per_step,
            c.pair_events_per_evaluation,
            c.time_to_full_coverage
                .map_or_else(String::new, |v| v.to_string())
        )
        .expect("String cannot fail");
    }
    out
}

fn render_curves(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 3_000 * 120);
    out.push_str("mode,width,seed,epoch,loss_before,loss_after,accuracy_after,selected_primitives,programs,utility_evaluations,pair_events\n");
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
        "{},{},{:016x},{},{:.8},{:.8},{:.8},{},{},{},{}",
        result.mode.label(),
        result.width,
        result.seed,
        point.epoch,
        point.loss_before,
        point.loss_after,
        point.accuracy_after,
        point.selected_primitives,
        point.programs,
        point.utility_evaluations,
        point.pair_events
    )
    .expect("String cannot fail");
}

fn render_coverage(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 136 * 40);
    out.push_str("mode,width,seed,first,second,joint_evaluations\n");
    for result in results {
        for first in 0..17 {
            for second in first + 1..17 {
                writeln!(
                    out,
                    "{},{},{:016x},{},{},{}",
                    result.mode.label(),
                    result.width,
                    result.seed,
                    first,
                    second,
                    result.coverage_matrix[first][second]
                )
                .expect("String cannot fail");
            }
        }
    }
    out
}

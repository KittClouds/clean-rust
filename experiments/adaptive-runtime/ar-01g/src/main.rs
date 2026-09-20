use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_01g::{
    AuditSummary, CurvePoint, MappedDataset, RunSummary, run_all, write_dataset,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("spiral-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = run_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-01g-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-01g-runs.csv"), render_runs(&results))?;
    fs::write(
        artifact_dir.join("ar-01g-curves.csv"),
        render_curves(&results),
    )?;
    println!("AR-01G — verification coverage geometry");
    println!(
        "dataset: {} samples (read-only mmap)",
        dataset.samples().len()
    );
    for result in &results {
        println!(
            "{} seed={:016x}: train_loss={:.6} val_loss={:.6} train_acc={:.1}% val_acc={:.1}% proposals={} compounds={} shortlist_misses={} verification_noise={} scheduler_misorders={}",
            result.arm.label(),
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy * 100.0,
            result.final_validation_accuracy * 100.0,
            result.telemetry.proposal_evaluations,
            result.telemetry.compound_evaluations,
            result.audit.shortlist_misses,
            result.audit.verification_noise,
            result.audit.scheduler_misorders,
        );
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 900 + 800);
    out.push_str("{\n  \"schema\": \"adaptive-runtime-ar-01g/v1\",\n  \"scope\": \"engineering-only\",\n  \"task\": \"three-class-spiral\",\n  \"protocol\": \"G0/G4 full 96, G1 random 64, G2 class-balanced 64, G3 geometry-stratified 64, G5 3x32, G6 2x48, G7 6x16; K2 with 4 sequential commits per evidence sample; G8 AdamW; G9 sign; proposal evidence is always a 16-example minibatch; 4800 total commits; 3 seeds\",\n  \"results\": [\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(
            out,
            "    {{\"arm\":\"{}\",\"seed\":{},\"final_train_loss\":{:.8},\"final_validation_loss\":{:.8},\"final_train_accuracy\":{:.8},\"final_validation_accuracy\":{:.8},\"final_mse\":{:.8},\"proposal_evaluations\":{},\"compound_evaluations\":{},\"committed_programs\":{},\"pair_coverage\":{:.8},\"audit\":{}}}",
            result.arm.label(), result.seed, result.final_train_loss,
            result.final_validation_loss, result.final_train_accuracy,
            result.final_validation_accuracy, result.final_mse,
            result.telemetry.proposal_evaluations, result.telemetry.compound_evaluations,
            result.telemetry.committed_programs,
            result.coverage.ever_pairs as f32 / result.coverage.possible_pairs as f32,
            render_audit_object(result.audit),
        )
        .expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

fn render_audit_object(audit: AuditSummary) -> String {
    format!(
        "{{\"snapshots\":{},\"reference_evaluations\":{},\"shortlist_misses\":{},\"verification_noise\":{},\"scheduler_misorders\":{},\"mean_reference_regret\":{:.8},\"max_reference_regret\":{:.8}}}",
        audit.snapshots,
        audit.reference_evaluations,
        audit.shortlist_misses,
        audit.verification_noise,
        audit.scheduler_misorders,
        audit.mean_reference_regret,
        audit.max_reference_regret,
    )
}

fn render_runs(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 350 + 300);
    out.push_str("arm,seed,final_train_loss,final_validation_loss,final_train_accuracy,final_validation_accuracy,final_mse,proposal_evaluations,compound_evaluations,committed_programs,committed_primitives,ever_pairs,possible_pairs,rounds,shortlist_misses,verification_noise,scheduler_misorders,mean_reference_regret,max_reference_regret\n");
    for result in results {
        writeln!(
            out,
            "{},{:016x},{:.8},{:.8},{:.8},{:.8},{:.8},{},{},{},{},{},{},{},{},{},{},{:.8},{:.8}",
            result.arm.label(),
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            result.final_mse,
            result.telemetry.proposal_evaluations,
            result.telemetry.compound_evaluations,
            result.telemetry.committed_programs,
            result.telemetry.committed_primitives,
            result.coverage.ever_pairs,
            result.coverage.possible_pairs,
            result.coverage.rounds,
            result.audit.shortlist_misses,
            result.audit.verification_noise,
            result.audit.scheduler_misorders,
            result.audit.mean_reference_regret,
            result.audit.max_reference_regret,
        )
        .expect("String cannot fail");
    }
    out
}

fn render_curves(results: &[RunSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 60 * 150);
    out.push_str("arm,seed,step,train_loss,validation_loss,train_accuracy,validation_accuracy\n");
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
        "{},{:016x},{},{:.8},{:.8},{:.8},{:.8}",
        result.arm.label(),
        result.seed,
        point.step,
        point.train_loss,
        point.validation_loss,
        point.train_accuracy,
        point.validation_accuracy,
    )
    .expect("String cannot fail");
}

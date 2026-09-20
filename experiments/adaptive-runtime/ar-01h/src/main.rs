use std::{fmt::Write as _, fs, path::PathBuf};

use adaptive_runtime_ar_01h::{
    DIAGNOSTIC_FAMILY_COUNT, DIAGNOSTIC_FAMILY_COUNTS, DIAGNOSTIC_FAMILY_OFFSETS,
    DIAGNOSTIC_FAMILY_SIZES, DiagnosticSummary, MappedDataset, diagnostic_all, write_dataset,
};

const FAMILY_LABELS: [&str; DIAGNOSTIC_FAMILY_COUNT] = [
    "6x16-independent",
    "3x32-independent",
    "2x48-independent",
    "full-96-reference",
];

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("spiral-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let results = diagnostic_all(dataset.samples());
    fs::write(
        artifact_dir.join("ar-01h-report.json"),
        render_report(&results),
    )?;
    fs::write(artifact_dir.join("ar-01h-runs.csv"), render_runs(&results))?;
    println!("AR-01H — verification uncertainty and authorization regret");
    println!(
        "trajectory: G3 stratified-64, K2, 4 sequential commits per evidence round, {} total commits, {} diagnostic snapshots/seed",
        adaptive_runtime_ar_01h::TOTAL_COMMITS,
        adaptive_runtime_ar_01h::DIAGNOSTIC_SNAPSHOTS,
    );
    println!(
        "dataset: {} samples (read-only mmap)",
        dataset.samples().len()
    );
    for result in &results {
        println!(
            "seed={:016x}: train_loss={:.6} val_loss={:.6} train_acc={:.1}% val_acc={:.1}% shadow_evals={} reference_evals={} selected_block_match={:.1}%",
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy * 100.0,
            result.final_validation_accuracy * 100.0,
            result.shadow_evaluations,
            result.reference_evaluations,
            result.selected_block_match_rate * 100.0,
        );
        for (family, label) in result.families.iter().zip(FAMILY_LABELS) {
            println!(
                "  {label}: sign={:.1}% regret={:.6} stddev-regret-r={:.3} block-rank={:.1}% component-block-rank={:.1}%",
                family.sign_reliability * 100.0,
                family.mean_selected_reference_regret,
                family.regret_stddev_correlation,
                family.family_best_block_match_rate * 100.0,
                family.component_best_block_match_rate * 100.0,
            );
        }
    }
    println!("artifacts: {}", artifact_dir.display());
    Ok(())
}

fn render_report(results: &[DiagnosticSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 3_000 + 1_200);
    out.push_str(
        "{\n  \"schema\": \"adaptive-runtime-ar-01h/v1\",\n  \"scope\": \"engineering-only\",\n  \"task\": \"three-class-spiral\",\n  \"protocol\": \"diagnostic-only shadow audit of the fixed G3 stratified-64 trajectory; K2 top-2x2 shortlist; proposal evidence is a 16-example minibatch; four sequential commits per evidence round; shadow families are 6x16, 3x32, 2x48 independent random verifier components plus full-96 reference; shadow observations never affect commits; snapshots occur every 50 commits; three seeds\",\n  \"family_layout\": {\n",
    );
    for family in 0..DIAGNOSTIC_FAMILY_COUNT {
        if family > 0 {
            out.push_str(",\n");
        }
        write!(
            out,
            "    \"{}\": {{\"offset\":{},\"components\":{},\"size\":{}}}",
            FAMILY_LABELS[family],
            DIAGNOSTIC_FAMILY_OFFSETS[family],
            DIAGNOSTIC_FAMILY_COUNTS[family],
            DIAGNOSTIC_FAMILY_SIZES[family],
        )
        .expect("String cannot fail");
    }
    out.push_str("\n  },\n  \"results\": [\n");
    for (index, result) in results.iter().enumerate() {
        if index > 0 {
            out.push_str(",\n");
        }
        write!(
            out,
            "    {{\"seed\":{},\"snapshots\":{},\"shadow_evaluations\":{},\"reference_evaluations\":{},\"final_train_loss\":{:.8},\"final_validation_loss\":{:.8},\"final_train_accuracy\":{:.8},\"final_validation_accuracy\":{:.8},\"selected_block_match_rate\":{:.8},\"selected_program_match_rate\":{:.8},\"families\":{{{}}}}}",
            result.seed,
            result.snapshots,
            result.shadow_evaluations,
            result.reference_evaluations,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            result.selected_block_match_rate,
            result.selected_program_match_rate,
            render_families(result),
        )
        .expect("String cannot fail");
    }
    out.push_str("\n  ]\n}\n");
    out
}

#[allow(clippy::needless_range_loop)]
fn render_families(result: &DiagnosticSummary) -> String {
    let mut out = String::new();
    for family in 0..DIAGNOSTIC_FAMILY_COUNT {
        if family > 0 {
            out.push(',');
        }
        let summary = result.families[family];
        write!(
            out,
            "\"{}\":{{\"snapshots\":{},\"sign_reliability\":{:.8},\"sign_matches\":{},\"sign_total\":{},\"selected_samples\":{},\"mean_selected_stddev\":{:.8},\"mean_selected_snr\":{:.8},\"mean_selected_positive_probability\":{:.8},\"mean_selected_reference_regret\":{:.8},\"max_selected_reference_regret\":{:.8},\"selected_block_match_rate\":{:.8},\"selected_program_match_rate\":{:.8},\"mean_selected_winner_agreement\":{:.8},\"mean_selected_utility_error\":{:.8},\"component_winner_match_rate\":{:.8},\"component_winner_matches\":{},\"component_winner_total\":{},\"family_best_block_match_rate\":{:.8},\"family_best_block_matches\":{},\"family_best_block_total\":{},\"mean_family_block_value_error\":{:.8},\"component_best_block_match_rate\":{:.8},\"component_best_block_matches\":{},\"component_best_block_total\":{},\"regret_stddev_correlation\":{:.8},\"regret_inverse_snr_correlation\":{:.8}}}",
            FAMILY_LABELS[family],
            summary.snapshots,
            summary.sign_reliability,
            summary.sign_matches,
            summary.sign_total,
            summary.selected_samples,
            summary.mean_selected_stddev,
            summary.mean_selected_snr,
            summary.mean_selected_positive_probability,
            summary.mean_selected_reference_regret,
            summary.max_selected_reference_regret,
            summary.selected_block_match_rate,
            summary.selected_program_match_rate,
            summary.mean_selected_winner_agreement,
            summary.mean_selected_utility_error,
            summary.component_winner_match_rate,
            summary.component_winner_matches,
            summary.component_winner_total,
            summary.family_best_block_match_rate,
            summary.family_best_block_matches,
            summary.family_best_block_total,
            summary.mean_family_block_value_error,
            summary.component_best_block_match_rate,
            summary.component_best_block_matches,
            summary.component_best_block_total,
            summary.regret_stddev_correlation,
            summary.regret_inverse_snr_correlation,
        )
        .expect("String cannot fail");
    }
    out
}

#[allow(clippy::needless_range_loop)]
fn render_runs(results: &[DiagnosticSummary]) -> String {
    let mut out = String::with_capacity(results.len() * 1_600 + 500);
    out.push_str("seed,final_train_loss,final_validation_loss,final_train_accuracy,final_validation_accuracy,snapshots,shadow_evaluations,reference_evaluations,selected_block_match_rate,selected_program_match_rate,family,sign_reliability,mean_selected_stddev,mean_selected_snr,mean_selected_positive_probability,mean_selected_reference_regret,max_selected_reference_regret,selected_block_match_rate_family,selected_program_match_rate_family,mean_selected_winner_agreement,mean_selected_utility_error,component_winner_match_rate,family_best_block_match_rate,component_best_block_match_rate,regret_stddev_correlation,regret_inverse_snr_correlation\n");
    for result in results {
        for family in 0..DIAGNOSTIC_FAMILY_COUNT {
            let summary = result.families[family];
            writeln!(
                out,
                "{:016x},{:.8},{:.8},{:.8},{:.8},{},{},{},{:.8},{:.8},{},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8},{:.8}",
                result.seed,
                result.final_train_loss,
                result.final_validation_loss,
                result.final_train_accuracy,
                result.final_validation_accuracy,
                result.snapshots,
                result.shadow_evaluations,
                result.reference_evaluations,
                result.selected_block_match_rate,
                result.selected_program_match_rate,
                FAMILY_LABELS[family],
                summary.sign_reliability,
                summary.mean_selected_stddev,
                summary.mean_selected_snr,
                summary.mean_selected_positive_probability,
                summary.mean_selected_reference_regret,
                summary.max_selected_reference_regret,
                summary.selected_block_match_rate,
                summary.selected_program_match_rate,
                summary.mean_selected_winner_agreement,
                summary.mean_selected_utility_error,
                summary.component_winner_match_rate,
                summary.family_best_block_match_rate,
                summary.component_best_block_match_rate,
                summary.regret_stddev_correlation,
                summary.regret_inverse_snr_correlation,
            )
            .expect("String cannot fail");
        }
    }
    out
}

use super::*;
use std::io::{self, Write};
use std::path::Path;

pub(super) fn write_results(
    output_dir: impl AsRef<Path>,
    samples: &[Sample],
    results: &[R1RunResult],
) -> io::Result<()> {
    std::fs::create_dir_all(output_dir.as_ref())?;
    write_runs(output_dir.as_ref().join("ar-02a-r1-runs.csv"), results)?;
    write_curves(output_dir.as_ref().join("ar-02a-r1-curve.csv"), results)?;
    write_strata(output_dir.as_ref().join("decision-strata.csv"), samples)?;
    write_report(output_dir.as_ref().join("ar-02a-r1-report.json"), results)
}

fn write_runs(path: impl AsRef<Path>, results: &[R1RunResult]) -> io::Result<()> {
    let mut file = std::fs::File::create(path)?;
    writeln!(
        file,
        "spec,proposal_size,verifier_size,verifier,seed,train_loss,validation_loss,train_accuracy,validation_accuracy,optimizer_steps,committed_programs,committed_primitives,proposal_evaluations,proposal_sample_evaluations,compound_evaluations,compound_sample_evaluations,schedule_pair_events,full_train_utility_sum,full_train_positive_commits,harmful_commits,mean_harmful_magnitude,p90_harmful_magnitude,p95_harmful_magnitude,p99_harmful_magnitude,max_harmful_magnitude,regret_audits,full_reference_candidate_evaluations,mean_sampled_reference_regret,cumulative_sampled_reference_regret,p90_sampled_reference_regret,p95_sampled_reference_regret,p99_sampled_reference_regret,max_sampled_reference_regret,pairs_seen,pairs_possible,elapsed_seconds"
    )?;
    for run in results {
        writeln!(
            file,
            "{},{},{},{},{:016x},{:.9},{:.9},{:.6},{:.6},{},{},{},{},{},{},{},{},{:.12},{},{},{:.12},{:.12},{:.12},{:.12},{:.12},{},{},{:.12},{:.12},{:.12},{:.12},{:.12},{:.12},{},{},{:.6}",
            run.spec.name,
            run.spec.proposal_size,
            run.spec.verifier_size,
            run.spec.verifier.as_str(),
            run.seed,
            run.final_train_loss,
            run.final_validation_loss,
            run.final_train_accuracy,
            run.final_validation_accuracy,
            run.optimizer_steps,
            run.committed_programs,
            run.committed_primitives,
            run.proposal_evaluations,
            run.proposal_sample_evaluations,
            run.compound_evaluations,
            run.compound_sample_evaluations,
            run.schedule_pair_events,
            run.full_train_utility_sum,
            run.full_train_positive_commits,
            run.harmful_commits,
            run.mean_harmful_magnitude,
            run.p90_harmful_magnitude,
            run.p95_harmful_magnitude,
            run.p99_harmful_magnitude,
            run.max_harmful_magnitude,
            run.regret_audits,
            run.full_reference_candidate_evaluations,
            run.mean_sampled_reference_regret,
            run.cumulative_sampled_reference_regret,
            run.p90_sampled_reference_regret,
            run.p95_sampled_reference_regret,
            run.p99_sampled_reference_regret,
            run.max_sampled_reference_regret,
            run.coverage.ever_pairs,
            run.coverage.possible_pairs,
            run.elapsed_seconds,
        )?;
    }
    file.flush()
}

fn write_curves(path: impl AsRef<Path>, results: &[R1RunResult]) -> io::Result<()> {
    let mut file = std::fs::File::create(path)?;
    writeln!(
        file,
        "spec,seed,commit,train_loss,validation_loss,train_accuracy,validation_accuracy"
    )?;
    for run in results {
        for point in &run.curve {
            writeln!(
                file,
                "{},{:016x},{},{:.9},{:.9},{:.6},{:.6}",
                run.spec.name,
                run.seed,
                point.step,
                point.train_loss,
                point.validation_loss,
                point.train_accuracy,
                point.validation_accuracy,
            )?;
        }
    }
    file.flush()
}

fn write_strata(path: impl AsRef<Path>, samples: &[Sample]) -> io::Result<()> {
    let train = &samples[..TRAIN_SAMPLES];
    let margins = build_margin_strata(train);
    let mut file = std::fs::File::create(path)?;
    writeln!(
        file,
        "train_index,class,latent_cell,bayes_margin,margin_stratum,class_conditional_bin"
    )?;
    for index in 0..TRAIN_SAMPLES {
        let class = train[index].target;
        let stratum = margins.ids[index] as usize;
        writeln!(
            file,
            "{index},{class},{},{:.9},{stratum},{}",
            index / TRAIN_PER_CELL,
            margins.margins[index],
            stratum % MARGIN_BINS,
        )?;
    }
    file.flush()
}

fn write_report(path: impl AsRef<Path>, results: &[R1RunResult]) -> io::Result<()> {
    let mut file = std::fs::File::create(path)?;
    writeln!(file, "{{")?;
    writeln!(
        file,
        "  \"protocol\": \"AR-02A-R1 corrected-strata and verifier oracle; engineering-only\","
    )?;
    writeln!(
        file,
        "  \"task\": {{\"train\": 96, \"validation\": 48, \"classes\": 3, \"latent_cells\": 12, \"margin_strata\": 12, \"margin_bins\": 4}},"
    )?;
    writeln!(
        file,
        "  \"runtime\": {{\"model\": \"2-8-8-3 ReLU\", \"commits\": {R1_COMMITS}, \"commits_per_evidence\": {COMMITS_PER_EVIDENCE}, \"K2_shortlist\": 2, \"full_reference_audit_interval\": {AUDIT_INTERVAL}}},"
    )?;
    writeln!(
        file,
        "  \"weighted_estimators\": {{\"class\": \"equal mean of per-class means\", \"cell\": \"equal mean of per-cell means\", \"decision_margin\": \"equal mean of class-conditional quartile-stratum means\", \"random_and_full\": \"ordinary sample mean\"}},"
    )?;
    writeln!(
        file,
        "  \"seeds\": [\"{:016x}\", \"{:016x}\", \"{:016x}\"],",
        R1_SEEDS[0], R1_SEEDS[1], R1_SEEDS[2]
    )?;
    writeln!(file, "  \"runs\": {},", results.len())?;
    writeln!(file, "  \"methods\": [")?;
    for (index, spec) in R1_METHODS.iter().enumerate() {
        let runs: Vec<_> = results
            .iter()
            .filter(|run| run.spec.name == spec.name)
            .collect();
        let count = runs.len().max(1) as f64;
        let mean_val_loss = runs
            .iter()
            .map(|run| f64::from(run.final_validation_loss))
            .sum::<f64>()
            / count;
        let mean_val_accuracy = runs
            .iter()
            .map(|run| f64::from(run.final_validation_accuracy))
            .sum::<f64>()
            / count;
        let mean_train_loss = runs
            .iter()
            .map(|run| f64::from(run.final_train_loss))
            .sum::<f64>()
            / count;
        let mean_regret = runs
            .iter()
            .map(|run| run.mean_sampled_reference_regret)
            .sum::<f64>()
            / count;
        let mean_runtime = runs.iter().map(|run| run.elapsed_seconds).sum::<f64>() / count;
        let suffix = if index + 1 == R1_METHODS.len() {
            ""
        } else {
            ","
        };
        writeln!(
            file,
            "    {{\"name\":\"{}\",\"proposal_size\":{},\"verifier_size\":{},\"verifier\":\"{}\",\"n\":{},\"mean_train_loss\":{:.9},\"mean_validation_loss\":{:.9},\"mean_validation_accuracy\":{:.6},\"mean_sampled_reference_regret\":{:.12},\"mean_wall_seconds\":{:.6}}}{}",
            spec.name,
            spec.proposal_size,
            spec.verifier_size,
            spec.verifier.as_str(),
            runs.len(),
            mean_train_loss,
            mean_val_loss,
            mean_val_accuracy,
            mean_regret,
            mean_runtime,
            suffix,
        )?;
    }
    writeln!(file, "  ],")?;
    writeln!(
        file,
        "  \"integrity\": {{\"validation_used_for_selection\":false,\"proposal_and_verifier_roles_are_independently_configurable\":true,\"random_p16_proposal_and_verifier_use_distinct_rng_streams\":true,\"strata_weights_sum_to_one\":true,\"extra_16_sample_strata_rotate_by_evidence_round\":true}},"
    )?;
    writeln!(
        file,
        "  \"artifacts\": [\"gaussian-cells.bin\",\"ar-02a-r1-runs.csv\",\"ar-02a-r1-curve.csv\",\"decision-strata.csv\"]"
    )?;
    writeln!(file, "}}")?;
    file.flush()
}

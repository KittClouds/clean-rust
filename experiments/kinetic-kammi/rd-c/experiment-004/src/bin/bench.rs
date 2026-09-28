use hashbrown::HashMap;
use std::{
    error::Error,
    fs::{self, File},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_001::DecisionCompiler;
use rdc_experiment_004::{
    Choice, EvalLabel, Policy, experiment_schema, heldout_episodes, heldout_labels, plan_budgets,
    report::build_report,
    runtime::{RunSpec, run_episode},
    scoring::budget_is_exact,
};

const BUDGETS: [usize; 4] = [16, 32, 48, 64];

fn main() -> Result<(), Box<dyn Error>> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts_root = manifest_dir.join("artifacts").join("runs");
    fs::create_dir_all(&artifacts_root)?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let run_dir = artifacts_root.join(format!("e004-{nonce}"));
    fs::create_dir(&run_dir)?;
    let public_dir = run_dir.join("inputs");
    let evaluation_dir = run_dir.join("evaluation");
    fs::create_dir_all(&public_dir)?;
    fs::create_dir_all(&evaluation_dir)?;

    let episodes = heldout_episodes();
    if episodes.len() != rdc_experiment_004::episodes::EPISODE_COUNT {
        return Err("episode bank cardinality mismatch".into());
    }
    write_public_bank(&public_dir.join("episodes.csv"), &episodes)?;
    let plans = plan_budgets(&episodes, &BUDGETS);
    if plans.iter().any(|plan| !budget_is_exact(plan)) {
        return Err("routing plan does not meet its exact call budget".into());
    }
    write_plans(&run_dir.join("routing-plans.csv"), &plans)?;

    // Freeze the public inputs and routing plans before the evaluator creates hidden labels.
    let labels = heldout_labels(&episodes);
    if labels.len() != episodes.len() {
        return Err("episode/label bank cardinality mismatch".into());
    }
    write_labels(&evaluation_dir.join("hidden-labels.csv"), &labels)?;

    let label_by_id = labels
        .iter()
        .map(|label| (label.episode_id, *label))
        .collect::<HashMap<_, _>>();
    let schema = experiment_schema();
    let compiler = DecisionCompiler::compile(&schema)?;
    let mut trace =
        BufWriter::with_capacity(64 * 1024, File::create(run_dir.join("run-trace.csv"))?);
    writeln!(
        trace,
        "policy,budget,episode_id,class,escalated,observer_a,observer_b,disagreement,witness,witness_source_id,resolver_action,selected_action,correct_action,wrong_legal_action,completed,illegal_commits,rejected,duplicates,missing,replay_ok,replay_identity,task_ns,observer_a_ns,observer_b_ns,witness_ns,resolver_ns,tool_ns,tool_calls,resolver_tokens,external_cost_micros,journal_bytes,action_bytes,journal_path"
    )?;
    let total = plans.len() * episodes.len();
    let mut completed_runs = 0usize;
    let mut runs = Vec::with_capacity(total);
    for plan in &plans {
        for episode in &episodes {
            let label = *label_by_id
                .get(&episode.id)
                .ok_or("missing held-out label")?;
            let run = run_episode(RunSpec {
                policy: plan.policy,
                budget: plan.budget,
                escalated: plan.selected_ids.contains(&episode.id),
                episode: *episode,
                label,
                compiler: &compiler,
                schema: &schema,
                journal_root: &run_dir.join("tasks"),
                task_salt: 0xE404_51A7_0000_0000,
            })?;
            write_trace_row(&mut trace, &run, &run_dir)?;
            runs.push(run);
            completed_runs += 1;
        }
        trace.flush()?;
        if completed_runs.is_multiple_of(32) || completed_runs == total {
            eprintln!("completed {completed_runs}/{total} paired tasks");
        }
    }
    trace.flush()?;
    let observed_calls = runs.iter().filter(|run| run.escalated).count();
    let expected_calls = Policy::ALL.len() * BUDGETS.iter().sum::<usize>();
    if observed_calls != expected_calls {
        return Err(
            format!("observed {observed_calls} resolver calls; expected {expected_calls}").into(),
        );
    }
    let report = build_report(&runs, &episodes, &BUDGETS);
    fs::write(run_dir.join("benchmark-report.md"), &report)?;
    fs::write(
        manifest_dir.join("artifacts").join("benchmark-report.md"),
        &report,
    )?;
    write_manifest(&run_dir, &manifest_dir)?;
    println!(
        "Experiment 004 report: {}",
        run_dir.join("benchmark-report.md").display()
    );
    println!(
        "Latest report: {}",
        manifest_dir
            .join("artifacts")
            .join("benchmark-report.md")
            .display()
    );
    println!("Tasks: {completed_runs}; resolver calls: {observed_calls}; report generated.");
    Ok(())
}

fn write_public_bank(
    path: &Path,
    episodes: &[rdc_experiment_004::Episode],
) -> Result<(), Box<dyn Error>> {
    let mut file = BufWriter::new(File::create(path)?);
    writeln!(
        file,
        "episode_id,stratum,goal,primary_action,audit_action,primary_revision,audit_revision,primary_age,audit_age,flags,confidence,public_frame_digest"
    )?;
    for episode in episodes {
        let f = episode.features;
        writeln!(
            file,
            "{},{},{},{},{},{},{},{},{},{},{},{}",
            episode.id,
            episode.class.label(),
            f.goal,
            f.primary_action.label(),
            f.audit_action.label(),
            f.primary_revision,
            f.audit_revision,
            f.primary_age,
            f.audit_age,
            f.flags,
            episode.confidence,
            hex(&f.frame_evidence().digest)
        )?;
    }
    file.flush()?;
    Ok(())
}

fn write_labels(path: &Path, labels: &[EvalLabel]) -> Result<(), Box<dyn Error>> {
    let mut file = BufWriter::new(File::create(path)?);
    writeln!(file, "episode_id,truth_revision,correct_action")?;
    for label in labels {
        writeln!(
            file,
            "{},{},{}",
            label.episode_id,
            label.truth_revision,
            label.correct_action.label()
        )?;
    }
    file.flush()?;
    Ok(())
}

fn write_plans(
    path: &Path,
    plans: &[rdc_experiment_004::BudgetPlan],
) -> Result<(), Box<dyn Error>> {
    let mut file = BufWriter::new(File::create(path)?);
    writeln!(file, "policy,budget,episode_id,escalate")?;
    for plan in plans {
        let mut ids = plan.selected_ids.iter().copied().collect::<Vec<_>>();
        ids.sort_unstable();
        for episode_id in ids {
            writeln!(
                file,
                "{},{},{episode_id},true",
                plan.policy.label(),
                plan.budget
            )?;
        }
    }
    file.flush()?;
    Ok(())
}

fn write_trace_row(
    file: &mut BufWriter<File>,
    run: &rdc_experiment_004::RunResult,
    run_dir: &Path,
) -> Result<(), Box<dyn Error>> {
    let resolver = run.resolver_action.map_or("none", Choice::label);
    let relative_journal = run
        .e2_journal
        .strip_prefix(run_dir)
        .unwrap_or(&run.e2_journal);
    writeln!(
        file,
        "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
        run.policy.label(),
        run.budget,
        run.episode_id,
        run.class,
        run.escalated,
        run.raw_active.label(),
        run.raw_shadow.label(),
        run.action_disagreement,
        run.witness,
        run.witness_source_id
            .map_or_else(|| "none".to_owned(), |source| source.to_string()),
        resolver,
        run.selected_action.label(),
        run.correct_action.label(),
        run.wrong_legal_action,
        run.task_completed,
        run.illegal_commits,
        run.rejected_proposals,
        run.duplicate_actions,
        run.missing_actions,
        run.replay_identity_ok,
        hex(&run.replay_identity),
        run.wall_ns,
        run.observer_a_ns,
        run.observer_b_ns,
        run.witness_ns,
        run.resolver_ns,
        run.tool_ns,
        run.tool_calls,
        run.resolver_tokens,
        run.external_model_cost_micros,
        run.journal_bytes,
        run.action_bytes,
        relative_journal.display()
    )?;
    Ok(())
}

fn write_manifest(run_dir: &Path, root: &Path) -> Result<(), Box<dyn Error>> {
    let files = [
        "inputs/episodes.csv",
        "evaluation/hidden-labels.csv",
        "routing-plans.csv",
        "run-trace.csv",
        "benchmark-report.md",
    ];
    let mut rows = String::new();
    let mut first = true;
    for relative in &files {
        let digest = hash_file(&run_dir.join(relative))?;
        if !first {
            rows.push_str(",\n");
        }
        first = false;
        rows.push_str(&format!("    \"{relative}\": \"{digest}\""));
    }
    let source_files = [
        "Cargo.toml",
        "Cargo.lock",
        "src/lib.rs",
        "src/domain.rs",
        "src/episodes.rs",
        "src/routing.rs",
        "src/runtime.rs",
        "src/scoring.rs",
        "src/report.rs",
        "src/bin/bench.rs",
        "src/evaluation.rs",
        "README.md",
        "tests/experiment004.rs",
        "BASELINE.md",
    ];
    for relative in source_files {
        let digest = hash_file(&root.join(relative))?;
        rows.push_str(&format!(",\n    \"source/{relative}\": \"{digest}\""));
    }
    let e2_baseline = hash_file(
        &root
            .parent()
            .unwrap_or(root)
            .join("experiment-002")
            .join("BASELINE.md"),
    )?;
    let cargo_lock = hash_file(&root.join("Cargo.lock"))?;
    let text = format!(
        "{{\n  \"experiment\": \"RDC-C-004\",\n  \"run_id\": \"{}\",\n  \"seed\": \"0x{:X}\",\n  \"episode_count\": {},\n  \"budgets\": {:?},\n  \"experiment002_baseline_manifest_blake3\": \"{}\",\n  \"cargo_lock_blake3\": \"{}\",\n  \"artifacts_blake3\": {{\n{}\n  }}\n}}\n",
        run_dir.file_name().unwrap_or_default().to_string_lossy(),
        rdc_experiment_004::episodes::HELDOUT_SEED,
        rdc_experiment_004::episodes::EPISODE_COUNT,
        BUDGETS,
        e2_baseline,
        cargo_lock,
        rows,
    );
    fs::write(run_dir.join("manifest.json"), text)?;
    Ok(())
}

fn hash_file(path: &Path) -> Result<String, Box<dyn Error>> {
    let bytes = fs::read(path)?;
    Ok(blake3::hash(&bytes).to_hex().to_string())
}

fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

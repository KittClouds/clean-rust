use std::{
    collections::BTreeMap,
    error::Error,
    fs::{self, File},
    io::{BufWriter, Read, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use hashbrown::HashMap;
use rdc_experiment_001::DecisionCompiler;
use rdc_experiment_004::Choice;
use rdc_experiment_005::{
    DevelopmentValueModel, Episode, EvalLabel, InspectionTool, Lane, SourceStateStore,
    development_episodes, heldout_episodes, labels_for,
};
use rdc_experiment_005::{
    inspection::{QueryReceiptLog, verify_receipt_log, write_source_fixture},
    report::build_report,
    routing::{
        BUDGETS, make_oracle_plans, make_public_plans, plan_map, validate_exact, write_plans,
    },
    runtime::{RunResult, RunSpec, experiment_schema, run_episode},
};
use serde_json::json;

fn main() -> Result<(), Box<dyn Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let run_root = root.join("artifacts").join("runs");
    fs::create_dir_all(&run_root)?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let run_dir = run_root.join(format!("e005-{nonce}"));
    for subdir in [
        "inputs",
        "development",
        "evaluation",
        "tasks",
        "query-receipts",
    ] {
        fs::create_dir_all(run_dir.join(subdir))?;
    }

    let development = development_episodes();
    let heldout = heldout_episodes();
    if development.len() != 256 || heldout.len() != 256 {
        return Err("E005 bank cardinality mismatch".into());
    }

    write_public_bank(&run_dir.join("inputs/development-public.csv"), &development)?;
    write_public_bank(&run_dir.join("inputs/heldout-public.csv"), &heldout)?;
    write_source_fixture(
        run_dir.join("inputs/development-inspection-source-state.csv"),
        &development,
    )?;
    write_source_fixture(
        run_dir.join("inputs/heldout-inspection-source-state.csv"),
        &heldout,
    )?;
    let development_source = SourceStateStore::load_mmap(
        run_dir.join("inputs/development-inspection-source-state.csv"),
    )?;
    let heldout_source =
        SourceStateStore::load_mmap(run_dir.join("inputs/heldout-inspection-source-state.csv"))?;
    if development_source.len() != development.len() || heldout_source.len() != heldout.len() {
        return Err("source-state fixture cardinality mismatch".into());
    }

    let development_labels =
        labels_for(&development, rdc_experiment_005::episodes::DEVELOPMENT_SEED);
    write_labels(&run_dir.join("development/labels.csv"), &development_labels)?;
    let value_model =
        DevelopmentValueModel::fit(&development, &development_labels, &development_source)?;
    value_model.write_csv(run_dir.join("development/value-model.csv"))?;

    // Public route plans are frozen from public frames and the development value table.
    let public_plans = make_public_plans(&heldout, &BUDGETS, &value_model)?;
    validate_exact(&public_plans, heldout.len())?;
    write_plans(run_dir.join("routing-plans.csv"), &public_plans)?;

    // The held-out label writer runs after public routing plans are persisted.
    let heldout_labels = labels_for(&heldout, rdc_experiment_005::episodes::HELDOUT_SEED);
    write_labels(
        &run_dir.join("evaluation/hidden-labels.csv"),
        &heldout_labels,
    )?;
    let oracle_plans = make_oracle_plans(&heldout, &BUDGETS, &heldout_labels, &heldout_source)?;
    write_plans(
        run_dir.join("evaluation/offline-oracle-plans.csv"),
        &oracle_plans,
    )?;

    let mut all_plans = public_plans;
    all_plans.extend(oracle_plans);
    validate_exact(&all_plans, heldout.len())?;
    let plans = plan_map(&all_plans);
    let label_by_id = heldout_labels
        .iter()
        .map(|label| (label.episode_id, *label))
        .collect::<HashMap<_, _>>();

    let schema = experiment_schema();
    let compiler = DecisionCompiler::compile(&schema)?;
    let trace_path = run_dir.join("run-trace.csv");
    let mut trace = BufWriter::with_capacity(64 * 1024, File::create(&trace_path)?);
    writeln!(
        trace,
        "lane,budget,episode_id,class,inspection_domain,confidence,escalated,active_action,shadow_action,disagreement,witness,resolver_action,selected_action,correct_action,outcome,completed,illegal_commits,rejected,duplicates,missing,replay_ok,replay_identity,task_ns,observer_ns,resolver_ns,query_ns,query_calls,query_cost_units,query_receipt_bytes,task_journal_bytes,action_ledger_bytes,journal_path"
    )?;

    let inspection_tool = InspectionTool::new(&heldout_source);
    let total = Lane::ALL.len() * BUDGETS.len() * heldout.len();
    let mut runs = Vec::with_capacity(total);
    let mut receipt_checks = Vec::with_capacity(Lane::ALL.len() * BUDGETS.len());
    let mut done = 0usize;
    for lane in Lane::ALL {
        for budget in BUDGETS {
            let selected = plans.get(&(lane, budget)).ok_or("routing plan missing")?;
            let receipt_path = run_dir
                .join("query-receipts")
                .join(format!("{}-budget-{budget:03}.rdi", lane.label()));
            let mut receipt_log = QueryReceiptLog::create(&receipt_path, lane, budget)?;
            for episode in &heldout {
                let label = label_by_id
                    .get(&episode.id)
                    .ok_or("held-out label missing")?;
                let run = run_episode(RunSpec {
                    lane,
                    budget,
                    escalated: selected.contains(&episode.id),
                    episode,
                    label,
                    compiler: &compiler,
                    schema: &schema,
                    journal_root: &run_dir.join("tasks"),
                    inspection_tool: &inspection_tool,
                    query_log: &mut receipt_log,
                })?;
                write_trace_row(&mut trace, &run, &run_dir)?;
                runs.push(run);
                done += 1;
                if done.is_multiple_of(128) || done == total {
                    trace.flush()?;
                    eprintln!("completed {done}/{total} tasks");
                }
            }
            receipt_log.close()?;
            let receipt_stats = verify_receipt_log(&receipt_path, &heldout_source)?;
            let valid = receipt_stats.calls == budget;
            if !valid {
                return Err(format!(
                    "{} budget {budget}: expected {budget} query receipts, found {}",
                    lane.label(),
                    receipt_stats.calls
                )
                .into());
            }
            receipt_checks.push((
                lane,
                budget,
                receipt_stats.calls,
                receipt_stats.bytes,
                hex(&receipt_stats.identity),
                valid,
            ));
        }
    }
    trace.flush()?;
    trace.get_ref().sync_all()?;
    if runs.len() != total {
        return Err(format!("expected {total} completed task rows, found {}", runs.len()).into());
    }
    write_receipt_checks(&run_dir.join("query-receipt-replay.csv"), &receipt_checks)?;

    let report = build_report(
        &runs,
        &heldout,
        &heldout_labels,
        &value_model,
        &receipt_checks,
    );
    fs::write(run_dir.join("benchmark-report.md"), &report)?;
    fs::write(root.join("artifacts/benchmark-report.md"), &report)?;
    write_manifest(&root, &run_dir, &heldout)?;
    println!(
        "Experiment 005 report: {}",
        run_dir.join("benchmark-report.md").display()
    );
    println!(
        "Tasks: {}; inspection queries: {}; query receipts verified.",
        runs.len(),
        runs.iter()
            .map(|run| run.query_calls as usize)
            .sum::<usize>()
    );
    Ok(())
}

fn write_public_bank(path: &Path, episodes: &[Episode]) -> Result<(), Box<dyn Error>> {
    let mut writer = BufWriter::with_capacity(16 * 1024, File::create(path)?);
    writeln!(
        writer,
        "episode_id,stratum,class,goal,primary_action,audit_action,primary_revision,audit_revision,primary_age,audit_age,flags,confidence,inspection_domain,public_frame_digest"
    )?;
    for episode in episodes {
        let f = episode.frame.features;
        writeln!(
            writer,
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
            episode.id,
            episode.stratum,
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
            episode.frame.inspection_domain,
            hex(&episode.frame.evidence().digest)
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_labels(path: &Path, labels: &[EvalLabel]) -> Result<(), Box<dyn Error>> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(writer, "episode_id,truth_revision,correct_action")?;
    for label in labels {
        writeln!(
            writer,
            "{},{},{}",
            label.episode_id,
            label.truth_revision,
            label.correct_action.label()
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_receipt_checks(
    path: &Path,
    rows: &[(Lane, usize, usize, u64, String, bool)],
) -> Result<(), Box<dyn Error>> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "lane,budget,query_receipts,receipt_bytes,final_receipt_hash,hash_chain_replay"
    )?;
    for (lane, budget, calls, bytes, identity, valid) in rows {
        writeln!(
            writer,
            "{},{budget},{calls},{bytes},{identity},{valid}",
            lane.label()
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_trace_row(
    file: &mut BufWriter<File>,
    run: &RunResult,
    run_dir: &Path,
) -> Result<(), Box<dyn Error>> {
    let journal = run
        .journal_path
        .strip_prefix(run_dir)
        .unwrap_or(&run.journal_path);
    writeln!(
        file,
        "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
        run.lane.label(),
        run.budget,
        run.episode_id,
        run.class,
        run.inspection_domain,
        run.confidence,
        run.escalated,
        run.active_action.label(),
        run.shadow_action.label(),
        run.active_action != run.shadow_action,
        run.witness,
        run.resolver_action.map_or("none", Choice::label),
        run.selected_action.label(),
        run.correct_action.label(),
        run.outcome,
        run.task_completed,
        run.illegal_commits,
        run.rejected_proposals,
        run.duplicate_actions,
        run.missing_actions,
        run.replay_identity_ok,
        hex(&run.replay_identity),
        run.wall_ns,
        run.observer_ns,
        run.resolver_ns,
        run.query_ns,
        run.query_calls,
        run.query_cost_units,
        run.query_receipt_bytes,
        run.task_journal_bytes,
        run.action_ledger_bytes,
        journal.display()
    )?;
    Ok(())
}

fn write_manifest(root: &Path, run_dir: &Path, episodes: &[Episode]) -> Result<(), Box<dyn Error>> {
    let fixed = [
        "inputs/development-public.csv",
        "inputs/heldout-public.csv",
        "inputs/development-inspection-source-state.csv",
        "inputs/heldout-inspection-source-state.csv",
        "development/labels.csv",
        "development/value-model.csv",
        "routing-plans.csv",
        "evaluation/hidden-labels.csv",
        "evaluation/offline-oracle-plans.csv",
        "query-receipt-replay.csv",
        "run-trace.csv",
        "benchmark-report.md",
    ];
    let mut artifacts = BTreeMap::new();
    for relative in fixed {
        artifacts.insert(relative.to_owned(), hash_file(&run_dir.join(relative))?);
    }
    for lane in Lane::ALL {
        for budget in BUDGETS {
            let relative = format!("query-receipts/{}-budget-{budget:03}.rdi", lane.label());
            artifacts.insert(relative.clone(), hash_file(&run_dir.join(relative))?);
        }
    }
    let mut sources = BTreeMap::new();
    for relative in [
        "Cargo.toml",
        "Cargo.lock",
        "README.md",
        "BASELINE.md",
        "src/lib.rs",
        "src/domain.rs",
        "src/episodes.rs",
        "src/evaluation.rs",
        "src/inspection.rs",
        "src/routing.rs",
        "src/scoring.rs",
        "src/runtime.rs",
        "src/report.rs",
        "src/bin/bench.rs",
        "tests/experiment005.rs",
    ] {
        let path = root.join(relative);
        if path.exists() {
            sources.insert(relative.to_owned(), hash_file(&path)?);
        }
    }
    let text = serde_json::to_vec_pretty(&json!({
        "experiment": "RDC-C-005",
        "run_id": run_dir.file_name().unwrap_or_default().to_string_lossy(),
        "development_seed": format!("0x{:X}", rdc_experiment_005::episodes::DEVELOPMENT_SEED),
        "heldout_seed": format!("0x{:X}", rdc_experiment_005::episodes::HELDOUT_SEED),
        "episode_count": episodes.len(),
        "budgets": BUDGETS,
        "inspection_query_contract": "one query and one hash-chained result receipt per routed episode",
        "trusted_revision_in_authority": false,
        "artifacts_blake3": artifacts,
        "source_blake3": sources,
        "e004_baseline_blake3": hash_file(&root.parent().unwrap_or(root).join("experiment-004/BASELINE.md")).ok(),
    }))?;
    fs::write(run_dir.join("manifest.json"), text)?;
    Ok(())
}

fn hash_file(path: &Path) -> Result<String, Box<dyn Error>> {
    let mut file = File::open(path)?;
    let mut hasher = blake3::Hasher::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hasher.finalize().to_hex().to_string())
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(DIGITS[(byte >> 4) as usize] as char);
        out.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    out
}

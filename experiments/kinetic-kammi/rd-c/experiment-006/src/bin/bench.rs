use std::{
    collections::BTreeMap,
    error::Error,
    fs::{self, File},
    io::{BufWriter, Read, Write},
    path::{Path, PathBuf},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use blake3::Hasher;
use hashbrown::HashMap;
use rdc_experiment_001::DecisionCompiler;
use rdc_experiment_004::Choice;
use rdc_experiment_006::{
    EvalLabel, FeatureValueModel, FrozenDomainTable, InspectionOutcome, InspectionResult,
    InspectionSourceStore, Lane, QueryId, QueryReceiptLog, QuerySimulator, Scenario,
    SmoothedValueModel, development_episodes, heldout_episodes, labels_for,
};
use rdc_experiment_006::{
    episodes::{DEVELOPMENT_SEED, HELDOUT_SEED},
    inspection::{CrashPoint, QueryReceiptStats, verify_receipt_log, write_source_fixture},
    report::{CrashRecoveryResult, build_report, crash_section},
    routing::{BUDGETS, make_plans, plan_map, validate_exact, write_plans},
    runtime::{RunResult, RunSpec, new_compiler, run_episode},
};
use serde_json::json;

const E005_RUN: &str = r"C:\rd-c\experiment-005\artifacts\runs\e005-1790277949554789600";

fn main() -> Result<(), Box<dyn Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let run_root = root.join("artifacts").join("runs");
    fs::create_dir_all(&run_root)?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let run_dir = run_root.join(format!("e006-{nonce}"));
    for subdir in [
        "inputs",
        "inputs/e005-baseline",
        "development",
        "evaluation",
        "tasks",
        "query-receipts",
        "endpoint-cache",
        "crash-recovery",
    ] {
        fs::create_dir_all(run_dir.join(subdir))?;
    }

    let development = development_episodes();
    let heldout = heldout_episodes();
    if development.len() != 256 || heldout.len() != 384 {
        return Err("E006 development/held-out bank cardinality mismatch".into());
    }
    write_public_bank(&run_dir.join("inputs/development-public.csv"), &development)?;
    write_public_bank(&run_dir.join("inputs/heldout-public.csv"), &heldout)?;
    write_source_fixture(
        run_dir.join("inputs/development-source-state.csv"),
        &development,
    )?;
    write_source_fixture(run_dir.join("inputs/heldout-source-state.csv"), &heldout)?;

    let development_source =
        InspectionSourceStore::load_mmap(run_dir.join("inputs/development-source-state.csv"))?;
    let heldout_source =
        InspectionSourceStore::load_mmap(run_dir.join("inputs/heldout-source-state.csv"))?;
    if development_source.len() != development.len() || heldout_source.len() != heldout.len() {
        return Err("source fixture count differs from public bank".into());
    }

    let development_labels = labels_for(&development);
    write_labels(run_dir.join("development/labels.csv"), &development_labels)?;
    let smoothed = SmoothedValueModel::fit(&development, &development_labels, &development_source)?;
    smoothed.write_csv(run_dir.join("development/smoothed-model.csv"))?;
    let feature = FeatureValueModel::fit(&development, &development_labels, &development_source)?;
    feature.write_csv(run_dir.join("development/feature-model.csv"))?;

    let (e005, e005_provenance) = load_e005_domain_table(&run_dir)?;
    if e005.score_milli(1) != 750
        || e005.score_milli(2) != 500
        || e005.score_milli(3) != 1000
        || e005.score_milli(5) != -1000
    {
        return Err("E005 frozen table values differ from its sealed report".into());
    }

    // Route plans are persisted before held-out labels are written or loaded.
    let plans = make_plans(&heldout, &BUDGETS, &e005, &smoothed, &feature)?;
    validate_exact(&plans, &heldout)?;
    write_plans(run_dir.join("routing-plans.csv"), &plans)?;
    let plans_by_lane = plan_map(&plans);
    let heldout_labels = labels_for(&heldout);
    write_labels(
        run_dir.join("evaluation/heldout-labels.csv"),
        &heldout_labels,
    )?;
    let labels_by_id = heldout_labels
        .iter()
        .map(|label| (label.episode_id, *label))
        .collect::<HashMap<_, _>>();

    let (schema, compiler) = new_compiler()?;
    let trace_path = run_dir.join("run-trace.csv");
    let mut trace = BufWriter::with_capacity(64 * 1024, File::create(&trace_path)?);
    writeln!(
        trace,
        "lane,budget,episode_id,domain,scenario,active_action,shadow_action,inspection_outcome,selected_action,reobserve,result_class,completed,illegal_commits,rejected,duplicate_actions,missing_actions,task_action_effects,reobserve_effects,replay_ok,replay_identity,task_ns,query_ns,resolver_ns,task_journal_bytes,action_ledger_bytes,query_id,task_journal"
    )?;

    let mut runs = Vec::with_capacity(4 * BUDGETS.len() * heldout.len() + heldout.len());
    let mut receipt_checks: Vec<(Lane, usize, QueryReceiptStats)> = Vec::with_capacity(16);
    let total = 4 * BUDGETS.len() * heldout.len() + heldout.len();
    let mut completed_rows = 0usize;
    for lane in Lane::ALL {
        let lane_budgets: &[usize] = if lane == Lane::NoInspection {
            &[0]
        } else {
            &BUDGETS
        };
        for budget in lane_budgets {
            let selected = plans_by_lane
                .get(&(lane, *budget))
                .ok_or("route plan missing")?;
            let mut receipt_log = if lane == Lane::NoInspection {
                None
            } else {
                Some(QueryReceiptLog::create(run_dir.join(format!(
                    "query-receipts/{}-budget-{budget:03}.rdi",
                    lane.label()
                )))?)
            };
            let mut endpoint = if lane == Lane::NoInspection {
                None
            } else {
                Some(QuerySimulator::create(
                    run_dir.join(format!(
                        "endpoint-cache/{}-budget-{budget:03}.rds",
                        lane.label()
                    )),
                    &heldout_source,
                )?)
            };

            for episode in &heldout {
                let label = labels_by_id
                    .get(&episode.id)
                    .ok_or("held-out label missing")?;
                let (result, query_ns, resolver_ns, query_id) = if selected.contains(&episode.id) {
                    let query_id =
                        QueryId::from_parts(HELDOUT_SEED, lane.index(), *budget, episode.id);
                    let query_start = Instant::now();
                    let result = receipt_log
                        .as_mut()
                        .ok_or("routed lane has no query journal")?
                        .execute(
                            endpoint
                                .as_mut()
                                .ok_or("routed lane has no query service")?,
                            query_id,
                            episode.id,
                            episode.frame.features.primary_action,
                            CrashPoint::None,
                        )?;
                    let query_ns = query_start.elapsed().as_nanos().min(u64::MAX as u128) as u64;
                    let resolver_start = Instant::now();
                    let resolved = InspectionResult::classify(
                        episode.frame.features.primary_action,
                        result.reply,
                    );
                    let resolver_ns =
                        resolver_start.elapsed().as_nanos().min(u64::MAX as u128) as u64;
                    if resolved != result {
                        return Err("receipt result differs from deterministic resolver".into());
                    }
                    (Some(resolved), query_ns, resolver_ns, Some(query_id))
                } else {
                    (None, 0, 0, None)
                };
                let run = run_episode(RunSpec {
                    lane,
                    budget: *budget,
                    episode,
                    label,
                    result,
                    compiler: &compiler,
                    schema: &schema,
                    journal_root: &run_dir.join("tasks"),
                    task_salt: 0xE006_51A7_0000_0000,
                    query_ns,
                    resolver_ns,
                    query_id,
                })?;
                write_trace_row(&mut trace, &run, &run_dir)?;
                runs.push(run);
                completed_rows += 1;
                if completed_rows.is_multiple_of(192) || completed_rows == total {
                    trace.flush()?;
                    eprintln!("completed {completed_rows}/{total} E006 tasks");
                }
            }

            if let Some(log) = receipt_log.take() {
                log.close()?;
            }
            if let Some(service) = endpoint.take() {
                service.close()?;
            }
            if lane != Lane::NoInspection {
                let relative = format!("query-receipts/{}-budget-{budget:03}.rdi", lane.label());
                let stats = verify_receipt_log(run_dir.join(&relative))?;
                if stats.queries != *budget
                    || stats.outcomes != *budget
                    || stats.charges != *budget
                    || stats.attempts != *budget
                    || stats.retries != 0
                {
                    return Err(format!(
                        "{} budget {budget} query receipt mismatch: {stats:?}",
                        lane.label()
                    )
                    .into());
                }
                let service = QuerySimulator::resume(
                    run_dir.join(format!(
                        "endpoint-cache/{}-budget-{budget:03}.rds",
                        lane.label()
                    )),
                    &heldout_source,
                )?;
                if service.charges != *budget {
                    return Err(format!(
                        "{} budget {budget} endpoint charge mismatch",
                        lane.label()
                    )
                    .into());
                }
                service.close()?;
                receipt_checks.push((lane, *budget, stats));
            }
        }
    }
    trace.flush()?;
    trace.get_ref().sync_all()?;

    let crash_results = run_crash_cases(
        &run_dir,
        &heldout,
        &heldout_labels,
        &heldout_source,
        &compiler,
        &schema,
    )?;
    write_crash_csv(
        run_dir.join("crash-recovery/crash-results.csv"),
        &crash_results,
    )?;

    let mut report = build_report(&runs, &heldout, &e005, &smoothed, &feature, &receipt_checks);
    report.push_str(&crash_section(&crash_results));
    fs::write(run_dir.join("benchmark-report.md"), &report)?;
    fs::write(root.join("artifacts/benchmark-report.md"), &report)?;
    write_receipt_summary(run_dir.join("query-receipt-summary.csv"), &receipt_checks)?;
    write_manifest(&root, &run_dir, &development, &heldout, &e005_provenance)?;

    let illegal = runs.iter().map(|run| run.illegal_commits).sum::<usize>();
    let duplicates = runs.iter().map(|run| run.duplicate_actions).sum::<usize>();
    let missing = runs.iter().map(|run| run.missing_actions).sum::<usize>();
    let replay_failures = runs.iter().filter(|run| !run.replay_identity_ok).count();
    let crash_failures = crash_results
        .iter()
        .filter(|row| !row.replay_ok || row.duplicate_actions > 0 || row.charges != 1)
        .count();
    if illegal != 0
        || duplicates != 0
        || missing != 0
        || replay_failures != 0
        || crash_failures != 0
    {
        return Err(format!("E006 reliability gate failed: illegal={illegal}, duplicates={duplicates}, missing={missing}, replay={replay_failures}, crash={crash_failures}").into());
    }
    println!(
        "E006 completed {} benchmark tasks and {} crash injections.",
        runs.len(),
        crash_results.len()
    );
    println!("Report: {}", run_dir.join("benchmark-report.md").display());
    Ok(())
}

fn load_e005_domain_table(
    run_dir: &Path,
) -> Result<(FrozenDomainTable, serde_json::Value), Box<dyn Error>> {
    let source_root = PathBuf::from(E005_RUN);
    let table_path = source_root.join("development/value-model.csv");
    let manifest_path = source_root.join("manifest.json");
    let manifest: serde_json::Value = serde_json::from_reader(File::open(&manifest_path)?)?;
    let expected = manifest["artifacts_blake3"]["development/value-model.csv"]
        .as_str()
        .ok_or("E005 manifest omits its domain table")?;
    let actual = hash_file(&table_path)?;
    if expected != actual {
        return Err("E005 domain table hash differs from its run manifest".into());
    }
    fs::copy(
        &table_path,
        run_dir.join("inputs/e005-baseline/value-model.csv"),
    )?;
    fs::copy(
        &manifest_path,
        run_dir.join("inputs/e005-baseline/manifest.json"),
    )?;
    fs::copy(
        source_root.join("benchmark-report.md"),
        run_dir.join("inputs/e005-baseline/benchmark-report.md"),
    )?;
    let model = FrozenDomainTable::load_csv(run_dir.join("inputs/e005-baseline/value-model.csv"))?;
    let provenance = json!({
        "run_id": "e005-1790277949554789600",
        "source_run": E005_RUN,
        "domain_table_blake3": actual,
        "source_manifest_blake3": hash_file(&manifest_path)?,
        "routing_rule": "score from the frozen E005 domain table; unseen IDs receive neutral score zero"
    });
    Ok((model, provenance))
}

fn run_crash_cases(
    run_dir: &Path,
    episodes: &[rdc_experiment_006::Episode],
    labels: &[EvalLabel],
    source_store: &InspectionSourceStore,
    compiler: &DecisionCompiler,
    schema: &[rdc_experiment_001::TransitionSpec],
) -> Result<Vec<CrashRecoveryResult>, Box<dyn Error>> {
    let episode = episodes
        .iter()
        .find(|episode| episode.scenario == Scenario::HelpfulContradiction)
        .ok_or("crash fixture episode missing")?;
    let label = labels
        .iter()
        .find(|label| label.episode_id == episode.id)
        .ok_or("crash fixture label missing")?;
    let mut rows = Vec::with_capacity(3);
    for (index, (name, point)) in [
        ("after-intent-before-query", CrashPoint::AfterIntent),
        (
            "after-paid-response-before-outcome-receipt",
            CrashPoint::AfterEndpointResponse,
        ),
        (
            "after-durable-outcome-receipt",
            CrashPoint::AfterOutcomeReceipt,
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let case_dir = run_dir.join("crash-recovery").join(name);
        fs::create_dir_all(case_dir.join("tasks"))?;
        let cache_path = case_dir.join("endpoint-cache.rds");
        let receipt_path = case_dir.join("query-receipts.rdi");
        let query_id = QueryId::from_parts(
            HELDOUT_SEED ^ (index as u64 + 1),
            Lane::MatchedRandom.index(),
            1,
            episode.id,
        );
        let active = episode.frame.features.primary_action;
        let mut source = QuerySimulator::create(&cache_path, source_store)?;
        let mut log = QueryReceiptLog::create(&receipt_path)?;
        if log
            .execute(&mut source, query_id, episode.id, active, point)
            .is_ok()
        {
            return Err(format!("crash point {name} did not interrupt query execution").into());
        }
        log.close()?;
        source.close()?;

        let mut source = QuerySimulator::resume(&cache_path, source_store)?;
        let mut log = QueryReceiptLog::resume(&receipt_path)?;
        let result = log.execute(&mut source, query_id, episode.id, active, CrashPoint::None)?;
        log.close()?;
        source.close()?;
        let stats = verify_receipt_log(&receipt_path)?;
        let cached = QuerySimulator::resume(&cache_path, source_store)?;
        let cache_charges = cached.charges;
        cached.close()?;
        if stats.queries != 1 || stats.outcomes != 1 || stats.charges != 1 || cache_charges != 1 {
            return Err(
                format!("crash case {name} did not recover one paid result: {stats:?}").into(),
            );
        }

        let run = run_episode(RunSpec {
            lane: Lane::MatchedRandom,
            budget: 1,
            episode,
            label,
            result: Some(result),
            compiler,
            schema,
            journal_root: &case_dir.join("tasks"),
            task_salt: 0xE006_CAFE_0000_0000 + index as u64,
            query_ns: 0,
            resolver_ns: 0,
            query_id: Some(query_id),
        })?;
        if run.task_action_effects != 1 || run.duplicate_actions != 0 || !run.replay_identity_ok {
            return Err(format!("crash case {name} duplicated or lost the task action").into());
        }
        rows.push(CrashRecoveryResult {
            point: name,
            queries: stats.queries,
            attempts: stats.attempts,
            retries: stats.retries,
            charges: stats.charges,
            outcomes: stats.outcomes,
            task_action_effects: run.task_action_effects,
            duplicate_actions: run.duplicate_actions,
            replay_ok: run.replay_identity_ok,
        });
    }
    Ok(rows)
}

fn write_public_bank(
    path: &Path,
    episodes: &[rdc_experiment_006::Episode],
) -> Result<(), Box<dyn Error>> {
    let mut writer = BufWriter::with_capacity(16 * 1024, File::create(path)?);
    writeln!(
        writer,
        "episode_id,domain,goal,primary_action,audit_action,primary_revision,audit_revision,primary_age,audit_age,flags,confidence,frame_digest"
    )?;
    for episode in episodes {
        let f = episode.frame.features;
        writeln!(
            writer,
            "{},{},{},{},{},{},{},{},{},{},{},{}",
            episode.id,
            episode.domain,
            f.goal,
            f.primary_action.label(),
            f.audit_action.label(),
            f.primary_revision,
            f.audit_revision,
            f.primary_age,
            f.audit_age,
            f.flags,
            episode.confidence,
            hex(&episode.frame.evidence().digest)
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_labels(path: impl AsRef<Path>, labels: &[EvalLabel]) -> Result<(), Box<dyn Error>> {
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

fn write_trace_row(
    writer: &mut BufWriter<File>,
    run: &RunResult,
    run_dir: &Path,
) -> Result<(), Box<dyn Error>> {
    let path = run
        .task_path
        .strip_prefix(run_dir)
        .unwrap_or(&run.task_path);
    let query_id = run
        .query_id
        .map_or_else(|| "none".to_owned(), |id| hex(&id.0));
    writeln!(
        writer,
        "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
        run.lane.label(),
        run.budget,
        run.episode_id,
        run.domain,
        run.scenario,
        run.active_action.label(),
        run.shadow_action.label(),
        run.inspection_outcome
            .map_or("none", InspectionOutcome::label),
        run.selected_action.map_or("reobserve", Choice::label),
        run.reobserve,
        run.outcome,
        run.task_completed,
        run.illegal_commits,
        run.rejected_proposals,
        run.duplicate_actions,
        run.missing_actions,
        run.task_action_effects,
        run.reobserve_effects,
        run.replay_identity_ok,
        hex(&run.replay_identity),
        run.wall_ns,
        run.query_ns,
        run.resolver_ns,
        run.task_journal_bytes,
        run.action_ledger_bytes,
        query_id,
        path.display()
    )?;
    Ok(())
}

fn write_receipt_summary(
    path: impl AsRef<Path>,
    rows: &[(Lane, usize, QueryReceiptStats)],
) -> Result<(), Box<dyn Error>> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "lane,budget,query_intents,endpoint_attempts,retries,paid_charges,result_receipts,unresolved,bytes,final_hash"
    )?;
    for (lane, budget, stats) in rows {
        writeln!(
            writer,
            "{},{budget},{},{},{},{},{},{},{},{}",
            lane.label(),
            stats.queries,
            stats.attempts,
            stats.retries,
            stats.charges,
            stats.outcomes,
            stats.unresolved,
            stats.bytes,
            hex(&stats.identity)
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_crash_csv(
    path: impl AsRef<Path>,
    rows: &[CrashRecoveryResult],
) -> Result<(), Box<dyn Error>> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "crash_boundary,query_intents,endpoint_attempts,retries,paid_charges,result_receipts,task_action_effects,duplicate_actions,replay_ok"
    )?;
    for row in rows {
        writeln!(
            writer,
            "{},{},{},{},{},{},{},{},{}",
            row.point,
            row.queries,
            row.attempts,
            row.retries,
            row.charges,
            row.outcomes,
            row.task_action_effects,
            row.duplicate_actions,
            row.replay_ok
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn write_manifest(
    root: &Path,
    run_dir: &Path,
    development: &[rdc_experiment_006::Episode],
    heldout: &[rdc_experiment_006::Episode],
    e005_provenance: &serde_json::Value,
) -> Result<(), Box<dyn Error>> {
    let mut artifacts = BTreeMap::new();
    for path in collect_files(run_dir)? {
        let relative = path
            .strip_prefix(run_dir)?
            .to_string_lossy()
            .replace('\\', "/");
        if relative != "manifest.json" {
            artifacts.insert(relative, hash_file(&path)?);
        }
    }
    let source_paths = [
        "Cargo.toml",
        "Cargo.lock",
        "README.md",
        "BASELINE.md",
        "src/lib.rs",
        "src/domain.rs",
        "src/episodes.rs",
        "src/evaluation.rs",
        "src/inspection.rs",
        "src/inspection/source.rs",
        "src/inspection/receipts.rs",
        "src/routing.rs",
        "src/scoring.rs",
        "src/runtime.rs",
        "src/report.rs",
        "src/bin/bench.rs",
        "tests/experiment006.rs",
    ];
    let mut sources = BTreeMap::new();
    for relative in source_paths {
        let path = root.join(relative);
        if path.exists() {
            sources.insert(relative.to_owned(), hash_file(&path)?);
        }
    }
    fs::write(
        run_dir.join("manifest.json"),
        serde_json::to_vec_pretty(&json!({
            "experiment": "RDC-C-006",
            "run_id": run_dir.file_name().unwrap_or_default().to_string_lossy(),
            "development_seed": format!("0x{:X}", DEVELOPMENT_SEED),
            "heldout_seed": format!("0x{:X}", HELDOUT_SEED),
            "development_episodes": development.len(),
            "heldout_episodes": heldout.len(),
            "budgets": BUDGETS,
            "typed_outcomes": ["Confirmed", "Contradicted", "Unknown", "Failed"],
            "unknown_failed_policy": "compiled Deciding-to-Observing Recover proposal; no active task action fallback",
            "endpoint_query_idempotency": "simulated durable cache keyed by 128-bit query ID",
            "e005_domain_table_input": e005_provenance,
            "artifacts_blake3": artifacts,
            "source_blake3": sources,
        }))?,
    )?;
    Ok(())
}

fn collect_files(root: &Path) -> Result<Vec<PathBuf>, Box<dyn Error>> {
    let mut files = Vec::with_capacity(64);
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(directory)? {
            let entry = entry?;
            let ty = entry.file_type()?;
            if ty.is_dir() {
                pending.push(entry.path());
            } else if ty.is_file() {
                files.push(entry.path());
            }
        }
    }
    files.sort_unstable();
    Ok(files)
}

fn hash_file(path: &Path) -> Result<String, Box<dyn Error>> {
    let mut file = File::open(path)?;
    let mut hasher = Hasher::new();
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

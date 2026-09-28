use std::{
    collections::{BTreeMap, BTreeSet},
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use rdc_experiment_001::{DecisionCompiler, Signal};
use rdc_experiment_003::{
    Choice, Episode, EpisodeClass, EscalationPolicy, experiment_schema, frozen_observer_pair,
    heldout_episodes, run_episode,
};

const RANDOM_MATCHED_SEED: u64 = 0x5244_4303_5EED_0001;
const RANDOM_MATCHED_RECIPE: &str =
    "BLAKE3(seed || episode_id), ascending digest, first D episodes";

fn main() -> Result<(), Box<dyn Error>> {
    let episodes = heldout_episodes();
    let schema = experiment_schema();
    let compiler = DecisionCompiler::compile(&schema)?;
    let plan = route_plan(&episodes);
    let disagreement_calls = plan.values().filter(|p| p.disagreement).count();
    let random_matched = matched_random_set(&episodes, disagreement_calls);
    let run_root = create_run_root()?;
    let journal_root = run_root.join("journals");
    fs::create_dir_all(&journal_root)?;

    let inputs = input_csv(&episodes);
    let labels = label_csv(&episodes);
    let route_plan_csv = route_plan_csv(&episodes, &plan, &random_matched);
    fs::write(run_root.join("heldout-inputs.csv"), &inputs)?;
    fs::write(run_root.join("heldout-labels.csv"), &labels)?;
    fs::write(run_root.join("route-plan.csv"), &route_plan_csv)?;

    let mut results: BTreeMap<&'static str, Vec<rdc_experiment_003::RunResult>> =
        EscalationPolicy::ALL
            .into_iter()
            .map(|policy| (policy.label(), Vec::with_capacity(episodes.len())))
            .collect();
    for episode in &episodes {
        for policy in EscalationPolicy::ALL {
            let random_call = random_matched.contains(&episode.id);
            let row = run_episode(
                policy,
                random_call,
                *episode,
                &compiler,
                &schema,
                &journal_root,
                0x5244_4303_0000_0000,
            )?;
            results.get_mut(policy.label()).unwrap().push(row);
        }
    }

    if random_matched.len() != disagreement_calls {
        return Err("random escalation count does not match disagreement call count".into());
    }
    let traces = decision_trace_csv(&results);
    fs::write(run_root.join("decision-traces.csv"), &traces)?;

    let report = build_report(ReportInput {
        episodes: &episodes,
        results: &results,
        plan: &plan,
        random_matched: &random_matched,
        inputs: &inputs,
        labels: &labels,
        route_plan: &route_plan_csv,
        traces: &traces,
        run_root: &run_root,
    });
    fs::write(run_root.join("benchmark-report.md"), &report)?;
    fs::write(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("artifacts")
            .join("benchmark-report.md"),
        &report,
    )?;
    write_run_manifest(&run_root, &episodes, &inputs, &labels, &route_plan_csv)?;
    print!("{report}");
    eprintln!("run artifacts: {}", run_root.display());
    Ok(())
}

#[derive(Clone, Copy)]
struct PlannedEpisode {
    active: Choice,
    shadow: Choice,
    confidence: u16,
    disagreement: bool,
}

struct ReportInput<'a> {
    episodes: &'a [Episode],
    results: &'a BTreeMap<&'static str, Vec<rdc_experiment_003::RunResult>>,
    plan: &'a BTreeMap<u32, PlannedEpisode>,
    random_matched: &'a BTreeSet<u32>,
    inputs: &'a str,
    labels: &'a str,
    route_plan: &'a str,
    traces: &'a str,
    run_root: &'a Path,
}

fn route_plan(episodes: &[Episode]) -> BTreeMap<u32, PlannedEpisode> {
    episodes
        .iter()
        .map(|episode| {
            let observation = episode.observation(Signal::Approve);
            let (active, shadow) = frozen_observer_pair(&observation)
                .expect("generated observation satisfies the frozen observer contract");
            let active_choice = Choice::from_action(active.action).expect("domain action");
            let shadow_choice = Choice::from_action(shadow.action).expect("domain action");
            (
                episode.id,
                PlannedEpisode {
                    active: active_choice,
                    shadow: shadow_choice,
                    confidence: active.confidence.unwrap_or(0),
                    disagreement: active.action != shadow.action,
                },
            )
        })
        .collect()
}

fn matched_random_set(episodes: &[Episode], target_count: usize) -> BTreeSet<u32> {
    let mut ranked = episodes
        .iter()
        .map(|episode| {
            let mut hasher = blake3::Hasher::new();
            hasher.update(&RANDOM_MATCHED_SEED.to_le_bytes());
            hasher.update(&episode.id.to_le_bytes());
            (*hasher.finalize().as_bytes(), episode.id)
        })
        .collect::<Vec<_>>();
    ranked.sort_unstable_by_key(|(hash, _)| *hash);
    ranked
        .into_iter()
        .take(target_count)
        .map(|(_, episode_id)| episode_id)
        .collect()
}

fn create_run_root() -> Result<PathBuf, Box<dyn Error>> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
    let artifact_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("artifacts/runs");
    fs::create_dir_all(&artifact_root)?;
    for suffix in 0..100u8 {
        let path = artifact_root.join(format!("run-{now}-{suffix:02}"));
        match fs::create_dir(&path) {
            Ok(()) => return Ok(path),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error.into()),
        }
    }
    Err("could not allocate a unique artifact run directory".into())
}

fn input_csv(episodes: &[Episode]) -> String {
    let mut output = String::from(
        "episode_id,goal,world_revision,primary_action,audit_action,flags,confidence\n",
    );
    for episode in episodes {
        output.push_str(&format!(
            "{},{},{},{},{},{},{}\n",
            episode.id,
            episode.features.goal,
            episode.features.world_revision,
            episode.features.primary_action.label(),
            episode.features.audit_action.label(),
            episode.features.flags,
            episode.confidence,
        ));
    }
    output
}

fn label_csv(episodes: &[Episode]) -> String {
    let mut output = String::from("episode_id,scenario,correct_action\n");
    for episode in episodes {
        output.push_str(&format!(
            "{},{},{}\n",
            episode.id,
            episode.class.label(),
            episode.correct_action.label(),
        ));
    }
    output
}

fn route_plan_csv(
    episodes: &[Episode],
    plan: &BTreeMap<u32, PlannedEpisode>,
    random_matched: &BTreeSet<u32>,
) -> String {
    let mut output = String::from(
        "episode_id,raw_active,raw_shadow,action_disagreement,active_confidence,random_matched_call\n",
    );
    for episode in episodes {
        let row = plan[&episode.id];
        output.push_str(&format!(
            "{},{},{},{},{},{}\n",
            episode.id,
            row.active.label(),
            row.shadow.label(),
            row.disagreement,
            row.confidence,
            random_matched.contains(&episode.id),
        ));
    }
    output
}

fn decision_trace_csv(
    results: &BTreeMap<&'static str, Vec<rdc_experiment_003::RunResult>>,
) -> String {
    let mut output = String::from(
        "policy,episode_id,scenario,correct_action,raw_active,raw_shadow,disagreement,escalated,resolver_action,selected_action,task_completed,wrong_legal_action,rejected_proposals,illegal_commits,duplicate_actions,missing_actions,replay_identity_ok,replay_identity,wall_ns,observer_a_ns,observer_b_ns,routing_ns,resolver_ns,journal_bytes,action_bytes,e2_journal_path\n",
    );
    for policy in EscalationPolicy::ALL {
        for row in &results[policy.label()] {
            output.push_str(&format!(
                "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}\n",
                policy.label(),
                row.episode_id,
                row.class,
                row.correct_action.label(),
                row.raw_active.label(),
                row.raw_shadow.label(),
                row.action_disagreement,
                row.escalated,
                row.resolver_action.map_or("none", Choice::label),
                row.selected_action.label(),
                row.task_completed,
                row.wrong_legal_action,
                row.rejected_proposals,
                row.illegal_commits,
                row.duplicate_actions,
                row.missing_actions,
                row.replay_identity_ok,
                hex(&row.replay_identity),
                row.wall_ns,
                row.observer_a_ns,
                row.observer_b_ns,
                row.routing_ns,
                row.resolver_ns,
                row.journal_bytes,
                row.action_bytes,
                row.e2_journal.display(),
            ));
        }
    }
    output
}

fn build_report(input: ReportInput<'_>) -> String {
    let ReportInput {
        episodes,
        results,
        plan,
        random_matched,
        inputs,
        labels,
        route_plan,
        traces,
        run_root,
    } = input;
    let mut report = String::new();
    report.push_str("# R&D-C / Experiment 003 — Disagreement Gate\n\n");
    report.push_str(&format!(
        "Held-out synthetic workflow bank: {} episodes; seed `0x{:X}`; four paired lanes; same episode IDs and observation prefixes in every lane.\n\n",
        episodes.len(),
        rdc_experiment_003::episodes::HELDOUT_SEED,
    ));
    report.push_str("The task contract independently maps `(goal, authoritative world revision)` to one correct domain action. The label writer uses that contract; neither observer nor routing policy receives the labels. The frozen resolver reads the same recorded goal and revision and does not receive observer proposals. Observers, resolver, confidence threshold, and matched-random seed were fixed before scoring.\n\n");
    report.push_str("Candidate actions map to legal Experiment 002 transitions from `DECIDING` to `ACTING`: `Execute` = `use_primary`, `Verify` = `verify_record`, and `Observe` = `refresh_snapshot`. All three are accepted by the experiment's compiled schema; only the task-contract action advances the episode. Thus wrong-action counts are legal-but-unhelpful actions, while illegal commits are checked separately against the compiled schema.\n\n");
    report.push_str("## Outcomes and authority gate\n\n");
    report.push_str("| Policy | Completion | Wrong legal actions | Escalation precision | Resolver correct / calls | Resolver calls | Illegal commits | Rejected proposals | Duplicate / missing actions | Replay identity |\n");
    report.push_str("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n");
    for policy in EscalationPolicy::ALL {
        let rows = &results[policy.label()];
        let completed = rows.iter().filter(|row| row.task_completed).count();
        let wrong = rows.iter().filter(|row| row.wrong_legal_action).count();
        let calls = rows.iter().filter(|row| row.escalated).count();
        let wrong_at_escalation = rows
            .iter()
            .filter(|row| row.escalated && row.raw_active != row.correct_action)
            .count();
        let resolver_correct = rows
            .iter()
            .filter(|row| row.escalated && row.resolver_action == Some(row.correct_action))
            .count();
        let precision = if calls == 0 {
            "n/a".to_owned()
        } else {
            format!(
                "{wrong_at_escalation}/{calls} ({:.1}%)",
                100.0 * wrong_at_escalation as f64 / calls as f64
            )
        };
        let illegal = rows.iter().map(|row| row.illegal_commits).sum::<usize>();
        let rejected = rows.iter().map(|row| row.rejected_proposals).sum::<usize>();
        let duplicates = rows.iter().map(|row| row.duplicate_actions).sum::<usize>();
        let missing = rows.iter().map(|row| row.missing_actions).sum::<usize>();
        let replay = rows.iter().filter(|row| row.replay_identity_ok).count();
        report.push_str(&format!(
            "| {} | {completed}/{} ({:.1}%) | {wrong}/{} ({:.1}%) | {} | {resolver_correct}/{calls} | {calls} | {illegal} | {rejected} | {duplicates} / {missing} | {replay}/{} |\n",
            policy.label(),
            episodes.len(),
            100.0 * completed as f64 / episodes.len() as f64,
            episodes.len(),
            100.0 * wrong as f64 / episodes.len() as f64,
            precision,
            episodes.len(),
        ));
    }

    let disagreements = plan.values().filter(|row| row.disagreement).count();
    let agree_cases = plan.values().filter(|row| !row.disagreement).count();
    let agree_wrong = episodes
        .iter()
        .filter(|episode| {
            let row = plan[&episode.id];
            !row.disagreement && row.active != episode.correct_action
        })
        .count();
    let disagreement_wrong = episodes
        .iter()
        .filter(|episode| {
            let row = plan[&episode.id];
            row.disagreement && row.active != episode.correct_action
        })
        .count();
    report.push_str(&format!(
        "\nRaw observer action disagreement: {disagreements}/{} episodes. When the observers agreed, the active observer was wrong in {agree_wrong}/{agree_cases} cases ({:.1}%). When they disagreed, the active observer was wrong in {disagreement_wrong}/{disagreements} cases ({:.1}%). The random lane escalated exactly {}/{disagreements} episodes using `{RANDOM_MATCHED_RECIPE}` with seed `0x{RANDOM_MATCHED_SEED:X}`; the schedule was formed without reading labels.\n\n",
        episodes.len(),
        100.0 * agree_wrong as f64 / agree_cases as f64,
        100.0 * disagreement_wrong as f64 / disagreements as f64,
        random_matched.len(),
    ));

    report.push_str("## Cost and runtime\n\n");
    report.push_str("Task wall time includes E002 task and action journal creation, every durable write, the complete workflow, close, and verification replay. Observer and routing time are reported separately. Resolver percentiles use escalated tasks only. Sub-microsecond timings are sampled per call at the Windows `Instant` clock resolution; a displayed `0.000` is below that elapsed-time resolution, not zero work. This v0 resolver is deterministic local code, so it consumes zero model tokens and incurs `$0` model/API cost; wall time is the local compute cost proxy.\n\n");
    report.push_str("| Policy | p50/p95 task wall ms | p50/p95 observer A us | p50/p95 observer B us | p50/p95 routing us | p50/p95 resolver us/call | Mean ms / completed task | Journal / action bytes per task | Tokens / task | Model cost / completed task |\n");
    report.push_str("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n");
    for policy in EscalationPolicy::ALL {
        let rows = &results[policy.label()];
        let task_ns = rows.iter().map(|row| row.wall_ns).collect::<Vec<_>>();
        let resolver_ns = rows
            .iter()
            .filter(|row| row.escalated)
            .map(|row| row.resolver_ns as u128)
            .collect::<Vec<_>>();
        let observer_a_ns = rows
            .iter()
            .map(|row| row.observer_a_ns as u128)
            .collect::<Vec<_>>();
        let observer_b_ns = rows
            .iter()
            .map(|row| row.observer_b_ns as u128)
            .collect::<Vec<_>>();
        let routing_ns = rows
            .iter()
            .map(|row| row.routing_ns as u128)
            .collect::<Vec<_>>();
        let completions = rows.iter().filter(|row| row.task_completed).count();
        let mean_task_ms = rows.iter().map(|row| row.wall_ns).sum::<u128>() as f64
            / rows.len() as f64
            / 1_000_000.0;
        let per_completed = mean_task_ms * rows.len() as f64 / completions.max(1) as f64;
        let journal_bytes = rows
            .iter()
            .map(|row| row.journal_bytes as u128)
            .sum::<u128>()
            / rows.len() as u128;
        let action_bytes = rows
            .iter()
            .map(|row| row.action_bytes as u128)
            .sum::<u128>()
            / rows.len() as u128;
        let resolver_percentiles = if resolver_ns.is_empty() {
            "n/a".to_owned()
        } else {
            format!(
                "{:.3}/{:.3}",
                percentile(&resolver_ns, 0.50) as f64 / 1000.0,
                percentile(&resolver_ns, 0.95) as f64 / 1000.0,
            )
        };
        report.push_str(&format!(
            "| {} | {:.3}/{:.3} | {:.3}/{:.3} | {:.3}/{:.3} | {:.3}/{:.3} | {} | {:.3} | {journal_bytes} / {action_bytes} | 0 | $0.000000 |\n",
            policy.label(),
            percentile(&task_ns, 0.50) as f64 / 1_000_000.0,
            percentile(&task_ns, 0.95) as f64 / 1_000_000.0,
            percentile(&observer_a_ns, 0.50) as f64 / 1000.0,
            percentile(&observer_a_ns, 0.95) as f64 / 1000.0,
            percentile(&observer_b_ns, 0.50) as f64 / 1000.0,
            percentile(&observer_b_ns, 0.95) as f64 / 1000.0,
            percentile(&routing_ns, 0.50) as f64 / 1000.0,
            percentile(&routing_ns, 0.95) as f64 / 1000.0,
            resolver_percentiles,
            per_completed,
        ));
    }

    report.push_str("\n## Error breakdown, including observer agreement\n\n");
    report.push_str("| Held-out stratum | Episodes | Raw disagreement | Active observer wrong | Never completion | Disagreement completion | Confidence completion | Random matched completion |\n");
    report.push_str("|---|---:|---:|---:|---:|---:|---:|---:|\n");
    for (class, _) in EpisodeClass::ALL {
        let group = episodes
            .iter()
            .filter(|episode| episode.class == class)
            .collect::<Vec<_>>();
        let ids = group
            .iter()
            .map(|episode| episode.id)
            .collect::<BTreeSet<_>>();
        let disagreement = group
            .iter()
            .filter(|episode| plan[&episode.id].disagreement)
            .count();
        let active_wrong = group
            .iter()
            .filter(|episode| plan[&episode.id].active != episode.correct_action)
            .count();
        let completed = |policy: EscalationPolicy| {
            results[policy.label()]
                .iter()
                .filter(|row| ids.contains(&row.episode_id) && row.task_completed)
                .count()
        };
        report.push_str(&format!(
            "| {} | {} | {} | {} | {}/{} | {}/{} | {}/{} | {}/{} |\n",
            class.label(),
            group.len(),
            disagreement,
            active_wrong,
            completed(EscalationPolicy::Never),
            group.len(),
            completed(EscalationPolicy::Disagreement),
            group.len(),
            completed(EscalationPolicy::ConfidenceThreshold),
            group.len(),
            completed(EscalationPolicy::RandomMatched),
            group.len(),
        ));
    }

    let disagreement = &results[EscalationPolicy::Disagreement.label()];
    let random = &results[EscalationPolicy::RandomMatched.label()];
    let disagreement_wrong = disagreement
        .iter()
        .filter(|row| row.wrong_legal_action)
        .count();
    let random_wrong = random.iter().filter(|row| row.wrong_legal_action).count();
    let disagreement_done = disagreement.iter().filter(|row| row.task_completed).count();
    let random_done = random.iter().filter(|row| row.task_completed).count();
    let confidence = &results[EscalationPolicy::ConfidenceThreshold.label()];
    let confidence_wrong = confidence
        .iter()
        .filter(|row| row.wrong_legal_action)
        .count();
    let confidence_done = confidence.iter().filter(|row| row.task_completed).count();
    let confidence_calls = confidence.iter().filter(|row| row.escalated).count();
    let all_lanes_clean = results.values().all(|rows| {
        rows.iter().all(|row| {
            row.illegal_commits == 0
                && row.duplicate_actions == 0
                && row.missing_actions == 0
                && row.replay_identity_ok
        })
    });
    let gate_pass = all_lanes_clean
        && random_matched.len() == disagreements
        && disagreement_wrong < random_wrong
        && disagreement_done > random_done;
    report.push_str("\n## Promotion gate\n\n");
    report.push_str(&format!(
        "Gate result: **{} vs matched random** for this held-out synthetic bank. Disagreement routing selected {disagreement_wrong} wrong legal actions and completed {disagreement_done}/{} tasks; matched-random selected {random_wrong} wrong legal actions and completed {random_done}/{} tasks with the same {} resolver calls. Confidence threshold used {confidence_calls} calls and performed better in absolute outcomes ({confidence_wrong} wrong actions; {confidence_done}/{} complete), at {} more calls than disagreement routing. All four lanes had zero illegal commits, duplicate actions, and missing actions, and every task replay identity matched.\n\n",
        if gate_pass { "PASS" } else { "DO NOT PROMOTE" },
        episodes.len(),
        episodes.len(),
        disagreements,
        episodes.len(),
        confidence_calls.saturating_sub(disagreements),
    ));
    report.push_str("This result applies only to the predeclared synthetic workflow bank and frozen deterministic proxy observers/resolver. It demonstrates whether the harness can distinguish targeted routing from call-matched random routing; it does not establish performance for learned observers or a large deliberator.\n\n");
    report.push_str("## Frozen components and provenance\n\n");
    report.push_str(&format!(
        "- Observer A: `tool-follow/v1`; observer B: `audit-filter/v1`; resolver: `workflow-contract-resolver/v1`.\n- Confidence threshold: `{}` (escalate below threshold).\n- Episode and label artifacts: `heldout-inputs.csv`, `heldout-labels.csv`; route schedule: `route-plan.csv`; every E002 lane journal and action ledger are retained under `journals/`.\n- Run directory: `{}`.\n- Digests: inputs `{}`, labels `{}`, route plan `{}`, traces `{}`.\n",
        rdc_experiment_003::routing::CONFIDENCE_THRESHOLD,
        run_root.display(),
        blake3::hash(inputs.as_bytes()).to_hex(),
        blake3::hash(labels.as_bytes()).to_hex(),
        blake3::hash(route_plan.as_bytes()).to_hex(),
        blake3::hash(traces.as_bytes()).to_hex(),
    ));
    report.push_str("\n## Limits\n\n");
    report.push_str("The lane journals use Experiment 002's compiled authority, mmap-backed replay, hash-chained journal, durable action intent/completion protocol, and idempotent simulator. The experiment schema adds two legal typed candidate actions at the decision state and removes the confidence guard from those three candidate transitions so confidence routing is evaluated as a policy rather than re-tested as authority. E002's legacy `illegal_commits` convenience counter assumes only the original standard schema; this report independently checks every accepted receipt against the compiled Experiment 003 schema.\n");
    report
}

fn percentile(values: &[u128], fraction: f64) -> u128 {
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let rank = ((sorted.len() as f64 * fraction).ceil() as usize)
        .max(1)
        .min(sorted.len());
    sorted[rank - 1]
}

fn write_run_manifest(
    run_root: &Path,
    episodes: &[Episode],
    inputs: &str,
    labels: &str,
    route_plan: &str,
) -> Result<(), Box<dyn Error>> {
    let observer_hash = blake3::hash(include_bytes!("../routing.rs")).to_hex();
    let episode_hash = blake3::hash(include_bytes!("../episodes.rs")).to_hex();
    let harness_hash = blake3::hash(include_bytes!("../evaluation.rs")).to_hex();
    let benchmark_hash = blake3::hash(include_bytes!("bench.rs")).to_hex();
    let manifest = format!(
        "experiment=RDC-C-003\nheldout_seed=0x{:X}\nepisode_count={}\nobserver_and_resolver_source_blake3={}\nepisode_generator_and_label_source_blake3={}\nruntime_harness_source_blake3={}\nbenchmark_source_blake3={}\ninputs_blake3={}\nlabels_blake3={}\nroute_plan_blake3={}\nrandom_matched_seed=0x{:X}\nrandom_matched_recipe={}\n",
        rdc_experiment_003::episodes::HELDOUT_SEED,
        episodes.len(),
        observer_hash,
        episode_hash,
        harness_hash,
        benchmark_hash,
        blake3::hash(inputs.as_bytes()).to_hex(),
        blake3::hash(labels.as_bytes()).to_hex(),
        blake3::hash(route_plan.as_bytes()).to_hex(),
        RANDOM_MATCHED_SEED,
        RANDOM_MATCHED_RECIPE,
    );
    fs::write(run_root.join("run-manifest.txt"), manifest)?;
    Ok(())
}

fn hex(bytes: &[u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

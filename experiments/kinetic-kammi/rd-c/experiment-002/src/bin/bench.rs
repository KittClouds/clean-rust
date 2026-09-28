use std::{
    error::Error,
    fs,
    path::PathBuf,
    sync::Arc,
    sync::atomic::{AtomicU64, Ordering},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use rdc_experiment_001::{DecisionCompiler, Observation, Signal, State, standard_schema};
use rdc_experiment_002::{
    Authority, CompiledAuthority, CrashPoint, HandwrittenAuthority, ObserverSwitchboard,
    TaskMetrics, TaskRunner, TaskRunnerError, WorkflowAdapter, WorkflowBehavior,
};

const TASKS_PER_LANE: usize = 20;
static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

const NOMINAL: &[Signal] = &[
    Signal::Start,
    Signal::Observed,
    Signal::Approve,
    Signal::ActionSucceeded,
    Signal::Verified,
];
const RECOVERY: &[Signal] = &[
    Signal::Start,
    Signal::Observed,
    Signal::Approve,
    Signal::ActionFailed,
    Signal::Recover,
    Signal::Observed,
    Signal::Approve,
    Signal::ActionSucceeded,
    Signal::Verified,
];
const ILLEGAL: &[Signal] = &[
    Signal::Unexpected,
    Signal::Start,
    Signal::Observed,
    Signal::Approve,
    Signal::ActionSucceeded,
    Signal::Verified,
];
const SWAP: &[Signal] = &[
    Signal::Start,
    Signal::Observed,
    Signal::Approve,
    Signal::Approve,
    Signal::ActionSucceeded,
    Signal::Verified,
];
const CRASH_POINTS: &[(usize, CrashPoint)] = &[
    (0, CrashPoint::AfterTransitionReceipt),
    (1, CrashPoint::AfterActionIntent),
    (2, CrashPoint::AfterActionEffect),
    (3, CrashPoint::AfterActionCompletion),
];

#[derive(Clone, Copy)]
struct Plan {
    name: &'static str,
    signals: &'static [Signal],
    active: WorkflowBehavior,
    active_id: &'static str,
    shadow: WorkflowBehavior,
    shadow_id: &'static str,
    crash_points: &'static [(usize, CrashPoint)],
    swap_after_step: Option<usize>,
    swapped_active: WorkflowBehavior,
    swapped_active_id: &'static str,
}

const PLANS: [Plan; 6] = [
    Plan {
        name: "nominal",
        signals: NOMINAL,
        active: WorkflowBehavior::Normal,
        active_id: "workflow/v1",
        shadow: WorkflowBehavior::Normal,
        shadow_id: "shadow/workflow-v1",
        crash_points: &[],
        swap_after_step: None,
        swapped_active: WorkflowBehavior::Normal,
        swapped_active_id: "workflow/v1",
    },
    Plan {
        name: "recovery",
        signals: RECOVERY,
        active: WorkflowBehavior::Normal,
        active_id: "workflow/v1",
        shadow: WorkflowBehavior::Normal,
        shadow_id: "shadow/workflow-v1",
        crash_points: &[],
        swap_after_step: None,
        swapped_active: WorkflowBehavior::Normal,
        swapped_active_id: "workflow/v1",
    },
    Plan {
        name: "illegal proposal",
        signals: ILLEGAL,
        active: WorkflowBehavior::Normal,
        active_id: "workflow/v1",
        shadow: WorkflowBehavior::Normal,
        shadow_id: "shadow/workflow-v1",
        crash_points: &[],
        swap_after_step: None,
        swapped_active: WorkflowBehavior::Normal,
        swapped_active_id: "workflow/v1",
    },
    Plan {
        name: "shadow disagreement",
        signals: NOMINAL,
        active: WorkflowBehavior::Normal,
        active_id: "workflow/v1",
        shadow: WorkflowBehavior::MisrouteApprove,
        shadow_id: "shadow/misroute-v1",
        crash_points: &[],
        swap_after_step: None,
        swapped_active: WorkflowBehavior::Normal,
        swapped_active_id: "workflow/v1",
    },
    Plan {
        name: "crash and resume",
        signals: NOMINAL,
        active: WorkflowBehavior::Normal,
        active_id: "workflow/v1",
        shadow: WorkflowBehavior::MisrouteApprove,
        shadow_id: "shadow/misroute-v1",
        crash_points: CRASH_POINTS,
        swap_after_step: None,
        swapped_active: WorkflowBehavior::Normal,
        swapped_active_id: "workflow/v1",
    },
    Plan {
        name: "observer swap",
        signals: SWAP,
        active: WorkflowBehavior::MisrouteApprove,
        active_id: "misrouter/v1",
        shadow: WorkflowBehavior::Normal,
        shadow_id: "shadow/workflow-v1",
        crash_points: &[],
        swap_after_step: Some(2),
        swapped_active: WorkflowBehavior::Normal,
        swapped_active_id: "repaired-router/v1",
    },
];

struct TempFiles {
    directory: PathBuf,
    journal: PathBuf,
    actions: PathBuf,
}

impl TempFiles {
    fn new(task_id: u64) -> Self {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let nonce = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
        let directory =
            std::env::temp_dir().join(format!("rdc002-bench-{task_id}-{stamp}-{nonce}"));
        fs::create_dir_all(&directory).expect("create benchmark directory");
        Self {
            journal: directory.join("task.journal"),
            actions: directory.join("actions.ledger"),
            directory,
        }
    }
}

impl Drop for TempFiles {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

struct TaskResult {
    task_ns: u128,
    metrics: TaskMetrics,
    process_resumes: usize,
    replay_ok: bool,
    final_state: State,
    receipt_hashes: Vec<[u8; 32]>,
}

fn board(active_behavior: WorkflowBehavior, active_id: &str, plan: Plan) -> ObserverSwitchboard {
    ObserverSwitchboard::new(
        Box::new(WorkflowAdapter::new(active_id, active_behavior)),
        Box::new(WorkflowAdapter::new(plan.shadow_id, plan.shadow)),
    )
    .expect("benchmark observer contracts are valid")
}

fn observation(signal: Signal) -> Observation {
    let mut value = Observation::new(signal);
    if signal != Signal::Start {
        value = value.with_evidence(rdc_experiment_001::Evidence {
            code: 33,
            digest: [0x33; 16],
        });
    }
    if matches!(signal, Signal::Approve | Signal::Recover) {
        value = value.with_confidence(900);
    }
    value
}

fn run_task<A, F>(
    plan: Plan,
    task_id: u64,
    authority_factory: F,
) -> Result<TaskResult, Box<dyn Error>>
where
    A: Authority,
    F: Fn() -> A,
{
    let files = TempFiles::new(task_id);
    let started = Instant::now();
    let mut active_behavior = plan.active;
    let mut active_id = plan.active_id;
    let mut process_resumes = 0usize;
    let mut runner = TaskRunner::create(
        authority_factory(),
        board(active_behavior, active_id, plan),
        task_id,
        &files.journal,
        &files.actions,
    )?;

    for (step, signal) in plan.signals.iter().copied().enumerate() {
        let crash = plan
            .crash_points
            .iter()
            .find(|(crash_step, _)| *crash_step == step)
            .map(|(_, point)| *point);
        match runner.step(&observation(signal), crash) {
            Ok(_) if crash.is_none() => {}
            Err(TaskRunnerError::InjectedCrash(actual)) if Some(actual) == crash => {
                drop(runner);
                // SAFETY: dropping runner closes the writers before read-only mapped replay.
                runner = unsafe {
                    TaskRunner::resume(
                        authority_factory(),
                        board(active_behavior, active_id, plan),
                        task_id,
                        &files.journal,
                        &files.actions,
                    )?
                };
                process_resumes += 1;
            }
            Ok(_) => return Err("expected crash injection did not fire".into()),
            Err(error) => return Err(Box::new(error)),
        }

        if plan.swap_after_step == Some(step) {
            active_behavior = plan.swapped_active;
            active_id = plan.swapped_active_id;
            runner.replace_active(Box::new(WorkflowAdapter::new(active_id, active_behavior)))?;
        }
    }

    let metrics = runner.metrics();
    let final_state = runner.state();
    let receipt_hashes = runner
        .receipts()
        .iter()
        .map(|receipt| receipt.hash)
        .collect::<Vec<_>>();
    runner.close()?;
    let task_ns = started.elapsed().as_nanos();

    // Replay and compare after task time is captured. Journal durability costs remain inside task time.
    // SAFETY: the task runner closed both writers and this function owns both files.
    let replayed = unsafe {
        TaskRunner::resume(
            authority_factory(),
            board(active_behavior, active_id, plan),
            task_id,
            &files.journal,
            &files.actions,
        )?
    };
    let replay_metrics = replayed.metrics();
    let replay_receipts = replayed
        .receipts()
        .iter()
        .map(|receipt| receipt.hash)
        .collect::<Vec<_>>();
    let replay_ok = replayed.state() == final_state
        && replay_metrics.replay_identity == metrics.replay_identity
        && replay_receipts == receipt_hashes;
    replayed.close()?;

    Ok(TaskResult {
        task_ns,
        metrics,
        process_resumes,
        replay_ok,
        final_state,
        receipt_hashes,
    })
}

fn percentile(values: &[u128], fraction: f64) -> u128 {
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let index = ((sorted.len() as f64 * fraction).ceil() as usize)
        .saturating_sub(1)
        .min(sorted.len() - 1);
    sorted[index]
}

fn average(values: impl Iterator<Item = u128>, count: usize) -> u128 {
    if count == 0 {
        0
    } else {
        values.sum::<u128>() / count as u128
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut report = String::new();
    report.push_str("# R&D-C / Experiment 002 benchmark report\n\n");
    report.push_str(&format!(
        "Platform: {}-{}; logical processors: {}; release build; {} paired tasks per workload.\n\n",
        std::env::consts::ARCH,
        std::env::consts::OS,
        std::thread::available_parallelism().map_or(1, usize::from),
        TASKS_PER_LANE,
    ));
    report.push_str("Each pair reuses the same task ID, observers, observation sequence, action simulator semantics, and fsync journal policy. The hand-written lane uses the Experiment 001 transition match directly; the compiled lane uses its frozen dense table. Task time includes journal creation, durable writes, simulated action effects, crash recovery, and final close, but excludes the post-task verification replay. Observer time is summed from calls and excludes journal writes.\n\n");
    report.push_str("| Workload | Controller | Completion | Illegal commits | Rejected proposals | Duplicate actions | Missing actions | Replay identity | Paired state/receipts | Shadow disagreements/task | Workflow recoveries/task | Process resumes/task | p50/p95 task us | p50/p95 active observer us | p50/p95 shadow observer us | p50/p95 swap us | Journal bytes/task | Action bytes/task | Idempotent retries |\n");
    report.push_str("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n");

    let compiled_template = Arc::new(DecisionCompiler::compile(&standard_schema())?);
    let compiled_factory = || CompiledAuthority::from_compiler((*compiled_template).clone());

    for (scenario_index, plan) in PLANS.into_iter().enumerate() {
        let mut compiled = Vec::with_capacity(TASKS_PER_LANE);
        let mut manual = Vec::with_capacity(TASKS_PER_LANE);
        let mut paired_matches = 0usize;
        for task_index in 0..TASKS_PER_LANE {
            let task_id = 50_000 + scenario_index as u64 * 10_000 + task_index as u64;
            let (compiled_result, manual_result) = if task_index % 2 == 0 {
                (
                    run_task::<CompiledAuthority, _>(plan, task_id, &compiled_factory)?,
                    run_task::<HandwrittenAuthority, _>(
                        plan,
                        task_id,
                        HandwrittenAuthority::default,
                    )?,
                )
            } else {
                let manual = run_task::<HandwrittenAuthority, _>(
                    plan,
                    task_id,
                    HandwrittenAuthority::default,
                )?;
                let compiled = run_task::<CompiledAuthority, _>(plan, task_id, &compiled_factory)?;
                (compiled, manual)
            };
            paired_matches += usize::from(
                compiled_result.final_state == manual_result.final_state
                    && compiled_result.receipt_hashes == manual_result.receipt_hashes,
            );
            compiled.push(compiled_result);
            manual.push(manual_result);
        }

        add_summary(
            &mut report,
            plan.name,
            "compiled runtime",
            &compiled,
            paired_matches,
        );
        add_summary(
            &mut report,
            plan.name,
            "hand-written baseline",
            &manual,
            paired_matches,
        );
    }

    report.push_str("\n## Interpretation\n\n");
    report.push_str("Observer disagreements are proposals only; active authority alone determines commits and effects. A successful replay means the journal hash chain verified, replayed transition receipts matched, and the final state and receipt sequence were identical. Observer swap time measures implementation replacement itself; its durable registry write is included in task time.\n\n");
    report.push_str("## Crash protocol\n\n");
    report.push_str("The crash workload injects failure after a committed transition receipt, after action intent, after the simulator's durable effect, and after action completion. Resume replays active proposals, resolves incomplete intents with deterministic action IDs, and asks the simulator to deduplicate retries.\n\n");
    report.push_str("## Limits\n\n");
    report.push_str("The simulator models an idempotent action endpoint by durably recording action IDs. Exactly-once side effects require the real endpoint to honor the same idempotency key; a local journal cannot make an arbitrary non-idempotent external system exactly once. Timing is machine-local and includes filesystem synchronization.\n");

    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("artifacts")
        .join("benchmark-report.md");
    fs::create_dir_all(path.parent().unwrap())?;
    fs::write(&path, &report)?;
    print!("{report}");
    eprintln!("report written to {}", path.display());
    Ok(())
}

fn add_summary(
    report: &mut String,
    workload: &str,
    lane: &str,
    results: &[TaskResult],
    paired_matches: usize,
) {
    let count = results.len();
    let completed = results
        .iter()
        .filter(|result| result.final_state == State::Done)
        .count();
    let illegal_commits = results
        .iter()
        .map(|r| r.metrics.illegal_commits)
        .sum::<usize>();
    let rejected = results
        .iter()
        .map(|r| r.metrics.rejected_proposals)
        .sum::<usize>();
    let duplicates = results
        .iter()
        .map(|r| r.metrics.duplicate_actions)
        .sum::<usize>();
    let missing = results
        .iter()
        .map(|r| r.metrics.missing_actions)
        .sum::<usize>();
    let replay_passes = results.iter().filter(|r| r.replay_ok).count();
    let disagreements = average(
        results
            .iter()
            .map(|r| r.metrics.observer_disagreements as u128),
        count,
    );
    let recoveries = average(results.iter().map(|r| r.metrics.recoveries as u128), count);
    let process_resumes = average(results.iter().map(|r| r.process_resumes as u128), count);
    let journal_bytes = average(
        results.iter().map(|r| r.metrics.journal_bytes as u128),
        count,
    );
    let action_bytes = average(
        results
            .iter()
            .map(|r| r.metrics.action_ledger_bytes as u128),
        count,
    );
    let retries = results
        .iter()
        .map(|r| r.metrics.idempotent_reuses)
        .sum::<usize>();
    let task_times = results.iter().map(|r| r.task_ns).collect::<Vec<_>>();
    let active_observer = results
        .iter()
        .map(|r| r.metrics.active_observer_ns)
        .collect::<Vec<_>>();
    let shadow_observer = results
        .iter()
        .map(|r| r.metrics.shadow_observer_ns)
        .collect::<Vec<_>>();
    let swap_time = results
        .iter()
        .map(|r| r.metrics.observer_swap_ns)
        .collect::<Vec<_>>();

    report.push_str(&format!(
        "| {workload} | {lane} | {:.1}% | {illegal_commits} | {rejected} | {duplicates} | {missing} | {replay_passes}/{count} | {paired_matches}/{count} | {disagreements} | {recoveries} | {process_resumes} | {:.2}/{:.2} | {:.3}/{:.3} | {:.3}/{:.3} | {:.3}/{:.3} | {journal_bytes} | {action_bytes} | {retries} |\n",
        completed as f64 * 100.0 / count as f64,
        percentile(&task_times, 0.50) as f64 / 1000.0,
        percentile(&task_times, 0.95) as f64 / 1000.0,
        percentile(&active_observer, 0.50) as f64 / 1000.0,
        percentile(&active_observer, 0.95) as f64 / 1000.0,
        percentile(&shadow_observer, 0.50) as f64 / 1000.0,
        percentile(&shadow_observer, 0.95) as f64 / 1000.0,
        percentile(&swap_time, 0.50) as f64 / 1000.0,
        percentile(&swap_time, 0.95) as f64 / 1000.0,
    ));
}

use std::{mem::size_of, time::Instant};

use rdc_experiment_001::{
    Action, DecisionCompiler, Evidence, Observation, Observer, Proposal, Receipt, RejectionReason,
    Runtime, Signal, State, WorkflowObserver, receipt_identity, standard_schema,
};

const TASKS_PER_SAMPLE: usize = 20_000;
const SAMPLES: usize = 7;

#[derive(Clone, Copy)]
struct Scenario {
    name: &'static str,
    signals: &'static [Signal],
}

const SUCCESS: &[Signal] = &[
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
const ILLEGAL: &[Signal] = &[Signal::Unexpected];
const SCENARIOS: [Scenario; 3] = [
    Scenario {
        name: "nominal",
        signals: SUCCESS,
    },
    Scenario {
        name: "one recovery",
        signals: RECOVERY,
    },
    Scenario {
        name: "illegal proposal",
        signals: ILLEGAL,
    },
];

#[derive(Clone, Copy)]
struct ResultRow {
    median_ns_per_task: u128,
    p95_ns_per_task: u128,
    completion_percent: f64,
    rejected_per_task: f64,
    recoveries_per_task: f64,
    replay_identity: bool,
    receipt_bytes_per_task: usize,
    shared_table_bytes: usize,
}

struct ManualController {
    state: State,
    recovery_count: u8,
    receipts: Vec<Receipt>,
}

impl ManualController {
    fn with_capacity(capacity: usize) -> Self {
        Self {
            state: State::Idle,
            recovery_count: 0,
            receipts: Vec::with_capacity(capacity),
        }
    }

    fn reset(&mut self) {
        self.state = State::Idle;
        self.recovery_count = 0;
        self.receipts.clear();
    }

    fn step<O: Observer>(&mut self, observation: &Observation, observer: &mut O) -> Receipt {
        let proposal = observer.propose(self.state, observation, self.recovery_count);
        self.apply(proposal)
    }

    fn apply(&mut self, proposal: Proposal) -> Receipt {
        let before = self.state;
        let previous_hash = self.receipts.last().map_or([0; 32], |receipt| receipt.hash);
        let rejection = self.validate(proposal);
        let authorized_action = if rejection.is_none() {
            self.state = proposal.requested_to;
            if proposal.action == Action::Recover {
                self.recovery_count = self.recovery_count.saturating_add(1);
            }
            Some(proposal.action)
        } else {
            None
        };
        let sequence = self.receipts.len() as u64;
        let hash = receipt_identity(
            sequence,
            before,
            self.state,
            proposal,
            authorized_action,
            rejection,
            previous_hash,
        );
        let receipt = Receipt {
            sequence,
            before,
            after: self.state,
            proposal,
            authorized_action,
            rejection,
            previous_hash,
            hash,
        };
        self.receipts.push(receipt);
        receipt
    }

    fn validate(&self, proposal: Proposal) -> Option<RejectionReason> {
        if proposal.from != self.state {
            return Some(RejectionReason::StaleFromState);
        }
        if proposal
            .confidence
            .is_some_and(|confidence| confidence > 1000)
        {
            return Some(RejectionReason::InvalidConfidence);
        }
        let guard = match (proposal.from, proposal.requested_to, proposal.action) {
            (State::Idle, State::Observing, Action::Observe) => Some((None, false, None)),
            (State::Observing, State::Deciding, Action::Decide) => Some((None, true, None)),
            (State::Deciding, State::Acting, Action::Execute) => Some((Some(700), true, None)),
            (State::Deciding, State::Failed, Action::Fail) => Some((None, false, None)),
            (State::Acting, State::Verifying, Action::Verify) => Some((None, false, None)),
            (State::Acting, State::Failed, Action::Fail) => Some((None, false, None)),
            (State::Verifying, State::Done, Action::Complete) => Some((None, true, None)),
            (State::Verifying, State::Failed, Action::Fail) => Some((None, false, None)),
            (State::Failed, State::Observing, Action::Recover) => Some((Some(600), true, Some(2))),
            _ => None,
        };
        let Some((minimum_confidence, requires_evidence, max_recoveries)) = guard else {
            return Some(RejectionReason::UnknownTransition);
        };
        if let Some(minimum) = minimum_confidence {
            let Some(confidence) = proposal.confidence else {
                return Some(RejectionReason::ConfidenceMissing);
            };
            if confidence < minimum {
                return Some(RejectionReason::ConfidenceTooLow);
            }
        }
        if requires_evidence && proposal.evidence.is_none() {
            return Some(RejectionReason::EvidenceMissing);
        }
        if max_recoveries.is_some_and(|limit| self.recovery_count >= limit) {
            return Some(RejectionReason::RecoveryLimit);
        }
        None
    }
}

fn observation(signal: Signal) -> Observation {
    let mut value = Observation::new(signal);
    if signal != Signal::Start {
        value = value.with_evidence(Evidence {
            code: 11,
            digest: [0x31; 16],
        });
    }
    if matches!(signal, Signal::Approve | Signal::Recover) {
        value = value.with_confidence(900);
    }
    value
}

fn run_compiled_task(runtime: &mut Runtime, observer: &mut WorkflowObserver, signals: &[Signal]) {
    runtime.reset();
    for signal in signals {
        runtime.step(&observation(*signal), observer);
    }
}

fn run_manual_task(
    controller: &mut ManualController,
    observer: &mut WorkflowObserver,
    signals: &[Signal],
) {
    controller.reset();
    for signal in signals {
        controller.step(&observation(*signal), observer);
    }
}

fn hashes(receipts: &[Receipt]) -> Vec<[u8; 32]> {
    receipts.iter().map(|receipt| receipt.hash).collect()
}

fn percentile(sorted: &[u128], fraction: f64) -> u128 {
    let index = ((sorted.len() as f64 * fraction).ceil() as usize)
        .saturating_sub(1)
        .min(sorted.len() - 1);
    sorted[index]
}

fn measure_compiled(compiler: &DecisionCompiler, scenario: Scenario) -> ResultRow {
    let mut runtime = Runtime::with_capacity(compiler.clone(), scenario.signals.len());
    let mut observer = WorkflowObserver;
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let started = Instant::now();
        for _ in 0..TASKS_PER_SAMPLE {
            run_compiled_task(&mut runtime, &mut observer, scenario.signals);
        }
        samples.push(started.elapsed().as_nanos() / TASKS_PER_SAMPLE as u128);
    }
    let mut sorted = samples;
    sorted.sort_unstable();

    let mut completed = 0usize;
    let mut rejected = 0usize;
    let mut recoveries = 0usize;
    for _ in 0..TASKS_PER_SAMPLE {
        run_compiled_task(&mut runtime, &mut observer, scenario.signals);
        completed += usize::from(runtime.state() == State::Done);
        recoveries += runtime.recovery_count() as usize;
        rejected += runtime.receipts().iter().filter(|r| !r.accepted()).count();
    }
    let first = hashes(runtime.receipts());
    run_compiled_task(&mut runtime, &mut observer, scenario.signals);
    let replay_identity = first == hashes(runtime.receipts());

    ResultRow {
        median_ns_per_task: percentile(&sorted, 0.50),
        p95_ns_per_task: percentile(&sorted, 0.95),
        completion_percent: completed as f64 * 100.0 / TASKS_PER_SAMPLE as f64,
        rejected_per_task: rejected as f64 / TASKS_PER_SAMPLE as f64,
        recoveries_per_task: recoveries as f64 / TASKS_PER_SAMPLE as f64,
        replay_identity,
        receipt_bytes_per_task: size_of::<Receipt>() * scenario.signals.len(),
        shared_table_bytes: compiler.table_bytes(),
    }
}

fn measure_manual(scenario: Scenario) -> ResultRow {
    let mut controller = ManualController::with_capacity(scenario.signals.len());
    let mut observer = WorkflowObserver;
    let mut samples = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        let started = Instant::now();
        for _ in 0..TASKS_PER_SAMPLE {
            run_manual_task(&mut controller, &mut observer, scenario.signals);
        }
        samples.push(started.elapsed().as_nanos() / TASKS_PER_SAMPLE as u128);
    }
    let mut sorted = samples;
    sorted.sort_unstable();

    let mut completed = 0usize;
    let mut rejected = 0usize;
    let mut recoveries = 0usize;
    for _ in 0..TASKS_PER_SAMPLE {
        run_manual_task(&mut controller, &mut observer, scenario.signals);
        completed += usize::from(controller.state == State::Done);
        recoveries += controller.recovery_count as usize;
        rejected += controller.receipts.iter().filter(|r| !r.accepted()).count();
    }
    let first = hashes(&controller.receipts);
    run_manual_task(&mut controller, &mut observer, scenario.signals);
    let replay_identity = first == hashes(&controller.receipts);

    ResultRow {
        median_ns_per_task: percentile(&sorted, 0.50),
        p95_ns_per_task: percentile(&sorted, 0.95),
        completion_percent: completed as f64 * 100.0 / TASKS_PER_SAMPLE as f64,
        rejected_per_task: rejected as f64 / TASKS_PER_SAMPLE as f64,
        recoveries_per_task: recoveries as f64 / TASKS_PER_SAMPLE as f64,
        replay_identity,
        receipt_bytes_per_task: size_of::<Receipt>() * scenario.signals.len(),
        shared_table_bytes: 0,
    }
}

fn main() {
    let compiler = DecisionCompiler::compile(&standard_schema()).expect("valid standard schema");
    let mut report = String::new();
    report.push_str("# R&D-C / Experiment 001 benchmark report\n\n");
    report.push_str(&format!(
        "Rust target: {}-{}; processors: {}; release profile; {} samples x {} tasks per sample and controller.\n\n",
        std::env::consts::ARCH,
        std::env::consts::OS,
        std::thread::available_parallelism().map_or(1, usize::from),
        SAMPLES,
        TASKS_PER_SAMPLE,
    ));
    report.push_str("The controller is single-threaded. Both lanes use the same observer and receipt hash function; the baseline uses a hand-written match dispatch, while the runtime uses the compiled dense table. Latency is wall-clock nanoseconds per task. Receipt memory is estimated from retained Receipt values; it excludes allocator metadata. Shared table bytes count the compiled table once.\n\n");
    report.push_str("| Workload | Controller | Completion | Rejections/task | Recoveries/task | Replay identity | p50 ns/task | p95 ns/task | p50 vs baseline | Receipt bytes/task | Shared table bytes |\n");
    report.push_str("|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|\n");

    for scenario in SCENARIOS {
        let compiled = measure_compiled(&compiler, scenario);
        let manual = measure_manual(scenario);
        let delta = (compiled.median_ns_per_task as f64 - manual.median_ns_per_task as f64) * 100.0
            / manual.median_ns_per_task as f64;
        add_row(
            &mut report,
            scenario.name,
            "compiled runtime",
            compiled,
            Some(delta),
        );
        add_row(
            &mut report,
            scenario.name,
            "hand-written baseline",
            manual,
            None,
        );
    }

    report.push_str("\n## Workloads\n\n");
    report.push_str("- **nominal**: observe, decide, execute, verify, complete.\n");
    report.push_str(
        "- **one recovery**: action failure, bounded recovery, then successful completion.\n",
    );
    report.push_str("- **illegal proposal**: observer requests DONE from IDLE; authority rejects and retains IDLE.\n\n");
    report.push_str("## Limits\n\n");
    report.push_str("This is a repeatable in-process controller microbenchmark, not a workload-level product claim. It measures no model calls, I/O latency, external action cost, or process RSS. The journal replay check is covered by the mapped-replay test and demo; replay identity in this table verifies repeated identical in-memory receipt sequences. Lower timing numbers can vary with OS scheduling and CPU frequency.\n");

    print!("{report}");
}

fn add_row(
    report: &mut String,
    workload: &str,
    controller: &str,
    row: ResultRow,
    delta_vs_baseline: Option<f64>,
) {
    let comparison =
        delta_vs_baseline.map_or_else(|| "reference".to_owned(), |delta| format!("{delta:+.2}%"));
    report.push_str(&format!(
        "| {workload} | {controller} | {:.2}% | {:.3} | {:.3} | {} | {} | {} | {} | {} | {} |\n",
        row.completion_percent,
        row.rejected_per_task,
        row.recoveries_per_task,
        if row.replay_identity { "pass" } else { "FAIL" },
        row.median_ns_per_task,
        row.p95_ns_per_task,
        comparison,
        row.receipt_bytes_per_task,
        row.shared_table_bytes,
    ));
}

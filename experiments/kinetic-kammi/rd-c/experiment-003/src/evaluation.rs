use std::{
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

use rdc_experiment_001::{
    Action, DecisionCompiler, Guard, Receipt, Signal, State, TransitionSpec, standard_schema,
};
use rdc_experiment_002::{CompiledAuthority, TaskRunner};

use crate::{
    Choice, Episode,
    routing::{EscalationPolicy, make_switchboard, new_shadow_cache, new_trace_sink},
};

#[derive(Clone, Debug)]
pub struct RunResult {
    pub policy: EscalationPolicy,
    pub episode_id: u32,
    pub class: &'static str,
    pub correct_action: Choice,
    pub raw_active: Choice,
    pub raw_shadow: Choice,
    pub selected_action: Choice,
    pub resolver_action: Option<Choice>,
    pub action_disagreement: bool,
    pub escalated: bool,
    pub task_completed: bool,
    pub wrong_legal_action: bool,
    pub rejected_proposals: usize,
    pub illegal_commits: usize,
    pub duplicate_actions: usize,
    pub missing_actions: usize,
    pub replay_identity_ok: bool,
    pub replay_identity: [u8; 32],
    pub wall_ns: u128,
    pub observer_a_ns: u64,
    pub observer_b_ns: u64,
    pub routing_ns: u64,
    pub resolver_ns: u64,
    pub journal_bytes: u64,
    pub action_bytes: u64,
    pub e2_journal: PathBuf,
}

pub fn experiment_schema() -> Vec<TransitionSpec> {
    let mut schema = standard_schema()
        .into_iter()
        .filter(|spec| {
            !(spec.from == State::Deciding
                && spec.to == State::Acting
                && spec.action == Action::Execute)
        })
        .collect::<Vec<_>>();
    let guard = Guard {
        min_confidence: None,
        requires_evidence: true,
        max_recoveries: None,
    };
    for action in [Action::Execute, Action::Verify, Action::Observe] {
        schema.push(TransitionSpec::new(
            State::Deciding,
            State::Acting,
            action,
            guard,
        ));
    }
    schema
}

pub fn run_episode(
    policy: EscalationPolicy,
    random_escalate: bool,
    episode: Episode,
    compiler: &DecisionCompiler,
    schema: &[TransitionSpec],
    journal_root: &Path,
    task_salt: u64,
) -> Result<RunResult, Box<dyn Error>> {
    let started = Instant::now();
    let lane = journal_root.join(policy.label());
    fs::create_dir_all(&lane)?;
    let task_dir = lane.join(format!("episode-{:04}", episode.id));
    fs::create_dir(&task_dir)?;
    let journal = task_dir.join("task.journal");
    let actions = task_dir.join("actions.ledger");
    let task_id = task_salt
        .wrapping_add((policy_index(policy) as u64) << 32)
        .wrapping_add(episode.id as u64);
    let trace_sink = new_trace_sink();
    let shadow_cache = new_shadow_cache();
    let mut runner = TaskRunner::create(
        CompiledAuthority::from_compiler(compiler.clone()),
        make_switchboard(
            policy,
            random_escalate,
            trace_sink.clone(),
            shadow_cache.clone(),
        )?,
        task_id,
        &journal,
        &actions,
    )?;
    for signal in [Signal::Start, Signal::Observed] {
        runner.step(&episode.observation(signal), None)?;
    }
    let decision = runner.step(&episode.observation(Signal::Approve), None)?;
    let trace = trace_sink
        .borrow_mut()
        .take()
        .ok_or("router did not record its decision trace")?;
    if decision.active != trace.selected || decision.shadow != trace.raw_shadow {
        return Err("recorded route proposals differ from E002 switchboard output".into());
    }
    let selected_action = Choice::from_action(decision.active.action)
        .ok_or("router selected an action outside the held-out action set")?;
    let correct = selected_action == episode.correct_action;
    if correct {
        runner.step(&episode.observation(Signal::ActionSucceeded), None)?;
        runner.step(&episode.observation(Signal::Verified), None)?;
    } else {
        runner.step(&episode.observation(Signal::ActionFailed), None)?;
    }

    let metrics = runner.metrics();
    let final_state = runner.state();
    let receipts = runner.receipts().to_vec();
    let receipt_hashes = receipts
        .iter()
        .map(|receipt| receipt.hash)
        .collect::<Vec<_>>();
    let replay_identity = metrics
        .replay_identity
        .ok_or("E002 task journal has no final hash")?;
    let illegal_commits = illegal_commits(&receipts, schema);
    if !decision.receipt.accepted() {
        return Err("experiment decision was rejected by the E002 authority".into());
    }
    runner.close()?;

    let replay = unsafe {
        TaskRunner::resume(
            CompiledAuthority::from_compiler(compiler.clone()),
            make_switchboard(
                policy,
                random_escalate,
                new_trace_sink(),
                new_shadow_cache(),
            )?,
            task_id,
            &journal,
            &actions,
        )?
    };
    let replay_metrics = replay.metrics();
    let replay_receipts = replay
        .receipts()
        .iter()
        .map(|receipt| receipt.hash)
        .collect::<Vec<_>>();
    let replay_identity_ok = replay.state() == final_state
        && replay_metrics.replay_identity == Some(replay_identity)
        && replay_receipts == receipt_hashes;
    replay.close()?;
    let wall_ns = started.elapsed().as_nanos();

    Ok(RunResult {
        policy,
        episode_id: episode.id,
        class: episode.class.label(),
        correct_action: episode.correct_action,
        raw_active: choice_from(trace.raw_active)?,
        raw_shadow: choice_from(trace.raw_shadow)?,
        selected_action,
        resolver_action: trace.resolver.map(choice_from).transpose()?,
        action_disagreement: trace.action_disagreement,
        escalated: trace.escalated,
        task_completed: final_state == State::Done,
        wrong_legal_action: selected_action != episode.correct_action,
        rejected_proposals: receipts
            .iter()
            .filter(|receipt| !receipt.accepted())
            .count(),
        illegal_commits,
        duplicate_actions: metrics.duplicate_actions,
        missing_actions: metrics.missing_actions,
        replay_identity_ok,
        replay_identity,
        wall_ns,
        observer_a_ns: trace.active_observer_ns,
        observer_b_ns: trace.shadow_observer_ns,
        routing_ns: trace.routing_ns,
        resolver_ns: trace.resolver_ns,
        journal_bytes: metrics.journal_bytes,
        action_bytes: metrics.action_ledger_bytes,
        e2_journal: journal,
    })
}

pub fn illegal_commits(receipts: &[Receipt], schema: &[TransitionSpec]) -> usize {
    receipts
        .iter()
        .filter(|receipt| {
            receipt.accepted()
                && !schema.iter().any(|spec| {
                    spec.from == receipt.proposal.from
                        && spec.to == receipt.proposal.requested_to
                        && spec.action == receipt.proposal.action
                })
        })
        .count()
}

fn choice_from(proposal: rdc_experiment_001::Proposal) -> Result<Choice, Box<dyn Error>> {
    Choice::from_action(proposal.action).ok_or_else(|| "proposal has no experiment action".into())
}

fn policy_index(policy: EscalationPolicy) -> u32 {
    match policy {
        EscalationPolicy::Never => 0,
        EscalationPolicy::Disagreement => 1,
        EscalationPolicy::ConfidenceThreshold => 2,
        EscalationPolicy::RandomMatched => 3,
    }
}

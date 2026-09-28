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
    domain::{Choice, ObservationFeatures},
    episodes::Episode,
    evaluation::EvalLabel,
    routing::{Policy, make_switchboard, new_shadow_cache, new_trace_sink},
};

#[derive(Clone, Debug)]
pub struct RunResult {
    pub policy: Policy,
    pub budget: usize,
    pub episode_id: u32,
    pub class: &'static str,
    pub correct_action: Choice,
    pub raw_active: Choice,
    pub raw_shadow: Choice,
    pub selected_action: Choice,
    pub resolver_action: Option<Choice>,
    pub action_disagreement: bool,
    pub witness: &'static str,
    pub witness_source_id: Option<u8>,
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
    pub witness_ns: u64,
    pub resolver_ns: u64,
    pub tool_ns: u64,
    pub tool_calls: u8,
    pub resolver_tokens: u32,
    pub external_model_cost_micros: u64,
    pub journal_bytes: u64,
    pub action_bytes: u64,
    pub e2_journal: PathBuf,
}

pub struct RunSpec<'a> {
    pub policy: Policy,
    pub budget: usize,
    pub escalated: bool,
    pub episode: Episode,
    pub label: EvalLabel,
    pub compiler: &'a DecisionCompiler,
    pub schema: &'a [TransitionSpec],
    pub journal_root: &'a Path,
    pub task_salt: u64,
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

pub fn run_episode(spec: RunSpec<'_>) -> Result<RunResult, Box<dyn Error>> {
    let RunSpec {
        policy,
        budget,
        escalated,
        episode,
        label,
        compiler,
        schema,
        journal_root,
        task_salt,
    } = spec;
    if label.episode_id != episode.id {
        return Err("label and episode IDs differ".into());
    }
    let started = Instant::now();
    let lane = journal_root
        .join(policy.label())
        .join(format!("budget-{budget:03}"));
    fs::create_dir_all(&lane)?;
    let task_dir = lane.join(format!("episode-{:04}", episode.id));
    fs::create_dir(&task_dir)?;
    let journal = task_dir.join("task.journal");
    let actions = task_dir.join("actions.ledger");
    let task_id = task_salt
        .wrapping_add((policy.index() as u64) << 48)
        .wrapping_add((budget as u64) << 32)
        .wrapping_add(episode.id as u64);
    let trace_sink = new_trace_sink();
    let shadow_cache = new_shadow_cache();
    let mut runner = TaskRunner::create(
        CompiledAuthority::from_compiler(compiler.clone()),
        make_switchboard(escalated, trace_sink.clone(), shadow_cache.clone())?,
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
        .ok_or("router omitted decision trace")?;
    if decision.active != trace.selected || decision.shadow != trace.raw_shadow {
        return Err("E002 switchboard journal differs from E004 route trace".into());
    }
    if !decision.receipt.accepted() {
        return Err("compiled authority rejected a schema-valid E004 action".into());
    }
    let selected_action = Choice::from_action(decision.active.action)
        .ok_or("selected action is outside the episode action universe")?;
    let completed = selected_action == label.correct_action;
    if completed {
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
    let identity = metrics
        .replay_identity
        .ok_or("missing E002 replay identity")?;
    let illegal_commits = illegal_commits(&receipts, schema);
    let journal_bytes = metrics.journal_bytes;
    let action_bytes = metrics.action_ledger_bytes;
    let rejected = metrics.rejected_proposals;
    let duplicate_actions = metrics.duplicate_actions;
    let missing_actions = metrics.missing_actions;
    runner.close()?;

    // E002 contract-aware replay replays every proposal and action receipt under the same schema.
    let replay = unsafe {
        TaskRunner::resume(
            CompiledAuthority::from_compiler(compiler.clone()),
            make_switchboard(escalated, new_trace_sink(), new_shadow_cache())?,
            task_id,
            &journal,
            &actions,
        )?
    };
    let replay_hashes = replay
        .receipts()
        .iter()
        .map(|receipt| receipt.hash)
        .collect::<Vec<_>>();
    let replay_identity_ok = replay.state() == final_state
        && replay.metrics().replay_identity == Some(identity)
        && replay_hashes == receipt_hashes;
    replay.close()?;
    let witness = match trace.witness {
        crate::routing::WitnessProposal::NoSignal => "none",
        crate::routing::WitnessProposal::InspectEvidence {
            reason: crate::routing::WitnessReason::SharedOldSource,
            ..
        } => "inspect_shared_old_source",
        crate::routing::WitnessProposal::InspectEvidence {
            reason: crate::routing::WitnessReason::SharedWarnedSource,
            ..
        } => "inspect_shared_warned_source",
        crate::routing::WitnessProposal::InspectEvidence {
            reason: crate::routing::WitnessReason::SharedMisleadingSource,
            ..
        } => "inspect_shared_misleading_source",
    };
    let witness_source_id = match trace.witness {
        crate::routing::WitnessProposal::NoSignal => None,
        crate::routing::WitnessProposal::InspectEvidence { source_id, .. } => Some(source_id),
    };
    let resolver_action = match trace.resolver {
        Some(proposal) => {
            Some(Choice::from_action(proposal.action).ok_or("invalid resolver action")?)
        }
        None => None,
    };
    let correct = selected_action == label.correct_action;
    let features = episode.features;
    debug_assert_eq!(
        ObservationFeatures::decode(&episode.observation(Signal::Approve)),
        Some(features)
    );

    Ok(RunResult {
        policy,
        budget,
        episode_id: episode.id,
        class: episode.class.label(),
        correct_action: label.correct_action,
        raw_active: Choice::from_action(trace.raw_active.action)
            .ok_or("invalid observer A action")?,
        raw_shadow: Choice::from_action(trace.raw_shadow.action)
            .ok_or("invalid observer B action")?,
        selected_action,
        resolver_action,
        action_disagreement: trace.action_disagreement,
        witness,
        witness_source_id,
        escalated,
        task_completed: final_state == State::Done && correct,
        wrong_legal_action: decision.receipt.accepted() && !correct,
        rejected_proposals: rejected,
        illegal_commits,
        duplicate_actions,
        missing_actions,
        replay_identity_ok,
        replay_identity: identity,
        wall_ns: started.elapsed().as_nanos(),
        observer_a_ns: trace.active_observer_ns,
        observer_b_ns: trace.shadow_observer_ns,
        witness_ns: trace.witness_ns,
        resolver_ns: trace.resolver_ns,
        tool_ns: trace.tool_ns,
        tool_calls: trace.tool_calls,
        resolver_tokens: trace.resolver_tokens,
        external_model_cost_micros: 0,
        journal_bytes,
        action_bytes,
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

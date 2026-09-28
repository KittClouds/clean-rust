use std::{
    cell::RefCell,
    error::Error,
    fs,
    path::{Path, PathBuf},
    rc::Rc,
    time::Instant,
};

use rdc_experiment_001::{
    Action, DecisionCompiler, Guard, Observation, Proposal, Signal, State, TransitionSpec,
    WorkflowObserver,
};
use rdc_experiment_002::{
    CompiledAuthority, INPUT_SCHEMA_V1, OBSERVER_INTERFACE_VERSION, OUTPUT_SCHEMA_V1,
    ObserverManifest, ObserverSwitchboard, TaskRunner, VersionedObserver, WorkflowAdapter,
    WorkflowBehavior,
};
use rdc_experiment_004::{Choice, runtime::illegal_commits};

use crate::{
    domain::PublicFrame,
    episodes::{Episode, Scenario},
    evaluation::EvalLabel,
    inspection::{InspectionOutcome, InspectionResult, QueryId},
    routing::Lane,
};

type TraceSink = Rc<RefCell<Option<RouteTrace>>>;

#[derive(Clone, Copy, Debug)]
pub struct RouteTrace {
    pub active: Choice,
    pub shadow: Choice,
    pub selected: Option<Choice>,
    pub outcome: Option<InspectionOutcome>,
    pub reobserve: bool,
    pub disagreement: bool,
}

#[derive(Clone, Debug)]
pub struct RunResult {
    pub lane: Lane,
    pub budget: usize,
    pub episode_id: u32,
    pub domain: u8,
    pub scenario: &'static str,
    pub active_action: Choice,
    pub shadow_action: Choice,
    pub selected_action: Option<Choice>,
    pub inspection_outcome: Option<InspectionOutcome>,
    pub reobserve: bool,
    pub correct_action: Choice,
    pub outcome: &'static str,
    pub task_completed: bool,
    pub illegal_commits: usize,
    pub rejected_proposals: usize,
    pub duplicate_actions: usize,
    pub missing_actions: usize,
    pub task_action_effects: usize,
    pub reobserve_effects: usize,
    pub replay_identity_ok: bool,
    pub replay_identity: [u8; 32],
    pub wall_ns: u128,
    pub query_ns: u64,
    pub resolver_ns: u64,
    pub task_journal_bytes: u64,
    pub action_ledger_bytes: u64,
    pub task_path: PathBuf,
    pub query_id: Option<QueryId>,
}

pub struct RunSpec<'a> {
    pub lane: Lane,
    pub budget: usize,
    pub episode: &'a Episode,
    pub label: &'a EvalLabel,
    pub result: Option<InspectionResult>,
    pub compiler: &'a DecisionCompiler,
    pub schema: &'a [TransitionSpec],
    pub journal_root: &'a Path,
    pub task_salt: u64,
    pub query_ns: u64,
    pub resolver_ns: u64,
    pub query_id: Option<QueryId>,
}

pub fn experiment_schema() -> Vec<TransitionSpec> {
    let mut schema = rdc_experiment_004::experiment_schema();
    let reobserve = TransitionSpec::new(
        State::Deciding,
        State::Observing,
        Action::Recover,
        Guard {
            min_confidence: Some(600),
            requires_evidence: true,
            max_recoveries: Some(2),
        },
    );
    schema.push(reobserve);
    schema
}

pub fn run_episode(spec: RunSpec<'_>) -> Result<RunResult, Box<dyn Error>> {
    let RunSpec {
        lane,
        budget,
        episode,
        label,
        result,
        compiler,
        schema,
        journal_root,
        task_salt,
        query_ns,
        resolver_ns,
        query_id,
    } = spec;
    if episode.id != label.episode_id {
        return Err("E006 episode and label IDs differ".into());
    }
    let started = Instant::now();
    let task_dir = journal_root
        .join(lane.label())
        .join(format!("budget-{budget:03}"))
        .join(format!("episode-{:08}", episode.id));
    fs::create_dir_all(&task_dir)?;
    let journal = task_dir.join("task.journal");
    let actions = task_dir.join("actions.ledger");
    let task_id = task_salt
        .wrapping_add((lane.index() as u64) << 48)
        .wrapping_add((budget as u64) << 32)
        .wrapping_add(episode.id as u64);
    let trace = Rc::new(RefCell::new(None));
    let switchboard = make_switchboard(trace.clone(), result)?;
    let mut runner = TaskRunner::create(
        CompiledAuthority::from_compiler(compiler.clone()),
        switchboard,
        task_id,
        &journal,
        &actions,
    )?;
    runner.step(
        &episode.frame.observation(Signal::Start, episode.confidence),
        None,
    )?;
    runner.step(
        &episode
            .frame
            .observation(Signal::Observed, episode.confidence),
        None,
    )?;
    let decision = runner.step(
        &episode
            .frame
            .observation(Signal::Approve, episode.confidence),
        None,
    )?;
    let route = trace
        .borrow_mut()
        .take()
        .ok_or("E006 router omitted decision trace")?;
    if !decision.receipt.accepted() {
        return Err("compiled authority rejected an E006 proposal".into());
    }
    if route.reobserve != (route.selected.is_none()) {
        return Err("typed inspection outcome and reobserve proposal diverged".into());
    }

    let completed = if route.reobserve {
        false
    } else {
        let selected = route
            .selected
            .ok_or("task-action proposal omitted action")?;
        let correct = selected == label.correct_action;
        if correct {
            runner.step(
                &episode
                    .frame
                    .observation(Signal::ActionSucceeded, episode.confidence),
                None,
            )?;
            runner.step(
                &episode
                    .frame
                    .observation(Signal::Verified, episode.confidence),
                None,
            )?;
        } else {
            runner.step(
                &episode
                    .frame
                    .observation(Signal::ActionFailed, episode.confidence),
                None,
            )?;
        }
        correct
    };

    let metrics = runner.metrics();
    let final_state = runner.state();
    let receipts = runner.receipts().to_vec();
    let identity = metrics
        .replay_identity
        .ok_or("E006 journal omitted replay identity")?;
    let illegal = illegal_commits(&receipts, schema);
    let journal_bytes = metrics.journal_bytes;
    let action_bytes = metrics.action_ledger_bytes;
    let rejected = metrics.rejected_proposals;
    let duplicates = metrics.duplicate_actions;
    let missing = metrics.missing_actions;
    let action_effects = metrics.unique_actions;
    runner.close()?;

    // Replay E002 authority state and idempotent action records after the writer is closed.
    let replay = unsafe {
        TaskRunner::resume(
            CompiledAuthority::from_compiler(compiler.clone()),
            make_switchboard(Rc::new(RefCell::new(None)), None)?,
            task_id,
            &journal,
            &actions,
        )?
    };
    let replay_identity_ok = replay.state() == final_state
        && replay.metrics().replay_identity == Some(identity)
        && replay
            .receipts()
            .iter()
            .map(|receipt| receipt.hash)
            .eq(receipts.iter().map(|receipt| receipt.hash));
    let reobserve_effects = usize::from(route.reobserve);
    let task_action_effects = usize::from(!route.reobserve);
    let expected_effects = if route.reobserve {
        3
    } else if completed {
        5
    } else {
        4
    };
    if action_effects != expected_effects {
        return Err(format!("unexpected action simulator effect count: {action_effects}").into());
    }
    let outcome = classify(route.active, route.selected, label.correct_action);
    Ok(RunResult {
        lane,
        budget,
        episode_id: episode.id,
        domain: episode.domain,
        scenario: episode.scenario.label(),
        active_action: route.active,
        shadow_action: route.shadow,
        selected_action: route.selected,
        inspection_outcome: route.outcome,
        reobserve: route.reobserve,
        correct_action: label.correct_action,
        outcome,
        task_completed: completed && final_state == State::Done,
        illegal_commits: illegal,
        rejected_proposals: rejected,
        duplicate_actions: duplicates,
        missing_actions: missing,
        task_action_effects,
        reobserve_effects,
        replay_identity_ok,
        replay_identity: identity,
        wall_ns: started.elapsed().as_nanos() + query_ns as u128 + resolver_ns as u128,
        query_ns,
        resolver_ns,
        task_journal_bytes: journal_bytes,
        action_ledger_bytes: action_bytes,
        task_path: journal,
        query_id,
    })
}

pub fn new_compiler() -> Result<(Vec<TransitionSpec>, DecisionCompiler), Box<dyn Error>> {
    let schema = experiment_schema();
    let compiler = DecisionCompiler::compile(&schema)?;
    Ok((schema, compiler))
}

fn make_switchboard(
    trace: TraceSink,
    result: Option<InspectionResult>,
) -> Result<ObserverSwitchboard, Box<dyn Error>> {
    let active = RouteObserver {
        manifest: manifest("rdc006/typed-inspection-resolver-v1"),
        trace,
        result,
        fallback: WorkflowObserver,
    };
    let shadow = WorkflowAdapter::new("rdc006/workflow-shadow-v1", WorkflowBehavior::Normal);
    Ok(ObserverSwitchboard::new(
        Box::new(active),
        Box::new(shadow),
    )?)
}

struct RouteObserver {
    manifest: ObserverManifest,
    trace: TraceSink,
    result: Option<InspectionResult>,
    fallback: WorkflowObserver,
}

impl VersionedObserver for RouteObserver {
    fn manifest(&self) -> &ObserverManifest {
        &self.manifest
    }

    fn propose(&mut self, state: State, observation: &Observation, recovery_count: u8) -> Proposal {
        if state != State::Deciding || observation.signal != Signal::Approve {
            return rdc_experiment_001::Observer::propose(
                &mut self.fallback,
                state,
                observation,
                recovery_count,
            );
        }
        let Some(frame) = PublicFrame::decode(observation) else {
            return rdc_experiment_001::Observer::propose(
                &mut self.fallback,
                state,
                observation,
                recovery_count,
            );
        };
        let active = frame.features.primary_action;
        let shadow = if frame.features.flags & 0b100 != 0 {
            frame.features.audit_action
        } else {
            frame.features.primary_action
        };
        let result = self.result;
        let selected = result.map_or(Some(active), |inspection| inspection.proposed_action);
        let reobserve = selected.is_none();
        let (to, action) = if let Some(choice) = selected {
            (State::Acting, choice.action())
        } else {
            (State::Observing, Action::Recover)
        };
        let evidence = Some(frame.proposal_evidence(
            action as u8,
            result.map(|inspection| inspection.reply.payload_digest),
        ));
        let route = RouteTrace {
            active,
            shadow,
            selected,
            outcome: result.map(|inspection| inspection.outcome),
            reobserve,
            disagreement: active != shadow,
        };
        *self.trace.borrow_mut() = Some(route);
        Proposal {
            from: state,
            requested_to: to,
            action,
            confidence: observation.confidence,
            evidence,
        }
    }
}

fn manifest(implementation_id: &str) -> ObserverManifest {
    ObserverManifest {
        interface_version: OBSERVER_INTERFACE_VERSION,
        implementation_id: implementation_id.to_owned(),
        input_schema: INPUT_SCHEMA_V1.to_owned(),
        output_schema: OUTPUT_SCHEMA_V1.to_owned(),
        normalization_contract: "e006-public-frame-v1".to_owned(),
    }
}

fn classify(active: Choice, selected: Option<Choice>, correct: Choice) -> &'static str {
    match (active == correct, selected.map(|choice| choice == correct)) {
        (false, Some(true)) => "wrong_to_right",
        (true, Some(false)) => "right_to_wrong",
        (true, Some(true)) => "both_right",
        (false, Some(false)) => "both_wrong",
        (true, None) => "unresolved_active_right",
        (false, None) => "unresolved_active_wrong",
    }
}

pub fn source_effect_contract(scenario: Scenario) -> &'static str {
    match scenario {
        Scenario::StaleEchoWrong => "stale_echo",
        Scenario::SelfConflict => "self_conflict",
        Scenario::Timeout => "timeout",
        Scenario::TransportFailure => "transport_failure",
        Scenario::MalformedEvidence => "malformed",
        _ => "candidate_reply",
    }
}

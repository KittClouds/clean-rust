use std::{
    cell::RefCell,
    error::Error,
    fs,
    path::{Path, PathBuf},
    rc::Rc,
    time::Instant,
};

use rdc_experiment_001::{
    Action, DecisionCompiler, Guard, Observation, Observer, Proposal, Signal, State, TransitionSpec,
};
use rdc_experiment_002::{
    CompiledAuthority, INPUT_SCHEMA_V1, OBSERVER_INTERFACE_VERSION, OUTPUT_SCHEMA_V1,
    ObserverContractError, ObserverManifest, ObserverSwitchboard, TaskRunner, VersionedObserver,
};
use rdc_experiment_004::{
    Choice,
    domain::{FLAG_AUDIT_SELECTED, FLAG_AUDIT_WARNING, FLAG_PRIMARY_WARNING},
    episodes::contract_action,
};

use crate::{
    domain::PublicFrame,
    episodes::Episode,
    evaluation::EvalLabel,
    inspection::{InspectionResult, InspectionTool, QueryReceiptLog},
    routing::Lane,
};

pub type TraceSink = Rc<RefCell<Option<RouteTrace>>>;
type QueryCache = Rc<RefCell<Option<(InspectionResult, [u8; 32])>>>;
type ProposalCache = Rc<RefCell<Option<Proposal>>>;

#[derive(Clone, Copy, Debug)]
pub struct RouteTrace {
    pub raw_active: Choice,
    pub raw_shadow: Choice,
    pub selected: Choice,
    pub resolver_action: Option<Choice>,
    pub disagreement: bool,
    pub witness: &'static str,
    pub escalated: bool,
    pub active_observer_ns: u64,
    pub shadow_observer_ns: u64,
    pub resolver_ns: u64,
}

#[derive(Clone, Debug)]
pub struct RunResult {
    pub lane: Lane,
    pub budget: usize,
    pub episode_id: u32,
    pub class: &'static str,
    pub inspection_domain: u8,
    pub confidence: u16,
    pub active_action: Choice,
    pub shadow_action: Choice,
    pub resolver_action: Option<Choice>,
    pub selected_action: Choice,
    pub witness: &'static str,
    pub correct_action: Choice,
    pub outcome: &'static str,
    pub escalated: bool,
    pub task_completed: bool,
    pub illegal_commits: usize,
    pub rejected_proposals: usize,
    pub duplicate_actions: usize,
    pub missing_actions: usize,
    pub replay_identity_ok: bool,
    pub replay_identity: [u8; 32],
    pub wall_ns: u128,
    pub observer_ns: u64,
    pub resolver_ns: u64,
    pub query_ns: u64,
    pub query_calls: u8,
    pub query_cost_units: u8,
    pub query_receipt_bytes: u64,
    pub task_journal_bytes: u64,
    pub action_ledger_bytes: u64,
    pub journal_path: PathBuf,
}

pub struct RunSpec<'a> {
    pub lane: Lane,
    pub budget: usize,
    pub escalated: bool,
    pub episode: &'a Episode,
    pub label: &'a EvalLabel,
    pub compiler: &'a DecisionCompiler,
    pub schema: &'a [TransitionSpec],
    pub journal_root: &'a Path,
    pub inspection_tool: &'a InspectionTool<'a>,
    pub query_log: &'a mut QueryReceiptLog,
}

pub fn experiment_schema() -> Vec<TransitionSpec> {
    let mut schema = rdc_experiment_004::experiment_schema();
    let guard = Guard {
        min_confidence: None,
        requires_evidence: true,
        max_recoveries: None,
    };
    for action in [Action::Execute, Action::Verify, Action::Observe] {
        if !schema.iter().any(|spec| {
            spec.from == State::Deciding && spec.to == State::Acting && spec.action == action
        }) {
            schema.push(TransitionSpec::new(
                State::Deciding,
                State::Acting,
                action,
                guard,
            ));
        }
    }
    schema
}

pub fn new_trace_sink() -> TraceSink {
    Rc::new(RefCell::new(None))
}

pub fn run_episode(spec: RunSpec<'_>) -> Result<RunResult, Box<dyn Error>> {
    let RunSpec {
        lane,
        budget,
        escalated,
        episode,
        label,
        compiler,
        schema,
        journal_root,
        inspection_tool,
        query_log,
    } = spec;
    if episode.id != label.episode_id {
        return Err("episode and evaluation label IDs differ".into());
    }
    let started = Instant::now();
    let mut query_result = None;
    let mut query_ns = 0;
    let mut query_receipt_bytes = 0;
    if escalated {
        let (result, elapsed) = inspection_tool.query(episode.id)?;
        query_ns = elapsed;
        let (bytes, receipt_hash) = query_log.append(episode.id, result)?;
        query_receipt_bytes = bytes;
        query_result = Some((result, receipt_hash));
    }

    let task_dir = journal_root
        .join(lane.label())
        .join(format!("budget-{budget:03}"))
        .join(format!("episode-{:08}", episode.id));
    fs::create_dir_all(&task_dir)?;
    let journal = task_dir.join("task.journal");
    let actions = task_dir.join("actions.ledger");
    let task_id = 0xE005_51A7_0000_0000u64
        .wrapping_add((lane.index() as u64) << 48)
        .wrapping_add((budget as u64) << 32)
        .wrapping_add(episode.id as u64);
    let trace = new_trace_sink();
    let (query_cache, proposal_cache) = new_caches(query_result);
    let switchboard = make_switchboard(
        lane,
        escalated,
        trace.clone(),
        query_cache,
        proposal_cache.clone(),
    )?;
    let mut runner = TaskRunner::create(
        CompiledAuthority::from_compiler(compiler.clone()),
        switchboard,
        task_id,
        &journal,
        &actions,
    )?;

    runner.step(&episode.observation(Signal::Start), None)?;
    runner.step(&episode.observation(Signal::Observed), None)?;
    let decision = runner.step(&episode.observation(Signal::Approve), None)?;
    let trace = trace
        .borrow_mut()
        .take()
        .ok_or("E005 router omitted decision trace")?;
    if decision.active.action != trace.selected.action() {
        return Err("E002 journal action differs from E005 selected action".into());
    }
    if !decision.receipt.accepted() {
        return Err("compiled authority rejected a schema-valid E005 action".into());
    }

    let completed = trace.selected == label.correct_action;
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
    let illegal_commits = rdc_experiment_004::runtime::illegal_commits(&receipts, schema);
    let journal_bytes = metrics.journal_bytes;
    let action_bytes = metrics.action_ledger_bytes;
    let rejected = metrics.rejected_proposals;
    let duplicate_actions = metrics.duplicate_actions;
    let missing_actions = metrics.missing_actions;
    runner.close()?;

    // Replay validates the compiled transition receipts, action intents, completions, and state.
    let replay = unsafe {
        TaskRunner::resume(
            CompiledAuthority::from_compiler(compiler.clone()),
            make_switchboard(
                lane,
                false,
                new_trace_sink(),
                Rc::new(RefCell::new(None)),
                Rc::new(RefCell::new(None)),
            )?,
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

    let outcome = classify(trace.raw_active, trace.selected, label.correct_action);
    Ok(RunResult {
        lane,
        budget,
        episode_id: episode.id,
        class: episode.class.label(),
        inspection_domain: episode.frame.inspection_domain,
        confidence: episode.confidence,
        active_action: trace.raw_active,
        shadow_action: trace.raw_shadow,
        resolver_action: trace.resolver_action,
        selected_action: trace.selected,
        witness: trace.witness,
        correct_action: label.correct_action,
        outcome,
        escalated,
        task_completed: final_state == State::Done && completed,
        illegal_commits,
        rejected_proposals: rejected,
        duplicate_actions,
        missing_actions,
        replay_identity_ok,
        replay_identity: identity,
        wall_ns: started.elapsed().as_nanos(),
        observer_ns: trace.active_observer_ns + trace.shadow_observer_ns,
        resolver_ns: trace.resolver_ns,
        query_ns,
        query_calls: u8::from(escalated),
        query_cost_units: u8::from(escalated),
        query_receipt_bytes,
        task_journal_bytes: journal_bytes,
        action_ledger_bytes: action_bytes,
        journal_path: journal,
    })
}

fn new_caches(query: Option<(InspectionResult, [u8; 32])>) -> (QueryCache, ProposalCache) {
    (Rc::new(RefCell::new(query)), Rc::new(RefCell::new(None)))
}

fn make_switchboard(
    lane: Lane,
    escalated: bool,
    trace: TraceSink,
    query_cache: QueryCache,
    proposal_cache: ProposalCache,
) -> Result<ObserverSwitchboard, ObserverContractError> {
    ObserverSwitchboard::new(
        Box::new(RouteObserver::new(
            lane,
            escalated,
            trace,
            query_cache,
            proposal_cache.clone(),
        )),
        Box::new(ShadowObserver::new(proposal_cache)),
    )
}

struct RouteObserver {
    manifest: ObserverManifest,
    lane: Lane,
    escalated: bool,
    trace: TraceSink,
    query_cache: QueryCache,
    proposal_cache: ProposalCache,
    fallback: rdc_experiment_001::WorkflowObserver,
}

struct ShadowObserver {
    manifest: ObserverManifest,
    proposal_cache: ProposalCache,
    fallback: rdc_experiment_001::WorkflowObserver,
}

impl RouteObserver {
    fn new(
        lane: Lane,
        escalated: bool,
        trace: TraceSink,
        query_cache: QueryCache,
        proposal_cache: ProposalCache,
    ) -> Self {
        Self {
            manifest: manifest("rdc005/typed-active-observer-v1"),
            lane,
            escalated,
            trace,
            query_cache,
            proposal_cache,
            fallback: rdc_experiment_001::WorkflowObserver,
        }
    }
}

impl ShadowObserver {
    fn new(proposal_cache: ProposalCache) -> Self {
        Self {
            manifest: manifest("rdc005/audit-shadow-observer-v1"),
            proposal_cache,
            fallback: rdc_experiment_001::WorkflowObserver,
        }
    }
}

impl VersionedObserver for RouteObserver {
    fn manifest(&self) -> &ObserverManifest {
        &self.manifest
    }

    fn propose(&mut self, state: State, observation: &Observation, recovery_count: u8) -> Proposal {
        if state != State::Deciding || observation.signal != Signal::Approve {
            return self.fallback.propose(state, observation, recovery_count);
        }
        let Some(frame) = PublicFrame::decode(observation) else {
            return self.fallback.propose(state, observation, recovery_count);
        };
        let active_start = Instant::now();
        let raw_active = frame.features.primary_action;
        let active_ns = elapsed_ns(active_start);
        let shadow_start = Instant::now();
        let raw_shadow = if frame.features.flags & FLAG_AUDIT_SELECTED != 0 {
            frame.features.audit_action
        } else {
            frame.features.primary_action
        };
        let shadow_ns = elapsed_ns(shadow_start);
        let active_proposal = proposal(state, observation, frame, raw_active, None);
        let shadow_proposal = proposal(state, observation, frame, raw_shadow, None);
        *self.proposal_cache.borrow_mut() = Some(shadow_proposal);

        let disagreement = raw_active != raw_shadow;
        let resolver_start = Instant::now();
        let (resolver_action, result_digest) = if self.escalated {
            let Some((result, digest)) = self.query_cache.borrow_mut().take() else {
                return active_proposal;
            };
            let action = if self.lane == Lane::E004Combined {
                frame_only_resolver(frame.features)
            } else if result.signature_valid && result.confidence >= 900 {
                result.choice().unwrap_or(raw_active)
            } else {
                raw_active
            };
            (Some(action), Some(digest))
        } else {
            (None, None)
        };
        let resolver_ns = if self.escalated {
            elapsed_ns(resolver_start)
        } else {
            0
        };
        let selected = resolver_action.unwrap_or(raw_active);
        let selected_proposal = proposal(state, observation, frame, selected, result_digest);
        let witness = witness_label(frame.features, raw_active, raw_shadow);
        *self.trace.borrow_mut() = Some(RouteTrace {
            raw_active,
            raw_shadow,
            selected,
            resolver_action,
            disagreement,
            witness,
            escalated: self.escalated,
            active_observer_ns: active_ns,
            shadow_observer_ns: shadow_ns,
            resolver_ns,
        });
        selected_proposal
    }
}

impl VersionedObserver for ShadowObserver {
    fn manifest(&self) -> &ObserverManifest {
        &self.manifest
    }

    fn propose(&mut self, state: State, observation: &Observation, recovery_count: u8) -> Proposal {
        if state == State::Deciding
            && observation.signal == Signal::Approve
            && let Some(proposal) = self.proposal_cache.borrow_mut().take()
        {
            return proposal;
        }
        self.fallback.propose(state, observation, recovery_count)
    }
}

fn proposal(
    state: State,
    observation: &Observation,
    frame: PublicFrame,
    choice: Choice,
    result: Option<[u8; 32]>,
) -> Proposal {
    Proposal {
        from: state,
        requested_to: State::Acting,
        action: choice.action(),
        confidence: observation.confidence,
        evidence: Some(frame.action_evidence(choice, result)),
    }
}

fn frame_only_resolver(features: rdc_experiment_004::ObservationFeatures) -> Choice {
    let primary = (
        features.flags & FLAG_PRIMARY_WARNING != 0,
        features.primary_age,
        1u8,
        features.primary_revision,
    );
    let audit = (
        features.flags & FLAG_AUDIT_WARNING != 0,
        features.audit_age,
        2u8,
        features.audit_revision,
    );
    let (warning, age, _selected_source_id, revision) =
        if primary <= audit { primary } else { audit };
    if age > 0 || warning {
        Choice::RefreshSnapshot
    } else {
        contract_action(features.goal, revision)
    }
}

fn witness_label(
    features: rdc_experiment_004::ObservationFeatures,
    active: Choice,
    shadow: Choice,
) -> &'static str {
    let source_id = if features.flags & FLAG_AUDIT_SELECTED != 0 {
        2
    } else {
        1
    };
    if active != shadow || source_id != 1 {
        return "none";
    }
    if features.primary_age > 0 {
        return "inspect_shared_old_source";
    }
    if features.flags & FLAG_PRIMARY_WARNING != 0 {
        return "inspect_shared_warned_source";
    }
    if features.primary_action != contract_action(features.goal, features.primary_revision) {
        return "inspect_shared_misleading_source";
    }
    "none"
}

fn classify(active: Choice, selected: Choice, correct: Choice) -> &'static str {
    let before = active == correct;
    let after = selected == correct;
    match (before, after) {
        (false, true) => "wrong_to_right",
        (true, false) => "right_to_wrong",
        (true, true) => "both_right",
        (false, false) => "both_wrong",
    }
}

fn manifest(implementation_id: &str) -> ObserverManifest {
    ObserverManifest {
        interface_version: OBSERVER_INTERFACE_VERSION,
        implementation_id: implementation_id.to_owned(),
        input_schema: INPUT_SCHEMA_V1.to_owned(),
        output_schema: OUTPUT_SCHEMA_V1.to_owned(),
        normalization_contract: "rdc005-public-frame-v1".to_owned(),
    }
}

fn elapsed_ns(started: Instant) -> u64 {
    started.elapsed().as_nanos().min(u64::MAX as u128) as u64
}

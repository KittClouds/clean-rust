use std::{cell::RefCell, rc::Rc, time::Instant};

use rdc_experiment_001::{
    Action, Observation, Observer, Proposal, Signal, State, WorkflowObserver,
};
use rdc_experiment_002::{
    INPUT_SCHEMA_V1, OBSERVER_INTERFACE_VERSION, OUTPUT_SCHEMA_V1, ObserverContractError,
    ObserverManifest, ObserverSwitchboard, VersionedObserver, WorkflowAdapter, WorkflowBehavior,
};

use crate::domain::{
    Choice, FLAG_PRIMARY_STALE, FLAG_TOOL_WARNING, ObservationFeatures, choice_proposal,
};

pub const CONFIDENCE_THRESHOLD: u16 = 700;
pub type TraceSink = Rc<RefCell<Option<RouteTrace>>>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EscalationPolicy {
    Never,
    Disagreement,
    ConfidenceThreshold,
    RandomMatched,
}

impl EscalationPolicy {
    pub const ALL: [Self; 4] = [
        Self::Never,
        Self::Disagreement,
        Self::ConfidenceThreshold,
        Self::RandomMatched,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Never => "never",
            Self::Disagreement => "disagreement",
            Self::ConfidenceThreshold => "confidence_threshold",
            Self::RandomMatched => "random_matched",
        }
    }

    fn should_escalate(self, active: Proposal, disagreement: bool, random: bool) -> bool {
        match self {
            Self::Never => false,
            Self::Disagreement => disagreement,
            Self::ConfidenceThreshold => active.confidence.unwrap_or(0) < CONFIDENCE_THRESHOLD,
            Self::RandomMatched => random,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct RouteTrace {
    pub raw_active: Proposal,
    pub raw_shadow: Proposal,
    pub selected: Proposal,
    pub resolver: Option<Proposal>,
    pub action_disagreement: bool,
    pub escalated: bool,
    pub active_observer_ns: u64,
    pub shadow_observer_ns: u64,
    pub routing_ns: u64,
    pub resolver_ns: u64,
}

pub struct RouterObserver {
    manifest: ObserverManifest,
    policy: EscalationPolicy,
    random_escalate: bool,
    trace: TraceSink,
    shadow_cache: Rc<RefCell<Option<Proposal>>>,
    fallback: WorkflowAdapter,
}

pub struct ShadowObserver {
    manifest: ObserverManifest,
    cache: Rc<RefCell<Option<Proposal>>>,
    fallback: WorkflowAdapter,
}

impl RouterObserver {
    pub fn new(
        policy: EscalationPolicy,
        random_escalate: bool,
        trace: TraceSink,
        shadow_cache: Rc<RefCell<Option<Proposal>>>,
    ) -> Self {
        Self {
            manifest: manifest(&format!("rdc003/router/{}/v1", policy.label())),
            policy,
            random_escalate,
            trace,
            shadow_cache,
            fallback: WorkflowAdapter::new("rdc003/fallback-workflow/v1", WorkflowBehavior::Normal),
        }
    }
}

impl ShadowObserver {
    pub fn new(cache: Rc<RefCell<Option<Proposal>>>) -> Self {
        Self {
            manifest: manifest("rdc003/observer-b/audit-filter-v1"),
            cache,
            fallback: WorkflowAdapter::new(
                "rdc003/observer-b-fallback/v1",
                WorkflowBehavior::Normal,
            ),
        }
    }
}

impl VersionedObserver for RouterObserver {
    fn manifest(&self) -> &ObserverManifest {
        &self.manifest
    }

    fn propose(&mut self, state: State, observation: &Observation, recovery_count: u8) -> Proposal {
        if state != State::Deciding || observation.signal != Signal::Approve {
            return self.fallback.propose(state, observation, recovery_count);
        }
        let Some((features, _episode_id)) = ObservationFeatures::decode(observation) else {
            return self.fallback.propose(state, observation, recovery_count);
        };

        let started = Instant::now();
        let raw_active = observer_a(state, observation, features);
        let active_observer_ns = elapsed_ns(started);

        let started = Instant::now();
        let raw_shadow = observer_b(state, observation, features);
        let shadow_observer_ns = elapsed_ns(started);
        *self.shadow_cache.borrow_mut() = Some(raw_shadow);

        let action_disagreement = raw_active.action != raw_shadow.action;
        let started = Instant::now();
        let escalate =
            self.policy
                .should_escalate(raw_active, action_disagreement, self.random_escalate);
        let routing_ns = elapsed_ns(started);

        let (resolver, resolver_ns, selected) = if escalate {
            let started = Instant::now();
            let choice = escalation_resolver(features);
            let resolver_ns = elapsed_ns(started);
            let proposal = choice_proposal(state, observation, choice);
            (Some(proposal), resolver_ns, proposal)
        } else {
            (None, 0, raw_active)
        };

        *self.trace.borrow_mut() = Some(RouteTrace {
            raw_active,
            raw_shadow,
            selected,
            resolver,
            action_disagreement,
            escalated: escalate,
            active_observer_ns,
            shadow_observer_ns,
            routing_ns,
            resolver_ns,
        });
        selected
    }
}

impl VersionedObserver for ShadowObserver {
    fn manifest(&self) -> &ObserverManifest {
        &self.manifest
    }

    fn propose(&mut self, state: State, observation: &Observation, recovery_count: u8) -> Proposal {
        if state == State::Deciding && observation.signal == Signal::Approve {
            if let Some(proposal) = self.cache.borrow_mut().take() {
                return proposal;
            }
            if let Some((features, _)) = ObservationFeatures::decode(observation) {
                return observer_b(state, observation, features);
            }
        }
        self.fallback.propose(state, observation, recovery_count)
    }
}

fn observer_a(state: State, observation: &Observation, features: ObservationFeatures) -> Proposal {
    choice_proposal(state, observation, features.primary_action)
}

fn observer_b(state: State, observation: &Observation, features: ObservationFeatures) -> Proposal {
    let use_audit = features.flags & (FLAG_PRIMARY_STALE | FLAG_TOOL_WARNING) != 0;
    let choice = if use_audit {
        features.audit_action
    } else {
        features.primary_action
    };
    choice_proposal(state, observation, choice)
}

pub fn frozen_observer_pair(observation: &Observation) -> Option<(Proposal, Proposal)> {
    let (features, _) = ObservationFeatures::decode(observation)?;
    Some((
        observer_a(State::Deciding, observation, features),
        observer_b(State::Deciding, observation, features),
    ))
}

/// Frozen contract-aware resolver. It reads the task goal and authoritative world revision;
/// it never receives the held-out answer label or either observer's proposal.
fn escalation_resolver(features: ObservationFeatures) -> Choice {
    match (features.goal % 3, features.world_revision % 3) {
        (0, 0) | (1, 2) | (2, 1) => Choice::UsePrimary,
        (0, 1) | (1, 0) | (2, 2) => Choice::VerifyRecord,
        (0, 2) | (1, 1) | (2, 0) => Choice::RefreshSnapshot,
        _ => unreachable!(),
    }
}

pub fn workflow_fallback(state: State, observation: &Observation) -> Proposal {
    WorkflowObserver.propose(state, observation, 0)
}

fn manifest(implementation_id: &str) -> ObserverManifest {
    ObserverManifest {
        interface_version: OBSERVER_INTERFACE_VERSION,
        implementation_id: implementation_id.to_owned(),
        input_schema: INPUT_SCHEMA_V1.to_owned(),
        output_schema: OUTPUT_SCHEMA_V1.to_owned(),
        normalization_contract: "rdc003-evidence-frame-v1".to_owned(),
    }
}

fn elapsed_ns(started: Instant) -> u64 {
    started.elapsed().as_nanos().min(u64::MAX as u128) as u64
}

pub fn new_trace_sink() -> TraceSink {
    Rc::new(RefCell::new(None))
}

pub fn new_shadow_cache() -> Rc<RefCell<Option<Proposal>>> {
    Rc::new(RefCell::new(None))
}

pub fn make_switchboard(
    policy: EscalationPolicy,
    random_escalate: bool,
    trace: TraceSink,
    shadow_cache: Rc<RefCell<Option<Proposal>>>,
) -> Result<ObserverSwitchboard, ObserverContractError> {
    ObserverSwitchboard::new(
        Box::new(RouterObserver::new(
            policy,
            random_escalate,
            trace,
            shadow_cache.clone(),
        )),
        Box::new(ShadowObserver::new(shadow_cache)),
    )
}

pub fn candidate_action(action: Action) -> Option<Choice> {
    Choice::from_action(action)
}

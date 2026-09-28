use std::{cell::RefCell, rc::Rc, time::Instant};

use rdc_experiment_001::{Observation, Observer, Proposal, Signal, State, WorkflowObserver};
use rdc_experiment_002::{
    INPUT_SCHEMA_V1, OBSERVER_INTERFACE_VERSION, OUTPUT_SCHEMA_V1, ObserverContractError,
    ObserverManifest, ObserverSwitchboard, VersionedObserver,
};

use crate::domain::{
    Choice, FLAG_AUDIT_SELECTED, ObservationFeatures, ToolEvidence, inspect_evidence, proposal,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum Policy {
    Disagreement,
    Confidence,
    Combined,
    RandomMatched,
}

impl Policy {
    pub const ALL: [Self; 4] = [
        Self::Disagreement,
        Self::Confidence,
        Self::Combined,
        Self::RandomMatched,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Disagreement => "disagreement",
            Self::Confidence => "confidence",
            Self::Combined => "combined",
            Self::RandomMatched => "random_matched",
        }
    }

    pub fn index(self) -> u8 {
        match self {
            Self::Disagreement => 0,
            Self::Confidence => 1,
            Self::Combined => 2,
            Self::RandomMatched => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WitnessReason {
    SharedOldSource,
    SharedWarnedSource,
    SharedMisleadingSource,
}

/// This proposal has no Action or State field and cannot authorize a workflow transition.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WitnessProposal {
    NoSignal,
    InspectEvidence {
        source_id: u8,
        reason: WitnessReason,
    },
}

#[derive(Clone, Copy, Debug)]
pub struct RouteTrace {
    pub raw_active: Proposal,
    pub raw_shadow: Proposal,
    pub selected: Proposal,
    pub resolver: Option<Proposal>,
    pub action_disagreement: bool,
    pub witness: WitnessProposal,
    pub escalated: bool,
    pub active_observer_ns: u64,
    pub shadow_observer_ns: u64,
    pub witness_ns: u64,
    pub resolver_ns: u64,
    pub tool_calls: u8,
    pub tool_ns: u64,
    pub resolver_tokens: u32,
}

pub type TraceSink = Rc<RefCell<Option<RouteTrace>>>;
pub type ProposalCache = Rc<RefCell<Option<Proposal>>>;

pub struct RouterObserver {
    manifest: ObserverManifest,
    escalate: bool,
    trace: TraceSink,
    shadow_cache: ProposalCache,
    fallback: WorkflowObserver,
}

pub struct ShadowObserver {
    manifest: ObserverManifest,
    cache: ProposalCache,
    fallback: WorkflowObserver,
}

impl RouterObserver {
    pub fn new(escalate: bool, trace: TraceSink, shadow_cache: ProposalCache) -> Self {
        Self {
            manifest: manifest("rdc004/router/compiled-plan-v1"),
            escalate,
            trace,
            shadow_cache,
            fallback: WorkflowObserver,
        }
    }
}

impl ShadowObserver {
    pub fn new(cache: ProposalCache) -> Self {
        Self {
            manifest: manifest("rdc004/observer-b/audit-filter-v1"),
            cache,
            fallback: WorkflowObserver,
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
        let Some(features) = ObservationFeatures::decode(observation) else {
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
        let witness_started = Instant::now();
        let witness = evidence_witness(raw_active, raw_shadow, features);
        let witness_ns = elapsed_ns(witness_started);

        let mut tool_calls = 0;
        let mut tool_ns = 0;
        let (resolver, resolver_ns, selected) = if self.escalate {
            let started = Instant::now();
            let query_started = Instant::now();
            let primary = inspect_evidence(features, 1);
            let audit = inspect_evidence(features, 2);
            tool_calls = 2;
            tool_ns = elapsed_ns(query_started);
            let selected_tool = resolve_source(primary, audit);
            let choice = selected_tool.map_or(Choice::RefreshSnapshot, |source| {
                if source.age_bucket > 0 || source.warning {
                    Choice::RefreshSnapshot
                } else {
                    crate::episodes::contract_action(features.goal, source.reported_revision)
                }
            });
            let source_id = selected_tool.map_or(0, |source| source.source_id);
            let revision = selected_tool.map_or(0, |source| source.reported_revision);
            let proposal = proposal(state, observation, choice, source_id, revision);
            let duration = elapsed_ns(started);
            (Some(proposal), duration, proposal)
        } else {
            (None, 0, raw_active)
        };
        *self.trace.borrow_mut() = Some(RouteTrace {
            raw_active,
            raw_shadow,
            selected,
            resolver,
            action_disagreement,
            witness,
            escalated: self.escalate,
            active_observer_ns,
            shadow_observer_ns,
            witness_ns,
            resolver_ns,
            tool_calls,
            tool_ns,
            resolver_tokens: 0,
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
            if let Some(features) = ObservationFeatures::decode(observation) {
                return observer_b(state, observation, features);
            }
        }
        self.fallback.propose(state, observation, recovery_count)
    }
}

fn observer_a(state: State, observation: &Observation, f: ObservationFeatures) -> Proposal {
    proposal(state, observation, f.primary_action, 1, f.primary_revision)
}

fn observer_b(state: State, observation: &Observation, f: ObservationFeatures) -> Proposal {
    let source = if f.flags & FLAG_AUDIT_SELECTED != 0 {
        2
    } else {
        1
    };
    let (choice, revision) = if source == 2 {
        (f.audit_action, f.audit_revision)
    } else {
        (f.primary_action, f.primary_revision)
    };
    proposal(state, observation, choice, source, revision)
}

/// Shared evidence witness: it can request inspection only, never specify an action or state.
pub fn evidence_witness(a: Proposal, b: Proposal, f: ObservationFeatures) -> WitnessProposal {
    let (Some(a_evidence), Some(b_evidence)) = (a.evidence, b.evidence) else {
        return WitnessProposal::NoSignal;
    };
    let source_a = ObservationFeatures::cited_source(a_evidence);
    let source_b = ObservationFeatures::cited_source(b_evidence);
    if a.action != b.action || source_a == 0 || source_a != source_b {
        return WitnessProposal::NoSignal;
    }
    let Some(source) = f.source(source_a) else {
        return WitnessProposal::NoSignal;
    };
    if source.age_bucket > 0 {
        WitnessProposal::InspectEvidence {
            source_id: source_a,
            reason: WitnessReason::SharedOldSource,
        }
    } else if source.warning {
        WitnessProposal::InspectEvidence {
            source_id: source_a,
            reason: WitnessReason::SharedWarnedSource,
        }
    } else if source.recommendation
        != crate::episodes::contract_action(f.goal, source.reported_revision)
    {
        WitnessProposal::InspectEvidence {
            source_id: source_a,
            reason: WitnessReason::SharedMisleadingSource,
        }
    } else {
        WitnessProposal::NoSignal
    }
}

fn resolve_source(
    primary: Option<ToolEvidence>,
    audit: Option<ToolEvidence>,
) -> Option<ToolEvidence> {
    [primary, audit]
        .into_iter()
        .flatten()
        .min_by_key(|source| (source.warning, source.age_bucket, source.source_id))
}

fn manifest(implementation_id: &str) -> ObserverManifest {
    ObserverManifest {
        interface_version: OBSERVER_INTERFACE_VERSION,
        implementation_id: implementation_id.to_owned(),
        input_schema: INPUT_SCHEMA_V1.to_owned(),
        output_schema: OUTPUT_SCHEMA_V1.to_owned(),
        normalization_contract: "rdc004-source-frame-v1".to_owned(),
    }
}

fn elapsed_ns(started: Instant) -> u64 {
    started.elapsed().as_nanos().min(u64::MAX as u128) as u64
}

pub fn new_trace_sink() -> TraceSink {
    Rc::new(RefCell::new(None))
}

pub fn new_shadow_cache() -> ProposalCache {
    Rc::new(RefCell::new(None))
}

pub fn make_switchboard(
    escalate: bool,
    trace: TraceSink,
    shadow_cache: ProposalCache,
) -> Result<ObserverSwitchboard, ObserverContractError> {
    ObserverSwitchboard::new(
        Box::new(RouterObserver::new(escalate, trace, shadow_cache.clone())),
        Box::new(ShadowObserver::new(shadow_cache)),
    )
}

pub fn workflow_fallback(state: State, observation: &Observation) -> Proposal {
    let mut observer = WorkflowObserver;
    observer.propose(state, observation, 0)
}

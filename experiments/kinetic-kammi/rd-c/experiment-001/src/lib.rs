use std::hash::Hash;

use hashbrown::HashMap;

pub const STATE_COUNT: usize = 7;
pub const ACTION_COUNT: usize = 7;
const TABLE_LEN: usize = STATE_COUNT * STATE_COUNT * ACTION_COUNT;
const GENESIS_HASH: [u8; 32] = [0; 32];

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[repr(u8)]
pub enum State {
    Idle = 0,
    Observing = 1,
    Deciding = 2,
    Acting = 3,
    Verifying = 4,
    Done = 5,
    Failed = 6,
}

impl State {
    pub const ALL: [Self; STATE_COUNT] = [
        Self::Idle,
        Self::Observing,
        Self::Deciding,
        Self::Acting,
        Self::Verifying,
        Self::Done,
        Self::Failed,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Idle => "IDLE",
            Self::Observing => "OBSERVING",
            Self::Deciding => "DECIDING",
            Self::Acting => "ACTING",
            Self::Verifying => "VERIFYING",
            Self::Done => "DONE",
            Self::Failed => "FAILED",
        }
    }
}

impl TryFrom<u8> for State {
    type Error = ();

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        Self::ALL.get(value as usize).copied().ok_or(())
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[repr(u8)]
pub enum Action {
    Observe = 0,
    Decide = 1,
    Execute = 2,
    Verify = 3,
    Complete = 4,
    Fail = 5,
    Recover = 6,
}

impl Action {
    pub const ALL: [Self; ACTION_COUNT] = [
        Self::Observe,
        Self::Decide,
        Self::Execute,
        Self::Verify,
        Self::Complete,
        Self::Fail,
        Self::Recover,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Observe => "observe",
            Self::Decide => "decide",
            Self::Execute => "execute",
            Self::Verify => "verify",
            Self::Complete => "complete",
            Self::Fail => "fail",
            Self::Recover => "recover",
        }
    }
}

impl TryFrom<u8> for Action {
    type Error = ();

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        Self::ALL.get(value as usize).copied().ok_or(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Evidence {
    pub code: u16,
    pub digest: [u8; 16],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Proposal {
    pub from: State,
    pub requested_to: State,
    pub action: Action,
    /// Fixed-point confidence in thousandths, from 0 through 1000.
    pub confidence: Option<u16>,
    pub evidence: Option<Evidence>,
}

impl Proposal {
    pub fn new(from: State, requested_to: State, action: Action) -> Self {
        Self {
            from,
            requested_to,
            action,
            confidence: None,
            evidence: None,
        }
    }

    pub fn with_confidence(mut self, confidence: u16) -> Self {
        self.confidence = Some(confidence);
        self
    }

    pub fn with_evidence(mut self, evidence: Evidence) -> Self {
        self.evidence = Some(evidence);
        self
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Signal {
    Start,
    Observed,
    Approve,
    Reject,
    ActionSucceeded,
    ActionFailed,
    Verified,
    VerificationFailed,
    Recover,
    Unexpected,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Observation {
    pub signal: Signal,
    pub confidence: Option<u16>,
    pub evidence: Option<Evidence>,
}

impl Observation {
    pub fn new(signal: Signal) -> Self {
        Self {
            signal,
            confidence: None,
            evidence: None,
        }
    }

    pub fn with_confidence(mut self, confidence: u16) -> Self {
        self.confidence = Some(confidence);
        self
    }

    pub fn with_evidence(mut self, evidence: Evidence) -> Self {
        self.evidence = Some(evidence);
        self
    }
}

/// An observer proposes. The runtime and compiled schema retain all authority.
pub trait Observer {
    fn propose(&mut self, state: State, observation: &Observation, recovery_count: u8) -> Proposal;
}

/// Small hand-written observer used as the baseline and demo.
#[derive(Default)]
pub struct WorkflowObserver;

impl Observer for WorkflowObserver {
    fn propose(
        &mut self,
        state: State,
        observation: &Observation,
        _recovery_count: u8,
    ) -> Proposal {
        let target = match (state, observation.signal) {
            (State::Idle, Signal::Start) => Some((State::Observing, Action::Observe)),
            (State::Observing, Signal::Observed) => Some((State::Deciding, Action::Decide)),
            (State::Deciding, Signal::Approve) => Some((State::Acting, Action::Execute)),
            (State::Deciding, Signal::Reject) => Some((State::Failed, Action::Fail)),
            (State::Acting, Signal::ActionSucceeded) => Some((State::Verifying, Action::Verify)),
            (State::Acting, Signal::ActionFailed) => Some((State::Failed, Action::Fail)),
            (State::Verifying, Signal::Verified) => Some((State::Done, Action::Complete)),
            (State::Verifying, Signal::VerificationFailed) => Some((State::Failed, Action::Fail)),
            (State::Failed, Signal::Recover) => Some((State::Observing, Action::Recover)),
            _ => None,
        };
        let (requested_to, action) = target.unwrap_or((State::Done, Action::Complete));
        Proposal {
            from: state,
            requested_to,
            action,
            confidence: observation.confidence,
            evidence: observation.evidence,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Guard {
    pub min_confidence: Option<u16>,
    pub requires_evidence: bool,
    pub max_recoveries: Option<u8>,
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
struct TransitionKey {
    from: State,
    to: State,
    action: Action,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TransitionSpec {
    pub from: State,
    pub to: State,
    pub action: Action,
    pub guard: Guard,
}

impl TransitionSpec {
    pub const fn new(from: State, to: State, action: Action, guard: Guard) -> Self {
        Self {
            from,
            to,
            action,
            guard,
        }
    }

    fn key(self) -> TransitionKey {
        TransitionKey {
            from: self.from,
            to: self.to,
            action: self.action,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CompiledRule {
    guard: Guard,
}

#[derive(Clone, Debug)]
pub struct DecisionCompiler {
    table: Box<[Option<CompiledRule>]>,
    transition_count: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompileError {
    DuplicateTransition,
    InvalidConfidenceGuard,
    ZeroRecoveryLimit,
}

impl std::fmt::Display for CompileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::DuplicateTransition => f.write_str("duplicate transition in schema"),
            Self::InvalidConfidenceGuard => f.write_str("confidence guard exceeds 1000"),
            Self::ZeroRecoveryLimit => f.write_str("recovery limit must be positive"),
        }
    }
}

impl std::error::Error for CompileError {}

impl DecisionCompiler {
    pub fn compile(schema: &[TransitionSpec]) -> Result<Self, CompileError> {
        let mut seen = HashMap::with_capacity(schema.len());
        let mut table = vec![None; TABLE_LEN];
        for spec in schema {
            if spec.guard.min_confidence.is_some_and(|v| v > 1000) {
                return Err(CompileError::InvalidConfidenceGuard);
            }
            if spec.guard.max_recoveries == Some(0) {
                return Err(CompileError::ZeroRecoveryLimit);
            }
            if seen.insert(spec.key(), ()).is_some() {
                return Err(CompileError::DuplicateTransition);
            }
            let slot = table_index(spec.from, spec.to, spec.action);
            table[slot] = Some(CompiledRule { guard: spec.guard });
        }
        Ok(Self {
            table: table.into_boxed_slice(),
            transition_count: schema.len(),
        })
    }

    fn rule(&self, key: TransitionKey) -> Option<CompiledRule> {
        self.table[table_index(key.from, key.to, key.action)]
    }

    pub fn transition_count(&self) -> usize {
        self.transition_count
    }

    pub fn table_bytes(&self) -> usize {
        self.table.len() * std::mem::size_of::<Option<CompiledRule>>()
    }
}

fn table_index(from: State, to: State, action: Action) -> usize {
    ((from as usize * STATE_COUNT + to as usize) * ACTION_COUNT) + action as usize
}

pub fn standard_schema() -> Vec<TransitionSpec> {
    use Action as A;
    use State as S;
    let mut specs = Vec::with_capacity(9);
    let add = |specs: &mut Vec<_>, from, to, action, guard| {
        specs.push(TransitionSpec::new(from, to, action, guard));
    };
    let evidence = Guard {
        requires_evidence: true,
        ..Guard::default()
    };
    add(
        &mut specs,
        S::Idle,
        S::Observing,
        A::Observe,
        Guard::default(),
    );
    add(&mut specs, S::Observing, S::Deciding, A::Decide, evidence);
    add(
        &mut specs,
        S::Deciding,
        S::Acting,
        A::Execute,
        Guard {
            min_confidence: Some(700),
            requires_evidence: true,
            max_recoveries: None,
        },
    );
    add(
        &mut specs,
        S::Deciding,
        S::Failed,
        A::Fail,
        Guard::default(),
    );
    add(
        &mut specs,
        S::Acting,
        S::Verifying,
        A::Verify,
        Guard::default(),
    );
    add(&mut specs, S::Acting, S::Failed, A::Fail, Guard::default());
    add(&mut specs, S::Verifying, S::Done, A::Complete, evidence);
    add(
        &mut specs,
        S::Verifying,
        S::Failed,
        A::Fail,
        Guard::default(),
    );
    add(
        &mut specs,
        S::Failed,
        S::Observing,
        A::Recover,
        Guard {
            min_confidence: Some(600),
            requires_evidence: true,
            max_recoveries: Some(2),
        },
    );
    specs
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum RejectionReason {
    StaleFromState = 1,
    InvalidConfidence = 2,
    UnknownTransition = 3,
    ConfidenceMissing = 4,
    ConfidenceTooLow = 5,
    EvidenceMissing = 6,
    RecoveryLimit = 7,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Receipt {
    pub sequence: u64,
    pub before: State,
    pub after: State,
    pub proposal: Proposal,
    pub authorized_action: Option<Action>,
    pub rejection: Option<RejectionReason>,
    pub previous_hash: [u8; 32],
    pub hash: [u8; 32],
}

impl Receipt {
    pub fn accepted(&self) -> bool {
        self.rejection.is_none()
    }
}

pub struct Runtime {
    compiler: DecisionCompiler,
    state: State,
    recovery_count: u8,
    receipts: Vec<Receipt>,
}

impl Runtime {
    pub fn new(compiler: DecisionCompiler) -> Self {
        Self::with_capacity(compiler, 0)
    }

    pub fn with_capacity(compiler: DecisionCompiler, receipt_capacity: usize) -> Self {
        Self {
            compiler,
            state: State::Idle,
            recovery_count: 0,
            receipts: Vec::with_capacity(receipt_capacity),
        }
    }

    pub fn state(&self) -> State {
        self.state
    }

    pub fn recovery_count(&self) -> u8 {
        self.recovery_count
    }

    pub fn receipts(&self) -> &[Receipt] {
        &self.receipts
    }

    pub fn apply(&mut self, proposal: Proposal) -> Receipt {
        let before = self.state;
        let previous_hash = self
            .receipts
            .last()
            .map_or(GENESIS_HASH, |receipt| receipt.hash);
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

    pub fn step<O: Observer>(&mut self, observation: &Observation, observer: &mut O) -> Receipt {
        let proposal = observer.propose(self.state, observation, self.recovery_count);
        self.apply(proposal)
    }

    pub fn reset(&mut self) {
        self.state = State::Idle;
        self.recovery_count = 0;
        self.receipts.clear();
    }

    fn validate(&self, proposal: Proposal) -> Option<RejectionReason> {
        if proposal.from != self.state {
            return Some(RejectionReason::StaleFromState);
        }
        if proposal.confidence.is_some_and(|value| value > 1000) {
            return Some(RejectionReason::InvalidConfidence);
        }
        let key = TransitionKey {
            from: proposal.from,
            to: proposal.requested_to,
            action: proposal.action,
        };
        let Some(rule) = self.compiler.rule(key) else {
            return Some(RejectionReason::UnknownTransition);
        };
        if let Some(minimum) = rule.guard.min_confidence {
            let Some(confidence) = proposal.confidence else {
                return Some(RejectionReason::ConfidenceMissing);
            };
            if confidence < minimum {
                return Some(RejectionReason::ConfidenceTooLow);
            }
        }
        if rule.guard.requires_evidence && proposal.evidence.is_none() {
            return Some(RejectionReason::EvidenceMissing);
        }
        if rule
            .guard
            .max_recoveries
            .is_some_and(|limit| self.recovery_count >= limit)
        {
            return Some(RejectionReason::RecoveryLimit);
        }
        None
    }
}

pub fn receipt_identity(
    sequence: u64,
    before: State,
    after: State,
    proposal: Proposal,
    authorized_action: Option<Action>,
    rejection: Option<RejectionReason>,
    previous_hash: [u8; 32],
) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-EXPERIMENT-001-RECEIPT-V1\0");
    hasher.update(&sequence.to_le_bytes());
    hasher.update(&previous_hash);
    hasher.update(&[
        before as u8,
        after as u8,
        proposal.from as u8,
        proposal.requested_to as u8,
        proposal.action as u8,
    ]);
    match proposal.confidence {
        Some(value) => hasher.update(&[1, (value & 0xff) as u8, (value >> 8) as u8]),
        None => hasher.update(&[0, 0, 0]),
    };
    match proposal.evidence {
        Some(evidence) => {
            hasher.update(&[1]);
            hasher.update(&evidence.code.to_le_bytes());
            hasher.update(&evidence.digest);
        }
        None => {
            hasher.update(&[0]);
        }
    };
    hasher.update(&[authorized_action.map_or(u8::MAX, |action| action as u8)]);
    hasher.update(&[rejection.map_or(0, |reason| reason as u8)]);
    *hasher.finalize().as_bytes()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evidence() -> Evidence {
        Evidence {
            code: 7,
            digest: [0x2a; 16],
        }
    }

    #[test]
    fn compiled_schema_has_nine_transitions_and_dense_dispatch() {
        let compiler = DecisionCompiler::compile(&standard_schema()).unwrap();
        assert_eq!(compiler.transition_count(), 9);
        assert!(compiler.table_bytes() > 0);
    }

    #[test]
    fn duplicate_transition_is_rejected_at_compile_time() {
        let schema = [
            TransitionSpec::new(
                State::Idle,
                State::Observing,
                Action::Observe,
                Guard::default(),
            ),
            TransitionSpec::new(
                State::Idle,
                State::Observing,
                Action::Observe,
                Guard::default(),
            ),
        ];
        assert_eq!(
            DecisionCompiler::compile(&schema).unwrap_err(),
            CompileError::DuplicateTransition
        );
    }

    #[test]
    fn illegal_transition_is_receipted_and_does_not_change_state() {
        let mut runtime = Runtime::new(DecisionCompiler::compile(&standard_schema()).unwrap());
        let receipt = runtime.apply(Proposal::new(State::Idle, State::Done, Action::Complete));
        assert_eq!(receipt.rejection, Some(RejectionReason::UnknownTransition));
        assert_eq!(receipt.authorized_action, None);
        assert_eq!(receipt.before, State::Idle);
        assert_eq!(receipt.after, State::Idle);
        assert_eq!(runtime.state(), State::Idle);
    }

    #[test]
    fn confidence_and_evidence_guards_are_explicit() {
        let mut runtime = Runtime::new(DecisionCompiler::compile(&standard_schema()).unwrap());
        runtime.apply(Proposal::new(
            State::Idle,
            State::Observing,
            Action::Observe,
        ));
        runtime.apply(
            Proposal::new(State::Observing, State::Deciding, Action::Decide)
                .with_evidence(evidence()),
        );
        let no_confidence = runtime.apply(
            Proposal::new(State::Deciding, State::Acting, Action::Execute)
                .with_evidence(evidence()),
        );
        assert_eq!(
            no_confidence.rejection,
            Some(RejectionReason::ConfidenceMissing)
        );
        let low_confidence = runtime.apply(
            Proposal::new(State::Deciding, State::Acting, Action::Execute)
                .with_confidence(699)
                .with_evidence(evidence()),
        );
        assert_eq!(
            low_confidence.rejection,
            Some(RejectionReason::ConfidenceTooLow)
        );
        let no_evidence = runtime.apply(
            Proposal::new(State::Deciding, State::Acting, Action::Execute).with_confidence(900),
        );
        assert_eq!(
            no_evidence.rejection,
            Some(RejectionReason::EvidenceMissing)
        );
    }

    #[test]
    fn workflow_observer_completes_and_proposals_are_replayable() {
        let mut runtime = Runtime::new(DecisionCompiler::compile(&standard_schema()).unwrap());
        let mut observer = WorkflowObserver;
        for signal in [
            Signal::Start,
            Signal::Observed,
            Signal::Approve,
            Signal::ActionSucceeded,
            Signal::Verified,
        ] {
            let mut observation = Observation::new(signal);
            if signal != Signal::Start {
                observation = observation.with_evidence(evidence());
            }
            if matches!(signal, Signal::Approve | Signal::Recover) {
                observation = observation.with_confidence(900);
            }
            assert!(runtime.step(&observation, &mut observer).accepted());
        }
        assert_eq!(runtime.state(), State::Done);
        let first: Vec<_> = runtime.receipts().iter().map(|r| r.hash).collect();
        runtime.reset();
        let mut observer = WorkflowObserver;
        for signal in [
            Signal::Start,
            Signal::Observed,
            Signal::Approve,
            Signal::ActionSucceeded,
            Signal::Verified,
        ] {
            let mut observation = Observation::new(signal);
            if signal != Signal::Start {
                observation = observation.with_evidence(evidence());
            }
            if signal == Signal::Approve {
                observation = observation.with_confidence(900);
            }
            runtime.step(&observation, &mut observer);
        }
        let second: Vec<_> = runtime.receipts().iter().map(|r| r.hash).collect();
        assert_eq!(first, second);
    }

    #[test]
    fn recoveries_are_bounded_by_compiled_guard() {
        let mut runtime = Runtime::new(DecisionCompiler::compile(&standard_schema()).unwrap());
        runtime.apply(Proposal::new(
            State::Idle,
            State::Observing,
            Action::Observe,
        ));
        runtime.apply(
            Proposal::new(State::Observing, State::Deciding, Action::Decide)
                .with_evidence(evidence()),
        );
        runtime.apply(Proposal::new(State::Deciding, State::Failed, Action::Fail));
        for expected in 1..=2 {
            let recovery = runtime.apply(
                Proposal::new(State::Failed, State::Observing, Action::Recover)
                    .with_confidence(900)
                    .with_evidence(evidence()),
            );
            assert!(recovery.accepted());
            assert_eq!(runtime.recovery_count(), expected);
            runtime.apply(
                Proposal::new(State::Observing, State::Deciding, Action::Decide)
                    .with_evidence(evidence()),
            );
            runtime.apply(Proposal::new(State::Deciding, State::Failed, Action::Fail));
        }
        let exhausted = runtime.apply(
            Proposal::new(State::Failed, State::Observing, Action::Recover)
                .with_confidence(900)
                .with_evidence(evidence()),
        );
        assert_eq!(exhausted.rejection, Some(RejectionReason::RecoveryLimit));
    }
}
mod journal;

pub use journal::{JournalError, ReplayReport, replay_mmap, write_journal};

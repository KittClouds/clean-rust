use serde::{Deserialize, Serialize};

use rdc_experiment_001::{Action, Evidence, Observation, Proposal, Receipt, Signal, State};

pub const JOURNAL_VERSION: u16 = 2;
pub const OBSERVER_INTERFACE_VERSION: u16 = 1;
pub const INPUT_SCHEMA_V1: &str = "rdc.observation.v1";
pub const OUTPUT_SCHEMA_V1: &str = "rdc.transition-proposal.v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ObserverManifest {
    pub interface_version: u16,
    pub implementation_id: String,
    pub input_schema: String,
    pub output_schema: String,
    pub normalization_contract: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ObserverRegistry {
    pub epoch: u64,
    pub active: ObserverManifest,
    pub shadow: ObserverManifest,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EvidenceSnapshot {
    pub code: u16,
    pub digest: [u8; 16],
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ProposalSnapshot {
    pub from: u8,
    pub requested_to: u8,
    pub action: u8,
    pub confidence: Option<u16>,
    pub evidence: Option<EvidenceSnapshot>,
}

impl From<Proposal> for ProposalSnapshot {
    fn from(proposal: Proposal) -> Self {
        Self {
            from: proposal.from as u8,
            requested_to: proposal.requested_to as u8,
            action: proposal.action as u8,
            confidence: proposal.confidence,
            evidence: proposal.evidence.map(|evidence| EvidenceSnapshot {
                code: evidence.code,
                digest: evidence.digest,
            }),
        }
    }
}

impl TryFrom<ProposalSnapshot> for Proposal {
    type Error = &'static str;

    fn try_from(snapshot: ProposalSnapshot) -> Result<Self, Self::Error> {
        Ok(Self {
            from: State::try_from(snapshot.from).map_err(|_| "unknown source state")?,
            requested_to: State::try_from(snapshot.requested_to)
                .map_err(|_| "unknown target state")?,
            action: Action::try_from(snapshot.action).map_err(|_| "unknown action")?,
            confidence: snapshot.confidence,
            evidence: snapshot.evidence.map(|e| Evidence {
                code: e.code,
                digest: e.digest,
            }),
        })
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ObservationSnapshot {
    pub signal: u8,
    pub confidence: Option<u16>,
    pub evidence: Option<EvidenceSnapshot>,
}

impl From<Observation> for ObservationSnapshot {
    fn from(observation: Observation) -> Self {
        Self {
            signal: signal_code(observation.signal),
            confidence: observation.confidence,
            evidence: observation.evidence.map(|evidence| EvidenceSnapshot {
                code: evidence.code,
                digest: evidence.digest,
            }),
        }
    }
}

impl TryFrom<ObservationSnapshot> for Observation {
    type Error = &'static str;

    fn try_from(snapshot: ObservationSnapshot) -> Result<Self, Self::Error> {
        Ok(Self {
            signal: signal_from_code(snapshot.signal).ok_or("unknown observation signal")?,
            confidence: snapshot.confidence,
            evidence: snapshot.evidence.map(|e| Evidence {
                code: e.code,
                digest: e.digest,
            }),
        })
    }
}

fn signal_code(signal: Signal) -> u8 {
    match signal {
        Signal::Start => 0,
        Signal::Observed => 1,
        Signal::Approve => 2,
        Signal::Reject => 3,
        Signal::ActionSucceeded => 4,
        Signal::ActionFailed => 5,
        Signal::Verified => 6,
        Signal::VerificationFailed => 7,
        Signal::Recover => 8,
        Signal::Unexpected => 9,
    }
}

fn signal_from_code(code: u8) -> Option<Signal> {
    match code {
        0 => Some(Signal::Start),
        1 => Some(Signal::Observed),
        2 => Some(Signal::Approve),
        3 => Some(Signal::Reject),
        4 => Some(Signal::ActionSucceeded),
        5 => Some(Signal::ActionFailed),
        6 => Some(Signal::Verified),
        7 => Some(Signal::VerificationFailed),
        8 => Some(Signal::Recover),
        9 => Some(Signal::Unexpected),
        _ => None,
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ReceiptSnapshot {
    pub sequence: u64,
    pub before: u8,
    pub after: u8,
    pub proposal: ProposalSnapshot,
    pub authorized_action: Option<u8>,
    pub rejection: Option<u8>,
    pub previous_hash: [u8; 32],
    pub hash: [u8; 32],
}

impl From<Receipt> for ReceiptSnapshot {
    fn from(receipt: Receipt) -> Self {
        Self {
            sequence: receipt.sequence,
            before: receipt.before as u8,
            after: receipt.after as u8,
            proposal: receipt.proposal.into(),
            authorized_action: receipt.authorized_action.map(|action| action as u8),
            rejection: receipt.rejection.map(|reason| reason as u8),
            previous_hash: receipt.previous_hash,
            hash: receipt.hash,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "payload")]
pub enum JournalEvent {
    ObserverRegistry {
        registry: ObserverRegistry,
        observer_swap_ns: Option<u64>,
    },
    Proposals {
        task_id: u64,
        step: u32,
        registry_epoch: u64,
        observation: ObservationSnapshot,
        active: ProposalSnapshot,
        shadow: ProposalSnapshot,
        active_observer_ns: u64,
        shadow_observer_ns: u64,
        disagreement: bool,
    },
    Transition {
        step: u32,
        receipt: ReceiptSnapshot,
    },
    ActionIntent {
        action_id: [u8; 16],
        task_id: u64,
        step: u32,
        transition_sequence: u64,
        action: u8,
    },
    ActionCompleted {
        action_id: [u8; 16],
        effect_index: u64,
        idempotent_reuse: bool,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct JournalEnvelope {
    pub sequence: u64,
    pub previous_hash: [u8; 32],
    pub event: JournalEvent,
    pub hash: [u8; 32],
}

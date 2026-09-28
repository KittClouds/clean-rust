//! Versioned contracts for typed inspection and durable paid external actions.

pub mod candidate_presentation;
pub mod inspection;
pub mod paid_action;

pub use candidate_presentation::{
    CandidateIdentity, CandidatePresentationError, SequencedCandidate,
    encode_candidate_presentation, order_by_producer_ordinal, resolve_candidate_proposal,
    validate_candidate_presentation,
};
pub use inspection::{
    ActionCode, InspectionKind, InspectionReply, InspectionResult, TransportStatus,
};
pub use paid_action::{
    CrashPoint, EndpointResponse, JournalStats, PaidActionEndpoint, QueryJournal, RequestId,
    ResultBytes,
};

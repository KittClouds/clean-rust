//! Versioned, ordered candidate identity receipts for observer requests.
//!
//! The receipt binds a task to the exact sequence of action IDs and patch digests
//! shown to an observer. Validation reads the encoded receipt without allocating.

use hashbrown::HashSet;
use zerocopy::{
    FromBytes, Immutable, IntoBytes, KnownLayout, byteorder::LittleEndian, byteorder::U16,
    byteorder::U32,
};

use crate::{ActionCode, inspection::NO_ACTION};

const MAGIC: [u8; 4] = *b"RDCQ";
const VERSION: u16 = 1;
/// Candidate sets are small in this workflow; this bound keeps borrowed
/// validation's duplicate check predictable and allocation-free.
const MAX_CANDIDATES: usize = 256;
const DOMAIN: &[u8] = b"RDC-CANDIDATE-PRESENTATION-V1\0";

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, FromBytes, IntoBytes, KnownLayout, Immutable)]
struct ReceiptHeader {
    magic: [u8; 4],
    version: U16<LittleEndian>,
    candidate_count: U32<LittleEndian>,
    task_digest: [u8; 32],
    sequence_digest: [u8; 32],
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, FromBytes, IntoBytes, KnownLayout, Immutable)]
struct CandidateEntry {
    action_code: U16<LittleEndian>,
    patch_digest: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct CandidateIdentity {
    pub action: ActionCode,
    pub patch_digest: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CandidatePresentationError {
    EmptyCandidateSet,
    TooManyCandidates,
    DuplicateActionCode,
    DuplicatePatchDigest,
    ReservedActionCode,
    DuplicateProducerOrdinal,
    InvalidReceipt,
    UnsupportedVersion,
    TaskChanged,
    CandidateCountChanged,
    CandidateSequenceChanged,
    SequenceDigestMismatch,
    ProposalNotOffered,
}

impl std::fmt::Display for CandidatePresentationError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::EmptyCandidateSet => "candidate set is empty",
            Self::TooManyCandidates => "candidate count exceeds the receipt format",
            Self::DuplicateActionCode => "candidate action codes must be unique",
            Self::DuplicatePatchDigest => "candidate patch digests must be unique",
            Self::ReservedActionCode => "reserved no-action code cannot name a candidate",
            Self::DuplicateProducerOrdinal => "candidate producer ordinals must be unique",
            Self::InvalidReceipt => "candidate presentation receipt is malformed",
            Self::UnsupportedVersion => "candidate presentation receipt version is unsupported",
            Self::TaskChanged => "candidate presentation task identity changed",
            Self::CandidateCountChanged => "candidate count changed after observer request",
            Self::CandidateSequenceChanged => {
                "candidate order or identity changed after observer request"
            }
            Self::SequenceDigestMismatch => "candidate presentation sequence digest is invalid",
            Self::ProposalNotOffered => "observer proposal does not name an offered action",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for CandidatePresentationError {}

/// An action plus the immutable sequence number assigned when its producer
/// created it. Carry this wrapper through queues and sort by the ordinal before
/// serializing observer input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequencedCandidate<T> {
    pub producer_ordinal: u16,
    pub value: T,
}

/// Restores producer order in place without allocating. The bounded candidate
/// count limits the duplicate-ordinal check while keeping the hot path simple.
pub fn order_by_producer_ordinal<T>(
    candidates: &mut [SequencedCandidate<T>],
) -> Result<(), CandidatePresentationError> {
    if candidates.is_empty() {
        return Err(CandidatePresentationError::EmptyCandidateSet);
    }
    if candidates.len() > MAX_CANDIDATES {
        return Err(CandidatePresentationError::TooManyCandidates);
    }
    for (index, candidate) in candidates.iter().enumerate() {
        if candidates[..index]
            .iter()
            .any(|prior| prior.producer_ordinal == candidate.producer_ordinal)
        {
            return Err(CandidatePresentationError::DuplicateProducerOrdinal);
        }
    }
    candidates.sort_unstable_by_key(|candidate| candidate.producer_ordinal);
    Ok(())
}

/// Encodes the ordered options shown to an observer as a compact versioned receipt.
/// Duplicate action codes or patch digests are rejected because either would make
/// proposal-to-action mapping ambiguous.
pub fn encode_candidate_presentation(
    task_digest: [u8; 32],
    candidates: &[CandidateIdentity],
) -> Result<Vec<u8>, CandidatePresentationError> {
    validate_candidate_set(candidates)?;
    let candidate_count = candidates.len() as u32;

    let header = ReceiptHeader {
        magic: MAGIC,
        version: U16::new(VERSION),
        candidate_count: U32::new(candidate_count),
        task_digest,
        sequence_digest: sequence_digest(task_digest, candidates),
    };

    let byte_len = std::mem::size_of::<ReceiptHeader>()
        .checked_add(
            candidates
                .len()
                .checked_mul(std::mem::size_of::<CandidateEntry>())
                .ok_or(CandidatePresentationError::TooManyCandidates)?,
        )
        .ok_or(CandidatePresentationError::TooManyCandidates)?;
    let mut bytes = Vec::with_capacity(byte_len);
    bytes.extend_from_slice(header.as_bytes());
    for candidate in candidates {
        let entry = CandidateEntry {
            action_code: U16::new(candidate.action.0),
            patch_digest: candidate.patch_digest,
        };
        bytes.extend_from_slice(entry.as_bytes());
    }
    Ok(bytes)
}

/// Validates a persisted receipt against the exact ordered options about to be
/// authorized. The encoded entries are viewed in place; this path allocates no
/// heap memory.
pub fn validate_candidate_presentation(
    receipt: &[u8],
    task_digest: [u8; 32],
    candidates: &[CandidateIdentity],
) -> Result<(), CandidatePresentationError> {
    validate_candidate_set_borrowed(candidates)?;
    let (header, entries_bytes) = ReceiptHeader::ref_from_prefix(receipt)
        .map_err(|_| CandidatePresentationError::InvalidReceipt)?;
    if header.magic != MAGIC {
        return Err(CandidatePresentationError::InvalidReceipt);
    }
    if header.version.get() != VERSION {
        return Err(CandidatePresentationError::UnsupportedVersion);
    }
    if header.task_digest != task_digest {
        return Err(CandidatePresentationError::TaskChanged);
    }
    if header.candidate_count.get() as usize != candidates.len() {
        return Err(CandidatePresentationError::CandidateCountChanged);
    }
    let expected_entries_len = candidates
        .len()
        .checked_mul(std::mem::size_of::<CandidateEntry>())
        .ok_or(CandidatePresentationError::InvalidReceipt)?;
    if entries_bytes.len() != expected_entries_len {
        return Err(CandidatePresentationError::InvalidReceipt);
    }
    let (entries, trailing_bytes) =
        <[CandidateEntry]>::ref_from_prefix_with_elems(entries_bytes, candidates.len())
            .map_err(|_| CandidatePresentationError::InvalidReceipt)?;
    if !trailing_bytes.is_empty() {
        return Err(CandidatePresentationError::InvalidReceipt);
    }
    for (entry, candidate) in entries.iter().zip(candidates) {
        if entry.action_code.get() != candidate.action.0
            || entry.patch_digest != candidate.patch_digest
        {
            return Err(CandidatePresentationError::CandidateSequenceChanged);
        }
    }
    if header.sequence_digest != sequence_digest(task_digest, candidates) {
        return Err(CandidatePresentationError::SequenceDigestMismatch);
    }
    Ok(())
}

/// Resolves an observer action only after the persisted presentation has been
/// validated. `None` is a valid abstention; an unoffered action is rejected.
pub fn resolve_candidate_proposal(
    receipt: &[u8],
    task_digest: [u8; 32],
    candidates: &[CandidateIdentity],
    proposed_action: Option<ActionCode>,
) -> Result<Option<CandidateIdentity>, CandidatePresentationError> {
    validate_candidate_presentation(receipt, task_digest, candidates)?;
    let Some(action) = proposed_action else {
        return Ok(None);
    };
    candidates
        .iter()
        .copied()
        .find(|candidate| candidate.action == action)
        .map(Some)
        .ok_or(CandidatePresentationError::ProposalNotOffered)
}

fn validate_candidate_set(
    candidates: &[CandidateIdentity],
) -> Result<(), CandidatePresentationError> {
    if candidates.is_empty() {
        return Err(CandidatePresentationError::EmptyCandidateSet);
    }
    if candidates.len() > MAX_CANDIDATES {
        return Err(CandidatePresentationError::TooManyCandidates);
    }
    let mut action_codes = HashSet::with_capacity(candidates.len());
    let mut patch_digests = HashSet::with_capacity(candidates.len());
    for candidate in candidates {
        if candidate.action.0 == NO_ACTION {
            return Err(CandidatePresentationError::ReservedActionCode);
        }
        if !action_codes.insert(candidate.action.0) {
            return Err(CandidatePresentationError::DuplicateActionCode);
        }
        if !patch_digests.insert(candidate.patch_digest) {
            return Err(CandidatePresentationError::DuplicatePatchDigest);
        }
    }
    Ok(())
}

fn validate_candidate_set_borrowed(
    candidates: &[CandidateIdentity],
) -> Result<(), CandidatePresentationError> {
    if candidates.is_empty() {
        return Err(CandidatePresentationError::EmptyCandidateSet);
    }
    if candidates.len() > MAX_CANDIDATES {
        return Err(CandidatePresentationError::TooManyCandidates);
    }
    for (index, candidate) in candidates.iter().enumerate() {
        if candidate.action.0 == NO_ACTION {
            return Err(CandidatePresentationError::ReservedActionCode);
        }
        if candidates[..index]
            .iter()
            .any(|prior| prior.action == candidate.action)
        {
            return Err(CandidatePresentationError::DuplicateActionCode);
        }
        if candidates[..index]
            .iter()
            .any(|prior| prior.patch_digest == candidate.patch_digest)
        {
            return Err(CandidatePresentationError::DuplicatePatchDigest);
        }
    }
    Ok(())
}

fn sequence_digest(task_digest: [u8; 32], candidates: &[CandidateIdentity]) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(DOMAIN);
    hasher.update(&task_digest);
    hasher.update(&(candidates.len() as u32).to_le_bytes());
    for candidate in candidates {
        hasher.update(&candidate.action.0.to_le_bytes());
        hasher.update(&candidate.patch_digest);
    }
    *hasher.finalize().as_bytes()
}

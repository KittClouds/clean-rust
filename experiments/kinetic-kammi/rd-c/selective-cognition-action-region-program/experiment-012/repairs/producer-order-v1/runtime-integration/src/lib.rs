use rdc_experiment_009::observer::ActionOption;
use rdc_runtime_contracts_v1::{
    ActionCode, CandidateIdentity, CandidatePresentationError, SequencedCandidate,
    encode_candidate_presentation, order_by_producer_ordinal, resolve_candidate_proposal,
};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PresentedOption {
    pub producer_ordinal: u16,
    pub action: ActionOption,
    pub summary: String,
    pub diff_excerpt: String,
    pub patch_sha256: String,
}

#[derive(Clone, Debug)]
pub struct PreparedPresentation {
    pub ordered_options: Vec<PresentedOption>,
    pub receipt: Vec<u8>,
    pub receipt_digest: [u8; 32],
    pub request_id: [u8; 32],
}

#[derive(Clone, Copy, Debug)]
pub struct PresentationBinding<'a> {
    pub task_digest: [u8; 32],
    pub receipt: &'a [u8],
    pub request_receipt_digest: [u8; 32],
    pub response_receipt_digest: [u8; 32],
    pub request_id: [u8; 32],
    pub response_request_id: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PresentationRuntimeError {
    InvalidDigest,
    ReceiptDigestMismatch,
    RequestIdMismatch,
    RequestResponseReceiptMismatch,
    Candidate(CandidatePresentationError),
}

impl std::fmt::Display for PresentationRuntimeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidDigest => formatter.write_str("expected a 32-byte hexadecimal digest"),
            Self::ReceiptDigestMismatch => {
                formatter.write_str("presentation receipt digest does not match the request")
            }
            Self::RequestIdMismatch => {
                formatter.write_str("observer request ID does not bind this task and receipt")
            }
            Self::RequestResponseReceiptMismatch => {
                formatter.write_str("observer response is bound to a different presentation")
            }
            Self::Candidate(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for PresentationRuntimeError {}

impl From<CandidatePresentationError> for PresentationRuntimeError {
    fn from(value: CandidatePresentationError) -> Self {
        Self::Candidate(value)
    }
}

/// Restores producer order before serialization, then seals the exact frame shown.
pub fn prepare_presentation(
    task_digest: [u8; 32],
    options: Vec<PresentedOption>,
) -> Result<PreparedPresentation, PresentationRuntimeError> {
    let mut sequenced = options
        .into_iter()
        .map(|option| SequencedCandidate {
            producer_ordinal: option.producer_ordinal,
            value: option,
        })
        .collect::<Vec<_>>();
    order_by_producer_ordinal(&mut sequenced)?;
    let ordered_options = sequenced
        .into_iter()
        .map(|candidate| candidate.value)
        .collect::<Vec<_>>();
    let identities = candidate_identities(&ordered_options)?;
    let receipt = encode_candidate_presentation(task_digest, &identities)?;
    let receipt_digest = *blake3::hash(&receipt).as_bytes();
    let request_id = request_id_for(task_digest, receipt_digest);
    Ok(PreparedPresentation {
        ordered_options,
        receipt,
        receipt_digest,
        request_id,
    })
}

/// Checks the request/response correlation and exact current presentation before mapping an ID.
pub fn resolve_response(
    binding: PresentationBinding<'_>,
    options: &[PresentedOption],
    proposal: Option<u16>,
) -> Result<Option<PresentedOption>, PresentationRuntimeError> {
    if *blake3::hash(binding.receipt).as_bytes() != binding.request_receipt_digest {
        return Err(PresentationRuntimeError::ReceiptDigestMismatch);
    }
    if binding.response_receipt_digest != binding.request_receipt_digest {
        return Err(PresentationRuntimeError::RequestResponseReceiptMismatch);
    }
    if binding.request_id != request_id_for(binding.task_digest, binding.request_receipt_digest) {
        return Err(PresentationRuntimeError::RequestIdMismatch);
    }
    if binding.response_request_id != binding.request_id {
        return Err(PresentationRuntimeError::RequestResponseReceiptMismatch);
    }
    if options
        .windows(2)
        .any(|pair| pair[0].producer_ordinal >= pair[1].producer_ordinal)
    {
        return Err(PresentationRuntimeError::Candidate(
            CandidatePresentationError::CandidateSequenceChanged,
        ));
    }
    let identities = candidate_identities(options)?;
    let resolved = resolve_candidate_proposal(
        binding.receipt,
        binding.task_digest,
        &identities,
        proposal.map(ActionCode),
    )?;
    Ok(resolved.and_then(|identity| {
        options
            .iter()
            .find(|option| {
                option.action.id == identity.action.0
                    && parse_hex_digest(&option.patch_sha256).ok() == Some(identity.patch_digest)
            })
            .cloned()
    }))
}

pub fn request_id_for(task_digest: [u8; 32], receipt_digest: [u8; 32]) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-E011-OBSERVER-REQUEST-V1\0");
    hasher.update(&task_digest);
    hasher.update(&receipt_digest);
    *hasher.finalize().as_bytes()
}

pub fn parse_hex_digest(value: &str) -> Result<[u8; 32], PresentationRuntimeError> {
    if value.len() != 64 {
        return Err(PresentationRuntimeError::InvalidDigest);
    }
    let mut digest = [0; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        digest[index] = (hex_nibble(pair[0])? << 4) | hex_nibble(pair[1])?;
    }
    Ok(digest)
}

pub fn hex_digest(value: &[u8; 32]) -> String {
    let mut output = String::with_capacity(64);
    for byte in value {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}

pub fn candidate_identities(
    options: &[PresentedOption],
) -> Result<Vec<CandidateIdentity>, PresentationRuntimeError> {
    options
        .iter()
        .map(|option| {
            Ok(CandidateIdentity {
                action: ActionCode(option.action.id),
                patch_digest: parse_hex_digest(&option.patch_sha256)?,
            })
        })
        .collect()
}

fn hex_nibble(value: u8) -> Result<u8, PresentationRuntimeError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        b'A'..=b'F' => Ok(value - b'A' + 10),
        _ => Err(PresentationRuntimeError::InvalidDigest),
    }
}

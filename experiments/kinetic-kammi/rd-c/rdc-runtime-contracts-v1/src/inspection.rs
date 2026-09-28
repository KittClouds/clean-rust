use serde::{Deserialize, Serialize};
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout};

pub const NO_ACTION: u16 = u16::MAX;
pub const DEFAULT_MIN_CONFIDENCE: u16 = 800;
pub const REPLY_BYTES: usize = 64;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, FromBytes, IntoBytes, KnownLayout, Immutable)]
#[repr(transparent)]
pub struct ActionCode(pub u16);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[repr(u8)]
pub enum TransportStatus {
    Complete = 0,
    Timeout = 1,
    Unavailable = 2,
    Malformed = 3,
}

impl TransportStatus {
    fn from_code(code: u8) -> Option<Self> {
        match code {
            0 => Some(Self::Complete),
            1 => Some(Self::Timeout),
            2 => Some(Self::Unavailable),
            3 => Some(Self::Malformed),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct InspectionReply {
    pub transport: TransportStatus,
    pub candidate: u16,
    pub competing_candidate: u16,
    pub confidence_milli: u16,
    pub signature_valid: bool,
    pub source_revision: u32,
    pub payload_digest: [u8; 32],
}

impl InspectionReply {
    pub fn encode(self) -> Result<[u8; REPLY_BYTES], &'static str> {
        if self.transport != TransportStatus::Complete
            && (self.candidate != NO_ACTION || self.competing_candidate != NO_ACTION)
        {
            return Err("failed or malformed transport cannot carry action candidates");
        }
        let mut bytes = [0; REPLY_BYTES];
        bytes[0] = self.transport as u8;
        bytes[1] = self.signature_valid as u8;
        bytes[2..4].copy_from_slice(&self.candidate.to_le_bytes());
        bytes[4..6].copy_from_slice(&self.competing_candidate.to_le_bytes());
        bytes[6..8].copy_from_slice(&self.confidence_milli.to_le_bytes());
        bytes[8..12].copy_from_slice(&self.source_revision.to_le_bytes());
        bytes[12..44].copy_from_slice(&self.payload_digest);
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8; REPLY_BYTES]) -> Result<Self, &'static str> {
        let transport = TransportStatus::from_code(bytes[0]).ok_or("unknown transport status")?;
        if bytes[1] > 1 || bytes[44..].iter().any(|byte| *byte != 0) {
            return Err("reply has invalid boolean or reserved bytes");
        }
        let reply = Self {
            transport,
            signature_valid: bytes[1] == 1,
            candidate: u16::from_le_bytes(bytes[2..4].try_into().unwrap()),
            competing_candidate: u16::from_le_bytes(bytes[4..6].try_into().unwrap()),
            confidence_milli: u16::from_le_bytes(bytes[6..8].try_into().unwrap()),
            source_revision: u32::from_le_bytes(bytes[8..12].try_into().unwrap()),
            payload_digest: bytes[12..44].try_into().unwrap(),
        };
        if transport != TransportStatus::Complete
            && (reply.candidate != NO_ACTION || reply.competing_candidate != NO_ACTION)
        {
            return Err("failed or malformed transport carries action candidates");
        }
        Ok(reply)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum InspectionKind {
    Confirmed,
    Contradicted,
    Unknown,
    Failed,
}

impl InspectionKind {
    pub fn label(self) -> &'static str {
        match self {
            Self::Confirmed => "confirmed",
            Self::Contradicted => "contradicted",
            Self::Unknown => "unknown",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InspectionResult {
    pub kind: InspectionKind,
    /// `None` explicitly means reobserve; it never means reuse the active action.
    pub proposed_action: Option<ActionCode>,
    pub reply: InspectionReply,
}

impl InspectionResult {
    pub fn classify(active: ActionCode, reply: InspectionReply) -> Self {
        Self::classify_with_threshold(active, reply, DEFAULT_MIN_CONFIDENCE)
    }

    pub fn classify_with_threshold(
        active: ActionCode,
        reply: InspectionReply,
        min_confidence: u16,
    ) -> Self {
        let kind = match reply.transport {
            TransportStatus::Timeout | TransportStatus::Unavailable => InspectionKind::Failed,
            TransportStatus::Malformed => InspectionKind::Unknown,
            TransportStatus::Complete
                if !reply.signature_valid
                    || reply.confidence_milli < min_confidence
                    || reply.candidate == NO_ACTION
                    || reply.competing_candidate != NO_ACTION =>
            {
                InspectionKind::Unknown
            }
            TransportStatus::Complete if reply.candidate == active.0 => InspectionKind::Confirmed,
            TransportStatus::Complete => InspectionKind::Contradicted,
        };
        let proposed_action = match kind {
            InspectionKind::Confirmed => Some(active),
            InspectionKind::Contradicted => Some(ActionCode(reply.candidate)),
            InspectionKind::Unknown | InspectionKind::Failed => None,
        };
        Self {
            kind,
            proposed_action,
            reply,
        }
    }
}

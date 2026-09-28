use rdc_experiment_001::{Action, Evidence, Observation, Proposal, Signal, State};

pub const EVIDENCE_CODE: u16 = 0xE404;
pub const FLAG_PRIMARY_WARNING: u8 = 1;
pub const FLAG_AUDIT_WARNING: u8 = 2;
pub const FLAG_AUDIT_SELECTED: u8 = 4;
const FRAME_LEN: usize = 14;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
#[repr(u8)]
pub enum Choice {
    UsePrimary = 0,
    VerifyRecord = 1,
    RefreshSnapshot = 2,
}

impl Choice {
    pub const ALL: [Self; 3] = [Self::UsePrimary, Self::VerifyRecord, Self::RefreshSnapshot];

    pub fn action(self) -> Action {
        match self {
            Self::UsePrimary => Action::Execute,
            Self::VerifyRecord => Action::Verify,
            Self::RefreshSnapshot => Action::Observe,
        }
    }

    pub fn from_action(action: Action) -> Option<Self> {
        match action {
            Action::Execute => Some(Self::UsePrimary),
            Action::Verify => Some(Self::VerifyRecord),
            Action::Observe => Some(Self::RefreshSnapshot),
            _ => None,
        }
    }

    pub fn from_code(code: u8) -> Option<Self> {
        Self::ALL.get(code as usize).copied()
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::UsePrimary => "use_primary",
            Self::VerifyRecord => "verify_record",
            Self::RefreshSnapshot => "refresh_snapshot",
        }
    }
}

/// Public observation frame. It contains source-reported revisions, never the truth revision.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ObservationFeatures {
    pub episode_id: u32,
    pub goal: u8,
    pub primary_action: Choice,
    pub audit_action: Choice,
    pub primary_revision: u8,
    pub audit_revision: u8,
    pub primary_age: u8,
    pub audit_age: u8,
    pub flags: u8,
}

impl ObservationFeatures {
    pub fn observation(self, signal: Signal, confidence: u16) -> Observation {
        Observation::new(signal)
            .with_confidence(confidence)
            .with_evidence(self.frame_evidence())
    }

    pub fn frame_evidence(self) -> Evidence {
        let mut digest = [0u8; 16];
        digest[0] = self.goal;
        digest[1] = self.primary_action as u8;
        digest[2] = self.audit_action as u8;
        digest[3] = self.primary_revision;
        digest[4] = self.audit_revision;
        digest[5] = self.primary_age;
        digest[6] = self.audit_age;
        digest[7] = self.flags;
        digest[8..12].copy_from_slice(&self.episode_id.to_le_bytes());
        // The source marker fields are zero in a full frame.
        digest[12] = 0;
        digest[13] = 0;
        finish_digest(&mut digest);
        Evidence {
            code: EVIDENCE_CODE,
            digest,
        }
    }

    pub fn action_evidence(self, source_id: u8, source_revision: u8) -> Evidence {
        let mut evidence = self.frame_evidence();
        evidence.digest[12] = source_id;
        evidence.digest[13] = source_revision;
        finish_digest(&mut evidence.digest);
        Evidence {
            code: EVIDENCE_CODE,
            digest: evidence.digest,
        }
    }

    pub fn decode(observation: &Observation) -> Option<Self> {
        Self::decode_evidence(observation.evidence?)
    }

    pub fn decode_evidence(evidence: Evidence) -> Option<Self> {
        if evidence.code != EVIDENCE_CODE
            || evidence.digest[14..] != blake3::hash(&evidence.digest[..FRAME_LEN]).as_bytes()[..2]
            || evidence.digest[12] > 2
        {
            return None;
        }
        Some(Self {
            episode_id: u32::from_le_bytes(evidence.digest[8..12].try_into().ok()?),
            goal: evidence.digest[0],
            primary_action: Choice::from_code(evidence.digest[1])?,
            audit_action: Choice::from_code(evidence.digest[2])?,
            primary_revision: evidence.digest[3],
            audit_revision: evidence.digest[4],
            primary_age: evidence.digest[5],
            audit_age: evidence.digest[6],
            flags: evidence.digest[7],
        })
    }

    pub fn cited_source(evidence: Evidence) -> u8 {
        evidence.digest[12]
    }

    pub fn source(self, source_id: u8) -> Option<ToolEvidence> {
        let (recommendation, reported_revision) = match source_id {
            1 => (self.primary_action, self.primary_revision),
            2 => (self.audit_action, self.audit_revision),
            _ => return None,
        };
        Some(ToolEvidence {
            source_id,
            recommendation,
            reported_revision,
            age_bucket: if source_id == 1 {
                self.primary_age
            } else {
                self.audit_age
            },
            warning: match source_id {
                1 => self.flags & FLAG_PRIMARY_WARNING != 0,
                2 => self.flags & FLAG_AUDIT_WARNING != 0,
                _ => false,
            },
            content_marker: (self.episode_id as u16).wrapping_mul(31) ^ source_id as u16,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ToolEvidence {
    pub source_id: u8,
    pub recommendation: Choice,
    pub reported_revision: u8,
    pub age_bucket: u8,
    pub warning: bool,
    pub content_marker: u16,
}

/// Read-only evidence query. It cannot return a truth label or authoritative revision.
pub fn inspect_evidence(features: ObservationFeatures, source_id: u8) -> Option<ToolEvidence> {
    features.source(source_id)
}

pub fn proposal(
    state: State,
    observation: &Observation,
    choice: Choice,
    source_id: u8,
    source_revision: u8,
) -> Proposal {
    Proposal {
        from: state,
        requested_to: State::Acting,
        action: choice.action(),
        confidence: observation.confidence,
        evidence: Some(ObservationFeatures::decode(observation).map_or_else(
            || {
                observation.evidence.unwrap_or(Evidence {
                    code: EVIDENCE_CODE,
                    digest: [0; 16],
                })
            },
            |frame| frame.action_evidence(source_id, source_revision),
        )),
    }
}

pub fn action_choice(proposal: Proposal) -> Option<Choice> {
    Choice::from_action(proposal.action)
}

fn finish_digest(digest: &mut [u8; 16]) {
    let checksum = blake3::hash(&digest[..FRAME_LEN]);
    digest[14..].copy_from_slice(&checksum.as_bytes()[..2]);
}

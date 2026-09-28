use rdc_experiment_001::{Action, Evidence, Observation, Proposal, Signal, State};

pub const EVIDENCE_CODE: u16 = 0xE303;
pub const FLAG_PRIMARY_STALE: u8 = 1;
pub const FLAG_TOOL_WARNING: u8 = 2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
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

    pub fn label(self) -> &'static str {
        match self {
            Self::UsePrimary => "use_primary",
            Self::VerifyRecord => "verify_record",
            Self::RefreshSnapshot => "refresh_snapshot",
        }
    }

    pub fn from_code(code: u8) -> Option<Self> {
        Self::ALL.get(code as usize).copied()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ObservationFeatures {
    pub goal: u8,
    pub world_revision: u8,
    pub primary_action: Choice,
    pub audit_action: Choice,
    pub flags: u8,
}

impl ObservationFeatures {
    pub fn encode(self, episode_id: u32) -> Evidence {
        let mut digest = [0; 16];
        digest[0] = self.goal;
        digest[1] = self.world_revision;
        digest[2] = self.primary_action as u8;
        digest[3] = self.audit_action as u8;
        digest[4] = self.flags;
        digest[5..9].copy_from_slice(&episode_id.to_le_bytes());
        let checksum = blake3::hash(&digest[..9]);
        digest[9..].copy_from_slice(&checksum.as_bytes()[..7]);
        Evidence {
            code: EVIDENCE_CODE,
            digest,
        }
    }

    pub fn decode(observation: &Observation) -> Option<(Self, u32)> {
        let evidence = observation.evidence?;
        if evidence.code != EVIDENCE_CODE
            || evidence.digest[9..] != blake3::hash(&evidence.digest[..9]).as_bytes()[..7]
        {
            return None;
        }
        let features = Self {
            goal: evidence.digest[0],
            world_revision: evidence.digest[1],
            primary_action: Choice::from_code(evidence.digest[2])?,
            audit_action: Choice::from_code(evidence.digest[3])?,
            flags: evidence.digest[4],
        };
        let episode_id = u32::from_le_bytes(evidence.digest[5..9].try_into().ok()?);
        Some((features, episode_id))
    }
}

pub fn choice_proposal(state: State, observation: &Observation, choice: Choice) -> Proposal {
    Proposal {
        from: state,
        requested_to: State::Acting,
        action: choice.action(),
        confidence: observation.confidence,
        evidence: observation.evidence,
    }
}

pub fn observation_for(signal: Signal, confidence: u16, evidence: Evidence) -> Observation {
    Observation::new(signal)
        .with_confidence(confidence)
        .with_evidence(evidence)
}

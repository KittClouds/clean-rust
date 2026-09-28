use rdc_experiment_001::{Evidence, Observation, Signal};
use rdc_experiment_004::Choice;

pub const EVIDENCE_CODE: u16 = 0xE606;
const FRAME_BYTES: usize = 14;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PublicFeatures {
    pub episode_id: u32,
    pub inspection_domain: u8,
    pub goal: u8,
    pub primary_action: Choice,
    pub audit_action: Choice,
    pub primary_revision: u8,
    pub audit_revision: u8,
    pub primary_age: u8,
    pub audit_age: u8,
    pub flags: u8,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PublicFrame {
    pub features: PublicFeatures,
}

impl PublicFrame {
    pub fn evidence(self) -> Evidence {
        let f = self.features;
        let mut digest = [0; 16];
        digest[..4].copy_from_slice(&f.episode_id.to_le_bytes());
        digest[4] = f.inspection_domain;
        digest[5] = f.goal;
        digest[6] = f.primary_action as u8;
        digest[7] = f.audit_action as u8;
        digest[8] = f.primary_revision;
        digest[9] = f.audit_revision;
        digest[10] = f.primary_age;
        digest[11] = f.audit_age;
        digest[12] = f.flags;
        digest[13] = 1;
        let checksum = blake3::hash(&digest[..FRAME_BYTES]);
        digest[14..].copy_from_slice(&checksum.as_bytes()[..2]);
        Evidence {
            code: EVIDENCE_CODE,
            digest,
        }
    }

    pub fn observation(self, signal: Signal, confidence: u16) -> Observation {
        Observation::new(signal)
            .with_confidence(confidence)
            .with_evidence(self.evidence())
    }

    pub fn decode(observation: &Observation) -> Option<Self> {
        let evidence = observation.evidence?;
        let bytes = evidence.digest;
        if evidence.code != EVIDENCE_CODE
            || bytes[13] != 1
            || bytes[14..] != blake3::hash(&bytes[..FRAME_BYTES]).as_bytes()[..2]
            || bytes[4] >= 12
        {
            return None;
        }
        Some(Self {
            features: PublicFeatures {
                episode_id: u32::from_le_bytes(bytes[..4].try_into().ok()?),
                inspection_domain: bytes[4],
                goal: bytes[5],
                primary_action: Choice::from_code(bytes[6])?,
                audit_action: Choice::from_code(bytes[7])?,
                primary_revision: bytes[8],
                audit_revision: bytes[9],
                primary_age: bytes[10],
                audit_age: bytes[11],
                flags: bytes[12],
            },
        })
    }

    pub fn proposal_evidence(self, action_code: u8, result: Option<[u8; 32]>) -> Evidence {
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"RDC-E006-PROPOSAL-V1\0");
        hasher.update(&self.evidence().digest);
        hasher.update(&[action_code]);
        if let Some(payload) = result {
            hasher.update(&[1]);
            hasher.update(&payload);
        } else {
            hasher.update(&[0]);
        }
        let hash = hasher.finalize();
        let mut digest = [0; 16];
        digest.copy_from_slice(&hash.as_bytes()[..16]);
        Evidence {
            code: EVIDENCE_CODE,
            digest,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct FeatureVector(pub [f32; 8]);

impl FeatureVector {
    pub fn from_public(frame: PublicFrame, confidence: u16) -> Self {
        let f = frame.features;
        let max_age = f.primary_age.max(f.audit_age) as f32 / 2.0;
        let warning = (f.flags & 0b11 != 0) as u8 as f32;
        let disagreement = (f.primary_action != f.audit_action) as u8 as f32;
        let confidence = confidence.min(1000) as f32 / 1000.0;
        let revision_gap = f.primary_revision.abs_diff(f.audit_revision) as f32 / 3.0;
        let selected_audit = (f.flags & 0b100 != 0) as u8 as f32;
        let stale_visible = (max_age > 0.0 || warning > 0.0) as u8 as f32;
        let confidence_gap = 1.0 - confidence;
        Self([
            1.0,
            disagreement,
            warning,
            max_age,
            confidence_gap,
            revision_gap,
            selected_audit,
            stale_visible,
        ])
    }
}

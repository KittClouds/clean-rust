use rdc_experiment_001::{Evidence, Observation, Signal};
use rdc_experiment_004::{Choice, ObservationFeatures};

pub const EVIDENCE_CODE: u16 = 0xE505;
const FRAME_BYTES: usize = 14;
const FRAME_VERSION: u8 = 1;

/// Public task input. Inspection results and source-state records are not fields of this frame.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PublicFrame {
    pub features: ObservationFeatures,
    pub inspection_domain: u8,
}

impl PublicFrame {
    pub fn evidence(self) -> Evidence {
        let f = self.features;
        let mut digest = [0u8; 16];
        digest[0] = f.goal;
        digest[1] = f.primary_action as u8;
        digest[2] = f.audit_action as u8;
        digest[3] = f.primary_revision;
        digest[4] = f.audit_revision;
        digest[5] = f.primary_age;
        digest[6] = f.audit_age;
        digest[7] = f.flags;
        digest[8..12].copy_from_slice(&f.episode_id.to_le_bytes());
        digest[12] = self.inspection_domain;
        digest[13] = FRAME_VERSION;
        finish_digest(&mut digest);
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
        Self::decode_evidence(observation.evidence?)
    }

    pub fn decode_evidence(evidence: Evidence) -> Option<Self> {
        let digest = evidence.digest;
        if evidence.code != EVIDENCE_CODE
            || digest[13] != FRAME_VERSION
            || digest[14..] != blake3::hash(&digest[..FRAME_BYTES]).as_bytes()[..2]
            || digest[12] > 7
        {
            return None;
        }
        Some(Self {
            features: ObservationFeatures {
                episode_id: u32::from_le_bytes(digest[8..12].try_into().ok()?),
                goal: digest[0],
                primary_action: Choice::from_code(digest[1])?,
                audit_action: Choice::from_code(digest[2])?,
                primary_revision: digest[3],
                audit_revision: digest[4],
                primary_age: digest[5],
                audit_age: digest[6],
                flags: digest[7],
            },
            inspection_domain: digest[12],
        })
    }

    /// Binds a typed proposal to the public frame and, when present, the queried result digest.
    pub fn action_evidence(self, action: Choice, result_digest: Option<[u8; 32]>) -> Evidence {
        let frame = self.evidence();
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"RDC-E005-PROPOSAL-EVIDENCE-V1\0");
        hasher.update(&frame.digest);
        hasher.update(&[action as u8]);
        if let Some(digest) = result_digest {
            hasher.update(&[1]);
            hasher.update(&digest);
        } else {
            hasher.update(&[0]);
        }
        let digest = *hasher.finalize().as_bytes();
        let mut compact = [0u8; 16];
        compact.copy_from_slice(&digest[..16]);
        Evidence {
            code: EVIDENCE_CODE,
            digest: compact,
        }
    }
}

fn finish_digest(digest: &mut [u8; 16]) {
    let checksum = blake3::hash(&digest[..FRAME_BYTES]);
    digest[14..].copy_from_slice(&checksum.as_bytes()[..2]);
}

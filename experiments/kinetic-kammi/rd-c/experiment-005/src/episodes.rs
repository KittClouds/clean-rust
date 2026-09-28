use rdc_experiment_004::{
    Choice,
    domain::{FLAG_AUDIT_SELECTED, FLAG_AUDIT_WARNING, FLAG_PRIMARY_WARNING, ObservationFeatures},
    episodes::contract_action,
};

use crate::domain::PublicFrame;

pub const DEVELOPMENT_SEED: u64 = 0xE005_2026_0901;
pub const HELDOUT_SEED: u64 = 0xE005_2026_0924;
pub const EPISODES_PER_CLASS: usize = 32;
pub const CLASS_STRIDE: u32 = 257;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EpisodeClass {
    FreshAgreement,
    FreshConsistentWrong,
    StaleSharedWrong,
    StalePrimarySplit,
    MisleadingAuditSplit,
    InspectionHarm,
    LowConfidenceAgreement,
    DisagreementWithoutValue,
}

impl EpisodeClass {
    pub const ALL: [Self; 8] = [
        Self::FreshAgreement,
        Self::FreshConsistentWrong,
        Self::StaleSharedWrong,
        Self::StalePrimarySplit,
        Self::MisleadingAuditSplit,
        Self::InspectionHarm,
        Self::LowConfidenceAgreement,
        Self::DisagreementWithoutValue,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::FreshAgreement => "fresh_agreement",
            Self::FreshConsistentWrong => "fresh_consistent_wrong",
            Self::StaleSharedWrong => "stale_shared_wrong",
            Self::StalePrimarySplit => "stale_primary_split",
            Self::MisleadingAuditSplit => "misleading_audit_split",
            Self::InspectionHarm => "inspection_harm",
            Self::LowConfidenceAgreement => "low_confidence_agreement",
            Self::DisagreementWithoutValue => "disagreement_without_value",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Episode {
    pub id: u32,
    pub class: EpisodeClass,
    pub frame: PublicFrame,
    pub confidence: u16,
    pub stratum: u8,
    pub within_stratum: u16,
}

impl Episode {
    pub fn observation(
        &self,
        signal: rdc_experiment_001::Signal,
    ) -> rdc_experiment_001::Observation {
        self.frame.observation(signal, self.confidence)
    }
}

pub fn development_episodes() -> Vec<Episode> {
    generate(DEVELOPMENT_SEED)
}

pub fn heldout_episodes() -> Vec<Episode> {
    generate(HELDOUT_SEED)
}

fn generate(seed: u64) -> Vec<Episode> {
    let mut episodes = Vec::with_capacity(EpisodeClass::ALL.len() * EPISODES_PER_CLASS);
    for (stratum, class) in EpisodeClass::ALL.into_iter().enumerate() {
        for within in 0..EPISODES_PER_CLASS {
            let id = (seed as u32).wrapping_add((stratum as u32 * CLASS_STRIDE) + within as u32);
            let goal = ((within * 2 + stratum) % 3) as u8;
            let truth_revision = hidden_revision(stratum, within);
            let correct = label_contract(goal, truth_revision);
            let previous_revision = truth_revision.saturating_sub(1);
            let stale = contract_action(goal, previous_revision);
            let wrong = rotate(correct, 1);
            let (
                primary_revision,
                audit_revision,
                primary_age,
                audit_age,
                mut flags,
                confidence,
                p,
                a,
                domain,
            ) = match class {
                EpisodeClass::FreshAgreement => (
                    truth_revision,
                    truth_revision,
                    0,
                    0,
                    0,
                    930,
                    correct,
                    correct,
                    0,
                ),
                EpisodeClass::FreshConsistentWrong => (
                    previous_revision,
                    previous_revision,
                    0,
                    0,
                    0,
                    960,
                    stale,
                    stale,
                    1,
                ),
                EpisodeClass::StaleSharedWrong => (
                    previous_revision,
                    previous_revision,
                    1,
                    1,
                    0,
                    900,
                    stale,
                    stale,
                    2,
                ),
                EpisodeClass::StalePrimarySplit => (
                    previous_revision,
                    truth_revision,
                    1,
                    0,
                    FLAG_PRIMARY_WARNING,
                    840,
                    stale,
                    correct,
                    3,
                ),
                EpisodeClass::MisleadingAuditSplit => (
                    truth_revision,
                    truth_revision,
                    0,
                    0,
                    FLAG_AUDIT_WARNING,
                    910,
                    correct,
                    wrong,
                    4,
                ),
                EpisodeClass::InspectionHarm => (
                    truth_revision,
                    truth_revision,
                    0,
                    0,
                    0,
                    930,
                    correct,
                    correct,
                    5,
                ),
                EpisodeClass::LowConfidenceAgreement => (
                    truth_revision,
                    truth_revision,
                    0,
                    0,
                    0,
                    460,
                    correct,
                    correct,
                    6,
                ),
                EpisodeClass::DisagreementWithoutValue => (
                    previous_revision,
                    truth_revision,
                    1,
                    0,
                    FLAG_PRIMARY_WARNING,
                    820,
                    stale,
                    correct,
                    7,
                ),
            };
            if flags & (FLAG_PRIMARY_WARNING | FLAG_AUDIT_WARNING) != 0 {
                flags |= FLAG_AUDIT_SELECTED;
            }
            let features = ObservationFeatures {
                episode_id: id,
                goal,
                primary_action: p,
                audit_action: a,
                primary_revision,
                audit_revision,
                primary_age,
                audit_age,
                flags,
            };
            episodes.push(Episode {
                id,
                class,
                frame: PublicFrame {
                    features,
                    inspection_domain: domain,
                },
                confidence,
                stratum: stratum as u8,
                within_stratum: within as u16,
            });
        }
    }
    episodes
}

/// Hidden state used by the separate label writer and by an independent source fixture.
pub fn hidden_revision(stratum: usize, within: usize) -> u8 {
    40 + ((within + 2 * stratum) % 3) as u8
}

fn label_contract(goal: u8, revision: u8) -> Choice {
    const CONTRACT: [[Choice; 3]; 3] = [
        [
            Choice::UsePrimary,
            Choice::VerifyRecord,
            Choice::RefreshSnapshot,
        ],
        [
            Choice::VerifyRecord,
            Choice::RefreshSnapshot,
            Choice::UsePrimary,
        ],
        [
            Choice::RefreshSnapshot,
            Choice::UsePrimary,
            Choice::VerifyRecord,
        ],
    ];
    CONTRACT[goal as usize % 3][revision as usize % 3]
}

fn rotate(action: Choice, by: usize) -> Choice {
    Choice::ALL[(action as usize + by) % Choice::ALL.len()]
}

pub fn observation_features(episode: &Episode) -> ObservationFeatures {
    episode.frame.features
}

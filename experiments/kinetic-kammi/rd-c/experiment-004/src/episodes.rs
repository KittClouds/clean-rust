use rdc_experiment_001::Signal;

use crate::domain::{
    Choice, FLAG_AUDIT_SELECTED, FLAG_AUDIT_WARNING, FLAG_PRIMARY_WARNING, ObservationFeatures,
};

pub const HELDOUT_SEED: u64 = 0xE404_2026_0924;
pub const EPISODE_COUNT: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EpisodeClass {
    FreshAgreement,
    StaleSharedAgreement,
    StalePrimarySplit,
    MisleadingFreshAgreement,
    LowConfidenceAgreement,
    MisleadingAuditSplit,
    StaleAuditSplit,
    WarningBothFresh,
}

impl EpisodeClass {
    pub const ALL: [Self; 8] = [
        Self::FreshAgreement,
        Self::StaleSharedAgreement,
        Self::StalePrimarySplit,
        Self::MisleadingFreshAgreement,
        Self::LowConfidenceAgreement,
        Self::MisleadingAuditSplit,
        Self::StaleAuditSplit,
        Self::WarningBothFresh,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::FreshAgreement => "fresh_agreement",
            Self::StaleSharedAgreement => "stale_shared_agreement",
            Self::StalePrimarySplit => "stale_primary_split",
            Self::MisleadingFreshAgreement => "misleading_fresh_agreement",
            Self::LowConfidenceAgreement => "low_confidence_agreement",
            Self::MisleadingAuditSplit => "misleading_audit_split",
            Self::StaleAuditSplit => "stale_audit_split",
            Self::WarningBothFresh => "warning_both_fresh",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Episode {
    pub id: u32,
    pub class: EpisodeClass,
    pub features: ObservationFeatures,
    pub confidence: u16,
}

impl Episode {
    pub fn observation(self, signal: Signal) -> rdc_experiment_001::Observation {
        self.features.observation(signal, self.confidence)
    }
}

pub fn heldout_episodes() -> Vec<Episode> {
    let mut episodes = Vec::with_capacity(EPISODE_COUNT);
    for (class_index, class) in EpisodeClass::ALL.into_iter().enumerate() {
        for offset in 0..(EPISODE_COUNT / EpisodeClass::ALL.len()) {
            let id = (HELDOUT_SEED as u32).wrapping_add((class_index * 257 + offset) as u32);
            let goal = ((offset * 2 + class_index) % 3) as u8;
            let truth_revision = 40 + ((offset + 2 * class_index) % 3) as u8;
            let correct_action = contract_action(goal, truth_revision);
            let stale_revision = truth_revision.saturating_sub(1);
            let wrong = rotate(correct_action, 1);
            let (
                primary_revision,
                audit_revision,
                primary_age,
                audit_age,
                mut flags,
                confidence,
                p,
                a,
            ) = match class {
                EpisodeClass::FreshAgreement => (
                    truth_revision,
                    truth_revision,
                    0,
                    0,
                    0,
                    930,
                    correct_action,
                    correct_action,
                ),
                EpisodeClass::StaleSharedAgreement => (
                    stale_revision,
                    stale_revision,
                    1,
                    1,
                    0,
                    900,
                    contract_action(goal, stale_revision),
                    contract_action(goal, stale_revision),
                ),
                EpisodeClass::StalePrimarySplit => (
                    stale_revision,
                    truth_revision,
                    1,
                    0,
                    FLAG_PRIMARY_WARNING,
                    840,
                    contract_action(goal, stale_revision),
                    correct_action,
                ),
                EpisodeClass::MisleadingFreshAgreement => {
                    (truth_revision, truth_revision, 0, 0, 0, 920, wrong, wrong)
                }
                EpisodeClass::LowConfidenceAgreement => (
                    truth_revision,
                    truth_revision,
                    0,
                    0,
                    0,
                    460,
                    correct_action,
                    correct_action,
                ),
                EpisodeClass::MisleadingAuditSplit => (
                    truth_revision,
                    truth_revision,
                    0,
                    0,
                    FLAG_AUDIT_WARNING,
                    910,
                    correct_action,
                    wrong,
                ),
                EpisodeClass::StaleAuditSplit => (
                    truth_revision,
                    stale_revision,
                    0,
                    1,
                    FLAG_AUDIT_WARNING,
                    820,
                    correct_action,
                    contract_action(goal, stale_revision),
                ),
                EpisodeClass::WarningBothFresh => (
                    truth_revision,
                    truth_revision,
                    0,
                    0,
                    FLAG_PRIMARY_WARNING,
                    780,
                    correct_action,
                    rotate(correct_action, 2),
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
                features,
                confidence,
            });
        }
    }
    episodes
}

pub fn contract_action(goal: u8, revision: u8) -> Choice {
    Choice::ALL[(goal as usize + revision as usize) % 3]
}

fn rotate(action: Choice, by: usize) -> Choice {
    Choice::ALL[(action as usize + by) % Choice::ALL.len()]
}

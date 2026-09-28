use rdc_experiment_001::{Observation, Signal};

use crate::domain::{Choice, FLAG_PRIMARY_STALE, FLAG_TOOL_WARNING, ObservationFeatures};

pub const HELDOUT_SEED: u64 = 0xE003_2026_0924;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EpisodeClass {
    FreshAgreementCorrect,
    MisleadingSharedWrong,
    StalePrimaryDisagreement,
    ConflictingAuditDisagreement,
    LowConfidenceAgreementCorrect,
    SplitWrongDisagreement,
    StaleSharedWrong,
    ActiveCorrectConflict,
}

impl EpisodeClass {
    pub const ALL: [(Self, usize); 8] = [
        (Self::FreshAgreementCorrect, 80),
        (Self::MisleadingSharedWrong, 20),
        (Self::StalePrimaryDisagreement, 48),
        (Self::ConflictingAuditDisagreement, 16),
        (Self::LowConfidenceAgreementCorrect, 32),
        (Self::SplitWrongDisagreement, 32),
        (Self::StaleSharedWrong, 16),
        (Self::ActiveCorrectConflict, 12),
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::FreshAgreementCorrect => "fresh_agreement_correct",
            Self::MisleadingSharedWrong => "misleading_shared_wrong",
            Self::StalePrimaryDisagreement => "stale_primary_disagreement",
            Self::ConflictingAuditDisagreement => "conflicting_audit_disagreement",
            Self::LowConfidenceAgreementCorrect => "low_confidence_agreement_correct",
            Self::SplitWrongDisagreement => "split_wrong_disagreement",
            Self::StaleSharedWrong => "stale_shared_wrong",
            Self::ActiveCorrectConflict => "active_correct_conflict",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Episode {
    pub id: u32,
    pub class: EpisodeClass,
    pub features: ObservationFeatures,
    pub correct_action: Choice,
    pub confidence: u16,
}

impl Episode {
    pub fn observation(self, signal: Signal) -> Observation {
        super::domain::observation_for(signal, self.confidence, self.features.encode(self.id))
    }
}

/// Correct action is specified by the task contract: goal category and authoritative world
/// revision jointly determine the only action that advances this workflow episode.
pub fn workflow_correct_action(goal: u8, world_revision: u8) -> Choice {
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
    CONTRACT[goal as usize % 3][world_revision as usize % 3]
}

pub fn heldout_episodes() -> Vec<Episode> {
    let mut episodes = Vec::with_capacity(256);
    for (class_index, (class, count)) in EpisodeClass::ALL.into_iter().enumerate() {
        for offset in 0..count {
            let id = (HELDOUT_SEED as u32).wrapping_add((class_index * 257 + offset) as u32);
            let goal = ((offset + class_index) % 3) as u8;
            let world_revision = ((offset * 2 + class_index + 1) % 3) as u8;
            let correct_action = workflow_correct_action(goal, world_revision);
            let wrong_one = Choice::ALL[(correct_action as usize + 1) % 3];
            let wrong_two = Choice::ALL[(correct_action as usize + 2) % 3];
            let (primary_action, audit_action, flags, confidence) = match class {
                EpisodeClass::FreshAgreementCorrect => (correct_action, correct_action, 0, 920),
                EpisodeClass::MisleadingSharedWrong => {
                    (wrong_one, wrong_one, FLAG_TOOL_WARNING, 920)
                }
                EpisodeClass::StalePrimaryDisagreement => {
                    (wrong_one, correct_action, FLAG_PRIMARY_STALE, 520)
                }
                EpisodeClass::ConflictingAuditDisagreement => {
                    (correct_action, wrong_one, FLAG_TOOL_WARNING, 920)
                }
                EpisodeClass::LowConfidenceAgreementCorrect => {
                    (correct_action, correct_action, 0, 520)
                }
                EpisodeClass::SplitWrongDisagreement => (
                    wrong_one,
                    wrong_two,
                    FLAG_PRIMARY_STALE | FLAG_TOOL_WARNING,
                    520,
                ),
                EpisodeClass::StaleSharedWrong => (wrong_one, wrong_one, FLAG_PRIMARY_STALE, 520),
                EpisodeClass::ActiveCorrectConflict => {
                    (correct_action, wrong_one, FLAG_TOOL_WARNING, 920)
                }
            };
            episodes.push(Episode {
                id,
                class,
                features: ObservationFeatures {
                    goal,
                    world_revision,
                    primary_action,
                    audit_action,
                    flags,
                },
                correct_action,
                confidence,
            });
        }
    }
    episodes
}

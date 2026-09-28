use crate::{
    domain::Choice,
    episodes::{Episode, HELDOUT_SEED},
};

/// Hidden labels derive from episode identity and task contract only. This module has no
/// observer, proposal, routing, or resolver dependency by design.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EvalLabel {
    pub episode_id: u32,
    pub truth_revision: u8,
    pub correct_action: Choice,
}

const LABEL_CONTRACT: [[Choice; 3]; 3] = [
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

pub fn heldout_labels(episodes: &[Episode]) -> Vec<EvalLabel> {
    episodes
        .iter()
        .map(|episode| {
            let offset = episode.id.wrapping_sub(HELDOUT_SEED as u32) as usize;
            let stratum = offset / 257;
            let within_stratum = offset % 257;
            let truth_revision = 40 + ((within_stratum + 2 * stratum) % 3) as u8;
            let correct_action =
                LABEL_CONTRACT[episode.features.goal as usize % 3][truth_revision as usize % 3];
            EvalLabel {
                episode_id: episode.id,
                truth_revision,
                correct_action,
            }
        })
        .collect()
}

pub fn hidden_label(goal: u8, truth_revision: u8) -> Choice {
    LABEL_CONTRACT[goal as usize % 3][truth_revision as usize % 3]
}

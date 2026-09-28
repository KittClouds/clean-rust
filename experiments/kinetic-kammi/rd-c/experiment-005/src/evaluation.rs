use rdc_experiment_004::Choice;

use crate::episodes::Episode;

/// Evaluation labels are generated from the task contract and hidden scenario coordinates.
/// This module does not depend on observers, routing plans, or inspection results.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EvalLabel {
    pub episode_id: u32,
    pub truth_revision: u8,
    pub correct_action: Choice,
}

pub fn labels_for(episodes: &[Episode], seed: u64) -> Vec<EvalLabel> {
    episodes
        .iter()
        .map(|episode| {
            let offset = episode.id.wrapping_sub(seed as u32) as usize;
            let stratum = offset / 257;
            let within = offset % 257;
            let truth_revision = 40 + ((within + 2 * stratum) % 3) as u8;
            EvalLabel {
                episode_id: episode.id,
                truth_revision,
                correct_action: label_contract(episode.frame.features.goal, truth_revision),
            }
        })
        .collect()
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

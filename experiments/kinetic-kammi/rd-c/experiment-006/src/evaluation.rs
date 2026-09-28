use rdc_experiment_004::Choice;

use crate::episodes::{Episode, contract_action, hidden_revision};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EvalLabel {
    pub episode_id: u32,
    pub truth_revision: u8,
    pub correct_action: Choice,
}

pub fn labels_for(episodes: &[Episode]) -> Vec<EvalLabel> {
    episodes
        .iter()
        .map(|episode| {
            let revision = hidden_revision(episode.domain as usize, episode.within as usize);
            EvalLabel {
                episode_id: episode.id,
                truth_revision: revision,
                correct_action: contract_action(episode.frame.features.goal, revision),
            }
        })
        .collect()
}

pub fn query_utility(active: Choice, result_action: Option<Choice>, correct: Choice) -> i8 {
    match result_action {
        Some(after) => match (active == correct, after == correct) {
            (false, true) => 1,
            (true, false) => -1,
            _ => 0,
        },
        None if active == correct => -1,
        None => 0,
    }
}

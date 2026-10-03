use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::{
    Digest, EPISODE_TAPE_V1, Error, FeatureCellState, MappedFeatureTape, ObservationSpec, Result,
    RunRawRow, identity,
};

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct Episode {
    pub episode_id: Digest,
    pub instrument_id: u32,
    pub first_source_row: u64,
    pub last_source_row: u64,
    pub first_actionable_row: u64,
    pub start_time: i64,
    pub end_time: i64,
    pub warmup_rows: u64,
    pub actionable_rows: u64,
    pub initial_account_state_id: Digest,
    pub observation_spec_id: Digest,
    pub action_spec_id: Digest,
    pub execution_spec_id: Digest,
    pub reward_spec_id: Digest,
    pub termination_contract_id: Digest,
    pub source_identity: Digest,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EpisodeTape {
    pub schema_version: String,
    pub runraw_tape_id: Digest,
    pub episode_spec_id: Digest,
    pub episodes: Vec<Episode>,
    pub content_hash: Digest,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ObservationDictionaryEntry {
    pub array_index: u32,
    pub feature_id: String,
    pub feature_implementation_hash: Digest,
    pub source_dependencies: Vec<String>,
}

#[derive(Clone, Copy, Debug)]
pub struct EpisodeBindings {
    pub initial_account_state_id: Digest,
    pub action_spec_id: Digest,
    pub execution_spec_id: Digest,
    pub reward_spec_id: Digest,
    pub termination_spec_id: Digest,
}

pub fn compile_session_episodes(
    rows: &[RunRawRow],
    feature_tape: &MappedFeatureTape,
    observation_spec: &ObservationSpec,
    runraw_tape_id: Digest,
    episode_spec_id: Digest,
    bindings: EpisodeBindings,
) -> Result<EpisodeTape> {
    if rows.len() != feature_tape.header().row_count as usize {
        return Err(Error::InvalidContract(
            "RunRaw and Feature Tape row counts differ".into(),
        ));
    }
    if observation_spec.history_depth == 0 {
        return Err(Error::InvalidContract(
            "observation history depth must be positive".into(),
        ));
    }
    for feature_id in &observation_spec.ordered_feature_ids {
        if feature_tape.column(feature_id).is_none() {
            return Err(Error::InvalidContract(format!(
                "observation feature {feature_id} is absent"
            )));
        }
    }
    let mut episodes = Vec::new();
    let mut first = 0;
    while first < rows.len() {
        let mut end = first + 1;
        while end < rows.len()
            && rows[end].instrument_id == rows[first].instrument_id
            && rows[end].session_id == rows[first].session_id
        {
            end += 1;
        }
        if let Some(actionable) = (first..end.saturating_sub(1))
            .find(|&index| observation_available(feature_tape, observation_spec, rows, index))
        {
            let draft = Episode {
                episode_id: Digest::ZERO,
                instrument_id: rows[first].instrument_id,
                first_source_row: rows[first].source_row_id,
                last_source_row: rows[end - 1].source_row_id,
                first_actionable_row: rows[actionable].source_row_id,
                start_time: rows[first].event_time,
                end_time: rows[end - 1].event_time,
                warmup_rows: (actionable - first) as u64,
                actionable_rows: (end - actionable - 1) as u64,
                initial_account_state_id: bindings.initial_account_state_id,
                observation_spec_id: observation_spec.observation_spec_id,
                action_spec_id: bindings.action_spec_id,
                execution_spec_id: bindings.execution_spec_id,
                reward_spec_id: bindings.reward_spec_id,
                termination_contract_id: bindings.termination_spec_id,
                source_identity: runraw_tape_id,
                content_hash: Digest::ZERO,
            };
            let mut episode = draft;
            episode.content_hash = identity(b"northstar-episode-content-v1", &episode)?;
            episode.episode_id = identity(b"northstar-episode-id-v1", &episode)?;
            episodes.push(episode);
        }
        first = end;
    }
    if episodes.is_empty() {
        return Err(Error::InvalidContract(
            "no qualified session episode could be built".into(),
        ));
    }
    let mut tape = EpisodeTape {
        schema_version: EPISODE_TAPE_V1.into(),
        runraw_tape_id,
        episode_spec_id,
        episodes,
        content_hash: Digest::ZERO,
    };
    tape.content_hash = identity(b"northstar-episode-tape-content-v1", &tape)?;
    Ok(tape)
}

pub fn observation_available(
    feature_tape: &MappedFeatureTape,
    observation_spec: &ObservationSpec,
    rows: &[RunRawRow],
    index: usize,
) -> bool {
    let depth = observation_spec.history_depth as usize;
    if index + 1 < depth {
        return false;
    }
    let first = index + 1 - depth;
    if rows[first].session_id != rows[index].session_id
        || rows[first].instrument_id != rows[index].instrument_id
    {
        return false;
    }
    let observation_time = rows[index].event_time;
    (first..=index).all(|row_index| {
        observation_spec
            .ordered_feature_ids
            .iter()
            .all(|feature_id| {
                feature_tape
                    .cell(feature_id, row_index)
                    .is_some_and(|(_, state, known)| {
                        state == FeatureCellState::Available && known <= observation_time
                    })
            })
    })
}

pub fn episode_tape_id(tape: &EpisodeTape) -> Result<Digest> {
    identity(b"northstar-episode-tape-identity-v1", tape)
}

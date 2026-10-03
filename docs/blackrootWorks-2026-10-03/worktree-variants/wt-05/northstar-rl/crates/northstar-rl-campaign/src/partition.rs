use std::collections::{BTreeMap, BTreeSet};

use northstar_rl_core::{Digest, identified, identity};

use crate::{
    EpisodePartitionInput, Error, PARTITION_TAPE_V1, PartitionAssignment, PartitionRole,
    PartitionTape, Result,
};

#[derive(Clone, Copy, Debug)]
pub struct ChronologicalPartitionPlan {
    pub train_groups: usize,
    pub development_groups: usize,
    pub embargo_ns: i64,
}

pub fn build_chronological_group_partition(
    source_episode_tape_id: Digest,
    inputs: &[EpisodePartitionInput],
    plan: ChronologicalPartitionPlan,
) -> Result<PartitionTape> {
    if inputs.is_empty() || plan.train_groups == 0 || plan.development_groups == 0 {
        return Err(Error::Contract(
            "partition requires episodes and non-empty train/development groups".into(),
        ));
    }
    let mut sorted = inputs.to_vec();
    sorted.sort_by_key(|episode| {
        (
            episode.start_time_ns,
            episode.end_time_ns,
            episode.episode_id,
        )
    });
    let mut ids = BTreeSet::new();
    for (index, episode) in sorted.iter().enumerate() {
        if !ids.insert(episode.episode_id) || episode.start_time_ns >= episode.end_time_ns {
            return Err(Error::Contract(
                "invalid or duplicate partition episode".into(),
            ));
        }
        if index > 0 && sorted[index - 1].end_time_ns > episode.start_time_ns {
            return Err(Error::Contract(
                "chronological partition inputs overlap".into(),
            ));
        }
    }
    let mut groups = BTreeMap::<String, Vec<usize>>::new();
    for (index, episode) in sorted.iter().enumerate() {
        groups
            .entry(episode.group_id.clone())
            .or_default()
            .push(index);
    }
    let mut ordered_groups = groups
        .into_iter()
        .map(|(id, members)| (sorted[members[0]].start_time_ns, id, members))
        .collect::<Vec<_>>();
    ordered_groups.sort_by_key(|(start, id, _)| (*start, id.clone()));
    if plan.train_groups + plan.development_groups >= ordered_groups.len() {
        return Err(Error::Contract(
            "partition plan leaves no evaluation group".into(),
        ));
    }
    let development_start = plan.train_groups;
    let evaluation_start = plan.train_groups + plan.development_groups;
    let dev_boundary = ordered_groups[development_start].0;
    let eval_boundary = ordered_groups[evaluation_start].0;
    let mut role_by_index = vec![PartitionRole::Evaluation; sorted.len()];
    for (group_index, (_, _, members)) in ordered_groups.iter().enumerate() {
        let base_role = if group_index < development_start {
            PartitionRole::Train
        } else if group_index < evaluation_start {
            PartitionRole::Development
        } else {
            PartitionRole::Evaluation
        };
        for &member in members {
            let episode = &sorted[member];
            let embargoed = plan.embargo_ns > 0
                && ([dev_boundary, eval_boundary].into_iter().any(|boundary| {
                    episode.end_time_ns > boundary.saturating_sub(plan.embargo_ns)
                        && episode.start_time_ns < boundary.saturating_add(plan.embargo_ns)
                }));
            role_by_index[member] = if embargoed {
                PartitionRole::ExcludedEmbargo
            } else {
                base_role
            };
        }
    }
    for required in [
        PartitionRole::Train,
        PartitionRole::Development,
        PartitionRole::Evaluation,
    ] {
        if !role_by_index.contains(&required) {
            return Err(Error::Contract(format!(
                "partition has no {required:?} episodes after embargo"
            )));
        }
    }
    let assignments = sorted
        .iter()
        .zip(role_by_index)
        .enumerate()
        .map(|(ordinal, (episode, role))| PartitionAssignment {
            episode_id: episode.episode_id,
            group_id: episode.group_id.clone(),
            chronological_ordinal: ordinal as u64,
            role,
            reason_code: if role == PartitionRole::ExcludedEmbargo {
                "BOUNDARY_EMBARGO".into()
            } else {
                "CHRONOLOGICAL_GROUP_ASSIGNMENT".into()
            },
        })
        .collect::<Vec<_>>();
    let episode_population_hash = identity(b"northstar-partition-population-v1", &sorted)?;
    let mut tape = PartitionTape {
        schema_version: PARTITION_TAPE_V1.into(),
        partition_tape_id: Digest::ZERO,
        source_episode_tape_id,
        strategy: "chronological_group_aware_v1".into(),
        group_key: "declared_group_id".into(),
        chronology_key: "episode_start_time_ns_then_end_time_ns".into(),
        embargo_ns: plan.embargo_ns,
        assignments,
        episode_population_hash,
        sealed: true,
        content_hash: Digest::ZERO,
    };
    tape.content_hash = identity(b"northstar-partition-tape-content-v1", &tape)?;
    tape = identified(b"northstar-partition-tape-v1", tape, |value, digest| {
        value.partition_tape_id = digest
    })?;
    Ok(tape)
}

pub fn validate_partition_identity(tape: &PartitionTape) -> Result<()> {
    if !tape.sealed {
        return Err(Error::Contract("campaign partition must be sealed".into()));
    }
    let mut candidate = tape.clone();
    candidate.partition_tape_id = Digest::ZERO;
    let actual = identity(b"northstar-partition-tape-v1", &candidate)?;
    if actual != tape.partition_tape_id {
        return Err(Error::Contract(
            "partition identity changed after sealing".into(),
        ));
    }
    Ok(())
}

pub fn role_episode_ids(tape: &PartitionTape, role: PartitionRole) -> Vec<Digest> {
    tape.assignments
        .iter()
        .filter(|assignment| assignment.role == role)
        .map(|assignment| assignment.episode_id)
        .collect()
}

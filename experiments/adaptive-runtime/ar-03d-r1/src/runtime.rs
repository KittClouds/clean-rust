use std::time::Instant;

use crate::model::{BATCH_SIZE, Model, PARAMS, Sample, TRAIN_SAMPLES, VERIFIER_SIZE};
use crate::partition::{self, STRATUM_COUNT, STRATUM_SIZE};
use crate::protocol;
use crate::runtime_partition;

pub const VALIDATION_SEEDS: [u64; 5] = [
    0xa303_d1fa_0000_0001,
    0xa303_d1fa_0000_0002,
    0xa303_d1fa_0000_0003,
    0xa303_d1fa_0000_0004,
    0xa303_d1fa_0000_0005,
];
pub const RUNTIME_STEPS: usize = 4_200;
pub const PARTITION_REFRESH_SLOTS: usize = 100;
pub const RUNTIME_CHECKPOINTS: [usize; 4] = [0, 600, 2_400, RUNTIME_STEPS];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeArm {
    ProjectedOrder1d,
    HashPlacebo,
}

impl RuntimeArm {
    pub const ALL: [Self; 2] = [Self::ProjectedOrder1d, Self::HashPlacebo];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ProjectedOrder1d => "projected_order_1d",
            Self::HashPlacebo => "hash_placebo",
        }
    }
}

#[derive(Clone, Debug)]
pub struct RuntimeCheckpoint {
    pub step: usize,
    pub train_loss: f32,
    pub evaluation_loss: f32,
    pub evaluation_accuracy: f32,
    pub fingerprint: u64,
}

#[derive(Clone, Debug)]
pub struct RuntimePanel {
    pub evidence_round: usize,
    pub slot_start: usize,
    pub partition_epoch: usize,
    pub partition_id: Option<u8>,
    pub partition_fingerprint: u64,
    pub panel_fingerprint: u64,
    pub proposal_fingerprint: u64,
    pub panel_ns: u128,
    pub quota_valid: bool,
}

#[derive(Clone, Debug)]
pub struct RuntimePartitionBuild {
    pub refresh_slot: usize,
    pub partition_id: Option<u8>,
    pub partition_fingerprint: u64,
    pub feature_ns: u128,
    pub ordering_or_hash_ns: u128,
}

#[derive(Clone, Debug)]
pub struct RuntimeDecision {
    pub step: usize,
    pub schedule_offset: usize,
    pub partition_epoch: usize,
    pub panel_fingerprint: u64,
    pub policy_ns: u128,
    pub verifier_programs_evaluated: u16,
    pub selected: bool,
    pub left_parameter: Option<usize>,
    pub right_parameter: Option<usize>,
    pub left_delta: f32,
    pub right_delta: f32,
    pub verifier_utility: f32,
    pub full_training_utility: Option<f32>,
    pub shadow_ns: u128,
}

#[derive(Clone, Debug)]
pub struct RuntimeTrajectory {
    pub dataset_index: u8,
    pub dataset_seed: u64,
    pub initialization_index: u8,
    pub initialization_seed: u64,
    pub stream_seed: u64,
    pub arm: RuntimeArm,
    pub hash_partition_id: Option<u8>,
    pub panels: Vec<RuntimePanel>,
    pub partition_builds: Vec<RuntimePartitionBuild>,
    pub decisions: Vec<RuntimeDecision>,
    pub checkpoints: Vec<RuntimeCheckpoint>,
}

#[derive(Clone, Copy, Debug)]
pub struct RuntimeContext {
    pub dataset_index: u8,
    pub dataset_seed: u64,
    pub initialization_index: u8,
    pub initialization_seed: u64,
    pub stream_seed: u64,
    pub arm: RuntimeArm,
    pub hash_partition_id: u8,
}

pub fn replay_training_arm(
    train: &[Sample],
    evaluation: &[Sample],
    context: RuntimeContext,
) -> RuntimeTrajectory {
    let RuntimeContext {
        dataset_index,
        dataset_seed,
        initialization_index,
        initialization_seed,
        stream_seed,
        arm,
        hash_partition_id,
    } = context;
    assert_eq!(train.len(), TRAIN_SAMPLES);
    assert_eq!(evaluation.len(), TRAIN_SAMPLES);
    assert!(hash_partition_id < 8);

    let mut model = Model::initial(initialization_seed);
    let mut partition_ids = [0_u8; TRAIN_SAMPLES];
    let mut partition_epoch = 0;
    let mut panels = Vec::with_capacity(RUNTIME_STEPS / protocol::COMMITS_PER_EVIDENCE);
    let mut partition_builds = Vec::with_capacity(RUNTIME_STEPS / PARTITION_REFRESH_SLOTS + 1);
    let mut decisions = Vec::with_capacity(RUNTIME_STEPS);
    let mut checkpoints = Vec::with_capacity(RUNTIME_CHECKPOINTS.len());
    let assigned_hash_id = (arm == RuntimeArm::HashPlacebo).then_some(hash_partition_id);

    if arm == RuntimeArm::HashPlacebo {
        let started = Instant::now();
        partition_ids = partition::hash_placebo(hash_partition_id);
        assert_eq!(
            partition::stratum_counts(&partition_ids),
            [STRATUM_SIZE; STRATUM_COUNT]
        );
        partition_builds.push(RuntimePartitionBuild {
            refresh_slot: 0,
            partition_id: Some(hash_partition_id),
            partition_fingerprint: runtime_partition::partition_fingerprint(&partition_ids),
            feature_ns: 0,
            ordering_or_hash_ns: started.elapsed().as_nanos(),
        });
    }

    push_checkpoint(&mut checkpoints, 0, &model, train, evaluation);
    for evidence_round in 0..RUNTIME_STEPS / protocol::COMMITS_PER_EVIDENCE {
        let slot_start = evidence_round * protocol::COMMITS_PER_EVIDENCE;
        if arm == RuntimeArm::ProjectedOrder1d && slot_start.is_multiple_of(PARTITION_REFRESH_SLOTS)
        {
            let built = runtime_partition::projected_order(&model, train);
            partition_ids = built.ids;
            partition_epoch = slot_start;
            partition_builds.push(RuntimePartitionBuild {
                refresh_slot: slot_start,
                partition_id: None,
                partition_fingerprint: runtime_partition::partition_fingerprint(&partition_ids),
                feature_ns: built.feature_ns,
                ordering_or_hash_ns: built.ordering_ns,
            });
        }

        let proposal_indices = protocol::proposal_indices(stream_seed, evidence_round);
        let proposal: [Sample; BATCH_SIZE] =
            std::array::from_fn(|index| train[proposal_indices[index]]);
        let panel_started = Instant::now();
        let panel_indices =
            runtime_partition::sample_panel(&partition_ids, stream_seed, evidence_round);
        let panel_fingerprint = runtime_partition::indices_fingerprint(&panel_indices);
        let verifier: [Sample; VERIFIER_SIZE] =
            std::array::from_fn(|index| train[panel_indices[index]]);
        let panel_ns = panel_started.elapsed().as_nanos();
        panels.push(RuntimePanel {
            evidence_round,
            slot_start,
            partition_epoch,
            partition_id: assigned_hash_id,
            partition_fingerprint: runtime_partition::partition_fingerprint(&partition_ids),
            panel_fingerprint,
            proposal_fingerprint: runtime_partition::indices_fingerprint(&proposal_indices),
            panel_ns,
            quota_valid: runtime_partition::has_exact_panel_quotas(&partition_ids, &panel_indices),
        });

        for inner in 0..protocol::COMMITS_PER_EVIDENCE {
            let global_commit = slot_start + inner;
            let schedule_offset = global_commit % PARAMS;
            let policy_started = Instant::now();
            let (selected, verifier_programs_evaluated) =
                protocol::select_runtime_program(&model, &proposal, &verifier, schedule_offset);
            let policy_ns = policy_started.elapsed().as_nanos();
            let (full_training_utility, shadow_ns) = if let Some(program) = selected {
                let shadow_started = Instant::now();
                let utility = full_training_utility(&model, train, program);
                let shadow_ns = shadow_started.elapsed().as_nanos();
                protocol::commit_runtime_program(&mut model, program);
                (Some(utility), shadow_ns)
            } else {
                (None, 0)
            };
            let step = global_commit + 1;
            decisions.push(RuntimeDecision {
                step,
                schedule_offset,
                partition_epoch,
                panel_fingerprint,
                policy_ns,
                verifier_programs_evaluated,
                selected: selected.is_some(),
                left_parameter: selected.map(|program| program.left),
                right_parameter: selected
                    .and_then(|program| (program.len == 2).then_some(program.right)),
                left_delta: selected.map_or(0.0, |program| program.deltas[0]),
                right_delta: selected.map_or(0.0, |program| program.deltas[1]),
                verifier_utility: selected.map_or(0.0, |program| program.verifier_utility),
                full_training_utility,
                shadow_ns,
            });
            if RUNTIME_CHECKPOINTS.contains(&step) {
                push_checkpoint(&mut checkpoints, step, &model, train, evaluation);
            }
        }
    }
    assert_eq!(decisions.len(), RUNTIME_STEPS);
    assert_eq!(panels.len(), RUNTIME_STEPS / protocol::COMMITS_PER_EVIDENCE);
    assert_eq!(checkpoints.len(), RUNTIME_CHECKPOINTS.len());

    RuntimeTrajectory {
        dataset_index,
        dataset_seed,
        initialization_index,
        initialization_seed,
        stream_seed,
        arm,
        hash_partition_id: assigned_hash_id,
        panels,
        partition_builds,
        decisions,
        checkpoints,
    }
}

fn full_training_utility(
    model: &Model,
    train: &[Sample],
    program: protocol::RuntimeProgram,
) -> f32 {
    let baseline = model.loss(train);
    let mut candidate = *model;
    candidate.parameters[program.left] += program.deltas[0];
    if program.len == 2 {
        candidate.parameters[program.right] += program.deltas[1];
    }
    baseline - candidate.loss(train)
}

fn push_checkpoint(
    checkpoints: &mut Vec<RuntimeCheckpoint>,
    step: usize,
    model: &Model,
    train: &[Sample],
    evaluation: &[Sample],
) {
    let correct = evaluation
        .iter()
        .filter(|sample| {
            let logits = model.logits(sample).0;
            let prediction = logits
                .iter()
                .enumerate()
                .max_by(|left, right| left.1.total_cmp(right.1))
                .map(|(index, _)| index)
                .expect("three class logits");
            prediction == sample.target as usize
        })
        .count();
    checkpoints.push(RuntimeCheckpoint {
        step,
        train_loss: model.loss(train),
        evaluation_loss: model.loss(evaluation),
        evaluation_accuracy: correct as f32 / evaluation.len() as f32,
        fingerprint: protocol::runtime_parameter_fingerprint(model),
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model;

    #[test]
    fn frozen_validation_seeds_are_disjoint_from_training_runtime_seeds() {
        let mut seeds = protocol::DATASET_SEEDS.to_vec();
        seeds.extend(protocol::INITIALIZATION_SEEDS);
        seeds.extend(protocol::DEVELOPMENT_SEEDS);
        seeds.extend(protocol::EVALUATION_SEEDS);
        seeds.extend(VALIDATION_SEEDS);
        seeds.sort_unstable();
        seeds.dedup();
        assert_eq!(
            seeds.len(),
            protocol::DATASET_SEEDS.len()
                + protocol::INITIALIZATION_SEEDS.len()
                + protocol::DEVELOPMENT_SEEDS.len()
                + protocol::EVALUATION_SEEDS.len()
                + VALIDATION_SEEDS.len()
        );
        assert_eq!(model::ACTION_VALUES.len(), 7);
    }

    #[test]
    fn full_training_shadow_is_the_exact_one_step_training_utility() {
        let samples = model::generate_dataset(protocol::DATASET_SEEDS[0]);
        let current = Model::initial(protocol::INITIALIZATION_SEEDS[0]);
        let old_loss = current.loss(&samples);
        let mut changed = current;
        changed.parameters[0] += -0.005;
        let measured = old_loss - changed.loss(&samples);
        assert!(measured.is_finite());
    }
}

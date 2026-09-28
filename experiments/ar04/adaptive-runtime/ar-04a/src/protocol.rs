use crate::frozen_protocol;
use crate::model::{
    ACTION_VALUES, BATCH_SIZE, LOWER_BOUND, Model, PARAMS, Sample, TRAIN_SAMPLES, UPPER_BOUND,
};
use crate::partition::{STRATUM_COUNT, STRATUM_SIZE};
use crate::runtime_partition;

pub const HORIZONS: [usize; 4] = [0, 8, 32, 128];
pub const STATE_STAGES: [usize; 3] = [600, 2_400, 4_200];
pub const DATASET_COUNT: usize = 5;
pub const INITIALIZATION_COUNT: usize = 5;
pub const CELL_COUNT: usize = DATASET_COUNT * INITIALIZATION_COUNT;
pub const STATE_COUNT: usize = CELL_COUNT * STATE_STAGES.len();
pub const CONTINUATIONS_PER_STATE: usize = 8;
pub const CONTINUATION_COUNT: usize = STATE_COUNT * CONTINUATIONS_PER_STATE;
pub const TIE_EPSILON: f64 = 1.0e-7;
pub const MIN_VALID_CONTINUATIONS: usize = 6;
pub const ACTION_SPLIT_SALT: u64 = 0x4152_3033_4152_3153;
#[cfg(test)]
pub use crate::frozen_protocol::{DATASET_SEEDS, EVALUATION_SEEDS};
pub const SEED_NAMESPACES: [u32; 6] = [
    0xa404_41da,
    0xa404_4e7a,
    0xa404_1a17,
    0xa404_57a7,
    0xa404_ca7a,
    0xa404_c07a,
];

pub const TRAINING_SEEDS: [u64; DATASET_COUNT] = seed_series(0xa404_41da_0000_0000);
pub const HELDOUT_SEEDS: [u64; DATASET_COUNT] = seed_series(0xa404_4e7a_0000_0000);
pub const INITIALIZATION_SEEDS: [u64; INITIALIZATION_COUNT] = seed_series(0xa404_1a17_0000_0000);
pub const STATE_STREAM_SEEDS: [u64; CELL_COUNT] = seed_series(0xa404_57a7_0000_0000);
pub const ACTION_PROPOSAL_SEEDS: [u64; STATE_COUNT] = seed_series(0xa404_ca7a_0000_0000);
pub const CONTINUATION_SEEDS: [u64; CONTINUATION_COUNT] = seed_series(0xa404_c07a_0000_0000);

const fn seed_series<const N: usize>(prefix: u64) -> [u64; N] {
    let mut seeds = [0; N];
    let mut index = 0;
    while index < N {
        seeds[index] = prefix | (index as u64 + 1);
        index += 1;
    }
    seeds
}

#[derive(Clone, Copy, Debug)]
pub struct ActionCandidate {
    pub action_id: u16,
    pub block_id: u16,
    pub left_parameter: u16,
    pub right_parameter: u16,
    pub left_rank: u8,
    pub right_rank: u8,
    pub left_delta: f32,
    pub right_delta: f32,
    pub immediate_train_utility: f64,
    pub immediate_heldout_utility: f64,
    pub taylor_train_utility: f64,
    pub taylor_heldout_utility: f64,
    pub output_taylor_train_utility: Option<f64>,
    pub output_taylor_heldout_utility: Option<f64>,
    pub projected_within_utility_variance: f64,
}

#[derive(Clone, Copy, Debug)]
pub struct StateRecord {
    pub cell_id: usize,
    pub dataset_id: usize,
    pub initialization_id: usize,
    pub initialization_seed: u64,
    pub state_id: usize,
    pub stage: usize,
    pub state_seed: u64,
    pub action_proposal_seed: u64,
    pub hash_partition_id: u8,
    pub model: Model,
    pub training_loss: f64,
    pub heldout_loss: f64,
    pub parameter_rms: f64,
    pub active_hidden_fraction: f64,
    pub fingerprint: u64,
    pub candidate_fingerprint: u64,
    pub candidate_count: usize,
    pub valid_continuations: usize,
    pub censored_continuations: usize,
}

#[derive(Clone, Copy, Debug)]
pub struct FrozenUpdate {
    pub selected: bool,
    pub left_parameter: u16,
    pub right_parameter: u16,
    pub len: u8,
    pub deltas: [f32; 2],
}

#[derive(Clone, Debug)]
pub struct Continuation {
    pub continuation_id: usize,
    pub seed: u64,
    pub hash_partition_id: u8,
    pub source_state_fingerprint: u64,
    pub proposal_fingerprints: Vec<u64>,
    pub panel_fingerprints: Vec<u64>,
    pub updates: Vec<FrozenUpdate>,
    pub sequence_fingerprint: u64,
    pub exogenous_fingerprint: u64,
    pub baseline_bound_events: usize,
}

#[derive(Clone, Copy, Debug)]
struct SingletonAction {
    delta: f32,
    utility: f32,
}

#[derive(Clone, Copy, Debug)]
struct PairBlock {
    left: usize,
    right: usize,
    len: usize,
}

pub fn fresh_seeds_are_unique() -> bool {
    let mut seeds = Vec::with_capacity(
        TRAINING_SEEDS.len()
            + HELDOUT_SEEDS.len()
            + INITIALIZATION_SEEDS.len()
            + STATE_STREAM_SEEDS.len()
            + ACTION_PROPOSAL_SEEDS.len()
            + CONTINUATION_SEEDS.len(),
    );
    seeds.extend(TRAINING_SEEDS);
    seeds.extend(HELDOUT_SEEDS);
    seeds.extend(INITIALIZATION_SEEDS);
    seeds.extend(STATE_STREAM_SEEDS);
    seeds.extend(ACTION_PROPOSAL_SEEDS);
    seeds.extend(CONTINUATION_SEEDS);
    let unique: hashbrown::HashSet<_> = seeds.iter().copied().collect();
    seeds.len() == unique.len()
        && seeds.iter().all(|seed| {
            let prefix = (seed >> 32) as u32;
            SEED_NAMESPACES.contains(&prefix)
                && !matches!(
                    prefix,
                    0xa303_dada | 0xa303_1a17 | 0xa303_de00 | 0xa303_ea00 | 0xa303_fa00
                )
        })
}

pub fn build_action_set(
    model: &Model,
    train: &[Sample],
    heldout: &[Sample],
    proposal_seed: u64,
    stage: usize,
) -> Vec<ActionCandidate> {
    assert_eq!(train.len(), TRAIN_SAMPLES);
    assert_eq!(heldout.len(), TRAIN_SAMPLES);
    let indices = frozen_protocol::proposal_indices(proposal_seed, 0);
    let proposal: [Sample; BATCH_SIZE] = std::array::from_fn(|index| train[indices[index]]);
    let proposal_baseline = model.loss(&proposal);
    let groups = pair_blocks(stage % PARAMS);
    let projected_ids = runtime_partition::projected_order(model, train).ids;
    let train_baseline: [f32; TRAIN_SAMPLES] =
        std::array::from_fn(|index| model.loss_one(&train[index]));
    let heldout_baseline: [f32; TRAIN_SAMPLES] =
        std::array::from_fn(|index| model.loss_one(&heldout[index]));
    let train_gradients: Vec<[f32; PARAMS]> = train
        .iter()
        .map(|sample| model.gradient_one(sample).1)
        .collect();
    let heldout_gradients: Vec<[f32; PARAMS]> = heldout
        .iter()
        .map(|sample| model.gradient_one(sample).1)
        .collect();
    let mut candidates = Vec::with_capacity(PARAMS * 2);

    for (block_id, block) in groups.into_iter().enumerate() {
        if block.len != 2 {
            continue;
        }
        let left_top = top_two(singleton_actions(
            model,
            &proposal,
            proposal_baseline,
            block.left,
        ));
        let right_top = top_two(singleton_actions(
            model,
            &proposal,
            proposal_baseline,
            block.right,
        ));
        let all_legal = left_top.iter().all(|action| {
            (LOWER_BOUND..=UPPER_BOUND).contains(&(model.parameters[block.left] + action.delta))
        }) && right_top.iter().all(|action| {
            (LOWER_BOUND..=UPPER_BOUND).contains(&(model.parameters[block.right] + action.delta))
        });
        if !all_legal {
            continue;
        }
        let pair_key =
            ((block.left.min(block.right) as u64) << 32) | block.left.max(block.right) as u64;
        let development_diagonal = mix64(pair_key ^ ACTION_SPLIT_SALT) & 1 == 0;
        for (left_rank, left_action) in left_top.iter().enumerate() {
            for (right_rank, right_action) in right_top.iter().enumerate() {
                let is_development = (left_rank == right_rank) == development_diagonal;
                if is_development {
                    continue;
                }
                let mut candidate = *model;
                candidate.parameters[block.left] += left_action.delta;
                candidate.parameters[block.right] += right_action.delta;

                let mut train_utility = 0.0;
                let mut heldout_utility = 0.0;
                let mut projected_sums = [0.0_f64; STRATUM_COUNT];
                let mut projected_squares = [0.0_f64; STRATUM_COUNT];
                let mut taylor_train = 0.0;
                let mut taylor_heldout = 0.0;
                for index in 0..TRAIN_SAMPLES {
                    let utility =
                        f64::from(train_baseline[index] - candidate.loss_one(&train[index]));
                    train_utility += utility;
                    let stratum = usize::from(projected_ids[index]);
                    projected_sums[stratum] += utility;
                    projected_squares[stratum] += utility * utility;
                    taylor_train -= f64::from(
                        train_gradients[index][block.left] * left_action.delta
                            + train_gradients[index][block.right] * right_action.delta,
                    );
                }
                for index in 0..TRAIN_SAMPLES {
                    heldout_utility +=
                        f64::from(heldout_baseline[index] - candidate.loss_one(&heldout[index]));
                    taylor_heldout -= f64::from(
                        heldout_gradients[index][block.left] * left_action.delta
                            + heldout_gradients[index][block.right] * right_action.delta,
                    );
                }
                train_utility /= TRAIN_SAMPLES as f64;
                heldout_utility /= TRAIN_SAMPLES as f64;
                taylor_train /= TRAIN_SAMPLES as f64;
                taylor_heldout /= TRAIN_SAMPLES as f64;
                let mut within_sse = 0.0;
                for stratum in 0..STRATUM_COUNT {
                    let mean = projected_sums[stratum] / STRATUM_SIZE as f64;
                    within_sse += projected_squares[stratum] - 2.0 * mean * projected_sums[stratum]
                        + STRATUM_SIZE as f64 * mean * mean;
                }
                let output_layer =
                    (144..PARAMS).contains(&block.left) && (144..PARAMS).contains(&block.right);
                let output_taylor_train = output_layer.then_some(taylor_train);
                let output_taylor_heldout = output_layer.then_some(taylor_heldout);
                candidates.push(ActionCandidate {
                    action_id: candidates.len() as u16,
                    block_id: block_id as u16,
                    left_parameter: block.left as u16,
                    right_parameter: block.right as u16,
                    left_rank: left_rank as u8,
                    right_rank: right_rank as u8,
                    left_delta: left_action.delta,
                    right_delta: right_action.delta,
                    immediate_train_utility: train_utility,
                    immediate_heldout_utility: heldout_utility,
                    taylor_train_utility: taylor_train,
                    taylor_heldout_utility: taylor_heldout,
                    output_taylor_train_utility: output_taylor_train,
                    output_taylor_heldout_utility: output_taylor_heldout,
                    projected_within_utility_variance: within_sse / TRAIN_SAMPLES as f64,
                });
            }
        }
    }
    candidates
}

pub fn action_fingerprint(actions: &[ActionCandidate]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for action in actions {
        for value in [
            u64::from(action.action_id),
            u64::from(action.block_id),
            u64::from(action.left_parameter),
            u64::from(action.right_parameter),
            u64::from(action.left_delta.to_bits()),
            u64::from(action.right_delta.to_bits()),
        ] {
            hash = (hash ^ value).wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    hash
}

pub fn state_features(model: &Model, train: &[Sample]) -> (f64, f64) {
    let parameter_rms = (model
        .parameters
        .iter()
        .map(|value| f64::from(*value).powi(2))
        .sum::<f64>()
        / PARAMS as f64)
        .sqrt();
    let active = train
        .iter()
        .map(|sample| {
            let (_, first, second) = model.logits(sample);
            first.iter().filter(|value| **value > 0.0).count()
                + second.iter().filter(|value| **value > 0.0).count()
        })
        .sum::<usize>();
    let total = train.len() * (crate::model::HIDDEN_1 + crate::model::HIDDEN_2);
    (parameter_rms, active as f64 / total as f64)
}

pub fn parameter_layer(parameter: usize) -> &'static str {
    match parameter {
        0..=63 => "input-hidden1",
        64..=71 => "hidden1-bias",
        72..=135 => "hidden1-hidden2",
        136..=143 => "hidden2-bias",
        144..=167 => "hidden2-output",
        _ => "output-bias",
    }
}

fn pair_blocks(round: usize) -> Vec<PairBlock> {
    let mut order = [PARAMS; PARAMS + 1];
    for (position, slot) in order.iter_mut().enumerate().skip(1) {
        *slot = (position - 1 + round) % PARAMS;
    }
    let mut groups = Vec::with_capacity(PARAMS / 2 + 1);
    for left in 0..=(PARAMS / 2) {
        let first = order[left];
        let second = order[PARAMS - left];
        if first == PARAMS {
            groups.push(PairBlock {
                left: second,
                right: second,
                len: 1,
            });
        } else if second == PARAMS {
            groups.push(PairBlock {
                left: first,
                right: first,
                len: 1,
            });
        } else {
            groups.push(PairBlock {
                left: first,
                right: second,
                len: 2,
            });
        }
    }
    groups
}

fn singleton_actions(
    model: &Model,
    proposal: &[Sample; BATCH_SIZE],
    baseline: f32,
    parameter: usize,
) -> [SingletonAction; 7] {
    let mut actions = [SingletonAction {
        delta: 0.0,
        utility: f32::NEG_INFINITY,
    }; 7];
    for (index, &delta) in ACTION_VALUES.iter().enumerate() {
        let value = model.parameters[parameter] + delta;
        if !(LOWER_BOUND..=UPPER_BOUND).contains(&value) {
            continue;
        }
        let mut candidate = *model;
        candidate.parameters[parameter] = value;
        actions[index] = SingletonAction {
            delta,
            utility: baseline - candidate.loss(proposal),
        };
    }
    actions
}

fn top_two(actions: [SingletonAction; 7]) -> [SingletonAction; 2] {
    let mut order = [0_usize, 1, 2, 3, 4, 5, 6];
    order.sort_by(|left, right| actions[*right].utility.total_cmp(&actions[*left].utility));
    [actions[order[0]], actions[order[1]]]
}

pub fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_ar04_seed_roles_are_unique_and_protocol_scoped() {
        assert!(fresh_seeds_are_unique());
        assert_eq!(
            TRAINING_SEEDS.len()
                + HELDOUT_SEEDS.len()
                + INITIALIZATION_SEEDS.len()
                + STATE_STREAM_SEEDS.len()
                + ACTION_PROPOSAL_SEEDS.len()
                + CONTINUATION_SEEDS.len(),
            715
        );
    }

    #[test]
    fn pair_schedule_covers_every_pair_and_has_one_singleton() {
        for phase in [0, 600, 2_400, 4_200] {
            let blocks = pair_blocks(phase % PARAMS);
            let pairs: Vec<_> = blocks.iter().filter(|block| block.len == 2).collect();
            assert_eq!(pairs.len(), PARAMS / 2);
            assert_eq!(blocks.iter().filter(|block| block.len == 1).count(), 1);
            assert!(pairs.iter().all(|block| block.left != block.right));
        }
    }

    #[test]
    fn action_split_retains_two_candidate_compounds_per_legal_block() {
        let train = crate::model::generate_dataset(TRAINING_SEEDS[0]);
        let heldout = crate::model::generate_dataset(HELDOUT_SEEDS[0]);
        let model = Model::initial(INITIALIZATION_SEEDS[0]);
        let candidates = build_action_set(&model, &train, &heldout, ACTION_PROPOSAL_SEEDS[0], 600);
        assert!(!candidates.is_empty());
        let mut by_block = std::collections::BTreeMap::new();
        for candidate in candidates {
            *by_block.entry(candidate.block_id).or_insert(0_usize) += 1;
        }
        assert!(by_block.values().all(|count| *count == 2));
        assert!(candidates_or_empty(&train, &heldout));
    }

    fn candidates_or_empty(
        train: &[Sample; TRAIN_SAMPLES],
        heldout: &[Sample; TRAIN_SAMPLES],
    ) -> bool {
        let model = Model::initial(INITIALIZATION_SEEDS[0]);
        let candidates = build_action_set(&model, train, heldout, ACTION_PROPOSAL_SEEDS[0], 600);
        candidates.iter().all(|action| {
            action.immediate_train_utility.is_finite()
                && action.immediate_heldout_utility.is_finite()
                && action.taylor_train_utility.is_finite()
                && action.projected_within_utility_variance >= -1.0e-10
        })
    }
}

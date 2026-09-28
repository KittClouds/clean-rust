use crate::frozen_protocol;
use crate::model::{
    ACTION_VALUES, BATCH_SIZE, LOWER_BOUND, Model, PARAMS, Sample, TRAIN_SAMPLES, UPPER_BOUND,
};

pub const DATASET_COUNT: usize = 5;
pub const INITIALIZATION_COUNT: usize = 5;
pub const CELL_COUNT: usize = DATASET_COUNT * INITIALIZATION_COUNT;
pub const STATE_STAGES: [usize; 3] = [600, 2_400, 4_200];
pub const STATE_COUNT: usize = CELL_COUNT * STATE_STAGES.len();
pub const PANEL_COUNT: usize = 4;
pub const PANEL_SIZE: usize = 128;
pub const PANEL_SIZES: [usize; 5] = [8, 16, 32, 64, 128];
pub const RUNTIME_STEPS: usize = 4_200;
pub const COMMITS_PER_EVIDENCE: usize = 4;
pub const ACTION_SPLIT_SALT: u64 = 0x4152_3033_4152_3153;
pub const TIE_EPSILON: f64 = 1.0e-7;

pub const TRAINING_SEEDS: [u64; DATASET_COUNT] = seed_series(0xa404_b101_0000_0000);
pub const MEASUREMENT_SEEDS: [u64; DATASET_COUNT] = seed_series(0xa404_b102_0000_0000);
pub const SENTINEL_DRAW_SEEDS: [u64; DATASET_COUNT * PANEL_COUNT * 2] =
    seed_series(0xa404_b103_0000_0000);
pub const SENTINEL_ORDER_SEEDS: [u64; DATASET_COUNT * PANEL_COUNT] =
    seed_series(0xa404_b104_0000_0000);
pub const INITIALIZATION_SEEDS: [u64; INITIALIZATION_COUNT] = seed_series(0xa404_b105_0000_0000);
pub const STATE_STREAM_SEEDS: [u64; CELL_COUNT] = seed_series(0xa404_b106_0000_0000);
pub const CANDIDATE_PROPOSAL_SEEDS: [u64; STATE_COUNT] = seed_series(0xa404_b107_0000_0000);

#[cfg(test)]
pub use crate::frozen_protocol::{DATASET_SEEDS, EVALUATION_SEEDS};

pub const SEED_NAMESPACES: [u32; 7] = [
    0xa404_b101,
    0xa404_b102,
    0xa404_b103,
    0xa404_b104,
    0xa404_b105,
    0xa404_b106,
    0xa404_b107,
];

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
pub struct Candidate {
    pub action_id: u16,
    pub block_id: u16,
    pub left_parameter: u16,
    pub right_parameter: u16,
    pub left_rank: u8,
    pub right_rank: u8,
    pub left_delta: f32,
    pub right_delta: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct FrozenState {
    pub state_id: usize,
    pub cell_id: usize,
    pub dataset_id: usize,
    pub initialization_id: usize,
    pub stage: usize,
    pub initialization_seed: u64,
    pub state_stream_seed: u64,
    pub proposal_seed: u64,
    pub model: Model,
    pub training_loss: f64,
    pub state_fingerprint: u64,
    pub candidate_fingerprint: u64,
}

#[derive(Clone, Copy, Debug)]
pub struct ReferenceScore {
    pub state_id: usize,
    pub action_id: u16,
    pub training_utility: f64,
    pub measurement_utility: f64,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum SentinelMethod {
    Exact,
    Taylor,
}

impl SentinelMethod {
    pub const fn name(self) -> &'static str {
        match self {
            Self::Exact => "sentinel_exact",
            Self::Taylor => "sentinel_taylor",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct SentinelScore {
    pub state_id: usize,
    pub cell_id: usize,
    pub dataset_id: usize,
    pub initialization_id: usize,
    pub stage: usize,
    pub action_id: u16,
    pub panel_id: u8,
    pub panel_seed: u64,
    pub sample_count: u16,
    pub method: SentinelMethod,
    pub utility: f64,
}

#[derive(Clone, Copy)]
struct SingletonAction {
    delta: f32,
    utility: f32,
}

#[derive(Clone, Copy)]
struct PairBlock {
    left: usize,
    right: usize,
    len: usize,
}

pub fn fresh_seeds_are_unique() -> bool {
    let mut seeds = Vec::with_capacity(
        TRAINING_SEEDS.len()
            + MEASUREMENT_SEEDS.len()
            + SENTINEL_DRAW_SEEDS.len()
            + SENTINEL_ORDER_SEEDS.len()
            + INITIALIZATION_SEEDS.len()
            + STATE_STREAM_SEEDS.len()
            + CANDIDATE_PROPOSAL_SEEDS.len(),
    );
    seeds.extend(TRAINING_SEEDS);
    seeds.extend(MEASUREMENT_SEEDS);
    seeds.extend(SENTINEL_DRAW_SEEDS);
    seeds.extend(SENTINEL_ORDER_SEEDS);
    seeds.extend(INITIALIZATION_SEEDS);
    seeds.extend(STATE_STREAM_SEEDS);
    seeds.extend(CANDIDATE_PROPOSAL_SEEDS);
    let unique: hashbrown::HashSet<_> = seeds.iter().copied().collect();
    seeds.len() == unique.len()
        && seeds
            .iter()
            .all(|seed| SEED_NAMESPACES.contains(&((seed >> 32) as u32)))
}

/// Builds candidate identities from training examples and P16 proposal evidence only.
/// The final measurement and sentinel panels are intentionally absent from this API.
pub fn build_candidates(
    model: &Model,
    train: &[Sample; TRAIN_SAMPLES],
    proposal_seed: u64,
    stage: usize,
) -> Vec<Candidate> {
    let proposal_indices = frozen_protocol::proposal_indices(proposal_seed, 0);
    let proposal: [Sample; BATCH_SIZE] =
        std::array::from_fn(|index| train[proposal_indices[index]]);
    let proposal_baseline = model.loss(&proposal);
    let mut candidates = Vec::with_capacity(PARAMS);

    for (block_id, block) in pair_blocks(stage % PARAMS).into_iter().enumerate() {
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
                candidates.push(Candidate {
                    action_id: candidates.len() as u16,
                    block_id: block_id as u16,
                    left_parameter: block.left as u16,
                    right_parameter: block.right as u16,
                    left_rank: left_rank as u8,
                    right_rank: right_rank as u8,
                    left_delta: left_action.delta,
                    right_delta: right_action.delta,
                });
            }
        }
    }
    candidates
}

pub fn candidate_fingerprint(candidates: &[Candidate]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for candidate in candidates {
        for value in [
            u64::from(candidate.action_id),
            u64::from(candidate.block_id),
            u64::from(candidate.left_parameter),
            u64::from(candidate.right_parameter),
            u64::from(candidate.left_delta.to_bits()),
            u64::from(candidate.right_delta.to_bits()),
        ] {
            hash = (hash ^ value).wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    hash
}

pub fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

pub fn sample_order(seed: u64) -> [usize; PANEL_SIZE] {
    let mut order = std::array::from_fn(|index| index);
    let mut state = seed;
    for index in (1..PANEL_SIZE).rev() {
        state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let random = mix64(state);
        order.swap(index, random as usize % (index + 1));
    }
    order
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
        if first != PARAMS && second != PARAMS {
            groups.push(PairBlock {
                left: first,
                right: second,
                len: 2,
            });
        } else {
            groups.push(PairBlock {
                left: first.min(second),
                right: first.min(second),
                len: 1,
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_role_seeds_are_unique_and_namespaced() {
        assert!(fresh_seeds_are_unique());
    }

    #[test]
    fn panel_prefix_order_is_a_permutation_and_size_nested() {
        let order = sample_order(0xa404_b104_0000_0001);
        let mut sorted = order;
        sorted.sort_unstable();
        assert_eq!(sorted, std::array::from_fn(|index| index));
        assert!(PANEL_SIZES.windows(2).all(|pair| pair[0] < pair[1]));
    }

    #[test]
    fn candidate_builder_uses_only_train_and_proposal_inputs() {
        let train = crate::model::generate_dataset(TRAINING_SEEDS[0]);
        let model = Model::initial(INITIALIZATION_SEEDS[0]);
        let candidates = build_candidates(&model, &train, CANDIDATE_PROPOSAL_SEEDS[0], 600);
        assert!(!candidates.is_empty());
        assert_eq!(candidates.len() % 2, 0);
        assert!(candidates.iter().all(|candidate| {
            usize::from(candidate.left_parameter) < PARAMS
                && usize::from(candidate.right_parameter) < PARAMS
                && candidate.left_parameter != candidate.right_parameter
                && candidate.left_delta.is_finite()
                && candidate.right_delta.is_finite()
        }));
        assert!(candidates.chunks_exact(2).all(|pair| {
            pair[0].block_id == pair[1].block_id
                && pair[0].left_parameter == pair[1].left_parameter
                && pair[0].right_parameter == pair[1].right_parameter
        }));
    }
}

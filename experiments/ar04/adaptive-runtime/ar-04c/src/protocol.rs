use crate::model::{BATCH_SIZE, Model, PARAMS, Sample, TRAIN_SAMPLES};

pub const DATASET_COUNT: usize = 5;
pub const INITIALIZATION_COUNT: usize = 5;
pub const CELL_COUNT: usize = DATASET_COUNT * INITIALIZATION_COUNT;
pub const RUNTIME_STEPS: usize = 4_200;
pub const COMMITS_PER_EVIDENCE: usize = 4;
pub const EVIDENCE_ROUNDS: usize = RUNTIME_STEPS / COMMITS_PER_EVIDENCE;
pub const PANEL_SIZE: usize = 128;
pub const CHECKPOINTS: [usize; 4] = [0, 600, 2_400, RUNTIME_STEPS];
pub const TIE_EPSILON: f64 = 1.0e-7;

const TRAINING_PREFIX: u64 = 0xa404_c101_0000_0000;
const MEASUREMENT_PREFIX: u64 = 0xa404_c102_0000_0000;
const INITIALIZATION_PREFIX: u64 = 0xa404_c103_0000_0000;
const STREAM_PREFIX: u64 = 0xa404_c104_0000_0000;
const FIXED_PANEL_PREFIX: u64 = 0xa404_c105_0000_0000;
const ROTATING_PANEL_PREFIX: u64 = 0xa404_c106_0000_0000;
const PANEL_ORDER_PREFIX: u64 = 0xa404_c107_0000_0000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Arm {
    TrainingFull96,
    SentinelFixed128,
    SentinelRotating128,
}

impl Arm {
    pub const ALL: [Self; 3] = [
        Self::TrainingFull96,
        Self::SentinelFixed128,
        Self::SentinelRotating128,
    ];

    pub const fn name(self) -> &'static str {
        match self {
            Self::TrainingFull96 => "training_full96",
            Self::SentinelFixed128 => "sentinel_fixed128",
            Self::SentinelRotating128 => "sentinel_rotating128",
        }
    }
}

pub const fn seed(prefix: u64, one_based_index: usize) -> u64 {
    prefix | one_based_index as u64
}

pub const fn training_seed(dataset_id: usize) -> u64 {
    seed(TRAINING_PREFIX, dataset_id + 1)
}

pub const fn measurement_seed(dataset_id: usize) -> u64 {
    seed(MEASUREMENT_PREFIX, dataset_id + 1)
}

pub const fn initialization_seed(initialization_id: usize) -> u64 {
    seed(INITIALIZATION_PREFIX, initialization_id + 1)
}

pub const fn stream_seed(cell_id: usize) -> u64 {
    seed(STREAM_PREFIX, cell_id + 1)
}

pub const fn fixed_draw_seed(cell_id: usize, draw_id: usize) -> u64 {
    seed(FIXED_PANEL_PREFIX, cell_id * 2 + draw_id + 1)
}

pub const fn rotating_draw_seed(cell_id: usize, round: usize, draw_id: usize) -> u64 {
    let panel_index = cell_id * EVIDENCE_ROUNDS + round;
    seed(ROTATING_PANEL_PREFIX, panel_index * 2 + draw_id + 1)
}

pub const fn fixed_order_seed(cell_id: usize) -> u64 {
    seed(PANEL_ORDER_PREFIX, cell_id + 1)
}

pub const fn rotating_order_seed(cell_id: usize, round: usize) -> u64 {
    let panel_index = cell_id * EVIDENCE_ROUNDS + round;
    seed(PANEL_ORDER_PREFIX, CELL_COUNT + panel_index + 1)
}

pub fn all_role_seeds() -> Vec<u64> {
    let mut seeds = Vec::with_capacity(
        DATASET_COUNT * 2
            + INITIALIZATION_COUNT
            + CELL_COUNT
            + CELL_COUNT * 2
            + CELL_COUNT * EVIDENCE_ROUNDS * 2
            + CELL_COUNT * (EVIDENCE_ROUNDS + 1),
    );
    for dataset_id in 0..DATASET_COUNT {
        seeds.push(training_seed(dataset_id));
        seeds.push(measurement_seed(dataset_id));
    }
    for initialization_id in 0..INITIALIZATION_COUNT {
        seeds.push(initialization_seed(initialization_id));
    }
    for cell_id in 0..CELL_COUNT {
        seeds.push(stream_seed(cell_id));
        seeds.push(fixed_order_seed(cell_id));
        seeds.push(fixed_draw_seed(cell_id, 0));
        seeds.push(fixed_draw_seed(cell_id, 1));
        for round in 0..EVIDENCE_ROUNDS {
            seeds.push(rotating_order_seed(cell_id, round));
            seeds.push(rotating_draw_seed(cell_id, round, 0));
            seeds.push(rotating_draw_seed(cell_id, round, 1));
        }
    }
    seeds
}

pub fn seeds_are_unique_and_namespaced() -> bool {
    let seeds = all_role_seeds();
    let unique: hashbrown::HashSet<_> = seeds.iter().copied().collect();
    seeds.len() == unique.len()
        && seeds
            .iter()
            .all(|value| (0xa404_c101..=0xa404_c107).contains(&(value >> 32)))
}

pub fn panel_from_seeds(seed_a: u64, seed_b: u64, order_seed: u64) -> [Sample; PANEL_SIZE] {
    let first = crate::model::generate_dataset(seed_a);
    let second = crate::model::generate_dataset(seed_b);
    let mut source = [first[0]; PANEL_SIZE];
    source[..64].copy_from_slice(&first[..64]);
    source[64..].copy_from_slice(&second[..64]);
    let order = sample_order(order_seed);
    std::array::from_fn(|index| source[order[index]])
}

pub fn rotating_panel(cell_id: usize, round: usize) -> [Sample; PANEL_SIZE] {
    panel_from_seeds(
        rotating_draw_seed(cell_id, round, 0),
        rotating_draw_seed(cell_id, round, 1),
        rotating_order_seed(cell_id, round),
    )
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

pub fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

pub fn sample_fingerprint(samples: &[Sample]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for sample in samples {
        for value in sample
            .x
            .into_iter()
            .chain(std::iter::once(sample.target as f32))
        {
            hash = (hash ^ u64::from(value.to_bits())).wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    hash
}

pub fn indices_fingerprint(indices: &[usize]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for &index in indices {
        hash = (hash ^ index as u64).wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

#[allow(dead_code)]
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

/// Diagnostic checkpoint candidate builder: the only data inputs are current
/// state, training data, and its frozen P16 proposal. It receives no verifier.
pub fn build_candidates(
    model: &Model,
    train: &[Sample; TRAIN_SAMPLES],
    proposal_indices: &[usize],
    stage: usize,
) -> Vec<Candidate> {
    assert_eq!(proposal_indices.len(), BATCH_SIZE);
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
        let all_legal = left_top
            .iter()
            .all(|action| (-2.0..=2.0).contains(&(model.parameters[block.left] + action.delta)))
            && right_top.iter().all(|action| {
                (-2.0..=2.0).contains(&(model.parameters[block.right] + action.delta))
            });
        if !all_legal {
            continue;
        }

        let pair_key =
            ((block.left.min(block.right) as u64) << 32) | block.left.max(block.right) as u64;
        let development_diagonal = mix64(pair_key ^ 0x4152_3033_4152_3153) & 1 == 0;
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
    for (index, &delta) in crate::model::ACTION_VALUES.iter().enumerate() {
        let value = model.parameters[parameter] + delta;
        if !(-2.0..=2.0).contains(&value) {
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::frozen_protocol;

    #[test]
    fn seed_roles_are_unique_and_panel_schedule_is_exact() {
        assert!(seeds_are_unique_and_namespaced());
        assert_eq!(EVIDENCE_ROUNDS, 1_050);
        assert_eq!(CELL_COUNT * EVIDENCE_ROUNDS, 26_250);
        assert_eq!(CELL_COUNT * EVIDENCE_ROUNDS * PANEL_SIZE, 3_360_000);
    }

    #[test]
    fn arm_verifier_sizes_match_the_frozen_contrast() {
        assert_eq!(TRAIN_SAMPLES, 96);
        assert_eq!(PANEL_SIZE, 128);
        assert_eq!(Arm::ALL.len(), 3);
    }

    #[test]
    fn checkpoint_candidate_builder_is_nonempty_and_pair_grouped() {
        let train = crate::model::generate_dataset(training_seed(0));
        let model = Model::initial(initialization_seed(0));
        let indices = frozen_protocol::proposal_indices(stream_seed(0), 0);
        let candidates = build_candidates(&model, &train, &indices, 0);
        assert!(!candidates.is_empty());
        assert!(candidates.chunks_exact(2).all(|pair| {
            pair[0].block_id == pair[1].block_id
                && pair[0].left_parameter == pair[1].left_parameter
                && pair[0].right_parameter == pair[1].right_parameter
        }));
    }
}

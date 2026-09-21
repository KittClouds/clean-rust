use crate::model::{
    ACTION_VALUES, BATCH_SIZE, LOWER_BOUND, Model, PARAMS, Sample, TRAIN_SAMPLES, UPPER_BOUND,
    VERIFIER_SIZE,
};

pub const CHECKPOINTS: [usize; 3] = [600, 2_400, 4_200];
pub const COMMITS_PER_EVIDENCE: usize = 4;
pub const ACTION_SCALE: f32 = 1.0;
pub const DATASET_SEEDS: [u64; 5] = seed_series(0xa303_d1da_0000_0000);
pub const INITIALIZATION_SEEDS: [u64; 5] = seed_series(0xa303_d1a7_0000_0000);
const PROPOSAL_STREAM: u64 = 0x5052_4f50_4f53_4131;
const VERIFY_STREAM: u64 = 0x4152_3033_4152_3156;
const ACTION_SPLIT_SALT: u64 = 0x4152_3033_4152_3153;
const STEP_MUL: u64 = 0x9e37_79b9;

pub const STREAMS_PER_ROLE_PER_CELL: usize = 2;
pub const DEVELOPMENT_SEEDS: [u64; 50] = seed_series(0xa303_d1de_0000_0000);
pub const EVALUATION_SEEDS: [u64; 50] = seed_series(0xa303_d1ea_0000_0000);

const fn seed_series<const N: usize>(prefix: u64) -> [u64; N] {
    let mut seeds = [0; N];
    let mut index = 0;
    while index < N {
        seeds[index] = prefix | (index as u64 + 1);
        index += 1;
    }
    seeds
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StreamRole {
    Development,
    Evaluation,
}

impl StreamRole {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Development => "development",
            Self::Evaluation => "evaluation",
        }
    }
}

#[derive(Clone, Debug)]
pub struct Candidate {
    pub block: usize,
    pub left_parameter: usize,
    pub right_parameter: usize,
    pub left_rank: u8,
    pub right_rank: u8,
    pub left_delta: f32,
    pub right_delta: f32,
    pub exact_utility: [f64; 1],
    pub per_example_utility: [Vec<f32>; 1],
}

#[derive(Clone, Debug)]
pub struct StateSnapshot {
    pub role: StreamRole,
    pub dataset_index: u8,
    pub dataset_seed: u64,
    pub initialization_index: u8,
    pub initialization_seed: u64,
    pub seed: u64,
    pub step: usize,
    pub model: Model,
    pub train_loss: f32,
    pub fingerprint: u64,
    pub development_candidates: Vec<Candidate>,
    pub evaluation_candidates: Vec<Candidate>,
    pub eligible_blocks: usize,
    pub bounds_skipped_blocks: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct Group {
    left: usize,
    right: usize,
    len: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct Action {
    delta: f32,
    utility: f32,
}

#[derive(Clone, Copy, Debug, Default)]
struct Program {
    left: usize,
    right: usize,
    deltas: [f32; 2],
    len: usize,
    utility: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RuntimeProgram {
    pub left: usize,
    pub right: usize,
    pub deltas: [f32; 2],
    pub len: usize,
    pub verifier_utility: f32,
}

#[derive(Clone, Copy, Debug)]
struct Rng {
    state: u64,
}

impl Rng {
    const fn new(state: u64) -> Self {
        Self { state }
    }

    fn next(&mut self) -> u64 {
        let mut value = self.state;
        value ^= value << 7;
        value ^= value >> 9;
        value ^= value << 8;
        self.state = value;
        value
    }
}

pub fn collect_states(
    train: &[Sample],
    dataset_index: u8,
    dataset_seed: u64,
    initialization_index: u8,
    initialization_seed: u64,
) -> Vec<StateSnapshot> {
    let first_seed =
        usize::from(dataset_index) * INITIALIZATION_SEEDS.len() + usize::from(initialization_index);
    let start = first_seed * STREAMS_PER_ROLE_PER_CELL;
    let mut states = Vec::with_capacity(12);
    for &seed in &DEVELOPMENT_SEEDS[start..start + STREAMS_PER_ROLE_PER_CELL] {
        states.extend(replay_seed(
            train,
            seed,
            StreamRole::Development,
            dataset_index,
            dataset_seed,
            initialization_index,
            initialization_seed,
        ));
    }
    for &seed in &EVALUATION_SEEDS[start..start + STREAMS_PER_ROLE_PER_CELL] {
        states.extend(replay_seed(
            train,
            seed,
            StreamRole::Evaluation,
            dataset_index,
            dataset_seed,
            initialization_index,
            initialization_seed,
        ));
    }
    states
}

pub fn replay_seed(
    train: &[Sample],
    seed: u64,
    role: StreamRole,
    dataset_index: u8,
    dataset_seed: u64,
    initialization_index: u8,
    initialization_seed: u64,
) -> Vec<StateSnapshot> {
    assert_eq!(train.len(), TRAIN_SAMPLES);
    let mut model = Model::initial(initialization_seed);
    let mut snapshots = Vec::with_capacity(CHECKPOINTS.len());
    for evidence_round in 0..CHECKPOINTS[2] / COMMITS_PER_EVIDENCE {
        let proposal_indices = batch_indices(seed, evidence_round, PROPOSAL_STREAM, BATCH_SIZE);
        let proposal: [Sample; BATCH_SIZE] =
            std::array::from_fn(|index| train[proposal_indices[index]]);
        let verifier_indices = batch_indices(seed, evidence_round, VERIFY_STREAM, VERIFIER_SIZE);
        let verifier: [Sample; VERIFIER_SIZE] =
            std::array::from_fn(|index| train[verifier_indices[index]]);

        for inner in 0..COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * COMMITS_PER_EVIDENCE + inner;
            let groups = partition(global_commit % PARAMS);
            if let Some(program) = select_program(&model, &proposal, &verifier, &groups) {
                commit(&mut model, program);
            }
            let step = global_commit + 1;
            if CHECKPOINTS.contains(&step) {
                let next_round = step / COMMITS_PER_EVIDENCE;
                let indices = batch_indices(seed, next_round, PROPOSAL_STREAM, BATCH_SIZE);
                let action_proposal: [Sample; BATCH_SIZE] =
                    std::array::from_fn(|index| train[indices[index]]);
                let (
                    development_candidates,
                    evaluation_candidates,
                    eligible_blocks,
                    bounds_skipped_blocks,
                ) = build_candidate_sets(&model, train, &action_proposal, step % PARAMS);
                snapshots.push(StateSnapshot {
                    role,
                    dataset_index,
                    dataset_seed,
                    initialization_index,
                    initialization_seed,
                    seed,
                    step,
                    train_loss: model.loss(train),
                    fingerprint: parameter_fingerprint(&model),
                    model,
                    development_candidates,
                    evaluation_candidates,
                    eligible_blocks,
                    bounds_skipped_blocks,
                });
            }
        }
    }
    assert_eq!(snapshots.len(), CHECKPOINTS.len());
    snapshots
}

fn build_candidate_sets(
    model: &Model,
    train: &[Sample],
    proposal: &[Sample],
    schedule_round: usize,
) -> (Vec<Candidate>, Vec<Candidate>, usize, usize) {
    let groups = partition(schedule_round);
    let baseline: [f32; TRAIN_SAMPLES] = std::array::from_fn(|index| model.loss_one(&train[index]));
    let proposal_baseline = model.loss(proposal);
    let mut development = Vec::with_capacity(PARAMS);
    let mut evaluation = Vec::with_capacity(PARAMS);
    let mut eligible_blocks = 0;
    let mut bounds_skipped_blocks = 0;

    for (block, group) in groups.iter().copied().enumerate() {
        if group.len != 2 {
            continue;
        }
        let left_actions = singleton_actions(model, proposal, proposal_baseline, group.left);
        let right_actions = singleton_actions(model, proposal, proposal_baseline, group.right);
        let left_top = ordered_top(&left_actions, 2);
        let right_top = ordered_top(&right_actions, 2);
        let left_by_rank = [left_top[0], left_top[1]];
        let right_by_rank = [right_top[0], right_top[1]];
        let all_legal = left_by_rank.iter().all(|&left_index| {
            (LOWER_BOUND..=UPPER_BOUND).contains(
                &(model.parameters[group.left] + ACTION_SCALE * ACTION_VALUES[left_index]),
            )
        }) && right_by_rank.iter().all(|&right_index| {
            (LOWER_BOUND..=UPPER_BOUND).contains(
                &(model.parameters[group.right] + ACTION_SCALE * ACTION_VALUES[right_index]),
            )
        });
        if !all_legal {
            bounds_skipped_blocks += 1;
            continue;
        }
        eligible_blocks += 1;
        let pair_key =
            ((group.left.min(group.right) as u64) << 32) | group.left.max(group.right) as u64;
        let development_diagonal = mix64(pair_key ^ ACTION_SPLIT_SALT) & 1 == 0;

        for (left_rank, &left_index) in left_by_rank.iter().enumerate() {
            for (right_rank, &right_index) in right_by_rank.iter().enumerate() {
                let left_delta = ACTION_VALUES[left_index];
                let right_delta = ACTION_VALUES[right_index];
                let mut utilities: [Vec<f32>; 1] =
                    std::array::from_fn(|_| Vec::with_capacity(TRAIN_SAMPLES));
                let mut exact_utility = [0.0; 1];
                let mut candidate_model = *model;
                candidate_model.parameters[group.left] += ACTION_SCALE * left_delta;
                candidate_model.parameters[group.right] += ACTION_SCALE * right_delta;
                for (sample_index, sample) in train.iter().enumerate() {
                    utilities[0].push(baseline[sample_index] - candidate_model.loss_one(sample));
                }
                exact_utility[0] =
                    f64::from(utilities[0].iter().sum::<f32>() / TRAIN_SAMPLES as f32);
                let candidate = Candidate {
                    block,
                    left_parameter: group.left,
                    right_parameter: group.right,
                    left_rank: left_rank as u8,
                    right_rank: right_rank as u8,
                    left_delta,
                    right_delta,
                    exact_utility,
                    per_example_utility: utilities,
                };
                let is_development = (left_rank == right_rank) == development_diagonal;
                if is_development {
                    development.push(candidate);
                } else {
                    evaluation.push(candidate);
                }
            }
        }
    }
    (
        development,
        evaluation,
        eligible_blocks,
        bounds_skipped_blocks,
    )
}

fn select_program(
    model: &Model,
    proposal: &[Sample],
    verifier: &[Sample],
    groups: &[Group],
) -> Option<Program> {
    select_program_counted(model, proposal, verifier, groups).0
}

fn select_program_counted(
    model: &Model,
    proposal: &[Sample],
    verifier: &[Sample],
    groups: &[Group],
) -> (Option<Program>, u16) {
    let proposal_baseline = model.loss(proposal);
    let verifier_baseline = model.loss(verifier);
    let mut selected: Option<Program> = None;
    let mut verifier_programs_evaluated = 0_u16;
    for &group in groups {
        let candidate = if group.len == 1 {
            let actions = singleton_actions(model, proposal, proposal_baseline, group.left);
            let mut best_action = Action::default();
            for action in actions {
                if action.utility > best_action.utility {
                    best_action = action;
                }
            }
            let utility = single_utility(
                model,
                verifier,
                verifier_baseline,
                group.left,
                best_action.delta,
            );
            if utility.is_finite() {
                verifier_programs_evaluated += 1;
            }
            (utility > 0.0).then_some(Program {
                left: group.left,
                right: group.right,
                deltas: [best_action.delta, 0.0],
                len: 1,
                utility,
            })
        } else {
            let left_actions = singleton_actions(model, proposal, proposal_baseline, group.left);
            let right_actions = singleton_actions(model, proposal, proposal_baseline, group.right);
            let left_top = ordered_top(&left_actions, 2);
            let right_top = ordered_top(&right_actions, 2);
            let mut best = Program {
                left: group.left,
                right: group.right,
                len: 2,
                ..Program::default()
            };
            for &left_index in &left_top[..2] {
                for &right_index in &right_top[..2] {
                    let left_delta = ACTION_VALUES[left_index];
                    let right_delta = ACTION_VALUES[right_index];
                    let utility = pair_utility(
                        model,
                        verifier,
                        verifier_baseline,
                        group,
                        left_delta,
                        right_delta,
                    );
                    if utility.is_finite() {
                        verifier_programs_evaluated += 1;
                    }
                    if utility > best.utility {
                        best = Program {
                            left: group.left,
                            right: group.right,
                            deltas: [left_delta, right_delta],
                            len: 2,
                            utility,
                        };
                    }
                }
            }
            (best.utility > 0.0).then_some(best)
        };
        if let Some(candidate) = candidate
            && selected.is_none_or(|current| candidate.utility > current.utility)
        {
            selected = Some(candidate);
        }
    }
    (selected, verifier_programs_evaluated)
}

pub fn select_runtime_program(
    model: &Model,
    proposal: &[Sample],
    verifier: &[Sample],
    schedule_offset: usize,
) -> (Option<RuntimeProgram>, u16) {
    let groups = partition(schedule_offset);
    let (selected, scored_programs) = select_program_counted(model, proposal, verifier, &groups);
    (
        selected.map(|program| RuntimeProgram {
            left: program.left,
            right: program.right,
            deltas: program.deltas,
            len: program.len,
            verifier_utility: program.utility,
        }),
        scored_programs,
    )
}

fn singleton_actions(
    model: &Model,
    batch: &[Sample],
    baseline: f32,
    parameter: usize,
) -> [Action; 7] {
    let mut actions = [Action::default(); 7];
    for (index, &delta) in ACTION_VALUES.iter().enumerate() {
        let value = model.parameters[parameter] + delta;
        if !(LOWER_BOUND..=UPPER_BOUND).contains(&value) {
            continue;
        }
        let mut candidate = *model;
        candidate.parameters[parameter] = value;
        actions[index] = Action {
            delta,
            utility: baseline - candidate.loss(batch),
        };
    }
    actions
}

fn ordered_top(actions: &[Action; 7], width: usize) -> [usize; 5] {
    let mut order = [0_usize; 7];
    for (index, slot) in order.iter_mut().enumerate() {
        *slot = index;
    }
    order.sort_by(|left, right| actions[*right].utility.total_cmp(&actions[*left].utility));
    let mut top = [0_usize; 5];
    for index in 0..5 {
        top[index] = order[index.min(width.saturating_sub(1))];
    }
    top
}

fn pair_utility(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    group: Group,
    left_delta: f32,
    right_delta: f32,
) -> f32 {
    let left = model.parameters[group.left] + left_delta;
    let right = model.parameters[group.right] + right_delta;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&left) || !(LOWER_BOUND..=UPPER_BOUND).contains(&right)
    {
        return f32::NEG_INFINITY;
    }
    let mut candidate = *model;
    candidate.parameters[group.left] = left;
    candidate.parameters[group.right] = right;
    baseline - candidate.loss(samples)
}

fn single_utility(
    model: &Model,
    samples: &[Sample],
    baseline: f32,
    parameter: usize,
    delta: f32,
) -> f32 {
    let value = model.parameters[parameter] + delta;
    if !(LOWER_BOUND..=UPPER_BOUND).contains(&value) {
        return f32::NEG_INFINITY;
    }
    let mut candidate = *model;
    candidate.parameters[parameter] = value;
    baseline - candidate.loss(samples)
}

fn commit(model: &mut Model, program: Program) {
    model.parameters[program.left] =
        (model.parameters[program.left] + program.deltas[0]).clamp(LOWER_BOUND, UPPER_BOUND);
    if program.len == 2 {
        model.parameters[program.right] =
            (model.parameters[program.right] + program.deltas[1]).clamp(LOWER_BOUND, UPPER_BOUND);
    }
}

pub fn commit_runtime_program(model: &mut Model, program: RuntimeProgram) {
    commit(
        model,
        Program {
            left: program.left,
            right: program.right,
            deltas: program.deltas,
            len: program.len,
            utility: program.verifier_utility,
        },
    );
}

fn partition(round: usize) -> Vec<Group> {
    let mut order = [PARAMS; PARAMS + 1];
    for (position, slot) in order.iter_mut().enumerate().skip(1) {
        *slot = (position - 1 + round) % PARAMS;
    }
    let mut groups = Vec::with_capacity(PARAMS / 2 + 1);
    for left in 0..=(PARAMS / 2) {
        let first = order[left];
        let second = order[PARAMS - left];
        if first == PARAMS {
            groups.push(Group {
                left: second,
                right: second,
                len: 1,
            });
        } else if second == PARAMS {
            groups.push(Group {
                left: first,
                right: first,
                len: 1,
            });
        } else {
            groups.push(Group {
                left: first,
                right: second,
                len: 2,
            });
        }
    }
    groups
}

fn batch_indices(seed: u64, round: usize, stream: u64, count: usize) -> Vec<usize> {
    let mut rng = Rng::new(seed ^ stream ^ (round as u64).wrapping_mul(STEP_MUL));
    (0..count)
        .map(|_| rng.next() as usize % TRAIN_SAMPLES)
        .collect()
}

fn parameter_fingerprint(model: &Model) -> u64 {
    model
        .parameters
        .iter()
        .enumerate()
        .fold(0xcbf2_9ce4_8422_2325_u64, |hash, (index, value)| {
            (hash ^ u64::from(value.to_bits()).wrapping_add(index as u64))
                .wrapping_mul(0x0000_0100_0000_01b3)
        })
}

pub fn proposal_indices(seed: u64, evidence_round: usize) -> Vec<usize> {
    batch_indices(seed, evidence_round, PROPOSAL_STREAM, BATCH_SIZE)
}

pub fn runtime_parameter_fingerprint(model: &Model) -> u64 {
    parameter_fingerprint(model)
}

fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pair_schedule_covers_every_coordinate_pair() {
        let mut seen = vec![vec![false; PARAMS]; PARAMS];
        for round in 0..PARAMS {
            for group in partition(round) {
                if group.len == 2 {
                    seen[group.left][group.right] = true;
                    seen[group.right][group.left] = true;
                }
            }
        }
        assert!((0..PARAMS).all(|left| (left + 1..PARAMS).all(|right| seen[left][right])));
    }

    #[test]
    fn stream_sampling_is_deterministic() {
        for stream in [PROPOSAL_STREAM, VERIFY_STREAM] {
            let first = batch_indices(DEVELOPMENT_SEEDS[0], 137, stream, VERIFIER_SIZE);
            let second = batch_indices(DEVELOPMENT_SEEDS[0], 137, stream, VERIFIER_SIZE);
            assert_eq!(first, second);
            assert_ne!(
                first,
                batch_indices(DEVELOPMENT_SEEDS[0], 138, stream, VERIFIER_SIZE)
            );
        }
    }

    #[test]
    fn candidate_action_split_is_balanced_and_scale_legal() {
        let train = crate::model::generate_dataset(DATASET_SEEDS[0]);
        let proposal: [Sample; BATCH_SIZE] =
            std::array::from_fn(|index| train[(index * 7) % TRAIN_SAMPLES]);
        let model = Model::initial(INITIALIZATION_SEEDS[0]);
        let (development, evaluation, eligible, skipped) =
            build_candidate_sets(&model, &train, &proposal, 0);
        assert!(eligible > 0);
        assert_eq!(eligible + skipped, PARAMS / 2);
        assert_eq!(development.len(), eligible * 2);
        assert_eq!(evaluation.len(), eligible * 2);

        let blocks: std::collections::BTreeSet<_> = development
            .iter()
            .map(|candidate| candidate.block)
            .chain(evaluation.iter().map(|candidate| candidate.block))
            .collect();
        for block in blocks {
            let development_block: Vec<_> = development
                .iter()
                .filter(|candidate| candidate.block == block)
                .collect();
            let evaluation_block: Vec<_> = evaluation
                .iter()
                .filter(|candidate| candidate.block == block)
                .collect();
            assert_eq!(development_block.len(), 2);
            assert_eq!(evaluation_block.len(), 2);
            for candidates in [&development_block, &evaluation_block] {
                assert_eq!(
                    candidates
                        .iter()
                        .map(|candidate| candidate.left_rank)
                        .collect::<std::collections::BTreeSet<_>>()
                        .len(),
                    2
                );
                assert_eq!(
                    candidates
                        .iter()
                        .map(|candidate| candidate.right_rank)
                        .collect::<std::collections::BTreeSet<_>>()
                        .len(),
                    2
                );
                for candidate in candidates.iter().copied() {
                    assert!(
                        candidate
                            .exact_utility
                            .iter()
                            .all(|value| value.is_finite())
                    );
                    assert!(
                        candidate
                            .per_example_utility
                            .iter()
                            .all(|values| values.len() == TRAIN_SAMPLES)
                    );
                }
            }
        }
    }
}

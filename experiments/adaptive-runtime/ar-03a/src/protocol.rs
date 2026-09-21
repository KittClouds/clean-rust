use adaptive_runtime_ar_02a_r2::{
    ACTION_VALUES, BATCH_SIZE, LOWER_BOUND, Model, PARAMS, Sample, TRAIN_SAMPLES, UPPER_BOUND,
};

pub const CHECKPOINTS: [usize; 3] = [600, 2_400, 4_200];
pub const COMMITS_PER_EVIDENCE: usize = 4;
pub const VERIFIER_SIZE: usize = 48;
pub const PROPOSAL_STREAM: u64 = 0x5052_4f50_4f53_414c;
pub const VERIFY_STREAM: u64 = 0x4152_3032_5645_5249;
const ACTION_SPLIT_SALT: u64 = 0x4130_3341_5350_4c54;
const STEP_MUL: u64 = 0x9e37_79b9;

pub const DEVELOPMENT_SEEDS: [u64; 6] = [
    0x8a6d_39c1_7f02_b4e5,
    0x31f0_c72b_a845_196d,
    0xe5b4_087a_61c3_9f20,
    0x7d29_a6f3_04b1_ce58,
    0xb062_5e91_d83f_47ac,
    0x4c17_8bfa_2d60_e935,
];

pub const EVALUATION_SEEDS: [u64; 6] = [
    0x96e1_04bd_3c72_a85f,
    0x205a_d7c3_918e_64fb,
    0xd43c_6a10_7e95_b281,
    0x5e8f_13a2_c649_70bd,
    0xa17c_2d48_f036_95e2,
    0x3bc9_704e_a251_d68f,
];

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

#[derive(Clone, Copy, Debug)]
pub struct Candidate {
    pub block: usize,
    pub left_parameter: usize,
    pub right_parameter: usize,
    pub left_rank: u8,
    pub right_rank: u8,
    pub left_delta: f32,
    pub right_delta: f32,
    pub exact_utility: f64,
    pub per_example_utility: [f32; TRAIN_SAMPLES],
}

#[derive(Clone, Debug)]
pub struct StateSnapshot {
    pub role: StreamRole,
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

#[derive(Clone, Copy, Debug)]
struct Rng {
    state: u64,
}

impl Rng {
    const fn new(seed: u64) -> Self {
        Self { state: seed }
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

pub fn collect_states(train: &[Sample]) -> Vec<StateSnapshot> {
    let mut states = Vec::with_capacity(18);
    for seed in DEVELOPMENT_SEEDS {
        states
            .extend(replay_seed(train, seed, StreamRole::Development).expect("development replay"));
    }
    for seed in EVALUATION_SEEDS {
        states.extend(replay_seed(train, seed, StreamRole::Evaluation).expect("evaluation replay"));
    }
    states
}

pub fn replay_seed(
    train: &[Sample],
    seed: u64,
    role: StreamRole,
) -> Result<Vec<StateSnapshot>, &'static str> {
    if train.len() != TRAIN_SAMPLES {
        return Err("AR-03A requires exactly the 96 training examples");
    }
    let mut model = Model::initial();
    let mut snapshots = Vec::with_capacity(CHECKPOINTS.len());
    let final_step = CHECKPOINTS[CHECKPOINTS.len() - 1];
    for evidence_round in 0..final_step / COMMITS_PER_EVIDENCE {
        let proposal_indices = batch_indices(seed, evidence_round, PROPOSAL_STREAM, BATCH_SIZE);
        let proposal: [Sample; BATCH_SIZE] =
            std::array::from_fn(|index| train[proposal_indices[index]]);
        let verifier_indices = batch_indices(seed, evidence_round, VERIFY_STREAM, VERIFIER_SIZE);
        let verifier: [Sample; VERIFIER_SIZE] =
            std::array::from_fn(|index| train[verifier_indices[index]]);

        for inner in 0..COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * COMMITS_PER_EVIDENCE + inner;
            let groups = partition(global_commit % PARAMS);
            let program = select_program(&model, &proposal, &verifier, &groups);
            if let Some(program) = program {
                commit(&mut model, program);
            }
            let step = global_commit + 1;
            if CHECKPOINTS.contains(&step) {
                let next_round = step / COMMITS_PER_EVIDENCE;
                let action_proposal_indices =
                    batch_indices(seed, next_round, PROPOSAL_STREAM, BATCH_SIZE);
                let action_proposal: [Sample; BATCH_SIZE] =
                    std::array::from_fn(|index| train[action_proposal_indices[index]]);
                let (
                    development_candidates,
                    evaluation_candidates,
                    eligible_blocks,
                    bounds_skipped_blocks,
                ) = build_candidate_sets(&model, train, &action_proposal, step % PARAMS);
                snapshots.push(StateSnapshot {
                    role,
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
    if snapshots.len() != CHECKPOINTS.len() {
        return Err("did not reach all frozen checkpoints");
    }
    Ok(snapshots)
}

#[cfg(test)]
pub fn build_candidate_universe(
    model: &Model,
    train: &[Sample],
    proposal: &[Sample],
    step: usize,
) -> StateSnapshot {
    let (development_candidates, evaluation_candidates, eligible_blocks, bounds_skipped_blocks) =
        build_candidate_sets(model, train, proposal, step % PARAMS);
    StateSnapshot {
        role: StreamRole::Development,
        seed: 0,
        step,
        model: *model,
        train_loss: model.loss(train),
        fingerprint: parameter_fingerprint(model),
        development_candidates,
        evaluation_candidates,
        eligible_blocks,
        bounds_skipped_blocks,
    }
}

fn build_candidate_sets(
    model: &Model,
    train: &[Sample],
    proposal: &[Sample],
    schedule_round: usize,
) -> (Vec<Candidate>, Vec<Candidate>, usize, usize) {
    let groups = partition(schedule_round);
    let baseline: [f32; TRAIN_SAMPLES] =
        std::array::from_fn(|index| sample_loss(model, train[index]));
    let proposal_baseline = model.loss(proposal);
    let mut development = Vec::with_capacity(128);
    let mut evaluation = Vec::with_capacity(128);
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
        let combos: [[usize; 2]; 4] = [
            [left_top[0], right_top[0]],
            [left_top[0], right_top[1]],
            [left_top[1], right_top[0]],
            [left_top[1], right_top[1]],
        ];
        let all_legal = combos.iter().all(|&[left_index, right_index]| {
            (LOWER_BOUND..=UPPER_BOUND)
                .contains(&(model.parameters[group.left] + ACTION_VALUES[left_index]))
                && (LOWER_BOUND..=UPPER_BOUND)
                    .contains(&(model.parameters[group.right] + ACTION_VALUES[right_index]))
        });
        if !all_legal {
            bounds_skipped_blocks += 1;
            continue;
        }
        eligible_blocks += 1;
        let canonical_left = group.left.min(group.right);
        let canonical_right = group.left.max(group.right);
        let pair_key = ((canonical_left as u64) << 32) | canonical_right as u64;
        let development_diagonal = mix64(pair_key ^ ACTION_SPLIT_SALT) & 1 == 0;
        let left_rank_by_index = [left_top[0], left_top[1]];
        let right_rank_by_index = [right_top[0], right_top[1]];

        for (left_rank, &left_action_index) in left_rank_by_index.iter().enumerate() {
            for (right_rank, &right_action_index) in right_rank_by_index.iter().enumerate() {
                let left_delta = ACTION_VALUES[left_action_index];
                let right_delta = ACTION_VALUES[right_action_index];
                let mut candidate_model = *model;
                candidate_model.parameters[group.left] += left_delta;
                candidate_model.parameters[group.right] += right_delta;
                let per_example_utility: [f32; TRAIN_SAMPLES] = std::array::from_fn(|index| {
                    baseline[index] - sample_loss(&candidate_model, train[index])
                });
                let exact_utility =
                    f64::from(per_example_utility.iter().sum::<f32>() / TRAIN_SAMPLES as f32);
                let is_development = (left_rank == right_rank) == development_diagonal;
                let candidate = Candidate {
                    block,
                    left_parameter: group.left,
                    right_parameter: group.right,
                    left_rank: left_rank as u8,
                    right_rank: right_rank as u8,
                    left_delta,
                    right_delta,
                    exact_utility,
                    per_example_utility,
                };
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
    let proposal_baseline = model.loss(proposal);
    let verifier_baseline = model.loss(verifier);
    let mut selected: Option<Program> = None;
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
    selected
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

fn partition(round: usize) -> Vec<Group> {
    let mut order = [0_usize; PARAMS + 1];
    order[0] = PARAMS;
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

fn batch_indices(seed: u64, step: usize, stream: u64, count: usize) -> Vec<usize> {
    let mut rng = Rng::new(seed ^ stream ^ (step as u64).wrapping_mul(STEP_MUL));
    (0..count)
        .map(|_| rng.next() as usize % TRAIN_SAMPLES)
        .collect()
}

fn sample_loss(model: &Model, sample: Sample) -> f32 {
    model.loss(std::slice::from_ref(&sample))
}

pub fn parameter_fingerprint(model: &Model) -> u64 {
    model
        .parameters
        .iter()
        .enumerate()
        .fold(0xcbf2_9ce4_8422_2325_u64, |hash, (index, value)| {
            (hash ^ u64::from(value.to_bits()).wrapping_add(index as u64))
                .wrapping_mul(0x0000_0100_0000_01b3)
        })
}

fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

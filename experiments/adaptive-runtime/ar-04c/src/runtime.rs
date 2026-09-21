use crate::frozen_protocol;
use crate::model::{Model, Sample, TRAIN_SAMPLES};
use crate::protocol::{self, Arm};

#[derive(Clone, Copy, Debug)]
pub struct Decision {
    pub cell_id: usize,
    pub arm: Arm,
    pub step: usize,
    pub evidence_round: usize,
    pub panel_hash: u64,
    pub verifier_size: usize,
    pub proposal_hash: u64,
    pub schedule_offset: usize,
    pub selected: bool,
    pub left_parameter: usize,
    pub right_parameter: usize,
    pub left_delta: f32,
    pub right_delta: f32,
    pub program_len: usize,
    pub verifier_utility: f32,
    pub training_utility: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct Checkpoint {
    pub cell_id: usize,
    pub arm: Arm,
    pub step: usize,
    pub model: Model,
    pub train_loss: f32,
}

#[derive(Debug)]
pub struct Trajectory {
    pub decisions: Vec<Decision>,
    pub checkpoints: Vec<Checkpoint>,
}

pub fn run_arm(
    cell_id: usize,
    train: &[Sample; TRAIN_SAMPLES],
    initialization_seed: u64,
    stream_seed: u64,
    arm: Arm,
    fixed_panel: &[Sample; protocol::PANEL_SIZE],
) -> Trajectory {
    let mut model = Model::initial(initialization_seed);
    let mut decisions = Vec::with_capacity(protocol::RUNTIME_STEPS);
    let mut checkpoints = Vec::with_capacity(protocol::CHECKPOINTS.len());
    push_checkpoint(&mut checkpoints, cell_id, arm, 0, &model, train);

    for evidence_round in 0..protocol::EVIDENCE_ROUNDS {
        let proposal_indices = frozen_protocol::proposal_indices(stream_seed, evidence_round);
        let proposal: [Sample; crate::model::BATCH_SIZE] =
            std::array::from_fn(|index| train[proposal_indices[index]]);
        let rotating_panel = (arm == Arm::SentinelRotating128)
            .then(|| protocol::rotating_panel(cell_id, evidence_round));
        let (verifier, panel_hash, verifier_size) = match arm {
            Arm::TrainingFull96 => (
                train.as_slice(),
                protocol::sample_fingerprint(train),
                TRAIN_SAMPLES,
            ),
            Arm::SentinelFixed128 => (
                fixed_panel.as_slice(),
                protocol::sample_fingerprint(fixed_panel),
                protocol::PANEL_SIZE,
            ),
            Arm::SentinelRotating128 => {
                let panel = rotating_panel
                    .as_ref()
                    .expect("rotating arm creates a rotating panel");
                (
                    panel.as_slice(),
                    protocol::sample_fingerprint(panel),
                    protocol::PANEL_SIZE,
                )
            }
        };
        let proposal_hash = protocol::indices_fingerprint(&proposal_indices);

        for inner in 0..protocol::COMMITS_PER_EVIDENCE {
            let step = evidence_round * protocol::COMMITS_PER_EVIDENCE + inner + 1;
            let (selected, _) = frozen_protocol::select_runtime_program(
                &model,
                &proposal,
                verifier,
                (step - 1) % crate::model::PARAMS,
            );
            let (selected, training_utility) = selected.map_or((None, 0.0), |program| {
                let utility = exact_program_utility(&model, train, &program);
                (Some(program), utility)
            });
            let decision = selected.map_or(
                Decision {
                    cell_id,
                    arm,
                    step,
                    evidence_round,
                    panel_hash,
                    verifier_size,
                    proposal_hash,
                    schedule_offset: (step - 1) % crate::model::PARAMS,
                    selected: false,
                    left_parameter: usize::MAX,
                    right_parameter: usize::MAX,
                    left_delta: 0.0,
                    right_delta: 0.0,
                    program_len: 0,
                    verifier_utility: 0.0,
                    training_utility: 0.0,
                },
                |program| Decision {
                    cell_id,
                    arm,
                    step,
                    evidence_round,
                    panel_hash,
                    verifier_size,
                    proposal_hash,
                    schedule_offset: (step - 1) % crate::model::PARAMS,
                    selected: true,
                    left_parameter: program.left,
                    right_parameter: program.right,
                    left_delta: program.deltas[0],
                    right_delta: program.deltas[1],
                    program_len: program.len,
                    verifier_utility: program.verifier_utility,
                    training_utility,
                },
            );
            decisions.push(decision);
            if let Some(program) = selected {
                frozen_protocol::commit_runtime_program(&mut model, program);
            }
            if protocol::CHECKPOINTS.contains(&step) {
                push_checkpoint(&mut checkpoints, cell_id, arm, step, &model, train);
            }
        }
    }
    assert_eq!(decisions.len(), protocol::RUNTIME_STEPS);
    assert_eq!(checkpoints.len(), protocol::CHECKPOINTS.len());
    Trajectory {
        decisions,
        checkpoints,
    }
}

fn exact_program_utility(
    model: &Model,
    samples: &[Sample],
    program: &frozen_protocol::RuntimeProgram,
) -> f32 {
    let baseline = model.loss(samples);
    let mut candidate = *model;
    candidate.parameters[program.left] += program.deltas[0];
    if program.len == 2 {
        candidate.parameters[program.right] += program.deltas[1];
    }
    baseline - candidate.loss(samples)
}

fn push_checkpoint(
    checkpoints: &mut Vec<Checkpoint>,
    cell_id: usize,
    arm: Arm,
    step: usize,
    model: &Model,
    train: &[Sample],
) {
    checkpoints.push(Checkpoint {
        cell_id,
        arm,
        step,
        model: *model,
        train_loss: model.loss(train),
    });
}

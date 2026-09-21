use crate::frozen_protocol;
use crate::model::{self, Model, Sample, TRAIN_SAMPLES};
use crate::partition;
use crate::protocol::{COMMITS_PER_EVIDENCE, RUNTIME_STEPS, STATE_STAGES};
use crate::runtime_partition;

/// Captures the frozen AR-04A hash-control trajectory using training data only.
pub fn capture_hash_reference_states(
    train: &[Sample; TRAIN_SAMPLES],
    initialization_seed: u64,
    stream_seed: u64,
    hash_partition_id: u8,
) -> [Model; 3] {
    let partition_ids = partition::hash_placebo(hash_partition_id);
    let mut learner = Model::initial(initialization_seed);
    let mut snapshots = Vec::with_capacity(STATE_STAGES.len());
    let mut proposal = [train[0]; model::BATCH_SIZE];
    let mut verifier = [train[0]; model::VERIFIER_SIZE];
    let mut active_round = usize::MAX;

    for global_commit in 0..RUNTIME_STEPS {
        let evidence_round = global_commit / COMMITS_PER_EVIDENCE;
        if active_round != evidence_round {
            let proposal_indices = frozen_protocol::proposal_indices(stream_seed, evidence_round);
            proposal = std::array::from_fn(|index| train[proposal_indices[index]]);
            let panel_indices =
                runtime_partition::sample_panel(&partition_ids, stream_seed, evidence_round);
            verifier = std::array::from_fn(|index| train[panel_indices[index]]);
            active_round = evidence_round;
        }
        let (program, _) = frozen_protocol::select_runtime_program(
            &learner,
            &proposal,
            &verifier,
            global_commit % model::PARAMS,
        );
        if let Some(program) = program {
            frozen_protocol::commit_runtime_program(&mut learner, program);
        }
        let step = global_commit + 1;
        if STATE_STAGES.contains(&step) {
            snapshots.push(learner);
        }
    }
    snapshots
        .try_into()
        .expect("all three frozen state stages must be captured exactly once")
}

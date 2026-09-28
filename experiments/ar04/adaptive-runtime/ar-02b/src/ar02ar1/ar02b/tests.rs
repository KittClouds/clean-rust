use super::*;

#[test]
fn cell_weighted_replay_matches_r1_checkpoint() {
    let dataset = generate_gaussian_cells();
    let train = &dataset.samples[..TRAIN_SAMPLES];
    let (classes, cells, margins) = verifier_indices(train);
    let snapshots = replay_cell_trajectory(train, R1_SEEDS[0], &classes, &cells, &margins);
    assert_eq!(snapshots[0].step, 600);
    assert!((snapshots[0].model.loss(train) - 0.898_978_05).abs() < 1.0e-7);
}

#[test]
fn checked_replay_does_not_clamp_an_illegal_action() {
    let mut model = Model::initial();
    let before = model;
    let program = Program {
        left: 0,
        right: 1,
        deltas: [UPPER_BOUND * 2.0, 0.0],
        len: 2,
        utility: 0.0,
    };
    assert!(apply_checked(&mut model, program).is_err());
    assert_eq!(model.parameters, before.parameters);
}

#[test]
fn frozen_common_path_preserves_distance_and_mixed_sum_identity() {
    let dataset = generate_gaussian_cells();
    let train = &dataset.samples[..TRAIN_SAMPLES];
    let base = Model::initial();
    let selected = Program {
        left: 0,
        right: 1,
        deltas: [0.02, -0.01],
        len: 2,
        utility: 0.0,
    };
    let control = Program {
        left: 0,
        right: 1,
        deltas: [0.01, -0.01],
        len: 2,
        utility: 0.0,
    };
    let common = Program {
        left: 2,
        right: 3,
        deltas: [-0.005, 0.01],
        len: 2,
        utility: 0.0,
    };
    let path = FrozenPath {
        programs: vec![Some(common)],
        invalid_source_step: 0,
    };
    let replay = replay_path(base, selected, control, &path, train);
    assert_eq!(replay.replayed_commits, 1);
    assert_eq!(replay.invalid_step, 0);
    assert!(replay.telescoping_residual.abs() < LOSS_TOLERANCE);
    assert!(replay.max_distance_drift < 1.0e-6);
    assert!(replay.points[1].is_some());
}

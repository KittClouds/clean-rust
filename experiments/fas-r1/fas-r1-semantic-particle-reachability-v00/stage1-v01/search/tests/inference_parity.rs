use r1_stage1_search::{
    Edit, FrozenProposalValueV01, SemanticFeatures, PROPOSAL_V01_SHA256, V_REACH_V01_SHA256,
};
use r1_world::InferenceTask;

fn fixture() -> (InferenceTask, SemanticFeatures) {
    let task = InferenceTask {
        id: "parity-task".to_owned(),
        family_id: "parity-family".to_owned(),
        n: 3,
        k: 2,
        role_anonymous: false,
        global_text: String::new(),
        clauses: vec!["c0".into(), "c1".into(), "c2".into()],
        entity_mentions: vec![vec![0, 1], vec![1, 2], vec![0, 2]],
        role_mentions: vec![vec![0], vec![1], vec![0, 1]],
    };
    let global = (0..2048)
        .map(|index| (((index * 7) % 101) - 50) as f32 / 1024.0)
        .collect::<Vec<_>>()
        .into_boxed_slice();
    let clauses = (0..3)
        .flat_map(|clause| {
            (0..2048).map(move |index| (((clause + 1) * (index % 29)) - 14) as f32 / 2048.0)
        })
        .collect::<Vec<_>>()
        .into_boxed_slice();
    let features = SemanticFeatures::from_projection(&task, 2048, clauses, global).unwrap();
    (task, features)
}

fn assert_close(actual: f32, expected: f32, tolerance: f32) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "actual={actual:.9}, expected={expected:.9}, delta={:.9}",
        (actual - expected).abs()
    );
}

#[test]
fn pinned_v01_heads_match_python_cpu_reference_vectors() {
    let (task, features) = fixture();
    let mut heads = FrozenProposalValueV01::load_default().unwrap();
    assert_eq!(heads.proposal_sha256(), PROPOSAL_V01_SHA256);
    assert_eq!(heads.value_sha256(), V_REACH_V01_SHA256);
    heads.prepare_task(&task, &features).unwrap();
    assert_eq!(heads.cache_len(), 1);

    // Python feature_math.candidate_features(task, [0,1,0]) emits edits in
    // entity-major, role-major order: (0,1), (1,0), (2,1).
    let assignment = [0, 1, 0];
    let edits = [
        Edit {
            entity: 0,
            new_role: 1,
        },
        Edit {
            entity: 1,
            new_role: 0,
        },
        Edit {
            entity: 2,
            new_role: 1,
        },
    ];
    let logits = heads
        .score_edits(&task, &features, &assignment, &edits)
        .unwrap();
    assert_eq!(logits.len(), 3);
    assert_close(logits[0], 11.119_778, 2e-4);
    assert_close(logits[1], 10.096_948, 2e-4);
    assert_close(logits[2], 13.807_789, 2e-4);
    assert_eq!(heads.cache_len(), 1);

    let latent = (0..128)
        .map(|index| (((index * 13) % 31) - 15) as f32 / 128.0)
        .collect::<Vec<_>>();
    let probability = heads
        .v_reach(&task, &features, &assignment, &latent, 13)
        .unwrap();
    assert_close(probability, 0.496_853_95, 3e-5);
}

#[test]
fn v01_dimension_and_assignment_checks_fail_closed() {
    let (task, features) = fixture();
    let mut heads = FrozenProposalValueV01::load_default().unwrap();
    let assignment = [0, 1, 0];
    let latent = vec![0.0; 127];
    assert!(heads
        .v_reach(&task, &features, &assignment, &latent, 1)
        .is_err());
    assert!(heads
        .score_edits(
            &task,
            &features,
            &assignment,
            &[Edit {
                entity: 0,
                new_role: 0,
            }]
        )
        .is_err());
}

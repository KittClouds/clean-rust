pub use r1_stage1_search::{Edit, SemanticFeatures};

#[path = "../src/inference_v02.rs"]
#[allow(dead_code)]
mod inference_v02;

use inference_v02::{
    FrozenProposalValueV02, ProposalMixV03, PROPOSAL_V02_SHA256, V_REACH_V02_64_SHA256,
    V_REACH_V03_SCALED_H_SHA256, V_REACH_V05_STRESS_SHA256, V_REACH_V06_STRESS_SHA256,
};
use r1_world::InferenceTask;
use sha2::{Digest, Sha256};
use std::sync::atomic::{AtomicU64, Ordering};

static TEMP_DIR_SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn fixture() -> (InferenceTask, SemanticFeatures) {
    let task = InferenceTask {
        id: "parity-task-v02".to_owned(),
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

#[test]
fn explicit_v04_head_loader_checks_both_supplied_hashes_and_v02_schemas() {
    let temp_dir = std::env::temp_dir().join(format!(
        "r1-v04-head-loader-{}-{}",
        std::process::id(),
        TEMP_DIR_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    std::fs::create_dir(&temp_dir).unwrap();

    let proposal = serde_json::json!({
        "schema": "r1-proposal-weights-v02",
        "architecture": "tanh_mlp_base_f10_h16_plus_adapter_bias_v02",
        "input_dim": 10,
        "hidden_dim": 16,
        "static_feature_dim": 8,
        "feature_schema": "r1-candidate-features-h-global-entity-role-load-v01-plus-semantic-adapter-expected-delta-v02",
        "adapter_logit_bias": 0.5,
        "w1": vec![vec![0.0f32; 10]; 16],
        "b1": vec![0.0f32; 16],
        "w2": vec![0.0f32; 16],
        "b2": 0.0f32
    });
    let value = serde_json::json!({
        "schema": "r1-v-reach-weights-v02",
        "architecture": "tanh_mlp_value_4345_h32_v02",
        "input_dim": 4345,
        "hidden_dim": 32,
        "budget_normalization_max": 64,
        "feature_schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v01",
        "w1": vec![vec![0.0f32; 4345]; 32],
        "b1": vec![0.0f32; 32],
        "w2": vec![0.0f32; 32],
        "b2": 0.0f32
    });
    let proposal_bytes = serde_json::to_vec(&proposal).unwrap();
    let value_bytes = serde_json::to_vec(&value).unwrap();
    let proposal_path = temp_dir.join("proposal-weights-v04.json");
    let value_path = temp_dir.join("v-reach-weights-v04.json");
    std::fs::write(&proposal_path, &proposal_bytes).unwrap();
    std::fs::write(&value_path, &value_bytes).unwrap();
    let proposal_sha = format!("{:x}", Sha256::digest(&proposal_bytes));
    let value_sha = format!("{:x}", Sha256::digest(&value_bytes));

    let heads = FrozenProposalValueV02::load_explicit_heads(
        &proposal_path,
        &proposal_sha,
        &value_path,
        &value_sha,
    )
    .unwrap();
    assert_eq!(heads.proposal_sha256(), proposal_sha);
    assert_eq!(heads.value_sha256(), value_sha);
    assert_eq!(heads.value_budget_max(), 64);
    assert!((heads.adapter_logit_bias() - 0.5).abs() < f32::EPSILON);

    let bad_hash = "0".repeat(64);
    assert!(FrozenProposalValueV02::load_explicit_heads(
        &proposal_path,
        &bad_hash,
        &value_path,
        &value_sha,
    )
    .is_err());
    std::fs::remove_dir_all(temp_dir).unwrap();
}

#[test]
fn stress_v05_uses_a_256_step_value_horizon() {
    let (task, features) = fixture();
    let mut heads = FrozenProposalValueV02::load_default_v05().unwrap();
    assert_eq!(heads.value_sha256(), V_REACH_V05_STRESS_SHA256);
    assert_eq!(heads.value_budget_max(), 256);
    heads.prepare_task(&task, &features).unwrap();
    let assignment = [0, 1, 0];
    let latent = vec![0.0; 128];
    let at_horizon = heads
        .v_reach(&task, &features, &assignment, &latent, 256)
        .unwrap();
    let beyond_horizon = heads
        .v_reach(&task, &features, &assignment, &latent, 512)
        .unwrap();
    assert_eq!(at_horizon, beyond_horizon);
    assert!((0.0..=1.0).contains(&at_horizon));
}

#[test]
fn stress_v06_neighborhood_checkpoint_is_hash_pinned_and_uses_256_steps() {
    let (task, features) = fixture();
    let mut heads = FrozenProposalValueV02::load_default_v06().unwrap();
    assert_eq!(heads.value_sha256(), V_REACH_V06_STRESS_SHA256);
    assert_eq!(heads.value_budget_max(), 256);
    heads.prepare_task(&task, &features).unwrap();
    let assignment = [0, 1, 0];
    let latent = vec![0.0; 128];
    let at_horizon = heads
        .v_reach(&task, &features, &assignment, &latent, 256)
        .unwrap();
    let beyond_horizon = heads
        .v_reach(&task, &features, &assignment, &latent, 512)
        .unwrap();
    assert_eq!(at_horizon, beyond_horizon);
    assert!((0.0..=1.0).contains(&at_horizon));
}

#[test]
fn scaled_v03_checkpoint_remains_pinned_to_its_64_step_horizon() {
    let heads = FrozenProposalValueV02::load_default_v03().unwrap();
    assert_eq!(heads.value_sha256(), V_REACH_V03_SCALED_H_SHA256);
    assert_eq!(heads.value_budget_max(), 64);
}

#[test]
fn v07_vreach_is_hash_pinned_proposal_bound_and_matches_python_reference() {
    const PROPOSAL_PATH: &str = r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v84-v04-proposal-v01\proposal-weights-v04.json";
    const PROPOSAL_SHA256: &str =
        "3ce84b1e4f44f7713c80999223d5638b8ada0eeffea00a06f787de9dc0616f33";
    const VALUE_PATH: &str = r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v89-v04-vreach-fit-v01\v-reach-weights-v07.json";
    const VALUE_SHA256: &str = "aa11fca9bea2556600974da1c68cd15fe1a32a30e88ade8e69691c8287910170";

    let mut heads = FrozenProposalValueV02::load_explicit_heads(
        PROPOSAL_PATH,
        PROPOSAL_SHA256,
        VALUE_PATH,
        VALUE_SHA256,
    )
    .unwrap();
    assert_eq!(heads.proposal_sha256(), PROPOSAL_SHA256);
    assert_eq!(heads.value_sha256(), VALUE_SHA256);
    assert_eq!(heads.value_budget_max(), 256);

    let (task, features) = fixture();
    heads.prepare_task(&task, &features).unwrap();
    let assignment = [0, 1, 0];
    let latent = (0..128)
        .map(|index| (((index * 13) % 31) - 15) as f32 / 128.0)
        .collect::<Vec<_>>();
    let probability = heads
        .v_reach(&task, &features, &assignment, &latent, 13)
        .unwrap();
    // Independent scalar Python readback of the V07 JSON and fixture above.
    assert_close(probability, 0.709_336_64, 5e-5);
    assert_eq!(
        heads
            .v_reach(&task, &features, &assignment, &latent, 256)
            .unwrap(),
        heads
            .v_reach(&task, &features, &assignment, &latent, 512)
            .unwrap()
    );

    // The V07 fit is proposal-specific; the legacy proposal pin must fail closed.
    assert!(FrozenProposalValueV02::load_explicit_value(VALUE_PATH, VALUE_SHA256).is_err());
}

#[test]
fn v07_vreach_rejects_schema_transform_and_horizon_drift() {
    const PROPOSAL_PATH: &str = r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v84-v04-proposal-v01\proposal-weights-v04.json";
    const PROPOSAL_SHA256: &str =
        "3ce84b1e4f44f7713c80999223d5638b8ada0eeffea00a06f787de9dc0616f33";
    const VALUE_PATH: &str = r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\run-v89-v04-vreach-fit-v01\v-reach-weights-v07.json";

    let original: serde_json::Value =
        serde_json::from_slice(&std::fs::read(VALUE_PATH).unwrap()).unwrap();
    let invalid_metadata = [
        ("schema", serde_json::json!("r1-v-reach-weights-v06")),
        (
            "architecture",
            serde_json::json!("tanh_mlp_value_4345_h32_v06_stress_scaled_h_groups_budget256"),
        ),
        (
            "feature_schema",
            serde_json::json!("r1-value-input-h-global-meanH-assignment-latent-budget-v01"),
        ),
        ("h_input_scale", serde_json::json!(1.01)),
        ("budget_normalization_max", serde_json::json!(64)),
    ];
    let temp_dir = std::env::temp_dir().join(format!(
        "r1-v07-vreach-invalid-{}-{}",
        std::process::id(),
        TEMP_DIR_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    std::fs::create_dir(&temp_dir).unwrap();

    for (index, (field, invalid_value)) in invalid_metadata.into_iter().enumerate() {
        let mut altered = original.clone();
        altered[field] = invalid_value;
        let bytes = serde_json::to_vec(&altered).unwrap();
        let path = temp_dir.join(format!("invalid-v07-{index}.json"));
        std::fs::write(&path, &bytes).unwrap();
        let digest = format!("{:x}", Sha256::digest(&bytes));
        assert!(
            FrozenProposalValueV02::load_explicit_heads(
                PROPOSAL_PATH,
                PROPOSAL_SHA256,
                &path,
                &digest,
            )
            .is_err(),
            "V07 loader accepted invalid {field}"
        );
    }

    assert!(FrozenProposalValueV02::load_explicit_heads(
        PROPOSAL_PATH,
        PROPOSAL_SHA256,
        VALUE_PATH,
        &"0".repeat(64),
    )
    .is_err());
    std::fs::remove_dir_all(temp_dir).unwrap();
}

fn assert_close(actual: f32, expected: f32, tolerance: f32) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "actual={actual:.9}, expected={expected:.9}, delta={:.9}",
        (actual - expected).abs()
    );
}

fn fixture_edits() -> [Edit; 3] {
    [
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
    ]
}

#[test]
fn pinned_v02_heads_match_python_cpu_reference_vectors() {
    let (task, features) = fixture();
    let mut heads = FrozenProposalValueV02::load_default().unwrap();
    assert_eq!(heads.proposal_sha256(), PROPOSAL_V02_SHA256);
    assert_eq!(heads.value_sha256(), V_REACH_V02_64_SHA256);
    heads.prepare_task(&task, &features).unwrap();
    assert_eq!(heads.cache_len(), 1);

    let assignment = [0, 1, 0];
    let edits = fixture_edits();
    let expected_delta = [0.25, -0.5, 1.0];
    let scored = heads
        .score_edits_detailed(&task, &features, &assignment, &edits, &expected_delta)
        .unwrap();
    assert_eq!(scored.base_logits.len(), 3);
    assert_close(scored.base_logits[0], 11.113_253, 3e-4);
    assert_close(scored.base_logits[1], 10.295_552, 3e-4);
    assert_close(scored.base_logits[2], 13.932_798, 3e-4);
    assert_close(scored.adapter_adjustments[0], 0.086_163_57, 2e-6);
    assert_close(scored.adapter_adjustments[1], -0.172_327_15, 2e-6);
    assert_close(scored.adapter_adjustments[2], 0.344_654_3, 2e-6);
    assert_close(scored.logits[0], 11.199_416, 3e-4);
    assert_close(scored.logits[1], 10.123_225, 3e-4);
    assert_close(scored.logits[2], 14.277_452, 3e-4);

    let latent = (0..128)
        .map(|index| (((index * 13) % 31) - 15) as f32 / 128.0)
        .collect::<Vec<_>>();
    let probability = heads
        .v_reach(&task, &features, &assignment, &latent, 13)
        .unwrap();
    assert_close(probability, 0.479_539_1, 4e-5);
    let at_training_horizon = heads
        .v_reach(&task, &features, &assignment, &latent, 64)
        .unwrap();
    let beyond_training_horizon = heads
        .v_reach(&task, &features, &assignment, &latent, 256)
        .unwrap();
    assert_eq!(at_training_horizon, beyond_training_horizon);
    assert_eq!(heads.cache_len(), 1);
    heads.clear_cache();
    assert_eq!(heads.cache_len(), 0);
}

#[test]
fn v03_proposal_mixes_preserve_base_and_set_adapter_spread() {
    assert_eq!(ProposalMixV03::BaseOnlyV03.id(), "base_only_v03");
    assert!(!ProposalMixV03::BaseOnlyV03.uses_action_signal());
    assert!(ProposalMixV03::IncidenceMaskedV03.uses_incidence_masked_signal());
    let (task, features) = fixture();
    let mut heads = FrozenProposalValueV02::load_default().unwrap();
    heads.prepare_task(&task, &features).unwrap();
    let assignment = [0, 1, 0];
    let edits = fixture_edits();
    let delta = [0.25, -0.5, 1.0];

    let pinned = heads
        .score_edits_detailed(&task, &features, &assignment, &edits, &delta)
        .unwrap();
    let base_only = heads
        .score_edits_detailed_with_mix(
            &task,
            &features,
            &assignment,
            &edits,
            &delta,
            ProposalMixV03::BaseOnlyV03,
        )
        .unwrap();
    assert_eq!(base_only.base_logits, pinned.base_logits);
    assert_eq!(base_only.logits, base_only.base_logits);
    assert!(base_only
        .adapter_adjustments
        .iter()
        .all(|value| *value == 0.0));

    for mix in [
        ProposalMixV03::RawNormalizedV03 { spread_ratio: 1.0 },
        ProposalMixV03::IncidenceMaskedNormalizedV03 { spread_ratio: 1.0 },
        ProposalMixV03::IncidenceMaskedV03,
    ] {
        let scored = heads
            .score_edits_detailed_with_mix(&task, &features, &assignment, &edits, &delta, mix)
            .unwrap();
        assert_eq!(scored.base_logits, pinned.base_logits);
        match mix {
            ProposalMixV03::RawNormalizedV03 { .. }
            | ProposalMixV03::IncidenceMaskedNormalizedV03 { .. } => {
                assert_close(
                    standard_deviation(&scored.adapter_adjustments),
                    standard_deviation(&scored.base_logits),
                    1e-5,
                );
            }
            ProposalMixV03::IncidenceMaskedV03 => {
                for (actual, expected) in scored.adapter_adjustments.iter().zip(&delta) {
                    assert_close(*actual, heads.adapter_logit_bias() * expected, 1e-6);
                }
            }
            _ => unreachable!(),
        }
    }

    let delta_dominant = heads
        .score_edits_detailed_with_mix(
            &task,
            &features,
            &assignment,
            &edits,
            &delta,
            ProposalMixV03::IncidenceMaskedNormalizedV03 { spread_ratio: 4.0 },
        )
        .unwrap();
    assert_close(
        standard_deviation(&delta_dominant.adapter_adjustments),
        4.0 * standard_deviation(&delta_dominant.base_logits),
        1e-5,
    );

    assert!(heads
        .score_edits_detailed_with_mix(
            &task,
            &features,
            &assignment,
            &edits,
            &delta,
            ProposalMixV03::IncidenceMaskedNormalizedV03 { spread_ratio: -1.0 },
        )
        .is_err());
}

fn standard_deviation(values: &[f32]) -> f32 {
    let mean = values.iter().sum::<f32>() / values.len() as f32;
    let variance = values
        .iter()
        .map(|value| (value - mean).powi(2))
        .sum::<f32>()
        / values.len() as f32;
    variance.sqrt()
}

#[test]
fn v02_requires_one_finite_adapter_value_per_legal_candidate() {
    let (task, features) = fixture();
    let mut heads = FrozenProposalValueV02::load_default().unwrap();
    let assignment = [0, 1, 0];
    let edits = fixture_edits();
    assert!(heads
        .score_edits(&task, &features, &assignment, &edits, &[0.0, 0.0])
        .is_err());
    assert!(heads
        .score_edits(&task, &features, &assignment, &edits, &[0.0, f32::NAN, 0.0])
        .is_err());
    assert!(heads
        .score_edits(&task, &features, &assignment, &edits, &[0.0, 0.0, 0.0])
        .is_ok());
}

#[test]
fn v02_fails_closed_on_invalid_edits_and_vreach_shapes() {
    let (task, features) = fixture();
    let mut heads = FrozenProposalValueV02::load_default().unwrap();
    let assignment = [0, 1, 0];
    let invalid_edit = [Edit {
        entity: 0,
        new_role: 0,
    }];
    assert!(heads
        .score_edits(&task, &features, &assignment, &invalid_edit, &[0.0])
        .is_err());
    assert!(heads
        .v_reach(&task, &features, &assignment, &[0.0; 127], 1)
        .is_err());
}

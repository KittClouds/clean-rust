use super::*;

fn legacy_v02_distribution(logits: &[f32]) -> Vec<f64> {
    let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let weights = logits
        .iter()
        .map(|value| f64::from((*value - maximum).exp()))
        .collect::<Vec<_>>();
    let total = weights.iter().sum::<f64>();
    weights.into_iter().map(|weight| weight / total).collect()
}

#[test]
fn temperature_one_is_bit_exact_with_v02_distribution() {
    for logits in [
        vec![0.0, 1.0, -2.0, 3.25],
        vec![100.0, 99.99999, -100.0],
        vec![0.125, 0.125, 0.125],
    ] {
        assert_eq!(
            softmax_temperature(&logits, 1.0).unwrap(),
            legacy_v02_distribution(&logits)
        );
    }
}

#[test]
fn nonunit_temperature_is_deterministic_and_sharpens_when_cooler() {
    let logits = [0.1, 0.6, 1.2, -0.4];
    let ordinary = softmax_temperature(&logits, 1.0).unwrap();
    let cool_a = softmax_temperature(&logits, 0.2).unwrap();
    let cool_b = softmax_temperature(&logits, 0.2).unwrap();
    assert_eq!(cool_a, cool_b);
    assert!(cool_a[2] > ordinary[2]);
    assert_eq!(
        cool_a
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.total_cmp(b.1))
            .unwrap()
            .0,
        2
    );
}

#[test]
fn incidence_masking_conditions_on_only_grounded_kinds() {
    let inference = InferenceTask {
        id: "t".into(),
        family_id: "f".into(),
        n: 2,
        k: 2,
        role_anonymous: false,
        global_text: String::new(),
        clauses: vec!["different".into()],
        entity_mentions: vec![vec![0, 1]],
        role_mentions: vec![vec![]],
    };
    let probabilities = [[0.15, 0.0, 0.8, 0.0, 0.0, 0.05]];
    let actual =
        incidence_masked_expected_delta(&inference, &probabilities, &[0, 0], 0, 1).unwrap();
    assert!((actual - 0.5).abs() < 1e-7);
}

#[test]
fn norm4_matches_runtime_population_standardization_sequence() {
    let base = [0.25f32, 0.75, 1.0, 2.0];
    let delta = [-0.5f32, 0.0, 0.5, 1.0];
    let (delta_mean, delta_sd) = mean_std(&delta);
    let (_, base_sd) = mean_std(&base);
    let expected = base
        .iter()
        .zip(delta)
        .map(|(&base_logit, change)| {
            base_logit + ((change - delta_mean) / delta_sd) * base_sd * 4.0f32
        })
        .collect::<Vec<_>>();
    assert_eq!(compose_norm4_logits(&base, &delta).unwrap(), expected);
}

#[test]
fn policy_digest_binds_temperature_bits_and_weights() {
    let weights = "11".repeat(32);
    let one = policy_identity(&weights, MIXTURE_ID, 1.0).unwrap();
    let lower = policy_identity(&weights, MIXTURE_ID, 0.5).unwrap();
    let different_weights = policy_identity(&"22".repeat(32), MIXTURE_ID, 1.0).unwrap();
    assert_ne!(one.sha256, lower.sha256);
    assert_ne!(one.sha256, different_weights.sha256);
    assert_eq!(
        one.temperature_f64_bits_le_hex,
        hex_bytes(&1.0f64.to_bits().to_le_bytes())
    );
}

#[test]
fn policy_source_and_identity_digests_are_single_sha256s() {
    let weights = "11".repeat(32);
    let temperature = 0.9809063775890474f64;
    let identity = policy_identity(&weights, MIXTURE_ID, temperature).unwrap();
    assert_eq!(identity.weights_sha256, weights);
    assert_eq!(
        identity.source_sha256.simulator_core,
        sha256_hex(SIMULATOR_SOURCE)
    );
    assert_eq!(
        identity.source_sha256.simulator_cli,
        sha256_hex(SIMULATOR_CLI_SOURCE)
    );
    assert_eq!(
        identity.source_sha256.runtime_sampler,
        sha256_hex(RUNTIME_SAMPLER_SOURCE)
    );

    let mut expected = Sha256::new();
    expected.update(b"FAS_R1_VREACH_POLICY_IDENTITY_V03\0");
    expected.update(parse_digest(&weights).unwrap());
    expected.update((MIXTURE_ID.len() as u64).to_le_bytes());
    expected.update(MIXTURE_ID.as_bytes());
    expected.update(temperature.to_bits().to_le_bytes());
    expected.update(SIMULATOR_VERSION.as_bytes());
    for digest in [
        &identity.source_sha256.simulator_core,
        &identity.source_sha256.simulator_cli,
        &identity.source_sha256.simulator_util,
        &identity.source_sha256.simulator_policy,
        &identity.source_sha256.rollout_engine,
        &identity.source_sha256.runtime_mixture,
        &identity.source_sha256.runtime_action_delta,
        &identity.source_sha256.runtime_sampler,
    ] {
        expected.update(parse_digest(digest).unwrap());
    }
    assert_eq!(identity.sha256, hex_bytes(&expected.finalize()));
    assert_eq!(
        identity.temperature_f64_bits_le_hex,
        hex_bytes(&temperature.to_bits().to_le_bytes())
    );
}

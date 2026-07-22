use crate::gradient_pressure::decide;
use crate::{
    CancellationBlockReceipt, CancellationReceipt, GradientPressureBlock, NegativePressureKind,
    NegativePressureReceipt, PressureDecision,
};

#[test]
fn majority_bias_dominated_real_batches_select_pressure_routing() {
    let pressure = vec![
        pressure(NegativePressureKind::FrozenRealBatch, 0.001, 0.99, 1.0),
        pressure(NegativePressureKind::FrozenRealBatch, 0.002, 0.98, 1.0),
        pressure(NegativePressureKind::FrozenRealBatch, 1.0, 0.0, 1.0),
        pressure(NegativePressureKind::PrimaryTarget, 1.0, 0.0, 1.0),
        pressure(NegativePressureKind::QualifierValue, 1.0, 0.0, 2.0),
        pressure(NegativePressureKind::QualifierRole, 1.0, 0.0, 3.0),
    ];
    assert_eq!(
        decide(&pressure, &[cancellation(0.7)]).expect("decision"),
        PressureDecision::ClippingDominant
    );
}

#[test]
fn clipping_and_explicit_qualifier_pressure_remain_separate_causes() {
    let pressure = vec![
        pressure(NegativePressureKind::FrozenRealBatch, 0.001, 0.99, 1.0),
        pressure(NegativePressureKind::PrimaryTarget, 1.0, 0.0, 1.0),
        pressure(NegativePressureKind::QualifierValue, 1.0, 0.0, 11.0),
        pressure(NegativePressureKind::QualifierRole, 1.0, 0.0, 2.0),
    ];
    assert_eq!(
        decide(&pressure, &[cancellation(0.2)]).expect("decision"),
        PressureDecision::ClippingAndObjective
    );
}

fn pressure(
    kind: NegativePressureKind,
    clip: f64,
    bias_share: f64,
    qualifier_gradient: f64,
) -> NegativePressureReceipt {
    NegativePressureReceipt {
        schedule_name: format!("{kind:?}").into(),
        kind,
        positive_negative_pairs: 8,
        schedule_blake3: "b3-test".into(),
        optimizer_identity: "b3-test".into(),
        raw_global_gradient_l2: 1.0,
        global_clip_coefficient: clip,
        decoder_bias_norm_share: bias_share,
        qualifier_projection_norm_share: 0.0,
        qualifier_to_decoder_gradient_ratio: 0.0,
        qualifier_value_embedding_raw_l2: 0.0,
        qualifier_role_embedding_raw_l2: 0.0,
        blocks: vec![block("qualifier-projection", qualifier_gradient)],
        bias_probes: Vec::new(),
    }
}

fn cancellation(ratio: f64) -> CancellationReceipt {
    CancellationReceipt {
        stratum: "qualified".into(),
        examples: 16,
        schedule_blake3: "b3-test".into(),
        split_half_cosine_similarity: 0.0,
        blocks: vec![CancellationBlockReceipt {
            name: "qualifier-projection".into(),
            aggregate_gradient_l2: 1.0,
            sum_individual_gradient_l2: 1.0,
            cancellation_ratio: ratio,
            sign_agreement: 1.0,
            nonzero_sign_comparisons: 1,
        }],
    }
}

fn block(name: &str, raw_gradient_l2: f64) -> GradientPressureBlock {
    GradientPressureBlock {
        name: name.into(),
        raw_gradient_l2,
        global_norm_share: 0.0,
        post_clip_gradient_l2: raw_gradient_l2,
        clip_coefficient: 1.0,
        update_l2: 0.0,
        update_to_weight: 0.0,
        changed_parameter_bits: 0,
        changed_parameter_bits_measured: true,
        parameters: 1,
    }
}

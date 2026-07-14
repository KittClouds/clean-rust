use crate::{
    HyperEpochEconomics, HyperGradientClipPolicy, HyperOptimizerConfig, ParameterDeltaReceipt,
};
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::{HyperEncoderWeights, HYPER_ENCODER_HIDDEN};

pub(crate) fn row_delta(before: &[f32], after: &[f32], rows: &[u32]) -> ParameterDeltaReceipt {
    let mut left = Vec::with_capacity(rows.len() * HYPER_ENCODER_HIDDEN);
    let mut right = Vec::with_capacity(rows.len() * HYPER_ENCODER_HIDDEN);
    for &row in rows {
        let range = row as usize * HYPER_ENCODER_HIDDEN..(row as usize + 1) * HYPER_ENCODER_HIDDEN;
        left.extend_from_slice(&before[range.clone()]);
        right.extend_from_slice(&after[range]);
    }
    tensor_delta(&left, &right)
}

pub(crate) fn tensor_delta(before: &[f32], after: &[f32]) -> ParameterDeltaReceipt {
    let mut changed = 0_u64;
    let mut non_finite = 0_u64;
    let mut total = 0.0_f64;
    let mut maximum = 0.0_f64;
    for (&left, &right) in before.iter().zip(after) {
        let delta = f64::from((right - left).abs());
        changed += u64::from(left.to_bits() != right.to_bits());
        non_finite += u64::from(!right.is_finite());
        total += delta;
        maximum = maximum.max(delta);
    }
    ParameterDeltaReceipt {
        changed_scalars: changed,
        unchanged_scalars: before.len() as u64 - changed,
        non_finite,
        max_absolute_delta: maximum,
        mean_absolute_delta: total / before.len().max(1) as f64,
    }
}

pub(crate) fn economics_gradient_norm(economics: &HyperEpochEconomics) -> f64 {
    [
        economics.entity_embeddings.gradient_l2,
        economics.relation_embeddings.gradient_l2,
        economics.relation_projection.gradient_l2,
        economics.qualifier_projection.gradient_l2,
        economics.direction_matrices.gradient_l2,
        economics.decoder_bias.gradient_l2,
    ]
    .into_iter()
    .map(|value| value * value)
    .sum::<f64>()
    .sqrt()
}

pub(crate) fn clip_coefficient(norm: f64, optimizer: HyperOptimizerConfig) -> f64 {
    if optimizer.gradient_clip_policy == HyperGradientClipPolicy::None
        || norm <= f64::from(optimizer.gradient_clip_norm)
    {
        1.0
    } else {
        f64::from(optimizer.gradient_clip_norm) / norm
    }
}

pub(crate) fn weights_digest(weights: &HyperEncoderWeights) -> CompactString {
    let mut hasher = blake3::Hasher::new();
    for tensor in [
        &weights.node_embeddings,
        &weights.direction_weights,
        &weights.relation_embeddings,
        &weights.relation_projection,
        &weights.qualifier_projection,
        &weights.decoder_bias,
    ] {
        for value in tensor {
            hasher.update(&value.to_bits().to_le_bytes());
        }
    }
    format_compact!("b3-{}", hasher.finalize().to_hex())
}

pub(crate) fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exponential = value.exp();
        exponential / (1.0 + exponential)
    }
}

use crate::hyper_encoder_memory::GradientArena;
use crate::{HyperGradientClipPolicy, HyperOptimizerConfig, HyperWeightDecaySemantics};
use phoenix_graph_research::HyperEncoderWeights;

#[derive(Clone, Copy)]
pub(crate) struct GradientClipScales {
    pub non_bias_norm: f64,
    pub bias_norm: f64,
    pub non_bias_coefficient: f32,
    pub bias_coefficient: f32,
}

pub(crate) fn gradient_clip_scales(
    gradients: &GradientArena,
    optimizer: HyperOptimizerConfig,
    gradient_unscale: f32,
) -> GradientClipScales {
    let mut non_bias_squared = 0.0_f64;
    for values in [
        gradients.node.as_slice(),
        gradients.direction.as_slice(),
        gradients.relation.as_slice(),
        gradients.relation_projection.as_slice(),
        gradients.qualifier_projection.as_slice(),
    ] {
        for &gradient in values {
            let gradient = f64::from(gradient * gradient_unscale);
            non_bias_squared += gradient * gradient;
        }
    }
    let mut bias_squared = 0.0_f64;
    for &gradient in &gradients.bias {
        let gradient = f64::from(gradient * gradient_unscale);
        bias_squared += gradient * gradient;
    }
    let non_bias_norm = non_bias_squared.sqrt();
    let bias_norm = bias_squared.sqrt();
    let (non_bias_coefficient, bias_coefficient) = routed_clip_coefficients(
        optimizer.gradient_clip_policy,
        optimizer.gradient_clip_norm,
        non_bias_norm,
        bias_norm,
    );
    GradientClipScales {
        non_bias_norm,
        bias_norm,
        non_bias_coefficient,
        bias_coefficient,
    }
}

pub(crate) fn routed_clip_coefficients(
    policy: HyperGradientClipPolicy,
    maximum_norm: f32,
    non_bias_norm: f64,
    bias_norm: f64,
) -> (f32, f32) {
    let coefficient = |norm: f64| {
        if norm <= f64::from(maximum_norm) {
            1.0
        } else {
            maximum_norm / norm as f32
        }
    };
    match policy {
        HyperGradientClipPolicy::None => (1.0, 1.0),
        HyperGradientClipPolicy::GlobalNorm | HyperGradientClipPolicy::PartitionedSingleGlobal => {
            let scale = coefficient((non_bias_norm * non_bias_norm + bias_norm * bias_norm).sqrt());
            (scale, scale)
        }
        HyperGradientClipPolicy::DecoderBiasVsNonBias => {
            (coefficient(non_bias_norm), coefficient(bias_norm))
        }
    }
}

#[rustfmt::skip]
pub(crate) fn apply_grouped_sgd(
    weights: &mut HyperEncoderWeights, gradients: &GradientArena,
    optimizer: HyperOptimizerConfig, non_bias_scale: f32, bias_scale: f32,
) {
    update(&mut weights.node_embeddings, &gradients.node, optimizer, non_bias_scale);
    update(&mut weights.direction_weights, &gradients.direction, optimizer, non_bias_scale);
    update(&mut weights.relation_embeddings, &gradients.relation, optimizer, non_bias_scale);
    update(&mut weights.relation_projection, &gradients.relation_projection, optimizer, non_bias_scale);
    update(&mut weights.qualifier_projection, &gradients.qualifier_projection, optimizer, non_bias_scale);
    update(&mut weights.decoder_bias, &gradients.bias, optimizer, bias_scale);
}

fn update(values: &mut [f32], gradients: &[f32], optimizer: HyperOptimizerConfig, clip_scale: f32) {
    for (value, gradient) in values.iter_mut().zip(gradients) {
        let gradient_step = optimizer.learning_rate * *gradient * clip_scale;
        match optimizer.weight_decay_semantics {
            HyperWeightDecaySemantics::None => *value -= gradient_step,
            HyperWeightDecaySemantics::CoupledL2 => {
                *value -= optimizer.learning_rate
                    * (*gradient * clip_scale + optimizer.weight_decay * *value);
            }
            HyperWeightDecaySemantics::Decoupled => {
                *value *= 1.0 - optimizer.learning_rate * optimizer.weight_decay;
                *value -= gradient_step;
            }
        }
    }
}

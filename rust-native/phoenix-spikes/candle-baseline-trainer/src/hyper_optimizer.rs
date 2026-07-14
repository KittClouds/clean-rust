use crate::CandleTrainerError;
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::HyperEncoderTrainingConfig;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GradientBlockEconomics {
    pub gradient_l2: f64,
    pub parameter_l2: f64,
    pub update_l2: f64,
    pub update_to_weight: f64,
    pub exactly_zero_gradients: u64,
    pub parameters: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperEpochEconomics {
    pub mean_binary_cross_entropy: f64,
    pub entity_embeddings: GradientBlockEconomics,
    pub relation_embeddings: GradientBlockEconomics,
    pub relation_projection: GradientBlockEconomics,
    pub qualifier_projection: GradientBlockEconomics,
    pub direction_matrices: GradientBlockEconomics,
    pub decoder_bias: GradientBlockEconomics,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperOptimizerAlgorithm {
    FullBatchSgd,
    DeterministicBatchSgd,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperLossReduction {
    Mean,
    Sum,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperWeightDecaySemantics {
    None,
    CoupledL2,
    Decoupled,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperGradientClipPolicy {
    None,
    GlobalNorm,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum QualifiedSamplingPolicy {
    Natural,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperOptimizerConfig {
    pub algorithm: HyperOptimizerAlgorithm,
    pub learning_rate: f32,
    pub loss_reduction: HyperLossReduction,
    pub batch_size: u32,
    pub gradient_accumulation_steps: u32,
    pub global_loss_scale: f32,
    pub gradient_clip_policy: HyperGradientClipPolicy,
    pub gradient_clip_norm: f32,
    pub weight_decay: f32,
    pub weight_decay_semantics: HyperWeightDecaySemantics,
    pub qualified_sampling_policy: QualifiedSamplingPolicy,
}

impl HyperOptimizerConfig {
    pub fn legacy(config: HyperEncoderTrainingConfig, examples: usize) -> Self {
        Self {
            algorithm: HyperOptimizerAlgorithm::FullBatchSgd,
            learning_rate: config.learning_rate,
            loss_reduction: HyperLossReduction::Mean,
            batch_size: examples as u32,
            gradient_accumulation_steps: 1,
            global_loss_scale: 1.0,
            gradient_clip_policy: HyperGradientClipPolicy::None,
            gradient_clip_norm: 0.0,
            weight_decay: config.l2,
            weight_decay_semantics: HyperWeightDecaySemantics::CoupledL2,
            qualified_sampling_policy: QualifiedSamplingPolicy::Natural,
        }
    }

    pub fn sum_no_decay(learning_rate: f32, examples: usize) -> Self {
        Self {
            algorithm: HyperOptimizerAlgorithm::FullBatchSgd,
            learning_rate,
            loss_reduction: HyperLossReduction::Sum,
            batch_size: examples as u32,
            gradient_accumulation_steps: 1,
            global_loss_scale: 1.0,
            gradient_clip_policy: HyperGradientClipPolicy::None,
            gradient_clip_norm: 0.0,
            weight_decay: 0.0,
            weight_decay_semantics: HyperWeightDecaySemantics::None,
            qualified_sampling_policy: QualifiedSamplingPolicy::Natural,
        }
    }

    pub fn bounded_sum_no_decay(learning_rate: f32, batch_size: u32) -> Self {
        Self {
            algorithm: HyperOptimizerAlgorithm::DeterministicBatchSgd,
            learning_rate,
            loss_reduction: HyperLossReduction::Sum,
            batch_size,
            gradient_accumulation_steps: 1,
            global_loss_scale: 1.0,
            gradient_clip_policy: HyperGradientClipPolicy::None,
            gradient_clip_norm: 0.0,
            weight_decay: 0.0,
            weight_decay_semantics: HyperWeightDecaySemantics::None,
            qualified_sampling_policy: QualifiedSamplingPolicy::Natural,
        }
    }

    pub fn validate(self, examples: usize) -> Result<(), CandleTrainerError> {
        if examples == 0
            || self.batch_size == 0
            || self.batch_size as usize > examples
            || (self.algorithm == HyperOptimizerAlgorithm::FullBatchSgd
                && self.batch_size as usize != examples)
            || self.gradient_accumulation_steps != 1
            || !self.learning_rate.is_finite()
            || self.learning_rate <= 0.0
            || !self.global_loss_scale.is_finite()
            || self.global_loss_scale <= 0.0
            || !self.weight_decay.is_finite()
            || self.weight_decay < 0.0
            || !self.gradient_clip_norm.is_finite()
            || (self.gradient_clip_policy == HyperGradientClipPolicy::GlobalNorm
                && self.gradient_clip_norm <= 0.0)
            || (self.gradient_clip_policy == HyperGradientClipPolicy::None
                && self.gradient_clip_norm != 0.0)
            || (self.weight_decay_semantics == HyperWeightDecaySemantics::None
                && self.weight_decay != 0.0)
        {
            return Err(CandleTrainerError::Contract(
                "hyper optimizer configuration",
            ));
        }
        Ok(())
    }

    pub fn identity(self) -> Result<CompactString, CandleTrainerError> {
        Ok(format_compact!(
            "b3-{}",
            blake3::hash(&serde_json::to_vec(&self)?).to_hex()
        ))
    }

    pub(crate) fn gradient_multiplier(self, examples: usize) -> f32 {
        let reduction = match self.loss_reduction {
            HyperLossReduction::Mean => (examples as f32).recip(),
            HyperLossReduction::Sum => 1.0,
        };
        reduction * self.global_loss_scale
    }
}

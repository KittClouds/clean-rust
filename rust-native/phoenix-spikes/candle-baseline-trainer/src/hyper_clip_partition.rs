use crate::{CandleTrainerError, HyperGradientClipPolicy, HyperOptimizerConfig};
use compact_str::{format_compact, CompactString};
use phoenix_graph_research::HyperEncoderWeights;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperClipGroup {
    Global,
    DecoderBias,
    NonBias,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HyperClipRoutingPolicy {
    SingleGlobal,
    DecoderBiasVsNonBias,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperClipPartitionSpan {
    pub parameter_block: CompactString,
    pub start_offset: u64,
    pub length: u64,
    pub clipping_group: HyperClipGroup,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperClipPartition {
    pub routing_policy: HyperClipRoutingPolicy,
    pub group_ordering: Vec<HyperClipGroup>,
    pub spans: Vec<HyperClipPartitionSpan>,
    pub decoder_weights_present: bool,
    pub partition_blake3: CompactString,
}

impl HyperClipPartition {
    pub fn for_optimizer(
        weights: &HyperEncoderWeights,
        optimizer: HyperOptimizerConfig,
    ) -> Result<Self, CandleTrainerError> {
        let policy = match optimizer.gradient_clip_policy {
            HyperGradientClipPolicy::None
            | HyperGradientClipPolicy::GlobalNorm
            | HyperGradientClipPolicy::PartitionedSingleGlobal => {
                HyperClipRoutingPolicy::SingleGlobal
            }
            HyperGradientClipPolicy::DecoderBiasVsNonBias => {
                HyperClipRoutingPolicy::DecoderBiasVsNonBias
            }
        };
        Self::build(weights, policy)
    }

    pub(crate) fn build(
        weights: &HyperEncoderWeights,
        policy: HyperClipRoutingPolicy,
    ) -> Result<Self, CandleTrainerError> {
        let mut partition = Self::construct(weights, policy)?;
        partition.partition_blake3 = partition.identity()?;
        partition.validate(weights)?;
        Ok(partition)
    }

    fn construct(
        weights: &HyperEncoderWeights,
        policy: HyperClipRoutingPolicy,
    ) -> Result<Self, CandleTrainerError> {
        let group_ordering = match policy {
            HyperClipRoutingPolicy::SingleGlobal => vec![HyperClipGroup::Global],
            HyperClipRoutingPolicy::DecoderBiasVsNonBias => {
                vec![HyperClipGroup::DecoderBias, HyperClipGroup::NonBias]
            }
        };
        let tensors = [
            ("entity-embeddings", weights.node_embeddings.len(), false),
            ("direction-matrices", weights.direction_weights.len(), false),
            (
                "relation-embeddings",
                weights.relation_embeddings.len(),
                false,
            ),
            (
                "relation-projection",
                weights.relation_projection.len(),
                false,
            ),
            (
                "qualifier-projection",
                weights.qualifier_projection.len(),
                false,
            ),
            ("decoder-bias", weights.decoder_bias.len(), true),
        ];
        let mut cursor = 0_u64;
        let mut spans = Vec::with_capacity(tensors.len());
        for (name, length, bias) in tensors {
            let length = u64::try_from(length)
                .map_err(|_| CandleTrainerError::Contract("clip partition length"))?;
            let clipping_group = match policy {
                HyperClipRoutingPolicy::SingleGlobal => HyperClipGroup::Global,
                HyperClipRoutingPolicy::DecoderBiasVsNonBias if bias => HyperClipGroup::DecoderBias,
                HyperClipRoutingPolicy::DecoderBiasVsNonBias => HyperClipGroup::NonBias,
            };
            spans.push(HyperClipPartitionSpan {
                parameter_block: name.into(),
                start_offset: cursor,
                length,
                clipping_group,
            });
            cursor = cursor
                .checked_add(length)
                .ok_or(CandleTrainerError::Contract("clip partition range"))?;
        }
        Ok(Self {
            routing_policy: policy,
            group_ordering,
            spans,
            decoder_weights_present: false,
            partition_blake3: "pending".into(),
        })
    }

    pub fn validate(&self, weights: &HyperEncoderWeights) -> Result<(), CandleTrainerError> {
        let expected = Self::construct(weights, self.routing_policy)?;
        if self.group_ordering != expected.group_ordering
            || self.spans != expected.spans
            || self.decoder_weights_present
            || self.partition_blake3 != self.identity()?
        {
            return Err(CandleTrainerError::Contract("clip partition coverage"));
        }
        Ok(())
    }

    fn identity(&self) -> Result<CompactString, CandleTrainerError> {
        let mut identity = self.clone();
        identity.partition_blake3 = "pending".into();
        Ok(format_compact!(
            "b3-{}",
            blake3::hash(&serde_json::to_vec(&identity)?).to_hex()
        ))
    }
}

impl HyperOptimizerConfig {
    pub fn identity_with_partition_and_schedule(
        self,
        partition: &HyperClipPartition,
        example_schedule_blake3: &str,
    ) -> Result<CompactString, CandleTrainerError> {
        let group_maximum_norms = vec![self.gradient_clip_norm; partition.group_ordering.len()];
        Ok(format_compact!(
            "b3-{}",
            blake3::hash(&serde_json::to_vec(&(
                self,
                partition.partition_blake3.as_str(),
                &partition.group_ordering,
                group_maximum_norms,
                example_schedule_blake3,
            ))?)
            .to_hex()
        ))
    }
}

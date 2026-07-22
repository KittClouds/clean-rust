use crate::hyper_encoder_examples::PreparedHyperExamples;
use crate::HyperOptimizerConfig;
use phoenix_graph_research::{
    ExternalDatasetMapped, HyperEncoderStagedInput, HyperEncoderWeights, HyperRelationalTaskMapped,
};
use std::path::Path;

pub(crate) struct GateArmContext<'a> {
    pub artifact_root: &'a Path,
    pub source: &'a ExternalDatasetMapped,
    pub task: &'a HyperRelationalTaskMapped,
    pub staged: &'a HyperEncoderStagedInput,
    pub examples: &'a PreparedHyperExamples,
    pub initial: &'a HyperEncoderWeights,
    pub initial_weights_blake3: &'a str,
    pub value_slots: &'a [u32],
    pub role_slots: &'a [u32],
    pub optimizer: HyperOptimizerConfig,
}

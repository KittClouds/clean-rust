use r1_search::{Arm, RunConfig};
use serde::Serialize;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MergeMode {
    None,
    RawAssignment,
    CanonicalAssignment,
    StrictDynamicState,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueRefreshPolicy {
    CachedTransition,
    EveryExpansion,
    ResampleBoundary,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchAllocationPolicy {
    StandardRoundRobin,
    ProtectedSpineThenWidth { spine_budget: u64 },
    ForkFromSpineThenWidth { spine_budget: u64 },
}

#[derive(Clone, Debug, Serialize)]
pub struct Stage1RunConfig {
    pub base: RunConfig,
    pub merge_mode: MergeMode,
    pub learned_sample_temperature: f64,
    pub proposal_id: String,
    pub selector_id: String,
    pub value_id: String,
    pub value_refresh_policy: ValueRefreshPolicy,
    pub allocation_policy: SearchAllocationPolicy,
    pub initial_assignment: Option<Vec<u8>>,
}

impl Stage1RunConfig {
    pub fn from_stage0(base: RunConfig) -> Self {
        Self {
            merge_mode: match base.arm {
                Arm::MergedWidth => MergeMode::RawAssignment,
                Arm::CanonicalMerge | Arm::Particle => MergeMode::CanonicalAssignment,
                Arm::Depth | Arm::SampledDepth | Arm::RandomWidth | Arm::LearnedWidth => {
                    MergeMode::None
                }
            },
            learned_sample_temperature: 1.0,
            proposal_id: "unset".to_owned(),
            selector_id: "unset".to_owned(),
            value_id: "unset".to_owned(),
            value_refresh_policy: ValueRefreshPolicy::CachedTransition,
            allocation_policy: SearchAllocationPolicy::StandardRoundRobin,
            initial_assignment: None,
            base,
        }
    }
}

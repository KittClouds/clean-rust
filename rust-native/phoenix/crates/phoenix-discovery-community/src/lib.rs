mod build;
mod error;
mod format;
mod graph;
mod leiden;
mod mapped;
mod metrics;
mod policy;
#[cfg(feature = "wgpu-shadow")]
mod wgpu_shadow;

pub use build::write_deterministic_community_artifact;
pub use error::CommunityArtifactError;
pub use format::{CommunityArtifactManifest, COMMUNITY_ARTIFACT_SCHEMA};
pub use mapped::{BridgeMetricView, DeterministicCommunityArtifact, SparseAffinitySlice};
pub use policy::DeterministicCommunityPolicy;
#[cfg(feature = "wgpu-shadow")]
pub use wgpu_shadow::{
    prepare_deterministic_community_shadow, write_deterministic_community_artifact_wgpu_shadow,
    CommunityWgpuShadowReceipt, CommunityWgpuShadowResult, CommunityWorkloadShape,
    PreparedCommunityShadow, COMMUNITY_WGPU_SHADOW_PATH_ID,
};

#[cfg(test)]
mod tests;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum DiscoveryQueryError {
    #[error("invalid discovery query contract: {0}")]
    Invalid(String),
    #[error("seed resolver failed: {0}")]
    Resolver(String),
    #[error(transparent)]
    Discovery(#[from] phoenix_discovery_view::DiscoveryViewError),
    #[error(transparent)]
    Community(#[from] phoenix_discovery_community::CommunityArtifactError),
}

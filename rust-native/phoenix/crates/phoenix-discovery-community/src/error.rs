use thiserror::Error;

#[derive(Debug, Error)]
pub enum CommunityArtifactError {
    #[error("community artifact I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("community artifact manifest error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("asserted discovery view error: {0}")]
    Discovery(#[from] phoenix_discovery_view::DiscoveryViewError),
    #[error("invalid community artifact: {0}")]
    Invalid(String),
}

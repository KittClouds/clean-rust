use thiserror::Error;

#[derive(Debug, Error)]
pub enum GraphAnalyticsError {
    #[error("invalid graph analytics input: {0}")]
    Input(String),
    #[error("GPU adapter unavailable: {0}")]
    Adapter(String),
    #[error("GPU device unavailable: {0}")]
    Device(String),
    #[error("GPU residency rejected: {0}")]
    Residency(String),
    #[error("GPU execution failed: {0}")]
    Execution(String),
    #[error("GPU weak-component propagation did not converge in {iterations} iterations")]
    ComponentsDidNotConverge { iterations: u32 },
}

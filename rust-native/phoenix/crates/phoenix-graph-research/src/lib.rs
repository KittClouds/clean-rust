//! Immutable, leakage-aware research snapshots over authoritative Phoenix graph state.

mod artifact;
mod build;
mod model;
mod tensor_artifact;
mod tensor_model;
mod tensorize;

pub use artifact::{FrozenGraphResearchBundle, FrozenGraphResearchMapped};
pub use build::{freeze_graph_research_snapshot, FrozenGraphResearchInput};
pub use model::*;
pub use tensor_artifact::{FrozenTensorBundle, FrozenTensorMapped};
pub use tensor_model::*;
pub use tensorize::tensorize_frozen_graph;

#[cfg(test)]
mod tests;

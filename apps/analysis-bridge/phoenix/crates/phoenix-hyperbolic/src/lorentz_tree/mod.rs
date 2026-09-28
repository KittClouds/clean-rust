//! Lorentz H4 multi-hierarchy forest space.
//!
//! This module is intentionally storage-agnostic. It gives hierarchy lenses a
//! deterministic hyperboloid geometry/index without wiring them into OverGraph
//! or semantic ANN.

mod error;
mod forest;
mod geometry;
mod index;
mod mmap;
mod model;
mod score;

pub use error::{LorentzResult, LorentzTreeError};
pub use forest::LorentzForest;
pub use geometry::{hyperbolic_distance, hyperbolic_similarity01, lorentz_dot, HyperboloidPoint};
pub use index::{LorentzForestIndex, LorentzMembershipRow};
pub use mmap::MmapLorentzForestIndex;
pub use model::{
    LorentzNode, LorentzQueryMode, LorentzScoreConfig, LorentzTree, LorentzTreeKind,
    LorentzTreeMembership, LorentzTreeQuery,
};
pub use score::{
    rank_lorentz_candidates, score_lorentz_candidate, LorentzCandidateRef, LorentzCandidateScore,
};

#[cfg(test)]
mod tests;

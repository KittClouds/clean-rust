//! Phoenix hyperbolic, hypersphere, hybrid geometry, and native ANN.
//!
//! Mutable ANN construction compacts into immutable dense pages. Verified V2
//! archives expose full-precision vectors and adjacency directly from mmap;
//! manifold metrics remain selected at the dynamic boundary and monomorphic in
//! search kernels.

mod ann;

pub mod ann_metric;
pub mod graph_adapter;
pub mod graph_hardening;
pub mod hopf;
pub mod hybrid_space;
pub mod lorentz_tree;
pub mod manifold_v2;
pub mod poincare;
pub mod shard;
pub mod siegel_finsler;
pub mod sphere;
pub mod sphere_shard;
pub mod sphere_tangent;
pub mod tangent;
pub mod v15cones;

pub use ann::*;
pub use ann_metric::AnnMetric;

#[cfg(test)]
mod sphere_hnsw_tests;

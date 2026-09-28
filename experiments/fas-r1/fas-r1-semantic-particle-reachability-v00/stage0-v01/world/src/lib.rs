//! Model-free symbolic universe for FAS-R1 Stage 0.
//!
//! The crate deliberately keeps the typed task AST and exact solution APIs
//! separate from InferenceTask, the rendered projection used at inference.
//! No language model, tokenizer, or external runtime is involved.

mod generator;
mod model;
mod reference;
mod render;
mod solver;
mod symmetry;
mod validate;

pub use generator::{
    generate_family, generate_qualified_fixture, generate_smoke_batch, generate_task,
    GeneratedFamily, GenerationSpec, GeneratorError, QualifiedFixture, SolutionStratum,
};
pub use model::{Clause, Task};
pub use reference::validate_independent;
pub use render::{render_task, InferenceTask, RenderedTask};
pub use solver::{enumerate_solutions, SolveError};
pub use symmetry::{automorphisms, canonical_assignment};
pub use validate::validate;

#[cfg(test)]
mod tests;

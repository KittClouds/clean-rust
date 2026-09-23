//! Production copy of the FP32 decoder qualified on 2026-08-26.
//! Source: experiments/phoenix-gliner25-eval. Only entity/long-context entry
//! points are exposed in the worker contract; other heads are not promoted.
pub mod chunk;
pub mod features;

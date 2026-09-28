#![allow(dead_code, unused_imports)]

mod allocation;
#[cfg(test)]
mod baseline;
mod graph;
mod observer;
mod plasticity;
mod rng;
mod simulation;
mod task;

pub use allocation::allocations;

fn main() -> anyhow::Result<()> {
    anyhow::bail!(
        "DH-07 is blocked before seal: constructor-first qualification failed; measured execution is disabled"
    )
}

#![allow(dead_code, unused_imports)] // Frozen lineage modules remain testable.
mod allocation;
#[cfg(test)]
mod baseline;
mod capture;
mod experiment_main;
mod graph;
mod observer;
mod plasticity;
mod policy;
mod rng;
mod rotation;
mod simulation;
mod task;

pub use allocation::allocations;

fn main() -> anyhow::Result<()> {
    experiment_main::main()
}

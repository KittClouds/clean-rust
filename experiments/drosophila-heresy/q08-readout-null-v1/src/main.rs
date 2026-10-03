#![allow(dead_code, unused_imports)] // Frozen lineage modules remain testable.
mod allocation;
#[cfg(test)]
mod baseline;
mod capture;
mod experiment_main;
mod geometry;
mod graph;
mod observer;
mod plasticity;
mod policy;
mod readout;
mod rng;
mod rotation;
mod simulation;
mod task;

pub use allocation::allocations;

fn main() -> anyhow::Result<()> {
    experiment_main::main()
}

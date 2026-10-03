#![allow(dead_code, unused_imports)] // Frozen lineage modules remain testable.
mod allocation;
#[cfg(test)]
mod baseline;
mod capture;
mod experiment_main;
mod graph;
mod linear;
mod observer;
mod plasticity;
mod policy;
mod q10;
mod q10rc;
mod rng;
mod simulation;
mod task;

pub use allocation::allocations;

fn main() -> anyhow::Result<()> {
    q10rc::main()
}

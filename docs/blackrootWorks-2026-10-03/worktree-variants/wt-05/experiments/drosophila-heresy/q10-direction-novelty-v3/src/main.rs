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
mod q10sr;
mod q10dn;
mod q10dn3;
mod rng;
mod simulation;
mod task;

pub use allocation::allocations;

fn main() -> anyhow::Result<()> {
    q10dn3::main()
}

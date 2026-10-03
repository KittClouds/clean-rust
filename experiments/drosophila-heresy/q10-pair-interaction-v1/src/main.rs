#![allow(dead_code, unused_imports)]

mod allocation;
mod capture;
mod graph;
mod linear;
mod observer;
mod pi_core;
mod pi_sampler;
mod pi_types;
mod plasticity;
mod policy;
mod q10;
mod q10pi;
mod q10sr;
mod rng;
mod rotation;
mod simulation;
mod task;

pub use allocation::allocations;

fn main() -> anyhow::Result<()> {
    q10pi::main()
}

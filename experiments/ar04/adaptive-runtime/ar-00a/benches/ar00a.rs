use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_ar_00a::{Arm, run_adamw, run_discrete};

fn main() {
    let samples = xor_samples();
    let repetitions = 8;
    for arm in Arm::all() {
        let start = Instant::now();
        for _ in 0..repetitions {
            let result = if arm == Arm::A4Adamw {
                run_adamw(black_box(&samples))
            } else {
                run_discrete(black_box(&samples), arm)
            };
            black_box(result.final_loss);
        }
        let ns_per_run = start.elapsed().as_nanos() / repetitions;
        println!("{}: {ns_per_run} ns/run", arm.label());
    }
}

use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_ar_00j::{Arm, SEEDS, run};

fn main() {
    let samples = xor_samples();
    for arm in Arm::ALL {
        let start = Instant::now();
        let result = run(black_box(&samples), arm, SEEDS[0]);
        black_box(result.final_loss);
        println!("{}: {} ns/run", arm.label(), start.elapsed().as_nanos());
    }
}

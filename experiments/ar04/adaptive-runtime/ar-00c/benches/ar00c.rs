use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_ar_00c::{UtilityArm, run};

fn main() {
    let samples = xor_samples();
    let repetitions = 4;
    for arm in UtilityArm::all() {
        let start = Instant::now();
        for _ in 0..repetitions {
            let result = run(black_box(&samples), arm);
            black_box(result.final_loss);
        }
        println!(
            "{}: {} ns/run",
            arm.label(),
            start.elapsed().as_nanos() / repetitions
        );
    }
}

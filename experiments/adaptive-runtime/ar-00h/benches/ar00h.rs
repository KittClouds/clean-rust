use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_ar_00h::{BudgetMode, run};

fn main() {
    let samples = xor_samples();
    for width in 1..=4 {
        let start = Instant::now();
        let result = run(
            black_box(&samples),
            width,
            0x2b7e_1516_28ae_d2a6,
            BudgetMode::EqualSteps,
        );
        black_box(result.final_loss);
        println!("width{}: {} ns/run", width, start.elapsed().as_nanos());
    }
}

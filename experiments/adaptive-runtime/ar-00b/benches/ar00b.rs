use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::{run_interposed, xor_samples};
use adaptive_runtime_ar_00b::run_sign_only;

fn main() {
    let samples = xor_samples();
    let repetitions = 64;
    for (label, run) in [("ar00_candidate_ranked", 0_u8), ("sign_only", 1_u8)] {
        let start = Instant::now();
        for _ in 0..repetitions {
            let result = if run == 0 {
                run_interposed(black_box(&samples), adaptive_runtime_ar_00b::EPOCHS)
            } else {
                run_sign_only(black_box(&samples))
            };
            black_box(result.final_loss);
        }
        println!(
            "{label}: {} ns/run",
            start.elapsed().as_nanos() / repetitions
        );
    }
}

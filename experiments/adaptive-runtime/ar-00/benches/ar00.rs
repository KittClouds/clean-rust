use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::{run_adamw, run_interposed, xor_samples};

fn main() {
    let samples = xor_samples();
    let repetitions = 64;

    let start = Instant::now();
    for _ in 0..repetitions {
        black_box(run_adamw(black_box(&samples), 3_000));
    }
    let baseline_ns = start.elapsed().as_nanos() / repetitions;

    let start = Instant::now();
    for _ in 0..repetitions {
        black_box(run_interposed(black_box(&samples), 3_000));
    }
    let interposed_ns = start.elapsed().as_nanos() / repetitions;

    println!("AR-00 benchmark");
    println!("adamw_baseline_ns_per_run={baseline_ns}");
    println!("action_runtime_ns_per_run={interposed_ns}");
}

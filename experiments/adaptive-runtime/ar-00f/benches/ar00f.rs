use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_ar_00f::{RunKind, run_kind};

fn main() {
    let samples = xor_samples();
    for kind in [
        RunKind::F0GlobalSingleton,
        RunKind::F4DynamicRandom,
        RunKind::Width(3),
    ] {
        let start = Instant::now();
        let result = run_kind(black_box(&samples), kind);
        black_box(result.final_loss);
        println!("{}: {} ns/run", kind.label(), start.elapsed().as_nanos());
    }
}

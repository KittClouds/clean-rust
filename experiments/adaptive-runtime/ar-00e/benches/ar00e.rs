use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_ar_00e::{Policy, run};

fn main() {
    let samples = xor_samples();
    for policy in Policy::all() {
        let start = Instant::now();
        let result = run(black_box(&samples), policy);
        black_box(result.final_loss);
        println!("{}: {} ns/run", policy.label(), start.elapsed().as_nanos());
    }
}

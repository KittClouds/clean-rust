use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_int2::run;

fn main() {
    let samples = xor_samples();
    let start = Instant::now();
    let report = run(black_box(&samples));
    black_box(report.summaries.len());
    println!("INT2 topology: {} ns/run", start.elapsed().as_nanos());
}

use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_ar_00e_aud1::run;

fn main() {
    let samples = xor_samples();
    let start = Instant::now();
    let report = run(black_box(&samples));
    black_box(report.summaries.len());
    println!("AR-00E-AUD1: {} ns/run", start.elapsed().as_nanos());
}

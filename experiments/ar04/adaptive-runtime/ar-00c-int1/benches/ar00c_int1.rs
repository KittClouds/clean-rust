use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_00::xor_samples;
use adaptive_runtime_ar_00c_int1::run;

fn main() {
    let samples = xor_samples();
    let start = Instant::now();
    let map = run(black_box(&samples));
    black_box(map.pairs.len());
    println!(
        "AR-00C-INT1 pair map: {} ns/run",
        start.elapsed().as_nanos()
    );
}

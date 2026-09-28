//! In-memory SHA-256 throughput, to separate hashing cost from disk cost.
//! `cargo run --release -p kammi-jcs --example sha_throughput`

use std::time::Instant;

use kammi_jcs::Sha256Hasher;

fn main() {
    let block = vec![0xA5u8; 8 << 20];
    let rounds = 128; // 1 GiB total
    let started = Instant::now();
    let mut hasher = Sha256Hasher::new();
    for _ in 0..rounds {
        hasher.update(&block);
    }
    let digest = hasher.finish();
    let seconds = started.elapsed().as_secs_f64();
    println!(
        "{} MiB in {seconds:.3}s = {:.0} MiB/s ({digest})",
        rounds * 8,
        (rounds * 8) as f64 / seconds
    );
}

use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let output_dir = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("artifacts/run-20260921-01"));
    let rows = adaptive_runtime_ar_03a_r1::run(&output_dir)?;
    println!(
        "AR-03A-R1 diagnostic complete: {rows} panel rows; elapsed {:.2}s; artifacts at {}",
        started.elapsed().as_secs_f64(),
        output_dir.display(),
    );
    Ok(())
}

use std::path::PathBuf;
use std::time::Instant;

use adaptive_runtime_ar_02a_r2::GaussianMappedDataset;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dataset_path = root.join("../ar-02a-r2/artifacts/gaussian-cells.bin");
    let output_path = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("artifacts/run-20260921-01"));
    let dataset = GaussianMappedDataset::open(dataset_path)?;
    let rows = adaptive_runtime_ar_03a::run(dataset.samples(), &output_path)?;
    println!(
        "AR-03A diagnostic complete: {rows} held-out panel rows; elapsed {:.2}s; artifacts at {}",
        started.elapsed().as_secs_f64(),
        output_path.display(),
    );
    Ok(())
}

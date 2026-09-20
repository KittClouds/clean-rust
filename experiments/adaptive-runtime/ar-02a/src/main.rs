use std::path::PathBuf;
use std::time::Instant;

use adaptive_runtime_ar_02a::{GaussianMappedDataset, run_ar02a, write_gaussian_dataset};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts = root.join("artifacts");
    std::fs::create_dir_all(&artifacts)?;
    let dataset_path = artifacts.join("gaussian-cells.bin");
    write_gaussian_dataset(&dataset_path)?;
    let dataset = GaussianMappedDataset::open(&dataset_path)?;
    let results = run_ar02a(dataset.samples(), &artifacts)?;
    println!(
        "AR-02A complete: {} runs, {} verifier constructions, {} seeds; elapsed {:.2}s; artifacts at {}",
        results.len(),
        4,
        3,
        started.elapsed().as_secs_f64(),
        artifacts.display(),
    );
    Ok(())
}

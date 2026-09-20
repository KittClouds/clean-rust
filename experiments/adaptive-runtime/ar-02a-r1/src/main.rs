use std::path::PathBuf;
use std::time::Instant;

use adaptive_runtime_ar_02a_r1::{
    GaussianMappedDataset, R1_METHODS, R1_SEEDS, run_ar02a_r1, write_gaussian_dataset,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts = root.join("artifacts");
    std::fs::create_dir_all(&artifacts)?;
    let dataset_path = artifacts.join("gaussian-cells.bin");
    write_gaussian_dataset(&dataset_path)?;
    let dataset = GaussianMappedDataset::open(&dataset_path)?;
    let results = run_ar02a_r1(dataset.samples(), &artifacts)?;
    println!(
        "AR-02A-R1 complete: {} runs ({} specs × {} seeds); elapsed {:.2}s; artifacts at {}",
        results.len(),
        R1_METHODS.len(),
        R1_SEEDS.len(),
        started.elapsed().as_secs_f64(),
        artifacts.display(),
    );
    Ok(())
}

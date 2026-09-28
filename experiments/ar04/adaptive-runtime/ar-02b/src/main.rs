use std::path::PathBuf;
use std::time::Instant;

use adaptive_runtime_ar_02b::{GaussianMappedDataset, run_path_source_crossover};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts = root.join("artifacts");
    std::fs::create_dir_all(&artifacts)?;
    let dataset_path = artifacts.join("gaussian-cells.bin");
    let dataset = GaussianMappedDataset::open(&dataset_path)?;
    let report = run_path_source_crossover(dataset.samples(), &artifacts)?;
    println!(
        "AR-02B complete: {} matched comparisons, {} complete crossovers; source interaction mean {:.6e}; elapsed {:.2}s; artifacts at {}",
        report.matched_controls,
        report.complete_crossovers,
        report.mean_source_interaction_h64,
        started.elapsed().as_secs_f64(),
        artifacts.display(),
    );
    Ok(())
}

use std::path::PathBuf;
use std::time::Instant;

use adaptive_runtime_ar_02a_r2::{GaussianMappedDataset, run_r2_audit};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts = root.join("artifacts");
    std::fs::create_dir_all(&artifacts)?;
    let dataset_path = artifacts.join("gaussian-cells.bin");
    let dataset = GaussianMappedDataset::open(&dataset_path)?;
    let panel_rows = run_r2_audit(dataset.samples(), &artifacts)?;
    println!(
        "AR-02A-R2 diagnostic complete: {panel_rows} panel audits; elapsed {:.2}s; artifacts at {}",
        started.elapsed().as_secs_f64(),
        artifacts.display(),
    );
    Ok(())
}

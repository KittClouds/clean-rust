use std::path::PathBuf;
use std::time::Instant;

use adaptive_runtime_ar_01q::{MappedDataset, run_path_source_crossover, write_dataset};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts = root.join("artifacts");
    std::fs::create_dir_all(&artifacts)?;
    let dataset_path = artifacts.join("spiral-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let report = run_path_source_crossover(dataset.samples(), &artifacts)?;
    println!(
        "AR-01Q complete: {} snapshots, {} matched controls, {} source paths, {} crossovers; max telescope residual {:.3e}; max source-identity residual {:.3e}; elapsed {:.2}s; artifacts at {}",
        report.snapshots,
        report.matched_controls,
        report.generated_paths,
        report.comparisons,
        report.max_telescoping_residual,
        report.max_source_interaction_identity_residual,
        started.elapsed().as_secs_f64(),
        artifacts.display(),
    );
    Ok(())
}

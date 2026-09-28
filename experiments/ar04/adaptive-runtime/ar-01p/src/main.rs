use std::path::PathBuf;

use adaptive_runtime_ar_01p::{MappedDataset, run_mixed_difference_ledger, write_dataset};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let artifacts = root.join("artifacts");
    std::fs::create_dir_all(&artifacts)?;
    let dataset_path = artifacts.join("spiral-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let report = run_mixed_difference_ledger(dataset.samples(), &artifacts)?;
    println!(
        "AR-01P complete: {} snapshots, {} matched controls, {} paired paths, {} path events; max telescope residual {:.3e}; artifacts at {}",
        report.snapshots,
        report.matched_controls,
        report.comparisons,
        report.path_events,
        report.max_telescoping_residual,
        artifacts.display(),
    );
    Ok(())
}

use std::path::PathBuf;

use adaptive_runtime_ar_02b::{GaussianMappedDataset, run_r2_variance_audit};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let source = root.join("..").join("ar-02a-r2").join("artifacts");
    let dataset = GaussianMappedDataset::open(source.join("gaussian-cells.bin"))?;
    let output = root.join("artifacts");
    let rows = run_r2_variance_audit(dataset.samples(), &source, &output)?;
    println!(
        "AR-02A-R2 variance sidecar complete: {rows} state/method rows; outputs at {}",
        output.display()
    );
    Ok(())
}

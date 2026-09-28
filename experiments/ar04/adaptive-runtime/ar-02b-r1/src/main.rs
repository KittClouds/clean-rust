use std::path::PathBuf;

use adaptive_runtime_ar_02b::{GaussianMappedDataset, run_path_source_crossover_with_seeds};

use adaptive_runtime_ar_02b_r1::{B_R1_SEEDS, audit_crossover};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dataset_path = root.join("artifacts").join("gaussian-cells.bin");
    let output = root.join("artifacts");
    if std::env::args().nth(1).as_deref() == Some("--audit-existing") {
        let audit = audit_crossover(&output, &B_R1_SEEDS)?;
        println!(
            "AR-02B-R1 audit refreshed: {} complete, {} divergent; p_div {:.4}; active mean interaction {:.6e}; overall mean {:.6e}",
            audit.complete,
            audit.divergent,
            audit.divergence_probability,
            audit.mean_active_interaction,
            audit.mean_overall_interaction
        );
        return Ok(());
    }
    let dataset = GaussianMappedDataset::open(&dataset_path)?;
    let report =
        run_path_source_crossover_with_seeds(dataset.samples(), &output, &B_R1_SEEDS, "ar-02b-r1")?;
    let audit = audit_crossover(&output, &B_R1_SEEDS)?;
    println!(
        "AR-02B-R1 complete: {} seeds, {} matched controls, {} complete, {} divergent; active mean interaction {:.6e}; outputs at {}",
        report.seeds,
        audit.matched,
        audit.complete,
        audit.divergent,
        audit.mean_active_interaction,
        output.display()
    );
    Ok(())
}

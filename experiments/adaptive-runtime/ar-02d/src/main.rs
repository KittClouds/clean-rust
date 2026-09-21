use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use adaptive_runtime_ar_02b::{GaussianMappedDataset, run_source_conditioning_null};

const SEEDS: [u64; 9] = [
    0x9f4a_7c15_d6e8_b301,
    0xc3a5_c85c_97cb_3127,
    0xb492_b66f_be98_f273,
    0x6a09_e667_f3bc_c909,
    0xbb67_ae85_84ca_a73b,
    0x3c6e_f372_fe94_f82b,
    0xa54f_f53a_5f1d_36f1,
    0x510e_527f_ade6_82d1,
    0x1f83_d9ab_fb41_bd6b,
];

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dataset_path = root
        .join("..")
        .join("ar-02b-r1")
        .join("artifacts")
        .join("gaussian-cells.bin");
    let run_id = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let output = root.join("artifacts").join(format!("run-{run_id}"));
    if output.exists() {
        return Err(format!(
            "refusing to overwrite existing run directory {}",
            output.display()
        )
        .into());
    }
    let dataset = GaussianMappedDataset::open(&dataset_path)?;
    let report = run_source_conditioning_null(dataset.samples(), &output, &SEEDS, "ar-02d")?;
    println!(
        "AR-02D complete: {} streams, {} snapshots, {} strict C1 controls, {} D1 triplets, {} D2 triplets, {} complete G/C1 comparisons, {} complete C1/C2 comparisons; artifacts at {}",
        report.seeds,
        report.snapshots,
        report.matched_selected_control_controls,
        report.exact_vector_triplets,
        report.magnitude_only_triplets,
        report.complete_selected_control,
        report.complete_control_control,
        output.display()
    );
    Ok(())
}

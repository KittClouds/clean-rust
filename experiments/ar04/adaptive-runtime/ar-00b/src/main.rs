use std::{fs, path::PathBuf};

use adaptive_runtime_ar_00::{MappedDataset, run_interposed, write_dataset};
use adaptive_runtime_ar_00b::run_sign_only;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let artifact_dir = PathBuf::from("artifacts");
    fs::create_dir_all(&artifact_dir)?;
    let dataset_path = artifact_dir.join("xor-dataset.bin");
    write_dataset(&dataset_path)?;
    let dataset = MappedDataset::open(&dataset_path)?;
    let ar00 = run_interposed(dataset.samples(), adaptive_runtime_ar_00b::EPOCHS);
    let sign_only = run_sign_only(dataset.samples());
    let report = format!(
        "{{\n  \"schema\": \"adaptive-runtime-ar-00b/v1\",\n  \"scope\": \"engineering-only\",\n  \"ar00_loss\": {:.8},\n  \"sign_only_loss\": {:.8},\n  \"ar00_accuracy\": {:.8},\n  \"sign_only_accuracy\": {:.8},\n  \"ar00_selected\": {},\n  \"sign_only_selected\": {},\n  \"ar00_no_op\": {},\n  \"sign_only_no_op\": {},\n  \"ar00_blocked\": {},\n  \"sign_only_blocked\": {}\n}}\n",
        ar00.final_loss,
        sign_only.final_loss,
        ar00.final_accuracy,
        sign_only.final_accuracy,
        ar00.action_stats.selected,
        sign_only.action_stats.selected,
        ar00.action_stats.no_op,
        sign_only.action_stats.no_op,
        ar00.action_stats.blocked,
        sign_only.action_stats.blocked,
    );
    fs::write(artifact_dir.join("ar-00b-report.json"), report)?;
    println!("AR-00B — Sign-Only Equivalence");
    println!(
        "AR-00:       loss={:.8} accuracy={:.2}%",
        ar00.final_loss,
        ar00.final_accuracy * 100.0
    );
    println!(
        "Sign-only:   loss={:.8} accuracy={:.2}%",
        sign_only.final_loss,
        sign_only.final_accuracy * 100.0
    );
    println!(
        "report: {}",
        artifact_dir.join("ar-00b-report.json").display()
    );
    Ok(())
}

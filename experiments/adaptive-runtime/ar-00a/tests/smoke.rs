use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00a::{Arm, EPOCHS, run_all};

#[test]
fn all_granularity_arms_complete_the_smoke_task() {
    let path = std::env::temp_dir().join(format!("ar00a-smoke-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    let results = run_all(mapped.samples());
    assert_eq!(results.len(), Arm::all().len());
    assert!(results.iter().all(|result| result.epochs == EPOCHS));
    assert!(results.iter().all(|result| result.final_accuracy == 1.0));
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

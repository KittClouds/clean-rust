use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00d::{EPOCHS, Policy, run_all};

#[test]
fn all_commit_policies_complete_the_smoke_contract() {
    let path = std::env::temp_dir().join(format!("ar00d-smoke-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    let results = run_all(mapped.samples());
    assert_eq!(results.len(), Policy::all().len());
    assert!(results.iter().all(|result| result.curve.len() == EPOCHS));
    assert!(results.iter().all(|result| result.telemetry.selected > 0));
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

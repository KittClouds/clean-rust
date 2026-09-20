use adaptive_runtime_ar_00::{MappedDataset, run_interposed, write_dataset};

#[test]
fn executable_smoke_contract() {
    let path = std::env::temp_dir().join(format!("ar00-smoke-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    let result = run_interposed(mapped.samples(), 3_000);
    assert_eq!(result.final_accuracy, 1.0);
    assert!(result.action_stats.selected > 10_000);
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

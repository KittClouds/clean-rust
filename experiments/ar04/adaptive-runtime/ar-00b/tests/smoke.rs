use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00b::run_sign_only;

#[test]
fn sign_only_smoke_contract() {
    let path = std::env::temp_dir().join(format!("ar00b-smoke-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    let result = run_sign_only(mapped.samples());
    assert_eq!(result.final_accuracy, 1.0);
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

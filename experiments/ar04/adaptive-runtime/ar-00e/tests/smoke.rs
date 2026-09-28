use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00e::{Policy, run_for_epochs};

#[test]
fn structural_policy_smoke_contract() {
    let path =
        std::env::temp_dir().join(format!("adaptive-runtime-ar00e-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    for policy in Policy::all() {
        let result = run_for_epochs(mapped.samples(), policy, 1);
        assert_eq!(result.curve.len(), 1);
        assert!(result.telemetry.utility_evaluations > 0);
    }
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

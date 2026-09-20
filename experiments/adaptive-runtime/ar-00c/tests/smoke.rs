use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00c::{EPOCHS, UtilityArm, run_all};

#[test]
fn all_utility_arms_complete_the_smoke_task() {
    let path = std::env::temp_dir().join(format!("ar00c-smoke-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    let results = run_all(mapped.samples());
    assert_eq!(results.len(), UtilityArm::all().len());
    assert!(
        results[..3]
            .iter()
            .all(|result| result.final_accuracy == 1.0)
    );
    assert!(results[3].telemetry.absolute_composition_error > 1.0);
    assert!(results.iter().all(|result| result.curve.len() == EPOCHS));
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

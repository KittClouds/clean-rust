use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_int2::{Category, PERMUTATIONS, SNAPSHOT_EPOCHS, run};

#[test]
fn topology_smoke_contract() {
    let path =
        std::env::temp_dir().join(format!("adaptive-runtime-int2-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    let report = run(mapped.samples());
    assert_eq!(
        report.summaries.len(),
        SNAPSHOT_EPOCHS.len() * Category::all().len()
    );
    assert!(
        report
            .summaries
            .iter()
            .all(|row| row.null.permutations == PERMUTATIONS)
    );
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00c_int1::{SNAPSHOT_EPOCHS, run};

#[test]
fn interaction_map_smoke_contract() {
    let path = std::env::temp_dir().join(format!("ar00c-int1-smoke-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    let map = run(mapped.samples());
    assert_eq!(map.snapshots.len(), SNAPSHOT_EPOCHS.len());
    assert_eq!(map.pairs.len(), SNAPSHOT_EPOCHS.len() * 136);
    assert!(!map.groups.is_empty());
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

use adaptive_runtime_ar_01q::{CLASSES, MappedDataset, TOTAL_SAMPLES, write_dataset};

#[test]
fn mapped_spiral_dataset_is_ready_for_q() {
    let path = std::env::temp_dir().join(format!("ar01q-smoke-{}.bin", std::process::id()));
    write_dataset(&path).expect("write frozen spiral dataset");
    let mapped = MappedDataset::open(&path).expect("map frozen spiral dataset");
    assert_eq!(mapped.samples().len(), TOTAL_SAMPLES);
    assert!(
        mapped
            .samples()
            .iter()
            .all(|sample| (sample.target as usize) < CLASSES)
    );
    std::fs::remove_file(path).expect("remove temporary smoke artifact");
}

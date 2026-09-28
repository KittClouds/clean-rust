use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00f::{RunKind, run_kind};

#[test]
fn grouping_causality_smoke_contract() {
    let path =
        std::env::temp_dir().join(format!("adaptive-runtime-ar00f-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    for kind in [
        RunKind::F1RandomFixed,
        RunKind::F4DynamicRandom,
        RunKind::F5StructuralSingletonScore,
        RunKind::F6StructuralCompoundScore,
        RunKind::Width(2),
    ] {
        let result = run_kind(mapped.samples(), kind);
        assert!(result.telemetry.utility_evaluations > 0);
    }
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

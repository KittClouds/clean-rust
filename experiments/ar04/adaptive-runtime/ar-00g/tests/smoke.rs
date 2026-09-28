use adaptive_runtime_ar_00::{MappedDataset, write_dataset};
use adaptive_runtime_ar_00g::{Policy, run};

#[test]
fn temporal_coverage_smoke_contract() {
    let path =
        std::env::temp_dir().join(format!("adaptive-runtime-ar00g-{}.bin", std::process::id()));
    write_dataset(&path).expect("dataset should be writable");
    let mapped = MappedDataset::open(&path).expect("dataset should be mappable");
    for policy in [
        Policy::G0DynamicRandom,
        Policy::G1RoundRobin,
        Policy::G2LowCoverage,
        Policy::G3NoRepeat,
        Policy::G4ForbiddenHotPairs,
        Policy::G5FreshTopology,
    ] {
        let result = run(mapped.samples(), policy);
        assert!(result.telemetry.utility_evaluations > 0);
        assert!(result.coverage.ever_covered_pairs > 0);
    }
    std::fs::remove_file(path).expect("temporary dataset should be removable");
}

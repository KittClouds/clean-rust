use adaptive_runtime_ar_02a_r2::{
    GaussianMappedDataset, R1_METHODS, R1_SEEDS, generate_gaussian_cells,
    run_r1_method_for_commits, write_gaussian_dataset,
};

#[test]
fn mapped_gaussian_task_runs_corrected_k2_short_path() {
    let path = std::env::temp_dir().join(format!("ar02ar1-smoke-{}.bin", std::process::id()));
    write_gaussian_dataset(&path).expect("write deterministic Gaussian-cell dataset");
    let mapped = GaussianMappedDataset::open(&path).expect("map Gaussian-cell dataset");
    assert_eq!(mapped.samples(), generate_gaussian_cells().samples);
    let result = run_r1_method_for_commits(mapped.samples(), R1_METHODS[0], R1_SEEDS[0], 4);
    assert_eq!(result.optimizer_steps, 4);
    assert_eq!(result.regret_audits, 1);
    std::fs::remove_file(path).expect("remove temporary dataset");
}

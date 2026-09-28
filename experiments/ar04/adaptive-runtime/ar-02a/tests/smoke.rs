use adaptive_runtime_ar_02a::{
    AR02A_SEEDS, GaussianMappedDataset, Method, generate_gaussian_cells, run_method,
    write_gaussian_dataset,
};

#[test]
fn mapped_gaussian_cells_and_short_run_are_operational() {
    let path = std::env::temp_dir().join(format!("ar02a-smoke-{}.bin", std::process::id()));
    write_gaussian_dataset(&path).expect("write deterministic Gaussian-cell dataset");
    let mapped = GaussianMappedDataset::open(&path).expect("map Gaussian-cell dataset");
    assert_eq!(mapped.samples(), generate_gaussian_cells().samples);
    let result = run_method(mapped.samples(), Method::SameBatchRandom, AR02A_SEEDS[0]);
    assert_eq!(result.optimizer_steps, 4_800);
    assert!(result.proposal_evaluations > 0);
    assert!(result.compound_evaluations > 0);
    std::fs::remove_file(path).expect("remove temporary smoke dataset");
}

use adaptive_runtime_ar_00h::{BudgetMode, SEEDS, run, xor_samples_for_tests};

#[test]
fn h_smoke_runs_all_budget_views() {
    let samples = xor_samples_for_tests();
    for mode in [
        BudgetMode::EqualSteps,
        BudgetMode::EqualEvaluations,
        BudgetMode::EqualPairEvents,
    ] {
        let width = if mode == BudgetMode::EqualPairEvents {
            2
        } else {
            1
        };
        let result = run(&samples, width, SEEDS[0], mode);
        assert!(result.telemetry.selected_primitives > 0);
        assert!(result.final_accuracy >= 0.5);
    }
}

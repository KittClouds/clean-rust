use adaptive_runtime_ar_01c::{Arm, SEEDS, dataset_for_tests, run};

#[test]
fn all_ar01a_arms_run() {
    let dataset = dataset_for_tests();
    for arm in Arm::ALL {
        let result = run(&dataset.samples, arm, SEEDS[0]);
        assert!(result.curve.len() > 1);
        if arm != Arm::C4AdamW && arm != Arm::C5Sign {
            assert!(result.telemetry.compound_evaluations > 0);
        }
    }
}

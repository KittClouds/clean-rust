use adaptive_runtime_ar_01a::{Arm, SEEDS, dataset_for_tests, run};

#[test]
fn all_ar01a_arms_run() {
    let dataset = dataset_for_tests();
    for arm in Arm::ALL {
        let result = run(&dataset.samples, arm, SEEDS[0]);
        assert!(result.curve.len() > 1);
        if arm != Arm::A0AdamW && arm != Arm::A1Sign {
            assert!(result.telemetry.compound_evaluations > 0);
        }
    }
}

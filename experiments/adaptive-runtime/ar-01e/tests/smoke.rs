use adaptive_runtime_ar_01e::{Arm, SEEDS, dataset_for_tests, run};

#[test]
fn all_ar01e_arms_run() {
    let dataset = dataset_for_tests();
    for arm in Arm::ALL {
        let result = run(&dataset.samples, arm, SEEDS[0]);
        assert!(result.curve.len() > 1);
        if arm != Arm::E12AdamW && arm != Arm::E13Sign {
            assert!(result.telemetry.compound_evaluations > 0);
        }
    }
}

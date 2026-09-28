use adaptive_runtime_ar_01o::{Arm, SEEDS, dataset_for_tests, run};

#[test]
fn inherited_ar01l_arms_run() {
    let dataset = dataset_for_tests();
    for arm in Arm::ALL {
        let result = run(&dataset.samples, arm, SEEDS[0]);
        assert!(result.curve.len() > 1);
        if arm != Arm::G8AdamW && arm != Arm::G9Sign {
            assert!(result.telemetry.compound_evaluations > 0);
        }
    }
}

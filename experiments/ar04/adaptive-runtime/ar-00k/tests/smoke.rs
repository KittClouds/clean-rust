use adaptive_runtime_ar_00k::{Arm, SEEDS, audit_all, run, xor_samples_for_tests};

#[test]
fn k_smoke_runs_all_beams() {
    let samples = xor_samples_for_tests();
    for arm in Arm::ALL {
        let result = run(&samples, arm, SEEDS[0]);
        assert!(result.telemetry.selected_primitives > 0);
        assert!(result.telemetry.utility_evaluations > 0);
    }
    let audit = audit_all(&samples);
    assert_eq!(audit.len(), Arm::ALL.len() * SEEDS.len());
}

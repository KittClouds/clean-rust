use adaptive_runtime_ar_00j::{Arm, SEEDS, on_policy_audit_all, run, xor_samples_for_tests};

#[test]
fn i_smoke_runs_all_scorers() {
    let samples = xor_samples_for_tests();
    for arm in Arm::ALL {
        let result = run(&samples, arm, SEEDS[0]);
        assert!(result.telemetry.selected_primitives > 0);
        assert!(result.telemetry.utility_evaluations > 0);
    }
    let audit = on_policy_audit_all(&samples);
    assert_eq!(audit.len(), Arm::ALL.len() * SEEDS.len());
}

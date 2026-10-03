use obs_open_03bpa::fixtures::qualify;
use obs_open_03bpa::model::{FINAL_STATE, PARENT_ROOT};

#[test]
fn decision_and_parent_are_frozen() {
    assert_eq!(FINAL_STATE, "INFERENCE_PROCEDURE_REQUIRES_REVISION");
    assert_eq!(PARENT_ROOT.len(), 64);
}

#[test]
fn adversarial_semantics_pass_without_real_data() {
    let cases = qualify().unwrap();
    assert_eq!(cases.len(), 6);
    assert!(cases.iter().all(|x| !x.real_session_assumption_established));
}

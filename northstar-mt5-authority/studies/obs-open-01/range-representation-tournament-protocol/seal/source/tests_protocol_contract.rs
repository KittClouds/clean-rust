use obs_open_03bp::contracts::contracts;
use obs_open_03bp::model::*;
use obs_open_03bp::target::predicate;

#[test]
fn protocol_identity_and_firewall_are_frozen() {
    assert_eq!(
        AUTHORITY,
        "OBS_OPEN_03BP_FROZEN_RANGE_REPRESENTATION_TOURNAMENT_V1"
    );
    assert_eq!(D_A_SESSIONS, 154);
    assert_eq!(D_B_SESSIONS, 103);
    assert_eq!(D_C_SESSIONS, 69);
    assert_eq!(RANDOMIZATIONS, 9999);
    assert_eq!(MIN_RELATIVE_BRIER_SKILL, 0.02);
}

#[test]
fn target_is_strict_and_contract_family_is_small() {
    assert!(!predicate(0.0));
    assert!(!predicate(-0.0));
    assert!(predicate(0.0001));
    assert_eq!(contracts().len(), 11);
}

#[test]
fn protocol_text_preserves_identifiability() {
    let p = include_str!("../OBS_OPEN_03B_P_PROTOCOL_V1.md");
    for needle in [
        "not identifiable",
        "lossy quotient",
        "D_B outcomes",
        "D_C remains unopened",
        "No direct RAW-versus-Z test",
    ] {
        assert!(p.contains(needle), "missing {needle}");
    }
}

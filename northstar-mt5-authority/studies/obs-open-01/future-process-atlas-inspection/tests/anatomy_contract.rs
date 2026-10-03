use obs_open_03ai::model::{AUTHORITY, PARENT_ROOT};

#[test]
fn authority_is_descriptive_supplement() {
    assert_eq!(AUTHORITY, "OBS_OPEN_03AI_ATLAS_ANATOMY_SUPPLEMENT_V1");
    assert_eq!(PARENT_ROOT.len(), 64);
}

#[test]
fn causal_identifiability_language_is_frozen() {
    let text = include_str!("../OBS_OPEN_03A_I_PROTOCOL_V1.md");
    for required in [
        "D_B",
        "D_C",
        "Candidate age",
        "retrospective",
        "deterministic aliases",
        "formal inference",
    ] {
        assert!(text.contains(required), "missing {required}");
    }
}

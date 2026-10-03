use obs_open_03bp2t::semantics::{DECISION, stationarity, temporal_contract, thinning, warning};

#[test]
fn temporal_index_is_explicit() {
    let c = temporal_contract();
    assert_eq!(c["hac_lag_unit"], "SELECTED_DB_SESSION_ORDINAL");
    assert_eq!(c["computation_changed_from_p2"], false);
    assert_eq!(
        stationarity()["stationarity_assumption_applies_to"],
        "HASH_THINNED_DB_SCORE_PROCESS"
    );
}

#[test]
fn authority_does_not_expand() {
    assert_eq!(DECISION, "TEMPORAL_INDEX_SEMANTIC_CLARIFICATION_REQUIRED");
    assert_eq!(thinning()["design_randomization"], false);
    assert_eq!(warning()["not_earned"].as_array().unwrap().len(), 3);
}

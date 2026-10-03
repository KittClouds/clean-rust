use serde_json::{Value, json};

pub const DECISION: &str = "TEMPORAL_INDEX_SEMANTIC_CLARIFICATION_REQUIRED";

pub fn temporal_contract() -> Value {
    json!({
        "schema":"HAC_TEMPORAL_INDEX_CONTRACT_V1","source_kind":"ARTIFACT_DECLARED",
        "hac_sequence_order":"D_B sessions sorted by civil_date ascending, then session_id ascending",
        "hac_lag_unit":"SELECTED_DB_SESSION_ORDINAL",
        "hac_pair_eligibility_rule":"for lag ell, pair dense values[j] with values[j-ell] for every j=ell..N-1 after formal eligibility and chronological sort",
        "hac_gap_handling_rule":"parent-session and calendar gaps are recorded but do not change kernel distance or pair weight",
        "bartlett_covariance_denominator":"N","lag_rule":"floor(4*(N/100)^(2/9)); capped at N-1",
        "computation_changed_from_p2":false
    })
}

pub fn stationarity() -> Value {
    json!({
        "schema":"STATIONARITY_TARGET_RECEIPT_V1","source_kind":"ARTIFACT_DECLARED",
        "stationarity_assumption_applies_to":"HASH_THINNED_DB_SCORE_PROCESS",
        "index":"SELECTED_DB_SESSION_ORDINAL",
        "assumption":"The fixed deterministic D_B subsequence score-difference process is directly assumed covariance stationary and weakly dependent in selected-session ordinal.",
        "not_inherited_from":"FULL_DISCOVERY_SESSION_SCORE_PROCESS",
        "unobserved_parent_positions":"not represented in covariance kernel",
        "calendar_intervals":"recorded as metadata; not represented in kernel",
        "status":"SCIENTIFICALLY_DECLARED_NOT_PROVEN_ON_UNOPENED_D_B"
    })
}

pub fn thinning() -> Value {
    json!({
        "schema":"THINNING_AUTHORITY_LEDGER_V1","source_kind":"ARTIFACT_DECLARED",
        "thinning_mechanism":"OUTCOME_BLIND_SALTED_HASH_RANK_PARTITION",
        "authority":"FIXED_DETERMINISTIC_SUBSEQUENCE",
        "outcome_blind_partition":true,"design_randomization":false,"stochastic_independent_thinning":false,"bernoulli_thinning":false,
        "claim":"Outcome blindness prevents target-based assignment; it does not make the realized partition a randomized design or prove stationarity after thinning."
    })
}

pub fn warning() -> Value {
    json!({
        "schema":"ASYMPTOTIC_AUTHORITY_WARNING_V1","source_kind":"ARTIFACT_DECLARED",
        "nominal_alpha":0.05,"synthetic_iid_gaussian_null_rejection":0.061,"synthetic_ar1_rho_0_35_null_rejection":0.07825,
        "classification":"PROCEDURE_QUALIFICATION_CONTEXT_ONLY",
        "earned":"Nominal asymptotic inference under the frozen HAC stochastic assumptions.",
        "not_earned":["FINITE_SAMPLE_5_PERCENT_TYPE_I_CONTROL","DESIGN_BASED_EXACTNESS","EXACT_5_PERCENT_FWER"],
        "holm_authority":"ASYMPTOTIC_UNDER_ADMITTED_ASSUMPTIONS"
    })
}

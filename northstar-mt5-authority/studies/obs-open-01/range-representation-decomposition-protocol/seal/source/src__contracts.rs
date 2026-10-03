use serde_json::{Value, json};

pub fn thing_boundary() -> Value {
    json!({"schema":"THING_002_AUTHORITY_BOUNDARY_LEDGER_V1","source_kind":"ARTIFACT_DECLARED","thing_id":"THING_002","meaning":"UNKNOWN","mechanism":"UNKNOWN","relation_to_THING_001":"UNKNOWN","economic_authority":"NONE","trading_authority":"NONE","empirical_authority_added_by_this_gate":false})
}

pub fn representation_contracts() -> (Value, Value) {
    let zw = json!({"schema":"ZW_REPRESENTATION_CONTRACT_V1","source_kind":"ARTIFACT_DECLARED","representation_id":"RANGE_Z_PLUS_WIDTH_SNAPSHOT_V1","anchor":"RANGE_FREEZE","field_order":["z_open","z_high","z_low","z_close","frozen_width"],"causal_availability":"AT_RANGE_FREEZE_COMMIT","algebra":"RAW_RECONSTRUCTIBLE_FOR_FINITE_W_GT_0","information_relation_to_Z":"ADDS_WIDTH_DEGREE_OF_FREEDOM","probe_equivalence_to_RAW":"NOT_ASSERTED; MULTIPLICATIVE_INTERACTIONS_ARE_NOT_IMPLICIT_IN_LINEAR_LOGIT"});
    let rawz = json!({"schema":"RAWZ_REPRESENTATION_CONTRACT_V1","source_kind":"ARTIFACT_DECLARED","representation_id":"RANGE_RAW_PLUS_Z_SNAPSHOT_V1","anchor":"RANGE_FREEZE","field_order":["frozen_width","open_minus_mid","high_minus_mid","low_minus_mid","close_minus_mid","z_open","z_high","z_low","z_close"],"causal_availability":"AT_RANGE_FREEZE_COMMIT","information_relation_to_RAW":"NO_NEW_UNDERLYING_INFORMATION","probe_relation_to_RAW":"EXPLICIT_NONLINEAR_QUOTIENT_BASIS","maximum_positive_interpretation":"PROBE_ACCESSIBILITY_INCREMENT"});
    (zw, rawz)
}

pub fn protocol() -> Value {
    json!({"schema":"OBS_OPEN_03B2P_PROTOCOL_V1","source_kind":"ARTIFACT_DECLARED","mission":"PROSPECTIVE_REPRESENTATION_DECOMPOSITION_PROTOCOL_FREEZE","object":{"anchor":"RANGE_FREEZE","k":[1,30],"target":"STRICT_ABOVE_FROZEN_MIDPOINT_AT_60M_V1","equality":false},"design_context":["k_or_freeze_coordinate","source_clock_offset_regime"],"primary_wagers":["WIDTH_INFORMATION_INCREMENT","QUOTIENT_ACCESSIBILITY_INCREMENT"],"formal_wager_count":2,"execution_authorized":false,"fresh_confirmation_state":"FRESH_CONFIRMATION_POPULATION_PENDING","D_C_state":"FROZEN_UNOPENED","maximum_authority":"OBS_OPEN_03B2_FROZEN_REPRESENTATION_DECOMPOSITION_PROTOCOL_V1"})
}

pub fn wagers() -> Value {
    json!({"schema":"OBS_OPEN_03B2P_PRIMARY_WAGERS_V1","source_kind":"ARTIFACT_DECLARED","wagers":[
        {"wager_id":"WIDTH_INFORMATION_INCREMENT","parent":"Z","augmented":"Z_PLUS_WIDTH","paired_difference":"B_s(M_Z)-B_s(M_ZW)","relative_skill":"1-B_ZW/B_Z","materiality_floor":0.02,"maximum_interpretation":"WIDTH_PROVIDES_INCREMENTAL_PROBE_ACCESSIBLE_INFORMATION_CONDITIONAL_ON_Z"},
        {"wager_id":"QUOTIENT_ACCESSIBILITY_INCREMENT","parent":"RAW","augmented":"RAW_PLUS_Z","paired_difference":"B_s(M_RAW)-B_s(M_RAWZ)","relative_skill":"1-B_RAWZ/B_RAW","materiality_floor":0.02,"maximum_interpretation":"DETERMINISTIC_QUOTIENT_COORDINATES_INCREASE_ACCESSIBILITY_TO_THE_FROZEN_PROBE"}
    ],"unauthorized_formal_tests":["RAW_VS_Z","RAW_VS_ZW","RAWZ_VS_ZW","RAWZ_VS_Z"],"representation_crown_authorized":false})
}

pub fn probe_contract() -> Value {
    json!({"schema":"OBS_OPEN_03B2P_PROBE_CONTRACT_V1","source_kind":"ARTIFACT_DECLARED","family":"L2_REGULARIZED_LOGISTIC_REGRESSION","sampling_unit":"SESSION","within_session_rows":"30_DEPENDENT_K_COORDINATES","session_aggregate_weight":"EQUAL","row_weight":0.03333333333333333,"score":"BRIER","development_population":"D_A_ONLY","lambda_grid":[0.0001,0.001,0.01,0.1,1.0,10.0],"folds":[[0,30,30,61],[0,61,61,92],[0,92,92,123],[0,123,123,154]],"selection":"MINIMUM_MEAN_VALIDATION_BRIER; TIES_WITHIN_1E-12_USE_LARGEST_LAMBDA","D_B_tuning":0,"D_C_access":0})
}

pub fn materiality_contract() -> Value {
    json!({"schema":"OBS_OPEN_03B2P_MATERIALITY_CONTRACT_V1","source_kind":"ARTIFACT_DECLARED","floor_relative_brier_skill":0.02,"WIDTH_INFORMATION_INCREMENT":"1-B_ZW/B_Z >= 0.02","QUOTIENT_ACCESSIBILITY_INCREMENT":"1-B_RAWZ/B_RAW >= 0.02","authority":"FROZEN_FUTURE_CONFIRMATION_POPULATION","separate_from_formal_inference":true})
}

pub fn inference_contract() -> Value {
    json!({"schema":"OBS_OPEN_03B2P_INFERENCE_CONTRACT_V1","source_kind":"ARTIFACT_DECLARED","authority":"AVERAGE_COMPETENCE_HAC_INFERENCE_V1_IF_FRESH_POPULATION_SUPPORTS_ITS_ASSUMPTIONS","parameter":"mu=E[d_s]","null":"mu<=0","alternative":"mu>0","estimator":"BARTLETT_HAC_LONG_RUN_VARIANCE","lag_rule":"floor(4*(N/100)^(2/9))","reference":"ASYMPTOTIC_NORMAL_ONE_SIDED","multiplicity":{"method":"HOLM_BONFERRONI","family_size":2,"nominal_alpha":0.05},"required_assumptions":["fixed_D_A_trained_models_throughout_evaluation","covariance_stationarity_of_the_exact_fresh_population_score_difference_process","finite_moments","weak_dependence","summable_autocovariances","positive_finite_long_run_variance"],"warnings":{"finite_sample_5_percent_control":"NOT_EARNED","design_based_exactness":"NOT_EARNED","exact_5_percent_FWER":"NOT_EARNED"},"procedure_qualification_context":{"iid_gaussian_null_rejection":0.061,"stationary_AR1_rho_0_35_null_rejection":0.07825,"classification":"PROCEDURE_QUALIFICATION_CONTEXT_ONLY"},"replacement_method_selection_during_execution":"FORBIDDEN"})
}

pub fn temporal_contract() -> Value {
    json!({"schema":"OBS_OPEN_03B2P_TEMPORAL_INDEX_REQUIREMENT_V1","source_kind":"ARTIFACT_DECLARED","population":"D_D_FRESH_PROSPECTIVE_CONTIGUOUS_V1","sequence_order":"CHRONOLOGICALLY_SORTED_FORMALLY_ELIGIBLE_PROSPECTIVE_SESSIONS","lag_unit":"ELIGIBLE_PROSPECTIVE_SESSION_ORDINAL","lag_one":"ADJACENT_FORMALLY_ELIGIBLE_SESSIONS_IN_THE_FROZEN_D_D_SEQUENCE","parent_session_gaps":"RECORDED_METADATA_ONLY","calendar_gaps":"RECORDED_METADATA_ONLY","stationarity_target":"FUTURE_D_D_PAIRED_SESSION_SCORE_DIFFERENCE_PROCESS","thinning_authority":"NONE; PROSPECTIVE_CONTIGUOUS_OUTCOME_BLIND_ACCRUAL","inherits_P2T_selected_DB_ordinal_semantics":false,"target_or_score_based_clock_selection":false})
}

pub fn population_contract() -> Value {
    json!({"schema":"D_D_FRESH_PROSPECTIVE_CONTIGUOUS_V1","source_kind":"ARTIFACT_DECLARED","state":"FRESH_CONFIRMATION_POPULATION_PENDING","earliest_civil_session_date":"2026-08-17","membership_rule":"EVERY_OTHERWISE_ADMISSIBLE_NORMAL_SESSION_IN_CHRONOLOGICAL_ORDER_UNDER_EXISTING_SOURCE_CLOCK_CALENDAR_AND_COVERAGE_AUTHORITY","outcome_blind":true,"contiguous_in_admissible_session_chronology":true,"stop_rule":"EARLIEST_CHRONOLOGICAL_PREFIX_WITH_AT_LEAST_80_FORMALLY_COMPLETE_SESSIONS_AND_AT_LEAST_20_COMPLETE_SESSIONS_IN_EACH_ADMITTED_OFFSET_REGIME","minimum_formally_complete_sessions":80,"minimum_complete_per_offset_regime":20,"incomplete_sessions":"RETAIN_WITH_TYPED_REASON; DO_NOT_COUNT_AS_FORMALLY_COMPLETE","D_C_membership_merge":"FORBIDDEN","execution_authorized_now":false})
}

pub fn freshness_ledger() -> Value {
    json!({"schema":"OBS_OPEN_03B2P_FRESHNESS_LEDGER_V1","source_kind":"ARTIFACT_DECLARED","D_A":{"role":"DEVELOPMENT_ONLY","new_models_allowed":true},"D_B":{"role":"HYPOTHESIS_GENERATION_AUTHORITY_ONLY","new_target_applications":0,"new_target_values_read":0,"new_scores":0,"new_tuning":0},"D_C":{"state":"FROZEN_UNOPENED","membership_decoding":0,"observations_read":0,"outcomes_computed":0,"outcomes_read":0},"D_D":{"membership_materialized":0,"target_derivation_application":"UNOPENED","target_values":"UNREAD","representation_scores":"UNOPENED","formal_decisions":"UNOPENED"}})
}

pub fn parked_questions() -> Value {
    json!({"schema":"OBS_OPEN_03B2P_PARKED_QUESTIONS_V1","source_kind":"ARTIFACT_DECLARED","questions":["OBS_OPEN_03C_CAUSAL_HISTORY_INCREMENTALITY","OUTCOME_HORIZON_COMPETENCE_SURFACE","CROSS_INSTRUMENT_TRANSPORT","THING_001_X_THING_002","LITERATURE_TRIANGULATION"],"execution_authorized":false})
}

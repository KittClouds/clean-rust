use crate::model::*;
use serde_json::{Value, json};

pub fn contracts() -> Vec<(&'static str, Value)> {
    vec![
        (
            "TARGET_CONTRACT_V1.json",
            json!({
                "schema":"STRICT_ABOVE_FROZEN_MIDPOINT_AT_60M_V1","anchor":"RANGE_FREEZE",
                "registry_binding":{"outcome_code":101,"representation":"RAW_PRICE","horizon_minutes":TARGET_HORIZON_MINUTES,"predicate":"value > 0","equality":false},
                "availability":"OBSERVED_COMPLETE with support_bars=60 and outcome_known_at=freeze_commit_time+3600",
                "new_outcome_family":false,"economic_semantics":false
            }),
        ),
        (
            "RANGE_DESIGN_CONTEXT_V1.json",
            json!({
                "schema":"RANGE_DESIGN_CONTEXT_V1","fields":["k_categorical_reference_k01","source_clock_offset_regime_reference_plus120"],
                "k_semantics":"COMPOSITE_DESIGN_AND_FREEZE_CLOCK_COORDINATE","evaluation_clock":"k+60 minutes after 09:30",
                "excluded":["market_geometry","future_values","candidate_history","redundant_clock_coordinates"]
            }),
        ),
        (
            "RANGE_RAW_SNAPSHOT_V1.json",
            json!({
                "schema":"RANGE_RAW_SNAPSHOT_V1","known_at":"freeze_commit_time","fields":["width","freeze_bar_open_minus_midpoint","freeze_bar_high_minus_midpoint","freeze_bar_low_minus_midpoint","freeze_bar_close_minus_midpoint"],
                "units":"SOURCE_PRICE_UNIT","freeze_bar":"instrument_inclusive_end_bar = configured_end - 60 seconds",
                "excluded":["absolute_midpoint","absolute_price_level","pre_freeze_path","candidate_history","future_information"]
            }),
        ),
        (
            "RANGE_Z_SNAPSHOT_V1.json",
            json!({
                "schema":"RANGE_Z_SNAPSHOT_V1","known_at":"freeze_commit_time","fields":["z_open","z_high","z_low","z_close"],
                "transform":"2*(freeze_bar_value-midpoint)/width","width_field_included":false,"degenerate_width":"NOT_EVALUABLE_DEGENERATE_RANGE",
                "excluded":["width","absolute_midpoint","absolute_price_level","pre_freeze_path","candidate_history","future_information"]
            }),
        ),
        (
            "REPRESENTATION_RELATION_AUDIT_V1.json",
            json!({
                "schema":"REPRESENTATION_RELATION_AUDIT_V1","audit_precedes_modeling":true,
                "classifications":["INFORMATIONALLY_EQUIVALENT_GIVEN_CONTEXT","LOSSY_QUOTIENT","CONDITIONALLY_INVERTIBLE","NON_EQUIVALENT","NOT_EVALUABLE"],
                "interpretation_law":"If equivalent given context, score differences are PROBE_ACCESSIBILITY_DIFFERENCE only."
            }),
        ),
        (
            "PROBE_CONTRACT_V1.json",
            json!({
                "schema":"L2_LOGISTIC_PROBE_V1","arms":["DESIGN_CONTEXT","DESIGN_CONTEXT_PLUS_RAW","DESIGN_CONTEXT_PLUS_Z"],
                "numeric":"f64","objective":"weighted binary log loss + lambda/2 * non_intercept_L2","optimizer":"deterministic damped Newton with Cholesky",
                "max_iterations":100,"gradient_infinity_tolerance":1e-10,"objective_relative_tolerance":1e-12,"max_step_halvings":50,
                "regularization_grid":[1e-4,1e-3,1e-2,1e-1,1.0,10.0],"regularize_intercept":false,
                "standardization":"representation continuous fields only; fit on each D_A training fold; final fit on all admitted D_A",
                "failed_fit":"LAMBDA_INELIGIBLE; all failed => PROBE_EXECUTION_FAILURE"
            }),
        ),
        (
            "D_A_TRAINING_CONTRACT_V1.json",
            json!({
                "schema":"D_A_TRAINING_CONTRACT_V1","sessions":D_A_SESSIONS,"weight_per_complete_anchor":1.0/30.0,
                "selection":"four expanding-window chronological validation folds after first 30 sessions","folds":[[30,31],[61,31],[92,31],[123,31]],
                "metric":"mean session Brier over validation sessions","tie_tolerance":1e-12,"tie_break":"largest lambda",
                "final_refit":"all admitted complete D_A sessions","D_B_involvement":false
            }),
        ),
        (
            "D_B_EVALUATION_CONTRACT_V1.json",
            json!({
                "schema":"D_B_EVALUATION_CONTRACT_V1","sessions_declared":D_B_SESSIONS,"one_shot":true,"no_refit":true,"no_recalibration":true,
                "complete_session_rule":"all 30 range anchors have valid snapshot and observed-complete 60-minute target",
                "support_floor":{"complete_sessions":D_B_MIN_COMPLETE_SESSIONS,"plus120":D_B_MIN_OFFSET_SESSIONS,"plus180":D_B_MIN_OFFSET_SESSIONS},
                "failure":"INSUFFICIENT_FORMAL_SUPPORT"
            }),
        ),
        (
            "SCORE_CONTRACT_V1.json",
            json!({
                "schema":"SESSION_WEIGHTED_BRIER_SCORE_V1","per_session":"mean over exactly 30 k anchors","population":"mean over complete sessions",
                "delta_brier":"B(M0)-B(MR)","relative_skill":"1-B(MR)/B(M0)","baseline_zero":"NOT_EVALUABLE_BASELINE_BRIER_ZERO",
                "material_floor":MIN_RELATIVE_BRIER_SKILL,"diagnostics_non_claim_bearing":true
            }),
        ),
        (
            "INFERENCE_CONTRACT_V1.json",
            json!({
                "schema":"PAIRED_SESSION_SIGN_REFLECTION_V1","tests":["RAW_VS_DESIGN","Z_VS_DESIGN"],"alternative":"mean paired Brier improvement > 0",
                "statistic":"sqrt(N)*mean(d)/sample_sd(d)","zero_variance":"NOT_EVALUABLE_ZERO_VARIANCE","randomizations":RANDOMIZATIONS,"seed":SEED,
                "monte_carlo":"plus-one","p_min":1.0/(RANDOMIZATIONS as f64+1.0),"wilson_confidence":0.99,"wilson_counts":"adjusted successes=exceedances+1, adjusted trials=B+1",
                "multiplicity":"Holm-Bonferroni across exactly two tests at alpha 0.05","tie_break":"RAW_VS_DESIGN before Z_VS_DESIGN",
                "unresolved":"99 percent Wilson interval straddles applicable Holm threshold"
            }),
        ),
        (
            "TOURNAMENT_DECISION_V1.json",
            json!({
                "schema":"TOURNAMENT_DECISION_V1","pays_rent":"Holm pass AND relative Brier skill >= 0.02",
                "states":["NEITHER_PAYS_RENT","RAW_ONLY_PAYS_RENT","Z_ONLY_PAYS_RENT","BOTH_PAY_RENT","NUMERICAL_DECISION_UNRESOLVED","INSUFFICIENT_FORMAL_SUPPORT","PROBE_EXECUTION_FAILURE"],
                "precedence":["PROBE_EXECUTION_FAILURE","INSUFFICIENT_FORMAL_SUPPORT","NUMERICAL_DECISION_UNRESOLVED","pay_rent_state"],
                "forbidden":["RAW_SUPERIOR_TO_Z","Z_SUPERIOR_TO_RAW","RAW_PLUS_Z_COMPLEMENTARITY"]
            }),
        ),
    ]
}

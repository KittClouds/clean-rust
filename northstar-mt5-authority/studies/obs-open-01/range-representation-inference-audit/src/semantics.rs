use crate::model::{AuditFinding, FINAL_STATE, ParentEvidence};
use serde_json::{Value, json};

pub fn audit(
    parent: &ParentEvidence,
) -> Result<Vec<(&'static str, Value)>, Box<dyn std::error::Error>> {
    let contract = &parent.inference_contract;
    require(
        contract["alternative"].as_str() == Some("mean paired Brier improvement > 0"),
        "ALTERNATIVE_DRIFT",
    )?;
    let current_null = "NOT_EXPLICITLY_DECLARED";
    let operative_null =
        "JOINT_COORDINATE_WISE_REFLECTION_INVARIANCE_OF_SESSION_SCORE_DIFFERENCE_VECTOR";
    let findings = findings(parent);
    Ok(vec![
        (
            "INFERENCE_NULL_AUDIT_V1.json",
            json!({
                "schema":"INFERENCE_NULL_AUDIT_V1","source_kind":"MACHINE_DERIVED",
                "parent_schema":contract["schema"],"declared_alternative":contract["alternative"],
                "exact_current_null_statement":current_null,
                "mean_null":"E[d_s^R]=0",
                "mean_null_explicitly_declared":false,
                "operative_null_required_by_intended_procedure":operative_null,
                "marginal_symmetry_sufficient":false,"global_reflection_invariance_sufficient":false,
                "coordinatewise_joint_reflection_invariance_declared":false,
                "classification":"REQUIRED_INVARIANCE_NULL_ABSENT","findings":findings
            }),
        ),
        (
            "REFLECTION_GROUP_RECEIPT.json",
            json!({
                "schema":"REFLECTION_GROUP_RECEIPT_V1","source_kind":"MACHINE_DERIVED",
                "REFLECTION_GROUP":"SESSION_COORDINATEWISE",
                "classification_basis":"schema PAIRED_SESSION_SIGN_REFLECTION_V1 and protocol phrase paired session-level sign-reflection",
                "intended_group":"all 2^n independent coordinate sign transformations on the session difference vector",
                "monte_carlo_draws":contract["randomizations"],"seed":contract["seed"],
                "sign_vector_generation_algorithm":"NOT_EXPLICITLY_DECLARED",
                "sampling_with_or_without_replacement":"NOT_EXPLICITLY_DECLARED",
                "identity_or_observed_configuration_handling":"NOT_EXPLICITLY_DECLARED",
                "group_specification":"INCOMPLETE","status":"FAIL"
            }),
        ),
        (
            "DEPENDENCE_ASSUMPTION_RECEIPT.json",
            json!({
                "schema":"DEPENDENCE_ASSUMPTION_RECEIPT_V1","source_kind":"MACHINE_DERIVED",
                "chronological_sessions":true,"declared_dependence_model":"NONE",
                "required_authority_for_session_coordinatewise_reflection":["INDEPENDENT_SYMMETRIC_SESSION_DIFFERENCES","or JOINT_COORDINATE_REFLECTION_INVARIANCE"],
                "independent_session_differences_declared":false,
                "joint_coordinate_reflection_invariance_declared":false,
                "serial_dependence_handling_declared":false,
                "classification":"NO_JUSTIFICATION_ESTABLISHED",
                "answer":"The sealed null does not license independent reflection of one chronological session while leaving related sessions unchanged.",
                "status":"FAIL"
            }),
        ),
        (
            "EXACTNESS_BASIS_RECEIPT.json",
            json!({
                "schema":"EXACTNESS_BASIS_RECEIPT_V1","source_kind":"MACHINE_DERIVED",
                "EXACTNESS_BASIS":"CONDITIONAL_ON_REFLECTION_INVARIANCE",
                "design_based_assignment_authority":false,
                "model_based_symmetry_authority_declared":false,
                "parent_exact_word_occurrences":parent.exact_word_occurrences,
                "parent_claims_exact_test":false,
                "classification":"ONLY_CONDITIONAL_MODEL_BASED_EXACTNESS_COULD_APPLY_BUT_ITS_ASSUMPTION_IS_ABSENT",
                "design_based_exactness_forbidden":true,"status":"FAIL"
            }),
        ),
        (
            "ESTIMAND_INFERENCE_TRANSFORMATION_UNIT_RECEIPT.json",
            json!({
                "schema":"ESTIMAND_INFERENCE_TRANSFORMATION_UNIT_RECEIPT_V1","source_kind":"ARTIFACT_DECLARED",
                "ESTIMAND_UNIT":"SESSION","estimand":"d_s^R=B_s(M0)-B_s(MR)",
                "INFERENCE_UNIT":"SESSION","basis":"studentized mean across paired session differences",
                "TRANSFORMATION_UNIT":"SESSION_COORDINATE","basis":"intended paired session-level sign reflection",
                "units_are_logically_distinct":true,"current_units_happen_to_match_at_session_level":true,
                "transformation_authority_established":false,"status":"FAIL"
            }),
        ),
        (
            "MEAN_INTERPRETATION_AUDIT.json",
            json!({
                "schema":"MEAN_INTERPRETATION_AUDIT_V1","source_kind":"MACHINE_DERIVED",
                "advertised_alternative":"mean paired Brier improvement > 0",
                "generic_exact_mean_null_test_licensed":false,
                "reason":"E[d_s]=0 alone does not imply joint coordinate-wise reflection invariance, and chronological dependence authority is undeclared.",
                "permitted_current_interpretation":"No formal interpretation is executable until a null, transformation group, and dependence authority are prospectively frozen.",
                "status":"FAIL"
            }),
        ),
        (
            "MATERIALITY_INFERENCE_AUTHORITY_LEDGER.json",
            json!({
                "schema":"MATERIALITY_INFERENCE_AUTHORITY_LEDGER_V1","source_kind":"ARTIFACT_DECLARED",
                "materiality":{"relative_brier_skill":"1-B(MR)/B(M0)","absolute_delta_brier":"B(M0)-B(MR)","floor":0.02,"authority":"FROZEN_POPULATION_DESCRIPTIVE_MATERIALITY","preserved":true},
                "formal_inference":{"authority":"CURRENTLY_NOT_EXECUTABLE","reason":"INFERENCE_PROCEDURE_REQUIRES_REVISION"},
                "MATERIALITY_AUTHORITY_NOT_EQUAL_INFERENTIAL_AUTHORITY":true,
                "materiality_does_not_rescue_inference":true,"inference_failure_does_not_erase_descriptive_scores":true,
                "status":"PASS"
            }),
        ),
        (
            "PREOPEN_AUDIT_DECISION.json",
            json!({
                "schema":"PREOPEN_AUDIT_DECISION_V1","source_kind":"MACHINE_DERIVED",
                "state":FINAL_STATE,
                "parent_root_remains_historical_authority":true,
                "parent_root_remains_executable_for_D_B_formal_inference":false,
                "new_protocol_root_required_before_D_B_open":true,
                "replacement_selected":false,
                "D_B_may_be_opened":false,
                "reason_codes":["INFERENCE_NULL_ABSENT","SIGN_GENERATOR_UNDERSPECIFIED","CHRONOLOGICAL_DEPENDENCE_AUTHORITY_ABSENT","GENERIC_MEAN_NULL_NOT_LICENSED"],
                "status":"FAIL_CLOSED"
            }),
        ),
        (
            "PROCEDURAL_DEFICIENCY_REPORT.json",
            json!({
                "schema":"PROCEDURAL_DEFICIENCY_REPORT_V1","source_kind":"MACHINE_DERIVED",
                "deficiencies":[
                    {"id":"NULL","statement":"No formal null or invariance statement is declared."},
                    {"id":"GROUP","statement":"The intended session-coordinate group is named only informally; sign-vector generation is not executable."},
                    {"id":"DEPENDENCE","statement":"No assumption licenses coordinate-wise transformations of chronological sessions."},
                    {"id":"MEAN","statement":"A zero mean is not sufficient for the intended finite-sample reflection reference distribution."}
                ],
                "candidate_methods_not_selected":["CALENDAR_BLOCK_REFLECTION","DEPENDENCE_AWARE_BOOTSTRAP","HAC_STUDENTIZED_INFERENCE"],
                "support_floors_preserved":{"minimum_complete_D_B_sessions":80,"minimum_per_offset_regime":20},
                "semantic_only_clarification_sufficient":false,
                "procedure_revision_required":true
            }),
        ),
    ])
}

fn findings(parent: &ParentEvidence) -> Vec<AuditFinding> {
    vec![
        AuditFinding {
            finding_id: "PA-001",
            source_kind: "ARTIFACT_DECLARED",
            state: "OBSERVED",
            statement: "The parent contract advertises a positive mean paired Brier improvement alternative.",
            evidence: vec![parent.inference_contract["alternative"].to_string()],
        },
        AuditFinding {
            finding_id: "PA-002",
            source_kind: "MACHINE_DERIVED",
            state: "DEFICIENCY",
            statement: "The parent contract contains no explicit formal null or joint invariance statement.",
            evidence: vec!["INFERENCE_CONTRACT_V1.json exhaustive field audit".into()],
        },
        AuditFinding {
            finding_id: "PA-003",
            source_kind: "MACHINE_DERIVED",
            state: "DEFICIENCY",
            statement: "The intended coordinate-wise reflection procedure requires stronger authority than a zero-mean statement.",
            evidence: vec![
                "ZERO_MEAN_ASYMMETRIC fixture".into(),
                "GLOBAL_NOT_COORDINATEWISE fixture".into(),
            ],
        },
        AuditFinding {
            finding_id: "PA-004",
            source_kind: "ARTIFACT_DECLARED",
            state: "ABSENT",
            statement: "The sealed parent does not use exactness language for this test.",
            evidence: vec![format!(
                "exact_word_occurrences={}",
                parent.exact_word_occurrences.len()
            )],
        },
    ]
}

fn require(ok: bool, err: &'static str) -> Result<(), Box<dyn std::error::Error>> {
    if ok { Ok(()) } else { Err(err.into()) }
}

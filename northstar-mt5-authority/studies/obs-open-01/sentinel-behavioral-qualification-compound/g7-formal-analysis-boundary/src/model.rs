use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PropertyRecord {
    pub property_id: &'static str,
    pub problem_signature_id: &'static str,
    pub semantic_target: &'static str,
    pub semantic_authority_source: &'static str,
    pub fixed_parameters: &'static [&'static str],
    pub variable_axes: &'static [&'static str],
    pub promise_domain: &'static str,
    pub input_encoding: &'static str,
    pub effective_presentation_status: &'static str,
    pub analysis_route_id: &'static str,
    pub formalism_fit_status: &'static str,
    pub theorem_or_result: &'static str,
    pub theorem_preconditions: &'static [&'static str],
    pub reduction_direction: &'static str,
    pub reduction_effective: bool,
    pub property_preservation: &'static str,
    pub property_reflection: &'static str,
    pub metatheoretic_status: &'static str,
    pub certification_authority: &'static str,
    pub search_or_decision_authority: &'static str,
    pub certificate_authority: &'static str,
    pub soundness: &'static str,
    pub completeness: &'static str,
    pub termination: &'static str,
    pub positive_result_authority: &'static str,
    pub negative_result_authority: &'static str,
    pub approximation_transfer_rule_ids: &'static [&'static str],
    pub failure_boundary: &'static str,
    pub safe_downstream_use: &'static [&'static str],
    pub forbidden_downstream_inference: &'static [&'static str],
    pub evidence_classes: &'static [&'static str],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FixtureResult {
    pub fixture_id: &'static str,
    pub expected: &'static str,
    pub observed: &'static str,
    pub status: &'static str,
    pub earns_metatheorem: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MachineryPermission {
    pub problem_signature_id: &'static str,
    pub permissions: &'static [&'static str],
    pub authoritative_output: &'static [&'static str],
    pub forbidden_output: &'static [&'static str],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct InvariantLanguage {
    pub invariant_language_id: &'static str,
    pub syntax: &'static str,
    pub semantic_invariance: &'static str,
    pub inductiveness_checking: &'static str,
    pub authority_boundary: &'static str,
}

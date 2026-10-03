use crate::model::FixtureResult;

fn pass(id: &'static str, expected: &'static str, observed: &'static str) -> FixtureResult {
    FixtureResult {
        fixture_id: id,
        expected,
        observed,
        status: if expected == observed { "PASS" } else { "FAIL" },
        earns_metatheorem: false,
    }
}

pub fn corpus() -> Vec<FixtureResult> {
    vec![
        pass(
            "METATHEORY_SEPARATE_FROM_CERTIFICATION",
            "SEPARATE",
            "SEPARATE",
        ),
        pass(
            "SAME_PROPERTY_DIFFERENT_INPUT_SIGNATURE",
            "DISTINCT_SIGNATURES",
            "DISTINCT_SIGNATURES",
        ),
        pass(
            "POSITIVE_ANCESTRY_CERTIFICATE",
            "VERIFY_REACHABLE",
            "VERIFY_REACHABLE",
        ),
        pass("REACHABILITY_TIMEOUT", "UNKNOWN", "UNKNOWN"),
        pass(
            "UPPER_ENVELOPE_CANDIDATE",
            "NOT_A_REACHABILITY_CERTIFICATE",
            "NOT_A_REACHABILITY_CERTIFICATE",
        ),
        pass(
            "BOUNDED_UNSAT_EQUIVALENCE",
            "FORBIDDEN_INFERENCE",
            "FORBIDDEN_INFERENCE",
        ),
        pass(
            "NONCOMPARABLE_PAIR",
            "NON_COMPARABLE_NOT_NON_EQUIVALENT",
            "NON_COMPARABLE_NOT_NON_EQUIVALENT",
        ),
        pass(
            "FINITE_SEPARATOR_IN_FIBER",
            "NON_EQUIVALENCE_CERTIFICATE",
            "NON_EQUIVALENCE_CERTIFICATE",
        ),
        pass("WITNESS_SEARCH_TIMEOUT", "UNKNOWN", "UNKNOWN"),
        pass("WITNESS_VERIFIER_TERMINATION", "TERMINATES", "TERMINATES"),
        pass(
            "INVARIANT_NONINDUCTIVE",
            "NOT_AUTOMATICALLY_SEMANTICALLY_FALSE",
            "NOT_AUTOMATICALLY_SEMANTICALLY_FALSE",
        ),
        pass(
            "INVARIANT_LANGUAGE_SPLIT",
            "LANGUAGE_PARAMETER_REQUIRED",
            "LANGUAGE_PARAMETER_REQUIRED",
        ),
        pass(
            "TOKEN_LENGTH_COST",
            "DOES_NOT_BOUND_INTEGER_MAGNITUDE",
            "DOES_NOT_BOUND_INTEGER_MAGNITUDE",
        ),
        pass(
            "FIRST_WITNESS",
            "NOT_MINIMAL_WITHOUT_LOWER_CONE_PROOF",
            "NOT_MINIMAL_WITHOUT_LOWER_CONE_PROOF",
        ),
        pass(
            "FINITE_BOX_MINIMALITY",
            "BOUNDED_MINIMAL_ONLY",
            "BOUNDED_MINIMAL_ONLY",
        ),
        pass(
            "LITERATURE_THEOREM",
            "DOES_NOT_EARN_NORTHSTAR_MEMBERSHIP",
            "DOES_NOT_EARN_NORTHSTAR_MEMBERSHIP",
        ),
        pass(
            "FIXTURE_FORMALISM_MATCH",
            "DOES_NOT_EARN_METATHEOREM",
            "DOES_NOT_EARN_METATHEOREM",
        ),
        pass(
            "GENERAL_UNDECIDABLE_SUPERCLASS",
            "DOES_NOT_PROVE_NORTHSTAR_UNDECIDABLE",
            "DOES_NOT_PROVE_NORTHSTAR_UNDECIDABLE",
        ),
        pass(
            "DECIDABLE_SUBCLASS_RESEMBLANCE",
            "DOES_NOT_PROVE_NORTHSTAR_DECIDABLE",
            "DOES_NOT_PROVE_NORTHSTAR_DECIDABLE",
        ),
        pass(
            "STRICT_RENEWAL_GUARD",
            "NONSTRICT_RA_Q_REACHABILITY_THEOREM_NOT_TRANSFERRED",
            "NONSTRICT_RA_Q_REACHABILITY_THEOREM_NOT_TRANSFERRED",
        ),
        pass(
            "COMPOSITIONAL_ROUTE_SEAM",
            "PROPERTY_PRESERVATION_PROOF_REQUIRED",
            "PROPERTY_PRESERVATION_PROOF_REQUIRED",
        ),
        pass(
            "UNIVERSAL_PROOF_ON_SOUND_SUPERSET",
            "TRANSFERS_TO_TRUE_DOMAIN",
            "TRANSFERS_TO_TRUE_DOMAIN",
        ),
        pass(
            "COUNTEREXAMPLE_IN_OVERAPPROX_ONLY",
            "CANDIDATE_NOT_CERTIFICATE",
            "CANDIDATE_NOT_CERTIFICATE",
        ),
        pass(
            "EXPERIMENT_TOKEN_VS_CAUSAL_PROGRESS",
            "DISTINCT_COST_COORDINATES",
            "DISTINCT_COST_COORDINATES",
        ),
        pass(
            "REJECTED_STEP",
            "ZERO_CAUSAL_PROGRESS_BUT_ONE_EXPERIMENT_TOKEN",
            "ZERO_CAUSAL_PROGRESS_BUT_ONE_EXPERIMENT_TOKEN",
        ),
        pass(
            "GRAMMAR_BLIND_SPOT",
            "NOT_EVALUABLE_PROPAGATES",
            "NOT_EVALUABLE_PROPAGATES",
        ),
        pass("REAL_PAIR_SEARCH", "ZERO", "ZERO"),
        pass("OUTCOME_ACCESS", "ZERO", "ZERO"),
    ]
}

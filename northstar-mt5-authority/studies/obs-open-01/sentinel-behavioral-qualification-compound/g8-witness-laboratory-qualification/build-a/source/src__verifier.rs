use crate::THETA_STAR_ID;
use crate::authority::{
    FIBER_CERTIFICATE_SCHEMA, UNIVERSAL_PROOF_SYSTEM_ID, expected_binding, hash_json,
    verify_synthetic_fiber_certificate,
};
use crate::model::{
    AuthorityVerdict, CoverageReceipt, DerivedClaims, FiniteMachine, FrozenComparison,
    NeutralToken, SeparatorCertificate, SyntheticMachine, UniversalProof, VerificationResult,
};
use crate::ranking::{finite_shell, rank_key};
use bitvec::prelude::*;
use hashbrown::HashSet;

const MISMATCH_ID: &str = "SYNTHETIC_PROTECTED_VALUE";
const LAMBDA_ID: &str = "RELATIVE_COMPLETED_BAR_COUPLING_V1";
const M_ID: &str = "SYNTHETIC_ORDER_PRESERVING_CORRESPONDENCE_V1";

fn unknown(code: &str) -> VerificationResult {
    VerificationResult {
        accepted: false,
        code: code.into(),
        verdict: AuthorityVerdict::Unknown,
        recomputed: None,
    }
}

pub fn derive_claims(
    comparison: &FrozenComparison,
    tokens: &[NeutralToken],
) -> Result<DerivedClaims, &'static str> {
    if comparison.left_start >= comparison.left_machine.states.len()
        || comparison.right_start >= comparison.right_machine.states.len()
    {
        return Err("IMPOSSIBLE_STARTING_CONFIGURATION");
    }
    let mut left = comparison.left_start;
    let mut right = comparison.right_start;
    let mut left_states = vec![left];
    let mut right_states = vec![right];
    let mut left_values = vec![comparison.left_machine.states[left].protected_value];
    let mut right_values = vec![comparison.right_machine.states[right].protected_value];
    let mut mismatch = (left_values[0] != right_values[0]).then_some(0);
    for (index, token) in tokens.iter().enumerate() {
        if !token.is_source_valid() {
            return Err("ILLEGAL_CONTINUATION_SOURCE_GRAMMAR");
        }
        left = comparison
            .left_machine
            .next(left, token)
            .ok_or("ILLEGAL_LEFT_CONTINUATION")?;
        right = comparison
            .right_machine
            .next(right, token)
            .ok_or("ILLEGAL_RIGHT_CONTINUATION")?;
        left_states.push(left);
        right_states.push(right);
        left_values.push(
            comparison
                .left_machine
                .states
                .get(left)
                .ok_or("INVALID_LEFT_TRANSITION_TARGET")?
                .protected_value,
        );
        right_values.push(
            comparison
                .right_machine
                .states
                .get(right)
                .ok_or("INVALID_RIGHT_TRANSITION_TARGET")?
                .protected_value,
        );
        if mismatch.is_none() && left_values[index + 1] != right_values[index + 1] {
            mismatch = Some(index + 1);
        }
    }
    Ok(DerivedClaims {
        left_state_trace: left_states,
        right_state_trace: right_states,
        protected_trace_left: left_values,
        protected_trace_right: right_values,
        first_mismatch_experiment_ordinal: mismatch,
        mismatch_observable_id: mismatch.map(|_| MISMATCH_ID.into()),
    })
}

pub fn make_certificate(
    comparison: FrozenComparison,
    tokens: Vec<NeutralToken>,
    note: &str,
) -> Result<SeparatorCertificate, &'static str> {
    let claimed = derive_claims(&comparison, &tokens)?;
    Ok(SeparatorCertificate {
        binding: expected_binding(),
        comparison,
        neutral_token_sequence: tokens,
        claimed,
        metadata_note: note.into(),
    })
}

pub fn verify_separator(certificate: &SeparatorCertificate) -> VerificationResult {
    if certificate.binding != expected_binding() {
        return unknown("AUTHORITY_LINEAGE_MISMATCH");
    }
    let comparison = &certificate.comparison;
    if comparison.theta_star_id != THETA_STAR_ID
        || comparison.lambda_policy_id != LAMBDA_ID
        || comparison.initial_correspondence_id != M_ID
    {
        return unknown("FROZEN_COMPARISON_CONTRACT_MISMATCH");
    }
    if comparison.fiber_certificate.schema_id != FIBER_CERTIFICATE_SCHEMA
        || !verify_synthetic_fiber_certificate(
            &comparison.fiber_certificate,
            &comparison.left_machine,
            &comparison.right_machine,
        )
    {
        return unknown("FIBER_QUALIFICATION_MISSING_OR_INVALID");
    }
    let recomputed = match derive_claims(comparison, &certificate.neutral_token_sequence) {
        Ok(value) => value,
        Err(code) => return unknown(code),
    };
    if recomputed != certificate.claimed {
        return unknown("DERIVED_CLAIM_MISMATCH");
    }
    if recomputed.first_mismatch_experiment_ordinal.is_none() {
        return VerificationResult {
            accepted: false,
            code: "NO_PROTECTED_MISMATCH".into(),
            verdict: AuthorityVerdict::Unknown,
            recomputed: Some(recomputed),
        };
    }
    VerificationResult {
        accepted: true,
        code: "VERIFIED_FINITE_SEPARATOR".into(),
        verdict: AuthorityVerdict::BehaviorallyNonEquivalentWithVerifiedSeparator,
        recomputed: Some(recomputed),
    }
}

pub fn verify_ancestry(
    machine: &SyntheticMachine,
    start: usize,
    tokens: &[NeutralToken],
    claimed_states: &[usize],
) -> VerificationResult {
    if start >= machine.states.len() || claimed_states.first() != Some(&start) {
        return unknown("INVALID_ANCESTRY_START");
    }
    let mut state = start;
    let mut recomputed = vec![state];
    for token in tokens {
        if !token.is_source_valid() {
            return unknown("ILLEGAL_ANCESTRY_TOKEN");
        }
        state = match machine.next(state, token) {
            Some(next) => next,
            None => return unknown("ANCESTRY_TRANSITION_REJECTED"),
        };
        if state >= machine.states.len() {
            return unknown("ANCESTRY_TARGET_OUT_OF_RANGE");
        }
        recomputed.push(state);
    }
    if recomputed != claimed_states {
        return unknown("ANCESTRY_DERIVED_CLAIM_MISMATCH");
    }
    VerificationResult {
        accepted: true,
        code: "VERIFIED_REACHABLE".into(),
        verdict: AuthorityVerdict::VerifiedReachable,
        recomputed: None,
    }
}

pub fn domain_id(words: &[Vec<NeutralToken>]) -> String {
    hash_json(words)
}

pub fn coverage_accumulator(indices: &[usize]) -> String {
    hash_json(&indices)
}

pub fn verify_bounded_exhaustion(max_shell: u8, receipt: &CoverageReceipt) -> bool {
    let words = finite_shell(max_shell);
    if receipt.domain_id != domain_id(&words) || receipt.domain_cardinality != words.len() {
        return false;
    }
    let mut seen = bitvec![0; words.len()];
    for &index in &receipt.visited_indices {
        let Some(mut bit) = seen.get_mut(index) else {
            return false;
        };
        if *bit {
            return false;
        }
        *bit = true;
    }
    seen.all() && receipt.visited_accumulator_hash == coverage_accumulator(&receipt.visited_indices)
}

pub fn verify_no_witness_box(
    comparison: &FrozenComparison,
    max_shell: u8,
    receipt: &CoverageReceipt,
) -> bool {
    if !verify_bounded_exhaustion(max_shell, receipt)
        || !receipt.accepted_separator_indices.is_empty()
    {
        return false;
    }
    finite_shell(max_shell).into_iter().all(|word| {
        make_certificate(comparison.clone(), word, "bounded recomputation")
            .map(|certificate| !verify_separator(&certificate).accepted)
            .unwrap_or(true)
    })
}

pub fn verify_finite_box_minimum(
    certificate: &SeparatorCertificate,
    max_shell: u8,
    receipt: &CoverageReceipt,
) -> VerificationResult {
    let accepted = verify_separator(certificate);
    if !accepted.accepted || !verify_bounded_exhaustion(max_shell, receipt) {
        return unknown("FINITE_BOX_MINIMUM_PREREQUISITE_FAILURE");
    }
    let witness_rank = rank_key(&certificate.neutral_token_sequence);
    let words = finite_shell(max_shell);
    for (index, word) in words.iter().enumerate() {
        if rank_key(word) >= witness_rank {
            continue;
        }
        let lower = match make_certificate(
            certificate.comparison.clone(),
            word.clone(),
            "lower cone recomputation",
        ) {
            Ok(value) => value,
            Err(_) => continue,
        };
        if verify_separator(&lower).accepted {
            return VerificationResult {
                accepted: false,
                code: format!("CHEAPER_VERIFIED_WITNESS_AT_INDEX_{index}"),
                verdict: AuthorityVerdict::CheaperVerifiedWitness,
                recomputed: None,
            };
        }
    }
    VerificationResult {
        accepted: true,
        code: "MINIMAL_WITHIN_DECLARED_FINITE_BOX".into(),
        verdict: AuthorityVerdict::MinimalWithinDeclaredFiniteBox,
        recomputed: accepted.recomputed,
    }
}

fn valid_finite_machine(machine: &FiniteMachine) -> bool {
    !machine.outputs.is_empty()
        && machine.initial_state < machine.outputs.len()
        && machine.transitions.len() == machine.outputs.len()
        && machine.transitions.iter().all(|row| {
            row.len() == machine.alphabet_size
                && row.iter().all(|&next| next < machine.outputs.len())
        })
}

pub fn verify_universal_proof(proof: &UniversalProof) -> VerificationResult {
    if proof.proof_system_id != UNIVERSAL_PROOF_SYSTEM_ID
        || !valid_finite_machine(&proof.left)
        || !valid_finite_machine(&proof.right)
        || proof.left.alphabet_size != proof.right.alphabet_size
    {
        return unknown("UNIVERSAL_PROOF_SCHEMA_OR_MACHINE_INVALID");
    }
    let relation = proof.relation.iter().copied().collect::<HashSet<_>>();
    if !relation.contains(&(proof.left.initial_state, proof.right.initial_state)) {
        return unknown("INITIAL_PAIR_NOT_IN_RELATION");
    }
    for &(left, right) in &relation {
        if proof.left.outputs.get(left) != proof.right.outputs.get(right) {
            return unknown("RELATION_OUTPUT_MISMATCH");
        }
        for token in 0..proof.left.alphabet_size {
            let next = (
                proof.left.transitions[left][token],
                proof.right.transitions[right][token],
            );
            if !relation.contains(&next) {
                return unknown("RELATION_NOT_TRANSITION_CLOSED");
            }
        }
    }
    VerificationResult {
        accepted: true,
        code: "EQUIVALENT_WITH_ACCEPTED_UNIVERSAL_PROOF".into(),
        verdict: AuthorityVerdict::EquivalentWithAcceptedUniversalProof,
        recomputed: None,
    }
}

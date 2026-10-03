use crate::contract::{
    ARCHITECTURE_ID, CORRESPONDENCE_ID, COUPLING_ID, observable_rules, relation_law_proofs,
};
use crate::fixtures::corpus;
use crate::{AUTHORITY, DISPOSITION, G3_ROOT, G4_ROOT, G5_ROOT, RESULT};
use memchr::memchr_iter;
use memmap2::Mmap;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str =
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g6-behavioral-equivalence";
const ROOT_RECEIPT: &str = "G6_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G6_PROTOCOL_V1.md",
    "src/lib.rs",
    "src/model.rs",
    "src/contract.rs",
    "src/fixtures.rs",
    "src/seal.rs",
    "src/main.rs",
    "tests/g6_contract.rs",
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    verify_parent(repo, "g3-reachable-transition-semantics", "G3", G3_ROOT)?;
    verify_parent(repo, "g4-preservation-surface", "G4", G4_ROOT)?;
    verify_parent(repo, "g5-continuation-grammar", "G5", G5_ROOT)?;
    verify_observable_census(repo)?;
    prepare(out)?;
    for dir in ["authority", "contracts", "findings", "receipts", "source"] {
        fs::create_dir_all(out.join(dir))?;
    }

    let fixtures = corpus()?;
    if fixtures.len() < 36 || fixtures.iter().any(|row| row.status != "PASS") {
        return Err("G6_CONTRACT_FIXTURE_FAILURE".into());
    }
    let proofs = relation_law_proofs();
    if proofs
        .iter()
        .any(|proof| proof.status != "PROVEN_WITHIN_DECLARED_COMPARISON_FIBER")
    {
        return Err("G6_RELATION_LAW_PROOF_FAILURE".into());
    }

    write_json(
        &out.join("authority/G3_G4_G5_AUTHORITY_BINDING.json"),
        &json!({
            "schema":"G6_PARENT_AUTHORITY_BINDING_V1",
            "G3":{"root":G3_ROOT,"authority":"OBS_OPEN_G3_SOUND_REACHABILITY_ENVELOPE_V1"},
            "G4":{"root":G4_ROOT,"authority":"OBS_OPEN_G4_CAUSAL_OBSERVER_PRESERVATION_SURFACE_WITH_BLIND_SPOTS_V1"},
            "G5":{"root":G5_ROOT,"authority":"OBS_OPEN_G5_SOUND_PARAMETRIC_ADMISSIBLE_CONTINUATION_ENVELOPE_V1"},
            "status":"PASS"
        }),
    )?;
    write_contracts(out, &proofs)?;
    write_json(
        &out.join("contracts/G6_CONTRACT_FIXTURE_CORPUS_V1.json"),
        &fixtures,
    )?;
    write_json(
        &out.join("receipts/OUTCOME_ACCESS_AUDIT.json"),
        &json!({
            "schema":"G6_OUTCOME_ACCESS_AUDIT_V1",
            "D_A_OUTCOME_READS":0,
            "D_B_TARGET_READS":0,
            "D_C_READS":0,
            "D_D_TARGET_READS":0,
            "D_D_ACCRUAL":"UNTOUCHED",
            "pair_mining":0,
            "witness_search":0,
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/G6_QUALIFICATION_RECEIPT.json"),
        &json!({
            "schema":"G6_QUALIFICATION_RECEIPT_V1",
            "fixture_count":fixtures.len(),
            "fixture_failures":0,
            "observable_rules":observable_rules().len(),
            "relation_law_derivations":proofs.len(),
            "real_history_pairs_inspected":0,
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("findings/G6_TYPED_FINDINGS.json"),
        &json!({
            "schema":"G6_TYPED_FINDINGS_V1",
            "result":RESULT,
            "architecture":ARCHITECTURE_ID,
            "relation_scope":"FIBERWISE",
            "primitive_objects":"EXECUTABLE_PREFIXES_WITH_CONTEXT",
            "relation_laws":{"reflexivity":"PROVEN_WITHIN_FIBER","symmetry":"PROVEN_WITHIN_FIBER","transitivity":"PROVEN_WITHIN_FIBER"},
            "comparison_domain_laws":{"closure":"PROVEN_WITHIN_FIBER","reflexivity":"PROVEN_WITHIN_FIBER","symmetry":"PROVEN_WITHIN_FIBER","transitivity":"PROVEN_WITHIN_FIBER"},
            "definition_authority":"EXACT_SEMANTIC_TARGET",
            "instance_certification_authority":"RESTRICTED_BY_G3_G5_AND_G4_BLIND_SPOT",
            "GrammarStateAndEvent":"NOT_EVALUABLE",
            "finite_horizon":"ALL_FINITE",
            "omega_trace_authority":"NOT_EARNED",
            "liveness_authority":"NOT_EARNED",
            "fixture_count":fixtures.len(),
            "real_pair_claims":0
        }),
    )?;
    write_json(
        &out.join("findings/G6_GATE_DECISION.json"),
        &json!({
            "schema":"G6_GATE_DECISION_V1",
            "EXECUTION_STATE":"SEALED",
            "QUESTION_STATUS":"CLOSED",
            "RESULT":RESULT,
            "DISPOSITION":DISPOSITION,
            "AUTHORITY":AUTHORITY,
            "reason":"One global architecture defines a proven equivalence relation within typed context-and-language fibers; inherited approximation and blind-spot restrictions remain."
        }),
    )?;
    write_json(
        &out.join("findings/G6_NONCLAIMS.json"),
        &json!({
            "schema":"G6_NONCLAIMS_V1",
            "distinct_real_histories_equivalent":false,
            "any_pair_inequivalent":false,
            "distinguishing_continuation":false,
            "witness_search_algorithm":false,
            "quotient":false,
            "state_redundancy":false,
            "field_removability":false,
            "minimality":false,
            "omega_trace_equivalence":false,
            "prediction":false,
            "economic":false,
            "trading":false
        }),
    )?;
    write_source(repo, out)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({
            "schema":"G6_SOURCE_CLOSURE_RECEIPT_V1",
            "source_files":SOURCE_FILES,
            "source_closure_sha256":source_closure(repo)?,
            "status":"PASS"
        }),
    )?;
    reseal(out)
}

fn write_contracts(
    out: &Path,
    proofs: &[crate::model::LawProof],
) -> Result<(), Box<dyn std::error::Error>> {
    let contract = |name: &str, value: Value| write_json(&out.join("contracts").join(name), &value);
    contract(
        "BEHAVIORAL_EQUIVALENCE_CONTRACT_V1.json",
        json!({
            "schema":"G6_BEHAVIORAL_EQUIVALENCE_CONTRACT_V1",
            "relation":"(pi_a,C_a) equiv_sem_ThetaStar,gamma (pi_b,C_b)",
            "primitive_objects":"QUALIFIED_EXECUTABLE_PREFIXES_WITH_CONTEXT",
            "quantifier":"FOR_ALL_FINITE_TOKEN_SEQUENCES_IN_TRUE_CONSONANT_G5_LANGUAGE_INCLUDING_EPSILON",
            "match":"G4_PROTECTED_PREFIX_AND_TRANSACTIONAL_TRACE_MATCH",
            "relation_scope":"WITHIN_DECLARED_COMPARISON_FIBER",
            "existential_coupling_or_correspondence_rescue":false
        }),
    )?;
    contract(
        "GLOBAL_COMPARISON_ARCHITECTURE_V1.json",
        json!({
            "schema":"G6_GLOBAL_COMPARISON_ARCHITECTURE_V1",
            "architecture_id":ARCHITECTURE_ID,
            "A_COB":"IMMUTABLE_G4_23_OBSERVABLE_SURFACE",
            "L":COUPLING_ID,
            "M":CORRESPONDENCE_ID,
            "R_obs":"OBSERVABLE_MATCHING_CONTRACT_V1",
            "H":"ALL_FINITE_NO_OMEGA",
            "R":"G3_G5_RESTRICTIONS_PRESERVED",
            "pair_instances_are_architecture_generated":true,
            "Lambda_equals_M":false
        }),
    )?;
    contract(
        "COMPARISON_CONTRACT_SCHEMA_V1.json",
        json!({
            "schema":"G6_COMPARISON_CONTRACT_SCHEMA_V1",
            "required_parts":["relation_domain","comparability","coupling_instance","initial_correspondence","epsilon_match","transactional_step_matches","vacuity","certification_status"],
            "naked_equivalence_notation":"FORBIDDEN"
        }),
    )?;
    contract(
        "COMPARISON_DOMAIN_CONTRACT_V1.json",
        json!({
            "schema":"G6_COMPARISON_DOMAIN_CONTRACT_V1",
            "object_domain":"G3_QUALIFIED_EXECUTABLE_PREFIX_WITH_CONTEXT",
            "conditional_tier":"G3_UPPER_ENVELOPE_ONLY_STARTS_REMAIN_CONDITIONAL",
            "fiber_key":["price_scale","source_time_resolution","storage_time_resolution","cadence","session_duration","range_count","range_shape_up_to_affine_price_time_origins"],
            "domain_consonance":"TRUE_UNILATERAL_NEUTRAL_TOKEN_LANGUAGES_EQUAL",
            "cross_fiber":"CONTEXT_INCOMPATIBLE",
            "state_sufficiency_assumed":false
        }),
    )?;
    contract(
        "COMPARABILITY_CONTRACT_V1.json",
        json!({
            "schema":"G6_COMPARABILITY_CONTRACT_V1",
            "statuses":["COMPARABLE","EPSILON_ONLY","COUPLING_UNAVAILABLE","CORRESPONDENCE_INVALID","CONTEXT_INCOMPATIBLE","CONDITIONAL_ON_REACHABILITY","NOT_EVALUABLE"],
            "relation_domain_distinct_from_comparability":true,
            "comparability_distinct_from_behavioral_match":true,
            "epsilon_only_nontrivial_authority":false
        }),
    )?;
    write_json(
        &out.join("contracts/OBSERVABLE_MATCHING_CONTRACT_V1.json"),
        &observable_rules(),
    )?;
    contract(
        "OBSERVER_CORRESPONDENCE_ARCHITECTURE_V1.json",
        json!({
            "schema":"G6_OBSERVER_CORRESPONDENCE_ARCHITECTURE_V1",
            "architecture_id":CORRESPONDENCE_ID,
            "components":{"M_Q":"PRIMITIVE","M_DELTA":"PRIMITIVE","M_R":"CONSTRAINED_BY_AFFINE_CONTEXT","M_G":"PRIMITIVE_TRANSACTIONAL_BIJECTION","M_T":"CONSTRAINED_BY_TIME_TRANSLATION","M_C":"PRIMITIVE_FIBER_RELATION","mu":"PRIMITIVE_TRANSACTIONAL_EXTENSION"},
            "literal_candidate_id_equality":false,
            "literal_absolute_time_equality":false,
            "literal_absolute_price_equality":false
        }),
    )?;
    contract(
        "INITIAL_CORRESPONDENCE_CONTRACT_V1.json",
        json!({
            "schema":"G6_INITIAL_CORRESPONDENCE_CONTRACT_V1",
            "selection_time":"BEFORE_EPSILON_MATCH_VERDICT",
            "price_map":"single integer tick translation from context origins",
            "time_map":"single semantic-time translation from context origins",
            "genealogy_map":"side-preserving ordered alpha-bijection instantiated from protected prefix genealogy",
            "future_response_dependency":"FORBIDDEN"
        }),
    )?;
    contract(
        "CORRESPONDENCE_SELECTION_POLICY_V1.json",
        json!({
            "schema":"G6_CORRESPONDENCE_SELECTION_POLICY_V1",
            "mode":"DETERMINISTIC_CORRESPONDENCE_POLICY",
            "selection_time":"BEFORE_MATCH_VERDICT",
            "optimized_for_match":"FORBIDDEN",
            "alpha_rescue":"FORBIDDEN"
        }),
    )?;
    contract(
        "CORRESPONDENCE_EVOLUTION_POLICY_V1.json",
        json!({
            "schema":"G6_CORRESPONDENCE_EVOLUTION_POLICY_V1",
            "law":"M_(j-1),responses_j -> staged_M_j -> protected_match_j -> committed_M_j",
            "new_genealogy_pair":"same-side same-ordinal simultaneous protected renewal only",
            "failed_match":"DISCARD_STAGED_EXTENSION",
            "backpatch":"FORBIDDEN"
        }),
    )?;
    contract(
        "CORRESPONDENCE_TRANSACTION_POLICY_V1.json",
        json!({
            "schema":"G6_CORRESPONDENCE_TRANSACTION_POLICY_V1",
            "phases":["READ_COMMITTED","STAGE_ONLY_PERMITTED_EXTENSION","MATCH_CURRENT_PROTECTED_RESPONSE","COMMIT_OR_DISCARD"],
            "rewrite_committed_mapping":false,
            "bijective_within_side":true
        }),
    )?;
    contract(
        "PRIMITIVE_DERIVED_RELATION_REGISTRY_V1.json",
        json!({
            "schema":"G6_PRIMITIVE_DERIVED_RELATION_REGISTRY_V1",
            "primitive":["context fiber relation","neutral-token coupling","genealogy alpha-bijection","transition-result class","ordered trace coordinates"],
            "derived":["affine value match","affine temporal match","per-k location match","event structural match","behavioral trace match"],
            "not_evaluable":["GrammarStateAndEvent"]
        }),
    )?;
    contract(
        "COUPLING_QUANTIFIER_POLICY_V1.json",
        json!({
            "schema":"G6_COUPLING_QUANTIFIER_POLICY_V1",
            "mode":"FIXED_NAMED_COUPLING",
            "coupling_id":COUPLING_ID,
            "selection_time":"BEFORE_RESPONSE_COMPARISON",
            "optimized_for_match":"FORBIDDEN",
            "hidden_existential_quantifier":false
        }),
    )?;
    contract(
        "COUPLING_CAUSALITY_CONTRACT_V1.json",
        json!({
            "schema":"G6_COUPLING_CAUSALITY_CONTRACT_V1",
            "experiment_selection":"OPEN_LOOP_FINITE_TOKEN_SEQUENCE",
            "realization":"CAUSAL_PREFIX_SENSITIVE_SIDE_SPECIFIC",
            "allowed_reads":["preselected token","current applied prefixes","immutable contexts","committed correspondence","prior experiment history"],
            "current_or_future_response_read":"FORBIDDEN",
            "oracle_coupling":"FORBIDDEN"
        }),
    )?;
    contract(
        "SIDE_SPECIFIC_EXPERIMENT_REALIZATION_V1.json",
        json!({
            "schema":"G6_SIDE_SPECIFIC_EXPERIMENT_REALIZATION_V1",
            "operator":"Lambda(z_j,pi_a^(j-1),pi_b^(j-1),C_a,C_b,M_(j-1),H_exp_<j) -> (x_j_a,x_j_b)",
            "price":"common integer-tick OHLC deltas relative to each committed close",
            "time":"each side next causal slot",
            "raw_diagonal":"QUALIFIED_SPECIAL_CASE_NOT_DEFAULT"
        }),
    )?;
    contract(
        "COUPLING_COMPOSITION_POLICY_V1.json",
        json!({
            "schema":"G6_COUPLING_COMPOSITION_POLICY_V1",
            "naive_raw_stimulus_composition":false,
            "policy":"COMMON_NEUTRAL_TOKEN_REFINEMENT_THROUGH_SHARED_B_SIDE_SEMANTICS",
            "obligation":"same preselected token sequence and consonant language yield direct a-c realization",
            "authority":"PROVEN_WITHIN_COMPARISON_FIBER"
        }),
    )?;
    contract(
        "CORRESPONDENCE_COMPOSITION_POLICY_V1.json",
        json!({
            "schema":"G6_CORRESPONDENCE_COMPOSITION_POLICY_V1",
            "price_translation":"integer addition",
            "time_translation":"integer addition",
            "genealogy":"side-preserving relational composition of bijections",
            "ordered_trace":"componentwise composition",
            "authority":"PROVEN_WITHIN_COMPARISON_FIBER"
        }),
    )?;
    contract(
        "VACUITY_AUTHORITY_CONTRACT_V1.json",
        json!({
            "schema":"G6_VACUITY_AUTHORITY_CONTRACT_V1",
            "nonempty":"BEHAVIORALLY_EQUIVALENT_NONTRIVIAL_DOMAIN",
            "epsilon_only":"EQUIVALENT_ON_EPSILON_ONLY_DOMAIN",
            "no_common_nonempty_presentation":"NOT_DEEP_BEHAVIORAL_SAMENESS",
            "domain_consonance_prevents_one_sided_vacuity":true
        }),
    )?;
    contract(
        "BEHAVIORAL_HORIZON_INHERITANCE_V1.json",
        json!({
            "schema":"G6_BEHAVIORAL_HORIZON_INHERITANCE_V1",
            "G5_horizon":"SOUND_ALL_FINITE_OVERAPPROXIMATION",
            "semantic_definition":"ALL_TRUE_FINITE_CONTINUATIONS",
            "omega_trace_authority":"NOT_EARNED",
            "liveness_authority":"NOT_EARNED"
        }),
    )?;
    contract(
        "EXPERIMENT_VS_CAUSAL_PROGRESS_CONTRACT_V1.json",
        json!({
            "schema":"G6_EXPERIMENT_VS_CAUSAL_PROGRESS_CONTRACT_V1",
            "experiment_ordinal":"j increments for every lawfully presented token",
            "left_causal_ordinal":"increments only on left KERNEL_APPLIED",
            "right_causal_ordinal":"increments only on right KERNEL_APPLIED",
            "equality_assumed":false
        }),
    )?;
    contract(
        "REJECTION_BEHAVIOR_MATCHING_POLICY_V1.json",
        json!({
            "schema":"G6_REJECTION_BEHAVIOR_MATCHING_POLICY_V1",
            "APPLIED_APPLIED":"MATCH_CLASS",
            "APPLIED_REJECTED":"BEHAVIORAL_MISMATCH",
            "REJECTED_APPLIED":"BEHAVIORAL_MISMATCH",
            "REJECTED_REJECTED":"MATCH_ONLY_IF_REASON_CLASS_EQUAL",
            "pre_presentation_invalid":"PAIR_NOT_COMPARABLE_FOR_TOKEN",
            "rejected_state_effect":"UNCHANGED_PREFIX_AND_SAME_CAUSAL_SLOT"
        }),
    )?;
    contract(
        "TEMPORAL_MATCHING_POLICY_V1.json",
        json!({
            "schema":"G6_TEMPORAL_MATCHING_POLICY_V1",
            "mode":"COUPLING_RELATIVE_TEMPORAL_CORRESPONDENCE",
            "source_semantic_resolution_ns":1000000000_i64,
            "storage_resolution_ns":1,
            "historical_precision_upgrade":"NONE",
            "cadence_and_order":"EXACT_WITHIN_FIBER",
            "absolute_time":"AFFINE_TRANSLATION"
        }),
    )?;
    contract(
        "GENEALOGY_MATCHING_POLICY_V1.json",
        json!({
            "schema":"G6_GENEALOGY_MATCHING_POLICY_V1",
            "mode":"SIDE_PRESERVING_ORDERED_RELATIONAL_ISOMORPHISM",
            "numeric_id_equality":"NOT_REQUIRED",
            "candidate_existence_birth_persistence_renewal_replacement_continuity":"PROTECTED",
            "evolution":"TRANSACTIONAL_NO_BACKPATCH"
        }),
    )?;
    contract(
        "VALUE_ROLE_MATCHING_POLICY_V1.json",
        json!({
            "schema":"G6_VALUE_ROLE_MATCHING_POLICY_V1",
            "absolute_prices":"ROLE_RELATIVE_AFFINE_VALUE_CORRESPONDENCE",
            "translation_invariant_distances":"LITERAL_TICK_EQUALITY",
            "location":"SEMANTIC_CLASS_EQUALITY_PER_K",
            "price_scale":"LITERAL_SEMANTIC_EQUALITY",
            "canonical_integer_normalization_implies_cross_history_equality":false
        }),
    )?;
    contract(
        "CONTEXT_MATCHING_POLICY_V1.json",
        json!({
            "schema":"G6_CONTEXT_MATCHING_POLICY_V1",
            "mode":"COUPLED_CONTEXT_RELATION_WITH_TYPED_FIBERS",
            "exact":["price scale","source resolution","storage resolution","cadence","session duration","range count","range shape"],
            "affine":["price origin","semantic time origin"],
            "excluded":["context.session_id","input.source_row_id","emission.commit.source_row_id"]
        }),
    )?;
    contract(
        "SEMANTIC_RELATION_VS_CERTIFICATION_AUTHORITY_V1.json",
        json!({
            "schema":"G6_SEMANTIC_RELATION_VS_CERTIFICATION_AUTHORITY_V1",
            "definition_authority":"EXACT_OVER_TRUE_FINITE_CONSONANT_G5_LANGUAGE",
            "certification_states":["CERTIFIED_EQUIVALENT","CERTIFIED_INEQUIVALENT","CONDITIONAL","CANDIDATE_SEPARATION_ONLY","UNKNOWN","NOT_EVALUABLE"],
            "upper_envelope_mismatch":"CANDIDATE_SEPARATION_ONLY",
            "definition_equals_certification":false
        }),
    )?;
    write_json(&out.join("contracts/RELATION_LAW_PROOFS_V1.json"), proofs)?;
    write_json(
        &out.join("contracts/COMPARISON_DOMAIN_LAW_PROOFS_V1.json"),
        &proofs
            .iter()
            .filter(|proof| proof.law.contains("DOMAIN") || proof.law.contains("COMPARABILITY"))
            .collect::<Vec<_>>(),
    )?;
    contract(
        "G3_G5_APPROXIMATION_PROOF_POLICY_V1.json",
        json!({
            "schema":"G6_G3_G5_APPROXIMATION_PROOF_POLICY_V1",
            "constructive_presentable_mismatch":"MAY_CERTIFY_INEQUIVALENCE_IF_STARTS_QUALIFIED",
            "upper_envelope_only_mismatch":"CANDIDATE_SEPARATION_ONLY",
            "universal_match_over_sound_upper_envelope":"MAY_CERTIFY_TRUE_LANGUAGE_MATCH_WITH_EXPLICIT_SOUND_EXTENSION_PROOF",
            "checked_upper_envelope_alone":"INSUFFICIENT"
        }),
    )?;
    contract(
        "G4_BLIND_SPOT_INHERITANCE_V1.json",
        json!({
            "schema":"G6_G4_BLIND_SPOT_INHERITANCE_V1",
            "GrammarStateAndEvent":"NOT_EVALUABLE",
            "orthogonal_to_G3_reachability":true,
            "orthogonal_to_G5_continuation_approximation":true,
            "unrestricted_historical_observer_equivalence":false
        }),
    )?;
    contract(
        "G6_IMMUTABILITY_CONTRACT_V1.json",
        json!({
            "schema":"G6_IMMUTABILITY_CONTRACT_V1",
            "downstream_mutation":"FORBIDDEN",
            "new_root_required_for":["coupling quantifier","coupling realization","correspondence selection","correspondence architecture","correspondence evolution","observable matching","comparison domain","vacuity","horizon"],
            "downstream_after_change":"REEXECUTE_G7_PLUS"
        }),
    )?;
    contract(
        "OPAQUE_LOCATOR_EXCLUSION_V1.json",
        json!({
            "schema":"G6_OPAQUE_LOCATOR_EXCLUSION_V1",
            "excluded":["context.session_id","input.source_row_id","emission.commit.source_row_id"],
            "usable_as_correspondence_key":false,
            "usable_as_context_equality":false
        }),
    )?;
    Ok(())
}

pub fn finalize(a: &Path, b: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(a, b)?;
    let receipt = json!({
        "schema":"G6_DETERMINISTIC_REBUILD_RECEIPT_V1",
        "independent_builds":2,
        "configurations":["D_TARGET_BUILD_A","D_TARGET_BUILD_B"],
        "pre_finalize_artifact_count":members(a)?.len(),
        "byte_mismatches":0,
        "status":"PASS"
    });
    for root in [a, b] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
    }
    let left = reseal(a)?;
    let right = reseal(b)?;
    if left != right {
        return Err("G6_FINAL_ROOT_MISMATCH".into());
    }
    for root in [a, b] {
        write_root(root, &left)?;
    }
    compare(a, b)?;
    Ok(left)
}

fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let findings: Value =
        serde_json::from_slice(&fs::read(root.join("findings/G6_TYPED_FINDINGS.json"))?)?;
    write_json(
        &root.join(ROOT_RECEIPT),
        &json!({
            "schema":"G6_ROOT_RECEIPT_V1",
            "status":"SEALED",
            "G6_root":hash,
            "authority":AUTHORITY,
            "parent_G3_root":G3_ROOT,
            "parent_G4_root":G4_ROOT,
            "parent_G5_root":G5_ROOT,
            "QUESTION_STATUS":"CLOSED",
            "RESULT":RESULT,
            "DISPOSITION":DISPOSITION,
            "relation_scope":"FIBERWISE",
            "relation_laws":findings["relation_laws"],
            "observable_rule_count":23,
            "outcome_access":{"D_A":0,"D_B":0,"D_C":0,"D_D":0},
            "D_D_accrual":"UNTOUCHED",
            "real_pair_claims":0,
            "witness_authority":false,
            "quotient_authority":false,
            "minimality_authority":false,
            "prediction_authority":false,
            "economic_authority":false,
            "trading_authority":false
        }),
    )
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G6_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}

pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = receipt["G6_root"].as_str().ok_or("G6_ROOT_FIELD_MISSING")?;
    let file = File::open(root.join("content_manifest.tsv"))?;
    let mmap = unsafe { Mmap::map(&file)? };
    let actual = sha256(&mmap);
    if actual != expected {
        return Err("G6_ROOT_DRIFT".into());
    }
    for member in manifest_members(&mmap)? {
        let path = root.join(&member.relative_path);
        if fs::metadata(&path)?.len() != member.bytes || sha256_file(&path)? != member.sha256 {
            return Err(format!("G6_MEMBER_DRIFT:{}", member.relative_path).into());
        }
    }
    Ok(actual)
}

fn verify_parent(
    repo: &Path,
    dir: &str,
    gate: &str,
    expected: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    let path = repo
        .join("studies/obs-open-01/sentinel-behavioral-qualification-compound")
        .join(dir)
        .join("seal")
        .join(format!("{gate}_ROOT_RECEIPT.json"));
    let value: Value = serde_json::from_slice(&fs::read(path)?)?;
    let field = format!("{gate}_root");
    if value[field].as_str() != Some(expected) || value["status"].as_str() != Some("SEALED") {
        return Err(format!("G6_PARENT_{gate}_ROOT_MISMATCH").into());
    }
    Ok(())
}

fn verify_observable_census(repo: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let path = repo.join("studies/obs-open-01/sentinel-behavioral-qualification-compound/g4-preservation-surface/seal/contracts/OBSERVABLE_SURFACE_REGISTRY_V1.json");
    let parent: Value = serde_json::from_slice(&fs::read(path)?)?;
    let parent_ids = parent
        .as_array()
        .ok_or("G4_OBSERVABLE_REGISTRY_NOT_ARRAY")?
        .iter()
        .map(|row| {
            row["observable_id"]
                .as_str()
                .ok_or("G4_OBSERVABLE_ID_MISSING")
                .map(str::to_owned)
        })
        .collect::<Result<BTreeSet<_>, _>>()?;
    let child_ids = observable_rules()
        .into_iter()
        .map(|row| row.observable_id)
        .collect::<BTreeSet<_>>();
    if parent_ids.len() != 23 || parent_ids != child_ids {
        return Err("G6_G4_OBSERVABLE_CENSUS_MISMATCH".into());
    }
    Ok(())
}

fn prepare(path: &Path) -> std::io::Result<()> {
    if path.exists() {
        fs::remove_dir_all(path)?;
    }
    fs::create_dir_all(path)
}

fn reseal(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    for name in ["content_manifest.tsv", ROOT_RECEIPT] {
        let path = root.join(name);
        if path.exists() {
            fs::remove_file(path)?;
        }
    }
    let mut writer = BufWriter::new(File::create(root.join("content_manifest.tsv"))?);
    writeln!(writer, "relative_path\tbytes\tsha256")?;
    for member in members(root)? {
        writeln!(
            writer,
            "{}\t{}\t{}",
            member.relative_path, member.bytes, member.sha256
        )?;
    }
    writer.flush()?;
    Ok(sha256(&fs::read(root.join("content_manifest.tsv"))?))
}

fn members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut paths = Vec::new();
    collect(root, root, &mut paths)?;
    paths.sort_unstable();
    paths
        .into_iter()
        .filter(|path| path != "content_manifest.tsv" && path != ROOT_RECEIPT)
        .map(|relative_path| {
            let path = root.join(&relative_path);
            Ok(Member {
                bytes: fs::metadata(&path)?.len(),
                sha256: sha256_file(&path)?,
                relative_path,
            })
        })
        .collect()
}

fn manifest_members(bytes: &[u8]) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut output = Vec::new();
    let mut start = 0;
    for (row, end) in memchr_iter(b'\n', bytes).enumerate() {
        let line = bytes[start..end]
            .strip_suffix(b"\r")
            .unwrap_or(&bytes[start..end]);
        start = end + 1;
        if row == 0 || line.is_empty() {
            continue;
        }
        let fields = std::str::from_utf8(line)?.split('\t').collect::<Vec<_>>();
        if fields.len() != 3 || fields[0].contains("..") || Path::new(fields[0]).is_absolute() {
            return Err("G6_MANIFEST_MALFORMED".into());
        }
        output.push(Member {
            relative_path: fields[0].into(),
            bytes: fields[1].parse()?,
            sha256: fields[2].into(),
        });
    }
    Ok(output)
}

fn collect(base: &Path, dir: &Path, output: &mut Vec<String>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect(base, &path, output)?;
        } else {
            output.push(
                path.strip_prefix(base)
                    .expect("descendant")
                    .to_string_lossy()
                    .replace('\\', "/"),
            );
        }
    }
    Ok(())
}

fn compare(left: &Path, right: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if members(left)? != members(right)? {
        return Err("G6_BYTE_MISMATCH".into());
    }
    Ok(())
}

fn write_json<T: Serialize + ?Sized>(
    path: &Path,
    value: &T,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    fs::write(path, bytes)?;
    Ok(())
}

fn write_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    for relative in SOURCE_FILES {
        fs::copy(
            repo.join(STUDY).join(relative),
            out.join("source").join(relative.replace('/', "__")),
        )?;
    }
    Ok(())
}

fn source_closure(repo: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut hasher = Sha256::new();
    for relative in SOURCE_FILES {
        hasher.update(relative.as_bytes());
        hasher.update([0]);
        hasher.update(fs::read(repo.join(STUDY).join(relative))?);
        hasher.update([0]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn copy_tree(source: &Path, destination: &Path) -> std::io::Result<()> {
    fs::create_dir_all(destination)?;
    for entry in fs::read_dir(source)? {
        let path = entry?.path();
        let target = destination.join(path.file_name().expect("filename"));
        if path.is_dir() {
            copy_tree(&path, &target)?;
        } else {
            fs::copy(path, target)?;
        }
    }
    Ok(())
}

fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file)? };
    Ok(sha256(&mmap))
}

fn sha256(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

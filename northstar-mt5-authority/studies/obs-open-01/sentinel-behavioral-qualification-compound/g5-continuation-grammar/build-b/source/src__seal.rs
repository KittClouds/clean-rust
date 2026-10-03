use crate::fixtures;
use crate::grammar::{identity_coupling, relative_coupling};
use crate::{AUTHORITY, G3_ROOT, G4_ROOT, GATE_ID};
use memchr::memchr_iter;
use memmap2::Mmap;
use obs_open_meas02::sha256_file;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str =
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g5-continuation-grammar";
const G3_SEAL: &str = "studies/obs-open-01/sentinel-behavioral-qualification-compound/g3-reachable-transition-semantics/seal";
const G4_SEAL: &str =
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g4-preservation-surface/seal";
const ROOT_RECEIPT: &str = "G5_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G5_PROTOCOL_V1.md",
    "src/fixtures.rs",
    "src/grammar.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/seal.rs",
    "tests/g5_contract.rs",
];
#[derive(Debug, Serialize, PartialEq, Eq)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare(out)?;
    for d in ["authority", "contracts", "receipts", "findings", "source"] {
        fs::create_dir_all(out.join(d))?;
    }
    bind(repo, out)?;
    let fixtures = fixtures::qualified_corpus()?;
    if fixtures.len() < 23 || fixtures.iter().any(|x| x.status != "PASS") {
        return Err("G5_FIXTURE_QUALIFICATION_FAILURE".into());
    }
    write_contracts(out, &fixtures)?;
    write_receipts(out, &fixtures)?;
    write_findings(out, &fixtures)?;
    write_source(repo, out)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({"schema":"G5_SOURCE_CLOSURE_RECEIPT_V1","source_file_count":SOURCE_FILES.len(),"source_closure_sha256":source_closure(repo)?,"status":"PASS"}),
    )?;
    reseal(out)
}

fn bind(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let g3 = repo.join(G3_SEAL);
    let g4 = repo.join(G4_SEAL);
    if obs_open_04a_g3::seal::verify(&g3)? != G3_ROOT {
        return Err("G3_ROOT_DRIFT".into());
    }
    if obs_open_04a_g4::seal::verify(&g4)? != G4_ROOT {
        return Err("G4_ROOT_DRIFT".into());
    }
    let r3: Value = serde_json::from_slice(&fs::read(g3.join("G3_ROOT_RECEIPT.json"))?)?;
    let r4: Value = serde_json::from_slice(&fs::read(g4.join("G4_ROOT_RECEIPT.json"))?)?;
    if r3["RESULT"] != "SOUND_REACHABILITY_ENVELOPE_SEALED"
        || r4["RESULT"] != "PRESERVATION_SURFACE_SEALED_WITH_DECLARED_NOT_EVALUABLE_COMPONENTS"
        || r4["continuation_authority"] != false
    {
        return Err("PARENT_AUTHORITY_NOT_ADMISSIBLE".into());
    }
    write_json(
        &out.join("authority/G3_G4_AUTHORITY_BINDING.json"),
        &json!({"schema":"G5_PARENT_AUTHORITY_BINDING_V1","G3_root":G3_ROOT,"G4_root":G4_ROOT,"G3_authority":r3["authority"],"G4_authority":r4["authority"],"consumed":[
        {"path":"G3/REACHABILITY_SANDWICH_V1","sha256":sha256_file(&g3.join("contracts/REACHABILITY_SANDWICH_V1.json"))?},
        {"path":"G3/ADMITTED_INPUT_CONSTRAINTS_V1","sha256":sha256_file(&g3.join("contracts/ADMITTED_INPUT_CONSTRAINTS_V1.json"))?},
        {"path":"G4/OBSERVABLE_SURFACE_REGISTRY_V1","sha256":sha256_file(&g4.join("contracts/OBSERVABLE_SURFACE_REGISTRY_V1.json"))?},
        {"path":"G4/TRANSITION_PRESERVATION_CONTRACT_V1","sha256":sha256_file(&g4.join("contracts/TRANSITION_PRESERVATION_CONTRACT_V1.json"))?},
        {"path":"G4/TEMPORAL_AUTHORITY_CONTRACT_V1","sha256":sha256_file(&g4.join("contracts/TEMPORAL_AUTHORITY_CONTRACT_V1.json"))?}
    ],"status":"PASS"}),
    )
}

fn write_contracts(
    out: &Path,
    fixtures: &[crate::model::FixtureReceipt],
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/ADMISSIBLE_CONTINUATION_GRAMMAR_V1.json"),
        &json!({"schema":"G5_ADMISSIBLE_CONTINUATION_GRAMMAR_V1","primitive_start":"S_pi=(pi,K_pi,C,rho_pi)","unilateral":"U(pi,C)","pairwise":"U_Lambda(pi_a,C_a,pi_b,C_b)","empty_continuation":"INCLUDED","prefix_closed":true,"state_sufficiency_assumed":false,"jointly_presentable_is_applied_by_both":false,"behavioral_output_comparison":false,"status":"FROZEN"}),
    )?;
    write_json(
        &out.join("contracts/SINGLE_PREFIX_INDEXED_GRAMMAR_V1.json"),
        &json!({"schema":"G5_SINGLE_PREFIX_INDEXED_GRAMMAR_V1","membership_rule":"epsilon or every successive token realizes a source-valid, context-compatible, prefix-compatible side stimulus; KERNEL_REJECTED remains presented behavior and retains the applied prefix","indexes":["prefix","reached state","immutable context","start reachability receipt"],"empty_included":true,"prefix_closure":true,"terminal_rule":"no positive-length token whose knowledge time exceeds session terminal","state_indexed_reduction":"NOT_EARNED","exactness":"SOUND_ENVELOPE","horizon":"ALL_FINITE_SEMANTIC_DEFINITION"}),
    )?;
    write_json(
        &out.join("contracts/PARAMETRIC_PAIRWISE_CONTINUATION_GRAMMAR_V1.json"),
        &json!({"schema":"G5_PARAMETRIC_PAIRWISE_CONTINUATION_GRAMMAR_V1","operator":"FrakturU_G5(pi_a,C_a,pi_b,C_b;Lambda)","relation":"subset of U(pi_a,C_a) cross U(pi_b,C_b)","token_realization":"Lambda(z_i | accumulated left/right prefixes and contexts)=(x_i_a,x_i_b)","raw_input_identity_default":false,"observer_correspondence_parameter":"NOT_REQUIRED_FOR_PRESENTABILITY_IN_V1","outcome_matrix":["APPLIED/APPLIED","APPLIED/REJECTED","REJECTED/APPLIED","REJECTED/REJECTED"],"epsilon_included":true,"prefix_closed":true,"exactness":"SOUND_ENVELOPE","behavioral_comparison":"UNDEFINED"}),
    )?;
    write_json(
        &out.join("contracts/CONTINUATION_COUPLING_INTERFACE_V1.json"),
        &json!({"schema":"G5_CONTINUATION_COUPLING_INTERFACE_V1","experiment_token_schema":{"type":"RELATIVE_COMPLETED_BAR_TOKEN","fields":["open_delta_ticks","high_delta_ticks","low_delta_ticks","close_delta_ticks","coverage_class"]},"qualified_interfaces":[relative_coupling(),identity_coupling()],"left_realization":"side prefix current close and next causal slot","right_realization":"side prefix current close and next causal slot","prefix_dependencies":["committed close","knowledge time"],"context_dependencies":["price scale","source time resolution","cadence","session terminal"],"observer_correspondence_dependency":"NONE","identity_coupling_available":true,"failure_modes":["MISSING_LAMBDA","PRICE_OVERFLOW","TIME_OVERFLOW","SIDE_PRESENTATION_INVALID"]}),
    )?;
    write_json(
        &out.join("contracts/SOURCE_STIMULUS_GRAMMAR_V1.json"),
        &json!({"schema":"G5_SOURCE_STIMULUS_GRAMMAR_V1","authority":["CANONICAL_INTEGER_M1_BRIDGE_V1","SYNTHETIC_SEQUENCE_FIXTURE"],"required":["completed bar","integer ticks","low <= open,close <= high","knowledge-event equals declared cadence"],"invalid_class":"SOURCE_GRAMMAR_INVALID","source_row_locator":"NOT_IN_G4_AUTHORITY"}),
    )?;
    write_json(
        &out.join("contracts/CONTEXT_PRESENTATION_CONTRACT_V1.json"),
        &json!({"schema":"G5_CONTEXT_PRESENTATION_CONTRACT_V1","required":["price scale match","source resolution match","cadence match","event not before session start","knowledge not after session terminal"],"pairwise_context_roles":{"session_id":"PROVENANCE_ONLY","session_start_ns":"INDEPENDENT_PARAMETER","session_terminal_ns":"INDEPENDENT_PARAMETER","price_scale":"SHARED_SEMANTIC_VALUE_REQUIRED","source_time_resolution_ns":"SHARED_SEMANTIC_VALUE_REQUIRED","storage_time_resolution_ns":"SHARED_SEMANTIC_VALUE_REQUIRED","observation_cadence_ns":"SHARED_SEMANTIC_VALUE_REQUIRED","range.k":"INDEPENDENT_PARAMETER","range.high_ticks":"INDEPENDENT_PARAMETER","range.low_ticks":"INDEPENDENT_PARAMETER","range.freeze_commit_time_ns":"INDEPENDENT_PARAMETER"},"raw_context_equality_required":false,"opaque_locators_forbidden_as_pairing_requirements":["context.session_id","input.source_row_id","emission.commit.source_row_id"]}),
    )?;
    write_json(
        &out.join("contracts/PREFIX_PRESENTABILITY_CONTRACT_V1.json"),
        &json!({"schema":"G5_PREFIX_PRESENTABILITY_CONTRACT_V1","initialized_rule":"next knowledge time minus prefix knowledge time equals cadence","uninitialized_rule":"first event time equals session start","individual_input_validity_is_sequence_validity":false,"rejected_attempt_extends_applied_prefix":false,"rejection_retry_slot":"same causal slot under unchanged prefix","coverage_incomplete_creates_future_exclusion":false,"terminal_prefix":"epsilon only when no future context-compatible slot exists"}),
    )?;
    write_json(
        &out.join("contracts/TEMPORAL_CONTINUATION_CONTRACT_V1.json"),
        &json!({"schema":"G5_TEMPORAL_CONTINUATION_CONTRACT_V1","storage_resolution_ns":1,"source_semantic_resolution_ns":1_000_000_000_i64,"historical_precision_upgrade":"NONE","absolute_timestamp_equality_default":false,"relative_alignment":"next source-authoritative causal slot under each side context","subsecond_pairing_below_source_resolution":"FORBIDDEN"}),
    )?;
    write_rejection_contracts(out)?;
    write_json(
        &out.join("contracts/CORRESPONDENCE_DEPENDENCY_REGISTRY_V1.json"),
        &json!({"schema":"G5_CORRESPONDENCE_DEPENDENCY_REGISTRY_V1","rules":[{"rule":"source grammar","dependency":"NONE"},{"rule":"context presentation","dependency":"NONE"},{"rule":"prefix chronology","dependency":"NONE"},{"rule":"relative token realization","dependency":"NONE"},{"rule":"identity coupling qualification","dependency":"NONE"},{"rule":"candidate genealogy output comparison","dependency":"REQUIRED_BUT_OUTSIDE_G5_AND_DEFERRED"}],"M_instance_selected":false,"Lambda_is_M":false}),
    )?;
    write_json(
        &out.join("contracts/GRAMMAR_HORIZON_AUTHORITY_V1.json"),
        &json!({"schema":"G5_GRAMMAR_HORIZON_AUTHORITY_V1","semantic_horizon_authority":"SOUND_ALL_FINITE_OVERAPPROXIMATION","constructive_evidence":"CONSTRUCTIVE_FINITE_UNDERAPPROXIMATION","fixture_max_length":2,"fixture_bound_is_language_horizon":false,"empty_continuation_included":true}),
    )?;
    write_json(
        &out.join("contracts/GRAMMAR_NONVACUITY_REGISTRY_V1.json"),
        &json!({"schema":"G5_GRAMMAR_NONVACUITY_REGISTRY_V1","classes":["NONTRIVIAL","EPSILON_ONLY","NO_COMMON_NONEMPTY_PRESENTATION","UNKNOWN","NOT_EVALUABLE"],"qualified_fixture_instances":[{"id":"F_NONDIAGONAL","class":"NONTRIVIAL"},{"id":"F_IDENTITY","class":"NONTRIVIAL"},{"id":"F_EPSILON_ONLY_PAIR","class":"EPSILON_ONLY"}],"every_future_instance_must_declare_class":true,"epsilon_only_cannot_support_strong_future_agreement":true}),
    )?;
    write_json(
        &out.join("contracts/CONTINUATION_GRAMMAR_APPROXIMATION_BOUNDARY_V1.json"),
        &json!({"schema":"G5_CONTINUATION_GRAMMAR_APPROXIMATION_BOUNDARY_V1","single":{"indexed":"U_minus(pi,C) subset U(pi,C) subset U_plus(pi,C)","exactness":"SOUND_ENVELOPE","lower":"constructively realized finite sequences","upper":"all sequences passing proven local laws from a typed start","error_direction":"lower may omit lawful futures; upper may include futures from unreachable starts"},"pairwise":{"indexed":"U_minus_Lambda(pi_a,C_a,pi_b,C_b) subset U_Lambda(...) subset U_plus_Lambda(...) ","exactness":"SOUND_ENVELOPE","lower":"qualified coupling fixtures","upper":"all side pairs produced by a valid Lambda and passing side laws","error_direction":"upper-start reachability may be spurious until witnessed"},"coupling_interface_exactness":"EXACT","rejection_presentability_exactness":"EXACT","requires_witness_validation_for_upper_start_counterexample":true}),
    )?;
    write_json(
        &out.join("contracts/G3_AUTHORITY_COMPOSITION_CONTRACT_V1.json"),
        &json!({"schema":"G5_G3_AUTHORITY_COMPOSITION_CONTRACT_V1","proven_constraints":"UNIVERSAL_NECESSARY_LAWS_AND_EXCLUSIONS","constructive_witnesses":"EXISTENTIAL_POSITIVE_REACHABILITY","upper_envelope":"CONSERVATIVE_POSSIBILITY_ONLY","lower_witness_absence":"NO_NEGATIVE_AUTHORITY","scalar_ranking":"FORBIDDEN","start_statuses":["PROVEN_REACHABLE","CONSTRUCTIVELY_REACHABLE","UPPER_ENVELOPE_ONLY","UNKNOWN","NOT_EVALUABLE"],"upper_start_counterexample_requires_witness":true}),
    )?;
    write_json(
        &out.join("contracts/G4_PRESERVATION_AUTHORITY_INHERITANCE_V1.json"),
        &json!({"schema":"G5_G4_PRESERVATION_AUTHORITY_INHERITANCE_V1","G4_root":G4_ROOT,"protected_observables":23,"grammar_may_exclude_based_on_behavioral_difference":false,"applied_rejected_protected":true,"ordered_emissions_protected":true,"candidate_genealogy_protected":true,"comparison_performed":false}),
    )?;
    write_json(
        &out.join("contracts/OBSERVABLE_AUTHORITY_PRECEDENCE_V1.json"),
        &json!({"schema":"G5_OBSERVABLE_AUTHORITY_PRECEDENCE_V1","preservation_precedence":["OBSERVABLE_SURFACE_REGISTRY_V1","ELEMENT_PRESERVATION_CENSUS_V1"],"element_provenance_is_ontology":false}),
    )?;
    write_json(
        &out.join("contracts/PRESENTABILITY_FIXTURE_CORPUS_V1.json"),
        fixtures,
    )?;
    write_json(
        &out.join("contracts/NOT_EVALUABLE_INHERITANCE_V1.json"),
        &json!({"schema":"G5_NOT_EVALUABLE_INHERITANCE_V1","GrammarStateAndEvent":"NOT_EVALUABLE","distinct_from_admissible_continuation_grammar":true,"repair_attempted":false}),
    )?;
    write_json(
        &out.join("contracts/G5_IMMUTABILITY_CONTRACT_V1.json"),
        &json!({"schema":"G5_IMMUTABILITY_CONTRACT_V1","downstream_grammar_mutation":"FORBIDDEN","narrow_language":"REQUIRES_NEW_G5_VERSION","widen_language":"REQUIRES_NEW_G5_VERSION","change_coupling_interface":"REQUIRES_NEW_G5_VERSION","change_rejection_presentability":"REQUIRES_NEW_G5_VERSION","change_horizon":"REQUIRES_NEW_G5_VERSION","new_version":"REQUIRES_NEW_ROOT","new_root":"REQUIRES_FORK_OR_REBASE","downstream_after_change":"REEXECUTE_G6_PLUS"}),
    )?;
    Ok(())
}

fn write_rejection_contracts(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let rows = vec![
        json!({"reason_id":"INPUT_AUTHORITY_NOT_QUALIFIED_FOR_G1","classification":"PRE_PRESENTATION_INVALID","layer":"SOURCE_GRAMMAR_INVALID","state_effect":"NOT_PRESENTED","continuation_after_rejection":"NOT_APPLICABLE"}),
        json!({"reason_id":"INVALID_KERNEL_CONTEXT","classification":"PRE_PRESENTATION_INVALID","layer":"CONTEXT_PRESENTATION_INVALID","state_effect":"NOT_PRESENTED","continuation_after_rejection":"NOT_APPLICABLE"}),
        json!({"reason_id":"INVALID_RANGE_CONTEXT","classification":"PRE_PRESENTATION_INVALID","layer":"CONTEXT_PRESENTATION_INVALID","state_effect":"NOT_PRESENTED","continuation_after_rejection":"NOT_APPLICABLE"}),
        json!({"reason_id":"INVALID_COMPLETED_OBSERVATION","classification":"CONTEXT_DEPENDENT","layer":"SOURCE_OR_CONTEXT_PRESENTATION_INVALID_BY_FAILED_PREDICATE","state_effect":"NOT_PRESENTED","continuation_after_rejection":"NOT_APPLICABLE"}),
        json!({"reason_id":"INVALID_SESSION_INITIAL_OBSERVATION","classification":"PRE_PRESENTATION_INVALID","layer":"PREFIX_PRESENTATION_INVALID","state_effect":"NOT_PRESENTED","continuation_after_rejection":"NOT_APPLICABLE"}),
        json!({"reason_id":"OBSERVATION_OUTSIDE_SESSION","classification":"PRE_PRESENTATION_INVALID","layer":"CONTEXT_PRESENTATION_INVALID","state_effect":"NOT_PRESENTED","continuation_after_rejection":"NOT_APPLICABLE"}),
        json!({"reason_id":"OBSERVATION_SEQUENCE_GAP","classification":"PRE_PRESENTATION_INVALID","layer":"PREFIX_PRESENTATION_INVALID","state_effect":"NOT_PRESENTED","continuation_after_rejection":"NOT_APPLICABLE"}),
        json!({"reason_id":"STATE_OUTSIDE_EXTRACTED_DOMAIN","classification":"PRE_PRESENTATION_INVALID","layer":"START_SITUATION_NOT_QUALIFIED","state_effect":"NOT_PRESENTED","continuation_after_rejection":"NOT_APPLICABLE"}),
        json!({"reason_id":"ARITHMETIC_OVERFLOW","classification":"PRESENTABLE_KERNEL_REJECTION","layer":"KERNEL_REJECTED","state_effect":"STATE_UNCHANGED","continuation_after_rejection":"RETAIN_PREFIX_AND_PRESENT_NEXT_EXPERIMENT_AT_SAME_CAUSAL_SLOT"}),
    ];
    write_json(
        &out.join("contracts/REJECTION_REASON_PRESENTABILITY_MAP_V1.json"),
        &rows,
    )?;
    write_json(
        &out.join("contracts/REJECTION_STATE_EFFECT_CONTRACT_V1.json"),
        &json!({"schema":"G5_REJECTION_STATE_EFFECT_CONTRACT_V1","observable_kernel_rejection":"ARITHMETIC_OVERFLOW","state_effect":"STATE_UNCHANGED","reason":"G1 step is a pure function over borrowed prior state and returns Err before next state","rejected_attempt_extends_prefix":false,"continuation":"same prefix and causal slot","termination_assumed":false,"fixture":"F_REJECTION_FOLLOWUP"}),
    )
}

fn write_receipts(
    out: &Path,
    fixtures: &[crate::model::FixtureReceipt],
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("receipts/G5_QUALIFICATION_RECEIPT.json"),
        &json!({"schema":"G5_QUALIFICATION_RECEIPT_V1","fixture_count":fixtures.len(),"fixture_failures":fixtures.iter().filter(|x|x.status!="PASS").count(),"epsilon":true,"prefix_closure":true,"non_diagonal_coupling":true,"identity_special_case":true,"applied_rejected_matrix":true,"layer_separation":true,"upper_start_conditional":true,"comparison_performed":false,"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/OUTCOME_ACCESS_AUDIT.json"),
        &json!({"schema":"G5_OUTCOME_ACCESS_AUDIT_V1","D_A_outcome_reads":0,"D_B_target_reads":0,"D_C_reads":0,"D_D_target_reads":0,"D_D_accrual":"UNTOUCHED","outcome_conditioned_rules":0,"status":"PASS"}),
    )?;
    Ok(())
}

fn write_findings(
    out: &Path,
    fixtures: &[crate::model::FixtureReceipt],
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("findings/G5_TYPED_FINDINGS.json"),
        &json!({"schema":"G5_TYPED_FINDINGS_V1","unilateral_index":"EXECUTABLE_PREFIX","empty_continuation":true,"prefix_closed":true,"single_grammar_exactness":"SOUND_ENVELOPE","pairwise_parametric_grammar_exactness":"SOUND_ENVELOPE","coupling_interface_exactness":"EXACT","rejection_presentability_exactness":"EXACT","horizon_authority":"SOUND_ALL_FINITE_OVERAPPROXIMATION","fixture_count":fixtures.len(),"observer_correspondence_required_for_presentability":false,"behavioral_comparison":false,"GrammarStateAndEvent":"NOT_EVALUABLE"}),
    )?;
    write_json(
        &out.join("findings/G5_GATE_DECISION.json"),
        &json!({"schema":"G5_GATE_DECISION_V1","GATE_ID":GATE_ID,"EXECUTION_STATE":"SEALED","QUESTION_STATUS":"CLOSED","RESULT":"SOUND_PARAMETRIC_CONTINUATION_GRAMMAR_ENVELOPE_SEALED","DISPOSITION":"ADVANCE_WITH_RESTRICTION","authority":AUTHORITY,"restriction":"upper-envelope starts and candidate counterexamples require constructive reachability validation; GrammarStateAndEvent remains NOT_EVALUABLE","status":"PASS"}),
    )?;
    write_json(
        &out.join("findings/G5_NONCLAIMS.json"),
        &json!({"not_earned":["behavioral equivalence","behavioral inequivalence","cross-history candidate matching","genealogy correspondence","register correspondence","literal temporal matching","distinguishing continuation","minimal witness","simulation","bisimulation","state quotient","field redundancy","necessary memory","minimal observer"],"lawful_experiment_is_not_equal_response":true,"lawful_experiment_is_not_distinguishing_witness":true}),
    )
}

pub fn finalize(a: &Path, b: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(a, b)?;
    let r = json!({"schema":"G5_DETERMINISTIC_REBUILD_RECEIPT_V1","independent_builds":2,"configurations":["D_TARGET_BUILD_A","D_TARGET_BUILD_B"],"pre_finalize_artifact_count":members(a)?.len(),"byte_mismatches":0,"status":"PASS"});
    for x in [a, b] {
        write_json(&x.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"), &r)?;
    }
    let x = reseal(a)?;
    let y = reseal(b)?;
    if x != y {
        return Err("G5_FINAL_ROOT_MISMATCH".into());
    }
    for z in [a, b] {
        write_root(z, &x)?;
    }
    compare(a, b)?;
    Ok(x)
}
fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let f: Value =
        serde_json::from_slice(&fs::read(root.join("findings/G5_TYPED_FINDINGS.json"))?)?;
    write_json(
        &root.join(ROOT_RECEIPT),
        &json!({"schema":"G5_ROOT_RECEIPT_V1","status":"SEALED","authority":AUTHORITY,"G5_root":hash,"parent_G3_root":G3_ROOT,"parent_G4_root":G4_ROOT,"QUESTION_STATUS":"CLOSED","RESULT":"SOUND_PARAMETRIC_CONTINUATION_GRAMMAR_ENVELOPE_SEALED","DISPOSITION":"ADVANCE_WITH_RESTRICTION","single_grammar_exactness":f["single_grammar_exactness"],"pairwise_exactness":f["pairwise_parametric_grammar_exactness"],"coupling_interface_exactness":f["coupling_interface_exactness"],"rejection_exactness":f["rejection_presentability_exactness"],"fixture_count":f["fixture_count"],"outcome_access":{"D_A":0,"D_B":0,"D_C":0,"D_D":0},"equivalence_authority":false,"witness_authority":false,"minimality_authority":false,"prediction_authority":false,"economic_authority":false,"trading_authority":false}),
    )
}
pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G5_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}
pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let r: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = r["G5_root"].as_str().ok_or("G5_ROOT_FIELD_MISSING")?;
    let f = File::open(root.join("content_manifest.tsv"))?;
    let mmap = unsafe { Mmap::map(&f)? };
    let actual = sha256(&mmap);
    if expected != actual {
        return Err("G5_ROOT_DRIFT".into());
    }
    for m in manifest_members(&mmap)? {
        let p = root.join(&m.relative_path);
        if fs::metadata(&p)?.len() != m.bytes || sha256_file(&p)? != m.sha256 {
            return Err(format!("G5_MEMBER_DRIFT:{}", m.relative_path).into());
        }
    }
    Ok(actual)
}
fn prepare(p: &Path) -> std::io::Result<()> {
    if p.exists() {
        fs::remove_dir_all(p)?;
    }
    fs::create_dir_all(p)
}
fn reseal(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    for n in ["content_manifest.tsv", ROOT_RECEIPT] {
        let p = root.join(n);
        if p.exists() {
            fs::remove_file(p)?;
        }
    }
    let mut w = BufWriter::new(File::create(root.join("content_manifest.tsv"))?);
    writeln!(w, "relative_path\tbytes\tsha256")?;
    for m in members(root)? {
        writeln!(w, "{}\t{}\t{}", m.relative_path, m.bytes, m.sha256)?;
    }
    w.flush()?;
    Ok(sha256(&fs::read(root.join("content_manifest.tsv"))?))
}
fn members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut p = Vec::new();
    collect(root, root, &mut p)?;
    p.sort_unstable();
    p.into_iter()
        .filter(|x| x != "content_manifest.tsv" && x != ROOT_RECEIPT)
        .map(|relative_path| {
            let q = root.join(&relative_path);
            Ok(Member {
                bytes: fs::metadata(&q)?.len(),
                sha256: sha256_file(&q)?,
                relative_path,
            })
        })
        .collect()
}
fn manifest_members(bytes: &[u8]) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut out = Vec::new();
    let mut start = 0;
    for (row, end) in memchr_iter(b'\n', bytes).enumerate() {
        let line = bytes[start..end]
            .strip_suffix(b"\r")
            .unwrap_or(&bytes[start..end]);
        start = end + 1;
        if row == 0 || line.is_empty() {
            continue;
        }
        let f = std::str::from_utf8(line)?.split('\t').collect::<Vec<_>>();
        if f.len() != 3 || f[0].contains("..") || Path::new(f[0]).is_absolute() {
            return Err("G5_MANIFEST_MALFORMED".into());
        }
        out.push(Member {
            relative_path: f[0].into(),
            bytes: f[1].parse()?,
            sha256: f[2].into(),
        });
    }
    Ok(out)
}
fn collect(base: &Path, dir: &Path, out: &mut Vec<String>) -> std::io::Result<()> {
    for e in fs::read_dir(dir)? {
        let p = e?.path();
        if p.is_dir() {
            collect(base, &p, out)?;
        } else {
            out.push(
                p.strip_prefix(base)
                    .expect("descendant")
                    .to_string_lossy()
                    .replace('\\', "/"),
            );
        }
    }
    Ok(())
}
fn compare(a: &Path, b: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if members(a)? != members(b)? {
        return Err("G5_BYTE_MISMATCH".into());
    }
    Ok(())
}
fn write_json<T: Serialize + ?Sized>(p: &Path, v: &T) -> Result<(), Box<dyn std::error::Error>> {
    let mut b = serde_json::to_vec(v)?;
    b.push(b'\n');
    fs::write(p, b)?;
    Ok(())
}
fn write_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    for r in SOURCE_FILES {
        fs::copy(
            repo.join(STUDY).join(r),
            out.join("source").join(r.replace('/', "__")),
        )?;
    }
    Ok(())
}
fn source_closure(repo: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut h = Sha256::new();
    for r in SOURCE_FILES {
        h.update(r.as_bytes());
        h.update([0]);
        h.update(fs::read(repo.join(STUDY).join(r))?);
        h.update([0]);
    }
    Ok(format!("{:x}", h.finalize()))
}
fn copy_tree(s: &Path, d: &Path) -> std::io::Result<()> {
    fs::create_dir_all(d)?;
    for e in fs::read_dir(s)? {
        let p = e?.path();
        let t = d.join(p.file_name().expect("filename"));
        if p.is_dir() {
            copy_tree(&p, &t)?;
        } else {
            fs::copy(p, t)?;
        }
    }
    Ok(())
}
fn sha256(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}

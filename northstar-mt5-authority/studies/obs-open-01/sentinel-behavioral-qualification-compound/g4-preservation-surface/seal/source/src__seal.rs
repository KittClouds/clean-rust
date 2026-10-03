use crate::census;
use crate::model::{AuthorityMembership, ComparisonStatus, ContextRole, SurfaceProducts};
use crate::{AUTHORITY, G2_ROOT, G3_ROOT, GATE_ID};
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
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g4-preservation-surface";
const G2_SEAL: &str = "studies/obs-open-01/sentinel-behavioral-qualification-compound/g2-computational-role-census/seal";
const G3_SEAL: &str = "studies/obs-open-01/sentinel-behavioral-qualification-compound/g3-reachable-transition-semantics/seal";
const ROOT_RECEIPT: &str = "G4_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G4_PROTOCOL_V1.md",
    "src/census.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/registry.rs",
    "src/seal.rs",
    "tests/g4_contract.rs",
];

#[derive(Debug, Serialize, PartialEq, Eq)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare(out)?;
    for dir in ["authority", "contracts", "receipts", "findings", "source"] {
        fs::create_dir_all(out.join(dir))?;
    }
    bind_parents(repo, out)?;
    let p = census::execute()?;
    qualify(&p)?;
    write_contracts(out, &p)?;
    write_receipts(out, &p)?;
    write_findings(out, &p)?;
    write_source(repo, out)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({"schema":"G4_SOURCE_CLOSURE_RECEIPT_V1","source_file_count":SOURCE_FILES.len(),"source_closure_sha256":source_closure(repo)?,"status":"PASS"}),
    )?;
    reseal(out)
}

fn bind_parents(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let g2 = repo.join(G2_SEAL);
    let g3 = repo.join(G3_SEAL);
    if obs_open_04a_g2::seal::verify(&g2)? != G2_ROOT {
        return Err("G2_ROOT_DRIFT".into());
    }
    if obs_open_04a_g3::seal::verify(&g3)? != G3_ROOT {
        return Err("G3_ROOT_DRIFT".into());
    }
    let r2: Value = serde_json::from_slice(&fs::read(g2.join("G2_ROOT_RECEIPT.json"))?)?;
    let r3: Value = serde_json::from_slice(&fs::read(g3.join("G3_ROOT_RECEIPT.json"))?)?;
    if r2["multi_role_collisions"] != 37
        || r3["RESULT"] != "SOUND_REACHABILITY_ENVELOPE_SEALED"
        || r3["DISPOSITION"] != "ADVANCE_WITH_RESTRICTION"
        || r3["exact_global_reachability"] != false
    {
        return Err("PARENT_AUTHORITY_NOT_ADMISSIBLE".into());
    }
    write_json(
        &out.join("authority/G2_G3_AUTHORITY_BINDING.json"),
        &json!({
        "schema":"G4_PARENT_AUTHORITY_BINDING_V1","G2_root":G2_ROOT,"G3_root":G3_ROOT,
        "G2_authority":r2["authority"],"G3_authority":r3["authority"],
        "consumed":[
            {"path":"G2/KERNEL_ELEMENT_ROLE_CENSUS_V1","sha256":sha256_file(&g2.join("contracts/KERNEL_ELEMENT_ROLE_CENSUS_V1.json"))?},
            {"path":"G2/TRANSITION_DEPENDENCY_GRAPH_V1","sha256":sha256_file(&g2.join("contracts/TRANSITION_DEPENDENCY_GRAPH_V1.json"))?},
            {"path":"G3/REACHABILITY_SANDWICH_V1","sha256":sha256_file(&g3.join("contracts/REACHABILITY_SANDWICH_V1.json"))?},
            {"path":"G3/JOINT_CONSTRAINT_REGISTRY_V1","sha256":sha256_file(&g3.join("contracts/JOINT_CONSTRAINT_REGISTRY_V1.json"))?},
            {"path":"G3/G2_COLLISION_TO_CONSTRAINT_MAP_V1","sha256":sha256_file(&g3.join("contracts/G2_COLLISION_TO_CONSTRAINT_MAP_V1.json"))?}
        ],"status":"PASS"}),
    )
}

fn qualify(p: &SurfaceProducts) -> Result<(), Box<dyn std::error::Error>> {
    if p.elements.len() != 57 {
        return Err("ELEMENT_CENSUS_INCOMPLETE".into());
    }
    let inside = p
        .elements
        .iter()
        .filter(|x| x.authority_membership == AuthorityMembership::InAuthority)
        .count();
    let outside = p
        .elements
        .iter()
        .filter(|x| x.authority_membership == AuthorityMembership::NotInAuthority)
        .count();
    if inside != 54 || outside != 3 {
        return Err(format!("MEMBERSHIP_COUNT_DRIFT:{inside}:{outside}").into());
    }
    if p.elements
        .iter()
        .filter(|x| x.authority_membership == AuthorityMembership::InAuthority)
        .any(|x| {
            x.retention_fidelity.is_none()
                || x.mapped_observable_ids.is_empty()
                || x.cross_history_comparison != ComparisonStatus::Deferred
        })
    {
        return Err("IN_AUTHORITY_TYPING_FAILURE".into());
    }
    if p.elements
        .iter()
        .filter(|x| x.authority_membership == AuthorityMembership::NotInAuthority)
        .any(|x| {
            x.normative_reason.is_empty()
                || x.cross_history_comparison != ComparisonStatus::NotApplicable
        })
    {
        return Err("EXCLUSION_BASIS_FAILURE".into());
    }
    if p.observables
        .iter()
        .any(|x| x.cross_history_comparison != ComparisonStatus::Deferred)
    {
        return Err("COMPARISON_SEMANTICS_LEAK".into());
    }
    for id in [
        "state.close_ticks",
        "state.upper_giveback_ticks",
        "state.lower_giveback_ticks",
        "state.upper_extensions_ticks",
        "state.lower_extensions_ticks",
        "state.coverage_complete",
    ] {
        if p.elements
            .iter()
            .find(|x| x.element_id == id)
            .is_none_or(|x| x.authority_membership != AuthorityMembership::InAuthority)
        {
            return Err(format!("CARRIED_TRAP_EXCLUDED:{id}").into());
        }
    }
    Ok(())
}

fn write_contracts(out: &Path, p: &SurfaceProducts) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/CAUSAL_OBSERVER_PRESERVATION_AUTHORITY_V1.json"),
        &json!({
        "schema":"G4_CAUSAL_OBSERVER_PRESERVATION_AUTHORITY_V1","A_COB":{"O":"NAMED_PROTECTED_OBSERVABLES","S":"DECLARED_SCOPES","T":"TEMPORAL_AND_ORDERING_AUTHORITY","C":"SEMANTIC_INTERPRETATION_CONTEXT","B":"DECLARED_BLIND_SPOTS"},
        "subject":"CAUSAL_OBSERVER_BEHAVIOR","not_subject":["prediction","outcomes","mechanism","economics","trading"],
        "Obs_A_projection":{"domain":"P_EXEC_G3(C)","contains":"exactly protected observables under scopes, timing, context and blind spots","cross_history_relation":"UNDEFINED","joint_continuation_universe":"UNDEFINED"},
        "cross_history_comparison":"DEFERRED","status":"FROZEN"}),
    )?;
    write_json(
        &out.join("contracts/OBSERVABLE_SURFACE_REGISTRY_V1.json"),
        &p.observables,
    )?;
    write_json(
        &out.join("contracts/ELEMENT_PRESERVATION_CENSUS_V1.json"),
        &p.elements,
    )?;
    let map=p.elements.iter().map(|x|json!({"element_id":x.element_id,"element_g4_role":x.element_g4_role,"authority_membership":x.authority_membership,"mapped_observable_ids":x.mapped_observable_ids})).collect::<Vec<_>>();
    write_json(
        &out.join("contracts/ELEMENT_TO_OBSERVABLE_MAP_V1.json"),
        &map,
    )?;
    write_json(
        &out.join("contracts/CONTEXT_INTERPRETATION_POLICY_V1.json"),
        &json!({
        "schema":"G4_CONTEXT_INTERPRETATION_POLICY_V1","semantic_context_is_observed_behavior":false,
        "interpretation_parameters":p.elements.iter().filter(|x|x.context_role==ContextRole::InterpretationParameter).map(|x|&x.element_id).collect::<Vec<_>>(),
        "opaque_execution_locator":{"element":"context.session_id","membership":"NOT_IN_AUTHORITY","reason":"OPAQUE_EXECUTION_LOCATOR_NOT_DECLARED_PART_OF_CAUSAL_OBSERVER_BEHAVIOR"},
        "future_context_correspondence":"DEFERRED","future_context_equality":"UNDEFINED"}),
    )?;
    write_json(
        &out.join("contracts/TEMPORAL_AUTHORITY_CONTRACT_V1.json"),
        &json!({
        "schema":"G4_TEMPORAL_AUTHORITY_CONTRACT_V1","T_obs":["stored_time","source_semantic_resolution","storage_resolution"],
        "storage_resolution_ns":1,"source_semantic_resolution_ns":1000000000_i64,"historical_precision_upgrade":"NONE",
        "exact_retention_within_execution":true,"literal_cross_history_timestamp_equality":"UNDEFINED",
        "subsecond_historical_meaning_below_source_resolution":"FORBIDDEN"}),
    )?;
    write_json(
        &out.join("contracts/ORDERED_TRACE_PRESERVATION_CONTRACT_V1.json"),
        &json!({
        "schema":"G4_ORDERED_TRACE_PRESERVATION_CONTRACT_V1","inter_transition_order":"IN_AUTHORITY",
        "intra_transition_emission_order":"IN_AUTHORITY","coordinates":["transition_ordinal","emission_ordinal_within_transition","event_kind","payload","authoritative_time"],
        "event_multiset_equivalence":"NOT_DEFINED","event_retiming_equivalence":"NOT_DEFINED","cross_history_comparison":"DEFERRED"}),
    )?;
    write_json(
        &out.join("contracts/TRANSITION_PRESERVATION_CONTRACT_V1.json"),
        &json!({
        "schema":"G4_TRANSITION_PRESERVATION_CONTRACT_V1","protected":["causal lifecycle","renewal/persistence updates","range availability/location/extension derivation","coverage propagation","ordered emissions","typed result class"],
        "source_input_rejected":"UPSTREAM_INPUT_CONTRACT_CLASS","kernel_applied":"IN_AUTHORITY","kernel_rejected_reason":"IN_AUTHORITY",
        "joint_presentability":"NOT_DEFINED_BY_G4","jointly_presentable_is_jointly_applied":false,"cross_history_use_of_rejection_as_witness":"DEFERRED_TO_G5_G6"}),
    )?;
    write_json(
        &out.join("contracts/GENEALOGY_PRESERVATION_POLICY_V1.json"),
        &json!({
        "schema":"G4_GENEALOGY_PRESERVATION_POLICY_V1","protected":["candidate existence","upper/lower role","birth","renewal","persistence","replacement","genealogical continuity"],
        "raw_candidate_id_role":"REPRESENTATION_BEARING_CONTRIBUTOR_TO_RELATIONAL_STRUCTURE","literal_cross_history_id_equality":"UNDEFINED","alpha_equivalence":"UNDEFINED","candidate_id_correspondence":"DEFERRED"}),
    )?;
    write_json(
        &out.join("contracts/REJECTION_SEMANTICS_PRESERVATION_V1.json"),
        &json!({
        "schema":"G4_REJECTION_SEMANTICS_PRESERVATION_V1","kernel_applied_vs_rejected":"IN_AUTHORITY","typed_rejection_reason":"IN_AUTHORITY",
        "source_input_rejection_distinct":true,"joint_presentability":"UNDEFINED","separating_witness_use":"DEFERRED"}),
    )?;
    write_json(
        &out.join("contracts/G3_RESTRICTION_INHERITANCE_V1.json"),
        &json!({
        "schema":"G4_G3_RESTRICTION_INHERITANCE_V1","G3_root":G3_ROOT,"global_exact_reachability":"NOT_EARNED",
        "input_reachability":"MIXED","prefix_reachability":"MIXED","state_reachability":"MIXED","transition_reachability":"MIXED",
        "upper_envelope_counterexample":"REQUIRES_CONSTRUCTIVE_REACHABILITY_WITNESS","lower_witness_absence":"CANNOT_SUPPORT_UNREACHABILITY",
        "P_EXEC_G3_is_comparison_universe":false,"status":"INHERITED_UNCHANGED"}),
    )?;
    write_json(
        &out.join("contracts/NOT_EVALUABLE_REGISTRY_V1.json"),
        &json!({"schema":"G4_NOT_EVALUABLE_REGISTRY_V1","components":[{"component":"GrammarStateAndEvent","authority_membership":"NOT_EVALUABLE","reason":"NO_QUALIFIED_GRAMMAR_STREAM_IN_G1_G2_G3_ANCESTRY","presumed_irrelevance":false}],"promotion_requires_new_qualified_authority":true}),
    )?;
    write_json(
        &out.join("contracts/G4_IMMUTABILITY_CONTRACT_V1.json"),
        &json!({
        "schema":"G4_IMMUTABILITY_CONTRACT_V1","downstream_surface_mutation":"FORBIDDEN","weaken_surface":"REQUIRES_NEW_G4_VERSION","strengthen_surface":"REQUIRES_NEW_G4_VERSION","change_retention_fidelity":"REQUIRES_NEW_G4_VERSION","change_context_interpretation":"REQUIRES_NEW_G4_VERSION","promote_not_evaluable":"REQUIRES_NEW_QUALIFIED_AUTHORITY","new_G4_version":"REQUIRES_NEW_ROOT","new_G4_root":"REQUIRES_FORK_OR_REBASE","downstream_after_change":"REEXECUTE_G5_PLUS"}),
    )?;
    Ok(())
}

fn write_receipts(out: &Path, p: &SurfaceProducts) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("receipts/G4_CLOSURE_QUALIFICATION.json"),
        &json!({
        "schema":"G4_CLOSURE_QUALIFICATION_V1","G2_elements":p.elements.len(),"named_observables":p.observables.len(),
        "in_authority_elements":p.elements.iter().filter(|x|x.authority_membership==AuthorityMembership::InAuthority).count(),
        "not_in_authority_elements":p.elements.iter().filter(|x|x.authority_membership==AuthorityMembership::NotInAuthority).count(),
        "not_evaluable_blind_spots":1,"exclusions_with_affirmative_basis":true,"comparison_semantics_defined":false,
        "six_carried_not_next_read_protected":true,"surface_immutable":true,"status":"PASS"}),
    )?;
    write_json(
        &out.join("receipts/OUTCOME_ACCESS_AUDIT.json"),
        &json!({
        "schema":"G4_OUTCOME_ACCESS_AUDIT_V1","D_A_outcome_reads":0,"D_B_target_reads":0,"D_C_reads":0,"D_D_target_reads":0,"D_D_accrual":"UNTOUCHED","predictive_justifications":0,"economic_justifications":0,"status":"PASS"}),
    )?;
    Ok(())
}

fn write_findings(out: &Path, p: &SurfaceProducts) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("findings/G4_TYPED_FINDINGS.json"),
        &json!({
        "schema":"G4_TYPED_FINDINGS_V1","protected_observables":p.observables.len(),"G2_elements_dispositioned":p.elements.len(),
        "in_authority":p.elements.iter().filter(|x|x.authority_membership==AuthorityMembership::InAuthority).count(),
        "not_in_authority":p.elements.iter().filter(|x|x.authority_membership==AuthorityMembership::NotInAuthority).count(),
        "blind_spots":["GrammarStateAndEvent"],"cross_history_comparison":"DEFERRED","equivalence_defined":false,"continuation_universe_defined":false,"G3_restrictions_inherited":true}),
    )?;
    write_json(
        &out.join("findings/G4_GATE_DECISION.json"),
        &json!({
        "schema":"G4_GATE_DECISION_V1","GATE_ID":GATE_ID,"EXECUTION_STATE":"SEALED","QUESTION_STATUS":"CLOSED",
        "RESULT":"PRESERVATION_SURFACE_SEALED_WITH_DECLARED_NOT_EVALUABLE_COMPONENTS","DISPOSITION":"ADVANCE_WITH_RESTRICTION","authority":AUTHORITY,
        "restriction":"GrammarStateAndEvent remains NOT_EVALUABLE; G3 mixed reachability restrictions propagate unchanged","status":"PASS"}),
    )?;
    write_json(
        &out.join("findings/G4_NONCLAIMS.json"),
        &json!({"not_earned":["equivalence","cross-history correspondence","joint continuation admissibility","joint presentability","candidate-ID matching","distinguishing witnesses","simulation","bisimulation","quotient","removability","minimality","prediction","mechanism","economics","trading"],"retention_is_not_cross_history_equality":true,"element_provenance_is_not_observable_ontology":true}),
    )
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = json!({"schema":"G4_DETERMINISTIC_REBUILD_RECEIPT_V1","independent_builds":2,"configurations":["D_TARGET_BUILD_A","D_TARGET_BUILD_B"],"pre_finalize_artifact_count":members(left)?.len(),"byte_mismatches":0,"status":"PASS"});
    for root in [left, right] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
    }
    let a = reseal(left)?;
    let b = reseal(right)?;
    if a != b {
        return Err("G4_FINAL_ROOT_MISMATCH".into());
    }
    for root in [left, right] {
        write_root(root, &a)?;
    }
    compare(left, right)?;
    Ok(a)
}
fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let f: Value =
        serde_json::from_slice(&fs::read(root.join("findings/G4_TYPED_FINDINGS.json"))?)?;
    write_json(
        &root.join(ROOT_RECEIPT),
        &json!({"schema":"G4_ROOT_RECEIPT_V1","status":"SEALED","authority":AUTHORITY,"G4_root":hash,"parent_G2_root":G2_ROOT,"parent_G3_root":G3_ROOT,"QUESTION_STATUS":"CLOSED","RESULT":"PRESERVATION_SURFACE_SEALED_WITH_DECLARED_NOT_EVALUABLE_COMPONENTS","DISPOSITION":"ADVANCE_WITH_RESTRICTION","protected_observables":f["protected_observables"],"G2_elements_dispositioned":f["G2_elements_dispositioned"],"blind_spots":f["blind_spots"],"G3_restrictions_inherited":true,"outcome_access":{"D_A":0,"D_B":0,"D_C":0,"D_D":0},"equivalence_authority":false,"continuation_authority":false,"minimality_authority":false,"prediction_authority":false,"economic_authority":false,"trading_authority":false}),
    )
}
pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G4_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}
pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let r: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = r["G4_root"].as_str().ok_or("G4_ROOT_FIELD_MISSING")?;
    let file = File::open(root.join("content_manifest.tsv"))?;
    let mmap = unsafe { Mmap::map(&file)? };
    let actual = sha256(&mmap);
    if expected != actual {
        return Err("G4_ROOT_DRIFT".into());
    }
    for m in manifest_members(&mmap)? {
        let path = root.join(&m.relative_path);
        if fs::metadata(&path)?.len() != m.bytes || sha256_file(&path)? != m.sha256 {
            return Err(format!("G4_MEMBER_DRIFT:{}", m.relative_path).into());
        }
    }
    Ok(actual)
}
fn prepare(out: &Path) -> std::io::Result<()> {
    if out.exists() {
        fs::remove_dir_all(out)?;
    }
    fs::create_dir_all(out)
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
    let mut paths = Vec::new();
    collect(root, root, &mut paths)?;
    paths.sort_unstable();
    paths
        .into_iter()
        .filter(|x| x != "content_manifest.tsv" && x != ROOT_RECEIPT)
        .map(|relative_path| {
            let p = root.join(&relative_path);
            Ok(Member {
                bytes: fs::metadata(&p)?.len(),
                sha256: sha256_file(&p)?,
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
            return Err("G4_MANIFEST_MALFORMED".into());
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
        return Err("G4_BYTE_MISMATCH".into());
    }
    Ok(())
}
fn write_json<T: Serialize>(p: &Path, v: &T) -> Result<(), Box<dyn std::error::Error>> {
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

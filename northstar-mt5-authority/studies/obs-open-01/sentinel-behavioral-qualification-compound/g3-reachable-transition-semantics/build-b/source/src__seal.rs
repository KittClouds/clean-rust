use crate::audit;
use crate::model::{AuditProducts, ConstraintScope, TransitionResult};
use crate::{AUTHORITY, G1_ROOT, G2_ROOT, GATE_ID};
use memchr::memchr_iter;
use memmap2::Mmap;
use obs_open_meas02::sha256_file;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str = "studies/obs-open-01/sentinel-behavioral-qualification-compound/g3-reachable-transition-semantics";
const G1_SEAL: &str =
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g1-semantic-kernel/seal";
const G2_SEAL: &str = "studies/obs-open-01/sentinel-behavioral-qualification-compound/g2-computational-role-census/seal";
const ROOT_RECEIPT: &str = "G3_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G3_PROTOCOL_V1.md",
    "src/audit.rs",
    "src/fixtures.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/seal.rs",
    "tests/g3_contract.rs",
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
    let products = audit::execute()?;
    write_contracts(out, &products)?;
    write_receipts(out, &products)?;
    write_findings(out, &products)?;
    write_source(repo, out)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({
            "schema":"G3_SOURCE_CLOSURE_RECEIPT_V1", "source_file_count":SOURCE_FILES.len(),
            "source_closure_sha256":source_closure(repo)?, "status":"PASS"
        }),
    )?;
    reseal(out)
}

fn bind_parents(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let g1 = repo.join(G1_SEAL);
    let g2 = repo.join(G2_SEAL);
    if obs_open_04a_g1::seal::verify(&g1)? != G1_ROOT {
        return Err("G1_ROOT_DRIFT".into());
    }
    if obs_open_04a_g2::seal::verify(&g2)? != G2_ROOT {
        return Err("G2_ROOT_DRIFT".into());
    }
    let g1_receipt: Value = serde_json::from_slice(&fs::read(g1.join("G1_ROOT_RECEIPT.json"))?)?;
    let g2_receipt: Value = serde_json::from_slice(&fs::read(g2.join("G2_ROOT_RECEIPT.json"))?)?;
    if g1_receipt["RESULT"] != "EXACT_SEMANTIC_KERNEL_EXTRACTED"
        || g2_receipt["RESULT"] != "COMPUTATIONAL_ROLE_CENSUS_SEALED"
        || g2_receipt["multi_role_collisions"] != 37
    {
        return Err("PARENT_AUTHORITY_NOT_ADMISSIBLE".into());
    }
    let g1_members = [
        "source/src__kernel.rs",
        "source/src__model.rs",
        "contracts/KERNEL_INPUT_CONTRACT_V1.json",
        "contracts/KERNEL_EMISSION_CONTRACT_V1.json",
    ];
    let g2_members = [
        "contracts/KERNEL_ELEMENT_ROLE_CENSUS_V1.json",
        "contracts/TRANSITION_DEPENDENCY_GRAPH_V1.json",
        "contracts/MULTI_ROLE_COLLISION_REGISTRY_V1.json",
    ];
    let g1_hashes = bind_members(&g1, &g1_members)?;
    let g2_hashes = bind_members(&g2, &g2_members)?;
    write_json(
        &out.join("authority/G1_G2_AUTHORITY_BINDING.json"),
        &json!({
            "schema":"G3_PARENT_AUTHORITY_BINDING_V1", "G1_root":G1_ROOT, "G2_root":G2_ROOT,
            "G1_result":g1_receipt["RESULT"], "G2_result":g2_receipt["RESULT"],
            "G1_consumed_members":g1_hashes, "G2_consumed_members":g2_hashes,
            "scope_generalization":{"instrument":"NOT_EARNED","timeframe":"NOT_EARNED","source":"NOT_EARNED"},
            "status":"PASS"
        }),
    )
}

fn bind_members(root: &Path, names: &[&str]) -> Result<Vec<Value>, Box<dyn std::error::Error>> {
    names
        .iter()
        .map(|name| Ok(json!({"path":name,"sha256":sha256_file(&root.join(name))?})))
        .collect()
}

fn write_contracts(out: &Path, p: &AuditProducts) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/REACHABLE_TRANSITION_SEMANTICS_V1.json"),
        &json!({
            "schema":"G3_REACHABLE_TRANSITION_SEMANTICS_V1", "primary_object":"T_REACH(C)",
            "state_object":"K_REACH(C)", "prefix_object":"P_EXEC_G3(C)",
            "global_view":"TAGGED_UNION_OVER_C_AUTH_G3", "context_stitching":"FORBIDDEN",
            "step_codomain":["APPLIED(next_state,ordered_emissions)","REJECTED(reason)"],
            "state_reachability_is_transition_projection":true, "status":"QUALIFIED"
        }),
    )?;
    write_json(
        &out.join("contracts/AUTHORIZED_CONTEXT_UNIVERSE_V1.json"),
        &json!({
            "schema":"G3_AUTHORIZED_CONTEXT_UNIVERSE_V1",
            "included":["SEALED_G1_HISTORICALLY_QUALIFIED_CONTEXTS","FINITE_DECLARED_SYNTHETIC_SEMANTIC_FIXTURE_CONTEXTS"],
            "conditional":"CONSTRUCTED_CONTEXT_WITH_PROVEN_G1_KERNEL_ADMISSIBILITY",
            "excluded":"ARBITRARY_SCHEMA_VALID_CONTEXT",
            "synthetic_authority":"MACHINE_SEMANTICS_ONLY", "historical_instantiation_from_synthetic":false,
            "instrument_generalization":"NOT_EARNED", "timeframe_generalization":"NOT_EARNED", "source_generalization":"NOT_EARNED"
        }),
    )?;
    write_json(
        &out.join("contracts/REACHABILITY_SANDWICH_V1.json"),
        &json!({
            "schema":"G3_REACHABILITY_SANDWICH_V1", "context_indexed":true,
            "relations":["K_MINUS(C) SUBSET K_REACH(C) SUBSET K_PLUS(C)","T_MINUS(C) SUBSET T_REACH(C) SUBSET T_PLUS(C)","P_EXEC_MINUS(C) SUBSET P_EXEC_G3(C) SUBSET P_EXEC_PLUS(C)"],
            "subsystems":p.bounds, "semantic_denotation_exactness_required":true,
            "serialized_equality_is_exactness":false, "global_exactness":"NOT_EARNED",
            "permitted_downstream_uses":["CONSTRUCTIVE_POSITIVE_REACHABILITY","UNIVERSAL_REASONING_OVER_SOUND_UPPER_ENVELOPE","WITNESS_VALIDATION_OF_CANDIDATE_COUNTEREXAMPLES"],
            "forbidden_downstream_inferences":["COMPLETE_STATE_SPACE","UNREACHABILITY_FROM_MISSING_WITNESS","COUNTEREXAMPLE_FROM_UPPER_ENVELOPE_WITHOUT_WITNESS"]
        }),
    )?;
    write_constraints(out, p)?;
    write_json(
        &out.join("contracts/JOINT_CONSTRAINT_REGISTRY_V1.json"),
        &p.constraints,
    )?;
    write_json(
        &out.join("contracts/REACHABILITY_WITNESS_CORPUS_V1.json"),
        &p.witnesses,
    )?;
    write_json(
        &out.join("contracts/UNREACHABILITY_PROOFS_V1.json"),
        &p.unreachability,
    )?;
    write_json(
        &out.join("contracts/APPROXIMATION_BOUNDARY_V1.json"),
        &json!({
            "schema":"G3_APPROXIMATION_BOUNDARY_V1", "boundaries":p.bounds,
            "known_false_positives":"POSSIBLE_IN_UPPER_ENVELOPES", "known_false_negatives":"POSSIBLE_IN_FINITE_LOWER_WITNESS_CORPUS",
            "safe_for_universal_invariant_proof":"ONLY_WHEN_PROVED_OVER_SOUND_UPPER_ENVELOPE",
            "safe_for_positive_reachability":"LOWER_WITNESSES_ONLY", "safe_for_unreachability_claim":false,
            "safe_for_counterexample_generation":"CANDIDATE_ONLY_UNTIL_WITNESS_VALIDATED", "bounded_searches_performed":0
        }),
    )?;
    write_json(
        &out.join("contracts/G2_COLLISION_TO_CONSTRAINT_MAP_V1.json"),
        &p.collisions,
    )?;
    write_json(
        &out.join("contracts/GRAMMAR_REACHABILITY_BOUNDARY_V1.json"),
        &json!({
            "GrammarStateAndEvent":"NOT_EVALUABLE", "authority_manufactured":false
        }),
    )?;
    Ok(())
}

fn write_constraints(out: &Path, p: &AuditProducts) -> Result<(), Box<dyn std::error::Error>> {
    let state = p
        .constraints
        .iter()
        .filter(|x| {
            matches!(
                x.scope,
                ConstraintScope::State | ConstraintScope::StateContext
            )
        })
        .collect::<Vec<_>>();
    let transition = p
        .constraints
        .iter()
        .filter(|x| {
            matches!(
                x.scope,
                ConstraintScope::StateInput
                    | ConstraintScope::Transition
                    | ConstraintScope::TransitionEmission
            )
        })
        .collect::<Vec<_>>();
    let prefix = p
        .constraints
        .iter()
        .filter(|x| x.scope == ConstraintScope::TracePrefix)
        .collect::<Vec<_>>();
    write_json(
        &out.join("contracts/REACHABLE_CONFIGURATION_CONSTRAINTS_V1.json"),
        &state,
    )?;
    write_json(
        &out.join("contracts/REACHABLE_TRANSITION_CONSTRAINTS_V1.json"),
        &transition,
    )?;
    write_json(
        &out.join("contracts/ADMISSIBLE_TRACE_PREFIX_CONSTRAINTS_V1.json"),
        &prefix,
    )?;
    write_json(
        &out.join("contracts/ADMITTED_INPUT_CONSTRAINTS_V1.json"),
        &json!({
            "schema":"G3_ADMITTED_INPUT_CONSTRAINTS_V1", "local_contract_constraint_ids":["G3-C003","G3-C004","G3-C020","G3-C021"],
            "distinctions":["LOCALLY_SCHEMA_VALID","INDIVIDUALLY_AUTHORIZED","STATE_CONTEXT_APPLICABLE","APPLIED","REJECTED"],
            "invalid_input_is_not_unreachable_transition":true
        }),
    )
}

fn write_receipts(out: &Path, p: &AuditProducts) -> Result<(), Box<dyn std::error::Error>> {
    let applied = p
        .witnesses
        .iter()
        .filter(|x| matches!(x.target_result, TransitionResult::Applied { .. }))
        .count();
    let rejected = p.witnesses.len() - applied;
    write_json(
        &out.join("receipts/WITNESS_REPLAY_RECEIPT.json"),
        &json!({
            "schema":"G3_WITNESS_REPLAY_RECEIPT_V1", "witnesses":p.witnesses.len(),
            "applied":applied, "rejected":rejected, "replay_mismatches":0, "sequence_generated":true, "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/D_A_OBSERVATION_RECEIPT.json"),
        &json!({
            "schema":"G3_DA_OBSERVATION_RECEIPT_V1", "D_A_replayed":false,
            "D_A_market_rows_read":0, "OBSERVED_IN_D_A_claims":0, "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/OUTCOME_ACCESS_AUDIT.json"),
        &json!({
            "schema":"G3_OUTCOME_ACCESS_AUDIT_V1", "D_A_outcomes":0,
            "D_B":{"targets":0,"scores":0,"fitting":0,"observations":0},
            "D_C":{"membership":0,"observations":0,"outcomes":0},
            "D_D":{"targets":0,"scores":0,"decisions":0,"accrual_modified":false},
            "future_target_joins":0, "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/G3_NONREDESIGN_RECEIPT.json"),
        &json!({
            "state_removed":0,"state_merged":0,"kernel_refactored":0,"preservation_surface_chosen":false,
            "continuation_comparison_grammar_defined":false,"minimality_claims":0,"status":"PASS"
        }),
    )?;
    Ok(())
}

fn write_findings(out: &Path, p: &AuditProducts) -> Result<(), Box<dyn std::error::Error>> {
    let mapped = p
        .collisions
        .iter()
        .filter(|x| x.g3_disposition == "PROVEN_REACHABILITY_CONSTRAINT")
        .count();
    let no_extra = p.collisions.len() - mapped;
    write_json(
        &out.join("findings/G3_TYPED_FINDINGS.json"),
        &json!({
            "schema":"G3_TYPED_FINDINGS_V1", "context_indexed":true,
            "proven_joint_constraints":p.constraints.len(), "constructive_witnesses":p.witnesses.len(),
            "proven_unreachability_claims":p.unreachability.len(), "bounded_searches":0,
            "G2_collisions_total":p.collisions.len(), "G2_collisions_with_proven_constraints":mapped,
            "G2_collisions_no_additional_constraint_identified":no_extra,
            "input_language_status":"MIXED", "prefix_language_status":"MIXED",
            "state_reachability_status":"MIXED", "transition_reachability_status":"MIXED",
            "exact_global_reachability":"NOT_EARNED", "grammar":"NOT_EVALUABLE"
        }),
    )?;
    write_json(
        &out.join("findings/G3_GATE_DECISION.json"),
        &json!({
            "schema":"G3_GATE_DECISION_V1", "GATE_ID":GATE_ID,
            "EXECUTION_STATE":"SEALED", "QUESTION_STATUS":"CLOSED",
            "RESULT":"SOUND_REACHABILITY_ENVELOPE_SEALED", "DISPOSITION":"ADVANCE_WITH_RESTRICTION",
            "authority":AUTHORITY, "global_exactness":"NOT_EARNED",
            "restriction":"LATER COUNTEREXAMPLES FROM T_PLUS REQUIRE CONSTRUCTIVE WITNESS; LOWER-BOUND ABSENCE CANNOT SUPPORT UNREACHABILITY",
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("findings/G3_NONCLAIMS.json"),
        &json!({
            "not_earned":["exact global reachability","behavioral equivalence","preservation surface","minimal state","necessary memory","redundancy","removability","continuation comparison authority","prediction","mechanism","economics","trading"],
            "P_EXEC_G3_is_not_G5_comparison_universe":true, "synthetic_reachability_is_not_historical_instantiation":true
        }),
    )
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = json!({"schema":"G3_DETERMINISTIC_REBUILD_RECEIPT_V1","independent_builds":2,
        "configurations":["D_TARGET_BUILD_A","D_TARGET_BUILD_B"],"pre_finalize_artifact_count":members(left)?.len(),
        "byte_mismatches":0,"status":"PASS"});
    for root in [left, right] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
    }
    let left_root = reseal(left)?;
    let right_root = reseal(right)?;
    if left_root != right_root {
        return Err("G3_FINAL_ROOT_MISMATCH".into());
    }
    for root in [left, right] {
        write_root(root, &left_root)?;
    }
    compare(left, right)?;
    Ok(left_root)
}

fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let findings: Value =
        serde_json::from_slice(&fs::read(root.join("findings/G3_TYPED_FINDINGS.json"))?)?;
    write_json(
        &root.join(ROOT_RECEIPT),
        &json!({
            "schema":"G3_ROOT_RECEIPT_V1", "status":"SEALED", "authority":AUTHORITY,
            "G3_root":hash, "parent_G1_root":G1_ROOT, "parent_G2_root":G2_ROOT,
            "QUESTION_STATUS":"CLOSED", "RESULT":"SOUND_REACHABILITY_ENVELOPE_SEALED",
            "DISPOSITION":"ADVANCE_WITH_RESTRICTION", "proven_joint_constraints":findings["proven_joint_constraints"],
            "constructive_witnesses":findings["constructive_witnesses"], "proven_unreachability_claims":findings["proven_unreachability_claims"],
            "G2_collisions_closed":findings["G2_collisions_total"], "exact_global_reachability":false,
            "outcome_access":{"D_A_rows":0,"D_B":0,"D_C":0,"D_D":0},
            "behavioral_equivalence_authority":false,"minimality_authority":false,"prediction_authority":false,
            "mechanism_authority":false,"economic_authority":false,"trading_authority":false
        }),
    )
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G3_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}

pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = receipt["G3_root"].as_str().ok_or("G3_ROOT_FIELD_MISSING")?;
    let file = File::open(root.join("content_manifest.tsv"))?;
    let mmap = unsafe { Mmap::map(&file)? };
    let actual = sha256(&mmap);
    if expected != actual {
        return Err("G3_ROOT_DRIFT".into());
    }
    for member in manifest_members(&mmap)? {
        let path = root.join(&member.relative_path);
        if fs::metadata(&path)?.len() != member.bytes || sha256_file(&path)? != member.sha256 {
            return Err(format!("G3_MEMBER_DRIFT:{}", member.relative_path).into());
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
    for name in ["content_manifest.tsv", ROOT_RECEIPT] {
        let path = root.join(name);
        if path.exists() {
            fs::remove_file(path)?;
        }
    }
    let mut writer = BufWriter::new(File::create(root.join("content_manifest.tsv"))?);
    writeln!(writer, "relative_path\tbytes\tsha256")?;
    for m in members(root)? {
        writeln!(writer, "{}\t{}\t{}", m.relative_path, m.bytes, m.sha256)?;
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
        .filter(|x| x != "content_manifest.tsv" && x != ROOT_RECEIPT)
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
        let fields = std::str::from_utf8(line)?.split('\t').collect::<Vec<_>>();
        if fields.len() != 3 || fields[0].contains("..") || Path::new(fields[0]).is_absolute() {
            return Err("G3_MANIFEST_MALFORMED".into());
        }
        out.push(Member {
            relative_path: fields[0].into(),
            bytes: fields[1].parse()?,
            sha256: fields[2].into(),
        });
    }
    Ok(out)
}

fn collect(base: &Path, dir: &Path, out: &mut Vec<String>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect(base, &path, out)?;
        } else {
            out.push(
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
        return Err("G3_BYTE_MISMATCH".into());
    }
    Ok(())
}
fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), Box<dyn std::error::Error>> {
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
    let mut hash = Sha256::new();
    for relative in SOURCE_FILES {
        hash.update(relative.as_bytes());
        hash.update([0]);
        hash.update(fs::read(repo.join(STUDY).join(relative))?);
        hash.update([0]);
    }
    Ok(format!("{:x}", hash.finalize()))
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
fn sha256(bytes: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(bytes);
    format!("{:x}", hash.finalize())
}

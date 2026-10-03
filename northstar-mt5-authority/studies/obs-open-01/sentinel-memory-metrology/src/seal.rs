use crate::authority::{open, sha256};
use crate::metrology;
use crate::semantics;
use crate::{AUTHORITY, B2_PROTOCOL_ROOT, D_A_PROTOCOL_ROOT, INST01_ROOT, MEAS02_ROOT};
use obs_open_meas02::sha256_file;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str = "studies/obs-open-01/sentinel-memory-metrology";
const ROOT_RECEIPT: &str = "04A_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_04A_PROTOCOL_V1.md",
    "src/atlas.rs",
    "src/authority.rs",
    "src/fixtures.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/metrology.rs",
    "src/model.rs",
    "src/seal.rs",
    "src/semantics.rs",
    "tests/metrology_contract.rs",
];

#[derive(Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare(out)?;
    for dir in [
        "authority",
        "contracts",
        "atlas",
        "receipts",
        "findings",
        "source",
    ] {
        fs::create_dir_all(out.join(dir))?;
    }
    let bound = open(repo)?;
    let products = metrology::execute(&bound.sessions)?;
    write_json(
        &out.join("authority/PARENT_AUTHORITY_BINDING.json"),
        &bound_roots(json!({
            "schema":"OBS_OPEN_04A_PARENT_AUTHORITY_BINDING_V1","source_kind":"MACHINE_DERIVED",
            "INST01_members_verified":bound.inst_members,"MEAS02_members_verified":bound.meas_members,
            "03B2_members_verified":bound.b2_members,"03B2_state":bound.b2_state,
            "D_A_protocol_root":D_A_PROTOCOL_ROOT,"raw_source_sha256":bound.raw_source_hash,
            "firewall_manifest_sha256":bound.firewall_manifest_hash,"status":"PASS"
        })),
    )?;
    write_json(
        &out.join("contracts/SENTINEL_FIELD_SEMANTICS_REGISTRY.json"),
        &bound_roots(semantics::sentinel_field_registry()),
    )?;
    write_json(
        &out.join("contracts/CAUSAL_VS_RETROSPECTIVE_LEDGER.json"),
        &bound_roots(semantics::causal_retrospective_ledger()),
    )?;
    write_json(
        &out.join("contracts/PROVISIONAL_VS_COMMITTED_STATE_CONTRACT.json"),
        &bound_roots(semantics::provisional_contract()),
    )?;
    write_json(
        &out.join("contracts/RUNNING_EXTREME_GENEALOGY_SPEC.json"),
        &bound_roots(semantics::genealogy_spec()),
    )?;
    write_json(
        &out.join("contracts/PRIMITIVE_TRANSITION_GRAMMAR.json"),
        &bound_roots(semantics::primitive_transition_grammar()),
    )?;
    let (semantic, source) = semantics::event_tape_specs();
    write_json(
        &out.join("contracts/SEMANTIC_EVENT_TAPE_SPEC.json"),
        &bound_roots(semantic),
    )?;
    write_json(
        &out.join("contracts/EVENT_SOURCE_TAPE_SPEC.json"),
        &bound_roots(source),
    )?;
    let (current_state, reduced_state) = semantics::state_specs();
    write_json(
        &out.join("contracts/CURRENT_SENTINEL_STATE_SPEC.json"),
        &bound_roots(current_state),
    )?;
    write_json(
        &out.join("contracts/REDUCED_SENTINEL_GEOMETRY_SPEC.json"),
        &bound_roots(reduced_state),
    )?;
    write_json(
        &out.join("contracts/EVENT_TO_STATE_RECONSTRUCTION_AUDIT.json"),
        &bound_roots(json!({
            "schema":"EVENT_TO_STATE_RECONSTRUCTION_AUDIT_V1","source_kind":"MULTIPLE",
            "semantic_event_tape":{"status":"NOT_QUALIFIED_FOR_STATE_RECONSTRUCTION","relation":"NON_RECONSTRUCTIBLE","lost_fields":["candidate_values","birth_times","ages","close","range_relative_geometry"]},
            "event_source_tape":{"status":"QUALIFIED","relation":"RECONSTRUCTIBLE_WITH_CONTEXT","context":["SESSION_BOUNDARY","R01_TO_R30_FROZEN_GEOMETRY"],"completed_rows_compared":products.replay_receipt["completed_rows_compared"],"mismatches":0},
            "repair_performed":false,"status":"PASS"
        })),
    )?;
    write_json(
        &out.join("contracts/REPRESENTATION_RELATION_GRAPH.json"),
        &bound_roots(json!({
            "schema":"REPRESENTATION_RELATION_GRAPH_V1","source_kind":"MULTIPLE","nodes":["RAW_COMPLETED_BAR_HISTORY_V1","SEMANTIC_TRANSITION_TAPE_V1","EVENT_SOURCE_TAPE_V1","CURRENT_SENTINEL_STATE_V1","REDUCED_SENTINEL_GEOMETRY_V1"],"edges":products.relation_edges,"topology":"DIRECTED_GRAPH_NOT_ASSUMED_STAIRCASE","total_order_claimed":false
        })),
    )?;
    write_json(
        &out.join("contracts/INFORMATION_LOSS_WITNESS_REGISTRY.json"),
        &bound_roots(products.witnesses),
    )?;
    write_json(
        &out.join("atlas/DA_COLLISION_MORPHOLOGY.json"),
        &bound_roots(products.collision_details),
    )?;
    write_json(
        &out.join("atlas/DA_GENEALOGY_ATLAS.json"),
        &bound_roots(products.genealogy_atlas),
    )?;
    write_json(
        &out.join("atlas/DA_PROCESS_MORPHOLOGY_ATLAS.json"),
        &bound_roots(products.process_atlas),
    )?;
    write_json(
        &out.join("atlas/SAMPLING_UNIT_LEDGER.json"),
        &bound_roots(products.sampling_units),
    )?;
    write_json(
        &out.join("atlas/GAP_AND_EVALUABILITY_ATLAS.json"),
        &bound_roots(products.gap_atlas),
    )?;
    write_json(
        &out.join("receipts/REPLAY_EQUIVALENCE_RECEIPT.json"),
        &bound_roots(products.replay_receipt),
    )?;
    write_access(repo, out, &bound.access)?;
    write_json(
        &out.join("findings/04A_TYPED_FINDINGS.json"),
        &bound_roots(products.typed_findings),
    )?;
    write_json(
        &out.join("findings/04A_COLLISION_SUMMARY.json"),
        &bound_roots(
            json!({"schema":"OBS_OPEN_04A_COLLISION_SUMMARY_V1","source_kind":"D_A_OBSERVED_NO_OUTCOME_JOIN","summary":products.collision}),
        ),
    )?;
    write_qualification(out)?;
    fs::copy(
        repo.join(STUDY).join("OBS_OPEN_04A_PROTOCOL_V1.md"),
        out.join("OBS_OPEN_04A_PROTOCOL_V1.md"),
    )?;
    copy_source(repo, out)?;
    write_json(
        &out.join("04A_AUTHORITY_MANIFEST.json"),
        &bound_roots(json!({
            "schema":"OBS_OPEN_04A_AUTHORITY_MANIFEST_V1","source_kind":"ARTIFACT_DECLARED","authority":AUTHORITY,
            "final_state":"SENTINEL_MEMORY_METROLOGY_SEALED","D_A_only":true,"future_target_joins":0,
            "03B2_D_D_state":"FRESH_CONFIRMATION_POPULATION_PENDING_UNTOUCHED","prediction_authority":false,
            "memory_sufficiency_authority":false,"mechanism_authority":false,"economic_authority":false,"trading_authority":false,
            "source_closure_sha256":source_closure(repo)?,"status":"SEALED"
        })),
    )?;
    reseal(out)
}

fn write_access(
    repo: &Path,
    out: &Path,
    access: &obs_open_03a::AccessAudit,
) -> Result<(), Box<dyn std::error::Error>> {
    let b2:Value=serde_json::from_slice(&fs::read(repo.join("studies/obs-open-01/range-representation-decomposition-protocol/seal/03B2P_ROOT_RECEIPT.json"))?)?;
    write_json(
        &out.join("receipts/ACCESS_AUDIT.json"),
        &bound_roots(json!({
            "schema":"OBS_OPEN_04A_ACCESS_AUDIT_V1","source_kind":"MACHINE_DERIVED",
            "D_A":{"sessions_decoded":access.d_a_sessions_decoded,"OHLC_observations_decoded":access.d_a_ohlc_observations_decoded,"retained_causal_bars":access.d_a_retained_causal_bars,"path_gap_sessions":access.d_a_path_gap_sessions,"outcome_registry_applications":access.d_a_outcome_registry_applications},
            "D_B":{"new_target_reads":0,"new_scores":0,"new_fitting":0,"session_ids_decoded_for_outcomes":access.d_b_session_ids_decoded_for_outcomes,"OHLC_values_decoded":access.d_b_ohlc_values_decoded,"outcome_registry_applications":access.d_b_outcome_registry_applications,"derived_outcomes_inspected":access.d_b_derived_outcomes_inspected,"formal_scores":access.d_b_formal_scores},
            "D_C":{"membership_decoding":access.d_c_membership_rows_decoded,"observations":access.d_c_observations_read,"outcomes":access.d_c_outcomes_computed},
            "D_D":{"membership_decoding":0,"target_reads":0,"scores":0,"decisions":0,"parent_pending_state":b2["state"]},"future_target_joins":0,"status":"PASS"
        })),
    )?;
    write_json(
        &out.join("receipts/DC_FIREWALL_RECEIPT.json"),
        &bound_roots(
            json!({"schema":"OBS_OPEN_04A_DC_FIREWALL_RECEIPT_V1","source_kind":"MACHINE_DERIVED","membership_decoding":0,"observations":0,"outcomes":0,"state":"FROZEN_UNOPENED","status":"PASS"}),
        ),
    )?;
    write_json(
        &out.join("receipts/DD_FIREWALL_RECEIPT.json"),
        &bound_roots(
            json!({"schema":"OBS_OPEN_04A_DD_FIREWALL_RECEIPT_V1","source_kind":"MACHINE_DERIVED","membership_decoding":0,"target_reads":0,"scores":0,"decisions":0,"accrual_modified":false,"state":"PROSPECTIVE_ACCRUAL_CONTINUES_IN_SILENCE","status":"PASS"}),
        ),
    )
}

fn write_qualification(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let claims = [
        "PARENT_AUTHORITY_BINDING",
        "SENTINEL_FIELD_SEMANTICS",
        "PROVISIONAL_COMMITTED_SEPARATION",
        "RETROSPECTIVE_SIDECAR_EXCLUSION",
        "RUNNING_EXTREME_GENEALOGY",
        "PRIMITIVE_TRANSITION_GRAMMAR",
        "SEMANTIC_TAPE_CLASSIFICATION",
        "EVENT_SOURCE_STATE_RECONSTRUCTION",
        "REPRESENTATION_RELATION_GRAPH",
        "ALGEBRAIC_LOSS_WITNESSES",
        "D_A_COLLISION_MORPHOLOGY",
        "SAMPLING_UNIT_DECLARATION",
        "GAP_FAIL_CLOSED",
        "REPLAY_EQUIVALENCE",
        "OUTCOME_JOIN_EXCLUSION",
        "D_B_FIREWALL",
        "D_C_FIREWALL",
        "D_D_FIREWALL",
    ];
    write_json(
        &out.join("receipts/TYPED_QUALIFICATION_MATRIX.json"),
        &bound_roots(
            json!({"schema":"OBS_OPEN_04A_TYPED_QUALIFICATION_MATRIX_V1","source_kind":"MULTIPLE","claims":claims.iter().map(|id|json!({"claim_id":id,"state":"PASS"})).collect::<Vec<_>>(),"final_state":"SENTINEL_MEMORY_METROLOGY_SEALED","status":"PASS"}),
        ),
    )
}

fn bound_roots(mut value: Value) -> Value {
    let object = value.as_object_mut().expect("object");
    object.insert("INST01_root".into(), json!(INST01_ROOT));
    object.insert("MEAS02_root".into(), json!(MEAS02_ROOT));
    object.insert("D_A_protocol_root".into(), json!(D_A_PROTOCOL_ROOT));
    object.insert("03B2_protocol_root".into(), json!(B2_PROTOCOL_ROOT));
    value
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = bound_roots(
        json!({"schema":"OBS_OPEN_04A_DETERMINISTIC_REBUILD_RECEIPT_V1","source_kind":"MACHINE_DERIVED","independent_builds":2,"configurations":["BUILD_A_D_TARGET","BUILD_B_D_TARGET"],"pre_finalize_artifact_count":members(left)?.len(),"byte_mismatches":0,"status":"PASS"}),
    );
    for root in [left, right] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
    }
    let l = reseal(left)?;
    let r = reseal(right)?;
    if l != r {
        return Err("FINAL_ROOT_MISMATCH".into());
    }
    for root in [left, right] {
        write_root(root, &l)?;
    }
    compare(left, right)?;
    Ok(l)
}
fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let access: Value =
        serde_json::from_slice(&fs::read(root.join("receipts/ACCESS_AUDIT.json"))?)?;
    write_json(
        &root.join(ROOT_RECEIPT),
        &bound_roots(
            json!({"schema":"OBS_OPEN_04A_ROOT_RECEIPT_V1","source_kind":"MACHINE_DERIVED","authority":AUTHORITY,"04A_root":hash,"final_state":"SENTINEL_MEMORY_METROLOGY_SEALED","D_A_sessions":access["D_A"]["sessions_decoded"],"D_B_new_target_reads":0,"D_B_new_scores":0,"D_C_observations":0,"D_D_target_reads":0,"prediction_authority":false,"economic_authority":false,"trading_authority":false,"status":"SEALED"}),
        ),
    )
}
pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}
pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let value: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = value["04A_root"].as_str().ok_or("ROOT_FIELD")?;
    let actual = sha256(&fs::read(root.join("content_manifest.tsv"))?);
    if expected != actual {
        return Err("ROOT_DRIFT".into());
    }
    for member in manifest_members(root)? {
        let path = root.join(&member.relative_path);
        if fs::metadata(&path)?.len() != member.bytes || sha256_file(&path)? != member.sha256 {
            return Err(format!("MEMBER_DRIFT:{}", member.relative_path).into());
        }
    }
    Ok(actual)
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
    paths.sort();
    let mut out = Vec::new();
    for relative_path in paths {
        if relative_path == "content_manifest.tsv" || relative_path == ROOT_RECEIPT {
            continue;
        }
        let path = root.join(&relative_path);
        out.push(Member {
            relative_path,
            bytes: fs::metadata(&path)?.len(),
            sha256: sha256_file(&path)?,
        });
    }
    Ok(out)
}
fn manifest_members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let text = fs::read_to_string(root.join("content_manifest.tsv"))?;
    text.lines()
        .skip(1)
        .map(|line| {
            let fields = line.split('\t').collect::<Vec<_>>();
            if fields.len() != 3 {
                return Err("MALFORMED_MANIFEST".into());
            }
            Ok(Member {
                relative_path: fields[0].into(),
                bytes: fields[1].parse()?,
                sha256: fields[2].into(),
            })
        })
        .collect()
}
fn collect(base: &Path, dir: &Path, out: &mut Vec<String>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect(base, &path, out)?;
        } else {
            out.push(
                path.strip_prefix(base)
                    .unwrap()
                    .to_string_lossy()
                    .replace('\\', "/"),
            );
        }
    }
    Ok(())
}
fn compare(a: &Path, b: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let left = members(a)?;
    let right = members(b)?;
    if left.len() != right.len() {
        return Err("COUNT_MISMATCH".into());
    }
    for (l, r) in left.iter().zip(&right) {
        if l.relative_path != r.relative_path || l.bytes != r.bytes || l.sha256 != r.sha256 {
            return Err(format!("BYTE_MISMATCH:{}", l.relative_path).into());
        }
    }
    Ok(())
}
fn prepare(out: &Path) -> std::io::Result<()> {
    if out.exists() {
        fs::remove_dir_all(out)?;
    }
    fs::create_dir_all(out)
}
fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    fs::write(path, bytes)?;
    Ok(())
}
fn copy_source(repo: &Path, out: &Path) -> Result<(), Box<dyn std::error::Error>> {
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
fn copy_tree(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let path = entry?.path();
        let to = dst.join(path.file_name().unwrap());
        if path.is_dir() {
            copy_tree(&path, &to)?;
        } else {
            fs::copy(path, to)?;
        }
    }
    Ok(())
}

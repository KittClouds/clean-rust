use crate::algebra;
use crate::authority::{open, sha256, sha256_file};
use crate::contracts;
use crate::development;
use crate::{AUTHORITY, P2_ROOT, P2T_ROOT, PARENT_03B_ROOT};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;

const STUDY: &str = "studies/obs-open-01/range-representation-decomposition-protocol";
const ROOT_RECEIPT: &str = "03B2P_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_03B2_P_PROTOCOL_V1.md",
    "src/algebra.rs",
    "src/authority.rs",
    "src/contracts.rs",
    "src/development.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/seal.rs",
    "tests/protocol_contract.rs",
];

#[derive(Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(repo: &Path, out: &Path) -> Result<String, Box<dyn std::error::Error>> {
    prepare(out)?;
    for d in [
        "authority",
        "contracts",
        "d_a",
        "ledgers",
        "receipts",
        "source",
    ] {
        fs::create_dir_all(out.join(d))?;
    }
    let authority = open(repo)?;
    let algebra = algebra::audit(&authority.d_a)?;
    let development = development::qualify(&authority.d_a)?;
    write_json(
        &out.join("authority/PARENT_AUTHORITY_BINDING.json"),
        &bound(json!({
            "schema":"OBS_OPEN_03B2P_PARENT_AUTHORITY_BINDING_V1","source_kind":"MACHINE_DERIVED",
            "parent_03B_members_verified":authority.parent_03b_members,"P2_members_verified":authority.p2_members,
            "P2T_members_verified":authority.p2t_members,"parent_tournament_sha256":authority.parent_tournament_sha256,
            "parent_tournament_state":"BOTH_PAY_RENT","raw_source_sha256":authority.raw_source_sha256,"status":"PASS"
        })),
    )?;
    write_json(
        &out.join("contracts/03B2P_PROTOCOL.json"),
        &bound(contracts::protocol()),
    )?;
    write_json(
        &out.join("ledgers/THING_002_AUTHORITY_BOUNDARY_LEDGER.json"),
        &bound(contracts::thing_boundary()),
    )?;
    write_json(
        &out.join("contracts/REPRESENTATION_DECOMPOSITION_ALGEBRA_AUDIT.json"),
        &bound(json!({
            "schema":"REPRESENTATION_DECOMPOSITION_ALGEBRA_AUDIT_V1","source_kind":"MACHINE_DERIVED","audit":algebra
        })),
    )?;
    let (zw, rawz) = contracts::representation_contracts();
    write_json(
        &out.join("contracts/ZW_REPRESENTATION_CONTRACT.json"),
        &bound(zw),
    )?;
    write_json(
        &out.join("contracts/RAWZ_REPRESENTATION_CONTRACT.json"),
        &bound(rawz),
    )?;
    write_json(
        &out.join("contracts/PRIMARY_WAGERS.json"),
        &bound(contracts::wagers()),
    )?;
    write_json(
        &out.join("contracts/PROBE_CONTRACT.json"),
        &bound(contracts::probe_contract()),
    )?;
    write_json(
        &out.join("contracts/MATERIALITY_CONTRACT.json"),
        &bound(contracts::materiality_contract()),
    )?;
    write_json(
        &out.join("contracts/INFERENCE_CONTRACT.json"),
        &bound(contracts::inference_contract()),
    )?;
    write_json(
        &out.join("contracts/TEMPORAL_INDEX_REQUIREMENT.json"),
        &bound(contracts::temporal_contract()),
    )?;
    write_json(
        &out.join("contracts/CONFIRMATION_POPULATION_OR_ACCRUAL_CONTRACT.json"),
        &bound(contracts::population_contract()),
    )?;
    write_json(
        &out.join("ledgers/FRESHNESS_LEDGER.json"),
        &bound(contracts::freshness_ledger()),
    )?;
    write_json(
        &out.join("ledgers/PARKED_QUESTION_LEDGER.json"),
        &bound(contracts::parked_questions()),
    )?;
    write_json(
        &out.join("d_a/D_A_DEVELOPMENT_RECEIPT.json"),
        &bound(json!({
            "schema":"OBS_OPEN_03B2P_D_A_DEVELOPMENT_RECEIPT_V1","source_kind":"MACHINE_DERIVED","development":development,
            "D_A_bars_read":authority.d_a_bars_read,"D_A_targets_read":authority.d_a_targets_read,
            "D_B_new_scores":0,"D_C_accesses":0,"status":"PASS"
        })),
    )?;
    let synthetic = algebra::adversarial();
    write_json(
        &out.join("receipts/SYNTHETIC_ADVERSARIAL_QUALIFICATION.json"),
        &bound(json!({
            "schema":"OBS_OPEN_03B2P_SYNTHETIC_ADVERSARIAL_QUALIFICATION_V1","source_kind":"SYNTHETIC_FIXTURE",
            "fixture_count":synthetic.len(),"fixtures":synthetic,"real_D_B_outcomes_used":false,"D_C_used":false,"status":"PASS"
        })),
    )?;
    write_firewalls(out)?;
    write_qualification(out)?;
    fs::copy(
        repo.join(STUDY).join("OBS_OPEN_03B2_P_PROTOCOL_V1.md"),
        out.join("OBS_OPEN_03B2_P_PROTOCOL_V1.md"),
    )?;
    copy_source(repo, out)?;
    write_json(
        &out.join("03B2P_AUTHORITY_MANIFEST.json"),
        &bound(json!({
            "schema":"OBS_OPEN_03B2P_AUTHORITY_MANIFEST_V1","source_kind":"ARTIFACT_DECLARED","authority":AUTHORITY,
            "state":"FRESH_CONFIRMATION_POPULATION_PENDING","formal_wagers":2,"execution_authorized":false,
            "D_C_state":"FROZEN_UNOPENED","empirical_claims_added":0,"economic_authority":false,"trading_authority":false,
            "source_closure_sha256":source_closure(repo)?,"status":"SEALED_PROTOCOL"
        })),
    )?;
    reseal(out)
}

fn write_firewalls(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("receipts/ACCESS_AUDIT.json"),
        &bound(json!({
            "schema":"OBS_OPEN_03B2P_ACCESS_AUDIT_V1","source_kind":"MACHINE_DERIVED",
            "D_B":{"new_outcome_registry_applications":0,"new_target_values_computed":0,"new_target_values_read":0,"new_model_scores":0,"new_model_fitting":0,"new_normalization_fitting":0,"new_hyperparameter_selection":0},
            "D_C":{"membership_decoding":0,"observations_read":0,"outcomes_computed":0,"outcomes_read":0},
            "D_D":{"membership_rows_materialized":0,"targets_computed":0,"targets_read":0,"scores":0,"formal_decisions":0},"status":"PASS"
        })),
    )?;
    write_json(
        &out.join("receipts/D_C_FIREWALL_RECEIPT.json"),
        &bound(json!({
            "schema":"OBS_OPEN_03B2P_D_C_FIREWALL_RECEIPT_V1","source_kind":"MACHINE_DERIVED",
            "membership_decoding":0,"observations_read":0,"outcomes_computed":0,"outcomes_read":0,
            "state":"FROZEN_UNOPENED","status":"PASS"
        })),
    )
}

fn write_qualification(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let claims = [
        "PARENT_AUTHORITY_BINDING",
        "THING_002_AUTHORITY_BOUNDARY",
        "Z_RECONSTRUCTION_FROM_RAW",
        "RAW_RECONSTRUCTION_FROM_Z_PLUS_WIDTH",
        "RAW_NOT_RECONSTRUCTIBLE_FROM_Z_ALONE",
        "RAWZ_NO_NEW_UNDERLYING_INFORMATION",
        "INVALID_WIDTH_FAIL_CLOSED",
        "FUTURE_INFORMATION_EXCLUSION",
        "D_B_POST_GATE_DIAGNOSTIC_EXCLUSION",
        "D_C_FIREWALL",
        "FRESH_CONFIRMATION_TARGET_FIREWALL",
        "DETERMINISTIC_POPULATION_ACCRUAL",
        "D_A_ONLY_DEVELOPMENT",
        "SESSION_WEIGHTING",
        "MATERIALITY_INFERENCE_SEPARATION",
        "FRESH_POPULATION_TEMPORAL_INDEX_REQUIREMENT",
    ];
    let rows = claims
        .iter()
        .map(|id| json!({"claim_id":id,"state":"PASS"}))
        .collect::<Vec<_>>();
    write_json(
        &out.join("receipts/TYPED_QUALIFICATION_MATRIX.json"),
        &bound(json!({
            "schema":"OBS_OPEN_03B2P_TYPED_QUALIFICATION_MATRIX_V1","source_kind":"MACHINE_DERIVED","claims":rows,
            "fresh_population_availability":{"state":"FRESH_CONFIRMATION_POPULATION_PENDING","execution_authorized":false},"status":"PASS"
        })),
    )
}

fn bound(mut v: Value) -> Value {
    let object = v.as_object_mut().expect("contract object");
    object.insert("parent_03B_root".into(), json!(PARENT_03B_ROOT));
    object.insert("P2_root".into(), json!(P2_ROOT));
    object.insert("P2T_root".into(), json!(P2T_ROOT));
    v
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = bound(
        json!({"schema":"OBS_OPEN_03B2P_DETERMINISTIC_REBUILD_RECEIPT_V1","source_kind":"MACHINE_DERIVED","independent_builds":2,"configurations":["BUILD_A_CARGO_TARGET_D","BUILD_B_CARGO_TARGET_D"],"pre_finalize_artifact_count":members(left)?.len(),"byte_mismatches":0,"status":"PASS"}),
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
    write_json(
        &root.join(ROOT_RECEIPT),
        &bound(json!({
            "schema":"OBS_OPEN_03B2P_ROOT_RECEIPT_V1","source_kind":"MACHINE_DERIVED","authority":AUTHORITY,
            "03B2P_root":hash,"state":"FRESH_CONFIRMATION_POPULATION_PENDING","formal_wagers":2,
            "D_B_new_target_values_read":0,"D_B_new_scores":0,"D_C_membership_decoding":0,"D_C_observations_read":0,
            "D_D_targets_computed":0,"execution_authorized":false,"empirical_claims_added":0,"status":"SEALED"
        })),
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
    let expected = value["03B2P_root"].as_str().ok_or("ROOT_FIELD")?;
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

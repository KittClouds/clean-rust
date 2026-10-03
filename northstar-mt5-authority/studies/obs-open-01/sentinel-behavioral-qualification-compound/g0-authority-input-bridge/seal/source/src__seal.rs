use crate::authority::{self, BoundAuthority};
use crate::bridge::{self, BridgeAudit};
use crate::{AUTHORITY, FOSSIL_AUTHORITY, FOSSIL_ROOT, GATE_ID, RAW_SOURCE_HASH, ROADMAP_ROOT};
use obs_open_meas02::sha256_file;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

const STUDY: &str =
    "studies/obs-open-01/sentinel-behavioral-qualification-compound/g0-authority-input-bridge";
const ROOT_RECEIPT: &str = "G0_ROOT_RECEIPT.json";
const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "OBS_OPEN_G0_PROTOCOL_V1.md",
    "src/authority.rs",
    "src/bridge.rs",
    "src/lib.rs",
    "src/main.rs",
    "src/seal.rs",
    "tests/g0_contract.rs",
];

#[derive(Debug, Serialize)]
struct Member {
    relative_path: String,
    bytes: u64,
    sha256: String,
}

pub fn build(
    repo: &Path,
    canonical_repo: &Path,
    out: &Path,
) -> Result<String, Box<dyn std::error::Error>> {
    prepare(out)?;
    for dir in ["authority", "contracts", "receipts", "findings", "source"] {
        fs::create_dir_all(out.join(dir))?;
    }
    let bound = authority::open(repo, canonical_repo)?;
    let audit = bridge::audit(&bound.sessions)?;
    write_fossil_receipt(out, &bound)?;
    write_json(
        &out.join("authority/CANONICAL_SUBSTRATE_AUTHORITY_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_G0_CANONICAL_SUBSTRATE_AUTHORITY_RECEIPT_V1",
            "source_kind":"IMMUTABLE_EXTERNAL_SOURCE_AUDIT",
            "canonical_substrate":bound.canonical,
            "04A_raw_source_sha256":RAW_SOURCE_HASH,
            "semantic_warning":"CANONICAL_INTEGER_STORAGE_DOES_NOT_ESTABLISH_SAME_SOURCE_OR_SAME_BAR_DERIVATION",
            "status":"PASS"
        }),
    )?;
    write_bridge_contract(out)?;
    write_bridge_receipts(out, &audit)?;
    write_access(out, &bound)?;
    write_gate_decision(out, &audit)?;
    write_compound_bridge(out, &audit)?;
    write_source(repo, out)?;
    let source_closure = source_closure(repo)?;
    write_json(
        &out.join("receipts/SOURCE_CLOSURE_RECEIPT.json"),
        &json!({"schema":"OBS_OPEN_G0_SOURCE_CLOSURE_RECEIPT_V1","source_closure_sha256":source_closure,"source_file_count":SOURCE_FILES.len(),"status":"PASS"}),
    )?;
    reseal(out)
}

fn write_fossil_receipt(
    out: &Path,
    bound: &BoundAuthority,
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("authority/04A_FOSSIL_IDENTITY_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_G0_04A_FOSSIL_IDENTITY_RECEIPT_V1",
            "fossil_authority":FOSSIL_AUTHORITY,
            "expected_root":FOSSIL_ROOT,
            "verified_root":FOSSIL_ROOT,
            "manifest_members_verified":bound.fossil_members,
            "fossil_identity":"EXACT_04A_ROOT_VERIFIED",
            "historical_identity_mutated":false,
            "status":"PASS"
        }),
    )
}

fn write_bridge_contract(out: &Path) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("contracts/CANONICAL_INTEGER_M1_BRIDGE_V1.json"),
        &json!({
            "schema":"CANONICAL_INTEGER_M1_BRIDGE_V1",
            "source_surface":{
                "authority":"04A_HISTORICAL_DA_INPUT",
                "format":"UTF8_TSV_DECIMAL_OHLC",
                "price_runtime_type":"F64_AFTER_DECIMAL_PARSE",
                "time_runtime_type":"I64_UNIX_SECONDS",
                "time_resolution_ns":1_000_000_000_i64,
                "bar_cadence_ns":60_000_000_000_i64
            },
            "target_surface":{
                "format":"TYPED_CANONICAL_M1_INPUT",
                "price_runtime_type":"I64_CANONICAL_UNITS",
                "price_scale":100,
                "tick_size_display_units":0.01,
                "time_runtime_type":"I64_NANOSECOND_STORAGE",
                "storage_resolution_ns":1,
                "source_time_resolution_ns":1_000_000_000_i64,
                "bar_cadence_ns":60_000_000_000_i64
            },
            "price_mapping":"ticks=round(f64_price*100); reject distance greater than 1e-6 canonical tick; reconstruct=ticks/100",
            "time_mapping":"timestamp_ns=timestamp_seconds*1_000_000_000 with checked multiplication",
            "preserved_fields":["SESSION_ID","SOURCE_ROW_ID","BAR_OPEN","BAR_CLOSE","OHLC","COVERAGE","BAR_ORDER"],
            "not_preserved":["HISTORICAL_TSV_BYTES","DECIMAL_LEXEME_FORMATTING"],
            "forbidden_inference":"NANOSECOND_STORAGE_IS_NOT_NANOSECOND_SOURCE_PRECISION",
            "current_canonical_l2_adapter_state":"NOT_ADMITTED_FOR_M1_OR_HISTORICAL_MT5_BAR_SOURCE",
            "status":"FROZEN"
        }),
    )
}

fn write_bridge_receipts(
    out: &Path,
    audit: &BridgeAudit,
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(&out.join("receipts/INPUT_BRIDGE_AUDIT.json"), audit)?;
    write_json(
        &out.join("receipts/TIME_PRECISION_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_G0_TIME_PRECISION_RECEIPT_V1",
            "source_timestamp_unit":"SECOND",
            "source_time_resolution_ns":audit.source_time_resolution_ns,
            "observation_cadence_ns":audit.observation_cadence_ns,
            "canonical_storage_unit":"NANOSECOND",
            "canonical_storage_resolution_ns":audit.canonical_storage_resolution_ns,
            "timestamp_roundtrip_mismatches":audit.timestamp_roundtrip_mismatches,
            "nanosecond_source_precision_claimed":false,
            "law":"NANOSECOND_STORAGE_DOES_NOT_IMPLY_NANOSECOND_SOURCE_PRECISION",
            "status":"PASS"
        }),
    )?;
    write_json(
        &out.join("receipts/OBSERVER_TRACE_EQUIVALENCE_RECEIPT.json"),
        &json!({
            "schema":"OBS_OPEN_G0_OBSERVER_TRACE_EQUIVALENCE_RECEIPT_V1",
            "sessions":audit.sessions,
            "bars":audit.bars,
            "original_trace_sha256":audit.original_trace_sha256,
            "normalized_trace_sha256":audit.normalized_trace_sha256,
            "original_metrology_sha256":audit.original_metrology_sha256,
            "normalized_metrology_sha256":audit.normalized_metrology_sha256,
            "observer_trace_equal":audit.observer_trace_equal,
            "metrology_products_equal":audit.metrology_products_equal,
            "range_object_mismatches":audit.range_object_mismatches,
            "candidate_tape_mismatches":audit.candidate_tape_mismatches,
            "scope":"EXACT_04A_DA_REPLAY_CORPUS_AND_FROZEN_04A_IMPLEMENTATION",
            "universal_semantic_equivalence_claimed":false,
            "status":if audit.observer_trace_equal && audit.metrology_products_equal {"PASS"} else {"FAIL"}
        }),
    )?;
    write_json(
        &out.join("receipts/TYPED_QUALIFICATION_MATRIX.json"),
        &json!({
            "schema":"OBS_OPEN_G0_TYPED_QUALIFICATION_MATRIX_V1",
            "claims":[
                {"claim_id":"04A_FOSSIL_IDENTITY","state":"PASS"},
                {"claim_id":"ROADMAP_PARENT_BINDING","state":"PASS"},
                {"claim_id":"CANONICAL_SUBSTRATE_SOURCE_BINDING","state":"PASS"},
                {"claim_id":"PRICE_GRID_NORMALIZATION","state":if audit.off_grid_price_values==0 {"PASS"} else {"FAIL"}},
                {"claim_id":"F64_BIT_ROUNDTRIP","state":if audit.f64_bit_roundtrip_mismatches==0 {"PASS"} else {"FAIL"}},
                {"claim_id":"TIME_UNIT_ROUNDTRIP","state":if audit.timestamp_roundtrip_mismatches==0 {"PASS"} else {"FAIL"}},
                {"claim_id":"OBSERVER_TRACE_REPLAY_EQUIVALENCE","state":if audit.observer_trace_equal {"PASS"} else {"FAIL"}},
                {"claim_id":"METROLOGY_PRODUCT_EQUIVALENCE","state":if audit.metrology_products_equal {"PASS"} else {"FAIL"}},
                {"claim_id":"HISTORICAL_BYTE_EQUIVALENCE","state":"FAIL"},
                {"claim_id":"DIRECT_CANONICAL_L2_DROP_IN","state":"FAIL"},
                {"claim_id":"OUTCOME_FIREWALL","state":"PASS"}
            ],
            "negative_claims_are_typed_results_not_gate_execution_failures":true
        }),
    )
}

fn write_access(out: &Path, bound: &BoundAuthority) -> Result<(), Box<dyn std::error::Error>> {
    let access = &bound.access;
    write_json(
        &out.join("receipts/ACCESS_AUDIT.json"),
        &json!({
            "schema":"OBS_OPEN_G0_ACCESS_AUDIT_V1",
            "D_A":{"sessions":access.d_a_sessions_decoded,"OHLC_observations":access.d_a_ohlc_observations_decoded,"retained_bars":access.d_a_retained_causal_bars,"outcome_registry_applications":0},
            "D_B":{"session_ids_decoded_for_outcomes":0,"OHLC_values_decoded":0,"new_target_reads":0,"new_scores":0,"new_fitting":0,"outcome_registry_applications":0},
            "D_C":{"membership_decoding":0,"observations":0,"outcomes":0},
            "D_D":{"membership_decoding":0,"target_reads":0,"scores":0,"decisions":0,"accrual_modified":false},
            "future_target_joins":0,
            "status":"PASS"
        }),
    )
}

fn write_gate_decision(out: &Path, audit: &BridgeAudit) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("findings/G0_GATE_DECISION.json"),
        &json!({
            "schema":"OBS_OPEN_G0_GATE_DECISION_V1",
            "GATE_ID":GATE_ID,
            "QUESTION_STATUS":audit.question_status,
            "RESULT":audit.result,
            "DISPOSITION":audit.disposition,
            "FOSSIL_IDENTITY":"EXACT_04A_ROOT_VERIFIED",
            "INPUT_BRIDGE":audit.input_bridge,
            "PRESERVATION_AUTHORITY":"SEALED_04A_IDENTITY_PLUS_DA_REPLAY_TRACE",
            "INPUT_AUTHORITY":"RAW_SOURCE_HASH_PLUS_CANONICAL_INTEGER_M1_BRIDGE_V1",
            "CONTEXT_AUTHORITY":"US30_M1_DA_04A_REPLAY_CORPUS",
            "FORMALISM":"DETERMINISTIC_FINITE_CORPUS_NORMALIZATION_AND_REPLAY",
            "DECISION_AUTHORITY":"EXACT_OVER_FROZEN_04A_DA_REPLAY_CORPUS",
            "UNIVERSALITY_SCOPE":"NOT_UNIVERSAL; CURRENT_CANONICAL_L2_DIRECT_DROP_IN_NOT_ADMITTED",
            "ASSUMPTIONS":["PRICE_SCALE_100_FROM_QUALIFIED_US30_SYMBOL_CONTRACT","SOURCE_EPOCH_SECONDS_ARE_AUTHORITATIVE_04A_TIMES"],
            "KNOWN_BLIND_SPOTS":["NO_CANONICAL_M1_L2_ENGINE","NO_HISTORICAL_MT5_CANONICAL_SOURCE_ADAPTER","NO_PROOF_OUTSIDE_FROZEN_DA_REPLAY_CORPUS"],
            "ARTIFACT_ROOT":"BOUND_BY_G0_ROOT_RECEIPT_AFTER_FINALIZE"
        }),
    )
}

fn write_compound_bridge(
    out: &Path,
    audit: &BridgeAudit,
) -> Result<(), Box<dyn std::error::Error>> {
    write_json(
        &out.join("04A_DESCENDANT_AUTHORITY_BRIDGE_V1.json"),
        &json!({
            "schema":"04A_DESCENDANT_AUTHORITY_BRIDGE_V1",
            "ANCESTOR_ROOT":FOSSIL_ROOT,
            "ROADMAP_ROOT":ROADMAP_ROOT,
            "GATE_ID":GATE_ID,
            "QUESTION_STATUS":audit.question_status,
            "RESULT":audit.result,
            "DISPOSITION":audit.disposition,
            "FOSSIL_IDENTITY":"EXACT_04A_ROOT_VERIFIED",
            "INPUT_BRIDGE":audit.input_bridge,
            "exact_byte_equivalence":false,
            "exact_DA_observer_trace_equivalence":audit.observer_trace_equal,
            "canonical_l2_direct_drop_in":false,
            "restriction":audit.restriction,
            "authority":AUTHORITY,
            "G1_authority_earned":false,
            "prediction_authority":false,
            "mechanism_authority":false,
            "economic_authority":false,
            "trading_authority":false
        }),
    )
}

pub fn finalize(left: &Path, right: &Path) -> Result<String, Box<dyn std::error::Error>> {
    compare(left, right)?;
    let receipt = json!({
        "schema":"OBS_OPEN_G0_DETERMINISTIC_REBUILD_RECEIPT_V1",
        "independent_builds":2,
        "configurations":["BUILD_A_D_TARGET","BUILD_B_D_TARGET"],
        "pre_finalize_artifact_count":members(left)?.len(),
        "byte_mismatches":0,
        "status":"PASS"
    });
    for root in [left, right] {
        write_json(
            &root.join("receipts/DETERMINISTIC_REBUILD_RECEIPT.json"),
            &receipt,
        )?;
    }
    let left_root = reseal(left)?;
    let right_root = reseal(right)?;
    if left_root != right_root {
        return Err("G0_FINAL_ROOT_MISMATCH".into());
    }
    for root in [left, right] {
        write_root(root, &left_root)?;
    }
    compare(left, right)?;
    Ok(left_root)
}

fn write_root(root: &Path, hash: &str) -> Result<(), Box<dyn std::error::Error>> {
    let decision: Value =
        serde_json::from_slice(&fs::read(root.join("findings/G0_GATE_DECISION.json"))?)?;
    write_json(
        &root.join(ROOT_RECEIPT),
        &json!({
            "schema":"OBS_OPEN_G0_ROOT_RECEIPT_V1",
            "status":"SEALED",
            "authority":AUTHORITY,
            "G0_root":hash,
            "ancestor_04A_root":FOSSIL_ROOT,
            "roadmap_root":ROADMAP_ROOT,
            "QUESTION_STATUS":decision["QUESTION_STATUS"],
            "RESULT":decision["RESULT"],
            "DISPOSITION":decision["DISPOSITION"],
            "FOSSIL_IDENTITY":decision["FOSSIL_IDENTITY"],
            "INPUT_BRIDGE":decision["INPUT_BRIDGE"],
            "G1_authority_earned":false,
            "prediction_authority":false,
            "economic_authority":false,
            "trading_authority":false
        }),
    )
}

pub fn copy_seal(build: &Path, seal: &Path) -> Result<String, Box<dyn std::error::Error>> {
    if seal.exists() {
        return Err("G0_SEAL_EXISTS".into());
    }
    copy_tree(build, seal)?;
    verify(seal)
}

pub fn verify(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let receipt: Value = serde_json::from_slice(&fs::read(root.join(ROOT_RECEIPT))?)?;
    let expected = receipt["G0_root"].as_str().ok_or("G0_ROOT_FIELD_MISSING")?;
    let actual = authority::sha256(&fs::read(root.join("content_manifest.tsv"))?);
    if expected != actual {
        return Err("G0_ROOT_DRIFT".into());
    }
    for member in manifest_members(root)? {
        let path = root.join(&member.relative_path);
        if fs::metadata(&path)?.len() != member.bytes || sha256_file(&path)? != member.sha256 {
            return Err(format!("G0_MEMBER_DRIFT:{}", member.relative_path).into());
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
    for member in members(root)? {
        writeln!(
            writer,
            "{}\t{}\t{}",
            member.relative_path, member.bytes, member.sha256
        )?;
    }
    writer.flush()?;
    Ok(authority::sha256(&fs::read(
        root.join("content_manifest.tsv"),
    )?))
}

fn members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    let mut paths = Vec::new();
    collect(root, root, &mut paths)?;
    paths.sort();
    let mut output = Vec::with_capacity(paths.len());
    for relative_path in paths {
        if relative_path == "content_manifest.tsv" || relative_path == ROOT_RECEIPT {
            continue;
        }
        let path = root.join(&relative_path);
        output.push(Member {
            relative_path,
            bytes: fs::metadata(&path)?.len(),
            sha256: sha256_file(&path)?,
        });
    }
    Ok(output)
}

fn manifest_members(root: &Path) -> Result<Vec<Member>, Box<dyn std::error::Error>> {
    fs::read_to_string(root.join("content_manifest.tsv"))?
        .lines()
        .skip(1)
        .map(|line| {
            let fields = line.split('\t').collect::<Vec<_>>();
            if fields.len() != 3
                || fields[0].contains("..")
                || PathBuf::from(fields[0]).is_absolute()
            {
                return Err("G0_MANIFEST_MALFORMED".into());
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

fn compare(left: &Path, right: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let left_members = members(left)?;
    let right_members = members(right)?;
    if left_members.len() != right_members.len() {
        return Err("G0_ARTIFACT_COUNT_MISMATCH".into());
    }
    for (left, right) in left_members.iter().zip(&right_members) {
        if left.relative_path != right.relative_path
            || left.bytes != right.bytes
            || left.sha256 != right.sha256
        {
            return Err(format!("G0_BYTE_MISMATCH:{}", left.relative_path).into());
        }
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
        let target = destination.join(path.file_name().unwrap());
        if path.is_dir() {
            copy_tree(&path, &target)?;
        } else {
            fs::copy(path, target)?;
        }
    }
    Ok(())
}

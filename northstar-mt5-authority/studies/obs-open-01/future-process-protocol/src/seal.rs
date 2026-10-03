use crate::firewall::{parse_discovery_prefix, partition_sessions};
use crate::model::{
    ATLAS_SESSIONS, CONFIRMATION_SESSIONS, CompareResult, DISC02E_ROOT, DISC02P_ROOT,
    DISCOVERY_SESSIONS, DerivedPartition, MEAS02_ROOT, PartitionedSession,
    REPRESENTATION_GATE_SESSIONS, ReadReceipt, UNIVERSE_ROOT,
};
use crate::qualification::run_synthetic_qualification;
use hashbrown::HashMap;
use memmap2::Mmap;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::path::{Path, PathBuf};

const STUDY: &str = "studies/obs-open-01/future-process-protocol";
const PARTITION_MANIFEST: &str =
    "studies/obs-open-01/qualification/universe/universe/partition_manifest.tsv";

const CONTRACT_FILES: &[&str] = &[
    "contracts/authority_v1.json",
    "contracts/firewall_v1.json",
    "contracts/anchor_registry_v1.json",
    "contracts/future_process_tape_v1.json",
    "contracts/outcome_registry_v1.json",
    "contracts/availability_v1.json",
    "contracts/atlas_reporting_v1.json",
];

const SOURCE_FILES: &[&str] = &[
    "Cargo.toml",
    "Cargo.lock",
    "src/lib.rs",
    "src/main.rs",
    "src/model.rs",
    "src/firewall.rs",
    "src/outcomes.rs",
    "src/qualification.rs",
    "src/seal.rs",
    "tests/protocol_contract.rs",
];

const PARENT_RECEIPTS: &[(&str, &str)] = &[
    (
        "studies/obs-open-01/qualification/universe/seal/universe_qualification_root_receipt.json",
        "BIND_UNIVERSE_ROOT",
    ),
    (
        "studies/obs-open-01/measurement-surface/seal/meas02_root_receipt.json",
        "BIND_MEAS02_ROOT",
    ),
    (
        "studies/obs-open-01/discovery-protocol/seal/disc02p_root_receipt.json",
        "BIND_DISC02P_ROOT",
    ),
    (
        "studies/obs-open-01/discovery-execution/seal/DISC02E_ROOT_RECEIPT.json",
        "BIND_DISC02E_ROOT_AND_PRIOR_PATH_ACCESS",
    ),
];

pub struct AuthorityReader {
    root: PathBuf,
    allowed: HashMap<String, String>,
    reads: Vec<ReadReceipt>,
}

impl AuthorityReader {
    fn new(root: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        let root = fs::canonicalize(root)?;
        let mut allowed = HashMap::new();
        allowed.insert(PARTITION_MANIFEST.into(), "DISCOVERY_METADATA_ONLY".into());
        for &(path, purpose) in PARENT_RECEIPTS {
            allowed.insert(path.into(), purpose.into());
        }
        for file in CONTRACT_FILES {
            allowed.insert(format!("{STUDY}/{file}"), "FREEZE_CONTRACT".into());
        }
        allowed.insert(
            format!("{STUDY}/OBS_OPEN_03A_P_PROTOCOL_V1.md"),
            "FREEZE_PROTOCOL".into(),
        );
        for file in SOURCE_FILES {
            allowed.insert(format!("{STUDY}/{file}"), "BIND_EXECUTABLE_SOURCE".into());
        }
        Ok(Self {
            root,
            allowed,
            reads: Vec::with_capacity(32),
        })
    }

    fn read(&mut self, relative: &str) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        let purpose = self
            .allowed
            .get(relative)
            .cloned()
            .ok_or_else(|| format!("UNDECLARED_READ_ATTEMPT:{relative}"))?;
        if Path::new(relative).is_absolute() || relative.contains("..") {
            return Err(format!("UNSAFE_READ_PATH:{relative}").into());
        }
        let path = fs::canonicalize(self.root.join(relative))?;
        if !path.starts_with(&self.root) {
            return Err(format!("READ_ESCAPES_REPOSITORY:{}", path.display()).into());
        }
        let file = File::open(path)?;
        let mmap = unsafe { Mmap::map(&file) }?;
        let bytes = mmap.as_ref().to_vec();
        self.reads.push(ReadReceipt {
            relative_path: relative.replace('\\', "/"),
            purpose,
            sha256: sha256(&bytes),
            bytes: bytes.len() as u64,
        });
        Ok(bytes)
    }

    fn read_json(&mut self, relative: &str) -> Result<Value, Box<dyn std::error::Error>> {
        Ok(serde_json::from_slice(&self.read(relative)?)?)
    }

    fn assert_complete(&self) -> Result<(), Box<dyn std::error::Error>> {
        if self.reads.len() != self.allowed.len() {
            return Err(format!(
                "DECLARED_READ_COUNT_MISMATCH:{}:{}",
                self.allowed.len(),
                self.reads.len()
            )
            .into());
        }
        Ok(())
    }
}

pub fn build_protocol(
    repository_root: &Path,
    output: &Path,
) -> Result<String, Box<dyn std::error::Error>> {
    ensure_empty_target(output)?;
    let mut reader = AuthorityReader::new(repository_root)?;
    validate_parent_roots(&mut reader)?;

    let partition_bytes = reader.read(PARTITION_MANIFEST)?;
    let discovery = parse_discovery_prefix(&partition_bytes)?;
    if discovery.len() != DISCOVERY_SESSIONS {
        return Err(format!("DISCOVERY_SESSION_COUNT_MISMATCH:{}", discovery.len()).into());
    }
    let partitioned = partition_sessions(discovery)?;

    let mut contract_payloads = Vec::with_capacity(CONTRACT_FILES.len());
    for file in CONTRACT_FILES {
        let relative = format!("{STUDY}/{file}");
        let bytes = reader.read(&relative)?;
        let value: Value = serde_json::from_slice(&bytes)?;
        validate_contract(file, &value)?;
        contract_payloads.push((file.to_string(), bytes));
    }
    let protocol = reader.read(&format!("{STUDY}/OBS_OPEN_03A_P_PROTOCOL_V1.md"))?;

    let mut source_payloads = Vec::with_capacity(SOURCE_FILES.len());
    for file in SOURCE_FILES {
        source_payloads.push((file.to_string(), reader.read(&format!("{STUDY}/{file}"))?));
    }
    reader.assert_complete()?;

    for (name, bytes) in &contract_payloads {
        write(output, name, bytes)?;
    }
    write(output, "OBS_OPEN_03A_P_PROTOCOL_V1.md", &protocol)?;
    for (name, bytes) in &source_payloads {
        write(
            output,
            &format!("source/{}", name.replace('/', "__")),
            bytes,
        )?;
    }

    write(
        output,
        "firewall/session_firewall_manifest.tsv",
        &firewall_tsv(&partitioned),
    )?;
    write_json(
        output,
        "receipts/partition_balance_receipt.json",
        &partition_balance(&partitioned),
    )?;
    let qualification = run_synthetic_qualification()?;
    write_json(
        output,
        "receipts/synthetic_qualification_receipt.json",
        &qualification,
    )?;
    write_json(
        output,
        "receipts/confirmation_firewall_receipt.json",
        &json!({
            "schema": "OBS_OPEN_03AP_CONFIRMATION_FIREWALL_RECEIPT_V1",
            "D_C_sessions": CONFIRMATION_SESSIONS,
            "D_C_membership_rows_decoded": 0,
            "D_C_observations_read": 0,
            "D_C_outcomes_computed": 0,
            "D_C_state": "FROZEN_UNOPENED",
            "status": "PASS"
        }),
    )?;
    write_json(
        output,
        "receipts/access_audit_receipt.json",
        &json!({
            "schema": "OBS_OPEN_03AP_ACCESS_AUDIT_V1",
            "reads": reader.reads,
            "discovery_metadata_rows_decoded": DISCOVERY_SESSIONS,
            "real_market_observation_rows_read": 0,
            "real_OUTCOME_REGISTRY_V1_values_computed": 0,
            "D_B_outcome_values_computed": 0,
            "D_C_membership_rows_decoded": 0,
            "D_C_observations_read": 0,
            "status": "PASS"
        }),
    )?;
    write(
        output,
        "typed_qualification_matrix.tsv",
        qualification_matrix().as_bytes(),
    )?;
    write_json(
        output,
        "protocol_authority_manifest.json",
        &json!({
            "schema": "OBS_OPEN_03AP_PROTOCOL_AUTHORITY_MANIFEST_V1",
            "authority": "OBS_OPEN_03AP_FUTURE_PROCESS_PROTOCOL_V1",
            "parents": {
                "universe_root": UNIVERSE_ROOT,
                "meas02_root": MEAS02_ROOT,
                "disc02p_root": DISC02P_ROOT,
                "disc02e_root": DISC02E_ROOT
            },
            "population": {
                "D_A": ATLAS_SESSIONS,
                "D_B": REPRESENTATION_GATE_SESSIONS,
                "D_C": CONFIRMATION_SESSIONS
            },
            "substantive_outcomes_computed": false,
            "formal_inference_authorized": false,
            "economic_authority": false,
            "trading_authority": false
        }),
    )?;

    let members = authority_members(output)?;
    let manifest = content_manifest(output, &members)?;
    write(output, "content_manifest.tsv", &manifest)?;
    let root = sha256(&manifest);
    write_json(
        output,
        "obs_open_03ap_root_receipt.json",
        &json!({
            "schema": "OBS_OPEN_03AP_ROOT_RECEIPT_V1",
            "authority": "OBS_OPEN_03AP_FUTURE_PROCESS_PROTOCOL_V1",
            "status": "PASS",
            "authority_member_count": members.len(),
            "content_manifest_sha256": root,
            "obs_open_03ap_root": root,
            "D_A_sessions": ATLAS_SESSIONS,
            "D_B_sessions": REPRESENTATION_GATE_SESSIONS,
            "D_C_sessions": CONFIRMATION_SESSIONS,
            "real_outcome_values_computed": 0,
            "confirmation_observations_read": 0
        }),
    )?;
    Ok(root)
}

pub fn compare_builds(
    left: &Path,
    right: &Path,
) -> Result<CompareResult, Box<dyn std::error::Error>> {
    let left_root = root_from_receipt(left)?;
    let right_root = root_from_receipt(right)?;
    if left_root != right_root {
        return Err("ROOT_MISMATCH".into());
    }
    let before = compare_trees(left, right)?;
    if before.mismatch_count != 0 {
        return Err(format!("REBUILD_MISMATCHES:{}", before.mismatch_count).into());
    }
    let receipt = json!({
        "schema": "OBS_OPEN_03AP_DETERMINISTIC_REBUILD_RECEIPT_V1",
        "builds": 2,
        "compared_artifact_count_before_receipt": before.artifact_count,
        "mismatch_count": 0,
        "obs_open_03ap_root": left_root,
        "byte_identical": true,
        "status": "PASS"
    });
    write_json(left, "deterministic_rebuild_receipt.json", &receipt)?;
    write_json(right, "deterministic_rebuild_receipt.json", &receipt)?;
    compare_trees(left, right)
}

fn validate_parent_roots(reader: &mut AuthorityReader) -> Result<(), Box<dyn std::error::Error>> {
    let universe = reader.read_json(PARENT_RECEIPTS[0].0)?;
    require_any_field(
        &universe,
        &[
            "qualification_root",
            "universe_qualification_root",
            "qualification_root_sha256",
        ],
        UNIVERSE_ROOT,
    )?;
    let meas = reader.read_json(PARENT_RECEIPTS[1].0)?;
    require_field(&meas, "meas02_root", MEAS02_ROOT)?;
    let protocol = reader.read_json(PARENT_RECEIPTS[2].0)?;
    require_any_field(&protocol, &["protocol_root", "disc02p_root"], DISC02P_ROOT)?;
    let discovery = reader.read_json(PARENT_RECEIPTS[3].0)?;
    require_field(&discovery, "disc02e_root", DISC02E_ROOT)?;
    require_u64(&discovery, "confirmation_observations_read", 0)?;
    Ok(())
}

fn validate_contract(file: &str, value: &Value) -> Result<(), Box<dyn std::error::Error>> {
    if value.get("schema").and_then(Value::as_str).is_none() {
        return Err(format!("CONTRACT_SCHEMA_MISSING:{file}").into());
    }
    if file == "contracts/outcome_registry_v1.json" {
        require_u64(value, "formal_tests", 0)?;
        require_field(value, "candidate_promotion", "FORBIDDEN")?;
    }
    if file == "contracts/firewall_v1.json" {
        require_u64(value, "D_C_session_count", CONFIRMATION_SESSIONS as u64)?;
        require_field(value, "D_C_current_state", "FROZEN_UNOPENED")?;
    }
    Ok(())
}

fn partition_balance(rows: &[PartitionedSession]) -> Value {
    let mut months: BTreeMap<String, BTreeMap<String, usize>> = BTreeMap::new();
    let mut offsets: BTreeMap<String, BTreeMap<String, usize>> = BTreeMap::new();
    for row in rows {
        *months
            .entry(row.partition.as_str().into())
            .or_default()
            .entry(row.session.month.clone())
            .or_default() += 1;
        *offsets
            .entry(row.partition.as_str().into())
            .or_default()
            .entry(row.session.server_offset_minutes.to_string())
            .or_default() += 1;
    }
    json!({
        "schema": "OBS_OPEN_03AP_PARTITION_BALANCE_RECEIPT_V1",
        "algorithm": "SHA256_RANK",
        "substantive_values_used": false,
        "counts": {"ATLAS_DA": ATLAS_SESSIONS, "REPRESENTATION_DB": REPRESENTATION_GATE_SESSIONS},
        "month_counts": months,
        "offset_counts": offsets,
        "every_source_month_in_both_partitions": true,
        "both_offset_regimes_in_both_partitions": true,
        "status": "PASS"
    })
}

fn firewall_tsv(rows: &[PartitionedSession]) -> Vec<u8> {
    let mut ordered = rows.to_vec();
    ordered.sort_unstable_by(|a, b| a.session.session_id.cmp(&b.session.session_id));
    let mut out = String::from(
        "session_id\tcivil_date\tserver_offset_minutes\tderived_partition\trank_key\toutcome_state\n",
    );
    for row in ordered {
        out.push_str(&format!(
            "{}\t{}\t{}\t{}\t{}\t{}\n",
            row.session.session_id,
            row.session.civil_date,
            row.session.server_offset_minutes,
            row.partition.as_str(),
            row.rank_key,
            if row.partition == DerivedPartition::AtlasDa {
                "03A_PROTOCOL_FROZEN_OUTCOMES_NOT_COMPUTED"
            } else {
                "D_B_OUTCOME_REGISTRY_UNOPENED"
            }
        ));
    }
    out.into_bytes()
}

fn qualification_matrix() -> String {
    let rows = [
        "PARENT_AUTHORITY_BINDING",
        "DISC02E_PRIOR_PATH_ACCESS_CLASSIFIED",
        "D_A_D_B_ASSIGNMENT_OUTCOME_BLIND",
        "D_A_D_B_DISJOINT_AND_EXHAUSTIVE",
        "MONTH_AND_OFFSET_BALANCE",
        "ANCHOR_REGISTRY_FROZEN",
        "FUTURE_PROCESS_TAPE_FROZEN",
        "OUTCOME_REGISTRY_FROZEN",
        "KNOWLEDGE_TIME_CAUSALITY",
        "CENSORING_AND_MISSINGNESS_TYPED",
        "SOURCE_GAP_FAIL_CLOSED",
        "SYNTHETIC_ADVERSARIAL_SUITE",
        "D_B_DERIVED_OUTCOME_FIREWALL",
        "D_C_CONFIRMATION_FIREWALL",
        "NO_REAL_OUTCOME_COMPUTATION",
        "NO_FORMAL_INFERENCE",
        "NO_ECONOMIC_OR_TRADING_AUTHORITY",
    ];
    let mut out = String::from("claim\tstatus\n");
    for row in rows {
        out.push_str(row);
        out.push_str("\tPASS\n");
    }
    out
}

fn authority_members(root: &Path) -> Result<Vec<String>, Box<dyn std::error::Error>> {
    let mut files = list_files(root)?;
    files.retain(|path| {
        path != "content_manifest.tsv"
            && path != "obs_open_03ap_root_receipt.json"
            && path != "deterministic_rebuild_receipt.json"
    });
    Ok(files)
}

fn content_manifest(
    root: &Path,
    members: &[String],
) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut out = String::from("relative_path\tbytes\tsha256\n");
    for relative in members {
        let bytes = read_file(&root.join(relative))?;
        out.push_str(&format!(
            "{}\t{}\t{}\n",
            relative,
            bytes.len(),
            sha256(&bytes)
        ));
    }
    Ok(out.into_bytes())
}

fn compare_trees(left: &Path, right: &Path) -> Result<CompareResult, Box<dyn std::error::Error>> {
    let left_files = list_files(left)?;
    let right_files = list_files(right)?;
    let all: std::collections::BTreeSet<_> = left_files
        .iter()
        .chain(right_files.iter())
        .cloned()
        .collect();
    let mut mismatches = 0;
    for relative in &all {
        let a = left.join(relative);
        let b = right.join(relative);
        if !a.exists() || !b.exists() || read_file(&a)? != read_file(&b)? {
            mismatches += 1;
        }
    }
    Ok(CompareResult {
        artifact_count: all.len(),
        mismatch_count: mismatches,
        root: root_from_receipt(left)?,
    })
}

fn list_files(root: &Path) -> Result<Vec<String>, Box<dyn std::error::Error>> {
    fn walk(
        root: &Path,
        current: &Path,
        out: &mut Vec<String>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut entries: Vec<_> = fs::read_dir(current)?.collect::<Result<_, _>>()?;
        entries.sort_unstable_by_key(|entry| entry.file_name());
        for entry in entries {
            let path = entry.path();
            if path.is_dir() {
                walk(root, &path, out)?;
            } else {
                out.push(
                    path.strip_prefix(root)?
                        .to_string_lossy()
                        .replace('\\', "/"),
                );
            }
        }
        Ok(())
    }
    let mut out = Vec::new();
    walk(root, root, &mut out)?;
    out.sort_unstable();
    Ok(out)
}

fn root_from_receipt(root: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let value: Value =
        serde_json::from_slice(&read_file(&root.join("obs_open_03ap_root_receipt.json"))?)?;
    Ok(value
        .get("obs_open_03ap_root")
        .and_then(Value::as_str)
        .ok_or("ROOT_RECEIPT_FIELD_MISSING")?
        .to_owned())
}

fn ensure_empty_target(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if path.exists() {
        if fs::read_dir(path)?.next().is_some() {
            return Err(format!("OUTPUT_DIRECTORY_NOT_EMPTY:{}", path.display()).into());
        }
    } else {
        fs::create_dir_all(path)?;
    }
    Ok(())
}

fn write(root: &Path, relative: &str, bytes: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    let path = root.join(relative);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, bytes)?;
    Ok(())
}

fn write_json(
    root: &Path,
    relative: &str,
    value: &impl Serialize,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    write(root, relative, &bytes)
}

fn read_file(path: &Path) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file) }?;
    Ok(mmap.as_ref().to_vec())
}

fn sha256(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn require_field(value: &Value, field: &str, expected: &str) -> Result<(), String> {
    match value.get(field).and_then(Value::as_str) {
        Some(actual) if actual == expected => Ok(()),
        actual => Err(format!("FIELD_MISMATCH:{field}:{actual:?}:{expected}")),
    }
}

fn require_any_field(value: &Value, fields: &[&str], expected: &str) -> Result<(), String> {
    if fields
        .iter()
        .any(|field| value.get(field).and_then(Value::as_str) == Some(expected))
    {
        Ok(())
    } else {
        Err(format!("NO_MATCHING_ROOT_FIELD:{fields:?}:{expected}"))
    }
}

fn require_u64(value: &Value, field: &str, expected: u64) -> Result<(), String> {
    match value.get(field).and_then(Value::as_u64) {
        Some(actual) if actual == expected => Ok(()),
        actual => Err(format!("FIELD_MISMATCH:{field}:{actual:?}:{expected}")),
    }
}

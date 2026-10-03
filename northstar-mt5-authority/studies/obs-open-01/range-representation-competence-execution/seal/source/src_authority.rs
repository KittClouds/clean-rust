use crate::{ORIGINAL_03BP_ROOT, P2_ROOT, P2T_ROOT, PREOPEN_AUDIT_ROOT, RAW_PATH};
use memchr::memchr;
use memmap2::Mmap;
use obs_open_meas02::{SessionSpec, session_spec};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::path::Path;

const FIREWALL: &str =
    "studies/obs-open-01/future-process-protocol/seal/firewall/session_firewall_manifest.tsv";

#[derive(Debug, Clone, Serialize)]
pub struct ContractHash {
    pub artifact: String,
    pub sha256: String,
}

pub struct BoundAuthority {
    pub d_b_specs: Vec<SessionSpec>,
    pub p2_members: usize,
    pub p2t_members: usize,
    pub firewall_sha256: String,
    pub contract_hashes: Vec<ContractHash>,
    pub raw_path: String,
}

pub fn open(repo: &Path) -> Result<BoundAuthority, Box<dyn std::error::Error>> {
    let p2 = repo.join("studies/obs-open-01/range-representation-inference-protocol-v2/seal");
    let p2t = repo.join("studies/obs-open-01/range-representation-temporal-index-audit/seal");
    let p2_members = verify_seal(
        &p2,
        "03BP2_ROOT_RECEIPT.json",
        "obs_open_03bp2_root",
        P2_ROOT,
    )?;
    let p2t_members = verify_seal(&p2t, "P2T_ROOT_RECEIPT.json", "P2T_root", P2T_ROOT)?;
    let p2_receipt: Value = serde_json::from_slice(&fs::read(p2.join("03BP2_ROOT_RECEIPT.json"))?)?;
    if p2_receipt["parent_protocol_root"] != ORIGINAL_03BP_ROOT
        || p2_receipt["preopen_audit_root"] != PREOPEN_AUDIT_ROOT
    {
        return Err("P2_HISTORICAL_LINEAGE_DRIFT".into());
    }
    let p2t_receipt: Value = serde_json::from_slice(&fs::read(p2t.join("P2T_ROOT_RECEIPT.json"))?)?;
    if p2t_receipt["P2_plus_P2T_executable"] != true
        || p2t_receipt["P2_root_alone_executable"] != false
    {
        return Err("P2T_EXECUTION_AUTHORITY_DRIFT".into());
    }
    let selected: Value = serde_json::from_slice(&fs::read(
        p2.join("contracts/SELECTED_INFERENCE_CONTRACT_V1.json"),
    )?)?;
    if selected["schema"] != "AVERAGE_COMPETENCE_HAC_INFERENCE_V1"
        || selected["state"] != "SELECTED"
        || selected["D_B_open_authorized"] != false
    {
        return Err("P2_CONTRACT_DRIFT".into());
    }
    let temporal: Value = serde_json::from_slice(&fs::read(
        p2t.join("contracts/HAC_TEMPORAL_INDEX_CONTRACT.json"),
    )?)?;
    if temporal["hac_lag_unit"] != "SELECTED_DB_SESSION_ORDINAL"
        || temporal["computation_changed_from_p2"] != false
    {
        return Err("P2T_CONTRACT_DRIFT".into());
    }
    let selected_lambdas: Value =
        serde_json::from_slice(&fs::read(p2.join("d_a/D_A_SELECTED_LAMBDAS.json"))?)?;
    let values = selected_lambdas["values"]
        .as_array()
        .ok_or("LAMBDA_ARRAY_MISSING")?;
    for (arm, lambda) in [("DESIGN", 10.0), ("RAW", 10.0), ("Z", 1.0)] {
        if !values
            .iter()
            .any(|v| v["arm"] == arm && v["lambda"].as_f64() == Some(lambda))
        {
            return Err(format!("SELECTED_LAMBDA_DRIFT:{arm}").into());
        }
    }
    let firewall_path = repo.join(FIREWALL);
    let bytes = map(&firewall_path)?;
    let d_b_specs = parse_d_b(&bytes)?;
    let raw = Path::new(RAW_PATH);
    if sha256_file(raw)? != obs_open_disc02e::RAW_BAR_HASH {
        return Err("RAW_BAR_HASH_DRIFT".into());
    }
    let contract_paths=[
        p2.join("contracts/SELECTED_INFERENCE_CONTRACT_V1.json"),p2.join("contracts/D_B_SUPPORT_GATE_V2.json"),
        p2.join("contracts/MATERIALITY_INFERENCE_AUTHORITY_V2.json"),p2.join("d_a/D_A_SELECTED_LAMBDAS.json"),
        p2t.join("contracts/HAC_TEMPORAL_INDEX_CONTRACT.json"),p2t.join("receipts/ASYMPTOTIC_AUTHORITY_WARNING.json"),
        repo.join("studies/obs-open-01/range-representation-tournament-protocol/seal/contracts/TARGET_CONTRACT_V1.json"),
        repo.join("studies/obs-open-01/range-representation-tournament-protocol/seal/contracts/PROBE_CONTRACT_V1.json"),
        repo.join("studies/obs-open-01/range-representation-tournament-protocol/seal/contracts/SCORE_CONTRACT_V1.json")];
    let mut contract_hashes = Vec::new();
    for path in contract_paths {
        contract_hashes.push(ContractHash {
            artifact: path
                .strip_prefix(repo)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/"),
            sha256: sha256_file(&path)?,
        });
    }
    Ok(BoundAuthority {
        d_b_specs,
        p2_members,
        p2t_members,
        firewall_sha256: sha256(&bytes),
        contract_hashes,
        raw_path: RAW_PATH.into(),
    })
}

fn parse_d_b(bytes: &[u8]) -> Result<Vec<SessionSpec>, Box<dyn std::error::Error>> {
    let header_end = memchr(b'\n', bytes).ok_or("FIREWALL_HEADER")?;
    let mut out = Vec::with_capacity(103);
    let mut da = 0;
    let mut start = header_end + 1;
    while start < bytes.len() {
        let remaining = &bytes[start..];
        let end_rel = memchr(b'\n', remaining).unwrap_or(remaining.len());
        let end = start + end_rel;
        let line = std::str::from_utf8(
            bytes[start..end]
                .strip_suffix(b"\r")
                .unwrap_or(&bytes[start..end]),
        )?;
        start = end + usize::from(end_rel < remaining.len());
        if line.is_empty() {
            continue;
        }
        let mut f = line.split('\t');
        let id = f.next().ok_or("ID")?;
        let date = f.next().ok_or("DATE")?;
        let offset = f.next().ok_or("OFFSET")?.parse::<i32>()?;
        let partition = f.next().ok_or("PARTITION")?;
        let _rank = f.next().ok_or("RANK")?;
        let state = f.next().ok_or("STATE")?;
        if f.next().is_some() {
            return Err("FIREWALL_COLUMN_DRIFT".into());
        }
        match partition {
            "ATLAS_DA" => da += 1,
            "REPRESENTATION_DB" => {
                if state != "D_B_OUTCOME_REGISTRY_UNOPENED" {
                    return Err("D_B_STATE_DRIFT".into());
                }
                out.push(session_spec(id, date, offset, "DISCOVERY")?);
            }
            _ => return Err("UNKNOWN_PARTITION".into()),
        }
    }
    out.sort_unstable_by_key(|s| s.start_epoch);
    if da != 154 || out.len() != 103 {
        return Err("FIREWALL_COUNT_DRIFT".into());
    }
    Ok(out)
}

pub fn verify_seal(
    root: &Path,
    receipt: &str,
    field: &str,
    expected: &str,
) -> Result<usize, Box<dyn std::error::Error>> {
    let v: Value = serde_json::from_slice(&fs::read(root.join(receipt))?)?;
    if v[field].as_str() != Some(expected) {
        return Err(format!("ROOT_DRIFT:{field}").into());
    }
    let manifest = map(&root.join("content_manifest.tsv"))?;
    if sha256(&manifest) != expected {
        return Err(format!("MANIFEST_ROOT_DRIFT:{field}").into());
    }
    let mut n = 0;
    for line in std::str::from_utf8(&manifest)?.lines().skip(1) {
        let f = line.split('\t').collect::<Vec<_>>();
        if f.len() != 3 || f[0].contains("..") || Path::new(f[0]).is_absolute() {
            return Err("INVALID_MANIFEST".into());
        }
        let p = root.join(f[0]);
        if fs::metadata(&p)?.len() != f[1].parse::<u64>()? || sha256_file(&p)? != f[2] {
            return Err(format!("MEMBER_DRIFT:{}", f[0]).into());
        }
        n += 1;
    }
    Ok(n)
}
pub fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    Ok(sha256(&map(path)?))
}
pub fn sha256(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}
pub fn map(path: &Path) -> Result<Mmap, Box<dyn std::error::Error>> {
    Ok(unsafe { Mmap::map(&File::open(path)?) }?)
}

use crate::{B2_PROTOCOL_ROOT, INST01_ROOT, MEAS02_ROOT};
use memchr::memchr_iter;
use memmap2::Mmap;
use obs_open_03a::{AccessAudit, AtlasSession, load_atlas_authority, raw_path};
use obs_open_meas02::sha256_file;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::path::Path;

pub struct BoundAuthority {
    pub sessions: Vec<AtlasSession>,
    pub access: AccessAudit,
    pub raw_source_hash: String,
    pub firewall_manifest_hash: String,
    pub inst_members: usize,
    pub meas_members: usize,
    pub b2_members: usize,
    pub b2_state: String,
}

pub fn open(repo: &Path) -> Result<BoundAuthority, Box<dyn std::error::Error>> {
    let inst = repo.join("studies/obs-open-01/instrument-qualification/seal");
    let meas = repo.join("studies/obs-open-01/measurement-surface/seal");
    let b2 = repo.join("studies/obs-open-01/range-representation-decomposition-protocol/seal");
    let inst_members = verify_inst(&inst)?;
    let meas_members = verify(
        &meas,
        "meas02_root_receipt.json",
        "meas02_root",
        MEAS02_ROOT,
    )?;
    let b2_members = verify(
        &b2,
        "03B2P_ROOT_RECEIPT.json",
        "03B2P_root",
        B2_PROTOCOL_ROOT,
    )?;
    let b2_receipt: Value = serde_json::from_slice(&fs::read(b2.join("03B2P_ROOT_RECEIPT.json"))?)?;
    let b2_state = b2_receipt["state"]
        .as_str()
        .ok_or("B2_STATE_MISSING")?
        .to_owned();
    if b2_state != "FRESH_CONFIRMATION_POPULATION_PENDING"
        || b2_receipt["D_C_observations_read"] != 0
        || b2_receipt["D_D_targets_computed"] != 0
    {
        return Err("03B2_FIREWALL_STATE_DRIFT".into());
    }
    let atlas = load_atlas_authority(repo, &raw_path())?;
    if atlas.access.d_a_outcome_registry_applications != 0
        || atlas.access.d_b_outcome_registry_applications != 0
        || atlas.access.d_b_derived_outcomes_inspected != 0
        || atlas.access.d_b_formal_scores != 0
        || atlas.access.d_c_membership_rows_decoded != 0
        || atlas.access.d_c_observations_read != 0
        || atlas.access.d_c_outcomes_computed != 0
    {
        return Err("OUTCOME_FIREWALL_FAILURE".into());
    }
    Ok(BoundAuthority {
        sessions: atlas.sessions,
        access: atlas.access,
        raw_source_hash: atlas.raw_source_hash,
        firewall_manifest_hash: atlas.firewall_manifest_hash,
        inst_members,
        meas_members,
        b2_members,
        b2_state,
    })
}

fn verify_inst(root: &Path) -> Result<usize, Box<dyn std::error::Error>> {
    let value: Value = serde_json::from_slice(&fs::read(root.join("inst01_root_receipt.json"))?)?;
    if value["inst01_root"].as_str() != Some(INST01_ROOT) {
        return Err("INST01_ROOT_DRIFT".into());
    }
    let artifacts = value["payload"]["artifacts"]
        .as_array()
        .ok_or("INST01_ARTIFACTS_MISSING")?;
    for artifact in artifacts {
        let relative = artifact["path"].as_str().ok_or("INST01_PATH_MISSING")?;
        let path = root.join(relative);
        if fs::metadata(&path)?.len() != artifact["bytes"].as_u64().ok_or("INST01_BYTES_MISSING")?
            || sha256_file(&path)? != artifact["sha256"].as_str().ok_or("INST01_HASH_MISSING")?
        {
            return Err(format!("INST01_MEMBER_DRIFT:{relative}").into());
        }
    }
    Ok(artifacts.len())
}

fn verify(
    root: &Path,
    receipt: &str,
    field: &str,
    expected: &str,
) -> Result<usize, Box<dyn std::error::Error>> {
    let value: Value = serde_json::from_slice(&fs::read(root.join(receipt))?)?;
    if value[field].as_str() != Some(expected) {
        return Err(format!("ROOT_FIELD_DRIFT:{field}").into());
    }
    let manifest = root.join("content_manifest.tsv");
    let file = File::open(&manifest)?;
    let mmap = unsafe { Mmap::map(&file)? };
    if sha256(&mmap) != expected {
        return Err(format!("ROOT_MANIFEST_DRIFT:{field}").into());
    }
    let mut start = 0;
    let mut count = 0usize;
    for end in memchr_iter(b'\n', &mmap) {
        let line = trim_cr(&mmap[start..end]);
        start = end + 1;
        if count == 0 {
            count += 1;
            continue;
        }
        if line.is_empty() {
            continue;
        }
        let text = std::str::from_utf8(line)?;
        let f = text.split('\t').collect::<Vec<_>>();
        if f.len() != 3 || f[0].contains("..") || Path::new(f[0]).is_absolute() {
            return Err("INVALID_MANIFEST".into());
        }
        let path = root.join(f[0]);
        if fs::metadata(&path)?.len() != f[1].parse::<u64>()? || sha256_file(&path)? != f[2] {
            return Err(format!("MEMBER_DRIFT:{}", f[0]).into());
        }
        count += 1;
    }
    Ok(count.saturating_sub(1))
}

fn trim_cr(bytes: &[u8]) -> &[u8] {
    bytes.strip_suffix(b"\r").unwrap_or(bytes)
}
pub fn sha256(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}

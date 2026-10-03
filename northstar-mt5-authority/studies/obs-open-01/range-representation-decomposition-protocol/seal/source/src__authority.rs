use crate::{P2_ROOT, P2T_ROOT, PARENT_03B_ROOT};
use memmap2::Mmap;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::path::Path;

pub struct Authority {
    pub d_a: Vec<obs_open_03bp2::model::SessionRows>,
    pub d_a_bars_read: usize,
    pub d_a_targets_read: usize,
    pub raw_source_sha256: String,
    pub parent_03b_members: usize,
    pub p2_members: usize,
    pub p2t_members: usize,
    pub parent_tournament_sha256: String,
}

pub fn open(repo: &Path) -> Result<Authority, Box<dyn std::error::Error>> {
    let b = repo.join("studies/obs-open-01/range-representation-competence-execution/seal");
    let p2 = repo.join("studies/obs-open-01/range-representation-inference-protocol-v2/seal");
    let p2t = repo.join("studies/obs-open-01/range-representation-temporal-index-audit/seal");
    let parent_03b_members = verify_seal(&b, "03B_ROOT_RECEIPT.json", "03B_root", PARENT_03B_ROOT)?;
    let p2_members = verify_seal(
        &p2,
        "03BP2_ROOT_RECEIPT.json",
        "obs_open_03bp2_root",
        P2_ROOT,
    )?;
    let p2t_members = verify_seal(&p2t, "P2T_ROOT_RECEIPT.json", "P2T_root", P2T_ROOT)?;
    let root: Value = serde_json::from_slice(&fs::read(b.join("03B_ROOT_RECEIPT.json"))?)?;
    if root["tournament_state"] != "BOTH_PAY_RENT" || root["D_C_observations_read"] != 0 {
        return Err("PARENT_03B_STATE_DRIFT".into());
    }
    let tournament = b.join("primary/TOURNAMENT_RESULT.json");
    let result: Value = serde_json::from_slice(&fs::read(&tournament)?)?;
    if result["RAW"]["combined_epistemic_state"] != "REPRESENTATION_PAYS_RENT"
        || result["Z"]["combined_epistemic_state"] != "REPRESENTATION_PAYS_RENT"
        || result["complementarity_authorized"] != false
    {
        return Err("PARENT_TOURNAMENT_DRIFT".into());
    }
    let da = obs_open_03bp2::authority::open(repo)?;
    if da.rows.len() != 150 || da.d_a_target_values_read != 4500 {
        return Err("D_A_AUTHORITY_DRIFT".into());
    }
    Ok(Authority {
        d_a: da.rows,
        d_a_bars_read: da.d_a_bars_read,
        d_a_targets_read: da.d_a_target_values_read,
        raw_source_sha256: da.raw_source_sha256,
        parent_03b_members,
        p2_members,
        p2t_members,
        parent_tournament_sha256: sha256_file(&tournament)?,
    })
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
    let m = map(&root.join("content_manifest.tsv"))?;
    if sha256(&m) != expected {
        return Err(format!("MANIFEST_ROOT_DRIFT:{field}").into());
    }
    let mut n = 0;
    for l in std::str::from_utf8(&m)?.lines().skip(1) {
        let f = l.split('\t').collect::<Vec<_>>();
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
pub fn sha256(x: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(x);
    format!("{:x}", h.finalize())
}
fn map(path: &Path) -> Result<Mmap, Box<dyn std::error::Error>> {
    Ok(unsafe { Mmap::map(&File::open(path)?) }?)
}

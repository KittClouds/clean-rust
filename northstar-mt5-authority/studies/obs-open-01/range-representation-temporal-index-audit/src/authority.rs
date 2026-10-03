use memchr::memchr_iter;
use memmap2::Mmap;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::path::Path;

pub const P2_ROOT: &str = "af0b7f804a8d8337572d6a4a6f2ddcb426defb1f4d5f28ed0fde54882050d00c";
pub const PA_ROOT: &str = "c6ec93a00a2d62e646d5565c727c233844c64d05e1485fe95956cfc905d86aff";
pub const FIREWALL_REL: &str =
    "studies/obs-open-01/future-process-protocol/seal/firewall/session_firewall_manifest.tsv";

#[derive(Debug, Clone)]
pub struct MembershipRow {
    pub session_id: String,
    pub civil_date: String,
    pub offset: i32,
    pub partition: String,
}

pub struct Authority {
    pub rows: Vec<MembershipRow>,
    pub p2_members: usize,
    pub pa_members: usize,
    pub firewall_hash: String,
    pub source_hash: String,
}

pub fn open(repo: &Path) -> Result<Authority, Box<dyn std::error::Error>> {
    let p2 = repo.join("studies/obs-open-01/range-representation-inference-protocol-v2/seal");
    let pa = repo.join("studies/obs-open-01/range-representation-inference-audit/seal");
    let p2_members = verify_seal(
        &p2,
        "03BP2_ROOT_RECEIPT.json",
        "obs_open_03bp2_root",
        P2_ROOT,
    )?;
    let pa_members = verify_seal(
        &pa,
        "PREOPEN_AUDIT_ROOT_RECEIPT.json",
        "preopen_audit_root",
        PA_ROOT,
    )?;
    let contract: Value = serde_json::from_slice(&fs::read(
        p2.join("contracts/SELECTED_INFERENCE_CONTRACT_V1.json"),
    )?)?;
    if contract["schema"] != "AVERAGE_COMPETENCE_HAC_INFERENCE_V1"
        || contract["kernel"] != "BARTLETT"
    {
        return Err("P2_INFERENCE_CONTRACT_DRIFT".into());
    }
    let source = p2.join("source/src_dependence.rs");
    let source_bytes = map(&source)?;
    if !source_bytes.windows(13).any(|w| w == b"values[lag..]") {
        return Err("P2_LAG_KERNEL_SOURCE_DRIFT".into());
    }
    let firewall_path = repo.join(FIREWALL_REL);
    let firewall = map(&firewall_path)?;
    let rows = parse_firewall(&firewall)?;
    if rows.len() != 257
        || rows
            .iter()
            .filter(|r| r.partition == "REPRESENTATION_DB")
            .count()
            != 103
    {
        return Err("PARTITION_MEMBERSHIP_DRIFT".into());
    }
    Ok(Authority {
        rows,
        p2_members,
        pa_members,
        firewall_hash: sha256(&firewall),
        source_hash: sha256(&source_bytes),
    })
}

fn parse_firewall(bytes: &[u8]) -> Result<Vec<MembershipRow>, Box<dyn std::error::Error>> {
    let mut starts = Vec::with_capacity(260);
    starts.push(0usize);
    starts.extend(memchr_iter(b'\n', bytes).map(|i| i + 1));
    let mut rows = Vec::with_capacity(257);
    for pair in starts.windows(2).skip(1) {
        let line = std::str::from_utf8(&bytes[pair[0]..pair[1] - 1])?.trim_end_matches('\r');
        if line.is_empty() {
            continue;
        }
        let mut f = line.split('\t');
        rows.push(MembershipRow {
            session_id: f.next().ok_or("SESSION_ID_MISSING")?.into(),
            civil_date: f.next().ok_or("DATE_MISSING")?.into(),
            offset: f.next().ok_or("OFFSET_MISSING")?.parse()?,
            partition: f.next().ok_or("PARTITION_MISSING")?.into(),
        });
    }
    Ok(rows)
}

pub fn verify_seal(
    root: &Path,
    receipt: &str,
    field: &str,
    expected: &str,
) -> Result<usize, Box<dyn std::error::Error>> {
    let value: Value = serde_json::from_slice(&fs::read(root.join(receipt))?)?;
    if value[field].as_str() != Some(expected) {
        return Err(format!("ROOT_DRIFT:{field}").into());
    }
    let manifest = map(&root.join("content_manifest.tsv"))?;
    if sha256(&manifest) != expected {
        return Err(format!("MANIFEST_ROOT_DRIFT:{field}").into());
    }
    let mut count = 0;
    for line in std::str::from_utf8(&manifest)?.lines().skip(1) {
        let f = line.split('\t').collect::<Vec<_>>();
        if f.len() != 3 || f[0].contains("..") || Path::new(f[0]).is_absolute() {
            return Err("INVALID_MANIFEST".into());
        }
        let path = root.join(f[0]);
        if fs::metadata(&path)?.len() != f[1].parse::<u64>()? || sha256_file(&path)? != f[2] {
            return Err(format!("MEMBER_DRIFT:{}", f[0]).into());
        }
        count += 1;
    }
    Ok(count)
}

pub fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    Ok(sha256(&map(path)?))
}
pub fn sha256(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}
fn map(path: &Path) -> Result<Mmap, Box<dyn std::error::Error>> {
    Ok(unsafe { Mmap::map(&File::open(path)?) }?)
}

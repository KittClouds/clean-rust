use crate::model::*;
use memmap2::Mmap;
use obs_open_03a::PackedOutcome;
use obs_open_03bp::algebra::{normalize, raw_snapshot};
use obs_open_03bp::authority::BoundAuthority;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::path::{Path, PathBuf};

const PARENT_SEAL: &str = "studies/obs-open-01/range-representation-tournament-protocol/seal";
const AUDIT_SEAL: &str = "studies/obs-open-01/range-representation-inference-audit/seal";
const ATLAS_AUTHORITY: &str = "D:/obs-open-01/atlas/obs-open-03a-build-a";

pub struct Authority {
    pub rows: Vec<SessionRows>,
    pub parent_member_count: usize,
    pub audit_member_count: usize,
    pub atlas_member_count: usize,
    pub d_a_sessions_decoded: usize,
    pub d_a_target_values_read: usize,
    pub d_a_outcome_records_scanned: usize,
    pub d_a_bars_read: usize,
    pub d_a_gap_sessions: usize,
    pub raw_source_sha256: String,
}

pub fn open(repo: &Path) -> Result<Authority, Box<dyn std::error::Error>> {
    let parent_member_count = verify_seal(
        &repo.join(PARENT_SEAL),
        "03BP_ROOT_RECEIPT.json",
        "obs_open_03bp_root",
        PARENT_PROTOCOL_ROOT,
    )?;
    let audit_member_count = verify_seal(
        &repo.join(AUDIT_SEAL),
        "PREOPEN_AUDIT_ROOT_RECEIPT.json",
        "preopen_audit_root",
        PREOPEN_AUDIT_ROOT,
    )?;
    let atlas_root = PathBuf::from(ATLAS_AUTHORITY);
    let atlas_member_count = verify_seal(
        &atlas_root,
        "OBS_OPEN_03A_ROOT_RECEIPT.json",
        "obs_open_03a_root",
        ATLAS_ROOT,
    )?;
    let parent = BoundAuthority::open(repo, &atlas_root)?;
    if parent.sessions.len() != D_A_SESSIONS {
        return Err("D_A_SESSION_COUNT_DRIFT".into());
    }
    let targets = target_matrix(parent.records())?;
    let mut rows = Vec::with_capacity(D_A_SESSIONS);
    for (session_index, session) in parent.sessions.iter().enumerate() {
        let Some(targets) = targets[session_index] else {
            continue;
        };
        let mut raw = [[0.0; 5]; RANGE_COUNT];
        let mut z = [[0.0; 4]; RANGE_COUNT];
        for k in 1..=RANGE_COUNT {
            let r = raw_snapshot(session, k)?;
            let n = normalize(r)?;
            raw[k - 1] = [
                r.width,
                r.open_minus_mid,
                r.high_minus_mid,
                r.low_minus_mid,
                r.close_minus_mid,
            ];
            z[k - 1] = [n.z_open, n.z_high, n.z_low, n.z_close];
        }
        rows.push(SessionRows {
            session_index,
            session_id: session.spec.session_id.clone(),
            civil_date: session.spec.civil_date.clone(),
            month: session.month.clone(),
            offset: session.spec.server_offset_minutes,
            targets,
            raw,
            z,
        });
    }
    let complete = rows.len();
    if complete != 150 {
        return Err(format!("D_A_COMPLETE_SESSION_DRIFT:{complete}").into());
    }
    Ok(Authority {
        rows,
        parent_member_count,
        audit_member_count,
        atlas_member_count,
        d_a_sessions_decoded: parent.sessions.len(),
        d_a_target_values_read: complete * RANGE_COUNT,
        d_a_outcome_records_scanned: parent.records().len(),
        d_a_bars_read: parent.d_a_bars_read,
        d_a_gap_sessions: parent.d_a_gap_sessions,
        raw_source_sha256: parent.raw_source_sha256,
    })
}

fn target_matrix(records: &[PackedOutcome]) -> Result<Vec<Option<[f64; RANGE_COUNT]>>, String> {
    let mut values = vec![None; D_A_SESSIONS];
    let mut temporary = vec![[f64::NAN; RANGE_COUNT]; D_A_SESSIONS];
    let mut counts = vec![0usize; D_A_SESSIONS];
    for record in records.iter().filter(|record| {
        record.anchor_kind == 2
            && record.outcome_code == 101
            && record.representation == 1
            && record.horizon_minutes == 60
    }) {
        let session = record.session_index as usize;
        let k = record.k as usize;
        if session >= D_A_SESSIONS || !(1..=RANGE_COUNT).contains(&k) {
            return Err("TARGET_IDENTITY_DRIFT".into());
        }
        if record.outcome_state == 1
            && record.value_present == 1
            && record.support_bars == 60
            && record.outcome_known_present == 1
            && record.outcome_known_at == record.anchor_known_at + 3600
        {
            if temporary[session][k - 1].is_finite() {
                return Err("DUPLICATE_COMPLETE_TARGET".into());
            }
            let value = record.value().ok_or("COMPLETE_TARGET_VALUE_MISSING")?;
            temporary[session][k - 1] = if value > 0.0 { 1.0 } else { 0.0 };
            counts[session] += 1;
        }
    }
    for session in 0..D_A_SESSIONS {
        if counts[session] == RANGE_COUNT {
            values[session] = Some(temporary[session]);
        }
    }
    Ok(values)
}

fn verify_seal(
    root: &Path,
    receipt_name: &str,
    field: &str,
    expected: &str,
) -> Result<usize, Box<dyn std::error::Error>> {
    let receipt: Value = serde_json::from_slice(&fs::read(root.join(receipt_name))?)?;
    if receipt[field].as_str() != Some(expected) {
        return Err(format!("ROOT_DRIFT:{field}").into());
    }
    let manifest = map(&root.join("content_manifest.tsv"))?;
    if sha256(&manifest) != expected {
        return Err(format!("MANIFEST_ROOT_DRIFT:{field}").into());
    }
    let mut count = 0;
    for line in std::str::from_utf8(&manifest)?.lines().skip(1) {
        let fields = line.split('\t').collect::<Vec<_>>();
        if fields.len() != 3 || fields[0].contains("..") || Path::new(fields[0]).is_absolute() {
            return Err("INVALID_PARENT_MANIFEST".into());
        }
        let path = root.join(fields[0]);
        if fs::metadata(&path)?.len() != fields[1].parse::<u64>()?
            || sha256_file(&path)? != fields[2]
        {
            return Err(format!("PARENT_MEMBER_DRIFT:{}", fields[0]).into());
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
pub fn atlas_authority_path() -> PathBuf {
    PathBuf::from(ATLAS_AUTHORITY)
}

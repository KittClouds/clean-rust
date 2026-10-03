use crate::{
    AnyResult, DISC02P_ROOT, DISCOVERY_PREFIX_HASH, DISCOVERY_PREFIX_ROWS, DISCOVERY_SESSIONS,
    MEAS02_ROOT, RAW_BAR_HASH,
};
use hashbrown::HashMap;
use memchr::memchr_iter;
use memmap2::Mmap;
use obs_open_disc02p::sha256_file;
use obs_open_meas02::{Bar, SessionSpec, session_spec};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::path::{Path, PathBuf};

const RAW_BYTES: u64 = 93_138_485;

#[derive(Debug, Clone)]
pub struct AuthorityPaths {
    pub repo: PathBuf,
    pub raw_bars: PathBuf,
    pub partition: PathBuf,
}

impl AuthorityPaths {
    pub fn new(repo: &Path, raw_bars: &Path) -> Self {
        Self {
            repo: repo.to_path_buf(),
            raw_bars: raw_bars.to_path_buf(),
            partition: repo
                .join("studies/obs-open-01/qualification/universe/universe/partition_manifest.tsv"),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ParentVerification {
    pub disc02p_root: String,
    pub meas02_root: String,
    pub disc02p_members_verified: usize,
    pub meas02_members_verified: usize,
    pub raw_declared_sha256: String,
    pub raw_declared_bytes: u64,
    pub discovery_prefix_sha256: String,
    pub partition_discovery_prefix_sha256: String,
    pub confirmation_membership_rows_decoded: u64,
    pub confirmation_observation_rows_decoded: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SourceAccess {
    pub source_prefix_rows_decoded: usize,
    pub selected_m1_observations_read: usize,
    pub retained_causal_m1_observations: usize,
    pub sessions_with_path_gap: usize,
    pub path_gaps: Vec<PathGap>,
    pub first_selected_open_epoch: i64,
    pub last_selected_close_epoch: i64,
    pub confirmation_observation_rows_decoded: u64,
    pub next_source_row_requested: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct PathGap {
    pub session_id: String,
    pub expected_open_epoch: i64,
    pub first_later_observed_epoch: Option<i64>,
    pub retained_prefix_bars: usize,
    pub coverage_state: String,
}

#[derive(Debug)]
pub struct LoadedAuthority {
    pub sessions: Vec<SessionSpec>,
    pub bars: Vec<Vec<Bar>>,
    pub parent: ParentVerification,
    pub access: SourceAccess,
}

pub fn load(paths: &AuthorityPaths) -> AnyResult<LoadedAuthority> {
    let disc_members = verify_seal(
        &paths.repo,
        "studies/obs-open-01/discovery-protocol/seal",
        "content_manifest.tsv",
    )?;
    let meas_members = verify_seal(
        &paths.repo,
        "studies/obs-open-01/measurement-surface/seal",
        "content_manifest.tsv",
    )?;
    verify_roots(&paths.repo)?;
    let metadata = std::fs::metadata(&paths.raw_bars)?;
    if metadata.len() != RAW_BYTES {
        return Err(format!(
            "RAW_AUTHORITY_SIZE_DRIFT expected={RAW_BYTES} observed={}",
            metadata.len()
        )
        .into());
    }
    let (sessions, partition_hash) = load_discovery_partition(&paths.partition)?;
    let (bars, prefix_hash, access) = load_discovery_prefix(&paths.raw_bars, &sessions)?;
    if prefix_hash != DISCOVERY_PREFIX_HASH {
        return Err(format!(
            "DISCOVERY_PREFIX_HASH_DRIFT expected={DISCOVERY_PREFIX_HASH} observed={prefix_hash}"
        )
        .into());
    }
    Ok(LoadedAuthority {
        sessions,
        bars,
        parent: ParentVerification {
            disc02p_root: DISC02P_ROOT.into(),
            meas02_root: MEAS02_ROOT.into(),
            disc02p_members_verified: disc_members,
            meas02_members_verified: meas_members,
            raw_declared_sha256: RAW_BAR_HASH.into(),
            raw_declared_bytes: RAW_BYTES,
            discovery_prefix_sha256: prefix_hash,
            partition_discovery_prefix_sha256: partition_hash,
            confirmation_membership_rows_decoded: 0,
            confirmation_observation_rows_decoded: 0,
        },
        access,
    })
}

fn verify_roots(repo: &Path) -> AnyResult<()> {
    let disc: Value = serde_json::from_slice(&std::fs::read(
        repo.join("studies/obs-open-01/discovery-protocol/seal/disc02p_root_receipt.json"),
    )?)?;
    if disc.pointer("/disc02p_root").and_then(Value::as_str) != Some(DISC02P_ROOT)
        || disc.pointer("/status").and_then(Value::as_str) != Some("PASS")
        || disc
            .pointer("/confirmation_rows_read")
            .and_then(Value::as_u64)
            != Some(0)
    {
        return Err("DISC02P_ROOT_AUTHORITY_MISMATCH".into());
    }
    let meas: Value = serde_json::from_slice(&std::fs::read(
        repo.join("studies/obs-open-01/measurement-surface/seal/meas02_root_receipt.json"),
    )?)?;
    if meas.pointer("/meas02_root").and_then(Value::as_str) != Some(MEAS02_ROOT)
        || meas.pointer("/status").and_then(Value::as_str) != Some("PASS")
        || meas
            .pointer("/confirmation_observation_rows_read")
            .and_then(Value::as_u64)
            != Some(0)
    {
        return Err("MEAS02_ROOT_AUTHORITY_MISMATCH".into());
    }
    Ok(())
}

fn verify_seal(repo: &Path, relative: &str, manifest_name: &str) -> AnyResult<usize> {
    let seal = repo.join(relative);
    let text = std::fs::read_to_string(seal.join(manifest_name))?;
    let mut verified = 0usize;
    for line in text.lines().skip(1) {
        let mut fields = line.split('\t');
        let member = fields.next().ok_or("SEAL_MANIFEST_PATH_MISSING")?;
        let bytes = fields
            .next()
            .ok_or("SEAL_MANIFEST_BYTES_MISSING")?
            .parse::<u64>()?;
        let hash = fields.next().ok_or("SEAL_MANIFEST_HASH_MISSING")?;
        if member.contains("..") || Path::new(member).is_absolute() {
            return Err(format!("UNSAFE_SEAL_MEMBER:{member}").into());
        }
        let path = seal.join(member);
        if std::fs::metadata(&path)?.len() != bytes || sha256_file(&path)? != hash {
            return Err(format!("SEALED_MEMBER_DRIFT:{}", path.display()).into());
        }
        verified += 1;
    }
    if verified == 0 {
        return Err("EMPTY_SEAL_MANIFEST".into());
    }
    Ok(verified)
}

fn load_discovery_partition(path: &Path) -> AnyResult<(Vec<SessionSpec>, String)> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file) }?;
    let required_lines = DISCOVERY_SESSIONS + 1;
    let end = memchr_iter(b'\n', &mmap)
        .nth(required_lines - 1)
        .ok_or("PARTITION_DISCOVERY_PREFIX_TRUNCATED")?
        + 1;
    let prefix = &mmap[..end];
    let text = std::str::from_utf8(prefix)?;
    let mut lines = text.lines();
    if lines.next()
        != Some("session_id\tcivil_date\tpartition\tserver_offset_minutes\tconfirmation_status")
    {
        return Err("PARTITION_SCHEMA_DRIFT".into());
    }
    let mut sessions = Vec::with_capacity(DISCOVERY_SESSIONS);
    for line in lines {
        let mut c = line.split('\t');
        let session_id = c.next().ok_or("PARTITION_SESSION_MISSING")?;
        let civil_date = c.next().ok_or("PARTITION_DATE_MISSING")?;
        let partition = c.next().ok_or("PARTITION_CLASS_MISSING")?;
        let offset = c.next().ok_or("PARTITION_OFFSET_MISSING")?.parse::<i32>()?;
        let confirmation_state = c.next().ok_or("PARTITION_STATE_MISSING")?;
        if partition != "DISCOVERY" || confirmation_state != "NOT_APPLICABLE" {
            return Err(format!("DISCOVERY_PREFIX_BOUNDARY_VIOLATION:{session_id}").into());
        }
        sessions.push(session_spec(session_id, civil_date, offset, partition)?);
    }
    if sessions.len() != DISCOVERY_SESSIONS {
        return Err("DISCOVERY_SESSION_CARDINALITY_DRIFT".into());
    }
    sessions.sort_unstable_by_key(|s| s.start_epoch);
    Ok((sessions, hash_bytes(prefix)))
}

fn load_discovery_prefix(
    path: &Path,
    sessions: &[SessionSpec],
) -> AnyResult<(Vec<Vec<Bar>>, String, SourceAccess)> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file) }?;
    let required_lines = DISCOVERY_PREFIX_ROWS + 1;
    let end = memchr_iter(b'\n', &mmap)
        .nth(required_lines - 1)
        .ok_or("SOURCE_DISCOVERY_PREFIX_TRUNCATED")?
        + 1;
    let prefix = &mmap[..end];
    let prefix_hash = hash_bytes(prefix);
    let mut owners = HashMap::with_capacity(sessions.len() * 390);
    for (session_index, session) in sessions.iter().enumerate() {
        for bar_index in 0..390usize {
            owners.insert(
                session.start_epoch + bar_index as i64 * 60,
                (session_index, bar_index),
            );
        }
    }
    let mut bars: Vec<Vec<Bar>> = (0..sessions.len())
        .map(|_| Vec::with_capacity(390))
        .collect();
    let mut gap_seen = vec![false; sessions.len()];
    let mut path_gaps = Vec::new();
    let mut selected_observations = 0usize;
    let mut line_start = 0usize;
    let mut row = 0usize;
    for line_end in memchr_iter(b'\n', prefix) {
        let mut line = &prefix[line_start..line_end];
        line_start = line_end + 1;
        if line.ends_with(b"\r") {
            line = &line[..line.len() - 1];
        }
        if row == 0 {
            if line != b"schema\tsource_day\ttimeframe\tserver_epoch\tserver_time\topen\thigh\tlow\tclose\ttick_volume\tspread\treal_volume" {
                return Err("SOURCE_SCHEMA_DRIFT".into());
            }
            row += 1;
            continue;
        }
        row += 1;
        let mut fields = line.split(|&b| b == b'\t');
        let _schema = fields.next().ok_or("SOURCE_SCHEMA_MISSING")?;
        let _day = fields.next().ok_or("SOURCE_DAY_MISSING")?;
        let timeframe = fields.next().ok_or("SOURCE_TIMEFRAME_MISSING")?;
        if timeframe != b"M1" {
            continue;
        }
        let epoch = parse_i64(fields.next().ok_or("SOURCE_EPOCH_MISSING")?)?;
        let Some(&(session_index, expected_index)) = owners.get(&epoch) else {
            continue;
        };
        selected_observations += 1;
        if gap_seen[session_index] {
            continue;
        }
        let _server_time = fields.next().ok_or("SOURCE_SERVER_TIME_MISSING")?;
        let open = parse_f64(fields.next().ok_or("SOURCE_OPEN_MISSING")?)?;
        let high = parse_f64(fields.next().ok_or("SOURCE_HIGH_MISSING")?)?;
        let low = parse_f64(fields.next().ok_or("SOURCE_LOW_MISSING")?)?;
        let close = parse_f64(fields.next().ok_or("SOURCE_CLOSE_MISSING")?)?;
        if bars[session_index].len() != expected_index {
            gap_seen[session_index] = true;
            path_gaps.push(PathGap {
                session_id: sessions[session_index].session_id.clone(),
                expected_open_epoch: sessions[session_index].start_epoch
                    + bars[session_index].len() as i64 * 60,
                first_later_observed_epoch: Some(epoch),
                retained_prefix_bars: bars[session_index].len(),
                coverage_state: "NOT_EVALUABLE_SENTINEL_PATH_GAP".into(),
            });
            continue;
        }
        bars[session_index].push(Bar {
            source_row_id: format!("RAW125B:M1:{epoch}"),
            open_time: epoch,
            close_time: epoch + 60,
            open,
            high,
            low,
            close,
            coverage: "COMPLETE".into(),
        });
    }
    if row != required_lines {
        return Err(
            format!("SOURCE_PREFIX_ROW_DRIFT expected={required_lines} observed={row}").into(),
        );
    }
    for (index, (session, observed)) in sessions.iter().zip(&bars).enumerate() {
        if observed.len() < 30 {
            return Err(format!(
                "SESSION_OPENING_CONSTRUCTION_COVERAGE_DRIFT session={} minimum=30 observed={}",
                session.session_id,
                observed.len()
            )
            .into());
        }
        if observed.len() < 390 && !gap_seen[index] {
            path_gaps.push(PathGap {
                session_id: session.session_id.clone(),
                expected_open_epoch: session.start_epoch + observed.len() as i64 * 60,
                first_later_observed_epoch: None,
                retained_prefix_bars: observed.len(),
                coverage_state: "NOT_EVALUABLE_SENTINEL_PATH_GAP".into(),
            });
        }
    }
    let first = sessions
        .first()
        .ok_or("EMPTY_DISCOVERY_SESSIONS")?
        .start_epoch;
    let last = sessions
        .last()
        .ok_or("EMPTY_DISCOVERY_SESSIONS")?
        .terminal_epoch;
    let retained_observations = bars.iter().map(Vec::len).sum();
    Ok((
        bars,
        prefix_hash,
        SourceAccess {
            source_prefix_rows_decoded: DISCOVERY_PREFIX_ROWS,
            selected_m1_observations_read: selected_observations,
            retained_causal_m1_observations: retained_observations,
            sessions_with_path_gap: path_gaps.len(),
            path_gaps,
            first_selected_open_epoch: first,
            last_selected_close_epoch: last,
            confirmation_observation_rows_decoded: 0,
            next_source_row_requested: false,
        },
    ))
}

fn parse_i64(raw: &[u8]) -> AnyResult<i64> {
    Ok(std::str::from_utf8(raw)?.parse::<i64>()?)
}

fn parse_f64(raw: &[u8]) -> AnyResult<f64> {
    Ok(std::str::from_utf8(raw)?.parse::<f64>()?)
}

fn hash_bytes(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}

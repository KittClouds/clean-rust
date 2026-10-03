use crate::model::{
    ATLAS_SESSIONS, AccessAudit, AtlasSession, D_B_SESSIONS, PROTOCOL_ROOT, PathGap, SESSION_BARS,
};
use hashbrown::HashMap;
use memchr::{memchr, memchr_iter};
use memmap2::Mmap;
use obs_open_disc02e::{DISCOVERY_PREFIX_HASH, DISCOVERY_PREFIX_ROWS, RAW_BAR_HASH};
use obs_open_meas02::{Bar, build_candidates_and_tape, build_ranges, session_spec, sha256_file};
use rayon::prelude::*;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::path::{Path, PathBuf};

const RAW_BYTES: u64 = 93_138_485;
const FIREWALL_MANIFEST: &str =
    "studies/obs-open-01/future-process-protocol/seal/firewall/session_firewall_manifest.tsv";
const PROTOCOL_SEAL: &str = "studies/obs-open-01/future-process-protocol/seal";

#[derive(Debug)]
pub struct LoadedAtlas {
    pub sessions: Vec<AtlasSession>,
    pub access: AccessAudit,
    pub raw_source_hash: String,
    pub firewall_manifest_hash: String,
}

pub fn load_atlas_authority(
    repository: &Path,
    raw_bars: &Path,
) -> Result<LoadedAtlas, Box<dyn std::error::Error>> {
    verify_protocol_seal(repository)?;
    let metadata = std::fs::metadata(raw_bars)?;
    if metadata.len() != RAW_BYTES {
        return Err(format!(
            "RAW_AUTHORITY_SIZE_DRIFT expected={RAW_BYTES} observed={}",
            metadata.len()
        )
        .into());
    }
    let firewall_path = repository.join(FIREWALL_MANIFEST);
    let firewall_manifest_hash = sha256_file(&firewall_path)?;
    let mut specs = load_da_sessions(&firewall_path)?;
    specs.sort_unstable_by_key(|spec| spec.start_epoch);
    let (bars, mut access) = load_da_prefix(raw_bars, &specs)?;
    let mut sessions: Vec<_> = specs
        .into_par_iter()
        .zip(bars.into_par_iter())
        .map(|(spec, bars)| {
            let ranges = build_ranges(&spec, &bars)?;
            let (mut candidates, _) = build_candidates_and_tape(&spec, &bars)?;
            let path_complete = bars.len() == SESSION_BARS;
            if !path_complete {
                for candidate in candidates
                    .iter_mut()
                    .filter(|candidate| candidate.terminal_survivor)
                {
                    candidate.terminal_survivor = false;
                    candidate.terminal_label_known_at = None;
                    candidate.terminal_label_knowledge_order = None;
                    candidate.coverage_state = "SOURCE_PATH_INCOMPLETE".into();
                }
            }
            Ok::<_, Box<dyn std::error::Error + Send + Sync>>(AtlasSession {
                month: spec.civil_date[..7].to_owned(),
                spec,
                bars,
                ranges,
                candidates,
                path_complete,
            })
        })
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| -> Box<dyn std::error::Error> { error })?;
    sessions.sort_unstable_by_key(|session| session.spec.start_epoch);
    if sessions.len() != ATLAS_SESSIONS {
        return Err(format!("D_A_SESSION_COUNT_DRIFT:{}", sessions.len()).into());
    }
    access.d_a_sessions_decoded = sessions.len();
    Ok(LoadedAtlas {
        sessions,
        access,
        raw_source_hash: RAW_BAR_HASH.into(),
        firewall_manifest_hash,
    })
}

fn verify_protocol_seal(repository: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let seal = repository.join(PROTOCOL_SEAL);
    let root: Value = serde_json::from_slice(&std::fs::read(
        seal.join("obs_open_03ap_root_receipt.json"),
    )?)?;
    if root.get("obs_open_03ap_root").and_then(Value::as_str) != Some(PROTOCOL_ROOT)
        || root.get("status").and_then(Value::as_str) != Some("PASS")
        || root
            .get("confirmation_observations_read")
            .and_then(Value::as_u64)
            != Some(0)
    {
        return Err("03AP_ROOT_AUTHORITY_MISMATCH".into());
    }
    let manifest = std::fs::read_to_string(seal.join("content_manifest.tsv"))?;
    let mut verified = 0;
    for line in manifest.lines().skip(1) {
        let mut fields = line.split('\t');
        let relative = fields.next().ok_or("03AP_MEMBER_PATH_MISSING")?;
        let bytes = fields
            .next()
            .ok_or("03AP_MEMBER_BYTES_MISSING")?
            .parse::<u64>()?;
        let hash = fields.next().ok_or("03AP_MEMBER_HASH_MISSING")?;
        if relative.contains("..") || Path::new(relative).is_absolute() {
            return Err(format!("UNSAFE_03AP_MEMBER:{relative}").into());
        }
        let path = seal.join(relative);
        if std::fs::metadata(&path)?.len() != bytes || sha256_file(&path)? != hash {
            return Err(format!("03AP_MEMBER_DRIFT:{relative}").into());
        }
        verified += 1;
    }
    if verified != 25 {
        return Err(format!("03AP_MEMBER_COUNT_DRIFT:{verified}").into());
    }
    Ok(())
}

fn load_da_sessions(
    path: &Path,
) -> Result<Vec<obs_open_meas02::SessionSpec>, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file) }?;
    let header_end = memchr(b'\n', &mmap).ok_or("FIREWALL_HEADER_MISSING")?;
    let header = trim_cr(&mmap[..header_end]);
    if header != b"session_id\tcivil_date\tserver_offset_minutes\tderived_partition\trank_key\toutcome_state" {
        return Err("FIREWALL_SCHEMA_DRIFT".into());
    }
    let mut atlas = Vec::with_capacity(ATLAS_SESSIONS);
    let mut db_count = 0;
    let mut cursor = header_end + 1;
    while cursor < mmap.len() {
        let remaining = &mmap[cursor..];
        let end = memchr(b'\n', remaining).unwrap_or(remaining.len());
        let line = trim_cr(&remaining[..end]);
        cursor += end + usize::from(end < remaining.len());
        if line.is_empty() {
            continue;
        }
        if contains(line, b"\tREPRESENTATION_DB\t") {
            db_count += 1;
            continue;
        }
        if !contains(line, b"\tATLAS_DA\t") {
            return Err("UNKNOWN_DERIVED_PARTITION".into());
        }
        let text = std::str::from_utf8(line)?;
        let mut fields = text.split('\t');
        let session_id = fields.next().ok_or("D_A_SESSION_ID_MISSING")?;
        let civil_date = fields.next().ok_or("D_A_DATE_MISSING")?;
        let offset = fields.next().ok_or("D_A_OFFSET_MISSING")?.parse::<i32>()?;
        let partition = fields.next().ok_or("D_A_PARTITION_MISSING")?;
        let _rank = fields.next().ok_or("D_A_RANK_MISSING")?;
        let state = fields.next().ok_or("D_A_STATE_MISSING")?;
        if fields.next().is_some()
            || partition != "ATLAS_DA"
            || state != "03A_PROTOCOL_FROZEN_OUTCOMES_NOT_COMPUTED"
        {
            return Err("D_A_FIREWALL_ROW_DRIFT".into());
        }
        atlas.push(session_spec(session_id, civil_date, offset, "DISCOVERY")?);
    }
    if atlas.len() != ATLAS_SESSIONS || db_count != D_B_SESSIONS {
        return Err(format!("FIREWALL_CARDINALITY_DRIFT:{}:{db_count}", atlas.len()).into());
    }
    Ok(atlas)
}

type LoadedBars = (Vec<Vec<Bar>>, AccessAudit);

fn load_da_prefix(
    path: &Path,
    sessions: &[obs_open_meas02::SessionSpec],
) -> Result<LoadedBars, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file) }?;
    let required_lines = DISCOVERY_PREFIX_ROWS + 1;
    let end = memchr_iter(b'\n', &mmap)
        .nth(required_lines - 1)
        .ok_or("SOURCE_DISCOVERY_PREFIX_TRUNCATED")?
        + 1;
    let prefix = &mmap[..end];
    let prefix_hash = sha256(prefix);
    if prefix_hash != DISCOVERY_PREFIX_HASH {
        return Err(format!("DISCOVERY_PREFIX_HASH_DRIFT:{prefix_hash}").into());
    }
    let mut owners = HashMap::with_capacity(sessions.len() * SESSION_BARS);
    for (session_index, session) in sessions.iter().enumerate() {
        for bar_index in 0..SESSION_BARS {
            owners.insert(
                session.start_epoch + bar_index as i64 * 60,
                (session_index, bar_index),
            );
        }
    }
    let mut bars: Vec<Vec<Bar>> = (0..sessions.len())
        .map(|_| Vec::with_capacity(SESSION_BARS))
        .collect();
    let mut gap_seen = vec![false; sessions.len()];
    let mut gaps = Vec::new();
    let mut selected = 0;
    let mut line_start = 0;
    let mut row = 0;
    for line_end in memchr_iter(b'\n', prefix) {
        let line = trim_cr(&prefix[line_start..line_end]);
        line_start = line_end + 1;
        if row == 0 {
            if line != b"schema\tsource_day\ttimeframe\tserver_epoch\tserver_time\topen\thigh\tlow\tclose\ttick_volume\tspread\treal_volume" {
                return Err("SOURCE_SCHEMA_DRIFT".into());
            }
            row += 1;
            continue;
        }
        row += 1;
        let mut fields = line.split(|&byte| byte == b'\t');
        let _schema = fields.next().ok_or("SOURCE_SCHEMA_MISSING")?;
        let _day = fields.next().ok_or("SOURCE_DAY_MISSING")?;
        if fields.next().ok_or("SOURCE_TIMEFRAME_MISSING")? != b"M1" {
            continue;
        }
        let epoch = parse_i64(fields.next().ok_or("SOURCE_EPOCH_MISSING")?)?;
        let Some(&(session_index, expected_index)) = owners.get(&epoch) else {
            continue;
        };
        if gap_seen[session_index] {
            continue;
        }
        if bars[session_index].len() != expected_index {
            gap_seen[session_index] = true;
            gaps.push(PathGap {
                session_id: sessions[session_index].session_id.clone(),
                expected_open_epoch: sessions[session_index].start_epoch
                    + bars[session_index].len() as i64 * 60,
                first_later_observed_epoch: Some(epoch),
                retained_prefix_bars: bars[session_index].len(),
                state: "SOURCE_PATH_INCOMPLETE".into(),
            });
            continue;
        }
        let _server_time = fields.next().ok_or("SOURCE_TIME_MISSING")?;
        let open = parse_f64(fields.next().ok_or("SOURCE_OPEN_MISSING")?)?;
        let high = parse_f64(fields.next().ok_or("SOURCE_HIGH_MISSING")?)?;
        let low = parse_f64(fields.next().ok_or("SOURCE_LOW_MISSING")?)?;
        let close = parse_f64(fields.next().ok_or("SOURCE_CLOSE_MISSING")?)?;
        selected += 1;
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
        return Err(format!("SOURCE_PREFIX_ROW_DRIFT:{row}:{required_lines}").into());
    }
    for (index, session) in sessions.iter().enumerate() {
        if bars[index].len() < 30 {
            return Err(format!("D_A_RANGE_CONSTRUCTION_INCOMPLETE:{}", session.session_id).into());
        }
        if bars[index].len() < SESSION_BARS && !gap_seen[index] {
            gaps.push(PathGap {
                session_id: session.session_id.clone(),
                expected_open_epoch: session.start_epoch + bars[index].len() as i64 * 60,
                first_later_observed_epoch: None,
                retained_prefix_bars: bars[index].len(),
                state: "SOURCE_PATH_INCOMPLETE".into(),
            });
        }
    }
    let retained = bars.iter().map(Vec::len).sum();
    Ok((
        bars,
        AccessAudit {
            source_prefix_rows_scanned: DISCOVERY_PREFIX_ROWS,
            source_prefix_sha256: prefix_hash,
            d_a_sessions_decoded: sessions.len(),
            d_a_ohlc_observations_decoded: selected,
            d_a_retained_causal_bars: retained,
            d_a_path_gap_sessions: gaps.len(),
            d_a_path_gaps: gaps,
            d_a_outcome_registry_applications: 0,
            d_b_session_ids_decoded_for_outcomes: 0,
            d_b_ohlc_values_decoded: 0,
            d_b_outcome_registry_applications: 0,
            d_b_derived_outcomes_inspected: 0,
            d_b_formal_scores: 0,
            d_c_membership_rows_decoded: 0,
            d_c_observations_read: 0,
            d_c_outcomes_computed: 0,
            next_source_row_requested: false,
        },
    ))
}

fn trim_cr(bytes: &[u8]) -> &[u8] {
    bytes.strip_suffix(b"\r").unwrap_or(bytes)
}

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    if needle.is_empty() {
        return true;
    }
    let mut offset = 0;
    while let Some(found) = memchr(needle[0], &haystack[offset..]) {
        let start = offset + found;
        if haystack[start..].starts_with(needle) {
            return true;
        }
        offset = start + 1;
    }
    false
}

fn parse_i64(raw: &[u8]) -> Result<i64, Box<dyn std::error::Error>> {
    Ok(std::str::from_utf8(raw)?.parse()?)
}

fn parse_f64(raw: &[u8]) -> Result<f64, Box<dyn std::error::Error>> {
    Ok(std::str::from_utf8(raw)?.parse()?)
}

fn sha256(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

pub fn raw_path() -> PathBuf {
    PathBuf::from("D:/obs-open-01/qualification/universe-v1/raw/OBS_OPEN_01_source_bars.tsv")
}

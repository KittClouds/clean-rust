use crate::authority::{BoundAuthority, map, sha256};
use hashbrown::HashMap;
use memchr::{memchr, memchr_iter};
use obs_open_03a::AtlasSession;
use obs_open_03bp::algebra::{normalize, raw_snapshot};
use obs_open_03bp2::model::{RANGE_COUNT, SessionRows};
use obs_open_disc02e::{DISCOVERY_PREFIX_HASH, DISCOVERY_PREFIX_ROWS};
use obs_open_meas02::{Bar, build_ranges};
use serde::Serialize;
use std::path::Path;

const REQUIRED_BARS: usize = 90;

#[derive(Debug, Clone, Serialize)]
pub struct IncompleteSession {
    pub session_id: String,
    pub civil_date: String,
    pub offset: i32,
    pub observed_required_bars: usize,
    pub first_missing_open_epoch: i64,
    pub state: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SupportReceipt {
    pub membership_sessions: usize,
    pub complete_formal_sessions: usize,
    pub incomplete_sessions: usize,
    pub unavailable_target_rows: usize,
    pub source_path_incomplete_rows: usize,
    pub offset_plus120_complete: usize,
    pub offset_plus180_complete: usize,
    pub chronological_start: String,
    pub chronological_end: String,
    pub support_state: String,
    pub timestamp_rows_scanned: usize,
    pub target_signs_read: usize,
    pub incomplete: Vec<IncompleteSession>,
}

#[derive(Debug)]
pub struct SupportScan {
    pub receipt: SupportReceipt,
    pub complete: Vec<bool>,
    pub prefix_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct TargetAccess {
    pub outcome_registry_applications: usize,
    pub target_values_computed: usize,
    pub target_values_read: usize,
    pub equality_false_rows: usize,
    pub ohlc_observations_decoded: usize,
}

pub fn support(authority: &BoundAuthority) -> Result<SupportScan, Box<dyn std::error::Error>> {
    let mmap = map(Path::new(&authority.raw_path))?;
    let prefix = discovery_prefix(&mmap)?;
    let mut owner = HashMap::with_capacity(authority.d_b_specs.len() * REQUIRED_BARS);
    for (s, spec) in authority.d_b_specs.iter().enumerate() {
        for i in 0..REQUIRED_BARS {
            owner.insert(spec.start_epoch + i as i64 * 60, (s, i));
        }
    }
    let mut seen = vec![[false; REQUIRED_BARS]; authority.d_b_specs.len()];
    scan_lines(prefix, |fields| {
        if fields.timeframe == b"M1"
            && let Some(&(s, i)) = owner.get(&fields.epoch)
        {
            seen[s][i] = true;
        }
        Ok(())
    })?;
    let mut complete = vec![false; authority.d_b_specs.len()];
    let mut incomplete = Vec::new();
    for (s, (spec, bits)) in authority.d_b_specs.iter().zip(&seen).enumerate() {
        if bits.iter().all(|x| *x) {
            complete[s] = true;
        } else {
            let first = bits.iter().position(|x| !*x).unwrap();
            incomplete.push(IncompleteSession {
                session_id: spec.session_id.clone(),
                civil_date: spec.civil_date.clone(),
                offset: spec.server_offset_minutes,
                observed_required_bars: bits.iter().filter(|x| **x).count(),
                first_missing_open_epoch: spec.start_epoch + first as i64 * 60,
                state: "SOURCE_PATH_INCOMPLETE".into(),
            });
        }
    }
    let n = complete.iter().filter(|x| **x).count();
    let plus120 = authority
        .d_b_specs
        .iter()
        .zip(&complete)
        .filter(|(s, c)| **c && s.server_offset_minutes == 120)
        .count();
    let plus180 = authority
        .d_b_specs
        .iter()
        .zip(&complete)
        .filter(|(s, c)| **c && s.server_offset_minutes == 180)
        .count();
    let state = if n >= 80 && plus120 >= 20 && plus180 >= 20 {
        "PASS"
    } else {
        "INSUFFICIENT_FORMAL_SUPPORT"
    };
    Ok(SupportScan {
        prefix_sha256: sha256(prefix),
        complete,
        receipt: SupportReceipt {
            membership_sessions: authority.d_b_specs.len(),
            complete_formal_sessions: n,
            incomplete_sessions: incomplete.len(),
            unavailable_target_rows: incomplete.len() * RANGE_COUNT,
            source_path_incomplete_rows: incomplete.len() * RANGE_COUNT,
            offset_plus120_complete: plus120,
            offset_plus180_complete: plus180,
            chronological_start: authority.d_b_specs.first().unwrap().civil_date.clone(),
            chronological_end: authority.d_b_specs.last().unwrap().civil_date.clone(),
            support_state: state.into(),
            timestamp_rows_scanned: DISCOVERY_PREFIX_ROWS,
            target_signs_read: 0,
            incomplete,
        },
    })
}

pub fn open_targets(
    authority: &BoundAuthority,
    support: &SupportScan,
) -> Result<(Vec<SessionRows>, TargetAccess), Box<dyn std::error::Error>> {
    if support.receipt.support_state != "PASS" {
        return Err("INSUFFICIENT_FORMAL_SUPPORT".into());
    }
    let mmap = map(Path::new(&authority.raw_path))?;
    let prefix = discovery_prefix(&mmap)?;
    if sha256(prefix) != support.prefix_sha256 {
        return Err("SUPPORT_TARGET_SOURCE_DRIFT".into());
    }
    let mut owner =
        HashMap::with_capacity(support.receipt.complete_formal_sessions * REQUIRED_BARS);
    for (s, (spec, complete)) in authority
        .d_b_specs
        .iter()
        .zip(&support.complete)
        .enumerate()
    {
        if *complete {
            for i in 0..REQUIRED_BARS {
                owner.insert(spec.start_epoch + i as i64 * 60, (s, i));
            }
        }
    }
    let mut bars = (0..authority.d_b_specs.len())
        .map(|_| Vec::new())
        .collect::<Vec<Vec<Bar>>>();
    scan_lines(prefix, |f| {
        if f.timeframe != b"M1" {
            return Ok(());
        }
        let Some(&(s, i)) = owner.get(&f.epoch) else {
            return Ok(());
        };
        if bars[s].len() != i {
            return Err("D_B_BAR_ORDER_OR_DUPLICATE");
        }
        bars[s].push(Bar {
            source_row_id: format!("RAW125B:M1:{}", f.epoch),
            open_time: f.epoch,
            close_time: f.epoch + 60,
            open: parse_f64(f.open)?,
            high: parse_f64(f.high)?,
            low: parse_f64(f.low)?,
            close: parse_f64(f.close)?,
            coverage: "COMPLETE".into(),
        });
        Ok(())
    })?;
    let mut rows = Vec::with_capacity(support.receipt.complete_formal_sessions);
    let mut equality = 0;
    for (selected, (spec, session_bars)) in authority.d_b_specs.iter().zip(bars).enumerate() {
        if !support.complete[selected] {
            continue;
        }
        if session_bars.len() != REQUIRED_BARS {
            return Err("D_B_REQUIRED_BAR_COUNT_DRIFT".into());
        }
        let ranges = build_ranges(spec, &session_bars)?;
        let atlas = AtlasSession {
            spec: spec.clone(),
            month: spec.civil_date[..7].into(),
            bars: session_bars,
            ranges,
            candidates: Vec::new(),
            path_complete: false,
        };
        let mut targets = [0.0; RANGE_COUNT];
        let mut raw = [[0.0; 5]; RANGE_COUNT];
        let mut z = [[0.0; 4]; RANGE_COUNT];
        for k in 1..=RANGE_COUNT {
            let r = raw_snapshot(&atlas, k)?;
            let n = normalize(r)?;
            raw[k - 1] = [
                r.width,
                r.open_minus_mid,
                r.high_minus_mid,
                r.low_minus_mid,
                r.close_minus_mid,
            ];
            z[k - 1] = [n.z_open, n.z_high, n.z_low, n.z_close];
            let terminal = atlas.bars[k + 59].close - atlas.ranges[k - 1].midpoint;
            if terminal == 0.0 {
                equality += 1;
            }
            targets[k - 1] = f64::from(terminal > 0.0);
        }
        rows.push(SessionRows {
            session_index: rows.len(),
            session_id: spec.session_id.clone(),
            civil_date: spec.civil_date.clone(),
            month: spec.civil_date[..7].into(),
            offset: spec.server_offset_minutes,
            targets,
            raw,
            z,
        });
    }
    let n = rows.len();
    Ok((
        rows,
        TargetAccess {
            outcome_registry_applications: n * RANGE_COUNT,
            target_values_computed: n * RANGE_COUNT,
            target_values_read: n * RANGE_COUNT,
            equality_false_rows: equality,
            ohlc_observations_decoded: n * REQUIRED_BARS,
        },
    ))
}

struct Fields<'a> {
    timeframe: &'a [u8],
    epoch: i64,
    open: &'a [u8],
    high: &'a [u8],
    low: &'a [u8],
    close: &'a [u8],
}
fn scan_lines<'a>(
    prefix: &'a [u8],
    mut visit: impl FnMut(Fields<'a>) -> Result<(), &'static str>,
) -> Result<(), Box<dyn std::error::Error>> {
    let header_end = memchr(b'\n', prefix).ok_or("SOURCE_HEADER")?;
    let mut start = header_end + 1;
    let mut rows = 0;
    while start < prefix.len() {
        let remaining = &prefix[start..];
        let end_rel = memchr(b'\n', remaining).unwrap_or(remaining.len());
        let end = start + end_rel;
        let line = prefix[start..end]
            .strip_suffix(b"\r")
            .unwrap_or(&prefix[start..end]);
        start = end + usize::from(end_rel < remaining.len());
        if line.is_empty() {
            continue;
        }
        rows += 1;
        let mut f = line.split(|b| *b == b'\t');
        let _schema = f.next().ok_or("SCHEMA")?;
        let _day = f.next().ok_or("DAY")?;
        let timeframe = f.next().ok_or("TF")?;
        let epoch = parse_i64(f.next().ok_or("EPOCH")?)?;
        let _time = f.next().ok_or("TIME")?;
        let open = f.next().ok_or("OPEN")?;
        let high = f.next().ok_or("HIGH")?;
        let low = f.next().ok_or("LOW")?;
        let close = f.next().ok_or("CLOSE")?;
        visit(Fields {
            timeframe,
            epoch,
            open,
            high,
            low,
            close,
        })?;
    }
    if rows != DISCOVERY_PREFIX_ROWS {
        return Err(format!("DISCOVERY_PREFIX_ROW_DRIFT:{rows}").into());
    }
    Ok(())
}
fn discovery_prefix(bytes: &[u8]) -> Result<&[u8], Box<dyn std::error::Error>> {
    let required = DISCOVERY_PREFIX_ROWS + 1;
    let end = memchr_iter(b'\n', bytes)
        .nth(required - 1)
        .ok_or("DISCOVERY_PREFIX_TRUNCATED")?
        + 1;
    let prefix = &bytes[..end];
    if sha256(prefix) != DISCOVERY_PREFIX_HASH {
        return Err("DISCOVERY_PREFIX_HASH_DRIFT".into());
    }
    Ok(prefix)
}
fn parse_i64(x: &[u8]) -> Result<i64, Box<dyn std::error::Error>> {
    Ok(std::str::from_utf8(x)?.parse()?)
}
fn parse_f64(x: &[u8]) -> Result<f64, &'static str> {
    std::str::from_utf8(x)
        .map_err(|_| "UTF8")?
        .parse()
        .map_err(|_| "F64")
}

use hashbrown::HashMap;
use memchr::memchr_iter;
use memmap2::Mmap;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::path::Path;

pub const INST01_ROOT: &str = "5930c7d4f5b2de4549bfedacbd2c3b9df7da78f68c7d765b9c0669d08a17490f";
pub const SRC01_ROOT: &str = "32e1207717afc29533e8a8fb0a7e0f329f9e092f58f3fb3c58d5661c5b7dd0fa";
pub const UNIVERSE_ROOT: &str = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235";
pub const V210_SOURCE_HASH: &str =
    "a133ef773531a1599d1cef1e5124fcacc24b037f84cca777205c67ee0a785c61";
pub const V210_EX5_HASH: &str = "a9e25979dc85a760b15499a13552216f19646e43274c93c4d032adc671f415dd";
pub const RAW_BAR_HASH: &str = "125b768ad87ba578c5498deffe50462909a6a1be422953a0f7488f036aac9d5b";
pub const OBSERVER_INSTANCE: &str = "CAUSAL_RANGE_EXTREME_M1_V1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Bar {
    pub source_row_id: String,
    pub open_time: i64,
    pub close_time: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub coverage: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionSpec {
    pub session_id: String,
    pub civil_date: String,
    pub server_offset_minutes: i32,
    pub start_epoch: i64,
    pub terminal_epoch: i64,
    pub partition: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RangeObject {
    pub range_object_id: String,
    pub session_id: String,
    pub k: u8,
    pub configured_start: i64,
    pub configured_end: i64,
    pub instrument_inclusive_end_bar: i64,
    pub actual_start_bar: i64,
    pub actual_end_bar: i64,
    pub freeze_commit_time: i64,
    pub high: f64,
    pub low: f64,
    pub midpoint: f64,
    pub width: f64,
    pub source_coverage: String,
    pub instrument_authority: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Candidate {
    pub candidate_id: String,
    pub session_id: String,
    pub side: String,
    pub sequence_number: u32,
    pub birth_bar: i64,
    pub birth_knowledge_time: i64,
    pub extreme_price: f64,
    pub superseded: bool,
    pub superseded_at: Option<i64>,
    pub superseded_by_candidate_id: Option<String>,
    pub terminal_survivor: bool,
    pub terminal_label_known_at: Option<i64>,
    pub terminal_label_knowledge_order: Option<String>,
    pub coverage_state: String,
    pub source_authority: String,
    #[serde(skip)]
    pub birth_index: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TapeRow {
    pub session_id: String,
    pub source_row_id: String,
    pub bar_open: i64,
    pub bar_close: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub coverage: String,
    pub active_upper_candidate_id: String,
    pub active_lower_candidate_id: String,
    pub new_upper_candidate: bool,
    pub new_lower_candidate: bool,
    pub upper_candidate_age_bars: usize,
    pub lower_candidate_age_bars: usize,
    pub committed_upper_extreme: f64,
    pub committed_lower_extreme: f64,
    pub grammar_state: Option<i32>,
    pub grammar_event: Option<i32>,
    pub grammar_availability: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RangeRelation {
    pub candidate_id: String,
    pub range_object_id: String,
    pub candidate_birth_vs_freeze: String,
    pub relation_available_at: i64,
    pub extreme_minus_range_high: f64,
    pub extreme_minus_range_low: f64,
    pub extreme_minus_mid: f64,
    pub normalized_mid_coordinate: Option<f64>,
    pub normalized_upper_extension: Option<f64>,
    pub normalized_lower_extension: Option<f64>,
    pub range_location_at_candidate_birth: String,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PathPoint {
    pub candidate_id: String,
    pub source_row_id: String,
    pub bar_open: i64,
    pub bar_close: i64,
    pub signed_close_minus_candidate: f64,
    pub signed_low_minus_candidate: f64,
    pub signed_high_minus_candidate: f64,
    pub coverage: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RangePathPoint {
    pub range_object_id: String,
    pub source_row_id: String,
    pub bar_open: i64,
    pub bar_close: i64,
    pub raw_close: f64,
    pub raw_high: f64,
    pub raw_low: f64,
    pub z_close: Option<f64>,
    pub z_high: Option<f64>,
    pub z_low: Option<f64>,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrammarPoint {
    pub bar_close: i64,
    pub state: i32,
    pub event: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrammarRelation {
    pub candidate_id: String,
    pub grammar_state_at_birth: Option<i32>,
    pub most_recent_grammar_event: Option<i32>,
    pub next_observed_grammar_event: Option<i32>,
    pub next_observed_grammar_event_time: Option<i64>,
    pub birth_vs_range_freeze: String,
    pub birth_location: String,
    pub join_status: String,
}

#[derive(Debug)]
pub enum BuildError {
    Io(String),
    Parse(String),
    CoverageGap {
        expected: i64,
        observed: Option<i64>,
    },
    ForbiddenPartition(String),
}

impl std::fmt::Display for BuildError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(x) | Self::Parse(x) | Self::ForbiddenPartition(x) => f.write_str(x),
            Self::CoverageGap { expected, observed } => {
                write!(
                    f,
                    "NOT_EVALUABLE_SENTINEL_PATH_GAP expected={expected} observed={observed:?}"
                )
            }
        }
    }
}

impl std::error::Error for BuildError {}

pub fn sha256_file(path: &Path) -> Result<String, BuildError> {
    let file = File::open(path).map_err(|e| BuildError::Io(format!("{}: {e}", path.display())))?;
    let mmap = unsafe { Mmap::map(&file) }.map_err(|e| BuildError::Io(e.to_string()))?;
    let mut h = Sha256::new();
    h.update(&mmap);
    Ok(format!("{:x}", h.finalize()))
}

fn parse_f64(raw: &[u8], name: &str) -> Result<f64, BuildError> {
    std::str::from_utf8(raw)
        .map_err(|e| BuildError::Parse(e.to_string()))?
        .parse::<f64>()
        .map_err(|e| BuildError::Parse(format!("{name}: {e}")))
}

fn parse_i64(raw: &[u8], name: &str) -> Result<i64, BuildError> {
    std::str::from_utf8(raw)
        .map_err(|e| BuildError::Parse(e.to_string()))?
        .parse::<i64>()
        .map_err(|e| BuildError::Parse(format!("{name}: {e}")))
}

fn tabs(line: &[u8]) -> Vec<&[u8]> {
    let mut out = Vec::with_capacity(12);
    let mut start = 0;
    for i in memchr_iter(b'\t', line) {
        out.push(&line[start..i]);
        start = i + 1;
    }
    out.push(&line[start..]);
    out
}

pub fn load_m1_window(path: &Path, start: i64, end: i64) -> Result<Vec<Bar>, BuildError> {
    let file = File::open(path).map_err(|e| BuildError::Io(format!("{}: {e}", path.display())))?;
    let mmap = unsafe { Mmap::map(&file) }.map_err(|e| BuildError::Io(e.to_string()))?;
    let mut out = Vec::with_capacity(((end - start) / 60) as usize);
    let mut line_start = 0usize;
    let mut data_row = 0u64;
    for line_end in memchr_iter(b'\n', &mmap) {
        let mut line = &mmap[line_start..line_end];
        line_start = line_end + 1;
        if line.ends_with(b"\r") {
            line = &line[..line.len() - 1];
        }
        if data_row == 0 {
            data_row += 1;
            continue;
        }
        data_row += 1;
        let c = tabs(line);
        if c.len() < 9 || c[2] != b"M1" {
            continue;
        }
        let epoch = parse_i64(c[3], "server_epoch")?;
        if epoch < start || epoch >= end {
            continue;
        }
        out.push(Bar {
            source_row_id: format!("RAW125B:M1:{epoch}"),
            open_time: epoch,
            close_time: epoch + 60,
            open: parse_f64(c[5], "open")?,
            high: parse_f64(c[6], "high")?,
            low: parse_f64(c[7], "low")?,
            close: parse_f64(c[8], "close")?,
            coverage: "COMPLETE".into(),
        });
    }
    out.sort_unstable_by_key(|b| b.open_time);
    let expected = ((end - start) / 60) as usize;
    if out.len() != expected {
        let mut wanted = start;
        for bar in &out {
            if bar.open_time != wanted {
                return Err(BuildError::CoverageGap {
                    expected: wanted,
                    observed: Some(bar.open_time),
                });
            }
            wanted += 60;
        }
        return Err(BuildError::CoverageGap {
            expected: wanted,
            observed: None,
        });
    }
    for (i, bar) in out.iter().enumerate() {
        let wanted = start + i as i64 * 60;
        if bar.open_time != wanted {
            return Err(BuildError::CoverageGap {
                expected: wanted,
                observed: Some(bar.open_time),
            });
        }
    }
    Ok(out)
}

fn days_from_civil(y: i32, m: u32, d: u32) -> i64 {
    let y = y - i32::from(m <= 2);
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = m as i32 + if m > 2 { -3 } else { 9 };
    let doy = (153 * mp + 2) / 5 + d as i32 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    (era * 146097 + doe - 719468) as i64
}

fn weekday_sunday_zero(y: i32, m: u32, d: u32) -> u32 {
    ((days_from_civil(y, m, d) + 4).rem_euclid(7)) as u32
}

fn nth_sunday(y: i32, m: u32, nth: u32) -> u32 {
    let first = weekday_sunday_zero(y, m, 1);
    1 + ((7 - first) % 7) + 7 * (nth - 1)
}

pub fn ny_utc_offset_minutes(civil_date: &str) -> Result<i32, BuildError> {
    let mut it = civil_date.split('-');
    let y = it
        .next()
        .ok_or_else(|| BuildError::Parse(civil_date.into()))?
        .parse::<i32>()
        .map_err(|e| BuildError::Parse(e.to_string()))?;
    let m = it
        .next()
        .ok_or_else(|| BuildError::Parse(civil_date.into()))?
        .parse::<u32>()
        .map_err(|e| BuildError::Parse(e.to_string()))?;
    let d = it
        .next()
        .ok_or_else(|| BuildError::Parse(civil_date.into()))?
        .parse::<u32>()
        .map_err(|e| BuildError::Parse(e.to_string()))?;
    let dst = (m > 3 && m < 11)
        || (m == 3 && d >= nth_sunday(y, 3, 2))
        || (m == 11 && d < nth_sunday(y, 11, 1));
    Ok(if dst { -240 } else { -300 })
}

pub fn session_spec(
    session_id: &str,
    civil_date: &str,
    server_offset: i32,
    partition: &str,
) -> Result<SessionSpec, BuildError> {
    if partition != "DISCOVERY" {
        return Err(BuildError::ForbiddenPartition(format!(
            "confirmation firewall: {session_id} is {partition}"
        )));
    }
    let mut it = civil_date.split('-');
    let y = it
        .next()
        .unwrap()
        .parse::<i32>()
        .map_err(|e| BuildError::Parse(e.to_string()))?;
    let m = it
        .next()
        .unwrap()
        .parse::<u32>()
        .map_err(|e| BuildError::Parse(e.to_string()))?;
    let d = it
        .next()
        .unwrap()
        .parse::<u32>()
        .map_err(|e| BuildError::Parse(e.to_string()))?;
    let local_naive = days_from_civil(y, m, d) * 86400 + 9 * 3600 + 30 * 60;
    let utc = local_naive - i64::from(ny_utc_offset_minutes(civil_date)?) * 60;
    let start = utc + i64::from(server_offset) * 60;
    Ok(SessionSpec {
        session_id: session_id.into(),
        civil_date: civil_date.into(),
        server_offset_minutes: server_offset,
        start_epoch: start,
        terminal_epoch: start + 390 * 60,
        partition: partition.into(),
    })
}

pub fn build_ranges(spec: &SessionSpec, bars: &[Bar]) -> Result<Vec<RangeObject>, BuildError> {
    if bars.len() < 30 {
        return Err(BuildError::CoverageGap {
            expected: spec.start_epoch + bars.len() as i64 * 60,
            observed: None,
        });
    }
    let mut out = Vec::with_capacity(30);
    for k in 1usize..=30 {
        let slice = &bars[..k];
        let high = slice
            .iter()
            .map(|b| b.high)
            .fold(f64::NEG_INFINITY, f64::max);
        let low = slice.iter().map(|b| b.low).fold(f64::INFINITY, f64::min);
        let end = spec.start_epoch + k as i64 * 60;
        out.push(RangeObject {
            range_object_id: format!("{}:R{k:02}", spec.session_id),
            session_id: spec.session_id.clone(),
            k: k as u8,
            configured_start: spec.start_epoch,
            configured_end: end,
            instrument_inclusive_end_bar: end - 60,
            actual_start_bar: spec.start_epoch,
            actual_end_bar: end - 60,
            freeze_commit_time: end,
            high,
            low,
            midpoint: (high + low) / 2.0,
            width: high - low,
            source_coverage: "COMPLETE".into(),
            instrument_authority: INST01_ROOT.into(),
        });
    }
    Ok(out)
}

fn new_candidate(
    spec: &SessionSpec,
    side: &str,
    seq: u32,
    bar: &Bar,
    price: f64,
    index: usize,
) -> Candidate {
    Candidate {
        candidate_id: format!(
            "{}:{}:{seq:04}",
            spec.session_id,
            side.chars().next().unwrap()
        ),
        session_id: spec.session_id.clone(),
        side: side.into(),
        sequence_number: seq,
        birth_bar: bar.open_time,
        birth_knowledge_time: bar.close_time,
        extreme_price: price,
        superseded: false,
        superseded_at: None,
        superseded_by_candidate_id: None,
        terminal_survivor: false,
        terminal_label_known_at: None,
        terminal_label_knowledge_order: None,
        coverage_state: "COMPLETE".into(),
        source_authority: RAW_BAR_HASH.into(),
        birth_index: index,
    }
}

pub fn build_candidates_and_tape(
    spec: &SessionSpec,
    bars: &[Bar],
) -> Result<(Vec<Candidate>, Vec<TapeRow>), BuildError> {
    if bars.is_empty() {
        return Err(BuildError::CoverageGap {
            expected: spec.start_epoch,
            observed: None,
        });
    }
    let mut candidates = Vec::with_capacity(128);
    candidates.push(new_candidate(spec, "UPPER", 1, &bars[0], bars[0].high, 0));
    let mut upper = 0usize;
    candidates.push(new_candidate(spec, "LOWER", 1, &bars[0], bars[0].low, 0));
    let mut lower = 1usize;
    let mut tape = Vec::with_capacity(bars.len());
    for (i, bar) in bars.iter().enumerate() {
        let mut new_up = i == 0;
        let mut new_down = i == 0;
        if i > 0 && bar.high > candidates[upper].extreme_price {
            let seq = candidates[upper].sequence_number + 1;
            let next = new_candidate(spec, "UPPER", seq, bar, bar.high, i);
            let next_id = next.candidate_id.clone();
            candidates[upper].superseded = true;
            candidates[upper].superseded_at = Some(bar.close_time);
            candidates[upper].superseded_by_candidate_id = Some(next_id);
            candidates.push(next);
            upper = candidates.len() - 1;
            new_up = true;
        }
        if i > 0 && bar.low < candidates[lower].extreme_price {
            let seq = candidates[lower].sequence_number + 1;
            let next = new_candidate(spec, "LOWER", seq, bar, bar.low, i);
            let next_id = next.candidate_id.clone();
            candidates[lower].superseded = true;
            candidates[lower].superseded_at = Some(bar.close_time);
            candidates[lower].superseded_by_candidate_id = Some(next_id);
            candidates.push(next);
            lower = candidates.len() - 1;
            new_down = true;
        }
        tape.push(TapeRow {
            session_id: spec.session_id.clone(),
            source_row_id: bar.source_row_id.clone(),
            bar_open: bar.open_time,
            bar_close: bar.close_time,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
            coverage: bar.coverage.clone(),
            active_upper_candidate_id: candidates[upper].candidate_id.clone(),
            active_lower_candidate_id: candidates[lower].candidate_id.clone(),
            new_upper_candidate: new_up,
            new_lower_candidate: new_down,
            upper_candidate_age_bars: i - candidates[upper].birth_index,
            lower_candidate_age_bars: i - candidates[lower].birth_index,
            committed_upper_extreme: candidates[upper].extreme_price,
            committed_lower_extreme: candidates[lower].extreme_price,
            grammar_state: None,
            grammar_event: None,
            grammar_availability: "NOT_EVALUABLE_OBSERVER_STREAM_ABSENT".into(),
        });
    }
    candidates[upper].terminal_survivor = true;
    candidates[upper].terminal_label_known_at = Some(spec.terminal_epoch);
    candidates[upper].terminal_label_knowledge_order =
        Some("AFTER_FINAL_BAR_COMMIT_AT_SESSION_BOUNDARY".into());
    candidates[lower].terminal_survivor = true;
    candidates[lower].terminal_label_known_at = Some(spec.terminal_epoch);
    candidates[lower].terminal_label_knowledge_order =
        Some("AFTER_FINAL_BAR_COMMIT_AT_SESSION_BOUNDARY".into());
    Ok((candidates, tape))
}

pub fn build_range_relations(
    candidates: &[Candidate],
    ranges: &[RangeObject],
) -> Vec<RangeRelation> {
    let mut out = Vec::with_capacity(candidates.len() * ranges.len());
    for c in candidates {
        for r in ranges {
            let half = r.width / 2.0;
            let status = if half > 0.0 {
                "AVAILABLE"
            } else {
                "NOT_EVALUABLE_DEGENERATE_RANGE"
            };
            out.push(RangeRelation {
                candidate_id: c.candidate_id.clone(),
                range_object_id: r.range_object_id.clone(),
                candidate_birth_vs_freeze: if c.birth_knowledge_time < r.freeze_commit_time {
                    "BEFORE_FREEZE"
                } else if c.birth_knowledge_time == r.freeze_commit_time {
                    "AT_FREEZE"
                } else {
                    "AFTER_FREEZE"
                }
                .into(),
                relation_available_at: c.birth_knowledge_time.max(r.freeze_commit_time),
                extreme_minus_range_high: c.extreme_price - r.high,
                extreme_minus_range_low: c.extreme_price - r.low,
                extreme_minus_mid: c.extreme_price - r.midpoint,
                normalized_mid_coordinate: (half > 0.0)
                    .then_some((c.extreme_price - r.midpoint) / half),
                normalized_upper_extension: (half > 0.0)
                    .then_some(((c.extreme_price - r.high).max(0.0)) / half),
                normalized_lower_extension: (half > 0.0)
                    .then_some(((r.low - c.extreme_price).max(0.0)) / half),
                range_location_at_candidate_birth: if c.extreme_price > r.high {
                    "ABOVE"
                } else if c.extreme_price < r.low {
                    "BELOW"
                } else {
                    "IN_ZONE"
                }
                .into(),
                status: status.into(),
            });
        }
    }
    out
}

pub fn candidate_path_view(candidate: &Candidate, bars: &[Bar]) -> Vec<PathPoint> {
    bars[candidate.birth_index..]
        .iter()
        .map(|b| PathPoint {
            candidate_id: candidate.candidate_id.clone(),
            source_row_id: b.source_row_id.clone(),
            bar_open: b.open_time,
            bar_close: b.close_time,
            signed_close_minus_candidate: b.close - candidate.extreme_price,
            signed_low_minus_candidate: b.low - candidate.extreme_price,
            signed_high_minus_candidate: b.high - candidate.extreme_price,
            coverage: b.coverage.clone(),
        })
        .collect()
}

pub fn range_path_view(range: &RangeObject, bars: &[Bar]) -> Vec<RangePathPoint> {
    let half = range.width / 2.0;
    bars.iter()
        .filter(|b| b.close_time >= range.freeze_commit_time)
        .map(|b| RangePathPoint {
            range_object_id: range.range_object_id.clone(),
            source_row_id: b.source_row_id.clone(),
            bar_open: b.open_time,
            bar_close: b.close_time,
            raw_close: b.close,
            raw_high: b.high,
            raw_low: b.low,
            z_close: (half > 0.0).then_some((b.close - range.midpoint) / half),
            z_high: (half > 0.0).then_some((b.high - range.midpoint) / half),
            z_low: (half > 0.0).then_some((b.low - range.midpoint) / half),
            status: if half > 0.0 {
                "AVAILABLE"
            } else {
                "NOT_EVALUABLE_DEGENERATE_RANGE"
            }
            .into(),
        })
        .collect()
}

pub fn join_grammar(
    candidate: &Candidate,
    range: &RangeObject,
    points: &[GrammarPoint],
) -> GrammarRelation {
    let mut state = None;
    let mut previous_event = None;
    let mut next_event = None;
    let mut next_event_time = None;
    for p in points {
        if p.bar_close <= candidate.birth_knowledge_time {
            state = Some(p.state);
            if p.event.is_some() {
                previous_event = p.event;
            }
        } else if next_event.is_none() && p.event.is_some() {
            next_event = p.event;
            next_event_time = Some(p.bar_close);
        }
    }
    GrammarRelation {
        candidate_id: candidate.candidate_id.clone(),
        grammar_state_at_birth: state,
        most_recent_grammar_event: previous_event,
        next_observed_grammar_event: next_event,
        next_observed_grammar_event_time: next_event_time,
        birth_vs_range_freeze: if candidate.birth_knowledge_time < range.freeze_commit_time {
            "BEFORE_FREEZE"
        } else {
            "AT_OR_AFTER_FREEZE"
        }
        .into(),
        birth_location: if candidate.extreme_price > range.high {
            "ABOVE"
        } else if candidate.extreme_price < range.low {
            "BELOW"
        } else {
            "IN_ZONE"
        }
        .into(),
        join_status: if state.is_some() {
            "AVAILABLE"
        } else {
            "NOT_EVALUABLE_OBSERVER_STREAM_ABSENT"
        }
        .into(),
    }
}

pub fn parse_partition(path: &Path, wanted: &str) -> Result<SessionSpec, BuildError> {
    let text = std::fs::read_to_string(path).map_err(|e| BuildError::Io(e.to_string()))?;
    for line in text.lines().skip(1) {
        let c: Vec<&str> = line.split('\t').collect();
        if c.len() >= 5 && c[0] == wanted {
            return session_spec(
                c[0],
                c[1],
                c[3].parse()
                    .map_err(|e| BuildError::Parse(format!("offset: {e}")))?,
                c[2],
            );
        }
    }
    Err(BuildError::Parse(format!(
        "session {wanted} absent from partition manifest"
    )))
}

pub fn candidate_index(candidates: &[Candidate]) -> HashMap<&str, usize> {
    candidates
        .iter()
        .enumerate()
        .map(|(i, c)| (c.candidate_id.as_str(), i))
        .collect()
}

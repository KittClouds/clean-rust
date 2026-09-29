//! `MemoryTimeV1`: the six-clock envelope of `MemoryRecordedV2` (amendment v4 §1).
//!
//! The JSON form of `phoenix-memory-contract::TemporalEnvelopeRecordV1`, validated with the
//! same rules as its `validate_envelope_metadata`. The system clock is not in the payload: the
//! Library derives it from the journal.

use serde_json::{Map, Value};

/// A clock whose value is not known. Never the same as [`OPEN`].
pub const UNKNOWN: &str = "unknown";
/// An unbounded interval end.
pub const OPEN: &str = "open";

/// `TemporalPrecisionV1`, in its raw order (raw value = index + 1).
pub const PRECISIONS: [&str; 10] = [
    "unknown", "instant", "minute", "hour", "day", "month", "year", "interval", "relative",
    "ordinal",
];

/// Envelope flags a client may set; sorted, no duplicates.
pub const FLAGS: [&str; 2] = ["normalized", "uncertain"];

/// The envelope's exact key set, sorted.
pub const KEYS: [&str; 10] = [
    "asserted_at",
    "confidence",
    "flags",
    "observed_at",
    "occurred",
    "original_text",
    "precision",
    "source_time",
    "timezone_offset_minutes",
    "valid",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Clock {
    Known(i64),
    Unknown,
    Open,
}

/// A validated envelope, reduced to what retrieval needs.
#[derive(Clone, Debug, PartialEq)]
pub struct MemoryTime {
    pub source_time: Clock,
    pub asserted_at: Clock,
    /// `None` when the occurrence time is unknown.
    pub occurred: Option<(i64, i64)>,
    pub observed_at: i64,
    pub valid: (Clock, Clock),
    pub precision: &'static str,
    pub timezone_offset_minutes: Option<i32>,
    pub original_text: String,
    pub confidence: f64,
    pub flags: Vec<&'static str>,
}

fn civil_days(y: i64, m: i64, d: i64) -> i64 {
    // Howard Hinnant's days_from_civil.
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// Parses an RFC 3339 UTC timestamp (`Z` or `+00:00`, optional fraction) to epoch milliseconds.
pub fn parse_utc(text: &str) -> Option<i64> {
    let b = text.as_bytes();
    let digits = |r: std::ops::Range<usize>| -> Option<i64> {
        let s = text.get(r)?;
        s.bytes()
            .all(|c| c.is_ascii_digit())
            .then(|| s.parse().ok())?
    };
    if b.len() < 20
        || b[4] != b'-'
        || b[7] != b'-'
        || b[10] != b'T'
        || b[13] != b':'
        || b[16] != b':'
    {
        return None;
    }
    let (y, mo, d) = (digits(0..4)?, digits(5..7)?, digits(8..10)?);
    let (h, mi, s) = (digits(11..13)?, digits(14..16)?, digits(17..19)?);
    let mut rest = &text[19..];
    let mut millis = 0;
    if let Some(fraction) = rest.strip_prefix('.') {
        let n = fraction.bytes().take_while(u8::is_ascii_digit).count();
        if n == 0 || n > 9 {
            return None;
        }
        millis = format!("{:0<3}", &fraction[..n.min(3)])
            .parse::<i64>()
            .ok()?;
        rest = &fraction[n..];
    }
    if rest != "Z" && rest != "+00:00" {
        return None;
    }
    let month_days = [
        31,
        if y % 4 == 0 && (y % 100 != 0 || y % 400 == 0) {
            29
        } else {
            28
        },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    if !(1..=12).contains(&mo)
        || d < 1
        || d > month_days[(mo - 1) as usize]
        || h > 23
        || mi > 59
        || s > 59
    {
        return None;
    }
    Some(((civil_days(y, mo, d) * 24 + h) * 60 + mi) * 60_000 + s * 1000 + millis)
}

fn clock(value: &Value, field: &str, open_allowed: bool) -> Result<Clock, String> {
    match value.as_str() {
        Some(UNKNOWN) => Ok(Clock::Unknown),
        Some(OPEN) if open_allowed => Ok(Clock::Open),
        Some(text) => parse_utc(text).map(Clock::Known).ok_or_else(|| {
            format!(
                "{field}: not an RFC 3339 UTC time, \"unknown\"{}",
                if open_allowed { " or \"open\"" } else { "" }
            )
        }),
        None => Err(format!("{field}: must be a string")),
    }
}

fn interval(value: &Value, field: &str) -> Result<(Clock, Clock), String> {
    let object = value
        .as_object()
        .ok_or_else(|| format!("{field}: must be an object"))?;
    if object.len() != 2 || !object.contains_key("from") || !object.contains_key("to") {
        return Err(format!("{field}: exactly the keys from and to"));
    }
    Ok((
        clock(&object["from"], &format!("{field}.from"), true)?,
        clock(&object["to"], &format!("{field}.to"), true)?,
    ))
}

/// Validates an envelope. `event_utc` is the carrying event's `utc`; `observed_at` must equal it.
pub fn validate(value: &Value, event_utc: Option<&str>) -> Result<MemoryTime, String> {
    let object = value.as_object().ok_or("time: must be an object")?;
    let mut keys: Vec<&str> = object.keys().map(String::as_str).collect();
    keys.sort_unstable();
    if keys != KEYS {
        return Err(format!("time: keys must be exactly {KEYS:?}"));
    }
    let observed_at = match clock(&object["observed_at"], "observed_at", false)? {
        Clock::Known(ms) => ms,
        _ => return Err("observed_at: required".into()),
    };
    if let Some(utc) = event_utc {
        if parse_utc(utc) != Some(observed_at) {
            return Err("observed_at: must equal the event's utc".into());
        }
    }
    let source_time = clock(&object["source_time"], "source_time", false)?;
    let asserted_at = clock(&object["asserted_at"], "asserted_at", false)?;
    let occurred = if object["occurred"].as_str() == Some(UNKNOWN) {
        None
    } else {
        match interval(&object["occurred"], "occurred")? {
            (Clock::Known(from), Clock::Known(to)) if from <= to => Some((from, to)),
            (Clock::Known(_), Clock::Known(_)) => return Err("occurred: from after to".into()),
            _ => return Err("occurred: both ends known, or the whole value \"unknown\"".into()),
        }
    };
    let valid = interval(&object["valid"], "valid")?;
    if let (Clock::Known(from), Clock::Known(to)) = valid {
        if from > to {
            return Err("valid: from after to".into());
        }
    }
    let precision = object["precision"]
        .as_str()
        .and_then(|p| PRECISIONS.iter().find(|&&known| known == p).copied())
        .ok_or("precision: not a TemporalPrecisionV1 value")?;
    let timezone_offset_minutes = match &object["timezone_offset_minutes"] {
        Value::String(s) if s == UNKNOWN => None,
        Value::Number(n) => match n.as_i64() {
            Some(m) if (-1439..=1439).contains(&m) => Some(m as i32),
            _ => return Err("timezone_offset_minutes: outside -1439..=1439".into()),
        },
        _ => return Err("timezone_offset_minutes: integer or \"unknown\"".into()),
    };
    let original_text = object["original_text"]
        .as_str()
        .ok_or("original_text: must be a string")?
        .to_string();
    let confidence = object["confidence"]
        .as_f64()
        .filter(|c| c.is_finite() && (0.0..=1.0).contains(c))
        .ok_or("confidence: a finite number in [0, 1]")?;
    let raw_flags = object["flags"]
        .as_array()
        .ok_or("flags: must be an array")?;
    let mut flags = Vec::new();
    for flag in raw_flags {
        let name = flag
            .as_str()
            .and_then(|f| FLAGS.iter().find(|&&known| known == f).copied())
            .ok_or("flags: only normalized and uncertain")?;
        if flags.last().is_some_and(|&last: &&str| last >= name) {
            return Err("flags: sorted, without duplicates".into());
        }
        flags.push(name);
    }
    Ok(MemoryTime {
        source_time,
        asserted_at,
        occurred,
        observed_at,
        valid,
        precision,
        timezone_offset_minutes,
        original_text,
        confidence,
        flags,
    })
}

/// The v2 reading of a v1 `MemoryRecorded` record: only `observed_at` is known.
pub fn v1_view(observed_utc: &str, confidence: f64) -> Value {
    let mut object = Map::new();
    object.insert("asserted_at".into(), UNKNOWN.into());
    object.insert("confidence".into(), confidence.into());
    object.insert("flags".into(), Value::Array(Vec::new()));
    object.insert("observed_at".into(), observed_utc.into());
    object.insert("occurred".into(), UNKNOWN.into());
    object.insert("original_text".into(), "".into());
    object.insert("precision".into(), "unknown".into());
    object.insert("source_time".into(), UNKNOWN.into());
    object.insert("timezone_offset_minutes".into(), UNKNOWN.into());
    let mut valid = Map::new();
    valid.insert("from".into(), UNKNOWN.into());
    valid.insert("to".into(), OPEN.into());
    object.insert("valid".into(), Value::Object(valid));
    Value::Object(object)
}

//! UTC instants with Python `datetime` formatting and `fromisoformat` parsing.
//!
//! Every timestamp the Library writes was produced by Python `datetime.isoformat()`:
//! `2026-09-28T01:02:03.123456+00:00`, with the fraction omitted when microseconds are zero.
//! Main-journal envelopes replace `+00:00` with `Z`; memory envelopes keep `+00:00`.

use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;

use crate::error::{value_error, Result};

/// Microseconds since 1970-01-01T00:00:00Z.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Timestamp(pub i64);

impl Timestamp {
    pub fn plus_seconds(self, seconds: i64) -> Timestamp {
        Timestamp(self.0 + seconds * 1_000_000)
    }

    /// Python `datetime.isoformat()` of an aware UTC datetime.
    pub fn isoformat(self) -> String {
        let micros = self.0.rem_euclid(1_000_000);
        let seconds = self.0.div_euclid(1_000_000);
        let days = seconds.div_euclid(86_400);
        let second_of_day = seconds.rem_euclid(86_400);
        let (year, month, day) = civil_from_days(days);
        let mut text = format!(
            "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}",
            second_of_day / 3600,
            second_of_day / 60 % 60,
            second_of_day % 60
        );
        if micros != 0 {
            text.push_str(&format!(".{micros:06}"));
        }
        text.push_str("+00:00");
        text
    }

    /// `isoformat().replace("+00:00", "Z")`, the main-journal envelope form.
    pub fn event_utc(self) -> String {
        self.isoformat().replace("+00:00", "Z")
    }
}

/// Source of the current time. Replay never reads a clock; only commands do.
pub trait Clock: Send + Sync {
    fn now(&self) -> Timestamp;
}

pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> Timestamp {
        let elapsed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock after 1970");
        Timestamp(elapsed.as_micros() as i64)
    }
}

/// A clock tests can set and advance.
#[derive(Clone)]
pub struct ManualClock(Arc<AtomicI64>);

impl ManualClock {
    pub fn new(at: Timestamp) -> Self {
        ManualClock(Arc::new(AtomicI64::new(at.0)))
    }

    pub fn set(&self, at: Timestamp) {
        self.0.store(at.0, Ordering::SeqCst);
    }

    pub fn advance_seconds(&self, seconds: i64) {
        self.0.fetch_add(seconds * 1_000_000, Ordering::SeqCst);
    }
}

impl Clock for ManualClock {
    fn now(&self) -> Timestamp {
        Timestamp(self.0.load(Ordering::SeqCst))
    }
}

/// Days since the epoch for a proleptic Gregorian date (Howard Hinnant's algorithm).
pub fn days_from_civil(year: i64, month: u32, day: u32) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = year.div_euclid(400);
    let yoe = year - era * 400;
    let month = i64::from(month);
    let doy = (153 * (if month > 2 { month - 3 } else { month + 9 }) + 2) / 5 + i64::from(day) - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

pub fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let year = yoe + era * 400 + i64::from(month <= 2);
    (year, month, day)
}

fn days_in_month(year: i64, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ if (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 => 29,
        _ => 28,
    }
}

fn invalid<T>(text: &str) -> Result<T> {
    value_error(format!("Invalid isoformat string: '{text}'"))
}

/// `authority.utc`: Python `datetime.fromisoformat(value.replace("Z", "+00:00"))`, which must
/// carry an offset, converted to UTC. Accepts the extended ISO forms Python produces and the
/// common client forms (`Z`, `±HH:MM`, `±HHMM`, fractional seconds, `T` or space separator).
pub fn parse_utc(text: &str) -> Result<Timestamp> {
    let normalized = text.replace('Z', "+00:00");
    let bytes = normalized.as_bytes();
    let digits = |from: usize, count: usize| -> Option<i64> {
        let slice = normalized.get(from..from + count)?;
        slice
            .bytes()
            .all(|b| b.is_ascii_digit())
            .then(|| slice.parse().ok())?
    };
    if bytes.len() < 10 || bytes[4] != b'-' || bytes[7] != b'-' {
        return invalid(text);
    }
    let (Some(year), Some(month), Some(day)) = (digits(0, 4), digits(5, 2), digits(8, 2)) else {
        return invalid(text);
    };
    let (month, day) = (month as u32, day as u32);
    if !(1..=12).contains(&month) || day == 0 || day > days_in_month(year, month) || year == 0 {
        return invalid(text);
    }
    if bytes.len() == 10 {
        return value_error("timestamp must include UTC offset");
    }
    // Python accepts any single separator character between date and time.
    let mut pos = 11;
    let (Some(hour), Some(minute)) = (digits(pos, 2), digits(pos + 3, 2)) else {
        return invalid(text);
    };
    if bytes.get(pos + 2) != Some(&b':') {
        return invalid(text);
    }
    pos += 5;
    let mut second = 0;
    let mut micros = 0i64;
    if bytes.get(pos) == Some(&b':') {
        second = match digits(pos + 1, 2) {
            Some(s) => s,
            None => return invalid(text),
        };
        pos += 3;
        if matches!(bytes.get(pos), Some(b'.' | b',')) {
            let start = pos + 1;
            let mut end = start;
            while end < bytes.len() && bytes[end].is_ascii_digit() {
                end += 1;
            }
            if end == start {
                return invalid(text);
            }
            let fraction = &normalized[start..end];
            let padded: String = fraction
                .chars()
                .chain(std::iter::repeat('0'))
                .take(6)
                .collect();
            micros = padded.parse().expect("digits");
            pos = end;
        }
    }
    if hour > 23 || minute > 59 || second > 59 {
        return invalid(text);
    }
    let offset_seconds = match bytes.get(pos) {
        None => return value_error("timestamp must include UTC offset"),
        Some(sign @ (b'+' | b'-')) => {
            let sign = if *sign == b'-' { -1 } else { 1 };
            let rest = &normalized[pos + 1..];
            let (hours, minutes, seconds) = match rest.len() {
                4 => (digits(pos + 1, 2), digits(pos + 3, 2), Some(0)),
                5 if rest.as_bytes()[2] == b':' => {
                    (digits(pos + 1, 2), digits(pos + 4, 2), Some(0))
                }
                8 if rest.as_bytes()[2] == b':' && rest.as_bytes()[5] == b':' => {
                    (digits(pos + 1, 2), digits(pos + 4, 2), digits(pos + 7, 2))
                }
                _ => return invalid(text),
            };
            let (Some(h), Some(m), Some(s)) = (hours, minutes, seconds) else {
                return invalid(text);
            };
            if h > 23 || m > 59 || s > 59 {
                return invalid(text);
            }
            sign * (h * 3600 + m * 60 + s)
        }
        _ => return invalid(text),
    };
    let days = days_from_civil(year, month, day);
    let local = days * 86_400 + hour * 3600 + minute * 60 + second;
    Ok(Timestamp((local - offset_seconds) * 1_000_000 + micros))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn isoformat_matches_python() {
        let at = parse_utc("2026-09-28T01:02:03.000004+00:00").unwrap();
        assert_eq!(at.isoformat(), "2026-09-28T01:02:03.000004+00:00");
        assert_eq!(at.event_utc(), "2026-09-28T01:02:03.000004Z");
        let whole = parse_utc("2026-09-28T01:02:03Z").unwrap();
        assert_eq!(whole.isoformat(), "2026-09-28T01:02:03+00:00");
        assert_eq!(Timestamp(0).isoformat(), "1970-01-01T00:00:00+00:00");
        assert_eq!(
            parse_utc("2000-02-29T23:59:59.5+00:00")
                .unwrap()
                .isoformat(),
            "2000-02-29T23:59:59.500000+00:00"
        );
    }

    #[test]
    fn offsets_convert_to_utc_and_naive_is_refused() {
        let a = parse_utc("2026-09-28T03:02:03+02:00").unwrap();
        let b = parse_utc("2026-09-28T01:02:03Z").unwrap();
        assert_eq!(a, b);
        assert_eq!(
            parse_utc("2026-09-28T01:02:03-0130").unwrap(),
            b.plus_seconds(5400)
        );
        assert!(parse_utc("2026-09-28T01:02:03").is_err());
        assert!(parse_utc("2026-02-30T00:00:00Z").is_err());
        assert!(parse_utc("not a date").is_err());
    }

    #[test]
    fn civil_round_trip_over_four_centuries() {
        for days in (-200_000..200_000).step_by(37) {
            let (y, m, d) = civil_from_days(days);
            assert_eq!(days_from_civil(y, m, d), days);
        }
    }
}

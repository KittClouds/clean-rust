//! RFC 8785 output identical to the pinned Python `jcs 0.2.1`.

use std::cmp::Ordering;
use std::fmt::Write as _;

use serde_json::{Number, Value};

use crate::{JcsError, MAX_SAFE_INTEGER};

/// Canonical bytes of `value`, validated with the same rules as `identity.canonical`.
pub fn canonical(value: &Value) -> Result<Vec<u8>, JcsError> {
    let mut out = Vec::with_capacity(256);
    canonical_into(value, &mut out)?;
    Ok(out)
}

/// Appends the canonical bytes of `value` to `out`. On error `out` may hold a partial write.
pub fn canonical_into(value: &Value, out: &mut Vec<u8>) -> Result<(), JcsError> {
    write_value(value, out)
}

fn write_value(value: &Value, out: &mut Vec<u8>) -> Result<(), JcsError> {
    match value {
        Value::Null => out.extend_from_slice(b"null"),
        Value::Bool(true) => out.extend_from_slice(b"true"),
        Value::Bool(false) => out.extend_from_slice(b"false"),
        Value::Number(number) => write_number(number, out)?,
        Value::String(text) => write_string(text, out),
        Value::Array(items) => {
            out.push(b'[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(b',');
                }
                write_value(item, out)?;
            }
            out.push(b']');
        }
        Value::Object(map) => {
            let mut entries: Vec<(&String, &Value)> = map.iter().collect();
            // jcs sorts by `key.encode("utf-16_be")`, i.e. by UTF-16 code units. That differs
            // from UTF-8 byte order for supplementary characters versus U+E000..U+FFFF.
            entries.sort_unstable_by(|a, b| utf16_cmp(a.0, b.0));
            out.push(b'{');
            for (index, (key, item)) in entries.into_iter().enumerate() {
                if index > 0 {
                    out.push(b',');
                }
                write_string(key, out);
                out.push(b':');
                write_value(item, out)?;
            }
            out.push(b'}');
        }
    }
    Ok(())
}

fn utf16_cmp(a: &str, b: &str) -> Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}

fn write_string(text: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    let bytes = text.as_bytes();
    let mut run = 0;
    for (index, &byte) in bytes.iter().enumerate() {
        let escape: Option<&[u8]> = match byte {
            b'"' => Some(b"\\\""),
            b'\\' => Some(b"\\\\"),
            0x08 => Some(b"\\b"),
            0x0c => Some(b"\\f"),
            b'\n' => Some(b"\\n"),
            b'\r' => Some(b"\\r"),
            b'\t' => Some(b"\\t"),
            0x00..=0x1f => None,
            _ => continue,
        };
        out.extend_from_slice(&bytes[run..index]);
        match escape {
            Some(sequence) => out.extend_from_slice(sequence),
            None => {
                const HEX: &[u8; 16] = b"0123456789abcdef";
                out.extend_from_slice(b"\\u00");
                out.push(HEX[usize::from(byte >> 4)]);
                out.push(HEX[usize::from(byte & 0x0f)]);
            }
        }
        run = index + 1;
    }
    out.extend_from_slice(&bytes[run..]);
    out.push(b'"');
}

fn write_number(number: &Number, out: &mut Vec<u8>) -> Result<(), JcsError> {
    if let Some(value) = number.as_i64() {
        if value.unsigned_abs() > MAX_SAFE_INTEGER {
            return Err(JcsError::UnsafeInteger);
        }
        // Python formats ints through float(); inside the safe range that is the plain decimal.
        let mut buffer = itoa_buffer();
        write!(buffer, "{value}").expect("write to string");
        out.extend_from_slice(buffer.as_bytes());
        return Ok(());
    }
    if let Some(value) = number.as_u64() {
        if value > MAX_SAFE_INTEGER {
            return Err(JcsError::UnsafeInteger);
        }
        let mut buffer = itoa_buffer();
        write!(buffer, "{value}").expect("write to string");
        out.extend_from_slice(buffer.as_bytes());
        return Ok(());
    }
    let value = number.as_f64().ok_or(JcsError::NonFinite)?;
    write_es6_double(value, out)
}

fn itoa_buffer() -> String {
    String::with_capacity(24)
}

/// ECMAScript `Number::toString` for a finite double, which is what `jcs.ntoj` produces from
/// Python's shortest round-trip `repr`.
fn write_es6_double(value: f64, out: &mut Vec<u8>) -> Result<(), JcsError> {
    if !value.is_finite() {
        return Err(JcsError::NonFinite);
    }
    if value == 0.0 {
        // Covers -0.0 as well.
        out.push(b'0');
        return Ok(());
    }
    let scientific = shortest_scientific(value);
    let (negative, body) = match scientific.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, scientific.as_str()),
    };
    let (mantissa, exponent) = body.split_once('e').expect("scientific notation");
    let exponent: i32 = exponent.parse().expect("exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let k = digits.len() as i32;
    let n = exponent + 1;
    let mut text = String::with_capacity(32);
    if negative {
        text.push('-');
    }
    if k <= n && n <= 21 {
        text.push_str(&digits);
        text.extend(std::iter::repeat_n('0', (n - k) as usize));
    } else if 0 < n && n <= 21 {
        text.push_str(&digits[..n as usize]);
        text.push('.');
        text.push_str(&digits[n as usize..]);
    } else if -6 < n && n <= 0 {
        text.push_str("0.");
        text.extend(std::iter::repeat_n('0', (-n) as usize));
        text.push_str(&digits);
    } else {
        text.push_str(&digits[..1]);
        if k > 1 {
            text.push('.');
            text.push_str(&digits[1..]);
        }
        text.push('e');
        text.push(if n > 0 { '+' } else { '-' });
        write!(text, "{}", (n - 1).abs()).expect("write to string");
    }
    out.extend_from_slice(text.as_bytes());
    Ok(())
}

/// Shortest round-trip digits in scientific form, with Python `repr` tie-breaking.
///
/// Rust's `{:e}` finds the shortest digit count `k`, but when the exact binary value sits
/// exactly halfway between two `k`-digit decimals it rounds away from even, while Python's
/// dtoa picks the even digit (`-113260523179066.625` → `…066.62`). Re-rounding to the same
/// `k` digits with the exact formatter (ties to even) reproduces Python; the round-trip check
/// guards the invariant.
fn shortest_scientific(value: f64) -> String {
    let shortest = format!("{value:e}");
    let mantissa = shortest.split_once('e').expect("scientific notation").0;
    let digits = mantissa.bytes().filter(u8::is_ascii_digit).count();
    let even = format!("{value:.precision$e}", precision = digits.saturating_sub(1));
    if even.parse::<f64>() == Ok(value) {
        even
    } else {
        shortest
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    // The literals spell each double's exact binary value on purpose.
    #[allow(clippy::excessive_precision)]
    fn halfway_digits_break_ties_to_even_like_python_repr() {
        // Each value is exactly halfway between two 17-digit decimals.
        assert_eq!(number_text(-113260523179066.625), "-113260523179066.62");
        assert_eq!(number_text(-2164674218406121.25), "-2164674218406121.2");
        assert_eq!(number_text(-1171821582793295.25), "-1171821582793295.2");
    }

    fn number_text(value: f64) -> String {
        let mut out = Vec::new();
        write_es6_double(value, &mut out).unwrap();
        String::from_utf8(out).unwrap()
    }

    #[test]
    fn es6_number_forms_match_jcs_ntoj() {
        // Expected strings follow the RFC 8785 appendix and the jcs.ntoj algorithm.
        let cases: &[(f64, &str)] = &[
            (0.0, "0"),
            (-0.0, "0"),
            (1.0, "1"),
            (-1.5, "-1.5"),
            (0.5, "0.5"),
            (100.0, "100"),
            (1e16, "10000000000000000"),
            (1.5e16, "15000000000000000"),
            (1e20, "100000000000000000000"),
            (1e21, "1e+21"),
            (1.2345678901234567e19, "12345678901234567000"),
            (1e-6, "0.000001"),
            (1.5e-5, "0.000015"),
            (1e-7, "1e-7"),
            (1.5e-7, "1.5e-7"),
            (5e-324, "5e-324"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
            (123456789012345.67, "123456789012345.67"),
            (0.1, "0.1"),
            (333333333.3333333, "333333333.3333333"),
        ];
        for &(value, expected) in cases {
            assert_eq!(number_text(value), expected, "value {value:e}");
        }
    }

    #[test]
    fn keys_sort_by_utf16_code_units() {
        let value: Value = serde_json::json!({"\u{e000}": 1, "\u{1f600}": 2, "a": 3});
        let text = String::from_utf8(canonical(&value).unwrap()).unwrap();
        // U+1F600 encodes as surrogates D83D DE00, which sort before U+E000.
        assert_eq!(text, "{\"a\":3,\"\u{1f600}\":2,\"\u{e000}\":1}");
    }

    #[test]
    fn escape_table_matches_jcs() {
        let value = Value::String("\"\\\u{8}\u{c}\n\r\t\u{1}\u{1f}\u{7f}é/".into());
        let text = String::from_utf8(canonical(&value).unwrap()).unwrap();
        assert_eq!(text, "\"\\\"\\\\\\b\\f\\n\\r\\t\\u0001\\u001f\u{7f}é/\"");
    }

    #[test]
    fn unsafe_integers_are_refused() {
        let value: Value = serde_json::json!({"n": 9_007_199_254_740_992u64});
        assert_eq!(canonical(&value), Err(JcsError::UnsafeInteger));
        let edge: Value = serde_json::json!(9_007_199_254_740_991i64);
        assert_eq!(canonical(&edge).unwrap(), b"9007199254740991");
    }
}

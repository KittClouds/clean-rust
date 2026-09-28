//! Strict JSON input matching Python `json.loads` plus `identity.strict_json`.

use serde_json::{Map, Number, Value};

use crate::{JcsError, MAX_SAFE_INTEGER};

/// Python's json scanner raises `RecursionError` near 1,000 levels. Payloads never come close;
/// refusing earlier keeps the parser's stack bounded.
const MAX_DEPTH: usize = 512;

/// Parses `raw` under the Library's strict JSON rules.
pub fn strict_json(raw: &[u8]) -> Result<Value, JcsError> {
    let text = std::str::from_utf8(raw).map_err(|_| JcsError::InvalidUtf8)?;
    let mut parser = Parser {
        bytes: text.as_bytes(),
        pos: 0,
    };
    // Python refuses a leading byte-order mark on decoded text.
    if text.starts_with('\u{feff}') {
        return Err(parser.error("unexpected UTF-8 BOM"));
    }
    parser.skip_ws();
    let value = parser.value(0)?;
    parser.skip_ws();
    if parser.pos != parser.bytes.len() {
        return Err(parser.error("extra data after JSON value"));
    }
    Ok(value)
}

struct Parser<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl Parser<'_> {
    fn error(&self, reason: &'static str) -> JcsError {
        JcsError::Syntax {
            offset: self.pos,
            reason,
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn skip_ws(&mut self) {
        while let Some(b' ' | b'\t' | b'\n' | b'\r') = self.peek() {
            self.pos += 1;
        }
    }

    fn literal(&mut self, word: &'static [u8], value: Value) -> Result<Value, JcsError> {
        if self.bytes[self.pos..].starts_with(word) {
            self.pos += word.len();
            Ok(value)
        } else {
            Err(self.error("invalid literal"))
        }
    }

    fn value(&mut self, depth: usize) -> Result<Value, JcsError> {
        match self.peek() {
            Some(b'{') => self.object(depth + 1),
            Some(b'[') => self.array(depth + 1),
            Some(b'"') => self.string().map(Value::String),
            Some(b't') => self.literal(b"true", Value::Bool(true)),
            Some(b'f') => self.literal(b"false", Value::Bool(false)),
            Some(b'n') => self.literal(b"null", Value::Null),
            Some(b'-' | b'0'..=b'9') => self.number(),
            // NaN, Infinity and -Infinity are rejected by the Python parse_constant hook.
            _ => Err(self.error("expected JSON value")),
        }
    }

    fn object(&mut self, depth: usize) -> Result<Value, JcsError> {
        if depth > MAX_DEPTH {
            return Err(JcsError::TooDeep(MAX_DEPTH));
        }
        self.pos += 1;
        let mut map = Map::new();
        self.skip_ws();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(Value::Object(map));
        }
        loop {
            self.skip_ws();
            if self.peek() != Some(b'"') {
                return Err(self.error("expected property name"));
            }
            let key = self.string()?;
            self.skip_ws();
            if self.peek() != Some(b':') {
                return Err(self.error("expected ':'"));
            }
            self.pos += 1;
            self.skip_ws();
            let item = self.value(depth)?;
            if map.contains_key(&key) {
                return Err(JcsError::DuplicateKey(key));
            }
            map.insert(key, item);
            self.skip_ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(Value::Object(map));
                }
                _ => return Err(self.error("expected ',' or '}'")),
            }
        }
    }

    fn array(&mut self, depth: usize) -> Result<Value, JcsError> {
        if depth > MAX_DEPTH {
            return Err(JcsError::TooDeep(MAX_DEPTH));
        }
        self.pos += 1;
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(Value::Array(items));
        }
        loop {
            self.skip_ws();
            items.push(self.value(depth)?);
            self.skip_ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b']') => {
                    self.pos += 1;
                    return Ok(Value::Array(items));
                }
                _ => return Err(self.error("expected ',' or ']'")),
            }
        }
    }

    fn hex4(&mut self) -> Result<u16, JcsError> {
        let digits = self
            .bytes
            .get(self.pos..self.pos + 4)
            .ok_or_else(|| self.error("short \\u escape"))?;
        let mut value = 0u16;
        for &digit in digits {
            let nibble = match digit {
                b'0'..=b'9' => digit - b'0',
                b'a'..=b'f' => digit - b'a' + 10,
                b'A'..=b'F' => digit - b'A' + 10,
                _ => return Err(self.error("invalid \\u escape")),
            };
            value = (value << 4) | u16::from(nibble);
        }
        self.pos += 4;
        Ok(value)
    }

    fn string(&mut self) -> Result<String, JcsError> {
        self.pos += 1;
        let mut out = String::new();
        loop {
            let start = self.pos;
            while let Some(byte) = self.peek() {
                if byte == b'"' || byte == b'\\' || byte < 0x20 {
                    break;
                }
                self.pos += 1;
            }
            // The input is valid UTF-8 and runs stop only at ASCII bytes.
            out.push_str(std::str::from_utf8(&self.bytes[start..self.pos]).expect("utf-8 run"));
            match self.peek() {
                Some(b'"') => {
                    self.pos += 1;
                    return Ok(out);
                }
                Some(b'\\') => {
                    self.pos += 1;
                    let escape = self
                        .peek()
                        .ok_or_else(|| self.error("unterminated escape"))?;
                    self.pos += 1;
                    match escape {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => out.push(self.unicode_escape()?),
                        _ => return Err(self.error("invalid escape")),
                    }
                }
                // Python's strict decoder refuses raw control characters inside strings.
                Some(_) => return Err(self.error("control character in string")),
                None => return Err(self.error("unterminated string")),
            }
        }
    }

    fn unicode_escape(&mut self) -> Result<char, JcsError> {
        let first = self.hex4()?;
        match first {
            0xD800..=0xDBFF => {
                // Python pairs a high surrogate only with an immediately following low escape;
                // anything else leaves a lone surrogate, which identity validation rejects.
                if self.bytes[self.pos..].starts_with(b"\\u") {
                    self.pos += 2;
                    let second = self.hex4()?;
                    if (0xDC00..=0xDFFF).contains(&second) {
                        let code = 0x10000
                            + ((u32::from(first) - 0xD800) << 10)
                            + (u32::from(second) - 0xDC00);
                        return char::from_u32(code).ok_or(JcsError::LoneSurrogate);
                    }
                }
                Err(JcsError::LoneSurrogate)
            }
            0xDC00..=0xDFFF => Err(JcsError::LoneSurrogate),
            code => char::from_u32(u32::from(code)).ok_or(JcsError::LoneSurrogate),
        }
    }

    fn number(&mut self) -> Result<Value, JcsError> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        match self.peek() {
            Some(b'0') => self.pos += 1,
            Some(b'1'..=b'9') => self.digits(),
            _ => return Err(self.error("invalid number")),
        }
        let mut is_float = false;
        let mut mantissa_end = self.pos;
        if self.peek() == Some(b'.') && matches!(self.bytes.get(self.pos + 1), Some(b'0'..=b'9')) {
            is_float = true;
            self.pos += 1;
            self.digits();
            mantissa_end = self.pos;
        }
        if let Some(b'e' | b'E') = self.peek() {
            let mark = self.pos;
            self.pos += 1;
            if let Some(b'+' | b'-') = self.peek() {
                self.pos += 1;
            }
            if matches!(self.peek(), Some(b'0'..=b'9')) {
                is_float = true;
                self.digits();
            } else {
                // Python's number pattern stops before a dangling exponent; the trailing
                // characters then fail as extra data or an invalid delimiter.
                self.pos = mark;
            }
        }
        let token = std::str::from_utf8(&self.bytes[start..self.pos]).expect("ascii number");
        if is_float {
            let number: f64 = token.parse().map_err(|_| self.error("invalid number"))?;
            if !number.is_finite() {
                return Err(JcsError::FloatRange);
            }
            // Python compares Decimal(token) with zero: any non-zero mantissa digit means
            // the value underflowed to zero.
            let mantissa = &self.bytes[start..mantissa_end];
            if number == 0.0 && mantissa.iter().any(|b| (b'1'..=b'9').contains(b)) {
                return Err(JcsError::FloatRange);
            }
            Ok(Value::Number(
                Number::from_f64(number).ok_or(JcsError::NonFinite)?,
            ))
        } else {
            let negative = token.starts_with('-');
            let digits = token.trim_start_matches('-');
            if digits.len() > 16 {
                return Err(JcsError::UnsafeInteger);
            }
            let magnitude: u64 = digits.parse().map_err(|_| self.error("invalid integer"))?;
            if magnitude > MAX_SAFE_INTEGER {
                return Err(JcsError::UnsafeInteger);
            }
            let value = if negative {
                -(magnitude as i64)
            } else {
                magnitude as i64
            };
            Ok(Value::Number(Number::from(value)))
        }
    }

    fn digits(&mut self) {
        while let Some(b'0'..=b'9') = self.peek() {
            self.pos += 1;
        }
    }
}

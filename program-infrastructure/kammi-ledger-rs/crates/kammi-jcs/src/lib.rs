//! Canonical custody identities for the Kammi Library.
//!
//! This crate reproduces `ledgerd/identity.py` byte for byte:
//!
//! - [`strict_json`] rejects exactly what the Python `strict_json` rejects: invalid UTF-8,
//!   duplicate object keys, lone surrogates, non-finite numbers, floats that overflow or
//!   underflow binary64, and integers outside the JCS safe range.
//! - [`canonical`] is RFC 8785 as implemented by the pinned `jcs 0.2.1` package: keys sorted
//!   by UTF-16 code units, ES6 number formatting (integers go through the same path), and the
//!   `jcs` escape table.
//! - [`raw_id`] and [`typed_id`] build `sha256:` identities, with the domain tags used for
//!   events, seals, facts and structured objects.

mod canon;
mod ids;
mod parse;

pub use canon::{canonical, canonical_into};
pub use ids::{raw_id, typed_id, typed_id_of_canonical, Domain, Sha256Hasher, Sha256Id};
pub use parse::strict_json;
pub use serde_json::{Map, Number, Value};

/// Largest integer magnitude a JCS payload may carry (`2^53 - 1`).
pub const MAX_SAFE_INTEGER: u64 = (1 << 53) - 1;

/// Every way an input can fail the Library's identity rules.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum JcsError {
    #[error("invalid UTF-8 in JSON input")]
    InvalidUtf8,
    #[error("JSON syntax error at byte {offset}: {reason}")]
    Syntax { offset: usize, reason: &'static str },
    #[error("duplicate JSON property: {0}")]
    DuplicateKey(String),
    #[error("unpaired Unicode surrogate")]
    LoneSurrogate,
    #[error("non-finite JSON number")]
    NonFinite,
    #[error("JSON number overflows or underflows binary64")]
    FloatRange,
    #[error("integer is outside JCS safe range; encode as schema string")]
    UnsafeInteger,
    #[error("JSON nesting exceeds {0} levels")]
    TooDeep(usize),
    #[error("expected lowercase sha256: digest")]
    InvalidId,
}

/// Returns true when `raw` parses strictly and is already in canonical form.
pub fn is_canonical(raw: &[u8]) -> bool {
    match strict_json(raw).and_then(|value| canonical(&value)) {
        Ok(bytes) => bytes == raw,
        Err(_) => false,
    }
}

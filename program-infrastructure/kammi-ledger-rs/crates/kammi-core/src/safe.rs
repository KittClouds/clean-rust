//! Identifier rules shared by every domain module.

use kammi_jcs::Sha256Id;

use crate::error::{value_error, Result};

/// `graph.py:SAFE = ^[A-Za-z0-9_.:-]{1,160}$`.
pub fn is_safe(text: &str) -> bool {
    !text.is_empty()
        && text.len() <= 160
        && text
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b':' | b'-'))
}

/// `identity.require_id`: returns the identity text unchanged when well-formed.
pub fn require_id(text: &str) -> Result<&str> {
    match Sha256Id::parse(text) {
        Ok(_) => Ok(text),
        Err(_) => value_error("expected lowercase sha256: digest"),
    }
}

pub fn is_id(text: &str) -> bool {
    Sha256Id::parse(text).is_ok()
}

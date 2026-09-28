//! `sha256:` identities with the Library's domain separation.

use std::fmt;

use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::{canonical, JcsError};

/// Domain tags from `identity.py:DOMAINS`. Each prefixes the canonical bytes before hashing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Domain {
    Object,
    Event,
    Seal,
    Fact,
}

impl Domain {
    pub const fn tag(self) -> &'static [u8] {
        match self {
            Domain::Object => b"kammi-object-v1\0",
            Domain::Event => b"kammi-event-v1\0",
            Domain::Seal => b"kammi-seal-v1\0",
            Domain::Fact => b"kammi-fact-v1\0",
        }
    }
}

/// A 32-byte SHA-256 digest, written as `sha256:` plus 64 lowercase hex digits.
#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Sha256Id(pub [u8; 32]);

impl Sha256Id {
    /// The all-zero digest used as the genesis `prev` of a journal.
    pub const ZERO: Sha256Id = Sha256Id([0; 32]);

    /// Parses an identity with the same rules as `identity.require_id`.
    pub fn parse(text: &str) -> Result<Self, JcsError> {
        let hex = text.strip_prefix("sha256:").ok_or(JcsError::InvalidId)?;
        if hex.len() != 64 {
            return Err(JcsError::InvalidId);
        }
        let mut digest = [0u8; 32];
        for (slot, pair) in digest.iter_mut().zip(hex.as_bytes().chunks_exact(2)) {
            *slot = (nibble(pair[0])? << 4) | nibble(pair[1])?;
        }
        Ok(Sha256Id(digest))
    }

    pub fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }
}

fn nibble(digit: u8) -> Result<u8, JcsError> {
    match digit {
        b'0'..=b'9' => Ok(digit - b'0'),
        b'a'..=b'f' => Ok(digit - b'a' + 10),
        _ => Err(JcsError::InvalidId),
    }
}

impl fmt::Display for Sha256Id {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut text = [0u8; 71];
        text[..7].copy_from_slice(b"sha256:");
        for (index, byte) in self.0.iter().enumerate() {
            text[7 + index * 2] = HEX[usize::from(byte >> 4)];
            text[8 + index * 2] = HEX[usize::from(byte & 0x0f)];
        }
        f.write_str(std::str::from_utf8(&text).expect("ascii"))
    }
}

impl fmt::Debug for Sha256Id {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}

impl std::str::FromStr for Sha256Id {
    type Err = JcsError;

    fn from_str(text: &str) -> Result<Self, Self::Err> {
        Sha256Id::parse(text)
    }
}

/// Incremental SHA-256 for streams too large to hold in memory.
#[derive(Clone, Default)]
pub struct Sha256Hasher(Sha256);

impl Sha256Hasher {
    pub fn new() -> Self {
        Sha256Hasher(Sha256::new())
    }

    pub fn update(&mut self, bytes: &[u8]) {
        self.0.update(bytes);
    }

    pub fn finish(self) -> Sha256Id {
        Sha256Id(self.0.finalize().into())
    }
}

/// Identity of raw bytes: CAS objects, policy hashes, memory IDs and package roots.
pub fn raw_id(bytes: &[u8]) -> Sha256Id {
    Sha256Id(Sha256::digest(bytes).into())
}

/// Domain-separated identity of already-canonical bytes.
pub fn typed_id_of_canonical(domain: Domain, canonical_bytes: &[u8]) -> Sha256Id {
    let mut hasher = Sha256::new();
    hasher.update(domain.tag());
    hasher.update(canonical_bytes);
    Sha256Id(hasher.finalize().into())
}

/// Domain-separated identity of a JSON value: `SHA256(tag || JCS(value))`.
pub fn typed_id(domain: Domain, value: &Value) -> Result<Sha256Id, JcsError> {
    Ok(typed_id_of_canonical(domain, &canonical(value)?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_text_round_trips_and_rejects_uppercase() {
        let id = raw_id(b"kammi");
        let text = id.to_string();
        assert_eq!(text.len(), 71);
        assert_eq!(Sha256Id::parse(&text).unwrap(), id);
        assert!(Sha256Id::parse(&text.to_uppercase()).is_err());
        assert!(Sha256Id::parse("sha256:00").is_err());
    }

    #[test]
    fn zero_event_matches_python_genesis() {
        assert_eq!(
            Sha256Id::ZERO.to_string(),
            format!("sha256:{}", "0".repeat(64))
        );
    }
}

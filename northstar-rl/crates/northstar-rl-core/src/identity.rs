use std::{fmt, str::FromStr};

use schemars::{JsonSchema, Schema, SchemaGenerator, json_schema};
use serde::{Deserialize, Deserializer, Serialize, Serializer, de};

use crate::{Error, Result};

/// A domain-separated BLAKE3 identity rendered as 64 lowercase hex digits.
#[derive(Clone, Copy, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct Digest(pub [u8; 32]);

impl Digest {
    pub const ZERO: Self = Self([0; 32]);

    #[inline]
    pub fn bytes(self) -> [u8; 32] {
        self.0
    }

    pub fn hash(domain: &[u8], payload: &[u8]) -> Self {
        let mut hasher = blake3::Hasher::new();
        hasher.update(&(domain.len() as u64).to_le_bytes());
        hasher.update(domain);
        hasher.update(&(payload.len() as u64).to_le_bytes());
        hasher.update(payload);
        Self(*hasher.finalize().as_bytes())
    }

    pub fn hash_parts<'a>(domain: &[u8], parts: impl IntoIterator<Item = &'a [u8]>) -> Self {
        let mut hasher = blake3::Hasher::new();
        hasher.update(&(domain.len() as u64).to_le_bytes());
        hasher.update(domain);
        for part in parts {
            hasher.update(&(part.len() as u64).to_le_bytes());
            hasher.update(part);
        }
        Self(*hasher.finalize().as_bytes())
    }
}

impl fmt::Debug for Digest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}

impl fmt::Display for Digest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for byte in self.0 {
            write!(f, "{byte:02x}")?;
        }
        Ok(())
    }
}

impl FromStr for Digest {
    type Err = Error;

    fn from_str(value: &str) -> Result<Self> {
        if value.len() != 64 {
            return Err(Error::InvalidContract(
                "digest must contain 64 hex digits".into(),
            ));
        }
        let mut bytes = [0_u8; 32];
        for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
            let text = std::str::from_utf8(pair)
                .map_err(|_| Error::InvalidContract("digest is not UTF-8".into()))?;
            bytes[index] = u8::from_str_radix(text, 16)
                .map_err(|_| Error::InvalidContract("digest contains non-hex data".into()))?;
        }
        Ok(Self(bytes))
    }
}

impl Serialize for Digest {
    fn serialize<S: Serializer>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_string())
    }
}

impl<'de> Deserialize<'de> for Digest {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        value.parse().map_err(de::Error::custom)
    }
}

impl JsonSchema for Digest {
    fn schema_name() -> std::borrow::Cow<'static, str> {
        "Digest256".into()
    }

    fn json_schema(_: &mut SchemaGenerator) -> Schema {
        json_schema!({
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
            "description": "Domain-separated BLAKE3 digest"
        })
    }
}

pub fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    Ok(serde_json::to_vec(value)?)
}

pub fn identity<T: Serialize>(domain: &[u8], value: &T) -> Result<Digest> {
    Ok(Digest::hash(domain, &canonical_json(value)?))
}

/// Source-bound identities for every authoritative kernel layer, in fixed order.
pub fn kernel_implementation_hashes() -> Vec<Digest> {
    [
        (
            b"account".as_slice(),
            include_bytes!("account.rs").as_slice(),
        ),
        (
            b"contracts".as_slice(),
            include_bytes!("contracts.rs").as_slice(),
        ),
        (b"batch".as_slice(), include_bytes!("batch.rs").as_slice()),
        (
            b"environment".as_slice(),
            include_bytes!("environment.rs").as_slice(),
        ),
        (
            b"episode".as_slice(),
            include_bytes!("episode.rs").as_slice(),
        ),
        (
            b"feature".as_slice(),
            include_bytes!("feature.rs").as_slice(),
        ),
        (b"replay".as_slice(), include_bytes!("replay.rs").as_slice()),
        (b"tape".as_slice(), include_bytes!("tape.rs").as_slice()),
    ]
    .into_iter()
    .map(|(name, source)| Digest::hash_parts(b"northstar-kernel-source-v1", [name, source]))
    .collect()
}

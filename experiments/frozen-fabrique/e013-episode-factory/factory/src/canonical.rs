use serde::Serialize;

use crate::FactoryError;

/// Stable JSON for schema structs: declaration field order, sorted map keys, UTF-8, trailing LF.
pub fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, FactoryError> {
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

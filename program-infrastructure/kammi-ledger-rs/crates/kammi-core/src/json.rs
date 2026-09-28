//! Python-dict semantics over `serde_json::Value`.
//!
//! `get(value, "k")` fails like `value["k"]` does in Python: a missing key is a `KeyError`
//! (HTTP 400, detail `'k'`), and a value of the wrong type is a `TypeError`.

use kammi_jcs::{canonical, raw_id, Map, Value};

use crate::error::{LedgerError, Result};

pub fn get<'a>(value: &'a Value, key: &str) -> Result<&'a Value> {
    match value {
        Value::Object(map) => map
            .get(key)
            .ok_or_else(|| LedgerError::Key(key.to_string())),
        _ => Err(LedgerError::Type("indices must be integers".into())),
    }
}

pub fn get_str<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    get(value, key)?
        .as_str()
        .ok_or_else(|| LedgerError::Type(format!("{key} must be a string")))
}

pub fn opt_str<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value.get(key).and_then(Value::as_str)
}

/// A Python `int` (JSON booleans are not integers here, unlike Python's bool subclass;
/// callers that must accept bools say so explicitly).
pub fn get_int(value: &Value, key: &str) -> Result<i64> {
    get(value, key)?
        .as_i64()
        .ok_or_else(|| LedgerError::Type(format!("{key} must be an integer")))
}

pub fn get_obj<'a>(value: &'a Value, key: &str) -> Result<&'a Map<String, Value>> {
    get(value, key)?
        .as_object()
        .ok_or_else(|| LedgerError::Type(format!("{key} must be an object")))
}

pub fn get_array<'a>(value: &'a Value, key: &str) -> Result<&'a Vec<Value>> {
    get(value, key)?
        .as_array()
        .ok_or_else(|| LedgerError::Type(format!("{key} must be an array")))
}

pub fn string_list(value: &Value, key: &str) -> Result<Vec<String>> {
    get_array(value, key)?
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_string)
                .ok_or_else(|| LedgerError::Type(format!("{key} items must be strings")))
        })
        .collect()
}

/// `raw_id(canonical(value))` as text.
pub fn object_id(value: &Value) -> Result<String> {
    Ok(raw_id(&canonical(value)?).to_string())
}

/// Builds an object from literal pairs, preserving nothing about order (canonical form sorts).
#[macro_export]
macro_rules! obj {
    ($($key:expr => $value:expr),* $(,)?) => {{
        let mut map = $crate::__jcs::Map::new();
        $( map.insert(($key).to_string(), $crate::__jcs::Value::from($value)); )*
        $crate::__jcs::Value::Object(map)
    }};
}

/// Merges `extra` into a copy of `base` (Python `{**base, **extra}`).
pub fn merged(base: &Value, extra: Value) -> Value {
    let mut map = base.as_object().cloned().unwrap_or_default();
    if let Value::Object(more) = extra {
        for (k, v) in more {
            map.insert(k, v);
        }
    }
    Value::Object(map)
}

/// A copy of `base` without the named keys.
pub fn without(base: &Value, keys: &[&str]) -> Value {
    let mut map = base.as_object().cloned().unwrap_or_default();
    for key in keys {
        map.remove(*key);
    }
    Value::Object(map)
}

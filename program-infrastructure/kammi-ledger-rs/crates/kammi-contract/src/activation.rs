//! `LibraryVocabularyActivated` (amendment v4 section 6): the journaled, one-way switch that
//! makes the v4 vocabulary journalable on a store.
//!
//! Payload: `vocabulary` (`"v4"`), `not_before` (the fixed rollback-window floor), and three
//! registered artifacts: the user's `closure_decision`, the Rust independent `verification` of
//! the store at its pre-activation head, and the `backup` manifest taken just before.

use serde_json::Value;

pub const EVENT: &str = "LibraryVocabularyActivated";
pub const VOCABULARY: &str = "v4";
/// Amendment v4 section 5: the rollback window cannot close before this instant.
pub const NOT_BEFORE: &str = "2026-10-06T00:00:00Z";
/// The artifact fields, each a registered `sha256:` artifact.
pub const ARTIFACT_FIELDS: [&str; 3] = ["backup", "closure_decision", "verification"];
/// Schema of the closure decision document the `closure_decision` artifact must hold.
pub const CLOSURE_SCHEMA: &str = "KAMMI_ROLLBACK_WINDOW_CLOSURE_V1";

fn is_sha256_id(text: &str) -> bool {
    text.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64 && hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
    })
}

/// Validates the activation payload's shape (existence of the artifacts is the core's check).
pub fn validate(payload: &Value) -> Result<(), String> {
    let object = payload.as_object().ok_or("payload: must be an object")?;
    let mut keys: Vec<&str> = object.keys().map(String::as_str).collect();
    keys.sort_unstable();
    if keys
        != [
            "backup",
            "closure_decision",
            "not_before",
            "verification",
            "vocabulary",
        ]
    {
        return Err("activation: keys must be exactly backup, closure_decision, not_before, verification, vocabulary".into());
    }
    if object["vocabulary"].as_str() != Some(VOCABULARY) {
        return Err("activation: only vocabulary v4 exists".into());
    }
    if object["not_before"].as_str() != Some(NOT_BEFORE) {
        return Err(format!("activation: not_before must be {NOT_BEFORE}"));
    }
    for field in ARTIFACT_FIELDS {
        if !object[field].as_str().is_some_and(is_sha256_id) {
            return Err(format!("{field}: a registered sha256 artifact"));
        }
    }
    Ok(())
}

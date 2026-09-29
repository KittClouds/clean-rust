//! `LibraryVocabularyActivated` (amendment v4 section 6): the journaled, one-way switch that
//! makes the v4 vocabulary journalable on a store.
//!
//! Payload: `vocabulary` (`"v4"`), the recorded `effective_at`, and six registered artifacts:
//! the approved amendment, the program owner's closure decision, independent monitoring and
//! rollback evidence, the Rust independent verification at the pre-activation head, and backup.

use serde_json::Value;

pub const EVENT: &str = "LibraryVocabularyActivated";
pub const VOCABULARY: &str = "v4";
/// The artifact fields, each a registered `sha256:` artifact.
pub const ARTIFACT_FIELDS: [&str; 6] = [
    "amendment",
    "backup",
    "closure_decision",
    "monitoring_snapshot",
    "rollback_evidence",
    "verification",
];
/// Schema of the closure decision document the `closure_decision` artifact must hold.
pub const CLOSURE_SCHEMA: &str = "KAMMI_ROLLBACK_WINDOW_CLOSURE_V2";
/// Schema of the recorded amendment authorizing immediate activation.
pub const AMENDMENT_SCHEMA: &str = "KAMMI_V4_EARLY_ACTIVATION_AMENDMENT_V1";

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
            "amendment",
            "backup",
            "closure_decision",
            "effective_at",
            "monitoring_snapshot",
            "rollback_evidence",
            "verification",
            "vocabulary",
        ]
    {
        return Err("activation: keys must be exactly amendment, backup, closure_decision, effective_at, monitoring_snapshot, rollback_evidence, verification, vocabulary".into());
    }
    if object["vocabulary"].as_str() != Some(VOCABULARY) {
        return Err("activation: only vocabulary v4 exists".into());
    }
    if object["effective_at"]
        .as_str()
        .and_then(crate::time::parse_utc)
        .is_none()
    {
        return Err("activation: effective_at must be an RFC 3339 UTC timestamp".into());
    }
    for field in ARTIFACT_FIELDS {
        if !object[field].as_str().is_some_and(is_sha256_id) {
            return Err(format!("{field}: a registered sha256 artifact"));
        }
    }
    Ok(())
}

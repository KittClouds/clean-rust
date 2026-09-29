//! Workspace events (amendment v4 §2): payload rules shared by the daemon and the shell.
//!
//! Every workspace payload carries `workspace_id` and `expected_head` (the workspace's
//! previous event ID, or `"genesis"` for `WorkspaceCreated`) plus its type's fields below.
//! Unknown keys are refused, so a payload's meaning cannot drift silently.

use serde_json::Value;

pub const GENESIS: &str = "genesis";
pub const WORKSPACE_GOVERNOR: &str = "chief-kammi";

/// Reference kinds a `refs` entry may name (`<kind>:<identity>`).
pub const REF_KINDS: [&str; 6] = ["artifact", "event", "memory", "run", "seal", "workspace"];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Field {
    /// Non-empty text, at most 65,536 characters.
    Text,
    /// An identifier: 1-128 of `A-Z a-z 0-9 . _ : -`.
    Id,
    /// A list of up to 256 non-empty texts.
    Texts,
    /// A list of up to 256 identifiers, at least one.
    Ids,
    /// A list of up to 256 distinct references.
    Refs,
    /// One reference.
    Ref,
}

/// `(name, kind, required)` for each field beyond `workspace_id` and `expected_head`.
pub fn fields(event_type: &str) -> Option<&'static [(&'static str, Field, bool)]> {
    use Field::*;
    Some(match event_type {
        "WorkspaceCreated" => &[
            ("title", Text, true),
            ("lab", Id, true),
            ("owners", Ids, true),
        ],
        "WorkspaceObjectiveSet" => &[("objective", Text, true), ("refs", Refs, true)],
        "WorkspaceScopeSet" => &[
            ("authorized", Texts, true),
            ("forbidden", Texts, true),
            ("refs", Refs, true),
        ],
        "WorkspaceNextStepSet" => &[("next_step", Text, true), ("refs", Refs, true)],
        "WorkspaceNoteRecorded" => &[
            ("note_id", Id, true),
            ("text", Text, true),
            ("refs", Refs, true),
        ],
        "WorkspaceDecisionRecorded" => &[
            ("decision_id", Id, true),
            ("text", Text, true),
            ("rationale", Text, true),
            ("refs", Refs, true),
            ("supersedes", Id, false),
        ],
        "WorkspaceQuestionOpened" => &[
            ("question_id", Id, true),
            ("text", Text, true),
            ("refs", Refs, true),
        ],
        "WorkspaceQuestionResolved" => &[
            ("question_id", Id, true),
            ("resolution", Text, true),
            ("refs", Refs, true),
        ],
        "WorkspacePinned" => &[("ref", Ref, true), ("note", Text, false)],
        "WorkspaceUnpinned" => &[("ref", Ref, true)],
        "WorkspaceHandoffSent" => &[
            ("handoff_id", Id, true),
            ("to", Id, true),
            ("summary", Text, true),
            ("next_step", Text, true),
            ("refs", Refs, true),
        ],
        "WorkspaceHandoffReceived" => &[("handoff_id", Id, true)],
        "WorkspaceAgentAttached" => &[
            ("session_id", Id, true),
            ("agent", Id, true),
            ("tool", Id, true),
        ],
        "WorkspaceAgentDetached" => &[("session_id", Id, true), ("outcome", Text, true)],
        "WorkspaceClosed" => &[("outcome", Text, true), ("summary", Text, true)],
        _ => return None,
    })
}

fn is_id(text: &str) -> bool {
    (1..=128).contains(&text.len())
        && text
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'))
}

fn is_sha256_id(text: &str) -> bool {
    text.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64 && hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
    })
}

/// A reference's syntax; whether it exists is the daemon's check at command time.
pub fn is_ref(text: &str) -> bool {
    let Some((kind, identity)) = text.split_once(':') else {
        return false;
    };
    match kind {
        "artifact" | "event" | "memory" | "seal" => is_sha256_id(identity),
        "run" | "workspace" => is_id(identity),
        _ => false,
    }
}

fn text(value: &Value) -> bool {
    value
        .as_str()
        .is_some_and(|s| !s.trim().is_empty() && s.chars().count() <= 65_536)
}

fn check(name: &str, kind: Field, value: &Value) -> Result<(), String> {
    let list = |item: &dyn Fn(&Value) -> bool, min: usize, distinct: bool| -> Result<(), String> {
        let items = value
            .as_array()
            .ok_or_else(|| format!("{name}: must be a list"))?;
        if items.len() < min || items.len() > 256 || !items.iter().all(item) {
            return Err(format!("{name}: invalid list"));
        }
        if distinct {
            let mut seen: Vec<&str> = items.iter().filter_map(Value::as_str).collect();
            seen.sort_unstable();
            if seen.windows(2).any(|w| w[0] == w[1]) {
                return Err(format!("{name}: duplicate entries"));
            }
        }
        Ok(())
    };
    match kind {
        Field::Text if text(value) => Ok(()),
        Field::Id if value.as_str().is_some_and(is_id) => Ok(()),
        Field::Ref if value.as_str().is_some_and(is_ref) => Ok(()),
        Field::Texts => list(&text, 0, false),
        Field::Ids => list(&|v| v.as_str().is_some_and(is_id), 1, true),
        Field::Refs => list(&|v| v.as_str().is_some_and(is_ref), 0, true),
        _ => Err(format!("{name}: invalid {kind:?}")),
    }
}

/// Validates a workspace event payload's shape.
pub fn validate(event_type: &str, payload: &Value) -> Result<(), String> {
    let spec = fields(event_type).ok_or_else(|| format!("{event_type}: not a workspace event"))?;
    let object = payload.as_object().ok_or("payload: must be an object")?;
    let workspace_id = object
        .get("workspace_id")
        .and_then(Value::as_str)
        .unwrap_or("");
    if !is_id(workspace_id) {
        return Err("workspace_id: invalid identifier".into());
    }
    match (
        event_type,
        object.get("expected_head").and_then(Value::as_str),
    ) {
        ("WorkspaceCreated", Some(GENESIS)) => {}
        ("WorkspaceCreated", _) => {
            return Err("expected_head: must be \"genesis\" for WorkspaceCreated".into())
        }
        (_, Some(head)) if is_sha256_id(head) => {}
        _ => return Err("expected_head: the workspace's current HEAD event ID".into()),
    }
    for (name, kind, required) in spec {
        match object.get(*name) {
            Some(value) => check(name, *kind, value)?,
            None if *required => return Err(format!("{name}: required")),
            None => {}
        }
    }
    if event_type == "WorkspaceCreated"
        && object
            .get("owners")
            .and_then(Value::as_array)
            .is_none_or(|owners| {
                owners.len() != 1 || owners[0].as_str() != Some(WORKSPACE_GOVERNOR)
            })
    {
        return Err(format!(
            "owners: must be exactly [{WORKSPACE_GOVERNOR}]; labs and agents participate by handoff"
        ));
    }
    if let Some(extra) = object.keys().find(|k| {
        !matches!(k.as_str(), "workspace_id" | "expected_head")
            && !spec.iter().any(|(n, _, _)| n == k)
    }) {
        return Err(format!("{extra}: not a field of {event_type}"));
    }
    Ok(())
}

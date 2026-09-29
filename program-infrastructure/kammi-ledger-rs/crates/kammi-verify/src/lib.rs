//! Independent verification of a Kammi v2 store (amendment v4 section 6).
//!
//! Shares no code with `kammi-core` or `kammi-store`: segments, frames, packs and loose objects
//! are parsed here from `docs/STORE-V2.md`, and the vocabulary, activation and workspace-chain
//! rules are re-derived from amendment v4. Only `kammi-jcs` (canonical form and strict parsing,
//! which is itself differential-tested against Python's `jcs`) is shared.
//!
//! The store must be at rest (no writer). A torn tail is a failure here: a verification that an
//! activation relies on must cover complete, committed history.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const SEGMENT_MAGIC: &[u8; 8] = b"KMJSEG02";
const PACK_MAGIC: &[u8; 8] = b"KMPACK02";
const EVENT_KEYS: [&str; 8] = [
    "actor",
    "payload_artifact",
    "prev",
    "request_id",
    "schema",
    "seq",
    "type",
    "utc",
];
const ZERO: &str = "sha256:0000000000000000000000000000000000000000000000000000000000000000";

/// The 47 v1 event types (the closed v1 vocabulary), written out independently.
const V1_TYPES: [&str; 47] = [
    "ActorRegistered",
    "AdapterApplied",
    "AdapterRegistered",
    "ArtifactRegistered",
    "AttemptCompleted",
    "AttemptStarted",
    "AttemptStopped",
    "AuthorizationDenied",
    "AuthorizationIssued",
    "ContactRecorded",
    "ExposureClosed",
    "ExposureDenied",
    "ExposureOpened",
    "ExposureRequested",
    "FactRecorded",
    "GrantIssued",
    "LeaseDenied",
    "LeaseExpired",
    "LeaseGranted",
    "LeaseReleased",
    "LeaseRenewed",
    "LeaseRequested",
    "LibraryAccepted",
    "MemoryRecorded",
    "MemoryRetrieved",
    "MemorySuperseded",
    "PanelRegistered",
    "PolicyEvaluated",
    "PolicyRegistered",
    "ProjectionRebuilt",
    "RemoteBundleCreated",
    "RemoteReceiptVerified",
    "RemoteWorkerReturned",
    "RemoteWorkerStarted",
    "ReplayVerified",
    "ResourceRegistered",
    "ResultDeclared",
    "RunCreated",
    "SealCreated",
    "SealVerified",
    "SpecBound",
    "VaultCreated",
    "VaultGenerationSelected",
    "VaultProductPrimarySelected",
    "VaultReaderPositionSet",
    "VaultSourceCommitted",
    "WorkerKeyRegistered",
];
const ACTIVATION: &str = "LibraryVocabularyActivated";
const MEMORY_TYPES: [&str; 3] = ["MemoryRecorded", "MemoryRetrieved", "MemorySuperseded"];

/// Workspace event field sets beyond `workspace_id` and `expected_head`: `(required, optional)`.
fn workspace_fields(kind: &str) -> Option<(&'static [&'static str], &'static [&'static str])> {
    Some(match kind {
        "WorkspaceCreated" => (&["lab", "owners", "title"], &[]),
        "WorkspaceObjectiveSet" => (&["objective", "refs"], &[]),
        "WorkspaceScopeSet" => (&["authorized", "forbidden", "refs"], &[]),
        "WorkspaceNextStepSet" => (&["next_step", "refs"], &[]),
        "WorkspaceNoteRecorded" => (&["note_id", "refs", "text"], &[]),
        "WorkspaceDecisionRecorded" => (
            &["decision_id", "rationale", "refs", "text"],
            &["supersedes"],
        ),
        "WorkspaceQuestionOpened" => (&["question_id", "refs", "text"], &[]),
        "WorkspaceQuestionResolved" => (&["question_id", "refs", "resolution"], &[]),
        "WorkspacePinned" => (&["ref"], &["note"]),
        "WorkspaceUnpinned" => (&["ref"], &[]),
        "WorkspaceHandoffSent" => (&["handoff_id", "next_step", "refs", "summary", "to"], &[]),
        "WorkspaceHandoffReceived" => (&["handoff_id"], &[]),
        "WorkspaceAgentAttached" => (&["agent", "session_id", "tool"], &[]),
        "WorkspaceAgentDetached" => (&["outcome", "session_id"], &[]),
        "WorkspaceClosed" => (&["outcome", "summary"], &[]),
        _ => return None,
    })
}

/// An RFC 3339 UTC time (`Z` or `+00:00`, optional fraction) as a sortable key, so instants
/// written in the main journal's form and the memory journal's form compare correctly.
fn instant(utc: &str) -> String {
    let base = utc
        .strip_suffix('Z')
        .or_else(|| utc.strip_suffix("+00:00"))
        .unwrap_or(utc);
    let (seconds, fraction) = base.split_once('.').unwrap_or((base, ""));
    format!("{seconds}.{:0<9}", &fraction[..fraction.len().min(9)])
}

fn sha256_hex(parts: &[&[u8]]) -> String {
    let mut h = Sha256::new();
    for p in parts {
        h.update(p);
    }
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

pub struct Report {
    pub errors: Vec<String>,
    pub value: Value,
}

struct JournalSummary {
    events: u64,
    head: String,
    /// `(seq, event id, envelope, payload)` in order.
    items: Vec<(u64, String, Value, Value)>,
}

fn read_journal(dir: &Path, errors: &mut Vec<String>, name: &str) -> JournalSummary {
    let mut summary = JournalSummary {
        events: 0,
        head: ZERO.into(),
        items: Vec::new(),
    };
    let Ok(entries) = fs::read_dir(dir) else {
        return summary;
    };
    let mut segments: Vec<PathBuf> = entries
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "seg"))
        .collect();
    segments.sort();
    let mut prev = ZERO.to_string();
    for segment in segments {
        let Ok(bytes) = fs::read(&segment) else {
            errors.push(format!("{name}: unreadable {}", segment.display()));
            continue;
        };
        if bytes.len() < 16 || &bytes[..8] != SEGMENT_MAGIC {
            errors.push(format!("{name}: bad segment header {}", segment.display()));
            continue;
        }
        let first = u64::from_le_bytes(bytes[8..16].try_into().unwrap());
        if first != summary.events + 1 {
            errors.push(format!(
                "{name}: segment {} starts at {first}, expected {}",
                segment.display(),
                summary.events + 1
            ));
        }
        let mut off = 16usize;
        while off < bytes.len() {
            if bytes.len() - off < 4 {
                errors.push(format!("{name}: torn tail in {}", segment.display()));
                break;
            }
            let body_len = u32::from_le_bytes(bytes[off..off + 4].try_into().unwrap()) as usize;
            if body_len == 0 || off + 4 + body_len + 32 > bytes.len() {
                errors.push(format!(
                    "{name}: torn tail in {} at {off}",
                    segment.display()
                ));
                break;
            }
            let body = &bytes[off + 4..off + 4 + body_len];
            let digest = &bytes[off + 4 + body_len..off + 4 + body_len + 32];
            if sha256_hex(&[body])
                != digest
                    .iter()
                    .map(|b| format!("{b:02x}"))
                    .collect::<String>()
            {
                errors.push(format!(
                    "{name}: frame checksum mismatch at seq {}",
                    summary.events + 1
                ));
            }
            off += 4 + body_len + 32;
            if body[0] != 1 || body.len() < 5 {
                errors.push(format!(
                    "{name}: bad frame kind at seq {}",
                    summary.events + 1
                ));
                continue;
            }
            let event_len = u32::from_le_bytes(body[1..5].try_into().unwrap()) as usize;
            if 5 + event_len > body.len() {
                errors.push(format!(
                    "{name}: bad event length at seq {}",
                    summary.events + 1
                ));
                continue;
            }
            let (event_bytes, payload_bytes) = (&body[5..5 + event_len], &body[5 + event_len..]);
            summary.events += 1;
            let seq = summary.events;
            let event_id = format!("sha256:{}", sha256_hex(&[b"kammi-event-v1\0", event_bytes]));
            let event = match kammi_jcs::strict_json(event_bytes) {
                Ok(v) => v,
                Err(e) => {
                    errors.push(format!("{name}: seq {seq}: event is not strict JSON: {e}"));
                    continue;
                }
            };
            let payload = kammi_jcs::strict_json(payload_bytes).unwrap_or(Value::Null);
            if kammi_jcs::canonical(&event).ok().as_deref() != Some(event_bytes) {
                errors.push(format!(
                    "{name}: seq {seq}: event bytes are not canonical JCS"
                ));
            }
            if payload.is_null()
                || kammi_jcs::canonical(&payload).ok().as_deref() != Some(payload_bytes)
            {
                errors.push(format!(
                    "{name}: seq {seq}: payload bytes are not canonical JCS"
                ));
            }
            let keys: Vec<&str> = event
                .as_object()
                .map(|o| o.keys().map(String::as_str).collect())
                .unwrap_or_default();
            if keys != EVENT_KEYS {
                errors.push(format!("{name}: seq {seq}: envelope keys {keys:?}"));
            }
            if event["schema"] != "KAMMI_EVENT_V1"
                || event["seq"].as_u64() != Some(seq)
                || event["prev"].as_str() != Some(prev.as_str())
            {
                errors.push(format!(
                    "{name}: seq {seq}: schema, seq or prev chain broken"
                ));
            }
            if event["payload_artifact"].as_str()
                != Some(format!("sha256:{}", sha256_hex(&[payload_bytes])).as_str())
            {
                errors.push(format!(
                    "{name}: seq {seq}: payload_artifact does not hash the payload"
                ));
            }
            prev = event_id.clone();
            summary.items.push((seq, event_id, event, payload));
        }
    }
    summary.head = prev;
    summary
}

fn verify_objects(root: &Path, errors: &mut Vec<String>) -> HashSet<String> {
    let mut ids = HashSet::new();
    let packs_dir = root.join("objects/packs");
    let mut packs: Vec<PathBuf> = fs::read_dir(&packs_dir)
        .map(|d| {
            d.flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().is_some_and(|x| x == "pack"))
                .collect()
        })
        .unwrap_or_default();
    packs.sort();
    for pack in packs {
        let Ok(bytes) = fs::read(&pack) else {
            errors.push(format!("objects: unreadable {}", pack.display()));
            continue;
        };
        if bytes.len() < 16 || &bytes[..8] != PACK_MAGIC {
            errors.push(format!("objects: bad pack header {}", pack.display()));
            continue;
        }
        let mut off = 16usize;
        while off < bytes.len() {
            if bytes.len() - off < 36 {
                errors.push(format!("objects: torn pack tail {}", pack.display()));
                break;
            }
            let len = u32::from_le_bytes(bytes[off..off + 4].try_into().unwrap()) as usize;
            let id: String = bytes[off + 4..off + 36]
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect();
            if off + 36 + len > bytes.len() {
                errors.push(format!("objects: torn pack record {}", pack.display()));
                break;
            }
            if sha256_hex(&[&bytes[off + 36..off + 36 + len]]) != id {
                errors.push(format!(
                    "objects: pack record sha256:{id} does not hash to its identity"
                ));
            }
            ids.insert(format!("sha256:{id}"));
            off += 36 + len;
        }
    }
    let loose = root.join("objects/sha256");
    for shard in fs::read_dir(&loose).into_iter().flatten().flatten() {
        let prefix = shard.file_name().to_string_lossy().to_string();
        for file in fs::read_dir(shard.path()).into_iter().flatten().flatten() {
            let name = format!("{prefix}{}", file.file_name().to_string_lossy());
            if name.len() != 64 || !name.bytes().all(|b| b.is_ascii_hexdigit()) {
                continue;
            }
            let mut hasher = Sha256::new();
            match fs::File::open(file.path()).and_then(|mut f| std::io::copy(&mut f, &mut hasher)) {
                Ok(_) => {
                    let digest: String = hasher
                        .finalize()
                        .iter()
                        .map(|b| format!("{b:02x}"))
                        .collect();
                    if digest != name {
                        errors.push(format!(
                            "objects: loose sha256:{name} does not hash to its identity"
                        ));
                    }
                }
                Err(e) => errors.push(format!("objects: unreadable loose sha256:{name}: {e}")),
            }
            ids.insert(format!("sha256:{name}"));
        }
    }
    ids
}

fn check_workspaces(main: &JournalSummary, errors: &mut Vec<String>) -> usize {
    let mut heads: HashMap<String, String> = HashMap::new();
    let mut closed: HashSet<String> = HashSet::new();
    for (seq, event_id, event, payload) in &main.items {
        let kind = event["type"].as_str().unwrap_or_default();
        let Some((required, optional)) = workspace_fields(kind) else {
            continue;
        };
        let Some(object) = payload.as_object() else {
            errors.push(format!("main: seq {seq}: {kind} payload is not an object"));
            continue;
        };
        let keys: HashSet<&str> = object.keys().map(String::as_str).collect();
        let all_required = required
            .iter()
            .chain(["workspace_id", "expected_head"].iter())
            .all(|k| keys.contains(k));
        let only_known = keys.iter().all(|k| {
            *k == "workspace_id"
                || *k == "expected_head"
                || required.contains(k)
                || optional.contains(k)
        });
        if !all_required || !only_known {
            errors.push(format!("main: seq {seq}: {kind} fields {keys:?}"));
        }
        let ws = object
            .get("workspace_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let expected = object
            .get("expected_head")
            .and_then(Value::as_str)
            .unwrap_or_default();
        match (kind, heads.get(&ws)) {
            ("WorkspaceCreated", None) if expected == "genesis" => {}
            ("WorkspaceCreated", _) => errors.push(format!(
                "main: seq {seq}: workspace {ws} created twice or without genesis"
            )),
            (_, Some(head)) if head == expected && !closed.contains(&ws) => {}
            (_, Some(_)) if closed.contains(&ws) => {
                errors.push(format!("main: seq {seq}: event on closed workspace {ws}"))
            }
            _ => errors.push(format!("main: seq {seq}: workspace {ws} HEAD chain broken")),
        }
        heads.insert(ws.clone(), event_id.clone());
        if kind == "WorkspaceClosed" {
            closed.insert(ws);
        }
    }
    heads.len()
}

/// Verifies the store at `root`. PASS requires no error at all.
pub fn verify(root: &Path) -> Report {
    let mut errors = Vec::new();
    if fs::read(root.join("STORE.json"))
        .ok()
        .and_then(|b| kammi_jcs::strict_json(&b).ok())
        .and_then(|v| v["schema"].as_str().map(str::to_string))
        .as_deref()
        != Some("KAMMI_STORE_V2")
    {
        errors.push("not a KAMMI_STORE_V2 store".into());
    }
    let main = read_journal(&root.join("journal/main"), &mut errors, "main");
    let memory = read_journal(&root.join("journal/memory"), &mut errors, "memory");
    let objects = verify_objects(root, &mut errors);

    // Vocabulary: v1 always; v4 only after the activation, which is the first v4 event.
    let mut activation: Option<(u64, String, String)> = None;
    let mut counts: BTreeMap<String, u64> = BTreeMap::new();
    for (seq, event_id, event, payload) in &main.items {
        let kind = event["type"].as_str().unwrap_or_default();
        *counts.entry(kind.to_string()).or_default() += 1;
        let v1 = V1_TYPES.contains(&kind) && !MEMORY_TYPES.contains(&kind);
        let v4_main = kind == ACTIVATION || workspace_fields(kind).is_some();
        if !v1 && !v4_main {
            errors.push(format!(
                "main: seq {seq}: {kind} is not a main-journal event type"
            ));
        }
        if kind == ACTIVATION {
            if activation.is_some() {
                errors.push(format!("main: seq {seq}: second activation"));
            }
            let fields_ok = payload["vocabulary"] == "v4"
                && payload["not_before"] == "2026-10-06T00:00:00Z"
                && ["backup", "closure_decision", "verification"]
                    .iter()
                    .all(|f| payload[*f].as_str().is_some_and(|id| objects.contains(id)))
                && payload.as_object().is_some_and(|o| o.len() == 5);
            if !fields_ok {
                errors.push(format!(
                    "main: seq {seq}: activation fields or artifacts invalid"
                ));
            }
            if instant(event["utc"].as_str().unwrap_or_default()) < instant("2026-10-06T00:00:00Z")
            {
                errors.push(format!("main: seq {seq}: activation before 2026-10-06"));
            }
            activation = Some((
                *seq,
                event_id.clone(),
                instant(event["utc"].as_str().unwrap_or_default()),
            ));
        } else if v4_main && activation.is_none() {
            errors.push(format!(
                "main: seq {seq}: {kind} before the vocabulary activation"
            ));
        }
        if kind == "ArtifactRegistered" {
            if let Some(id) = payload["artifact_id"].as_str() {
                if !objects.contains(id) {
                    errors.push(format!(
                        "main: seq {seq}: registered artifact {id} is missing"
                    ));
                }
            }
        }
    }
    for (seq, _, event, _) in &memory.items {
        let kind = event["type"].as_str().unwrap_or_default();
        let allowed = MEMORY_TYPES.contains(&kind)
            || (kind == "MemoryRecordedV2"
                && activation.as_ref().is_some_and(|(_, _, utc)| {
                    instant(event["utc"].as_str().unwrap_or_default()) >= *utc
                }));
        if !allowed {
            errors.push(format!("memory: seq {seq}: {kind} is not allowed here"));
        }
    }
    let receipts = read_journal(&root.join("journal/receipts"), &mut errors, "receipts");
    for (seq, _, event, _) in &receipts.items {
        let after_activation = activation
            .as_ref()
            .is_some_and(|(_, _, utc)| instant(event["utc"].as_str().unwrap_or_default()) >= *utc);
        if event["type"] != "MemoryRetrieved" || !after_activation {
            errors.push(format!(
                "receipts: seq {seq}: only MemoryRetrieved after the activation belongs here"
            ));
        }
    }
    let workspaces = check_workspaces(&main, &mut errors);
    let value = json!({
        "schema": "KAMMI_RUST_INDEPENDENT_VERIFY_V1",
        "verifier": "kammi-verify (shares no code with kammi-core or kammi-store)",
        "status": if errors.is_empty() { "PASS" } else { "FAIL" },
        "journal_head": main.head, "journal_events": main.events,
        "memory_head": memory.head, "memory_events": memory.events,
        "receipts_head": receipts.head, "receipts_events": receipts.events,
        "objects_verified": objects.len(),
        "vocabulary_v4": activation.as_ref().map(|(seq, id, _)| json!({"seq": seq, "event": id})),
        "workspaces": workspaces,
        "event_types": counts,
        "errors": errors.iter().take(50).cloned().collect::<Vec<_>>(),
        "error_count": errors.len(),
    });
    Report { errors, value }
}

#[cfg(test)]
mod tests {
    use super::instant;

    #[test]
    fn instants_compare_across_journal_timestamp_forms() {
        assert_eq!(instant("2026-10-07T09:00:00Z"), instant("2026-10-07T09:00:00+00:00"));
        assert_eq!(instant("2026-10-07T09:00:00.5Z"), instant("2026-10-07T09:00:00.500000+00:00"));
        assert!(instant("2026-10-07T09:00:00+00:00") > instant("2026-10-06T23:59:59.999999Z"));
        assert!(instant("2026-10-07T09:00:00.000001+00:00") > instant("2026-10-07T09:00:00Z"));
    }
}

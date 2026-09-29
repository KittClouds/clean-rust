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

fn valid_utc(utc: &str) -> bool {
    let base = utc.strip_suffix('Z').or_else(|| utc.strip_suffix("+00:00"));
    let Some(base) = base else { return false };
    let (whole, fraction) = base.split_once('.').unwrap_or((base, ""));
    whole.len() == 19
        && whole.as_bytes()[4] == b'-'
        && whole.as_bytes()[7] == b'-'
        && whole.as_bytes()[10] == b'T'
        && whole.as_bytes()[13] == b':'
        && whole.as_bytes()[16] == b':'
        && whole.bytes().enumerate().all(|(i, b)| {
            matches!(i, 4 | 7) && b == b'-'
                || i == 10 && b == b'T'
                || matches!(i, 13 | 16) && b == b':'
                || matches!(i, 0..=3 | 5..=6 | 8..=9 | 11..=12 | 14..=15 | 17..=18)
                    && b.is_ascii_digit()
        })
        && (fraction.is_empty()
            || (fraction.len() <= 9 && fraction.bytes().all(|b| b.is_ascii_digit())))
}

fn sha256_hex(parts: &[&[u8]]) -> String {
    let mut h = Sha256::new();
    for p in parts {
        h.update(p);
    }
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

/// Independently reconstruct the path/size/content-hash commitment used by the backup tool.
fn backup_inventory_matches(
    manifest: &Value,
    expected_hash: &str,
    expected_count: u64,
    expected_bytes: u64,
) -> bool {
    let Some(files) = manifest["files"].as_array() else {
        return false;
    };
    if files.len() as u64 != expected_count
        || manifest["file_count"].as_u64() != Some(expected_count)
        || manifest["total_bytes"].as_u64() != Some(expected_bytes)
    {
        return false;
    }
    let mut hash_input = Vec::new();
    let mut prior_path: Option<&str> = None;
    let mut total_bytes = 0u64;
    for file in files {
        let (Some(path), Some(bytes), Some(content_hash)) = (
            file["path"].as_str(),
            file["bytes"].as_u64(),
            file["sha256"].as_str(),
        ) else {
            return false;
        };
        if path.is_empty()
            || path.starts_with('/')
            || path.contains('\\')
            || path
                .split('/')
                .any(|part| part.is_empty() || part == "." || part == "..")
            || prior_path.is_some_and(|previous| previous >= path)
            || content_hash.len() != 64
            || !content_hash
                .bytes()
                .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
        {
            return false;
        }
        let Some(next_total) = total_bytes.checked_add(bytes) else {
            return false;
        };
        total_bytes = next_total;
        prior_path = Some(path);
        hash_input.extend_from_slice(path.as_bytes());
        hash_input.push(0);
        hash_input.extend_from_slice(bytes.to_string().as_bytes());
        hash_input.push(0);
        hash_input.extend_from_slice(content_hash.as_bytes());
        hash_input.push(b'\n');
    }
    total_bytes == expected_bytes && sha256_hex(&[&hash_input]) == expected_hash
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

fn read_object_bytes(root: &Path, id: &str) -> Option<Vec<u8>> {
    let hex = id.strip_prefix("sha256:")?;
    if hex.len() != 64 {
        return None;
    }
    let loose = root.join("objects/sha256").join(&hex[..2]).join(&hex[2..]);
    if let Ok(bytes) = fs::read(loose) {
        return Some(bytes);
    }
    let mut packs: Vec<PathBuf> = fs::read_dir(root.join("objects/packs"))
        .ok()?
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "pack"))
        .collect();
    packs.sort();
    for pack in packs {
        let bytes = fs::read(pack).ok()?;
        if bytes.len() < 16 || &bytes[..8] != PACK_MAGIC {
            continue;
        }
        let mut off = 16usize;
        while off + 36 <= bytes.len() {
            let len = u32::from_le_bytes(bytes[off..off + 4].try_into().ok()?) as usize;
            if off + 36 + len > bytes.len() {
                break;
            }
            if bytes[off + 4..off + 36]
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>()
                == hex
            {
                return Some(bytes[off + 36..off + 36 + len].to_vec());
            }
            off += 36 + len;
        }
    }
    None
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
        if kind == "WorkspaceCreated" && payload["owners"] != json!(["chief-kammi"]) {
            errors.push(format!(
                "main: seq {seq}: Chief Kammi must be the sole workspace owner"
            ));
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
    let mut registered_artifacts = HashSet::new();
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
            let artifact_ids_ok = [
                "amendment",
                "backup",
                "closure_decision",
                "monitoring_snapshot",
                "rollback_evidence",
                "verification",
            ]
            .iter()
            .all(|field| {
                payload[*field]
                    .as_str()
                    .is_some_and(|id| objects.contains(id) && registered_artifacts.contains(id))
            });
            let effective_at = payload["effective_at"].as_str().unwrap_or_default();
            let amendment_id = payload["amendment"].as_str().unwrap_or_default();
            let closure_id = payload["closure_decision"].as_str().unwrap_or_default();
            let backup_id = payload["backup"].as_str().unwrap_or_default();
            let monitoring_id = payload["monitoring_snapshot"].as_str().unwrap_or_default();
            let rollback_id = payload["rollback_evidence"].as_str().unwrap_or_default();
            let amendment = read_object_bytes(root, amendment_id)
                .and_then(|bytes| kammi_jcs::strict_json(&bytes).ok());
            let closure = read_object_bytes(root, closure_id)
                .and_then(|bytes| kammi_jcs::strict_json(&bytes).ok());
            let backup = read_object_bytes(root, backup_id)
                .and_then(|bytes| kammi_jcs::strict_json(&bytes).ok());
            let rollback = read_object_bytes(root, rollback_id)
                .and_then(|bytes| kammi_jcs::strict_json(&bytes).ok());
            let inventory_id = backup
                .as_ref()
                .and_then(|doc| doc["inventory_artifact"].as_str())
                .unwrap_or_default();
            let inventory_registered =
                objects.contains(inventory_id) && registered_artifacts.contains(inventory_id);
            let inventory = read_object_bytes(root, inventory_id)
                .and_then(|bytes| kammi_jcs::strict_json(&bytes).ok());
            let backup_ok = backup.as_ref().is_some_and(|doc| {
                let count = doc["file_count"].as_u64().unwrap_or_default();
                let total_bytes = doc["total_bytes"].as_u64().unwrap_or_default();
                let inventory_hash = doc["inventory_sha256"].as_str().unwrap_or_default();
                let source_head = doc["source_head"].as_str().unwrap_or_default();
                doc["schema"] == "KAMMI_PRE_ACTIVATION_BACKUP_V2"
                    && doc["source_head"]
                        .as_str()
                        .is_some_and(|head| head.starts_with("sha256:"))
                    && count > 0
                    && total_bytes > 0
                    && inventory_hash.len() == 64
                    && doc["kammi_verify"]["status"] == "PASS"
                    && doc["kammi_verify"]["journal_head"] == source_head
                    && doc["python_export_verify"]["status"] == "PASS"
                    && doc["python_export_verify"]["journal_head"] == source_head
                    && inventory_registered
                    && inventory.as_ref().is_some_and(|manifest| {
                        manifest["schema"] == "KAMMI_BACKUP_INVENTORY_V1"
                            && manifest["inventory_sha256"] == inventory_hash
                            && backup_inventory_matches(
                                manifest,
                                inventory_hash,
                                count,
                                total_bytes,
                            )
                    })
            });
            let monitor_bytes = read_object_bytes(root, monitoring_id);
            let monitor_rows: Vec<Value> = monitor_bytes
                .as_deref()
                .unwrap_or_default()
                .split(|byte| *byte == b'\n')
                .filter(|line| !line.is_empty())
                .filter_map(|line| kammi_jcs::strict_json(line).ok())
                .collect();
            let actual_warnings = monitor_rows
                .iter()
                .filter(|row| row["warning"].as_bool() != Some(false))
                .count() as u64;
            let latest_monitor_utc = monitor_rows
                .last()
                .and_then(|row| row["utc"].as_str())
                .unwrap_or_default();
            let monitor_audit_ok = closure.as_ref().is_some_and(|doc| {
                let audit = &doc["monitoring_audit"];
                audit["snapshot_artifact"] == monitoring_id
                    && audit["snapshot_sha256"]
                        == monitoring_id.strip_prefix("sha256:").unwrap_or_default()
                    && audit["sample_count"].as_u64() == Some(monitor_rows.len() as u64)
                    && audit["warning_count"].as_u64() == Some(actual_warnings)
                    && audit["latest_sample_utc"] == latest_monitor_utc
                    && audit["gap_count"].as_u64().is_some()
                    && audit["max_gap_seconds"].as_u64().is_some()
                    && audit["latest_sample_fresh"] == true
                    && audit["scheduled_backup_configured"].as_bool().is_some()
                    && audit["monitor_requires_interactive_logon"]
                        .as_bool()
                        .is_some()
                    && audit["daemon_autostart_configured"].as_bool().is_some()
                    && !monitor_rows.is_empty()
            });
            let risk_ok = closure.as_ref().is_some_and(|decision| {
                let risk = &decision["risk_acceptance"];
                [
                    "early_activation",
                    "known_monitoring_gaps",
                    "known_rollback_evidence",
                    "fix_forward",
                    "rollback_to_python_ends",
                    "backup_policy_reviewed",
                    "monitoring_policy_reviewed",
                    "restart_policy_reviewed",
                    "source_publicity_reviewed",
                ]
                .iter()
                .all(|field| risk[*field] == true)
            });
            let docs_ok = amendment.as_ref().is_some_and(|doc| {
                doc["schema"] == "KAMMI_V4_EARLY_ACTIVATION_AMENDMENT_V1"
                    && doc["decision_authority"] == "PROGRAM_OWNER"
                    && doc["effective_at"] == effective_at
                    && doc["removes_fixed_floor"] == true
            }) && closure.as_ref().is_some_and(|doc| {
                doc["schema"] == "KAMMI_ROLLBACK_WINDOW_CLOSURE_V2"
                    && doc["decision"] == "CLOSE"
                    && doc["decision_authority"] == "PROGRAM_OWNER"
                    && doc["amendment_artifact"] == amendment_id
                    && doc["monitoring_snapshot_artifact"] == monitoring_id
                    && doc["rollback_evidence_artifact"] == rollback_id
                    && doc["effective_at"] == effective_at
            }) && backup_ok
                && rollback.as_ref().is_some_and(|doc| {
                    doc["schema"] == "KAMMI_ROLLBACK_EVIDENCE_AUDIT_V1"
                        && doc["rollback_available"] == true
                        && doc["previous_release_rollback_proven"] == true
                        && doc["release_reports_valid"] == true
                        && doc["python_verification"]["status"] == "PASS"
                });
            let fields_ok = payload["vocabulary"] == "v4"
                && valid_utc(effective_at)
                && instant(event["utc"].as_str().unwrap_or_default()) >= instant(effective_at)
                && payload.as_object().is_some_and(|o| o.len() == 8)
                && artifact_ids_ok
                && docs_ok
                && monitor_audit_ok
                && risk_ok;
            if !fields_ok {
                errors.push(format!(
                    "main: seq {seq}: activation fields, registered artifacts, owner decision or risk acceptance invalid"
                ));
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
                } else {
                    registered_artifacts.insert(id.to_string());
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
        assert_eq!(
            instant("2026-10-07T09:00:00Z"),
            instant("2026-10-07T09:00:00+00:00")
        );
        assert_eq!(
            instant("2026-10-07T09:00:00.5Z"),
            instant("2026-10-07T09:00:00.500000+00:00")
        );
        assert!(instant("2026-10-07T09:00:00+00:00") > instant("2026-10-06T23:59:59.999999Z"));
        assert!(instant("2026-10-07T09:00:00.000001+00:00") > instant("2026-10-07T09:00:00Z"));
    }
}

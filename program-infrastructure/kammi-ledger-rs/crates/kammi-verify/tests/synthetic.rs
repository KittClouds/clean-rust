//! Hand-built stores (no kammi-store): the v4 rules are checked by themselves, on journals whose
//! hashes and chain are otherwise perfect.

use std::path::Path;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn sha(parts: &[&[u8]]) -> [u8; 32] {
    let mut h = Sha256::new();
    for p in parts {
        h.update(p);
    }
    h.finalize().into()
}

struct Builder {
    frames: Vec<u8>,
    seq: u64,
    prev: String,
    pack: Vec<u8>,
}

impl Builder {
    fn new() -> Self {
        let mut pack = b"KMPACK02".to_vec();
        pack.extend_from_slice(&1u64.to_le_bytes());
        Builder {
            frames: Vec::new(),
            seq: 0,
            prev: format!("sha256:{}", "0".repeat(64)),
            pack,
        }
    }

    fn object(&mut self, bytes: &[u8]) -> String {
        let id = sha(&[bytes]);
        self.pack
            .extend_from_slice(&(bytes.len() as u32).to_le_bytes());
        self.pack.extend_from_slice(&id);
        self.pack.extend_from_slice(bytes);
        format!("sha256:{}", hex(&id))
    }

    fn event(&mut self, kind: &str, payload: Value, utc: &str) -> String {
        self.seq += 1;
        let payload_bytes = kammi_jcs::canonical(&payload).unwrap();
        let event = json!({"schema": "KAMMI_EVENT_V1", "seq": self.seq, "prev": self.prev, "type": kind,
            "payload_artifact": format!("sha256:{}", hex(&sha(&[&payload_bytes]))), "actor": "admin",
            "request_id": format!("r{}", self.seq), "utc": utc});
        let event_bytes = kammi_jcs::canonical(&event).unwrap();
        let mut body = vec![1u8];
        body.extend_from_slice(&(event_bytes.len() as u32).to_le_bytes());
        body.extend_from_slice(&event_bytes);
        body.extend_from_slice(&payload_bytes);
        self.frames
            .extend_from_slice(&(body.len() as u32).to_le_bytes());
        self.frames.extend_from_slice(&body);
        self.frames.extend_from_slice(&sha(&[&body]));
        self.prev = format!("sha256:{}", hex(&sha(&[b"kammi-event-v1\0", &event_bytes])));
        self.prev.clone()
    }

    fn register(&mut self, bytes: &[u8]) -> String {
        let id = self.object(bytes);
        self.event(
            "ArtifactRegistered",
            json!({"artifact_id": id, "bytes": bytes.len(), "kind": "x"}),
            "2026-10-07T00:00:00Z",
        );
        id
    }

    fn write(&self, root: &Path) {
        std::fs::create_dir_all(root.join("journal/main")).unwrap();
        std::fs::create_dir_all(root.join("journal/memory")).unwrap();
        std::fs::create_dir_all(root.join("objects/packs")).unwrap();
        std::fs::write(
            root.join("STORE.json"),
            br#"{"schema":"KAMMI_STORE_V2","version":1}"#,
        )
        .unwrap();
        let mut segment = b"KMJSEG02".to_vec();
        segment.extend_from_slice(&1u64.to_le_bytes());
        segment.extend_from_slice(&self.frames);
        std::fs::write(root.join("journal/main/seg-00000001.seg"), segment).unwrap();
        std::fs::write(root.join("objects/packs/pack-00000001.pack"), &self.pack).unwrap();
    }
}

fn activated() -> Builder {
    let mut b = Builder::new();
    let decision = b.register(b"decision");
    let backup = b.register(b"backup");
    let verification = b.register(b"verification");
    b.event(
        "LibraryVocabularyActivated",
        json!({"vocabulary": "v4", "not_before": "2026-10-06T00:00:00Z",
        "closure_decision": decision, "verification": verification, "backup": backup}),
        "2026-10-07T00:00:00Z",
    );
    b
}

fn verify(b: &Builder) -> kammi_verify::Report {
    let dir = tempfile::tempdir().unwrap();
    b.write(dir.path());
    kammi_verify::verify(dir.path())
}

fn created(b: &mut Builder) -> String {
    b.event("WorkspaceCreated", json!({"workspace_id": "w", "expected_head": "genesis", "title": "t", "lab": "l", "owners": ["o"]}), "2026-10-07T01:00:00Z")
}

#[test]
fn a_well_formed_v4_store_passes() {
    let mut b = activated();
    let head = created(&mut b);
    b.event("WorkspaceNoteRecorded", json!({"workspace_id": "w", "expected_head": head, "note_id": "n", "text": "t", "refs": []}), "2026-10-07T01:01:00Z");
    let r = verify(&b);
    assert!(r.errors.is_empty(), "{:?}", r.errors);
    assert_eq!(r.value["workspaces"], 1);
}

#[test]
fn a_broken_workspace_chain_fails_even_with_perfect_hashes() {
    let mut b = activated();
    created(&mut b);
    b.event("WorkspaceNoteRecorded", json!({"workspace_id": "w", "expected_head": format!("sha256:{}", "1".repeat(64)), "note_id": "n", "text": "t", "refs": []}), "2026-10-07T01:01:00Z");
    let r = verify(&b);
    assert!(
        r.errors.iter().any(|e| e.contains("HEAD chain broken")),
        "{:?}",
        r.errors
    );
}

#[test]
fn v4_before_activation_and_unknown_types_fail() {
    let mut b = Builder::new();
    created(&mut b);
    b.event("NoSuchEvent", json!({}), "2026-10-07T01:00:00Z");
    let r = verify(&b);
    assert!(
        r.errors
            .iter()
            .any(|e| e.contains("before the vocabulary activation")),
        "{:?}",
        r.errors
    );
    assert!(
        r.errors.iter().any(|e| e.contains("NoSuchEvent")),
        "{:?}",
        r.errors
    );
}

#[test]
fn an_early_or_malformed_activation_fails() {
    let mut b = Builder::new();
    let a = b.register(b"a");
    b.event(
        "LibraryVocabularyActivated",
        json!({"vocabulary": "v4", "not_before": "2026-10-06T00:00:00Z",
        "closure_decision": a, "verification": a, "backup": format!("sha256:{}", "2".repeat(64))}),
        "2026-10-05T00:00:00Z",
    );
    let r = verify(&b);
    assert!(
        r.errors.iter().any(|e| e.contains("before 2026-10-06")),
        "{:?}",
        r.errors
    );
    assert!(
        r.errors.iter().any(|e| e.contains("artifacts invalid")),
        "{:?}",
        r.errors
    );
}

#[test]
fn events_after_close_fail() {
    let mut b = activated();
    let head = created(&mut b);
    let closed = b.event(
        "WorkspaceClosed",
        json!({"workspace_id": "w", "expected_head": head, "outcome": "o", "summary": "s"}),
        "2026-10-07T02:00:00Z",
    );
    b.event("WorkspaceNoteRecorded", json!({"workspace_id": "w", "expected_head": closed, "note_id": "n", "text": "t", "refs": []}), "2026-10-07T02:01:00Z");
    let r = verify(&b);
    assert!(
        r.errors.iter().any(|e| e.contains("closed workspace")),
        "{:?}",
        r.errors
    );
}

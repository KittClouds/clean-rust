//! Amendment v4 in the core: journaled activation, workspace commands, replay identity.

use std::sync::Arc;

use kammi_core::ops_workspace::{Principal, PACKET_BUDGET};
use kammi_core::time::parse_utc;
use kammi_core::{FlightIdentity, Ledger, LedgerError, LedgerOptions, ManualClock};
use kammi_store::{Store, StoreOptions};
use serde_json::{json, Value};

const ADMIN: Principal<'static> = Principal::Admin("admin");
const CHIEF: Principal<'static> = Principal::Actor("chief-kammi");
const REVIEWER: Principal<'static> = Principal::Actor("reviewer");

fn open(root: &std::path::Path, clock: &ManualClock) -> Ledger {
    let store = if root.join("STORE.json").exists() {
        Store::open(root, StoreOptions::default())
    } else {
        Store::create(root, StoreOptions::default())
    }
    .unwrap();
    Ledger::open(
        store,
        LedgerOptions {
            clock: Arc::new(clock.clone()),
            signing_key: None,
            embedder: None,
            flight: FlightIdentity {
                architecture: "test".into(),
                source_root: "test".into(),
                runtime_identity: "test".into(),
            },
            writer: json!({"test": true}),
        },
    )
    .unwrap()
}

fn clock(at: &str) -> ManualClock {
    ManualClock::new(parse_utc(at).unwrap())
}

fn setup(ledger: &mut Ledger) {
    for (actor, lab) in [
        ("chief-kammi", "kammi-ops"),
        ("reviewer", "fabrique"),
        ("outsider", "elsewhere"),
    ] {
        ledger
            .register_actor(
                actor,
                "agent",
                lab,
                &"a".repeat(64),
                &format!("actor-{actor}"),
            )
            .unwrap();
    }
}

/// Registers the closure decision, the backup manifest, then a verification of the head just
/// before its own registration, and returns the activation payload.
fn activation_payload(ledger: &mut Ledger, decision: &str) -> Value {
    let n = ledger.store.main.seq();
    let (closure, _) = ledger.register_bytes(json!({"schema": "KAMMI_ROLLBACK_WINDOW_CLOSURE_V1", "decision": decision, "decided_by": "user", "n": n}).to_string().as_bytes(), "decision", "admin", &format!("closure-{n}")).unwrap();
    let (backup, _) = ledger
        .register_bytes(
            json!({"backup": "manifest", "n": n}).to_string().as_bytes(),
            "backup",
            "admin",
            &format!("backup-{n}"),
        )
        .unwrap();
    let head = ledger.store.main.head().to_string();
    let (verification, _) = ledger
        .register_bytes(
            json!({"status": "PASS", "journal_head": head, "verifier": "kammi-verify"})
                .to_string()
                .as_bytes(),
            "verification",
            "admin",
            &format!("verify-{n}"),
        )
        .unwrap();
    json!({"vocabulary": "v4", "not_before": "2026-10-06T00:00:00Z", "closure_decision": closure, "verification": verification, "backup": backup})
}

fn activate(ledger: &mut Ledger) {
    let payload = activation_payload(ledger, "CLOSE");
    ledger
        .activate_vocabulary(payload, "admin", "activate-v4")
        .unwrap();
}

fn cmd(
    ledger: &mut Ledger,
    kind: &str,
    payload: Value,
    who: Principal<'_>,
    request: &str,
) -> Result<Value, LedgerError> {
    ledger.workspace_command(kind, payload, who, request)
}

fn head(ledger: &Ledger, ws: &str) -> String {
    ledger.state.workspaces.map[ws].head().to_string()
}

#[test]
fn v4_is_refused_until_the_journaled_activation() {
    let dir = tempfile::tempdir().unwrap();
    let c = clock("2026-10-07T00:00:00Z");
    let mut ledger = open(dir.path(), &c);
    setup(&mut ledger);
    let created = json!({"workspace_id": "ws", "expected_head": "genesis", "title": "t", "lab": "kammi-ops", "owners": ["chief-kammi"]});
    let error = cmd(
        &mut ledger,
        "WorkspaceCreated",
        created.clone(),
        ADMIN,
        "create",
    )
    .unwrap_err();
    assert!(error.detail().contains("not active"), "{}", error.detail());
    // Replay refuses a v4 event that predates activation, whatever its source.
    let error = ledger
        .state
        .apply("WorkspaceCreated", &created, "sha256:00", &|_| None)
        .unwrap_err();
    assert!(error.detail().contains("requires vocabulary v4"));
    assert!(ledger
        .state
        .apply("NoSuchEvent", &json!({}), "sha256:00", &|_| None)
        .is_err());
}

#[test]
fn activation_is_dated_decided_verified_and_one_way() {
    let dir = tempfile::tempdir().unwrap();
    let c = clock("2026-10-01T00:00:00Z");
    let mut ledger = open(dir.path(), &c);
    setup(&mut ledger);
    let early = activation_payload(&mut ledger, "CLOSE");
    assert!(ledger
        .activate_vocabulary(early.clone(), "admin", "a1")
        .unwrap_err()
        .detail()
        .contains("cannot close before"));
    c.set(parse_utc("2026-10-06T00:00:00Z").unwrap());
    let keep = activation_payload(&mut ledger, "KEEP_OPEN");
    assert!(ledger
        .activate_vocabulary(keep, "admin", "a2")
        .unwrap_err()
        .detail()
        .contains("deciding CLOSE"));
    // `early` was verified before later events: its verification is no longer the latest event.
    assert!(ledger
        .activate_vocabulary(early, "admin", "a3")
        .unwrap_err()
        .detail()
        .contains("latest event"));
    let good = activation_payload(&mut ledger, "CLOSE");
    let event = ledger
        .activate_vocabulary(good.clone(), "admin", "a4")
        .unwrap();
    assert_eq!(
        ledger
            .activate_vocabulary(good.clone(), "admin", "a4")
            .unwrap(),
        event,
        "retry is idempotent"
    );
    assert!(ledger
        .activate_vocabulary(good, "admin", "a5")
        .unwrap_err()
        .detail()
        .contains("already active"));
    drop(ledger);
    let reopened = open(dir.path(), &c);
    assert_eq!(
        reopened.state.vocabulary_v4.as_deref(),
        Some(event.as_str()),
        "activation replays"
    );
}

#[test]
fn workspace_life_cycle_and_replay_identity() {
    let dir = tempfile::tempdir().unwrap();
    let c = clock("2026-10-07T09:00:00Z");
    let mut ledger = open(dir.path(), &c);
    setup(&mut ledger);
    let (evidence, _) = ledger
        .register_bytes(b"reviewer packet", "evidence", "admin", "evidence")
        .unwrap();
    activate(&mut ledger);
    let ws = "frozen-fabrique.e4-0";
    let created = cmd(&mut ledger, "WorkspaceCreated", json!({"workspace_id": ws, "expected_head": "genesis", "title": "Frozen Fabrique E4-0", "lab": "frozen-fabrique", "owners": ["chief-kammi"]}), ADMIN, "ws-create").unwrap();
    assert!(cmd(&mut ledger, "WorkspaceCreated", json!({"workspace_id": "x", "expected_head": "genesis", "title": "t", "lab": "l", "owners": ["chief-kammi"]}), CHIEF, "x").is_err(), "only admin creates");
    let h = created["head"].as_str().unwrap().to_string();
    cmd(&mut ledger, "WorkspaceObjectiveSet", json!({"workspace_id": ws, "expected_head": h, "objective": "Reach a single scoped E4-0 scoring decision", "refs": [format!("artifact:{evidence}")]}), CHIEF, "objective").unwrap();
    let h = head(&ledger, ws);
    cmd(&mut ledger, "WorkspaceScopeSet", json!({"workspace_id": ws, "expected_head": h, "authorized": ["bookkeeping on the E4-0 record"], "forbidden": ["open protected labels", "enter E4-01"], "refs": []}), CHIEF, "scope").unwrap();
    let h = head(&ledger, ws);
    cmd(&mut ledger, "WorkspaceHandoffSent", json!({"workspace_id": ws, "expected_head": h, "handoff_id": "h-review", "to": "reviewer", "summary": "Review the scoring packet", "next_step": "Return READY or BLOCKED", "refs": [format!("artifact:{evidence}")]}), CHIEF, "handoff").unwrap();

    // The outsider may not write; the handoff recipient may take part but not set scope.
    let h = head(&ledger, ws);
    assert!(cmd(
        &mut ledger,
        "WorkspaceNoteRecorded",
        json!({"workspace_id": ws, "expected_head": h, "note_id": "n0", "text": "hi", "refs": []}),
        Principal::Actor("outsider"),
        "n0"
    )
    .is_err());
    assert!(cmd(
        &mut ledger,
        "WorkspaceObjectiveSet",
        json!({"workspace_id": ws, "expected_head": h, "objective": "other", "refs": []}),
        REVIEWER,
        "o2"
    )
    .is_err());
    let attached = cmd(&mut ledger, "WorkspaceAgentAttached", json!({"workspace_id": ws, "expected_head": h, "session_id": "s1", "agent": "reviewer", "tool": "claude-subagent"}), REVIEWER, "attach").unwrap();

    // Stale HEAD: 409 with the current HEAD; a retry of the committed request replays.
    let stale = cmd(&mut ledger, "WorkspaceNoteRecorded", json!({"workspace_id": ws, "expected_head": h, "note_id": "n1", "text": "late", "refs": []}), REVIEWER, "n1-stale").unwrap_err();
    match stale {
        LedgerError::Conflict(detail) => assert_eq!(detail["head"], attached["head"]),
        other => panic!("expected a conflict, got {other:?}"),
    }
    let again = cmd(&mut ledger, "WorkspaceAgentAttached", json!({"workspace_id": ws, "expected_head": h, "session_id": "s1", "agent": "reviewer", "tool": "claude-subagent"}), REVIEWER, "attach").unwrap();
    assert_eq!(
        (again["event_id"].clone(), again["replayed"].clone()),
        (attached["event_id"].clone(), json!(true))
    );

    let h = head(&ledger, ws);
    assert!(cmd(&mut ledger, "WorkspacePinned", json!({"workspace_id": ws, "expected_head": h, "ref": "artifact:sha256:".to_string() + &"9".repeat(64)}), REVIEWER, "pin-bad").unwrap_err().detail().contains("unknown reference"));
    cmd(&mut ledger, "WorkspacePinned", json!({"workspace_id": ws, "expected_head": h, "ref": format!("artifact:{evidence}"), "note": "the packet under review"}), REVIEWER, "pin").unwrap();
    let h = head(&ledger, ws);
    cmd(
        &mut ledger,
        "WorkspaceHandoffReceived",
        json!({"workspace_id": ws, "expected_head": h, "handoff_id": "h-review"}),
        REVIEWER,
        "receive",
    )
    .unwrap();
    let h = head(&ledger, ws);
    cmd(&mut ledger, "WorkspaceDecisionRecorded", json!({"workspace_id": ws, "expected_head": h, "decision_id": "d1", "text": "READY for scoped scoring authorization", "rationale": "bindings match", "refs": [format!("event:{}", attached["event_id"].as_str().unwrap())]}), REVIEWER, "decide").unwrap();
    let h = head(&ledger, ws);
    cmd(&mut ledger, "WorkspaceNextStepSet", json!({"workspace_id": ws, "expected_head": h, "next_step": "Chief prepares the scoped scoring grant", "refs": []}), CHIEF, "next").unwrap();

    let packet = ledger.work_packet(ws).unwrap();
    let text = packet["text"].as_str().unwrap();
    for needle in [
        "OBJECTIVE Reach a single scoped",
        "DO NOT",
        "  - enter E4-01",
        "NEXT STEP Chief prepares",
        "d1: READY",
        "ATTACHED",
        "PINNED",
    ] {
        assert!(text.contains(needle), "packet lacks {needle}:\n{text}");
    }
    assert!(
        !text.contains("PENDING HANDOFFS"),
        "a received handoff is not pending"
    );
    assert!(
        text.lines()
            .filter(|l| !l.is_empty() && !l.ends_with(':'))
            .all(|l| l.contains("[e:")
                || l.starts_with("HEAD")
                || l.ends_with("(not set)")
                || !l.starts_with("  ")
                    && l.chars()
                        .all(|c| c.is_ascii_uppercase() || c == ' ' || c == '/')),
        "every content line cites an event:\n{text}"
    );
    let view = ledger.workspace_view(ws).unwrap();

    let h = head(&ledger, ws);
    cmd(&mut ledger, "WorkspaceClosed", json!({"workspace_id": ws, "expected_head": h, "outcome": "handed to scoring", "summary": "review complete"}), CHIEF, "close").unwrap();
    let h = head(&ledger, ws);
    assert!(cmd(&mut ledger, "WorkspaceNoteRecorded", json!({"workspace_id": ws, "expected_head": h, "note_id": "n9", "text": "after", "refs": []}), CHIEF, "n9").unwrap_err().detail().contains("closed"));
    let closed_packet = serde_json::to_string(&ledger.work_packet(ws).unwrap()).unwrap();
    let closed_view = serde_json::to_string(&ledger.workspace_view(ws).unwrap()).unwrap();
    assert_ne!(serde_json::to_string(&view).unwrap(), closed_view);

    drop(ledger);
    let replayed = open(dir.path(), &c);
    assert_eq!(
        serde_json::to_string(&replayed.work_packet(ws).unwrap()).unwrap(),
        closed_packet,
        "packet identical after replay"
    );
    assert_eq!(
        serde_json::to_string(&replayed.workspace_view(ws).unwrap()).unwrap(),
        closed_view,
        "state identical after replay"
    );
}

#[test]
fn the_packet_stays_inside_its_budget() {
    let dir = tempfile::tempdir().unwrap();
    let c = clock("2026-10-07T09:00:00Z");
    let mut ledger = open(dir.path(), &c);
    setup(&mut ledger);
    activate(&mut ledger);
    let ws = "busy";
    cmd(&mut ledger, "WorkspaceCreated", json!({"workspace_id": ws, "expected_head": "genesis", "title": "busy", "lab": "kammi-ops", "owners": ["chief-kammi"]}), ADMIN, "create").unwrap();
    for i in 0..120 {
        let h = head(&ledger, ws);
        cmd(&mut ledger, "WorkspaceNoteRecorded", json!({"workspace_id": ws, "expected_head": h, "note_id": format!("n{i}"), "text": "long note ".repeat(40), "refs": []}), CHIEF, &format!("n{i}")).unwrap();
    }
    let packet = ledger.work_packet(ws).unwrap();
    let text = packet["text"].as_str().unwrap();
    assert!(
        text.len() <= PACKET_BUDGET && packet["within_budget"] == true,
        "{} bytes",
        text.len()
    );
    assert!(text.contains("older omitted"));
}

/// Random command sequences (a fixed-seed generator, so failures reproduce): refused commands
/// never touch the journal, successes add exactly one event, retries replay, and replay
/// reproduces every workspace byte for byte.
#[test]
fn random_command_sequences_keep_every_invariant() {
    let dir = tempfile::tempdir().unwrap();
    let c = clock("2026-10-07T09:00:00Z");
    let mut ledger = open(dir.path(), &c);
    setup(&mut ledger);
    let (evidence, _) = ledger
        .register_bytes(b"evidence", "evidence", "admin", "evidence")
        .unwrap();
    activate(&mut ledger);
    let workspaces = ["w0", "w1", "w2"];
    for ws in workspaces {
        cmd(&mut ledger, "WorkspaceCreated", json!({"workspace_id": ws, "expected_head": "genesis", "title": ws, "lab": "kammi-ops", "owners": ["chief-kammi"]}), ADMIN, &format!("create-{ws}")).unwrap();
    }
    let mut state: u64 = 0x9e37_79b9_7f4a_7c15;
    let mut next = |n: u64| {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state % n
    };
    let principals = [ADMIN, CHIEF, REVIEWER, Principal::Actor("outsider")];
    let mut seen_heads: Vec<String> = Vec::new();
    let mut committed: Vec<(String, Value, String, String)> = Vec::new();
    let (mut ok, mut refused, mut conflicts, mut replays) = (0, 0, 0, 0);
    for i in 0..400 {
        let before = ledger.store.main.seq();
        if !committed.is_empty() && next(10) == 0 {
            // Retry a committed command with its original request ID and payload.
            let (kind, payload, request, event) =
                committed[next(committed.len() as u64) as usize].clone();
            let who = if kind == "WorkspaceObjectiveSet"
                || kind == "WorkspaceScopeSet"
                || kind == "WorkspaceClosed"
            {
                CHIEF
            } else {
                ADMIN
            };
            let out = cmd(&mut ledger, &kind, payload, who, &request).unwrap();
            assert_eq!(out["event_id"].as_str(), Some(event.as_str()));
            assert_eq!(ledger.store.main.seq(), before, "a retry appends nothing");
            replays += 1;
            continue;
        }
        let ws = workspaces[next(3) as usize];
        let current = head(&ledger, ws);
        let expected = if next(4) == 0 && !seen_heads.is_empty() {
            seen_heads[next(seen_heads.len() as u64) as usize].clone()
        } else {
            current.clone()
        };
        let who = principals[next(4) as usize];
        let (kind, mut payload) = match next(9) {
            0 => (
                "WorkspaceNoteRecorded",
                json!({"note_id": format!("n{}", next(40)), "text": format!("note {i}"), "refs": []}),
            ),
            1 => (
                "WorkspaceDecisionRecorded",
                json!({"decision_id": format!("d{}", next(20)), "text": "decide", "rationale": "because", "refs": [format!("artifact:{evidence}")]}),
            ),
            2 => (
                "WorkspaceQuestionOpened",
                json!({"question_id": format!("q{}", next(10)), "text": "why?", "refs": []}),
            ),
            3 => (
                "WorkspaceQuestionResolved",
                json!({"question_id": format!("q{}", next(10)), "resolution": "because", "refs": []}),
            ),
            4 => (
                "WorkspaceObjectiveSet",
                json!({"objective": format!("objective {i}"), "refs": []}),
            ),
            5 => (
                "WorkspaceHandoffSent",
                json!({"handoff_id": format!("h{}", next(10)), "to": "reviewer", "summary": "s", "next_step": "n", "refs": []}),
            ),
            6 => (
                "WorkspaceHandoffReceived",
                json!({"handoff_id": format!("h{}", next(10))}),
            ),
            7 => (
                "WorkspacePinned",
                json!({"ref": if next(3) == 0 { format!("artifact:sha256:{}", "7".repeat(64)) } else { format!("artifact:{evidence}") }}),
            ),
            _ => (
                "WorkspaceNextStepSet",
                json!({"next_step": format!("step {i}"), "refs": []}),
            ),
        };
        payload["workspace_id"] = json!(ws);
        payload["expected_head"] = json!(expected);
        let request = format!("cmd-{i}");
        match cmd(&mut ledger, kind, payload.clone(), who, &request) {
            Ok(out) => {
                assert_eq!(
                    ledger.store.main.seq(),
                    before + 1,
                    "a success appends exactly one event"
                );
                assert_eq!(out["head"], out["event_id"]);
                assert_eq!(expected, current, "a stale HEAD must never be accepted");
                seen_heads.push(current);
                committed.push((
                    kind.to_string(),
                    payload,
                    request,
                    out["event_id"].as_str().unwrap().to_string(),
                ));
                ok += 1;
            }
            Err(e) => {
                assert_eq!(
                    ledger.store.main.seq(),
                    before,
                    "a refused command must not reach the journal: {}",
                    e.detail()
                );
                if matches!(e, LedgerError::Conflict(_)) {
                    assert_ne!(expected, current);
                    conflicts += 1;
                } else {
                    refused += 1;
                }
            }
        }
    }
    assert!(
        ok > 50 && refused > 20 && conflicts > 10 && replays > 10,
        "coverage: {ok} ok, {refused} refused, {conflicts} conflicts, {replays} replays"
    );
    let snapshot: Vec<String> = workspaces
        .iter()
        .map(|ws| {
            serde_json::to_string(&(
                ledger.workspace_view(ws).unwrap(),
                ledger.work_packet(ws).unwrap(),
            ))
            .unwrap()
        })
        .collect();
    drop(ledger);
    let replayed = open(dir.path(), &c);
    let again: Vec<String> = workspaces
        .iter()
        .map(|ws| {
            serde_json::to_string(&(
                replayed.workspace_view(ws).unwrap(),
                replayed.work_packet(ws).unwrap(),
            ))
            .unwrap()
        })
        .collect();
    assert_eq!(
        snapshot, again,
        "replay reproduces every workspace byte for byte"
    );
}

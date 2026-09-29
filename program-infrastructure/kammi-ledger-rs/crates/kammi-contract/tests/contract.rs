//! Pins amendment v4's frozen contract.

use kammi_contract::{time, verbs, workspace, V4_EVENT_TYPES};
use serde_json::{json, Value};

const HEAD: &str = "sha256:1111111111111111111111111111111111111111111111111111111111111111";
const ART: &str =
    "artifact:sha256:2222222222222222222222222222222222222222222222222222222222222222";

fn envelope() -> Value {
    json!({
        "asserted_at": "2026-09-27T14:00:00Z",
        "confidence": 0.9,
        "flags": ["normalized"],
        "observed_at": "2026-09-29T02:10:30.849Z",
        "occurred": {"from": "2026-09-26T00:00:00Z", "to": "2026-09-26T23:59:59Z"},
        "original_text": "yesterday",
        "precision": "day",
        "source_time": "unknown",
        "timezone_offset_minutes": -240,
        "valid": {"from": "2026-09-26T00:00:00Z", "to": "open"}
    })
}

#[test]
fn v4_is_frozen_but_not_active() {
    // Rollback safety: the live closed registry accepts no v4 type until the activation release.
    for name in V4_EVENT_TYPES {
        assert!(
            !kammi_v1::EVENT_TYPES.contains(&name),
            "{name} is already journalable"
        );
    }
    assert!(V4_EVENT_TYPES.windows(2).all(|w| w[0] < w[1]));
    assert_eq!(kammi_v1::EVENT_TYPES.len(), 47);
    for name in V4_EVENT_TYPES.iter().filter(|n| n.starts_with("Workspace")) {
        assert!(
            workspace::fields(name).is_some(),
            "{name} has no payload rule"
        );
    }
}

#[test]
fn clock_model_matches_phoenix() {
    use phoenix_memory_contract::TemporalPrecisionV1;
    for (index, name) in time::PRECISIONS.iter().enumerate() {
        let raw = index as u16 + 1;
        let phoenix = TemporalPrecisionV1::from_raw(raw).expect("same raw range");
        assert_eq!(format!("{phoenix:?}").to_lowercase(), *name);
    }
    assert!(TemporalPrecisionV1::from_raw(time::PRECISIONS.len() as u16 + 1).is_none());
}

#[test]
fn a_full_envelope_validates() {
    let t = time::validate(&envelope(), Some("2026-09-29T02:10:30.849000Z")).unwrap();
    assert_eq!(t.precision, "day");
    assert_eq!(t.timezone_offset_minutes, Some(-240));
    assert_eq!(t.valid.1, time::Clock::Open);
    assert_eq!(t.source_time, time::Clock::Unknown);
    assert!(t.occurred.is_some());
}

#[test]
fn unknown_is_not_open() {
    let mut e = envelope();
    e["occurred"] = json!({"from": "unknown", "to": "open"});
    assert!(
        time::validate(&e, None).is_err(),
        "a half-known occurrence must be refused"
    );
    e["occurred"] = json!("unknown");
    assert!(time::validate(&e, None).unwrap().occurred.is_none());
    e["source_time"] = json!("open");
    assert!(
        time::validate(&e, None).is_err(),
        "a point clock cannot be open"
    );
}

#[test]
fn envelope_rules_fail_closed() {
    let cases: Vec<(&str, Value)> = vec![
        ("observed_at", json!("unknown")),
        ("confidence", json!(1.5)),
        ("timezone_offset_minutes", json!(1440)),
        ("precision", json!("fortnight")),
        ("flags", json!(["uncertain", "normalized"])),
        ("flags", json!(["normalized", "normalized"])),
        (
            "occurred",
            json!({"from": "2026-09-27T00:00:00Z", "to": "2026-09-26T00:00:00Z"}),
        ),
        (
            "valid",
            json!({"from": "2026-09-27T00:00:00Z", "to": "2026-09-26T00:00:00Z"}),
        ),
        ("asserted_at", json!("2026-09-27T14:00:00+02:00")),
        ("asserted_at", json!("2026-02-30T00:00:00Z")),
    ];
    for (field, bad) in cases {
        let mut e = envelope();
        e[field] = bad.clone();
        assert!(
            time::validate(&e, None).is_err(),
            "{field} = {bad} accepted"
        );
    }
    let mut extra = envelope();
    extra["decay"] = json!(0.5);
    assert!(
        time::validate(&extra, None).is_err(),
        "unknown key accepted"
    );
    assert!(
        time::validate(&envelope(), Some("2026-09-29T02:10:31Z")).is_err(),
        "observed_at must equal the event utc"
    );
}

#[test]
fn v1_records_read_as_v2() {
    let view = time::v1_view("2026-09-27T13:55:41.123456+00:00", 1.0);
    let t = time::validate(&view, Some("2026-09-27T13:55:41.123Z")).unwrap();
    assert_eq!(
        (t.source_time, t.asserted_at, t.occurred),
        (time::Clock::Unknown, time::Clock::Unknown, None)
    );
    assert_eq!(t.valid, (time::Clock::Unknown, time::Clock::Open));
}

#[test]
fn workspace_payloads() {
    let created = json!({"workspace_id": "frozen-fabrique.e4-0", "expected_head": "genesis",
        "title": "Frozen Fabrique E4-0", "lab": "fabrique", "owners": ["chief-kammi"]});
    workspace::validate("WorkspaceCreated", &created).unwrap();
    let scope = json!({"workspace_id": "frozen-fabrique.e4-0", "expected_head": HEAD,
        "authorized": ["extract stage under grant e4-extract"], "forbidden": ["open the hidden panel"], "refs": [ART]});
    workspace::validate("WorkspaceScopeSet", &scope).unwrap();

    let mut stale = created.clone();
    stale["expected_head"] = json!(HEAD);
    assert!(workspace::validate("WorkspaceCreated", &stale).is_err());
    let mut genesis = scope.clone();
    genesis["expected_head"] = json!("genesis");
    assert!(workspace::validate("WorkspaceScopeSet", &genesis).is_err());
    let mut extra = scope.clone();
    extra["priority"] = json!("high");
    assert!(workspace::validate("WorkspaceScopeSet", &extra).is_err());
    let mut dup = scope.clone();
    dup["refs"] = json!([ART, ART]);
    assert!(workspace::validate("WorkspaceScopeSet", &dup).is_err());
    let mut bad_ref = scope;
    bad_ref["refs"] = json!(["artifact:not-a-hash"]);
    assert!(workspace::validate("WorkspaceScopeSet", &bad_ref).is_err());
    assert!(workspace::validate("WorkspaceRenamed", &created).is_err());
}

#[test]
fn verb_abi_is_unique_and_phased() {
    let mut names: Vec<&str> = verbs::VERBS.iter().map(|v| v.name).collect();
    names.sort_unstable();
    assert!(names.windows(2).all(|w| w[0] != w[1]));
    for v1 in [
        "status", "call", "artifact", "run", "seal", "lineage", "history",
    ] {
        assert_eq!(verbs::lookup(v1).unwrap().phase, 0);
    }
    assert_eq!(
        verbs::mcp_tool(verbs::lookup("recall").unwrap()),
        "kammi_recall"
    );
}

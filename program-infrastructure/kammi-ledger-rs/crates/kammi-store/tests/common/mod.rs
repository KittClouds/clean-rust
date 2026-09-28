#![allow(dead_code)]

use kammi_jcs::{canonical, raw_id, typed_id_of_canonical, Domain, Sha256Id};
use kammi_store::{Journal, JournalOptions, NewEvent};
use serde_json::json;

/// Deterministic event `seq` with its payload, chained on `prev`.
pub fn make(seq: u64, prev: Sha256Id) -> (Vec<u8>, Vec<u8>) {
    let payload =
        canonical(&json!({"n": seq, "pad": "x".repeat((seq as usize * 7) % 90)})).unwrap();
    let event = canonical(&json!({
        "schema": "KAMMI_EVENT_V1",
        "seq": seq,
        "prev": prev.to_string(),
        "type": "RunCreated",
        "payload_artifact": raw_id(&payload).to_string(),
        "actor": "test",
        "request_id": format!("req-{seq}"),
        "utc": "2026-09-28T00:00:00Z",
    }))
    .unwrap();
    (event, payload)
}

/// Appends events `journal.seq()+1 ..= to`, `per_batch` at a time.
pub fn fill(journal: &mut Journal, to: u64, per_batch: usize) -> Vec<Sha256Id> {
    let mut ids = Vec::new();
    while journal.seq() < to {
        let mut prev = journal.head();
        let mut built = Vec::new();
        for seq in journal.seq() + 1..=to.min(journal.seq() + per_batch as u64) {
            let (event, payload) = make(seq, prev);
            prev = typed_id_of_canonical(Domain::Event, &event);
            built.push((event, payload));
        }
        let events: Vec<NewEvent> = built
            .iter()
            .map(|(e, p)| NewEvent {
                event: e,
                payload: p,
            })
            .collect();
        ids.extend(journal.append_batch(&events).unwrap());
    }
    ids
}

/// Head of a journal holding events 1..=n, computed without any store.
pub fn expected_head(n: u64) -> Sha256Id {
    let mut prev = Sha256Id::ZERO;
    for seq in 1..=n {
        prev = typed_id_of_canonical(Domain::Event, &make(seq, prev).0);
    }
    prev
}

pub fn small_segments() -> JournalOptions {
    JournalOptions {
        max_segment_bytes: 2048,
    }
}

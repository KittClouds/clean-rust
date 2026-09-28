//! Test driver for crash and lock qualification. Not a product binary.
//!
//! ```text
//! kammi-store-driver workload <root> <events>   deterministic, resumable workload
//! kammi-store-driver verify <root>              deep verify + referential check, prints heads
//! kammi-store-driver lock-hold <root> <ms>      hold the writer lock, print LOCKED
//! kammi-store-driver lock-probe <root>          print OK or BUSY
//! ```
//!
//! The workload uses tiny segment, pack and threshold limits so rollovers, loose objects and
//! checkpoints all happen within a few dozen events. Event `i` of each journal is a pure
//! function of `i`, so any interrupted run resumed to completion must reach the same heads
//! as an uninterrupted one.

use std::path::Path;
use std::process::ExitCode;

use kammi_jcs::{canonical, raw_id, strict_json, Sha256Id};
use kammi_store::{JournalOptions, NewEvent, ObjectOptions, Store, StoreError, StoreOptions};
use serde_json::json;

fn options() -> StoreOptions {
    StoreOptions {
        journal: JournalOptions {
            max_segment_bytes: 8 * 1024,
        },
        objects: ObjectOptions {
            pack_threshold: 1024,
            max_pack_bytes: 16 * 1024,
        },
    }
}

fn open_or_create(root: &Path) -> Result<Store, StoreError> {
    if root.join("STORE.json").exists() {
        Store::open(root, options())
    } else {
        Store::create(root, options())
    }
}

/// Object referenced by main event `i`: small most of the time, loose every 7th.
fn object_bytes(i: u64) -> Vec<u8> {
    let size = if i.is_multiple_of(7) {
        3000 + (i as usize * 13) % 500
    } else {
        40 + (i as usize * 29) % 700
    };
    (0..size)
        .map(|k| ((k as u64 * 31 + i * 17) % 251) as u8)
        .collect()
}

fn event_bytes(seq: u64, prev: Sha256Id, kind: &str, request: &str, payload: &[u8]) -> Vec<u8> {
    canonical(&json!({
        "schema": "KAMMI_EVENT_V1",
        "seq": seq,
        "prev": prev.to_string(),
        "type": kind,
        "payload_artifact": raw_id(payload).to_string(),
        "actor": "driver",
        "request_id": request,
        "utc": format!("2026-09-28T00:00:{:02}.{:06}Z", seq % 60, seq),
    }))
    .unwrap()
}

fn main_payload(i: u64, artifact: &Sha256Id) -> Vec<u8> {
    canonical(
        &json!({"artifact_id": artifact.to_string(), "byte_count": object_bytes(i).len(), "i": i}),
    )
    .unwrap()
}

fn memory_payload(i: u64) -> Vec<u8> {
    canonical(&json!({"memory": i, "text": format!("memory {i}")})).unwrap()
}

fn workload(root: &Path, target: u64) -> Result<(), StoreError> {
    let mut store = open_or_create(root)?;
    let memory_target = target / 5;
    loop {
        let main_seq = store.main.seq();
        if main_seq >= target && store.memory.seq() >= memory_target {
            break;
        }
        if main_seq < target {
            // Group commit: objects first (durable), then up to three events in one flush.
            let batch: Vec<u64> = (main_seq + 1..=target.min(main_seq + 3)).collect();
            let objects: Vec<Vec<u8>> = batch.iter().map(|i| object_bytes(*i)).collect();
            let refs: Vec<&[u8]> = objects.iter().map(Vec::as_slice).collect();
            let ids = store.objects.put_many(&refs)?;
            let mut prev = store.main.head();
            let mut built = Vec::new();
            for (i, id) in batch.iter().zip(&ids) {
                let payload = main_payload(*i, id);
                let event = event_bytes(
                    *i,
                    prev,
                    "ArtifactRegistered",
                    &format!("main-{i}"),
                    &payload,
                );
                prev = kammi_jcs::typed_id_of_canonical(kammi_jcs::Domain::Event, &event);
                built.push((event, payload));
            }
            let events: Vec<NewEvent> = built
                .iter()
                .map(|(e, p)| NewEvent {
                    event: e,
                    payload: p,
                })
                .collect();
            store.main.append_batch(&events)?;
        }
        let memory_seq = store.memory.seq();
        if memory_seq < memory_target && store.main.seq() >= (memory_seq + 1) * 5 {
            let i = memory_seq + 1;
            let payload = memory_payload(i);
            let event = event_bytes(
                i,
                store.memory.head(),
                "MemoryRecorded",
                &format!("memory-{i}"),
                &payload,
            );
            store.memory.append_batch(&[NewEvent {
                event: &event,
                payload: &payload,
            }])?;
        }
        if store.main.seq() % 10 == 0 {
            let state = format!("state-{}-{}", store.main.seq(), store.memory.seq());
            store.checkpoint("driver", state.as_bytes())?;
        }
    }
    Ok(())
}

fn verify(root: &Path) -> Result<(), StoreError> {
    let store = Store::open(root, options())?;
    let report = store.verify_deep()?;
    // Referential integrity: no committed event may name a missing object.
    for seq in 1..=store.main.seq() {
        let stored = store.main.read(seq)?;
        let payload = strict_json(&stored.payload)?;
        let artifact = Sha256Id::parse(payload["artifact_id"].as_str().unwrap())?;
        if store.get_object(&artifact)?.is_none() {
            return Err(StoreError::ObjectMissing(artifact));
        }
    }
    println!(
        "main={} {} memory={} {} objects={} checkpoint={}",
        store.main.seq(),
        store.main.head(),
        store.memory.seq(),
        store.memory.head(),
        report.objects.packed + report.objects.loose,
        report.checkpoint.is_some()
    );
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let result = match args.get(1).map(String::as_str) {
        Some("workload") => workload(Path::new(&args[2]), args[3].parse().unwrap()),
        Some("verify") => verify(Path::new(&args[2])),
        Some("lock-hold") => match Store::open(Path::new(&args[2]), options()) {
            Ok(store) => {
                println!("LOCKED");
                std::thread::sleep(std::time::Duration::from_millis(args[3].parse().unwrap()));
                drop(store);
                Ok(())
            }
            Err(e) => Err(e),
        },
        Some("lock-probe") => match Store::open(Path::new(&args[2]), options()) {
            Ok(_) => {
                println!("OK");
                Ok(())
            }
            Err(StoreError::Busy(_)) => {
                println!("BUSY");
                Ok(())
            }
            Err(e) => Err(e),
        },
        _ => {
            eprintln!("usage: kammi-store-driver workload|verify|lock-hold|lock-probe ...");
            return ExitCode::from(2);
        }
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::from(1)
        }
    }
}

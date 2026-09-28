//! Conformance against real Python-written stores.
//!
//! Set `KAMMI_V1_CORPUS` to one or more v1 store roots separated by `;` (for example the
//! operational store and the E4 import fixture). Stores are opened read-only with ordinary
//! shared handles; a partially written trailing frame is treated as not yet committed.
//! Without the variable the test reports that it was skipped.

use std::fs;
use std::path::{Path, PathBuf};

use kammi_jcs::{canonical, is_canonical, raw_id, strict_json, typed_id, Domain, Sha256Id, Value};

const EVENT_FIELDS: [&str; 8] = [
    "actor",
    "payload_artifact",
    "prev",
    "request_id",
    "schema",
    "seq",
    "type",
    "utc",
];

#[derive(Default, Debug)]
struct Tally {
    frames: usize,
    payloads: usize,
    seals: usize,
    facts: usize,
    memories: usize,
}

fn object_path(root: &Path, id: &str) -> PathBuf {
    let hex = &id[7..];
    root.join("objects")
        .join("sha256")
        .join(&hex[..2])
        .join(&hex[2..])
}

fn load_object(root: &Path, id: &str) -> Vec<u8> {
    let bytes =
        fs::read(object_path(root, id)).unwrap_or_else(|e| panic!("missing CAS object {id}: {e}"));
    assert_eq!(
        raw_id(&bytes).to_string(),
        id,
        "CAS digest mismatch for {id}"
    );
    bytes
}

fn without(value: &Value, key: &str) -> Value {
    let mut map = value.as_object().expect("object").clone();
    map.remove(key);
    Value::Object(map)
}

fn check_journal(store: &Path, journal: &Path, tally: &mut Tally) {
    let bytes = match fs::read(journal) {
        Ok(bytes) => bytes,
        Err(_) => return,
    };
    let mut offset = 0usize;
    let mut prev = Sha256Id::ZERO;
    let mut seq = 0i64;
    while offset < bytes.len() {
        if bytes.len() - offset < 4 {
            break;
        }
        let length = u32::from_be_bytes(bytes[offset..offset + 4].try_into().unwrap()) as usize;
        let end = offset + 4 + length + 32;
        if end > bytes.len() {
            break; // Uncommitted tail of a live journal.
        }
        let raw = &bytes[offset + 4..offset + 4 + length];
        let checksum = &bytes[offset + 4 + length..end];
        assert_eq!(
            raw_id(raw).as_bytes().as_slice(),
            checksum,
            "frame checksum at {offset} in {}",
            journal.display()
        );
        assert!(
            is_canonical(raw),
            "noncanonical frame at {offset} in {}",
            journal.display()
        );
        let event = strict_json(raw).expect("frame parses");
        let keys: Vec<&str> = event
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        assert_eq!(keys, EVENT_FIELDS, "event field set at {offset}");
        seq += 1;
        assert_eq!(event["seq"].as_i64(), Some(seq), "seq at {offset}");
        assert_eq!(
            event["prev"].as_str(),
            Some(prev.to_string().as_str()),
            "prev at {offset}"
        );
        prev = typed_id(Domain::Event, &event).unwrap();

        let payload_id = event["payload_artifact"].as_str().unwrap();
        let payload_raw = load_object(store, payload_id);
        assert!(
            is_canonical(&payload_raw),
            "noncanonical payload {payload_id}"
        );
        let payload = strict_json(&payload_raw).unwrap();
        tally.payloads += 1;

        match event["type"].as_str().unwrap() {
            "SealCreated" => {
                let seal_raw = load_object(store, payload["seal_artifact"].as_str().unwrap());
                let seal = strict_json(&seal_raw).unwrap();
                assert_eq!(canonical(&seal).unwrap(), seal_raw, "seal object canonical");
                assert_eq!(
                    typed_id(Domain::Seal, &seal).unwrap().to_string(),
                    payload["root"].as_str().unwrap()
                );
                tally.seals += 1;
            }
            "FactRecorded" => {
                let fact = without(&payload, "fact_id");
                assert_eq!(
                    typed_id(Domain::Fact, &fact).unwrap().to_string(),
                    payload["fact_id"].as_str().unwrap()
                );
                tally.facts += 1;
            }
            "MemoryRecorded" => {
                let record_raw =
                    load_object(store, payload["record_artifact_id"].as_str().unwrap());
                let record = strict_json(&record_raw).unwrap();
                let body = without(&record, "memory_id");
                assert_eq!(
                    raw_id(&canonical(&body).unwrap()).to_string(),
                    record["memory_id"].as_str().unwrap()
                );
                tally.memories += 1;
            }
            _ => {}
        }
        tally.frames += 1;
        offset = end;
    }
}

#[test]
fn python_written_stores_reproduce_byte_for_byte() {
    let Ok(roots) = std::env::var("KAMMI_V1_CORPUS") else {
        eprintln!("skipped: set KAMMI_V1_CORPUS to v1 store roots separated by ';'");
        return;
    };
    for root in roots.split(';').filter(|r| !r.is_empty()) {
        let store = PathBuf::from(root);
        assert!(
            store.join("journal").join("events.log").is_file(),
            "not a v1 store: {root}"
        );
        let mut tally = Tally::default();
        check_journal(
            &store,
            &store.join("journal").join("events.log"),
            &mut tally,
        );
        check_journal(
            &store,
            &store.join("memory").join("journal").join("events.log"),
            &mut tally,
        );
        assert!(tally.frames > 0, "no frames read from {root}");
        eprintln!("{root}: {tally:?}");
    }
}

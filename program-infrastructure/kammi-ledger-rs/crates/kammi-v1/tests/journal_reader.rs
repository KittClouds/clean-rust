//! Reader behaviour on synthetic journals written exactly as `journal.py` writes them.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

use kammi_jcs::{canonical, raw_id, typed_id, Domain, Sha256Id, Value};
use kammi_v1::{JournalReader, V1Error, V1Store};
use serde_json::json;

fn event(seq: u64, prev: Sha256Id, kind: &str, request: &str) -> Value {
    json!({
        "schema": "KAMMI_EVENT_V1",
        "seq": seq,
        "prev": prev.to_string(),
        "type": kind,
        "payload_artifact": raw_id(format!("payload-{seq}").as_bytes()).to_string(),
        "actor": "ledger-admin",
        "request_id": request,
        "utc": "2026-09-28T00:00:00.000001Z",
    })
}

fn frame(raw: &[u8]) -> Vec<u8> {
    let mut out = (raw.len() as u32).to_be_bytes().to_vec();
    out.extend_from_slice(raw);
    out.extend_from_slice(raw_id(raw).as_bytes());
    out
}

/// Writes `count` valid events and returns the frames' bytes plus the head.
fn valid_journal(count: u64) -> (Vec<u8>, Sha256Id) {
    let mut bytes = Vec::new();
    let mut prev = Sha256Id::ZERO;
    for seq in 1..=count {
        let value = event(seq, prev, "RunCreated", &format!("req-{seq}"));
        bytes.extend(frame(&canonical(&value).unwrap()));
        prev = typed_id(Domain::Event, &value).unwrap();
    }
    (bytes, prev)
}

fn append(path: &Path, bytes: &[u8]) {
    OpenOptions::new()
        .append(true)
        .create(true)
        .open(path)
        .unwrap()
        .write_all(bytes)
        .unwrap();
}

#[test]
fn reads_chain_and_reports_head() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.log");
    let (bytes, head) = valid_journal(5);
    fs::write(&path, &bytes).unwrap();
    let mut reader = JournalReader::open(&path).unwrap();
    let events = reader.read_all().unwrap();
    assert_eq!(events.len(), 5);
    assert_eq!(reader.head(), head);
    assert_eq!(reader.seq(), 5);
    assert_eq!(reader.committed_offset(), bytes.len() as u64);
    assert_eq!(events[4].event_id, head);
    assert_eq!(events[0].kind(), "RunCreated");
}

#[test]
fn torn_tail_is_pending_until_the_writer_finishes_it() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.log");
    let (bytes, _) = valid_journal(3);
    let first_two = {
        let mut reader_bytes = Vec::new();
        let (two, _) = valid_journal(2);
        reader_bytes.extend(two);
        reader_bytes
    };
    let third = &bytes[first_two.len()..];
    fs::write(&path, &first_two).unwrap();
    let mut reader = JournalReader::open(&path).unwrap();
    assert_eq!(reader.read_all().unwrap().len(), 2);
    // Header only, then half the body, then everything but the checksum.
    for cut in [2, 4, 4 + (third.len() - 36) / 2, third.len() - 1] {
        fs::write(&path, [first_two.as_slice(), &third[..cut]].concat()).unwrap();
        assert!(
            reader.next_event().unwrap().is_none(),
            "cut {cut} must be pending"
        );
        assert_eq!(reader.seq(), 2);
    }
    fs::write(&path, &bytes).unwrap();
    let event = reader.next_event().unwrap().expect("completed frame");
    assert_eq!(event.seq, 3);
    assert!(reader.next_event().unwrap().is_none());
}

#[test]
fn tamper_and_contract_violations_are_refused() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.log");
    let (good, head) = valid_journal(2);

    let refuse = |bytes: &[u8]| -> V1Error {
        fs::write(&path, bytes).unwrap();
        let mut reader = JournalReader::open(&path).unwrap();
        reader.read_all().unwrap_err()
    };

    // One flipped byte in the body: checksum mismatch.
    let mut flipped = good.clone();
    flipped[10] ^= 1;
    assert!(matches!(refuse(&flipped), V1Error::Checksum { .. }));

    // Valid checksum over non-canonical bytes.
    let spaced = br#"{"actor": "a"}"#;
    assert!(matches!(refuse(&frame(spaced)), V1Error::Vocabulary { .. }));
    let mut value = event(1, Sha256Id::ZERO, "RunCreated", "req-1");
    let pretty = serde_json::to_vec_pretty(&value).unwrap();
    assert!(matches!(
        refuse(&frame(&pretty)),
        V1Error::NonCanonical { .. }
    ));

    // Wrong prev, unknown type, extra field, duplicate request.
    let bad_prev = event(3, Sha256Id::ZERO, "RunCreated", "req-3");
    let chain = [good.as_slice(), &frame(&canonical(&bad_prev).unwrap())].concat();
    assert!(matches!(refuse(&chain), V1Error::Chain { .. }));

    let unknown = event(3, head, "WorkspaceCreated", "req-3");
    let vocab = [good.as_slice(), &frame(&canonical(&unknown).unwrap())].concat();
    assert!(matches!(refuse(&vocab), V1Error::Vocabulary { .. }));

    value["extra"] = json!(1);
    assert!(matches!(
        refuse(&frame(&canonical(&value).unwrap())),
        V1Error::Vocabulary { .. }
    ));

    let duplicate = event(3, head, "RunCreated", "req-1");
    let dup = [good.as_slice(), &frame(&canonical(&duplicate).unwrap())].concat();
    assert!(matches!(refuse(&dup), V1Error::DuplicateRequest { .. }));

    // Zero and oversized frame lengths.
    assert!(matches!(
        refuse(&[0, 0, 0, 0, 1, 2, 3]),
        V1Error::FrameLength { .. }
    ));
    assert!(matches!(
        refuse(&[0x01, 0, 0, 1]),
        V1Error::FrameLength { .. }
    ));
}

#[test]
fn shrinking_below_committed_history_is_detected() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.log");
    let (bytes, _) = valid_journal(3);
    fs::write(&path, &bytes).unwrap();
    let mut reader = JournalReader::open(&path).unwrap();
    reader.read_all().unwrap();
    fs::write(&path, &bytes[..bytes.len() / 2]).unwrap();
    assert!(matches!(
        reader.next_event(),
        Err(V1Error::HistoryRewritten { .. })
    ));
}

#[test]
fn live_append_is_followed_while_the_file_stays_open() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.log");
    let (bytes, _) = valid_journal(4);
    let (first, _) = valid_journal(1);
    fs::write(&path, &first).unwrap();
    let mut reader = JournalReader::open(&path).unwrap();
    assert_eq!(reader.read_all().unwrap().len(), 1);
    // A second handle appends while the reader's handle stays open (Python's pattern).
    append(&path, &bytes[first.len()..]);
    assert_eq!(reader.read_all().unwrap().len(), 3);
    assert_eq!(reader.seq(), 4);
}

#[test]
fn store_objects_verify_and_list() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    fs::create_dir_all(root.join("journal")).unwrap();
    fs::write(root.join("journal").join("events.log"), b"").unwrap();
    let store = V1Store::open(root).unwrap();
    let data = b"custody bytes";
    let id = raw_id(data);
    let path = store.object_path(&id);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, data).unwrap();
    assert_eq!(store.read_object(&id).unwrap(), data);
    assert!(store.verify_object(&id).unwrap());
    assert_eq!(store.object_ids().unwrap(), vec![id]);
    fs::write(&path, b"custody byteS").unwrap();
    assert!(matches!(
        store.read_object(&id),
        Err(V1Error::ObjectCorrupt(_))
    ));
    assert!(!store.verify_object(&id).unwrap());
    let missing = raw_id(b"absent");
    assert!(matches!(
        store.read_object(&missing),
        Err(V1Error::ObjectMissing(_))
    ));
    assert!(store.memory_journal().unwrap().is_none());
}

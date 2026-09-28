use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use kammi_jcs::{canonical, raw_id, typed_id_of_canonical, Domain, Sha256Id};
use kammi_migrate::{compare_v1, export_v1, sync, MigrateError};
use kammi_store::{Store, StoreOptions};
use kammi_v1::V1Store;
use serde_json::json;

/// Writes a store exactly the way `ledgerd` does: loose CAS files and framed journals.
struct V1Builder {
    root: PathBuf,
    main: (u64, Sha256Id),
    memory: (u64, Sha256Id),
}

impl V1Builder {
    fn new(root: &Path) -> Self {
        fs::create_dir_all(root.join("journal")).unwrap();
        fs::write(root.join("journal").join("events.log"), b"").unwrap();
        V1Builder {
            root: root.to_path_buf(),
            main: (0, Sha256Id::ZERO),
            memory: (0, Sha256Id::ZERO),
        }
    }

    fn object(&self, bytes: &[u8]) -> Sha256Id {
        let id = raw_id(bytes);
        let text = id.to_string();
        let dir = self.root.join("objects").join("sha256").join(&text[7..9]);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(&text[9..]), bytes).unwrap();
        id
    }

    fn frame(event: &[u8]) -> Vec<u8> {
        let mut out = (event.len() as u32).to_be_bytes().to_vec();
        out.extend_from_slice(event);
        out.extend_from_slice(raw_id(event).as_bytes());
        out
    }

    fn event(
        &mut self,
        memory: bool,
        kind: &str,
        payload: serde_json::Value,
        tag: &str,
    ) -> Vec<u8> {
        let payload = canonical(&payload).unwrap();
        let payload_id = self.object(&payload);
        let (seq, prev) = if memory { self.memory } else { self.main };
        let utc = if memory {
            "2026-09-28T01:02:03.000004+00:00"
        } else {
            "2026-09-28T01:02:03.000004Z"
        };
        let event = canonical(&json!({
            "schema": "KAMMI_EVENT_V1", "seq": seq + 1, "prev": prev.to_string(), "type": kind,
            "payload_artifact": payload_id.to_string(), "actor": "ledger-admin",
            "request_id": format!("{tag}-{}-{}", if memory {"mem"} else {"main"}, seq + 1), "utc": utc,
        }))
        .unwrap();
        let next = (seq + 1, typed_id_of_canonical(Domain::Event, &event));
        if memory {
            self.memory = next;
        } else {
            self.main = next;
        }
        Self::frame(&event)
    }

    fn append(&mut self, memory: bool, kind: &str, payload: serde_json::Value, tag: &str) {
        let frame = self.event(memory, kind, payload, tag);
        let path = self.journal_path(memory);
        OpenOptions::new()
            .append(true)
            .create(true)
            .open(path)
            .unwrap()
            .write_all(&frame)
            .unwrap();
    }

    fn journal_path(&self, memory: bool) -> PathBuf {
        if memory {
            let dir = self.root.join("memory").join("journal");
            fs::create_dir_all(&dir).unwrap();
            dir.join("events.log")
        } else {
            self.root.join("journal").join("events.log")
        }
    }

    fn populate(&mut self, main: u64, memory: u64, tag: &str) {
        for i in 0..main {
            let artifact = self.object(format!("artifact {tag} {i}").as_bytes());
            self.append(
                false,
                "ArtifactRegistered",
                json!({"artifact_id": artifact.to_string(), "i": i, "score": 0.1 * i as f64}),
                tag,
            );
        }
        for i in 0..memory {
            self.append(
                true,
                "MemoryRecorded",
                json!({"memory": i, "text": format!("m {i}")}),
                tag,
            );
        }
    }
}

fn import_into(v1: &Path, v2: &Path) -> (Store, kammi_migrate::SyncReport) {
    let mut store = if v2.join("STORE.json").exists() {
        Store::open(v2, StoreOptions::default()).unwrap()
    } else {
        Store::create(v2, StoreOptions::default()).unwrap()
    };
    let report = sync(&V1Store::open(v1).unwrap(), &mut store).unwrap();
    (store, report)
}

#[test]
fn import_export_round_trip_is_byte_identical() {
    let dir = tempfile::tempdir().unwrap();
    let v1 = dir.path().join("v1");
    let mut builder = V1Builder::new(&v1);
    builder.populate(50, 6, "a");
    builder.object(b"orphan small object");
    builder.object(&vec![9u8; 300 * 1024]); // above the pack threshold: stored loose
    let (store, report) = import_into(&v1, &dir.path().join("v2"));
    assert_eq!((report.main.appended, report.memory.appended), (50, 6));
    assert_eq!(store.main.head(), builder.main.1);
    assert_eq!(store.memory.head(), builder.memory.1);
    assert_eq!(
        report.objects_copied, 52,
        "50 artifacts + 2 orphans; payloads travel inline"
    );
    store.verify_deep().unwrap();
    let genesis = fs::read(dir.path().join("v2").join("genesis").join("v1-import.json")).unwrap();
    assert!(String::from_utf8(genesis)
        .unwrap()
        .contains(&builder.main.1.to_string()));

    let out = dir.path().join("exported");
    let exported = export_v1(&store, &out).unwrap();
    assert_eq!((exported.main_events, exported.memory_events), (50, 6));
    let (main_bytes, memory_bytes, objects) =
        compare_v1(&V1Store::open(&v1).unwrap(), &V1Store::open(&out).unwrap()).unwrap();
    assert_eq!(
        main_bytes,
        fs::metadata(v1.join("journal").join("events.log"))
            .unwrap()
            .len()
    );
    assert!(memory_bytes > 0);
    assert_eq!(objects, 50 + 6 + 52);
    assert!(matches!(
        export_v1(&store, &out),
        Err(MigrateError::DestinationExists(_))
    ));
}

#[test]
fn sync_resumes_after_python_appends_and_ignores_torn_tails() {
    let dir = tempfile::tempdir().unwrap();
    let v1 = dir.path().join("v1");
    let v2 = dir.path().join("v2");
    let mut builder = V1Builder::new(&v1);
    builder.populate(10, 2, "a");
    drop(import_into(&v1, &v2).0);

    // Python keeps writing; its last frame is still being written.
    builder.populate(20, 1, "b");
    let pending = builder.event(false, "RunCreated", json!({"run_id": "r"}), "c");
    let path = builder.journal_path(false);
    OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(&pending[..pending.len() / 2])
        .unwrap();
    let (store, report) = import_into(&v1, &v2);
    assert_eq!(
        (report.main.already_present, report.main.appended),
        (10, 20)
    );
    assert_eq!(report.memory.appended, 1);
    assert_eq!(store.main.seq(), 30);
    drop(store);

    // The writer finishes the frame; the next sync picks it up, and a repeat is a no-op.
    OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(&pending[pending.len() / 2..])
        .unwrap();
    let (store, report) = import_into(&v1, &v2);
    assert_eq!(report.main.appended, 1);
    assert_eq!(store.main.head(), builder.main.1);
    drop(store);
    let (store, report) = import_into(&v1, &v2);
    assert_eq!(
        (
            report.main.appended,
            report.memory.appended,
            report.objects_copied
        ),
        (0, 0, 0)
    );
    store.verify_deep().unwrap();
}

#[test]
fn divergent_or_trailing_v1_histories_are_refused() {
    let dir = tempfile::tempdir().unwrap();
    let a = dir.path().join("a");
    let b = dir.path().join("b");
    V1Builder::new(&a).populate(8, 0, "a");
    V1Builder::new(&b).populate(8, 0, "b"); // same shape, different content
    let v2 = dir.path().join("v2");
    drop(import_into(&a, &v2).0);
    let mut store = Store::open(&v2, StoreOptions::default()).unwrap();
    let error = sync(&V1Store::open(&b).unwrap(), &mut store).unwrap_err();
    assert!(
        matches!(
            error,
            MigrateError::Diverged {
                journal: "main",
                seq: 1
            }
        ),
        "{error}"
    );

    let short = dir.path().join("short");
    V1Builder::new(&short).populate(3, 0, "a");
    let error = sync(&V1Store::open(&short).unwrap(), &mut store).unwrap_err();
    assert!(
        matches!(
            error,
            MigrateError::Ahead {
                journal: "main",
                ..
            }
        ),
        "{error}"
    );
    assert_eq!(store.main.seq(), 8);
    store.verify_deep().unwrap();
}

#[test]
fn corrupt_v1_payload_stops_the_import_without_damaging_v2() {
    let dir = tempfile::tempdir().unwrap();
    let v1 = dir.path().join("v1");
    let mut builder = V1Builder::new(&v1);
    builder.populate(5, 0, "a");
    // Corrupt the payload object of event 3.
    let store_v1 = V1Store::open(&v1).unwrap();
    let events = store_v1.main_journal().unwrap().read_all().unwrap();
    let payload_path = store_v1.object_path(&events[2].payload_artifact());
    let mut bytes = fs::read(&payload_path).unwrap();
    bytes[0] ^= 1;
    fs::write(&payload_path, &bytes).unwrap();
    let v2 = dir.path().join("v2");
    let mut store = Store::create(&v2, StoreOptions::default()).unwrap();
    assert!(sync(&store_v1, &mut store).is_err());
    assert_eq!(
        store.main.seq(),
        0,
        "the batch holding the corrupt payload is not committed"
    );
    store.verify_deep().unwrap();
}

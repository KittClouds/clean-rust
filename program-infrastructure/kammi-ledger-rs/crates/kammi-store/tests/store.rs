mod common;

use std::fs;
use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};

use common::{expected_head, fill};
use kammi_jcs::raw_id;
use kammi_store::{Store, StoreError, StoreOptions};

const DRIVER: &str = env!("CARGO_BIN_EXE_kammi-store-driver");

#[test]
fn single_writer_in_process_and_across_processes() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("store");
    let store = Store::create(&root, StoreOptions::default()).unwrap();
    assert!(matches!(
        Store::open(&root, StoreOptions::default()),
        Err(StoreError::Busy(_))
    ));
    let probe = Command::new(DRIVER)
        .args(["lock-probe", root.to_str().unwrap()])
        .output()
        .unwrap();
    assert_eq!(String::from_utf8_lossy(&probe.stdout).trim(), "BUSY");
    drop(store);
    let probe = Command::new(DRIVER)
        .args(["lock-probe", root.to_str().unwrap()])
        .output()
        .unwrap();
    assert_eq!(String::from_utf8_lossy(&probe.stdout).trim(), "OK");

    // Another process holds it; then it is killed and the lock must be released by the OS.
    let mut holder = Command::new(DRIVER)
        .args(["lock-hold", root.to_str().unwrap(), "60000"])
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut line = String::new();
    BufReader::new(holder.stdout.take().unwrap())
        .read_line(&mut line)
        .unwrap();
    assert_eq!(line.trim(), "LOCKED");
    assert!(matches!(
        Store::open(&root, StoreOptions::default()),
        Err(StoreError::Busy(_))
    ));
    holder.kill().unwrap();
    holder.wait().unwrap();
    Store::open(&root, StoreOptions::default()).unwrap();
}

#[test]
fn create_refuses_foreign_directories_and_open_refuses_non_stores() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("something"), b"x").unwrap();
    assert!(matches!(
        Store::create(dir.path(), StoreOptions::default()),
        Err(StoreError::AlreadyExists(_))
    ));
    assert!(matches!(
        Store::open(dir.path(), StoreOptions::default()),
        Err(StoreError::NotAStore(_))
    ));
}

#[test]
fn checkpoints_bind_to_heads_and_are_only_accelerators() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("store");
    let mut store = Store::create(&root, StoreOptions::default()).unwrap();
    for round in 1..=5u64 {
        fill(&mut store.main, round * 10, 4);
        store
            .checkpoint("state", format!("state-{round}").as_bytes())
            .unwrap();
    }
    let (latest, rejected) = store.latest_checkpoint().unwrap();
    let latest = latest.unwrap();
    assert!(rejected.is_empty());
    assert_eq!(latest.payload, b"state-5");
    assert_eq!(latest.main.seq, 50);
    assert_eq!(latest.main.head, expected_head(50));
    let names: Vec<_> = fs::read_dir(root.join("checkpoints"))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".ckpt"))
        .collect();
    assert_eq!(names.len(), 3, "pruned to the newest three");

    // Corrupt the newest: it is skipped and the previous one is used.
    let mut bytes = fs::read(&latest.path).unwrap();
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    fs::write(&latest.path, &bytes).unwrap();
    let (fallback, rejected) = store.latest_checkpoint().unwrap();
    assert_eq!(fallback.unwrap().payload, b"state-4");
    assert_eq!(rejected, vec![latest.path.clone()]);

    // A checkpoint bound to a head that is not in this history is never trusted.
    drop(store);
    let other = dir.path().join("other");
    {
        let mut store = Store::create(&other, StoreOptions::default()).unwrap();
        fill(&mut store.main, 40, 4);
    }
    for entry in fs::read_dir(root.join("checkpoints")).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().is_some_and(|x| x == "ckpt") {
            let target = other.join("checkpoints").join(path.file_name().unwrap());
            let mut bytes = fs::read(&path).unwrap();
            // Rebind to a foreign head while keeping the file well-formed.
            bytes[24..56].copy_from_slice(&raw_id(b"foreign").0);
            fs::write(target, bytes).unwrap();
        }
    }
    let store = Store::open(&other, StoreOptions::default()).unwrap();
    let (none, rejected) = store.latest_checkpoint().unwrap();
    assert!(none.is_none());
    assert_eq!(rejected.len(), 3);
    store.verify_deep().unwrap();
}

#[test]
fn objects_resolve_across_packs_loose_and_journal_payloads() {
    let dir = tempfile::tempdir().unwrap();
    let mut store = Store::create(&dir.path().join("s"), StoreOptions::default()).unwrap();
    fill(&mut store.main, 5, 5);
    let payload_id = store.main.read(3).unwrap().payload_id;
    assert!(store.contains_object(&payload_id));
    assert!(store.get_object(&payload_id).unwrap().is_some());
    let small = store.objects.put(b"small").unwrap();
    let large = store.objects.put(&vec![7u8; 400_000]).unwrap();
    assert_eq!(store.get_object(&small).unwrap().unwrap(), b"small");
    assert_eq!(store.get_object(&large).unwrap().unwrap().len(), 400_000);
    assert!(store.get_object(&raw_id(b"nothing")).unwrap().is_none());
    let report = store.verify_deep().unwrap();
    assert_eq!(
        (
            report.objects.packed,
            report.objects.loose,
            report.main.events
        ),
        (1, 1, 5)
    );
}

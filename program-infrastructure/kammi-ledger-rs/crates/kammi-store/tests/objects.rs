use std::fs;
use std::path::Path;

use kammi_jcs::raw_id;
use kammi_store::{ObjectOptions, Objects, StoreError};

fn options() -> ObjectOptions {
    ObjectOptions {
        pack_threshold: 512,
        max_pack_bytes: 4096,
    }
}

fn open(dir: &Path) -> Objects {
    Objects::open(dir, options()).unwrap()
}

fn blob(i: usize, size: usize) -> Vec<u8> {
    (0..size).map(|k| ((k * 7 + i * 13) % 256) as u8).collect()
}

#[test]
fn put_get_dedupe_stream_and_reopen() {
    let dir = tempfile::tempdir().unwrap();
    let items: Vec<Vec<u8>> = (0..200).map(|i| blob(i, (i * 37) % 900)).collect();
    let ids = {
        let mut objects = open(dir.path());
        let refs: Vec<&[u8]> = items.iter().map(Vec::as_slice).collect();
        let ids = objects.put_many(&refs).unwrap();
        // Re-putting is a verified no-op.
        assert_eq!(objects.put_many(&refs).unwrap(), ids);
        assert!(objects.pack_count() > 3, "small packs roll over");
        let big = blob(999, 5 << 20);
        let streamed = objects
            .put_stream(&mut big.as_slice(), Some(raw_id(&big)))
            .unwrap();
        assert_eq!(streamed, raw_id(&big));
        let mut copy = Vec::new();
        assert_eq!(
            objects.copy_to(&streamed, &mut copy).unwrap(),
            big.len() as u64
        );
        assert_eq!(copy, big);
        let wrong = objects.put_stream(&mut b"abc".as_slice(), Some(raw_id(b"xyz")));
        assert!(matches!(wrong, Err(StoreError::ObjectCorrupt(_))));
        ids
    };
    let mut objects = open(dir.path());
    for (item, id) in items.iter().zip(&ids) {
        assert_eq!(objects.get(id).unwrap().as_deref(), Some(item.as_slice()));
        assert_eq!(objects.len(id).unwrap(), Some(item.len() as u64));
    }
    assert!(objects.get(&raw_id(b"absent")).unwrap().is_none());
    objects.compact_index().unwrap();
    assert_eq!(objects.tail_entries(), 0);
    drop(objects);
    let objects = open(dir.path());
    assert_eq!(objects.get(&ids[150]).unwrap().unwrap(), items[150]);
    let report = objects.verify_deep().unwrap();
    let unique: std::collections::HashSet<_> = ids.iter().collect();
    assert_eq!(report.packed + report.loose, unique.len() as u64 + 1);
    assert_eq!(objects.ids().unwrap().len(), unique.len() + 1);
}

#[test]
fn every_torn_pack_cut_drops_only_the_unacknowledged_record() {
    let dir = tempfile::tempdir().unwrap();
    let template = dir.path().join("template");
    let (ids, last_len) = {
        let mut objects = open(&template);
        let ids: Vec<_> = (0..5)
            .map(|i| objects.put(&blob(i, 100 + i)).unwrap())
            .collect();
        (ids, 36 + 104)
    };
    let pack = template.join("packs").join("pack-00000001.pack");
    let full = fs::read(&pack).unwrap();
    for cut in 1..last_len {
        let work = dir.path().join(format!("cut-{cut}"));
        copy_dir(&template, &work);
        fs::write(
            work.join("packs").join("pack-00000001.pack"),
            &full[..full.len() - cut],
        )
        .unwrap();
        // The index log still names the cut record; it must be rebuilt, not trusted.
        let mut objects = open(&work);
        for id in &ids[..4] {
            assert!(objects.get(id).unwrap().is_some(), "cut {cut}");
        }
        assert!(!objects.contains(&ids[4]), "cut {cut}");
        assert_eq!(objects.put(&blob(4, 104)).unwrap(), ids[4]);
        objects.verify_deep().unwrap();
        drop(objects);
        fs::remove_dir_all(&work).unwrap();
    }
}

#[test]
fn unlogged_but_durable_records_are_recovered() {
    let dir = tempfile::tempdir().unwrap();
    let id = {
        let mut objects = open(dir.path());
        objects.put(b"first").unwrap();
        objects.put(b"second").unwrap()
    };
    // Simulate a crash after the pack fsync but before the log append.
    let log = dir.path().join("packs").join("index.log");
    let bytes = fs::read(&log).unwrap();
    fs::write(&log, &bytes[..bytes.len() - 48]).unwrap();
    let objects = open(dir.path());
    assert_eq!(objects.get(&id).unwrap().unwrap(), b"second");
    objects.verify_deep().unwrap();
}

#[test]
fn corruption_is_detected_not_repaired() {
    let dir = tempfile::tempdir().unwrap();
    let (small, big) = {
        let mut objects = open(dir.path());
        (
            objects.put(&blob(1, 300)).unwrap(),
            objects.put(&blob(2, 4000)).unwrap(),
        )
    };
    // Flip one byte of a packed record body. Opening does not re-hash every object (that
    // would not scale); the read path and deep verification must both catch it.
    let pack = dir.path().join("packs").join("pack-00000001.pack");
    let mut bytes = fs::read(&pack).unwrap();
    bytes[16 + 36 + 10] ^= 1;
    fs::write(&pack, &bytes).unwrap();
    {
        let objects = open(dir.path());
        assert!(matches!(
            objects.get(&small),
            Err(StoreError::ObjectCorrupt(_))
        ));
        assert!(objects.verify_deep().is_err());
    }
    bytes[16 + 36 + 10] ^= 1;
    fs::write(&pack, &bytes).unwrap();
    // Flip one byte of a loose object.
    let objects = open(dir.path());
    let loose = objects.loose_path(&big);
    let mut data = fs::read(&loose).unwrap();
    data[0] ^= 1;
    fs::write(&loose, &data).unwrap();
    assert!(matches!(
        objects.get(&big),
        Err(StoreError::ObjectCorrupt(_))
    ));
    assert!(matches!(
        objects.copy_to(&big, &mut Vec::new()),
        Err(StoreError::ObjectCorrupt(_))
    ));
    assert!(objects.verify_deep().is_err());
    assert!(objects.get(&small).unwrap().is_some());
}

#[test]
fn damaged_derived_files_are_rebuilt() {
    let dir = tempfile::tempdir().unwrap();
    let items: Vec<Vec<u8>> = (0..60).map(|i| blob(i, 50 + i * 3)).collect();
    let ids = {
        let mut objects = open(dir.path());
        let refs: Vec<&[u8]> = items.iter().map(Vec::as_slice).collect();
        let ids = objects.put_many(&refs).unwrap();
        objects.compact_index().unwrap();
        ids
    };
    let packs = dir.path().join("packs");
    for damage in ["delete log", "garbage log", "torn log", "garbage table"] {
        match damage {
            "delete log" => fs::remove_file(packs.join("index.log")).unwrap(),
            "garbage log" => fs::write(packs.join("index.log"), b"garbage").unwrap(),
            "torn log" => {
                let b = fs::read(packs.join("index.log")).unwrap();
                fs::write(packs.join("index.log"), &b[..b.len() - 7]).unwrap();
            }
            _ => fs::write(packs.join("packs.tbl"), b"KMKTAB02 nope").unwrap(),
        }
        let objects = open(dir.path());
        for (item, id) in items.iter().zip(&ids) {
            assert_eq!(
                objects.get(id).unwrap().as_deref(),
                Some(item.as_slice()),
                "{damage}"
            );
        }
        objects
            .verify_deep()
            .unwrap_or_else(|e| panic!("{damage}: {e}"));
    }
}

pub fn copy_dir(from: &Path, to: &Path) {
    fs::create_dir_all(to).unwrap();
    for entry in fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).unwrap();
        }
    }
}

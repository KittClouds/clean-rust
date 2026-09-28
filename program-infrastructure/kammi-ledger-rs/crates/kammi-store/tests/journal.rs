mod common;

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

use common::{expected_head, fill, make, small_segments};
use kammi_jcs::{canonical, raw_id, Sha256Id};
use kammi_store::{Journal, JournalOptions, NewEvent, StoreError};

fn open(dir: &Path) -> Journal {
    Journal::open(dir, "main", small_segments()).unwrap()
}

fn last_segment(dir: &Path) -> std::path::PathBuf {
    let mut segments: Vec<_> = fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|x| x == "seg"))
        .collect();
    segments.sort();
    segments.pop().unwrap()
}

#[test]
fn append_reopen_and_lookups_agree() {
    let dir = tempfile::tempdir().unwrap();
    let ids = {
        let mut journal = open(dir.path());
        fill(&mut journal, 120, 7)
    };
    let journal = open(dir.path());
    assert_eq!(journal.seq(), 120);
    assert_eq!(journal.head(), expected_head(120));
    assert!(journal.segment_count() > 5, "small segments must roll over");
    let mut prev = Sha256Id::ZERO;
    for seq in 1..=120 {
        let stored = journal.read(seq).unwrap();
        let (event, payload) = make(seq, prev);
        assert_eq!(stored.event, event);
        assert_eq!(stored.payload, payload);
        assert_eq!(stored.event_id, ids[seq as usize - 1]);
        assert_eq!(
            journal
                .by_request(&format!("req-{seq}"))
                .unwrap()
                .unwrap()
                .seq,
            seq
        );
        assert_eq!(
            journal.payload(&raw_id(&payload)).unwrap().unwrap(),
            payload
        );
        prev = stored.event_id;
    }
    assert!(journal.by_request("req-999").unwrap().is_none());
    assert!(matches!(
        journal.read(121),
        Err(StoreError::UnknownSeq(121))
    ));
    let report = journal.verify_deep().unwrap();
    assert_eq!(report.events, 120);
    assert_eq!(report.head, Some(expected_head(120)));
}

#[test]
fn invalid_batches_write_nothing() {
    let dir = tempfile::tempdir().unwrap();
    let mut journal = open(dir.path());
    fill(&mut journal, 3, 3);
    let head = journal.head();
    let (good, good_payload) = make(4, head);
    let (wrong_chain, wc_payload) = make(4, Sha256Id::ZERO);
    let (dup_event, dup_payload) = {
        // Correct chain but reuses request "req-1".
        let (event, payload) = make(4, head);
        let text = String::from_utf8(event)
            .unwrap()
            .replace("\"req-4\"", "\"req-1\"");
        (text.into_bytes(), payload)
    };
    let pretty =
        serde_json::to_vec_pretty(&serde_json::from_slice::<serde_json::Value>(&good).unwrap())
            .unwrap();
    type Case<'a> = (Vec<NewEvent<'a>>, fn(&StoreError) -> bool);
    let cases: Vec<Case> = vec![
        (
            vec![
                NewEvent {
                    event: &good,
                    payload: &good_payload,
                },
                NewEvent {
                    event: &wrong_chain,
                    payload: &wc_payload,
                },
            ],
            |e| matches!(e, StoreError::Chain { .. }),
        ),
        (
            vec![NewEvent {
                event: &good,
                payload: b"other bytes",
            }],
            |e| matches!(e, StoreError::PayloadMismatch(_)),
        ),
        (
            vec![NewEvent {
                event: &dup_event,
                payload: &dup_payload,
            }],
            |e| matches!(e, StoreError::DuplicateRequest(_)),
        ),
        (
            vec![
                NewEvent {
                    event: &good,
                    payload: &good_payload,
                },
                NewEvent {
                    event: &good,
                    payload: &good_payload,
                },
            ],
            |e| {
                matches!(
                    e,
                    StoreError::Chain { .. } | StoreError::DuplicateRequest(_)
                )
            },
        ),
        (
            vec![NewEvent {
                event: &pretty,
                payload: &good_payload,
            }],
            |e| matches!(e, StoreError::InvalidEvent(_)),
        ),
        (
            vec![NewEvent {
                event: b"{\"a\":1,\"a\":2}",
                payload: b"",
            }],
            |e| matches!(e, StoreError::Jcs(_)),
        ),
    ];
    for (batch, expected) in cases {
        let error = journal.append_batch(&batch).unwrap_err();
        assert!(expected(&error), "unexpected error {error}");
        assert_eq!(journal.seq(), 3);
        assert_eq!(journal.head(), head);
    }
    drop(journal);
    let journal = open(dir.path());
    assert_eq!(journal.seq(), 3);
    journal.verify_deep().unwrap();
}

#[test]
fn every_torn_tail_cut_recovers_the_previous_commit() {
    let dir = tempfile::tempdir().unwrap();
    let template = dir.path().join("template");
    {
        let mut journal = open(&template);
        fill(&mut journal, 9, 3);
    }
    let segment_name = last_segment(&template).file_name().unwrap().to_owned();
    let full = fs::read(template.join(&segment_name)).unwrap();
    // Size of the last frame, from the index record.
    let frame_len = {
        let journal = open(&template);
        u64::from(journal.record(9).unwrap().frame_len) as usize
    };
    for cut in 1..frame_len {
        let work = dir.path().join(format!("cut-{cut}"));
        copy_dir(&template, &work);
        fs::write(work.join(&segment_name), &full[..full.len() - cut]).unwrap();
        let mut journal = open(&work);
        assert_eq!(journal.seq(), 8, "cut {cut}");
        assert_eq!(journal.head(), expected_head(8));
        assert_eq!(journal.recovered_tails().len(), 1, "cut {cut}");
        let saved = fs::read(&journal.recovered_tails()[0]).unwrap();
        assert_eq!(saved, &full[full.len() - frame_len..full.len() - cut]);
        fill(&mut journal, 10, 5);
        assert_eq!(journal.head(), expected_head(10), "cut {cut}");
        journal.verify_deep().unwrap();
        drop(journal);
        fs::remove_dir_all(&work).unwrap();
    }
}

#[test]
fn zero_filled_tail_is_torn_but_garbage_is_corruption() {
    let dir = tempfile::tempdir().unwrap();
    {
        let mut journal = open(dir.path());
        fill(&mut journal, 4, 4);
    }
    let segment = last_segment(dir.path());
    OpenOptions::new()
        .append(true)
        .open(&segment)
        .unwrap()
        .write_all(&[0u8; 700])
        .unwrap();
    {
        let journal = open(dir.path());
        assert_eq!(journal.seq(), 4);
        assert_eq!(journal.recovered_tails().len(), 1);
    }
    // A complete frame with a bad checksum is never "repaired".
    let mut bytes = fs::read(&segment).unwrap();
    let last = bytes.len() - 40;
    bytes[last] ^= 1;
    fs::write(&segment, &bytes).unwrap();
    let error = Journal::open(dir.path(), "main", small_segments())
        .err()
        .unwrap();
    assert!(matches!(error, StoreError::Corrupt { .. }), "{error}");
}

#[test]
fn committed_history_tamper_refuses_to_open() {
    let dir = tempfile::tempdir().unwrap();
    {
        let mut journal = open(dir.path());
        fill(&mut journal, 60, 4);
    }
    let first = dir.path().join("seg-00000001.seg");
    let original = fs::read(&first).unwrap();
    // Flip a byte inside a sealed segment's first frame, drop that segment's index so it is
    // rescanned, and demand a refusal.
    let mut bytes = original.clone();
    bytes[40] ^= 0x20;
    fs::write(&first, &bytes).unwrap();
    fs::remove_file(dir.path().join("seg-00000001.idx")).unwrap();
    assert!(matches!(
        Journal::open(dir.path(), "main", small_segments()),
        Err(StoreError::Corrupt { .. })
    ));
    // Even with a trusted index, deep verification catches it.
    fs::write(&first, &original).unwrap();
    let journal = open(dir.path());
    drop(journal);
    fs::write(&first, &bytes).unwrap();
    let journal = open(dir.path());
    assert!(journal.verify_deep().is_err());
    drop(journal);
    // Shortening a sealed segment is a rewritten history, not a torn tail.
    fs::write(&first, &original[..original.len() - 10]).unwrap();
    assert!(matches!(
        Journal::open(dir.path(), "main", small_segments()),
        Err(StoreError::Corrupt { .. })
    ));
}

#[test]
fn derived_indexes_rebuild_identically() {
    let dir = tempfile::tempdir().unwrap();
    {
        let mut journal = open(dir.path());
        fill(&mut journal, 80, 5);
        journal.compact_indexes().unwrap();
        fill(&mut journal, 95, 5);
    }
    let reference: Vec<_> = {
        let journal = open(dir.path());
        (1..=95).map(|s| journal.record(s).unwrap()).collect()
    };
    type Damage = (&'static str, fn(&Path));
    let damage: &[Damage] = &[
        ("delete every idx", |d| {
            for e in fs::read_dir(d).unwrap() {
                let p = e.unwrap().path();
                if p.extension().is_some_and(|x| x == "idx") {
                    fs::remove_file(p).unwrap();
                }
            }
        }),
        ("garbage idx", |d| {
            fs::write(d.join("seg-00000002.idx"), b"not an index").unwrap()
        }),
        ("torn idx record", |d| {
            let p = d.join("seg-00000003.idx");
            let b = fs::read(&p).unwrap();
            fs::write(&p, &b[..b.len() - 5]).unwrap();
        }),
        ("garbage tables", |d| {
            fs::write(d.join("requests.tbl"), b"junk").unwrap();
            fs::write(d.join("payloads.tbl"), b"KMKTAB02junk").unwrap();
        }),
        ("delete tables", |d| {
            let _ = fs::remove_file(d.join("requests.tbl"));
            let _ = fs::remove_file(d.join("payloads.tbl"));
        }),
    ];
    for (name, apply) in damage {
        apply(dir.path());
        let journal = open(dir.path());
        let records: Vec<_> = (1..=95).map(|s| journal.record(s).unwrap()).collect();
        assert_eq!(records, reference, "{name}");
        assert_eq!(journal.head(), expected_head(95), "{name}");
        journal
            .verify_deep()
            .unwrap_or_else(|e| panic!("{name}: {e}"));
        for seq in [1, 50, 95] {
            assert_eq!(
                journal
                    .by_request(&format!("req-{seq}"))
                    .unwrap()
                    .unwrap()
                    .seq,
                seq,
                "{name}"
            );
        }
    }
}

#[test]
fn tampered_index_record_is_caught_by_deep_verification() {
    let dir = tempfile::tempdir().unwrap();
    {
        let mut journal = open(dir.path());
        fill(&mut journal, 40, 4);
    }
    let idx = dir.path().join("seg-00000001.idx");
    let mut bytes = fs::read(&idx).unwrap();
    bytes[16 + 32] ^= 1; // first record's event_id
    fs::write(&idx, &bytes).unwrap();
    let journal = open(dir.path());
    assert!(
        journal.read(1).is_err(),
        "read re-verifies the frame against its record"
    );
    assert!(journal.verify_deep().is_err());
}

#[test]
fn oversized_and_empty_inputs_are_rejected() {
    let dir = tempfile::tempdir().unwrap();
    let mut journal = Journal::open(dir.path(), "main", JournalOptions::default()).unwrap();
    let huge = vec![b'x'; 17 * 1024 * 1024];
    assert!(matches!(
        journal.append_batch(&[NewEvent {
            event: &huge,
            payload: b""
        }]),
        Err(StoreError::TooLarge(_))
    ));
    assert!(journal.append_batch(&[]).unwrap().is_empty());
    let not_object = canonical(&serde_json::json!([1, 2])).unwrap();
    assert!(journal
        .append_batch(&[NewEvent {
            event: &not_object,
            payload: b""
        }])
        .is_err());
    assert_eq!(journal.seq(), 0);
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

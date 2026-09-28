//! Property test: random interleavings of appends, reopens, index compaction, torn garbage
//! and zero-filled tails never change what is committed. The model is simply "events 1..=n",
//! whose head is computed independently of the store.

mod common;

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

use common::{expected_head, fill, make, small_segments};
use kammi_store::Journal;
use proptest::prelude::*;

#[derive(Debug, Clone)]
enum Op {
    Append(usize),
    Reopen,
    Compact,
    TornGarbage(Vec<u8>),
    ZeroTail(usize),
    PartialNextFrame(usize),
}

fn op() -> impl Strategy<Value = Op> {
    prop_oneof![
        4 => (1usize..12).prop_map(Op::Append),
        2 => Just(Op::Reopen),
        1 => Just(Op::Compact),
        1 => proptest::collection::vec(1u8..=255, 1..40).prop_map(Op::TornGarbage),
        1 => (1usize..600).prop_map(Op::ZeroTail),
        1 => (1usize..200).prop_map(Op::PartialNextFrame),
    ]
}

fn active_segment(dir: &Path) -> std::path::PathBuf {
    let mut segments: Vec<_> = fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|x| x == "seg"))
        .collect();
    segments.sort();
    segments.pop().unwrap()
}

fn append_raw(dir: &Path, bytes: &[u8]) {
    OpenOptions::new()
        .append(true)
        .open(active_segment(dir))
        .unwrap()
        .write_all(bytes)
        .unwrap();
}

proptest! {
    #![proptest_config(ProptestConfig { cases: 64, ..ProptestConfig::default() })]

    #[test]
    fn committed_history_survives_any_interleaving(ops in proptest::collection::vec(op(), 1..40)) {
        let dir = tempfile::tempdir().unwrap();
        let mut committed = 0u64;
        let mut journal = Some(Journal::open(dir.path(), "main", small_segments()).unwrap());
        for op in ops {
            match op {
                Op::Append(count) => {
                    committed += count as u64;
                    fill(journal.as_mut().unwrap(), committed, 3);
                }
                Op::Reopen => {
                    drop(journal.take()); // release the files before reopening
                    journal = Some(Journal::open(dir.path(), "main", small_segments()).unwrap());
                }
                Op::Compact => journal.as_mut().unwrap().compact_indexes().unwrap(),
                Op::TornGarbage(_) | Op::ZeroTail(_) | Op::PartialNextFrame(_) => {
                    // A crash leaves uncommitted bytes after the last frame; reopen must drop them.
                    drop(journal.take());
                    match op {
                        // A header claiming more body than follows: an interrupted append.
                        Op::TornGarbage(bytes) => {
                            let claimed = (bytes.len() as u32 + 100).to_le_bytes();
                            append_raw(dir.path(), &[claimed.as_slice(), bytes.as_slice()].concat());
                        }
                        Op::ZeroTail(n) => append_raw(dir.path(), &vec![0u8; n]),
                        Op::PartialNextFrame(n) => {
                            let (event, payload) = make(committed + 1, expected_head(committed));
                            let mut frame = Vec::new();
                            frame.extend_from_slice(&((5 + event.len() + payload.len()) as u32).to_le_bytes());
                            frame.push(1);
                            frame.extend_from_slice(&(event.len() as u32).to_le_bytes());
                            frame.extend_from_slice(&event);
                            frame.extend_from_slice(&payload);
                            append_raw(dir.path(), &frame[..n.min(frame.len())]);
                        }
                        _ => unreachable!(),
                    }
                    journal = Some(Journal::open(dir.path(), "main", small_segments()).unwrap());
                }
            }
            let j = journal.as_ref().unwrap();
            prop_assert_eq!(j.seq(), committed);
            prop_assert_eq!(j.head(), expected_head(committed));
        }
        let j = journal.as_ref().unwrap();
        j.verify_deep().unwrap();
        for seq in 1..=committed {
            prop_assert_eq!(j.by_request(&format!("req-{seq}")).unwrap().unwrap().seq, seq);
        }
    }
}

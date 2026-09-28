mod common;

use std::fs::{self, OpenOptions};
use std::io::Write;

use common::{expected_head, fill, make, small_segments};
use kammi_jcs::Sha256Id;
use kammi_store::{Journal, JournalFollower, StoreError};

fn drain(follower: &mut JournalFollower) -> Vec<u64> {
    let mut seqs = Vec::new();
    while let Some(event) = follower.next_event().unwrap() {
        seqs.push(event.seq);
    }
    seqs
}

#[test]
fn follows_a_live_writer_across_rollovers_and_resumes() {
    let root = tempfile::tempdir().unwrap();
    let dir = root.path().join("journal").join("main");
    fs::create_dir_all(&dir).unwrap();
    let mut follower = JournalFollower::new(root.path(), "main");
    assert!(
        follower.next_event().unwrap().is_none(),
        "empty journal: nothing yet"
    );

    let mut journal = Journal::open(&dir, "main", small_segments()).unwrap();
    let mut seen = Vec::new();
    for to in [1, 7, 40, 41, 120] {
        fill(&mut journal, to, 5);
        seen.extend(drain(&mut follower));
        assert_eq!(follower.seq(), to);
        assert_eq!(follower.head(), expected_head(to));
    }
    assert_eq!(seen, (1..=120).collect::<Vec<_>>());
    assert!(journal.segment_count() > 5, "small segments must roll over");

    // Payloads come back verified and in order.
    let mut resumed = JournalFollower::resume(root.path(), "main", 60, expected_head(60));
    let first = resumed.next_event().unwrap().unwrap();
    assert_eq!(first.seq, 61);
    assert_eq!(
        (first.event.clone(), first.payload.clone()),
        make(61, expected_head(60))
    );
    assert_eq!(drain(&mut resumed), (62..=120).collect::<Vec<_>>());

    // Resuming with a head that is not the committed event at that seq is refused.
    let mut wrong = JournalFollower::resume(root.path(), "main", 60, Sha256Id::ZERO);
    assert!(wrong.next_event().is_err());
}

#[test]
fn torn_tail_is_not_delivered_until_the_writer_commits_past_it() {
    let root = tempfile::tempdir().unwrap();
    let dir = root.path().join("journal").join("main");
    fs::create_dir_all(&dir).unwrap();
    {
        let mut journal = Journal::open(&dir, "main", small_segments()).unwrap();
        fill(&mut journal, 10, 3);
    }
    let mut follower = JournalFollower::new(root.path(), "main");
    assert_eq!(drain(&mut follower).len(), 10);

    // Half a frame appended by a writer that died mid-write.
    let mut segments: Vec<_> = fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|x| x == "seg"))
        .collect();
    segments.sort();
    let last = segments.pop().unwrap();
    let torn = [0x40u8, 0, 0, 0, 1, 2, 3];
    OpenOptions::new()
        .append(true)
        .open(&last)
        .unwrap()
        .write_all(&torn)
        .unwrap();
    assert!(
        follower.next_event().unwrap().is_none(),
        "incomplete frame is not committed"
    );
    assert_eq!(follower.seq(), 10);

    // The writer reopens (cutting the tail into recovery/) and commits more.
    let mut journal = Journal::open(&dir, "main", small_segments()).unwrap();
    fill(&mut journal, 14, 2);
    assert_eq!(drain(&mut follower), vec![11, 12, 13, 14]);
    assert_eq!(follower.head(), expected_head(14));
}

#[test]
fn committed_corruption_is_an_error_not_a_stop() {
    let root = tempfile::tempdir().unwrap();
    let dir = root.path().join("journal").join("main");
    fs::create_dir_all(&dir).unwrap();
    {
        let mut journal = Journal::open(&dir, "main", small_segments()).unwrap();
        fill(&mut journal, 3, 3);
    }
    let segment = fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|x| x == "seg"))
        .unwrap();
    let mut bytes = fs::read(&segment).unwrap();
    let flip = bytes.len() - 40; // inside the last frame's body
    bytes[flip] ^= 1;
    fs::write(&segment, bytes).unwrap();
    let mut follower = JournalFollower::new(root.path(), "main");
    assert_eq!(follower.next_event().unwrap().unwrap().seq, 1);
    assert_eq!(follower.next_event().unwrap().unwrap().seq, 2);
    assert!(matches!(
        follower.next_event(),
        Err(StoreError::Corrupt { .. })
    ));
}

//! Reads the real Python-written stores named in `KAMMI_V1_CORPUS` (`;`-separated roots):
//! every committed event of both journals, every payload object, and a full streaming
//! verification of every loose CAS object. Skipped when the variable is unset.

use std::time::Instant;

use kammi_v1::V1Store;

#[test]
fn real_stores_read_and_verify_completely() {
    let Ok(roots) = std::env::var("KAMMI_V1_CORPUS") else {
        eprintln!("skipped: set KAMMI_V1_CORPUS to v1 store roots separated by ';'");
        return;
    };
    for root in roots.split(';').filter(|r| !r.is_empty()) {
        let store = V1Store::open(root).unwrap();
        let started = Instant::now();
        let mut main = store.main_journal().unwrap();
        let events = main.read_all().unwrap();
        let memory_events = match store.memory_journal().unwrap() {
            Some(mut journal) => journal.read_all().unwrap(),
            None => Vec::new(),
        };
        let replay = started.elapsed();
        for event in events.iter().chain(memory_events.iter()) {
            store.read_object(&event.payload_artifact()).unwrap();
        }
        let payloads = started.elapsed() - replay;

        let hashing = Instant::now();
        let ids = store.object_ids().unwrap();
        let mut bytes = 0u64;
        for id in &ids {
            assert!(
                store.verify_object(id).unwrap(),
                "object {id} fails verification"
            );
            bytes += store.object_len(id).unwrap();
        }
        let hash_time = hashing.elapsed();
        eprintln!(
            "{root}: {} main + {} memory events (head {}), read in {replay:?}; payloads in {payloads:?}; \
             {} objects / {:.1} MiB verified in {hash_time:?} ({:.0} MiB/s)",
            events.len(),
            memory_events.len(),
            main.head(),
            ids.len(),
            bytes as f64 / 1048576.0,
            bytes as f64 / 1048576.0 / hash_time.as_secs_f64(),
        );
        assert!(!events.is_empty());
    }
}

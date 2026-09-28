//! Phase 1 acceptance on real Python-written stores.
//!
//! `KAMMI_V1_CORPUS` lists v1 store roots (`;`-separated); they are only read. Work goes to
//! `KAMMI_WORK_DIR` (default: the system temp directory). With `KAMMI_JCS_PYTHON` and
//! `KAMMI_LEDGER_PY` set, the unmodified Python journal and CAS code also judge the export.
//! For each store: import, re-import (must be a no-op), deep verify, heads equal the v1
//! reader's, export to v1 layout, byte-compare with the original, and optionally the Python
//! oracle. A live store may grow during the run; the comparison then re-syncs once.

use std::path::PathBuf;
use std::process::Command;

use kammi_migrate::{compare_v1, export_v1, sync};
use kammi_store::{Store, StoreOptions};
use kammi_v1::V1Store;

#[test]
fn real_stores_import_and_round_trip_exactly() {
    let Ok(roots) = std::env::var("KAMMI_V1_CORPUS") else {
        eprintln!("skipped: set KAMMI_V1_CORPUS");
        return;
    };
    let base = std::env::var("KAMMI_WORK_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::temp_dir());
    std::fs::create_dir_all(&base).unwrap();
    for root in roots.split(';').filter(|r| !r.is_empty()) {
        let work = tempfile::tempdir_in(&base).unwrap();
        let v1 = V1Store::open(root).unwrap();
        let v2 = work.path().join("v2");
        let mut store = Store::create(&v2, StoreOptions::default()).unwrap();
        let first = sync(&v1, &mut store).unwrap();
        let second = sync(&v1, &mut store).unwrap();
        assert_eq!(second.objects_copied, 0);
        store.verify_deep().unwrap();

        let mut main = v1.main_journal().unwrap();
        main.read_all().unwrap();
        assert_eq!(store.main.head(), main.head());
        if let Some(mut memory) = v1.memory_journal().unwrap() {
            memory.read_all().unwrap();
            assert_eq!(store.memory.head(), memory.head());
        }

        drop(store);
        let store = Store::open(&v2, StoreOptions::default()).unwrap();
        let exported = work.path().join("exported");
        export_v1(&store, &exported).unwrap();
        let (main_bytes, memory_bytes, objects) =
            compare_v1(&v1, &V1Store::open(&exported).unwrap()).unwrap();
        eprintln!(
            "{root}: imported {} + {} events, {} objects ({} bytes) in {:.1}s; export identical: \
             {main_bytes} + {memory_bytes} journal bytes, {objects} objects",
            first.main.appended + second.main.appended,
            first.memory.appended + second.memory.appended,
            first.objects_copied,
            first.object_bytes_copied,
            first.seconds,
        );

        if let (Ok(python), Ok(ledger)) = (
            std::env::var("KAMMI_JCS_PYTHON"),
            std::env::var("KAMMI_LEDGER_PY"),
        ) {
            let script =
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tools/v1_store_oracle.py");
            let output = Command::new(python)
                .arg(script)
                .arg(ledger)
                .arg(&exported)
                .env("PYTHONDONTWRITEBYTECODE", "1")
                .output()
                .unwrap();
            assert!(
                output.status.success(),
                "Python rejected the export: {}",
                String::from_utf8_lossy(&output.stderr)
            );
            let verdict = String::from_utf8(output.stdout).unwrap();
            assert!(
                verdict.contains(&store.main.head().to_string()),
                "{verdict}"
            );
            eprintln!("  python oracle: {}", verdict.trim());
        }
    }
}

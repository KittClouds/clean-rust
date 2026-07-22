use std::fs;
use std::path::PathBuf;

use phoenix_graph_kernel::{KernelGraphSnapshot, KernelVertex, KernelVertexClass, KernelVertexId};
use phoenix_store_native_core::PhoenixGraphKernelStoreV2;

use super::PhoenixOvergraphStore;

#[test]
fn current_checkpoint_with_empty_journal_uses_direct_snapshot_fast_path() {
    let path = temp_store_path("kernel-replay-fast-path");
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    store.init_graph_kernel_schema().expect("init kernel");
    let snapshot = KernelGraphSnapshot {
        vertices: vec![KernelVertex {
            id: KernelVertexId("doc:1".to_owned()),
            kind: "document".to_owned(),
            class: KernelVertexClass::Document,
            ..KernelVertex::default()
        }],
        asserted_edges: Vec::new(),
        candidate_edges: Vec::new(),
    };
    store
        .write_kernel_checkpoint(1, "test-checkpoint", &snapshot)
        .expect("write checkpoint");
    store.close_fast().expect("close store");

    let reopened = PhoenixOvergraphStore::open(&path).expect("reopen store");
    let result = reopened
        .audit_live_kernel_snapshot_replay()
        .expect("audit replay");

    assert!(result.audit.checkpoint_present);
    assert!(result.audit.checkpoint_fast_path);
    assert_eq!(result.audit.journal_len, 0);
    assert_eq!(result.audit.journal_entry_count, 0);
    assert_eq!(result.audit.hydrated_commit_count, 0);
    assert_eq!(result.audit.timings.checkpoint_rebuild_us, 0);
    assert_eq!(result.audit.timings.journal_node_scan_us, 0);
    assert_eq!(result.snapshot, snapshot);

    reopened.close_fast().expect("close reopened");
    let _ = fs::remove_dir_all(path);
}

fn temp_store_path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "phoenix-{name}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ))
}

use phoenix_graph_kernel::{
    GraphTruthCommit, GraphTruthLineage, KernelGraphLayer, KernelJournalEntry, KernelMutationBatch,
    KernelMutationScope, KernelVertex, KernelVertexId,
};
use phoenix_store_native_core::{GraphTruthCommitAppend, PhoenixGraphKernelStoreV2, StoreError};
use phoenix_types::{
    GraphTruthCommitHeader, GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthDigest,
    GraphTruthKind, GraphTruthOperation, GraphTruthPlane, GraphTruthSourceGenerationRef,
};
use serde_json::json;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

use super::graph_truth_persistence::{
    append_graph_truth_commit_with_fault, CommitFaultPoint, TYPE_GRAPH_TRUTH_COMMIT,
};
use super::{
    now_ms, OvergraphTuning, PhoenixOvergraphStore, TYPE_KERNEL_COMMIT, TYPE_KERNEL_JOURNAL,
    TYPE_KERNEL_STATE,
};

fn commit(
    id: &str,
    generation: u64,
    operation: GraphTruthOperation,
    vertex_id: Option<&str>,
) -> GraphTruthCommit {
    let mut header = GraphTruthCommitHeader {
        commit_id: id.into(),
        generation,
        operation,
        truth: GraphTruthDescriptor {
            kind: GraphTruthKind::Assertion,
            plane: Some(GraphTruthPlane::WorldState),
        },
        source_generations: [GraphTruthSourceGenerationRef {
            source_id: "test:scope-1".into(),
            generation,
        }]
        .into_iter()
        .collect(),
        receipt_ids: [format!("receipt:{id}").into()].into_iter().collect(),
        compiler_policy: GraphTruthCompilerPolicy {
            compiler_id: "test-compiler".into(),
            compiler_version: "1".into(),
            policy_id: "test-policy".into(),
            policy_version: "1".into(),
        },
        idempotency_hash: GraphTruthDigest([generation as u8; 32]),
        committed_at: generation as i64,
        ..GraphTruthCommitHeader::default()
    };
    if matches!(operation, GraphTruthOperation::Retract) {
        header.predecessor_commit_ids.push("commit-1".into());
    }

    GraphTruthCommit {
        header,
        batch: KernelMutationBatch {
            layer: KernelGraphLayer::Asserted,
            scope: KernelMutationScope::Projection {
                scope_key: "scope-1".to_owned(),
            },
            recorded_at: Some(generation as i64),
            vertices: vertex_id
                .map(|vertex_id| KernelVertex {
                    id: KernelVertexId(vertex_id.to_owned()),
                    kind: "claim".to_owned(),
                    value: json!({"id": vertex_id}),
                    attributes: json!({}),
                    ..KernelVertex::default()
                })
                .into_iter()
                .collect(),
            edges: Vec::new(),
        },
    }
}

fn temp_path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "phoenix-graph-truth-{name}-{}-{}",
        std::process::id(),
        now_ms()
    ))
}

fn count_type(store: &PhoenixOvergraphStore, type_id: u32) -> usize {
    store
        .with_engine(|engine| {
            engine
                .count_nodes_by_type(type_id)
                .map(|count| count as usize)
                .map_err(super::store_query_error)
        })
        .expect("count persisted nodes")
}

fn assert_storage_counts(store: &PhoenixOvergraphStore, expected: usize) {
    assert_eq!(count_type(store, TYPE_KERNEL_JOURNAL), expected);
    assert_eq!(count_type(store, TYPE_GRAPH_TRUTH_COMMIT), expected);
    assert_eq!(count_type(store, TYPE_KERNEL_COMMIT), expected);
    assert_eq!(count_type(store, TYPE_KERNEL_STATE), expected.min(1));
}

#[test]
fn pre_write_faults_cannot_persist_partial_graph_truth_commits() {
    let faults = [
        CommitFaultPoint::JournalPrepared,
        CommitFaultPoint::CommitPrepared,
        CommitFaultPoint::IndexPrepared,
        CommitFaultPoint::GenerationPrepared,
    ];

    for (index, fault) in faults.into_iter().enumerate() {
        let path = temp_path(&format!("pre-write-{index}"));
        let store = PhoenixOvergraphStore::open(&path).expect("open store");
        let result = store.with_engine(|engine| {
            append_graph_truth_commit_with_fault(
                &store,
                engine,
                &commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1")),
                fault,
            )
        });
        assert!(matches!(result, Err(StoreError::Query(_))));
        assert_storage_counts(&store, 0);
        assert_eq!(store.kernel_current_generation().expect("generation"), 0);
        assert_eq!(store.kernel_journal_len().expect("journal length"), 0);
        store.close_fast().expect("close store");
        let _ = fs::remove_dir_all(path);
    }
}

#[test]
fn lost_ack_retry_reopens_without_duplicate_journal_or_topology() {
    let path = temp_path("lost-ack");
    let value = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    let result = store.with_engine(|engine| {
        append_graph_truth_commit_with_fault(
            &store,
            engine,
            &value,
            CommitFaultPoint::AtomicWriteCompleted,
        )
    });
    assert!(matches!(result, Err(StoreError::Query(_))));
    assert_storage_counts(&store, 1);
    store.close_fast().expect("sync WAL and close");

    let reopened = PhoenixOvergraphStore::open(&path).expect("reopen store");
    assert_eq!(
        reopened
            .append_graph_truth_commit(&value)
            .expect("idempotent retry"),
        GraphTruthCommitAppend::AlreadyPresent {
            commit_id: "commit-1".to_owned(),
            generation: 1,
        }
    );
    assert_storage_counts(&reopened, 1);
    assert_eq!(reopened.kernel_journal_len().expect("journal length"), 1);
    let raw_journal = reopened
        .with_engine(|engine| {
            let node = engine
                .get_nodes_by_type(TYPE_KERNEL_JOURNAL)
                .map_err(super::store_query_error)?
                .pop()
                .expect("persisted journal node");
            super::decode_record_prop_required::<KernelJournalEntry>(&node, super::PROP_RECORD)
        })
        .expect("decode persisted journal");
    assert!(
        raw_journal.batch.is_none(),
        "journal must only reference the commit"
    );
    let entries = reopened.load_kernel_journal_after(0).expect("load journal");
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].batch.as_ref(), Some(&value.batch));
    let snapshot = reopened
        .with_engine(|engine| reopened.load_live_kernel_snapshot_with_engine(engine))
        .expect("replay graph truth commit");
    assert_eq!(snapshot.vertices.len(), 1);
    assert_eq!(snapshot.vertices[0].id.0, "claim-1");
    reopened.close_fast().expect("close reopened store");
    let _ = fs::remove_dir_all(path);
}

#[test]
fn checkpoint_compaction_preserves_commit_lookup_and_reversal_lineage() {
    let path = temp_path("checkpoint-lineage");
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    let asserted = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));
    let retracted = commit("commit-2", 2, GraphTruthOperation::Retract, None);
    assert_eq!(
        store
            .append_graph_truth_commit(&asserted)
            .expect("append assertion"),
        GraphTruthCommitAppend::Appended
    );
    assert_eq!(
        store
            .append_graph_truth_commit(&retracted)
            .expect("append retraction"),
        GraphTruthCommitAppend::Appended
    );
    let snapshot = store
        .with_engine(|engine| store.load_live_kernel_snapshot_with_engine(engine))
        .expect("load snapshot");
    store
        .write_kernel_checkpoint(2, "test:scope-1", &snapshot)
        .expect("write checkpoint");

    assert_eq!(store.kernel_journal_len().expect("journal length"), 0);
    assert_eq!(count_type(&store, TYPE_KERNEL_JOURNAL), 0);
    assert_eq!(count_type(&store, TYPE_GRAPH_TRUTH_COMMIT), 2);
    assert_eq!(count_type(&store, TYPE_KERNEL_COMMIT), 2);
    assert_eq!(
        store
            .kernel_generation_for_commit("commit-1")
            .expect("assert lookup"),
        Some(1)
    );
    assert_eq!(
        store
            .kernel_generation_for_commit("commit-2")
            .expect("retract lookup"),
        Some(2)
    );
    let commits = store
        .load_graph_truth_commits()
        .expect("load retained lineage");
    assert_eq!(commits.len(), 2);
    let lineage = GraphTruthLineage::build(commits).expect("rebuild lineage");
    assert_eq!(lineage.active_atom_count(), 0);
    assert_eq!(
        lineage.commits()[1].header.predecessor_commit_ids[0].as_str(),
        "commit-1"
    );

    store.close_fast().expect("close store");
    let reopened = PhoenixOvergraphStore::open(&path).expect("reopen checkpoint");
    assert_eq!(
        reopened
            .load_graph_truth_commit("commit-2")
            .expect("load retraction after restart"),
        Some(retracted)
    );
    reopened.close_fast().expect("close reopened store");
    let _ = fs::remove_dir_all(path);
}

#[test]
fn checkpoint_policy_keeps_small_journal_delta_hot() {
    let path = temp_path("checkpoint-policy-hot");
    let store = PhoenixOvergraphStore::open_with_tuning(
        &path,
        OvergraphTuning {
            kernel_checkpoint_hot_journal_bytes: usize::MAX,
            kernel_checkpoint_replay_cost_us: u64::MAX,
            ..OvergraphTuning::default()
        },
    )
    .expect("open store");
    let value = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));

    assert_eq!(
        store
            .append_graph_truth_commit(&value)
            .expect("append assertion"),
        GraphTruthCommitAppend::Appended
    );

    assert_eq!(store.kernel_journal_len().expect("journal length"), 1);
    assert!(
        store
            .load_kernel_checkpoint()
            .expect("load checkpoint")
            .is_none(),
        "below byte and replay thresholds the journal delta should stay hot"
    );

    store.close_fast().expect("close store");
    let _ = fs::remove_dir_all(path);
}

#[test]
fn checkpoint_policy_compacts_when_hot_journal_bytes_cross_threshold() {
    let path = temp_path("checkpoint-policy-bytes");
    let store = PhoenixOvergraphStore::open_with_tuning(
        &path,
        OvergraphTuning {
            kernel_checkpoint_hot_journal_bytes: 1,
            kernel_checkpoint_replay_cost_us: u64::MAX,
            ..OvergraphTuning::default()
        },
    )
    .expect("open store");
    let value = commit("commit-1", 1, GraphTruthOperation::Assert, Some("claim-1"));

    assert_eq!(
        store
            .append_graph_truth_commit(&value)
            .expect("append assertion"),
        GraphTruthCommitAppend::Appended
    );

    assert_eq!(store.kernel_journal_len().expect("journal length"), 0);
    let checkpoint = store
        .load_kernel_checkpoint()
        .expect("load checkpoint")
        .expect("policy checkpoint");
    assert_eq!(checkpoint.meta.generation, 1);
    assert_eq!(checkpoint.snapshot.vertices.len(), 1);

    store.close_fast().expect("close store");
    let _ = fs::remove_dir_all(path);
}

#[test]
fn atomic_commit_scale_smoke_keeps_one_record_per_generation() {
    const COMMIT_COUNT: u64 = 192;
    let path = temp_path("scale-smoke");
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    let started = Instant::now();

    for generation in 1..=COMMIT_COUNT {
        let commit_id = format!("commit-{generation}");
        let vertex_id = format!("claim-{generation}");
        let value = commit(
            &commit_id,
            generation,
            GraphTruthOperation::Assert,
            Some(&vertex_id),
        );
        assert_eq!(
            store
                .append_graph_truth_commit(&value)
                .expect("append scale commit"),
            GraphTruthCommitAppend::Appended
        );
    }

    let elapsed = started.elapsed();
    eprintln!(
        "atomic graph truth scale smoke: {} commits in {:?}",
        COMMIT_COUNT, elapsed
    );
    assert_eq!(
        store.kernel_current_generation().expect("generation"),
        COMMIT_COUNT
    );
    assert_eq!(
        store.kernel_journal_len().expect("journal length"),
        COMMIT_COUNT as usize
    );
    assert_eq!(
        count_type(&store, TYPE_GRAPH_TRUTH_COMMIT),
        COMMIT_COUNT as usize
    );
    assert_eq!(
        count_type(&store, TYPE_KERNEL_COMMIT),
        COMMIT_COUNT as usize
    );
    assert_eq!(
        store
            .load_graph_truth_commits()
            .expect("load scale commits")
            .len(),
        COMMIT_COUNT as usize
    );

    store.close_fast().expect("close store");
    let _ = fs::remove_dir_all(path);
}

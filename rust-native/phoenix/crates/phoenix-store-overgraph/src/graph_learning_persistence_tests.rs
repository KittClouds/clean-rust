use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_graph_kernel::{
    GraphProposalBatchReceipt, GraphProposalFeatures, GraphProposalObservation,
    GraphProposalStatus, GraphTruthAtomKey, GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
};
use phoenix_store_native_core::{GraphProposalReceiptAppend, PhoenixGraphLearningStore};
use phoenix_types::{
    GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthKind, GraphTruthPlane,
    GraphTruthSourceGenerationRef,
};

use super::PhoenixOvergraphStore;

fn receipt(id: &str, generation: u64, count: usize) -> GraphProposalBatchReceipt {
    GraphProposalBatchReceipt {
        schema_version: GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
        receipt_id: id.into(),
        scope_key: "scope:test".into(),
        generation,
        created_at: 1_700_000_000_000 + generation as i64,
        compiler_policy: GraphTruthCompilerPolicy {
            compiler_id: "phoenix-graph-post".into(),
            compiler_version: "0.1.1".into(),
            policy_id: "graph-post-proposal:semantic-phase5".into(),
            policy_version: "1".into(),
        },
        source_generations: [GraphTruthSourceGenerationRef {
            source_id: "semantic-graph:scope:test".into(),
            generation,
        }]
        .into_iter()
        .collect(),
        model_id: Some("promotion-test-v1".into()),
        proposals: (0..count)
            .map(|index| GraphProposalObservation {
                proposal_id: format!("proposal-{generation}-{index}").into(),
                atom: GraphTruthAtomKey::edge(
                    &format!("entity-{index}"),
                    &format!("state-{index}"),
                    "semantic::entity_state_support",
                ),
                family: "entityStateSupport".into(),
                source_kind: "entity".into(),
                target_kind: "state".into(),
                truth: GraphTruthDescriptor {
                    kind: GraphTruthKind::Semantic,
                    plane: Some(GraphTruthPlane::WorldState),
                },
                status: GraphProposalStatus::ReviewedSupport,
                evidence_refs: ["evidence:shared".into(), format!("evidence:{index}").into()]
                    .into_iter()
                    .collect(),
                features: GraphProposalFeatures([index.min(1000) as i16; 16]),
                shadow_score_millis: Some(700),
            })
            .collect(),
    }
}

#[test]
fn compact_receipt_roundtrips_idempotently_across_restart() {
    let path = temp_path("roundtrip");
    let value = receipt("receipt-1", 1, 24);
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    let appended = store
        .append_graph_proposal_receipt(&value)
        .expect("append receipt");
    assert!(matches!(
        appended,
        GraphProposalReceiptAppend::Appended { .. }
    ));
    assert_eq!(
        store
            .append_graph_proposal_receipt(&value)
            .expect("retry receipt"),
        GraphProposalReceiptAppend::AlreadyPresent {
            receipt_id: "receipt-1".to_owned()
        }
    );
    store.close_fast().expect("close store");

    let reopened = PhoenixOvergraphStore::open(&path).expect("reopen store");
    assert_eq!(
        reopened
            .load_graph_proposal_receipt("receipt-1")
            .expect("load receipt"),
        Some(value.clone())
    );
    assert_eq!(
        reopened
            .load_graph_proposal_receipts()
            .expect("load receipts"),
        vec![value]
    );
    reopened.close_fast().expect("close reopened store");
    let _ = fs::remove_dir_all(path);
}

#[test]
fn append_truncates_a_partial_tail_before_writing_next_record() {
    let path = temp_path("partial-tail");
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    store
        .append_graph_proposal_receipt(&receipt("receipt-1", 1, 3))
        .expect("append first");
    let log_path = store.graph_proposal_receipt_log_path();
    store.close_fast().expect("close store");
    OpenOptions::new()
        .append(true)
        .open(&log_path)
        .expect("open log")
        .write_all(b"partial")
        .expect("write partial tail");

    let reopened = PhoenixOvergraphStore::open(&path).expect("reopen store");
    reopened
        .append_graph_proposal_receipt(&receipt("receipt-2", 2, 4))
        .expect("append second");
    let values = reopened
        .load_graph_proposal_receipts()
        .expect("load receipts");
    assert_eq!(
        values
            .iter()
            .map(|value| value.receipt_id.as_str())
            .collect::<Vec<_>>(),
        vec!["receipt-1", "receipt-2"]
    );
    reopened.close_fast().expect("close reopened store");
    let _ = fs::remove_dir_all(path);
}

#[test]
fn receipt_batch_keeps_192_rows_compact_and_fast() {
    let path = temp_path("scale");
    let store = PhoenixOvergraphStore::open(&path).expect("open store");
    let value = receipt("receipt-scale", 1, 192);
    let started = Instant::now();
    let result = store
        .append_graph_proposal_receipt(&value)
        .expect("append scale receipt");
    let loaded = store
        .load_graph_proposal_receipt("receipt-scale")
        .expect("load scale receipt")
        .expect("scale receipt present");
    let elapsed = started.elapsed();
    let GraphProposalReceiptAppend::Appended { byte_len } = result else {
        panic!("scale receipt should append");
    };
    eprintln!("graph proposal receipt scale: 192 rows, {byte_len} bytes, {elapsed:?}");
    assert_eq!(loaded.proposals.len(), 192);
    assert!(byte_len < 128 * 1024, "receipt grew to {byte_len} bytes");
    assert!(elapsed.as_millis() < 500, "receipt path took {elapsed:?}");
    store.close_fast().expect("close store");
    let _ = fs::remove_dir_all(path);
}

fn temp_path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "phoenix-graph-learning-{name}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ))
}

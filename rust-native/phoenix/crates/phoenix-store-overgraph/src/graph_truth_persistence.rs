use overgraph::{DatabaseEngine, GraphPatch, NodeInput, PropValue};
use phoenix_graph_kernel::{GraphTruthCommit, KernelJournalEntry};
use phoenix_store_native_core::{GraphTruthCommitAppend, StoreError};

use super::{
    btree_props, decode_record_prop_required, encode_record, kernel_journal_key,
    optional_string_prop, optional_u64_prop, store_query_error, PhoenixOvergraphStore,
    KERNEL_STATE_KEY, PROP_BYTE_LEN, PROP_COMMIT_ID, PROP_CREATED_AT, PROP_GENERATION,
    PROP_JOURNAL_BYTES, PROP_JOURNAL_LEN, PROP_RECORD, PROP_REPLAY_COST_US, PROP_SEQ,
    PROP_SOURCE_REVISION, TYPE_KERNEL_COMMIT, TYPE_KERNEL_JOURNAL, TYPE_KERNEL_STATE,
};

pub(super) const TYPE_GRAPH_TRUTH_COMMIT: u32 = 36;
const PROP_IDEMPOTENCY_HASH: &str = "idempotency_hash";

pub(super) fn append_graph_truth_commit_with_engine(
    store: &PhoenixOvergraphStore,
    engine: &mut DatabaseEngine,
    commit: &GraphTruthCommit,
) -> Result<GraphTruthCommitAppend, StoreError> {
    append_graph_truth_commit_inner(store, engine, commit, None)
}

pub(crate) fn load_graph_truth_commit_with_engine(
    engine: &mut DatabaseEngine,
    commit_id: &str,
) -> Result<Option<GraphTruthCommit>, StoreError> {
    let Some(node) = engine
        .get_node_by_key(TYPE_GRAPH_TRUTH_COMMIT, commit_id)
        .map_err(store_query_error)?
    else {
        return Ok(None);
    };
    decode_record_prop_required(&node, PROP_RECORD).map(Some)
}

pub(super) fn load_graph_truth_commits_with_engine(
    engine: &mut DatabaseEngine,
) -> Result<Vec<GraphTruthCommit>, StoreError> {
    let mut commits = engine
        .get_nodes_by_type(TYPE_GRAPH_TRUTH_COMMIT)
        .map_err(store_query_error)?
        .into_iter()
        .map(|node| decode_record_prop_required::<GraphTruthCommit>(&node, PROP_RECORD))
        .collect::<Result<Vec<_>, _>>()?;
    commits.sort_unstable_by(|left, right| {
        left.header
            .generation
            .cmp(&right.header.generation)
            .then_with(|| left.header.commit_id.cmp(&right.header.commit_id))
    });
    Ok(commits)
}

pub(super) fn kernel_generation_for_commit_with_engine(
    engine: &mut DatabaseEngine,
    commit_id: &str,
) -> Result<Option<u64>, StoreError> {
    if let Some(node) = engine
        .get_node_by_key(TYPE_GRAPH_TRUTH_COMMIT, commit_id)
        .map_err(store_query_error)?
    {
        return Ok(optional_u64_prop(&node, PROP_GENERATION));
    }

    // Compatibility for commit markers written before GraphTruthCommit existed.
    Ok(engine
        .get_node_by_key(TYPE_KERNEL_COMMIT, commit_id)
        .map_err(store_query_error)?
        .and_then(|node| optional_u64_prop(&node, PROP_GENERATION)))
}

pub(crate) fn hydrate_graph_truth_journal_entry(
    engine: &mut DatabaseEngine,
    entry: &mut KernelJournalEntry,
) -> Result<(), StoreError> {
    if entry.batch.is_some() {
        return Ok(());
    }
    let Some(commit_id) = entry.commit_id.as_deref() else {
        return Ok(());
    };
    if let Some(commit) = load_graph_truth_commit_with_engine(engine, commit_id)? {
        entry.batch = Some(commit.batch);
    }
    Ok(())
}

fn append_graph_truth_commit_inner(
    store: &PhoenixOvergraphStore,
    engine: &mut DatabaseEngine,
    commit: &GraphTruthCommit,
    fault: Option<CommitFaultPoint>,
) -> Result<GraphTruthCommitAppend, StoreError> {
    commit
        .validate()
        .map_err(|error| StoreError::Query(error.to_string()))?;

    if let Some(existing) = load_graph_truth_commit_with_engine(engine, commit.commit_id())? {
        if existing == *commit {
            return Ok(GraphTruthCommitAppend::AlreadyPresent {
                commit_id: existing.header.commit_id.to_string(),
                generation: existing.header.generation,
            });
        }
        return Err(StoreError::Query(format!(
            "graph truth commit id '{}' already stores different content",
            commit.commit_id()
        )));
    }

    let idempotency_key = digest_key(commit.header.idempotency_hash.0);
    if let Some(index) = engine
        .get_node_by_key(TYPE_KERNEL_COMMIT, &idempotency_key)
        .map_err(store_query_error)?
    {
        let existing_id = optional_string_prop(&index, PROP_COMMIT_ID).unwrap_or_default();
        return Err(StoreError::Query(format!(
            "graph truth idempotency hash is already committed as '{existing_id}'"
        )));
    }

    ensure_lineage_references_exist(engine, commit)?;
    let current_generation = store.kernel_current_generation_with_engine(engine)?;
    let expected_generation = current_generation
        .checked_add(1)
        .ok_or_else(|| StoreError::Query("graph truth generation overflow".to_owned()))?;
    if commit.header.generation != expected_generation {
        return Err(StoreError::Query(format!(
            "graph truth generation must be {expected_generation}, got {}",
            commit.header.generation
        )));
    }

    let next_seq = store.kernel_journal_len_with_engine(engine)? as u64 + 1;
    let replay_cost_us = store.kernel_replay_cost_us_with_engine(engine)?;
    let source_revision = commit.header.source_generations[0].source_id.to_string();
    let journal_entry = KernelJournalEntry {
        generation: commit.header.generation,
        source_revision: source_revision.clone(),
        batch: None,
        commit_id: Some(commit.commit_id().to_owned()),
        created_at: commit.header.committed_at,
    };
    let journal_record = encode_record(&journal_entry)?;
    let commit_record = encode_record(commit)?;
    let journal_delta_bytes = journal_record.len().saturating_add(commit_record.len());
    let journal_bytes = store
        .kernel_journal_bytes_with_engine(engine)?
        .saturating_add(journal_delta_bytes);

    let mut nodes = Vec::with_capacity(4);
    nodes.push(node_input(
        TYPE_KERNEL_JOURNAL,
        kernel_journal_key(commit.header.generation, next_seq),
        btree_props([
            (PROP_SEQ, PropValue::UInt(next_seq)),
            (PROP_GENERATION, PropValue::UInt(commit.header.generation)),
            (PROP_SOURCE_REVISION, PropValue::String(source_revision)),
            (PROP_CREATED_AT, PropValue::Int(commit.header.committed_at)),
            (
                PROP_COMMIT_ID,
                PropValue::String(commit.commit_id().to_owned()),
            ),
            (PROP_BYTE_LEN, PropValue::UInt(journal_delta_bytes as u64)),
            (PROP_RECORD, PropValue::Bytes(journal_record)),
        ]),
    ));
    inject_fault(fault, CommitFaultPoint::JournalPrepared)?;

    nodes.push(node_input(
        TYPE_GRAPH_TRUTH_COMMIT,
        commit.commit_id().to_owned(),
        btree_props([
            (PROP_GENERATION, PropValue::UInt(commit.header.generation)),
            (
                PROP_COMMIT_ID,
                PropValue::String(commit.commit_id().to_owned()),
            ),
            (
                PROP_IDEMPOTENCY_HASH,
                PropValue::String(idempotency_key.clone()),
            ),
            (PROP_CREATED_AT, PropValue::Int(commit.header.committed_at)),
            (PROP_BYTE_LEN, PropValue::UInt(commit_record.len() as u64)),
            (PROP_RECORD, PropValue::Bytes(commit_record)),
        ]),
    ));
    inject_fault(fault, CommitFaultPoint::CommitPrepared)?;

    nodes.push(node_input(
        TYPE_KERNEL_COMMIT,
        idempotency_key,
        btree_props([
            (PROP_GENERATION, PropValue::UInt(commit.header.generation)),
            (
                PROP_COMMIT_ID,
                PropValue::String(commit.commit_id().to_owned()),
            ),
        ]),
    ));
    inject_fault(fault, CommitFaultPoint::IndexPrepared)?;

    nodes.push(node_input(
        TYPE_KERNEL_STATE,
        KERNEL_STATE_KEY.to_owned(),
        btree_props([
            (PROP_GENERATION, PropValue::UInt(commit.header.generation)),
            (PROP_JOURNAL_LEN, PropValue::UInt(next_seq)),
            (PROP_JOURNAL_BYTES, PropValue::UInt(journal_bytes as u64)),
            (PROP_REPLAY_COST_US, PropValue::UInt(replay_cost_us)),
        ]),
    ));
    inject_fault(fault, CommitFaultPoint::GenerationPrepared)?;

    engine
        .graph_patch(&GraphPatch {
            upsert_nodes: nodes,
            ..GraphPatch::default()
        })
        .map_err(store_query_error)?;
    inject_fault(fault, CommitFaultPoint::AtomicWriteCompleted)?;
    Ok(GraphTruthCommitAppend::Appended)
}

fn ensure_lineage_references_exist(
    engine: &mut DatabaseEngine,
    commit: &GraphTruthCommit,
) -> Result<(), StoreError> {
    for referenced_id in commit
        .header
        .predecessor_commit_ids
        .iter()
        .chain(commit.header.reverses_commit_id.iter())
    {
        if kernel_generation_for_commit_with_engine(engine, referenced_id)?.is_none() {
            return Err(StoreError::Query(format!(
                "graph truth commit '{}' references missing commit '{referenced_id}'",
                commit.commit_id()
            )));
        }
    }
    Ok(())
}

fn node_input(
    type_id: u32,
    key: String,
    props: std::collections::BTreeMap<String, PropValue>,
) -> NodeInput {
    NodeInput {
        type_id,
        key,
        props,
        weight: 1.0,
        dense_vector: None,
        sparse_vector: None,
    }
}

fn digest_key(digest: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut key = String::with_capacity(76);
    key.push_str("idempotency:");
    for byte in digest {
        key.push(HEX[(byte >> 4) as usize] as char);
        key.push(HEX[(byte & 0x0f) as usize] as char);
    }
    key
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum CommitFaultPoint {
    JournalPrepared,
    CommitPrepared,
    IndexPrepared,
    GenerationPrepared,
    AtomicWriteCompleted,
}

fn inject_fault(
    actual: Option<CommitFaultPoint>,
    expected: CommitFaultPoint,
) -> Result<(), StoreError> {
    if actual == Some(expected) {
        return Err(StoreError::Query(format!(
            "injected graph truth persistence fault at {expected:?}"
        )));
    }
    Ok(())
}

#[cfg(test)]
pub(super) fn append_graph_truth_commit_with_fault(
    store: &PhoenixOvergraphStore,
    engine: &mut DatabaseEngine,
    commit: &GraphTruthCommit,
    fault: CommitFaultPoint,
) -> Result<GraphTruthCommitAppend, StoreError> {
    append_graph_truth_commit_inner(store, engine, commit, Some(fault))
}

use std::sync::atomic::Ordering;
use std::time::Instant;

use overgraph::DatabaseEngine;
use phoenix_kernel::{
    DeterministicKernel, KernelCheckpointData, KernelGraphLayer, KernelGraphSnapshot,
    KernelJournalEntry, KernelMutationBatch, KernelMutationScope,
};
use phoenix_store_native_core::StoreError;
use serde::Serialize;

use super::{
    decode_record_prop, graph_truth_persistence, optional_u64_prop, store_query_error,
    PhoenixOvergraphStore, KERNEL_CHECKPOINT_KEY, PROP_GENERATION, PROP_RECORD,
    TYPE_KERNEL_CHECKPOINT, TYPE_KERNEL_JOURNAL,
};

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct KernelSnapshotReplayTimings {
    pub total_us: u64,
    pub current_generation_us: u64,
    pub cache_lookup_us: u64,
    pub checkpoint_node_read_us: u64,
    pub checkpoint_decode_us: u64,
    pub journal_len_lookup_us: u64,
    pub journal_node_scan_us: u64,
    pub journal_decode_sort_us: u64,
    pub commit_load_us: u64,
    pub checkpoint_rebuild_us: u64,
    pub journal_rebuild_us: u64,
    pub journal_apply_us: u64,
    pub snapshot_materialize_us: u64,
    pub cache_store_us: u64,
}

impl KernelSnapshotReplayTimings {
    pub fn measured_replay_cost_us(&self) -> u64 {
        self.checkpoint_node_read_us
            .saturating_add(self.checkpoint_decode_us)
            .saturating_add(self.journal_node_scan_us)
            .saturating_add(self.journal_decode_sort_us)
            .saturating_add(self.commit_load_us)
            .saturating_add(self.checkpoint_rebuild_us)
            .saturating_add(self.journal_rebuild_us)
            .saturating_add(self.journal_apply_us)
            .saturating_add(self.snapshot_materialize_us)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct KernelSnapshotReplayAudit {
    pub generation: u64,
    pub cached_hit: bool,
    pub checkpoint_present: bool,
    pub checkpoint_fast_path: bool,
    pub checkpoint_generation: Option<u64>,
    pub journal_len: usize,
    pub journal_entry_count: usize,
    pub hydrated_commit_count: usize,
    pub journal_batch_count: usize,
    pub vertices: usize,
    pub asserted_edges: usize,
    pub candidate_edges: usize,
    pub timings: KernelSnapshotReplayTimings,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct KernelSnapshotReplayAuditResult {
    pub snapshot: KernelGraphSnapshot,
    pub audit: KernelSnapshotReplayAudit,
}

impl PhoenixOvergraphStore {
    pub fn audit_live_kernel_snapshot_replay(
        &self,
    ) -> Result<KernelSnapshotReplayAuditResult, StoreError> {
        self.with_engine(|engine| self.audit_live_kernel_snapshot_replay_with_engine(engine))
    }

    pub(crate) fn audit_live_kernel_snapshot_replay_with_engine(
        &self,
        engine: &mut DatabaseEngine,
    ) -> Result<KernelSnapshotReplayAuditResult, StoreError> {
        let total_started = Instant::now();
        let mut audit = KernelSnapshotReplayAudit::default();

        let started = Instant::now();
        let generation = self.kernel_current_generation_with_engine(engine)?;
        audit.timings.current_generation_us = elapsed_us(started);
        audit.generation = generation;

        let started = Instant::now();
        let cached_generation = self.live_kernel_generation.load(Ordering::Acquire);
        if cached_generation == generation {
            if let Ok(guard) = self.live_kernel_snapshot.lock() {
                if let Some(snapshot) = guard.as_ref() {
                    audit.cached_hit = true;
                    audit.vertices = snapshot.vertices.len();
                    audit.asserted_edges = snapshot.asserted_edges.len();
                    audit.candidate_edges = snapshot.candidate_edges.len();
                    audit.timings.cache_lookup_us = elapsed_us(started);
                    audit.timings.total_us = elapsed_us(total_started);
                    return Ok(KernelSnapshotReplayAuditResult {
                        snapshot: snapshot.clone(),
                        audit,
                    });
                }
            }
        }
        audit.timings.cache_lookup_us = elapsed_us(started);

        let checkpoint = load_checkpoint_for_audit(engine, &mut audit)?;
        let kernel = DeterministicKernel::default();
        let snapshot = if let Some(checkpoint) = checkpoint {
            audit.checkpoint_present = true;
            audit.checkpoint_generation = Some(checkpoint.meta.generation);
            let started = Instant::now();
            audit.journal_len = self.kernel_journal_len_with_engine(engine)?;
            audit.timings.journal_len_lookup_us = elapsed_us(started);
            if checkpoint.meta.generation == generation && audit.journal_len == 0 {
                audit.checkpoint_fast_path = true;
                checkpoint.snapshot
            } else {
                let started = Instant::now();
                kernel
                    .rebuild_from_kernel_batches(
                        vec![
                            KernelMutationBatch {
                                layer: KernelGraphLayer::Asserted,
                                scope: KernelMutationScope::Full,
                                recorded_at: None,
                                vertices: checkpoint.snapshot.vertices.clone(),
                                edges: checkpoint.snapshot.asserted_edges.clone(),
                            },
                            KernelMutationBatch {
                                layer: KernelGraphLayer::Candidate,
                                scope: KernelMutationScope::Full,
                                recorded_at: None,
                                vertices: Vec::new(),
                                edges: checkpoint.snapshot.candidate_edges.clone(),
                            },
                        ],
                        None,
                    )
                    .map_err(|error| StoreError::Query(error.to_string()))?;
                audit.timings.checkpoint_rebuild_us = elapsed_us(started);
                let entries =
                    load_journal_after_for_audit(engine, checkpoint.meta.generation, &mut audit)?;
                apply_entries_for_audit(&kernel, entries, &mut audit)?;
                materialize_snapshot_for_audit(&kernel, &mut audit)
            }
        } else {
            let entries = load_journal_after_for_audit(engine, 0, &mut audit)?;
            let started = Instant::now();
            let batches = entries
                .into_iter()
                .filter_map(|entry| entry.batch)
                .collect::<Vec<_>>();
            kernel
                .rebuild_from_kernel_batches(batches, None)
                .map_err(|error| StoreError::Query(error.to_string()))?;
            audit.timings.journal_rebuild_us = elapsed_us(started);
            materialize_snapshot_for_audit(&kernel, &mut audit)
        };

        audit.vertices = snapshot.vertices.len();
        audit.asserted_edges = snapshot.asserted_edges.len();
        audit.candidate_edges = snapshot.candidate_edges.len();
        let started = Instant::now();
        self.cache_live_kernel_snapshot(generation, snapshot.clone());
        audit.timings.cache_store_us = elapsed_us(started);
        audit.timings.total_us = elapsed_us(total_started);
        self.record_kernel_replay_cost_with_engine(
            engine,
            audit.timings.measured_replay_cost_us(),
        )?;
        Ok(KernelSnapshotReplayAuditResult { snapshot, audit })
    }
}

fn load_checkpoint_for_audit(
    engine: &mut DatabaseEngine,
    audit: &mut KernelSnapshotReplayAudit,
) -> Result<Option<KernelCheckpointData>, StoreError> {
    let started = Instant::now();
    let node = engine
        .get_node_by_key(TYPE_KERNEL_CHECKPOINT, KERNEL_CHECKPOINT_KEY)
        .map_err(store_query_error)?;
    audit.timings.checkpoint_node_read_us = elapsed_us(started);
    let Some(node) = node else {
        return Ok(None);
    };
    let started = Instant::now();
    let checkpoint = decode_record_prop(&node, PROP_RECORD)?;
    audit.timings.checkpoint_decode_us = elapsed_us(started);
    Ok(checkpoint)
}

fn load_journal_after_for_audit(
    engine: &mut DatabaseEngine,
    generation: u64,
    audit: &mut KernelSnapshotReplayAudit,
) -> Result<Vec<KernelJournalEntry>, StoreError> {
    let started = Instant::now();
    let nodes = engine
        .get_nodes_by_type(TYPE_KERNEL_JOURNAL)
        .map_err(store_query_error)?;
    audit.timings.journal_node_scan_us = elapsed_us(started);

    let started = Instant::now();
    let mut entries = nodes
        .into_iter()
        .filter(|node| optional_u64_prop(node, PROP_GENERATION).unwrap_or_default() > generation)
        .filter_map(|node| decode_record_prop::<KernelJournalEntry>(&node, PROP_RECORD).transpose())
        .collect::<Result<Vec<_>, _>>()?;
    entries.sort_by(|left, right| {
        left.generation
            .cmp(&right.generation)
            .then_with(|| left.created_at.cmp(&right.created_at))
    });
    audit.timings.journal_decode_sort_us = elapsed_us(started);

    for entry in &mut entries {
        if entry.batch.is_some() {
            audit.journal_batch_count += 1;
            continue;
        }
        let Some(commit_id) = entry.commit_id.as_deref() else {
            continue;
        };
        let started = Instant::now();
        if let Some(commit) =
            graph_truth_persistence::load_graph_truth_commit_with_engine(engine, commit_id)?
        {
            entry.batch = Some(commit.batch);
            audit.hydrated_commit_count += 1;
        }
        audit.timings.commit_load_us += elapsed_us(started);
    }
    audit.journal_entry_count = entries.len();
    Ok(entries)
}

fn apply_entries_for_audit(
    kernel: &DeterministicKernel,
    entries: Vec<KernelJournalEntry>,
    audit: &mut KernelSnapshotReplayAudit,
) -> Result<(), StoreError> {
    let started = Instant::now();
    for entry in entries {
        if let Some(batch) = entry.batch {
            kernel
                .apply_batch(batch)
                .map_err(|error| StoreError::Query(error.to_string()))?;
        }
    }
    audit.timings.journal_apply_us = elapsed_us(started);
    Ok(())
}

fn materialize_snapshot_for_audit(
    kernel: &DeterministicKernel,
    audit: &mut KernelSnapshotReplayAudit,
) -> KernelGraphSnapshot {
    let started = Instant::now();
    let snapshot = kernel.snapshot().as_ref().clone();
    audit.timings.snapshot_materialize_us = elapsed_us(started);
    snapshot
}

fn elapsed_us(started: Instant) -> u64 {
    started.elapsed().as_micros() as u64
}

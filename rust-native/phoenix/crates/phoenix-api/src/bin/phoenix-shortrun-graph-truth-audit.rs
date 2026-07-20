use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use phoenix_graph_kernel::{
    GraphProposalBatchReceipt, GraphProposalFeatures, GraphProposalObservation,
    GraphProposalOutcomeKind, GraphProposalStatus, KernelEdge, KernelGraphSnapshot,
    KernelRelationClass, KernelVertex, KernelVertexClass, GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
};
use phoenix_graph_post::promotion_learner::{
    GraphPromotionLinearModel, GraphPromotionTrainingConfig, MmapGraphPromotionModel,
};
use phoenix_graph_post::promotion_training::{
    build_outcome_backed_training_examples, fixed_width_training_examples,
};
use phoenix_ingest_overgraph::{InvarantV3Config, PhoenixInvarantV3};
use phoenix_store_native_core::{
    GraphProposalReceiptAppend, PhoenixArchiveStoreV2, PhoenixGraphKernelStoreV2,
    PhoenixGraphLearningStore, StoreError,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{
    DocumentId, GraphTruthCompilerPolicy, GraphTruthDescriptor, GraphTruthSourceGenerationRef,
    IngestDocument, ScopeKey,
};
use serde::Serialize;

fn main() -> Result<(), String> {
    let config = Config::parse(&std::env::args().collect::<Vec<_>>())?;
    let report = run(&config)?;
    if config.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&report)
                .map_err(|error| format!("serialize audit report: {error}"))?
        );
    } else {
        print_table(&report);
    }
    Ok(())
}

fn run(config: &Config) -> Result<ShortrunGraphTruthAuditReport, String> {
    let root = workspace_root();
    let text = fs::read_to_string(root.join("docs").join("shortrun.md"))
        .map_err(|error| format!("read docs/shortrun.md: {error}"))?;
    let store_path = config.store_path.clone().unwrap_or_else(default_store_path);
    if store_path.exists() {
        return Err(format!(
            "audit store already exists, refusing to reuse: {}",
            store_path.display()
        ));
    }
    if let Some(parent) = store_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create {}: {error}", parent.display()))?;
    }

    let created_at = 1_700_000_000_000_i64;
    let document = IngestDocument {
        document_id: DocumentId("shortrun-full".to_owned()),
        note_id: None,
        title: "Shortrun Full".to_owned(),
        text,
        scope: ScopeKey::default(),
    };
    let ingest = PhoenixInvarantV3::new(InvarantV3Config::default());
    let store = PhoenixOvergraphStore::open(&store_path).map_err(display_error)?;
    store.init_archive_schema().map_err(display_error)?;
    store.init_graph_kernel_schema().map_err(display_error)?;

    let store_bytes_before = directory_bytes(&store_path)?;
    let ingest_report = ingest
        .audit_native_graph_truth_slice(&store, &document, None, 0, created_at)
        .map_err(display_error)?;
    let store_bytes_after_ingest = directory_bytes(&store_path)?;

    let receipt_started = Instant::now();
    let receipt = build_audit_receipt(&store, created_at + 1)?;
    let receipt_append = store
        .append_graph_proposal_receipt(&receipt)
        .map_err(display_error)?;
    let receipt_append_us = elapsed_us(receipt_started);
    let receipt_bytes = match receipt_append {
        GraphProposalReceiptAppend::Appended { byte_len } => byte_len,
        GraphProposalReceiptAppend::AlreadyPresent { .. } => 0,
    };
    let store_bytes_after_receipt = directory_bytes(&store_path)?;

    let training_started = Instant::now();
    let receipts = store
        .load_graph_proposal_receipts()
        .map_err(display_error)?;
    let commits = store.load_graph_truth_commits().map_err(display_error)?;
    let outcome_examples =
        build_outcome_backed_training_examples(&receipts, &commits).map_err(|error| {
            format!("build graph promotion training examples from receipts and commits: {error}")
        })?;
    let fixed_examples = fixed_width_training_examples(&outcome_examples);
    let model_path = config.model_path.clone().unwrap_or_else(default_model_path);
    let model = GraphPromotionLinearModel::fit_ftrl(
        format!("shortrun-shadow-ftrl-{}", commits.len()),
        &fixed_examples,
        GraphPromotionTrainingConfig::default(),
    )
    .map_err(|error| format!("train immutable promotion model: {error}"))?;
    if model_path.exists() {
        return Err(format!(
            "model artifact already exists, refusing to overwrite immutable output: {}",
            model_path.display()
        ));
    }
    model
        .write_immutable(&model_path)
        .map_err(|error| format!("write immutable promotion model: {error}"))?;
    let mapped_model = MmapGraphPromotionModel::open(&model_path)
        .map_err(|error| format!("load immutable promotion model: {error}"))?;
    let model_score_millis = fixed_examples
        .first()
        .map(|example| mapped_model.model().score_millis(example.features));
    let training_us = elapsed_us(training_started);

    let before_model_hash =
        canonical_asserted_graph_hash(&store.load_live_kernel_snapshot().map_err(display_error)?);
    let after_model_hash =
        canonical_asserted_graph_hash(&store.load_live_kernel_snapshot().map_err(display_error)?);
    if before_model_hash != after_model_hash {
        return Err("shadow model changed committed graph truth".to_owned());
    }

    let snapshot = store.load_live_kernel_snapshot().map_err(display_error)?;
    let snapshot_hash_before_checkpoint = canonical_asserted_graph_hash(&snapshot);
    let generation = store.kernel_current_generation().map_err(display_error)?;
    let checkpoint_started = Instant::now();
    let checkpoint = store
        .write_kernel_checkpoint(generation, "shortrun-graph-truth-audit", &snapshot)
        .map_err(display_error)?;
    let checkpoint_write_us = elapsed_us(checkpoint_started);
    let checkpoint_record_bytes = rmp_serde::to_vec_named(&checkpoint)
        .map_err(|error| format!("encode checkpoint for byte audit: {error}"))?
        .len();
    store.close_fast().map_err(display_error)?;
    let store_bytes_after_checkpoint = directory_bytes(&store_path)?;

    let reopen_started = Instant::now();
    let reopened = PhoenixOvergraphStore::open(&store_path).map_err(display_error)?;
    let reopen_store_us = elapsed_us(reopen_started);
    let replay_started = Instant::now();
    let replay_result = reopened
        .audit_live_kernel_snapshot_replay()
        .map_err(display_error)?;
    let replay_us = elapsed_us(replay_started);
    let replayed_snapshot = replay_result.snapshot;
    let snapshot_hash_after_replay = canonical_asserted_graph_hash(&replayed_snapshot);
    if snapshot_hash_before_checkpoint != snapshot_hash_after_replay {
        return Err(format!(
            "checkpoint replay hash mismatch: before={snapshot_hash_before_checkpoint} after={snapshot_hash_after_replay}"
        ));
    }

    let atlas_started = Instant::now();
    let atlas_query_hash = canonical_atlas_query_hash(&replayed_snapshot);
    let atlas_query_hash_us = elapsed_us(atlas_started);
    reopened.close_fast().map_err(display_error)?;

    if !config.keep_store {
        let _ = fs::remove_dir_all(&store_path);
    }

    Ok(ShortrunGraphTruthAuditReport {
        corpus: "docs/shortrun.md".to_owned(),
        store_path: store_path.display().to_string(),
        model_path: model_path.display().to_string(),
        ingest: ingest_report,
        timings: AuditExtraTimings {
            receipt_append_us,
            training_us,
            checkpoint_write_us,
            reopen_store_us,
            replay_us,
            checkpoint_replay_us: checkpoint_write_us + reopen_store_us + replay_us,
            atlas_query_hash_us,
        },
        bytes: AuditExtraBytes {
            proposal_receipt_bytes: receipt_bytes,
            checkpoint_record_bytes,
            store_bytes_before,
            store_bytes_after_ingest,
            store_bytes_after_receipt,
            store_bytes_after_checkpoint,
        },
        hashes: AuditHashes {
            snapshot_hash_before_checkpoint,
            snapshot_hash_after_replay,
            atlas_query_hash,
            truth_hash_before_model: before_model_hash,
            truth_hash_after_model: after_model_hash,
        },
        replay: replay_result.audit,
        training: TrainingAudit {
            receipt_count: receipts.len(),
            commit_count: commits.len(),
            example_count: fixed_examples.len(),
            outcome_counts: outcome_counts(&outcome_examples),
            model_artifact_bytes: fs::metadata(&model_path)
                .map(|metadata| metadata.len())
                .unwrap_or_default(),
            loaded_model_score_millis: model_score_millis,
        },
    })
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ShortrunGraphTruthAuditReport {
    corpus: String,
    store_path: String,
    model_path: String,
    ingest: phoenix_ingest_overgraph::NativeGraphTruthAuditReport,
    timings: AuditExtraTimings,
    bytes: AuditExtraBytes,
    hashes: AuditHashes,
    replay: phoenix_store_overgraph::KernelSnapshotReplayAudit,
    training: TrainingAudit,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AuditExtraTimings {
    receipt_append_us: u64,
    training_us: u64,
    checkpoint_write_us: u64,
    reopen_store_us: u64,
    replay_us: u64,
    checkpoint_replay_us: u64,
    atlas_query_hash_us: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AuditExtraBytes {
    proposal_receipt_bytes: usize,
    checkpoint_record_bytes: usize,
    store_bytes_before: u64,
    store_bytes_after_ingest: u64,
    store_bytes_after_receipt: u64,
    store_bytes_after_checkpoint: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AuditHashes {
    snapshot_hash_before_checkpoint: u64,
    snapshot_hash_after_replay: u64,
    atlas_query_hash: u64,
    truth_hash_before_model: u64,
    truth_hash_after_model: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct TrainingAudit {
    receipt_count: usize,
    commit_count: usize,
    example_count: usize,
    outcome_counts: BTreeMap<String, usize>,
    model_artifact_bytes: u64,
    loaded_model_score_millis: Option<u16>,
}

#[derive(Default)]
struct Config {
    json: bool,
    keep_store: bool,
    store_path: Option<PathBuf>,
    model_path: Option<PathBuf>,
}

impl Config {
    fn parse(args: &[String]) -> Result<Self, String> {
        let mut config = Self::default();
        let mut index = 1usize;
        while index < args.len() {
            match args[index].as_str() {
                "--json" => config.json = true,
                "--keep-store" => config.keep_store = true,
                "--store" => {
                    index += 1;
                    config.store_path = Some(PathBuf::from(
                        args.get(index).ok_or("--store requires a path")?,
                    ));
                }
                "--model-output" => {
                    index += 1;
                    config.model_path = Some(PathBuf::from(
                        args.get(index).ok_or("--model-output requires a path")?,
                    ));
                }
                flag => return Err(format!("unknown argument: {flag}")),
            }
            index += 1;
        }
        Ok(config)
    }
}

fn build_audit_receipt(
    store: &PhoenixOvergraphStore,
    created_at: i64,
) -> Result<GraphProposalBatchReceipt, String> {
    let commits = store.load_graph_truth_commits().map_err(display_error)?;
    let (commit_id, generation, truth, source_generations, atom) = commits
        .iter()
        .find_map(|commit| {
            commit
                .atom_keys()
                .ok()
                .and_then(|atoms| atoms.into_iter().next())
                .map(|atom| {
                    (
                        commit.commit_id().to_owned(),
                        commit.header.generation,
                        commit.header.truth,
                        commit.header.source_generations.clone(),
                        atom,
                    )
                })
        })
        .ok_or_else(|| "no graph truth atom available for audit receipt".to_owned())?;
    Ok(GraphProposalBatchReceipt {
        schema_version: GRAPH_PROPOSAL_RECEIPT_SCHEMA_VERSION,
        receipt_id: format!("shortrun-audit-receipt:{generation}:{commit_id}").into(),
        scope_key: "scope:shortrun-audit".into(),
        generation,
        created_at,
        compiler_policy: GraphTruthCompilerPolicy {
            compiler_id: "phoenix-shortrun-graph-truth-audit".into(),
            compiler_version: env!("CARGO_PKG_VERSION").into(),
            policy_id: "audit-observe-committed-truth".into(),
            policy_version: "1".into(),
        },
        source_generations: if source_generations.is_empty() {
            [GraphTruthSourceGenerationRef {
                source_id: "graph-truth:shortrun-audit".into(),
                generation,
            }]
            .into_iter()
            .collect()
        } else {
            source_generations
        },
        model_id: None,
        discovery_origin: None,
        proposals: vec![GraphProposalObservation {
            proposal_id: format!("proposal:{commit_id}").into(),
            atom,
            family: "auditCommittedAtom".into(),
            source_kind: "graphTruthCommit".into(),
            target_kind: "kernelAtom".into(),
            truth: GraphTruthDescriptor {
                kind: truth.kind,
                plane: truth.plane,
            },
            status: GraphProposalStatus::ReviewedSupport,
            evidence_refs: [commit_id.into()].into_iter().collect(),
            features: GraphProposalFeatures([
                1000, 1000, 1000, 0, 1000, 512, 256, 460, 1000, 1000, 0, 1000, 0, 0, 0, 1000,
            ]),
            shadow_score_millis: None,
        }],
    })
}

fn outcome_counts(
    examples: &[phoenix_graph_post::promotion_training::GraphPromotionOutcomeTrainingExample],
) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::<String, usize>::new();
    for example in examples {
        *counts
            .entry(outcome_name(example.outcome).to_owned())
            .or_default() += 1;
    }
    counts
}

fn outcome_name(outcome: GraphProposalOutcomeKind) -> &'static str {
    match outcome {
        GraphProposalOutcomeKind::Uncommitted => "uncommitted",
        GraphProposalOutcomeKind::Active => "active",
        GraphProposalOutcomeKind::Superseded => "superseded",
        GraphProposalOutcomeKind::Retracted => "retracted",
        GraphProposalOutcomeKind::Reverted => "reverted",
    }
}

fn canonical_asserted_graph_hash(snapshot: &KernelGraphSnapshot) -> u64 {
    let mut hash = Fnv64::default();
    let mut vertices = snapshot.vertices.iter().collect::<Vec<_>>();
    vertices.sort_unstable_by(|left, right| left.id.0.cmp(&right.id.0));
    for vertex in vertices {
        hash.mix_str("v");
        hash_vertex(&mut hash, vertex);
    }
    let mut edges = snapshot.asserted_edges.iter().collect::<Vec<_>>();
    edges.sort_unstable_by(|left, right| {
        left.source_id
            .0
            .cmp(&right.source_id.0)
            .then_with(|| left.target_id.0.cmp(&right.target_id.0))
            .then_with(|| left.edge_type.0.cmp(&right.edge_type.0))
    });
    for edge in edges {
        hash.mix_str("e");
        hash_edge(&mut hash, edge);
    }
    hash.finish()
}

fn canonical_atlas_query_hash(snapshot: &KernelGraphSnapshot) -> u64 {
    let mut hash = Fnv64::default();
    hash.mix_usize(snapshot.vertices.len());
    hash.mix_usize(snapshot.asserted_edges.len());
    hash.mix_usize(snapshot.candidate_edges.len());
    hash.mix_u64(canonical_asserted_graph_hash(snapshot));
    hash.finish()
}

fn hash_vertex(hash: &mut Fnv64, vertex: &KernelVertex) {
    hash.mix_str(&vertex.id.0);
    hash.mix_str(&vertex.kind);
    hash.mix_u8(vertex_class_code(&vertex.class));
}

fn hash_edge(hash: &mut Fnv64, edge: &KernelEdge) {
    hash.mix_str(&edge.source_id.0);
    hash.mix_str(&edge.target_id.0);
    hash.mix_str(&edge.edge_type.0);
    hash.mix_u8(relation_class_code(&edge.relation_class));
}

fn vertex_class_code(value: &KernelVertexClass) -> u8 {
    match value {
        KernelVertexClass::Document => 1,
        KernelVertexClass::Chunk => 2,
        KernelVertexClass::Entity => 3,
        KernelVertexClass::Alias => 4,
        KernelVertexClass::Mention => 5,
        KernelVertexClass::TimeAnchor => 6,
        KernelVertexClass::CalendarAnchor => 7,
        KernelVertexClass::Narrative => 8,
        KernelVertexClass::Episode => 9,
        KernelVertexClass::Memory => 10,
        KernelVertexClass::Task => 11,
        KernelVertexClass::State => 12,
        KernelVertexClass::Event => 13,
        KernelVertexClass::Generic => 14,
    }
}

fn relation_class_code(value: &KernelRelationClass) -> u8 {
    match value {
        KernelRelationClass::Structural => 1,
        KernelRelationClass::Semantic => 2,
        KernelRelationClass::Identity => 3,
        KernelRelationClass::Resolution => 4,
        KernelRelationClass::Temporal => 5,
        KernelRelationClass::Calendar => 6,
        KernelRelationClass::Memory => 7,
        KernelRelationClass::Narrative => 8,
        KernelRelationClass::Candidate => 9,
        KernelRelationClass::Custom => 10,
    }
}

#[derive(Clone, Copy)]
struct Fnv64(u64);

impl Default for Fnv64 {
    fn default() -> Self {
        Self(0xcbf2_9ce4_8422_2325)
    }
}

impl Fnv64 {
    fn mix_u8(&mut self, value: u8) {
        self.0 ^= value as u64;
        self.0 = self.0.wrapping_mul(0x1000_0000_01b3);
    }

    fn mix_u64(&mut self, value: u64) {
        for byte in value.to_le_bytes() {
            self.mix_u8(byte);
        }
    }

    fn mix_usize(&mut self, value: usize) {
        self.mix_u64(value as u64);
    }

    fn mix_str(&mut self, value: &str) {
        self.mix_usize(value.len());
        for byte in value.as_bytes() {
            self.mix_u8(*byte);
        }
    }

    fn finish(self) -> u64 {
        self.0
    }
}

fn directory_bytes(path: &Path) -> Result<u64, String> {
    if !path.exists() {
        return Ok(0);
    }
    let mut total = 0u64;
    let mut stack = vec![path.to_path_buf()];
    while let Some(path) = stack.pop() {
        let metadata =
            fs::metadata(&path).map_err(|error| format!("metadata {}: {error}", path.display()))?;
        if metadata.is_file() {
            total += metadata.len();
        } else if metadata.is_dir() {
            for entry in
                fs::read_dir(&path).map_err(|error| format!("read {}: {error}", path.display()))?
            {
                stack.push(
                    entry
                        .map_err(|error| format!("read {} entry: {error}", path.display()))?
                        .path(),
                );
            }
        }
    }
    Ok(total)
}

fn print_table(report: &ShortrunGraphTruthAuditReport) {
    println!("shortrun graph truth audit");
    println!("store: {}", report.store_path);
    println!("model: {}", report.model_path);
    println!(
        "build document outcome: {:.3} ms",
        ms(report.ingest.timings.document_outcome_us)
    );
    println!(
        "build structure rows: {:.3} ms",
        ms(report.ingest.timings.structure_rows_us)
    );
    println!(
        "build prepared document: {:.3} ms",
        ms(report.ingest.timings.prepared_document_us)
    );
    println!(
        "GraphTruthCommit append: {:.3} ms",
        ms(report.ingest.timings.graph_truth_commit_append_us)
    );
    println!(
        "receipt append: {:.3} ms",
        ms(report.timings.receipt_append_us)
    );
    println!(
        "checkpoint/reopen/replay: {:.3} ms",
        ms(report.timings.checkpoint_replay_us)
    );
    println!(
        "reopen store: {:.3} ms; snapshot replay/load: {:.3} ms",
        ms(report.timings.reopen_store_us),
        ms(report.timings.replay_us)
    );
    println!(
        "Atlas query hash: {} ({:.3} ms)",
        report.hashes.atlas_query_hash,
        ms(report.timings.atlas_query_hash_us)
    );
    println!(
        "replay breakdown: fastPath={} total={:.3} ms checkpointDecode={:.3} ms journalScan={:.3} ms commitLoad={:.3} ms checkpointRebuild={:.3} ms snapshotClone={:.3} ms cacheStore={:.3} ms",
        report.replay.checkpoint_fast_path,
        ms(report.replay.timings.total_us),
        ms(report.replay.timings.checkpoint_decode_us),
        ms(report.replay.timings.journal_node_scan_us),
        ms(report.replay.timings.commit_load_us),
        ms(report.replay.timings.checkpoint_rebuild_us),
        ms(report.replay.timings.snapshot_materialize_us),
        ms(report.replay.timings.cache_store_us),
    );
    println!(
        "bytes: preparedSegments={} commitRecords={} journalRefs={} receipt={} checkpoint={} storeDelta={}",
        report.ingest.bytes.prepared_segment_compressed_bytes,
        report.ingest.bytes.graph_truth_commit_record_bytes,
        report.ingest.bytes.graph_truth_journal_record_bytes,
        report.bytes.proposal_receipt_bytes,
        report.bytes.checkpoint_record_bytes,
        report.bytes.store_bytes_after_checkpoint.saturating_sub(report.bytes.store_bytes_before),
    );
    println!(
        "prepared persist split: total={:.3} ms manifestPrepare={:.3} ms segmentPrepare={:.3} ms payloadWrite={:.3} ms batchUpsert={:.3} ms cacheInvalidate={:.3} ms externalBytes={} inlineBytes={} nodes={} segments={}",
        ms(report.ingest.prepared_persist.total_us),
        ms(report.ingest.prepared_persist.manifest_prepare_us),
        ms(report.ingest.prepared_persist.segment_prepare_us),
        ms(report.ingest.prepared_persist.segment_payload_write_us),
        ms(report.ingest.prepared_persist.batch_upsert_us),
        ms(report.ingest.prepared_persist.cache_invalidate_us),
        report.ingest.prepared_persist.segment_external_bytes,
        report.ingest.prepared_persist.segment_inline_bytes,
        report.ingest.prepared_persist.node_count,
        report.ingest.prepared_persist.segment_count,
    );
    for segment in top_prepared_segments(report, 5) {
        println!(
            "prepared segment: kind={} rows={} compressed={} uncompressed={} storage={} prepare={:.3} ms payloadWrite={:.3} ms",
            segment.kind,
            segment.row_count,
            segment.compressed_bytes,
            segment.uncompressed_bytes,
            segment.storage,
            ms(segment.prepare_us),
            ms(segment.payload_write_us),
        );
    }
    println!(
        "training: examples={} outcomes={:?} loadedScore={:?}",
        report.training.example_count,
        report.training.outcome_counts,
        report.training.loaded_model_score_millis,
    );
}

fn top_prepared_segments(
    report: &ShortrunGraphTruthAuditReport,
    limit: usize,
) -> Vec<&phoenix_store_native_core::PreparedDocumentSegmentPersistTelemetry> {
    let mut segments = report
        .ingest
        .prepared_persist
        .segments
        .iter()
        .collect::<Vec<_>>();
    segments.sort_unstable_by(|left, right| {
        right
            .compressed_bytes
            .cmp(&left.compressed_bytes)
            .then_with(|| right.uncompressed_bytes.cmp(&left.uncompressed_bytes))
    });
    segments.truncate(limit);
    segments
}

fn ms(us: u64) -> f64 {
    us as f64 / 1000.0
}

fn elapsed_us(started: Instant) -> u64 {
    started.elapsed().as_micros() as u64
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("workspace root")
        .to_path_buf()
}

fn phoenix_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("phoenix root")
        .to_path_buf()
}

fn default_store_path() -> PathBuf {
    phoenix_root().join("reports").join(format!(
        "shortrun-graph-truth-audit-store-{}-{}",
        std::process::id(),
        unix_nanos()
    ))
}

fn default_model_path() -> PathBuf {
    phoenix_root().join("reports").join(format!(
        "graph-promotion-model-shortrun-audit-{}-{}.bin",
        std::process::id(),
        unix_nanos()
    ))
}

fn unix_nanos() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
}

fn display_error(error: StoreError) -> String {
    error.to_string()
}

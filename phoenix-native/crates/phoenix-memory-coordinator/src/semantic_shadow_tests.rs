use crate::semantic_shadow::SemanticShadowController;
use crate::tests::{committed_turn, conversation, test_config, FixtureProducer};
use crate::*;
use phoenix_memory_embeddings::{
    write_embedding_pages_new, EmbeddingPageWriteAuthority, EmbeddingRowV1, ROW_FLAG_NORMALIZED,
};
use phoenix_turboquant::{write_quantized_artifact_new, ArtifactAuthority};
use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};
use tempfile::TempDir;

#[derive(Debug)]
struct BasisEmbedder;

impl SemanticQueryEmbedder for BasisEmbedder {
    fn embed_query(
        &self,
        query: &str,
        expected_dimension: usize,
        output: &mut Vec<f32>,
    ) -> Result<(), SemanticEmbeddingError> {
        if expected_dimension != 8 || query.is_empty() {
            return Err(SemanticEmbeddingError::Rejected);
        }
        output.extend_from_slice(&[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]);
        Ok(())
    }
}

#[derive(Debug)]
struct BlockingEmbedder {
    entered: Arc<(Mutex<bool>, Condvar)>,
    release: Arc<(Mutex<bool>, Condvar)>,
}

impl SemanticQueryEmbedder for BlockingEmbedder {
    fn embed_query(
        &self,
        _query: &str,
        _expected_dimension: usize,
        output: &mut Vec<f32>,
    ) -> Result<(), SemanticEmbeddingError> {
        let (entered_lock, entered_signal) = &*self.entered;
        *entered_lock.lock().expect("entered lock") = true;
        entered_signal.notify_all();
        let (release_lock, release_signal) = &*self.release;
        let mut released = release_lock.lock().expect("release lock");
        while !*released {
            released = release_signal.wait(released).expect("release wait");
        }
        output.extend_from_slice(&[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]);
        Ok(())
    }
}

#[test]
fn generation_bound_pair_runs_async_and_never_changes_authoritative_items() {
    let temp = TempDir::new().expect("temporary shadow directory");
    let mut config = test_config(temp.path());
    config.semantic_shadow = exact_config(2);
    config.semantic_query_embedder = Some(Arc::new(BasisEmbedder));
    let coordinator =
        DualFaceIngestionCoordinator::new(config, Arc::new(FixtureProducer::default()))
            .expect("semantic coordinator");
    let conversation = conversation();
    let publication = coordinator
        .try_ingest_turn(IngestTurn {
            conversation: conversation.clone(),
            committed_turn: committed_turn(0, b"semantic/0", "Mira prefers tea.", None),
        })
        .expect("submit history")
        .wait()
        .expect("publish history");
    let request = RecallTurn {
        conversation: conversation.clone(),
        pending_turn: PendingTurn {
            external_id: Arc::from(&b"semantic/pending"[..]),
            ordinal: 1,
            role: phoenix_memory_contract::ParticipantRole::User,
            event_time_millis: 1_010,
            reply_to_ordinal: Some(0),
            content: Arc::from("What does Mira prefer?"),
            origin: IngestionOrigin::ExternalConversation,
        },
        scope: MemoryScope::Workspace,
    };
    let before = coordinator
        .try_recall(request.clone())
        .expect("submit pre-sidecar recall")
        .wait()
        .expect("pre-sidecar recall");
    assert_eq!(
        before.semantic_shadow.status,
        SemanticShadowStatus::Deferred
    );

    let (embedding, quantized) = sidecars(temp.path(), publication.generation_hash);
    coordinator
        .mark_semantic_sidecars_building(publication.generation_hash)
        .expect("mark sidecars building");
    coordinator
        .install_semantic_sidecars(&embedding, &quantized, publication.generation_hash)
        .expect("install sidecars");
    let after = coordinator
        .try_recall(request.clone())
        .expect("submit semantic recall")
        .wait()
        .expect("semantic recall");
    assert_eq!(before.items, after.items);
    assert_eq!(before.proposed_candidates, after.proposed_candidates);
    assert!(after.semantic_shadow.authority_unchanged);
    assert_eq!(after.semantic_shadow.status, SemanticShadowStatus::Deferred);

    let snapshot = wait_completed(&coordinator, 1);
    assert_eq!(
        snapshot
            .latest_submission
            .as_ref()
            .map(|receipt| receipt.status),
        Some(SemanticShadowStatus::Queued)
    );
    let receipt = snapshot.latest.expect("completed semantic receipt");
    assert_eq!(receipt.status, SemanticShadowEvaluationStatus::Ready);
    assert!(receipt.authority_unchanged);
    assert!(receipt.exact_reference_sampled);
    assert!(receipt.exact_top1_in_top64);
    assert_eq!(receipt.exact_top10_recall_at_64, 3);
    assert!(receipt.reranked_top1_equal);
    assert!(receipt.ordered_top10_equal);
    assert_ne!(receipt.query_hash, [0; 32]);
    assert_ne!(receipt.query_embedding_hash, [0; 32]);

    let next = coordinator
        .try_ingest_turn(IngestTurn {
            conversation,
            committed_turn: committed_turn(1, b"semantic/1", "Mira also likes jasmine.", Some(0)),
        })
        .expect("submit next generation")
        .wait()
        .expect("publish next generation");
    assert_ne!(next.generation_hash, publication.generation_hash);
    assert_eq!(
        coordinator.semantic_shadow_snapshot().sidecar_status,
        SemanticSidecarStatus::Stale
    );
    let stale = coordinator
        .try_recall(request)
        .expect("submit stale-sidecar recall")
        .wait()
        .expect("authority survives stale sidecar");
    assert_eq!(stale.semantic_shadow.status, SemanticShadowStatus::Deferred);
    assert!(stale.semantic_shadow.authority_unchanged);
    assert_eq!(
        wait_submission_status(&coordinator, SemanticShadowStatus::SidecarStale)
            .latest_submission
            .as_ref()
            .map(|receipt| receipt.sidecar_status),
        Some(SemanticSidecarStatus::Stale)
    );
    coordinator.shutdown().expect("clean shutdown");
}

#[test]
fn bounded_queue_drops_shadow_work_without_backpressuring_recall() {
    let temp = TempDir::new().expect("temporary queue directory");
    let generation = [0x41; 32];
    let (embedding, quantized) = sidecars(temp.path(), generation);
    let entered = Arc::new((Mutex::new(false), Condvar::new()));
    let release = Arc::new((Mutex::new(false), Condvar::new()));
    let embedder = Arc::new(BlockingEmbedder {
        entered: Arc::clone(&entered),
        release: Arc::clone(&release),
    });
    let mut controller = SemanticShadowController::start(exact_config(1), Some(embedder));
    let handle = controller.handle();
    handle.observe_generation(generation);
    controller.mark_building(generation).expect("mark building");
    let index = Arc::new(
        ResidentSemanticIndex::open(&embedding, &quantized, generation).expect("open sidecars"),
    );
    controller.install(index).expect("install sidecars");
    assert_eq!(
        handle.submit(Arc::from("first"), Some(generation)).status,
        SemanticShadowStatus::Queued
    );
    wait_entered(&entered);
    assert_eq!(
        handle.submit(Arc::from("second"), Some(generation)).status,
        SemanticShadowStatus::Queued
    );
    assert_eq!(
        handle.submit(Arc::from("third"), Some(generation)).status,
        SemanticShadowStatus::QueueFull
    );
    let snapshot = controller.snapshot();
    assert_eq!(snapshot.dropped, 1);
    assert_eq!(snapshot.queue_high_water, 1);
    let (release_lock, release_signal) = &*release;
    *release_lock.lock().expect("release lock") = true;
    release_signal.notify_all();
    controller.stop();
}

#[test]
fn mismatched_or_corrupt_sidecars_fail_closed_and_keyed_query_hashes_do_not_link() {
    let temp = TempDir::new().expect("temporary corruption directory");
    let generation = [0x51; 32];
    let (embedding, quantized) = sidecars(temp.path(), generation);
    assert!(matches!(
        ResidentSemanticIndex::open(&embedding, &quantized, [0x52; 32]),
        Err(SemanticShadowInstallError::Embedding(_))
    ));
    let mut file = OpenOptions::new()
        .write(true)
        .open(&quantized)
        .expect("open quantized artifact for corruption");
    file.seek(SeekFrom::Start(576)).expect("seek codes");
    file.write_all(&[0xff]).expect("corrupt codes");
    file.sync_all().expect("flush corruption");
    assert!(ResidentSemanticIndex::open(&embedding, &quantized, generation).is_err());

    let first = controller_with_key([0x61; 32]);
    let second = controller_with_key([0x62; 32]);
    let left = first
        .handle()
        .submit(Arc::from("common query text"), Some(generation));
    let right = second
        .handle()
        .submit(Arc::from("common query text"), Some(generation));
    assert_ne!(left.query_hash, right.query_hash);
    let debug = format!("{:?}", SemanticShadowConfig::enabled([0x61; 32]));
    assert!(debug.contains("[REDACTED]"));
    assert!(!debug.contains("97, 97, 97"));

    let mut building = controller_with_key([0x63; 32]);
    let building_generation = [0x64; 32];
    building.handle().observe_generation(building_generation);
    building
        .mark_building(building_generation)
        .expect("mark transient build");
    building.handle().observe_generation([0x65; 32]);
    assert_eq!(
        building.snapshot().sidecar_status,
        SemanticSidecarStatus::Absent
    );
    building.stop();
}

#[test]
#[ignore = "manual release performance gate"]
fn semantic_shadow_recall_latency_profile() {
    let disabled_temp = TempDir::new().expect("disabled profile directory");
    let disabled = profile_coordinator(disabled_temp.path(), None);
    let disabled_request = profile_history(&disabled);

    let enabled_temp = TempDir::new().expect("enabled profile directory");
    let enabled = profile_coordinator(enabled_temp.path(), Some(exact_config(64)));
    let enabled_request = profile_history(&enabled);
    let generation = enabled
        .try_verify_current()
        .expect("submit generation check")
        .wait()
        .expect("verify generation")
        .expect("profile generation");
    let (embedding, quantized) = sidecars(enabled_temp.path(), generation);
    enabled
        .mark_semantic_sidecars_building(generation)
        .expect("mark profile sidecars building");
    enabled
        .install_semantic_sidecars(embedding, quantized, generation)
        .expect("install profile sidecars");
    warm_recalls(&disabled, &disabled_request, 128);
    warm_recalls(&enabled, &enabled_request, 128);
    let mut disabled_times = Vec::with_capacity(2_000);
    let mut enabled_times = Vec::with_capacity(2_000);
    for round in 0..20 {
        if round % 2 == 0 {
            measure_recalls(&disabled, &disabled_request, 100, &mut disabled_times);
            measure_recalls(&enabled, &enabled_request, 100, &mut enabled_times);
        } else {
            measure_recalls(&enabled, &enabled_request, 100, &mut enabled_times);
            measure_recalls(&disabled, &disabled_request, 100, &mut disabled_times);
        }
    }
    disabled_times.sort_unstable();
    enabled_times.sort_unstable();
    let metrics = wait_idle(&enabled);
    println!(
        "SEMANTIC_SHADOW_PROFILE disabled_p50_ns={} disabled_p95_ns={} disabled_p99_ns={} enabled_p50_ns={} enabled_p95_ns={} enabled_p99_ns={} submitted={} completed={} dropped={} queue_high_water={}",
        percentile(&disabled_times, 50),
        percentile(&disabled_times, 95),
        percentile(&disabled_times, 99),
        percentile(&enabled_times, 50),
        percentile(&enabled_times, 95),
        percentile(&enabled_times, 99),
        metrics.submitted,
        metrics.completed,
        metrics.dropped,
        metrics.queue_high_water,
    );
    disabled.shutdown().expect("disabled shutdown");
    enabled.shutdown().expect("enabled shutdown");
}

fn controller_with_key(key: [u8; 32]) -> SemanticShadowController {
    SemanticShadowController::start(
        SemanticShadowConfig::enabled(key),
        Some(Arc::new(BasisEmbedder)),
    )
}

fn profile_coordinator(
    root: &Path,
    semantic: Option<SemanticShadowConfig>,
) -> DualFaceIngestionCoordinator<FixtureProducer> {
    let mut config = test_config(root);
    if let Some(semantic) = semantic {
        config.semantic_shadow = semantic;
        config.semantic_query_embedder = Some(Arc::new(BasisEmbedder));
    }
    DualFaceIngestionCoordinator::new(config, Arc::new(FixtureProducer::default()))
        .expect("profile coordinator")
}

fn profile_history(coordinator: &DualFaceIngestionCoordinator<FixtureProducer>) -> RecallTurn {
    let conversation = conversation();
    coordinator
        .try_ingest_turn(IngestTurn {
            conversation: conversation.clone(),
            committed_turn: committed_turn(0, b"profile/0", "Mira prefers tea.", None),
        })
        .expect("submit profile history")
        .wait()
        .expect("publish profile history");
    RecallTurn {
        conversation,
        pending_turn: PendingTurn {
            external_id: Arc::from(&b"profile/pending"[..]),
            ordinal: 1,
            role: phoenix_memory_contract::ParticipantRole::User,
            event_time_millis: 1_010,
            reply_to_ordinal: Some(0),
            content: Arc::from("What does Mira prefer?"),
            origin: IngestionOrigin::ExternalConversation,
        },
        scope: MemoryScope::Workspace,
    }
}

fn warm_recalls(
    coordinator: &DualFaceIngestionCoordinator<FixtureProducer>,
    request: &RecallTurn,
    iterations: usize,
) {
    for _ in 0..iterations {
        coordinator
            .try_recall(request.clone())
            .expect("submit warm recall")
            .wait()
            .expect("warm recall");
    }
}

fn measure_recalls(
    coordinator: &DualFaceIngestionCoordinator<FixtureProducer>,
    request: &RecallTurn,
    iterations: usize,
    times: &mut Vec<u64>,
) {
    for _ in 0..iterations {
        let started = Instant::now();
        let packet = coordinator
            .try_recall(request.clone())
            .expect("submit measured recall")
            .wait()
            .expect("measured recall");
        assert_eq!(packet.items.len(), 1);
        times.push(started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64);
    }
}

fn percentile(sorted: &[u64], percentile: usize) -> u64 {
    sorted[(sorted.len() * percentile / 100).min(sorted.len() - 1)]
}

fn exact_config(queue_capacity: usize) -> SemanticShadowConfig {
    SemanticShadowConfig {
        queue_capacity,
        exact_reference_denominator: 1,
        privacy_key: [0x31; 32],
        enabled: true,
        ..SemanticShadowConfig::default()
    }
}

fn sidecars(root: &Path, generation_hash: [u8; 32]) -> (PathBuf, PathBuf) {
    let rows = [
        row(101, 7, 0, [0x11; 32]),
        row(202, 8, 1, [0x22; 32]),
        row(303, 9, 2, [0x33; 32]),
    ];
    let vectors = [
        1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        1.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    ];
    let embedding = root.join(format!("{}.phxe1", hex_prefix(generation_hash)));
    let quantized = root.join(format!("{}.phxq1", hex_prefix(generation_hash)));
    let pages = write_embedding_pages_new(
        &embedding,
        EmbeddingPageWriteAuthority {
            generation_hash,
            source_set_hash: [0x72; 32],
            model_identity_hash: [0x73; 32],
            model_asset_hash: [0x74; 32],
            config_hash: [0x75; 32],
            dimension: 8,
        },
        &rows,
        &vectors,
    )
    .expect("write embedding pages");
    write_quantized_artifact_new(
        &quantized,
        ArtifactAuthority::from_embedding_header(pages.header()),
        &[101, 202, 303],
        &vectors,
        8,
        2,
    )
    .expect("write quantized sidecar");
    (embedding, quantized)
}

fn row(subject_id: u64, source_id: u64, ordinal: u32, content_hash: [u8; 32]) -> EmbeddingRowV1 {
    EmbeddingRowV1 {
        subject_id,
        source_id,
        content_hash,
        vector_start: u64::from(ordinal) * 8,
        source_start: ordinal * 10,
        source_end: ordinal * 10 + 9,
        ordinal,
        dimension: 8,
        source_kind: 1,
        content_kind: 1,
        flags: ROW_FLAG_NORMALIZED,
        reserved: [0; 2],
    }
}

fn wait_completed<P: DualFaceProducer>(
    coordinator: &DualFaceIngestionCoordinator<P>,
    expected: u64,
) -> SemanticShadowRuntimeSnapshot {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let snapshot = coordinator.semantic_shadow_snapshot();
        if snapshot.completed >= expected {
            return snapshot;
        }
        assert!(Instant::now() < deadline, "semantic shadow timed out");
        std::thread::yield_now();
    }
}

fn wait_submission_status<P: DualFaceProducer>(
    coordinator: &DualFaceIngestionCoordinator<P>,
    expected: SemanticShadowStatus,
) -> SemanticShadowRuntimeSnapshot {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let snapshot = coordinator.semantic_shadow_snapshot();
        if snapshot
            .latest_submission
            .as_ref()
            .is_some_and(|receipt| receipt.status == expected)
        {
            return snapshot;
        }
        assert!(Instant::now() < deadline, "semantic submission timed out");
        std::thread::yield_now();
    }
}

fn wait_idle<P: DualFaceProducer>(
    coordinator: &DualFaceIngestionCoordinator<P>,
) -> SemanticShadowRuntimeSnapshot {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let snapshot = coordinator.semantic_shadow_snapshot();
        if snapshot.queue_depth == 0 && snapshot.completed >= snapshot.submitted {
            return snapshot;
        }
        assert!(Instant::now() < deadline, "semantic queue did not drain");
        std::thread::yield_now();
    }
}

fn wait_entered(entered: &(Mutex<bool>, Condvar)) {
    let (lock, signal) = entered;
    let entered = lock.lock().expect("entered lock");
    let (entered, timeout) = signal
        .wait_timeout_while(entered, Duration::from_secs(2), |value| !*value)
        .expect("entered wait");
    assert!(
        *entered && !timeout.timed_out(),
        "worker did not enter embedder"
    );
}

fn hex_prefix(hash: [u8; 32]) -> String {
    format!(
        "{:02x}{:02x}{:02x}{:02x}",
        hash[0], hash[1], hash[2], hash[3]
    )
}

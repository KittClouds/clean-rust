use phoenix_memory_embeddings::{
    EmbeddingPageError, EmbeddingPageExpectation, VerifiedEmbeddingPagesV1,
};
use phoenix_turboquant::{
    ArtifactAuthority, SearchExecution, SearchKernel, TurboQuantError, VerifiedQuantizedIndex,
};
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, SyncSender, TrySendError};
use std::sync::{Arc, RwLock};
use std::thread::{self, JoinHandle};
use thiserror::Error;

mod worker;

use worker::run_worker;

pub const PHXQ1_SEMANTIC_SHADOW_PATH: &str = "phoenix.semantic.phxq1/shadow-v1";

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum SemanticShadowPathId {
    #[default]
    Phxq1ShadowV1,
}

impl SemanticShadowPathId {
    pub const fn as_str(self) -> &'static str {
        PHXQ1_SEMANTIC_SHADOW_PATH
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum SemanticSidecarStatus {
    #[default]
    Absent,
    Building,
    Ready,
    Stale,
    Invalid,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum SemanticShadowStatus {
    #[default]
    Disabled,
    SidecarAbsent,
    SidecarBuilding,
    SidecarStale,
    SidecarInvalid,
    ModelUnavailable,
    HostUnqualified,
    SkippedBudget,
    QueueFull,
    Deferred,
    Queued,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum SemanticShadowEvaluationStatus {
    #[default]
    Ready,
    EmbeddingFailed,
    SearchFailed,
    GenerationChanged,
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub struct SemanticShadowConfig {
    pub enabled: bool,
    pub queue_capacity: usize,
    pub candidate_k: usize,
    pub rerank_k: usize,
    pub maximum_rows: usize,
    pub minimum_logical_cpus: usize,
    /// Evaluate one in every N eligible queries. One means every query.
    pub sample_denominator: u32,
    /// Run the corpus-wide exact reference for one in every N shadow jobs.
    pub exact_reference_denominator: u32,
    /// Process-local privacy key. It is never serialized into a receipt.
    pub privacy_key: [u8; 32],
}

impl std::fmt::Debug for SemanticShadowConfig {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SemanticShadowConfig")
            .field("enabled", &self.enabled)
            .field("queue_capacity", &self.queue_capacity)
            .field("candidate_k", &self.candidate_k)
            .field("rerank_k", &self.rerank_k)
            .field("maximum_rows", &self.maximum_rows)
            .field("minimum_logical_cpus", &self.minimum_logical_cpus)
            .field("sample_denominator", &self.sample_denominator)
            .field(
                "exact_reference_denominator",
                &self.exact_reference_denominator,
            )
            .field("privacy_key", &"[REDACTED]")
            .finish()
    }
}

impl Default for SemanticShadowConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            queue_capacity: 2,
            candidate_k: 64,
            rerank_k: 10,
            maximum_rows: 1_000_000,
            minimum_logical_cpus: 1,
            sample_denominator: 1,
            exact_reference_denominator: 16,
            privacy_key: [0; 32],
        }
    }
}

impl SemanticShadowConfig {
    pub fn enabled(privacy_key: [u8; 32]) -> Self {
        Self {
            enabled: true,
            privacy_key,
            ..Self::default()
        }
    }

    pub(crate) fn is_valid(self) -> bool {
        !self.enabled
            || (self.queue_capacity > 0
                // PHXQ1 receipts intentionally have a frozen top-64 candidate and
                // top-10 exact-rerank meaning. A different geometry needs a new
                // receipt contract rather than silently changing these metrics.
                && self.candidate_k == 64
                && self.rerank_k == 10
                && self.maximum_rows > 0
                && self.minimum_logical_cpus > 0
                && self.sample_denominator > 0
                && self.exact_reference_denominator > 0
                && self.privacy_key != [0; 32])
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SemanticEmbeddingError {
    Unavailable,
    Rejected,
}

pub trait SemanticQueryEmbedder: Send + Sync + std::fmt::Debug + 'static {
    fn embed_query(
        &self,
        query: &str,
        expected_dimension: usize,
        output: &mut Vec<f32>,
    ) -> Result<(), SemanticEmbeddingError>;
}

#[derive(Debug, Error)]
pub enum SemanticShadowInstallError {
    #[error(transparent)]
    Embedding(#[from] EmbeddingPageError),
    #[error(transparent)]
    Quantized(#[from] TurboQuantError),
    #[error("semantic sidecars do not share one exact row and authority contract")]
    AuthorityMismatch,
    #[error("semantic sidecar generation is not the current resident generation")]
    GenerationMismatch,
    #[error("semantic sidecar has {actual} rows, exceeding the qualified maximum {maximum}")]
    Oversized { actual: usize, maximum: usize },
    #[error("semantic shadow lifecycle lock is poisoned")]
    Poisoned,
}

pub struct ResidentSemanticIndex {
    embeddings: VerifiedEmbeddingPagesV1,
    quantized: VerifiedQuantizedIndex,
}

impl std::fmt::Debug for ResidentSemanticIndex {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ResidentSemanticIndex")
            .field("generation_hash", &self.generation_hash())
            .field("rows", &self.quantized.len())
            .field("dimension", &self.quantized.dimension())
            .field("bits", &self.quantized.bits())
            .finish()
    }
}

impl ResidentSemanticIndex {
    pub fn open(
        embedding_path: impl AsRef<Path>,
        quantized_path: impl AsRef<Path>,
        expected_generation_hash: [u8; 32],
    ) -> Result<Self, SemanticShadowInstallError> {
        let embeddings = VerifiedEmbeddingPagesV1::open_expected(
            embedding_path,
            EmbeddingPageExpectation {
                generation_hash: Some(expected_generation_hash),
                ..EmbeddingPageExpectation::default()
            },
        )?;
        let authority = ArtifactAuthority::from_embedding_header(embeddings.header());
        let quantized = VerifiedQuantizedIndex::open_expected(quantized_path, Some(authority))?;
        let rows = embeddings.rows()?;
        let subject_ids = quantized.subject_ids()?;
        if quantized.dimension() != embeddings.header().dimension as usize
            || quantized.len() != rows.len()
            || subject_ids
                .iter()
                .zip(rows)
                .any(|(subject_id, row)| *subject_id != row.subject_id)
        {
            return Err(SemanticShadowInstallError::AuthorityMismatch);
        }
        Ok(Self {
            embeddings,
            quantized,
        })
    }

    pub fn generation_hash(&self) -> [u8; 32] {
        self.embeddings.header().generation_hash
    }

    pub fn embedding_artifact_hash(&self) -> [u8; 32] {
        self.embeddings.header().artifact_hash
    }

    pub fn quantized_artifact_hash(&self) -> [u8; 32] {
        self.quantized.header().artifact_hash
    }

    pub fn rows(&self) -> usize {
        self.quantized.len()
    }

    pub fn dimension(&self) -> usize {
        self.quantized.dimension()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticShadowSubmissionReceipt {
    pub path_id: SemanticShadowPathId,
    pub status: SemanticShadowStatus,
    pub authority_unchanged: bool,
    pub query_hash: [u8; 32],
    pub generation_hash: Option<[u8; 32]>,
    pub sidecar_status: SemanticSidecarStatus,
}

impl Default for SemanticShadowSubmissionReceipt {
    fn default() -> Self {
        Self {
            path_id: SemanticShadowPathId::Phxq1ShadowV1,
            status: SemanticShadowStatus::Disabled,
            authority_unchanged: true,
            query_hash: [0; 32],
            generation_hash: None,
            sidecar_status: SemanticSidecarStatus::Absent,
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct SemanticShadowEvaluationReceipt {
    pub path_id: SemanticShadowPathId,
    pub status: SemanticShadowEvaluationStatus,
    pub authority_unchanged: bool,
    pub query_hash: [u8; 32],
    pub query_embedding_hash: [u8; 32],
    pub generation_hash: [u8; 32],
    pub embedding_artifact_hash: [u8; 32],
    pub quantized_artifact_hash: [u8; 32],
    pub quantizer_hash: [u8; 32],
    pub bits: u8,
    pub rows: u32,
    pub dimension: u32,
    pub kernel: Option<SearchKernel>,
    pub execution: Option<SearchExecution>,
    pub exact_reference_sampled: bool,
    pub quantized_top64_hash: [u8; 32],
    pub reranked_top10_hash: [u8; 32],
    pub exact_top10_hash: [u8; 32],
    pub exact_top1_in_top64: bool,
    pub exact_top10_recall_at_64: u16,
    pub reranked_top1_equal: bool,
    pub ordered_top10_equal: bool,
    pub embedding_ns: u64,
    pub quantized_ns: u64,
    pub rerank_ns: u64,
    pub exact_reference_ns: u64,
    pub total_ns: u64,
}

#[derive(Clone, Debug, Default)]
pub struct SemanticShadowRuntimeSnapshot {
    pub sidecar_status: SemanticSidecarStatus,
    pub generation_hash: Option<[u8; 32]>,
    pub embedding_artifact_hash: Option<[u8; 32]>,
    pub quantized_artifact_hash: Option<[u8; 32]>,
    pub queue_capacity: u64,
    pub queue_depth: u64,
    pub queue_high_water: u64,
    pub submitted: u64,
    pub completed: u64,
    pub dropped: u64,
    pub failures: u64,
    pub latest_submission: Option<SemanticShadowSubmissionReceipt>,
    pub latest: Option<Arc<SemanticShadowEvaluationReceipt>>,
}

struct SidecarSlot {
    observed_generation: Option<[u8; 32]>,
    building_generation: Option<[u8; 32]>,
    status: SemanticSidecarStatus,
    index: Option<Arc<ResidentSemanticIndex>>,
}

impl Default for SidecarSlot {
    fn default() -> Self {
        Self {
            observed_generation: None,
            building_generation: None,
            status: SemanticSidecarStatus::Absent,
            index: None,
        }
    }
}

struct RuntimeMetrics {
    queue_depth: AtomicU64,
    queue_high_water: AtomicU64,
    submitted: AtomicU64,
    completed: AtomicU64,
    dropped: AtomicU64,
    failures: AtomicU64,
    latest_submission: RwLock<Option<SemanticShadowSubmissionReceipt>>,
    latest: RwLock<Option<Arc<SemanticShadowEvaluationReceipt>>>,
}

impl Default for RuntimeMetrics {
    fn default() -> Self {
        Self {
            queue_depth: AtomicU64::new(0),
            queue_high_water: AtomicU64::new(0),
            submitted: AtomicU64::new(0),
            completed: AtomicU64::new(0),
            dropped: AtomicU64::new(0),
            failures: AtomicU64::new(0),
            latest_submission: RwLock::new(None),
            latest: RwLock::new(None),
        }
    }
}

enum Work {
    Evaluate(EvaluationJob),
    Shutdown,
}

struct EvaluationJob {
    query: Arc<str>,
    query_hash: [u8; 32],
    generation_hash: [u8; 32],
    exact_reference_sampled: bool,
    index: Arc<ResidentSemanticIndex>,
}

#[derive(Clone)]
pub(crate) struct SemanticShadowHandle {
    config: SemanticShadowConfig,
    sender: Option<SyncSender<Work>>,
    sidecar: Arc<RwLock<SidecarSlot>>,
    metrics: Arc<RuntimeMetrics>,
    shutting_down: Arc<AtomicBool>,
}

pub(crate) struct SemanticShadowController {
    handle: SemanticShadowHandle,
    worker: Option<JoinHandle<()>>,
}

impl SemanticShadowController {
    pub(crate) fn start(
        config: SemanticShadowConfig,
        embedder: Option<Arc<dyn SemanticQueryEmbedder>>,
    ) -> Self {
        let sidecar = Arc::new(RwLock::new(SidecarSlot::default()));
        let metrics = Arc::new(RuntimeMetrics::default());
        let shutting_down = Arc::new(AtomicBool::new(false));
        let mut worker = None;
        let sender = if config.enabled {
            if let Some(embedder) = embedder {
                let (sender, receiver) = mpsc::sync_channel(config.queue_capacity);
                let worker_metrics = Arc::clone(&metrics);
                let worker_sidecar = Arc::clone(&sidecar);
                let worker_shutdown = Arc::clone(&shutting_down);
                worker = thread::Builder::new()
                    .name("phoenix-semantic-shadow".to_owned())
                    .spawn(move || {
                        run_worker(
                            receiver,
                            worker_metrics,
                            worker_sidecar,
                            worker_shutdown,
                            embedder,
                            config,
                        )
                    })
                    .ok();
                worker.as_ref().map(|_| sender)
            } else {
                None
            }
        } else {
            None
        };
        let handle = SemanticShadowHandle {
            config,
            sender,
            sidecar,
            metrics,
            shutting_down,
        };
        Self { handle, worker }
    }

    pub(crate) fn handle(&self) -> SemanticShadowHandle {
        self.handle.clone()
    }

    pub(crate) fn install(
        &self,
        index: Arc<ResidentSemanticIndex>,
    ) -> Result<(), SemanticShadowInstallError> {
        self.handle.install(index)
    }

    pub(crate) fn mark_building(
        &self,
        generation_hash: [u8; 32],
    ) -> Result<(), SemanticShadowInstallError> {
        self.handle.mark_building(generation_hash)
    }

    pub(crate) fn mark_invalid(&self, generation_hash: [u8; 32]) {
        self.handle.mark_invalid(generation_hash);
    }

    pub(crate) fn snapshot(&self) -> SemanticShadowRuntimeSnapshot {
        self.handle.snapshot()
    }

    pub(crate) fn stop(&mut self) {
        self.handle.shutting_down.store(true, Ordering::Release);
        if let Some(sender) = &self.handle.sender {
            let _ = sender.try_send(Work::Shutdown);
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

impl Drop for SemanticShadowController {
    fn drop(&mut self) {
        self.stop();
    }
}

impl SemanticShadowHandle {
    pub(crate) fn deferred(
        &self,
        generation_hash: Option<[u8; 32]>,
    ) -> SemanticShadowSubmissionReceipt {
        if !self.config.enabled {
            return SemanticShadowSubmissionReceipt::default();
        }
        SemanticShadowSubmissionReceipt {
            status: SemanticShadowStatus::Deferred,
            generation_hash,
            ..SemanticShadowSubmissionReceipt::default()
        }
    }

    pub(crate) fn observe_generation(&self, generation_hash: [u8; 32]) {
        let Ok(mut slot) = self.sidecar.write() else {
            return;
        };
        slot.observed_generation = Some(generation_hash);
        if slot
            .index
            .as_ref()
            .is_some_and(|index| index.generation_hash() == generation_hash)
        {
            slot.status = SemanticSidecarStatus::Ready;
            slot.building_generation = None;
        } else if slot.index.is_some() {
            slot.status = SemanticSidecarStatus::Stale;
            slot.building_generation = None;
        } else if slot.building_generation != Some(generation_hash) {
            slot.status = SemanticSidecarStatus::Absent;
            slot.building_generation = None;
        }
    }

    fn mark_building(&self, generation_hash: [u8; 32]) -> Result<(), SemanticShadowInstallError> {
        let mut slot = self
            .sidecar
            .write()
            .map_err(|_| SemanticShadowInstallError::Poisoned)?;
        if slot.observed_generation != Some(generation_hash) {
            return Err(SemanticShadowInstallError::GenerationMismatch);
        }
        slot.status = SemanticSidecarStatus::Building;
        slot.building_generation = Some(generation_hash);
        Ok(())
    }

    fn mark_invalid(&self, generation_hash: [u8; 32]) {
        if let Ok(mut slot) = self.sidecar.write() {
            if slot.observed_generation == Some(generation_hash) {
                slot.status = SemanticSidecarStatus::Invalid;
                slot.building_generation = None;
            }
        }
    }

    fn install(&self, index: Arc<ResidentSemanticIndex>) -> Result<(), SemanticShadowInstallError> {
        let mut slot = self
            .sidecar
            .write()
            .map_err(|_| SemanticShadowInstallError::Poisoned)?;
        if slot.observed_generation != Some(index.generation_hash()) {
            return Err(SemanticShadowInstallError::GenerationMismatch);
        }
        if index.rows() > self.config.maximum_rows {
            return Err(SemanticShadowInstallError::Oversized {
                actual: index.rows(),
                maximum: self.config.maximum_rows,
            });
        }
        slot.index = Some(index);
        slot.status = SemanticSidecarStatus::Ready;
        slot.building_generation = None;
        Ok(())
    }

    pub(crate) fn submit(
        &self,
        query: Arc<str>,
        generation_hash: Option<[u8; 32]>,
    ) -> SemanticShadowSubmissionReceipt {
        let receipt = self.submit_inner(query, generation_hash);
        if let Ok(mut latest) = self.metrics.latest_submission.write() {
            *latest = Some(receipt.clone());
        }
        receipt
    }

    fn submit_inner(
        &self,
        query: Arc<str>,
        generation_hash: Option<[u8; 32]>,
    ) -> SemanticShadowSubmissionReceipt {
        if !self.config.enabled {
            return SemanticShadowSubmissionReceipt::default();
        }
        let query_hash = keyed_hash(self.config.privacy_key, b"query/v1", query.as_bytes());
        let base = |status, sidecar_status| SemanticShadowSubmissionReceipt {
            status,
            query_hash,
            generation_hash,
            sidecar_status,
            ..SemanticShadowSubmissionReceipt::default()
        };
        let Some(generation_hash) = generation_hash else {
            return base(
                SemanticShadowStatus::SidecarAbsent,
                SemanticSidecarStatus::Absent,
            );
        };
        if std::thread::available_parallelism().map_or(1, usize::from)
            < self.config.minimum_logical_cpus
        {
            return base(
                SemanticShadowStatus::HostUnqualified,
                self.sidecar
                    .read()
                    .map_or(SemanticSidecarStatus::Invalid, |slot| slot.status),
            );
        }
        if !sample(query_hash, self.config.sample_denominator) {
            return base(
                SemanticShadowStatus::SkippedBudget,
                self.sidecar
                    .read()
                    .map_or(SemanticSidecarStatus::Invalid, |slot| slot.status),
            );
        }
        let (sidecar_status, index) = match self.sidecar.read() {
            Ok(slot) => (slot.status, slot.index.clone()),
            Err(_) => (SemanticSidecarStatus::Invalid, None),
        };
        if sidecar_status != SemanticSidecarStatus::Ready {
            return base(status_for_sidecar(sidecar_status), sidecar_status);
        }
        let Some(index) = index.filter(|index| index.generation_hash() == generation_hash) else {
            return base(
                SemanticShadowStatus::SidecarStale,
                SemanticSidecarStatus::Stale,
            );
        };
        let Some(sender) = &self.sender else {
            return base(SemanticShadowStatus::ModelUnavailable, sidecar_status);
        };
        let exact_reference_sampled = sample(query_hash, self.config.exact_reference_denominator);
        let depth = self
            .metrics
            .queue_depth
            .fetch_add(1, Ordering::AcqRel)
            .saturating_add(1);
        let job = Work::Evaluate(EvaluationJob {
            query,
            query_hash,
            generation_hash,
            exact_reference_sampled,
            index,
        });
        match sender.try_send(job) {
            Ok(()) => {
                self.metrics
                    .queue_high_water
                    .fetch_max(depth, Ordering::AcqRel);
                self.metrics.submitted.fetch_add(1, Ordering::AcqRel);
                base(SemanticShadowStatus::Queued, sidecar_status)
            }
            Err(TrySendError::Full(_)) => {
                self.metrics.queue_depth.fetch_sub(1, Ordering::AcqRel);
                self.metrics.dropped.fetch_add(1, Ordering::AcqRel);
                base(SemanticShadowStatus::QueueFull, sidecar_status)
            }
            Err(TrySendError::Disconnected(_)) => {
                self.metrics.queue_depth.fetch_sub(1, Ordering::AcqRel);
                base(SemanticShadowStatus::ModelUnavailable, sidecar_status)
            }
        }
    }

    fn snapshot(&self) -> SemanticShadowRuntimeSnapshot {
        let (sidecar_status, generation_hash, embedding_hash, quantized_hash) = self
            .sidecar
            .read()
            .map(|slot| {
                (
                    slot.status,
                    slot.observed_generation,
                    slot.index
                        .as_ref()
                        .map(|index| index.embedding_artifact_hash()),
                    slot.index
                        .as_ref()
                        .map(|index| index.quantized_artifact_hash()),
                )
            })
            .unwrap_or((SemanticSidecarStatus::Invalid, None, None, None));
        SemanticShadowRuntimeSnapshot {
            sidecar_status,
            generation_hash,
            embedding_artifact_hash: embedding_hash,
            quantized_artifact_hash: quantized_hash,
            queue_capacity: self.config.queue_capacity as u64,
            queue_depth: self.metrics.queue_depth.load(Ordering::Acquire),
            queue_high_water: self.metrics.queue_high_water.load(Ordering::Acquire),
            submitted: self.metrics.submitted.load(Ordering::Acquire),
            completed: self.metrics.completed.load(Ordering::Acquire),
            dropped: self.metrics.dropped.load(Ordering::Acquire),
            failures: self.metrics.failures.load(Ordering::Acquire),
            latest_submission: self
                .metrics
                .latest_submission
                .read()
                .ok()
                .and_then(|value| value.clone()),
            latest: self
                .metrics
                .latest
                .read()
                .ok()
                .and_then(|value| value.clone()),
        }
    }
}

fn status_for_sidecar(status: SemanticSidecarStatus) -> SemanticShadowStatus {
    match status {
        SemanticSidecarStatus::Absent => SemanticShadowStatus::SidecarAbsent,
        SemanticSidecarStatus::Building => SemanticShadowStatus::SidecarBuilding,
        SemanticSidecarStatus::Ready => SemanticShadowStatus::Queued,
        SemanticSidecarStatus::Stale => SemanticShadowStatus::SidecarStale,
        SemanticSidecarStatus::Invalid => SemanticShadowStatus::SidecarInvalid,
    }
}

fn sample(hash: [u8; 32], denominator: u32) -> bool {
    u64::from_le_bytes(hash[..8].try_into().expect("fixed hash width")) % u64::from(denominator)
        == 0
}

fn keyed_hash(key: [u8; 32], domain: &[u8], bytes: &[u8]) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new_keyed(&key);
    hasher.update(b"phoenix/semantic-shadow/");
    hasher.update(domain);
    hasher.update(bytes);
    *hasher.finalize().as_bytes()
}

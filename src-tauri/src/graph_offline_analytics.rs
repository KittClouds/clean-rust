use std::fmt;
#[cfg(feature = "graph-analytics-wgpu-shadow")]
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use graph_analytics_wgpu_kernel::{
    cpu_analyze, AnalyticsInput, AnalyticsOutput, DispatchBackend, DispatchPolicy, EdgePolicy,
    GpuGraphAnalyticsRuntime, PackedEdge, RunConfig, WorkloadShape,
};
#[cfg(feature = "graph-analytics-wgpu-shadow")]
use phoenix_discovery_community::{
    prepare_deterministic_community_shadow, CommunityArtifactManifest, CommunityWgpuShadowReceipt,
    CommunityWorkloadShape, DeterministicCommunityPolicy,
};
#[cfg(feature = "graph-analytics-wgpu-shadow")]
use phoenix_discovery_view::{AssertedDiscoveryView, DiscoveryRelationPolicy};
use serde::Serialize;

pub const SHADOW_PATH_ID: &str = "offline_graph_analytics_shadow_v1";
const GPU_PATH_ID: &str = "gpu_wgpu_resident_v1";
const CPU_PATH_ID: &str = "cpu_deterministic_v1";
const DEFAULT_GPU_BUDGET: u64 = 2 * 1024 * 1024 * 1024;
const COMMUNITY_CPU_PATH_ID: &str = "community_cpu_deterministic_v1";
const COMMUNITY_GPU_PATH_ID: &str = "community_gpu_wgpu_resident_v1";
const COMMUNITY_GPU_MIN_CORE_NODES: u64 = 50_000;
const COMMUNITY_GPU_MIN_SELECTED_EDGES: u64 = 500_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OfflineAnalyticsMode {
    CpuRequired,
    GpuRequired,
    AutoQualified,
}

#[derive(Clone, Debug)]
pub struct OfflineAnalyticsBatch {
    pub node_count: u32,
    pub relation_family_count: u32,
    pub edges: Vec<PackedEdge>,
    pub node_policy_mask: Vec<u32>,
    pub partition_labels: Vec<u32>,
    pub diffusion_seeds: Vec<f32>,
    pub diffusion_source_count: u32,
    pub edge_policy: EdgePolicy,
}

impl OfflineAnalyticsBatch {
    fn input(&self) -> AnalyticsInput<'_> {
        AnalyticsInput {
            node_count: self.node_count,
            relation_family_count: self.relation_family_count,
            edges: &self.edges,
            node_policy_mask: &self.node_policy_mask,
            partition_labels: &self.partition_labels,
            diffusion_seeds: &self.diffusion_seeds,
            diffusion_source_count: self.diffusion_source_count,
            edge_policy: self.edge_policy,
        }
    }
}

#[derive(Clone, Debug)]
pub struct OfflineAnalyticsJob {
    pub generation: u64,
    pub source_artifact_digest: String,
    pub mode: OfflineAnalyticsMode,
    pub config: RunConfig,
    pub batch: OfflineAnalyticsBatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OfflineAnalyticsReceipt {
    pub schema_version: &'static str,
    pub shadow_path_id: &'static str,
    pub execution_path_id: &'static str,
    pub selection_reason: &'static str,
    pub generation: u64,
    pub source_artifact_digest: String,
    pub output_digest_blake3: String,
    pub nodes: u32,
    pub edges: u32,
    pub diffusion_sources: u32,
    pub fallback_count: u32,
    pub resident_uploads: u32,
    pub prepartition_dispatches: u32,
    pub postpartition_dispatches: u32,
    pub runtime_reused: bool,
    pub runtime_init_micros: u64,
    pub adapter: Option<String>,
    pub prepare_micros: u64,
    pub execute_micros: u64,
    pub readback_micros: u64,
    pub resident_bytes: u64,
    pub readback_bytes: u64,
    pub published: bool,
}

#[derive(Clone, Debug)]
pub struct OfflineAnalyticsShadowResult {
    pub receipt: OfflineAnalyticsReceipt,
    pub output: AnalyticsOutput,
}

#[derive(Clone, Debug)]
pub struct OfflineCommunityArtifactJob {
    pub generation: u64,
    pub source_artifact_digest: String,
    pub source_artifact_root: PathBuf,
    pub shadow_artifact_root: PathBuf,
    pub mode: OfflineAnalyticsMode,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OfflineCommunityArtifactReceipt {
    pub schema_version: &'static str,
    pub execution_path_id: &'static str,
    pub selection_reason: &'static str,
    pub generation: u64,
    pub source_artifact_digest: String,
    pub artifact_digest: String,
    pub payload_digest: String,
    pub nodes: u64,
    pub core_nodes: u64,
    pub selected_edges: u64,
    pub fallback_count: u32,
    pub resident_uploads: u32,
    pub runtime_reused: bool,
    pub runtime_init_micros: u64,
    pub wall_micros: u64,
    pub gpu_prepare_micros: u64,
    pub gpu_execute_micros: u64,
    pub gpu_readback_micros: u64,
    pub cpu_pipeline_micros: u64,
    pub cpu_leiden_micros: u64,
    pub cpu_metrics_micros: u64,
    pub seal_micros: u64,
    pub resident_bytes: u64,
    pub readback_bytes: u64,
    pub adapter: Option<String>,
    pub production_published: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OfflineCommunityArtifactShadowResult {
    pub manifest: CommunityArtifactManifest,
    pub receipt: OfflineCommunityArtifactReceipt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OfflineAnalyticsError {
    pub code: &'static str,
    pub message: String,
}

impl fmt::Display for OfflineAnalyticsError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for OfflineAnalyticsError {}

#[derive(Default)]
struct RuntimeSlot {
    runtime: Option<Arc<GpuGraphAnalyticsRuntime>>,
    failure: Option<String>,
}

pub struct OfflineAnalyticsCoordinator {
    latest_generation: AtomicU64,
    runtime: Mutex<RuntimeSlot>,
    dispatch_policy: DispatchPolicy,
    maximum_gpu_bytes: u64,
}

impl Default for OfflineAnalyticsCoordinator {
    fn default() -> Self {
        Self::new(DispatchPolicy::default(), DEFAULT_GPU_BUDGET)
    }
}

impl OfflineAnalyticsCoordinator {
    pub fn new(dispatch_policy: DispatchPolicy, maximum_gpu_bytes: u64) -> Self {
        Self {
            latest_generation: AtomicU64::new(0),
            runtime: Mutex::new(RuntimeSlot::default()),
            dispatch_policy,
            maximum_gpu_bytes,
        }
    }

    pub fn latest_generation(&self) -> u64 {
        self.latest_generation.load(Ordering::Acquire)
    }

    pub fn run_community_artifact_shadow(
        &self,
        job: &OfflineCommunityArtifactJob,
    ) -> Result<OfflineCommunityArtifactShadowResult, OfflineAnalyticsError> {
        if job.generation == 0 || job.source_artifact_digest.is_empty() {
            return Err(error(
                "PHX_ANALYTICS_INPUT_INVALID",
                "generation and source artifact digest are required",
            ));
        }
        self.claim_generation(job.generation)?;
        let source = AssertedDiscoveryView::open(&job.source_artifact_root)
            .map_err(|cause| error("PHX_ANALYTICS_MMAP_SOURCE_INVALID", cause.to_string()))?;
        if source.manifest().generation != job.generation
            || source.manifest().artifact_digest != job.source_artifact_digest
        {
            return Err(error(
                "PHX_ANALYTICS_REPLAY_IDENTITY_MISMATCH",
                "mapped discovery generation or digest differs from the frozen job",
            ));
        }
        self.ensure_current(job.generation)?;
        let wall_started = Instant::now();
        let relation_policy = DiscoveryRelationPolicy::phoenix_asserted_v1();
        let community_policy = DeterministicCommunityPolicy::phoenix_semantic_core_v1();
        let prepared =
            prepare_deterministic_community_shadow(&source, &relation_policy, &community_policy)
                .map_err(|cause| {
                    error("PHX_ANALYTICS_COMMUNITY_PREPARE_FAILED", cause.to_string())
                })?;
        let shape = prepared.shape();
        let qualified = community_gpu_qualified(shape);
        let use_gpu = match job.mode {
            OfflineAnalyticsMode::CpuRequired => false,
            OfflineAnalyticsMode::GpuRequired => true,
            OfflineAnalyticsMode::AutoQualified => qualified,
        };
        self.ensure_current(job.generation)?;
        let (manifest, runtime_reused, runtime_init_micros, gpu, cpu_pipeline_micros) = if use_gpu {
            let (runtime, reused, init_micros) = self.runtime()?;
            let result = prepared
                .write_gpu(
                    &source,
                    &relation_policy,
                    &community_policy,
                    &runtime,
                    &job.shadow_artifact_root,
                )
                .map_err(|cause| error("PHX_ANALYTICS_COMMUNITY_GPU_FAILED", cause.to_string()))?;
            (
                result.manifest,
                reused,
                init_micros,
                Some(result.receipt),
                0,
            )
        } else {
            let cpu_started = Instant::now();
            let manifest = prepared
                .write_cpu(
                    &source,
                    &relation_policy,
                    &community_policy,
                    &job.shadow_artifact_root,
                )
                .map_err(|cause| error("PHX_ANALYTICS_COMMUNITY_CPU_FAILED", cause.to_string()))?;
            (
                manifest,
                false,
                0,
                None,
                cpu_started.elapsed().as_micros() as u64,
            )
        };
        self.ensure_current(job.generation)?;
        let execution_path_id = if use_gpu {
            COMMUNITY_GPU_PATH_ID
        } else {
            COMMUNITY_CPU_PATH_ID
        };
        let selection_reason = match (job.mode, use_gpu) {
            (OfflineAnalyticsMode::CpuRequired, _) => "cpu_required",
            (OfflineAnalyticsMode::GpuRequired, _) => "gpu_required",
            (OfflineAnalyticsMode::AutoQualified, true) => "structural_gpu_crossover_met",
            (OfflineAnalyticsMode::AutoQualified, false) => "below_structural_gpu_crossover",
        };
        let receipt = community_receipt(
            execution_path_id,
            selection_reason,
            &job.source_artifact_digest,
            shape,
            &manifest,
            runtime_reused,
            runtime_init_micros,
            wall_started.elapsed().as_micros() as u64,
            cpu_pipeline_micros,
            gpu.as_ref(),
        );
        Ok(OfflineCommunityArtifactShadowResult { manifest, receipt })
    }

    pub fn run_shadow(
        &self,
        job: &OfflineAnalyticsJob,
    ) -> Result<OfflineAnalyticsShadowResult, OfflineAnalyticsError> {
        if job.generation == 0 || job.source_artifact_digest.is_empty() {
            return Err(error(
                "PHX_ANALYTICS_INPUT_INVALID",
                "generation and source artifact digest are required",
            ));
        }
        self.claim_generation(job.generation)?;
        let input = job.batch.input();
        let shape = WorkloadShape::from_input(input, job.config).ok_or_else(|| {
            error(
                "PHX_ANALYTICS_INPUT_INVALID",
                "workload shape exceeds supported packed counters",
            )
        })?;
        let selection = self.select(job.mode, shape)?;
        let execution_path_id = selection.path_id;
        let selection_reason = selection.reason;
        let selected_runtime_reused = selection.runtime_reused;
        let runtime_init_micros = selection.runtime_init_micros;
        self.ensure_current(job.generation)?;
        let (output, runtime_reused, adapter, resident_uploads, pre, post) = match selection.backend
        {
            SelectedBackend::Cpu => {
                let started = Instant::now();
                let mut output = cpu_analyze(input, job.config)
                    .map_err(|cause| error("PHX_ANALYTICS_CPU_FAILED", cause.to_string()))?;
                output.timing.execute_micros = started.elapsed().as_micros() as u64;
                (output, false, None, 0, 0, 0)
            }
            SelectedBackend::Gpu(runtime) => {
                let adapter = runtime.adapter_receipt().name.clone();
                let mut resident = runtime
                    .upload_generation(input, job.config)
                    .map_err(|cause| error("PHX_ANALYTICS_GPU_UPLOAD_FAILED", cause.to_string()))?;
                self.ensure_current(job.generation)?;
                let prepartition = resident.prepartition().map_err(|cause| {
                    error("PHX_ANALYTICS_GPU_PREPARTITION_FAILED", cause.to_string())
                })?;
                self.ensure_current(job.generation)?;
                let bridge = resident
                    .postpartition(&job.batch.partition_labels)
                    .map_err(|cause| {
                        error("PHX_ANALYTICS_GPU_POSTPARTITION_FAILED", cause.to_string())
                    })?;
                self.ensure_current(job.generation)?;
                (
                    prepartition.finish(bridge),
                    selected_runtime_reused,
                    Some(adapter),
                    1,
                    1,
                    1,
                )
            }
        };
        self.ensure_current(job.generation)?;
        let output_digest_blake3 = output_digest(&output);
        let receipt = OfflineAnalyticsReceipt {
            schema_version: "phoenix-offline-graph-analytics-shadow/v1",
            shadow_path_id: SHADOW_PATH_ID,
            execution_path_id,
            selection_reason,
            generation: job.generation,
            source_artifact_digest: job.source_artifact_digest.clone(),
            output_digest_blake3,
            nodes: shape.nodes,
            edges: shape.edges,
            diffusion_sources: job.batch.diffusion_source_count,
            fallback_count: 0,
            resident_uploads,
            prepartition_dispatches: pre,
            postpartition_dispatches: post,
            runtime_reused,
            runtime_init_micros,
            adapter,
            prepare_micros: output.timing.prepare_micros,
            execute_micros: output.timing.execute_micros,
            readback_micros: output.timing.readback_micros,
            resident_bytes: output.timing.gpu_resident_bytes,
            readback_bytes: output.timing.readback_bytes,
            published: false,
        };
        Ok(OfflineAnalyticsShadowResult { receipt, output })
    }

    fn select(
        &self,
        mode: OfflineAnalyticsMode,
        shape: WorkloadShape,
    ) -> Result<Selection, OfflineAnalyticsError> {
        match mode {
            OfflineAnalyticsMode::CpuRequired => Ok(Selection::cpu("cpu_required")),
            OfflineAnalyticsMode::GpuRequired => {
                let (runtime, reused, init_micros) = self.runtime()?;
                Ok(Selection::gpu(runtime, reused, init_micros, "gpu_required"))
            }
            OfflineAnalyticsMode::AutoQualified => {
                if self.dispatch_policy.select(shape, 0, true) == DispatchBackend::Cpu {
                    return Ok(Selection::cpu("below_gpu_crossover"));
                }
                match self.runtime() {
                    Ok((runtime, reused, init_micros)) => Ok(Selection::gpu(
                        runtime,
                        reused,
                        init_micros,
                        "qualified_gpu_available",
                    )),
                    Err(_) => Ok(Selection::cpu("gpu_capability_unavailable_at_preflight")),
                }
            }
        }
    }

    fn runtime(&self) -> Result<(Arc<GpuGraphAnalyticsRuntime>, bool, u64), OfflineAnalyticsError> {
        let mut slot = self.runtime.lock().map_err(|_| {
            error(
                "PHX_ANALYTICS_COORDINATOR_POISONED",
                "GPU runtime slot lock is poisoned",
            )
        })?;
        if let Some(runtime) = slot.runtime.as_ref() {
            return Ok((Arc::clone(runtime), true, 0));
        }
        if let Some(failure) = slot.failure.as_ref() {
            return Err(error("PHX_ANALYTICS_GPU_UNAVAILABLE", failure.clone()));
        }
        let started = Instant::now();
        match GpuGraphAnalyticsRuntime::request(self.maximum_gpu_bytes) {
            Ok(runtime) => {
                let runtime = Arc::new(runtime);
                slot.runtime = Some(Arc::clone(&runtime));
                Ok((runtime, false, started.elapsed().as_micros() as u64))
            }
            Err(cause) => {
                let message = cause.to_string();
                slot.failure = Some(message.clone());
                Err(error("PHX_ANALYTICS_GPU_UNAVAILABLE", message))
            }
        }
    }

    fn claim_generation(&self, generation: u64) -> Result<(), OfflineAnalyticsError> {
        let previous = self
            .latest_generation
            .fetch_max(generation, Ordering::AcqRel);
        if generation < previous {
            return Err(cancelled(generation, previous));
        }
        Ok(())
    }

    fn ensure_current(&self, generation: u64) -> Result<(), OfflineAnalyticsError> {
        let latest = self.latest_generation.load(Ordering::Acquire);
        if generation == latest {
            Ok(())
        } else {
            Err(cancelled(generation, latest))
        }
    }
}

enum SelectedBackend {
    Cpu,
    Gpu(Arc<GpuGraphAnalyticsRuntime>),
}

struct Selection {
    backend: SelectedBackend,
    path_id: &'static str,
    reason: &'static str,
    runtime_reused: bool,
    runtime_init_micros: u64,
}

impl Selection {
    fn cpu(reason: &'static str) -> Self {
        Self {
            backend: SelectedBackend::Cpu,
            path_id: CPU_PATH_ID,
            reason,
            runtime_reused: false,
            runtime_init_micros: 0,
        }
    }

    fn gpu(
        runtime: Arc<GpuGraphAnalyticsRuntime>,
        runtime_reused: bool,
        runtime_init_micros: u64,
        reason: &'static str,
    ) -> Self {
        Self {
            backend: SelectedBackend::Gpu(runtime),
            path_id: GPU_PATH_ID,
            reason,
            runtime_reused,
            runtime_init_micros,
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn community_receipt(
    execution_path_id: &'static str,
    selection_reason: &'static str,
    source_artifact_digest: &str,
    shape: CommunityWorkloadShape,
    manifest: &CommunityArtifactManifest,
    runtime_reused: bool,
    runtime_init_micros: u64,
    wall_micros: u64,
    cpu_pipeline_micros: u64,
    gpu: Option<&CommunityWgpuShadowReceipt>,
) -> OfflineCommunityArtifactReceipt {
    OfflineCommunityArtifactReceipt {
        schema_version: "phoenix-offline-community-artifact-shadow/v1",
        execution_path_id,
        selection_reason,
        generation: manifest.generation,
        source_artifact_digest: source_artifact_digest.to_owned(),
        artifact_digest: manifest.artifact_digest.clone(),
        payload_digest: manifest.payload_digest.clone(),
        nodes: shape.nodes,
        core_nodes: shape.core_nodes,
        selected_edges: shape.selected_edges,
        fallback_count: 0,
        resident_uploads: gpu.map_or(0, |receipt| receipt.resident_uploads),
        runtime_reused,
        runtime_init_micros,
        wall_micros,
        gpu_prepare_micros: gpu.map_or(0, |receipt| receipt.prepare_micros),
        gpu_execute_micros: gpu.map_or(0, |receipt| receipt.gpu_execute_micros),
        gpu_readback_micros: gpu.map_or(0, |receipt| receipt.readback_micros),
        cpu_pipeline_micros,
        cpu_leiden_micros: gpu.map_or(0, |receipt| receipt.cpu_leiden_micros),
        cpu_metrics_micros: gpu.map_or(0, |receipt| receipt.cpu_metrics_micros),
        seal_micros: gpu.map_or(0, |receipt| receipt.seal_micros),
        resident_bytes: gpu.map_or(0, |receipt| receipt.resident_bytes),
        readback_bytes: gpu.map_or(0, |receipt| receipt.readback_bytes),
        adapter: gpu.map(|receipt| receipt.adapter.clone()),
        production_published: false,
    }
}

fn community_gpu_qualified(shape: CommunityWorkloadShape) -> bool {
    shape.core_nodes >= COMMUNITY_GPU_MIN_CORE_NODES
        && shape.selected_edges >= COMMUNITY_GPU_MIN_SELECTED_EDGES
}

fn output_digest(output: &AnalyticsOutput) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-offline-graph-analytics-output/v1\0");
    hash_u32(&mut hasher, &output.active_edge_mask);
    hash_u32(&mut hasher, &output.out_degree);
    hash_u32(&mut hasher, &output.in_degree);
    hash_u32(&mut hasher, &output.incident_degree);
    hash_u32(&mut hasher, &output.relation_family_histogram);
    hash_u32(&mut hasher, &output.component_labels);
    hash_u32(&mut hasher, &output.out_strength);
    hash_u32(&mut hasher, &output.total_strength);
    hash_u32(&mut hasher, &output.boundary_degree);
    hash_u32(&mut hasher, &output.boundary_strength);
    hash_u32(&mut hasher, &output.neighbor_degree_sum);
    hasher.update(&(output.diffusion_ranks.len() as u64).to_le_bytes());
    for value in &output.diffusion_ranks {
        hasher.update(&value.to_bits().to_le_bytes());
    }
    format!("b3-{}", hasher.finalize().to_hex())
}

fn hash_u32(hasher: &mut blake3::Hasher, values: &[u32]) {
    hasher.update(&(values.len() as u64).to_le_bytes());
    for value in values {
        hasher.update(&value.to_le_bytes());
    }
}

fn cancelled(generation: u64, latest: u64) -> OfflineAnalyticsError {
    error(
        "PHX_ANALYTICS_GENERATION_CANCELLED",
        format!("generation {generation} is stale; latest generation is {latest}"),
    )
}

fn error(code: &'static str, message: impl Into<String>) -> OfflineAnalyticsError {
    OfflineAnalyticsError {
        code,
        message: message.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn small_auto_job_is_explicit_cpu_shadow_and_never_publishes() {
        let coordinator = OfflineAnalyticsCoordinator::default();
        let job = fixture(7, OfflineAnalyticsMode::AutoQualified);
        let result = coordinator.run_shadow(&job).unwrap();
        assert_eq!(result.receipt.execution_path_id, CPU_PATH_ID);
        assert_eq!(result.receipt.selection_reason, "below_gpu_crossover");
        assert_eq!(result.receipt.fallback_count, 0);
        assert_eq!(result.receipt.resident_uploads, 0);
        assert!(!result.receipt.published);
    }

    #[test]
    fn newer_generation_cancels_older_job_before_execution() {
        let coordinator = OfflineAnalyticsCoordinator::default();
        coordinator
            .run_shadow(&fixture(9, OfflineAnalyticsMode::CpuRequired))
            .unwrap();
        let error = coordinator
            .run_shadow(&fixture(8, OfflineAnalyticsMode::CpuRequired))
            .unwrap_err();
        assert_eq!(error.code, "PHX_ANALYTICS_GENERATION_CANCELLED");
        assert_eq!(coordinator.latest_generation(), 9);
    }

    #[test]
    fn community_shadow_fails_closed_before_gpu_init_for_missing_mmap_source() {
        let coordinator = OfflineAnalyticsCoordinator::default();
        let root = tempfile::tempdir().unwrap();
        let error = coordinator
            .run_community_artifact_shadow(&OfflineCommunityArtifactJob {
                generation: 10,
                source_artifact_digest: "a".repeat(64),
                source_artifact_root: root.path().join("missing-source"),
                shadow_artifact_root: root.path().join("shadow"),
                mode: OfflineAnalyticsMode::AutoQualified,
            })
            .unwrap_err();
        assert_eq!(error.code, "PHX_ANALYTICS_MMAP_SOURCE_INVALID");
    }

    #[test]
    fn structural_gpu_crossover_requires_both_qualified_dimensions() {
        let qualified = CommunityWorkloadShape {
            nodes: 60_000,
            core_nodes: COMMUNITY_GPU_MIN_CORE_NODES,
            selected_edges: COMMUNITY_GPU_MIN_SELECTED_EDGES,
        };
        assert!(community_gpu_qualified(qualified));
        assert!(!community_gpu_qualified(CommunityWorkloadShape {
            core_nodes: COMMUNITY_GPU_MIN_CORE_NODES - 1,
            ..qualified
        }));
        assert!(!community_gpu_qualified(CommunityWorkloadShape {
            selected_edges: COMMUNITY_GPU_MIN_SELECTED_EDGES - 1,
            ..qualified
        }));
    }

    #[test]
    fn gpu_required_uses_one_resident_upload_for_both_stages() {
        let coordinator = OfflineAnalyticsCoordinator::default();
        let first = match coordinator.run_shadow(&fixture(11, OfflineAnalyticsMode::GpuRequired)) {
            Ok(result) => result,
            Err(error) if error.code == "PHX_ANALYTICS_GPU_UNAVAILABLE" => {
                eprintln!("hardware GPU test skipped: {error}");
                return;
            }
            Err(error) => panic!("unexpected coordinator error: {error}"),
        };
        let second = coordinator
            .run_shadow(&fixture(12, OfflineAnalyticsMode::GpuRequired))
            .unwrap();
        assert_eq!(first.receipt.execution_path_id, GPU_PATH_ID);
        assert_eq!(first.receipt.resident_uploads, 1);
        assert_eq!(first.receipt.prepartition_dispatches, 1);
        assert_eq!(first.receipt.postpartition_dispatches, 1);
        assert!(!first.receipt.runtime_reused);
        assert!(first.receipt.runtime_init_micros > 0);
        assert!(second.receipt.runtime_reused);
        assert_eq!(second.receipt.runtime_init_micros, 0);
        assert_eq!(
            first.receipt.output_digest_blake3,
            second.receipt.output_digest_blake3
        );
    }

    fn fixture(generation: u64, mode: OfflineAnalyticsMode) -> OfflineAnalyticsJob {
        let edges = vec![
            PackedEdge {
                source: 0,
                target: 1,
                relation_family: 0,
                weight: 2,
            },
            PackedEdge {
                source: 1,
                target: 2,
                relation_family: 1,
                weight: 3,
            },
            PackedEdge {
                source: 3,
                target: 4,
                relation_family: 0,
                weight: 5,
            },
        ];
        OfflineAnalyticsJob {
            generation,
            source_artifact_digest: "b3-fixture".to_owned(),
            mode,
            config: RunConfig {
                weak_component_iterations: 8,
                diffusion_iterations: 4,
                diffusion_damping: 0.85,
            },
            batch: OfflineAnalyticsBatch {
                node_count: 5,
                relation_family_count: 2,
                edges,
                node_policy_mask: vec![1; 5],
                partition_labels: vec![0, 0, 1, 2, 3],
                diffusion_seeds: vec![1.0, 0.0, 0.0, 0.0, 0.0],
                diffusion_source_count: 1,
                edge_policy: EdgePolicy::default(),
            },
        }
    }
}

use crate::build::write_prepared_community_artifact;
use crate::graph::{stable_key, SemanticCoreGraph};
use crate::leiden::{deterministic_leiden, PartitionResult};
use crate::metrics::{compute_metrics, CommunityMetrics};
use crate::{
    CommunityArtifactError, CommunityArtifactManifest, DeterministicCommunityPolicy,
    COMMUNITY_ARTIFACT_SCHEMA,
};
use graph_analytics_wgpu_kernel::{
    AnalyticsInput, EdgePolicy, GpuGraphAnalyticsRuntime, PackedEdge, PrepartitionOutput, RunConfig,
};
use hashbrown::HashMap;
use phoenix_discovery_view::{AssertedDiscoveryView, DiscoveryRelationPolicy, DiscoveryStableId};
use std::path::Path;
use std::time::Instant;

pub const COMMUNITY_WGPU_SHADOW_PATH_ID: &str = "community_mmap_wgpu_resident_shadow_v1";
const CPU_LEIDEN_PATH_ID: &str = "deterministic_rust_leiden_v1";
const WCC_ITERATIONS: u32 = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommunityWgpuShadowReceipt {
    pub schema_version: &'static str,
    pub path_id: &'static str,
    pub source_discovery_digest: String,
    pub source_mmap_bytes: u64,
    pub artifact_digest: String,
    pub payload_digest: String,
    pub artifact_schema: &'static str,
    pub generation: u64,
    pub node_count: u64,
    pub core_node_count: u64,
    pub selected_edge_count: u64,
    pub component_count: u64,
    pub community_count: u64,
    pub adapter: String,
    pub adapter_driver: String,
    pub resident_uploads: u32,
    pub prepartition_dispatches: u32,
    pub postpartition_dispatches: u32,
    pub fallback_count: u32,
    pub stable_component_canonicalization: bool,
    pub authoritative_partition_path: &'static str,
    pub prepare_micros: u64,
    pub gpu_execute_micros: u64,
    pub readback_micros: u64,
    pub cpu_leiden_micros: u64,
    pub cpu_metrics_micros: u64,
    pub seal_micros: u64,
    pub resident_bytes: u64,
    pub readback_bytes: u64,
    pub production_published: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommunityWgpuShadowResult {
    pub manifest: CommunityArtifactManifest,
    pub receipt: CommunityWgpuShadowReceipt,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CommunityWorkloadShape {
    pub nodes: u64,
    pub core_nodes: u64,
    pub selected_edges: u64,
}

pub struct PreparedCommunityShadow {
    graph: SemanticCoreGraph,
}

pub fn prepare_deterministic_community_shadow(
    source: &AssertedDiscoveryView,
    relation_policy: &DiscoveryRelationPolicy,
    policy: &DeterministicCommunityPolicy,
) -> Result<PreparedCommunityShadow, CommunityArtifactError> {
    policy.validate(relation_policy)?;
    Ok(PreparedCommunityShadow {
        graph: SemanticCoreGraph::build_unpartitioned(source, relation_policy, policy)?,
    })
}

pub fn write_deterministic_community_artifact_wgpu_shadow(
    source: &AssertedDiscoveryView,
    relation_policy: &DiscoveryRelationPolicy,
    policy: &DeterministicCommunityPolicy,
    runtime: &GpuGraphAnalyticsRuntime,
    artifact_root: impl AsRef<Path>,
) -> Result<CommunityWgpuShadowResult, CommunityArtifactError> {
    prepare_deterministic_community_shadow(source, relation_policy, policy)?.write_gpu(
        source,
        relation_policy,
        policy,
        runtime,
        artifact_root,
    )
}

impl PreparedCommunityShadow {
    pub fn shape(&self) -> CommunityWorkloadShape {
        CommunityWorkloadShape {
            nodes: self.graph.node_count as u64,
            core_nodes: self.graph.core_nodes.len() as u64,
            selected_edges: self.graph.edges.len() as u64,
        }
    }

    pub fn write_cpu(
        mut self,
        source: &AssertedDiscoveryView,
        relation_policy: &DiscoveryRelationPolicy,
        policy: &DeterministicCommunityPolicy,
        artifact_root: impl AsRef<Path>,
    ) -> Result<CommunityArtifactManifest, CommunityArtifactError> {
        self.graph.install_cpu_components()?;
        let partition = deterministic_leiden(&self.graph, policy)?;
        let metrics = compute_metrics(&self.graph, &partition, policy)?;
        write_prepared_community_artifact(
            source,
            relation_policy,
            policy,
            &self.graph,
            &partition,
            &metrics,
            artifact_root,
        )
    }

    pub fn write_gpu(
        mut self,
        source: &AssertedDiscoveryView,
        relation_policy: &DiscoveryRelationPolicy,
        policy: &DeterministicCommunityPolicy,
        runtime: &GpuGraphAnalyticsRuntime,
        artifact_root: impl AsRef<Path>,
    ) -> Result<CommunityWgpuShadowResult, CommunityArtifactError> {
        let prepared = PreparedGpuInput::new(&self.graph)?;
        let config = RunConfig {
            weak_component_iterations: WCC_ITERATIONS,
            diffusion_iterations: 0,
            diffusion_damping: 0.85,
        };
        let mut resident = runtime
            .upload_generation(prepared.input(), config)
            .map_err(|error| invalid("PHX_COMMUNITY_GPU_UPLOAD_FAILED", error))?;
        let prepartition = resident
            .prepartition()
            .map_err(|error| invalid("PHX_COMMUNITY_GPU_PREPARTITION_FAILED", error))?;
        verify_prepartition(&self.graph, &prepartition)?;
        let components = canonicalize_components(&self.graph, &prepartition.component_labels)?;
        self.graph.install_component_labels(components)?;

        let leiden_started = Instant::now();
        let partition = deterministic_leiden(&self.graph, policy)?;
        let cpu_leiden_micros = micros(leiden_started.elapsed());
        let bridge = resident
            .postpartition(&partition.node_community)
            .map_err(|error| invalid("PHX_COMMUNITY_GPU_POSTPARTITION_FAILED", error))?;
        verify_bridge_preprocessing(&self.graph, &partition, &bridge)?;

        let metrics_started = Instant::now();
        let metrics = compute_metrics(&self.graph, &partition, policy)?;
        let cpu_metrics_micros = micros(metrics_started.elapsed());
        verify_metric_bridge_rows(&self.graph, &partition, &metrics, &bridge)?;

        let seal_started = Instant::now();
        let manifest = write_prepared_community_artifact(
            source,
            relation_policy,
            policy,
            &self.graph,
            &partition,
            &metrics,
            artifact_root,
        )?;
        let seal_micros = micros(seal_started.elapsed());
        let adapter = runtime.adapter_receipt();
        let receipt = CommunityWgpuShadowReceipt {
            schema_version: "phoenix-community-wgpu-shadow-receipt/v1",
            path_id: COMMUNITY_WGPU_SHADOW_PATH_ID,
            source_discovery_digest: source.manifest().artifact_digest.clone(),
            source_mmap_bytes: source.manifest().binary_bytes,
            artifact_digest: manifest.artifact_digest.clone(),
            payload_digest: manifest.payload_digest.clone(),
            artifact_schema: COMMUNITY_ARTIFACT_SCHEMA,
            generation: manifest.generation,
            node_count: manifest.node_count,
            core_node_count: manifest.core_node_count,
            selected_edge_count: manifest.selected_edge_count,
            component_count: manifest.component_count,
            community_count: manifest.community_count,
            adapter: adapter.name.clone(),
            adapter_driver: adapter.driver_info.clone(),
            resident_uploads: 1,
            prepartition_dispatches: 1,
            postpartition_dispatches: 1,
            fallback_count: 0,
            stable_component_canonicalization: true,
            authoritative_partition_path: CPU_LEIDEN_PATH_ID,
            prepare_micros: prepartition.timing.prepare_micros,
            gpu_execute_micros: prepartition
                .timing
                .execute_micros
                .saturating_add(bridge.timing.execute_micros),
            readback_micros: prepartition
                .timing
                .readback_micros
                .saturating_add(bridge.timing.readback_micros),
            cpu_leiden_micros,
            cpu_metrics_micros,
            seal_micros,
            resident_bytes: prepartition.timing.gpu_resident_bytes,
            readback_bytes: prepartition
                .timing
                .readback_bytes
                .saturating_add(bridge.timing.readback_bytes),
            production_published: false,
        };
        Ok(CommunityWgpuShadowResult { manifest, receipt })
    }
}

struct PreparedGpuInput {
    node_count: u32,
    edges: Vec<PackedEdge>,
    node_mask: Vec<u32>,
    partition: Vec<u32>,
}

impl PreparedGpuInput {
    fn new(graph: &SemanticCoreGraph) -> Result<Self, CommunityArtifactError> {
        let node_count = u32::try_from(graph.node_count).map_err(|_| {
            invalid_message(
                "PHX_COMMUNITY_GPU_CAPABILITY_REJECTED",
                "node count exceeds packed GPU identity capacity",
            )
        })?;
        let mut edges = Vec::with_capacity(graph.edges.len());
        for edge in &graph.edges {
            edges.push(PackedEdge {
                source: edge.source,
                target: edge.target,
                relation_family: 0,
                weight: u32::try_from(edge.weight).map_err(|_| {
                    invalid_message(
                        "PHX_COMMUNITY_GPU_CAPABILITY_REJECTED",
                        "semantic edge weight exceeds exact u32 GPU capacity",
                    )
                })?,
            });
        }
        let mut node_mask = vec![0_u32; graph.node_count];
        for &node in &graph.core_nodes {
            node_mask[node as usize] = 1;
        }
        Ok(Self {
            node_count,
            edges,
            node_mask,
            partition: vec![u32::MAX; graph.node_count],
        })
    }

    fn input(&self) -> AnalyticsInput<'_> {
        AnalyticsInput {
            node_count: self.node_count,
            relation_family_count: 1,
            edges: &self.edges,
            node_policy_mask: &self.node_mask,
            partition_labels: &self.partition,
            diffusion_seeds: &[],
            diffusion_source_count: 0,
            edge_policy: EdgePolicy::default(),
        }
    }
}

fn canonicalize_components(
    graph: &SemanticCoreGraph,
    raw: &[u32],
) -> Result<Vec<u32>, CommunityArtifactError> {
    if raw.len() != graph.node_count {
        return Err(invalid_message(
            "PHX_COMMUNITY_GPU_COMPONENTS_INVALID",
            "GPU component labels do not match graph node count",
        ));
    }
    let mut minima = HashMap::<u32, DiscoveryStableId>::new();
    let mut core_mask = vec![false; graph.node_count];
    for &node in &graph.core_nodes {
        core_mask[node as usize] = true;
        let label = raw[node as usize];
        if label == u32::MAX {
            return Err(invalid_message(
                "PHX_COMMUNITY_GPU_COMPONENTS_INVALID",
                "GPU omitted a semantic-core node",
            ));
        }
        let identity = graph.stable[node as usize];
        minima
            .entry(label)
            .and_modify(|current| {
                if stable_key(identity) < stable_key(*current) {
                    *current = identity;
                }
            })
            .or_insert(identity);
    }
    for (node, &label) in raw.iter().enumerate() {
        if !core_mask[node] && label != u32::MAX {
            return Err(invalid_message(
                "PHX_COMMUNITY_GPU_COMPONENTS_INVALID",
                "GPU assigned a non-core node to a component",
            ));
        }
    }
    let mut order = minima.into_iter().collect::<Vec<_>>();
    order.sort_unstable_by_key(|(_, identity)| stable_key(*identity));
    let remap = order
        .into_iter()
        .enumerate()
        .map(|(dense, (label, _))| (label, dense as u32))
        .collect::<HashMap<_, _>>();
    let mut canonical = vec![u32::MAX; graph.node_count];
    for &node in &graph.core_nodes {
        canonical[node as usize] = remap[&raw[node as usize]];
    }
    Ok(canonical)
}

fn verify_prepartition(
    graph: &SemanticCoreGraph,
    output: &PrepartitionOutput,
) -> Result<(), CommunityArtifactError> {
    if output.active_edge_mask.len() != graph.edges.len()
        || output.active_edge_mask.iter().any(|&active| active != 1)
    {
        return Err(invalid_message(
            "PHX_COMMUNITY_GPU_POLICY_MISMATCH",
            "GPU edge policy did not preserve the asserted semantic-core graph",
        ));
    }
    for node in 0..graph.node_count {
        let expected = u32::try_from(graph.neighbors(node as u32).len()).map_err(|_| {
            invalid_message(
                "PHX_COMMUNITY_GPU_CAPABILITY_REJECTED",
                "semantic-core degree exceeds exact u32 GPU capacity",
            )
        })?;
        if output.incident_degree[node] != expected {
            return Err(invalid_message(
                "PHX_COMMUNITY_GPU_DEGREE_MISMATCH",
                "GPU incident degrees differ from the mmap graph",
            ));
        }
    }
    Ok(())
}

fn verify_bridge_preprocessing(
    graph: &SemanticCoreGraph,
    partition: &PartitionResult,
    bridge: &graph_analytics_wgpu_kernel::BridgePreprocessOutput,
) -> Result<(), CommunityArtifactError> {
    for node in 0..graph.node_count {
        let own = partition.node_community[node];
        let mut total = 0_u64;
        let mut boundary = 0_u64;
        let mut boundary_degree = 0_u32;
        for neighbor in graph.neighbors(node as u32) {
            total = total.checked_add(neighbor.weight).ok_or_else(|| {
                invalid_message(
                    "PHX_COMMUNITY_GPU_CAPABILITY_REJECTED",
                    "node strength overflow",
                )
            })?;
            if own != u32::MAX && partition.node_community[neighbor.node as usize] != own {
                boundary = boundary.checked_add(neighbor.weight).ok_or_else(|| {
                    invalid_message(
                        "PHX_COMMUNITY_GPU_CAPABILITY_REJECTED",
                        "boundary strength overflow",
                    )
                })?;
                boundary_degree = boundary_degree.checked_add(1).ok_or_else(|| {
                    invalid_message(
                        "PHX_COMMUNITY_GPU_CAPABILITY_REJECTED",
                        "boundary degree overflow",
                    )
                })?;
            }
        }
        let total = u32::try_from(total).map_err(|_| {
            invalid_message(
                "PHX_COMMUNITY_GPU_CAPABILITY_REJECTED",
                "node strength exceeds exact u32 GPU capacity",
            )
        })?;
        let boundary = u32::try_from(boundary).map_err(|_| {
            invalid_message(
                "PHX_COMMUNITY_GPU_CAPABILITY_REJECTED",
                "boundary strength exceeds exact u32 GPU capacity",
            )
        })?;
        if bridge.total_strength[node] != total
            || bridge.boundary_strength[node] != boundary
            || bridge.boundary_degree[node] != boundary_degree
        {
            return Err(invalid_message(
                "PHX_COMMUNITY_GPU_BRIDGE_MISMATCH",
                "GPU bridge preprocessing differs from deterministic Rust",
            ));
        }
    }
    Ok(())
}

fn verify_metric_bridge_rows(
    graph: &SemanticCoreGraph,
    partition: &PartitionResult,
    metrics: &CommunityMetrics,
    bridge: &graph_analytics_wgpu_kernel::BridgePreprocessOutput,
) -> Result<(), CommunityArtifactError> {
    for row in &metrics.bridges {
        let node = row.node as usize;
        if partition.node_community[node] == u32::MAX
            || row.total_strength != u64::from(bridge.total_strength[node])
            || row.boundary_strength != u64::from(bridge.boundary_strength[node])
            || graph.neighbors(row.node).is_empty()
        {
            return Err(invalid_message(
                "PHX_COMMUNITY_GPU_METRIC_MISMATCH",
                "sealed bridge metric inputs differ from GPU preprocessing",
            ));
        }
    }
    Ok(())
}

fn invalid(code: &'static str, error: impl std::fmt::Display) -> CommunityArtifactError {
    invalid_message(code, &error.to_string())
}

fn invalid_message(code: &'static str, message: &str) -> CommunityArtifactError {
    CommunityArtifactError::Invalid(format!("{code}: {message}"))
}

fn micros(duration: std::time::Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}

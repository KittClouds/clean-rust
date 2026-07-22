use bytemuck::{Pod, Zeroable};

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Pod, Zeroable)]
pub struct PackedEdge {
    pub source: u32,
    pub target: u32,
    pub relation_family: u32,
    pub weight: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EdgePolicy {
    /// Bit `n` admits relation family `n`; this exact proof supports 32 families.
    pub admitted_relation_families: u32,
    pub minimum_weight: u32,
}

impl Default for EdgePolicy {
    fn default() -> Self {
        Self {
            admitted_relation_families: u32::MAX,
            minimum_weight: 1,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct AnalyticsInput<'a> {
    pub node_count: u32,
    pub relation_family_count: u32,
    pub edges: &'a [PackedEdge],
    /// Zero excludes a node and all of its incident edges.
    pub node_policy_mask: &'a [u32],
    /// Existing authoritative partition labels used only for bridge preprocessing.
    /// `u32::MAX` means no partition label is available for that node.
    pub partition_labels: &'a [u32],
    /// Row-major personalized restart vectors: `source_count * node_count`.
    pub diffusion_seeds: &'a [f32],
    pub diffusion_source_count: u32,
    pub edge_policy: EdgePolicy,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RunConfig {
    pub weak_component_iterations: u32,
    pub diffusion_iterations: u32,
    pub diffusion_damping: f32,
}

impl Default for RunConfig {
    fn default() -> Self {
        Self {
            weak_component_iterations: 32,
            diffusion_iterations: 20,
            diffusion_damping: 0.85,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct AnalyticsTiming {
    pub prepare_micros: u64,
    pub execute_micros: u64,
    pub readback_micros: u64,
    pub gpu_resident_bytes: u64,
    pub readback_bytes: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct AnalyticsOutput {
    pub active_edge_mask: Vec<u32>,
    pub out_degree: Vec<u32>,
    pub in_degree: Vec<u32>,
    pub incident_degree: Vec<u32>,
    pub relation_family_histogram: Vec<u32>,
    pub component_labels: Vec<u32>,
    pub out_strength: Vec<u32>,
    pub total_strength: Vec<u32>,
    pub boundary_degree: Vec<u32>,
    pub boundary_strength: Vec<u32>,
    pub neighbor_degree_sum: Vec<u32>,
    pub diffusion_ranks: Vec<f32>,
    pub timing: AnalyticsTiming,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PrepartitionOutput {
    pub active_edge_mask: Vec<u32>,
    pub out_degree: Vec<u32>,
    pub in_degree: Vec<u32>,
    pub incident_degree: Vec<u32>,
    pub relation_family_histogram: Vec<u32>,
    pub component_labels: Vec<u32>,
    pub out_strength: Vec<u32>,
    pub neighbor_degree_sum: Vec<u32>,
    pub diffusion_ranks: Vec<f32>,
    pub timing: AnalyticsTiming,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BridgePreprocessOutput {
    pub total_strength: Vec<u32>,
    pub boundary_degree: Vec<u32>,
    pub boundary_strength: Vec<u32>,
    pub timing: AnalyticsTiming,
}

impl PrepartitionOutput {
    pub fn finish(self, bridge: BridgePreprocessOutput) -> AnalyticsOutput {
        AnalyticsOutput {
            active_edge_mask: self.active_edge_mask,
            out_degree: self.out_degree,
            in_degree: self.in_degree,
            incident_degree: self.incident_degree,
            relation_family_histogram: self.relation_family_histogram,
            component_labels: self.component_labels,
            out_strength: self.out_strength,
            total_strength: bridge.total_strength,
            boundary_degree: bridge.boundary_degree,
            boundary_strength: bridge.boundary_strength,
            neighbor_degree_sum: self.neighbor_degree_sum,
            diffusion_ranks: self.diffusion_ranks,
            timing: AnalyticsTiming {
                prepare_micros: self.timing.prepare_micros,
                execute_micros: self
                    .timing
                    .execute_micros
                    .saturating_add(bridge.timing.execute_micros),
                readback_micros: self
                    .timing
                    .readback_micros
                    .saturating_add(bridge.timing.readback_micros),
                gpu_resident_bytes: self.timing.gpu_resident_bytes,
                readback_bytes: self
                    .timing
                    .readback_bytes
                    .saturating_add(bridge.timing.readback_bytes),
            },
        }
    }
}

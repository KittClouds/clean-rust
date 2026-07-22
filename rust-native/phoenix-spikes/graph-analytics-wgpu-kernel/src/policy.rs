use crate::{AnalyticsInput, RunConfig};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DispatchBackend {
    Cpu,
    Gpu,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WorkloadShape {
    pub nodes: u32,
    pub edges: u32,
    pub diffusion_cell_updates: u64,
}

impl WorkloadShape {
    pub fn from_input(input: AnalyticsInput<'_>, config: RunConfig) -> Option<Self> {
        Some(Self {
            nodes: input.node_count,
            edges: u32::try_from(input.edges.len()).ok()?,
            diffusion_cell_updates: u64::from(input.node_count)
                .checked_mul(u64::from(input.diffusion_source_count))?
                .checked_mul(u64::from(config.diffusion_iterations))?,
        })
    }
}

/// Conservative RTX 3080 crossover policy for the whole one-shot envelope.
/// The caller records the returned backend; the GPU runtime never falls back.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DispatchPolicy {
    pub minimum_nodes: u32,
    pub minimum_edges: u32,
    pub minimum_diffusion_cell_updates: u64,
    pub maximum_resident_bytes: u64,
}

impl Default for DispatchPolicy {
    fn default() -> Self {
        Self {
            minimum_nodes: 10_000,
            minimum_edges: 100_000,
            minimum_diffusion_cell_updates: 320_000,
            maximum_resident_bytes: 2 * 1024 * 1024 * 1024,
        }
    }
}

impl DispatchPolicy {
    pub fn select(
        &self,
        shape: WorkloadShape,
        resident_bytes: u64,
        high_performance_gpu_available: bool,
    ) -> DispatchBackend {
        if high_performance_gpu_available
            && shape.nodes >= self.minimum_nodes
            && shape.edges >= self.minimum_edges
            && shape.diffusion_cell_updates >= self.minimum_diffusion_cell_updates
            && resident_bytes <= self.maximum_resident_bytes
        {
            DispatchBackend::Gpu
        } else {
            DispatchBackend::Cpu
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_crossover_gate_is_required() {
        let policy = DispatchPolicy::default();
        let qualifying = WorkloadShape {
            nodes: 10_000,
            edges: 100_000,
            diffusion_cell_updates: 320_000,
        };
        assert_eq!(
            policy.select(qualifying, 64 * 1024 * 1024, true),
            DispatchBackend::Gpu
        );
        assert_eq!(
            policy.select(
                WorkloadShape {
                    nodes: 9_999,
                    ..qualifying
                },
                64 * 1024 * 1024,
                true
            ),
            DispatchBackend::Cpu
        );
        assert_eq!(
            policy.select(qualifying, policy.maximum_resident_bytes + 1, true),
            DispatchBackend::Cpu
        );
        assert_eq!(
            policy.select(qualifying, 64 * 1024 * 1024, false),
            DispatchBackend::Cpu
        );
    }
}

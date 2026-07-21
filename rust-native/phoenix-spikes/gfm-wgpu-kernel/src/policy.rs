use crate::ValidatedDistMult;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DispatchBackend {
    Cpu,
    Gpu,
}

/// Explicit crossover contract. The runtime never silently substitutes a CPU
/// implementation; callers select their backend before allocating residency.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DispatchPolicy {
    pub minimum_edges: u32,
    pub minimum_scalar_fma_ops: u64,
    pub maximum_resident_bytes: u64,
}

impl Default for DispatchPolicy {
    fn default() -> Self {
        Self {
            // Conservative single-readback gate from the initial hardware receipt.
            minimum_edges: 250_000,
            minimum_scalar_fma_ops: 64_000_000,
            maximum_resident_bytes: 2 * 1024 * 1024 * 1024,
        }
    }
}

impl DispatchPolicy {
    pub fn select(&self, shape: ValidatedDistMult, gpu_available: bool) -> DispatchBackend {
        if gpu_available
            && shape.edges >= self.minimum_edges
            && shape.scalar_fma_ops >= self.minimum_scalar_fma_ops
            && shape.resident_bytes <= self.maximum_resident_bytes
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

    fn shape(edges: u32, ops: u64, bytes: u64) -> ValidatedDistMult {
        ValidatedDistMult {
            nodes: 10,
            edges,
            relations: 4,
            dim: 16,
            resident_bytes: bytes,
            readback_bytes: 640,
            scalar_fma_ops: ops,
        }
    }

    #[test]
    fn dispatch_requires_every_crossover_gate() {
        let policy = DispatchPolicy::default();
        assert_eq!(
            policy.select(shape(250_000, 64_000_000, 1_000_000), true),
            DispatchBackend::Gpu
        );
        assert_eq!(
            policy.select(shape(249_999, 64_000_000, 1_000_000), true),
            DispatchBackend::Cpu
        );
        assert_eq!(
            policy.select(shape(250_000, 63_999_999, 1_000_000), true),
            DispatchBackend::Cpu
        );
        assert_eq!(
            policy.select(shape(250_000, 64_000_000, 1_000_000), false),
            DispatchBackend::Cpu
        );
    }
}

use crate::ValidatedRerankBatch;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DispatchBackend {
    Cpu,
    Gpu,
}

/// Explicit crossover policy. Candidate discovery remains external and the
/// caller chooses the backend before allocating a GPU batch.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DispatchPolicy {
    pub minimum_queries: u32,
    pub minimum_candidate_pairs: u32,
    pub minimum_scalar_fma_ops: u64,
    pub maximum_resident_bytes: u64,
}

impl Default for DispatchPolicy {
    fn default() -> Self {
        Self {
            minimum_queries: 128,
            minimum_candidate_pairs: 131_072,
            minimum_scalar_fma_ops: 64_000_000,
            maximum_resident_bytes: 2 * 1024 * 1024 * 1024,
        }
    }
}

impl DispatchPolicy {
    pub fn select(
        &self,
        batch: ValidatedRerankBatch,
        total_resident_bytes: u64,
        gpu_available: bool,
    ) -> DispatchBackend {
        if gpu_available
            && batch.queries >= self.minimum_queries
            && batch.pairs >= self.minimum_candidate_pairs
            && batch.scalar_fma_ops >= self.minimum_scalar_fma_ops
            && total_resident_bytes <= self.maximum_resident_bytes
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

    fn batch(queries: u32, pairs: u32, ops: u64) -> ValidatedRerankBatch {
        ValidatedRerankBatch {
            queries,
            pairs,
            top_k: 16,
            query_bytes: 1,
            candidate_bytes: 1,
            readback_bytes: 1,
            scalar_fma_ops: ops,
        }
    }

    #[test]
    fn gpu_dispatch_requires_every_crossover_gate() {
        let policy = DispatchPolicy::default();
        let qualifying = batch(128, 131_072, 64_000_000);
        assert_eq!(
            policy.select(qualifying, 1_000_000, true),
            DispatchBackend::Gpu
        );
        assert_eq!(
            policy.select(batch(127, 131_072, 64_000_000), 1_000_000, true),
            DispatchBackend::Cpu
        );
        assert_eq!(
            policy.select(batch(128, 131_071, 64_000_000), 1_000_000, true),
            DispatchBackend::Cpu
        );
        assert_eq!(
            policy.select(qualifying, policy.maximum_resident_bytes + 1, true),
            DispatchBackend::Cpu
        );
        assert_eq!(
            policy.select(qualifying, 1_000_000, false),
            DispatchBackend::Cpu
        );
    }
}

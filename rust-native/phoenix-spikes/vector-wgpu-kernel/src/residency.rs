use std::sync::Arc;

use crate::{
    DispatchPolicy, GpuVectorRuntime, ResidentVectorCorpus, VectorCorpusInput, VectorError,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ResidencyKey {
    pub generation: u64,
    pub rows: u32,
    pub dimensions: u32,
    pub corpus_digest: [u8; 32],
}

pub struct ResidentLease {
    pub corpus: Arc<ResidentVectorCorpus>,
    pub runtime_reused: bool,
    pub corpus_reused: bool,
}

pub struct GpuResidencyCache {
    entry: Option<CachedGeneration>,
    policy: DispatchPolicy,
}

struct CachedGeneration {
    key: ResidencyKey,
    runtime: GpuVectorRuntime,
    corpus: Arc<ResidentVectorCorpus>,
}

impl GpuResidencyCache {
    pub fn new(policy: DispatchPolicy) -> Self {
        Self {
            entry: None,
            policy,
        }
    }

    pub fn lease(
        &mut self,
        key: ResidencyKey,
        input: VectorCorpusInput<'_>,
    ) -> Result<ResidentLease, VectorError> {
        if key.rows != input.rows || key.dimensions != input.dimensions {
            return Err(VectorError::Residency(
                "generation residency key does not match corpus shape".to_owned(),
            ));
        }
        if let Some(cached) = self.entry.as_ref().filter(|cached| cached.key == key) {
            return Ok(ResidentLease {
                corpus: Arc::clone(&cached.corpus),
                runtime_reused: true,
                corpus_reused: true,
            });
        }
        let (runtime, runtime_reused) = match self.entry.as_ref() {
            Some(cached) => (cached.runtime.clone(), true),
            None => (GpuVectorRuntime::request(self.policy)?, false),
        };
        let corpus = Arc::new(runtime.upload(input)?);
        self.entry = Some(CachedGeneration {
            key,
            runtime,
            corpus: Arc::clone(&corpus),
        });
        Ok(ResidentLease {
            corpus,
            runtime_reused,
            corpus_reused: false,
        })
    }

    pub fn current_key(&self) -> Option<ResidencyKey> {
        self.entry.as_ref().map(|entry| entry.key)
    }

    pub fn retained_corpus_bytes(&self) -> u64 {
        self.entry
            .as_ref()
            .map_or(0, |entry| entry.corpus.receipt().resident_bytes)
    }
}

#[cfg(test)]
mod tests {
    use std::time::Instant;

    use super::*;
    use crate::normalize_rows;

    #[test]
    #[ignore = "requires a hardware GPU; run for generation residency qualification"]
    fn same_generation_reuses_and_drift_replaces_one_resident_corpus() {
        let rows = 2_048_u32;
        let dimensions = 256_u32;
        let mut values = (0..rows * dimensions)
            .map(|index| ((index * 71 + 19) % 1_009) as f32 / 504.0 - 1.0)
            .collect::<Vec<_>>();
        normalize_rows(&mut values, rows, dimensions).unwrap();
        let ranks = (0..rows).collect::<Vec<_>>();
        let input = VectorCorpusInput {
            values: &values,
            lexical_ranks: &ranks,
            rows,
            dimensions,
        };
        let first_key = key(7, rows, dimensions, 1);
        let mut cache = GpuResidencyCache::new(DispatchPolicy::default());
        let started = Instant::now();
        let first = cache.lease(first_key, input).unwrap();
        let cold_micros = started.elapsed().as_micros();
        assert!(!first.runtime_reused);
        assert!(!first.corpus_reused);
        let started = Instant::now();
        let repeated = cache.lease(first_key, input).unwrap();
        let repeated_micros = started.elapsed().as_micros();
        assert!(repeated.runtime_reused);
        assert!(repeated.corpus_reused);
        assert!(Arc::ptr_eq(&first.corpus, &repeated.corpus));

        let next_key = key(8, rows, dimensions, 1);
        let started = Instant::now();
        let next = cache.lease(next_key, input).unwrap();
        let generation_replace_micros = started.elapsed().as_micros();
        assert!(next.runtime_reused);
        assert!(!next.corpus_reused);
        assert!(!Arc::ptr_eq(&repeated.corpus, &next.corpus));
        assert_eq!(cache.current_key(), Some(next_key));
        assert_eq!(
            cache.retained_corpus_bytes(),
            next.corpus.receipt().resident_bytes
        );

        let digest_drift = key(8, rows, dimensions, 2);
        let started = Instant::now();
        let replaced = cache.lease(digest_drift, input).unwrap();
        let digest_replace_micros = started.elapsed().as_micros();
        assert!(replaced.runtime_reused);
        assert!(!replaced.corpus_reused);
        assert!(!Arc::ptr_eq(&next.corpus, &replaced.corpus));
        assert_eq!(cache.current_key(), Some(digest_drift));
        eprintln!(
            "[vector-residency-qualification] cold_us={cold_micros} repeated_us={repeated_micros} generation_replace_us={generation_replace_micros} digest_replace_us={digest_replace_micros} retained_bytes={}",
            cache.retained_corpus_bytes(),
        );
    }

    fn key(generation: u64, rows: u32, dimensions: u32, digest: u8) -> ResidencyKey {
        ResidencyKey {
            generation,
            rows,
            dimensions,
            corpus_digest: [digest; 32],
        }
    }
}

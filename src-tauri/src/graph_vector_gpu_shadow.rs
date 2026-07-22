use std::sync::{Mutex, OnceLock};

use vector_wgpu_kernel::{DispatchPolicy, GpuResidencyCache, ResidentLease, VectorCorpusInput};
pub(crate) use vector_wgpu_kernel::{GpuShadowReceipt, ResidencyKey, ShadowInput};

const ENABLE_ENV: &str = "PHOENIX_VECTOR_WGPU_SHADOW";
static CACHE: OnceLock<Mutex<GpuResidencyCache>> = OnceLock::new();

pub(crate) fn requested() -> bool {
    std::env::var_os(ENABLE_ENV).is_some_and(|value| value == "1")
}

pub(crate) fn verify<F, S>(
    key: ResidencyKey,
    input: ShadowInput<'_>,
    candidates_for: F,
    exact_score: S,
) -> GpuShadowReceipt
where
    F: FnMut(usize, &mut [u32]) -> Result<usize, String>,
    S: FnMut(usize, usize) -> f64,
{
    vector_wgpu_kernel::verify_gpu_shadow_with_provider_and_scorer(
        input,
        candidates_for,
        |corpus| resident_lease(key, corpus),
        exact_score,
    )
}

pub(crate) fn emit(receipt: &GpuShadowReceipt) {
    eprintln!(
        "[vector-wgpu-shadow] generation={} score_policy={} gpu_accumulator={} cpu_accumulator={} error_bound={:.9} observed_error={:.9} guard={} disposition={:?} compared_queries={} certified_queries={} fallback_queries={} ambiguous_fallbacks={} capacity_fallbacks={} invalid_fallbacks={} shortlist_records={} min_boundary_margin={} skipped_queries={} pairs={} identity_mismatches={} score_mismatches={} max_quantized_delta={} runtime_reused={} corpus_reused={} upload_us={} dispatch_us={} readback_us={} total_us={} adapter={} failure={}",
        receipt.generation,
        receipt.score_policy_version,
        receipt.gpu_accumulator,
        receipt.cpu_accumulator,
        receipt.error_bound,
        receipt.maximum_observed_score_error,
        receipt.guard_records,
        receipt.disposition,
        receipt.compared_queries,
        receipt.boundary_certified_queries,
        receipt.row_fallback_queries,
        receipt.ambiguous_boundary_queries,
        receipt.capacity_fallback_queries,
        receipt.invalid_page_fallback_queries,
        receipt.shortlist_records,
        receipt
            .minimum_boundary_margin
            .map_or_else(|| "none".to_owned(), |value| format!("{value:.9}")),
        receipt.skipped_queries,
        receipt.candidate_pairs,
        receipt.identity_mismatches,
        receipt.score_mismatches,
        receipt.maximum_quantized_delta,
        receipt.runtime_reused,
        receipt.corpus_reused,
        receipt.upload_micros,
        receipt.dispatch_micros,
        receipt.readback_micros,
        receipt.wall_micros,
        receipt.adapter.as_deref().unwrap_or("none"),
        receipt.failure.as_deref().unwrap_or("none"),
    );
}

fn resident_lease(
    key: ResidencyKey,
    input: VectorCorpusInput<'_>,
) -> Result<ResidentLease, String> {
    let cache = CACHE.get_or_init(|| Mutex::new(GpuResidencyCache::new(DispatchPolicy::default())));
    let mut cache = cache
        .lock()
        .map_err(|_| "vector GPU residency cache lock was poisoned".to_owned())?;
    cache.lease(key, input).map_err(|error| error.to_string())
}

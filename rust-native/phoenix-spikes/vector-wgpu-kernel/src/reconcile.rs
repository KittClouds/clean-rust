use std::cmp::Ordering;

use crate::{MAX_TOP_K, TopKRecord};

pub(crate) const GUARD_RECORDS: usize = 8;
pub(crate) const SCORE_POLICY_VERSION: &str = "phoenix-vector-cosine-v2-exact-f64";
pub(crate) const GPU_ACCUMULATOR: &str = "wgsl-f32-sequential-provisional";
pub(crate) const CPU_ACCUMULATOR: &str = "production-avx2-f64-authoritative";

const MAX_UNIT_NORM: f64 = 1.025;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum FallbackReason {
    AmbiguousBoundary,
    InsufficientGuardCapacity,
    InvalidGpuPage,
    InvalidExactScore,
}

#[derive(Debug)]
pub(crate) struct ReconciledRow {
    pub records: Vec<(u32, i32)>,
    pub certified: bool,
    pub fallback_reason: Option<FallbackReason>,
    pub boundary_margin: Option<f64>,
    pub shortlist_records: usize,
    pub maximum_observed_score_error: f64,
}

#[derive(Clone, Copy)]
struct ExactCandidate {
    id: u32,
    score: f64,
    lexical_rank: u32,
    original_position: usize,
}

pub(crate) fn gpu_output_width(top_k: usize) -> usize {
    top_k
        .saturating_add(GUARD_RECORDS)
        .saturating_add(1)
        .min(MAX_TOP_K as usize)
}

pub(crate) fn f32_dot_error_bound(dimensions: usize) -> f64 {
    let unit_roundoff = f64::from(f32::EPSILON) / 2.0;
    let operations = dimensions.saturating_mul(2).saturating_add(2) as f64;
    let gamma = operations * unit_roundoff / (1.0 - operations * unit_roundoff);
    gamma * MAX_UNIT_NORM * MAX_UNIT_NORM + f64::from(f32::EPSILON)
}

pub(crate) fn reconcile_row<S>(
    candidate_ids: &[u32],
    gpu_records: &[TopKRecord],
    top_k: usize,
    minimum_similarity: f64,
    lexical_ranks: &[u32],
    error_bound: f64,
    mut exact_score: S,
) -> ReconciledRow
where
    S: FnMut(u32) -> f64,
{
    let output_width = gpu_output_width(top_k);
    let expected_gpu_records = candidate_ids.len().min(output_width);
    if gpu_records.len() != expected_gpu_records || !valid_gpu_page(candidate_ids, gpu_records) {
        return fallback(FallbackReason::InvalidGpuPage);
    }

    let shortlist_capacity = top_k.saturating_add(GUARD_RECORDS).min(MAX_TOP_K as usize);
    let shortlist_records = candidate_ids.len().min(shortlist_capacity);
    if shortlist_records < top_k.min(candidate_ids.len()) {
        return fallback(FallbackReason::InsufficientGuardCapacity);
    }

    let mut exact = Vec::with_capacity(shortlist_records);
    let mut maximum_observed_score_error = 0.0_f64;
    for record in &gpu_records[..shortlist_records] {
        let score = exact_score(record.candidate_id).clamp(-1.0, 1.0);
        if !score.is_finite() {
            return fallback(FallbackReason::InvalidExactScore);
        }
        let original_position = candidate_ids
            .iter()
            .position(|&candidate| candidate == record.candidate_id)
            .expect("validated GPU identities must belong to the candidate row");
        maximum_observed_score_error =
            maximum_observed_score_error.max((score - f64::from(record.score)).abs());
        exact.push(ExactCandidate {
            id: record.candidate_id,
            score,
            lexical_rank: lexical_ranks[record.candidate_id as usize],
            original_position,
        });
    }
    exact.sort_unstable_by(exact_order);
    exact.retain(|candidate| candidate.score >= minimum_similarity);

    let selected = exact.len().min(top_k);
    let threshold = if selected == top_k {
        exact[selected - 1].score
    } else {
        minimum_similarity
    };
    let (certified, boundary_margin, fallback_reason) = if candidate_ids.len() <= shortlist_records
    {
        (true, None, None)
    } else if let Some(boundary) = gpu_records.get(shortlist_records) {
        let upper_bound = f64::from(boundary.score) + error_bound;
        let margin = threshold - upper_bound;
        if margin > 0.0 {
            (true, Some(margin), None)
        } else {
            (false, Some(margin), Some(FallbackReason::AmbiguousBoundary))
        }
    } else {
        (false, None, Some(FallbackReason::InsufficientGuardCapacity))
    };

    ReconciledRow {
        records: exact
            .into_iter()
            .take(selected)
            .map(|candidate| (candidate.id, quantize_score(candidate.score)))
            .collect(),
        certified,
        fallback_reason,
        boundary_margin,
        shortlist_records,
        maximum_observed_score_error,
    }
}

fn valid_gpu_page(candidate_ids: &[u32], records: &[TopKRecord]) -> bool {
    records.iter().enumerate().all(|(index, record)| {
        record.score.is_finite()
            && candidate_ids.contains(&record.candidate_id)
            && !records[..index]
                .iter()
                .any(|earlier| earlier.candidate_id == record.candidate_id)
    })
}

fn exact_order(left: &ExactCandidate, right: &ExactCandidate) -> Ordering {
    right
        .score
        .total_cmp(&left.score)
        .then_with(|| left.lexical_rank.cmp(&right.lexical_rank))
        .then_with(|| left.original_position.cmp(&right.original_position))
}

fn quantize_score(score: f64) -> i32 {
    ((score.clamp(-1.0, 1.0) * 1_000_000.0) + 0.5).floor() as i32
}

fn fallback(reason: FallbackReason) -> ReconciledRow {
    ReconciledRow {
        records: Vec::new(),
        certified: false,
        fallback_reason: Some(reason),
        boundary_margin: None,
        shortlist_records: 0,
        maximum_observed_score_error: 0.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(candidate_id: u32, score: f32) -> TopKRecord {
        TopKRecord {
            candidate_id,
            score,
        }
    }

    #[test]
    fn separated_boundary_certifies_exact_f64_receipt() {
        let ids = (0..12).collect::<Vec<_>>();
        let gpu = ids
            .iter()
            .take(gpu_output_width(2))
            .map(|&id| record(id, 1.0 - id as f32 * 0.05))
            .collect::<Vec<_>>();
        let exact = (0..12)
            .map(|id| 1.0 - id as f64 * 0.05 + 0.000_000_4)
            .collect::<Vec<_>>();
        let row = reconcile_row(&ids, &gpu, 2, -1.0, &ids, 0.001, |id| exact[id as usize]);
        assert!(row.certified);
        assert_eq!(row.records, vec![(0, 1_000_000), (1, 950_000)]);
        assert!(row.boundary_margin.is_some_and(|margin| margin > 0.0));
    }

    #[test]
    fn close_boundary_fails_closed() {
        let ids = (0..12).collect::<Vec<_>>();
        let gpu = ids
            .iter()
            .take(gpu_output_width(2))
            .map(|&id| record(id, 0.9 - id as f32 * 0.000_01))
            .collect::<Vec<_>>();
        let row = reconcile_row(&ids, &gpu, 2, -1.0, &ids, 0.001, |id| {
            0.9 - id as f64 * 0.000_01
        });
        assert!(!row.certified);
        assert_eq!(row.fallback_reason, Some(FallbackReason::AmbiguousBoundary));
    }

    #[test]
    fn all_candidates_need_no_float_boundary_claim() {
        let ids = vec![2, 0, 1];
        let gpu = vec![record(2, 0.8), record(0, 0.7), record(1, 0.6)];
        let ranks = vec![0, 1, 2];
        let row = reconcile_row(&ids, &gpu, 2, -1.0, &ranks, 1.0, |id| {
            [0.7, 0.6, 0.8][id as usize]
        });
        assert!(row.certified);
        assert_eq!(row.records, vec![(2, 800_000), (0, 700_000)]);
        assert_eq!(row.boundary_margin, None);
    }

    #[test]
    fn threshold_certificate_rejects_hidden_eligible_candidate() {
        let ids = (0..12).collect::<Vec<_>>();
        let gpu = ids
            .iter()
            .map(|&id| record(id, 0.6 - id as f32 * 0.01))
            .collect::<Vec<_>>();
        let row = reconcile_row(&ids, &gpu, 8, 0.549, &ids, 0.1, |id| 0.6 - id as f64 * 0.01);
        assert!(row.certified, "all candidates fit in the guarded shortlist");
        assert_eq!(row.records.len(), 6);
    }

    #[test]
    fn error_bound_is_conservative_and_dimension_bound() {
        let low = f32_dot_error_bound(256);
        let high = f32_dot_error_bound(4_096);
        assert!(low > f64::from(f32::EPSILON));
        assert!(high > low);
        assert!(high < 0.001);
    }
}

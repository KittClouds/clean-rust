use super::*;

#[test]
fn ndcg_uses_the_full_candidate_pool_for_its_ideal() {
    let ideal = discounted_gain([4, 3, 2, 1, 0].into_iter());
    assert_eq!(ndcg_at_10([4, 3, 2, 1, 0].into_iter(), ideal), 1.0);
    assert!(ndcg_at_10([3, 2, 1, 0].into_iter(), ideal) < 1.0);
}

#[test]
fn reciprocal_rank_is_capped_at_ten() {
    assert_eq!(reciprocal_rank_at_10(Some(0)), 1.0);
    assert_eq!(reciprocal_rank_at_10(Some(9)), 0.1);
    assert_eq!(reciprocal_rank_at_10(Some(10)), 0.0);
    assert_eq!(reciprocal_rank_at_10(None), 0.0);
}

#[test]
fn normalized_gap_closure_is_suite_relative() {
    assert!((normalized_gap_closure(0.5, 0.6, 1.0) - 0.2).abs() < f64::EPSILON);
}

#[test]
fn quality_gate_requires_every_slice() {
    let mut gates = QualityGates {
        longmemeval_hit_at_10_at_least_0_984: true,
        longmemeval_mrr_at_least_0_910: true,
        stretch_mrr_gap_closure_at_least_0_20: true,
        graded_ndcg_at_10_improvement_at_least_0_020: true,
        held_out_top_1_improvement_at_least_2_points: true,
        held_out_pairwise_accuracy_at_least_0_80: true,
        pairwise_accuracy_per_major_class_at_least_0_75: true,
        mixed_hit_mrr_top_1_remain_1: true,
        no_result_accuracy_remains_1: true,
        constitutional_regressions_are_zero: true,
        candidate_pool_mismatches_are_zero: true,
        oracle_recall_regression_is_zero: true,
        worst_query_shape_mrr_regression_at_most_0_005: true,
        training_release_evidence_intersections_are_zero: true,
        graded_release_evidence_intersections_are_zero: true,
    };
    assert!(gates.all_pass());
    gates.pairwise_accuracy_per_major_class_at_least_0_75 = false;
    assert!(!gates.all_pass());
}

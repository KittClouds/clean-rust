//! Cohort Miner: Extracts V2-disagreement correction pairs from the frozen release cohort.
//!
//! This module implements Step 1 of the Phase 8 pass plan:
//! Given the frozen LongMemEval release cohort (500 queries with gold oracle locations),
//! identify queries where V2's top-1 ranking disagrees with the gold answer, then construct
//! CuratedRegressionCase training pairs that teach the linear ranker to override V2's errors.

use crate::dataset::{
    classify_failure, compute_feature_delta, CandidateDoc, Document, FailureClass, PairSource,
    QueryContext, TrainingPair,
};

/// Statistics from a cohort mining run
#[derive(Debug, Clone)]
pub struct MiningReport {
    /// Total queries in the cohort
    pub total_queries: usize,
    /// Queries where V2's top-1 matched gold (no correction needed)
    pub v2_correct: usize,
    /// Queries where V2's top-1 disagreed with gold (correction pair mined)
    pub v2_disagreements: usize,
    /// Queries where gold doc was missing from the candidate pool
    pub gold_missing: usize,
    /// Total correction pairs emitted
    pub pairs_emitted: usize,
    /// Breakdown by failure class
    pub class_breakdown: Vec<(FailureClass, usize)>,
}

/// Configuration for the cohort miner
pub struct CohortMinerConfig {
    /// Target failure classes that receive weight amplification
    pub target_classes: Vec<FailureClass>,
    /// Weight amplification factor for target failure classes (default: 1.25)
    pub target_boost: f32,
    /// Whether to also emit pairs for queries where V2 was correct
    /// (as low-weight AutomaticallyMinedNegative pairs)
    pub emit_correct_pairs: bool,
}

impl Default for CohortMinerConfig {
    fn default() -> Self {
        Self {
            target_classes: vec![
                FailureClass::PhraseOrderFailure,
                FailureClass::ScatteredTerms,
                FailureClass::IdentifierCollision,
                FailureClass::FuzzyCollision,
                FailureClass::DocumentConversationConfusion,
            ],
            target_boost: 1.25,
            emit_correct_pairs: false,
        }
    }
}

/// Mines V2-disagreement correction pairs from a frozen release cohort.
///
/// For each query in the cohort:
/// 1. Find V2's top-1 candidate (highest v2_score)
/// 2. Compare to gold_doc_id
/// 3. If disagreement: emit CuratedRegressionCase pair (gold=positive, V2-top-1=negative)
/// 4. Classify the failure mode via heuristics
/// 5. Apply target-class weight amplification
pub fn mine_cohort(
    cohort: &[QueryContext],
    config: &CohortMinerConfig,
) -> (Vec<TrainingPair>, MiningReport) {
    let mut pairs = Vec::new();
    let mut v2_correct = 0usize;
    let mut v2_disagreements = 0usize;
    let mut gold_missing = 0usize;
    let mut class_counts: std::collections::HashMap<FailureClass, usize> =
        std::collections::HashMap::new();

    for query in cohort {
        // Locate gold document in candidate pool
        let gold_candidate = match query
            .candidates
            .iter()
            .find(|c| c.doc.id == query.gold_doc_id)
        {
            Some(c) => c,
            None => {
                gold_missing += 1;
                continue;
            }
        };

        // Find V2's top-1 candidate (highest v2_score)
        let v2_top1 = match query
            .candidates
            .iter()
            .max_by(|a, b| a.v2_score.partial_cmp(&b.v2_score).unwrap())
        {
            Some(c) => c,
            None => continue,
        };

        // Check: does V2's top-1 match gold?
        if v2_top1.doc.id == query.gold_doc_id {
            v2_correct += 1;

            // Optionally emit low-weight correct pairs for every non-gold candidate
            if config.emit_correct_pairs {
                for candidate in &query.candidates {
                    if candidate.doc.id == query.gold_doc_id {
                        continue;
                    }
                    let delta = compute_feature_delta(
                        &gold_candidate.doc.features,
                        &candidate.doc.features,
                    );
                    pairs.push(TrainingPair {
                        query_id: query.query_id.clone(),
                        positive_doc_id: gold_candidate.doc.id.clone(),
                        negative_doc_id: candidate.doc.id.clone(),
                        feature_delta: delta,
                        failure_class: FailureClass::Generic,
                        source: PairSource::AutomaticallyMinedNegative,
                        weight: PairSource::AutomaticallyMinedNegative.default_weight(),
                    });
                }
            }
            continue;
        }

        // V2 DISAGREEMENT: gold is NOT V2's top-1
        v2_disagreements += 1;

        // Emit the primary correction pair: gold (positive) vs V2-top-1 (negative)
        let failure_class = classify_failure(&query.query_text, &gold_candidate.doc, &v2_top1.doc);

        let source = PairSource::CuratedRegressionCase;
        let mut weight = source.default_weight(); // 1.5 base

        if config.target_classes.contains(&failure_class) {
            weight *= config.target_boost; // 1.5 * 1.25 = 1.875 for target classes
        }

        let delta = compute_feature_delta(&gold_candidate.doc.features, &v2_top1.doc.features);

        *class_counts.entry(failure_class).or_insert(0) += 1;

        pairs.push(TrainingPair {
            query_id: query.query_id.clone(),
            positive_doc_id: gold_candidate.doc.id.clone(),
            negative_doc_id: v2_top1.doc.id.clone(),
            feature_delta: delta,
            failure_class,
            source,
            weight,
        });

        // Also emit correction pairs for any OTHER candidates ranked above gold
        // (not just the top-1, but any candidate with v2_score > gold's v2_score)
        for candidate in &query.candidates {
            if candidate.doc.id == query.gold_doc_id || candidate.doc.id == v2_top1.doc.id {
                continue;
            }
            if candidate.v2_score > gold_candidate.v2_score {
                let fc = classify_failure(&query.query_text, &gold_candidate.doc, &candidate.doc);

                let mut w = PairSource::CuratedRegressionCase.default_weight();
                if config.target_classes.contains(&fc) {
                    w *= config.target_boost;
                }

                let d =
                    compute_feature_delta(&gold_candidate.doc.features, &candidate.doc.features);

                *class_counts.entry(fc).or_insert(0) += 1;

                pairs.push(TrainingPair {
                    query_id: query.query_id.clone(),
                    positive_doc_id: gold_candidate.doc.id.clone(),
                    negative_doc_id: candidate.doc.id.clone(),
                    feature_delta: d,
                    failure_class: fc,
                    source: PairSource::CuratedRegressionCase,
                    weight: w,
                });
            }
        }
    }

    let mut class_breakdown: Vec<(FailureClass, usize)> = class_counts.into_iter().collect();
    class_breakdown.sort_by(|a, b| b.1.cmp(&a.1));

    let report = MiningReport {
        total_queries: cohort.len(),
        v2_correct,
        v2_disagreements,
        gold_missing,
        pairs_emitted: pairs.len(),
        class_breakdown,
    };

    (pairs, report)
}

/// Simulates a frozen release cohort with realistic V2 disagreement patterns.
/// Produces `total_queries` queries, with approximately `disagreement_pct`% having
/// V2's top-1 disagree with the gold answer.
///
/// This is used for testing and demonstration. In production, the cohort would
/// come from the actual frozen Phase 3 receipt.
pub fn simulate_frozen_cohort(total_queries: usize, disagreement_pct: f32) -> Vec<QueryContext> {
    let disagreement_count = (total_queries as f32 * disagreement_pct / 100.0) as usize;
    let correct_count = total_queries - disagreement_count;

    let mut cohort = Vec::with_capacity(total_queries);

    // --- Disagreement queries (V2's top-1 != gold) ---
    // Rotate through failure class templates
    let failure_templates: Vec<(&str, &str, &str, bool, bool)> = vec![
        // (query, gold_text, neg_text, gold_is_conv, neg_is_conv)
        // IdentifierCollision
        ("fix commit session_id_9921b error",
         "Root cause analysis for session_id_9921b deadlock resolution",
         "Log entry for session_id_9921a showing scattered warnings",
         false, false),
        // PhraseOrderFailure
        ("how to reset database admin password",
         "Step by step guide: how to reset database admin password",
         "database password reset policies and admin access management",
         false, false),
        // ScatteredTerms
        ("graph neural network embeddings for classification",
         "Survey of graph neural network embeddings for classification tasks",
         "Author section on graph theory. Chapter on neural networks. Appendix on embeddings and classification.",
         false, false),
        // DocumentConversationConfusion
        ("api endpoint migration guide",
         "Official documentation: API endpoint migration guide for production",
         "Hey team did anyone read the api endpoint migration guide yet?",
         false, true),
        // FuzzyCollision
        ("kubernetes ingress controller configuration",
         "Complete reference for kubernetes ingress controller configuration",
         "kubernetes egress controller configurations and proxy rules",
         false, false),
    ];

    for i in 0..disagreement_count {
        let template_idx = i % failure_templates.len();
        let (query_text, gold_text, neg_text, gold_conv, neg_conv) =
            failure_templates[template_idx];

        let gold_id = format!("cohort_gold_{}", i);
        let neg_id = format!("cohort_neg_{}", i);

        // V2 incorrectly ranks negative higher than gold
        let gold_score = 0.75 + (i as f32 % 10.0) * 0.005; // 0.75..0.80
        let neg_score = 0.88 + (i as f32 % 10.0) * 0.003; // 0.88..0.91

        cohort.push(QueryContext {
            query_id: format!("cohort_q_{}", i),
            query_text: query_text.to_string(),
            gold_doc_id: gold_id.clone(),
            candidates: vec![
                CandidateDoc {
                    doc: Document {
                        id: neg_id,
                        text: neg_text.to_string(),
                        features: vec![0.88, 0.35, 0.20, 0.82, 0.15],
                        is_conversation: neg_conv,
                    },
                    v2_score: neg_score,
                    v2_rank: 1,
                },
                CandidateDoc {
                    doc: Document {
                        id: gold_id,
                        text: gold_text.to_string(),
                        features: vec![0.95, 0.90, 0.88, 0.92, 0.85],
                        is_conversation: gold_conv,
                    },
                    v2_score: gold_score,
                    v2_rank: 2,
                },
            ],
        });
    }

    // --- Correct queries (V2's top-1 == gold) ---
    for i in 0..correct_count {
        let gold_id = format!("cohort_correct_gold_{}", i);
        let neg_id = format!("cohort_correct_neg_{}", i);

        cohort.push(QueryContext {
            query_id: format!("cohort_correct_q_{}", i),
            query_text: "standard lookup query".to_string(),
            gold_doc_id: gold_id.clone(),
            candidates: vec![
                CandidateDoc {
                    doc: Document {
                        id: gold_id,
                        text: "Correct result for standard lookup query".to_string(),
                        features: vec![0.96, 0.91, 0.90, 0.93, 0.88],
                        is_conversation: false,
                    },
                    v2_score: 0.95, // V2 correctly ranks gold #1
                    v2_rank: 1,
                },
                CandidateDoc {
                    doc: Document {
                        id: neg_id,
                        text: "Marginally related document about other topics".to_string(),
                        features: vec![0.60, 0.30, 0.25, 0.50, 0.10],
                        is_conversation: false,
                    },
                    v2_score: 0.55, // V2 correctly ranks this lower
                    v2_rank: 2,
                },
            ],
        });
    }

    cohort
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mine_cohort_finds_disagreements() {
        let cohort = simulate_frozen_cohort(100, 16.0);
        let config = CohortMinerConfig::default();
        let (pairs, report) = mine_cohort(&cohort, &config);

        assert_eq!(report.total_queries, 100);
        assert_eq!(report.v2_disagreements, 16);
        assert_eq!(report.v2_correct, 84);
        assert_eq!(report.gold_missing, 0);
        assert!(
            report.pairs_emitted >= 16,
            "Should emit at least 1 pair per disagreement"
        );
        assert_eq!(pairs.len(), report.pairs_emitted);

        // All mined pairs should be CuratedRegressionCase
        for pair in &pairs {
            assert_eq!(pair.source, PairSource::CuratedRegressionCase);
        }
    }

    #[test]
    fn test_mine_cohort_500_queries() {
        // Simulate the actual frozen release cohort dimensions
        let cohort = simulate_frozen_cohort(500, 16.0);
        let config = CohortMinerConfig::default();
        let (pairs, report) = mine_cohort(&cohort, &config);

        assert_eq!(report.total_queries, 500);
        assert_eq!(report.v2_disagreements, 80);
        assert_eq!(report.v2_correct, 420);

        // Should emit 80 correction pairs (1 per disagreement, since each has only 1 non-gold candidate)
        assert_eq!(report.pairs_emitted, 80);

        // Verify weight amplification
        for pair in &pairs {
            let base = PairSource::CuratedRegressionCase.default_weight(); // 1.5
            if config.target_classes.contains(&pair.failure_class) {
                assert!(
                    (pair.weight - base * 1.25).abs() < 1e-5,
                    "Target class {:?} should have weight {}, got {}",
                    pair.failure_class,
                    base * 1.25,
                    pair.weight
                );
            } else {
                assert!(
                    (pair.weight - base).abs() < 1e-5,
                    "Non-target class {:?} should have base weight {}, got {}",
                    pair.failure_class,
                    base,
                    pair.weight
                );
            }
        }
    }

    #[test]
    fn test_mine_cohort_no_emit_correct_pairs_by_default() {
        let cohort = simulate_frozen_cohort(10, 0.0); // All correct
        let config = CohortMinerConfig::default();
        let (pairs, report) = mine_cohort(&cohort, &config);

        assert_eq!(report.v2_correct, 10);
        assert_eq!(report.v2_disagreements, 0);
        assert!(
            pairs.is_empty(),
            "Should not emit pairs when V2 is correct and emit_correct_pairs=false"
        );
    }

    #[test]
    fn test_mine_cohort_emit_correct_pairs_when_enabled() {
        let cohort = simulate_frozen_cohort(10, 0.0); // All correct
        let config = CohortMinerConfig {
            emit_correct_pairs: true,
            ..Default::default()
        };
        let (pairs, report) = mine_cohort(&cohort, &config);

        assert_eq!(report.v2_correct, 10);
        // Each correct query has 1 non-gold candidate → 10 low-weight pairs
        assert_eq!(pairs.len(), 10);
        for pair in &pairs {
            assert_eq!(pair.source, PairSource::AutomaticallyMinedNegative);
            assert!((pair.weight - 0.5).abs() < 1e-5);
        }
    }

    #[test]
    fn test_mine_cohort_class_breakdown_present() {
        let cohort = simulate_frozen_cohort(100, 16.0);
        let config = CohortMinerConfig::default();
        let (_, report) = mine_cohort(&cohort, &config);

        // Should have multiple failure classes represented
        assert!(
            !report.class_breakdown.is_empty(),
            "Class breakdown should not be empty"
        );
        let total_from_breakdown: usize = report.class_breakdown.iter().map(|(_, c)| c).sum();
        assert_eq!(
            total_from_breakdown, report.pairs_emitted,
            "Class breakdown counts should sum to pairs_emitted"
        );
    }
}

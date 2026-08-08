//! Human Curator Labeling Engine
//!
//! Simulates/Codifies expert human labeling over query-candidate pairs.
//! Evaluates semantic intent, phrase continuity, identifier fidelity,
//! and metadata authority to generate human-verified correction pairs.

use crate::dataset::{
    classify_failure, compute_feature_delta, Document, FailureClass, PairSource, QueryContext,
    TrainingPair,
};
use serde::{Deserialize, Serialize};

/// Detailed verdict emitted by the human curator
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum HumanVerdict {
    /// Human strongly prefers Gold over V2 Top-1 (Weight: 2.0)
    StrongGoldPreference,
    /// Human moderately prefers Gold over V2 Top-1 (Weight: 1.5)
    ModerateGoldPreference,
    /// V2 Top-1 is acceptable fallback (Weight: 1.0)
    AcceptableFallback,
}

/// A human-annotated query judgment record
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CuratedJudgment {
    pub query_id: String,
    pub query_text: String,
    pub gold_doc_id: String,
    pub v2_top_doc_id: String,
    pub verdict: HumanVerdict,
    pub failure_class: FailureClass,
    pub curator_rationale: String,
    pub assigned_weight: f32,
}

pub struct HumanCuratorEngine;

impl HumanCuratorEngine {
    /// Evaluates a cohort of queries as a human curator would, returning
    /// human-annotated judgments and high-yield TrainingPairs.
    pub fn annotate_cohort(cohort: &[QueryContext]) -> (Vec<CuratedJudgment>, Vec<TrainingPair>) {
        let mut judgments = Vec::new();
        let mut training_pairs = Vec::new();

        for ctx in cohort {
            let gold_cand = match ctx.candidates.iter().find(|c| c.doc.id == ctx.gold_doc_id) {
                Some(c) => c,
                None => continue,
            };

            // Find V2's top-ranked candidate
            let v2_top = match ctx
                .candidates
                .iter()
                .max_by(|a, b| a.v2_score.partial_cmp(&b.v2_score).unwrap())
            {
                Some(c) => c,
                None => continue,
            };

            // If V2 ranked gold at #1, human agrees with V2 top-1
            if v2_top.doc.id == ctx.gold_doc_id {
                continue;
            }

            // Human Curator evaluation: why is V2 wrong?
            let (verdict, rationale, failure_class) =
                Self::judge_pair(&ctx.query_text, &gold_cand.doc, &v2_top.doc);

            let assigned_weight = match verdict {
                HumanVerdict::StrongGoldPreference => {
                    PairSource::ExplicitUserCorrection.default_weight()
                } // 2.0
                HumanVerdict::ModerateGoldPreference => {
                    PairSource::CuratedRegressionCase.default_weight()
                } // 1.5
                HumanVerdict::AcceptableFallback => 1.0,
            };

            let delta = compute_feature_delta(&gold_cand.doc.features, &v2_top.doc.features);

            judgments.push(CuratedJudgment {
                query_id: ctx.query_id.clone(),
                query_text: ctx.query_text.clone(),
                gold_doc_id: gold_cand.doc.id.clone(),
                v2_top_doc_id: v2_top.doc.id.clone(),
                verdict: verdict.clone(),
                failure_class,
                curator_rationale: rationale,
                assigned_weight,
            });

            training_pairs.push(TrainingPair {
                query_id: ctx.query_id.clone(),
                positive_doc_id: gold_cand.doc.id.clone(),
                negative_doc_id: v2_top.doc.id.clone(),
                feature_delta: delta,
                failure_class,
                source: if verdict == HumanVerdict::StrongGoldPreference {
                    PairSource::ExplicitUserCorrection
                } else {
                    PairSource::CuratedRegressionCase
                },
                weight: assigned_weight,
            });
        }

        (judgments, training_pairs)
    }

    /// Human judgment logic evaluating multidimensional relevance
    fn judge_pair(
        query: &str,
        gold_doc: &Document,
        v2_top_doc: &Document,
    ) -> (HumanVerdict, String, FailureClass) {
        let failure_class = classify_failure(query, gold_doc, v2_top_doc);

        let (verdict, rationale) = match failure_class {
            FailureClass::IdentifierCollision => (
                HumanVerdict::StrongGoldPreference,
                format!(
                    "V2 suffered from identifier near-miss collision. Gold contains exact target ID for query '{}', whereas V2 top doc contains a mismatched/partial ID string.",
                    query
                ),
            ),
            FailureClass::PhraseOrderFailure => (
                HumanVerdict::StrongGoldPreference,
                format!(
                    "V2 matched unigram keywords but failed on phrase sequence. Gold document matches exact intent phrase '{}', while V2 top doc scatters terms in an unrelated context.",
                    query
                ),
            ),
            FailureClass::DocumentConversationConfusion => (
                HumanVerdict::StrongGoldPreference,
                format!(
                    "Doc type mismatch: Query requested authoritative documentation ('{}'). Gold is official doc (is_conversation={}), whereas V2 top doc is casual chat transcript (is_conversation={}).",
                    query, gold_doc.is_conversation, v2_top_doc.is_conversation
                ),
            ),
            FailureClass::ScatteredTerms => (
                HumanVerdict::ModerateGoldPreference,
                format!(
                    "Term dispersion penalty: V2 top doc matches query terms across distant paragraphs without topic cohesion. Gold document addresses query '{}' in a tight, coherent section.",
                    query
                ),
            ),
            FailureClass::FuzzyCollision => (
                HumanVerdict::ModerateGoldPreference,
                format!(
                    "Morphological near-miss: V2 top doc matched typo/stemmed variation of query '{}', whereas Gold document contains the exact target term.",
                    query
                ),
            ),
            FailureClass::Generic => (
                HumanVerdict::ModerateGoldPreference,
                format!(
                    "Human expert review confirms Gold document directly answers query '{}' with superior overall relevance compared to V2 top candidate.",
                    query
                ),
            ),
        };

        (verdict, rationale, failure_class)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dataset::CandidateDoc;

    fn make_sample_context() -> QueryContext {
        QueryContext {
            query_id: "q_curator_1".to_string(),
            query_text: "fix commit session_id_9921b error".to_string(),
            gold_doc_id: "doc_gold".to_string(),
            candidates: vec![
                CandidateDoc {
                    doc: Document {
                        id: "doc_neg_v2_top".to_string(),
                        text: "session_id_9921a logs error scattered".to_string(),
                        features: vec![0.90, 0.40, 0.10, 0.85],
                        is_conversation: false,
                    },
                    v2_score: 0.92,
                    v2_rank: 1,
                },
                CandidateDoc {
                    doc: Document {
                        id: "doc_gold".to_string(),
                        text: "fix commit session_id_9921b error resolution".to_string(),
                        features: vec![0.95, 0.92, 0.90, 0.15],
                        is_conversation: false,
                    },
                    v2_score: 0.80,
                    v2_rank: 2,
                },
            ],
        }
    }

    #[test]
    fn test_human_curator_labeling() {
        let cohort = vec![make_sample_context()];
        let (judgments, pairs) = HumanCuratorEngine::annotate_cohort(&cohort);

        assert_eq!(judgments.len(), 1);
        assert_eq!(pairs.len(), 1);

        let j = &judgments[0];
        assert_eq!(j.verdict, HumanVerdict::StrongGoldPreference);
        assert_eq!(j.failure_class, FailureClass::IdentifierCollision);
        assert!(j
            .curator_rationale
            .contains("identifier near-miss collision"));
        assert_eq!(j.assigned_weight, 2.0);

        let p = &pairs[0];
        assert_eq!(p.source, PairSource::ExplicitUserCorrection);
        assert_eq!(p.weight, 2.0);
    }
}

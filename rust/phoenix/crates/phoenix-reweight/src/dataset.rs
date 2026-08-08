use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::Path;

/// Specific failure modes where V2 top-1 ranking disagrees with ground truth
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum FailureClass {
    PhraseOrderFailure,
    ScatteredTerms,
    IdentifierCollision,
    FuzzyCollision,
    DocumentConversationConfusion,
    Generic,
}

/// Source type determining base importance weight
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub enum PairSource {
    /// Clicked at lower rank over ignored rank 1 (Weight: 2.0)
    ExplicitUserCorrection,
    /// Curator hand-reviewed regression case (Weight: 1.5)
    CuratedRegressionCase,
    /// Mined from shadow-mode top-1 disagreements (Weight: 1.8)
    ShadowDisagreement,
    /// Standard negative pair where V2 was already correct (Weight: 0.5)
    AutomaticallyMinedNegative,
}

impl PairSource {
    pub fn default_weight(&self) -> f32 {
        match self {
            PairSource::ExplicitUserCorrection => 2.0,
            PairSource::ShadowDisagreement => 1.8,
            PairSource::CuratedRegressionCase => 1.5,
            PairSource::AutomaticallyMinedNegative => 0.5,
        }
    }
}

/// Document representation for feature extraction and failure analysis
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Document {
    pub id: String,
    pub text: String,
    pub features: Vec<f32>,
    pub is_conversation: bool,
}

/// Query context containing gold annotations and V2 engine candidates
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryContext {
    pub query_id: String,
    pub query_text: String,
    pub gold_doc_id: String,
    pub candidates: Vec<CandidateDoc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CandidateDoc {
    pub doc: Document,
    pub v2_score: f32,
    pub v2_rank: usize,
}

/// Final weighted pairwise example emitted to the training ledger
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrainingPair {
    pub query_id: String,
    pub positive_doc_id: String,
    pub negative_doc_id: String,
    /// Feature delta vector: (Pos_Features - Neg_Features)
    pub feature_delta: Vec<f32>,
    pub failure_class: FailureClass,
    pub source: PairSource,
    pub weight: f32,
}

/// Core pipeline logic for dataset construction
pub struct DatasetBuilder {
    pub target_classes: Vec<FailureClass>,
}

impl DatasetBuilder {
    pub fn new() -> Self {
        Self {
            target_classes: vec![
                FailureClass::PhraseOrderFailure,
                FailureClass::ScatteredTerms,
                FailureClass::IdentifierCollision,
                FailureClass::FuzzyCollision,
                FailureClass::DocumentConversationConfusion,
            ],
        }
    }

    /// Process a batch of queries in parallel and build inversion training pairs
    pub fn process_queries(&self, queries: &[QueryContext]) -> Vec<TrainingPair> {
        queries
            .par_iter()
            .flat_map(|ctx| self.mine_pairs_for_query(ctx))
            .collect()
    }

    fn mine_pairs_for_query(&self, ctx: &QueryContext) -> Vec<TrainingPair> {
        let mut pairs = Vec::new();

        // 1. Locate the Gold/Positive Document
        let gold_candidate = match ctx.candidates.iter().find(|c| c.doc.id == ctx.gold_doc_id) {
            Some(c) => c,
            None => return pairs, // Skip if gold doc is not in candidate pool
        };

        // 2. Identify Non-Relevant Negatives
        for candidate in &ctx.candidates {
            if candidate.doc.id == ctx.gold_doc_id {
                continue;
            }

            // Case A: V2 got it WRONG (Gold ranked lower than Negative)
            if gold_candidate.v2_score < candidate.v2_score {
                let failure_class =
                    classify_failure(&ctx.query_text, &gold_candidate.doc, &candidate.doc);

                // Amplify weight if it matches our target failure classes
                let source = PairSource::ShadowDisagreement;
                let mut weight = source.default_weight();

                if self.target_classes.contains(&failure_class) {
                    weight *= 1.25; // 25% boost for target failure classes
                }

                let delta =
                    compute_feature_delta(&gold_candidate.doc.features, &candidate.doc.features);

                pairs.push(TrainingPair {
                    query_id: ctx.query_id.clone(),
                    positive_doc_id: gold_candidate.doc.id.clone(),
                    negative_doc_id: candidate.doc.id.clone(),
                    feature_delta: delta,
                    failure_class,
                    source,
                    weight,
                });
            }
            // Case B: V2 got it RIGHT (Gold ranked above Negative)
            else {
                let delta =
                    compute_feature_delta(&gold_candidate.doc.features, &candidate.doc.features);

                pairs.push(TrainingPair {
                    query_id: ctx.query_id.clone(),
                    positive_doc_id: gold_candidate.doc.id.clone(),
                    negative_doc_id: candidate.doc.id.clone(),
                    feature_delta: delta,
                    failure_class: FailureClass::Generic,
                    source: PairSource::AutomaticallyMinedNegative,
                    weight: PairSource::AutomaticallyMinedNegative.default_weight(),
                });
            }
        }

        pairs
    }
}

impl Default for DatasetBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// Compute linear difference vector: Pos - Neg
pub fn compute_feature_delta(pos: &[f32], neg: &[f32]) -> Vec<f32> {
    pos.iter().zip(neg.iter()).map(|(p, n)| p - n).collect()
}

/// Heuristic-based classifier identifying *why* V2 failed on this pair
pub fn classify_failure(query: &str, gold_doc: &Document, neg_doc: &Document) -> FailureClass {
    let q = query.to_lowercase();
    let g_text = gold_doc.text.to_lowercase();
    let n_text = neg_doc.text.to_lowercase();

    // 1. Identifier Collision: Query looks like an ID/hash/UUID, and negative matches partially
    if has_identifier_pattern(&q) && contains_similar_id(&q, &n_text) {
        return FailureClass::IdentifierCollision;
    }

    // 2. Document/Conversation Confusion: Query target is chat vs doc type mismatch
    if gold_doc.is_conversation != neg_doc.is_conversation {
        return FailureClass::DocumentConversationConfusion;
    }

    // 3. Phrase Order Failure: Exact phrase present in gold, but negative scatters terms
    if is_exact_phrase_match(&q, &g_text) && !is_exact_phrase_match(&q, &n_text) {
        return FailureClass::PhraseOrderFailure;
    }

    // 4. Scattered Terms: Negative doc has high term frequency across scattered sections
    if has_scattered_terms(&q, &n_text) {
        return FailureClass::ScatteredTerms;
    }

    // 5. Fuzzy Collision: Near-miss terms (typos / morphological variations) in negative doc
    if has_fuzzy_near_miss(&q, &n_text) {
        return FailureClass::FuzzyCollision;
    }

    FailureClass::Generic
}

// --- Helper heuristics ---

fn has_identifier_pattern(q: &str) -> bool {
    q.chars().any(|c| c.is_ascii_digit()) && (q.contains('-') || q.contains('_') || q.len() > 8)
}

fn contains_similar_id(q: &str, text: &str) -> bool {
    let q_tokens: Vec<&str> = q.split_whitespace().collect();
    q_tokens.iter().any(|t| {
        if t.len() > 4 {
            if text.contains(t) {
                return true;
            }
            if let Some((prefix, _)) = t.split_once('_').or_else(|| t.split_once('-')) {
                return prefix.len() > 3 && text.contains(prefix);
            }
        }
        false
    })
}

fn is_exact_phrase_match(q: &str, text: &str) -> bool {
    text.contains(q)
}

fn has_scattered_terms(q: &str, text: &str) -> bool {
    let terms: Vec<&str> = q.split_whitespace().collect();
    if terms.len() < 2 {
        return false;
    }
    terms.iter().all(|t| text.contains(t)) && !text.contains(q)
}

fn has_fuzzy_near_miss(q: &str, text: &str) -> bool {
    let q_tokens: Vec<&str> = q.split_whitespace().collect();
    q_tokens.iter().any(|t| {
        if t.len() >= 5 {
            let prefix = &t[..t.len() - 2];
            text.contains(prefix) && !text.contains(t)
        } else {
            false
        }
    })
}

/// Serializes output dataset to JSON Lines format for linear training execution
pub fn export_ledger_jsonl(path: impl AsRef<Path>, pairs: &[TrainingPair]) -> std::io::Result<()> {
    let file = File::create(path)?;
    let mut writer = BufWriter::new(file);

    for pair in pairs {
        let json = serde_json::to_string(pair)?;
        writeln!(writer, "{}", json)?;
    }

    writer.flush()?;
    Ok(())
}

/// Load an existing JSONL ledger from disk
pub fn load_ledger_jsonl(path: impl AsRef<Path>) -> std::io::Result<Vec<TrainingPair>> {
    let file = File::open(path)?;
    let reader = BufReader::new(file);
    let mut pairs = Vec::new();

    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let pair: TrainingPair = serde_json::from_str(&line)?;
        pairs.push(pair);
    }

    Ok(pairs)
}

/// Append new pairs to an existing JSONL ledger, deduplicating by (query_id, pos, neg) identity.
/// Returns the count of pairs actually appended (after dedup).
pub fn append_to_ledger_jsonl(
    path: impl AsRef<Path>,
    new_pairs: &[TrainingPair],
) -> std::io::Result<usize> {
    // Build identity set from existing ledger (if it exists)
    let mut existing_ids: HashSet<(String, String, String)> = HashSet::new();

    if path.as_ref().exists() {
        let existing = load_ledger_jsonl(&path)?;
        for pair in &existing {
            existing_ids.insert((
                pair.query_id.clone(),
                pair.positive_doc_id.clone(),
                pair.negative_doc_id.clone(),
            ));
        }
    }

    // Filter to only genuinely new pairs
    let deduped: Vec<&TrainingPair> = new_pairs
        .iter()
        .filter(|p| {
            !existing_ids.contains(&(
                p.query_id.clone(),
                p.positive_doc_id.clone(),
                p.negative_doc_id.clone(),
            ))
        })
        .collect();

    let appended_count = deduped.len();

    // Append to file
    let file = OpenOptions::new().create(true).append(true).open(path)?;
    let mut writer = BufWriter::new(file);

    for pair in &deduped {
        let json = serde_json::to_string(pair)?;
        writeln!(writer, "{}", json)?;
    }

    writer.flush()?;
    Ok(appended_count)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_test_query(gold_score: f32, neg_score: f32) -> QueryContext {
        QueryContext {
            query_id: "q_test".to_string(),
            query_text: "fix commit session_id_9921b error".to_string(),
            gold_doc_id: "doc_gold".to_string(),
            candidates: vec![
                CandidateDoc {
                    doc: Document {
                        id: "doc_neg".to_string(),
                        text: "session_id_9921a error logs scattered across session".to_string(),
                        features: vec![0.90, 0.45, 0.12, 0.88],
                        is_conversation: false,
                    },
                    v2_score: neg_score,
                    v2_rank: 1,
                },
                CandidateDoc {
                    doc: Document {
                        id: "doc_gold".to_string(),
                        text: "fix commit session_id_9921b error resolution".to_string(),
                        features: vec![0.95, 0.88, 0.92, 0.10],
                        is_conversation: false,
                    },
                    v2_score: gold_score,
                    v2_rank: 2,
                },
            ],
        }
    }

    #[test]
    fn test_inversion_detected() {
        // V2 error: gold=0.81 < neg=0.92
        let query = make_test_query(0.81, 0.92);
        let builder = DatasetBuilder::new();
        let pairs = builder.process_queries(&[query]);

        assert_eq!(pairs.len(), 1);
        let pair = &pairs[0];
        assert_eq!(pair.positive_doc_id, "doc_gold");
        assert_eq!(pair.negative_doc_id, "doc_neg");
        assert_eq!(pair.failure_class, FailureClass::IdentifierCollision);
        assert_eq!(pair.source, PairSource::ShadowDisagreement);
        // 1.8 * 1.25 = 2.25
        assert!((pair.weight - 2.25).abs() < 1e-5);
    }

    #[test]
    fn test_no_inversion_correct_ranking() {
        // V2 correct: gold=0.95 > neg=0.60
        let query = make_test_query(0.95, 0.60);
        let builder = DatasetBuilder::new();
        let pairs = builder.process_queries(&[query]);

        assert_eq!(pairs.len(), 1);
        let pair = &pairs[0];
        assert_eq!(pair.failure_class, FailureClass::Generic);
        assert_eq!(pair.source, PairSource::AutomaticallyMinedNegative);
        assert!((pair.weight - 0.5).abs() < 1e-5);
    }

    #[test]
    fn test_feature_delta() {
        let delta = compute_feature_delta(&[0.95, 0.88, 0.92, 0.10], &[0.90, 0.45, 0.12, 0.88]);
        let expected = vec![0.05, 0.43, 0.80, -0.78];
        for (d, e) in delta.iter().zip(expected.iter()) {
            assert!((d - e).abs() < 1e-4, "delta={d}, expected={e}");
        }
    }

    #[test]
    fn test_gold_doc_missing_from_candidates() {
        let query = QueryContext {
            query_id: "q_missing".to_string(),
            query_text: "some query".to_string(),
            gold_doc_id: "doc_nonexistent".to_string(),
            candidates: vec![CandidateDoc {
                doc: Document {
                    id: "doc_other".to_string(),
                    text: "irrelevant".to_string(),
                    features: vec![0.5],
                    is_conversation: false,
                },
                v2_score: 0.9,
                v2_rank: 1,
            }],
        };
        let builder = DatasetBuilder::new();
        let pairs = builder.process_queries(&[query]);
        assert!(pairs.is_empty());
    }

    #[test]
    fn test_classify_doc_conversation_confusion() {
        let gold = Document {
            id: "g".into(),
            text: "hello world".into(),
            features: vec![],
            is_conversation: true,
        };
        let neg = Document {
            id: "n".into(),
            text: "hello world".into(),
            features: vec![],
            is_conversation: false,
        };
        assert_eq!(
            classify_failure("hello", &gold, &neg),
            FailureClass::DocumentConversationConfusion
        );
    }

    #[test]
    fn test_classify_phrase_order() {
        let gold = Document {
            id: "g".into(),
            text: "how to reset password".into(),
            features: vec![],
            is_conversation: false,
        };
        let neg = Document {
            id: "n".into(),
            text: "password policies and how they reset".into(),
            features: vec![],
            is_conversation: false,
        };
        assert_eq!(
            classify_failure("how to reset password", &gold, &neg),
            FailureClass::PhraseOrderFailure
        );
    }
}

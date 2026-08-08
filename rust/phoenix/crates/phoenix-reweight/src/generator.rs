use crate::dataset::{CandidateDoc, Document, QueryContext};

/// Synthesizes high-quality, varied query contexts and candidate sets simulating real-world V2 failure modes
pub struct InteractionGenerator;

impl InteractionGenerator {
    /// Generates a rich test suite with diverse failure modes, domains, and feature profiles
    pub fn generate_suite(count_per_class: usize) -> Vec<QueryContext> {
        let mut suite = Vec::new();

        for i in 0..count_per_class {
            suite.push(Self::generate_identifier_collision(i));
            suite.push(Self::generate_phrase_order_failure(i));
            suite.push(Self::generate_scattered_terms(i));
            suite.push(Self::generate_doc_conversation_confusion(i));
            suite.push(Self::generate_fuzzy_collision(i));
        }

        suite
    }

    /// Category 1: Identifier Collision (UUIDs, Commit Hashes, Session IDs, Log Codes)
    pub fn generate_identifier_collision(idx: usize) -> QueryContext {
        let id_templates = [
            (
                "session_id_9921b",
                "session_id_9921a",
                "fix commit session_id_9921b error",
            ),
            (
                "err_code_4091_x",
                "err_code_4091_y",
                "resolve panic err_code_4091_x in memory",
            ),
            (
                "usr_77a91f00",
                "usr_77a91f01",
                "lookup payload for usr_77a91f00 profile",
            ),
            (
                "commit_c8f29d1",
                "commit_c8f29d0",
                "revert breaking change commit_c8f29d1",
            ),
            (
                "tx_8819203948",
                "tx_8819203949",
                "audit ledger transaction tx_8819203948",
            ),
        ];

        let (target_id, distractor_id, query_text) = id_templates[idx % id_templates.len()];

        let gold_id = format!("doc_gold_id_{}", idx);
        let neg_id = format!("doc_neg_id_{}", idx);

        QueryContext {
            query_id: format!("q_id_collision_{}", idx),
            query_text: query_text.to_string(),
            gold_doc_id: gold_id.clone(),
            candidates: vec![
                // False Positive: V2 over-relies on keyword n-gram overlap of distractor ID
                CandidateDoc {
                    doc: Document {
                        id: neg_id,
                        text: format!(
                            "Log entry for {} showing scattered stack trace and warnings",
                            distractor_id
                        ),
                        features: vec![0.92, 0.40, 0.15, 0.85, 0.20], // High lexical, low semantic
                        is_conversation: false,
                    },
                    v2_score: 0.93, // V2 incorrectly ranks this #1
                    v2_rank: 1,
                },
                // True Positive: Contains exact target ID and context
                CandidateDoc {
                    doc: Document {
                        id: gold_id,
                        text: format!(
                            "Root cause analysis and fix for {} session deadlock error",
                            target_id
                        ),
                        features: vec![0.98, 0.95, 0.92, 0.10, 0.90], // High semantic and exact identifier match
                        is_conversation: false,
                    },
                    v2_score: 0.82, // V2 incorrectly ranks this #2
                    v2_rank: 2,
                },
            ],
        }
    }

    /// Category 2: Phrase Order Failure (Exact word sequence vs scrambled terms)
    pub fn generate_phrase_order_failure(idx: usize) -> QueryContext {
        let phrase_templates = [
            (
                "how to reset database admin password",
                "database password reset policies and how to request admin access",
            ),
            (
                "rate limit exceeded error handler",
                "handler errors when exceeding rate limit settings",
            ),
            (
                "distributed lock acquisition timeout",
                "timeout settings for lock acquisition in distributed nodes",
            ),
            (
                "quantum state vector collapsing algorithm",
                "algorithm for collapsing vector state in quantum simulations",
            ),
        ];

        let (query_text, scrambled_text) = phrase_templates[idx % phrase_templates.len()];

        let gold_id = format!("doc_gold_phrase_{}", idx);
        let neg_id = format!("doc_neg_phrase_{}", idx);

        QueryContext {
            query_id: format!("q_phrase_order_{}", idx),
            query_text: query_text.to_string(),
            gold_doc_id: gold_id.clone(),
            candidates: vec![
                // False Positive: V2 matches all words but ignores exact word ordering
                CandidateDoc {
                    doc: Document {
                        id: neg_id,
                        text: scrambled_text.to_string(),
                        features: vec![0.88, 0.35, 0.25, 0.80, 0.10], // High unigram overlap, low n-gram order
                        is_conversation: false,
                    },
                    v2_score: 0.91,
                    v2_rank: 1,
                },
                // True Positive: Contains exact phrase sequence
                CandidateDoc {
                    doc: Document {
                        id: gold_id,
                        text: format!("Step by step guide: {}", query_text),
                        features: vec![0.96, 0.92, 0.89, 0.95, 0.85], // High exact phrase match feature
                        is_conversation: false,
                    },
                    v2_score: 0.79,
                    v2_rank: 2,
                },
            ],
        }
    }

    /// Category 3: Scattered Terms (Terms scattered across distant paragraphs vs coherent doc)
    pub fn generate_scattered_terms(idx: usize) -> QueryContext {
        let query_text = "raymond graph neural network embeddings node classification";
        let gold_id = format!("doc_gold_scattered_{}", idx);
        let neg_id = format!("doc_neg_scattered_{}", idx);

        QueryContext {
            query_id: format!("q_scattered_{}", idx),
            query_text: query_text.to_string(),
            gold_doc_id: gold_id.clone(),
            candidates: vec![
                // False Positive: Terms appear in unrelated sections of a long document
                CandidateDoc {
                    doc: Document {
                        id: neg_id,
                        text: "Author: Raymond. Section 1: Graph theory and embeddings. Section 5: Neural network architectures. Section 9: Node classification metrics.".to_string(),
                        features: vec![0.85, 0.25, 0.10, 0.75, 0.05],
                        is_conversation: false,
                    },
                    v2_score: 0.89,
                    v2_rank: 1,
                },
                // True Positive: Coherent section discussing graph neural network embeddings for node classification
                CandidateDoc {
                    doc: Document {
                        id: gold_id,
                        text: "Author: Raymond. Paper topic: graph neural network embeddings for node classification.".to_string(),
                        features: vec![0.94, 0.89, 0.90, 0.88, 0.92],
                        is_conversation: false,
                    },
                    v2_score: 0.80,
                    v2_rank: 2,
                },
            ],
        }
    }

    /// Category 4: Document vs Conversation Confusion (Metadata & type mismatch)
    pub fn generate_doc_conversation_confusion(idx: usize) -> QueryContext {
        // Query must not contain digits so identifier collision heuristic won't trigger first
        let query_text = "official release notes migration guide";
        let gold_id = format!("doc_gold_type_{}", idx);
        let neg_id = format!("doc_neg_type_{}", idx);

        QueryContext {
            query_id: format!("q_doc_conv_{}", idx),
            query_text: query_text.to_string(),
            gold_doc_id: gold_id.clone(),
            candidates: vec![
                // False Positive: Casual Slack chat discussion
                CandidateDoc {
                    doc: Document {
                        id: neg_id,
                        text: "Hey team, did anyone check the release notes migration guide?"
                            .to_string(),
                        features: vec![0.87, 0.40, 0.20, 0.85, 0.15],
                        is_conversation: true, // Mismatched doc type
                    },
                    v2_score: 0.88,
                    v2_rank: 1,
                },
                // True Positive: Official documentation page
                CandidateDoc {
                    doc: Document {
                        id: gold_id,
                        text: "Official documentation: Migration Guide & Release Notes."
                            .to_string(),
                        features: vec![0.97, 0.91, 0.95, 0.90, 0.95],
                        is_conversation: false, // Target doc type
                    },
                    v2_score: 0.78,
                    v2_rank: 2,
                },
            ],
        }
    }

    /// Category 5: Fuzzy Collision (Stemming / Levenshtein typos)
    pub fn generate_fuzzy_collision(idx: usize) -> QueryContext {
        // Query without numbers to prevent IdentifierCollision precedence
        let query_text = "kubernetes ingress controller configuration";
        let gold_id = format!("doc_gold_fuzzy_{}", idx);
        let neg_id = format!("doc_neg_fuzzy_{}", idx);

        QueryContext {
            query_id: format!("q_fuzzy_{}", idx),
            query_text: query_text.to_string(),
            gold_doc_id: gold_id.clone(),
            candidates: vec![
                // False Positive: Near-miss terms (e.g. egress controller / proxy)
                CandidateDoc {
                    doc: Document {
                        id: neg_id,
                        text: "kubernetes egress controller configurations and proxy rules".to_string(),
                        features: vec![0.86, 0.50, 0.30, 0.82, 0.25],
                        is_conversation: false,
                    },
                    v2_score: 0.87,
                    v2_rank: 1,
                },
                // True Positive
                CandidateDoc {
                    doc: Document {
                        id: gold_id,
                        text: "Complete reference for kubernetes ingress controller configuration options.".to_string(),
                        features: vec![0.96, 0.93, 0.91, 0.92, 0.89],
                        is_conversation: false,
                    },
                    v2_score: 0.81,
                    v2_rank: 2,
                },
            ],
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dataset::{DatasetBuilder, FailureClass};

    #[test]
    fn test_generator_produces_all_target_classes() {
        let suite = InteractionGenerator::generate_suite(2);
        assert_eq!(suite.len(), 10);

        let builder = DatasetBuilder::new();
        let pairs = builder.process_queries(&suite);

        assert_eq!(pairs.len(), 10);

        let classes: std::collections::HashSet<_> = pairs.iter().map(|p| p.failure_class).collect();
        assert!(classes.contains(&FailureClass::IdentifierCollision));
        assert!(classes.contains(&FailureClass::PhraseOrderFailure));
        assert!(classes.contains(&FailureClass::ScatteredTerms));
        assert!(classes.contains(&FailureClass::DocumentConversationConfusion));
        assert!(classes.contains(&FailureClass::FuzzyCollision));
    }
}

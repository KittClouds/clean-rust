use rustc_hash::FxHashMap;

use crate::glirel::GlirelRelationTypeSpec;
use crate::nli::{should_use_reverse_direction, NliError, NliPairJudgment, NliScorer, NliScores};
use crate::worker::{
    build_relation_hypotheses, RelationDecision, RelationDecisionKind, RelationScopeReviewBatch,
};

const DEFAULT_MAX_PAIRS_PER_BATCH: usize = 32;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NliAdjudicationBatchOptions {
    pub max_pairs_per_batch: usize,
}

impl Default for NliAdjudicationBatchOptions {
    fn default() -> Self {
        Self {
            max_pairs_per_batch: DEFAULT_MAX_PAIRS_PER_BATCH,
        }
    }
}

impl NliAdjudicationBatchOptions {
    fn normalized_batch_size(self) -> usize {
        self.max_pairs_per_batch.max(1)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum NliStageDirection {
    Forward,
    Reverse,
}

#[derive(Clone, Debug, Default, PartialEq)]
struct NliStageCorpus {
    premises: Vec<String>,
    rows: Vec<NliStageRow>,
}

#[derive(Clone, Debug, PartialEq)]
struct NliStageRow {
    case_id: String,
    premise_index: usize,
    direction: NliStageDirection,
    hypothesis: String,
}

#[derive(Clone, Debug, PartialEq)]
struct NliScoredStageRow {
    case_id: String,
    direction: NliStageDirection,
    hypothesis: String,
    scores: NliScores,
}

#[derive(Clone, Debug, PartialEq)]
struct DirectionBest {
    scores: NliScores,
    hypothesis: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
struct JudgmentAccumulator {
    forward: Option<DirectionBest>,
    reverse: Option<DirectionBest>,
}

pub(crate) fn stage_relation_judgments<S: NliScorer + ?Sized>(
    batch: &RelationScopeReviewBatch,
    decisions: &[RelationDecision],
    relation_specs: &[GlirelRelationTypeSpec],
    scorer: &S,
    options: NliAdjudicationBatchOptions,
) -> Result<FxHashMap<String, NliPairJudgment>, NliError> {
    let corpus = build_relation_stage_corpus(batch, decisions, relation_specs);
    let scored = score_stage_corpus(&corpus, scorer, options)?;
    Ok(reduce_scored_rows(scored))
}

fn build_relation_stage_corpus(
    batch: &RelationScopeReviewBatch,
    decisions: &[RelationDecision],
    relation_specs: &[GlirelRelationTypeSpec],
) -> NliStageCorpus {
    let spec_by_label = relation_specs
        .iter()
        .map(|spec| (spec.label.as_str(), spec))
        .collect::<FxHashMap<_, _>>();
    let case_by_id = batch
        .review_cases
        .iter()
        .map(|case| (case.case_id.as_str(), case))
        .collect::<FxHashMap<_, _>>();
    let window_text_by_id = batch
        .windows
        .iter()
        .map(|window| (window.window_id.as_str(), window.text.as_str()))
        .collect::<FxHashMap<_, _>>();
    let mut corpus = NliStageCorpus {
        premises: Vec::with_capacity(decisions.len()),
        rows: Vec::new(),
    };
    for decision in decisions {
        if decision.kind == RelationDecisionKind::Reject && decision.score_millis <= 0 {
            continue;
        }
        let Some(edge_type) = decision.edge_type.as_deref() else {
            continue;
        };
        let Some(spec) = spec_by_label.get(edge_type) else {
            continue;
        };
        let Some(case) = case_by_id.get(decision.case_id.as_str()) else {
            continue;
        };
        let premise = if case.window_text.is_empty() {
            window_text_by_id
                .get(case.window_id.as_str())
                .copied()
                .unwrap_or_default()
        } else {
            case.window_text.as_str()
        };
        let premise_index = corpus.premises.len();
        corpus.premises.push(premise.to_owned());
        push_hypotheses(
            &mut corpus.rows,
            &decision.case_id,
            premise_index,
            NliStageDirection::Forward,
            build_relation_hypotheses(edge_type, &case.source_name, &case.target_name),
        );
        if spec.directed {
            push_hypotheses(
                &mut corpus.rows,
                &decision.case_id,
                premise_index,
                NliStageDirection::Reverse,
                build_relation_hypotheses(edge_type, &case.target_name, &case.source_name),
            );
        }
    }
    corpus
}

fn push_hypotheses(
    rows: &mut Vec<NliStageRow>,
    case_id: &str,
    premise_index: usize,
    direction: NliStageDirection,
    hypotheses: Vec<String>,
) {
    rows.reserve(hypotheses.len());
    rows.extend(hypotheses.into_iter().map(|hypothesis| NliStageRow {
        case_id: case_id.to_owned(),
        premise_index,
        direction,
        hypothesis,
    }));
}

fn score_stage_corpus<S: NliScorer + ?Sized>(
    corpus: &NliStageCorpus,
    scorer: &S,
    options: NliAdjudicationBatchOptions,
) -> Result<Vec<NliScoredStageRow>, NliError> {
    let batch_size = options.normalized_batch_size();
    let mut scored = Vec::with_capacity(corpus.rows.len());
    for chunk in corpus.rows.chunks(batch_size) {
        let pairs = chunk
            .iter()
            .map(|row| {
                (
                    corpus.premises[row.premise_index].as_str(),
                    row.hypothesis.as_str(),
                )
            })
            .collect::<Vec<_>>();
        let scores = scorer.score_batch(&pairs)?;
        if scores.len() != chunk.len() {
            return Err(NliError::Inference(format!(
                "NLI scorer returned {} scores for {} staged pairs",
                scores.len(),
                chunk.len()
            )));
        }
        scored.extend(
            chunk
                .iter()
                .zip(scores)
                .map(|(row, scores)| NliScoredStageRow {
                    case_id: row.case_id.clone(),
                    direction: row.direction,
                    hypothesis: row.hypothesis.clone(),
                    scores,
                }),
        );
    }
    Ok(scored)
}

fn reduce_scored_rows(rows: Vec<NliScoredStageRow>) -> FxHashMap<String, NliPairJudgment> {
    let mut grouped = FxHashMap::<String, JudgmentAccumulator>::default();
    for row in rows {
        let accumulator = grouped.entry(row.case_id).or_default();
        let slot = match row.direction {
            NliStageDirection::Forward => &mut accumulator.forward,
            NliStageDirection::Reverse => &mut accumulator.reverse,
        };
        update_best(slot, row.scores, row.hypothesis);
    }
    let mut judgments = FxHashMap::default();
    judgments.reserve(grouped.len());
    for (case_id, accumulator) in grouped {
        let Some(forward) = accumulator.forward else {
            continue;
        };
        let reverse_scores = accumulator.reverse.as_ref().map(|best| best.scores);
        let used_reverse = reverse_scores
            .map(|reverse| should_use_reverse_direction(forward.scores, reverse))
            .unwrap_or(false);
        let best_hypothesis = if used_reverse {
            accumulator
                .reverse
                .as_ref()
                .map(|best| best.hypothesis.clone())
                .unwrap_or_else(|| forward.hypothesis.clone())
        } else {
            forward.hypothesis.clone()
        };
        judgments.insert(
            case_id,
            NliPairJudgment {
                forward: forward.scores,
                reverse: accumulator.reverse.map(|best| best.scores),
                used_reverse,
                best_hypothesis,
            },
        );
    }
    judgments
}

fn update_best(slot: &mut Option<DirectionBest>, scores: NliScores, hypothesis: String) {
    let replace = match slot {
        Some(current) => {
            scores.entailment > current.scores.entailment
                || (scores.entailment == current.scores.entailment
                    && scores.contradiction < current.scores.contradiction)
        }
        None => true,
    };
    if replace {
        *slot = Some(DirectionBest { scores, hypothesis });
    }
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;

    use super::*;

    struct FakeScorer {
        call_sizes: RefCell<Vec<usize>>,
    }

    impl FakeScorer {
        fn new() -> Self {
            Self {
                call_sizes: RefCell::new(Vec::new()),
            }
        }
    }

    impl NliScorer for FakeScorer {
        fn score_batch(&self, pairs: &[(&str, &str)]) -> Result<Vec<NliScores>, NliError> {
            self.call_sizes.borrow_mut().push(pairs.len());
            Ok(pairs
                .iter()
                .map(|(_, hypothesis)| match *hypothesis {
                    "forward-weak" => scores(0.42, 0.08),
                    "forward-strong" => scores(0.76, 0.04),
                    "reverse-weak" => scores(0.49, 0.01),
                    "reverse-strong" => scores(0.86, 0.02),
                    _ => scores(0.12, 0.10),
                })
                .collect())
        }
    }

    fn scores(entailment: f32, contradiction: f32) -> NliScores {
        NliScores {
            contradiction,
            entailment,
            neutral: (1.0 - entailment - contradiction).max(0.0),
        }
    }

    fn row(
        case_id: &str,
        premise_index: usize,
        direction: NliStageDirection,
        hypothesis: &str,
    ) -> NliStageRow {
        NliStageRow {
            case_id: case_id.to_owned(),
            premise_index,
            direction,
            hypothesis: hypothesis.to_owned(),
        }
    }

    #[test]
    fn scorer_uses_configured_chunks() {
        let corpus = NliStageCorpus {
            premises: vec!["Borrik stood beside Hazel.".to_owned()],
            rows: vec![
                row("case-a", 0, NliStageDirection::Forward, "forward-weak"),
                row("case-a", 0, NliStageDirection::Forward, "forward-strong"),
                row("case-a", 0, NliStageDirection::Reverse, "reverse-weak"),
                row("case-b", 0, NliStageDirection::Forward, "forward-weak"),
                row("case-b", 0, NliStageDirection::Reverse, "reverse-strong"),
            ],
        };
        let scorer = FakeScorer::new();
        let scored = score_stage_corpus(
            &corpus,
            &scorer,
            NliAdjudicationBatchOptions {
                max_pairs_per_batch: 2,
            },
        )
        .expect("scored rows");

        assert_eq!(scored.len(), 5);
        assert_eq!(*scorer.call_sizes.borrow(), vec![2, 2, 1]);
    }

    #[test]
    fn reducer_selects_best_hypothesis_and_safe_reverse() {
        let scored = vec![
            NliScoredStageRow {
                case_id: "case-a".to_owned(),
                direction: NliStageDirection::Forward,
                hypothesis: "forward-weak".to_owned(),
                scores: scores(0.42, 0.08),
            },
            NliScoredStageRow {
                case_id: "case-a".to_owned(),
                direction: NliStageDirection::Forward,
                hypothesis: "forward-strong".to_owned(),
                scores: scores(0.76, 0.04),
            },
            NliScoredStageRow {
                case_id: "case-a".to_owned(),
                direction: NliStageDirection::Reverse,
                hypothesis: "reverse-weak".to_owned(),
                scores: scores(0.49, 0.01),
            },
            NliScoredStageRow {
                case_id: "case-b".to_owned(),
                direction: NliStageDirection::Forward,
                hypothesis: "forward-weak".to_owned(),
                scores: scores(0.42, 0.08),
            },
            NliScoredStageRow {
                case_id: "case-b".to_owned(),
                direction: NliStageDirection::Reverse,
                hypothesis: "reverse-strong".to_owned(),
                scores: scores(0.86, 0.02),
            },
        ];
        let judgments = reduce_scored_rows(scored);

        let case_a = judgments.get("case-a").expect("case a");
        assert_eq!(case_a.best_hypothesis, "forward-strong");
        assert!(!case_a.used_reverse);

        let case_b = judgments.get("case-b").expect("case b");
        assert_eq!(case_b.best_hypothesis, "reverse-strong");
        assert!(case_b.used_reverse);
    }
}

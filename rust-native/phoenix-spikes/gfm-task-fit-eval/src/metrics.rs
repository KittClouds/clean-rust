use serde::Serialize;

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RetrievalMetrics {
    pub cases: usize,
    pub recall_at_1: f64,
    pub recall_at_3: f64,
    pub recall_at_5: f64,
    pub mean_reciprocal_rank: f64,
    pub mean_ndcg_at_5: f64,
    pub full_support_at_5: f64,
}

#[derive(Default)]
pub struct MetricsAccumulator {
    cases: usize,
    recall_at_1: f64,
    recall_at_3: f64,
    recall_at_5: f64,
    reciprocal_rank: f64,
    ndcg_at_5: f64,
    full_support_at_5: f64,
}

impl MetricsAccumulator {
    pub fn observe(&mut self, ranking: &[String], gold: &[String]) {
        self.cases += 1;
        self.recall_at_1 += recall_at(ranking, gold, 1);
        self.recall_at_3 += recall_at(ranking, gold, 3);
        self.recall_at_5 += recall_at(ranking, gold, 5);
        self.reciprocal_rank += reciprocal_rank(ranking, gold);
        self.ndcg_at_5 += ndcg_at(ranking, gold, 5);
        self.full_support_at_5 += f64::from(full_support_at(ranking, gold, 5));
    }

    pub fn finish(self) -> RetrievalMetrics {
        if self.cases == 0 {
            return RetrievalMetrics::default();
        }
        let denominator = self.cases as f64;
        RetrievalMetrics {
            cases: self.cases,
            recall_at_1: self.recall_at_1 / denominator,
            recall_at_3: self.recall_at_3 / denominator,
            recall_at_5: self.recall_at_5 / denominator,
            mean_reciprocal_rank: self.reciprocal_rank / denominator,
            mean_ndcg_at_5: self.ndcg_at_5 / denominator,
            full_support_at_5: self.full_support_at_5 / denominator,
        }
    }
}

fn ndcg_at(ranking: &[String], gold: &[String], k: usize) -> f64 {
    if gold.is_empty() {
        return 0.0;
    }
    let dcg = ranking
        .iter()
        .take(k)
        .enumerate()
        .filter(|(_, id)| gold.iter().any(|gold_id| gold_id == *id))
        .map(|(index, _)| 1.0 / ((index + 2) as f64).log2())
        .sum::<f64>();
    let ideal = (0..gold.len().min(k))
        .map(|index| 1.0 / ((index + 2) as f64).log2())
        .sum::<f64>();
    dcg / ideal
}

fn recall_at(ranking: &[String], gold: &[String], k: usize) -> f64 {
    if gold.is_empty() {
        return 0.0;
    }
    let hits = gold
        .iter()
        .filter(|gold_id| ranking.iter().take(k).any(|id| id == *gold_id))
        .count();
    hits as f64 / gold.len() as f64
}

fn reciprocal_rank(ranking: &[String], gold: &[String]) -> f64 {
    ranking
        .iter()
        .position(|id| gold.iter().any(|gold_id| gold_id == id))
        .map_or(0.0, |index| 1.0 / (index + 1) as f64)
}

fn full_support_at(ranking: &[String], gold: &[String], k: usize) -> bool {
    !gold.is_empty()
        && gold
            .iter()
            .all(|gold_id| ranking.iter().take(k).any(|id| id == gold_id))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scores_multi_document_support_without_hiding_partial_recall() {
        let mut metrics = MetricsAccumulator::default();
        metrics.observe(
            &["doc:a".into(), "doc:x".into(), "doc:b".into()],
            &["doc:a".into(), "doc:b".into()],
        );
        let metrics = metrics.finish();
        assert_eq!(metrics.recall_at_1, 0.5);
        assert_eq!(metrics.recall_at_3, 1.0);
        assert_eq!(metrics.mean_reciprocal_rank, 1.0);
        assert!(metrics.mean_ndcg_at_5 > 0.9);
        assert_eq!(metrics.full_support_at_5, 1.0);
    }
}

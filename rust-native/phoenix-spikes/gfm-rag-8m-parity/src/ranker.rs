use std::cmp::Ordering;

use crate::{GfmError, Result};

#[derive(Clone, Debug)]
pub struct RankedDocuments {
    pub top_entities: Vec<usize>,
    pub scores: Vec<f32>,
    pub order: Vec<usize>,
}

/// Exact IDFWeightedTopKRanker semantics: logits select membership only; each
/// selected entity contributes reciprocal document frequency to every mapped doc.
pub fn reciprocal_frequency_rank(
    logits: &[f32],
    entity_documents: &[Box<[u32]>],
    document_count: usize,
    top_k: usize,
) -> Result<RankedDocuments> {
    if logits.len() != entity_documents.len() {
        return Err(GfmError::Shape("logits and entity mapping disagree".into()));
    }
    let mut entities: Vec<usize> = (0..logits.len()).collect();
    entities.sort_unstable_by(|&left, &right| {
        logits[right]
            .partial_cmp(&logits[left])
            .unwrap_or(Ordering::Equal)
            .then_with(|| left.cmp(&right))
    });
    entities.truncate(top_k.min(entities.len()));

    let mut scores = vec![0_f32; document_count];
    for &entity in &entities {
        let documents = &entity_documents[entity];
        if documents.is_empty() {
            continue;
        }
        let contribution = 1.0 / documents.len() as f32;
        for &document in documents.iter() {
            let score = scores.get_mut(document as usize).ok_or_else(|| {
                GfmError::InvalidGraph(format!("document index {document} out of bounds"))
            })?;
            *score += contribution;
        }
    }
    let mut order: Vec<usize> = (0..document_count).collect();
    order.sort_unstable_by(|&left, &right| {
        scores[right]
            .partial_cmp(&scores[left])
            .unwrap_or(Ordering::Equal)
            .then_with(|| left.cmp(&right))
    });
    Ok(RankedDocuments {
        top_entities: entities,
        scores,
        order,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn discards_logit_magnitude_after_selection() {
        let mapping = vec![
            vec![0_u32, 1].into_boxed_slice(),
            vec![1].into_boxed_slice(),
        ];
        let ranked = reciprocal_frequency_rank(&[100.0, 0.5], &mapping, 2, 2).unwrap();
        assert_eq!(ranked.scores, vec![0.5, 1.5]);
        assert_eq!(ranked.order, vec![1, 0]);
    }
}

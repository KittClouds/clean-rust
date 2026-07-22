use std::cmp::Ordering;

use crate::{
    CompactTopKOutput, QuantizedRows, TopKRecord, ValidatedCorpus, VectorCorpusInput, VectorError,
    VectorRerankBatch,
};

#[derive(Clone, Copy)]
struct RankedCandidate {
    id: u32,
    lexical_rank: u32,
    score: f32,
}

pub struct CpuResidentCorpus<'a> {
    corpus: VectorCorpusInput<'a>,
    shape: ValidatedCorpus,
}

impl<'a> CpuResidentCorpus<'a> {
    pub fn new(corpus: VectorCorpusInput<'a>) -> Result<Self, VectorError> {
        let shape = corpus.validate()?;
        Ok(Self { corpus, shape })
    }

    pub fn shape(&self) -> ValidatedCorpus {
        self.shape
    }

    pub fn rerank(&self, batch: VectorRerankBatch<'_>) -> Result<CompactTopKOutput, VectorError> {
        batch.validate(self.shape)?;
        Ok(rank_batch(self.corpus, self.shape, batch))
    }
}

pub fn cpu_exact_top_k(
    corpus: VectorCorpusInput<'_>,
    batch: VectorRerankBatch<'_>,
) -> Result<CompactTopKOutput, VectorError> {
    CpuResidentCorpus::new(corpus)?.rerank(batch)
}

fn rank_batch(
    corpus: VectorCorpusInput<'_>,
    corpus_shape: ValidatedCorpus,
    batch: VectorRerankBatch<'_>,
) -> CompactTopKOutput {
    let dimensions = corpus_shape.dimensions as usize;
    let mut offsets = Vec::with_capacity(batch.query_count as usize + 1);
    let mut records = Vec::with_capacity(batch.query_count as usize * batch.top_k as usize);
    let mut ranked = Vec::with_capacity(crate::MAX_CANDIDATES_PER_QUERY as usize);
    offsets.push(0);
    for query_index in 0..batch.query_count as usize {
        ranked.clear();
        let query = &batch.queries[query_index * dimensions..(query_index + 1) * dimensions];
        let start = batch.candidate_offsets[query_index] as usize;
        let end = batch.candidate_offsets[query_index + 1] as usize;
        for &candidate_id in &batch.candidate_ids[start..end] {
            let candidate_start = candidate_id as usize * dimensions;
            let candidate = &corpus.values[candidate_start..candidate_start + dimensions];
            let score = dot_f32(query, candidate).clamp(-1.0, 1.0);
            if score >= batch.minimum_similarity {
                ranked.push(RankedCandidate {
                    id: candidate_id,
                    lexical_rank: corpus.lexical_ranks[candidate_id as usize],
                    score,
                });
            }
        }
        ranked.sort_unstable_by(rank_before);
        records.extend(
            ranked
                .iter()
                .take(batch.top_k as usize)
                .map(|candidate| TopKRecord {
                    candidate_id: candidate.id,
                    score: candidate.score,
                }),
        );
        offsets.push(records.len() as u32);
    }
    CompactTopKOutput { offsets, records }
}

pub fn normalize_rows(values: &mut [f32], rows: u32, dimensions: u32) -> Result<(), VectorError> {
    let expected = (rows as usize)
        .checked_mul(dimensions as usize)
        .ok_or_else(|| VectorError::Shape("normalization extent overflow".to_owned()))?;
    if rows == 0 || dimensions == 0 || values.len() != expected {
        return Err(VectorError::Shape(
            "normalization extent does not match rows x dimensions".to_owned(),
        ));
    }
    for row in values.chunks_exact_mut(dimensions as usize) {
        let mut norm_squared = 0.0_f64;
        for &value in row.iter() {
            if !value.is_finite() {
                return Err(VectorError::Shape(
                    "normalization input contains a non-finite value".to_owned(),
                ));
            }
            norm_squared += f64::from(value) * f64::from(value);
        }
        if norm_squared <= 0.0 {
            return Err(VectorError::Shape(
                "normalization input contains a zero row".to_owned(),
            ));
        }
        let inverse = (1.0 / norm_squared.sqrt()) as f32;
        for value in row {
            *value *= inverse;
        }
    }
    Ok(())
}

pub fn quantize_symmetric_i8(
    values: &[f32],
    rows: u32,
    dimensions: u32,
) -> Result<QuantizedRows, VectorError> {
    let expected = (rows as usize)
        .checked_mul(dimensions as usize)
        .ok_or_else(|| VectorError::Shape("quantization extent overflow".to_owned()))?;
    if rows == 0 || dimensions == 0 || values.len() != expected {
        return Err(VectorError::Shape(
            "quantization extent does not match rows x dimensions".to_owned(),
        ));
    }
    let mut quantized = Vec::with_capacity(values.len());
    let mut scales = Vec::with_capacity(rows as usize);
    for row in values.chunks_exact(dimensions as usize) {
        let mut maximum = 0.0_f32;
        for &value in row {
            if !value.is_finite() {
                return Err(VectorError::Shape(
                    "quantization input contains a non-finite value".to_owned(),
                ));
            }
            maximum = maximum.max(value.abs());
        }
        if maximum == 0.0 {
            return Err(VectorError::Shape(
                "quantization input contains a zero row".to_owned(),
            ));
        }
        let scale = maximum / 127.0;
        scales.push(scale);
        quantized.extend(
            row.iter()
                .map(|value| (value / scale).round().clamp(-127.0, 127.0) as i8),
        );
    }
    Ok(QuantizedRows {
        values: quantized,
        scales,
        rows,
        dimensions,
    })
}

fn dot_f32(left: &[f32], right: &[f32]) -> f32 {
    left.iter()
        .zip(right)
        .fold(0.0_f32, |sum, (&left, &right)| left.mul_add(right, sum))
}

fn rank_before(left: &RankedCandidate, right: &RankedCandidate) -> Ordering {
    right
        .score
        .total_cmp(&left.score)
        .then_with(|| left.lexical_rank.cmp(&right.lexical_rank))
        .then_with(|| left.id.cmp(&right.id))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalization_and_quantization_are_bounded() {
        let mut values = vec![3.0, 4.0, 0.0, 1.0, 2.0, 2.0];
        normalize_rows(&mut values, 2, 3).unwrap();
        for row in values.chunks_exact(3) {
            let norm = row.iter().map(|value| value * value).sum::<f32>().sqrt();
            assert!((norm - 1.0).abs() < 1.0e-6);
        }
        let quantized = quantize_symmetric_i8(&values, 2, 3).unwrap();
        assert_eq!(quantized.values.len(), 6);
        assert_eq!(quantized.scales.len(), 2);
        assert!(quantized.values.iter().all(|value| *value >= -127));
    }
}

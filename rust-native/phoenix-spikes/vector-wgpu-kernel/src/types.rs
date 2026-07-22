use std::mem::size_of;

use bytemuck::{Pod, Zeroable};
use hashbrown::HashSet;
use thiserror::Error;

pub const WORKGROUP_WIDTH: u32 = 128;
pub const MAX_DIMENSIONS: u32 = 4_096;
pub const MAX_CANDIDATES_PER_QUERY: u32 = 512;
pub const MAX_TOP_K: u32 = 64;
pub const INVALID_CANDIDATE: u32 = u32::MAX;
const MAX_CORPUS_ROWS: u32 = 10_000_000;
const MAX_QUERY_ROWS: u32 = 1_000_000;

#[derive(Debug, Error)]
pub enum VectorError {
    #[error("invalid vector scoring contract: {0}")]
    Shape(String),
    #[error("GPU adapter unavailable: {0}")]
    Adapter(String),
    #[error("GPU device unavailable: {0}")]
    Device(String),
    #[error("GPU residency rejected: {0}")]
    Residency(String),
    #[error("GPU execution failed: {0}")]
    Execution(String),
}

#[derive(Clone, Copy, Debug)]
pub struct VectorCorpusInput<'a> {
    pub values: &'a [f32],
    pub lexical_ranks: &'a [u32],
    pub rows: u32,
    pub dimensions: u32,
}

#[derive(Clone, Copy, Debug)]
pub struct VectorRerankBatch<'a> {
    pub queries: &'a [f32],
    pub query_count: u32,
    pub candidate_offsets: &'a [u32],
    pub candidate_ids: &'a [u32],
    pub top_k: u32,
    pub minimum_similarity: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct RawVectorInput<'a> {
    pub values: &'a [f32],
    pub rows: u32,
    pub dimensions: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidatedCorpus {
    pub rows: u32,
    pub dimensions: u32,
    pub vector_bytes: u64,
    pub lexical_rank_bytes: u64,
    pub resident_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidatedRerankBatch {
    pub queries: u32,
    pub pairs: u32,
    pub top_k: u32,
    pub query_bytes: u64,
    pub candidate_bytes: u64,
    pub readback_bytes: u64,
    pub scalar_fma_ops: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ValidatedPreprocess {
    pub rows: u32,
    pub dimensions: u32,
    pub packed_words_per_row: u32,
    pub input_bytes: u64,
    pub normalized_bytes: u64,
    pub quantized_bytes: u64,
    pub scale_bytes: u64,
    pub resident_bytes: u64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, Pod, Zeroable)]
pub struct TopKRecord {
    pub candidate_id: u32,
    pub score: f32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CompactTopKOutput {
    pub offsets: Vec<u32>,
    pub records: Vec<TopKRecord>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct QuantizedRows {
    pub values: Vec<i8>,
    pub scales: Vec<f32>,
    pub rows: u32,
    pub dimensions: u32,
}

impl VectorCorpusInput<'_> {
    pub fn validate(self) -> Result<ValidatedCorpus, VectorError> {
        if self.rows == 0 || self.rows > MAX_CORPUS_ROWS {
            return Err(shape(format!(
                "corpus rows must be within 1..={MAX_CORPUS_ROWS}"
            )));
        }
        if self.dimensions == 0 || self.dimensions > MAX_DIMENSIONS {
            return Err(shape(format!(
                "dimensions must be within 1..={MAX_DIMENSIONS}"
            )));
        }
        let elements = product(self.rows, self.dimensions, "corpus elements")?;
        if self.values.len() as u64 != elements {
            return Err(shape(
                "corpus vector extent does not match rows x dimensions",
            ));
        }
        if self.lexical_ranks.len() != self.rows as usize {
            return Err(shape("lexical rank extent does not match corpus rows"));
        }
        validate_unit_rows(self.values, self.rows, self.dimensions, "corpus")?;
        for &rank in self.lexical_ranks {
            if rank >= self.rows {
                return Err(shape("lexical rank is outside the corpus row set"));
            }
        }
        let vector_bytes = bytes::<f32>(elements)?;
        let lexical_rank_bytes = bytes::<u32>(u64::from(self.rows))?;
        Ok(ValidatedCorpus {
            rows: self.rows,
            dimensions: self.dimensions,
            vector_bytes,
            lexical_rank_bytes,
            resident_bytes: vector_bytes
                .checked_add(lexical_rank_bytes)
                .ok_or_else(|| shape("corpus resident byte accounting overflow"))?,
        })
    }
}

impl VectorRerankBatch<'_> {
    pub fn validate(self, corpus: ValidatedCorpus) -> Result<ValidatedRerankBatch, VectorError> {
        if self.query_count == 0 || self.query_count > MAX_QUERY_ROWS {
            return Err(shape(format!(
                "query rows must be within 1..={MAX_QUERY_ROWS}"
            )));
        }
        if self.top_k == 0 || self.top_k > MAX_TOP_K {
            return Err(shape(format!("top-k must be within 1..={MAX_TOP_K}")));
        }
        if !self.minimum_similarity.is_finite() || !(-1.0..=1.0).contains(&self.minimum_similarity)
        {
            return Err(shape(
                "minimum similarity must be finite and within [-1, 1]",
            ));
        }
        let query_elements = product(self.query_count, corpus.dimensions, "query elements")?;
        if self.queries.len() as u64 != query_elements {
            return Err(shape(
                "query vector extent does not match rows x dimensions",
            ));
        }
        validate_unit_rows(self.queries, self.query_count, corpus.dimensions, "query")?;
        if self.candidate_offsets.len() != self.query_count as usize + 1
            || self.candidate_offsets.first() != Some(&0)
            || self.candidate_offsets.last().copied() != Some(self.candidate_ids.len() as u32)
        {
            return Err(shape(
                "candidate offsets do not seal the candidate identity page",
            ));
        }
        let mut unique = HashSet::with_capacity(MAX_CANDIDATES_PER_QUERY as usize);
        for pair in self.candidate_offsets.windows(2) {
            if pair[0] > pair[1] || pair[1] - pair[0] > MAX_CANDIDATES_PER_QUERY {
                return Err(shape(format!(
                    "each ANN candidate row must be monotonic and bounded by {MAX_CANDIDATES_PER_QUERY}"
                )));
            }
            unique.clear();
            for &candidate in &self.candidate_ids[pair[0] as usize..pair[1] as usize] {
                if !unique.insert(candidate) {
                    return Err(shape(
                        "ANN candidate rows must not contain duplicate identities",
                    ));
                }
            }
        }
        if self.candidate_ids.len() > u32::MAX as usize {
            return Err(shape("candidate identity page exceeds u32 addressing"));
        }
        if self.candidate_ids.iter().any(|&id| id >= corpus.rows) {
            return Err(shape("candidate identity is outside the resident corpus"));
        }
        let pairs = self.candidate_ids.len() as u32;
        let query_bytes = bytes::<f32>(query_elements)?;
        let candidate_bytes = bytes::<u32>(
            u64::from(pairs)
                .checked_add(u64::from(self.query_count) + 1)
                .ok_or_else(|| shape("candidate byte accounting overflow"))?,
        )?;
        let fixed_records = product(self.query_count, self.top_k, "top-k records")?;
        let readback_bytes = bytes::<TopKRecord>(fixed_records)?
            .checked_add(bytes::<u32>(u64::from(self.query_count))?)
            .ok_or_else(|| shape("readback byte accounting overflow"))?;
        Ok(ValidatedRerankBatch {
            queries: self.query_count,
            pairs,
            top_k: self.top_k,
            query_bytes,
            candidate_bytes,
            readback_bytes,
            scalar_fma_ops: u64::from(pairs) * u64::from(corpus.dimensions),
        })
    }
}

impl RawVectorInput<'_> {
    pub fn validate(self) -> Result<ValidatedPreprocess, VectorError> {
        if self.rows == 0 || self.rows > MAX_CORPUS_ROWS {
            return Err(shape(format!(
                "preprocess rows must be within 1..={MAX_CORPUS_ROWS}"
            )));
        }
        if self.dimensions == 0 || self.dimensions > MAX_DIMENSIONS {
            return Err(shape(format!(
                "preprocess dimensions must be within 1..={MAX_DIMENSIONS}"
            )));
        }
        let elements = product(self.rows, self.dimensions, "preprocess elements")?;
        if self.values.len() as u64 != elements {
            return Err(shape(
                "preprocess vector extent does not match rows x dimensions",
            ));
        }
        for (row, values) in self
            .values
            .chunks_exact(self.dimensions as usize)
            .enumerate()
        {
            let mut has_nonzero = false;
            for &value in values {
                if !value.is_finite() {
                    return Err(shape(format!(
                        "preprocess row {row} contains a non-finite value"
                    )));
                }
                has_nonzero |= value != 0.0;
            }
            if !has_nonzero {
                return Err(shape(format!("preprocess row {row} is zero")));
            }
        }
        let packed_words_per_row = self.dimensions.div_ceil(4);
        let input_bytes = bytes::<f32>(elements)?;
        let normalized_bytes = input_bytes;
        let quantized_bytes = bytes::<u32>(product(
            self.rows,
            packed_words_per_row,
            "packed quantized words",
        )?)?;
        let scale_bytes = bytes::<f32>(u64::from(self.rows))?;
        let resident_bytes = input_bytes
            .checked_add(normalized_bytes)
            .and_then(|value| value.checked_add(quantized_bytes))
            .and_then(|value| value.checked_add(scale_bytes))
            .ok_or_else(|| shape("preprocess resident byte accounting overflow"))?;
        Ok(ValidatedPreprocess {
            rows: self.rows,
            dimensions: self.dimensions,
            packed_words_per_row,
            input_bytes,
            normalized_bytes,
            quantized_bytes,
            scale_bytes,
            resident_bytes,
        })
    }
}

impl CompactTopKOutput {
    pub fn query(&self, index: usize) -> &[TopKRecord] {
        let Some((&start, &end)) = self.offsets.get(index).zip(self.offsets.get(index + 1)) else {
            return &[];
        };
        &self.records[start as usize..end as usize]
    }
}

fn validate_unit_rows(
    values: &[f32],
    rows: u32,
    dimensions: u32,
    label: &str,
) -> Result<(), VectorError> {
    for row in 0..rows as usize {
        let start = row * dimensions as usize;
        let mut norm_squared = 0.0_f64;
        for &value in &values[start..start + dimensions as usize] {
            if !value.is_finite() {
                return Err(shape(format!(
                    "{label} row {row} contains a non-finite value"
                )));
            }
            norm_squared += f64::from(value) * f64::from(value);
        }
        let norm = norm_squared.sqrt();
        if norm <= 0.0 || (norm - 1.0).abs() > 0.025 {
            return Err(shape(format!("{label} row {row} is not unit normalized")));
        }
    }
    Ok(())
}

fn product(left: u32, right: u32, label: &str) -> Result<u64, VectorError> {
    u64::from(left)
        .checked_mul(u64::from(right))
        .ok_or_else(|| shape(format!("{label} overflow")))
}

fn bytes<T>(elements: u64) -> Result<u64, VectorError> {
    elements
        .checked_mul(size_of::<T>() as u64)
        .ok_or_else(|| shape("byte accounting overflow"))
}

fn shape(message: impl Into<String>) -> VectorError {
    VectorError::Shape(message.into())
}

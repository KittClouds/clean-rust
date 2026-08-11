use std::path::PathBuf;

use crate::{EmbeddingBatchOrder, OrtExecutionProviderPreference};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct EmbeddingRunTelemetry {
    pub input_rows: usize,
    pub batches: usize,
    pub useful_tokens: u64,
    pub padded_tokens: u64,
    pub useful_attention_cells: u64,
    pub padded_attention_cells: u64,
    pub max_sequence_tokens: usize,
    pub order: EmbeddingBatchOrder,
}

impl EmbeddingRunTelemetry {
    pub fn token_padding_ratio(self) -> f64 {
        ratio(self.padded_tokens, self.useful_tokens)
    }

    pub fn attention_padding_ratio(self) -> f64 {
        ratio(self.padded_attention_cells, self.useful_attention_cells)
    }

    pub(crate) fn include(&mut self, batch: BatchTelemetry) {
        self.batches += 1;
        self.useful_tokens += batch.useful_tokens;
        self.padded_tokens += batch.padded_tokens;
        self.useful_attention_cells += batch.useful_attention_cells;
        self.padded_attention_cells += batch.padded_attention_cells;
        self.max_sequence_tokens = self.max_sequence_tokens.max(batch.max_sequence_tokens);
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(crate) struct BatchTelemetry {
    pub useful_tokens: u64,
    pub padded_tokens: u64,
    pub useful_attention_cells: u64,
    pub padded_attention_cells: u64,
    pub max_sequence_tokens: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OrtTextEmbedderInfo {
    pub model_path: PathBuf,
    pub batch_size: usize,
    pub max_length: usize,
    pub intra_threads: usize,
    pub inter_threads: usize,
    pub parallel_execution: bool,
    pub batch_order: EmbeddingBatchOrder,
    pub execution_provider: OrtExecutionProviderPreference,
}

fn ratio(numerator: u64, denominator: u64) -> f64 {
    if denominator == 0 {
        return 1.0;
    }
    numerator as f64 / denominator as f64
}

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use ort::session::Session;
use ort::value::Tensor;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokenizers::Tokenizer;

use crate::gliner_x_tensors::{
    build_span_tensors, build_text_tensors, decode_predictions, extract_logits,
};
use crate::ort_runtime::{load_session_with_intra_threads, recommended_thread_count};

const DEFAULT_MAX_WIDTH: usize = 12;
const DEFAULT_MAX_LEN: usize = 1024;
const DEFAULT_BATCH_SIZE: usize = 2;
const DEFAULT_ENT_TOKEN: &str = "<<ENT>>";
const DEFAULT_SEP_TOKEN: &str = "<<SEP>>";
const GLINER_X_ONNX_FILE_ENV: &str = "PHOENIX_GLINER_X_ONNX_FILE";
const GLINER_X_THREADS_ENV: &str = "PHOENIX_GLINER_X_THREADS";
const GLINER_X_BATCH_SIZE_ENV: &str = "PHOENIX_GLINER_X_BATCH_SIZE";

#[derive(Debug, Error)]
pub enum GlinerXError {
    #[error("failed to load GLiNER-X model: {0}")]
    ModelLoad(String),
    #[error("GLiNER-X inference failed: {0}")]
    Inference(String),
    #[error("invalid GLiNER-X input: {0}")]
    InvalidInput(String),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlinerXPrediction {
    pub sequence: usize,
    pub text: String,
    pub label: String,
    pub score: f32,
    pub span_start: usize,
    pub span_end: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlinerXMetadata {
    pub model_path: String,
    pub tokenizer_path: String,
    pub threshold: f32,
    pub max_width: usize,
    pub max_len: usize,
    pub ent_token: String,
    pub sep_token: String,
    pub input_names: Vec<String>,
    pub output_names: Vec<String>,
}

pub struct GlinerXModel {
    session: Session,
    tokenizer: Tokenizer,
    threshold: f32,
    max_width: usize,
    max_len: usize,
    ent_token: String,
    sep_token: String,
    metadata: GlinerXMetadata,
}

struct PreparedXText<'a> {
    sequence: usize,
    text: &'a str,
    tensors: crate::gliner_x_tensors::GlinerXTextTensors,
}

#[derive(Clone, Debug, Default, Deserialize)]
struct GlinerXConfig {
    #[serde(default)]
    max_width: Option<usize>,
    #[serde(default)]
    max_len: Option<usize>,
    #[serde(default)]
    ent_token: Option<String>,
    #[serde(default)]
    sep_token: Option<String>,
}

impl GlinerXModel {
    pub fn load(model_root: &Path, threshold: f32) -> Result<Self, GlinerXError> {
        if !(0.0..=1.0).contains(&threshold) {
            return Err(GlinerXError::InvalidInput(format!(
                "threshold must be in [0, 1], got {threshold}"
            )));
        }

        let model_path = find_model_asset(model_root)?;
        let tokenizer_path =
            find_existing_path(model_root, &["tokenizer.json", "onnx/tokenizer.json"])?;
        let tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|error| GlinerXError::ModelLoad(format!("tokenizer: {error}")))?;
        let session = load_session_with_intra_threads(&model_path, gliner_x_thread_count())
            .map_err(|error| GlinerXError::ModelLoad(format!("session: {error}")))?;
        let config = load_json::<GlinerXConfig>(&model_root.join("gliner_config.json"))
            .or_else(|| load_json::<GlinerXConfig>(&model_root.join("config.json")))
            .unwrap_or_default();
        let max_width = config
            .max_width
            .filter(|value| *value > 0)
            .unwrap_or(DEFAULT_MAX_WIDTH);
        let max_len = config
            .max_len
            .filter(|value| *value > 0)
            .unwrap_or(DEFAULT_MAX_LEN);
        let ent_token = config
            .ent_token
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| DEFAULT_ENT_TOKEN.to_owned());
        let sep_token = config
            .sep_token
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| DEFAULT_SEP_TOKEN.to_owned());
        let metadata = GlinerXMetadata {
            model_path: model_path.display().to_string(),
            tokenizer_path: tokenizer_path.display().to_string(),
            threshold,
            max_width,
            max_len,
            ent_token: ent_token.clone(),
            sep_token: sep_token.clone(),
            input_names: session
                .inputs
                .iter()
                .map(|input| input.name.clone())
                .collect(),
            output_names: session
                .outputs
                .iter()
                .map(|output| output.name.clone())
                .collect(),
        };

        Ok(Self {
            session,
            tokenizer,
            threshold,
            max_width,
            max_len,
            ent_token,
            sep_token,
            metadata,
        })
    }

    pub fn metadata(&self) -> &GlinerXMetadata {
        &self.metadata
    }

    pub fn predict_texts(
        &self,
        texts: &[&str],
        labels: &[&str],
    ) -> Result<Vec<GlinerXPrediction>, GlinerXError> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let labels = normalize_labels(labels)?;
        let batch_size = gliner_x_batch_size();
        if batch_size <= 1 || texts.len() <= 1 {
            let mut predictions = Vec::new();
            for (sequence, text) in texts.iter().enumerate() {
                predictions.extend(self.predict_one(sequence, text, &labels)?);
            }
            return Ok(predictions);
        }

        let mut prepared = Vec::with_capacity(texts.len());
        for (sequence, text) in texts.iter().enumerate() {
            if text.trim().is_empty() {
                continue;
            }
            let Some(tensors) = build_text_tensors(
                text,
                &self.tokenizer,
                &labels,
                &self.ent_token,
                &self.sep_token,
                self.max_len,
            )?
            else {
                continue;
            };
            prepared.push(PreparedXText {
                sequence,
                text,
                tensors,
            });
        }
        prepared.sort_by_key(|item| (item.tensors.input_ids.len(), item.tensors.words.len()));

        let mut predictions = Vec::new();
        for chunk in prepared.chunks(batch_size) {
            predictions.extend(self.predict_prepared_batch(chunk, &labels)?);
        }
        Ok(predictions)
    }

    fn predict_prepared_batch(
        &self,
        prepared: &[PreparedXText<'_>],
        labels: &[String],
    ) -> Result<Vec<GlinerXPrediction>, GlinerXError> {
        if prepared.is_empty() {
            return Ok(Vec::new());
        }
        if prepared.len() == 1 {
            let item = &prepared[0];
            return self.predict_one(item.sequence, item.text, labels);
        }

        let batch = prepared.len();
        let max_seq_len = prepared
            .iter()
            .map(|item| item.tensors.input_ids.len())
            .max()
            .unwrap_or(0);
        let max_word_count = prepared
            .iter()
            .map(|item| item.tensors.words.len())
            .max()
            .unwrap_or(0);
        if max_seq_len == 0 || max_word_count == 0 {
            return Ok(Vec::new());
        }
        let num_spans = max_word_count * self.max_width;
        let num_labels = labels.len();

        let mut input_ids = vec![0_i64; batch * max_seq_len];
        let mut attention_mask = vec![0_i64; batch * max_seq_len];
        let mut words_mask = vec![0_i64; batch * max_seq_len];
        let mut text_lengths = vec![0_i64; batch];
        let mut span_idx = vec![0_i64; batch * num_spans * 2];
        let mut span_mask = vec![false; batch * num_spans];

        for (batch_idx, item) in prepared.iter().enumerate() {
            let seq_offset = batch_idx * max_seq_len;
            let input_len = item.tensors.input_ids.len();
            input_ids[seq_offset..seq_offset + input_len].copy_from_slice(&item.tensors.input_ids);
            attention_mask[seq_offset..seq_offset + input_len]
                .copy_from_slice(&item.tensors.attention_mask);
            words_mask[seq_offset..seq_offset + input_len]
                .copy_from_slice(&item.tensors.words_mask);
            text_lengths[batch_idx] = item.tensors.words.len() as i64;

            let (item_span_idx, item_span_mask) =
                build_span_tensors(item.tensors.words.len(), self.max_width);
            let span_idx_offset = batch_idx * num_spans * 2;
            let span_mask_offset = batch_idx * num_spans;
            span_idx[span_idx_offset..span_idx_offset + item_span_idx.len()]
                .copy_from_slice(&item_span_idx);
            span_mask[span_mask_offset..span_mask_offset + item_span_mask.len()]
                .copy_from_slice(&item_span_mask);
        }

        let input_ids_tensor = Tensor::from_array(([batch, max_seq_len], input_ids))
            .map_err(|error| GlinerXError::Inference(format!("input_ids: {error}")))?;
        let attention_mask_tensor = Tensor::from_array(([batch, max_seq_len], attention_mask))
            .map_err(|error| GlinerXError::Inference(format!("attention_mask: {error}")))?;
        let words_mask_tensor = Tensor::from_array(([batch, max_seq_len], words_mask))
            .map_err(|error| GlinerXError::Inference(format!("words_mask: {error}")))?;
        let text_lengths_tensor = Tensor::from_array(([batch, 1], text_lengths))
            .map_err(|error| GlinerXError::Inference(format!("text_lengths: {error}")))?;
        let span_idx_tensor = Tensor::from_array(([batch, num_spans, 2], span_idx))
            .map_err(|error| GlinerXError::Inference(format!("span_idx: {error}")))?;
        let span_mask_tensor = Tensor::from_array(([batch, num_spans], span_mask))
            .map_err(|error| GlinerXError::Inference(format!("span_mask: {error}")))?;

        let inputs = ort::inputs! {
            "input_ids" => input_ids_tensor,
            "attention_mask" => attention_mask_tensor,
            "words_mask" => words_mask_tensor,
            "text_lengths" => text_lengths_tensor,
            "span_idx" => span_idx_tensor,
            "span_mask" => span_mask_tensor,
        }
        .map_err(|error| GlinerXError::Inference(format!("build inputs: {error}")))?;
        let outputs = self
            .session
            .run(inputs)
            .map_err(|error| GlinerXError::Inference(format!("session run: {error}")))?;
        let logits = extract_logits(
            outputs
                .get("logits")
                .ok_or_else(|| GlinerXError::Inference("missing logits output".to_owned()))?,
        )?;

        let per_sequence_logits = num_spans * num_labels;
        let expected_len = batch * per_sequence_logits;
        if logits.len() < expected_len {
            return Err(GlinerXError::Inference(format!(
                "batched logits too short: expected {expected_len}, got {}",
                logits.len()
            )));
        }

        let mut predictions = Vec::new();
        for (batch_idx, item) in prepared.iter().enumerate() {
            let start = batch_idx * per_sequence_logits;
            let end = start + per_sequence_logits;
            predictions.extend(decode_predictions(
                item.sequence,
                item.text,
                &item.tensors.words,
                labels,
                self.max_width,
                self.threshold,
                &logits[start..end],
            )?);
        }
        Ok(predictions)
    }

    fn predict_one(
        &self,
        sequence: usize,
        text: &str,
        labels: &[String],
    ) -> Result<Vec<GlinerXPrediction>, GlinerXError> {
        if text.trim().is_empty() {
            return Ok(Vec::new());
        }
        let Some(text_tensors) = build_text_tensors(
            text,
            &self.tokenizer,
            labels,
            &self.ent_token,
            &self.sep_token,
            self.max_len,
        )?
        else {
            return Ok(Vec::new());
        };
        let seq_len = text_tensors.input_ids.len();
        let word_count = text_tensors.words.len();
        let num_spans = word_count * self.max_width;
        let (span_idx, span_mask) = build_span_tensors(word_count, self.max_width);

        let input_ids_tensor = Tensor::from_array(([1, seq_len], text_tensors.input_ids))
            .map_err(|error| GlinerXError::Inference(format!("input_ids: {error}")))?;
        let attention_mask_tensor = Tensor::from_array(([1, seq_len], text_tensors.attention_mask))
            .map_err(|error| GlinerXError::Inference(format!("attention_mask: {error}")))?;
        let words_mask_tensor = Tensor::from_array(([1, seq_len], text_tensors.words_mask))
            .map_err(|error| GlinerXError::Inference(format!("words_mask: {error}")))?;
        let text_lengths_tensor = Tensor::from_array(([1, 1], vec![word_count as i64]))
            .map_err(|error| GlinerXError::Inference(format!("text_lengths: {error}")))?;
        let span_idx_tensor = Tensor::from_array(([1, num_spans, 2], span_idx))
            .map_err(|error| GlinerXError::Inference(format!("span_idx: {error}")))?;
        let span_mask_tensor = Tensor::from_array(([1, num_spans], span_mask))
            .map_err(|error| GlinerXError::Inference(format!("span_mask: {error}")))?;

        let inputs = ort::inputs! {
            "input_ids" => input_ids_tensor,
            "attention_mask" => attention_mask_tensor,
            "words_mask" => words_mask_tensor,
            "text_lengths" => text_lengths_tensor,
            "span_idx" => span_idx_tensor,
            "span_mask" => span_mask_tensor,
        }
        .map_err(|error| GlinerXError::Inference(format!("build inputs: {error}")))?;
        let outputs = self
            .session
            .run(inputs)
            .map_err(|error| GlinerXError::Inference(format!("session run: {error}")))?;
        let logits = extract_logits(
            outputs
                .get("logits")
                .ok_or_else(|| GlinerXError::Inference("missing logits output".to_owned()))?,
        )?;

        decode_predictions(
            sequence,
            text,
            &text_tensors.words,
            labels,
            self.max_width,
            self.threshold,
            &logits,
        )
    }
}

fn normalize_labels(labels: &[&str]) -> Result<Vec<String>, GlinerXError> {
    let mut normalized = Vec::with_capacity(labels.len());
    for label in labels {
        let trimmed = label.trim();
        if trimmed.is_empty() {
            continue;
        }
        if !normalized
            .iter()
            .any(|existing: &String| existing.eq_ignore_ascii_case(trimmed))
        {
            normalized.push(trimmed.to_owned());
        }
    }
    if normalized.is_empty() {
        return Err(GlinerXError::InvalidInput(
            "at least one label is required".to_owned(),
        ));
    }
    Ok(normalized)
}

fn find_model_asset(model_dir: &Path) -> Result<PathBuf, GlinerXError> {
    if let Ok(value) = env::var(GLINER_X_ONNX_FILE_ENV) {
        if !value.trim().is_empty() {
            let path = PathBuf::from(value.trim());
            let candidate = if path.is_absolute() {
                path
            } else {
                model_dir.join(path)
            };
            return if candidate.is_file() {
                Ok(candidate)
            } else {
                Err(GlinerXError::ModelLoad(format!(
                    "{} points to missing ONNX asset: {}",
                    GLINER_X_ONNX_FILE_ENV,
                    candidate.display()
                )))
            };
        }
    }
    find_existing_path(
        model_dir,
        &[
            "onnx/model_quantized.onnx",
            "model_quantized.onnx",
            "onnx/model.onnx",
            "model.onnx",
        ],
    )
}

fn find_existing_path(base: &Path, candidates: &[&str]) -> Result<PathBuf, GlinerXError> {
    for candidate in candidates {
        let path = base.join(candidate);
        if path.is_file() {
            return Ok(path);
        }
    }
    Err(GlinerXError::ModelLoad(format!(
        "missing asset in {}: tried {}",
        base.display(),
        candidates.join(", ")
    )))
}

fn load_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Option<T> {
    let bytes = fs::read(path).ok()?;
    serde_json::from_slice(&bytes).ok()
}

fn gliner_x_thread_count() -> usize {
    env::var(GLINER_X_THREADS_ENV)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or_else(recommended_thread_count)
}

fn gliner_x_batch_size() -> usize {
    env::var(GLINER_X_BATCH_SIZE_ENV)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(DEFAULT_BATCH_SIZE)
}

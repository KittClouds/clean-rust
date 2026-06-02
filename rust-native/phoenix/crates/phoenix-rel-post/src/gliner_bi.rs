use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use ort::session::Session;
use ort::value::Tensor;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokenizers::Tokenizer;

use crate::gliner_bi_tensors::{
    build_constrained_span_tensors, build_label_set, build_span_tensors, build_text_tensors,
    decode_predictions, decode_predictions_for_word_ranges, decode_token_predictions,
    decode_token_predictions_for_word_ranges, extract_logits, word_ranges_for_input_spans,
    GlinerBiTextTensors,
};
use crate::ort_runtime::{load_session_with_intra_threads, recommended_thread_count};

const DEFAULT_BI_BATCH_SIZE: usize = 2;
const GLINER_BI_BATCH_SIZE_ENV: &str = "PHOENIX_GLINER_BI_BATCH_SIZE";

#[derive(Debug, Error)]
pub enum GlinerBiError {
    #[error("failed to load GLiNER Bi-Encoder model: {0}")]
    ModelLoad(String),
    #[error("GLiNER inference failed: {0}")]
    Inference(String),
    #[error("invalid GLiNER input: {0}")]
    InvalidInput(String),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlinerBiPrediction {
    pub text: String,
    pub label: String,
    pub span_start: usize,
    pub span_end: usize,
    pub score: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlinerBiSequencePrediction {
    pub sequence: usize,
    pub text: String,
    pub label: String,
    pub span_start: usize,
    pub span_end: usize,
    pub score: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlinerBiModelMetadata {
    pub max_width: usize,
    pub model_mode: String,
    pub model_path: String,
    pub text_tokenizer_path: String,
    pub labels_tokenizer_path: String,
    pub input_names: Vec<String>,
    pub output_names: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GlinerBiLabelSet {
    pub(crate) labels: Vec<String>,
    pub(crate) input_ids: Vec<i64>,
    pub(crate) attention_mask: Vec<i64>,
    pub(crate) max_label_len: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlinerBiInputSpan {
    pub start: usize,
    pub end: usize,
}

impl GlinerBiLabelSet {
    pub fn labels(&self) -> &[String] {
        &self.labels
    }

    pub fn label_count(&self) -> usize {
        self.labels.len()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum GlinerBiOverlapPolicy {
    KeepAll,
    HighestScore,
    LongestThenScore,
}

impl Default for GlinerBiOverlapPolicy {
    fn default() -> Self {
        Self::HighestScore
    }
}

impl GlinerBiOverlapPolicy {
    pub fn parse(value: &str) -> Result<Self, String> {
        match value.trim().to_ascii_lowercase().as_str() {
            "keep-all" | "keep_all" | "all" => Ok(Self::KeepAll),
            "highest-score" | "highest_score" | "flat" => Ok(Self::HighestScore),
            "longest-then-score" | "longest_then_score" | "longest" => Ok(Self::LongestThenScore),
            other => Err(format!("unknown GLiNER-BI overlap policy '{other}'")),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlinerBiPredictOptions {
    pub threshold: f32,
    pub overlap_policy: GlinerBiOverlapPolicy,
}

impl Default for GlinerBiPredictOptions {
    fn default() -> Self {
        Self {
            threshold: 0.5,
            overlap_policy: GlinerBiOverlapPolicy::HighestScore,
        }
    }
}

pub struct GlinerBiModel {
    session: Session,
    text_tokenizer: Tokenizer,
    labels_tokenizer: Tokenizer,
    max_width: usize,
    text_cls_id: i64,
    text_sep_id: i64,
    labels_cls_id: i64,
    labels_sep_id: i64,
    label_cache: Mutex<GlinerBiLabelCache>,
    span_cache: Mutex<GlinerBiSpanCache>,
    label_inputs: GlinerBiLabelInputs,
    output_mode: GlinerBiOutputMode,
    metadata: GlinerBiModelMetadata,
}

#[derive(Default)]
struct GlinerBiLabelCache {
    entries: Vec<(Vec<String>, Arc<GlinerBiLabelSet>)>,
}

#[derive(Clone, Debug)]
struct CachedSpanTensors {
    span_idx: Arc<Vec<i64>>,
    span_mask: Arc<Vec<bool>>,
}

struct PreparedBiText<'a> {
    sequence: usize,
    text: &'a str,
    tensors: GlinerBiTextTensors,
}

#[derive(Default)]
struct GlinerBiSpanCache {
    entries: Vec<(usize, CachedSpanTensors)>,
}

enum GlinerBiLabelInputs {
    Tokenized,
    Embeddings(Arc<GlinerBiLabelEmbeddingStore>),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum GlinerBiOutputMode {
    Span,
    Token,
}

impl GlinerBiOutputMode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Span => "span",
            Self::Token => "token",
        }
    }
}

#[derive(Clone, Debug)]
struct GlinerBiLabelEmbeddingStore {
    hidden_size: usize,
    labels: HashMap<String, Arc<Vec<f32>>>,
}

#[derive(Debug, Deserialize)]
struct GlinerBiLabelEmbeddingsFile {
    hidden_size: usize,
    labels: Vec<GlinerBiLabelEmbeddingRow>,
}

#[derive(Debug, Deserialize)]
struct GlinerBiLabelEmbeddingRow {
    label: String,
    embedding: Vec<f32>,
}

#[derive(Clone, Debug, Default, Deserialize)]
struct GlinerEncoderConfig {
    #[serde(default)]
    bos_token_id: Option<i64>,
    #[serde(default)]
    eos_token_id: Option<i64>,
    #[serde(default)]
    cls_token_id: Option<i64>,
    #[serde(default)]
    sep_token_id: Option<i64>,
}

#[derive(Clone, Debug, Default, Deserialize)]
struct GlinerLabelsEncoderConfig {
    #[serde(default)]
    bos_token_id: Option<i64>,
    #[serde(default)]
    eos_token_id: Option<i64>,
    #[serde(default)]
    cls_token_id: Option<i64>,
    #[serde(default)]
    sep_token_id: Option<i64>,
}

#[derive(Clone, Debug, Default, Deserialize)]
struct GlinerRootConfig {
    #[serde(default)]
    max_width: Option<usize>,
    #[serde(default)]
    bos_token_id: Option<i64>,
    #[serde(default)]
    eos_token_id: Option<i64>,
    #[serde(default)]
    cls_token_id: Option<i64>,
    #[serde(default)]
    sep_token_id: Option<i64>,
    #[serde(default)]
    encoder_config: Option<GlinerEncoderConfig>,
    #[serde(default)]
    labels_encoder_config: Option<GlinerLabelsEncoderConfig>,
}

impl GlinerBiModel {
    pub fn load(model_dir: &Path) -> Result<Self, GlinerBiError> {
        let model_path = find_model_asset(model_dir)?;
        let text_tokenizer_path =
            find_existing_path(model_dir, &["tokenizer.json", "onnx/tokenizer.json"])?;
        let labels_tokenizer_path = find_existing_path_optional(
            model_dir,
            &[
                "labels_tokenizer/tokenizer.json",
                "labels_tokenizer.json",
                "onnx/labels_tokenizer.json",
            ],
        )
        .unwrap_or_else(|| text_tokenizer_path.clone());

        let text_tokenizer = Tokenizer::from_file(&text_tokenizer_path)
            .map_err(|error| GlinerBiError::ModelLoad(format!("text tokenizer: {error}")))?;
        let labels_tokenizer = Tokenizer::from_file(&labels_tokenizer_path)
            .map_err(|error| GlinerBiError::ModelLoad(format!("labels tokenizer: {error}")))?;
        let session = load_session_with_intra_threads(&model_path, gliner_bi_thread_count())
            .map_err(|error| GlinerBiError::ModelLoad(format!("session: {error}")))?;
        let label_inputs = detect_label_input_mode(model_dir, &session)?;

        let root_config = load_json::<GlinerRootConfig>(&model_dir.join("gliner_config.json"))
            .or_else(|| load_json::<GlinerRootConfig>(&model_dir.join("config.json")))
            .unwrap_or_default();
        let max_width = root_config.max_width.unwrap_or(12);
        let root_cls_id = root_config.cls_token_id.or(root_config.bos_token_id);
        let root_sep_id = root_config.sep_token_id.or(root_config.eos_token_id);
        let text_cls_id = root_config
            .encoder_config
            .as_ref()
            .and_then(|config| config.cls_token_id.or(config.bos_token_id))
            .or(root_cls_id)
            .unwrap_or(50281);
        let text_sep_id = root_config
            .encoder_config
            .as_ref()
            .and_then(|config| config.sep_token_id.or(config.eos_token_id))
            .or(root_sep_id)
            .unwrap_or(50282);
        let labels_cls_id = root_config
            .labels_encoder_config
            .as_ref()
            .and_then(|config| config.cls_token_id.or(config.bos_token_id))
            .or(root_cls_id)
            .unwrap_or(101);
        let labels_sep_id = root_config
            .labels_encoder_config
            .as_ref()
            .and_then(|config| config.sep_token_id.or(config.eos_token_id))
            .or(root_sep_id)
            .unwrap_or(102);

        let input_names = session
            .inputs
            .iter()
            .map(|input| input.name.clone())
            .collect::<Vec<_>>();
        let output_mode = detect_output_mode(&input_names);
        let metadata = GlinerBiModelMetadata {
            max_width,
            model_mode: output_mode.as_str().to_owned(),
            model_path: model_path.display().to_string(),
            text_tokenizer_path: text_tokenizer_path.display().to_string(),
            labels_tokenizer_path: labels_tokenizer_path.display().to_string(),
            input_names,
            output_names: session
                .outputs
                .iter()
                .map(|output| output.name.clone())
                .collect(),
        };

        Ok(Self {
            session,
            text_tokenizer,
            labels_tokenizer,
            max_width,
            text_cls_id,
            text_sep_id,
            labels_cls_id,
            labels_sep_id,
            label_cache: Mutex::default(),
            span_cache: Mutex::default(),
            label_inputs,
            output_mode,
            metadata,
        })
    }

    pub fn metadata(&self) -> &GlinerBiModelMetadata {
        &self.metadata
    }

    pub fn prepare_labels(&self, labels: &[String]) -> Result<GlinerBiLabelSet, GlinerBiError> {
        build_label_set(
            labels,
            &self.labels_tokenizer,
            self.labels_cls_id,
            self.labels_sep_id,
        )
    }

    pub fn predict(
        &self,
        text: &str,
        labels: &[String],
        threshold: f32,
        flat_ner: bool,
    ) -> Result<Vec<GlinerBiPrediction>, GlinerBiError> {
        if text.trim().is_empty() || labels.is_empty() {
            return Ok(Vec::new());
        }
        let label_set = self.cached_label_set(labels)?;
        let options = GlinerBiPredictOptions {
            threshold,
            overlap_policy: if flat_ner {
                GlinerBiOverlapPolicy::HighestScore
            } else {
                GlinerBiOverlapPolicy::KeepAll
            },
        };
        self.predict_with_label_set(text, label_set.as_ref(), &options)
    }

    pub fn predict_with_options(
        &self,
        text: &str,
        labels: &[String],
        options: &GlinerBiPredictOptions,
    ) -> Result<Vec<GlinerBiPrediction>, GlinerBiError> {
        if text.trim().is_empty() || labels.is_empty() {
            return Ok(Vec::new());
        }
        let label_set = self.cached_label_set(labels)?;
        self.predict_with_label_set(text, label_set.as_ref(), options)
    }

    pub fn predict_texts_with_options(
        &self,
        texts: &[&str],
        labels: &[String],
        options: &GlinerBiPredictOptions,
    ) -> Result<Vec<GlinerBiSequencePrediction>, GlinerBiError> {
        if texts.is_empty() || labels.is_empty() {
            return Ok(Vec::new());
        }
        let label_set = self.cached_label_set(labels)?;
        self.predict_texts_with_label_set(texts, label_set.as_ref(), options)
    }

    pub fn predict_texts_with_label_set(
        &self,
        texts: &[&str],
        label_set: &GlinerBiLabelSet,
        options: &GlinerBiPredictOptions,
    ) -> Result<Vec<GlinerBiSequencePrediction>, GlinerBiError> {
        if texts.is_empty() || label_set.label_count() == 0 {
            return Ok(Vec::new());
        }
        let batch_size = gliner_bi_batch_size();
        if batch_size <= 1 || texts.len() <= 1 || self.output_mode == GlinerBiOutputMode::Token {
            return self.predict_texts_sequential(texts, label_set, options);
        }

        let mut prepared = Vec::with_capacity(texts.len());
        for (sequence, text) in texts.iter().enumerate() {
            if text.trim().is_empty() {
                continue;
            }
            let Some(tensors) = build_text_tensors(
                text,
                &self.text_tokenizer,
                self.text_cls_id,
                self.text_sep_id,
            )?
            else {
                continue;
            };
            prepared.push(PreparedBiText {
                sequence,
                text,
                tensors,
            });
        }
        prepared.sort_by_key(|item| (item.tensors.seq_len(), item.tensors.word_count()));

        let mut predictions = Vec::new();
        for chunk in prepared.chunks(batch_size) {
            predictions.extend(self.predict_prepared_span_batch(chunk, label_set, options)?);
        }
        Ok(predictions)
    }

    pub fn predict_with_label_set(
        &self,
        text: &str,
        label_set: &GlinerBiLabelSet,
        options: &GlinerBiPredictOptions,
    ) -> Result<Vec<GlinerBiPrediction>, GlinerBiError> {
        if text.trim().is_empty() || label_set.label_count() == 0 {
            return Ok(Vec::new());
        }
        let Some(text_tensors) = build_text_tensors(
            text,
            &self.text_tokenizer,
            self.text_cls_id,
            self.text_sep_id,
        )?
        else {
            return Ok(Vec::new());
        };
        match self.output_mode {
            GlinerBiOutputMode::Span => {
                let num_words = text_tensors.word_count();
                let span_tensors = self.cached_span_tensors(num_words)?;
                let num_spans = num_words * self.max_width;
                self.predict_with_span_tensors(
                    text,
                    label_set,
                    options,
                    text_tensors,
                    span_tensors.span_idx.as_ref().clone(),
                    span_tensors.span_mask.as_ref().clone(),
                    num_spans,
                    None,
                )
            }
            GlinerBiOutputMode::Token => {
                self.predict_with_token_tensors(text, label_set, options, text_tensors, None)
            }
        }
    }

    fn predict_texts_sequential(
        &self,
        texts: &[&str],
        label_set: &GlinerBiLabelSet,
        options: &GlinerBiPredictOptions,
    ) -> Result<Vec<GlinerBiSequencePrediction>, GlinerBiError> {
        let mut predictions = Vec::new();
        for (sequence, text) in texts.iter().enumerate() {
            predictions.extend(
                self.predict_with_label_set(text, label_set, options)?
                    .into_iter()
                    .map(|prediction| sequence_prediction(sequence, prediction)),
            );
        }
        Ok(predictions)
    }

    fn predict_prepared_span_batch(
        &self,
        prepared: &[PreparedBiText<'_>],
        label_set: &GlinerBiLabelSet,
        options: &GlinerBiPredictOptions,
    ) -> Result<Vec<GlinerBiSequencePrediction>, GlinerBiError> {
        if prepared.is_empty() {
            return Ok(Vec::new());
        }
        if prepared.len() == 1 {
            let item = &prepared[0];
            return Ok(self
                .predict_with_label_set(item.text, label_set, options)?
                .into_iter()
                .map(|prediction| sequence_prediction(item.sequence, prediction))
                .collect());
        }

        let batch = prepared.len();
        let max_seq_len = prepared
            .iter()
            .map(|item| item.tensors.seq_len())
            .max()
            .unwrap_or(0);
        let max_word_count = prepared
            .iter()
            .map(|item| item.tensors.word_count())
            .max()
            .unwrap_or(0);
        if max_seq_len == 0 || max_word_count == 0 {
            return Ok(Vec::new());
        }
        let num_spans = max_word_count * self.max_width;
        let num_labels = label_set.label_count();

        let mut input_ids = vec![0_i64; batch * max_seq_len];
        let mut attention_mask = vec![0_i64; batch * max_seq_len];
        let mut words_mask = vec![0_i64; batch * max_seq_len];
        let mut text_lengths = vec![0_i64; batch];
        let mut span_idx = vec![0_i64; batch * num_spans * 2];
        let mut span_mask = vec![false; batch * num_spans];

        for (batch_idx, item) in prepared.iter().enumerate() {
            let seq_offset = batch_idx * max_seq_len;
            let input_len = item.tensors.seq_len();
            input_ids[seq_offset..seq_offset + input_len].copy_from_slice(&item.tensors.input_ids);
            attention_mask[seq_offset..seq_offset + input_len]
                .copy_from_slice(&item.tensors.attention_mask);
            words_mask[seq_offset..seq_offset + input_len]
                .copy_from_slice(&item.tensors.words_mask);
            text_lengths[batch_idx] = item.tensors.word_count() as i64;

            let (item_span_idx, item_span_mask) =
                build_span_tensors(item.tensors.word_count(), self.max_width);
            let span_idx_offset = batch_idx * num_spans * 2;
            let span_mask_offset = batch_idx * num_spans;
            span_idx[span_idx_offset..span_idx_offset + item_span_idx.len()]
                .copy_from_slice(&item_span_idx);
            span_mask[span_mask_offset..span_mask_offset + item_span_mask.len()]
                .copy_from_slice(&item_span_mask);
        }

        let input_ids_tensor = Tensor::from_array(([batch, max_seq_len], input_ids))
            .map_err(|error| GlinerBiError::Inference(format!("input_ids: {error}")))?;
        let attention_mask_tensor = Tensor::from_array(([batch, max_seq_len], attention_mask))
            .map_err(|error| GlinerBiError::Inference(format!("attention_mask: {error}")))?;
        let words_mask_tensor = Tensor::from_array(([batch, max_seq_len], words_mask))
            .map_err(|error| GlinerBiError::Inference(format!("words_mask: {error}")))?;
        let text_lengths_tensor = Tensor::from_array(([batch, 1], text_lengths))
            .map_err(|error| GlinerBiError::Inference(format!("text_lengths: {error}")))?;
        let span_idx_tensor = Tensor::from_array(([batch, num_spans, 2], span_idx))
            .map_err(|error| GlinerBiError::Inference(format!("span_idx: {error}")))?;
        let span_mask_tensor = Tensor::from_array(([batch, num_spans], span_mask))
            .map_err(|error| GlinerBiError::Inference(format!("span_mask: {error}")))?;

        let outputs = match &self.label_inputs {
            GlinerBiLabelInputs::Tokenized => {
                let labels_input_ids_tensor = Tensor::from_array((
                    [label_set.label_count(), label_set.max_label_len],
                    label_set.input_ids.clone(),
                ))
                .map_err(|error| GlinerBiError::Inference(format!("labels_input_ids: {error}")))?;
                let labels_attention_mask_tensor = Tensor::from_array((
                    [label_set.label_count(), label_set.max_label_len],
                    label_set.attention_mask.clone(),
                ))
                .map_err(|error| {
                    GlinerBiError::Inference(format!("labels_attention_mask: {error}"))
                })?;

                let inputs = ort::inputs! {
                    "input_ids" => input_ids_tensor,
                    "attention_mask" => attention_mask_tensor,
                    "words_mask" => words_mask_tensor,
                    "text_lengths" => text_lengths_tensor,
                    "span_idx" => span_idx_tensor,
                    "span_mask" => span_mask_tensor,
                    "labels_input_ids" => labels_input_ids_tensor,
                    "labels_attention_mask" => labels_attention_mask_tensor,
                }
                .map_err(|error| GlinerBiError::Inference(format!("build inputs: {error}")))?;

                self.session
                    .run(inputs)
                    .map_err(|error| GlinerBiError::Inference(format!("session run: {error}")))?
            }
            GlinerBiLabelInputs::Embeddings(store) => {
                let labels_embeds = store.embeddings_for(&label_set.labels)?;
                let labels_embeds_tensor = Tensor::from_array((
                    [label_set.label_count(), store.hidden_size],
                    labels_embeds,
                ))
                .map_err(|error| GlinerBiError::Inference(format!("labels_embeds: {error}")))?;

                let inputs = ort::inputs! {
                    "input_ids" => input_ids_tensor,
                    "attention_mask" => attention_mask_tensor,
                    "words_mask" => words_mask_tensor,
                    "text_lengths" => text_lengths_tensor,
                    "span_idx" => span_idx_tensor,
                    "span_mask" => span_mask_tensor,
                    "labels_embeds" => labels_embeds_tensor,
                }
                .map_err(|error| GlinerBiError::Inference(format!("build inputs: {error}")))?;

                self.session
                    .run(inputs)
                    .map_err(|error| GlinerBiError::Inference(format!("session run: {error}")))?
            }
        };
        let logits = extract_logits(
            outputs
                .get("logits")
                .ok_or_else(|| GlinerBiError::Inference("missing logits output".to_owned()))?,
        )?;

        let per_sequence_logits = num_spans * num_labels;
        let expected_len = batch * per_sequence_logits;
        if logits.len() < expected_len {
            return Err(GlinerBiError::Inference(format!(
                "batched logits too short: expected {expected_len}, got {}",
                logits.len()
            )));
        }

        let mut predictions = Vec::new();
        for (batch_idx, item) in prepared.iter().enumerate() {
            let start = batch_idx * per_sequence_logits;
            let end = start + per_sequence_logits;
            predictions.extend(
                decode_predictions(
                    item.text,
                    &item.tensors.words,
                    label_set,
                    self.max_width,
                    options.threshold,
                    options.overlap_policy,
                    &logits[start..end],
                )?
                .into_iter()
                .map(|prediction| sequence_prediction(item.sequence, prediction)),
            );
        }
        Ok(predictions)
    }

    pub fn predict_constrained(
        &self,
        text: &str,
        labels: &[String],
        spans: &[GlinerBiInputSpan],
        options: &GlinerBiPredictOptions,
    ) -> Result<Vec<GlinerBiPrediction>, GlinerBiError> {
        if text.trim().is_empty() || labels.is_empty() || spans.is_empty() {
            return Ok(Vec::new());
        }
        let label_set = self.cached_label_set(labels)?;
        self.predict_constrained_with_label_set(text, label_set.as_ref(), spans, options)
    }

    pub fn predict_constrained_with_label_set(
        &self,
        text: &str,
        label_set: &GlinerBiLabelSet,
        spans: &[GlinerBiInputSpan],
        options: &GlinerBiPredictOptions,
    ) -> Result<Vec<GlinerBiPrediction>, GlinerBiError> {
        if text.trim().is_empty() || label_set.label_count() == 0 || spans.is_empty() {
            return Ok(Vec::new());
        }
        let Some(text_tensors) = build_text_tensors(
            text,
            &self.text_tokenizer,
            self.text_cls_id,
            self.text_sep_id,
        )?
        else {
            return Ok(Vec::new());
        };
        match self.output_mode {
            GlinerBiOutputMode::Span => {
                let (span_idx, span_mask, word_ranges) =
                    build_constrained_span_tensors(&text_tensors.words, spans, self.max_width);
                if word_ranges.is_empty() {
                    return Ok(Vec::new());
                }
                let num_spans = span_mask.len();
                self.predict_with_span_tensors(
                    text,
                    label_set,
                    options,
                    text_tensors,
                    span_idx,
                    span_mask,
                    num_spans,
                    Some(&word_ranges),
                )
            }
            GlinerBiOutputMode::Token => {
                let word_ranges = word_ranges_for_input_spans(&text_tensors.words, spans);
                if word_ranges.is_empty() {
                    return Ok(Vec::new());
                }
                self.predict_with_token_tensors(
                    text,
                    label_set,
                    options,
                    text_tensors,
                    Some(&word_ranges),
                )
            }
        }
    }

    fn predict_with_span_tensors(
        &self,
        text: &str,
        label_set: &GlinerBiLabelSet,
        options: &GlinerBiPredictOptions,
        text_tensors: GlinerBiTextTensors,
        span_idx: Vec<i64>,
        span_mask: Vec<bool>,
        num_spans: usize,
        constrained_ranges: Option<&[(usize, usize)]>,
    ) -> Result<Vec<GlinerBiPrediction>, GlinerBiError> {
        let text_seq_len = text_tensors.seq_len();
        let num_words = text_tensors.word_count();
        if num_spans == 0 {
            return Ok(Vec::new());
        }
        let input_ids_tensor = Tensor::from_array(([1, text_seq_len], text_tensors.input_ids))
            .map_err(|error| GlinerBiError::Inference(format!("input_ids: {error}")))?;
        let attention_mask_tensor =
            Tensor::from_array(([1, text_seq_len], text_tensors.attention_mask))
                .map_err(|error| GlinerBiError::Inference(format!("attention_mask: {error}")))?;
        let words_mask_tensor = Tensor::from_array(([1, text_seq_len], text_tensors.words_mask))
            .map_err(|error| GlinerBiError::Inference(format!("words_mask: {error}")))?;
        let text_lengths_tensor = Tensor::from_array(([1, 1], vec![num_words as i64]))
            .map_err(|error| GlinerBiError::Inference(format!("text_lengths: {error}")))?;
        let span_idx_tensor = Tensor::from_array(([1, num_spans, 2], span_idx))
            .map_err(|error| GlinerBiError::Inference(format!("span_idx: {error}")))?;
        let span_mask_tensor = Tensor::from_array(([1, num_spans], span_mask))
            .map_err(|error| GlinerBiError::Inference(format!("span_mask: {error}")))?;
        let outputs = match &self.label_inputs {
            GlinerBiLabelInputs::Tokenized => {
                let labels_input_ids_tensor = Tensor::from_array((
                    [label_set.label_count(), label_set.max_label_len],
                    label_set.input_ids.clone(),
                ))
                .map_err(|error| GlinerBiError::Inference(format!("labels_input_ids: {error}")))?;
                let labels_attention_mask_tensor = Tensor::from_array((
                    [label_set.label_count(), label_set.max_label_len],
                    label_set.attention_mask.clone(),
                ))
                .map_err(|error| {
                    GlinerBiError::Inference(format!("labels_attention_mask: {error}"))
                })?;

                let inputs = ort::inputs! {
                    "input_ids" => input_ids_tensor,
                    "attention_mask" => attention_mask_tensor,
                    "words_mask" => words_mask_tensor,
                    "text_lengths" => text_lengths_tensor,
                    "span_idx" => span_idx_tensor,
                    "span_mask" => span_mask_tensor,
                    "labels_input_ids" => labels_input_ids_tensor,
                    "labels_attention_mask" => labels_attention_mask_tensor,
                }
                .map_err(|error| GlinerBiError::Inference(format!("build inputs: {error}")))?;

                self.session
                    .run(inputs)
                    .map_err(|error| GlinerBiError::Inference(format!("session run: {error}")))?
            }
            GlinerBiLabelInputs::Embeddings(store) => {
                let labels_embeds = store.embeddings_for(&label_set.labels)?;
                let labels_embeds_tensor = Tensor::from_array((
                    [label_set.label_count(), store.hidden_size],
                    labels_embeds,
                ))
                .map_err(|error| GlinerBiError::Inference(format!("labels_embeds: {error}")))?;

                let inputs = ort::inputs! {
                    "input_ids" => input_ids_tensor,
                    "attention_mask" => attention_mask_tensor,
                    "words_mask" => words_mask_tensor,
                    "text_lengths" => text_lengths_tensor,
                    "span_idx" => span_idx_tensor,
                    "span_mask" => span_mask_tensor,
                    "labels_embeds" => labels_embeds_tensor,
                }
                .map_err(|error| GlinerBiError::Inference(format!("build inputs: {error}")))?;

                self.session
                    .run(inputs)
                    .map_err(|error| GlinerBiError::Inference(format!("session run: {error}")))?
            }
        };
        let logits = extract_logits(
            outputs
                .get("logits")
                .ok_or_else(|| GlinerBiError::Inference("missing logits output".to_owned()))?,
        )?;
        if let Some(word_ranges) = constrained_ranges {
            decode_predictions_for_word_ranges(
                text,
                &text_tensors.words,
                label_set,
                self.max_width,
                word_ranges,
                options.threshold,
                options.overlap_policy,
                &logits,
            )
        } else {
            decode_predictions(
                text,
                &text_tensors.words,
                label_set,
                self.max_width,
                options.threshold,
                options.overlap_policy,
                &logits,
            )
        }
    }

    fn predict_with_token_tensors(
        &self,
        text: &str,
        label_set: &GlinerBiLabelSet,
        options: &GlinerBiPredictOptions,
        text_tensors: GlinerBiTextTensors,
        constrained_ranges: Option<&[(usize, usize)]>,
    ) -> Result<Vec<GlinerBiPrediction>, GlinerBiError> {
        let text_seq_len = text_tensors.seq_len();
        let num_words = text_tensors.word_count();
        let input_ids_tensor = Tensor::from_array(([1, text_seq_len], text_tensors.input_ids))
            .map_err(|error| GlinerBiError::Inference(format!("input_ids: {error}")))?;
        let attention_mask_tensor =
            Tensor::from_array(([1, text_seq_len], text_tensors.attention_mask))
                .map_err(|error| GlinerBiError::Inference(format!("attention_mask: {error}")))?;
        let words_mask_tensor = Tensor::from_array(([1, text_seq_len], text_tensors.words_mask))
            .map_err(|error| GlinerBiError::Inference(format!("words_mask: {error}")))?;
        let text_lengths_tensor = Tensor::from_array(([1, 1], vec![num_words as i64]))
            .map_err(|error| GlinerBiError::Inference(format!("text_lengths: {error}")))?;

        let outputs = match &self.label_inputs {
            GlinerBiLabelInputs::Tokenized => {
                let labels_input_ids_tensor = Tensor::from_array((
                    [label_set.label_count(), label_set.max_label_len],
                    label_set.input_ids.clone(),
                ))
                .map_err(|error| GlinerBiError::Inference(format!("labels_input_ids: {error}")))?;
                let labels_attention_mask_tensor = Tensor::from_array((
                    [label_set.label_count(), label_set.max_label_len],
                    label_set.attention_mask.clone(),
                ))
                .map_err(|error| {
                    GlinerBiError::Inference(format!("labels_attention_mask: {error}"))
                })?;

                let inputs = ort::inputs! {
                    "input_ids" => input_ids_tensor,
                    "attention_mask" => attention_mask_tensor,
                    "words_mask" => words_mask_tensor,
                    "text_lengths" => text_lengths_tensor,
                    "labels_input_ids" => labels_input_ids_tensor,
                    "labels_attention_mask" => labels_attention_mask_tensor,
                }
                .map_err(|error| GlinerBiError::Inference(format!("build inputs: {error}")))?;

                self.session
                    .run(inputs)
                    .map_err(|error| GlinerBiError::Inference(format!("session run: {error}")))?
            }
            GlinerBiLabelInputs::Embeddings(store) => {
                let labels_embeds = store.embeddings_for(&label_set.labels)?;
                let labels_embeds_tensor = Tensor::from_array((
                    [label_set.label_count(), store.hidden_size],
                    labels_embeds,
                ))
                .map_err(|error| GlinerBiError::Inference(format!("labels_embeds: {error}")))?;

                let inputs = ort::inputs! {
                    "input_ids" => input_ids_tensor,
                    "attention_mask" => attention_mask_tensor,
                    "words_mask" => words_mask_tensor,
                    "text_lengths" => text_lengths_tensor,
                    "labels_embeds" => labels_embeds_tensor,
                }
                .map_err(|error| GlinerBiError::Inference(format!("build inputs: {error}")))?;

                self.session
                    .run(inputs)
                    .map_err(|error| GlinerBiError::Inference(format!("session run: {error}")))?
            }
        };
        let logits = extract_logits(
            outputs
                .get("logits")
                .ok_or_else(|| GlinerBiError::Inference("missing logits output".to_owned()))?,
        )?;
        if let Some(word_ranges) = constrained_ranges {
            decode_token_predictions_for_word_ranges(
                text,
                &text_tensors.words,
                label_set,
                word_ranges,
                options.threshold,
                options.overlap_policy,
                &logits,
            )
        } else {
            decode_token_predictions(
                text,
                &text_tensors.words,
                label_set,
                options.threshold,
                options.overlap_policy,
                &logits,
            )
        }
    }

    fn cached_label_set(&self, labels: &[String]) -> Result<Arc<GlinerBiLabelSet>, GlinerBiError> {
        {
            let cache = self.label_cache.lock().map_err(|_| {
                GlinerBiError::Inference("GLiNER-BI label cache lock poisoned".to_owned())
            })?;
            if let Some((_, label_set)) = cache
                .entries
                .iter()
                .find(|(cached_labels, _)| cached_labels.as_slice() == labels)
            {
                return Ok(Arc::clone(label_set));
            }
        }

        let label_set = Arc::new(self.prepare_labels(labels)?);
        let mut cache = self.label_cache.lock().map_err(|_| {
            GlinerBiError::Inference("GLiNER-BI label cache lock poisoned".to_owned())
        })?;
        if let Some((_, existing)) = cache
            .entries
            .iter()
            .find(|(cached_labels, _)| cached_labels.as_slice() == labels)
        {
            return Ok(Arc::clone(existing));
        }
        if cache.entries.len() >= 16 {
            cache.entries.remove(0);
        }
        cache
            .entries
            .push((labels.to_vec(), Arc::clone(&label_set)));
        Ok(label_set)
    }

    fn cached_span_tensors(&self, num_words: usize) -> Result<CachedSpanTensors, GlinerBiError> {
        {
            let cache = self.span_cache.lock().map_err(|_| {
                GlinerBiError::Inference("GLiNER-BI span cache lock poisoned".to_owned())
            })?;
            if let Some((_, tensors)) = cache
                .entries
                .iter()
                .find(|(word_count, _)| *word_count == num_words)
            {
                return Ok(tensors.clone());
            }
        }

        let (span_idx, span_mask) = build_span_tensors(num_words, self.max_width);
        let tensors = CachedSpanTensors {
            span_idx: Arc::new(span_idx),
            span_mask: Arc::new(span_mask),
        };
        let mut cache = self.span_cache.lock().map_err(|_| {
            GlinerBiError::Inference("GLiNER-BI span cache lock poisoned".to_owned())
        })?;
        if let Some((_, existing)) = cache
            .entries
            .iter()
            .find(|(word_count, _)| *word_count == num_words)
        {
            return Ok(existing.clone());
        }
        if cache.entries.len() >= 128 {
            cache.entries.remove(0);
        }
        cache.entries.push((num_words, tensors.clone()));
        Ok(tensors)
    }
}

impl GlinerBiLabelEmbeddingStore {
    fn load(model_dir: &Path) -> Result<Self, GlinerBiError> {
        let path = env::var("PHOENIX_GLINER_BI_LABEL_EMBEDDINGS")
            .map(PathBuf::from)
            .unwrap_or_else(|_| model_dir.join("labels_embeddings.json"));
        let contents = fs::read_to_string(&path).map_err(|error| {
            GlinerBiError::ModelLoad(format!(
                "failed to read label embeddings {}: {error}",
                path.display()
            ))
        })?;
        let file: GlinerBiLabelEmbeddingsFile =
            serde_json::from_str(&contents).map_err(|error| {
                GlinerBiError::ModelLoad(format!(
                    "failed to parse label embeddings {}: {error}",
                    path.display()
                ))
            })?;
        let mut labels = HashMap::with_capacity(file.labels.len());
        for row in file.labels {
            if row.embedding.len() != file.hidden_size {
                return Err(GlinerBiError::ModelLoad(format!(
                    "label embedding '{}' has width {}, expected {}",
                    row.label,
                    row.embedding.len(),
                    file.hidden_size
                )));
            }
            labels.insert(row.label, Arc::new(row.embedding));
        }
        Ok(Self {
            hidden_size: file.hidden_size,
            labels,
        })
    }

    fn embeddings_for(&self, labels: &[String]) -> Result<Vec<f32>, GlinerBiError> {
        let mut out = Vec::with_capacity(labels.len() * self.hidden_size);
        for label in labels {
            let Some(embedding) = self.labels.get(label.as_str()) else {
                return Err(GlinerBiError::InvalidInput(format!(
                    "no precomputed GLiNER-BI label embedding for '{label}'"
                )));
            };
            out.extend_from_slice(embedding);
        }
        Ok(out)
    }
}

fn find_model_asset(root: &Path) -> Result<PathBuf, GlinerBiError> {
    if let Ok(file_name) = env::var("PHOENIX_GLINER_BI_ONNX_FILE") {
        let path = root.join(file_name);
        if path.exists() {
            return Ok(path);
        }
        return Err(GlinerBiError::ModelLoad(format!(
            "PHOENIX_GLINER_BI_ONNX_FILE points to missing asset under {}",
            root.display()
        )));
    }
    find_existing_path(
        root,
        &[
            "model_label_embeds_quantized.onnx",
            "onnx/model_label_embeds_quantized.onnx",
            "model_label_embeds.onnx",
            "onnx/model_label_embeds.onnx",
            "model_quantized.onnx",
            "onnx/model_quantized.onnx",
            "model.onnx",
            "onnx/model.onnx",
        ],
    )
}

fn detect_label_input_mode(
    model_dir: &Path,
    session: &Session,
) -> Result<GlinerBiLabelInputs, GlinerBiError> {
    let has_label_embeds = session
        .inputs
        .iter()
        .any(|input| input.name == "labels_embeds");
    if has_label_embeds {
        return Ok(GlinerBiLabelInputs::Embeddings(Arc::new(
            GlinerBiLabelEmbeddingStore::load(model_dir)?,
        )));
    }
    Ok(GlinerBiLabelInputs::Tokenized)
}

fn detect_output_mode(input_names: &[String]) -> GlinerBiOutputMode {
    let has_span_idx = input_names.iter().any(|name| name == "span_idx");
    let has_span_mask = input_names.iter().any(|name| name == "span_mask");
    if has_span_idx && has_span_mask {
        GlinerBiOutputMode::Span
    } else {
        GlinerBiOutputMode::Token
    }
}

fn gliner_bi_thread_count() -> usize {
    env::var("PHOENIX_GLINER_BI_THREADS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|&value| value > 0)
        .unwrap_or_else(recommended_thread_count)
}

fn gliner_bi_batch_size() -> usize {
    env::var(GLINER_BI_BATCH_SIZE_ENV)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|&value| value > 0)
        .unwrap_or(DEFAULT_BI_BATCH_SIZE)
}

fn sequence_prediction(
    sequence: usize,
    prediction: GlinerBiPrediction,
) -> GlinerBiSequencePrediction {
    GlinerBiSequencePrediction {
        sequence,
        text: prediction.text,
        label: prediction.label,
        span_start: prediction.span_start,
        span_end: prediction.span_end,
        score: prediction.score,
    }
}

fn load_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Option<T> {
    let contents = fs::read_to_string(path).ok()?;
    serde_json::from_str(&contents).ok()
}

fn find_existing_path(dir: &Path, candidates: &[&str]) -> Result<PathBuf, GlinerBiError> {
    for &candidate in candidates {
        let path = dir.join(candidate);
        if path.exists() {
            return Ok(path);
        }
    }
    Err(GlinerBiError::ModelLoad(format!(
        "none of the candidates {:?} found in {}",
        candidates,
        dir.display()
    )))
}

fn find_existing_path_optional(dir: &Path, candidates: &[&str]) -> Option<PathBuf> {
    candidates
        .iter()
        .map(|candidate| dir.join(candidate))
        .find(|path| path.exists())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlap_policy_parser_accepts_cli_friendly_names() {
        assert_eq!(
            GlinerBiOverlapPolicy::parse("keep-all").unwrap(),
            GlinerBiOverlapPolicy::KeepAll
        );
        assert_eq!(
            GlinerBiOverlapPolicy::parse("longest").unwrap(),
            GlinerBiOverlapPolicy::LongestThenScore
        );
    }

    #[test]
    fn model_asset_prefers_precomputed_label_embeddings() {
        let root = std::env::temp_dir().join(format!(
            "phoenix-gliner-bi-asset-test-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("model.onnx"), b"slow-tokenized-model").unwrap();
        std::fs::write(
            root.join("model_label_embeds_quantized.onnx"),
            b"fast-precomputed-labels-model",
        )
        .unwrap();
        std::env::remove_var("PHOENIX_GLINER_BI_ONNX_FILE");

        let selected = find_model_asset(&root).unwrap();

        assert_eq!(
            selected.file_name().and_then(|value| value.to_str()),
            Some("model_label_embeds_quantized.onnx")
        );
        let _ = std::fs::remove_dir_all(root);
    }
}

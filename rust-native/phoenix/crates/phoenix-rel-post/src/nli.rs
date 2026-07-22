use std::env;
use std::fs::File;
use std::path::{Path, PathBuf};

use hashbrown::HashMap;
use memmap2::Mmap;
use ort::session::Session;
use ort::value::Tensor;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokenizers::{tokenizer::TruncationDirection, EncodeInput, PaddingDirection, Tokenizer};

use crate::ort_runtime::{load_nli_session, nli_ort_preference, resolved_ort_dylib_path};

const DEFAULT_NLI_MAX_LENGTH: usize = 2048;
const MAX_REASONABLE_NLI_LENGTH: usize = 8192;
const REVERSE_DIRECTION_MIN_ENTAILMENT: f32 = 0.50;
const MODEL_FILE_ENV: &str = "PHOENIX_NLI_ONNX_FILE";
const MODEL_CANDIDATES: &[&str] = &[
    "model.onnx",
    "model_quantized.onnx",
    "model_uint8.onnx",
    "model_int8.onnx",
    "model_q4f16.onnx",
    "model_q4.onnx",
    "model_bnb4.onnx",
    "model_fp16.onnx",
    "onnx/model_quantized.onnx",
    "onnx/model_uint8.onnx",
    "onnx/model_int8.onnx",
    "onnx/model_q4f16.onnx",
    "onnx/model_q4.onnx",
    "onnx/model_bnb4.onnx",
    "onnx/model_fp16.onnx",
    "onnx/model.onnx",
];
const TOKENIZER_CANDIDATES: &[&str] =
    &["tokenizer.json", "onnx/tokenizer.json", "../tokenizer.json"];
const CONFIG_CANDIDATES: &[&str] = &["config.json", "onnx/config.json", "../config.json"];
const TOKENIZER_CONFIG_CANDIDATES: &[&str] = &[
    "tokenizer_config.json",
    "onnx/tokenizer_config.json",
    "../tokenizer_config.json",
];
const EXPORT_METADATA_CANDIDATES: &[&str] = &[
    "export_metadata.json",
    "onnx/export_metadata.json",
    "../export_metadata.json",
];

#[derive(Debug, thiserror::Error)]
pub enum NliError {
    #[error("failed to load NLI model: {0}")]
    ModelLoad(String),
    #[error("NLI inference failed: {0}")]
    Inference(String),
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NliScores {
    pub contradiction: f32,
    pub entailment: f32,
    pub neutral: f32,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NliPairJudgment {
    pub forward: NliScores,
    pub reverse: Option<NliScores>,
    pub used_reverse: bool,
    pub best_hypothesis: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NliExportMetadata {
    #[serde(default)]
    contradiction_idx: Option<usize>,
    #[serde(default)]
    entailment_idx: Option<usize>,
    #[serde(default)]
    neutral_idx: Option<usize>,
    #[serde(default)]
    max_length: Option<usize>,
}

#[derive(Clone, Copy, Debug)]
struct NliLabelMap {
    contradiction_idx: usize,
    entailment_idx: usize,
    neutral_idx: usize,
}

impl Default for NliLabelMap {
    fn default() -> Self {
        Self {
            contradiction_idx: 0,
            entailment_idx: 1,
            neutral_idx: 2,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NliModelMetadata {
    pub model_path: String,
    pub tokenizer_path: String,
    pub ort_execution_provider_preference: String,
    pub ort_dylib_path: Option<String>,
    pub max_length: usize,
    pub contradiction_idx: usize,
    pub entailment_idx: usize,
    pub neutral_idx: usize,
    pub input_names: Vec<String>,
    pub output_names: Vec<String>,
}

pub struct NliModel {
    session: Session,
    tokenizer: Tokenizer,
    labels: NliLabelMap,
    max_length: usize,
    pad_token_id: u32,
    padding_direction: PaddingDirection,
    input_ids_name: String,
    attention_mask_name: String,
    metadata: NliModelMetadata,
}

pub trait NliScorer {
    fn score_batch(&self, pairs: &[(&str, &str)]) -> Result<Vec<NliScores>, NliError>;
}

impl NliModel {
    pub fn load(model_dir: &Path) -> Result<Self, NliError> {
        let model_path = find_model_path(model_dir)?;
        let tokenizer_path = find_existing_path(model_dir, TOKENIZER_CANDIDATES)?;
        let tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|error| NliError::ModelLoad(error.to_string()))?;
        let (pad_token_id, padding_direction) = tokenizer
            .get_padding()
            .map(|padding| (padding.pad_id, padding.direction))
            .unwrap_or_else(|| {
                (
                    tokenizer.token_to_id("[PAD]").unwrap_or_default(),
                    PaddingDirection::Right,
                )
            });
        let ort_preference = nli_ort_preference();
        let session = load_nli_session(&model_path)
            .map_err(|error| NliError::ModelLoad(error.to_string()))?;
        let export_metadata = load_export_metadata(model_dir);
        let config = load_first_json(model_dir, CONFIG_CANDIDATES);
        let tokenizer_config = load_first_json(model_dir, TOKENIZER_CONFIG_CANDIDATES);
        let labels = resolve_label_map(export_metadata.as_ref(), config.as_ref());
        let max_length = resolve_max_length(
            export_metadata.as_ref(),
            config.as_ref(),
            tokenizer_config.as_ref(),
        );
        let input_names = session
            .inputs
            .iter()
            .map(|input| input.name.clone())
            .collect::<Vec<_>>();
        let output_names = session
            .outputs
            .iter()
            .map(|output| output.name.clone())
            .collect::<Vec<_>>();
        let input_ids_name = resolve_input_name(&input_names, &["input_ids", "input_ids:0"])?;
        let attention_mask_name =
            resolve_input_name(&input_names, &["attention_mask", "attention_mask:0"])?;
        let metadata = NliModelMetadata {
            model_path: model_path.display().to_string(),
            tokenizer_path: tokenizer_path.display().to_string(),
            ort_execution_provider_preference: ort_preference.as_str().to_owned(),
            ort_dylib_path: resolved_ort_dylib_path().map(|path| path.display().to_string()),
            max_length,
            contradiction_idx: labels.contradiction_idx,
            entailment_idx: labels.entailment_idx,
            neutral_idx: labels.neutral_idx,
            input_names,
            output_names,
        };
        Ok(Self {
            session,
            tokenizer,
            labels,
            max_length,
            pad_token_id,
            padding_direction,
            input_ids_name,
            attention_mask_name,
            metadata,
        })
    }

    pub fn metadata(&self) -> &NliModelMetadata {
        &self.metadata
    }

    pub fn score(&self, premise: &str, hypothesis: &str) -> Result<NliScores, NliError> {
        self.score_batch(&[(premise, hypothesis)])?
            .into_iter()
            .next()
            .ok_or_else(|| NliError::Inference("empty NLI score batch".to_owned()))
    }

    pub fn score_batch(&self, pairs: &[(&str, &str)]) -> Result<Vec<NliScores>, NliError> {
        if pairs.is_empty() {
            return Ok(Vec::new());
        }
        let inputs = pairs
            .iter()
            .map(|(premise, hypothesis)| EncodeInput::Dual((*premise).into(), (*hypothesis).into()))
            .collect::<Vec<_>>();
        let mut encodings = self
            .tokenizer
            .encode_batch(inputs, true)
            .map_err(|error| NliError::Inference(error.to_string()))?;
        let mut sequence_len = 0usize;
        for encoding in &mut encodings {
            if encoding.len() > self.max_length {
                encoding.truncate(self.max_length, 0, TruncationDirection::Right);
            }
            sequence_len = sequence_len.max(encoding.len());
        }
        if sequence_len == 0 {
            return Err(NliError::Inference("empty tokenized sequence".to_owned()));
        }
        let batch_size = encodings.len();
        let mut input_ids = Vec::<i64>::with_capacity(batch_size * sequence_len);
        let mut attention_mask = Vec::<i64>::with_capacity(batch_size * sequence_len);
        for encoding in &encodings {
            append_padded_i64(
                &mut input_ids,
                encoding.get_ids(),
                sequence_len,
                i64::from(self.pad_token_id),
                self.padding_direction,
            );
            append_padded_i64(
                &mut attention_mask,
                encoding.get_attention_mask(),
                sequence_len,
                0,
                self.padding_direction,
            );
        }
        let ids_tensor = Tensor::from_array(([batch_size, sequence_len], input_ids))
            .map_err(|error| NliError::Inference(error.to_string()))?;
        let mask_tensor = Tensor::from_array(([batch_size, sequence_len], attention_mask))
            .map_err(|error| NliError::Inference(error.to_string()))?;
        let inputs = vec![
            (self.input_ids_name.as_str(), ids_tensor),
            (self.attention_mask_name.as_str(), mask_tensor),
        ];
        let outputs = self
            .session
            .run(inputs)
            .map_err(|error| NliError::Inference(error.to_string()))?;
        let logits = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|error| NliError::Inference(error.to_string()))?;
        let values = logits
            .as_slice()
            .ok_or_else(|| NliError::Inference("non-contiguous logits".to_owned()))?;
        let row_stride = values
            .len()
            .checked_div(batch_size)
            .filter(|stride| *stride >= 3 && *stride * batch_size == values.len())
            .ok_or_else(|| {
                NliError::Inference(format!(
                    "expected batched logits divisible by {batch_size}, got {}",
                    values.len()
                ))
            })?;
        let mut scores = Vec::with_capacity(batch_size);
        for row in 0..batch_size {
            let start = row * row_stride;
            scores.push(scores_from_logits(&values[start..start + 3], self.labels)?);
        }
        Ok(scores)
    }

    pub fn judge_relation(
        &self,
        premise: &str,
        forward_hypotheses: &[String],
        reverse_hypotheses: &[String],
    ) -> Result<NliPairJudgment, NliError> {
        let (forward, forward_hypothesis) = self.best_scores(premise, forward_hypotheses)?;
        let reverse = if reverse_hypotheses.is_empty() {
            None
        } else {
            Some(self.best_scores(premise, reverse_hypotheses)?)
        };
        let use_reverse = reverse
            .as_ref()
            .map(|(scores, _)| should_use_reverse_direction(forward, *scores))
            .unwrap_or(false);
        let best_hypothesis = if use_reverse {
            reverse
                .as_ref()
                .map(|(_, hypothesis)| hypothesis.clone())
                .unwrap_or_else(|| forward_hypothesis.clone())
        } else {
            forward_hypothesis.clone()
        };
        Ok(NliPairJudgment {
            forward,
            reverse: reverse.map(|value| value.0),
            used_reverse: use_reverse,
            best_hypothesis,
        })
    }

    fn best_scores(
        &self,
        premise: &str,
        hypotheses: &[String],
    ) -> Result<(NliScores, String), NliError> {
        let mut best_scores = None::<NliScores>;
        let mut best_hypothesis = None::<String>;
        for hypothesis in hypotheses {
            let scores = self.score(premise, hypothesis)?;
            let replace = match best_scores {
                Some(current) => {
                    scores.entailment > current.entailment
                        || (scores.entailment == current.entailment
                            && scores.contradiction < current.contradiction)
                }
                None => true,
            };
            if replace {
                best_scores = Some(scores);
                best_hypothesis = Some(hypothesis.clone());
            }
        }
        match (best_scores, best_hypothesis) {
            (Some(scores), Some(hypothesis)) => Ok((scores, hypothesis)),
            _ => Err(NliError::Inference(
                "no hypotheses were provided for NLI scoring".to_owned(),
            )),
        }
    }
}

impl NliScorer for NliModel {
    fn score_batch(&self, pairs: &[(&str, &str)]) -> Result<Vec<NliScores>, NliError> {
        NliModel::score_batch(self, pairs)
    }
}

fn append_padded_i64(
    out: &mut Vec<i64>,
    values: &[u32],
    target_len: usize,
    pad_value: i64,
    direction: PaddingDirection,
) {
    let pad_len = target_len.saturating_sub(values.len());
    if matches!(direction, PaddingDirection::Left) {
        out.resize(out.len() + pad_len, pad_value);
    }
    out.extend(values.iter().map(|&value| i64::from(value)));
    if matches!(direction, PaddingDirection::Right) {
        out.resize(out.len() + pad_len, pad_value);
    }
}

fn scores_from_logits(logits: &[f32], labels: NliLabelMap) -> Result<NliScores, NliError> {
    if logits.len() < 3 {
        return Err(NliError::Inference(format!(
            "expected at least 3 logits, got {}",
            logits.len()
        )));
    }
    let max_logit = logits[..3]
        .iter()
        .copied()
        .fold(f32::NEG_INFINITY, f32::max);
    let mut exp = [0.0f32; 3];
    let mut sum = 0.0f32;
    for (index, value) in logits[..3].iter().enumerate() {
        exp[index] = (*value - max_logit).exp();
        sum += exp[index];
    }
    if sum <= f32::EPSILON {
        return Err(NliError::Inference("softmax sum was zero".to_owned()));
    }
    let probs = [exp[0] / sum, exp[1] / sum, exp[2] / sum];
    Ok(NliScores {
        contradiction: probs[labels.contradiction_idx],
        entailment: probs[labels.entailment_idx],
        neutral: probs[labels.neutral_idx],
    })
}

pub(crate) fn should_use_reverse_direction(forward: NliScores, reverse: NliScores) -> bool {
    reverse.entailment >= REVERSE_DIRECTION_MIN_ENTAILMENT
        && reverse.entailment > forward.entailment
        && reverse.entailment - forward.entailment >= 0.005
        && reverse.contradiction <= forward.contradiction + 0.02
}

fn find_model_path(root: &Path) -> Result<PathBuf, NliError> {
    if let Some(value) = env::var_os(MODEL_FILE_ENV) {
        let path = root.join(value);
        if path.exists() {
            return Ok(path);
        }
        return Err(NliError::ModelLoad(format!(
            "{MODEL_FILE_ENV} points at a missing asset under {}",
            root.display()
        )));
    }
    find_existing_path(root, MODEL_CANDIDATES)
}

fn find_existing_path(root: &Path, candidates: &[&str]) -> Result<PathBuf, NliError> {
    for candidate in candidates {
        let path = root.join(candidate);
        if path.exists() {
            return Ok(path);
        }
    }
    Err(NliError::ModelLoad(format!(
        "missing required asset under {}",
        root.display()
    )))
}

fn resolve_input_name(input_names: &[String], candidates: &[&str]) -> Result<String, NliError> {
    candidates
        .iter()
        .find_map(|candidate| {
            input_names
                .iter()
                .find(|name| name.as_str() == *candidate)
                .cloned()
        })
        .ok_or_else(|| {
            NliError::ModelLoad(format!(
                "missing required ONNX input; saw {:?}",
                input_names
            ))
        })
}

fn load_export_metadata(root: &Path) -> Option<NliExportMetadata> {
    load_first_json(root, EXPORT_METADATA_CANDIDATES)
        .and_then(|value| serde_json::from_value(value).ok())
}

fn load_first_json(root: &Path, candidates: &[&str]) -> Option<Value> {
    candidates
        .iter()
        .map(|candidate| root.join(candidate))
        .find_map(|path| load_json_value(&path))
}

fn load_json_value(path: &Path) -> Option<Value> {
    let file = File::open(path).ok()?;
    // The mapping is read-only and short-lived; serde parses before the file handle is dropped.
    let mmap = unsafe { Mmap::map(&file).ok()? };
    serde_json::from_slice::<Value>(&mmap).ok()
}

fn resolve_label_map(
    export_metadata: Option<&NliExportMetadata>,
    config: Option<&Value>,
) -> NliLabelMap {
    if let Some(map) = export_metadata.and_then(label_map_from_export_metadata) {
        return map;
    }
    config.and_then(label_map_from_config).unwrap_or_default()
}

fn label_map_from_export_metadata(metadata: &NliExportMetadata) -> Option<NliLabelMap> {
    let labels = NliLabelMap {
        contradiction_idx: metadata.contradiction_idx?,
        entailment_idx: metadata.entailment_idx?,
        neutral_idx: metadata.neutral_idx?,
    };
    valid_label_map(labels)
}

fn label_map_from_config(config: &Value) -> Option<NliLabelMap> {
    config
        .get("label2id")
        .and_then(labels_from_label2id)
        .or_else(|| config.get("id2label").and_then(labels_from_id2label))
        .and_then(valid_label_map)
}

fn labels_from_label2id(value: &Value) -> Option<NliLabelMap> {
    let object = value.as_object()?;
    let mut labels = HashMap::<String, usize>::with_capacity(object.len());
    for (label, index) in object {
        labels.insert(normalize_label(label), index.as_u64()? as usize);
    }
    Some(NliLabelMap {
        contradiction_idx: *labels.get("contradiction")?,
        entailment_idx: *labels.get("entailment")?,
        neutral_idx: *labels.get("neutral")?,
    })
}

fn labels_from_id2label(value: &Value) -> Option<NliLabelMap> {
    let object = value.as_object()?;
    let mut labels = HashMap::<String, usize>::with_capacity(object.len());
    for (index, label) in object {
        labels.insert(
            normalize_label(label.as_str()?),
            index.parse::<usize>().ok()?,
        );
    }
    Some(NliLabelMap {
        contradiction_idx: *labels.get("contradiction")?,
        entailment_idx: *labels.get("entailment")?,
        neutral_idx: *labels.get("neutral")?,
    })
}

fn valid_label_map(labels: NliLabelMap) -> Option<NliLabelMap> {
    let mut seen = [false; 3];
    for index in [
        labels.contradiction_idx,
        labels.entailment_idx,
        labels.neutral_idx,
    ] {
        if index >= 3 || seen[index] {
            return None;
        }
        seen[index] = true;
    }
    Some(labels)
}

fn normalize_label(label: &str) -> String {
    label.trim().to_ascii_lowercase().replace([' ', '-'], "_")
}

fn resolve_max_length(
    export_metadata: Option<&NliExportMetadata>,
    config: Option<&Value>,
    tokenizer_config: Option<&Value>,
) -> usize {
    let config_limit = json_usize(config, "max_position_embeddings");
    let mut max_length = export_metadata
        .and_then(|value| value.max_length)
        .or_else(|| json_usize(tokenizer_config, "max_length"))
        .or_else(|| json_usize(tokenizer_config, "model_max_length"))
        .or(config_limit)
        .unwrap_or(DEFAULT_NLI_MAX_LENGTH);
    if let Some(limit) = config_limit {
        max_length = max_length.min(limit);
    }
    max_length.clamp(32, MAX_REASONABLE_NLI_LENGTH)
}

fn json_usize(value: Option<&Value>, key: &str) -> Option<usize> {
    value
        .and_then(|value| value.get(key))
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .filter(|value| *value <= MAX_REASONABLE_NLI_LENGTH)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn modernbert_label2id_overrides_default_nli_order() {
        let config = serde_json::json!({
            "label2id": {
                "entailment": 0,
                "neutral": 1,
                "contradiction": 2
            }
        });
        let labels = label_map_from_config(&config).expect("label map");
        assert_eq!(labels.entailment_idx, 0);
        assert_eq!(labels.neutral_idx, 1);
        assert_eq!(labels.contradiction_idx, 2);
    }

    #[test]
    fn id2label_config_order_is_supported() {
        let config = serde_json::json!({
            "id2label": {
                "0": "entailment",
                "1": "neutral",
                "2": "contradiction"
            }
        });
        let labels = label_map_from_config(&config).expect("label map");
        assert_eq!(labels.entailment_idx, 0);
        assert_eq!(labels.neutral_idx, 1);
        assert_eq!(labels.contradiction_idx, 2);
    }

    #[test]
    fn export_metadata_takes_precedence_over_config() {
        let export = NliExportMetadata {
            contradiction_idx: Some(0),
            entailment_idx: Some(2),
            neutral_idx: Some(1),
            max_length: None,
        };
        let config = serde_json::json!({
            "label2id": {
                "entailment": 0,
                "neutral": 1,
                "contradiction": 2
            }
        });
        let labels = resolve_label_map(Some(&export), Some(&config));
        assert_eq!(labels.contradiction_idx, 0);
        assert_eq!(labels.neutral_idx, 1);
        assert_eq!(labels.entailment_idx, 2);
    }

    #[test]
    fn max_length_uses_modernbert_position_cap() {
        let config = serde_json::json!({ "max_position_embeddings": 2048 });
        let tokenizer_config = serde_json::json!({ "model_max_length": 4096 });
        assert_eq!(
            resolve_max_length(None, Some(&config), Some(&tokenizer_config)),
            2048
        );
    }

    #[test]
    fn logits_respect_modernbert_label_order() {
        let labels = NliLabelMap {
            entailment_idx: 0,
            neutral_idx: 1,
            contradiction_idx: 2,
        };
        let scores = scores_from_logits(&[6.0, 1.0, -2.0], labels).expect("scores");
        assert!(scores.entailment > 0.99);
        assert!(scores.neutral < 0.01);
        assert!(scores.contradiction < 0.001);
    }

    #[test]
    fn batch_padding_preserves_direction() {
        let mut right = Vec::new();
        append_padded_i64(&mut right, &[7, 8], 4, 0, PaddingDirection::Right);
        assert_eq!(right, vec![7, 8, 0, 0]);

        let mut left = Vec::new();
        append_padded_i64(&mut left, &[7, 8], 4, 0, PaddingDirection::Left);
        assert_eq!(left, vec![0, 0, 7, 8]);
    }

    #[test]
    fn reverse_direction_requires_real_entailment() {
        let forward = NliScores {
            contradiction: 0.99,
            entailment: 0.01,
            neutral: 0.0,
        };
        let reverse = NliScores {
            contradiction: 0.85,
            entailment: 0.03,
            neutral: 0.12,
        };
        assert!(!should_use_reverse_direction(forward, reverse));

        let supported_reverse = NliScores {
            contradiction: 0.01,
            entailment: 0.91,
            neutral: 0.08,
        };
        assert!(should_use_reverse_direction(forward, supported_reverse));
    }
}

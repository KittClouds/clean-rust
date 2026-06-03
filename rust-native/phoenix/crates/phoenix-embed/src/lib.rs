use std::env;
use std::path::{Path, PathBuf};
use std::thread;

use ort::execution_providers::{CUDAExecutionProvider, DirectMLExecutionProvider};
use ort::memory::{AllocationDevice, AllocatorType, MemoryInfo, MemoryType};
use ort::session::builder::{GraphOptimizationLevel, SessionBuilder};
use ort::session::{Session, SessionInputValue};
use ort::value::TensorRefMut;
use thiserror::Error;
use tokenizers::{
    PaddingParams, PaddingStrategy, Tokenizer, TruncationDirection, TruncationParams,
    TruncationStrategy,
};

mod config;

pub use config::{
    OrtExecutionProviderPreference, OrtTextEmbedConfig, TextEmbeddingInputPrefix,
    TextEmbeddingPooling, TextEmbeddingProfile,
};

impl TextEmbeddingProfile {
    #[cfg(test)]
    fn project(self, values: &[f32]) -> Result<Vec<f32>, OrtTextEmbedError> {
        let mut out = Vec::with_capacity(self.target_dim());
        self.project_into(values, &mut out)?;
        Ok(out)
    }

    fn project_into(self, values: &[f32], out: &mut Vec<f32>) -> Result<(), OrtTextEmbedError> {
        let target_dim = self.target_dim();
        if matches!(
            self,
            Self::Truncate128 | Self::Truncate256 | Self::Truncate512
        ) {
            if values.len() < target_dim {
                return Err(OrtTextEmbedError::EmbeddingDimension {
                    expected: target_dim,
                    actual: values.len(),
                    profile: self.label(),
                });
            }
            normalize_embedding_into(&values[..target_dim], out);
            return Ok(());
        }

        if values.len() != target_dim {
            return Err(OrtTextEmbedError::EmbeddingDimension {
                expected: target_dim,
                actual: values.len(),
                profile: self.label(),
            });
        }
        normalize_embedding_into(values, out);
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct TextEmbeddingBatch {
    values: Vec<f32>,
    rows: usize,
    dims: usize,
}

impl TextEmbeddingBatch {
    fn with_capacity(rows: usize, dims: usize) -> Self {
        Self {
            values: Vec::with_capacity(rows.saturating_mul(dims)),
            rows: 0,
            dims,
        }
    }

    pub fn values(&self) -> &[f32] {
        &self.values
    }

    pub fn rows(&self) -> usize {
        self.rows
    }

    pub fn dims(&self) -> usize {
        self.dims
    }

    pub fn row(&self, index: usize) -> Option<&[f32]> {
        if index >= self.rows || self.dims == 0 {
            return None;
        }
        let start = index.checked_mul(self.dims)?;
        let end = start.checked_add(self.dims)?;
        self.values.get(start..end)
    }

    pub fn into_values(self) -> Vec<f32> {
        self.values
    }

    pub fn into_rows(self) -> Vec<Vec<f32>> {
        if self.dims == 0 {
            return Vec::new();
        }
        self.values
            .chunks_exact(self.dims)
            .take(self.rows)
            .map(|row| row.to_vec())
            .collect()
    }
}

#[derive(Debug, Error)]
pub enum OrtTextEmbedError {
    #[error("failed to load embedding model: {0}")]
    ModelLoad(String),
    #[error("embedding inference failed: {0}")]
    Inference(String),
    #[error(
        "embedding dimension mismatch for profile {profile}: expected {expected}, got {actual}"
    )]
    EmbeddingDimension {
        expected: usize,
        actual: usize,
        profile: &'static str,
    },
}

pub struct OrtTextEmbedder {
    session: Session,
    tokenizer: Tokenizer,
    cpu_memory_info: MemoryInfo,
    batch_size: usize,
    profile: TextEmbeddingProfile,
    input_prefix: TextEmbeddingInputPrefix,
    pooling: TextEmbeddingPooling,
    need_token_type_ids: bool,
}

#[derive(Default)]
struct TensorScratch {
    input_ids: Vec<i64>,
    attention_mask: Vec<i64>,
    token_type_ids: Vec<i64>,
    pooled: Vec<f32>,
}

impl TensorScratch {
    fn prepare(&mut self, len: usize, need_token_type_ids: bool) {
        self.input_ids.resize(len, 0);
        self.attention_mask.resize(len, 0);
        if need_token_type_ids {
            self.token_type_ids.resize(len, 0);
        } else {
            self.token_type_ids.clear();
        }
    }
}

impl OrtTextEmbedder {
    pub fn load(config: &OrtTextEmbedConfig) -> Result<Self, OrtTextEmbedError> {
        let tokenizer_path = find_existing_path(
            &config.model_root,
            &["tokenizer.json", "onnx\\tokenizer.json"],
        )?;
        let mut tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|error| OrtTextEmbedError::ModelLoad(format!("tokenizer: {error}")))?;
        configure_tokenizer(&mut tokenizer, config.max_length.max(16))
            .map_err(|error| OrtTextEmbedError::ModelLoad(format!("tokenizer config: {error}")))?;
        let available_threads = thread::available_parallelism()
            .map(|value| value.get().min(8))
            .unwrap_or(1);
        let model_paths = find_existing_paths(
            &config.model_root,
            &[
                "onnx\\model_q4f16.onnx",
                "onnx\\model_quantized.onnx",
                "onnx\\model_fp16.onnx",
                "onnx\\model.onnx",
                "model.onnx",
            ],
        )?;
        let mut session_error = String::new();
        let mut session = None;
        for model_path in model_paths {
            let loaded = build_session(&model_path, available_threads, config.execution_provider);
            match loaded {
                Ok(loaded) => {
                    session = Some(loaded);
                    break;
                }
                Err(error) => {
                    session_error.push_str(&format!("{} -> {error}; ", model_path.display()));
                }
            }
        }
        let session = session
            .ok_or_else(|| OrtTextEmbedError::ModelLoad(format!("session: {session_error}")))?;
        let need_token_type_ids = session
            .inputs
            .iter()
            .any(|input| input.name == "token_type_ids");
        let cpu_memory_info = MemoryInfo::new(
            AllocationDevice::CPU,
            0,
            AllocatorType::Arena,
            MemoryType::CPUInput,
        )
        .map_err(|error| OrtTextEmbedError::ModelLoad(format!("memory info: {error}")))?;
        Ok(Self {
            session,
            tokenizer,
            cpu_memory_info,
            batch_size: config.batch_size.max(1),
            profile: config.profile,
            input_prefix: if config.prefix_passage {
                TextEmbeddingInputPrefix::Passage
            } else {
                config.input_prefix
            },
            pooling: config.pooling,
            need_token_type_ids,
        })
    }

    pub fn profile(&self) -> TextEmbeddingProfile {
        self.profile
    }

    pub fn embed_batched<S: AsRef<str>>(
        &self,
        texts: &[S],
        batch_size: usize,
    ) -> Result<Vec<Vec<f32>>, OrtTextEmbedError> {
        Ok(self.embed_batched_flat(texts, batch_size)?.into_rows())
    }

    pub fn embed_batched_flat<S: AsRef<str>>(
        &self,
        texts: &[S],
        batch_size: usize,
    ) -> Result<TextEmbeddingBatch, OrtTextEmbedError> {
        let batch_size = batch_size.max(1);
        let mut rows = TextEmbeddingBatch::with_capacity(texts.len(), self.profile.target_dim());
        let mut scratch = TensorScratch::default();
        for chunk in texts.chunks(batch_size) {
            self.embed_batch_into(chunk, &mut scratch, &mut rows)?;
        }
        Ok(rows)
    }

    pub fn embed_texts<S: AsRef<str>>(
        &self,
        texts: &[S],
    ) -> Result<Vec<Vec<f32>>, OrtTextEmbedError> {
        self.embed_batched(texts, self.batch_size)
    }

    pub fn embed_texts_flat<S: AsRef<str>>(
        &self,
        texts: &[S],
    ) -> Result<TextEmbeddingBatch, OrtTextEmbedError> {
        self.embed_batched_flat(texts, self.batch_size)
    }

    pub fn embed_slices(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, OrtTextEmbedError> {
        self.embed_texts(texts)
    }

    pub fn embed_slices_flat(
        &self,
        texts: &[&str],
    ) -> Result<TextEmbeddingBatch, OrtTextEmbedError> {
        self.embed_texts_flat(texts)
    }

    fn embed_batch_into<S: AsRef<str>>(
        &self,
        texts: &[S],
        scratch: &mut TensorScratch,
        rows: &mut TextEmbeddingBatch,
    ) -> Result<(), OrtTextEmbedError> {
        if texts.is_empty() {
            return Ok(());
        }

        let prefix = self.input_prefix.text();
        let encodings = if prefix.is_empty() {
            let mut inputs = Vec::with_capacity(texts.len());
            for text in texts {
                inputs.push(text.as_ref());
            }
            self.tokenizer
                .encode_batch_fast(inputs, true)
                .map_err(|error| OrtTextEmbedError::Inference(format!("encode_batch: {error}")))?
        } else {
            let mut prefixed = Vec::with_capacity(texts.len());
            for text in texts {
                let text = text.as_ref();
                let mut value = String::with_capacity(prefix.len() + text.len());
                value.push_str(prefix);
                value.push_str(text);
                prefixed.push(value);
            }
            self.tokenizer
                .encode_batch_fast(prefixed, true)
                .map_err(|error| OrtTextEmbedError::Inference(format!("encode_batch: {error}")))?
        };
        let max_len = encodings
            .first()
            .map(|encoding| encoding.len().max(1))
            .unwrap_or(1);
        let batch_len = encodings.len();
        let flat_len = batch_len * max_len;
        scratch.prepare(flat_len, self.need_token_type_ids);
        for (row, encoding) in encodings.iter().enumerate() {
            let offset = row * max_len;
            copy_ids(
                &mut scratch.input_ids[offset..offset + max_len],
                encoding.get_ids(),
            );
            copy_ids(
                &mut scratch.attention_mask[offset..offset + max_len],
                encoding.get_attention_mask(),
            );
            if self.need_token_type_ids {
                copy_ids(
                    &mut scratch.token_type_ids[offset..offset + max_len],
                    encoding.get_type_ids(),
                );
            }
        }

        let shape = [batch_len as i64, max_len as i64];
        let input_ids = tensor_ref_from_buffer(
            &self.cpu_memory_info,
            &mut scratch.input_ids,
            shape,
            "input_ids",
        )?;
        let attention_mask = tensor_ref_from_buffer(
            &self.cpu_memory_info,
            &mut scratch.attention_mask,
            shape,
            "attention_mask",
        )?;
        let outputs = if self.need_token_type_ids {
            let token_type_ids = tensor_ref_from_buffer(
                &self.cpu_memory_info,
                &mut scratch.token_type_ids,
                shape,
                "token_type_ids",
            )?;
            self.session
                .run([
                    SessionInputValue::from(input_ids),
                    SessionInputValue::from(attention_mask),
                    SessionInputValue::from(token_type_ids),
                ])
                .map_err(|error| OrtTextEmbedError::Inference(format!("run: {error}")))?
        } else {
            self.session
                .run([
                    SessionInputValue::from(input_ids),
                    SessionInputValue::from(attention_mask),
                ])
                .map_err(|error| OrtTextEmbedError::Inference(format!("run: {error}")))?
        };

        let hidden = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|error| OrtTextEmbedError::Inference(format!("extract: {error}")))?;
        let view = hidden.view();
        let shape = view.shape();
        if shape.len() != 3 {
            return Err(OrtTextEmbedError::Inference(format!(
                "expected 3D hidden state, got shape {shape:?}"
            )));
        }
        let hidden_dim = shape[2];
        let values = view.as_slice().ok_or_else(|| {
            OrtTextEmbedError::Inference("hidden state was non-contiguous".to_owned())
        })?;

        for row in 0..batch_len {
            match self.pooling {
                TextEmbeddingPooling::Cls => {
                    let start = row * max_len * hidden_dim;
                    self.profile
                        .project_into(&values[start..start + hidden_dim], &mut rows.values)?;
                }
                TextEmbeddingPooling::Mean => {
                    let attention = &scratch.attention_mask[row * max_len..][..max_len];
                    mean_pool_row(
                        values,
                        row,
                        max_len,
                        hidden_dim,
                        attention,
                        &mut scratch.pooled,
                    );
                    self.profile
                        .project_into(&scratch.pooled, &mut rows.values)?;
                }
                TextEmbeddingPooling::LastToken => {
                    let token_index =
                        last_non_padding_index(&scratch.attention_mask[row * max_len..][..max_len]);
                    let start = (row * max_len + token_index) * hidden_dim;
                    self.profile
                        .project_into(&values[start..start + hidden_dim], &mut rows.values)?;
                }
            }
            rows.rows += 1;
        }
        Ok(())
    }
}

fn build_session(
    model_path: &Path,
    available_threads: usize,
    provider: OrtExecutionProviderPreference,
) -> Result<Session, ort::Error> {
    let mut builder = Session::builder()?
        .with_optimization_level(GraphOptimizationLevel::Level3)?
        .with_parallel_execution(false)?
        .with_inter_threads(1)?
        .with_intra_threads(available_threads)?;
    if matches!(provider, OrtExecutionProviderPreference::DirectMl) {
        builder = builder.with_memory_pattern(false)?;
    }
    builder = apply_execution_provider_preference(builder, provider)?;
    builder.commit_from_file(model_path)
}

fn apply_execution_provider_preference(
    builder: SessionBuilder,
    provider: OrtExecutionProviderPreference,
) -> Result<SessionBuilder, ort::Error> {
    let strict = env_flag("PHOENIX_EMBED_ORT_EP_STRICT", true);
    let provider = match provider {
        OrtExecutionProviderPreference::Cpu => return Ok(builder),
        OrtExecutionProviderPreference::DirectMl => DirectMLExecutionProvider::default().build(),
        OrtExecutionProviderPreference::Cuda => CUDAExecutionProvider::default().build(),
    };
    let provider = if strict {
        provider.error_on_failure()
    } else {
        provider.fail_silently()
    };
    builder.with_execution_providers([provider])
}

fn env_flag(name: &str, default: bool) -> bool {
    env::var(name)
        .ok()
        .map(|value| {
            matches!(
                value.trim(),
                "1" | "true" | "TRUE" | "yes" | "YES" | "on" | "ON"
            )
        })
        .unwrap_or(default)
}

fn mean_pool_row(
    values: &[f32],
    row: usize,
    max_len: usize,
    hidden_dim: usize,
    attention: &[i64],
    out: &mut Vec<f32>,
) {
    out.clear();
    out.resize(hidden_dim, 0.0);
    let mut count = 0usize;
    for token_index in 0..max_len {
        if attention.get(token_index).copied().unwrap_or_default() == 0 {
            continue;
        }
        let start = (row * max_len + token_index) * hidden_dim;
        for dim in 0..hidden_dim {
            out[dim] += values[start + dim];
        }
        count += 1;
    }
    let denom = count.max(1) as f32;
    for value in out.iter_mut() {
        *value /= denom;
    }
}

pub fn default_embedding_model_root() -> PathBuf {
    workspace_root()
        .join("rust-native")
        .join("phoenix-hnsw-smoke")
        .join("models")
        .join("snowflake-arctic-embed-xs")
}

pub fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("workspace root")
        .to_path_buf()
}

pub fn default_ort_dylib_path(workspace_root: &Path) -> Option<PathBuf> {
    [
        workspace_root
            .join("node_modules")
            .join("@huggingface")
            .join("transformers")
            .join("node_modules")
            .join("onnxruntime-node")
            .join("bin")
            .join("napi-v6")
            .join("win32")
            .join("x64")
            .join("onnxruntime.dll"),
        workspace_root
            .join("node_modules")
            .join("onnxruntime-node")
            .join("bin")
            .join("napi-v3")
            .join("win32")
            .join("x64")
            .join("onnxruntime.dll"),
    ]
    .into_iter()
    .find(|path| path.exists())
}

fn find_existing_path(root: &Path, candidates: &[&str]) -> Result<PathBuf, OrtTextEmbedError> {
    find_existing_paths(root, candidates)?
        .into_iter()
        .next()
        .ok_or_else(|| {
            OrtTextEmbedError::ModelLoad(format!("missing required asset under {}", root.display()))
        })
}

fn find_existing_paths(
    root: &Path,
    candidates: &[&str],
) -> Result<Vec<PathBuf>, OrtTextEmbedError> {
    let mut paths = Vec::new();
    for candidate in candidates {
        let path = root.join(candidate);
        if path.exists() {
            paths.push(path);
        }
    }
    if paths.is_empty() {
        Err(OrtTextEmbedError::ModelLoad(format!(
            "missing required asset under {}",
            root.display()
        )))
    } else {
        Ok(paths)
    }
}

fn normalize_embedding_into(values: &[f32], out: &mut Vec<f32>) {
    let norm = values
        .iter()
        .map(|value| value * value)
        .sum::<f32>()
        .sqrt()
        .max(1e-12);
    out.reserve(values.len());
    out.extend(values.iter().map(|value| *value / norm));
}

fn configure_tokenizer(
    tokenizer: &mut Tokenizer,
    max_length: usize,
) -> Result<(), tokenizers::Error> {
    let mut padding = tokenizer
        .get_padding()
        .cloned()
        .unwrap_or_else(|| PaddingParams {
            strategy: PaddingStrategy::BatchLongest,
            ..Default::default()
        });
    padding.strategy = PaddingStrategy::BatchLongest;
    tokenizer.with_padding(Some(padding));
    tokenizer.with_truncation(Some(TruncationParams {
        max_length,
        strategy: TruncationStrategy::LongestFirst,
        stride: 0,
        direction: TruncationDirection::Right,
    }))?;
    Ok(())
}

fn copy_ids(target: &mut [i64], values: &[u32]) {
    for (slot, value) in target.iter_mut().zip(values.iter()) {
        *slot = i64::from(*value);
    }
}

fn last_non_padding_index(attention_mask: &[i64]) -> usize {
    attention_mask
        .iter()
        .rposition(|value| *value != 0)
        .unwrap_or(0)
}

fn tensor_ref_from_buffer<'a>(
    memory_info: &MemoryInfo,
    buffer: &'a mut Vec<i64>,
    shape: [i64; 2],
    label: &str,
) -> Result<TensorRefMut<'a, i64>, OrtTextEmbedError> {
    unsafe {
        TensorRefMut::from_raw(
            memory_info.clone(),
            buffer.as_mut_ptr().cast(),
            Vec::from(shape),
        )
        .map_err(|error| OrtTextEmbedError::Inference(format!("{label}: {error}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profiles_parse_expected_labels() {
        assert_eq!(
            TextEmbeddingProfile::parse("256-truncated"),
            Some(TextEmbeddingProfile::Truncate256)
        );
        assert_eq!(
            TextEmbeddingProfile::parse("384"),
            Some(TextEmbeddingProfile::Native384)
        );
        assert_eq!(
            TextEmbeddingProfile::parse("768"),
            Some(TextEmbeddingProfile::Native768)
        );
        assert_eq!(
            TextEmbeddingProfile::parse("786"),
            Some(TextEmbeddingProfile::Native768)
        );
        assert_eq!(
            TextEmbeddingProfile::parse("1024"),
            Some(TextEmbeddingProfile::Native1024)
        );
    }

    #[test]
    fn truncate_profile_projects_first_256_dims() {
        let values = (0..384).map(|value| value as f32 + 1.0).collect::<Vec<_>>();
        let projected = TextEmbeddingProfile::Truncate256
            .project(&values)
            .expect("truncate profile");
        assert_eq!(projected.len(), 256);
    }

    #[test]
    fn native_profile_rejects_wrong_dimension() {
        let error = TextEmbeddingProfile::Native384
            .project(&vec![1.0; 256])
            .expect_err("dimension mismatch");
        assert!(matches!(
            error,
            OrtTextEmbedError::EmbeddingDimension {
                expected: 384,
                actual: 256,
                ..
            }
        ));
    }

    #[test]
    fn last_token_pooling_uses_final_non_padding_token() {
        assert_eq!(last_non_padding_index(&[1, 1, 1, 0, 0]), 2);
        assert_eq!(last_non_padding_index(&[0, 0, 0]), 0);
    }
}

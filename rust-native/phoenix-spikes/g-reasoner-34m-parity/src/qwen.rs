//! Optional native query embedding for the model's pinned Qwen3 encoder.

use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};

use candle_core::{DType, Device, IndexOp, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::qwen3::{Config, Model};
use phoenix_model_hot_cache::MaterializedArtifact;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use tokenizers::Tokenizer;

use crate::constants::{
    FEATURE_DIM, QWEN_QUERY_INSTRUCTION, QWEN_REPOSITORY, QWEN_REVISION, QWEN_SAFETENSORS_SHA256,
};
use crate::{GfmError, Result};

/// A mmap-backed Qwen encoder. A fresh lightweight model view is constructed
/// per call so Candle's internal decoder KV cache can never leak across queries.
pub struct QwenEmbedder {
    tokenizer: Tokenizer,
    config: Config,
    weights: PathBuf,
    device: Device,
    dtype: DType,
    max_length: usize,
}

#[derive(Deserialize)]
struct ArtifactManifest {
    schema: String,
    repository: String,
    revision: String,
    artifacts: Vec<ArtifactRecord>,
}

#[derive(Deserialize)]
struct ArtifactRecord {
    file: String,
    bytes: u64,
    sha256: String,
}

impl QwenEmbedder {
    pub fn load(model_dir: impl AsRef<Path>, max_length: usize) -> Result<Self> {
        Self::load_inner(model_dir.as_ref(), max_length, None)
    }

    pub fn load_materialized(
        model_dir: impl AsRef<Path>,
        max_length: usize,
        weights: &MaterializedArtifact,
    ) -> Result<Self> {
        Self::load_inner(model_dir.as_ref(), max_length, Some(weights))
    }

    fn load_inner(
        model_dir: &Path,
        max_length: usize,
        materialized_weights: Option<&MaterializedArtifact>,
    ) -> Result<Self> {
        if max_length == 0 {
            return Err(GfmError::Shape("Qwen max_length must be nonzero".into()));
        }
        verify_artifacts(model_dir, materialized_weights)?;
        let config_path = model_dir.join("config.json");
        let tokenizer_path = model_dir.join("tokenizer.json");
        let weights = materialized_weights.map_or_else(
            || model_dir.join("model.safetensors"),
            |artifact| artifact.hot_path().to_path_buf(),
        );
        let config_bytes = std::fs::read(&config_path)
            .map_err(|source| crate::error::io_error(&config_path, source))?;
        let config: Config = serde_json::from_slice(&config_bytes)?;
        if config.hidden_size != FEATURE_DIM {
            return Err(GfmError::Shape(format!(
                "Qwen hidden size {} does not match graph feature size {FEATURE_DIM}",
                config.hidden_size
            )));
        }
        if max_length > config.max_position_embeddings {
            return Err(GfmError::Shape(format!(
                "Qwen max_length {max_length} exceeds model capacity {}",
                config.max_position_embeddings
            )));
        }
        let tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|error| GfmError::Tokenizer(error.to_string()))?;
        if !weights.is_file() {
            return Err(GfmError::InvalidCheckpoint(format!(
                "missing Qwen weights at {}",
                weights.display()
            )));
        }
        Ok(Self {
            tokenizer,
            config,
            weights,
            device: Device::Cpu,
            // Candle's portable CPU matmul does not accept BF16. The pinned
            // BF16 weights are widened on demand without changing values.
            dtype: DType::F32,
            max_length,
        })
    }

    pub fn format_query(query: &str) -> String {
        let mut formatted = String::with_capacity(QWEN_QUERY_INSTRUCTION.len() + query.len());
        formatted.push_str(QWEN_QUERY_INSTRUCTION);
        formatted.push_str(query);
        formatted
    }

    /// Returns the normalized 1024-dimensional last-token embedding expected
    /// by the frozen G-reasoner projection layers.
    pub fn embed_query(&self, query: &str) -> Result<Vec<f32>> {
        self.embed_text(&Self::format_query(query))
    }

    /// Encodes graph-stable node or relation text without a query instruction.
    pub fn embed_passage(&self, text: &str) -> Result<Vec<f32>> {
        self.embed_text(text)
    }

    /// Encodes immutable bundle vocabulary in one right-padded causal batch.
    /// Pooling occurs at each row's real final token, so padding is never in
    /// that token's attention history.
    pub fn embed_passages_batch(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        self.embed_texts(texts)
    }

    pub fn embed_passages_chunked(&self, texts: &[&str], max_rows: usize) -> Result<Vec<Vec<f32>>> {
        if max_rows == 0 {
            return Err(GfmError::Shape(
                "Qwen chunk row limit must be nonzero".into(),
            ));
        }
        let mut output = Vec::with_capacity(texts.len());
        for chunk in texts.chunks(max_rows) {
            output.extend(self.embed_texts(chunk)?);
        }
        Ok(output)
    }

    pub fn token_ids(&self, query: &str) -> Result<Vec<u32>> {
        self.token_ids_for_text(&Self::format_query(query))
    }

    fn embed_text(&self, text: &str) -> Result<Vec<f32>> {
        self.embed_texts(&[text])?
            .pop()
            .ok_or_else(|| GfmError::Shape("Qwen batch returned no row".into()))
    }

    fn embed_texts(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let token_rows = texts
            .iter()
            .map(|text| self.token_ids_for_text(text))
            .collect::<Result<Vec<_>>>()?;
        let sequence = token_rows.iter().map(Vec::len).max().unwrap_or(0);
        let mut padded = vec![0_u32; token_rows.len() * sequence];
        for (row, ids) in token_rows.iter().enumerate() {
            let start = row * sequence;
            padded[start..start + ids.len()].copy_from_slice(ids);
        }
        let input = Tensor::from_vec(padded, (token_rows.len(), sequence), &self.device)?;
        // Safety: the isolated pinned artifact is immutable for this process.
        let builder = unsafe {
            VarBuilder::from_mmaped_safetensors(&[&self.weights], self.dtype, &self.device)?
        }
        .rename_f(|name| name.strip_prefix("model.").unwrap_or(name).to_owned());
        let mut model = Model::new(&self.config, builder)?;
        let hidden = model.forward(&input, 0)?;
        let mut output = Vec::with_capacity(token_rows.len());
        for (row, ids) in token_rows.iter().enumerate() {
            let pooled = hidden.i((row, ids.len() - 1, ..))?.to_dtype(DType::F32)?;
            output.push(normalize(&pooled)?.to_vec1::<f32>()?);
        }
        Ok(output)
    }

    fn token_ids_for_text(&self, text: &str) -> Result<Vec<u32>> {
        let encoding = self
            .tokenizer
            .encode(text, true)
            .map_err(|error| GfmError::Tokenizer(error.to_string()))?;
        let ids = encoding.get_ids();
        if ids.is_empty() {
            return Err(GfmError::Shape("Qwen tokenizer returned no tokens".into()));
        }
        if ids.len() > self.max_length {
            return Err(GfmError::Shape(format!(
                "Qwen query has {} tokens; configured limit is {}",
                ids.len(),
                self.max_length
            )));
        }
        Ok(ids.to_vec())
    }
}

fn verify_artifacts(
    model_dir: &Path,
    materialized_weights: Option<&MaterializedArtifact>,
) -> Result<()> {
    let manifest_path = model_dir.join("artifact-manifest.json");
    let manifest_bytes = std::fs::read(&manifest_path)
        .map_err(|source| crate::error::io_error(&manifest_path, source))?;
    let manifest: ArtifactManifest = serde_json::from_slice(&manifest_bytes)?;
    if manifest.schema != "phoenix.g-reasoner.qwen-artifacts.v1"
        || manifest.repository != QWEN_REPOSITORY
        || manifest.revision != QWEN_REVISION
    {
        return Err(GfmError::InvalidCheckpoint(
            "Qwen artifact provenance does not match compiled pins".into(),
        ));
    }
    for required in [
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "model.safetensors",
    ] {
        if !manifest
            .artifacts
            .iter()
            .any(|artifact| artifact.file == required)
        {
            return Err(GfmError::InvalidCheckpoint(format!(
                "Qwen manifest is missing {required}"
            )));
        }
    }
    if !manifest.artifacts.iter().any(|artifact| {
        artifact.file == "model.safetensors" && artifact.sha256 == QWEN_SAFETENSORS_SHA256
    }) {
        return Err(GfmError::InvalidCheckpoint(
            "Qwen weights do not match the compiled digest".into(),
        ));
    }
    for artifact in manifest.artifacts {
        let path = if artifact.file == "model.safetensors" {
            materialized_weights.map_or_else(
                || model_dir.join(&artifact.file),
                |materialized| materialized.hot_path().to_path_buf(),
            )
        } else {
            model_dir.join(&artifact.file)
        };
        let metadata =
            std::fs::metadata(&path).map_err(|source| crate::error::io_error(&path, source))?;
        let digest_matches = if artifact.file == "model.safetensors" {
            materialized_weights.map_or_else(
                || sha256(&path).map(|digest| digest == artifact.sha256),
                |materialized| Ok(materialized.sha256() == artifact.sha256),
            )?
        } else {
            sha256(&path)? == artifact.sha256
        };
        if metadata.len() != artifact.bytes || !digest_matches {
            return Err(GfmError::InvalidCheckpoint(format!(
                "Qwen artifact checksum mismatch for {}",
                artifact.file
            )));
        }
    }
    Ok(())
}

fn sha256(path: &Path) -> Result<String> {
    let file = std::fs::File::open(path).map_err(|source| crate::error::io_error(path, source))?;
    let mut reader = BufReader::with_capacity(8 * 1024 * 1024, file);
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 8 * 1024 * 1024];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|source| crate::error::io_error(path, source))?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn normalize(value: &Tensor) -> Result<Tensor> {
    let norm = value.sqr()?.sum_all()?.sqrt()?;
    let norm_value = norm.to_scalar::<f32>()?;
    if !norm_value.is_finite() || norm_value <= f32::EPSILON {
        return Err(GfmError::Shape("Qwen embedding has invalid norm".into()));
    }
    Ok(value.broadcast_div(&norm)?)
}

#[cfg(test)]
mod tests {
    use super::QwenEmbedder;
    use crate::constants::QWEN_QUERY_INSTRUCTION;

    #[test]
    fn query_instruction_is_exact_and_not_applied_twice() {
        assert_eq!(
            QwenEmbedder::format_query("where is Phoenix?"),
            format!("{QWEN_QUERY_INSTRUCTION}where is Phoenix?")
        );
    }
}

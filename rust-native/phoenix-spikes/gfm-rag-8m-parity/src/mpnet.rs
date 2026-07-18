use std::io::Read;
use std::path::Path;

use ort::memory::{AllocationDevice, AllocatorType, MemoryInfo, MemoryType};
use ort::session::builder::GraphOptimizationLevel;
use ort::session::{Session, SessionInputValue};
use ort::value::TensorRefMut;
use phoenix_model_hot_cache::MaterializedArtifact;
use sha2::{Digest, Sha256};
use tokenizers::{Tokenizer, TruncationDirection, TruncationParams, TruncationStrategy};

use crate::constants::{EMBEDDING_DIM, MPNET_ONNX_SHA256, MPNET_REVISION};
use crate::error::io_error;
use crate::{GfmError, Result};

/// Pinned MPNet ONNX runtime. Mean pooling is intentionally not normalized.
pub struct MpnetEmbedder {
    session: Session,
    tokenizer: Tokenizer,
    cpu_memory: MemoryInfo,
}

impl MpnetEmbedder {
    pub fn open(model_path: impl AsRef<Path>, tokenizer_path: impl AsRef<Path>) -> Result<Self> {
        let model_path = model_path.as_ref();
        let digest = sha256_file(model_path)?;
        if digest != MPNET_ONNX_SHA256 {
            return Err(GfmError::InvalidCheckpoint(format!(
                "MPNet ONNX checksum mismatch for revision {MPNET_REVISION}"
            )));
        }
        Self::open_inner(model_path, tokenizer_path.as_ref())
    }

    pub fn open_materialized(
        artifact: &MaterializedArtifact,
        tokenizer_path: impl AsRef<Path>,
    ) -> Result<Self> {
        if artifact.sha256() != MPNET_ONNX_SHA256 {
            return Err(GfmError::InvalidCheckpoint(
                "materialized MPNet digest does not match the compiled pin".into(),
            ));
        }
        Self::open_inner(artifact.hot_path(), tokenizer_path.as_ref())
    }

    fn open_inner(model_path: &Path, tokenizer_path: &Path) -> Result<Self> {
        let mut tokenizer = Tokenizer::from_file(tokenizer_path)
            .map_err(|error| GfmError::Tokenizer(error.to_string()))?;
        tokenizer
            .with_truncation(Some(TruncationParams {
                max_length: 384,
                strategy: TruncationStrategy::LongestFirst,
                stride: 0,
                direction: TruncationDirection::Right,
            }))
            .map_err(|error| GfmError::Tokenizer(error.to_string()))?;
        let session = Session::builder()
            .map_err(|error| GfmError::Ort(error.to_string()))?
            .with_optimization_level(GraphOptimizationLevel::Level3)
            .map_err(|error| GfmError::Ort(error.to_string()))?
            .with_parallel_execution(false)
            .map_err(|error| GfmError::Ort(error.to_string()))?
            .with_inter_threads(1)
            .map_err(|error| GfmError::Ort(error.to_string()))?
            .with_intra_threads(
                std::thread::available_parallelism()
                    .map(usize::from)
                    .unwrap_or(1),
            )
            .map_err(|error| GfmError::Ort(error.to_string()))?
            .commit_from_file(model_path)
            .map_err(|error| GfmError::Ort(error.to_string()))?;
        let cpu_memory = MemoryInfo::new(
            AllocationDevice::CPU,
            0,
            AllocatorType::Arena,
            MemoryType::CPUInput,
        )
        .map_err(|error| GfmError::Ort(error.to_string()))?;
        Ok(Self {
            session,
            tokenizer,
            cpu_memory,
        })
    }

    pub fn embed_unnormalized(&mut self, text: &str) -> Result<Vec<f32>> {
        self.embed_unnormalized_batch(&[text])?
            .pop()
            .ok_or_else(|| GfmError::Shape("MPNet batch returned no row".into()))
    }

    pub fn embed_unnormalized_batch(&mut self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let encodings = texts
            .iter()
            .map(|text| {
                self.tokenizer
                    .encode(*text, true)
                    .map_err(|error| GfmError::Tokenizer(error.to_string()))
            })
            .collect::<Result<Vec<_>>>()?;
        let sequence = encodings
            .iter()
            .map(|encoding| encoding.len())
            .max()
            .unwrap_or(0);
        if sequence == 0 {
            return Err(GfmError::Shape("MPNet produced no tokens".into()));
        }
        let batch = encodings.len();
        let mut input_ids = vec![0_i64; batch * sequence];
        let mut attention = vec![0_i64; batch * sequence];
        for (row, encoding) in encodings.iter().enumerate() {
            let start = row * sequence;
            for (column, (&id, &keep)) in encoding
                .get_ids()
                .iter()
                .zip(encoding.get_attention_mask())
                .enumerate()
            {
                input_ids[start + column] = i64::from(id);
                attention[start + column] = i64::from(keep);
            }
        }
        let shape = [batch as i64, sequence as i64];
        let ids = tensor_ref(&self.cpu_memory, &mut input_ids, shape, "input_ids")?;
        let mask = tensor_ref(&self.cpu_memory, &mut attention, shape, "attention_mask")?;
        let outputs = self
            .session
            .run([SessionInputValue::from(ids), SessionInputValue::from(mask)])
            .map_err(|error| GfmError::Ort(format!("run: {error}")))?;
        let hidden = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|error| GfmError::Ort(format!("extract: {error}")))?;
        let view = hidden.view();
        let values = view
            .as_slice()
            .ok_or_else(|| GfmError::Ort("non-contiguous hidden state".into()))?;
        if view.shape() != [batch, sequence, EMBEDDING_DIM] {
            return Err(GfmError::Shape(format!(
                "unexpected MPNet output shape {:?}",
                view.shape()
            )));
        }
        let mut output = Vec::with_capacity(batch);
        for row in 0..batch {
            let mut pooled = vec![0_f32; EMBEDDING_DIM];
            let mut count = 0_f32;
            for token in 0..sequence {
                if attention[row * sequence + token] == 0 {
                    continue;
                }
                let start = (row * sequence + token) * EMBEDDING_DIM;
                let values = &values[start..start + EMBEDDING_DIM];
                for (output, &value) in pooled.iter_mut().zip(values) {
                    *output += value;
                }
                count += 1.0;
            }
            if count == 0.0 {
                return Err(GfmError::Shape("MPNet produced no unmasked tokens".into()));
            }
            for value in &mut pooled {
                *value /= count;
            }
            output.push(pooled);
        }
        Ok(output)
    }

    pub fn embed_unnormalized_chunked(
        &mut self,
        texts: &[&str],
        max_rows: usize,
    ) -> Result<Vec<Vec<f32>>> {
        if max_rows == 0 {
            return Err(GfmError::Shape(
                "MPNet chunk row limit must be nonzero".into(),
            ));
        }
        let mut output = Vec::with_capacity(texts.len());
        for chunk in texts.chunks(max_rows) {
            output.extend(self.embed_unnormalized_batch(chunk)?);
        }
        Ok(output)
    }
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut file = std::fs::File::open(path).map_err(|error| io_error(path, error))?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 8 * 1024 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| io_error(path, error))?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn tensor_ref<'a>(
    memory: &MemoryInfo,
    buffer: &'a mut Vec<i64>,
    shape: [i64; 2],
    label: &str,
) -> Result<TensorRefMut<'a, i64>> {
    // SAFETY: the Vec remains borrowed for the TensorRef lifetime and shape
    // exactly matches its initialized length.
    unsafe {
        TensorRefMut::from_raw(memory.clone(), buffer.as_mut_ptr().cast(), Vec::from(shape))
            .map_err(|error| GfmError::Ort(format!("{label}: {error}")))
    }
}

//! FP32 ONNX execution for the pinned Qwen3 embedding envelope.

use std::io::Read;
use std::path::Path;

use ort::memory::{AllocationDevice, AllocatorType, MemoryInfo, MemoryType};
use ort::session::builder::GraphOptimizationLevel;
use ort::session::{Session, SessionInputValue};
use ort::value::TensorRefMut;
use phoenix_model_hot_cache::MaterializedArtifact;
use sha2::{Digest, Sha256};
use tokenizers::Tokenizer;

use crate::constants::{
    FEATURE_DIM, QWEN_ONNX_DATA_SHA256, QWEN_ONNX_MODEL_SHA256, QWEN_QUERY_INSTRUCTION,
    QWEN_TOKENIZER_SHA256,
};
use crate::error::io_error;
use crate::{GfmError, Result};

/// A reusable ONNX Runtime session over an immutable two-file Qwen bundle.
pub struct QwenOnnxEmbedder {
    session: Session,
    tokenizer: Tokenizer,
    max_length: usize,
}

impl QwenOnnxEmbedder {
    pub fn open_materialized(
        bundle_root: impl AsRef<Path>,
        tokenizer_path: impl AsRef<Path>,
        model: &MaterializedArtifact,
        data: &MaterializedArtifact,
        max_length: usize,
    ) -> Result<Self> {
        if max_length == 0 {
            return Err(GfmError::Shape(
                "Qwen ONNX max_length must be nonzero".into(),
            ));
        }
        if model.sha256() != QWEN_ONNX_MODEL_SHA256 || data.sha256() != QWEN_ONNX_DATA_SHA256 {
            return Err(GfmError::InvalidCheckpoint(
                "materialized Qwen ONNX digests do not match compiled pins".into(),
            ));
        }
        let bundle_root = bundle_root.as_ref();
        let model_path = bundle_root.join("model.onnx");
        let data_path = bundle_root.join("model.onnx.data");
        if !model_path.is_file() || !data_path.is_file() {
            return Err(GfmError::InvalidCheckpoint(format!(
                "Qwen ONNX bundle is incomplete at {}",
                bundle_root.display()
            )));
        }
        let tokenizer_path = tokenizer_path.as_ref();
        if sha256_file(tokenizer_path)? != QWEN_TOKENIZER_SHA256 {
            return Err(GfmError::InvalidCheckpoint(
                "Qwen tokenizer digest does not match the compiled pin".into(),
            ));
        }
        let tokenizer = Tokenizer::from_file(tokenizer_path)
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
            .commit_from_file(&model_path)
            .map_err(|error| GfmError::Ort(error.to_string()))?;
        Ok(Self {
            session,
            tokenizer,
            max_length,
        })
    }

    pub fn format_query(query: &str) -> String {
        let mut formatted = String::with_capacity(QWEN_QUERY_INSTRUCTION.len() + query.len());
        formatted.push_str(QWEN_QUERY_INSTRUCTION);
        formatted.push_str(query);
        formatted
    }

    pub fn embed_query(&mut self, query: &str) -> Result<Vec<f32>> {
        self.embed_text(&Self::format_query(query))
    }

    pub fn embed_passage(&mut self, text: &str) -> Result<Vec<f32>> {
        self.embed_text(text)
    }

    pub fn embed_passages_chunked(
        &mut self,
        texts: &[&str],
        max_rows: usize,
    ) -> Result<Vec<Vec<f32>>> {
        if max_rows == 0 {
            return Err(GfmError::Shape(
                "Qwen ONNX chunk row limit must be nonzero".into(),
            ));
        }
        let mut output = Vec::with_capacity(texts.len());
        for chunk in texts.chunks(max_rows) {
            output.extend(self.embed_texts(chunk)?);
        }
        Ok(output)
    }

    fn embed_text(&mut self, text: &str) -> Result<Vec<f32>> {
        self.embed_texts(&[text])?
            .pop()
            .ok_or_else(|| GfmError::Shape("Qwen ONNX batch returned no row".into()))
    }

    fn embed_texts(&mut self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
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
        if sequence == 0 || sequence > self.max_length {
            return Err(GfmError::Shape(format!(
                "Qwen ONNX sequence length {sequence} is outside 1..={}",
                self.max_length
            )));
        }
        let batch = encodings.len();
        let mut input_ids = vec![0_i64; batch * sequence];
        let mut attention = vec![0_i64; batch * sequence];
        for (row, encoding) in encodings.iter().enumerate() {
            let start = row * sequence;
            for (column, &id) in encoding.get_ids().iter().enumerate() {
                input_ids[start + column] = i64::from(id);
                attention[start + column] = 1;
            }
        }
        let shape = [batch as i64, sequence as i64];
        let cpu_memory = MemoryInfo::new(
            AllocationDevice::CPU,
            0,
            AllocatorType::Arena,
            MemoryType::CPUInput,
        )
        .map_err(|error| GfmError::Ort(error.to_string()))?;
        let ids = tensor_ref(&cpu_memory, &mut input_ids, shape, "input_ids")?;
        let mask = tensor_ref(&cpu_memory, &mut attention, shape, "attention_mask")?;
        let outputs = self
            .session
            .run([SessionInputValue::from(ids), SessionInputValue::from(mask)])
            .map_err(|error| GfmError::Ort(format!("run: {error}")))?;
        let embeddings = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|error| GfmError::Ort(format!("extract: {error}")))?;
        let view = embeddings.view();
        if view.shape() != [batch, FEATURE_DIM] {
            return Err(GfmError::Shape(format!(
                "unexpected Qwen ONNX output shape {:?}",
                view.shape()
            )));
        }
        let values = view
            .as_slice()
            .ok_or_else(|| GfmError::Ort("non-contiguous Qwen ONNX embedding".into()))?;
        let mut output = Vec::with_capacity(batch);
        for row in values.chunks_exact(FEATURE_DIM) {
            let norm = row.iter().map(|value| value * value).sum::<f32>().sqrt();
            if !norm.is_finite() || (norm - 1.0).abs() > 1.0e-3 {
                return Err(GfmError::Shape(format!(
                    "Qwen ONNX returned invalid normalized embedding: {norm}"
                )));
            }
            output.push(row.to_vec());
        }
        Ok(output)
    }
}

fn tensor_ref<'a>(
    memory: &MemoryInfo,
    buffer: &'a mut Vec<i64>,
    shape: [i64; 2],
    label: &str,
) -> Result<TensorRefMut<'a, i64>> {
    // SAFETY: the Vec remains borrowed for the TensorRef lifetime and the
    // supplied shape exactly matches its initialized length.
    unsafe {
        TensorRefMut::from_raw(memory.clone(), buffer.as_mut_ptr().cast(), Vec::from(shape))
            .map_err(|error| GfmError::Ort(format!("{label}: {error}")))
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

#[cfg(test)]
mod tests {
    use super::QwenOnnxEmbedder;
    use crate::constants::QWEN_QUERY_INSTRUCTION;

    #[test]
    fn query_instruction_is_exact() {
        assert_eq!(
            QwenOnnxEmbedder::format_query("where is Phoenix?"),
            format!("{QWEN_QUERY_INSTRUCTION}where is Phoenix?")
        );
    }
}

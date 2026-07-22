use std::fs::{File, OpenOptions};
use std::path::{Path, PathBuf};

use candle_core::{DType, Device, Tensor};
use memmap2::{Mmap, MmapOptions};
use phoenix_model_hot_cache::MaterializedArtifact;
use safetensors::SafeTensors;
use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::constants::{CHECKPOINT_REVISION, CHECKPOINT_SAFETENSORS_SHA256, UPSTREAM_REVISION};
use crate::error::io_error;
use crate::{GfmError, Result};

#[derive(Debug, Deserialize)]
pub struct CheckpointManifest {
    pub schema: String,
    pub checkpoint_revision: String,
    pub upstream_revision: String,
    pub source_sha256: String,
    pub safetensors_sha256: String,
    pub parameter_count: u64,
    pub tensors: Vec<TensorManifest>,
}

#[derive(Debug, Deserialize)]
pub struct TensorManifest {
    pub name: String,
    pub shape: Vec<usize>,
    pub dtype: String,
    pub sha256: String,
}

/// Read-only, memory-mapped safetensors checkpoint with pinned provenance.
pub struct MappedCheckpoint {
    mmap: Mmap,
    manifest: CheckpointManifest,
    path: PathBuf,
}

impl MappedCheckpoint {
    pub fn open(path: impl AsRef<Path>, manifest_path: impl AsRef<Path>) -> Result<Self> {
        Self::open_inner(path.as_ref(), manifest_path.as_ref(), None)
    }

    pub fn open_materialized(
        artifact: &MaterializedArtifact,
        manifest_path: impl AsRef<Path>,
    ) -> Result<Self> {
        Self::open_inner(artifact.hot_path(), manifest_path.as_ref(), Some(artifact))
    }

    fn open_inner(
        path: &Path,
        manifest_path: &Path,
        materialized: Option<&MaterializedArtifact>,
    ) -> Result<Self> {
        let path = path.to_path_buf();
        let manifest: CheckpointManifest = serde_json::from_reader(
            File::open(manifest_path).map_err(|error| io_error(manifest_path, error))?,
        )?;
        if manifest.schema != "phoenix.gfm.checkpoint-manifest.v1"
            || manifest.checkpoint_revision != CHECKPOINT_REVISION
            || manifest.upstream_revision != UPSTREAM_REVISION
            || manifest.safetensors_sha256 != CHECKPOINT_SAFETENSORS_SHA256
        {
            return Err(GfmError::InvalidCheckpoint(
                "manifest provenance does not match compiled pins".into(),
            ));
        }
        let file = OpenOptions::new()
            .read(true)
            .open(&path)
            .map_err(|error| io_error(&path, error))?;
        // SAFETY: the map is read-only and the converted checkpoint is immutable.
        let mmap =
            unsafe { MmapOptions::new().map(&file) }.map_err(|error| io_error(&path, error))?;
        if let Some(materialized) = materialized {
            if materialized.sha256() != manifest.safetensors_sha256 {
                return Err(GfmError::InvalidCheckpoint(
                    "materialized checkpoint digest does not match manifest".into(),
                ));
            }
        } else {
            let digest = format!("{:x}", Sha256::digest(&mmap));
            if digest != manifest.safetensors_sha256 {
                return Err(GfmError::InvalidCheckpoint(format!(
                    "safetensors SHA-256 mismatch: expected {}, got {digest}",
                    manifest.safetensors_sha256
                )));
            }
        }
        let tensors = SafeTensors::deserialize(&mmap)?;
        if tensors.len() != manifest.tensors.len() {
            return Err(GfmError::InvalidCheckpoint("tensor count mismatch".into()));
        }
        for expected in &manifest.tensors {
            let view = tensors.tensor(&expected.name)?;
            if view.shape() != expected.shape || expected.dtype != "float32" {
                return Err(GfmError::InvalidCheckpoint(format!(
                    "manifest mismatch for tensor {}",
                    expected.name
                )));
            }
        }
        Ok(Self {
            mmap,
            manifest,
            path,
        })
    }

    pub fn manifest(&self) -> &CheckpointManifest {
        &self.manifest
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn tensor(&self, name: &str, device: &Device) -> Result<Tensor> {
        let tensors = SafeTensors::deserialize(&self.mmap)?;
        let view = tensors.tensor(name)?;
        if view.dtype() != safetensors::Dtype::F32 {
            return Err(GfmError::InvalidCheckpoint(format!("{name} is not F32")));
        }
        Ok(Tensor::from_raw_buffer(
            view.data(),
            DType::F32,
            view.shape(),
            device,
        )?)
    }
}

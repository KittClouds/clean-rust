use anyhow::{Context, Result};
use memmap2::Mmap;
use phoenix_analysis_contract::AnalysisModelIdentity;
use std::fs::File;
use std::path::Path;

pub fn file_hash(path: &Path) -> Result<[u8; 32]> {
    let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    // SAFETY: Model and executable assets are immutable during bridge execution.
    let mapping = unsafe { Mmap::map(&file) }.with_context(|| format!("map {}", path.display()))?;
    Ok(*blake3::hash(&mapping).as_bytes())
}

pub fn combined_file_hash(paths: &[&Path]) -> Result<[u8; 32]> {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix.analysis.asset-set/v1\0");
    for path in paths {
        let metadata =
            std::fs::metadata(path).with_context(|| format!("read metadata {}", path.display()))?;
        hasher.update(path.to_string_lossy().as_bytes());
        hasher.update(&metadata.len().to_le_bytes());
        hasher.update(&file_hash(path)?);
    }
    Ok(*hasher.finalize().as_bytes())
}

pub fn config_hash(bytes: &[u8]) -> [u8; 32] {
    *blake3::hash(bytes).as_bytes()
}

pub fn identity(
    model_id: impl Into<String>,
    artifact_hash: [u8; 32],
    config_hash: [u8; 32],
    runtime_id: impl Into<String>,
) -> AnalysisModelIdentity {
    AnalysisModelIdentity {
        model_id: model_id.into(),
        artifact_hash,
        config_hash,
        runtime_id: runtime_id.into(),
    }
}

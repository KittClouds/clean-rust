use std::path::PathBuf;
use std::{env, io};

use phoenix_embed::{
    default_embedding_model_root, OrtExecutionProviderPreference, OrtTextEmbedConfig,
    OrtTextEmbedError, OrtTextEmbedder, TextEmbeddingProfile,
};
use phoenix_store_native_core::SEMANTIC_MODEL_ID;
use thiserror::Error;

pub type SnowflakeOrtEmbedder = OrtTextEmbedder;
pub use phoenix_embed::{default_ort_dylib_path, workspace_root};

#[derive(Debug, Error)]
pub enum SemanticNeighborError {
    #[error(transparent)]
    Embed(#[from] OrtTextEmbedError),
    #[error(transparent)]
    Io(#[from] io::Error),
    #[error("semantic embedding cache error: {0}")]
    Cache(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SemanticEmbedConfig {
    pub model_id: String,
    pub model_root: PathBuf,
    pub embedding_cache_dir: Option<PathBuf>,
    pub batch_size: usize,
    pub max_length: usize,
    pub profile: TextEmbeddingProfile,
    pub execution_provider: OrtExecutionProviderPreference,
}

impl Default for SemanticEmbedConfig {
    fn default() -> Self {
        Self {
            model_id: SEMANTIC_MODEL_ID.to_owned(),
            model_root: default_embedding_model_root(),
            embedding_cache_dir: env::var_os("PHOENIX_SEMANTIC_EMBED_CACHE_DIR").map(PathBuf::from),
            batch_size: 12,
            max_length: 512,
            profile: TextEmbeddingProfile::Native384,
            execution_provider: OrtExecutionProviderPreference::from_env(),
        }
    }
}

impl SemanticEmbedConfig {
    pub fn execution_provider(&self) -> OrtExecutionProviderPreference {
        self.execution_provider
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticEmbeddingBatch {
    pub values: Vec<f32>,
    pub rows: usize,
    pub dims: usize,
    pub cache_hits: usize,
    pub cache_misses: usize,
}

pub fn semantic_embedder(
    config: &SemanticEmbedConfig,
) -> Result<SnowflakeOrtEmbedder, SemanticNeighborError> {
    let _ = ensure_ort_dylib_path();
    Ok(SnowflakeOrtEmbedder::load(&OrtTextEmbedConfig {
        model_root: config.model_root.clone(),
        batch_size: config.batch_size,
        max_length: config.max_length,
        profile: config.profile,
        prefix_passage: true,
        pooling: Default::default(),
        input_prefix: Default::default(),
        batch_order: Default::default(),
        execution_provider: config.execution_provider(),
    })?)
}

pub fn ensure_ort_dylib_path() -> Option<PathBuf> {
    if let Some(existing) = env::var_os("ORT_DYLIB_PATH") {
        return Some(PathBuf::from(existing));
    }
    let root = workspace_root();
    let path = default_ort_dylib_path(&root)?;
    env::set_var("ORT_DYLIB_PATH", &path);
    Some(path)
}

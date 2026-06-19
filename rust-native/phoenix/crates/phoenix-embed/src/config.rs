use std::{env, path::PathBuf};

use crate::default_embedding_model_root;

const PASSAGE_PREFIX: &str = "passage: ";
const JINA_QUERY_PREFIX: &str = "Query: ";
const JINA_DOCUMENT_PREFIX: &str = "Document: ";
const MDBR_LEAF_QUERY_PREFIX: &str = "Represent this sentence for searching relevant passages: ";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TextEmbeddingProfile {
    Truncate128,
    Truncate256,
    Truncate512,
    Native384,
    Native768,
    Native1024,
}

impl Default for TextEmbeddingProfile {
    fn default() -> Self {
        Self::Native384
    }
}

impl TextEmbeddingProfile {
    pub fn parse(value: &str) -> Option<Self> {
        match value.trim().to_ascii_lowercase().as_str() {
            "128" | "128-truncated" | "truncated-128" => Some(Self::Truncate128),
            "256" | "256-truncated" | "truncated-256" => Some(Self::Truncate256),
            "512" | "512-truncated" | "truncated-512" => Some(Self::Truncate512),
            "384" | "native-384" => Some(Self::Native384),
            "768" | "native-768" | "786" | "native-786" => Some(Self::Native768),
            "1024" | "native-1024" => Some(Self::Native1024),
            _ => None,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Truncate128 => "128-truncated",
            Self::Truncate256 => "256-truncated",
            Self::Truncate512 => "512-truncated",
            Self::Native384 => "384",
            Self::Native768 => "768",
            Self::Native1024 => "1024",
        }
    }

    pub fn target_dim(self) -> usize {
        match self {
            Self::Truncate128 => 128,
            Self::Truncate256 => 256,
            Self::Truncate512 => 512,
            Self::Native384 => 384,
            Self::Native768 => 768,
            Self::Native1024 => 1024,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum TextEmbeddingPooling {
    #[default]
    Cls,
    Mean,
    LastToken,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum TextEmbeddingInputPrefix {
    #[default]
    None,
    Passage,
    JinaQuery,
    JinaDocument,
    MdbrLeafQuery,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum OrtExecutionProviderPreference {
    #[default]
    Cpu,
    DirectMl,
    Cuda,
}

impl OrtExecutionProviderPreference {
    pub fn from_env() -> Self {
        env::var("PHOENIX_EMBED_ORT_EP")
            .ok()
            .and_then(|value| Self::parse(&value))
            .unwrap_or_default()
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value.trim().to_ascii_lowercase().as_str() {
            "" | "cpu" => Some(Self::Cpu),
            "dml" | "directml" | "direct-ml" => Some(Self::DirectMl),
            "cuda" | "nvidia" => Some(Self::Cuda),
            _ => None,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Cpu => "cpu",
            Self::DirectMl => "directml",
            Self::Cuda => "cuda",
        }
    }
}

impl TextEmbeddingInputPrefix {
    pub(crate) fn text(self) -> &'static str {
        match self {
            Self::None => "",
            Self::Passage => PASSAGE_PREFIX,
            Self::JinaQuery => JINA_QUERY_PREFIX,
            Self::JinaDocument => JINA_DOCUMENT_PREFIX,
            Self::MdbrLeafQuery => MDBR_LEAF_QUERY_PREFIX,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OrtTextEmbedConfig {
    pub model_root: PathBuf,
    pub batch_size: usize,
    pub max_length: usize,
    pub profile: TextEmbeddingProfile,
    pub prefix_passage: bool,
    pub pooling: TextEmbeddingPooling,
    pub input_prefix: TextEmbeddingInputPrefix,
    pub execution_provider: OrtExecutionProviderPreference,
}

impl Default for OrtTextEmbedConfig {
    fn default() -> Self {
        Self {
            model_root: default_embedding_model_root(),
            batch_size: 12,
            max_length: 512,
            profile: TextEmbeddingProfile::default(),
            prefix_passage: false,
            pooling: TextEmbeddingPooling::default(),
            input_prefix: TextEmbeddingInputPrefix::default(),
            execution_provider: OrtExecutionProviderPreference::from_env(),
        }
    }
}

impl OrtTextEmbedConfig {
    pub fn jina_v5_retrieval_query(model_root: PathBuf) -> Self {
        Self {
            model_root,
            batch_size: 8,
            max_length: 1024,
            profile: TextEmbeddingProfile::Native768,
            prefix_passage: false,
            pooling: TextEmbeddingPooling::LastToken,
            input_prefix: TextEmbeddingInputPrefix::JinaQuery,
            execution_provider: OrtExecutionProviderPreference::from_env(),
        }
    }

    pub fn jina_v5_retrieval_document(model_root: PathBuf) -> Self {
        Self {
            input_prefix: TextEmbeddingInputPrefix::JinaDocument,
            ..Self::jina_v5_retrieval_query(model_root)
        }
    }

    pub fn mdbr_leaf_mt_query(model_root: PathBuf) -> Self {
        Self {
            model_root,
            batch_size: 16,
            max_length: 512,
            profile: TextEmbeddingProfile::Native384,
            prefix_passage: false,
            pooling: TextEmbeddingPooling::Mean,
            input_prefix: TextEmbeddingInputPrefix::MdbrLeafQuery,
            execution_provider: OrtExecutionProviderPreference::from_env(),
        }
    }

    pub fn mdbr_leaf_mt_document(model_root: PathBuf) -> Self {
        Self {
            input_prefix: TextEmbeddingInputPrefix::None,
            ..Self::mdbr_leaf_mt_query(model_root)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mdbr_leaf_mt_query_uses_native_384_profile() {
        let config = OrtTextEmbedConfig::mdbr_leaf_mt_query(PathBuf::from("models/mdbr"));

        assert_eq!(config.model_root, PathBuf::from("models/mdbr"));
        assert_eq!(config.batch_size, 16);
        assert_eq!(config.max_length, 512);
        assert_eq!(config.profile, TextEmbeddingProfile::Native384);
        assert_eq!(config.profile.target_dim(), 384);
        assert_eq!(config.pooling, TextEmbeddingPooling::Mean);
        assert_eq!(config.input_prefix, TextEmbeddingInputPrefix::MdbrLeafQuery);
        assert_eq!(
            config.input_prefix.text(),
            "Represent this sentence for searching relevant passages: "
        );
    }

    #[test]
    fn mdbr_leaf_mt_document_keeps_passages_unprefixed() {
        let config = OrtTextEmbedConfig::mdbr_leaf_mt_document(PathBuf::from("models/mdbr"));

        assert_eq!(config.profile, TextEmbeddingProfile::Native384);
        assert_eq!(config.pooling, TextEmbeddingPooling::Mean);
        assert_eq!(config.input_prefix, TextEmbeddingInputPrefix::None);
        assert_eq!(config.input_prefix.text(), "");
    }
}

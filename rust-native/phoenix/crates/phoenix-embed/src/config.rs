use std::{env, path::PathBuf};

use crate::default_embedding_model_root;

const PASSAGE_PREFIX: &str = "passage: ";
const JINA_QUERY_PREFIX: &str = "Query: ";
const JINA_DOCUMENT_PREFIX: &str = "Document: ";
const MDBR_LEAF_QUERY_PREFIX: &str = "Represent this sentence for searching relevant passages: ";
const EMBEDDING_GEMMA_QUERY_PREFIX: &str = "task: search result | query: ";
const EMBEDDING_GEMMA_DOCUMENT_PREFIX: &str = "title: none | text: ";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum EmbeddingBatchOrder {
    #[default]
    Input,
    LengthBucketed,
}

impl EmbeddingBatchOrder {
    pub fn label(self) -> &'static str {
        match self {
            Self::Input => "input",
            Self::LengthBucketed => "length-bucketed",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum TextEmbeddingProfile {
    Truncate128,
    Truncate256,
    Truncate512,
    #[default]
    Native384,
    Native768,
    Native1024,
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
    EmbeddingGemmaQuery,
    EmbeddingGemmaDocument,
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
            Self::EmbeddingGemmaQuery => EMBEDDING_GEMMA_QUERY_PREFIX,
            Self::EmbeddingGemmaDocument => EMBEDDING_GEMMA_DOCUMENT_PREFIX,
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
    pub batch_order: EmbeddingBatchOrder,
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
            batch_order: EmbeddingBatchOrder::Input,
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
            batch_order: EmbeddingBatchOrder::LengthBucketed,
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
            batch_order: EmbeddingBatchOrder::Input,
            execution_provider: OrtExecutionProviderPreference::from_env(),
        }
    }

    pub fn mdbr_leaf_mt_document(model_root: PathBuf) -> Self {
        Self {
            input_prefix: TextEmbeddingInputPrefix::None,
            ..Self::mdbr_leaf_mt_query(model_root)
        }
    }

    pub fn embedding_gemma_query(model_root: PathBuf) -> Self {
        Self {
            model_root,
            batch_size: 8,
            max_length: 2048,
            profile: TextEmbeddingProfile::Native768,
            prefix_passage: false,
            pooling: TextEmbeddingPooling::Mean,
            input_prefix: TextEmbeddingInputPrefix::EmbeddingGemmaQuery,
            batch_order: EmbeddingBatchOrder::LengthBucketed,
            execution_provider: OrtExecutionProviderPreference::from_env(),
        }
    }

    pub fn embedding_gemma_document(model_root: PathBuf) -> Self {
        Self {
            input_prefix: TextEmbeddingInputPrefix::EmbeddingGemmaDocument,
            ..Self::embedding_gemma_query(model_root)
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
        assert_eq!(config.batch_order, EmbeddingBatchOrder::Input);
        assert_eq!(
            config.input_prefix.text(),
            "Represent this sentence for searching relevant passages: "
        );
    }

    #[test]
    fn jina_v5_uses_qualified_length_bucketed_batches() {
        let config = OrtTextEmbedConfig::jina_v5_retrieval_query(PathBuf::from("models/jina"));

        assert_eq!(config.profile, TextEmbeddingProfile::Native768);
        assert_eq!(config.batch_order, EmbeddingBatchOrder::LengthBucketed);
    }

    #[test]
    fn mdbr_leaf_mt_document_keeps_passages_unprefixed() {
        let config = OrtTextEmbedConfig::mdbr_leaf_mt_document(PathBuf::from("models/mdbr"));

        assert_eq!(config.profile, TextEmbeddingProfile::Native384);
        assert_eq!(config.pooling, TextEmbeddingPooling::Mean);
        assert_eq!(config.input_prefix, TextEmbeddingInputPrefix::None);
        assert_eq!(config.input_prefix.text(), "");
    }

    #[test]
    fn embedding_gemma_uses_official_prefixes_and_native_dimension() {
        let query = OrtTextEmbedConfig::embedding_gemma_query(PathBuf::from("models/gemma"));
        let document = OrtTextEmbedConfig::embedding_gemma_document(PathBuf::from("models/gemma"));

        assert_eq!(query.profile, TextEmbeddingProfile::Native768);
        assert_eq!(query.max_length, 2048);
        assert_eq!(query.batch_order, EmbeddingBatchOrder::LengthBucketed);
        assert_eq!(query.input_prefix.text(), "task: search result | query: ");
        assert_eq!(document.input_prefix.text(), "title: none | text: ");
    }
}

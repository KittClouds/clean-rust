pub const CHECKPOINT_REPOSITORY: &str = "rmanluo/G-reasoner-34M";
pub const CHECKPOINT_REVISION: &str = "a3a4ed2c62281e1c3e0551bd42f2072d9204674f";
pub const UPSTREAM_REPOSITORY: &str = "RManLuo/gfm-rag";
pub const UPSTREAM_REVISION: &str = "57e3e28045fffff5411e2454a4323fbe4dff9b91";
pub const CHECKPOINT_SAFETENSORS_SHA256: &str =
    "b62cc4a9bd186ea9f7549814d9641e3aebe7c849c510892c3b83aaee3ef8fa73";
pub const QWEN_REPOSITORY: &str = "Qwen/Qwen3-Embedding-0.6B";
pub const QWEN_REVISION: &str = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3";
pub const QWEN_SAFETENSORS_SHA256: &str =
    "0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd";
pub const QWEN_TOKENIZER_SHA256: &str =
    "def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a";
pub const QWEN_ONNX_MODEL_SHA256: &str =
    "b6c87649f0856e31ceca18cacf31ff26b43080022af620591909327e29e861bb";
pub const QWEN_ONNX_DATA_SHA256: &str =
    "2611cd936457a18786d4e0ffc7d21a5029f64df4cfc2fb69f87d9392108fa2f5";
pub const QWEN_ONNX_BUNDLE_BLAKE3: &str =
    "0d82159172ff1c7085b9291c340bff35d7314b004dcee9e5c3556e2b43972104";
pub const QWEN_QUERY_INSTRUCTION: &str =
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ";

pub const FEATURE_DIM: usize = 1024;
pub const HIDDEN_DIM: usize = 1024;
pub const LAYER_COUNT: usize = 6;
pub const GRAPH_ARTIFACT_MAGIC: [u8; 8] = *b"GR34CSR1";
pub const GRAPH_ARTIFACT_VERSION: u32 = 1;

pub const CHECKPOINT_REPOSITORY: &str = "rmanluo/GFM-RAG-8M";
pub const CHECKPOINT_REVISION: &str = "4da9e4655d126a783ae2b795ab73b7c7a7c3f4ac";
pub const UPSTREAM_REPOSITORY: &str = "RManLuo/gfm-rag";
pub const UPSTREAM_REVISION: &str = "57e3e28045fffff5411e2454a4323fbe4dff9b91";
pub const CHECKPOINT_SAFETENSORS_SHA256: &str =
    "9e4a79d25829c4356bcc58c8bd433a985e02fd52a0885f1745f2560cbc75528b";
pub const MPNET_REPOSITORY: &str = "sentence-transformers/all-mpnet-base-v2";
pub const MPNET_REVISION: &str = "e8c3b32edf5434bc2275fc9bab85f82640a19130";
pub const MPNET_ONNX_SHA256: &str =
    "74187b16d9c946fea252e120cfd7a12c5779d8b8b86838a2e4c56573c47941bd";

pub const EMBEDDING_DIM: usize = 768;
pub const HIDDEN_DIM: usize = 512;
pub const LAYER_COUNT: usize = 6;
pub const TOP_K_ENTITIES: usize = 20;
pub const GRAPH_ARTIFACT_MAGIC: [u8; 8] = *b"GFMCSR01";
pub const GRAPH_ARTIFACT_VERSION: u32 = 1;

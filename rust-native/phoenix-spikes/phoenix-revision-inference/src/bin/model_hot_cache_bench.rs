use std::path::PathBuf;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use g_reasoner_34m_parity::constants::{
    CHECKPOINT_SAFETENSORS_SHA256 as REASONER_CHECKPOINT_SHA256, QWEN_SAFETENSORS_SHA256,
};
use gfm_rag_8m_parity::constants::{
    CHECKPOINT_SAFETENSORS_SHA256 as GFM_CHECKPOINT_SHA256, MPNET_ONNX_SHA256,
};
use phoenix_model_hot_cache::{MaterializationReceipt, ModelHotCache};
use serde::Serialize;

const CHUNK_BYTES: usize = 16 * 1024 * 1024;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ArtifactBenchReceipt {
    name: &'static str,
    source: PathBuf,
    hot_path: PathBuf,
    materialization: MaterializationReceipt,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BenchReceipt {
    schema: &'static str,
    cache_root: PathBuf,
    chunk_bytes: usize,
    complete_micros: u64,
    artifacts: Vec<ArtifactBenchReceipt>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cache_root = model_hot_cache_root();
    let cache = ModelHotCache::new(&cache_root, CHUNK_BYTES)?;
    let assets = [
        (
            "mpnet-onnx",
            PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\onnx\model.onnx"),
            MPNET_ONNX_SHA256,
        ),
        (
            "gfm-rag-8m-checkpoint",
            PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\gfm-rag-8m.safetensors"),
            GFM_CHECKPOINT_SHA256,
        ),
        (
            "qwen-0.6b-weights",
            PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen\model.safetensors"),
            QWEN_SAFETENSORS_SHA256,
        ),
        (
            "g-reasoner-34m-checkpoint",
            PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\assets\g-reasoner-34m.safetensors"),
            REASONER_CHECKPOINT_SHA256,
        ),
    ];
    let started = Instant::now();
    let mut artifacts = Vec::with_capacity(assets.len());
    for (name, source, digest) in assets {
        let artifact = cache.materialize(&source, digest)?;
        artifacts.push(ArtifactBenchReceipt {
            name,
            source,
            hot_path: artifact.hot_path().to_path_buf(),
            materialization: artifact.receipt().clone(),
        });
    }
    let receipt = BenchReceipt {
        schema: "phoenix.model-hot-cache-bench/v1",
        cache_root,
        chunk_bytes: CHUNK_BYTES,
        complete_micros: micros(started.elapsed()),
        artifacts,
    };
    let encoded = serde_json::to_vec_pretty(&receipt)?;
    persist(&encoded)?;
    use std::io::Write;
    std::io::stdout().lock().write_all(&encoded)?;
    println!();
    Ok(())
}

fn model_hot_cache_root() -> PathBuf {
    std::env::var_os("PHOENIX_MODEL_HOT_CACHE_ROOT").map_or_else(
        || {
            std::env::var_os("LOCALAPPDATA").map_or_else(
                || PathBuf::from(r"C:\phoenix-model-hot-cache"),
                |root| PathBuf::from(root).join("Phoenix/model-hot-cache/v1"),
            )
        },
        PathBuf::from,
    )
}

fn persist(encoded: &[u8]) -> std::io::Result<()> {
    use std::io::Write;

    let root = PathBuf::from(r"D:\phoenix-target-revision-inference\receipts");
    std::fs::create_dir_all(&root)?;
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let path = root.join(format!(
        "model-hot-cache-{timestamp}-{}.json",
        std::process::id()
    ));
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)?;
    file.write_all(encoded)
}

fn micros(duration: std::time::Duration) -> u64 {
    duration.as_micros().min(u64::MAX as u128) as u64
}

use std::path::PathBuf;
use std::time::Instant;

use g_reasoner_34m_parity::constants::{QWEN_ONNX_DATA_SHA256, QWEN_ONNX_MODEL_SHA256};
use g_reasoner_34m_parity::qwen_onnx::QwenOnnxEmbedder;
use phoenix_model_hot_cache::ModelHotCache;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let source = argument(1)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen-onnx-fp32\fp32"));
    let tokenizer = argument(2)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen\tokenizer.json"));
    let runtime = argument(3).unwrap_or_else(|| {
        PathBuf::from(
            r"D:\phoenix-target-gfm-rag-8m\runtime\onnxruntime-1.20.1\package-v2\runtimes\win-x64\native\onnxruntime.dll",
        )
    });
    let cache_root = argument(4).unwrap_or_else(default_cache_root);
    ort::init_from(runtime.to_string_lossy()).commit()?;
    let cache = ModelHotCache::new(cache_root, 16 * 1024 * 1024)?;

    let started = Instant::now();
    let model = cache.materialize(source.join("model.onnx"), QWEN_ONNX_MODEL_SHA256)?;
    let data = cache.materialize(source.join("model.onnx.data"), QWEN_ONNX_DATA_SHA256)?;
    let bundle = cache.assemble_bundle(&[(&model, "model.onnx"), (&data, "model.onnx.data")])?;
    let cache_micros = micros(started.elapsed());

    let started = Instant::now();
    let mut encoder =
        QwenOnnxEmbedder::open_materialized(bundle.root(), tokenizer, &model, &data, 512)?;
    let load_micros = micros(started.elapsed());
    let query = "Which document explains Ryan arriving in New Rome?";
    let started = Instant::now();
    let cold = encoder.embed_query(query)?;
    let cold_micros = micros(started.elapsed());
    let started = Instant::now();
    let warm = encoder.embed_query(query)?;
    let warm_micros = micros(started.elapsed());
    let max_repeat_delta = cold
        .iter()
        .zip(&warm)
        .map(|(left, right)| (left - right).abs())
        .fold(0.0_f32, f32::max);
    let started = Instant::now();
    let batch = encoder.embed_passages_chunked(
        &[
            "Ryan",
            "New Rome",
            "A much longer passage about temporal travel.",
        ],
        3,
    )?;
    let batch_micros = micros(started.elapsed());
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "schema": "phoenix.qwen-onnx-smoke/v1",
            "bundleDigest": bundle.digest(),
            "bundleReused": bundle.reused(),
            "modelCache": model.receipt(),
            "dataCache": data.receipt(),
            "cacheMicros": cache_micros,
            "loadMicros": load_micros,
            "coldMicros": cold_micros,
            "warmMicros": warm_micros,
            "batchRows": batch.len(),
            "batchMicros": batch_micros,
            "embeddingDimensions": cold.len(),
            "maxRepeatDelta": max_repeat_delta,
        }))?
    );
    Ok(())
}

fn argument(index: usize) -> Option<PathBuf> {
    std::env::args_os().nth(index).map(PathBuf::from)
}

fn default_cache_root() -> PathBuf {
    std::env::var_os("LOCALAPPDATA").map_or_else(
        || PathBuf::from(r"C:\phoenix-model-hot-cache"),
        |root| PathBuf::from(root).join("Phoenix/model-hot-cache/v1"),
    )
}

fn micros(duration: std::time::Duration) -> u64 {
    duration.as_micros().min(u64::MAX as u128) as u64
}

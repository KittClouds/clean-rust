use std::path::PathBuf;
use std::time::Instant;

use g_reasoner_34m_parity::constants::{
    QWEN_ONNX_DATA_SHA256, QWEN_ONNX_MODEL_SHA256, QWEN_SAFETENSORS_SHA256,
};
use g_reasoner_34m_parity::qwen::QwenEmbedder;
use g_reasoner_34m_parity::qwen_onnx::QwenOnnxEmbedder;
use phoenix_model_hot_cache::ModelHotCache;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let qwen = PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen");
    let onnx = PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen-onnx-fp32\fp32");
    let runtime = PathBuf::from(
        r"D:\phoenix-target-gfm-rag-8m\runtime\onnxruntime-1.20.1\package-v2\runtimes\win-x64\native\onnxruntime.dll",
    );
    ort::init_from(runtime.to_string_lossy()).commit()?;
    let cache = ModelHotCache::new(default_cache_root(), 16 * 1024 * 1024)?;
    let weights = cache.materialize(qwen.join("model.safetensors"), QWEN_SAFETENSORS_SHA256)?;
    let model = cache.materialize(onnx.join("model.onnx"), QWEN_ONNX_MODEL_SHA256)?;
    let data = cache.materialize(onnx.join("model.onnx.data"), QWEN_ONNX_DATA_SHA256)?;
    let bundle = cache.assemble_bundle(&[(&model, "model.onnx"), (&data, "model.onnx.data")])?;
    let candle = QwenEmbedder::load_materialized(&qwen, 512, &weights)?;
    let mut ort = QwenOnnxEmbedder::open_materialized(
        bundle.root(),
        qwen.join("tokenizer.json"),
        &model,
        &data,
        512,
    )?;

    let cases = [
        (
            "query",
            "Which document explains Ryan arriving in New Rome?",
            true,
        ),
        ("short_passage", "Ryan", false),
        (
            "long_passage",
            "Ryan arrives in New Rome after a temporal transition and records the event.",
            false,
        ),
    ];
    let mut results = Vec::with_capacity(cases.len());
    for (name, text, is_query) in cases {
        let started = Instant::now();
        let expected = if is_query {
            candle.embed_query(text)?
        } else {
            candle.embed_passage(text)?
        };
        let candle_micros = micros(started.elapsed());
        let started = Instant::now();
        let actual = if is_query {
            ort.embed_query(text)?
        } else {
            ort.embed_passage(text)?
        };
        let onnx_micros = micros(started.elapsed());
        let (max_abs, cosine) = compare(&expected, &actual);
        if max_abs > 1.0e-5 || cosine < 0.999_999 {
            return Err(format!(
                "Qwen backend parity failed for {name}: max_abs={max_abs}, cosine={cosine}"
            )
            .into());
        }
        results.push(serde_json::json!({
            "name": name,
            "maxAbs": max_abs,
            "cosine": cosine,
            "candleMicros": candle_micros,
            "onnxMicros": onnx_micros,
        }));
    }
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "schema": "phoenix.qwen-backend-parity/v1",
            "cases": results,
        }))?
    );
    Ok(())
}

fn compare(left: &[f32], right: &[f32]) -> (f32, f32) {
    let mut max_abs = 0.0_f32;
    let mut dot = 0.0_f64;
    let mut left_norm = 0.0_f64;
    let mut right_norm = 0.0_f64;
    for (&left, &right) in left.iter().zip(right) {
        max_abs = max_abs.max((left - right).abs());
        dot += f64::from(left) * f64::from(right);
        left_norm += f64::from(left) * f64::from(left);
        right_norm += f64::from(right) * f64::from(right);
    }
    (
        max_abs,
        (dot / (left_norm.sqrt() * right_norm.sqrt())) as f32,
    )
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

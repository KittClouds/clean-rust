//! Dumps what a Phoenix family produces for the qualification corpus, for
//! `tools/embed_qualify.py` to score against an independent reference.
//!
//! `kammi-embed-dump <family> <corpus.json> <out.json> [model dir]`
//!
//! Per input: the exact prompt, its token ids (the runner's tokenizer configuration: family
//! `max_length`, right truncation, no padding in the record), the batched vector, the vector
//! embedded alone, and whether a second batched run was bitwise identical.

use std::path::PathBuf;

use base64::Engine;
use kammi_core::{Embedder, Input};
use kammi_embed::{ensure_ort_dylib, Family, PhoenixEmbedder};
use serde_json::{json, Value};

fn b64(values: &[f32]) -> String {
    let bytes: Vec<u8> = values.iter().flat_map(|v| v.to_le_bytes()).collect();
    base64::engine::general_purpose::STANDARD.encode(bytes)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 4 {
        return Err("usage: kammi-embed-dump <family> <corpus.json> <out.json> [model dir]".into());
    }
    ensure_ort_dylib().ok_or("ONNX Runtime DLL not found (set ORT_DYLIB_PATH)")?;
    let family = Family::parse(&args[1]).ok_or("unknown family")?;
    let root = args
        .get(4)
        .map(PathBuf::from)
        .unwrap_or_else(|| family.default_model_root());
    let corpus: Value = serde_json::from_slice(&std::fs::read(&args[2])?)?;
    let embedder = PhoenixEmbedder::load(family, &root)?;
    let max_length = family.config(root.clone()).max_length;

    let tokenizer = kammi_embed::family_tokenizer(embedder.model_dir(), max_length)?;

    let mut out = serde_json::Map::new();
    for (section, role) in [
        ("documents", "document"),
        ("queries", "query"),
        ("edge_cases", "document"),
        ("edge_cases", "query"),
    ] {
        let items = corpus[section].as_array().ok_or("corpus section missing")?;
        let inputs: Vec<Input> = items
            .iter()
            .map(|i| {
                let text = i["text"].as_str().unwrap_or("");
                if role == "query" {
                    Input::query(text)
                } else {
                    Input::document(text)
                }
            })
            .collect();
        let started = std::time::Instant::now();
        let batched = embedder.embed(&inputs)?;
        let batch_ms = started.elapsed().as_secs_f64() * 1e3;
        let repeat = embedder.embed(&inputs)?;
        let prompts = embedder.prompts(&inputs);
        let mut rows = Vec::new();
        for (index, item) in items.iter().enumerate() {
            let single = embedder.embed_one(inputs[index])?;
            let encoding = tokenizer
                .encode(prompts[index].as_str(), true)
                .map_err(|e| e.to_string())?;
            rows.push(json!({
                "id": item["id"],
                "prompt": prompts[index],
                "tokens": encoding.get_ids(),
                "vector": b64(batched.row(index)),
                "single": b64(&single),
                "repeat_identical": batched.row(index) == repeat.row(index),
            }));
        }
        out.insert(
            format!("{section}:{role}"),
            json!({"batch_ms": batch_ms, "rows": rows}),
        );
    }
    let report = json!({
        "family": family.label(),
        "identity": embedder.model_identity().id,
        "dims": embedder.dimension(),
        "model_root": embedder.model_dir(),
        "model_path": embedder.model_path(),
        "max_length": max_length,
        "scheduler": format!("{:?}", family.scheduler()),
        "ort_dylib": std::env::var("ORT_DYLIB_PATH").ok(),
        "sections": out,
    });
    std::fs::write(&args[3], serde_json::to_vec(&report)?)?;
    eprintln!("wrote {} ({})", args[3], embedder.model_identity().id);
    Ok(())
}

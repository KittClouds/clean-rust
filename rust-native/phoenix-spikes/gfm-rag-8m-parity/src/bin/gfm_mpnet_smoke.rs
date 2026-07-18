use std::path::PathBuf;

use gfm_rag_8m_parity::mpnet::MpnetEmbedder;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = std::env::var_os("GFM_MPNET_ASSET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet"));
    let text = std::env::args().skip(1).collect::<Vec<_>>().join(" ");
    let text = if text.is_empty() {
        "Which documents explain relational graph inference?"
    } else {
        &text
    };
    let mut embedder = MpnetEmbedder::open(
        root.join("onnx").join("model.onnx"),
        root.join("tokenizer.json"),
    )?;
    let embedding = embedder.embed_unnormalized(text)?;
    let norm = embedding
        .iter()
        .map(|value| value * value)
        .sum::<f32>()
        .sqrt();
    println!(
        "dimensions={} l2_norm={norm:.6} normalized=false",
        embedding.len()
    );
    Ok(())
}

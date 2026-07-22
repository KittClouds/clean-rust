use std::path::PathBuf;

use g_reasoner_34m_parity::qwen::QwenEmbedder;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let model_dir = std::env::var_os("G_REASONER_QWEN_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen"));
    let query = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "How does relational graph reasoning work?".into());
    let embedder = QwenEmbedder::load(model_dir, 512)?;
    let embedding = embedder.embed_query(&query)?;
    let norm = embedding
        .iter()
        .map(|value| value * value)
        .sum::<f32>()
        .sqrt();
    println!(
        "{{\"dimensions\":{},\"norm\":{norm:.9},\"first\":{:.9}}}",
        embedding.len(),
        embedding[0]
    );
    Ok(())
}

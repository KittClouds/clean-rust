#[path = "../corpus.rs"]
#[allow(dead_code)]
mod corpus;
#[path = "../metrics.rs"]
mod metrics;
#[path = "../retrieval_duel.rs"]
mod retrieval_duel;

use std::fs;
use std::path::{Path, PathBuf};

use phoenix_revision_inference::GfmAssets;
use retrieval_duel::execute_retrieval_duel;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = std::env::var_os("PHOENIX_RETRIEVAL_DUEL_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-retrieval-duel-v1"));
    let bundle = root.join("bundles").join("gfm-rag-8m");
    let receipts = root.join("receipts");
    fs::create_dir_all(&root)?;
    fs::create_dir_all(&receipts)?;
    let receipt = execute_retrieval_duel(&bundle, &gfm_assets(&root))?;
    let encoded = serde_json::to_vec_pretty(&receipt)?;
    let path = receipts.join("retrieval-duel-v1.json");
    fs::write(&path, &encoded)?;
    println!("{}", String::from_utf8(encoded)?);
    eprintln!("receipt={}", path.display());
    Ok(())
}

fn gfm_assets(root: &Path) -> GfmAssets {
    GfmAssets {
        checkpoint: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\gfm-rag-8m.safetensors"),
        checkpoint_manifest: PathBuf::from(
            r"C:\code land\clean-rust\rust-native\phoenix-spikes\gfm-rag-8m-parity\fixtures\checkpoint-manifest.json",
        ),
        mpnet_model: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\onnx\model.onnx"),
        mpnet_tokenizer: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\tokenizer.json"),
        onnx_runtime: PathBuf::from(
            r"D:\phoenix-target-gfm-rag-8m\runtime\onnxruntime-1.20.1\package-v2\runtimes\win-x64\native\onnxruntime.dll",
        ),
        hot_cache: root.join("hot-cache-gfm"),
    }
}

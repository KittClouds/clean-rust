#[path = "../corpus.rs"]
#[allow(dead_code)]
mod corpus;

use std::fs;
use std::path::{Path, PathBuf};

use phoenix_revision_inference::{
    BundleBuildReceipt, GfmAssets, GfmEncoderPrewarmReceipt, build_gfm_bundle_with_encoder,
    prewarm_gfm_encoder, project_gfm,
};
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BenchReceipt {
    schema: &'static str,
    relation_suffix: String,
    prewarm: Option<PrewarmReceipt>,
    build: BundleBuildReceipt,
    exact_rebuild: Option<BundleBuildReceipt>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PrewarmReceipt {
    encoder_resident_reused: bool,
    prepare_micros: u64,
    peak_resident_bytes: u64,
}

impl From<GfmEncoderPrewarmReceipt> for PrewarmReceipt {
    fn from(receipt: GfmEncoderPrewarmReceipt) -> Self {
        Self {
            encoder_resident_reused: receipt.encoder_resident_reused,
            prepare_micros: receipt.prepare_micros,
            peak_resident_bytes: receipt.peak_resident_bytes,
        }
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = std::env::var_os("PHOENIX_GFM_8M_BENCH_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-index-build-nuke\gfm-8m-runtime"));
    let tag = std::env::var("PHOENIX_GFM_BUNDLE_TAG").unwrap_or_else(|_| "default".into());
    let relation_suffix = std::env::var("PHOENIX_GFM_DIRTY_RELATION_SUFFIX").unwrap_or_default();
    let output = root.join("bundles").join(tag);
    fs::create_dir_all(&root)?;
    let assets = gfm_assets(&root);
    let prewarm = std::env::var_os("PHOENIX_GFM_PREWARM").map(|_| prewarm_gfm_encoder(&assets));
    let prewarm = prewarm.transpose()?.map(PrewarmReceipt::from);
    let graph = corpus::graph_with_first_dirty_suffix("", &relation_suffix);
    let build = build_gfm_bundle_with_encoder(&output, 1, project_gfm(&graph)?, &assets)?;
    let exact_rebuild = if std::env::var_os("PHOENIX_GFM_REPEAT_EXACT").is_some() {
        Some(build_gfm_bundle_with_encoder(
            &output,
            1,
            project_gfm(&graph)?,
            &assets,
        )?)
    } else {
        None
    };
    let receipt = BenchReceipt {
        schema: "phoenix.gfm-8m-index-bench/v1",
        relation_suffix,
        prewarm,
        build,
        exact_rebuild,
    };
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

fn gfm_assets(root: &Path) -> GfmAssets {
    let hot_cache = std::env::var_os("PHOENIX_GFM_HOT_CACHE")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("hot-cache"));
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
        hot_cache,
    }
}

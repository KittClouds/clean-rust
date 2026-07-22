mod corpus;
mod metrics;

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use corpus::{GoldTask, TASKS, TaskTarget};
use metrics::{MetricsAccumulator, RetrievalMetrics};
use phoenix_revision_inference::{
    BundleBuildReceipt, EncoderExecutionBackend, GfmAssets, ReasonerAssets,
    build_gfm_bundle_with_encoder, build_reasoner_bundle_with_encoder,
    prepare_reasoner_query_embedding, project_gfm, project_reasoner, run_gfm_complete,
    run_reasoner_complete,
};
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CaseReceipt {
    task_id: String,
    family: String,
    target_type: String,
    gold_ids: Vec<String>,
    ranked_ids: Vec<String>,
    complete_inference_micros: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ModelReceipt {
    model: String,
    supported_targets: Vec<String>,
    overall: RetrievalMetrics,
    by_family: BTreeMap<String, RetrievalMetrics>,
    cases: Vec<CaseReceipt>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EvaluationReceipt {
    schema: &'static str,
    generated_at_unix_ms: u128,
    oracle_start_nodes: bool,
    candidate_edges_admitted: u64,
    gfm_bundle_build_micros: u64,
    reasoner_bundle_build_micros: u64,
    reasoner_prewarm_micros: u64,
    gfm_build: BundleBuildReceipt,
    reasoner_build: BundleBuildReceipt,
    models: Vec<ModelReceipt>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = std::env::var_os("PHOENIX_GFM_TASK_FIT_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-gfm-task-fit"));
    let bundle_tag = std::env::var("PHOENIX_GFM_BUNDLE_TAG").unwrap_or_else(|_| "default".into());
    let bundles = root.join("bundles").join(bundle_tag);
    let receipts = root.join("receipts");
    fs::create_dir_all(&bundles)?;
    fs::create_dir_all(&receipts)?;

    let dirty_suffix = std::env::var("PHOENIX_GFM_DIRTY_TEXT_SUFFIX").unwrap_or_default();
    let graph = corpus::graph_with_first_embedding_suffix(&dirty_suffix);
    let candidate_edges_admitted = 0;
    let gfm_projection = project_gfm(&graph)?;
    let reasoner_projection = project_reasoner(&graph)?;
    let gfm_assets = gfm_assets(&root);
    let reasoner_assets = reasoner_assets(&root);
    let reasoner_prewarm_micros = if std::env::var_os("PHOENIX_GFM_PREWARM_REASONER").is_some() {
        prepare_reasoner_query_embedding(&reasoner_assets, "index encoder prewarm")?.prepare_micros
    } else {
        0
    };
    let gfm_root = bundles.join("gfm-rag-8m");
    let reasoner_root = bundles.join("g-reasoner-34m");

    let gfm_build = build_gfm_bundle_with_encoder(&gfm_root, 1, gfm_projection, &gfm_assets)?;
    let reasoner_build = build_reasoner_bundle_with_encoder(
        &reasoner_root,
        1,
        reasoner_projection,
        &reasoner_assets,
    )?;

    let models = if std::env::var_os("PHOENIX_GFM_INDEX_ONLY").is_some() {
        Vec::new()
    } else {
        vec![
            evaluate_gfm(&gfm_root, &gfm_assets)?,
            evaluate_reasoner(&reasoner_root, &reasoner_assets)?,
        ]
    };
    let receipt = EvaluationReceipt {
        schema: "phoenix.gfm-task-fit-evaluation/v1",
        generated_at_unix_ms: SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
        oracle_start_nodes: true,
        candidate_edges_admitted,
        gfm_bundle_build_micros: build_total_micros(&gfm_build),
        reasoner_bundle_build_micros: build_total_micros(&reasoner_build),
        reasoner_prewarm_micros,
        gfm_build,
        reasoner_build,
        models,
    };
    let encoded = serde_json::to_vec_pretty(&receipt)?;
    let path = receipts.join("task-fit-v1.json");
    fs::write(&path, &encoded)?;
    println!("{}", String::from_utf8(encoded)?);
    eprintln!("receipt={}", path.display());
    Ok(())
}

fn evaluate_gfm(
    root: &Path,
    assets: &GfmAssets,
) -> Result<ModelReceipt, Box<dyn std::error::Error>> {
    let mut cases = Vec::new();
    for task in TASKS
        .iter()
        .filter(|task| task.target == TaskTarget::Document)
    {
        let output = run_gfm_complete(root, assets, task.query, task.start_ids, 8)?;
        cases.push(case_receipt(
            task,
            output.ordered_document_ids,
            output.receipt.complete_inference_micros,
        ));
    }
    Ok(model_receipt("gfm-rag-8m", vec!["document".into()], cases))
}

fn evaluate_reasoner(
    root: &Path,
    assets: &ReasonerAssets,
) -> Result<ModelReceipt, Box<dyn std::error::Error>> {
    let mut cases = Vec::new();
    for task in TASKS {
        let output = run_reasoner_complete(
            root,
            assets,
            task.query,
            task.start_ids,
            task.target.as_str(),
            10,
        )?;
        let ranking = output
            .ranking
            .ranked_nodes
            .into_iter()
            .map(|node| node.stable_id)
            .collect();
        cases.push(case_receipt(
            task,
            ranking,
            output.receipt.complete_inference_micros,
        ));
    }
    Ok(model_receipt(
        "g-reasoner-34m",
        vec!["document".into(), "entity".into(), "chapter".into()],
        cases,
    ))
}

fn case_receipt(task: &GoldTask, ranked_ids: Vec<String>, micros: u64) -> CaseReceipt {
    CaseReceipt {
        task_id: task.id.into(),
        family: task.family.into(),
        target_type: task.target.as_str().into(),
        gold_ids: task.gold_ids.iter().map(|id| (*id).into()).collect(),
        ranked_ids,
        complete_inference_micros: micros,
    }
}

fn model_receipt(model: &str, targets: Vec<String>, cases: Vec<CaseReceipt>) -> ModelReceipt {
    let mut overall = MetricsAccumulator::default();
    let mut families = BTreeMap::<String, MetricsAccumulator>::new();
    for case in &cases {
        overall.observe(&case.ranked_ids, &case.gold_ids);
        families
            .entry(case.family.clone())
            .or_default()
            .observe(&case.ranked_ids, &case.gold_ids);
    }
    ModelReceipt {
        model: model.into(),
        supported_targets: targets,
        overall: overall.finish(),
        by_family: families
            .into_iter()
            .map(|(family, metrics)| (family, metrics.finish()))
            .collect(),
        cases,
    }
}

fn build_total_micros(receipt: &phoenix_revision_inference::BundleBuildReceipt) -> u64 {
    receipt.bundle_probe_micros
        + receipt.embedding_cache_probe_micros
        + receipt.encoder_load_micros
        + receipt.embedding_compute_micros
        + receipt.embedding_cache_write_micros
        + receipt.artifact_write_micros
}

fn gfm_assets(root: &Path) -> GfmAssets {
    GfmAssets {
        checkpoint: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\gfm-rag-8m.safetensors"),
        checkpoint_manifest: PathBuf::from(
            r"C:\code land\clean-rust\rust-native\phoenix-spikes\gfm-rag-8m-parity\fixtures\checkpoint-manifest.json",
        ),
        mpnet_model: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\onnx\model.onnx"),
        mpnet_tokenizer: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\tokenizer.json"),
        onnx_runtime: onnx_runtime(),
        hot_cache: root.join("hot-cache-gfm"),
    }
}

fn reasoner_assets(root: &Path) -> ReasonerAssets {
    ReasonerAssets {
        checkpoint: PathBuf::from(
            r"D:\phoenix-target-g-reasoner-34m\assets\g-reasoner-34m.safetensors",
        ),
        checkpoint_manifest: PathBuf::from(
            r"C:\code land\clean-rust\rust-native\phoenix-spikes\g-reasoner-34m-parity\fixtures\checkpoint-manifest.json",
        ),
        qwen_directory: PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen"),
        qwen_onnx_directory: PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen-onnx-fp32\fp32"),
        onnx_runtime: onnx_runtime(),
        encoder_backend: EncoderExecutionBackend::QwenOnnxFp32,
        hot_cache: root.join("hot-cache-reasoner"),
    }
}

fn onnx_runtime() -> PathBuf {
    PathBuf::from(
        r"D:\phoenix-target-gfm-rag-8m\runtime\onnxruntime-1.20.1\package-v2\runtimes\win-x64\native\onnxruntime.dll",
    )
}

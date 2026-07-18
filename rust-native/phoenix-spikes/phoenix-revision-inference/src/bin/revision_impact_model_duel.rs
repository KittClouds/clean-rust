use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use phoenix_revision_impact::truth_adapter::gold_harness::{analyze_case, gold_fixtures};
use phoenix_revision_inference::{
    BundleBuildReceipt, EncoderExecutionBackend, GfmAssets, GfmBundle, ModelDuelExecution,
    PeakMemorySampler, ReasonerAssets, ReasonerBundle, build_gfm_bundle_with_encoder,
    build_gold_duel_projection, build_reasoner_bundle_with_encoder, execute_model_duel,
    project_gfm, project_reasoner, snapshot_digest,
};
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RevisionImpactDuelReceipt {
    schema: &'static str,
    generation: u64,
    snapshot_digest: String,
    gold_case_count: usize,
    labels_author_reviewed: bool,
    pending_author_review_ids: Vec<String>,
    provisional_metrics: [&'static str; 3],
    projected_nodes: usize,
    projected_edges: usize,
    excluded_candidate_edges: usize,
    admitted_candidate_edges: u64,
    phoenix_persistence_writes: u64,
    source_projection_unchanged: bool,
    gfm_bundle_reused: bool,
    reasoner_bundle_reused: bool,
    gfm_build: Option<BundleBuildReceipt>,
    reasoner_build: Option<BundleBuildReceipt>,
    detector_latency_micros: u64,
    detector_peak_resident_bytes: u64,
    execution: ModelDuelExecution,
    gate_status: &'static str,
    integration_earned: bool,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut duel = build_gold_duel_projection()?;
    let digest_before = snapshot_digest(&duel.graph);
    let (detector_latency_micros, detector_peak_resident_bytes) = measure_detector(&duel)?;
    if duel.excluded_candidate_edges != duel.cases.len() {
        return Err("candidate-truth leak traps were not all excluded".into());
    }

    let repository = repository_root();
    let bundle_root = std::env::var_os("PHOENIX_REVISION_DUEL_BUNDLE_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-revision-impact-duel\bundles"));
    let target = bundle_root.join(&digest_before[..16]);
    let gfm_root = target.join("gfm-rag-8m");
    let reasoner_root = target.join("g-reasoner-34m");
    let gfm_assets = gfm_assets(&repository);
    let reasoner_assets = reasoner_assets(&repository);

    let gfm_bundle_reused = gfm_root.is_dir();
    let gfm_build = if gfm_bundle_reused {
        None
    } else {
        Some(build_gfm_bundle_with_encoder(
            &gfm_root,
            duel.graph.generation().0,
            project_gfm(&duel.graph)?,
            &gfm_assets,
        )?)
    };
    let reasoner_bundle_reused = reasoner_root.is_dir();
    let reasoner_build = if reasoner_bundle_reused {
        None
    } else {
        Some(build_reasoner_bundle_with_encoder(
            &reasoner_root,
            duel.graph.generation().0,
            project_reasoner(&duel.graph)?,
            &reasoner_assets,
        )?)
    };
    let gfm_bundle = GfmBundle::open(&gfm_root)?;
    let reasoner_bundle = ReasonerBundle::open(&reasoner_root)?;
    let admitted_candidate_edges = gfm_bundle.manifest.authority.admitted_candidate_edges
        + reasoner_bundle.manifest.authority.admitted_candidate_edges;
    if gfm_bundle.manifest.snapshot_digest != digest_before
        || reasoner_bundle.manifest.snapshot_digest != digest_before
        || admitted_candidate_edges != 0
    {
        return Err("model bundle authority contract failed".into());
    }

    let execution = execute_model_duel(
        &mut duel,
        &gfm_root,
        &reasoner_root,
        &gfm_assets,
        &reasoner_assets,
        detector_latency_micros,
        detector_peak_resident_bytes,
    )?;
    let source_projection_unchanged = snapshot_digest(&duel.graph) == digest_before;
    if !source_projection_unchanged
        || execution
            .arms
            .iter()
            .any(|arm| !arm.deterministic_traversal_unpruned)
    {
        return Err("model execution altered or pruned deterministic authority".into());
    }
    let labels_author_reviewed = duel.cases.iter().all(|case| case.gold.is_author_reviewed());
    let pending_author_review_ids = duel
        .cases
        .iter()
        .filter(|case| !case.gold.is_author_reviewed())
        .map(|case| case.gold.case_id.0.to_string())
        .collect::<Vec<_>>();
    let integration_earned = labels_author_reviewed && execution.technical_integration_candidate;
    let gate_status = if !labels_author_reviewed {
        "provisional_pending_author_review"
    } else if integration_earned {
        "earned"
    } else {
        "not_earned"
    };
    let receipt = RevisionImpactDuelReceipt {
        schema: "phoenix.revision-impact-model-duel/v1",
        generation: duel.graph.generation().0,
        snapshot_digest: digest_before,
        gold_case_count: duel.cases.len(),
        labels_author_reviewed,
        pending_author_review_ids,
        provisional_metrics: [
            "review_minutes_saved",
            "suspicious_result_usefulness",
            "repair_usefulness",
        ],
        projected_nodes: duel.graph.nodes().len(),
        projected_edges: duel.graph.edge_metadata().len(),
        excluded_candidate_edges: duel.excluded_candidate_edges,
        admitted_candidate_edges,
        phoenix_persistence_writes: 0,
        source_projection_unchanged,
        gfm_bundle_reused,
        reasoner_bundle_reused,
        gfm_build,
        reasoner_build,
        detector_latency_micros,
        detector_peak_resident_bytes,
        execution,
        gate_status,
        integration_earned,
    };
    let encoded = serde_json::to_vec_pretty(&receipt)?;
    let path = persist_receipt(&encoded, &receipt.snapshot_digest)?;
    use std::io::Write;
    std::io::stdout().lock().write_all(&encoded)?;
    println!();
    eprintln!("receipt={}", path.display());
    Ok(())
}

fn measure_detector(
    duel: &phoenix_revision_inference::GoldDuelProjection,
) -> Result<(u64, u64), Box<dyn std::error::Error>> {
    let (gold, projection) = gold_fixtures();
    let sampler = PeakMemorySampler::start(Duration::from_millis(2));
    let started = Instant::now();
    for (index, gold_case) in gold.cases.iter().enumerate() {
        let projection_case = projection
            .cases
            .iter()
            .find(|candidate| candidate.case_id == gold_case.case_id.0)
            .ok_or("missing projection case")?;
        let analysis = analyze_case(gold_case, projection_case);
        if analysis.report != duel.cases[index].deterministic_report {
            return Err("detector rerun was not stable".into());
        }
    }
    Ok((started.elapsed().as_micros() as u64, sampler.finish()))
}

fn persist_receipt(encoded: &[u8], snapshot_digest: &str) -> std::io::Result<PathBuf> {
    use std::io::Write;

    let directory = PathBuf::from(r"D:\phoenix-target-revision-impact-duel\receipts");
    std::fs::create_dir_all(&directory)?;
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let path = directory.join(format!(
        "phase7-8-{}-{timestamp}-{}.json",
        &snapshot_digest[..16],
        std::process::id()
    ));
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&path)?;
    file.write_all(encoded)?;
    file.sync_all()?;
    Ok(path)
}

fn gfm_assets(root: &Path) -> GfmAssets {
    GfmAssets {
        checkpoint: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\gfm-rag-8m.safetensors"),
        checkpoint_manifest: root
            .join("rust-native/phoenix-spikes/gfm-rag-8m-parity/fixtures/checkpoint-manifest.json"),
        mpnet_model: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\onnx\model.onnx"),
        mpnet_tokenizer: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\tokenizer.json"),
        onnx_runtime: onnx_runtime(),
        hot_cache: model_hot_cache_root(),
    }
}

fn reasoner_assets(root: &Path) -> ReasonerAssets {
    ReasonerAssets {
        checkpoint: PathBuf::from(
            r"D:\phoenix-target-g-reasoner-34m\assets\g-reasoner-34m.safetensors",
        ),
        checkpoint_manifest: root.join(
            "rust-native/phoenix-spikes/g-reasoner-34m-parity/fixtures/checkpoint-manifest.json",
        ),
        qwen_directory: PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen"),
        qwen_onnx_directory: PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\qwen-onnx-fp32\fp32"),
        onnx_runtime: onnx_runtime(),
        encoder_backend: EncoderExecutionBackend::QwenOnnxFp32,
        hot_cache: model_hot_cache_root(),
    }
}

fn onnx_runtime() -> PathBuf {
    PathBuf::from(
        r"D:\phoenix-target-gfm-rag-8m\runtime\onnxruntime-1.20.1\package-v2\runtimes\win-x64\native\onnxruntime.dll",
    )
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

fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf()
}

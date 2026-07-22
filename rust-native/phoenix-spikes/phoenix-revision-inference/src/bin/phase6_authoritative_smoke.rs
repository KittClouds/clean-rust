use std::path::{Path, PathBuf};

use phoenix_graph_rebuild::{
    GraphRebuildInput, GraphRelationship, GraphScopeKind, build_graph_rebuild_snapshot,
};
use phoenix_revision_impact::{
    GraphGeneration, RevisionAnalysisViews, graph_rebuild_asserted_inference_input,
};
use phoenix_revision_inference::{
    BundleBuildReceipt, EncoderExecutionBackend, GfmAssets, GfmBundle, InferencePerformanceReceipt,
    ReasonerAssets, ReasonerBundle, build_gfm_bundle_with_encoder,
    build_reasoner_bundle_with_encoder, project_gfm, project_reasoner, run_gfm_complete,
    run_reasoner_complete, snapshot_digest,
};
use phoenix_types::{EntityId, EntityKind, GenderHint, LexiconEntry, ScopeKey};
use serde::Serialize;

const GENERATION: u64 = 600;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct GateReceipt {
    schema: &'static str,
    source: &'static str,
    generation: u64,
    snapshot_digest: String,
    source_snapshot_unchanged: bool,
    projected_nodes: usize,
    projected_edges: usize,
    excluded_candidate_edges: usize,
    admitted_candidate_edges: u64,
    phoenix_persistence_writes: u64,
    gfm_bundle_reused: bool,
    reasoner_bundle_reused: bool,
    gfm_build: Option<BundleBuildReceipt>,
    reasoner_build: Option<BundleBuildReceipt>,
    gfm_inference: InferencePerformanceReceipt,
    reasoner_inference: InferencePerformanceReceipt,
    gfm_logit_count: usize,
    gfm_top_entity_ids: Vec<String>,
    gfm_document_ids: Vec<String>,
    reasoner_logit_count: usize,
    reasoner_ranked_ids: Vec<String>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = repository_root();
    let shortrun = std::fs::read_to_string(root.join("docs").join("shortrun.md"))?;
    let excerpt = shortrun.chars().take(1_200).collect::<String>();
    let lexicon = shortrun_lexicon();
    let mut snapshot = build_graph_rebuild_snapshot(GraphRebuildInput {
        scope_kind: GraphScopeKind::Note,
        scope_id: "phase6-authoritative-shortrun",
        note_id: "docs/shortrun.md#phase6-authoritative-excerpt",
        text: &excerpt,
        scope: ScopeKey::default(),
        entities: &lexicon,
        candidate_count: 1,
        built_at: Some(GENERATION),
    })?;
    if snapshot.nodes.len() < 2 {
        return Err("authoritative excerpt produced fewer than two entity nodes".into());
    }
    snapshot.relationships.push(GraphRelationship {
        id: "phase6:candidate-leak-trap".into(),
        source_entity_id: snapshot.nodes[0].entity_id.clone(),
        target_entity_id: snapshot.nodes[1].entity_id.clone(),
        relation_type: "candidate_only_relation".into(),
        evidence_anchor_ids: Vec::new(),
        confidence: 0.5,
        status: "candidate".into(),
        adjudication_source: "phase6-gate".into(),
        adjudication_score: 0.5,
        rationale: "must never enter production model arrays".into(),
        decision_evidence: Vec::new(),
    });
    let source_before = blake3::hash(&serde_json::to_vec(&snapshot)?);
    let input = graph_rebuild_asserted_inference_input(&snapshot);
    let views = RevisionAnalysisViews::project(GraphGeneration(GENERATION), Vec::new(), input)?;
    let digest = snapshot_digest(&views.inference_graph);
    let excluded_candidate_edges = views.inference_graph.receipt().excluded_candidate_edges;
    if excluded_candidate_edges == 0 {
        return Err("candidate leak trap was not rejected".into());
    }

    let bundle_root = std::env::var_os("PHOENIX_REVISION_BUNDLE_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-revision-inference\bundles"));
    let target = bundle_root.join(&digest[..16]);
    let gfm_root = target.join("gfm-rag-8m");
    let reasoner_root = target.join("g-reasoner-34m");
    let gfm_assets = gfm_assets(&root);
    let reasoner_assets = reasoner_assets(&root);

    let gfm_bundle_reused = gfm_root.is_dir();
    let gfm_build = if gfm_bundle_reused {
        None
    } else {
        Some(build_gfm_bundle_with_encoder(
            &gfm_root,
            GENERATION,
            project_gfm(&views.inference_graph)?,
            &gfm_assets,
        )?)
    };
    let reasoner_bundle_reused = reasoner_root.is_dir();
    let reasoner_build = if reasoner_bundle_reused {
        None
    } else {
        Some(build_reasoner_bundle_with_encoder(
            &reasoner_root,
            GENERATION,
            project_reasoner(&views.inference_graph)?,
            &reasoner_assets,
        )?)
    };

    let gfm_bundle = GfmBundle::open(&gfm_root)?;
    let reasoner_bundle = ReasonerBundle::open(&reasoner_root)?;
    if gfm_bundle.manifest.snapshot_digest != digest
        || reasoner_bundle.manifest.snapshot_digest != digest
        || gfm_bundle.manifest.authority.admitted_candidate_edges != 0
        || reasoner_bundle.manifest.authority.admitted_candidate_edges != 0
    {
        return Err("bundle authority or snapshot digest mismatch".into());
    }

    let query = "Which document explains Ryan arriving in New Rome?";
    let gfm = run_gfm_complete(&gfm_root, &gfm_assets, query, &["inference:entity:ryan"], 5)?;
    let reasoner = run_reasoner_complete(
        &reasoner_root,
        &reasoner_assets,
        query,
        &["inference:entity:ryan"],
        "document",
        5,
    )?;
    let source_after = blake3::hash(&serde_json::to_vec(&snapshot)?);
    let receipt = GateReceipt {
        schema: "phoenix.revision-inference-phase6-gate/v1",
        source: "docs/shortrun.md authoritative Phoenix graph-rebuild excerpt",
        generation: GENERATION,
        snapshot_digest: digest,
        source_snapshot_unchanged: source_before == source_after,
        projected_nodes: views.inference_graph.nodes().len(),
        projected_edges: views.inference_graph.edge_metadata().len(),
        excluded_candidate_edges,
        admitted_candidate_edges: 0,
        phoenix_persistence_writes: 0,
        gfm_bundle_reused,
        reasoner_bundle_reused,
        gfm_build,
        reasoner_build,
        gfm_inference: gfm.receipt,
        reasoner_inference: reasoner.receipt,
        gfm_logit_count: gfm.logits.len(),
        gfm_top_entity_ids: gfm.top_entity_ids,
        gfm_document_ids: gfm.ordered_document_ids,
        reasoner_logit_count: reasoner.ranking.logits.len(),
        reasoner_ranked_ids: reasoner
            .ranking
            .ranked_nodes
            .into_iter()
            .map(|node| node.stable_id)
            .collect(),
    };
    let encoded = serde_json::to_vec_pretty(&receipt)?;
    persist_receipt(&encoded, &receipt.snapshot_digest)?;
    use std::io::Write;
    std::io::stdout().lock().write_all(&encoded)?;
    println!();
    Ok(())
}

fn persist_receipt(encoded: &[u8], snapshot_digest: &str) -> std::io::Result<()> {
    use std::io::Write;
    use std::time::{SystemTime, UNIX_EPOCH};

    let directory = PathBuf::from(r"D:\phoenix-target-revision-inference\receipts");
    std::fs::create_dir_all(&directory)?;
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let path = directory.join(format!(
        "phase6-{}-{timestamp}-{}.json",
        &snapshot_digest[..16],
        std::process::id()
    ));
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)?;
    file.write_all(encoded)?;
    file.sync_all()
}

fn shortrun_lexicon() -> Vec<LexiconEntry> {
    [
        ("ryan", "Ryan", EntityKind::Character),
        ("quicksave", "Quicksave", EntityKind::Character),
        ("new-rome", "New Rome", EntityKind::Location),
        ("dynamis", "Dynamis", EntityKind::Organization),
    ]
    .into_iter()
    .map(|(id, label, kind)| LexiconEntry {
        entity_id: EntityId(id.into()),
        label: label.into(),
        aliases: Vec::new(),
        kind: Some(kind),
        gender: Some(GenderHint::Unknown),
        number: None,
        scope: ScopeKey::default(),
    })
    .collect()
}

fn gfm_assets(root: &Path) -> GfmAssets {
    GfmAssets {
        checkpoint: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\gfm-rag-8m.safetensors"),
        checkpoint_manifest: root
            .join("rust-native/phoenix-spikes/gfm-rag-8m-parity/fixtures/checkpoint-manifest.json"),
        mpnet_model: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\onnx\model.onnx"),
        mpnet_tokenizer: PathBuf::from(r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\tokenizer.json"),
        onnx_runtime: PathBuf::from(
            r"D:\phoenix-target-gfm-rag-8m\runtime\onnxruntime-1.20.1\package-v2\runtimes\win-x64\native\onnxruntime.dll",
        ),
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
        onnx_runtime: PathBuf::from(
            r"D:\phoenix-target-gfm-rag-8m\runtime\onnxruntime-1.20.1\package-v2\runtimes\win-x64\native\onnxruntime.dll",
        ),
        encoder_backend: EncoderExecutionBackend::QwenOnnxFp32,
        hot_cache: model_hot_cache_root(),
    }
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

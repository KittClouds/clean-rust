use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::Instant;

use phoenix_graph_rebuild::GraphRebuildSnapshot;
use phoenix_revision_impact::{
    graph_rebuild_asserted_inference_input, GraphGeneration, InferenceGraph, RevisionAnalysisViews,
};
use phoenix_revision_inference::{
    build_gfm_bundle_with_encoder, project_gfm, run_gfm_complete, GfmAssets,
};
const DEFAULT_LIMIT: u32 = 12;
const MAX_LIMIT: u32 = 50;
const SEED_LIMIT: usize = 4;

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopGfmShadowQueryRequest {
    pub run_handle: String,
    pub query: String,
    pub request_generation: u32,
    #[serde(default)]
    pub semantic_document_ids: Vec<String>,
    #[serde(default = "default_limit")]
    pub limit: u32,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopGfmShadowResult {
    pub stable_id: String,
    pub document_id: String,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopGfmShadowTiming {
    pub index_micros: f64,
    pub inference_micros: f64,
    pub total_micros: f64,
}

#[taurpc::ipc_type]
#[serde(rename_all = "camelCase")]
pub struct DesktopGfmShadowResponse {
    pub schema_version: &'static str,
    pub source: &'static str,
    pub status: String,
    pub reason: Option<String>,
    pub request_generation: u32,
    pub snapshot_id: String,
    pub selected_seed_ids: Vec<String>,
    pub results: Vec<DesktopGfmShadowResult>,
    pub evidence_entity_ids: Vec<String>,
    pub semantic_result_count: u32,
    pub overlap_count: u32,
    pub unique_gfm_count: u32,
    pub bundle_reused: bool,
    pub encoder_resident_reused: bool,
    pub relation_rows_reused: u32,
    pub relation_rows_computed: u32,
    pub excluded_candidate_edges: u32,
    pub excluded_rejected_edges: u32,
    pub no_topology_writes: bool,
    pub visible_ranking_unchanged: bool,
    pub timing: DesktopGfmShadowTiming,
}

pub fn build_gfm_shadow_graph(snapshot: &GraphRebuildSnapshot) -> Result<InferenceGraph, String> {
    let input = graph_rebuild_asserted_inference_input(snapshot);
    RevisionAnalysisViews::project(GraphGeneration(snapshot.built_at), Vec::new(), input)
        .map(|views| views.inference_graph)
        .map_err(|error| error.to_string())
}

pub fn execute_gfm_shadow_query(
    graph: Arc<InferenceGraph>,
    snapshot_id: String,
    request: DesktopGfmShadowQueryRequest,
    latest_generation: Arc<AtomicU32>,
) -> Result<DesktopGfmShadowResponse, String> {
    let started = Instant::now();
    if request.query.trim().is_empty() {
        return Ok(unavailable_gfm_shadow_response(
            &request,
            snapshot_id,
            "query is empty",
        ));
    }
    if cancelled(&latest_generation, request.request_generation) {
        return Ok(cancelled_response(&request, snapshot_id));
    }
    let assets = match gfm_assets() {
        Ok(assets) => assets,
        Err(reason) => {
            return Ok(unavailable_gfm_shadow_response(
                &request,
                snapshot_id,
                &reason,
            ))
        }
    };
    let projection = match project_gfm(&graph) {
        Ok(projection) => projection,
        Err(error) => {
            return Ok(unavailable_gfm_shadow_response(
                &request,
                snapshot_id,
                &error.to_string(),
            ))
        }
    };
    if projection.authority.admitted_candidate_edges != 0 {
        return Ok(unavailable_gfm_shadow_response(
            &request,
            snapshot_id,
            "GFM shadow projection admitted candidate truth",
        ));
    }
    let root = shadow_root();
    if let Err(error) = std::fs::create_dir_all(root.join("bundles")) {
        return Ok(unavailable_gfm_shadow_response(
            &request,
            snapshot_id,
            &format!("GFM shadow cache is unavailable: {error}"),
        ));
    }
    let bundle_root = root.join("bundles").join(&projection.snapshot_digest);
    let index_started = Instant::now();
    let build = match build_gfm_bundle_with_encoder(
        &bundle_root,
        graph.generation().0,
        projection,
        &assets,
    ) {
        Ok(build) => build,
        Err(error) => {
            return Ok(unavailable_gfm_shadow_response(
                &request,
                snapshot_id,
                &format!("GFM shadow index failed: {error}"),
            ))
        }
    };
    let index_micros = micros(index_started);
    if cancelled(&latest_generation, request.request_generation) {
        return Ok(cancelled_response(&request, snapshot_id));
    }
    let selected_seed_ids = resolve_seeds(&graph, &request.query, SEED_LIMIT);
    if selected_seed_ids.is_empty() {
        return Ok(unavailable_gfm_shadow_response(
            &request,
            snapshot_id,
            "authoritative snapshot has no entity seed",
        ));
    }
    let seed_refs = selected_seed_ids
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>();
    let inference_started = Instant::now();
    let output = match run_gfm_complete(
        &bundle_root,
        &assets,
        &request.query,
        &seed_refs,
        request.limit.clamp(1, MAX_LIMIT) as usize,
    ) {
        Ok(output) => output,
        Err(error) => {
            return Ok(unavailable_gfm_shadow_response(
                &request,
                snapshot_id,
                &format!("GFM shadow inference failed: {error}"),
            ))
        }
    };
    let inference_micros = micros(inference_started);
    if cancelled(&latest_generation, request.request_generation) {
        return Ok(cancelled_response(&request, snapshot_id));
    }
    let semantic = request
        .semantic_document_ids
        .iter()
        .map(|id| id.as_str())
        .collect::<BTreeSet<_>>();
    let results = output
        .ordered_document_ids
        .into_iter()
        .map(|stable_id| DesktopGfmShadowResult {
            document_id: strip_prefix(&stable_id, "inference:document:").to_owned(),
            stable_id,
        })
        .collect::<Vec<_>>();
    let overlap_count = results
        .iter()
        .filter(|row| semantic.contains(row.document_id.as_str()))
        .count() as u32;
    let unique_gfm_count = results.len() as u32 - overlap_count;
    Ok(DesktopGfmShadowResponse {
        schema_version: "phoenix.gfm-retrieval-shadow/v1",
        source: "rust-gfm-rag-8m",
        status: "completed".into(),
        reason: None,
        request_generation: request.request_generation,
        snapshot_id,
        selected_seed_ids,
        results,
        evidence_entity_ids: output
            .top_entity_ids
            .into_iter()
            .map(|id| strip_prefix(&id, "inference:entity:").to_owned())
            .collect(),
        semantic_result_count: semantic.len() as u32,
        overlap_count,
        unique_gfm_count,
        bundle_reused: build.bundle_reused,
        encoder_resident_reused: output.receipt.encoder_resident_reused,
        relation_rows_reused: bounded_count(build.relation_rows_reused),
        relation_rows_computed: bounded_count(build.relation_rows_computed),
        excluded_candidate_edges: bounded_count(graph.receipt().excluded_candidate_edges),
        excluded_rejected_edges: bounded_count(graph.receipt().excluded_rejected_edges),
        no_topology_writes: true,
        visible_ranking_unchanged: true,
        timing: DesktopGfmShadowTiming {
            index_micros,
            inference_micros,
            total_micros: micros(started),
        },
    })
}

fn resolve_seeds(graph: &InferenceGraph, query: &str, limit: usize) -> Vec<String> {
    let query_tokens = tokens(query);
    let mut candidates = graph
        .nodes()
        .iter()
        .filter(|node| graph.node_types()[node.node_type_id as usize] == "entity")
        .map(|node| {
            let text = format!("{} {}", node.node_id, node.embedding_text).to_lowercase();
            let hits = query_tokens
                .iter()
                .filter(|token| text.contains(token.as_str()))
                .count();
            (node.node_id.to_string(), hits)
        })
        .collect::<Vec<_>>();
    candidates
        .sort_unstable_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    candidates
        .into_iter()
        .filter(|(_, hits)| *hits > 0)
        .take(limit)
        .map(|(id, _)| id)
        .collect()
}

fn tokens(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|character: char| !character.is_alphanumeric())
        .filter(|token| token.len() > 2)
        .map(str::to_owned)
        .collect()
}

fn gfm_assets() -> Result<GfmAssets, String> {
    let assets = GfmAssets {
        checkpoint: env_path(
            "PHOENIX_GFM_CHECKPOINT",
            r"D:\phoenix-target-gfm-rag-8m\assets\gfm-rag-8m.safetensors",
        ),
        checkpoint_manifest: env_path(
            "PHOENIX_GFM_CHECKPOINT_MANIFEST",
            r"C:\code land\clean-rust\rust-native\phoenix-spikes\gfm-rag-8m-parity\fixtures\checkpoint-manifest.json",
        ),
        mpnet_model: env_path(
            "PHOENIX_GFM_MPNET_MODEL",
            r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\onnx\model.onnx",
        ),
        mpnet_tokenizer: env_path(
            "PHOENIX_GFM_MPNET_TOKENIZER",
            r"D:\phoenix-target-gfm-rag-8m\assets\mpnet\tokenizer.json",
        ),
        onnx_runtime: env_path(
            "PHOENIX_GFM_ONNX_RUNTIME",
            r"D:\phoenix-target-gfm-rag-8m\runtime\onnxruntime-1.20.1\package-v2\runtimes\win-x64\native\onnxruntime.dll",
        ),
        hot_cache: shadow_root().join("hot-cache"),
    };
    for path in [
        &assets.checkpoint,
        &assets.checkpoint_manifest,
        &assets.mpnet_model,
        &assets.mpnet_tokenizer,
        &assets.onnx_runtime,
    ] {
        if !path.is_file() {
            return Err(format!(
                "GFM shadow asset is unavailable: {}",
                path.display()
            ));
        }
    }
    Ok(assets)
}

fn shadow_root() -> PathBuf {
    env_path(
        "PHOENIX_GFM_SHADOW_ROOT",
        r"D:\phoenix-target-gfm-shadow-runtime",
    )
}

fn env_path(name: &str, fallback: &str) -> PathBuf {
    std::env::var_os(name)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(fallback))
}

pub fn unavailable_gfm_shadow_response(
    request: &DesktopGfmShadowQueryRequest,
    snapshot_id: String,
    reason: &str,
) -> DesktopGfmShadowResponse {
    terminal_response(request, snapshot_id, "unavailable", Some(reason.into()))
}

fn cancelled_response(
    request: &DesktopGfmShadowQueryRequest,
    snapshot_id: String,
) -> DesktopGfmShadowResponse {
    terminal_response(
        request,
        snapshot_id,
        "cancelled",
        Some("superseded by a newer shadow query".into()),
    )
}

fn terminal_response(
    request: &DesktopGfmShadowQueryRequest,
    snapshot_id: String,
    status: &str,
    reason: Option<String>,
) -> DesktopGfmShadowResponse {
    DesktopGfmShadowResponse {
        schema_version: "phoenix.gfm-retrieval-shadow/v1",
        source: "rust-gfm-rag-8m",
        status: status.into(),
        reason,
        request_generation: request.request_generation,
        snapshot_id,
        selected_seed_ids: Vec::new(),
        results: Vec::new(),
        evidence_entity_ids: Vec::new(),
        semantic_result_count: request.semantic_document_ids.len() as u32,
        overlap_count: 0,
        unique_gfm_count: 0,
        bundle_reused: false,
        encoder_resident_reused: false,
        relation_rows_reused: 0,
        relation_rows_computed: 0,
        excluded_candidate_edges: 0,
        excluded_rejected_edges: 0,
        no_topology_writes: true,
        visible_ranking_unchanged: true,
        timing: DesktopGfmShadowTiming {
            index_micros: 0.0,
            inference_micros: 0.0,
            total_micros: 0.0,
        },
    }
}

fn cancelled(latest: &AtomicU32, generation: u32) -> bool {
    generation < latest.fetch_max(generation, Ordering::AcqRel)
}

fn strip_prefix<'a>(value: &'a str, prefix: &str) -> &'a str {
    value.strip_prefix(prefix).unwrap_or(value)
}

fn default_limit() -> u32 {
    DEFAULT_LIMIT
}

fn micros(started: Instant) -> f64 {
    started.elapsed().as_micros() as f64
}

fn bounded_count(value: impl TryInto<u32>) -> u32 {
    value.try_into().unwrap_or(u32::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newer_generation_cancels_older_work() {
        let latest = AtomicU32::new(7);
        assert!(cancelled(&latest, 6));
        assert!(!cancelled(&latest, 8));
        assert_eq!(latest.load(Ordering::Acquire), 8);
    }

    #[test]
    fn terminal_receipts_never_claim_ranking_authority() {
        let request = DesktopGfmShadowQueryRequest {
            run_handle: "graph-run:test".into(),
            query: "test".into(),
            request_generation: 1,
            semantic_document_ids: vec!["doc:a".into()],
            limit: 12,
        };
        let receipt =
            unavailable_gfm_shadow_response(&request, "snapshot:test".into(), "missing fixture");
        assert!(receipt.no_topology_writes);
        assert!(receipt.visible_ranking_unchanged);
        assert!(receipt.results.is_empty());
    }
}

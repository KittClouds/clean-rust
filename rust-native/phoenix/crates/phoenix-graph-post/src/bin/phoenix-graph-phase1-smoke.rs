use std::env;
use std::path::PathBuf;

use phoenix_embed::{OrtExecutionProviderPreference, TextEmbeddingProfile};
use phoenix_graph_post::semantic_graph::{
    derive_semantic_graph_review_batch_from_store, persist_semantic_graph_patch_sidecar,
    profile_semantic_graph_inputs_from_store, SemanticGraphConfig, SemanticGraphInputProfile,
};
use phoenix_graph_post::SemanticNliConfig;
use phoenix_store_native_core::{
    PhoenixArchiveStoreV2, PhoenixSemanticGraphPatchStore, StoreError,
};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::ScopeKey;
use serde::Serialize;

#[derive(Clone, Debug)]
struct SmokeConfig {
    store_path: PathBuf,
    persist: bool,
    profile_only: bool,
    edge_limit: usize,
    graph: SemanticGraphConfig,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EdgePreview {
    edge_id: String,
    family: String,
    status: String,
    score_millis: u32,
    source_node_id: String,
    target_node_id: String,
    nli_support_millis: Option<u32>,
    nli_contradiction_millis: Option<u32>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SmokeReport {
    store_path: String,
    scope_key: String,
    model_id: String,
    embedding_profile: String,
    embedding_dim: usize,
    execution_provider: String,
    batch_size: usize,
    max_length: usize,
    vector_index_enabled: bool,
    chunk_nodes_enabled: bool,
    event_nodes_enabled: bool,
    embedding_cache_dir: Option<String>,
    embedding_cache_hits: usize,
    embedding_cache_misses: usize,
    node_count: usize,
    edge_count: usize,
    edge_family_counts: std::collections::BTreeMap<String, usize>,
    persisted: bool,
    derive_ms: u128,
    persist_ms: u128,
    total_ms: u128,
    preview: Vec<EdgePreview>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProfileReport {
    store_path: String,
    scope_key: String,
    model_id: String,
    embedding_profile: String,
    embedding_dim: usize,
    profile: SemanticGraphInputProfile,
}

fn main() {
    let config = parse_args(env::args().skip(1).collect());
    let report = if config.profile_only {
        run_profile(config).and_then(|report| {
            serde_json::to_string_pretty(&report).map_err(|error| error.to_string())
        })
    } else {
        run(config).and_then(|report| {
            serde_json::to_string_pretty(&report).map_err(|error| error.to_string())
        })
    };
    match report {
        Ok(report) => {
            phoenix_graph_post::clear_graph_thread_local_caches();
            println!("{report}");
        }
        Err(error) => {
            phoenix_graph_post::clear_graph_thread_local_caches();
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}

fn run_profile(config: SmokeConfig) -> Result<ProfileReport, String> {
    let store =
        PhoenixOvergraphStore::open(&config.store_path).map_err(|error| error.to_string())?;
    let scope = discover_scope(&store)?;
    let profile = profile_semantic_graph_inputs_from_store(&store, &scope)
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "no semantic graph inputs could be profiled".to_owned())?;
    Ok(ProfileReport {
        store_path: config.store_path.display().to_string(),
        scope_key: profile.scope_key.clone(),
        model_id: config.graph.embed.model_id.clone(),
        embedding_profile: config.graph.embed.profile.label().to_owned(),
        embedding_dim: config.graph.embed.profile.target_dim(),
        profile,
    })
}

fn run(config: SmokeConfig) -> Result<SmokeReport, String> {
    let total_started = std::time::Instant::now();
    let store =
        PhoenixOvergraphStore::open(&config.store_path).map_err(|error| error.to_string())?;
    let scope = discover_scope(&store)?;
    let created_at = now_ms();
    let derive_started = std::time::Instant::now();
    let Some(batch) =
        derive_semantic_graph_review_batch_from_store(&store, &scope, &config.graph, created_at)
            .map_err(|error| error.to_string())?
    else {
        return Err("no semantic graph batch could be derived".to_owned());
    };
    let derive_ms = derive_started.elapsed().as_millis();
    let persist_started = std::time::Instant::now();
    let persisted = if config.persist {
        store
            .init_semantic_graph_patch_schema()
            .map_err(|error| error.to_string())?;
        persist_semantic_graph_patch_sidecar(&store, &batch.sidecar)
            .map_err(|error| error.to_string())?;
        true
    } else {
        false
    };
    let persist_ms = persist_started.elapsed().as_millis();
    Ok(SmokeReport {
        store_path: config.store_path.display().to_string(),
        scope_key: batch.scope_key,
        model_id: batch.sidecar.model_id,
        embedding_profile: batch.sidecar.embedding_profile,
        embedding_dim: batch.sidecar.embedding_dim,
        execution_provider: config.graph.embed.execution_provider.label().to_owned(),
        batch_size: config.graph.embed.batch_size,
        max_length: config.graph.embed.max_length,
        vector_index_enabled: config.graph.index_node_vectors,
        chunk_nodes_enabled: config.graph.include_chunk_nodes,
        event_nodes_enabled: config.graph.include_event_nodes,
        embedding_cache_dir: config
            .graph
            .embed
            .embedding_cache_dir
            .as_ref()
            .map(|path| path.display().to_string()),
        embedding_cache_hits: batch.embedding_cache_hits,
        embedding_cache_misses: batch.embedding_cache_misses,
        node_count: batch.sidecar.summary.node_count,
        edge_count: batch.sidecar.summary.edge_count,
        edge_family_counts: batch.sidecar.summary.edge_family_counts,
        persisted,
        derive_ms,
        persist_ms,
        total_ms: total_started.elapsed().as_millis(),
        preview: batch
            .sidecar
            .candidate_edges
            .iter()
            .filter(|edge| {
                !matches!(
                    edge.candidate_status,
                    phoenix_semantic_v2::SemanticCandidateStatus::Rejected
                )
            })
            .take(config.edge_limit)
            .map(|edge| EdgePreview {
                edge_id: edge.edge_id.clone(),
                family: format!("{:?}", edge.family),
                status: format!("{:?}", edge.candidate_status),
                score_millis: edge.score_millis,
                source_node_id: edge.source_node_id.clone(),
                target_node_id: edge.target_node_id.clone(),
                nli_support_millis: edge.nli_support_millis,
                nli_contradiction_millis: edge.nli_contradiction_millis,
            })
            .collect(),
    })
}

fn discover_scope(store: &PhoenixOvergraphStore) -> Result<ScopeKey, String> {
    let archives = store
        .load_latest_document_archives(None)
        .map_err(|error| error.to_string())?;
    archives
        .first()
        .map(|archive| archive.manifest.scope.clone())
        .ok_or_else(|| "store did not contain any document archives".to_owned())
}

fn parse_args(args: Vec<String>) -> SmokeConfig {
    let mut config = SmokeConfig {
        store_path: PathBuf::new(),
        persist: false,
        profile_only: false,
        edge_limit: 16,
        graph: SemanticGraphConfig::default(),
    };
    if let Some(path) = string_arg(&args, "--store-path") {
        config.store_path = PathBuf::from(path);
    }
    if let Some(value) = usize_arg(&args, "--neighbor-limit") {
        config.graph.neighbor_limit = value.max(1);
    }
    if let Some(value) = usize_arg(&args, "--oversample") {
        config.graph.oversample = value.max(config.graph.neighbor_limit);
    }
    if let Some(value) = usize_arg(&args, "--min-score") {
        config.graph.min_score_millis = value.min(1000) as u32;
    }
    if let Some(value) = usize_arg(&args, "--edge-limit") {
        config.edge_limit = value.max(1);
    }
    if let Some(value) = usize_arg(&args, "--batch-size") {
        config.graph.embed.batch_size = value.max(1);
    }
    if let Some(value) = usize_arg(&args, "--max-length") {
        config.graph.embed.max_length = value.max(1);
    }
    if let Some(path) = string_arg(&args, "--model-root") {
        config.graph.embed.model_root = PathBuf::from(path);
    }
    if let Some(value) = string_arg(&args, "--model-id") {
        config.graph.embed.model_id = value;
    }
    if let Some(value) = string_arg(&args, "--execution-provider") {
        if let Some(provider) = OrtExecutionProviderPreference::parse(&value) {
            config.graph.embed.execution_provider = provider;
        }
    }
    if let Some(path) = string_arg(&args, "--embedding-cache-dir") {
        config.graph.embed.embedding_cache_dir = Some(PathBuf::from(path));
    } else if !args.iter().any(|arg| arg == "--no-embedding-cache") {
        config.graph.embed.embedding_cache_dir =
            Some(config.store_path.join("semantic-embedding-cache"));
    }
    if let Some(value) = string_arg(&args, "--embedding-profile") {
        if let Some(profile) = TextEmbeddingProfile::parse(&value) {
            config.graph.embed.profile = profile;
        }
    }
    if let Some(path) = string_arg(&args, "--nli-model-root") {
        config.graph.nli = Some(SemanticNliConfig {
            model_root: PathBuf::from(path),
            support_threshold_millis: 720,
            contradiction_threshold_millis: 740,
            review_threshold_millis: 560,
        });
    }
    if args.iter().any(|arg| arg == "--persist-patches") {
        config.persist = true;
    }
    if args.iter().any(|arg| arg == "--skip-vector-index") {
        config.graph.index_node_vectors = false;
    }
    if args.iter().any(|arg| arg == "--skip-chunks") {
        config.graph.include_chunk_nodes = false;
    }
    if args.iter().any(|arg| arg == "--skip-events") {
        config.graph.include_event_nodes = false;
    }
    if args.iter().any(|arg| arg == "--profile-only") {
        config.profile_only = true;
    }
    config
}

fn string_arg(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find_map(|window| (window[0] == flag).then(|| window[1].clone()))
}

fn usize_arg(args: &[String], flag: &str) -> Option<usize> {
    string_arg(args, flag).and_then(|value| value.parse::<usize>().ok())
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

#[allow(dead_code)]
fn _store_error(error: StoreError) -> String {
    error.to_string()
}

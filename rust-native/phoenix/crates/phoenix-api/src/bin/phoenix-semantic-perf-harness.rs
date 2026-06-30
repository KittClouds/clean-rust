use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use phoenix_embed::{OrtExecutionProviderPreference, TextEmbeddingProfile};
use phoenix_graph_post::semantic_graph::{
    profile_semantic_graph_inputs_from_store, SemanticGraphConfig, SemanticGraphInputProfile,
};
use phoenix_graph_post::semantic_service::{
    run_semantic_embedder_service_from_store, SemanticEmbedderModelRequest,
    SemanticEmbedderServiceRequest,
};
use phoenix_ingest_overgraph::{InvarantV3Config, PhoenixInvarantV3};
use phoenix_semantic_v2::SemanticGraphCompilerSummary;
use phoenix_store_native_core::{PhoenixArchiveStoreV2, PhoenixGraphKernelStoreV2, StoreError};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use phoenix_types::{DocumentId, IngestDocument, ScopeKey};
use serde::Serialize;

const DEFAULT_PROFILE_BUDGET_MS: u128 = 2_000;
const DEFAULT_INGEST_BUDGET_MS: u128 = 30_000;
const DEFAULT_COLD_BUDGET_MS: u128 = 30_000;
const DEFAULT_WARM_BUDGET_MS: u128 = 5_000;

fn main() {
    let config = match Config::parse(&std::env::args().collect::<Vec<_>>()) {
        Ok(config) => config,
        Err(error) => exit_err(error),
    };
    match run(&config) {
        Ok(report) => {
            phoenix_graph_post::clear_graph_thread_local_caches();
            if let Err(error) = write_report(&config, &report) {
                exit_err(error);
            }
            match serde_json::to_string_pretty(&report) {
                Ok(json) => println!("{json}"),
                Err(error) => exit_err(format!("serialize semantic perf report: {error}")),
            }
            if report.status == HarnessStatus::Fail {
                std::process::exit(2);
            }
        }
        Err(error) => {
            phoenix_graph_post::clear_graph_thread_local_caches();
            exit_err(error);
        }
    }
}

fn run(config: &Config) -> Result<SemanticPerfHarnessReport, String> {
    let total_started = Instant::now();
    ensure_empty_path(&config.store_path, "store")?;
    ensure_empty_path(&config.cache_dir, "embedding cache")?;
    fs::create_dir_all(&config.store_path)
        .map_err(|error| format!("create store dir {}: {error}", config.store_path.display()))?;
    fs::create_dir_all(&config.cache_dir)
        .map_err(|error| format!("create cache dir {}: {error}", config.cache_dir.display()))?;

    let store = PhoenixOvergraphStore::open(&config.store_path).map_err(display_error)?;
    store.init_archive_schema().map_err(display_error)?;
    store.init_graph_kernel_schema().map_err(display_error)?;

    let ingest_started = Instant::now();
    let ingest = ingest_shortrun(&store)?;
    let ingest_ms = ingest_started.elapsed().as_millis();
    let scope = discover_scope(&store)?;

    let profile_started = Instant::now();
    let profile = profile_semantic_graph_inputs_from_store(&store, &scope)
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "no semantic graph inputs could be profiled".to_owned())?;
    let profile_ms = profile_started.elapsed().as_millis();

    let cold = run_truth_review_lane(config, &store, &scope, "truth-review-cold")?;
    let warm = run_truth_review_lane(config, &store, &scope, "truth-review-warm")?;
    let budgets = evaluate_budgets(config, ingest_ms, profile_ms, &cold, &warm);
    let status = if budgets.iter().any(|budget| !budget.ok) {
        HarnessStatus::Fail
    } else {
        HarnessStatus::Pass
    };

    if !config.keep_store {
        store.close_fast().map_err(display_error)?;
        let _ = fs::remove_dir_all(&config.store_path);
    }

    Ok(SemanticPerfHarnessReport {
        schema_version: 1,
        status,
        corpus: "docs/shortrun.md".to_owned(),
        store_path: config.store_path.display().to_string(),
        cache_dir: config.cache_dir.display().to_string(),
        model_id: config.graph.embed.model_id.clone(),
        model_root: config.graph.embed.model_root.display().to_string(),
        embedding_profile: config.graph.embed.profile.label().to_owned(),
        embedding_dim: config.graph.embed.profile.target_dim(),
        execution_provider: config.graph.embed.execution_provider.label().to_owned(),
        batch_size: config.graph.embed.batch_size,
        max_length: config.graph.embed.max_length,
        timings: HarnessTimings {
            ingest_ms,
            profile_ms,
            total_ms: total_started.elapsed().as_millis(),
        },
        ingest,
        profile,
        truth_review: TruthReviewPerf { cold, warm },
        budgets,
    })
}

fn ingest_shortrun(
    store: &PhoenixOvergraphStore,
) -> Result<phoenix_ingest_overgraph::NativeGraphTruthAuditReport, String> {
    let root = workspace_root();
    let text = fs::read_to_string(root.join("docs").join("shortrun.md"))
        .map_err(|error| format!("read docs/shortrun.md: {error}"))?;
    let document = IngestDocument {
        document_id: DocumentId("shortrun-full".to_owned()),
        note_id: None,
        title: "Shortrun Full".to_owned(),
        text,
        scope: ScopeKey::default(),
    };
    PhoenixInvarantV3::new(InvarantV3Config::default())
        .audit_native_graph_truth_slice(store, &document, None, 0, now_ms())
        .map_err(display_error)
}

fn run_truth_review_lane(
    config: &Config,
    store: &PhoenixOvergraphStore,
    scope: &ScopeKey,
    lane: &'static str,
) -> Result<LaneReport, String> {
    let request = SemanticEmbedderServiceRequest {
        scope: Some(scope.clone()),
        model: SemanticEmbedderModelRequest {
            model_id: Some(config.graph.embed.model_id.clone()),
            model_root: Some(config.graph.embed.model_root.clone()),
            embedding_profile: Some(config.graph.embed.profile.label().to_owned()),
            batch_size: Some(config.graph.embed.batch_size),
            max_length: Some(config.graph.embed.max_length),
            execution_provider: Some(config.graph.embed.execution_provider.label().to_owned()),
            embedding_cache_dir: Some(config.cache_dir.clone()),
        },
        edge_preview_limit: Some(0),
        ..Default::default()
    };
    let response = run_semantic_embedder_service_from_store(store, &request, now_ms())
        .map_err(|error| error.to_string())?
        .ok_or_else(|| format!("{lane} semantic graph batch was empty"))?;
    Ok(LaneReport {
        lane,
        derive_ms: response.timings.derive_ms,
        cache_hits: response.cache.hits,
        cache_misses: response.cache.misses,
        node_count: response.output.summary.node_count,
        edge_count: response.output.summary.edge_count,
        summary: response.output.summary,
    })
}

fn evaluate_budgets(
    config: &Config,
    ingest_ms: u128,
    profile_ms: u128,
    cold: &LaneReport,
    warm: &LaneReport,
) -> Vec<BudgetCheck> {
    let mut checks = Vec::with_capacity(7);
    push_ms(&mut checks, "ingestMs", ingest_ms, config.max_ingest_ms);
    push_ms(&mut checks, "profileMs", profile_ms, config.max_profile_ms);
    push_ms(
        &mut checks,
        "truthReviewColdMs",
        cold.derive_ms,
        config.max_cold_ms,
    );
    push_ms(
        &mut checks,
        "truthReviewWarmMs",
        warm.derive_ms,
        config.max_warm_ms,
    );
    checks.push(BudgetCheck {
        name: "truthReviewColdMisses".to_owned(),
        actual: cold.cache_misses as u128,
        limit: 1,
        ok: cold.cache_misses > 0,
        kind: BudgetKind::Minimum,
    });
    checks.push(BudgetCheck {
        name: "truthReviewWarmMisses".to_owned(),
        actual: warm.cache_misses as u128,
        limit: 0,
        ok: warm.cache_misses == 0,
        kind: BudgetKind::Maximum,
    });
    checks.push(BudgetCheck {
        name: "truthReviewWarmHits".to_owned(),
        actual: warm.cache_hits as u128,
        limit: cold.cache_misses as u128,
        ok: warm.cache_hits >= cold.cache_misses,
        kind: BudgetKind::Minimum,
    });
    checks
}

fn push_ms(checks: &mut Vec<BudgetCheck>, name: &str, actual: u128, limit: u128) {
    checks.push(BudgetCheck {
        name: name.to_owned(),
        actual,
        limit,
        ok: actual <= limit,
        kind: BudgetKind::Maximum,
    });
}

fn discover_scope(store: &PhoenixOvergraphStore) -> Result<ScopeKey, String> {
    let archives = store
        .load_latest_document_archives(None)
        .map_err(display_error)?;
    archives
        .first()
        .map(|archive| archive.manifest.scope.clone())
        .ok_or_else(|| "store did not contain any document archives".to_owned())
}

fn ensure_empty_path(path: &Path, label: &str) -> Result<(), String> {
    if !path.exists() {
        return Ok(());
    }
    if !path.is_dir() {
        return Err(format!(
            "{label} path is not a directory: {}",
            path.display()
        ));
    }
    let mut entries = fs::read_dir(path)
        .map_err(|error| format!("read {label} dir {}: {error}", path.display()))?;
    if entries.next().is_some() {
        return Err(format!(
            "{label} dir must be empty for a reproducible cold run: {}",
            path.display()
        ));
    }
    Ok(())
}

fn write_report(config: &Config, report: &SemanticPerfHarnessReport) -> Result<(), String> {
    let Some(path) = config.report_path.as_ref() else {
        return Ok(());
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create report dir {}: {error}", parent.display()))?;
    }
    let payload = serde_json::to_vec_pretty(report)
        .map_err(|error| format!("serialize semantic perf report: {error}"))?;
    fs::write(path, payload).map_err(|error| format!("write {}: {error}", path.display()))
}

#[derive(Clone, Debug)]
struct Config {
    store_path: PathBuf,
    cache_dir: PathBuf,
    report_path: Option<PathBuf>,
    keep_store: bool,
    max_ingest_ms: u128,
    max_profile_ms: u128,
    max_cold_ms: u128,
    max_warm_ms: u128,
    graph: SemanticGraphConfig,
}

impl Config {
    fn parse(args: &[String]) -> Result<Self, String> {
        let mut config = Self::default();
        let mut index = 1usize;
        while index < args.len() {
            match args[index].as_str() {
                "--store-path" => {
                    index += 1;
                    config.store_path = path_arg(args, index, "--store-path")?;
                }
                "--embedding-cache-dir" => {
                    index += 1;
                    config.cache_dir = path_arg(args, index, "--embedding-cache-dir")?;
                }
                "--report-output" => {
                    index += 1;
                    config.report_path = Some(path_arg(args, index, "--report-output")?);
                }
                "--keep-store" => config.keep_store = true,
                "--model-root" => {
                    index += 1;
                    config.graph.embed.model_root = path_arg(args, index, "--model-root")?;
                }
                "--model-id" => {
                    index += 1;
                    config.graph.embed.model_id = string_arg(args, index, "--model-id")?;
                }
                "--embedding-profile" => {
                    index += 1;
                    let value = string_arg(args, index, "--embedding-profile")?;
                    config.graph.embed.profile = TextEmbeddingProfile::parse(&value)
                        .ok_or_else(|| format!("unknown embedding profile: {value}"))?;
                }
                "--batch-size" => {
                    index += 1;
                    config.graph.embed.batch_size = usize_arg(args, index, "--batch-size")?.max(1);
                }
                "--max-length" => {
                    index += 1;
                    config.graph.embed.max_length = usize_arg(args, index, "--max-length")?.max(1);
                }
                "--execution-provider" => {
                    index += 1;
                    let value = string_arg(args, index, "--execution-provider")?;
                    config.graph.embed.execution_provider =
                        OrtExecutionProviderPreference::parse(&value)
                            .ok_or_else(|| format!("unknown execution provider: {value}"))?;
                }
                "--max-ingest-ms" => {
                    index += 1;
                    config.max_ingest_ms = u128_arg(args, index, "--max-ingest-ms")?;
                }
                "--max-profile-ms" => {
                    index += 1;
                    config.max_profile_ms = u128_arg(args, index, "--max-profile-ms")?;
                }
                "--max-cold-ms" => {
                    index += 1;
                    config.max_cold_ms = u128_arg(args, index, "--max-cold-ms")?;
                }
                "--max-warm-ms" => {
                    index += 1;
                    config.max_warm_ms = u128_arg(args, index, "--max-warm-ms")?;
                }
                flag => return Err(format!("unknown argument: {flag}")),
            }
            index += 1;
        }
        config.graph.embed.embedding_cache_dir = Some(config.cache_dir.clone());
        Ok(config)
    }
}

impl Default for Config {
    fn default() -> Self {
        let run_id = format!("{}-{}", std::process::id(), unix_nanos());
        let report_root = phoenix_root().join("reports");
        Self {
            store_path: report_root.join(format!("semantic-perf-store-{run_id}")),
            cache_dir: report_root.join(format!("semantic-perf-cache-{run_id}")),
            report_path: Some(report_root.join(format!("semantic-perf-harness-{run_id}.json"))),
            keep_store: false,
            max_ingest_ms: DEFAULT_INGEST_BUDGET_MS,
            max_profile_ms: DEFAULT_PROFILE_BUDGET_MS,
            max_cold_ms: DEFAULT_COLD_BUDGET_MS,
            max_warm_ms: DEFAULT_WARM_BUDGET_MS,
            graph: SemanticGraphConfig::default(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
struct SemanticPerfHarnessReport {
    schema_version: u32,
    status: HarnessStatus,
    corpus: String,
    store_path: String,
    cache_dir: String,
    model_id: String,
    model_root: String,
    embedding_profile: String,
    embedding_dim: usize,
    execution_provider: String,
    batch_size: usize,
    max_length: usize,
    timings: HarnessTimings,
    ingest: phoenix_ingest_overgraph::NativeGraphTruthAuditReport,
    profile: SemanticGraphInputProfile,
    truth_review: TruthReviewPerf,
    budgets: Vec<BudgetCheck>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
enum HarnessStatus {
    Pass,
    Fail,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
struct HarnessTimings {
    ingest_ms: u128,
    profile_ms: u128,
    total_ms: u128,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
struct TruthReviewPerf {
    cold: LaneReport,
    warm: LaneReport,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
struct LaneReport {
    lane: &'static str,
    derive_ms: u128,
    cache_hits: usize,
    cache_misses: usize,
    node_count: usize,
    edge_count: usize,
    summary: SemanticGraphCompilerSummary,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
struct BudgetCheck {
    name: String,
    actual: u128,
    limit: u128,
    ok: bool,
    kind: BudgetKind,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
enum BudgetKind {
    Maximum,
    Minimum,
}

fn path_arg(args: &[String], index: usize, flag: &str) -> Result<PathBuf, String> {
    Ok(PathBuf::from(string_arg(args, index, flag)?))
}

fn string_arg(args: &[String], index: usize, flag: &str) -> Result<String, String> {
    args.get(index)
        .cloned()
        .ok_or_else(|| format!("{flag} requires a value"))
}

fn usize_arg(args: &[String], index: usize, flag: &str) -> Result<usize, String> {
    string_arg(args, index, flag)?
        .parse::<usize>()
        .map_err(|error| format!("{flag} requires a usize: {error}"))
}

fn u128_arg(args: &[String], index: usize, flag: &str) -> Result<u128, String> {
    string_arg(args, index, flag)?
        .parse::<u128>()
        .map_err(|error| format!("{flag} requires an integer millisecond budget: {error}"))
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("workspace root")
        .to_path_buf()
}

fn phoenix_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("phoenix root")
        .to_path_buf()
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

fn unix_nanos() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
}

fn display_error(error: StoreError) -> String {
    error.to_string()
}

fn exit_err(error: String) -> ! {
    eprintln!("{error}");
    std::process::exit(1);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn budget_checks_require_warm_cache_hits_without_warm_misses() {
        let mut config = Config::default();
        config.max_ingest_ms = 100;
        config.max_profile_ms = 50;
        config.max_cold_ms = 300;
        config.max_warm_ms = 40;
        let cold = lane(250, 0, 65);
        let warm = lane(30, 65, 0);

        let checks = evaluate_budgets(&config, 80, 20, &cold, &warm);

        assert!(checks.iter().all(|check| check.ok));
    }

    #[test]
    fn budget_checks_fail_on_warm_cache_miss_or_slow_warm_lane() {
        let mut config = Config::default();
        config.max_ingest_ms = 100;
        config.max_profile_ms = 50;
        config.max_cold_ms = 300;
        config.max_warm_ms = 40;
        let cold = lane(250, 0, 65);
        let warm = lane(41, 64, 1);

        let checks = evaluate_budgets(&config, 80, 20, &cold, &warm);

        let failed = checks
            .iter()
            .filter(|check| !check.ok)
            .map(|check| check.name.as_str())
            .collect::<Vec<_>>();
        assert_eq!(
            failed,
            vec![
                "truthReviewWarmMs",
                "truthReviewWarmMisses",
                "truthReviewWarmHits"
            ]
        );
    }

    #[test]
    fn parses_model_execution_and_budget_args() {
        let args = vec![
            "phoenix-semantic-perf-harness".to_owned(),
            "--model-id".to_owned(),
            "example/model".to_owned(),
            "--embedding-profile".to_owned(),
            "768".to_owned(),
            "--execution-provider".to_owned(),
            "directml".to_owned(),
            "--batch-size".to_owned(),
            "64".to_owned(),
            "--max-warm-ms".to_owned(),
            "1234".to_owned(),
        ];

        let config = Config::parse(&args).expect("config");

        assert_eq!(config.graph.embed.model_id, "example/model");
        assert_eq!(config.graph.embed.profile, TextEmbeddingProfile::Native768);
        assert_eq!(
            config.graph.embed.execution_provider,
            OrtExecutionProviderPreference::DirectMl
        );
        assert_eq!(config.graph.embed.batch_size, 64);
        assert_eq!(config.max_warm_ms, 1234);
    }

    fn lane(derive_ms: u128, cache_hits: usize, cache_misses: usize) -> LaneReport {
        LaneReport {
            lane: "test",
            derive_ms,
            cache_hits,
            cache_misses,
            node_count: 65,
            edge_count: 178,
            summary: SemanticGraphCompilerSummary::default(),
        }
    }
}

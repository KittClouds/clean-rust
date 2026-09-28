#[path = "phoenix_advisor_probe/support.rs"]
mod support;

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use ort::session::builder::GraphOptimizationLevel;
use ort::session::Session;
use phoenix_rel_post::{
    build_advisor_packet_tasks_from_value, build_advisor_probe_tasks, AdvisorProbeTask,
};
use serde_json::Value;
use support::{build_task_result, cpu_input_memory_info, run_task, ProbeReport, ProbeScratch};
use tokenizers::Tokenizer;

#[derive(Debug, Clone)]
struct Config {
    suite: String,
    variant: String,
    tasks: String,
    max_new_tokens: usize,
    input_path: PathBuf,
    model_root: PathBuf,
    json: bool,
    no_save: bool,
}

impl Default for Config {
    fn default() -> Self {
        let workspace_root = workspace_root();
        Self {
            suite: "report".to_owned(),
            variant: "q4".to_owned(),
            tasks: "all".to_owned(),
            max_new_tokens: 80,
            input_path: default_report_path(&workspace_root),
            model_root: workspace_root
                .join("lfm25-turboquant-onnx")
                .join(".cache")
                .join("hf-models")
                .join("LiquidAI")
                .join("LFM2.5-350M-ONNX"),
            json: false,
            no_save: false,
        }
    }
}

fn main() -> Result<(), String> {
    let config = parse_args(&env::args().collect::<Vec<_>>())?;
    configure_ort_dylib_path();
    let input_value = load_json_value(&config.input_path)?;
    let tasks = select_tasks(build_tasks(&config, &input_value)?, &config.tasks)?;
    let model_path = model_path(&config.model_root, &config.variant)?;
    let tokenizer = Tokenizer::from_file(config.model_root.join("tokenizer.json"))
        .map_err(|error| format!("load tokenizer: {error}"))?;
    let session = Session::builder()
        .and_then(|builder| builder.with_optimization_level(GraphOptimizationLevel::Level3))
        .and_then(|builder| builder.with_parallel_execution(false))
        .and_then(|builder| builder.with_inter_threads(1))
        .and_then(|builder| builder.with_intra_threads(recommended_thread_count()))
        .and_then(|builder| builder.commit_from_file(&model_path))
        .map_err(|error| format!("load model {}: {error}", model_path.display()))?;
    let cpu_memory_info = cpu_input_memory_info()?;
    let mut scratch = ProbeScratch::default();

    let mut results = Vec::with_capacity(tasks.len());
    for task in tasks {
        results.push(build_task_result(
            &task,
            run_task(
                &session,
                &tokenizer,
                &task,
                config.max_new_tokens,
                &cpu_memory_info,
                &mut scratch,
            )?,
        ));
    }
    let report = ProbeReport {
        model_root: config.model_root.display().to_string(),
        variant: config.variant.clone(),
        report_path: config.input_path.display().to_string(),
        timestamp_ms: now_ms(),
        tasks: results,
    };
    if config.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&report)
                .map_err(|error| format!("render json: {error}"))?
        );
    } else {
        print_human(&report);
    }
    if !config.no_save {
        let out_path = save_report(&report, &workspace_root())?;
        eprintln!("saved advisor probe to {}", out_path.display());
    }
    Ok(())
}

fn parse_args(args: &[String]) -> Result<Config, String> {
    let mut config = Config::default();
    let mut custom_input_path = false;
    if let Some(value) = string_arg(args, "--suite") {
        config.suite = value;
    }
    if let Some(value) = string_arg(args, "--variant") {
        config.variant = value;
    }
    if let Some(value) = string_arg(args, "--tasks") {
        config.tasks = value;
    }
    if let Some(value) = string_arg(args, "--report") {
        config.input_path = PathBuf::from(value);
        custom_input_path = true;
    }
    if let Some(value) = string_arg(args, "--packet-file") {
        config.input_path = PathBuf::from(value);
        custom_input_path = true;
    }
    if let Some(value) = string_arg(args, "--model-root") {
        config.model_root = PathBuf::from(value);
    }
    if let Some(value) = string_arg(args, "--max-new-tokens") {
        config.max_new_tokens = value
            .parse::<usize>()
            .map_err(|error| format!("invalid --max-new-tokens: {error}"))?;
    }
    config.json = args.iter().any(|arg| arg == "--json");
    config.no_save = args.iter().any(|arg| arg == "--no-save");
    if !custom_input_path && config.suite == "packets" {
        config.input_path = default_packet_path(&workspace_root());
    }
    Ok(config)
}

fn build_tasks(config: &Config, input_value: &Value) -> Result<Vec<AdvisorProbeTask>, String> {
    match config.suite.as_str() {
        "report" => build_advisor_probe_tasks(input_value),
        "packets" => build_advisor_packet_tasks_from_value(input_value),
        other => Err(format!("unknown --suite: {other}")),
    }
}

fn string_arg(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|window| window[0] == flag)
        .map(|window| window[1].clone())
}

fn select_tasks(
    tasks: Vec<AdvisorProbeTask>,
    selected: &str,
) -> Result<Vec<AdvisorProbeTask>, String> {
    if selected == "all" {
        return Ok(tasks);
    }
    let wanted = selected
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>();
    let by_name = tasks
        .into_iter()
        .map(|task| (task.name.clone(), task))
        .collect::<BTreeMap<_, _>>();
    let mut selected_tasks = Vec::with_capacity(wanted.len());
    for name in wanted {
        let Some(task) = by_name.get(name) else {
            return Err(format!("unknown task: {name}"));
        };
        selected_tasks.push(task.clone());
    }
    Ok(selected_tasks)
}

fn model_path(model_root: &Path, variant: &str) -> Result<PathBuf, String> {
    let file = match variant {
        "fp16" => "model_fp16.onnx",
        "q4" => "model_q4.onnx",
        "q4f32" => "model_q4f32.onnx",
        "q8" => "model_q8.onnx",
        _ => return Err(format!("unknown variant: {variant}")),
    };
    let path = model_root.join(file);
    if path.exists() {
        Ok(path)
    } else {
        Err(format!("missing model file {}", path.display()))
    }
}

fn load_json_value(path: &Path) -> Result<Value, String> {
    let payload = std::fs::read_to_string(path)
        .map_err(|error| format!("read {}: {error}", path.display()))?;
    serde_json::from_str(&payload).map_err(|error| format!("parse {}: {error}", path.display()))
}

fn default_report_path(workspace_root: &Path) -> PathBuf {
    workspace_root
        .join("rust-native")
        .join("phoenix")
        .join("reports")
        .join("depth-audit-runtime-image-cache-warm-2.json")
}

fn default_packet_path(workspace_root: &Path) -> PathBuf {
    workspace_root
        .join("lfm25-turboquant-onnx")
        .join("config")
        .join("phoenix_advisor_packets.json")
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("workspace root")
        .to_path_buf()
}

fn configure_ort_dylib_path() {
    if env::var_os("ORT_DYLIB_PATH").is_some() {
        return;
    }
    if let Some(path) = default_ort_dylib_path(&workspace_root()) {
        env::set_var("ORT_DYLIB_PATH", path);
    }
}

fn default_ort_dylib_path(workspace_root: &Path) -> Option<PathBuf> {
    [
        workspace_root
            .join("node_modules")
            .join("@huggingface")
            .join("transformers")
            .join("node_modules")
            .join("onnxruntime-node")
            .join("bin")
            .join("napi-v6")
            .join("win32")
            .join("x64")
            .join("onnxruntime.dll"),
        workspace_root
            .join("node_modules")
            .join("onnxruntime-node")
            .join("bin")
            .join("napi-v3")
            .join("win32")
            .join("x64")
            .join("onnxruntime.dll"),
    ]
    .into_iter()
    .find(|path| path.exists())
}

fn recommended_thread_count() -> usize {
    std::thread::available_parallelism()
        .map(|count| count.get().min(8))
        .unwrap_or(1)
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or_default()
}

fn print_human(report: &ProbeReport) {
    println!("variant: {}", report.variant);
    println!("model_root: {}", report.model_root);
    println!("input_path: {}", report.report_path);
    let evaluated = report
        .tasks
        .iter()
        .filter_map(|task| task.evaluation.as_ref())
        .collect::<Vec<_>>();
    if !evaluated.is_empty() {
        let overall = evaluated
            .iter()
            .filter(|evaluation| evaluation.overall_pass)
            .count();
        let exact = evaluated
            .iter()
            .filter(|evaluation| evaluation.exact_pass)
            .count();
        let containment = evaluated
            .iter()
            .filter(|evaluation| evaluation.containment_pass)
            .count();
        println!(
            "packetEval: overall={}/{} exact={}/{} containment={}/{}",
            overall,
            evaluated.len(),
            exact,
            evaluated.len(),
            containment,
            evaluated.len()
        );
    }
    for task in &report.tasks {
        println!("\n== {} ==", task.task);
        println!("raw: {}", task.raw.text);
        println!(
            "  packetKind={:?} jsonError={:?} schemaError={:?} eval={:?} tokens={} decodeMs={:.3} cache={}/{}",
            task.packet_kind,
            task.raw.json_error,
            task.raw.schema_error,
            task.evaluation
                .as_ref()
                .map(|evaluation| (evaluation.overall_pass, evaluation.issues.as_slice())),
            task.raw.generated_token_count,
            task.raw.avg_decode_ms,
            task.raw.cache.kv_bytes,
            task.raw.cache.total_bytes
        );
    }
}

fn save_report(report: &ProbeReport, workspace_root: &Path) -> Result<PathBuf, String> {
    let path = workspace_root
        .join("lfm25-turboquant-onnx")
        .join("results")
        .join(format!(
            "phoenix-advisor-probe-rust-{}.json",
            report.timestamp_ms
        ));
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("create results dir {}: {error}", parent.display()))?;
    }
    fs::write(
        &path,
        serde_json::to_vec_pretty(report).map_err(|error| format!("serialize report: {error}"))?,
    )
    .map_err(|error| format!("write report {}: {error}", path.display()))?;
    Ok(path)
}

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use openrouter_rs::{
    api::chat::{ChatCompletionRequest, Message},
    types::{completion::CompletionsResponse, ResponseUsage, Role},
    OpenRouterClient,
};
use phoenix_rel_post::{
    build_advisor_packet_tasks_from_value, build_advisor_probe_tasks, evaluate_packet_output,
    missing_required_keys, parse_advisor_output, AdvisorPacketEvaluation, AdvisorProbeTask,
};
use serde::Serialize;
use serde_json::Value;

const SYSTEM_PROMPT: &str = "You are a late-stage Phoenix graph aide. Return one compact JSON object only. Do not use markdown fences. Fill values from evidence; never copy placeholder text. The first character of your answer must be { and the final character must be }. Never write prose before or after the JSON object. Do not assert graph truth, mutate graph truth, or invent missing evidence. Use review or defer language when the evidence is weak.";

#[derive(Debug, Clone)]
struct Config {
    suite: String,
    tasks: String,
    input_path: PathBuf,
    api_key_path: PathBuf,
    model: String,
    max_tokens: u32,
    temperature: f64,
    retries: u32,
    json: bool,
    no_save: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProbeReport {
    model: String,
    input_path: String,
    timestamp_ms: i64,
    tasks: Vec<TaskResult>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct TaskResult {
    task: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    packet_kind: Option<String>,
    raw_text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    request_error: Option<String>,
    parsed_json: Option<Value>,
    json_error: Option<String>,
    schema_error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    evaluation: Option<AdvisorPacketEvaluation>,
    latency_ms: f64,
    provider: Option<String>,
    response_model: String,
    usage: Option<ResponseUsage>,
    reasoning: Option<String>,
}

impl Default for Config {
    fn default() -> Self {
        let workspace_root = workspace_root();
        Self {
            suite: "packets".to_owned(),
            tasks: "all".to_owned(),
            input_path: workspace_root
                .join("lfm25-turboquant-onnx")
                .join("config")
                .join("phoenix_advisor_packets.json"),
            api_key_path: workspace_root.join("docs").join("key.md"),
            model: "google/gemma-4-31b-it:free".to_owned(),
            max_tokens: 160,
            temperature: 0.1,
            retries: 2,
            json: false,
            no_save: false,
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let config = parse_args(&env::args().collect::<Vec<_>>())?;
    let api_key = resolve_api_key(&config)?;
    let input_value = load_json_value(&config.input_path)?;
    let tasks = select_tasks(build_tasks(&config, &input_value)?, &config.tasks)?;
    let client = OpenRouterClient::builder()
        .api_key(api_key)
        .http_referer("https://overgraph.io")
        .x_title("Phoenix Advisor Probe")
        .build()
        .map_err(|error| format!("build openrouter client: {error}"))?;

    let mut results = Vec::with_capacity(tasks.len());
    for task in tasks {
        results.push(run_task(&client, &config, &task).await);
    }

    let report = ProbeReport {
        model: config.model.clone(),
        input_path: config.input_path.display().to_string(),
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

async fn run_task(
    client: &OpenRouterClient,
    config: &Config,
    task: &AdvisorProbeTask,
) -> TaskResult {
    let request = ChatCompletionRequest::builder()
        .model(config.model.clone())
        .messages(vec![
            Message::new(Role::System, SYSTEM_PROMPT),
            Message::new(Role::User, build_user_prompt(task)),
        ])
        .max_tokens(config.max_tokens)
        .temperature(config.temperature)
        .build()
        .map_err(|error| format!("build request for {}: {error}", task.name));
    let request = match request {
        Ok(request) => request,
        Err(error) => return failed_task_result(task, error, 0.0),
    };

    let started = Instant::now();
    let response =
        match send_chat_completion_with_retry(client, &request, &task.name, config.retries).await {
            Ok(response) => response,
            Err(error) => {
                return failed_task_result(task, error, started.elapsed().as_secs_f64() * 1000.0)
            }
        };
    let latency_ms = started.elapsed().as_secs_f64() * 1000.0;
    let raw_text = first_response_text(&response).trim().to_owned();
    let (parsed_json, json_error) = parse_advisor_output(&raw_text);
    let schema_error = missing_required_keys(parsed_json.as_ref(), &task.required_keys);
    let evaluation = evaluate_packet_output(task, parsed_json.as_ref());

    TaskResult {
        task: task.name.clone(),
        packet_kind: task.packet_kind.clone(),
        raw_text,
        request_error: None,
        parsed_json,
        json_error,
        schema_error,
        evaluation,
        latency_ms,
        provider: response.provider.clone(),
        response_model: response.model.clone(),
        usage: response.usage.clone(),
        reasoning: first_reasoning(&response),
    }
}

fn build_user_prompt(task: &AdvisorProbeTask) -> String {
    format!(
        "{}\nOutput contract: return exactly one JSON object with every requested key. Required keys: {}. Start with {{ and end with }}. No markdown fences. No prose before or after JSON.",
        task.prompt,
        task.required_keys.join(", ")
    )
}

fn first_response_text(response: &CompletionsResponse) -> String {
    response
        .choices
        .first()
        .and_then(|choice| choice.content())
        .unwrap_or_default()
        .to_owned()
}

fn first_reasoning(response: &CompletionsResponse) -> Option<String> {
    response
        .choices
        .first()
        .and_then(|choice| choice.reasoning())
        .map(str::to_owned)
}

fn parse_args(args: &[String]) -> Result<Config, String> {
    let mut config = Config::default();
    let mut custom_input_path = false;
    if let Some(value) = string_arg(args, "--suite") {
        config.suite = value;
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
    if let Some(value) = string_arg(args, "--api-key-file") {
        config.api_key_path = PathBuf::from(value);
    }
    if let Some(value) = string_arg(args, "--model") {
        config.model = value;
    }
    if let Some(value) = string_arg(args, "--max-tokens") {
        config.max_tokens = value
            .parse::<u32>()
            .map_err(|error| format!("invalid --max-tokens: {error}"))?;
    }
    if let Some(value) = string_arg(args, "--temperature") {
        config.temperature = value
            .parse::<f64>()
            .map_err(|error| format!("invalid --temperature: {error}"))?;
    }
    if let Some(value) = string_arg(args, "--retries") {
        config.retries = value
            .parse::<u32>()
            .map_err(|error| format!("invalid --retries: {error}"))?;
    }
    config.json = args.iter().any(|arg| arg == "--json");
    config.no_save = args.iter().any(|arg| arg == "--no-save");
    if !custom_input_path && config.suite == "report" {
        config.input_path = workspace_root()
            .join("rust-native")
            .join("phoenix")
            .join("reports")
            .join("depth-audit-runtime-image-cache-warm-2.json");
    }
    Ok(config)
}

fn string_arg(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|window| window[0] == flag)
        .map(|window| window[1].clone())
}

fn build_tasks(config: &Config, input_value: &Value) -> Result<Vec<AdvisorProbeTask>, String> {
    match config.suite.as_str() {
        "report" => build_advisor_probe_tasks(input_value),
        "packets" => build_advisor_packet_tasks_from_value(input_value),
        other => Err(format!("unknown --suite: {other}")),
    }
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

fn resolve_api_key(config: &Config) -> Result<String, String> {
    if let Ok(value) = env::var("OPENROUTER_API_KEY") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(trimmed.to_owned());
        }
    }
    let payload = fs::read_to_string(&config.api_key_path).map_err(|error| {
        format!(
            "read api key file {}: {error}",
            config.api_key_path.display()
        )
    })?;
    let trimmed = payload.trim();
    if trimmed.is_empty() {
        Err(format!(
            "api key file {} is empty",
            config.api_key_path.display()
        ))
    } else {
        Ok(trimmed.to_owned())
    }
}

fn load_json_value(path: &Path) -> Result<Value, String> {
    let payload =
        fs::read_to_string(path).map_err(|error| format!("read {}: {error}", path.display()))?;
    serde_json::from_str(&payload).map_err(|error| format!("parse {}: {error}", path.display()))
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(4)
        .expect("workspace root")
        .to_path_buf()
}

fn print_human(report: &ProbeReport) {
    println!("model: {}", report.model);
    println!("input_path: {}", report.input_path);
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
        println!("raw: {}", task.raw_text);
        println!(
            "  provider={:?} model={} requestError={:?} jsonError={:?} schemaError={:?} eval={:?} latencyMs={:.1} usage={:?}",
            task.provider,
            task.response_model,
            task.request_error,
            task.json_error,
            task.schema_error,
            task.evaluation
                .as_ref()
                .map(|evaluation| (evaluation.overall_pass, evaluation.issues.as_slice())),
            task.latency_ms,
            task.usage.as_ref().map(|usage| (
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens
            ))
        );
    }
}

fn save_report(report: &ProbeReport, workspace_root: &Path) -> Result<PathBuf, String> {
    let path = workspace_root
        .join("lfm25-turboquant-onnx")
        .join("results")
        .join(format!(
            "phoenix-advisor-openrouter-{}.json",
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

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or_default()
}

async fn send_chat_completion_with_retry(
    client: &OpenRouterClient,
    request: &ChatCompletionRequest,
    task_name: &str,
    retries: u32,
) -> Result<CompletionsResponse, String> {
    let mut attempt = 0u32;
    loop {
        match client.send_chat_completion(request).await {
            Ok(response) => return Ok(response),
            Err(error) => {
                let message = format!("openrouter request for {task_name}: {error}");
                if attempt >= retries {
                    return Err(message);
                }
                let Some(delay_ms) = retry_delay_ms(&message) else {
                    return Err(message);
                };
                tokio::time::sleep(std::time::Duration::from_millis(delay_ms)).await;
                attempt += 1;
            }
        }
    }
}

fn retry_delay_ms(message: &str) -> Option<u64> {
    let marker = "retry in ";
    let start = message.find(marker)? + marker.len();
    let tail = &message[start..];
    let seconds = tail
        .chars()
        .take_while(|ch| ch.is_ascii_digit() || *ch == '.')
        .collect::<String>();
    if seconds.is_empty() {
        return None;
    }
    let seconds = seconds.parse::<f64>().ok()?;
    Some((seconds * 1000.0).ceil() as u64 + 1_000)
}

fn failed_task_result(task: &AdvisorProbeTask, error: String, latency_ms: f64) -> TaskResult {
    TaskResult {
        task: task.name.clone(),
        packet_kind: task.packet_kind.clone(),
        raw_text: String::new(),
        request_error: Some(error),
        parsed_json: None,
        json_error: None,
        schema_error: None,
        evaluation: evaluate_packet_output(task, None),
        latency_ms,
        provider: None,
        response_model: String::new(),
        usage: None,
        reasoning: None,
    }
}

#[cfg(test)]
mod tests {
    use super::{retry_delay_ms, workspace_root, Config};

    #[test]
    fn retry_delay_parses_provider_backoff_seconds() {
        let message = "Provider error: Please retry in 55.2827267s.";
        let delay_ms = retry_delay_ms(message).expect("retry delay");
        assert!(delay_ms >= 56_000);
        assert!(delay_ms < 57_000);
    }

    #[test]
    fn default_remote_suite_points_to_packet_file() {
        let config = Config::default();
        assert_eq!(config.suite, "packets");
        assert_eq!(
            config.input_path,
            workspace_root()
                .join("lfm25-turboquant-onnx")
                .join("config")
                .join("phoenix_advisor_packets.json")
        );
    }
}

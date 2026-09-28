use hashbrown::HashMap;
use r1_stage1_search::{IdentityCompositionV03, MappedSensorExtraction};
use r1_world::InferenceTask;
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::env;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

#[derive(Serialize)]
struct SelectorSidecar {
    schema: &'static str,
    trace_id: String,
    score_semantics: String,
    initial_assignment_scores: Vec<f64>,
    event_assignment_scores: Vec<f64>,
}

#[derive(Serialize)]
struct SidecarReceipt {
    trace_file: String,
    trace_sha256: String,
    selector_file: String,
    selector_sha256: String,
    task_id: String,
    event_count: usize,
}

#[derive(Serialize)]
struct RerankManifest {
    schema: &'static str,
    status: &'static str,
    ranking: &'static str,
    pooled_weight: f64,
    identity_binary_sha256: &'static str,
    sidecars: Vec<SidecarReceipt>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let public_tasks_path = PathBuf::from(args.next().ok_or("missing public task JSONL")?);
    let support_manifest_path = PathBuf::from(args.next().ok_or("missing support manifest")?);
    let sensor_dir = PathBuf::from(args.next().ok_or("missing sensor extraction directory")?);
    let trace_dir = PathBuf::from(args.next().ok_or("missing trace directory")?);
    let output_dir = PathBuf::from(args.next().ok_or("missing fresh output directory")?);
    let pooled_weight = args
        .next()
        .map(|value| value.parse::<f64>())
        .transpose()?
        .unwrap_or(0.0);
    if args.next().is_some() {
        return Err("unexpected extra arguments".into());
    }
    if !pooled_weight.is_finite() || !(0.0..=1.0).contains(&pooled_weight) {
        return Err("optional pooled identity weight must be between zero and one".into());
    }
    if output_dir.exists() {
        return Err(format!("output already exists: {}", output_dir.display()).into());
    }
    fs::create_dir_all(&output_dir)?;

    let tasks: Vec<InferenceTask> = read_jsonl(&public_tasks_path)?;
    let tasks_by_id: HashMap<String, InferenceTask> = tasks
        .into_iter()
        .map(|task| (task.id.clone(), task))
        .collect();
    let extraction =
        MappedSensorExtraction::open(&sensor_dir, &public_tasks_path, &support_manifest_path)?;
    let mut features_by_id = HashMap::with_capacity(tasks_by_id.len());
    for (task_id, task) in &tasks_by_id {
        features_by_id.insert(task_id.clone(), extraction.load_task(task)?);
    }
    let mut identity = IdentityCompositionV03::load_default()?;
    let mut trace_paths = fs::read_dir(&trace_dir)?
        .map(|entry| entry.map(|item| item.path()))
        .collect::<Result<Vec<_>, _>>()?;
    trace_paths.retain(|path| {
        path.file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.ends_with(".trace.jsonl"))
    });
    trace_paths.sort();
    if trace_paths.is_empty() {
        return Err(format!("no trace JSONL files in {}", trace_dir.display()).into());
    }

    let mut receipts = Vec::with_capacity(trace_paths.len());
    for trace_path in trace_paths {
        let trace_name = trace_path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or("trace file name is not UTF-8")?;
        let trace_file = File::open(&trace_path)?;
        let mut reader = BufReader::new(trace_file);
        let mut line = String::new();
        let mut header: Option<Value> = None;
        let mut footer: Option<Value> = None;
        let mut events = Vec::new();
        while reader.read_line(&mut line)? != 0 {
            let record: Value = serde_json::from_str(&line)?;
            let kind = record
                .get("record")
                .and_then(Value::as_str)
                .ok_or("trace record omits record kind")?;
            let payload = record.get("payload").ok_or("trace record omits payload")?;
            match kind {
                "header" => {
                    if header.replace(payload.clone()).is_some() {
                        return Err(format!("duplicate header in {trace_name}").into());
                    }
                }
                "event" => events.push(payload.clone()),
                "footer" => {
                    if footer.replace(payload.clone()).is_some() {
                        return Err(format!("duplicate footer in {trace_name}").into());
                    }
                }
                other => return Err(format!("unexpected trace record {other:?}").into()),
            }
            line.clear();
        }
        let header = header.ok_or_else(|| format!("missing header in {trace_name}"))?;
        let footer = footer.ok_or_else(|| format!("missing footer in {trace_name}"))?;
        let footer_expansions = footer
            .get("ledger")
            .and_then(|ledger| ledger.get("expansions"))
            .and_then(Value::as_u64)
            .ok_or("trace footer omits ledger expansions")?;
        if footer_expansions != events.len() as u64 {
            return Err(
                format!("footer expansion count differs from events in {trace_name}").into(),
            );
        }
        let task_id = string_field(&header, "task_id")?.to_owned();
        let features = features_by_id
            .get(&task_id)
            .ok_or_else(|| format!("trace task {task_id} is absent from public tasks"))?;
        let trace_id = string_field(&header, "trace_id")?.to_owned();
        let initial_particles = header
            .get("initial_particles")
            .and_then(Value::as_array)
            .ok_or("trace header omits initial particles")?;
        let initial_assignment_scores = initial_particles
            .iter()
            .map(|particle| {
                let assignment = byte_array_field(particle, "assignment")?;
                identity
                    .expected_satisfied_clause_count_with_task_prior_for_task(
                        &task_id,
                        features,
                        &assignment,
                        pooled_weight,
                    )
                    .map_err(Into::into)
            })
            .collect::<Result<Vec<_>, Box<dyn std::error::Error>>>()?;
        let mut event_assignment_scores = Vec::with_capacity(events.len());
        for (expected_index, event) in events.iter().enumerate() {
            let event_index = event
                .get("event_index")
                .and_then(Value::as_u64)
                .ok_or("trace event omits event_index")? as usize;
            if event_index != expected_index {
                return Err(format!("noncontiguous event index in {trace_name}").into());
            }
            let assignment = byte_array_field(event, "assignment_after")?;
            event_assignment_scores.push(
                identity.expected_satisfied_clause_count_with_task_prior_for_task(
                    &task_id,
                    features,
                    &assignment,
                    pooled_weight,
                )?,
            );
        }
        let sidecar = SelectorSidecar {
            schema: if pooled_weight == 0.0 {
                "r1-terminal-ranking-sidecar-v02"
            } else {
                "r1-terminal-ranking-sidecar-v03"
            },
            trace_id,
            score_semantics: format!(
                "sum expected satisfaction using task-pooled identity weight {pooled_weight}; higher wins"
            ),
            initial_assignment_scores,
            event_assignment_scores,
        };
        let weight_tag = pooled_weight.to_string().replace('.', "p");
        let output_name = if pooled_weight == 0.0 {
            trace_name.replace(".trace.jsonl", ".expected-count.selector.json")
        } else {
            trace_name.replace(
                ".trace.jsonl",
                &format!(".task-pooled-{weight_tag}.selector.json"),
            )
        };
        let output_path = output_dir.join(&output_name);
        let bytes = serde_json::to_vec_pretty(&sidecar)?;
        fs::write(&output_path, &bytes)?;
        receipts.push(SidecarReceipt {
            trace_file: trace_name.to_owned(),
            trace_sha256: sha256_file(&trace_path)?,
            selector_file: output_name,
            selector_sha256: sha256_bytes(&bytes),
            task_id,
            event_count: events.len(),
        });
    }

    let manifest = RerankManifest {
        schema: if pooled_weight == 0.0 {
            "FAS_R1_Q_TERMINAL_RERANK_V07"
        } else {
            "FAS_R1_Q_TERMINAL_RERANK_V08"
        },
        status: "COMPLETE",
        ranking: if pooled_weight == 0.0 {
            "label-free local expected satisfied-clause count from pinned identity v03 and public incidence"
        } else {
            "label-free expected satisfied-clause count blending local identity with task-pooled prior"
        },
        pooled_weight,
        identity_binary_sha256: r1_stage1_search::IDENTITY_LINEAR_V03_BINARY_SHA256,
        sidecars: receipts,
    };
    let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
    let manifest_name = if pooled_weight == 0.0 {
        "rerank-manifest-v07.json"
    } else {
        "rerank-manifest-v08.json"
    };
    let mut writer = BufWriter::new(File::create(output_dir.join(manifest_name))?);
    writer.write_all(&manifest_bytes)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn read_jsonl<T: serde::de::DeserializeOwned>(
    path: &Path,
) -> Result<Vec<T>, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mut rows = Vec::new();
    for line in BufReader::new(file).lines() {
        let line = line?;
        if !line.trim().is_empty() {
            rows.push(serde_json::from_str(&line)?);
        }
    }
    Ok(rows)
}

fn string_field<'a>(value: &'a Value, name: &str) -> Result<&'a str, Box<dyn std::error::Error>> {
    value
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing string field {name}").into())
}

fn byte_array_field(value: &Value, name: &str) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let array = value
        .get(name)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("missing array field {name}"))?;
    array
        .iter()
        .map(|item| {
            item.as_u64()
                .and_then(|byte| u8::try_from(byte).ok())
                .ok_or_else(|| format!("invalid byte in {name}").into())
        })
        .collect()
}

fn sha256_file(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    Ok(sha256_bytes(&fs::read(path)?))
}

fn sha256_bytes(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::env;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

use r1_search::{annotate_posthoc, run, verify_replay, write_jsonl, Arm, RunConfig};
use r1_world::{enumerate_solutions, validate, validate_independent, InferenceTask, Task};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

const CANDIDATE_SCHEMA: &str = "R1_QTERMINAL_CANDIDATE_V01";
const POLICY_ID: &str = "R1_QTERMINAL_BASELINE_VISITATION_V1";
const RANDOM_ID: &str = "R1_QTERMINAL_CLASS_CONDITIONED_ASSIGNMENTS_V1";
const POSTHOC_LABEL_SOURCE: &str = "independent_typed_validator_v1";
const DEFAULT_SOLUTION_CAP: usize = 1_000_000;
const INVALID_DRAW_LIMIT: u64 = 1_000_000;

#[derive(Clone, Debug)]
struct Args {
    extraction_dir: PathBuf,
    private_tasks: PathBuf,
    output_dir: PathBuf,
    manifest: PathBuf,
    solution_cap: usize,
}

#[derive(Clone, Debug, Serialize)]
struct CandidateRecord {
    schema: &'static str,
    sample_id: String,
    feature_id: String,
    task_id: String,
    family_id: String,
    source_kind: &'static str,
    assignment: Vec<u8>,
    posthoc_valid: bool,
    label_source: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    random_sampler_id: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    random_replicate_index: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    policy_checkpoint_id: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    policy_training_split: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    policy_trace_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    trace_event_index: Option<i64>,
}

#[derive(Clone, Debug, Serialize)]
struct ArtifactHash {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Clone, Debug, Serialize)]
struct Receipt {
    schema: &'static str,
    status: &'static str,
    manifest_sha256: String,
    sensor_extraction_receipt_sha256: String,
    public_tasks_path: String,
    public_tasks_sha256: String,
    private_tasks_path: String,
    private_tasks_sha256: String,
    candidate_file: ArtifactHash,
    task_count: usize,
    family_counts: BTreeMap<String, usize>,
    candidate_counts: BTreeMap<String, usize>,
    solution_counts_exact: bool,
    validator_agreement_all_candidates: bool,
    policy_trace_count: usize,
    policy_trace_expansions: u64,
    policy_trace_replays_passed: bool,
    policy_config: Value,
    sensor_output_files: Vec<ArtifactHash>,
    policy_traces: Vec<ArtifactHash>,
    policy_sidecars: Vec<ArtifactHash>,
    output_files: Vec<ArtifactHash>,
    sensor_extraction_outputs_verified: bool,
    encoder_forward_performed_by_generator: bool,
    selector_training_performed: bool,
}

#[derive(Deserialize)]
struct ExtractionReceipt {
    schema: String,
    status: String,
    input: ExtractionInput,
    output_files: Vec<ExtractionOutput>,
    training_performed: bool,
    selector_training_performed: bool,
}

#[derive(Deserialize)]
struct ExtractionInput {
    path: PathBuf,
    sha256: String,
}

#[derive(Deserialize)]
struct ExtractionOutput {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Serialize)]
struct FailureReceipt {
    schema: &'static str,
    status: &'static str,
    error: String,
    sensor_extraction_outputs_verified: bool,
    encoder_forward_performed_by_generator: bool,
    selector_training_performed: bool,
}

fn main() {
    let args = match parse_args() {
        Ok(value) => value,
        Err(message) => {
            eprintln!("{message}\nusage: r1-qterminal-candidates --extraction DIR --private-tasks FILE --output NEW_DIR [--manifest FILE] [--solution-cap N]");
            std::process::exit(2);
        }
    };
    if args.output_dir.exists() {
        eprintln!(
            "refusing to overwrite existing output directory: {}",
            args.output_dir.display()
        );
        std::process::exit(2);
    }
    if let Err(error) = fs::create_dir_all(&args.output_dir) {
        eprintln!("cannot create output directory: {error}");
        std::process::exit(2);
    }
    match execute(&args) {
        Ok(receipt) => {
            if let Err(error) = write_json(
                &args.output_dir.join("candidate-generator-receipt.json"),
                &receipt,
            ) {
                eprintln!("cannot write success receipt: {error}");
                std::process::exit(1);
            }
            println!("{}", receipt.status);
        }
        Err(error) => {
            let receipt = FailureReceipt {
                schema: "R1_QTERMINAL_CANDIDATE_GENERATOR_RECEIPT_V02",
                status: "R1_QTERMINAL_CANDIDATE_GENERATION_FAILED",
                error: error.clone(),
                sensor_extraction_outputs_verified: false,
                encoder_forward_performed_by_generator: false,
                selector_training_performed: false,
            };
            let _ = write_json(
                &args.output_dir.join("candidate-generator-failure.json"),
                &receipt,
            );
            eprintln!("candidate generation failed: {error}");
            std::process::exit(1);
        }
    }
}

fn parse_args() -> Result<Args, String> {
    let mut values = env::args().skip(1);
    let mut extraction_dir = None;
    let mut private_tasks = None;
    let mut output_dir = None;
    let mut manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../manifest-v02.json");
    let mut solution_cap = DEFAULT_SOLUTION_CAP;
    while let Some(flag) = values.next() {
        let value = values
            .next()
            .ok_or_else(|| format!("missing value for {flag}"))?;
        match flag.as_str() {
            "--extraction" => extraction_dir = Some(PathBuf::from(value)),
            "--private-tasks" => private_tasks = Some(PathBuf::from(value)),
            "--output" => output_dir = Some(PathBuf::from(value)),
            "--manifest" => manifest = PathBuf::from(value),
            "--solution-cap" => {
                solution_cap = value
                    .parse()
                    .map_err(|_| "invalid --solution-cap".to_owned())?;
                if solution_cap == 0 {
                    return Err("--solution-cap must be positive".to_owned());
                }
            }
            _ => return Err(format!("unknown argument: {flag}")),
        }
    }
    Ok(Args {
        extraction_dir: extraction_dir.ok_or_else(|| "--extraction is required".to_owned())?,
        private_tasks: private_tasks.ok_or_else(|| "--private-tasks is required".to_owned())?,
        output_dir: output_dir.ok_or_else(|| "--output is required".to_owned())?,
        manifest,
        solution_cap,
    })
}

fn execute(args: &Args) -> Result<Receipt, String> {
    let manifest_bytes = fs::read(&args.manifest).map_err(display_error)?;
    let manifest: Value = serde_json::from_slice(&manifest_bytes).map_err(display_error)?;
    verify_manifest(&manifest)?;
    let extraction_receipt_path = args.extraction_dir.join("receipt.json");
    let extraction_receipt_bytes = fs::read(&extraction_receipt_path).map_err(display_error)?;
    let extraction: ExtractionReceipt =
        serde_json::from_slice(&extraction_receipt_bytes).map_err(display_error)?;
    if extraction.schema != "R1_STAGE1_SENSOR_EXTRACTION_V01"
        || extraction.status != "R1_SENSOR_EXTRACTION_COMPLETE"
        || extraction.training_performed
        || extraction.selector_training_performed
    {
        return Err(
            "sensor extraction receipt is incomplete or reports selector training".to_owned(),
        );
    }
    verify_extraction_outputs(&args.extraction_dir, &extraction.output_files)?;
    let public_tasks_path = extraction.input.path.clone();
    let public_hash = sha256_file(&public_tasks_path)?;
    if public_hash != extraction.input.sha256.to_lowercase() {
        return Err("extraction public-task input hash mismatch".to_owned());
    }
    let public_tasks: Vec<InferenceTask> = read_jsonl(&public_tasks_path)?;
    let private_tasks: Vec<Task> = read_jsonl(&args.private_tasks)?;
    if public_tasks.len() != private_tasks.len() || public_tasks.is_empty() {
        return Err("private/public task counts differ or are empty".to_owned());
    }
    let public_by_id: BTreeMap<_, _> = public_tasks
        .into_iter()
        .map(|task| (task.id.clone(), task))
        .collect();
    if public_by_id.len() != private_tasks.len() {
        return Err("public task IDs are not unique".to_owned());
    }

    let candidate_count = manifest["random_assignment_source"]
        ["candidate_count_per_feature_per_label"]
        .as_u64()
        .ok_or_else(|| "manifest random candidate count is absent".to_owned())?
        as usize;
    let trace_replicates = manifest["policy_trace_source"]["replicates_per_training_family"]
        .as_u64()
        .ok_or_else(|| "manifest policy replicate count is absent".to_owned())?
        as usize;
    let trace_budget = manifest["policy_trace_source"]["expansion_budget"]
        .as_u64()
        .ok_or_else(|| "manifest policy budget is absent".to_owned())?;
    let trace_width = manifest["policy_trace_source"]["width"]
        .as_u64()
        .ok_or_else(|| "manifest policy width is absent".to_owned())? as u16;

    let traces_dir = args.output_dir.join("policy-traces");
    let sidecars_dir = args.output_dir.join("policy-posthoc");
    fs::create_dir(&traces_dir).map_err(display_error)?;
    fs::create_dir(&sidecars_dir).map_err(display_error)?;
    let mut candidates = Vec::new();
    let mut family_sets = BTreeMap::<String, BTreeSet<String>>::new();
    let mut candidate_counts = BTreeMap::<String, usize>::new();
    let mut trace_hashes = Vec::new();
    let mut sidecar_hashes = Vec::new();
    let mut trace_replays_passed = true;
    let mut trace_expansions = 0u64;
    let mut validator_agreement = true;

    for (task_index, task) in private_tasks.iter().enumerate() {
        let public = public_by_id.get(&task.id).ok_or_else(|| {
            format!(
                "private task {} is absent from public extraction input",
                task.id
            )
        })?;
        if task.family_id != public.family_id
            || task.n != public.n
            || task.k != public.k
            || task.clauses.len() != public.clauses.len()
        {
            return Err(format!(
                "private/public task shape mismatch for {}",
                task.id
            ));
        }
        let split = family_split(&task.family_id, &manifest)?;
        family_sets
            .entry(split.to_owned())
            .or_default()
            .insert(task.family_id.clone());
        let solutions = enumerate_solutions(task, args.solution_cap).map_err(|error| {
            format!("exact solution enumeration failed for {}: {error}", task.id)
        })?;
        if solutions.is_empty() {
            return Err(format!("task {} has no valid assignment", task.id));
        }
        let positives = sample_valid_assignments(task, &solutions, &public.id, candidate_count)?;
        for (replicate, assignment) in positives {
            let valid = check_validator_pair(task, &assignment)?;
            if !valid {
                return Err(format!(
                    "exact solution sampler emitted an invalid assignment for {}",
                    task.id
                ));
            }
            push_random_candidate(
                &mut candidates,
                task,
                &public.id,
                assignment,
                valid,
                replicate,
                &mut candidate_counts,
            );
        }
        let negatives = sample_invalid_assignments(task, &public.id, candidate_count)?;
        for (replicate, assignment) in negatives {
            let valid = check_validator_pair(task, &assignment)?;
            if valid {
                return Err(format!(
                    "invalid sampler emitted a valid assignment for {}",
                    task.id
                ));
            }
            push_random_candidate(
                &mut candidates,
                task,
                &public.id,
                assignment,
                false,
                replicate,
                &mut candidate_counts,
            );
        }

        if split == "train" {
            for replicate in 0..trace_replicates {
                let seed = trace_seed(&task.family_id, replicate as u64);
                let mut config = RunConfig::new(Arm::RandomWidth, trace_budget, trace_width, seed);
                config.latent_dim = manifest["policy_trace_source"]["latent_dim"]
                    .as_u64()
                    .ok_or_else(|| "manifest latent_dim is absent".to_owned())?
                    as u16;
                let trace = run(public, config)
                    .map_err(|error| format!("baseline trace failed for {}: {error}", task.id))?;
                if trace.header.proposal_mode != r1_search::ProposalMode::UniformRandomStub
                    || trace.header.config.width != trace_width
                    || trace.header.config.budget != trace_budget
                    || trace.ledger.expansions != trace_budget
                    || trace.events.len() as u64 != trace_budget
                {
                    return Err(format!(
                        "trace for {} does not match the frozen baseline config",
                        task.id
                    ));
                }
                let sidecar = annotate_posthoc(task, &trace)
                    .map_err(|error| format!("posthoc labeling failed for {}: {error}", task.id))?;
                for initial in &trace.header.initial_particles {
                    let valid = check_validator_pair(task, &initial.assignment)?;
                    if valid != sidecar.initial_valid {
                        validator_agreement = false;
                    }
                    candidates.push(policy_candidate(
                        task,
                        &public.id,
                        trace.header.trace_id.clone(),
                        -1,
                        initial.assignment.clone(),
                        valid,
                    ));
                    count_candidate(&mut candidate_counts, "policy_visited", valid);
                }
                for (event, label) in trace.events.iter().zip(&sidecar.events) {
                    let valid = check_validator_pair(task, &event.assignment_after)?;
                    if valid != label.valid || label.event_index != event.event_index {
                        validator_agreement = false;
                    }
                    candidates.push(policy_candidate(
                        task,
                        &public.id,
                        trace.header.trace_id.clone(),
                        event.event_index as i64,
                        event.assignment_after.clone(),
                        valid,
                    ));
                    count_candidate(&mut candidate_counts, "policy_visited", valid);
                }
                if !validator_agreement {
                    return Err(format!(
                        "independent posthoc validator disagreement for {}",
                        task.id
                    ));
                }
                let replay = verify_replay(public, &trace).map_err(|error| {
                    format!("baseline trace replay failed for {}: {error}", task.id)
                })?;
                trace_replays_passed &= replay.passed;
                if !replay.passed {
                    return Err(format!("baseline trace replay mismatch for {}", task.id));
                }
                trace_expansions += trace.ledger.expansions;
                let stem = format!("task-{task_index:04}-rep-{replicate:02}");
                let trace_path = traces_dir.join(format!("{stem}.jsonl"));
                let sidecar_path = sidecars_dir.join(format!("{stem}.json"));
                write_jsonl(&trace_path, &trace).map_err(|error| error.to_string())?;
                write_json(&sidecar_path, &sidecar)?;
                trace_hashes.push(artifact_hash(&trace_path, &args.output_dir)?);
                sidecar_hashes.push(artifact_hash(&sidecar_path, &args.output_dir)?);
            }
        }
    }
    if !validator_agreement || !trace_replays_passed {
        return Err("validator or baseline replay gate failed".to_owned());
    }

    let candidates_path = args.output_dir.join("candidate-records.jsonl");
    let mut writer = BufWriter::new(File::create(&candidates_path).map_err(display_error)?);
    for candidate in &candidates {
        serde_json::to_writer(&mut writer, candidate).map_err(display_error)?;
        writer.write_all(b"\n").map_err(display_error)?;
    }
    writer.flush().map_err(display_error)?;
    let candidate_hash = artifact_hash(&candidates_path, &args.output_dir)?;
    let mut outputs = vec![candidate_hash.clone()];
    outputs.extend(trace_hashes.iter().cloned());
    outputs.extend(sidecar_hashes.iter().cloned());
    outputs.sort_by(|left, right| left.path.cmp(&right.path));
    let policy_config = serde_json::json!({
        "policy_checkpoint_id": POLICY_ID,
        "arm": "random_width",
        "proposal_mode": "uniform_random_stub",
        "width": trace_width,
        "expansion_budget": trace_budget,
        "replicates_per_training_family": trace_replicates,
        "latent_dim": manifest["policy_trace_source"]["latent_dim"],
        "seed_rule": manifest["policy_trace_source"]["trace_seed"],
    });
    let family_counts = family_sets
        .into_iter()
        .map(|(split, families)| (split, families.len()))
        .collect();
    let sensor_output_files = extraction
        .output_files
        .iter()
        .map(|file| ArtifactHash {
            path: file.path.clone(),
            bytes: file.bytes,
            sha256: file.sha256.to_lowercase(),
        })
        .collect();
    Ok(Receipt {
        schema: "R1_QTERMINAL_CANDIDATE_GENERATOR_RECEIPT_V02",
        status: "R1_QTERMINAL_CANDIDATES_READY",
        manifest_sha256: sha256_file(&args.manifest)?,
        sensor_extraction_receipt_sha256: sha256_file(&extraction_receipt_path)?,
        public_tasks_path: public_tasks_path.display().to_string(),
        public_tasks_sha256: public_hash,
        private_tasks_path: args.private_tasks.display().to_string(),
        private_tasks_sha256: sha256_file(&args.private_tasks)?,
        candidate_file: candidate_hash,
        task_count: private_tasks.len(),
        family_counts,
        candidate_counts,
        solution_counts_exact: true,
        validator_agreement_all_candidates: validator_agreement,
        policy_trace_count: trace_hashes.len(),
        policy_trace_expansions: trace_expansions,
        policy_trace_replays_passed: trace_replays_passed,
        policy_config,
        sensor_output_files,
        policy_traces: trace_hashes,
        policy_sidecars: sidecar_hashes,
        output_files: outputs,
        sensor_extraction_outputs_verified: true,
        encoder_forward_performed_by_generator: false,
        selector_training_performed: false,
    })
}

fn verify_manifest(manifest: &Value) -> Result<(), String> {
    if manifest["schema"] != "R1_QTERMINAL_TRAINING_MIXTURE_V02"
        || manifest["policy_trace_source"]["policy_checkpoint_id"] != POLICY_ID
        || manifest["random_assignment_source"]["sampler_id"] != RANDOM_ID
    {
        return Err("mixture manifest does not match this candidate-generator version".to_owned());
    }
    Ok(())
}

fn verify_extraction_outputs(directory: &Path, files: &[ExtractionOutput]) -> Result<(), String> {
    let expected = [
        "constraint_H.float32.npy",
        "global_h.float32.npy",
        "rows.jsonl",
    ];
    let observed: BTreeSet<_> = files.iter().map(|file| file.path.as_str()).collect();
    if observed != expected.into_iter().collect() {
        return Err("extraction output set differs from its frozen schema".to_owned());
    }
    for file in files {
        let path = directory.join(&file.path);
        if !path.is_file() || path.metadata().map_err(display_error)?.len() != file.bytes {
            return Err(format!(
                "extraction output missing or size mismatch: {}",
                file.path
            ));
        }
        if sha256_file(&path)? != file.sha256.to_lowercase() {
            return Err(format!("extraction output hash mismatch: {}", file.path));
        }
    }
    Ok(())
}

fn read_jsonl<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<Vec<T>, String> {
    let file = File::open(path).map_err(display_error)?;
    let mut output = Vec::new();
    for (line_index, line) in BufReader::new(file).lines().enumerate() {
        let line = line.map_err(display_error)?;
        if line.trim().is_empty() {
            continue;
        }
        output.push(serde_json::from_str(&line).map_err(|error| {
            format!(
                "JSONL parse failure at {}:{}: {error}",
                path.display(),
                line_index + 1
            )
        })?);
    }
    Ok(output)
}

fn family_split(family_id: &str, manifest: &Value) -> Result<&'static str, String> {
    let salt = manifest["family_split"]["salt"]
        .as_str()
        .ok_or_else(|| "family split salt is missing".to_owned())?;
    let digest = Sha256::digest(format!("{salt}\0{family_id}").as_bytes());
    let bucket = u64::from_be_bytes(digest[..8].try_into().expect("SHA256 prefix length")) % 10_000;
    for split in ["train", "validation", "test"] {
        let bounds = &manifest["family_split"]["ranges"][split];
        let low = bounds[0]
            .as_u64()
            .ok_or_else(|| "bad split lower bound".to_owned())?;
        let high = bounds[1]
            .as_u64()
            .ok_or_else(|| "bad split upper bound".to_owned())?;
        if (low..=high).contains(&bucket) {
            return Ok(match split {
                "train" => "train",
                "validation" => "validation",
                _ => "test",
            });
        }
    }
    Err(format!(
        "manifest family ranges do not cover bucket {bucket}"
    ))
}

fn sample_valid_assignments(
    task: &Task,
    solutions: &[Vec<u8>],
    feature_id: &str,
    requested: usize,
) -> Result<Vec<(u64, Vec<u8>)>, String> {
    let target = requested.min(solutions.len());
    let mut selected = HashSet::<Vec<u8>>::with_capacity(target);
    let mut samples = Vec::with_capacity(target);
    for replicate in 0..INVALID_DRAW_LIMIT {
        if samples.len() == target {
            break;
        }
        let mut rng = StableRng::new(random_seed(feature_id, replicate));
        let index = rng.bounded(solutions.len() as u64) as usize;
        let assignment = &solutions[index];
        if selected.insert(assignment.clone()) {
            if !validate(task, assignment) || !validate_independent(task, assignment) {
                return Err(format!(
                    "exact solution sampler failed validation for {}",
                    task.id
                ));
            }
            samples.push((replicate, assignment.clone()));
        }
    }
    if samples.len() != target {
        return Err(format!("valid assignment sample shortfall for {}", task.id));
    }
    Ok(samples)
}

fn sample_invalid_assignments(
    task: &Task,
    feature_id: &str,
    requested: usize,
) -> Result<Vec<(u64, Vec<u8>)>, String> {
    // An empty conjunction is true for every complete assignment, so this
    // task has no invalid class to sample. The global mixture handles class
    // support across families and never fabricates an opposite label.
    if task.clauses.is_empty() {
        return Ok(Vec::new());
    }
    let mut selected = HashSet::<Vec<u8>>::with_capacity(requested);
    let mut samples = Vec::with_capacity(requested);
    for replicate in 0..INVALID_DRAW_LIMIT {
        if samples.len() == requested {
            break;
        }
        let mut rng = StableRng::new(random_seed(feature_id, replicate));
        let assignment: Vec<u8> = (0..task.n)
            .map(|_| rng.bounded(u64::from(task.k)) as u8)
            .collect();
        let valid = validate(task, &assignment);
        let independently_valid = validate_independent(task, &assignment);
        if valid != independently_valid {
            return Err(format!(
                "independent validator disagreement for {}",
                task.id
            ));
        }
        if !valid && selected.insert(assignment.clone()) {
            samples.push((replicate, assignment));
        }
    }
    if samples.len() != requested {
        return Err(format!(
            "invalid assignment sample shortfall for {} after {INVALID_DRAW_LIMIT} deterministic attempts",
            task.id
        ));
    }
    Ok(samples)
}

fn push_random_candidate(
    candidates: &mut Vec<CandidateRecord>,
    task: &Task,
    feature_id: &str,
    assignment: Vec<u8>,
    valid: bool,
    replicate: u64,
    counts: &mut BTreeMap<String, usize>,
) {
    candidates.push(CandidateRecord {
        schema: CANDIDATE_SCHEMA,
        sample_id: random_sample_id(&task.id, valid, replicate),
        feature_id: feature_id.to_owned(),
        task_id: task.id.clone(),
        family_id: task.family_id.clone(),
        source_kind: "random_complete",
        assignment,
        posthoc_valid: valid,
        label_source: POSTHOC_LABEL_SOURCE,
        random_sampler_id: Some(RANDOM_ID),
        random_replicate_index: Some(replicate),
        policy_checkpoint_id: None,
        policy_training_split: None,
        policy_trace_id: None,
        trace_event_index: None,
    });
    count_candidate(counts, "random_complete", valid);
}

fn random_sample_id(task_id: &str, valid: bool, replicate: u64) -> String {
    let label_name = if valid { "valid" } else { "invalid" };
    format!("random-{task_id}-{label_name}-{replicate:06}")
}

fn policy_candidate(
    task: &Task,
    feature_id: &str,
    trace_id: String,
    event_index: i64,
    assignment: Vec<u8>,
    valid: bool,
) -> CandidateRecord {
    CandidateRecord {
        schema: CANDIDATE_SCHEMA,
        sample_id: format!("policy-{}-{trace_id}-{event_index}", task.id),
        feature_id: feature_id.to_owned(),
        task_id: task.id.clone(),
        family_id: task.family_id.clone(),
        source_kind: "policy_visited",
        assignment,
        posthoc_valid: valid,
        label_source: POSTHOC_LABEL_SOURCE,
        random_sampler_id: None,
        random_replicate_index: None,
        policy_checkpoint_id: Some(POLICY_ID),
        policy_training_split: Some("train"),
        policy_trace_id: Some(trace_id),
        trace_event_index: Some(event_index),
    }
}

fn count_candidate(counts: &mut BTreeMap<String, usize>, source: &str, valid: bool) {
    let key = format!("{source}:valid={}", u8::from(valid));
    *counts.entry(key).or_default() += 1;
}

fn check_validator_pair(task: &Task, assignment: &[u8]) -> Result<bool, String> {
    let first = validate(task, assignment);
    let second = validate_independent(task, assignment);
    if first != second {
        return Err(format!(
            "independent validator disagreement for {}",
            task.id
        ));
    }
    Ok(second)
}

fn trace_seed(family_id: &str, replicate: u64) -> u64 {
    let digest =
        Sha256::digest(format!("FAS-R1-QTERM-TRACE-V1\0{family_id}\0{replicate}").as_bytes());
    u64::from_be_bytes(digest[..8].try_into().expect("SHA256 prefix length"))
}

fn random_seed(feature_id: &str, replicate: u64) -> u64 {
    let digest =
        Sha256::digest(format!("FAS-R1-QTERM-RANDOM-V1\0{feature_id}\0{replicate}").as_bytes());
    u64::from_be_bytes(digest[..8].try_into().expect("SHA256 prefix length"))
}

#[derive(Clone, Copy)]
struct StableRng {
    state: u64,
}

impl StableRng {
    fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }

    fn bounded(&mut self, bound: u64) -> u64 {
        assert!(bound > 0);
        let threshold = bound.wrapping_neg() % bound;
        loop {
            let value = self.next_u64();
            if value >= threshold {
                return value % bound;
            }
        }
    }
}

fn artifact_hash(path: &Path, root: &Path) -> Result<ArtifactHash, String> {
    let relative = path
        .strip_prefix(root)
        .map_err(|error| format!("artifact path escapes output root: {error}"))?;
    Ok(ArtifactHash {
        path: relative.to_string_lossy().replace('\\', "/"),
        bytes: path.metadata().map_err(display_error)?.len(),
        sha256: sha256_file(path)?,
    })
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(display_error)?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let file = File::create(path).map_err(display_error)?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer_pretty(&mut writer, value).map_err(display_error)?;
    writer.write_all(b"\n").map_err(display_error)?;
    writer.flush().map_err(display_error)
}

fn display_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests;

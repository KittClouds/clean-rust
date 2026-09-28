use std::collections::{BTreeMap, HashSet};
use std::env;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

use r1_world::{validate, validate_independent, Clause, InferenceTask, Task};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

const LABEL_SOURCE: &str = "independent_typed_validator_v1";
const UNASSIGNED: u8 = u8::MAX;
const MAX_SEARCH_NODES_PER_ATTEMPT: u64 = 250_000;

#[derive(Debug)]
struct Args {
    view_dir: PathBuf,
    features_dir: PathBuf,
    output_dir: PathBuf,
    per_class: usize,
}

#[derive(Deserialize)]
struct Roster {
    task_id: String,
    family_id: String,
    paired_world_id: String,
    split: String,
}

#[derive(Deserialize, Serialize)]
struct Candidate {
    schema: &'static str,
    candidate_id: String,
    task_id: String,
    family_id: String,
    split: String,
    source_kind: String,
    assignment: Vec<u8>,
    posthoc_valid: bool,
    label_source: &'static str,
}

#[derive(Serialize)]
struct FilePin {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Serialize)]
struct Receipt {
    schema: &'static str,
    status: &'static str,
    view_receipt_sha256: String,
    private_tasks: FilePin,
    public_tasks: FilePin,
    support_manifest: FilePin,
    features_receipt_sha256: String,
    feature_files: Vec<FilePin>,
    candidate_file: FilePin,
    task_count: usize,
    task_counts_by_split: BTreeMap<String, usize>,
    candidate_counts_by_split_label_source: BTreeMap<String, usize>,
    candidate_counts_by_task: BTreeMap<String, usize>,
    validator_agreement_all_candidates: bool,
    qualification_rows: usize,
    qualification_targets_generated: bool,
    qualification_target_paths_or_hashes_recorded: bool,
    encoder_forward_performed: bool,
    selector_training_performed: bool,
    sampler: &'static str,
    requested_per_class_per_task: usize,
}

#[derive(Serialize)]
struct Failure {
    schema: &'static str,
    status: &'static str,
    error: String,
    qualification_rows: usize,
    qualification_targets_generated: bool,
    qualification_target_paths_or_hashes_recorded: bool,
    encoder_forward_performed: bool,
    selector_training_performed: bool,
}

fn main() {
    let args = match parse_args() {
        Ok(args) => args,
        Err(error) => {
            eprintln!("{error}\nusage: r1_qterminal_v05_candidates --view DIR --features DIR --output NEW_DIR [--per-class N]");
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
                &args.output_dir.join("candidate-receipt-v05-v01.json"),
                &receipt,
            ) {
                eprintln!("cannot write success receipt: {error}");
                std::process::exit(1);
            }
            println!("{}", receipt.status);
        }
        Err(error) => {
            let failure = Failure {
                schema: "R1_QTERMINAL_V05_CANDIDATE_RECEIPT_V01",
                status: "QTERMINAL_V05_CANDIDATES_FAILED",
                error: error.clone(),
                qualification_rows: 0,
                qualification_targets_generated: false,
                qualification_target_paths_or_hashes_recorded: false,
                encoder_forward_performed: false,
                selector_training_performed: false,
            };
            let _ = write_json(
                &args.output_dir.join("candidate-failure-v05-v01.json"),
                &failure,
            );
            eprintln!("candidate generation failed: {error}");
            std::process::exit(1);
        }
    }
}

fn parse_args() -> Result<Args, String> {
    let mut args = env::args().skip(1);
    let mut view_dir = None;
    let mut features_dir = None;
    let mut output_dir = None;
    let mut per_class = 32usize;
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}"))?;
        match flag.as_str() {
            "--view" => view_dir = Some(PathBuf::from(value)),
            "--features" => features_dir = Some(PathBuf::from(value)),
            "--output" => output_dir = Some(PathBuf::from(value)),
            "--per-class" => {
                per_class = value
                    .parse()
                    .map_err(|_| "invalid --per-class".to_owned())?;
                if per_class == 0 || per_class > 256 {
                    return Err("--per-class must be in 1..=256".to_owned());
                }
            }
            _ => return Err(format!("unknown argument: {flag}")),
        }
    }
    Ok(Args {
        view_dir: view_dir.ok_or_else(|| "--view is required".to_owned())?,
        features_dir: features_dir.ok_or_else(|| "--features is required".to_owned())?,
        output_dir: output_dir.ok_or_else(|| "--output is required".to_owned())?,
        per_class,
    })
}

fn execute(args: &Args) -> Result<Receipt, String> {
    let view_receipt_path = args.view_dir.join("trainval-view-receipt-v05-v01.json");
    let view_receipt_bytes = fs::read(&view_receipt_path).map_err(display_error)?;
    let view_receipt: Value = serde_json::from_slice(&view_receipt_bytes).map_err(display_error)?;
    require_eq(
        &view_receipt,
        "schema",
        "R1_STAGE1_TRAIN_VALIDATION_VIEW_RECEIPT_V05_V01",
    )?;
    require_eq(&view_receipt, "status", "TRAIN_VALIDATION_VIEW_COMPLETE")?;
    require_zero(&view_receipt, "qualification_rows_emitted")?;
    require_false(&view_receipt, "qualification_targets_generated")?;
    require_false(
        &view_receipt,
        "qualification_target_paths_or_hashes_recorded",
    )?;

    let private_path = args.view_dir.join("private-tasks-trainval-v05.jsonl");
    let public_path = args.view_dir.join("public-tasks-trainval-v05.jsonl");
    let support_path = args.view_dir.join("stress-support-trainval-v05.json");
    let private_pin = verify_output_pin(
        &private_path,
        &view_receipt["outputs"]["private-tasks-trainval-v05.jsonl"],
    )?;
    let public_pin = verify_output_pin(
        &public_path,
        &view_receipt["outputs"]["public-tasks-trainval-v05.jsonl"],
    )?;
    let support_pin = verify_output_pin(
        &support_path,
        &view_receipt["outputs"]["stress-support-trainval-v05.json"],
    )?;
    let view_receipt_sha = sha256_file(&view_receipt_path)?;

    let feature_receipt_path = args
        .features_dir
        .join("frozen-features-trainval-receipt-v05-v01.json");
    let feature_receipt_bytes = fs::read(&feature_receipt_path).map_err(display_error)?;
    let feature_receipt: Value =
        serde_json::from_slice(&feature_receipt_bytes).map_err(display_error)?;
    require_eq(
        &feature_receipt,
        "schema",
        "R1_STAGE1_FROZEN_FEATURES_TRAINVAL_V05_V01",
    )?;
    require_eq(&feature_receipt, "status", "V05_TRAINVAL_FEATURES_COMPLETE")?;
    require_zero(&feature_receipt, "qualification_rows_emitted")?;
    require_false(&feature_receipt, "qualification_targets_generated")?;
    require_false(
        &feature_receipt,
        "qualification_target_paths_or_hashes_recorded",
    )?;
    if feature_receipt["view_receipt_sha256"].as_str() != Some(view_receipt_sha.as_str()) {
        return Err("feature receipt is not bound to the supplied V241 view receipt".to_owned());
    }
    if feature_receipt["trainval_public_tasks_sha256"].as_str() != Some(public_pin.sha256.as_str())
    {
        return Err("feature receipt public-task hash differs from the V241 view".to_owned());
    }
    let feature_names = [
        "constraint_H_trainval.float32.npy",
        "global_h_trainval.float32.npy",
        "rows_trainval.jsonl",
    ];
    let mut feature_pins = Vec::with_capacity(feature_names.len());
    for name in feature_names {
        let path = args.features_dir.join(name);
        feature_pins.push(verify_output_pin(&path, &feature_receipt["outputs"][name])?);
    }

    let roster: Vec<Roster> = {
        let bytes = fs::read(&support_path).map_err(display_error)?;
        let value: Value = serde_json::from_slice(&bytes).map_err(display_error)?;
        serde_json::from_value(value["family_roster"].clone()).map_err(display_error)?
    };
    let mut split_by_id = BTreeMap::new();
    let mut family_by_id = BTreeMap::new();
    let mut pair_split = BTreeMap::<String, String>::new();
    let mut pair_count = BTreeMap::<String, usize>::new();
    let mut task_counts_by_split = BTreeMap::<String, usize>::new();
    for row in roster {
        if !matches!(row.split.as_str(), "train" | "validation") {
            return Err(format!("unexpected split in V241 roster: {}", row.split));
        }
        if split_by_id
            .insert(row.task_id.clone(), row.split.clone())
            .is_some()
            || family_by_id
                .insert(row.task_id.clone(), row.family_id.clone())
                .is_some()
        {
            return Err("duplicate task ID in V241 family roster".to_owned());
        }
        if let Some(previous) = pair_split.insert(row.paired_world_id.clone(), row.split.clone()) {
            if previous != row.split {
                return Err("paired world variants cross the V241 split boundary".to_owned());
            }
        }
        *pair_count.entry(row.paired_world_id).or_default() += 1;
        *task_counts_by_split.entry(row.split).or_default() += 1;
    }
    if pair_count.values().any(|count| *count != 4) || pair_count.len() != 20 {
        return Err("V241 paired-world roster must contain 20 groups of four variants".to_owned());
    }

    let public_tasks: Vec<InferenceTask> = read_jsonl(&public_path)?;
    let private_tasks: Vec<Task> = read_jsonl(&private_path)?;
    if public_tasks.is_empty()
        || public_tasks.len() != private_tasks.len()
        || public_tasks.len() != split_by_id.len()
    {
        return Err("V241 public/private/roster task counts differ or are empty".to_owned());
    }
    let public_by_id: BTreeMap<_, _> = public_tasks
        .into_iter()
        .map(|task| (task.id.clone(), task))
        .collect();
    if public_by_id.len() != private_tasks.len() {
        return Err("V241 public task IDs are not unique".to_owned());
    }
    let private_ids: HashSet<_> = private_tasks.iter().map(|task| task.id.as_str()).collect();
    if private_ids.len() != private_tasks.len()
        || private_ids.len() != public_by_id.len()
        || private_ids
            .iter()
            .any(|task_id| !public_by_id.contains_key(*task_id))
    {
        return Err("V241 private/public task ID sets differ or private IDs repeat".to_owned());
    }

    let output_path = args.output_dir.join("candidate-records-v05-v01.jsonl");
    let mut writer = BufWriter::new(File::create(&output_path).map_err(display_error)?);
    let mut candidate_counts = BTreeMap::<String, usize>::new();
    let mut candidate_counts_by_task = BTreeMap::<String, usize>::new();
    let mut agreement = true;
    for task in &private_tasks {
        let public = public_by_id
            .get(&task.id)
            .ok_or_else(|| format!("private task {} absent from public V241 roster", task.id))?;
        let split = split_by_id
            .get(&task.id)
            .ok_or_else(|| format!("task {} missing from V241 split roster", task.id))?;
        let family = family_by_id
            .get(&task.id)
            .ok_or_else(|| format!("task {} missing family in V241 roster", task.id))?;
        if &task.family_id != family
            || &public.family_id != family
            || task.n != public.n
            || task.k != public.k
            || task.clauses.len() != public.clauses.len()
        {
            return Err(format!(
                "public/private/roster identity mismatch for {}",
                task.id
            ));
        }
        if task.n != 20 || task.k != 3 || task.clauses.len() > 512 {
            return Err(format!("V05 QTerminal support exceeded by {}", task.id));
        }
        let seed = stable_seed(&task.id);
        let positives = sample_valid_solutions(task, args.per_class, seed)?;
        if positives.is_empty() {
            return Err(format!("no valid assignments sampled for {}", task.id));
        }
        let negatives = sample_invalid_assignments(
            task,
            &positives,
            positives.len(),
            seed ^ 0xa076_1d64_78bd_642f,
        )?;
        if negatives.len() != positives.len() {
            return Err(format!(
                "could not balance candidate classes for {}",
                task.id
            ));
        }

        for (index, assignment) in positives.iter().enumerate() {
            let valid = validator_pair(task, assignment)?;
            agreement &= valid;
            let record = Candidate {
                schema: "R1_QTERMINAL_V05_CANDIDATE_V01",
                candidate_id: format!("{}-positive-{index:04}", task.id),
                task_id: task.id.clone(),
                family_id: family.clone(),
                split: split.clone(),
                source_kind: "randomized_backtracking_solution".to_owned(),
                assignment: assignment.clone(),
                posthoc_valid: valid,
                label_source: LABEL_SOURCE,
            };
            write_json_line(&mut writer, &record)?;
            count_candidate(
                &mut candidate_counts,
                split,
                true,
                "randomized_backtracking_solution",
            );
            *candidate_counts_by_task.entry(task.id.clone()).or_default() += 1;
        }
        for (index, (assignment, source)) in negatives.iter().enumerate() {
            let valid = validator_pair(task, assignment)?;
            agreement &= !valid;
            let record = Candidate {
                schema: "R1_QTERMINAL_V05_CANDIDATE_V01",
                candidate_id: format!("{}-negative-{index:04}", task.id),
                task_id: task.id.clone(),
                family_id: family.clone(),
                split: split.clone(),
                source_kind: (*source).to_owned(),
                assignment: assignment.clone(),
                posthoc_valid: valid,
                label_source: LABEL_SOURCE,
            };
            write_json_line(&mut writer, &record)?;
            count_candidate(&mut candidate_counts, split, false, source);
            *candidate_counts_by_task.entry(task.id.clone()).or_default() += 1;
        }
    }
    writer.flush().map_err(display_error)?;
    if !agreement {
        return Err("candidate labels disagree with the independent typed validator".to_owned());
    }
    if task_counts_by_split.get("train") != Some(&64)
        || task_counts_by_split.get("validation") != Some(&16)
    {
        return Err(
            "V241 roster does not contain the expected 64/16 train/validation tasks".to_owned(),
        );
    }
    let candidate_pin = pin_file(&output_path)?;
    Ok(Receipt {
        schema: "R1_QTERMINAL_V05_CANDIDATE_RECEIPT_V01",
        status: "QTERMINAL_V05_CANDIDATES_COMPLETE",
        view_receipt_sha256: view_receipt_sha,
        private_tasks: private_pin,
        public_tasks: public_pin,
        support_manifest: support_pin,
        features_receipt_sha256: sha256_bytes(&feature_receipt_bytes),
        feature_files: feature_pins,
        candidate_file: candidate_pin,
        task_count: private_tasks.len(),
        task_counts_by_split,
        candidate_counts_by_split_label_source: candidate_counts,
        candidate_counts_by_task,
        validator_agreement_all_candidates: true,
        qualification_rows: 0,
        qualification_targets_generated: false,
        qualification_target_paths_or_hashes_recorded: false,
        encoder_forward_performed: false,
        selector_training_performed: false,
        sampler: "randomized_constraint_guided_backtracking_with_unique_solution_assignments_and_balanced_near_miss_uniform_invalid_negatives",
        requested_per_class_per_task: args.per_class,
    })
}

fn sample_valid_solutions(
    task: &Task,
    requested: usize,
    seed: u64,
) -> Result<Vec<Vec<u8>>, String> {
    let mut degree = vec![0usize; usize::from(task.n)];
    for clause in &task.clauses {
        match clause {
            Clause::Same { a, b } | Clause::Different { a, b } => {
                degree[usize::from(*a)] += 1;
                degree[usize::from(*b)] += 1;
            }
            Clause::FixedRole { entity, .. } | Clause::ForbiddenRole { entity, .. } => {
                degree[usize::from(*entity)] += 1
            }
            Clause::ExactlyOneRole { entities, .. } => {
                for entity in entities {
                    degree[usize::from(*entity)] += 1;
                }
            }
            Clause::ImpliesNotRole {
                if_entity,
                then_entity,
                ..
            } => {
                degree[usize::from(*if_entity)] += 1;
                degree[usize::from(*then_entity)] += 1;
            }
        }
    }
    let mut order: Vec<usize> = (0..usize::from(task.n)).collect();
    order.sort_by_key(|entity| (std::cmp::Reverse(degree[*entity]), *entity));
    let mut rng = StableRng::new(seed);
    let mut seen = HashSet::<Vec<u8>>::with_capacity(requested);
    let mut unique = Vec::<Vec<u8>>::with_capacity(requested);
    let max_attempts = requested.saturating_mul(256).max(512);
    for _ in 0..max_attempts {
        if unique.len() >= requested {
            break;
        }
        let mut assignment = vec![UNASSIGNED; usize::from(task.n)];
        let mut nodes = 0u64;
        if solve_one(task, &order, 0, &mut assignment, &mut rng, &mut nodes)
            && validate(task, &assignment)
            && validate_independent(task, &assignment)
        {
            if seen.insert(assignment.clone()) {
                unique.push(assignment);
            }
        }
    }
    Ok(unique)
}

fn solve_one(
    task: &Task,
    order: &[usize],
    depth: usize,
    state: &mut [u8],
    rng: &mut StableRng,
    nodes: &mut u64,
) -> bool {
    *nodes += 1;
    if *nodes > MAX_SEARCH_NODES_PER_ATTEMPT {
        return false;
    }
    if depth == order.len() {
        return true;
    }
    let entity = order[depth];
    let mut roles: Vec<u8> = (0..task.k).collect();
    rng.shuffle(&mut roles);
    for role in roles {
        state[entity] = role;
        if partial_constraints_hold(task, state)
            && solve_one(task, order, depth + 1, state, rng, nodes)
        {
            return true;
        }
    }
    state[entity] = UNASSIGNED;
    false
}

fn partial_constraints_hold(task: &Task, state: &[u8]) -> bool {
    task.clauses.iter().all(|clause| match clause {
        Clause::Same { a, b } => {
            state[usize::from(*a)] == UNASSIGNED
                || state[usize::from(*b)] == UNASSIGNED
                || state[usize::from(*a)] == state[usize::from(*b)]
        }
        Clause::Different { a, b } => {
            state[usize::from(*a)] == UNASSIGNED
                || state[usize::from(*b)] == UNASSIGNED
                || state[usize::from(*a)] != state[usize::from(*b)]
        }
        Clause::FixedRole { entity, role } => {
            state[usize::from(*entity)] == UNASSIGNED || state[usize::from(*entity)] == *role
        }
        Clause::ForbiddenRole { entity, role } => {
            state[usize::from(*entity)] == UNASSIGNED || state[usize::from(*entity)] != *role
        }
        Clause::ExactlyOneRole { entities, role } => {
            let mut seen = 0usize;
            let mut remaining = 0usize;
            for entity in entities {
                match state[usize::from(*entity)] {
                    UNASSIGNED => remaining += 1,
                    value if value == *role => seen += 1,
                    _ => {}
                }
            }
            seen <= 1 && seen + remaining >= 1
        }
        Clause::ImpliesNotRole {
            if_entity,
            if_role,
            then_entity,
            then_role,
        } => {
            let antecedent = state[usize::from(*if_entity)];
            let consequent = state[usize::from(*then_entity)];
            antecedent == UNASSIGNED
                || antecedent != *if_role
                || consequent == UNASSIGNED
                || consequent != *then_role
        }
    })
}

fn sample_invalid_assignments(
    task: &Task,
    positives: &[Vec<u8>],
    requested: usize,
    seed: u64,
) -> Result<Vec<(Vec<u8>, &'static str)>, String> {
    let mut rng = StableRng::new(seed);
    let mut selected = HashSet::<Vec<u8>>::with_capacity(requested);
    let mut output = Vec::with_capacity(requested);
    let near_target = requested / 2;
    let mut attempt = 0usize;
    while output.len() < near_target && attempt < requested.saturating_mul(256).max(512) {
        let base = &positives[attempt % positives.len()];
        let entity = rng.bounded(task.n as u64) as usize;
        let mut assignment = base.clone();
        let old = assignment[entity];
        let mut role = rng.bounded(task.k as u64) as u8;
        if role == old {
            role = (role + 1) % task.k;
        }
        assignment[entity] = role;
        if !validate(task, &assignment)
            && !validate_independent(task, &assignment)
            && selected.insert(assignment.clone())
        {
            output.push((assignment, "near_miss_invalid"));
        }
        attempt += 1;
    }
    let mut draw = 0u64;
    while output.len() < requested && draw < 1_000_000 {
        let mut assignment = Vec::with_capacity(usize::from(task.n));
        for _ in 0..task.n {
            assignment.push(rng.bounded(task.k as u64) as u8);
        }
        if !validate(task, &assignment)
            && !validate_independent(task, &assignment)
            && selected.insert(assignment.clone())
        {
            output.push((assignment, "uniform_invalid"));
        }
        draw += 1;
    }
    if output.len() != requested {
        return Err(format!(
            "invalid candidate sampling shortfall for {}",
            task.id
        ));
    }
    Ok(output)
}

fn validator_pair(task: &Task, assignment: &[u8]) -> Result<bool, String> {
    let fast = validate(task, assignment);
    let independent = validate_independent(task, assignment);
    if fast != independent {
        return Err(format!("validator disagreement for {}", task.id));
    }
    Ok(independent)
}

fn count_candidate(counts: &mut BTreeMap<String, usize>, split: &str, valid: bool, source: &str) {
    *counts
        .entry(format!("{split}:valid={}:source={source}", u8::from(valid)))
        .or_default() += 1;
}

fn verify_output_pin(path: &Path, record: &Value) -> Result<FilePin, String> {
    let expected_bytes = record["bytes"]
        .as_u64()
        .ok_or_else(|| format!("missing byte count for {}", path.display()))?;
    let expected_hash = record["sha256"]
        .as_str()
        .ok_or_else(|| format!("missing hash for {}", path.display()))?
        .to_lowercase();
    let pin = pin_file(path)?;
    if pin.bytes != expected_bytes || pin.sha256 != expected_hash {
        return Err(format!("input does not match receipt: {}", path.display()));
    }
    Ok(pin)
}

fn pin_file(path: &Path) -> Result<FilePin, String> {
    let metadata = fs::metadata(path).map_err(display_error)?;
    Ok(FilePin {
        path: path.to_string_lossy().into_owned(),
        bytes: metadata.len(),
        sha256: sha256_file(path)?,
    })
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let file = File::open(path).map_err(display_error)?;
    let mut reader = BufReader::new(file);
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let count = std::io::Read::read(&mut reader, &mut buffer).map_err(display_error)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(hex(&hasher.finalize()))
}

fn sha256_bytes(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}
fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as FmtWrite;
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}
fn stable_seed(value: &str) -> u64 {
    let hash = Sha256::digest(value.as_bytes());
    u64::from_be_bytes(hash[..8].try_into().expect("digest prefix"))
}

fn require_eq(value: &Value, field: &str, expected: &str) -> Result<(), String> {
    if value[field].as_str() != Some(expected) {
        return Err(format!("unexpected receipt field {field}"));
    }
    Ok(())
}
fn require_zero(value: &Value, field: &str) -> Result<(), String> {
    if value[field].as_u64() != Some(0) {
        return Err(format!("receipt field {field} must be zero"));
    }
    Ok(())
}
fn require_false(value: &Value, field: &str) -> Result<(), String> {
    if value[field].as_bool() != Some(false) {
        return Err(format!("receipt field {field} must be false"));
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
        output.push(
            serde_json::from_str(&line)
                .map_err(|error| format!("{} line {}: {error}", path.display(), line_index + 1))?,
        );
    }
    Ok(output)
}

fn write_json_line<T: Serialize>(writer: &mut BufWriter<File>, value: &T) -> Result<(), String> {
    serde_json::to_writer(&mut *writer, value).map_err(display_error)?;
    writer.write_all(b"\n").map_err(display_error)
}

fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let file = File::create(path).map_err(display_error)?;
    serde_json::to_writer_pretty(file, value).map_err(display_error)
}
fn display_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

struct StableRng {
    state: u64,
}
impl StableRng {
    fn new(seed: u64) -> Self {
        Self {
            state: seed ^ 0x9e37_79b9_7f4a_7c15,
        }
    }
    fn next(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }
    fn bounded(&mut self, upper: u64) -> u64 {
        if upper == 0 {
            0
        } else {
            self.next() % upper
        }
    }
    fn shuffle<T>(&mut self, values: &mut [T]) {
        for index in (1..values.len()).rev() {
            let other = self.bounded((index + 1) as u64) as usize;
            values.swap(index, other);
        }
    }
}

#[cfg(test)]
#[path = "r1_qterminal_v05_candidates/tests.rs"]
mod tests;

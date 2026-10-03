use std::collections::BTreeMap;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use hashbrown::{HashMap, HashSet};
use r1_world::{validate, validate_independent, Clause, InferenceTask, Task};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

const LABEL_SOURCE: &str = "independent_typed_validator_v1";

#[derive(Debug)]
struct Args {
    view_dir: PathBuf,
    features_dir: PathBuf,
    source_candidates_dir: PathBuf,
    output_dir: PathBuf,
}

#[derive(Deserialize)]
struct RosterRow {
    task_id: String,
    family_id: String,
    split: String,
}

#[derive(Deserialize)]
struct CandidateV01 {
    schema: String,
    candidate_id: String,
    task_id: String,
    family_id: String,
    split: String,
    source_kind: String,
    assignment: Vec<u8>,
    posthoc_valid: bool,
    label_source: String,
}

#[derive(Serialize)]
struct CandidateV02 {
    schema: &'static str,
    candidate_id: String,
    task_id: String,
    family_id: String,
    split: String,
    source_kind: String,
    assignment: Vec<u8>,
    posthoc_valid: bool,
    clause_satisfied: Vec<bool>,
    label_source: &'static str,
}

#[derive(Clone, Debug, Serialize)]
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
    source_candidate_receipt: FilePin,
    source_candidate_file: FilePin,
    candidate_file: FilePin,
    generator_source: FilePin,
    generator_binary: FilePin,
    task_count: usize,
    task_counts_by_split: BTreeMap<String, usize>,
    candidate_counts_by_split_label_source: BTreeMap<String, usize>,
    candidate_counts_by_task: BTreeMap<String, usize>,
    candidate_counts_by_task_label: BTreeMap<String, usize>,
    candidate_count: usize,
    requested_per_class_per_task: usize,
    validator_agreement_all_candidates: bool,
    public_private_pair_multiset_match_all_tasks: bool,
    clause_targets_match_validity_all_candidates: bool,
    supported_semantics: &'static str,
    assignments_preserved_from_v01: bool,
    inherited_sampler: String,
    sampler_uniformity_claimed: bool,
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
            eprintln!("{error}\nusage: r1_qterminal_v05_candidates_v02 --view DIR --features DIR --source-candidates DIR --output NEW_DIR");
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
            let path = args.output_dir.join("candidate-receipt-v05-v02.json");
            if let Err(error) = write_json(&path, &receipt) {
                eprintln!("cannot write success receipt: {error}");
                std::process::exit(1);
            }
            println!("{}", receipt.status);
        }
        Err(error) => {
            let path = args.output_dir.join("candidate-failure-v05-v02.json");
            let failure = serde_json::json!({
                "schema": "R1_QTERMINAL_V05_CANDIDATE_RECEIPT_V02",
                "status": "QTERMINAL_V05_CANDIDATES_FAILED",
                "error": error,
                "qualification_rows": 0,
                "qualification_targets_generated": false,
                "qualification_target_paths_or_hashes_recorded": false,
                "encoder_forward_performed": false,
                "selector_training_performed": false
            });
            let _ = write_json(&path, &failure);
            eprintln!("candidate augmentation failed: {error}");
            std::process::exit(1);
        }
    }
}

fn parse_args() -> Result<Args, String> {
    let mut values = HashMap::<String, PathBuf>::new();
    let mut args = env::args().skip(1);
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}"))?;
        if !matches!(
            flag.as_str(),
            "--view" | "--features" | "--source-candidates" | "--output"
        ) {
            return Err(format!("unknown argument: {flag}"));
        }
        if values.insert(flag.clone(), PathBuf::from(value)).is_some() {
            return Err(format!("duplicate argument: {flag}"));
        }
    }
    let take = |values: &mut HashMap<String, PathBuf>, key: &str| {
        values
            .remove(key)
            .ok_or_else(|| format!("{key} is required"))
    };
    Ok(Args {
        view_dir: take(&mut values, "--view")?,
        features_dir: take(&mut values, "--features")?,
        source_candidates_dir: take(&mut values, "--source-candidates")?,
        output_dir: take(&mut values, "--output")?,
    })
}

fn execute(args: &Args) -> Result<Receipt, String> {
    let view_receipt_path = args.view_dir.join("trainval-view-receipt-v05-v01.json");
    let view_receipt: Value = read_json(&view_receipt_path)?;
    require_eq(
        &view_receipt,
        "schema",
        "R1_STAGE1_TRAIN_VALIDATION_VIEW_RECEIPT_V05_V01",
    )?;
    require_eq(&view_receipt, "status", "TRAIN_VALIDATION_VIEW_COMPLETE")?;
    require_no_qualification(&view_receipt, "qualification_rows_emitted")?;

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
    let view_hash = sha256_file(&view_receipt_path)?;

    let feature_receipt_path = args
        .features_dir
        .join("frozen-features-trainval-receipt-v05-v01.json");
    let feature_receipt: Value = read_json(&feature_receipt_path)?;
    require_eq(
        &feature_receipt,
        "schema",
        "R1_STAGE1_FROZEN_FEATURES_TRAINVAL_V05_V01",
    )?;
    require_eq(&feature_receipt, "status", "V05_TRAINVAL_FEATURES_COMPLETE")?;
    require_no_qualification(&feature_receipt, "qualification_rows_emitted")?;
    if feature_receipt["view_receipt_sha256"].as_str() != Some(&view_hash) {
        return Err("V246 feature receipt is not bound to the supplied V241 receipt".to_owned());
    }
    if feature_receipt["trainval_public_tasks_sha256"].as_str() != Some(&public_pin.sha256) {
        return Err("V246 feature receipt public-task hash differs from V241".to_owned());
    }
    let feature_names = [
        "constraint_H_trainval.float32.npy",
        "global_h_trainval.float32.npy",
        "rows_trainval.jsonl",
    ];
    let feature_files = feature_names
        .iter()
        .map(|name| {
            verify_output_pin(
                &args.features_dir.join(name),
                &feature_receipt["outputs"][*name],
            )
        })
        .collect::<Result<Vec<_>, _>>()?;

    let source_receipt_path = args
        .source_candidates_dir
        .join("candidate-receipt-v05-v01.json");
    let source_receipt: Value = read_json(&source_receipt_path)?;
    require_eq(
        &source_receipt,
        "schema",
        "R1_QTERMINAL_V05_CANDIDATE_RECEIPT_V01",
    )?;
    require_eq(
        &source_receipt,
        "status",
        "QTERMINAL_V05_CANDIDATES_COMPLETE",
    )?;
    require_no_qualification(&source_receipt, "qualification_rows")?;
    if source_receipt["validator_agreement_all_candidates"].as_bool() != Some(true) {
        return Err("V01 candidate receipt does not attest dual-validator agreement".to_owned());
    }
    if source_receipt["view_receipt_sha256"].as_str() != Some(&view_hash)
        || source_receipt["features_receipt_sha256"].as_str()
            != Some(sha256_file(&feature_receipt_path)?.as_str())
    {
        return Err(
            "V01 candidate receipt is not bound to the supplied V241/V246 inputs".to_owned(),
        );
    }
    require_matching_pin(
        &source_receipt["private_tasks"],
        &private_pin,
        "V241 private tasks",
    )?;
    require_matching_pin(
        &source_receipt["public_tasks"],
        &public_pin,
        "V241 public tasks",
    )?;
    require_matching_pin(
        &source_receipt["support_manifest"],
        &support_pin,
        "V241 support manifest",
    )?;
    verify_receipt_feature_pins(&source_receipt["feature_files"], &feature_files)?;

    let source_candidate_path = args
        .source_candidates_dir
        .join("candidate-records-v05-v01.jsonl");
    let source_candidate_pin =
        verify_output_pin(&source_candidate_path, &source_receipt["candidate_file"])?;
    let source_receipt_pin = pin_file(&source_receipt_path)?;
    let roster_value: Value = read_json(&support_path)?;
    let roster_rows: Vec<RosterRow> =
        serde_json::from_value(roster_value["family_roster"].clone()).map_err(display_error)?;
    let roster = make_roster(roster_rows)?;
    if roster.len() != 80
        || roster.values().filter(|row| row.1 == "train").count() != 64
        || roster.values().filter(|row| row.1 == "validation").count() != 16
    {
        return Err("V241 train/validation roster differs from the fixed 64/16 view".to_owned());
    }

    let public_tasks: Vec<InferenceTask> = read_jsonl(&public_path)?;
    let private_tasks: Vec<Task> = read_jsonl(&private_path)?;
    if public_tasks.len() != 80 || private_tasks.len() != 80 {
        return Err("V241 must contain exactly 80 public/private tasks".to_owned());
    }
    let public_by_id = public_tasks
        .into_iter()
        .map(|task| (task.id.clone(), task))
        .collect::<HashMap<_, _>>();
    let private_by_id = private_tasks
        .into_iter()
        .map(|task| (task.id.clone(), task))
        .collect::<HashMap<_, _>>();
    if public_by_id.len() != 80
        || private_by_id.len() != 80
        || public_by_id.len() != private_by_id.len()
    {
        return Err("V241 public/private task IDs are not unique and aligned".to_owned());
    }
    let mut edge_pairs = HashMap::<String, Vec<(u16, u16)>>::with_capacity(80);
    for (task_id, (family_id, split)) in &roster {
        let public = public_by_id
            .get(task_id)
            .ok_or_else(|| format!("public task {task_id} absent from V241"))?;
        let private = private_by_id
            .get(task_id)
            .ok_or_else(|| format!("private task {task_id} absent from V241"))?;
        if public.family_id != *family_id
            || private.family_id != *family_id
            || public.n != private.n
            || public.k != private.k
        {
            return Err(format!(
                "V241 identity/shape mismatch for {task_id} ({split})"
            ));
        }
        edge_pairs.insert(
            task_id.clone(),
            public_private_edges_match(private, public)?,
        );
    }

    let source_rows: Vec<CandidateV01> = read_jsonl(&source_candidate_path)?;
    let mut candidate_ids = HashSet::with_capacity(source_rows.len());
    let mut assignments_by_task = HashMap::<String, HashSet<Vec<u8>>>::with_capacity(80);
    let mut candidate_counts_by_split_label_source = BTreeMap::new();
    let mut candidate_counts_by_task = BTreeMap::new();
    let mut candidate_counts_by_task_label = BTreeMap::new();
    let mut converted = Vec::with_capacity(source_rows.len());
    for row in source_rows {
        if row.schema != "R1_QTERMINAL_V05_CANDIDATE_V01" || row.label_source != LABEL_SOURCE {
            return Err("source candidate row schema/label provenance mismatch".to_owned());
        }
        if row.candidate_id.is_empty() || !candidate_ids.insert(row.candidate_id.clone()) {
            return Err("source candidate IDs must be nonempty and unique".to_owned());
        }
        let (family_id, split) = roster
            .get(&row.task_id)
            .ok_or_else(|| format!("candidate task {} is outside V241", row.task_id))?;
        if row.family_id != *family_id || row.split != *split {
            return Err(format!(
                "candidate family/split mismatch for {}",
                row.task_id
            ));
        }
        let private = private_by_id
            .get(&row.task_id)
            .expect("roster and private IDs checked");
        if row.assignment.len() != usize::from(private.n)
            || row.assignment.iter().any(|role| *role >= private.k)
        {
            return Err(format!(
                "candidate assignment shape/range mismatch for {}",
                row.task_id
            ));
        }
        if !assignments_by_task
            .entry(row.task_id.clone())
            .or_default()
            .insert(row.assignment.clone())
        {
            return Err(format!(
                "duplicate assignment candidate for {}",
                row.task_id
            ));
        }
        let typed_valid = validate(private, &row.assignment);
        let independent_valid = validate_independent(private, &row.assignment);
        if typed_valid != independent_valid || row.posthoc_valid != independent_valid {
            return Err(format!(
                "source candidate label disagrees with dual validators for {}",
                row.task_id
            ));
        }
        let clause_satisfied = edge_pairs[&row.task_id]
            .iter()
            .map(|(a, b)| row.assignment[usize::from(*a)] != row.assignment[usize::from(*b)])
            .collect::<Vec<_>>();
        if clause_satisfied.iter().all(|value| *value) != row.posthoc_valid {
            return Err(format!(
                "clause targets do not conjoin to validity for {}",
                row.task_id
            ));
        }
        let count_key = format!(
            "{}:valid={}:source={}",
            row.split,
            u8::from(row.posthoc_valid),
            row.source_kind
        );
        *candidate_counts_by_split_label_source
            .entry(count_key)
            .or_insert(0) += 1;
        *candidate_counts_by_task
            .entry(row.task_id.clone())
            .or_insert(0) += 1;
        *candidate_counts_by_task_label
            .entry(format!(
                "{}:valid={}",
                row.task_id,
                u8::from(row.posthoc_valid)
            ))
            .or_insert(0) += 1;
        converted.push(CandidateV02 {
            schema: "R1_QTERMINAL_V05_CANDIDATE_V02",
            candidate_id: row.candidate_id,
            task_id: row.task_id,
            family_id: row.family_id,
            split: row.split,
            source_kind: row.source_kind,
            assignment: row.assignment,
            posthoc_valid: row.posthoc_valid,
            clause_satisfied,
            label_source: LABEL_SOURCE,
        });
    }
    if converted.len() != 5_120 || assignments_by_task.len() != 80 {
        return Err("V01 source must provide 64 candidates for each of 80 tasks".to_owned());
    }
    for task_id in roster.keys() {
        if assignments_by_task.get(task_id).map(HashSet::len) != Some(64)
            || candidate_counts_by_task.get(task_id) != Some(&64)
            || candidate_counts_by_task_label.get(&format!("{task_id}:valid=0")) != Some(&32)
            || candidate_counts_by_task_label.get(&format!("{task_id}:valid=1")) != Some(&32)
        {
            return Err(format!("candidate count for {task_id} is not 64"));
        }
    }
    let source_candidate_counts = source_receipt["candidate_counts_by_split_label_source"]
        .as_object()
        .ok_or_else(|| "V01 receipt lacks candidate source counts".to_owned())?;
    for (key, count) in source_candidate_counts {
        if candidate_counts_by_split_label_source.get(key)
            != count.as_u64().map(|value| value as usize).as_ref()
        {
            return Err(format!("V01 candidate count differs for {key}"));
        }
    }

    let output_path = args.output_dir.join("candidate-records-v05-v02.jsonl");
    let temp_path = args.output_dir.join("candidate-records-v05-v02.jsonl.tmp");
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)
        .map_err(display_error)?;
    let mut writer = BufWriter::new(file);
    for candidate in &converted {
        serde_json::to_writer(&mut writer, candidate).map_err(display_error)?;
        writer.write_all(b"\n").map_err(display_error)?;
    }
    writer.flush().map_err(display_error)?;
    writer.get_ref().sync_all().map_err(display_error)?;
    drop(writer);
    fs::rename(&temp_path, &output_path).map_err(display_error)?;

    let candidate_pin = pin_file(&output_path)?;
    let manifest_source =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("src/bin/r1_qterminal_v05_candidates_v02.rs");
    let generator_source = pin_file(&manifest_source)?;
    let generator_binary = pin_file(&env::current_exe().map_err(display_error)?)?;
    Ok(Receipt {
        schema: "R1_QTERMINAL_V05_CANDIDATE_RECEIPT_V02",
        status: "QTERMINAL_V05_CANDIDATES_COMPLETE",
        view_receipt_sha256: view_hash,
        private_tasks: private_pin,
        public_tasks: public_pin,
        support_manifest: support_pin,
        features_receipt_sha256: sha256_file(&feature_receipt_path)?,
        feature_files,
        source_candidate_receipt: source_receipt_pin,
        source_candidate_file: source_candidate_pin,
        candidate_file: candidate_pin,
        generator_source,
        generator_binary,
        task_count: roster.len(),
        task_counts_by_split: BTreeMap::from([
            (String::from("train"), 64),
            (String::from("validation"), 16),
        ]),
        candidate_counts_by_split_label_source,
        candidate_counts_by_task,
        candidate_counts_by_task_label,
        candidate_count: converted.len(),
        requested_per_class_per_task: 32,
        validator_agreement_all_candidates: true,
        public_private_pair_multiset_match_all_tasks: true,
        clause_targets_match_validity_all_candidates: true,
        supported_semantics:
            "all-different binary entity constraints with one of two pinned rendered templates",
        assignments_preserved_from_v01: true,
        inherited_sampler: source_receipt["sampler"]
            .as_str()
            .unwrap_or("unknown_v01_sampler")
            .to_owned(),
        sampler_uniformity_claimed: false,
        qualification_rows: 0,
        qualification_targets_generated: false,
        qualification_target_paths_or_hashes_recorded: false,
        encoder_forward_performed: false,
        selector_training_performed: false,
    })
}

fn make_roster(rows: Vec<RosterRow>) -> Result<HashMap<String, (String, String)>, String> {
    let mut roster = HashMap::with_capacity(rows.len());
    for row in rows {
        if !matches!(row.split.as_str(), "train" | "validation")
            || roster
                .insert(row.task_id, (row.family_id, row.split))
                .is_some()
        {
            return Err("V241 roster has a duplicate ID or non-train/validation split".to_owned());
        }
    }
    Ok(roster)
}

fn public_private_edges_match(
    task: &Task,
    public: &InferenceTask,
) -> Result<Vec<(u16, u16)>, String> {
    if task.clauses.len() != public.clauses.len()
        || public.clauses.len() != public.entity_mentions.len()
        || public.clauses.len() != public.role_mentions.len()
    {
        return Err(format!(
            "clause/text/mention lengths differ for {}",
            task.id
        ));
    }
    let mut typed_edges = Vec::with_capacity(task.clauses.len());
    for clause in &task.clauses {
        let Clause::Different { a, b } = clause else {
            return Err(format!("unsupported private clause type for {}", task.id));
        };
        typed_edges.push(canonical_pair(*a, *b));
    }
    let mut public_edges = Vec::with_capacity(public.clauses.len());
    for (index, text) in public.clauses.iter().enumerate() {
        let mentions = &public.entity_mentions[index];
        if mentions.len() != 2
            || mentions[0] == mentions[1]
            || !public.role_mentions[index].is_empty()
        {
            return Err(format!(
                "unsupported public mention shape for {} clause {index}",
                task.id
            ));
        }
        let text = text.to_ascii_lowercase();
        let supported = text.ends_with("must have different roles")
            || (text.starts_with("do not assign ") && text.ends_with("to the same role"));
        if !supported {
            return Err(format!(
                "unsupported public different-clause wording for {} clause {index}",
                task.id
            ));
        }
        public_edges.push(canonical_pair(mentions[0], mentions[1]));
    }
    typed_edges.sort_unstable();
    let mut public_sorted = public_edges.clone();
    public_sorted.sort_unstable();
    if typed_edges != public_sorted {
        return Err(format!(
            "public/private edge multiset mismatch for {}",
            task.id
        ));
    }
    Ok(public_edges)
}

fn canonical_pair(a: u16, b: u16) -> (u16, u16) {
    if a <= b {
        (a, b)
    } else {
        (b, a)
    }
}

fn verify_receipt_feature_pins(receipt_pins: &Value, actual: &[FilePin]) -> Result<(), String> {
    let rows = receipt_pins
        .as_array()
        .ok_or_else(|| "V01 candidate receipt feature_files is not an array".to_owned())?;
    if rows.len() != actual.len() {
        return Err("V01 candidate receipt feature pin count differs from V246".to_owned());
    }
    let expected = actual
        .iter()
        .map(|pin| {
            (
                Path::new(&pin.path)
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .to_string(),
                pin,
            )
        })
        .collect::<HashMap<_, _>>();
    for row in rows {
        let path = row["path"]
            .as_str()
            .ok_or_else(|| "feature pin lacks path".to_owned())?;
        let name = Path::new(path)
            .file_name()
            .unwrap()
            .to_string_lossy()
            .to_string();
        let actual_pin = expected
            .get(&name)
            .ok_or_else(|| format!("unexpected feature pin {name}"))?;
        require_matching_pin(row, actual_pin, &format!("V246 {name}"))?;
    }
    Ok(())
}

fn require_matching_pin(receipt_pin: &Value, actual: &FilePin, name: &str) -> Result<(), String> {
    if receipt_pin["bytes"].as_u64() != Some(actual.bytes)
        || receipt_pin["sha256"].as_str().map(str::to_ascii_lowercase)
            != Some(actual.sha256.clone())
    {
        return Err(format!(
            "candidate receipt {name} pin differs from supplied input"
        ));
    }
    Ok(())
}

fn verify_output_pin(path: &Path, record: &Value) -> Result<FilePin, String> {
    let expected_bytes = record["bytes"]
        .as_u64()
        .ok_or_else(|| format!("missing byte count for {}", path.display()))?;
    let expected_hash = record["sha256"]
        .as_str()
        .ok_or_else(|| format!("missing hash for {}", path.display()))?
        .to_ascii_lowercase();
    let pin = pin_file(path)?;
    if pin.bytes != expected_bytes || pin.sha256 != expected_hash {
        return Err(format!("input does not match receipt: {}", path.display()));
    }
    Ok(pin)
}

fn pin_file(path: &Path) -> Result<FilePin, String> {
    Ok(FilePin {
        path: path.to_string_lossy().into_owned(),
        bytes: fs::metadata(path).map_err(display_error)?.len(),
        sha256: sha256_file(path)?,
    })
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut reader = BufReader::new(File::open(path).map_err(display_error)?);
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let count = reader.read(&mut buffer).map_err(display_error)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(hex(&hasher.finalize()))
}

fn read_json(path: &Path) -> Result<Value, String> {
    serde_json::from_slice(&fs::read(path).map_err(display_error)?).map_err(display_error)
}

fn read_jsonl<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<Vec<T>, String> {
    let mut output = Vec::new();
    for (line_index, line) in BufReader::new(File::open(path).map_err(display_error)?)
        .lines()
        .enumerate()
    {
        let line = line.map_err(display_error)?;
        if !line.trim().is_empty() {
            output.push(
                serde_json::from_str(&line).map_err(|error| {
                    format!("{} line {}: {error}", path.display(), line_index + 1)
                })?,
            );
        }
    }
    Ok(output)
}

fn require_eq(value: &Value, field: &str, expected: &str) -> Result<(), String> {
    if value[field].as_str() != Some(expected) {
        return Err(format!("unexpected receipt field {field}"));
    }
    Ok(())
}

fn require_no_qualification(value: &Value, rows_field: &str) -> Result<(), String> {
    if value[rows_field].as_u64() != Some(0)
        || value["qualification_targets_generated"].as_bool() != Some(false)
        || value["qualification_target_paths_or_hashes_recorded"].as_bool() != Some(false)
    {
        return Err("input receipt violates the train/validation-only boundary".to_owned());
    }
    Ok(())
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let mut file = File::create(path).map_err(display_error)?;
    serde_json::to_writer_pretty(&mut file, value).map_err(display_error)?;
    file.write_all(b"\n").map_err(display_error)?;
    file.sync_all().map_err(display_error)
}

fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as FmtWrite;
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}

fn display_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[cfg(test)]
#[path = "r1_qterminal_v05_candidates_v02/tests.rs"]
mod tests;

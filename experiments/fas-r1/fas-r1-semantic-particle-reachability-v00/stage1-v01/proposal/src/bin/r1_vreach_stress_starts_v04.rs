use r1_world::{
    automorphisms, canonical_assignment, enumerate_solutions, validate, InferenceTask, Task,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

const SOLUTION_CAP: usize = 1_000_000;
const TASK_COUNT: usize = 96;
const TRAIN_TASKS: usize = 64;
const VALIDATION_TASKS: usize = 16;
const QUALIFICATION_TASKS: usize = 16;
const FULL_PRIVATE_SHA256: &str =
    "57705fa8c73281ffdd91e5b742f34fcdbdb443dc168cfc98ef1d7c029ab66ce8";
const PRIVATE_TRAINVAL_FILENAME: &str = "private-tasks-trainval-v04.jsonl";
const STARTS_PER_TASK: u32 = 32;
const UNIFORM_STARTS: u32 = 16;
const PERTURBATION_DISTANCES: [usize; 4] = [1, 2, 4, 8];

#[derive(Debug, Deserialize)]
struct SupportManifest {
    schema: String,
    source: SupportSource,
    split_counts: BTreeMap<String, usize>,
    family_roster: Vec<SupportRow>,
}

#[derive(Debug, Deserialize)]
struct SupportSource {
    sha256: String,
    rows: usize,
}

#[derive(Debug, Deserialize)]
struct SupportRow {
    task_id: String,
    family_id: String,
    split: String,
}

#[derive(Debug, Serialize)]
struct StartRow {
    schema: &'static str,
    task_id: String,
    family_id: String,
    family_split: String,
    state_index: u32,
    assignment: Vec<u8>,
    source_kind: &'static str,
    source_solution_class: Option<u32>,
    hamming_distance: Option<usize>,
}

#[derive(Debug, Serialize)]
struct GenerationReceipt {
    schema: &'static str,
    status: &'static str,
    analysis_mode: &'static str,
    qualification_previously_opened: bool,
    scientific_confirmation_eligible: bool,
    uniform_starts_per_task: u32,
    solution_neighborhood_starts_per_task: u32,
    perturbation_distances: [usize; 4],
    qualification_private_rows_opened: bool,
    qualification_states_consumed: bool,
    qualification_targets_consumed: bool,
    proposal_fit_receipt_sha256: String,
    public_tasks_sha256: String,
    private_trainval_sha256: String,
    support_manifest_sha256: String,
    start_states_sha256: String,
    start_state_rows: usize,
    source_sha256: String,
    task_counts: BTreeMap<String, usize>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("r1-vreach-stress-starts-v04: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let args = std::env::args_os()
        .skip(1)
        .map(PathBuf::from)
        .collect::<Vec<_>>();
    if args.len() != 5 {
        return Err("usage: r1_vreach_stress_starts_v04 PRIVATE_TRAINVAL PUBLIC_TASKS SUPPORT_MANIFEST PROPOSAL_FIT_RECEIPT OUTPUT_JSONL".into());
    }
    let private_path = &args[0];
    let public_path = &args[1];
    let support_path = &args[2];
    let proposal_receipt_path = &args[3];
    let output_path = &args[4];
    if private_path.file_name().and_then(|name| name.to_str()) != Some(PRIVATE_TRAINVAL_FILENAME) {
        return Err(format!("private input must be named {PRIVATE_TRAINVAL_FILENAME}").into());
    }

    // Only the explicitly supplied 80-row train/validation sidecar is opened.
    // This binary never opens the all-splits V04 private task file.
    let public_bytes = fs::read(public_path)?;
    let support_bytes = fs::read(support_path)?;
    let support: SupportManifest = serde_json::from_slice(&support_bytes)?;
    if support.schema != "R1_STAGE1_STRESS_SENSOR_SUPPORT_V04" {
        return Err("support manifest is not the V04 schema".into());
    }
    if support.source.sha256 != sha256_hex(&public_bytes) || support.source.rows != TASK_COUNT {
        return Err("public task digest/count differs from V04 support manifest".into());
    }
    let expected_counts = BTreeMap::from([
        ("train".to_owned(), TRAIN_TASKS),
        ("validation".to_owned(), VALIDATION_TASKS),
        ("qualification".to_owned(), QUALIFICATION_TASKS),
    ]);
    if support.split_counts != expected_counts {
        return Err("V04 support split counts must be exactly 64/16/16".into());
    }

    let private_bytes = fs::read(private_path)?;
    let private_sha256 = sha256_hex(&private_bytes);
    let proposal_receipt_bytes = fs::read(proposal_receipt_path)?;
    let proposal_receipt: serde_json::Value = serde_json::from_slice(&proposal_receipt_bytes)?;
    validate_proposal_receipt(
        &proposal_receipt,
        private_sha256.as_str(),
        private_bytes.len(),
        &private_path.canonicalize()?,
    )?;

    let public: Vec<InferenceTask> = read_jsonl(public_path)?;
    let private_trainval: Vec<Task> = serde_json::Deserializer::from_slice(&private_bytes)
        .into_iter::<Task>()
        .collect::<Result<Vec<_>, _>>()?;
    if public.len() != TASK_COUNT || private_trainval.len() != TRAIN_TASKS + VALIDATION_TASKS {
        return Err("V04 start generation requires 96 public rows and exactly 80 private train/validation rows".into());
    }
    let public_by_id = public
        .iter()
        .map(|task| (task.id.as_str(), task))
        .collect::<BTreeMap<_, _>>();
    if public_by_id.len() != TASK_COUNT {
        return Err("V04 public task IDs are not unique".into());
    }
    let split_by_task = support
        .family_roster
        .into_iter()
        .map(|row| (row.task_id, (row.family_id, row.split)))
        .collect::<BTreeMap<_, _>>();
    if split_by_task.len() != TASK_COUNT
        || split_by_task
            .keys()
            .any(|task_id| !public_by_id.contains_key(task_id.as_str()))
    {
        return Err("V04 support roster does not exactly cover public tasks".into());
    }

    let expected_trainval = split_by_task
        .iter()
        .filter(|(_, (_, split))| split == "train" || split == "validation")
        .map(|(task_id, _)| task_id.clone())
        .collect::<HashSet<_>>();
    let mut private_by_id = BTreeMap::<String, Task>::new();
    for task in private_trainval {
        let Some((family_id, split)) = split_by_task.get(&task.id) else {
            return Err(format!(
                "private train/validation task {} is absent from support",
                task.id
            )
            .into());
        };
        if split == "qualification" {
            return Err("qualification private task entered the train/validation sidecar".into());
        }
        if split != "train" && split != "validation" {
            return Err(format!("unknown V04 split {split:?} for {}", task.id).into());
        }
        if family_id != &task.family_id {
            return Err(format!("support family mismatch for {}", task.id).into());
        }
        let inference = public_by_id[task.id.as_str()];
        if task.family_id != inference.family_id
            || task.n != inference.n
            || task.k != inference.k
            || task.clauses.len() != inference.clauses.len()
        {
            return Err(format!("private/public task mismatch for {}", task.id).into());
        }
        if private_by_id.insert(task.id.clone(), task).is_some() {
            return Err("private train/validation sidecar has duplicate task IDs".into());
        }
    }
    if private_by_id.keys().cloned().collect::<HashSet<_>>() != expected_trainval {
        return Err(
            "private sidecar must contain exactly the 64/16 train/validation roster".into(),
        );
    }

    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output_path)?;
    let mut writer = BufWriter::new(&mut output);
    let mut task_counts = BTreeMap::<String, usize>::new();
    let mut written = 0usize;
    for task in private_by_id.values() {
        let (family_id, split) = &split_by_task[&task.id];
        if family_id != &task.family_id || split == "qualification" {
            return Err(format!("invalid train/validation task lineage for {}", task.id).into());
        }
        let starts = build_starts(task, split)?;
        if starts.len() != STARTS_PER_TASK as usize {
            return Err(format!("wrong state count for {}", task.id).into());
        }
        for row in starts {
            serde_json::to_writer(&mut writer, &row)?;
            writer.write_all(b"\n")?;
            written += 1;
        }
        *task_counts.entry(split.clone()).or_default() += 1;
    }
    writer.flush()?;
    drop(writer);
    output.sync_all()?;
    let start_bytes = fs::read(output_path)?;
    let source_path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("src/bin/r1_vreach_stress_starts_v04.rs");
    let receipt = GenerationReceipt {
        schema: "FAS_R1_VREACH_STARTS_V04_V01",
        status: "STRESS_VREACH_STARTS_COMPLETE",
        analysis_mode: "ADAPTIVE_ENGINEERING",
        qualification_previously_opened: true,
        scientific_confirmation_eligible: false,
        uniform_starts_per_task: UNIFORM_STARTS,
        solution_neighborhood_starts_per_task: STARTS_PER_TASK - UNIFORM_STARTS,
        perturbation_distances: PERTURBATION_DISTANCES,
        qualification_private_rows_opened: false,
        qualification_states_consumed: false,
        qualification_targets_consumed: false,
        proposal_fit_receipt_sha256: sha256_hex(&proposal_receipt_bytes),
        public_tasks_sha256: sha256_hex(&public_bytes),
        private_trainval_sha256: private_sha256,
        support_manifest_sha256: sha256_hex(&support_bytes),
        start_states_sha256: sha256_hex(&start_bytes),
        start_state_rows: written,
        source_sha256: sha256_hex(&fs::read(source_path)?),
        task_counts,
    };
    let receipt_path = output_path.with_extension("receipt-v04-v01.json");
    let mut receipt_bytes = serde_json::to_vec_pretty(&receipt)?;
    receipt_bytes.push(b'\n');
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(receipt_path)?
        .write_all(&receipt_bytes)?;
    println!("start_state_rows={written}");
    println!("start_states_sha256={}", receipt.start_states_sha256);
    println!(
        "train_tasks={}",
        receipt.task_counts.get("train").copied().unwrap_or(0)
    );
    println!(
        "validation_tasks={}",
        receipt.task_counts.get("validation").copied().unwrap_or(0)
    );
    Ok(())
}

fn validate_proposal_receipt(
    receipt: &serde_json::Value,
    observed_private_sha256: &str,
    observed_private_bytes: usize,
    observed_private_path: &Path,
) -> Result<(), Box<dyn Error>> {
    if receipt.get("schema").and_then(|value| value.as_str()) != Some("FAS_R1_PROPOSAL_FIT_V04_V01")
        || receipt.get("status").and_then(|value| value.as_str())
            != Some("R1_V04_PROPOSAL_FIT_COMPLETE")
    {
        return Err("proposal fit receipt schema/status is not completed V04".into());
    }
    if receipt
        .get("world_bundle")
        .and_then(|value| value.get("private_sha256"))
        .and_then(|value| value.as_str())
        != Some(FULL_PRIVATE_SHA256)
    {
        return Err(
            "proposal receipt does not bind the frozen full V04 private source hash".into(),
        );
    }
    let lineage = receipt
        .get("private_trainval")
        .ok_or("proposal receipt lacks the trainval private sidecar lineage")?;
    if lineage.get("file").and_then(|value| value.as_str()) != Some(PRIVATE_TRAINVAL_FILENAME)
        || lineage.get("rows").and_then(|value| value.as_u64()) != Some(80)
        || lineage
            .get("qualification_rows_omitted")
            .and_then(|value| value.as_u64())
            != Some(16)
        || lineage
            .get("source_private_sha256")
            .and_then(|value| value.as_str())
            != Some(FULL_PRIVATE_SHA256)
        || lineage.get("sha256").and_then(|value| value.as_str()) != Some(observed_private_sha256)
        || lineage.get("bytes").and_then(|value| value.as_u64())
            != Some(observed_private_bytes as u64)
    {
        return Err("trainval sidecar differs from proposal receipt lineage".into());
    }
    let splits = lineage
        .get("split_counts")
        .ok_or("trainval sidecar receipt lacks split counts")?;
    if splits.get("train").and_then(|value| value.as_u64()) != Some(64)
        || splits.get("validation").and_then(|value| value.as_u64()) != Some(16)
    {
        return Err("trainval sidecar receipt must bind 64 train and 16 validation rows".into());
    }
    let output = receipt
        .get("output_files")
        .and_then(|value| value.get(PRIVATE_TRAINVAL_FILENAME))
        .ok_or("proposal output_files does not include trainval private sidecar")?;
    let recorded_output_path = output
        .get("path")
        .and_then(|value| value.as_str())
        .ok_or("proposal output_files lacks the private trainval path")?;
    if output.get("sha256").and_then(|value| value.as_str()) != Some(observed_private_sha256)
        || output.get("bytes").and_then(|value| value.as_u64())
            != Some(observed_private_bytes as u64)
        || normalized_windows_path(recorded_output_path)
            != normalized_windows_path(
                observed_private_path
                    .to_str()
                    .ok_or("private trainval path is not valid UTF-8")?,
            )
    {
        return Err("proposal output_files hash/size differs from trainval private sidecar".into());
    }
    Ok(())
}

fn normalized_windows_path(path: &str) -> String {
    let mut value = path.replace('/', "\\");
    if let Some(rest) = value.strip_prefix(r"\\?\UNC\") {
        value = format!(r"\\{}", rest);
    } else if let Some(rest) = value.strip_prefix(r"\\?\") {
        value = rest.to_owned();
    }
    value.trim_end_matches('\\').to_ascii_lowercase()
}

fn build_starts(task: &Task, split: &str) -> Result<Vec<StartRow>, Box<dyn Error>> {
    let solutions = enumerate_solutions(task, SOLUTION_CAP)?;
    let group = automorphisms(task);
    let mut classes = BTreeMap::<Vec<u8>, Vec<u8>>::new();
    for solution in &solutions {
        classes
            .entry(canonical_assignment(solution, &group))
            .or_insert_with(|| solution.clone());
    }
    if classes.is_empty() {
        return Err(format!("task {} has no valid assignment", task.id).into());
    }
    let representatives = classes.into_values().collect::<Vec<_>>();
    let mut rows = Vec::with_capacity(STARTS_PER_TASK as usize);
    let mut unique = HashSet::<Vec<u8>>::with_capacity(STARTS_PER_TASK as usize);

    for state_index in 0..UNIFORM_STARTS {
        let mut rng = SplitMix64::new(seed_for(&task.id, state_index));
        let assignment = (0..task.n)
            .map(|_| (rng.next_u64() % u64::from(task.k)) as u8)
            .collect::<Vec<_>>();
        unique.insert(assignment.clone());
        rows.push(StartRow {
            schema: "r1-vreach-stress-start-v04-v01",
            task_id: task.id.clone(),
            family_id: task.family_id.clone(),
            family_split: split.to_owned(),
            state_index,
            assignment,
            source_kind: "uniform",
            source_solution_class: None,
            hamming_distance: None,
        });
    }

    for offset in 0..(STARTS_PER_TASK - UNIFORM_STARTS) {
        let state_index = UNIFORM_STARTS + offset;
        let distance = PERTURBATION_DISTANCES[offset as usize % PERTURBATION_DISTANCES.len()];
        let mut accepted = None;
        for attempt in 0..256u64 {
            let mut rng = SplitMix64::new(seed_for(&task.id, state_index).wrapping_add(attempt));
            let class_index = ((offset as usize) + attempt as usize) % representatives.len();
            let mut assignment = representatives[class_index].clone();
            let mut entities = (0..usize::from(task.n)).collect::<Vec<_>>();
            rng.shuffle(&mut entities);
            for &entity in entities.iter().take(distance) {
                let old_role = assignment[entity];
                let mut role = (rng.next_u64() % u64::from(task.k - 1)) as u8;
                if role >= old_role {
                    role += 1;
                }
                assignment[entity] = role;
            }
            if unique.contains(&assignment) || validate(task, &assignment) {
                continue;
            }
            unique.insert(assignment.clone());
            accepted = Some((assignment, class_index as u32));
            break;
        }
        let (assignment, class_index) = accepted.ok_or_else(|| {
            format!(
                "could not make unique distance-{distance} state for {}",
                task.id
            )
        })?;
        rows.push(StartRow {
            schema: "r1-vreach-stress-start-v04-v01",
            task_id: task.id.clone(),
            family_id: task.family_id.clone(),
            family_split: split.to_owned(),
            state_index,
            assignment,
            source_kind: "solution_neighborhood",
            source_solution_class: Some(class_index),
            hamming_distance: Some(distance),
        });
    }
    Ok(rows)
}

fn seed_for(task_id: &str, state_index: u32) -> u64 {
    let mut hash = Sha256::new();
    hash.update(b"FAS-R1-VREACH-STRESS-START-V04-V01\0");
    hash.update(task_id.as_bytes());
    hash.update(state_index.to_le_bytes());
    u64::from_le_bytes(hash.finalize()[..8].try_into().expect("SHA prefix"))
}

fn read_jsonl<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<Vec<T>, Box<dyn Error>> {
    let file = File::open(path)?;
    BufReader::new(file)
        .lines()
        .enumerate()
        .filter_map(|(index, line)| match line {
            Ok(line) if line.trim().is_empty() => None,
            Ok(line) => Some(
                serde_json::from_str(&line)
                    .map_err(|error| {
                        format!("invalid JSON at {}:{}: {error}", path.display(), index + 1)
                    })
                    .map_err(Into::into),
            ),
            Err(error) => Some(Err(error.into())),
        })
        .collect()
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[derive(Clone, Copy)]
struct SplitMix64(u64);

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self(seed)
    }

    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }

    fn shuffle<T>(&mut self, values: &mut [T]) {
        for end in (1..values.len()).rev() {
            values.swap((self.next_u64() as usize) % (end + 1), end);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use r1_world::Clause;

    fn fixture_task() -> Task {
        Task {
            id: "fixture-v04-neighborhood".to_owned(),
            family_id: "fixture".to_owned(),
            seed: 7,
            n: 8,
            k: 3,
            clauses: (1..8)
                .map(|entity| Clause::Same {
                    a: entity - 1,
                    b: entity,
                })
                .collect(),
            role_anonymous: true,
        }
    }

    #[test]
    fn v04_neighborhood_starts_are_repeatable_and_semantically_valid() {
        let task = fixture_task();
        let first = build_starts(&task, "train").expect("fixture starts");
        let second = build_starts(&task, "train").expect("repeat fixture starts");
        assert_eq!(
            serde_json::to_vec(&first).unwrap(),
            serde_json::to_vec(&second).unwrap()
        );
        assert_eq!(first.len(), STARTS_PER_TASK as usize);
        assert_eq!(
            first
                .iter()
                .filter(|row| row.source_kind == "uniform")
                .count(),
            16
        );
        let neighborhoods = first
            .iter()
            .filter(|row| row.source_kind == "solution_neighborhood")
            .collect::<Vec<_>>();
        assert_eq!(neighborhoods.len(), 16);
        assert!(neighborhoods
            .iter()
            .all(|row| !validate(&task, &row.assignment)));
    }

    #[test]
    fn v04_seed_domain_is_distinct_and_repeatable() {
        assert_eq!(seed_for("task", 9), seed_for("task", 9));
        assert_ne!(seed_for("task", 9), seed_for("task", 10));
        let mut left = SplitMix64::new(seed_for("task", 3));
        let mut right = SplitMix64::new(seed_for("task", 3));
        assert_eq!(left.next_u64(), right.next_u64());
    }

    #[test]
    fn private_trainval_must_match_proposal_receipt_lineage() {
        let path = Path::new("C:\\fixture\\private-tasks-trainval-v04.jsonl");
        let receipt = serde_json::json!({
            "schema": "FAS_R1_PROPOSAL_FIT_V04_V01",
            "status": "R1_V04_PROPOSAL_FIT_COMPLETE",
            "world_bundle": { "private_sha256": FULL_PRIVATE_SHA256 },
            "private_trainval": {
                "file": PRIVATE_TRAINVAL_FILENAME,
                "rows": 80,
                "split_counts": { "train": 64, "validation": 16 },
                "qualification_rows_omitted": 16,
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "bytes": 123,
                "source_private_sha256": FULL_PRIVATE_SHA256
            },
            "output_files": {
                "private-tasks-trainval-v04.jsonl": {
                    "path": format!(r"\\?\{}", path.to_str().unwrap()),
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "bytes": 123
                }
            }
        });
        assert!(validate_proposal_receipt(
            &receipt,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            123,
            path,
        )
        .is_ok());
        let mut changed = receipt;
        changed["world_bundle"]["private_sha256"] = serde_json::json!("b".repeat(64));
        assert!(validate_proposal_receipt(
            &changed,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            123,
            path,
        )
        .is_err());
    }

    #[test]
    fn canonical_extended_windows_path_matches_receipt_path() {
        assert_eq!(
            normalized_windows_path(r"\\?\D:\codex-runs\run-v84\private.jsonl"),
            normalized_windows_path(r"d:/codex-runs/run-v84/private.jsonl")
        );
    }
}

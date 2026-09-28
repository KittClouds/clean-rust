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
const STARTS_PER_TASK: u32 = 32;
const UNIFORM_STARTS: u32 = 16;
const PERTURBATION_DISTANCES: [usize; 4] = [1, 2, 4, 8];

#[derive(Debug, Deserialize)]
struct SupportManifest {
    source: SupportSource,
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
    uniform_starts_per_task: u32,
    solution_neighborhood_starts_per_task: u32,
    perturbation_distances: [usize; 4],
    qualification_states_consumed: bool,
    public_tasks_sha256: String,
    support_manifest_sha256: String,
    start_states_sha256: String,
    start_state_rows: usize,
    source_sha256: String,
    task_counts: BTreeMap<String, usize>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("r1-vreach-stress-starts: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let args = std::env::args_os()
        .skip(1)
        .map(PathBuf::from)
        .collect::<Vec<_>>();
    if args.len() != 4 {
        return Err("usage: r1_vreach_stress_starts PRIVATE_TASKS PUBLIC_TASKS SUPPORT_MANIFEST OUTPUT_JSONL".into());
    }
    let private_path = &args[0];
    let public_path = &args[1];
    let support_path = &args[2];
    let output_path = &args[3];
    let public_bytes = fs::read(public_path)?;
    let support_bytes = fs::read(support_path)?;
    let support: SupportManifest = serde_json::from_slice(&support_bytes)?;
    if support.source.sha256 != sha256_hex(&public_bytes) {
        return Err("public task digest differs from support manifest".into());
    }
    let private: Vec<Task> = read_jsonl(private_path)?;
    let public: Vec<InferenceTask> = read_jsonl(public_path)?;
    if private.is_empty() || private.len() != public.len() || private.len() != support.source.rows {
        return Err("private, public, and support row counts differ".into());
    }

    let split_by_task = support
        .family_roster
        .into_iter()
        .map(|row| (row.task_id, (row.family_id, row.split)))
        .collect::<BTreeMap<_, _>>();
    if split_by_task.len() != private.len() {
        return Err("support roster has duplicate tasks or a mismatched row count".into());
    }

    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output_path)?;
    let mut writer = BufWriter::new(&mut output);
    let mut task_counts = BTreeMap::<String, usize>::new();
    let mut written = 0usize;
    for (task, inference) in private.iter().zip(&public) {
        if task.id != inference.id
            || task.family_id != inference.family_id
            || task.n != inference.n
            || task.k != inference.k
            || task.clauses.len() != inference.clauses.len()
        {
            return Err(format!("private/public task mismatch for {}", task.id).into());
        }
        let Some((family_id, split)) = split_by_task.get(&task.id) else {
            return Err(format!("task {} absent from support roster", task.id).into());
        };
        if family_id != &task.family_id {
            return Err(format!("support family mismatch for {}", task.id).into());
        }
        if split == "qualification" {
            continue;
        }
        if split != "train" && split != "validation" {
            return Err(format!("unknown split {split:?} for {}", task.id).into());
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
        Path::new(env!("CARGO_MANIFEST_DIR")).join("src/bin/r1_vreach_stress_starts.rs");
    let receipt = GenerationReceipt {
        schema: "FAS_R1_VREACH_STRESS_STARTS_V01",
        status: "STRESS_VREACH_STARTS_COMPLETE",
        uniform_starts_per_task: UNIFORM_STARTS,
        solution_neighborhood_starts_per_task: STARTS_PER_TASK - UNIFORM_STARTS,
        perturbation_distances: PERTURBATION_DISTANCES,
        qualification_states_consumed: false,
        public_tasks_sha256: sha256_hex(&public_bytes),
        support_manifest_sha256: sha256_hex(&support_bytes),
        start_states_sha256: sha256_hex(&start_bytes),
        start_state_rows: written,
        source_sha256: sha256_hex(&fs::read(source_path)?),
        task_counts,
    };
    let receipt_path = output_path.with_extension("receipt-v01.json");
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
            schema: "r1-vreach-stress-start-v01",
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
            schema: "r1-vreach-stress-start-v01",
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
    hash.update(b"FAS-R1-VREACH-STRESS-START-v01\0");
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
            id: "fixture-neighborhood".to_owned(),
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
    fn neighborhood_starts_are_repeatable_unique_and_invalid() {
        let task = fixture_task();
        let first = build_starts(&task, "train").expect("fixture starts");
        let second = build_starts(&task, "train").expect("repeat fixture starts");
        assert_eq!(
            serde_json::to_vec(&first).expect("serialize first"),
            serde_json::to_vec(&second).expect("serialize second")
        );
        assert_eq!(first.len(), STARTS_PER_TASK as usize);

        let solutions = enumerate_solutions(&task, SOLUTION_CAP).expect("fixture solutions");
        let group = automorphisms(&task);
        let mut classes = BTreeMap::<Vec<u8>, Vec<u8>>::new();
        for solution in &solutions {
            classes
                .entry(canonical_assignment(solution, &group))
                .or_insert_with(|| solution.clone());
        }
        let representatives = classes.into_values().collect::<Vec<_>>();
        let neighborhoods = first
            .iter()
            .filter(|row| row.source_kind == "solution_neighborhood")
            .collect::<Vec<_>>();
        assert_eq!(
            neighborhoods.len(),
            (STARTS_PER_TASK - UNIFORM_STARTS) as usize
        );
        assert_eq!(
            neighborhoods
                .iter()
                .map(|row| row.assignment.clone())
                .collect::<HashSet<_>>()
                .len(),
            neighborhoods.len(),
            "neighborhood starts must be distinct"
        );
        for row in neighborhoods {
            let class = row.source_solution_class.expect("source class");
            let representative = &representatives[class as usize];
            let distance = row.hamming_distance.expect("declared distance");
            assert_eq!(
                row.assignment
                    .iter()
                    .zip(representative)
                    .filter(|(left, right)| left != right)
                    .count(),
                distance
            );
            assert!(!validate(&task, &row.assignment));
        }
    }

    #[test]
    fn splitmix_shuffle_is_deterministic_and_preserves_values() {
        let mut left = SplitMix64::new(91);
        let mut right = SplitMix64::new(91);
        let mut first = (0..32).collect::<Vec<_>>();
        let mut second = first.clone();
        left.shuffle(&mut first);
        right.shuffle(&mut second);
        assert_eq!(first, second);
        first.sort_unstable();
        assert_eq!(first, (0..32).collect::<Vec<_>>());
    }
}

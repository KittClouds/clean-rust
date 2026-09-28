//! Offline-only label reconstruction for the R1 sensor ladder.
//! The executable reads private Stage 0 tasks but emits labels to a separate
//! sidecar. No label field is added to InferenceTask or any model input.

use r1_world::{render_task, Clause, InferenceTask, Task};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::env;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

const BASE_SEED: u64 = 0xF451_2026_0925_0001;
const STATES_PER_FAMILY: usize = 32;
const SEED_DOMAIN: &str = "FAS-R1-ACTION-PROBE-v01";

#[derive(Serialize)]
struct ClauseLabel<'a> {
    constraint_row: usize,
    task_index: usize,
    task_id: &'a str,
    family_id: &'a str,
    split: &'a str,
    clause_index: usize,
    clause_kind: &'static str,
    entity_ids: Vec<u16>,
    role_ids: Vec<u8>,
    template_id: u8,
}

#[derive(Serialize)]
struct Edit {
    entity: u16,
    from_role: u8,
    to_role: u8,
}

#[derive(Serialize)]
struct ActionLabel<'a> {
    action_row: usize,
    task_index: usize,
    task_id: &'a str,
    family_id: &'a str,
    split: &'a str,
    state_index: usize,
    assignment: Vec<u8>,
    edit: Edit,
    satisfied_before: usize,
    satisfied_after: usize,
    delta_satisfied: isize,
    sign_delta: i8,
}

#[derive(Serialize)]
struct Receipt {
    schema: &'static str,
    status: &'static str,
    public_input_sha256: String,
    private_input_sha256: String,
    support_manifest_sha256: String,
    clause_labels_sha256: String,
    action_labels_sha256: String,
    clause_label_rows: usize,
    action_label_rows: usize,
    support: SupportSummary,
    model_or_probe_training_performed: bool,
}

#[derive(Default, Serialize)]
struct SupportSummary {
    family_counts: BTreeMap<String, usize>,
    clause_kind_counts: BTreeMap<String, BTreeMap<String, usize>>,
    binding_entity_mentions: BTreeMap<String, usize>,
    binding_role_mentions: BTreeMap<String, usize>,
    action_sign_counts: BTreeMap<String, BTreeMap<String, usize>>,
    action_sign_family_counts: BTreeMap<String, BTreeMap<String, usize>>,
    qualification_support_gate: BTreeMap<String, QualificationClassSupport>,
}

#[derive(Default, Serialize)]
struct QualificationClassSupport {
    examples: usize,
    distinct_families: usize,
    minimum_examples: usize,
    minimum_families: usize,
    sufficient: bool,
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    let mut reader = BufReader::new(file);
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let read = reader.read(&mut buffer).map_err(|e| format!("read {}: {e}", path.display()))?;
        if read == 0 { break; }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn read_jsonl<T: serde::de::DeserializeOwned>(path: &Path) -> Result<Vec<T>, String> {
    let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    BufReader::new(file)
        .lines()
        .enumerate()
        .map(|(index, line)| {
            let line = line.map_err(|e| format!("read line {}: {e}", index + 1))?;
            serde_json::from_str(&line)
                .map_err(|e| format!("parse line {} in {}: {e}", index + 1, path.display()))
        })
        .collect()
}

fn clause_name(clause: &Clause) -> &'static str {
    match clause {
        Clause::Same { .. } => "same",
        Clause::Different { .. } => "different",
        Clause::FixedRole { .. } => "fixed_role",
        Clause::ForbiddenRole { .. } => "forbidden_role",
        Clause::ExactlyOneRole { .. } => "exactly_one_role",
        Clause::ImpliesNotRole { .. } => "implies_not_role",
    }
}

fn clause_mentions(clause: &Clause) -> (Vec<u16>, Vec<u8>) {
    let mut entities = Vec::new();
    let mut roles = Vec::new();
    match clause {
        Clause::Same { a, b } | Clause::Different { a, b } => entities.extend([*a, *b]),
        Clause::FixedRole { entity, role } | Clause::ForbiddenRole { entity, role } => {
            entities.push(*entity);
            roles.push(*role);
        }
        Clause::ExactlyOneRole { entities: ids, role } => {
            entities.extend_from_slice(ids);
            roles.push(*role);
        }
        Clause::ImpliesNotRole { if_entity, if_role, then_entity, then_role } => {
            entities.extend([*if_entity, *then_entity]);
            roles.extend([*if_role, *then_role]);
        }
    }
    entities.sort_unstable();
    entities.dedup();
    roles.sort_unstable();
    roles.dedup();
    (entities, roles)
}

fn clause_satisfied(clause: &Clause, assignment: &[u8]) -> bool {
    match clause {
        Clause::Same { a, b } => assignment[usize::from(*a)] == assignment[usize::from(*b)],
        Clause::Different { a, b } => assignment[usize::from(*a)] != assignment[usize::from(*b)],
        Clause::FixedRole { entity, role } => assignment[usize::from(*entity)] == *role,
        Clause::ForbiddenRole { entity, role } => assignment[usize::from(*entity)] != *role,
        Clause::ExactlyOneRole { entities, role } => {
            entities.iter().filter(|entity| assignment[usize::from(**entity)] == *role).count() == 1
        }
        Clause::ImpliesNotRole { if_entity, if_role, then_entity, then_role } => {
            !(assignment[usize::from(*if_entity)] == *if_role
                && assignment[usize::from(*then_entity)] == *then_role)
        }
    }
}

fn satisfied_count(task: &Task, assignment: &[u8]) -> usize {
    task.clauses.iter().filter(|clause| clause_satisfied(clause, assignment)).count()
}

struct SplitMix64(u64);

impl SplitMix64 {
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^ (z >> 31)
    }
}

fn assignment_seed(task_id: &str, state_index: usize) -> u64 {
    let input = format!("{SEED_DOMAIN}\0{task_id}\0{state_index}");
    let digest = Sha256::digest(input.as_bytes());
    u64::from_le_bytes(digest[..8].try_into().expect("SHA-256 prefix is 8 bytes"))
}

fn sample_assignment(task: &Task, state_index: usize) -> Vec<u8> {
    let mut rng = SplitMix64(assignment_seed(&task.id, state_index));
    (0..task.n).map(|_| (rng.next_u64() % u64::from(task.k)) as u8).collect()
}

fn sign_name(sign: i8) -> &'static str {
    match sign {
        -1 => "negative",
        0 => "zero",
        1 => "positive",
        _ => unreachable!("delta sign is in -1..=1"),
    }
}

fn main_result() -> Result<(), String> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 5 {
        return Err("usage: r1-sensor-label-exporter PRIVATE_TASKS PUBLIC_TASKS SUPPORT_MANIFEST NEW_OUTPUT_DIR".into());
    }
    let private_path = PathBuf::from(&args[1]);
    let public_path = PathBuf::from(&args[2]);
    let manifest_path = PathBuf::from(&args[3]);
    let output_dir = PathBuf::from(&args[4]);
    if output_dir.exists() {
        return Err(format!("refusing to overwrite {}", output_dir.display()));
    }

    eprintln!("label-export: hashing inputs");
    let public_hash = sha256_file(&public_path)?;
    let private_hash = sha256_file(&private_path)?;
    let manifest_hash = sha256_file(&manifest_path)?;
    let manifest: Value = serde_json::from_slice(
        &fs::read(&manifest_path).map_err(|e| format!("read support manifest: {e}"))?,
    ).map_err(|e| format!("parse support manifest: {e}"))?;
    if manifest["source"]["sha256"].as_str() != Some(&public_hash) {
        return Err("public input SHA-256 differs from frozen support manifest".into());
    }

    eprintln!("label-export: parsing private tasks");
    let private_tasks: Vec<Task> = read_jsonl(&private_path)?;
    eprintln!("label-export: private tasks parsed {}", private_tasks.len());
    eprintln!("label-export: parsing public tasks");
    let public_tasks: Vec<InferenceTask> = read_jsonl(&public_path)?;
    eprintln!("label-export: public tasks parsed {}", public_tasks.len());
    if private_tasks.len() != public_tasks.len()
        || manifest["source"]["rows"].as_u64() != Some(public_tasks.len() as u64)
    {
        return Err("private/public row counts disagree with manifest".into());
    }
    eprintln!("label-export: parsing roster");
    let roster = manifest["family_roster"].as_array()
        .ok_or("support manifest has no family_roster")?;
    let mut split_for_task = HashMap::with_capacity(roster.len());
    for entry in roster {
        let id = entry["task_id"].as_str().ok_or("roster task_id missing")?;
        let family = entry["family_id"].as_str().ok_or("roster family_id missing")?;
        let split = entry["split"].as_str().ok_or("roster split missing")?;
        if split_for_task.insert(id.to_owned(), (family.to_owned(), split.to_owned())).is_some() {
            return Err(format!("duplicate roster task {id}"));
        }
    }

    eprintln!("label-export: roster validated; creating outputs");
    output_dir.parent().ok_or("output directory needs a parent")?;
    fs::create_dir_all(output_dir.parent().unwrap()).map_err(|e| format!("create parent: {e}"))?;
    fs::create_dir(&output_dir).map_err(|e| format!("create output directory: {e}"))?;
    let clause_path = output_dir.join("private-clause-labels.jsonl");
    let action_path = output_dir.join("private-action-labels.jsonl");
    let clause_file = File::create(&clause_path).map_err(|e| format!("create clause labels: {e}"))?;
    let action_file = File::create(&action_path).map_err(|e| format!("create action labels: {e}"))?;
    let mut clause_writer = BufWriter::new(clause_file);
    let mut action_writer = BufWriter::new(action_file);
    let mut summary = SupportSummary::default();
    let mut family_signs: HashSet<(String, String, String)> = HashSet::new();
    let mut clause_row = 0usize;
    let mut action_row = 0usize;

    for (task_index, (task, public)) in private_tasks.iter().zip(&public_tasks).enumerate() {
        eprintln!("label-export: task {task_index} {}", task.id);
        if task.id != public.id || task.family_id != public.family_id
            || task.n != public.n || task.k != public.k || task.role_anonymous != public.role_anonymous
        {
            return Err(format!("private/public task metadata mismatch at row {task_index}"));
        }
        let (family, split) = split_for_task.get(&task.id)
            .ok_or_else(|| format!("task {} absent from split roster", task.id))?;
        if family != &task.family_id {
            return Err(format!("task {} family differs from frozen roster", task.id));
        }
        *summary.family_counts.entry(split.clone()).or_default() += 1;
        let surface_seed = BASE_SEED ^ task_index as u64;
        let rendered = render_task(task, surface_seed);
        if rendered.inference != *public {
            return Err(format!("exact renderer mismatch at task {}", task.id));
        }

        for clause_index in 0..task.clauses.len() {
            let ast_index = rendered.clause_order[clause_index];
            let clause = &task.clauses[ast_index];
            let (entities, roles) = clause_mentions(clause);
            if public.entity_mentions[clause_index] != entities
                || public.role_mentions[clause_index] != roles
            {
                return Err(format!("public incidence mismatch at {} clause {clause_index}", task.id));
            }
            let kind = clause_name(clause);
            *summary.clause_kind_counts.entry(split.clone()).or_default()
                .entry(kind.to_owned()).or_default() += 1;
            *summary.binding_entity_mentions.entry(split.clone()).or_default() += entities.len();
            *summary.binding_role_mentions.entry(split.clone()).or_default() += roles.len();
            let label = ClauseLabel {
                constraint_row: clause_row,
                task_index,
                task_id: &task.id,
                family_id: &task.family_id,
                split,
                clause_index,
                clause_kind: kind,
                entity_ids: entities,
                role_ids: roles,
                template_id: rendered.template_ids[clause_index],
            };
            serde_json::to_writer(&mut clause_writer, &label).map_err(|e| e.to_string())?;
            clause_writer.write_all(b"\n").map_err(|e| e.to_string())?;
            clause_row += 1;
        }

        for state_index in 0..STATES_PER_FAMILY {
            let assignment = sample_assignment(task, state_index);
            let before = satisfied_count(task, &assignment);
            for entity_index in 0..usize::from(task.n) {
                let from_role = assignment[entity_index];
                for to_role in 0..task.k {
                    if to_role == from_role { continue; }
                    let mut edited = assignment.clone();
                    edited[entity_index] = to_role;
                    let after = satisfied_count(task, &edited);
                    let delta = after as isize - before as isize;
                    let sign = delta.signum() as i8;
                    let sign_key = sign_name(sign).to_owned();
                    *summary.action_sign_counts.entry(split.clone()).or_default()
                        .entry(sign_key.clone()).or_default() += 1;
                    family_signs.insert((split.clone(), sign_key, task.family_id.clone()));
                    let label = ActionLabel {
                        action_row,
                        task_index,
                        task_id: &task.id,
                        family_id: &task.family_id,
                        split,
                        state_index,
                        assignment: assignment.clone(),
                        edit: Edit { entity: entity_index as u16, from_role, to_role },
                        satisfied_before: before,
                        satisfied_after: after,
                        delta_satisfied: delta,
                        sign_delta: sign,
                    };
                    serde_json::to_writer(&mut action_writer, &label).map_err(|e| e.to_string())?;
                    action_writer.write_all(b"\n").map_err(|e| e.to_string())?;
                    action_row += 1;
                }
            }
        }
    }
    clause_writer.flush().map_err(|e| format!("flush clause labels: {e}"))?;
    action_writer.flush().map_err(|e| format!("flush action labels: {e}"))?;

    for (split, sign, family) in family_signs {
        *summary.action_sign_family_counts.entry(split).or_default()
            .entry(sign).or_default() += 1;
        let _ = family;
    }
    let minimum_examples = manifest["action_relevance_support"]["qualification_minimum"]
        ["examples_per_sign_class"].as_u64().unwrap_or(100) as usize;
    let minimum_families = manifest["action_relevance_support"]["qualification_minimum"]
        ["distinct_qualification_families_per_sign_class"].as_u64().unwrap_or(20) as usize;
    for sign in ["negative", "zero", "positive"] {
        let examples = summary.action_sign_counts.get("qualification")
            .and_then(|counts| counts.get(sign)).copied().unwrap_or(0);
        let families = summary.action_sign_family_counts.get("qualification")
            .and_then(|counts| counts.get(sign)).copied().unwrap_or(0);
        summary.qualification_support_gate.insert(sign.to_owned(), QualificationClassSupport {
            examples,
            distinct_families: families,
            minimum_examples,
            minimum_families,
            sufficient: examples >= minimum_examples && families >= minimum_families,
        });
    }

    let clause_labels_hash = sha256_file(&clause_path)?;
    let action_labels_hash = sha256_file(&action_path)?;
    let receipt = Receipt {
        schema: "R1_SENSOR_OFFLINE_LABELS_V01",
        status: "R1_SENSOR_LABELS_READY",
        public_input_sha256: public_hash,
        private_input_sha256: private_hash,
        support_manifest_sha256: manifest_hash,
        clause_labels_sha256: clause_labels_hash,
        action_labels_sha256: action_labels_hash,
        clause_label_rows: clause_row,
        action_label_rows: action_row,
        support: summary,
        model_or_probe_training_performed: false,
    };
    let receipt_path = output_dir.join("support-summary.json");
    let file = File::create(&receipt_path).map_err(|e| format!("create support summary: {e}"))?;
    serde_json::to_writer_pretty(BufWriter::new(file), &receipt)
        .map_err(|e| format!("write support summary: {e}"))?;
    println!("R1_SENSOR_LABELS_READY clauses={clause_row} actions={action_row}");
    Ok(())
}

fn main() {
    if let Err(error) = main_result() {
        eprintln!("R1_SENSOR_LABEL_EXPORT_FAILED: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitmix_seed_and_sampling_are_replayable() {
        let task = Task {
            id: "task-test".into(), family_id: "fam-test".into(), seed: 7,
            n: 4, k: 3, clauses: Vec::new(), role_anonymous: false,
        };
        assert_eq!(sample_assignment(&task, 11), sample_assignment(&task, 11));
        assert_ne!(sample_assignment(&task, 11), sample_assignment(&task, 12));
        assert!(sample_assignment(&task, 11).iter().all(|&role| role < task.k));
    }

    #[test]
    fn satisfied_count_counts_each_clause_once() {
        let task = Task {
            id: "t".into(), family_id: "f".into(), seed: 0, n: 3, k: 2,
            role_anonymous: false,
            clauses: vec![
                Clause::Same { a: 0, b: 1 },
                Clause::Different { a: 1, b: 2 },
                Clause::FixedRole { entity: 2, role: 0 },
            ],
        };
        assert_eq!(satisfied_count(&task, &[0, 0, 1]), 2);
        assert_eq!(satisfied_count(&task, &[0, 0, 0]), 2);
    }
}


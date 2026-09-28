use std::time::Instant;

use hashbrown::HashSet;
use r1_world::{
    automorphisms, canonical_assignment, enumerate_solutions, validate, validate_independent,
    Clause, InferenceTask, RenderedTask, SolveError, Task,
};
use serde::Serialize;
use sha2::{Digest, Sha256};

pub const BATCH_SIZE: usize = 96;
pub const K: u8 = 3;
pub const SOLUTION_CAP: usize = 4096;
pub const EXPECTED_RAW_SOLUTIONS: usize = 54;
pub const EXPECTED_CANONICAL_CLASSES: usize = 9;
pub const MAX_WORLD_SOLVE_MS: u128 = 30_000;
const BASE_SEED: u64 = 0x5231_5354_5245_5353;
const N: u16 = 20;
const SPLIT_TRAIN: usize = 64;
const SPLIT_VALIDATION: usize = 16;

#[derive(Clone, Debug, PartialEq)]
pub struct StressWorld {
    pub task: Task,
    pub rendered: RenderedTask,
    pub record: WorldRecord,
    pub private_diagnostics: PrivateDiagnostics,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct WorldRecord {
    pub index: usize,
    pub task_id: String,
    pub family_id: String,
    pub seed: u64,
    pub n: u16,
    pub k: u8,
    pub role_anonymous: bool,
    pub graph_recipe: &'static str,
    pub edge_count: usize,
    pub all_pair_density: f64,
    pub exact_count_status: &'static str,
    pub raw_solution_count: usize,
    pub canonical_solution_class_count: usize,
    pub role_automorphism_count: usize,
    pub independent_validator_checks: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PrivateDiagnostics {
    pub planted_assignment: Vec<u8>,
    pub module_anchors: [[u16; 3]; 4],
    pub raw_solution_count: usize,
    pub canonical_solution_class_count: usize,
    pub role_automorphism_count: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct StressBatch {
    pub worlds: Vec<StressWorld>,
    pub max_solver_elapsed_ms: u128,
    pub total_solver_elapsed_ms: u128,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StressError(pub String);

impl std::fmt::Display for StressError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for StressError {}

#[derive(Clone, Debug, Eq, PartialEq)]
struct CandidateGraph {
    seed: u64,
    n: u16,
    planted_roles: Vec<u8>,
    module_anchors: [[u16; 3]; 4],
    edges: Vec<(u16, u16)>,
}

#[derive(Serialize)]
struct PrivateDiagnosticsRow<'a> {
    task_id: &'a str,
    family_id: &'a str,
    seed: u64,
    planted_assignment: &'a [u8],
    module_anchors: &'a [[u16; 3]; 4],
    exact_count_status: &'static str,
    raw_solution_count: usize,
    canonical_solution_class_count: usize,
    role_automorphism_count: usize,
}

#[derive(Serialize)]
pub struct SupportManifest<'a> {
    pub schema: &'static str,
    pub status: &'static str,
    pub source: SupportSource,
    pub family_roster: Vec<FamilyRosterEntry<'a>>,
    pub split_counts: SplitCounts,
}

#[derive(Serialize)]
pub struct SupportSource {
    pub path: &'static str,
    pub sha256: String,
    pub bytes: usize,
    pub rows: usize,
}

#[derive(Serialize)]
pub struct FamilyRosterEntry<'a> {
    pub task_id: &'a str,
    pub family_id: &'a str,
    pub split: &'static str,
}

#[derive(Serialize)]
pub struct SplitCounts {
    pub train: usize,
    pub validation: usize,
    pub qualification: usize,
}

/// Build 96 deterministic bridge-motif worlds at n=20.
/// Each of four modules has a triangle core and leaves constrained to its third
/// role. Two bridge edges per module pair leave three relative role maps. Four
/// cross-pair bridges fix the remaining relative map, yielding nine classes.
pub fn generate_batch() -> Result<StressBatch, StressError> {
    let mut worlds = Vec::with_capacity(BATCH_SIZE);
    let mut task_ids = HashSet::<String>::with_capacity(BATCH_SIZE);
    let mut total_solver_elapsed_ms = 0u128;
    let mut max_solver_elapsed_ms = 0u128;

    for index in 0..BATCH_SIZE {
        let n = N;
        let seed = candidate_seed(index);
        let candidate = build_candidate(seed, n)?;
        let (task, family_id) = candidate_task(&candidate);
        if !task_ids.insert(task.id.clone()) {
            return Err(StressError(format!(
                "duplicate generated task id {}",
                task.id
            )));
        }
        if !validate_independent(&task, &candidate.planted_roles) {
            return Err(StressError(format!(
                "planted assignment failed independent validation for {}",
                task.id
            )));
        }

        let started = Instant::now();
        let solutions = match enumerate_solutions(&task, SOLUTION_CAP) {
            Ok(solutions) => solutions,
            Err(SolveError::CapExceeded { found_at_least, .. }) => {
                return Err(StressError(format!(
                    "exact solution cap exceeded for {} at {found_at_least}",
                    task.id
                )))
            }
            Err(error) => {
                return Err(StressError(format!(
                    "exact solver rejected generated task {}: {error}",
                    task.id
                )))
            }
        };
        let elapsed_ms = started.elapsed().as_millis();
        total_solver_elapsed_ms += elapsed_ms;
        max_solver_elapsed_ms = max_solver_elapsed_ms.max(elapsed_ms);
        if elapsed_ms > MAX_WORLD_SOLVE_MS {
            return Err(StressError(format!(
                "exact solver budget exceeded for {}: {elapsed_ms}ms > {MAX_WORLD_SOLVE_MS}ms",
                task.id
            )));
        }

        for solution in &solutions {
            if !validate(&task, solution) || !validate_independent(&task, solution) {
                return Err(StressError(format!(
                    "solver solution failed a validator for {}",
                    task.id
                )));
            }
        }
        let role_group = automorphisms(&task);
        let mut classes = HashSet::<Vec<u8>>::with_capacity(solutions.len());
        for solution in &solutions {
            classes.insert(canonical_assignment(solution, &role_group));
        }
        let class_count = classes.len();
        if solutions.len() != EXPECTED_RAW_SOLUTIONS
            || class_count != EXPECTED_CANONICAL_CLASSES
            || role_group.len() != 6
        {
            return Err(StressError(format!(
                "bridge motif qualification changed for {}: raw={}, classes={}, role_automorphisms={}",
                task.id,
                solutions.len(),
                class_count,
                role_group.len()
            )));
        }

        let rendered = r1_world::render_task(&task, seed ^ 0x0053_5552_4641_4345);
        let possible_pairs = usize::from(n) * (usize::from(n) - 1) / 2;
        let record = WorldRecord {
            index,
            task_id: task.id.clone(),
            family_id: family_id.clone(),
            seed,
            n,
            k: K,
            role_anonymous: true,
            graph_recipe: "four triangle-core modules; paired two-edge relative-color locks",
            edge_count: candidate.edges.len(),
            all_pair_density: candidate.edges.len() as f64 / possible_pairs as f64,
            exact_count_status: "EXHAUSTED",
            raw_solution_count: solutions.len(),
            canonical_solution_class_count: class_count,
            role_automorphism_count: role_group.len(),
            independent_validator_checks: solutions.len(),
        };
        let private_diagnostics = PrivateDiagnostics {
            planted_assignment: candidate.planted_roles,
            module_anchors: candidate.module_anchors,
            raw_solution_count: solutions.len(),
            canonical_solution_class_count: class_count,
            role_automorphism_count: role_group.len(),
        };
        worlds.push(StressWorld {
            task,
            rendered,
            record,
            private_diagnostics,
        });
    }

    Ok(StressBatch {
        worlds,
        max_solver_elapsed_ms,
        total_solver_elapsed_ms,
    })
}

fn build_candidate(seed: u64, n: u16) -> Result<CandidateGraph, StressError> {
    if n != N || !n.is_multiple_of(4) {
        return Err(StressError(format!("unsupported bridge-motif size {n}")));
    }
    let module_size = usize::from(n) / 4;
    if module_size < 4 {
        return Err(StressError(format!(
            "module size {module_size} is too small"
        )));
    }

    let mut source_roles = vec![0u8; usize::from(n)];
    let mut source_anchors = [[0u16; 3]; 4];
    let mut edges = Vec::with_capacity(4 * (3 + 2 * (module_size - 3)) + 8);
    for (module, anchors) in source_anchors.iter_mut().enumerate() {
        let base = module * module_size;
        *anchors = [base as u16, (base + 1) as u16, (base + 2) as u16];
        source_roles[base] = 0;
        source_roles[base + 1] = 1;
        source_roles[base + 2] = 2;
        add_edge(&mut edges, base, base + 1);
        add_edge(&mut edges, base, base + 2);
        add_edge(&mut edges, base + 1, base + 2);
        for (leaf, role) in source_roles
            .iter_mut()
            .enumerate()
            .take(base + module_size)
            .skip(base + 3)
        {
            *role = 2;
            add_edge(&mut edges, base, leaf);
            add_edge(&mut edges, base + 1, leaf);
        }
    }
    for pair_start in [0usize, 2] {
        let left = pair_start * module_size;
        let right = (pair_start + 1) * module_size;
        add_edge(&mut edges, left, right + 1);
        add_edge(&mut edges, left + 1, right);
    }
    let first_module = 0usize;
    let third_module = 2 * module_size;
    for (left_role, right_role) in [(1usize, 0usize), (2, 1), (0, 2), (2, 0)] {
        add_edge(
            &mut edges,
            first_module + left_role,
            third_module + right_role,
        );
    }

    let mut rng = SplitMix64(seed);
    let mut new_to_old: Vec<usize> = (0..usize::from(n)).collect();
    rng.shuffle(&mut new_to_old);
    let mut old_to_new = vec![0u16; usize::from(n)];
    for (new, old) in new_to_old.into_iter().enumerate() {
        old_to_new[old] = new as u16;
    }

    let mut planted_roles = vec![0u8; usize::from(n)];
    for (old, role) in source_roles.into_iter().enumerate() {
        planted_roles[usize::from(old_to_new[old])] = role;
    }
    let mut module_anchors = [[0u16; 3]; 4];
    for (source, mapped) in source_anchors.iter().zip(module_anchors.iter_mut()) {
        for (source_anchor, mapped_anchor) in source.iter().zip(mapped.iter_mut()) {
            *mapped_anchor = old_to_new[usize::from(*source_anchor)];
        }
    }
    for (left, right) in &mut edges {
        *left = old_to_new[usize::from(*left)];
        *right = old_to_new[usize::from(*right)];
        if *left > *right {
            std::mem::swap(left, right);
        }
    }
    edges.sort_unstable();
    edges.dedup();
    rng.shuffle(&mut edges);

    Ok(CandidateGraph {
        seed,
        n,
        planted_roles,
        module_anchors,
        edges,
    })
}

fn add_edge(edges: &mut Vec<(u16, u16)>, left: usize, right: usize) {
    let left = left as u16;
    let right = right as u16;
    if left < right {
        edges.push((left, right));
    } else {
        edges.push((right, left));
    }
}

fn candidate_task(candidate: &CandidateGraph) -> (Task, String) {
    let clauses = candidate
        .edges
        .iter()
        .map(|(a, b)| Clause::Different { a: *a, b: *b })
        .collect();
    let hash = graph_hash(candidate.n, &candidate.edges);
    let family_id = format!("r1-stress-v04-{hash}");
    let task = Task {
        id: format!("stress-v04-n{}-{hash}", candidate.n),
        family_id: family_id.clone(),
        seed: candidate.seed,
        n: candidate.n,
        k: K,
        clauses,
        role_anonymous: true,
    };
    (task, family_id)
}

fn graph_hash(n: u16, edges: &[(u16, u16)]) -> String {
    let mut canonical_edges = edges.to_vec();
    canonical_edges.sort_unstable();
    let mut bytes = Vec::with_capacity(5 + canonical_edges.len() * 4);
    bytes.extend_from_slice(b"R1G4\x01");
    bytes.extend_from_slice(&n.to_le_bytes());
    bytes.push(K);
    for (left, right) in canonical_edges {
        bytes.extend_from_slice(&left.to_le_bytes());
        bytes.extend_from_slice(&right.to_le_bytes());
    }
    let digest = Sha256::digest(&bytes);
    digest[..12]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn candidate_seed(index: usize) -> u64 {
    BASE_SEED.wrapping_add((index as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15))
}

fn split_for_index(index: usize) -> &'static str {
    if index < SPLIT_TRAIN {
        "train"
    } else if index < SPLIT_TRAIN + SPLIT_VALIDATION {
        "validation"
    } else {
        "qualification"
    }
}

pub fn public_projection_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| &world.rendered.inference))
}

pub fn private_task_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| &world.task))
}

pub fn private_diagnostics_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| PrivateDiagnosticsRow {
        task_id: &world.task.id,
        family_id: &world.task.family_id,
        seed: world.task.seed,
        planted_assignment: &world.private_diagnostics.planted_assignment,
        module_anchors: &world.private_diagnostics.module_anchors,
        exact_count_status: world.record.exact_count_status,
        raw_solution_count: world.private_diagnostics.raw_solution_count,
        canonical_solution_class_count: world.private_diagnostics.canonical_solution_class_count,
        role_automorphism_count: world.private_diagnostics.role_automorphism_count,
    }))
}

fn jsonl_bytes<'a, T: Serialize + 'a>(
    rows: impl Iterator<Item = T>,
) -> Result<Vec<u8>, StressError> {
    let mut bytes = Vec::new();
    for row in rows {
        serde_json::to_writer(&mut bytes, &row)
            .map_err(|error| StressError(format!("serialize JSONL row: {error}")))?;
        bytes.push(b'\n');
    }
    Ok(bytes)
}

pub fn make_support_manifest<'a>(
    public_bytes: &[u8],
    worlds: &'a [StressWorld],
) -> SupportManifest<'a> {
    SupportManifest {
        schema: "R1_STAGE1_STRESS_SENSOR_SUPPORT_V04",
        status: "STRESS_TRAIN_VALIDATION_QUALIFICATION_READY",
        source: SupportSource {
            path: "public-tasks.jsonl",
            sha256: sha256_hex(public_bytes),
            bytes: public_bytes.len(),
            rows: worlds.len(),
        },
        family_roster: worlds
            .iter()
            .map(|world| FamilyRosterEntry {
                task_id: &world.task.id,
                family_id: &world.task.family_id,
                split: split_for_index(world.record.index),
            })
            .collect(),
        split_counts: SplitCounts {
            train: worlds
                .iter()
                .filter(|world| split_for_index(world.record.index) == "train")
                .count(),
            validation: worlds
                .iter()
                .filter(|world| split_for_index(world.record.index) == "validation")
                .count(),
            qualification: worlds
                .iter()
                .filter(|world| split_for_index(world.record.index) == "qualification")
                .count(),
        },
    }
}

pub fn public_tasks(worlds: &[StressWorld]) -> impl Iterator<Item = &InferenceTask> {
    worlds.iter().map(|world| &world.rendered.inference)
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct SplitMix64(u64);

impl SplitMix64 {
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }

    fn shuffle<T>(&mut self, values: &mut [T]) {
        for end in (1..values.len()).rev() {
            let index = (self.next_u64() as usize) % (end + 1);
            values.swap(end, index);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::OnceLock;

    fn fixture() -> &'static StressBatch {
        static BATCH: OnceLock<StressBatch> = OnceLock::new();
        BATCH.get_or_init(|| generate_batch().unwrap())
    }

    #[test]
    fn every_world_exhausts_exactly_54_solutions_and_nine_classes() {
        let batch = fixture();
        assert_eq!(batch.worlds.len(), BATCH_SIZE);
        assert_eq!(
            batch
                .worlds
                .iter()
                .filter(|world| world.task.n == 20)
                .count(),
            BATCH_SIZE
        );
        for world in &batch.worlds {
            assert_eq!(world.record.exact_count_status, "EXHAUSTED");
            assert_eq!(world.record.raw_solution_count, EXPECTED_RAW_SOLUTIONS);
            assert_eq!(
                world.record.canonical_solution_class_count,
                EXPECTED_CANONICAL_CLASSES
            );
            assert_eq!(world.record.role_automorphism_count, 6);
            assert_eq!(
                world.record.independent_validator_checks,
                EXPECTED_RAW_SOLUTIONS
            );
            assert_eq!(
                world.private_diagnostics.planted_assignment.len(),
                world.task.n as usize
            );
            assert!(validate(
                &world.task,
                &world.private_diagnostics.planted_assignment
            ));
            assert!(validate_independent(
                &world.task,
                &world.private_diagnostics.planted_assignment
            ));
        }
    }

    #[test]
    fn public_projection_has_no_private_solver_or_seed_fields() {
        let batch = fixture();
        let public = public_projection_bytes(&batch.worlds).unwrap();
        let forbidden = [
            b"\"seed\"".as_slice(),
            b"planted_assignment".as_slice(),
            b"raw_solution_count".as_slice(),
            b"canonical_solution_class_count".as_slice(),
            b"role_automorphism_count".as_slice(),
            b"exact_count_status".as_slice(),
        ];
        assert!(forbidden
            .iter()
            .all(|needle| !public.windows(needle.len()).any(|window| window == *needle)));
        let decoded: Vec<InferenceTask> = public
            .split(|byte| *byte == b'\n')
            .filter(|line| !line.is_empty())
            .map(|line| serde_json::from_slice(line).unwrap())
            .collect();
        assert_eq!(decoded.len(), BATCH_SIZE);
        assert!(decoded
            .iter()
            .all(|task| { !task.clauses.is_empty() && task.n == N }));
    }

    #[test]
    fn generation_and_receipt_inputs_are_byte_deterministic() {
        let first = fixture();
        let second = generate_batch().unwrap();
        assert_eq!(
            public_projection_bytes(&first.worlds).unwrap(),
            public_projection_bytes(&second.worlds).unwrap()
        );
        assert_eq!(
            private_task_bytes(&first.worlds).unwrap(),
            private_task_bytes(&second.worlds).unwrap()
        );
        assert_eq!(
            private_diagnostics_bytes(&first.worlds).unwrap(),
            private_diagnostics_bytes(&second.worlds).unwrap()
        );
        let first_public = public_projection_bytes(&first.worlds).unwrap();
        let second_public = public_projection_bytes(&second.worlds).unwrap();
        let first_manifest =
            serde_json::to_vec(&make_support_manifest(&first_public, &first.worlds)).unwrap();
        let second_manifest =
            serde_json::to_vec(&make_support_manifest(&second_public, &second.worlds)).unwrap();
        assert_eq!(first_manifest, second_manifest);
    }

    #[test]
    fn support_manifest_has_stratified_64_16_16_split_and_pins_public_bytes() {
        let batch = fixture();
        let public = public_projection_bytes(&batch.worlds).unwrap();
        let manifest = make_support_manifest(&public, &batch.worlds);
        assert_eq!(manifest.split_counts.train, 64);
        assert_eq!(manifest.split_counts.validation, 16);
        assert_eq!(manifest.split_counts.qualification, 16);
        assert_eq!(manifest.source.rows, BATCH_SIZE);
        assert_eq!(manifest.source.bytes, public.len());
        assert_eq!(manifest.source.sha256, sha256_hex(&public));
        assert_eq!(manifest.family_roster.len(), BATCH_SIZE);
        assert_eq!(
            manifest
                .family_roster
                .iter()
                .map(|entry| entry.task_id)
                .collect::<HashSet<_>>()
                .len(),
            BATCH_SIZE
        );
        assert_eq!(
            manifest
                .family_roster
                .iter()
                .map(|entry| entry.family_id)
                .collect::<HashSet<_>>()
                .len(),
            BATCH_SIZE
        );
        let splits: Vec<_> = (0..BATCH_SIZE).map(split_for_index).collect();
        assert_eq!(splits.iter().filter(|split| **split == "train").count(), 64);
        assert_eq!(
            splits
                .iter()
                .filter(|split| **split == "validation")
                .count(),
            16
        );
        assert_eq!(
            splits
                .iter()
                .filter(|split| **split == "qualification")
                .count(),
            16
        );
    }
}

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
const BASE_SEED: u64 = 0x5231_5354_5245_5353;
const MAX_ATTEMPTS_PER_WORLD: usize = 96;
const DENSITY_PROFILES: [&str; 4] = ["low", "mid_low", "mid_high", "high"];
const PROFILE_STARTS: [[u16; 4]; 3] = [
    [180, 280, 380, 480],
    [140, 230, 320, 410],
    [100, 180, 260, 340],
];
const SIZES: [u16; 3] = [14, 18, 20];

#[derive(Clone, Debug, PartialEq)]
pub struct StressWorld {
    pub task: Task,
    pub rendered: RenderedTask,
    pub record: WorldRecord,
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
    pub density_search_start_profile: String,
    pub profile_start_probability_permille: u16,
    pub cross_edge_probability_permille: u16,
    pub cross_pair_count: usize,
    pub edge_count: usize,
    pub all_pair_density: f64,
    pub attempts_to_accept: usize,
    pub exact_count_status: &'static str,
    pub raw_solution_count: usize,
    pub canonical_solution_class_count: usize,
    pub role_automorphism_count: usize,
    pub independent_validator_checks: usize,
    pub solve_elapsed_ms: u128,
}

#[derive(Clone, Debug, PartialEq)]
pub struct StressBatch {
    pub worlds: Vec<StressWorld>,
    pub attempts: usize,
    pub rejected_too_many: usize,
    pub rejected_too_few: usize,
}

#[derive(Clone, Debug, PartialEq)]
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
    probability_permille: u16,
    planted_roles: Vec<u8>,
    edges: Vec<(u16, u16)>,
    cross_pair_count: usize,
}

struct WorldRecordInput<'a> {
    index: usize,
    task: &'a Task,
    family_id: String,
    profile: &'a str,
    profile_start_probability_permille: u16,
    candidate: &'a CandidateGraph,
    attempts: usize,
    raw_solution_count: usize,
    canonical_solution_class_count: usize,
    role_automorphism_count: usize,
    solve_elapsed_ms: u128,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum Qualification {
    Accepted {
        solutions: Vec<Vec<u8>>,
        classes: usize,
        automorphisms: usize,
        elapsed_ms: u128,
    },
    TooMany {
        found_at_least: usize,
        elapsed_ms: u128,
    },
    TooFew {
        raw_solutions: usize,
        classes: usize,
        elapsed_ms: u128,
    },
    TooManyClasses {
        raw_solutions: usize,
        classes: usize,
        elapsed_ms: u128,
    },
}

/// Generate 96 deterministically seeded graph-coloring worlds, 32 per size.
/// Every accepted graph is planted 3-colorable and has 5-16 exact colorings
/// after role-label automorphisms are quotiented out. Eight worlds per size
/// begin from each density-search profile.
pub fn generate_batch() -> Result<StressBatch, StressError> {
    let mut worlds = Vec::with_capacity(BATCH_SIZE);
    let mut ids = HashSet::<String>::with_capacity(BATCH_SIZE);
    let mut total_attempts = 0usize;
    let mut rejected_too_many = 0usize;
    let mut rejected_too_few = 0usize;

    for index in 0..BATCH_SIZE {
        let size_index = index / 32;
        let profile_index = index % DENSITY_PROFILES.len();
        let n = SIZES[size_index];
        let profile = DENSITY_PROFILES[profile_index];
        let mut lower = 25u16;
        let mut upper = 975u16;
        let mut probability = PROFILE_STARTS[size_index][profile_index];
        let profile_start_probability_permille = probability;
        let mut accepted = None;

        for attempt in 0..MAX_ATTEMPTS_PER_WORLD {
            let seed = candidate_seed(index, attempt);
            let candidate = sample_candidate(seed, n, probability);
            let (task, family_id) = candidate_task(&candidate);
            if !validate_independent(&task, &candidate.planted_roles) {
                return Err(StressError(format!(
                    "planted assignment failed independent validation for {}",
                    task.id
                )));
            }
            let qualification = qualify(&task, SOLUTION_CAP)?;
            total_attempts += 1;

            match qualification {
                Qualification::Accepted {
                    solutions,
                    classes,
                    automorphisms: automorphism_count,
                    elapsed_ms,
                } => {
                    let id = task.id.clone();
                    if ids.insert(id.clone()) {
                        let rendered = r1_world::render_task(&task, seed ^ 0x0053_5552_4641_4345);
                        let record = world_record(WorldRecordInput {
                            index,
                            task: &task,
                            family_id,
                            profile,
                            profile_start_probability_permille,
                            candidate: &candidate,
                            attempts: attempt + 1,
                            raw_solution_count: solutions.len(),
                            canonical_solution_class_count: classes,
                            role_automorphism_count: automorphism_count,
                            solve_elapsed_ms: elapsed_ms,
                        });
                        accepted = Some(StressWorld {
                            task,
                            rendered,
                            record,
                        });
                        break;
                    }
                    probability = midpoint(lower, upper);
                }
                Qualification::TooMany {
                    elapsed_ms: _,
                    found_at_least: _,
                } => {
                    rejected_too_many += 1;
                    lower = probability;
                    probability = midpoint(lower, upper);
                }
                Qualification::TooFew {
                    raw_solutions: _,
                    classes: _,
                    elapsed_ms: _,
                } => {
                    rejected_too_few += 1;
                    upper = probability;
                    probability = midpoint(lower, upper);
                }
                Qualification::TooManyClasses {
                    raw_solutions: _,
                    classes: _,
                    elapsed_ms: _,
                } => {
                    rejected_too_many += 1;
                    lower = probability;
                    probability = midpoint(lower, upper);
                }
            }

            if probability <= lower || probability >= upper {
                probability = fallback_probability(index, attempt, lower, upper);
            }
        }

        let world = accepted.ok_or_else(|| {
            StressError(format!(
                "could not accept n={n} profile={profile} after {MAX_ATTEMPTS_PER_WORLD} exact candidates"
            ))
        })?;
        worlds.push(world);
    }

    Ok(StressBatch {
        worlds,
        attempts: total_attempts,
        rejected_too_many,
        rejected_too_few,
    })
}

fn midpoint(left: u16, right: u16) -> u16 {
    left + (right.saturating_sub(left) / 2)
}

fn fallback_probability(index: usize, attempt: usize, lower: u16, upper: u16) -> u16 {
    let span = upper.saturating_sub(lower).max(2);
    let offset = ((index * 97 + attempt * 53) as u16) % span;
    (lower + 1 + offset).clamp(26, 974)
}

fn candidate_seed(index: usize, attempt: usize) -> u64 {
    BASE_SEED
        .wrapping_add((index as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15))
        .wrapping_add((attempt as u64).wrapping_mul(0xbf58_476d_1ce4_e5b9))
}

fn sample_candidate(seed: u64, n: u16, probability_permille: u16) -> CandidateGraph {
    let mut rng = SplitMix64(seed);
    let mut planted_roles: Vec<u8> = (0..usize::from(n))
        .map(|entity| (entity % usize::from(K)) as u8)
        .collect();
    rng.shuffle(&mut planted_roles);

    let mut edges = Vec::new();
    let mut cross_pair_count = 0usize;
    for left in 0..usize::from(n) {
        for right in (left + 1)..usize::from(n) {
            if planted_roles[left] == planted_roles[right] {
                continue;
            }
            cross_pair_count += 1;
            if rng.next_u64() % 1000 < u64::from(probability_permille) {
                edges.push((left as u16, right as u16));
            }
        }
    }

    CandidateGraph {
        seed,
        n,
        probability_permille,
        planted_roles,
        edges,
        cross_pair_count,
    }
}

fn candidate_task(candidate: &CandidateGraph) -> (Task, String) {
    let clauses: Vec<Clause> = candidate
        .edges
        .iter()
        .map(|(a, b)| Clause::Different { a: *a, b: *b })
        .collect();
    let graph_hash = graph_hash(candidate.n, &candidate.edges);
    let family_id = format!("r1-stress-color-{graph_hash}");
    let task = Task {
        id: format!("stress-n{}-{graph_hash}", candidate.n),
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
    let mut bytes = Vec::with_capacity(4 + edges.len() * 4);
    bytes.extend_from_slice(b"R1GC\x01");
    bytes.extend_from_slice(&n.to_le_bytes());
    bytes.push(K);
    for (left, right) in edges {
        bytes.extend_from_slice(&left.to_le_bytes());
        bytes.extend_from_slice(&right.to_le_bytes());
    }
    let digest = Sha256::digest(&bytes);
    digest[..12]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn qualify(task: &Task, cap: usize) -> Result<Qualification, StressError> {
    let started = Instant::now();
    let solutions = match enumerate_solutions(task, cap) {
        Ok(solutions) => solutions,
        Err(SolveError::CapExceeded { found_at_least, .. }) => {
            return Ok(Qualification::TooMany {
                found_at_least,
                elapsed_ms: started.elapsed().as_millis(),
            });
        }
        Err(error) => {
            return Err(StressError(format!(
                "exact solver rejected generated task: {error}"
            )))
        }
    };

    for solution in &solutions {
        if !validate(task, solution) || !validate_independent(task, solution) {
            return Err(StressError(format!(
                "solver returned an assignment rejected by an independent validator for {}",
                task.id
            )));
        }
    }

    let group = automorphisms(task);
    let mut classes = HashSet::<Vec<u8>>::with_capacity(solutions.len());
    for solution in &solutions {
        classes.insert(canonical_assignment(solution, &group));
    }
    let class_count = classes.len();
    let elapsed_ms = started.elapsed().as_millis();
    if (5..=16).contains(&class_count) {
        Ok(Qualification::Accepted {
            solutions,
            classes: class_count,
            automorphisms: group.len(),
            elapsed_ms,
        })
    } else if class_count < 5 {
        Ok(Qualification::TooFew {
            raw_solutions: solutions.len(),
            classes: class_count,
            elapsed_ms,
        })
    } else {
        Ok(Qualification::TooManyClasses {
            raw_solutions: solutions.len(),
            classes: class_count,
            elapsed_ms,
        })
    }
}

fn world_record(input: WorldRecordInput<'_>) -> WorldRecord {
    let possible_pairs = usize::from(input.candidate.n) * (usize::from(input.candidate.n) - 1) / 2;
    WorldRecord {
        index: input.index,
        task_id: input.task.id.clone(),
        family_id: input.family_id,
        seed: input.candidate.seed,
        n: input.task.n,
        k: input.task.k,
        role_anonymous: input.task.role_anonymous,
        density_search_start_profile: input.profile.to_owned(),
        profile_start_probability_permille: input.profile_start_probability_permille,
        cross_edge_probability_permille: input.candidate.probability_permille,
        cross_pair_count: input.candidate.cross_pair_count,
        edge_count: input.candidate.edges.len(),
        all_pair_density: input.candidate.edges.len() as f64 / possible_pairs as f64,
        attempts_to_accept: input.attempts,
        exact_count_status: "EXHAUSTED",
        raw_solution_count: input.raw_solution_count,
        canonical_solution_class_count: input.canonical_solution_class_count,
        role_automorphism_count: input.role_automorphism_count,
        independent_validator_checks: input.raw_solution_count,
        solve_elapsed_ms: input.solve_elapsed_ms,
    }
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

pub fn public_projection_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| &world.rendered.inference))
}

pub fn private_task_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| &world.task))
}

fn jsonl_bytes<'a, T: Serialize + 'a>(
    rows: impl Iterator<Item = &'a T>,
) -> Result<Vec<u8>, StressError> {
    let mut bytes = Vec::new();
    for row in rows {
        serde_json::to_writer(&mut bytes, row)
            .map_err(|error| StressError(format!("serialize JSONL row: {error}")))?;
        bytes.push(b'\n');
    }
    Ok(bytes)
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

pub fn make_support_manifest<'a>(
    public_bytes: &[u8],
    worlds: &'a [StressWorld],
) -> SupportManifest<'a> {
    SupportManifest {
        schema: "R1_STAGE1_STRESS_SENSOR_SUPPORT_V03",
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
                split: split_for_world(world),
            })
            .collect(),
        split_counts: SplitCounts {
            train: worlds
                .iter()
                .filter(|world| split_for_world(world) == "train")
                .count(),
            validation: worlds
                .iter()
                .filter(|world| split_for_world(world) == "validation")
                .count(),
            qualification: worlds
                .iter()
                .filter(|world| split_for_world(world) == "qualification")
                .count(),
        },
    }
}

fn split_for_world(world: &StressWorld) -> &'static str {
    let within_size = world.record.index % 32;
    match world.record.n {
        14 | 18 if within_size < 21 => "train",
        14 | 18 if within_size < 26 => "validation",
        14 | 18 => "qualification",
        20 if within_size < 22 => "train",
        20 if within_size < 28 => "validation",
        20 => "qualification",
        _ => "qualification",
    }
}

pub fn public_tasks(worlds: &[StressWorld]) -> impl Iterator<Item = &InferenceTask> {
    worlds.iter().map(|world| &world.rendered.inference)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct SplitMix64(u64);

impl SplitMix64 {
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^ (z >> 31)
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

    #[test]
    fn planted_candidates_are_deterministic_and_use_only_different_clauses() {
        let first = sample_candidate(0x1234, 20, 320);
        let replay = sample_candidate(0x1234, 20, 320);
        assert_eq!(first, replay);
        assert!(first.edges.len() < first.cross_pair_count);
        let (task, _) = candidate_task(&first);
        assert!(task.role_anonymous);
        assert_eq!(task.k, K);
        assert!(task
            .clauses
            .iter()
            .all(|clause| matches!(clause, Clause::Different { .. })));
        assert!(validate_independent(&task, &first.planted_roles));
    }

    #[test]
    fn exact_qualification_keeps_five_to_sixteen_role_anonymous_classes() {
        let task = Task {
            id: "fixture-triangle-with-isolates".to_owned(),
            family_id: "fixture-triangle-with-isolates".to_owned(),
            seed: 7,
            n: 5,
            k: 3,
            clauses: vec![
                Clause::Different { a: 0, b: 1 },
                Clause::Different { a: 0, b: 2 },
                Clause::Different { a: 1, b: 2 },
            ],
            role_anonymous: true,
        };
        let result = qualify(&task, SOLUTION_CAP).unwrap();
        match result {
            Qualification::Accepted {
                solutions,
                classes,
                automorphisms,
                ..
            } => {
                assert_eq!(solutions.len(), 54);
                assert_eq!(classes, 9);
                assert_eq!(automorphisms, 6);
                assert!(solutions
                    .iter()
                    .all(|solution| validate_independent(&task, solution)));
            }
            other => panic!("expected exact qualification, got {other:?}"),
        }
    }

    #[test]
    fn public_and_support_rows_share_exact_ids_and_qualification_counts() {
        let candidate = sample_candidate(0x4321, 5, 1000);
        let (task, _) = candidate_task(&candidate);
        let task = Task {
            clauses: vec![Clause::Different { a: 0, b: 1 }],
            ..task
        };
        let rendered = r1_world::render_task(&task, 88);
        let world = StressWorld {
            record: world_record(WorldRecordInput {
                index: 0,
                task: &task,
                family_id: task.family_id.clone(),
                profile: "low",
                profile_start_probability_permille: 100,
                candidate: &candidate,
                attempts: 1,
                raw_solution_count: 6,
                canonical_solution_class_count: 1,
                role_automorphism_count: 6,
                solve_elapsed_ms: 0,
            }),
            task,
            rendered,
        };
        let worlds = [world];
        let public = public_projection_bytes(&worlds).unwrap();
        let decoded: InferenceTask = serde_json::from_slice(&public[..public.len() - 1]).unwrap();
        assert_eq!(decoded.id, worlds[0].task.id);
        assert!(!public
            .windows(b"seed".len())
            .any(|window| window == b"seed"));
        let manifest = make_support_manifest(&public, &worlds);
        assert_eq!(manifest.family_roster.len(), 1);
        assert_eq!(manifest.family_roster[0].split, "qualification");
        assert_eq!(manifest.split_counts.qualification, 1);
        assert_eq!(manifest.source.rows, 1);
        assert_eq!(manifest.source.bytes, public.len());
    }
}

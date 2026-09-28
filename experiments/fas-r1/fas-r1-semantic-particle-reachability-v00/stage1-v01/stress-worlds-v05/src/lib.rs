use std::time::Instant;

use hashbrown::HashSet;
use r1_world::{
    automorphisms, canonical_assignment, enumerate_solutions, validate, validate_independent,
    Clause, RenderedTask, SolveError, Task,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
mod artifacts;
mod rng;

pub use artifacts::{
    make_support_manifest, private_diagnostics_bytes, private_task_bytes, public_projection_bytes,
    public_search_starts_bytes, sha256_hex, ConfigSource, FamilyRosterEntry, ScenarioCounts,
    SearchStartRow, SearchStartSource, SplitCounts, SupportManifest, SupportSource,
};
use rng::{parse_hex_u64, SplitMix64};

pub const BATCH_SIZE: usize = 96;
pub const N: u16 = 20;
pub const K: u8 = 3;
pub const WORLD_SIZE: usize = 24;
pub const MODULE_COUNT: usize = 4;
pub const MODULE_SIZE: usize = 5;
pub const EXPECTED_RAW_SOLUTIONS: usize = 54;
pub const EXPECTED_CANONICAL_CLASSES: usize = 9;
pub const EXPECTED_ROLE_AUTOMORPHISMS: usize = 6;
pub const EXPECTED_DECOY_CONFLICTS: usize = 2;
pub const EXPECTED_DENSE_EXTRA_EDGES: usize = 10;

pub const UNDERLYING_WORLDS: usize = 24;
pub const VARIANTS_PER_WORLD: usize = 4;
const SPLIT_TRAIN_SEEDS: usize = 16;
const SPLIT_VALIDATION_SEEDS: usize = 4;
const SCENARIO_IDS: [&str; 4] = [
    "base-random",
    "base-swap-trap",
    "dense-random",
    "dense-swap-trap",
];
const ROLE_SWAP_01: [u8; 3] = [1, 0, 2];
const RANDOM_START_KIND: &str = "independent_random_assignment";
const DECOY_START_KIND: &str = "witness_module1_swap_trap";

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GeneratorConfig {
    pub schema: String,
    pub batch_size: usize,
    pub n: u16,
    pub k: u8,
    pub seed_base: String,
    pub seed_stride: String,
    pub initial_state_seed_tag: String,
    pub split_counts: ConfigSplitCounts,
    pub solution_cap: usize,
    pub expected_raw_solutions: usize,
    pub expected_canonical_classes: usize,
    pub expected_role_automorphisms: usize,
    pub max_world_solve_ms: u128,
    pub underlying_worlds: usize,
    pub scenarios: Vec<ScenarioConfig>,
    pub dense_overlay: DenseOverlayConfig,
    pub decoy: DecoyConfig,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ConfigSplitCounts {
    pub train: usize,
    pub validation: usize,
    pub qualification: usize,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ScenarioConfig {
    pub id: String,
    pub density_level: String,
    pub start_kind: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DenseOverlayConfig {
    pub left_module: usize,
    pub right_module: usize,
    pub expected_extra_edges: usize,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DecoyConfig {
    pub module: usize,
    pub role_permutation: [u8; 3],
    pub expected_conflicts: usize,
    pub one_edit_repair_conflicts: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct WorldRecord {
    pub index: usize,
    pub task_id: String,
    pub family_id: String,
    pub paired_world_id: String,
    pub scenario_id: String,
    pub density_level: String,
    pub start_kind: String,
    pub split: &'static str,
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
    pub decoy_conflict_count: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PrivateDiagnostics {
    pub planted_assignment: Vec<u8>,
    pub module_anchors: [[u16; 3]; MODULE_COUNT],
    pub decoy_conflict_clause_indices: Vec<usize>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct StressWorld {
    pub task: Task,
    pub rendered: RenderedTask,
    pub search_start: SearchStartRow,
    pub record: WorldRecord,
    pub private_diagnostics: PrivateDiagnostics,
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
    module_anchors: [[u16; 3]; MODULE_COUNT],
    module_entities: [[u16; MODULE_SIZE]; MODULE_COUNT],
    edges: Vec<(u16, u16)>,
}

pub fn load_config(bytes: &[u8]) -> Result<GeneratorConfig, StressError> {
    let config: GeneratorConfig = serde_json::from_slice(bytes)
        .map_err(|error| StressError(format!("parse v05 config: {error}")))?;
    validate_config(&config)?;
    Ok(config)
}

pub fn validate_config(config: &GeneratorConfig) -> Result<(), StressError> {
    if config.schema != "R1_STAGE1_STRESS_CONFIG_V05"
        || config.batch_size != BATCH_SIZE
        || config.n != N
        || config.k != K
        || config.underlying_worlds != UNDERLYING_WORLDS
        || config.solution_cap < EXPECTED_RAW_SOLUTIONS
        || config.expected_raw_solutions != EXPECTED_RAW_SOLUTIONS
        || config.expected_canonical_classes != EXPECTED_CANONICAL_CLASSES
        || config.expected_role_automorphisms != EXPECTED_ROLE_AUTOMORPHISMS
        || config.max_world_solve_ms == 0
        || config.split_counts.train != 64
        || config.split_counts.validation != 16
        || config.split_counts.qualification != 16
    {
        return Err(StressError(
            "v05 config violates the frozen roster/solver contract".into(),
        ));
    }
    let ids: Vec<_> = config
        .scenarios
        .iter()
        .map(|scenario| scenario.id.as_str())
        .collect();
    if ids != SCENARIO_IDS {
        return Err(StressError(
            "v05 scenarios must be ordered base-random, base-swap-trap, dense-random, dense-swap-trap".into(),
        ));
    }
    let expected_factors = [
        ("base", RANDOM_START_KIND),
        ("base", DECOY_START_KIND),
        ("dense", RANDOM_START_KIND),
        ("dense", DECOY_START_KIND),
    ];
    if config
        .scenarios
        .iter()
        .zip(expected_factors)
        .any(|(scenario, expected)| {
            (
                scenario.density_level.as_str(),
                scenario.start_kind.as_str(),
            ) != expected
        })
    {
        return Err(StressError(
            "v05 scenarios do not match the density-by-start-policy factorial".into(),
        ));
    }
    if config.dense_overlay.left_module != 0
        || config.dense_overlay.right_module != 2
        || config.dense_overlay.expected_extra_edges != EXPECTED_DENSE_EXTRA_EDGES
        || config.decoy.module != 1
        || config.decoy.role_permutation != ROLE_SWAP_01
        || config.decoy.expected_conflicts != EXPECTED_DECOY_CONFLICTS
        || config.decoy.one_edit_repair_conflicts != EXPECTED_DECOY_CONFLICTS
    {
        return Err(StressError("v05 density or decoy contract changed".into()));
    }
    if config.underlying_worlds * config.scenarios.len() != config.batch_size
        || config.scenarios.len() != VARIANTS_PER_WORLD
        || SPLIT_TRAIN_SEEDS + SPLIT_VALIDATION_SEEDS + 4 != config.underlying_worlds
    {
        return Err(StressError(
            "v05 paired-seed split or 2x2 roster size changed".into(),
        ));
    }
    parse_hex_u64(&config.seed_base)?;
    parse_hex_u64(&config.seed_stride)?;
    parse_hex_u64(&config.initial_state_seed_tag)?;
    Ok(())
}

pub fn generate_batch(config: &GeneratorConfig) -> Result<StressBatch, StressError> {
    validate_config(config)?;
    let seed_base = parse_hex_u64(&config.seed_base)?;
    let seed_stride = parse_hex_u64(&config.seed_stride)?;
    let start_seed_tag = parse_hex_u64(&config.initial_state_seed_tag)?;
    let mut worlds = Vec::with_capacity(config.batch_size);
    let mut ids = HashSet::<String>::with_capacity(config.batch_size);
    let mut family_ids = HashSet::<String>::with_capacity(config.batch_size);
    let mut max_solver_elapsed_ms = 0u128;
    let mut total_solver_elapsed_ms = 0u128;

    for pair_index in 0..config.underlying_worlds {
        let world_seed = seed_base.wrapping_add((pair_index as u64).wrapping_mul(seed_stride));
        let paired_world_id = paired_world_id(world_seed);
        let split = split_for_seed(pair_index);
        let initialization_seed = world_seed ^ start_seed_tag;
        let random_assignment = random_start_assignment(initialization_seed, config.n, config.k);

        for (variant_index, scenario) in config.scenarios.iter().enumerate() {
            let index = pair_index * VARIANTS_PER_WORLD + variant_index;
            let candidate = build_candidate(world_seed, config, scenario.density_level == "dense")?;
            let task = candidate_task(&candidate, scenario);
            if !ids.insert(task.id.clone()) || !family_ids.insert(task.family_id.clone()) {
                return Err(StressError(format!(
                    "duplicate v05 task/family id for {}",
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
            let solutions = match enumerate_solutions(&task, config.solution_cap) {
                Ok(solutions) => solutions,
                Err(SolveError::CapExceeded { found_at_least, .. }) => {
                    return Err(StressError(format!(
                        "exact cap exceeded for {} at {found_at_least}",
                        task.id
                    )));
                }
                Err(error) => {
                    return Err(StressError(format!("solver rejected {}: {error}", task.id)))
                }
            };
            let elapsed_ms = started.elapsed().as_millis();
            total_solver_elapsed_ms += elapsed_ms;
            max_solver_elapsed_ms = max_solver_elapsed_ms.max(elapsed_ms);
            if elapsed_ms > config.max_world_solve_ms {
                return Err(StressError(format!(
                    "solver budget exceeded for {}: {elapsed_ms} ms",
                    task.id
                )));
            }
            for solution in &solutions {
                if !validate(&task, solution) || !validate_independent(&task, solution) {
                    return Err(StressError(format!(
                        "solution failed an independent validator for {}",
                        task.id
                    )));
                }
            }
            let role_group = automorphisms(&task);
            let classes: HashSet<Vec<u8>> = solutions
                .iter()
                .map(|solution| canonical_assignment(solution, &role_group))
                .collect();
            if solutions.len() != config.expected_raw_solutions
                || classes.len() != config.expected_canonical_classes
                || role_group.len() != config.expected_role_automorphisms
            {
                return Err(StressError(format!(
                    "v05 exact class contract changed for {}: raw={}, classes={}, automorphisms={}",
                    task.id,
                    solutions.len(),
                    classes.len(),
                    role_group.len()
                )));
            }

            let (start_assignment, start_kind, start_seed, decoy_conflicts) =
                if scenario.start_kind == DECOY_START_KIND {
                    let decoy = make_bridge_swap_decoy(
                        &candidate,
                        config.decoy.module,
                        config.decoy.role_permutation,
                    );
                    let conflicts = different_conflict_indices(&task, &decoy);
                    validate_decoy(&task, &candidate, &decoy, &conflicts, config)?;
                    (decoy, DECOY_START_KIND, None, conflicts)
                } else {
                    (
                        random_assignment.clone(),
                        RANDOM_START_KIND,
                        Some(initialization_seed),
                        Vec::new(),
                    )
                };
            if start_assignment.len() != usize::from(config.n)
                || start_assignment.iter().any(|role| *role >= config.k)
            {
                return Err(StressError(format!(
                    "invalid public start assignment for {}",
                    task.id
                )));
            }
            let search_start = SearchStartRow::new(
                task.id.clone(),
                task.family_id.clone(),
                paired_world_id.clone(),
                scenario.density_level.clone(),
                start_kind,
                config.n,
                config.k,
                start_seed,
                start_assignment,
            );
            let rendered = r1_world::render_task(&task, world_seed ^ 0x0053_5552_4641_4345);
            let possible_pairs = usize::from(task.n) * (usize::from(task.n) - 1) / 2;
            let family_id = task.family_id.clone();
            let record = WorldRecord {
                index,
                task_id: task.id.clone(),
                family_id,
                paired_world_id: paired_world_id.clone(),
                scenario_id: scenario.id.clone(),
                density_level: scenario.density_level.clone(),
                start_kind: start_kind.to_owned(),
                split,
                seed: world_seed,
                n: task.n,
                k: task.k,
                role_anonymous: true,
                graph_recipe: recipe_for(&scenario.density_level),
                edge_count: candidate.edges.len(),
                all_pair_density: candidate.edges.len() as f64 / possible_pairs as f64,
                exact_count_status: "EXHAUSTED",
                raw_solution_count: solutions.len(),
                canonical_solution_class_count: classes.len(),
                role_automorphism_count: role_group.len(),
                independent_validator_checks: solutions.len(),
                decoy_conflict_count: decoy_conflicts.len(),
            };
            worlds.push(StressWorld {
                task,
                rendered,
                search_start,
                record,
                private_diagnostics: PrivateDiagnostics {
                    planted_assignment: candidate.planted_roles,
                    module_anchors: candidate.module_anchors,
                    decoy_conflict_clause_indices: decoy_conflicts,
                },
            });
        }
    }

    if worlds.len() != config.batch_size {
        return Err(StressError(format!(
            "generated {} worlds; expected {}",
            worlds.len(),
            config.batch_size
        )));
    }
    validate_pair_splits(&worlds, config)?;
    Ok(StressBatch {
        worlds,
        max_solver_elapsed_ms,
        total_solver_elapsed_ms,
    })
}

fn build_candidate(
    seed: u64,
    config: &GeneratorConfig,
    dense_overlay: bool,
) -> Result<CandidateGraph, StressError> {
    let module_size = usize::from(config.n) / MODULE_COUNT;
    if config.n as usize != MODULE_COUNT * MODULE_SIZE || module_size != MODULE_SIZE {
        return Err(StressError(
            "v05 only supports the frozen four-module n=20 shape".into(),
        ));
    }
    let mut source_roles = vec![0u8; usize::from(config.n)];
    let mut source_anchors = [[0u16; 3]; MODULE_COUNT];
    let mut source_entities = [[0u16; MODULE_SIZE]; MODULE_COUNT];
    let mut edges = Vec::with_capacity(if dense_overlay { 46 } else { 36 });
    for (module, (anchors, entities)) in source_anchors
        .iter_mut()
        .zip(source_entities.iter_mut())
        .enumerate()
    {
        let base = module * module_size;
        *anchors = [base as u16, (base + 1) as u16, (base + 2) as u16];
        for (offset, entity) in entities.iter_mut().enumerate() {
            *entity = (base + offset) as u16;
        }
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
    for (left_role, right_role) in [(1usize, 0usize), (2, 1), (0, 2), (2, 0)] {
        add_edge(&mut edges, left_role, 2 * module_size + right_role);
    }

    if dense_overlay {
        let mut added = 0;
        for left in source_entities[config.dense_overlay.left_module] {
            for right in source_entities[config.dense_overlay.right_module] {
                if source_roles[usize::from(left)] != source_roles[usize::from(right)]
                    && !edges.contains(&(left.min(right), left.max(right)))
                {
                    add_edge(&mut edges, usize::from(left), usize::from(right));
                    added += 1;
                }
            }
        }
        if added != config.dense_overlay.expected_extra_edges {
            return Err(StressError(format!(
                "dense overlay added {added} edges, expected {}",
                config.dense_overlay.expected_extra_edges
            )));
        }
    }

    let mut rng = SplitMix64::new(seed);
    let mut new_to_old: Vec<usize> = (0..usize::from(config.n)).collect();
    rng.shuffle(&mut new_to_old);
    let mut old_to_new = vec![0u16; usize::from(config.n)];
    for (new, old) in new_to_old.into_iter().enumerate() {
        old_to_new[old] = new as u16;
    }
    let mut planted_roles = vec![0u8; usize::from(config.n)];
    for (old, role) in source_roles.into_iter().enumerate() {
        planted_roles[usize::from(old_to_new[old])] = role;
    }
    let mut module_anchors = [[0u16; 3]; MODULE_COUNT];
    let mut module_entities = [[0u16; MODULE_SIZE]; MODULE_COUNT];
    for module in 0..MODULE_COUNT {
        for offset in 0..3 {
            module_anchors[module][offset] =
                old_to_new[usize::from(source_anchors[module][offset])];
        }
        for offset in 0..MODULE_SIZE {
            module_entities[module][offset] =
                old_to_new[usize::from(source_entities[module][offset])];
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
        n: config.n,
        planted_roles,
        module_anchors,
        module_entities,
        edges,
    })
}

fn candidate_task(candidate: &CandidateGraph, scenario: &ScenarioConfig) -> Task {
    let clauses = candidate
        .edges
        .iter()
        .map(|(a, b)| Clause::Different { a: *a, b: *b })
        .collect();
    let graph = graph_hash(candidate.n, &candidate.edges);
    let mut hasher = Sha256::new();
    hasher.update(b"R1V05TASK\x01");
    hasher.update(graph.as_bytes());
    hasher.update([0]);
    hasher.update(scenario.id.as_bytes());
    let digest = hasher.finalize();
    let identity: String = digest[..12]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Task {
        id: format!("stress-v05-n{}-{identity}", candidate.n),
        family_id: format!("r1-stress-v05-{identity}"),
        seed: candidate.seed,
        n: candidate.n,
        k: K,
        clauses,
        role_anonymous: true,
    }
}

fn make_bridge_swap_decoy(
    candidate: &CandidateGraph,
    module: usize,
    permutation: [u8; 3],
) -> Vec<u8> {
    let mut assignment = candidate.planted_roles.clone();
    for entity in candidate.module_entities[module] {
        let index = usize::from(entity);
        assignment[index] = permutation[usize::from(assignment[index])];
    }
    assignment
}

fn validate_decoy(
    task: &Task,
    candidate: &CandidateGraph,
    decoy: &[u8],
    conflicts: &[usize],
    config: &GeneratorConfig,
) -> Result<(), StressError> {
    if decoy.len() != usize::from(task.n)
        || validate(task, decoy)
        || validate_independent(task, decoy)
        || conflicts.len() != config.decoy.expected_conflicts
        || conflicts
            .iter()
            .any(|index| !matches!(task.clauses[*index], Clause::Different { .. }))
    {
        return Err(StressError(format!(
            "decoy contract failed for {}",
            task.id
        )));
    }
    let anchors = candidate.module_anchors[config.decoy.module];
    for entity in anchors.into_iter().take(2) {
        let mut one_edit = decoy.to_vec();
        one_edit[usize::from(entity)] = candidate.planted_roles[usize::from(entity)];
        if different_conflict_indices(task, &one_edit).len()
            != config.decoy.one_edit_repair_conflicts
        {
            return Err(StressError(format!(
                "decoy is not a two-conflict one-edit plateau for {}",
                task.id
            )));
        }
    }
    Ok(())
}

pub fn different_conflict_indices(task: &Task, assignment: &[u8]) -> Vec<usize> {
    task.clauses
        .iter()
        .enumerate()
        .filter_map(|(index, clause)| match clause {
            Clause::Different { a, b }
                if assignment.get(usize::from(*a)) == assignment.get(usize::from(*b)) =>
            {
                Some(index)
            }
            _ => None,
        })
        .collect()
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

fn graph_hash(n: u16, edges: &[(u16, u16)]) -> String {
    let mut canonical_edges = edges.to_vec();
    canonical_edges.sort_unstable();
    let mut bytes = Vec::with_capacity(5 + canonical_edges.len() * 4);
    bytes.extend_from_slice(b"R1G5\x01");
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

fn split_for_seed(index: usize) -> &'static str {
    if index < SPLIT_TRAIN_SEEDS {
        "train"
    } else if index < SPLIT_TRAIN_SEEDS + SPLIT_VALIDATION_SEEDS {
        "validation"
    } else {
        "qualification"
    }
}

fn recipe_for(density_level: &str) -> &'static str {
    match density_level {
        "base" => "v05 four-module bridge base",
        "dense" => "v05 base plus ten implied module-0/module-2 edges",
        _ => "invalid-density-level",
    }
}

fn paired_world_id(seed: u64) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"R1V05PAIR\x01");
    hasher.update(seed.to_le_bytes());
    let digest = hasher.finalize();
    let suffix: String = digest[..12]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    format!("r1-stress-v05-pair-{suffix}")
}

fn random_start_assignment(seed: u64, n: u16, k: u8) -> Vec<u8> {
    let mut rng = SplitMix64::new(seed);
    (0..n).map(|_| rng.bounded(u64::from(k)) as u8).collect()
}

fn validate_pair_splits(
    worlds: &[StressWorld],
    config: &GeneratorConfig,
) -> Result<(), StressError> {
    let mut by_pair =
        hashbrown::HashMap::<&str, Vec<&StressWorld>>::with_capacity(config.underlying_worlds);
    for world in worlds {
        by_pair
            .entry(&world.record.paired_world_id)
            .or_default()
            .push(world);
    }
    if by_pair.len() != config.underlying_worlds
        || by_pair.values().any(|members| {
            members.len() != VARIANTS_PER_WORLD
                || members
                    .iter()
                    .any(|world| world.record.split != members[0].record.split)
        })
    {
        return Err(StressError(
            "paired world variants are incomplete or cross a split boundary".into(),
        ));
    }
    Ok(())
}

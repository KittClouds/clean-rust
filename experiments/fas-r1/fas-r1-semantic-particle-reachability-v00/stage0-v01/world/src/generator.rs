use std::fmt;

use hashbrown::HashSet;
use serde::{Deserialize, Serialize};

use crate::{
    automorphisms, canonical_assignment, enumerate_solutions, render_task, Clause, RenderedTask,
    SolveError, Task,
};

const MAX_GENERATED_K: u8 = 6;
const QUALIFICATION_CAP: usize = 200_000;

/// Canonical solution-class strata, measured after legal role relabeling.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum SolutionStratum {
    Unique,
    Small,
    Medium,
    Broad,
}

impl SolutionStratum {
    pub fn contains(self, count: usize) -> bool {
        match self {
            SolutionStratum::Unique => count == 1,
            SolutionStratum::Small => (2..=4).contains(&count),
            SolutionStratum::Medium => (5..=16).contains(&count),
            SolutionStratum::Broad => count >= 17,
        }
    }

    fn code(self) -> u8 {
        match self {
            SolutionStratum::Unique => 0,
            SolutionStratum::Small => 1,
            SolutionStratum::Medium => 2,
            SolutionStratum::Broad => 3,
        }
    }
}

/// A deterministic symbolic task request.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub struct GenerationSpec {
    pub n: u16,
    pub k: u8,
    pub stratum: SolutionStratum,
    pub role_anonymous: bool,
}

/// Exact offline qualification details for one generated task.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct QualifiedFixture {
    pub task: Task,
    pub raw_solution_count: usize,
    pub canonical_solution_class_count: usize,
}

/// A latent task paired with independent rendered surfaces.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GeneratedFamily {
    pub task: Task,
    pub surfaces: Vec<RenderedTask>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorError {
    InvalidDimensions {
        n: u16,
        k: u8,
    },
    UnsupportedRoleCount {
        k: u8,
        maximum: u8,
    },
    InfeasibleStratum {
        n: u16,
        k: u8,
        stratum: SolutionStratum,
        role_anonymous: bool,
        reason: String,
    },
    Qualification(SolveError),
    WrongStratum {
        requested: SolutionStratum,
        observed: usize,
    },
}

impl fmt::Display for GeneratorError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            GeneratorError::InvalidDimensions { n, k } => {
                write!(f, "n and k must be positive, got n={n}, k={k}")
            }
            GeneratorError::UnsupportedRoleCount { k, maximum } => {
                write!(f, "generator supports 2..={maximum} roles, got k={k}")
            }
            GeneratorError::InfeasibleStratum {
                n,
                k,
                stratum,
                role_anonymous,
                reason,
            } => write!(
                f,
                "cannot generate {stratum:?} canonical class count for n={n}, k={k}, \
                 role_anonymous={role_anonymous}: {reason}"
            ),
            GeneratorError::Qualification(error) => {
                write!(f, "generated task did not qualify: {error}")
            }
            GeneratorError::WrongStratum {
                requested,
                observed,
            } => write!(
                f,
                "requested {requested:?} canonical classes, observed {observed}"
            ),
        }
    }
}

impl std::error::Error for GeneratorError {}

impl From<SolveError> for GeneratorError {
    fn from(value: SolveError) -> Self {
        GeneratorError::Qualification(value)
    }
}

/// Generate and exhaustively qualify one deterministic task.
///
/// Seeds randomize entity and role labels and clause order within the same
/// latent blueprint family. Distinct surfaces can be made with render_task.
pub fn generate_task(seed: u64, spec: GenerationSpec) -> Result<Task, GeneratorError> {
    Ok(generate_qualified_fixture(seed, spec)?.task)
}

/// Generate one task and expose exact raw and canonical solution counts for
/// offline fixture qualification. The returned task itself carries no labels.
pub fn generate_qualified_fixture(
    seed: u64,
    spec: GenerationSpec,
) -> Result<QualifiedFixture, GeneratorError> {
    validate_spec(spec)?;
    let mut rng = StableRng::new(seed);
    let mut clauses = blueprint(spec, &mut rng)?;
    let family_id = family_id(spec, &clauses);

    let entity_map = shuffled_indices(usize::from(spec.n), &mut rng);
    let role_map = shuffled_indices(usize::from(spec.k), &mut rng);
    for clause in &mut clauses {
        *clause = remap_clause(clause, &entity_map, &role_map);
    }
    rng.shuffle(&mut clauses);

    let task = Task {
        id: task_id(seed, &family_id),
        family_id,
        seed,
        n: spec.n,
        k: spec.k,
        clauses,
        role_anonymous: spec.role_anonymous,
    };
    let solutions = enumerate_solutions(&task, QUALIFICATION_CAP)?;
    let raw_solution_count = solutions.len();
    let group = automorphisms(&task);
    let mut classes: HashSet<Vec<u8>> = HashSet::with_capacity(raw_solution_count);
    for assignment in &solutions {
        classes.insert(canonical_assignment(assignment, &group));
    }
    let canonical_solution_class_count = classes.len();
    if !spec.stratum.contains(canonical_solution_class_count) {
        return Err(GeneratorError::WrongStratum {
            requested: spec.stratum,
            observed: canonical_solution_class_count,
        });
    }

    Ok(QualifiedFixture {
        task,
        raw_solution_count,
        canonical_solution_class_count,
    })
}

/// Generate deterministic model-free smoke tasks spanning n, k, both role
/// modes, and all canonical solution strata. Each seed is a relabeling of its
/// latent blueprint; family IDs therefore remain stable across its surfaces.
pub fn generate_smoke_batch(base_seed: u64, count: usize) -> Result<Vec<Task>, GeneratorError> {
    let strata = [
        SolutionStratum::Unique,
        SolutionStratum::Small,
        SolutionStratum::Medium,
        SolutionStratum::Broad,
    ];
    let mut tasks = Vec::with_capacity(count);
    for index in 0..count {
        let stratum = strata[index % strata.len()];
        let n = 6 + (index % 7) as u16;
        let k = 2 + ((index / 8) % 3) as u8;
        let role_anonymous = (index / 4) % 2 == 1;
        let spec = GenerationSpec {
            n,
            k,
            stratum,
            role_anonymous,
        };
        let seed = base_seed.wrapping_add(index as u64);
        tasks.push(generate_task(seed, spec)?);
    }
    Ok(tasks)
}

/// Generate one latent task and surface variants. Family assignment happens
/// before rendering because every surface shares the same private Task.
pub fn generate_family(
    seed: u64,
    spec: GenerationSpec,
    surface_seeds: &[u64],
) -> Result<GeneratedFamily, GeneratorError> {
    let task = generate_task(seed, spec)?;
    let surfaces = surface_seeds
        .iter()
        .map(|surface_seed| render_task(&task, *surface_seed))
        .collect();
    Ok(GeneratedFamily { task, surfaces })
}

fn validate_spec(spec: GenerationSpec) -> Result<(), GeneratorError> {
    if spec.n == 0 || spec.k == 0 {
        return Err(GeneratorError::InvalidDimensions {
            n: spec.n,
            k: spec.k,
        });
    }
    if spec.k > MAX_GENERATED_K || spec.k < 2 {
        return Err(GeneratorError::UnsupportedRoleCount {
            k: spec.k,
            maximum: MAX_GENERATED_K,
        });
    }
    Ok(())
}

fn blueprint(spec: GenerationSpec, rng: &mut StableRng) -> Result<Vec<Clause>, GeneratorError> {
    if spec.role_anonymous {
        let components = anonymous_component_count(spec);
        if components > usize::from(spec.n) {
            return Err(GeneratorError::InfeasibleStratum {
                n: spec.n,
                k: spec.k,
                stratum: spec.stratum,
                role_anonymous: true,
                reason: "not enough entities to realize the requested class count".to_owned(),
            });
        }
        let mut component_sizes = vec![1usize; components];
        for _ in components..usize::from(spec.n) {
            let index = (rng.next_u64() as usize) % components;
            component_sizes[index] += 1;
        }
        rng.shuffle(&mut component_sizes);
        let mut groups = Vec::<Vec<u16>>::with_capacity(components);
        let mut next_entity = 0usize;
        for size in component_sizes {
            let end = next_entity + size;
            groups.push((next_entity..end).map(|entity| entity as u16).collect());
            next_entity = end;
        }
        let mut clauses = Vec::with_capacity(usize::from(spec.n).saturating_sub(components));
        for group in &groups {
            if let Some((&first, rest)) = group.split_first() {
                clauses.extend(rest.iter().map(|entity| Clause::Same {
                    a: first,
                    b: *entity,
                }));
            }
        }
        return Ok(clauses);
    }

    let (free_count, domain_size) = role_specific_plan(spec)?;
    let n = usize::from(spec.n);
    let k = usize::from(spec.k);
    let mut clauses = Vec::with_capacity(n + free_count * k + 8);
    let base_roles: Vec<u8> = (0..n)
        .map(|_| (rng.next_u64() % u64::from(spec.k)) as u8)
        .collect();
    let fixed_entities: Vec<usize> = (free_count..n).collect();

    for entity in &fixed_entities {
        clauses.push(Clause::FixedRole {
            entity: *entity as u16,
            role: base_roles[*entity],
        });
    }
    for entity in 0..free_count {
        for role in domain_size..k {
            clauses.push(Clause::ForbiddenRole {
                entity: entity as u16,
                role: role as u8,
            });
        }
    }

    if let Some(entity) = fixed_entities.first().copied() {
        let assigned = base_roles[entity];
        clauses.push(Clause::ForbiddenRole {
            entity: entity as u16,
            role: (usize::from(assigned) + 1).rem_euclid(k) as u8,
        });
        clauses.push(Clause::ImpliesNotRole {
            if_entity: entity as u16,
            if_role: (usize::from(assigned) + 1).rem_euclid(k) as u8,
            then_entity: entity as u16,
            then_role: assigned,
        });
    }

    if let Some(pair) = find_pair(&fixed_entities, &base_roles, true) {
        clauses.push(Clause::Same {
            a: pair.0 as u16,
            b: pair.1 as u16,
        });
    }
    if let Some(pair) = find_pair(&fixed_entities, &base_roles, false) {
        clauses.push(Clause::Different {
            a: pair.0 as u16,
            b: pair.1 as u16,
        });
    }

    if let Some(first) = fixed_entities.first().copied() {
        let role = base_roles[first];
        let second = fixed_entities
            .iter()
            .copied()
            .find(|entity| base_roles[*entity] != role);
        let entities = second
            .map(|other| vec![first as u16, other as u16])
            .unwrap_or_else(|| vec![first as u16]);
        clauses.push(Clause::ExactlyOneRole { entities, role });
    }

    Ok(clauses)
}

fn role_specific_plan(spec: GenerationSpec) -> Result<(usize, usize), GeneratorError> {
    let k = usize::from(spec.k);
    let n = usize::from(spec.n);
    let plan = match spec.stratum {
        SolutionStratum::Unique => (0, 1),
        SolutionStratum::Small => (1, k.min(4)),
        SolutionStratum::Medium => {
            let free = match k {
                2 => 3,
                3 | 4 => 2,
                _ => 1,
            };
            (free, k)
        }
        SolutionStratum::Broad => {
            let free = match k {
                2 => 5,
                3 => 3,
                4 => 3,
                5..=6 => 2,
                _ => unreachable!(),
            };
            (free, k)
        }
    };
    if plan.0 > n {
        return Err(GeneratorError::InfeasibleStratum {
            n: spec.n,
            k: spec.k,
            stratum: spec.stratum,
            role_anonymous: false,
            reason: format!("requires at least {} independent entities", plan.0),
        });
    }
    Ok(plan)
}

fn anonymous_component_count(spec: GenerationSpec) -> usize {
    let n = usize::from(spec.n);
    let k = usize::from(spec.k);
    match spec.stratum {
        SolutionStratum::Unique => 1,
        SolutionStratum::Small => 2,
        SolutionStratum::Medium => (1..=n)
            .find(|components| (5..=16).contains(&restricted_bell(*components, k)))
            .unwrap_or(n + 1),
        SolutionStratum::Broad => (1..=n)
            .find(|components| restricted_bell(*components, k) >= 17)
            .unwrap_or(n + 1),
    }
}

fn restricted_bell(elements: usize, roles: usize) -> u128 {
    let mut row = vec![0u128; roles.min(elements) + 1];
    row[0] = 1;
    let mut max_blocks = 0usize;
    for _ in 0..elements {
        let mut next = vec![0u128; row.len()];
        for blocks in 1..row.len() {
            next[blocks] = row[blocks - 1] + (blocks as u128) * row[blocks];
        }
        max_blocks = (max_blocks + 1).min(roles);
        row = next;
    }
    row.iter().take(max_blocks + 1).sum()
}

fn find_pair(entities: &[usize], roles: &[u8], want_same: bool) -> Option<(usize, usize)> {
    for (left_index, left) in entities.iter().enumerate() {
        for right in entities.iter().skip(left_index + 1) {
            if (roles[*left] == roles[*right]) == want_same {
                return Some((*left, *right));
            }
        }
    }
    None
}

fn remap_clause(clause: &Clause, entities: &[usize], roles: &[usize]) -> Clause {
    let entity = |value: u16| entities[usize::from(value)] as u16;
    let role = |value: u8| roles[usize::from(value)] as u8;
    match clause {
        Clause::Same { a, b } => Clause::Same {
            a: entity(*a),
            b: entity(*b),
        },
        Clause::Different { a, b } => Clause::Different {
            a: entity(*a),
            b: entity(*b),
        },
        Clause::FixedRole {
            entity: id,
            role: value,
        } => Clause::FixedRole {
            entity: entity(*id),
            role: role(*value),
        },
        Clause::ForbiddenRole {
            entity: id,
            role: value,
        } => Clause::ForbiddenRole {
            entity: entity(*id),
            role: role(*value),
        },
        Clause::ExactlyOneRole {
            entities: ids,
            role: value,
        } => Clause::ExactlyOneRole {
            entities: ids.iter().map(|id| entity(*id)).collect(),
            role: role(*value),
        },
        Clause::ImpliesNotRole {
            if_entity,
            if_role,
            then_entity,
            then_role,
        } => Clause::ImpliesNotRole {
            if_entity: entity(*if_entity),
            if_role: role(*if_role),
            then_entity: entity(*then_entity),
            then_role: role(*then_role),
        },
    }
}

/// Hash a label-invariant description of this generator's latent constraint
/// family. Anonymous tasks are identified by their equality-component sizes;
/// role-specific tasks by the multiset of allowed-role masks. The extra
/// generated relational clauses are consequences of those domain signatures.
pub(super) fn family_id(spec: GenerationSpec, clauses: &[Clause]) -> String {
    let mut bytes = vec![
        spec.n as u8,
        (spec.n >> 8) as u8,
        spec.k,
        u8::from(spec.role_anonymous),
        spec.stratum.code(),
    ];
    if spec.role_anonymous {
        let mut parents: Vec<usize> = (0..usize::from(spec.n)).collect();
        for clause in clauses {
            if let Clause::Same { a, b } = clause {
                let left = root(&mut parents, usize::from(*a));
                let right = root(&mut parents, usize::from(*b));
                parents[right] = left;
            }
        }
        let mut sizes = vec![0u16; usize::from(spec.n)];
        for entity in 0..usize::from(spec.n) {
            let component = root(&mut parents, entity);
            sizes[component] += 1;
        }
        sizes.retain(|size| *size != 0);
        sizes.sort_unstable();
        for size in sizes {
            bytes.extend_from_slice(&size.to_le_bytes());
        }
    } else {
        let mut allowed = vec![(1u8 << spec.k) - 1; usize::from(spec.n)];
        for clause in clauses {
            match clause {
                Clause::FixedRole { entity, role } => {
                    allowed[usize::from(*entity)] = 1u8 << role;
                }
                Clause::ForbiddenRole { entity, role } => {
                    allowed[usize::from(*entity)] &= !(1u8 << role);
                }
                _ => {}
            }
        }
        bytes.extend_from_slice(&canonical_role_masks(&allowed, spec.k));
    }
    format!("fam-{}", stable_hash(&bytes))
}

fn canonical_role_masks(masks: &[u8], role_count: u8) -> Vec<u8> {
    fn visit(
        position: usize,
        mapping: &mut [u8],
        used: &mut [bool],
        masks: &[u8],
        best: &mut Option<Vec<u8>>,
    ) {
        if position == mapping.len() {
            let mut relabeled = Vec::with_capacity(masks.len());
            for mask in masks {
                let mut next_mask = 0u8;
                for (old_role, new_role) in mapping.iter().enumerate() {
                    if mask & (1u8 << old_role) != 0 {
                        next_mask |= 1u8 << new_role;
                    }
                }
                relabeled.push(next_mask);
            }
            relabeled.sort_unstable();
            if best.as_ref().is_none_or(|current| relabeled < *current) {
                *best = Some(relabeled);
            }
            return;
        }

        for role in 0..mapping.len() {
            if !used[role] {
                mapping[position] = role as u8;
                used[role] = true;
                visit(position + 1, mapping, used, masks, best);
                used[role] = false;
            }
        }
    }

    let mut mapping = vec![0u8; usize::from(role_count)];
    let mut used = vec![false; usize::from(role_count)];
    let mut best = None;
    visit(0, &mut mapping, &mut used, masks, &mut best);
    best.unwrap_or_default()
}

fn root(parents: &mut [usize], mut node: usize) -> usize {
    while parents[node] != node {
        let grandparent = parents[parents[node]];
        parents[node] = grandparent;
        node = grandparent;
    }
    node
}

fn task_id(seed: u64, family_id: &str) -> String {
    let mut bytes = family_id.as_bytes().to_vec();
    bytes.extend_from_slice(&seed.to_le_bytes());
    format!("task-{}", stable_hash(&bytes))
}

fn stable_hash(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(bytes))
}

fn shuffled_indices(length: usize, rng: &mut StableRng) -> Vec<usize> {
    let mut indices: Vec<usize> = (0..length).collect();
    rng.shuffle(&mut indices);
    indices
}

struct StableRng(u64);

impl StableRng {
    fn new(seed: u64) -> Self {
        Self(seed.wrapping_add(0x9e37_79b9_7f4a_7c15))
    }

    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut value = self.0;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        value ^ (value >> 31)
    }

    fn shuffle<T>(&mut self, values: &mut [T]) {
        for index in (1..values.len()).rev() {
            let other = (self.next_u64() as usize) % (index + 1);
            values.swap(index, other);
        }
    }
}

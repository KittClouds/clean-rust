use hashbrown::HashSet;
use serde::{Deserialize, Serialize};

use crate::{Clause, Task};

/// Safe runtime projection: rendered language and public task metadata only.
///
/// It contains no typed clauses, solutions, solver status, or symmetry data.
/// In particular, the private task seed is omitted.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct InferenceTask {
    pub id: String,
    pub family_id: String,
    pub n: u16,
    pub k: u8,
    pub role_anonymous: bool,
    pub global_text: String,
    pub clauses: Vec<String>,
    /// Per-rendered-clause zero-based entity IDs mentioned in its text.
    pub entity_mentions: Vec<Vec<u16>>,
    /// Per-rendered-clause zero-based role IDs mentioned in its text.
    pub role_mentions: Vec<Vec<u8>>,
}

/// A deterministic natural-language rendering plus offline surface metadata.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RenderedTask {
    pub inference: InferenceTask,
    pub text: String,
    pub entity_names: Vec<String>,
    pub role_names: Vec<String>,
    /// For each rendered clause position, its source AST clause position.
    pub clause_order: Vec<usize>,
    /// For each rendered clause position, a stable paraphrase template ID.
    pub template_ids: Vec<u8>,
    /// Opaque surface identity. The raw surface seed is not exposed.
    pub surface_id: String,
}

pub fn render_task(task: &Task, surface_seed: u64) -> RenderedTask {
    let mut rng = StableRng::new(surface_seed ^ task.seed.rotate_left(19));
    let entity_names = invented_names(usize::from(task.n), &mut rng, false);
    let role_names = invented_names(usize::from(task.k), &mut rng, true);

    let mut order: Vec<usize> = (0..task.clauses.len()).collect();
    rng.shuffle(&mut order);
    let mut rendered_clauses = Vec::with_capacity(order.len());
    let mut entity_mentions = Vec::with_capacity(order.len());
    let mut role_mentions = Vec::with_capacity(order.len());
    let mut template_ids = Vec::with_capacity(order.len());
    for clause_index in &order {
        let template = (rng.next_u64() % 2) as u8;
        let clause = &task.clauses[*clause_index];
        rendered_clauses.push(render_clause(clause, template, &entity_names, &role_names));
        let (entities, roles) = mentions(clause);
        entity_mentions.push(entities);
        role_mentions.push(roles);
        template_ids.push(template);
    }

    let mut text = String::new();
    text.push_str("Assign every entity to exactly one available role. Entities: ");
    for (index, name) in entity_names.iter().enumerate() {
        if index != 0 {
            text.push_str(", ");
        }
        text.push_str(name);
    }
    text.push_str(". Available roles: ");
    for (index, name) in role_names.iter().enumerate() {
        if index != 0 {
            text.push_str(", ");
        }
        text.push_str(name);
    }
    text.push('.');
    for clause in &rendered_clauses {
        text.push(' ');
        text.push_str(clause);
        text.push('.');
    }

    let inference = InferenceTask {
        id: task.id.clone(),
        family_id: task.family_id.clone(),
        n: task.n,
        k: task.k,
        role_anonymous: task.role_anonymous,
        global_text: text.clone(),
        clauses: rendered_clauses,
        entity_mentions,
        role_mentions,
    };
    let surface_id = opaque_surface_id(&task.family_id, surface_seed);
    RenderedTask {
        inference,
        text,
        entity_names,
        role_names,
        clause_order: order,
        template_ids,
        surface_id,
    }
}

fn render_clause(clause: &Clause, template: u8, entities: &[String], roles: &[String]) -> String {
    match clause {
        Clause::Same { a, b } => {
            if template == 0 {
                format!(
                    "{} and {} share the same role",
                    entities[usize::from(*a)],
                    entities[usize::from(*b)]
                )
            } else {
                format!(
                    "Place {} and {} in one role",
                    entities[usize::from(*a)],
                    entities[usize::from(*b)]
                )
            }
        }
        Clause::Different { a, b } => {
            if template == 0 {
                format!(
                    "{} and {} must have different roles",
                    entities[usize::from(*a)],
                    entities[usize::from(*b)]
                )
            } else {
                format!(
                    "Do not assign {} and {} to the same role",
                    entities[usize::from(*a)],
                    entities[usize::from(*b)]
                )
            }
        }
        Clause::FixedRole { entity, role } => {
            if template == 0 {
                format!(
                    "{} must be assigned to {}",
                    entities[usize::from(*entity)],
                    roles[usize::from(*role)]
                )
            } else {
                format!(
                    "The role for {} is {}",
                    entities[usize::from(*entity)],
                    roles[usize::from(*role)]
                )
            }
        }
        Clause::ForbiddenRole { entity, role } => {
            if template == 0 {
                format!(
                    "{} cannot take {}",
                    entities[usize::from(*entity)],
                    roles[usize::from(*role)]
                )
            } else {
                format!(
                    "Do not place {} in {}",
                    entities[usize::from(*entity)],
                    roles[usize::from(*role)]
                )
            }
        }
        Clause::ExactlyOneRole {
            entities: ids,
            role,
        } => {
            let names = ids
                .iter()
                .map(|id| entities[usize::from(*id)].as_str())
                .collect::<Vec<_>>()
                .join(", ");
            if template == 0 {
                format!(
                    "Exactly one of {names} must take {}",
                    roles[usize::from(*role)]
                )
            } else {
                format!(
                    "Among {names}, one and only one has role {}",
                    roles[usize::from(*role)]
                )
            }
        }
        Clause::ImpliesNotRole {
            if_entity,
            if_role,
            then_entity,
            then_role,
        } => {
            if template == 0 {
                format!(
                    "If {} takes {}, {} cannot take {}",
                    entities[usize::from(*if_entity)],
                    roles[usize::from(*if_role)],
                    entities[usize::from(*then_entity)],
                    roles[usize::from(*then_role)]
                )
            } else {
                format!(
                    "When {} is in {}, keep {} out of {}",
                    entities[usize::from(*if_entity)],
                    roles[usize::from(*if_role)],
                    entities[usize::from(*then_entity)],
                    roles[usize::from(*then_role)]
                )
            }
        }
    }
}

fn mentions(clause: &Clause) -> (Vec<u16>, Vec<u8>) {
    let mut entities = Vec::new();
    let mut roles = Vec::new();
    match clause {
        Clause::Same { a, b } | Clause::Different { a, b } => {
            entities.extend([*a, *b]);
        }
        Clause::FixedRole { entity, role } | Clause::ForbiddenRole { entity, role } => {
            entities.push(*entity);
            roles.push(*role);
        }
        Clause::ExactlyOneRole {
            entities: members,
            role,
        } => {
            entities.extend_from_slice(members);
            roles.push(*role);
        }
        Clause::ImpliesNotRole {
            if_entity,
            if_role,
            then_entity,
            then_role,
        } => {
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

fn invented_names(count: usize, rng: &mut StableRng, role: bool) -> Vec<String> {
    let mut used = HashSet::with_capacity(count);
    let mut names = Vec::with_capacity(count);
    while names.len() < count {
        let candidate = invented_name(rng, role);
        if used.insert(candidate.clone()) {
            names.push(candidate);
        }
    }
    names
}

fn invented_name(rng: &mut StableRng, role: bool) -> String {
    const ENTITY_ONSETS: [&str; 8] = [
        "vex", "nori", "pavo", "ziri", "kumo", "dexa", "miri", "tavo",
    ];
    const ROLE_ONSETS: [&str; 8] = [
        "doru", "savi", "luma", "kepi", "ranu", "bexo", "tuli", "nexa",
    ];
    const CODAS: [&str; 8] = ["n", "m", "r", "s", "v", "k", "t", "l"];
    const VOWELS: [&str; 5] = ["a", "e", "i", "o", "u"];
    const ALPHABET: &[u8; 26] = b"abcdefghijklmnopqrstuvwxyz";
    let onset = if role {
        ROLE_ONSETS[(rng.next_u64() as usize) % ROLE_ONSETS.len()]
    } else {
        ENTITY_ONSETS[(rng.next_u64() as usize) % ENTITY_ONSETS.len()]
    };
    let vowel = VOWELS[(rng.next_u64() as usize) % VOWELS.len()];
    let coda = CODAS[(rng.next_u64() as usize) % CODAS.len()];
    let mut suffix = [b'a'; 5];
    let mut bits = rng.next_u64();
    for letter in &mut suffix {
        *letter = ALPHABET[(bits % 26) as usize];
        bits /= 26;
    }
    let suffix = std::str::from_utf8(&suffix).expect("suffix alphabet is ASCII");
    format!("{onset}{vowel}{coda}{suffix}")
}

fn opaque_surface_id(family_id: &str, seed: u64) -> String {
    use sha2::{Digest, Sha256};
    let mut bytes = Vec::with_capacity(family_id.len() + 8);
    bytes.extend_from_slice(family_id.as_bytes());
    bytes.extend_from_slice(&seed.to_le_bytes());
    format!("surface-{:x}", Sha256::digest(bytes))
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

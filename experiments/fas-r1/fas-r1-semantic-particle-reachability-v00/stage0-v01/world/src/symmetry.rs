use crate::{Clause, Task};

/// Return all role permutations that preserve the task's declared role
/// semantics and constraint multiset. A permutation maps old role IDs to new
/// role IDs. Role-specific tasks expose only identity; anonymous tasks retain
/// precisely the relabelings under which the typed constraint set is invariant.
///
/// The explicit Vec API means output size is factorial in the number of
/// unconstrained roles. Generated Stage 0 tasks keep k at six or below.
pub fn automorphisms(task: &Task) -> Vec<Vec<u8>> {
    let identity: Vec<u8> = (0..task.k).collect();
    if !task.role_anonymous || task.k <= 1 || task.shape_error().is_some() {
        return vec![identity];
    }

    let original = normalized_clauses(&task.clauses);
    let mut mapping = vec![0u8; usize::from(task.k)];
    let mut used = vec![false; usize::from(task.k)];
    let mut result = Vec::new();
    enumerate_permutations(0, &mut mapping, &mut used, &mut |permutation| {
        if normalized_clauses(&map_clauses(&task.clauses, permutation)) == original {
            result.push(permutation.to_vec());
        }
    });
    result
}

/// Canonicalize an assignment by choosing the lexicographically smallest
/// assignment in its role-permutation orbit. Malformed permutations are
/// ignored; an empty or unusable group leaves the assignment unchanged.
pub fn canonical_assignment(assignment: &[u8], perms: &[Vec<u8>]) -> Vec<u8> {
    let mut best: Option<Vec<u8>> = None;
    for permutation in perms {
        if !is_permutation(permutation) {
            continue;
        }
        let mapped: Vec<u8> = assignment
            .iter()
            .map(|role| {
                permutation
                    .get(usize::from(*role))
                    .copied()
                    .unwrap_or(*role)
            })
            .collect();
        if best.as_ref().is_none_or(|current| mapped < *current) {
            best = Some(mapped);
        }
    }
    best.unwrap_or_else(|| assignment.to_vec())
}

fn enumerate_permutations(
    position: usize,
    mapping: &mut [u8],
    used: &mut [bool],
    accept: &mut impl FnMut(&[u8]),
) {
    if position == mapping.len() {
        accept(mapping);
        return;
    }
    for role in 0..mapping.len() {
        if !used[role] {
            mapping[position] = role as u8;
            used[role] = true;
            enumerate_permutations(position + 1, mapping, used, accept);
            used[role] = false;
        }
    }
}

fn is_permutation(values: &[u8]) -> bool {
    let mut seen = vec![false; values.len()];
    for value in values {
        let index = usize::from(*value);
        if index >= seen.len() || seen[index] {
            return false;
        }
        seen[index] = true;
    }
    true
}

fn map_clauses(clauses: &[Clause], permutation: &[u8]) -> Vec<Clause> {
    clauses
        .iter()
        .map(|clause| match clause {
            Clause::Same { a, b } => Clause::Same { a: *a, b: *b },
            Clause::Different { a, b } => Clause::Different { a: *a, b: *b },
            Clause::FixedRole { entity, role } => Clause::FixedRole {
                entity: *entity,
                role: permutation[usize::from(*role)],
            },
            Clause::ForbiddenRole { entity, role } => Clause::ForbiddenRole {
                entity: *entity,
                role: permutation[usize::from(*role)],
            },
            Clause::ExactlyOneRole { entities, role } => Clause::ExactlyOneRole {
                entities: entities.clone(),
                role: permutation[usize::from(*role)],
            },
            Clause::ImpliesNotRole {
                if_entity,
                if_role,
                then_entity,
                then_role,
            } => Clause::ImpliesNotRole {
                if_entity: *if_entity,
                if_role: permutation[usize::from(*if_role)],
                then_entity: *then_entity,
                then_role: permutation[usize::from(*then_role)],
            },
        })
        .collect()
}

fn normalized_clauses(clauses: &[Clause]) -> Vec<Clause> {
    let mut normalized = clauses.to_vec();
    for clause in &mut normalized {
        if let Clause::ExactlyOneRole { entities, .. } = clause {
            entities.sort_unstable();
        }
    }
    normalized.sort_unstable();
    normalized
}

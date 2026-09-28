use std::fmt;

use crate::{Clause, Task};

/// Solver termination outcomes. An Ok return from enumerate_solutions means
/// the entire finite assignment space was exhausted. CapExceeded is distinct
/// and never masquerades as an exact count.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SolveError {
    InvalidTask(String),
    CapExceeded { cap: usize, found_at_least: usize },
}

impl fmt::Display for SolveError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SolveError::InvalidTask(message) => write!(f, "invalid task: {message}"),
            SolveError::CapExceeded {
                cap,
                found_at_least,
            } => write!(
                f,
                "solution cap {cap} exceeded; found at least {found_at_least}"
            ),
        }
    }
}

impl std::error::Error for SolveError {}

/// Enumerate all satisfying assignments in deterministic lexicographic order.
///
/// Successful return proves exhaustion. If one more solution than cap is
/// found, the function returns CapExceeded. No wall-clock timeout is used.
pub fn enumerate_solutions(task: &Task, cap: usize) -> Result<Vec<Vec<u8>>, SolveError> {
    if let Some(message) = task.shape_error() {
        return Err(SolveError::InvalidTask(message));
    }

    let mut state = vec![UNASSIGNED; usize::from(task.n)];
    let mut output = Vec::with_capacity(cap.min(64));
    let mut exceeded = false;
    visit(task, 0, &mut state, cap, &mut output, &mut exceeded);
    if exceeded {
        Err(SolveError::CapExceeded {
            cap,
            found_at_least: cap.saturating_add(1),
        })
    } else {
        Ok(output)
    }
}

const UNASSIGNED: u8 = u8::MAX;

fn visit(
    task: &Task,
    entity: usize,
    state: &mut [u8],
    cap: usize,
    output: &mut Vec<Vec<u8>>,
    exceeded: &mut bool,
) {
    if *exceeded {
        return;
    }
    if entity == state.len() {
        if output.len() == cap {
            *exceeded = true;
        } else {
            output.push(state.to_vec());
        }
        return;
    }

    for role in 0..task.k {
        state[entity] = role;
        if partial_constraints_hold(task, state) {
            visit(task, entity + 1, state, cap, output, exceeded);
        }
        if *exceeded {
            break;
        }
    }
    state[entity] = UNASSIGNED;
}

fn partial_constraints_hold(task: &Task, state: &[u8]) -> bool {
    task.clauses.iter().all(|clause| match clause {
        Clause::Same { a, b } => {
            let left = state[usize::from(*a)];
            let right = state[usize::from(*b)];
            left == UNASSIGNED || right == UNASSIGNED || left == right
        }
        Clause::Different { a, b } => {
            let left = state[usize::from(*a)];
            let right = state[usize::from(*b)];
            left == UNASSIGNED || right == UNASSIGNED || left != right
        }
        Clause::FixedRole { entity, role } => {
            let value = state[usize::from(*entity)];
            value == UNASSIGNED || value == *role
        }
        Clause::ForbiddenRole { entity, role } => {
            let value = state[usize::from(*entity)];
            value == UNASSIGNED || value != *role
        }
        Clause::ExactlyOneRole { entities, role } => {
            let mut seen = 0usize;
            let mut remaining = 0usize;
            for entity in entities {
                match state[usize::from(*entity)] {
                    UNASSIGNED => remaining += 1,
                    assigned if assigned == *role => seen += 1,
                    _ => {}
                }
            }
            seen <= 1 && seen + remaining >= 1
        }
        Clause::ImpliesNotRole {
            if_entity,
            if_role,
            then_entity,
            then_role,
        } => {
            let antecedent = state[usize::from(*if_entity)];
            let consequent = state[usize::from(*then_entity)];
            antecedent == UNASSIGNED
                || antecedent != *if_role
                || consequent == UNASSIGNED
                || consequent != *then_role
        }
    })
}

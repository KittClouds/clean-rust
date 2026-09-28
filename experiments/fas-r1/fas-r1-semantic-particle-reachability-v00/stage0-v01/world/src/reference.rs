use crate::{Clause, Task};

/// Independent, allocation-free reference validator used to cross-check the
/// fast validator and exact solver during Stage 0.
pub fn validate_independent(task: &Task, values: &[u8]) -> bool {
    if task.n == 0 || task.k == 0 || values.len() != task.n as usize {
        return false;
    }
    for value in values {
        if *value >= task.k {
            return false;
        }
    }

    for condition in task.clauses.iter() {
        let satisfied = match condition {
            Clause::Same { a, b } => {
                (*a as usize) < values.len()
                    && (*b as usize) < values.len()
                    && values[*a as usize] == values[*b as usize]
            }
            Clause::Different { a, b } => {
                (*a as usize) < values.len()
                    && (*b as usize) < values.len()
                    && values[*a as usize] != values[*b as usize]
            }
            Clause::FixedRole { entity, role } => {
                (*entity as usize) < values.len()
                    && *role < task.k
                    && values[*entity as usize] == *role
            }
            Clause::ForbiddenRole { entity, role } => {
                (*entity as usize) < values.len()
                    && *role < task.k
                    && values[*entity as usize] != *role
            }
            Clause::ExactlyOneRole { entities, role } => {
                let mut hits = 0usize;
                let mut valid_indices = !entities.is_empty();
                let mut seen_entities = vec![false; values.len()];
                for entity in entities {
                    let index = usize::from(*entity);
                    if index >= values.len() || *role >= task.k || seen_entities[index] {
                        valid_indices = false;
                        break;
                    }
                    seen_entities[index] = true;
                    if values[index] == *role {
                        hits += 1;
                    }
                }
                valid_indices && hits == 1
            }
            Clause::ImpliesNotRole {
                if_entity,
                if_role,
                then_entity,
                then_role,
            } => {
                let indices_ok =
                    (*if_entity as usize) < values.len() && (*then_entity as usize) < values.len();
                indices_ok
                    && *if_role < task.k
                    && *then_role < task.k
                    && (values[*if_entity as usize] != *if_role
                        || values[*then_entity as usize] != *then_role)
            }
        };
        if !satisfied {
            return false;
        }
    }
    true
}

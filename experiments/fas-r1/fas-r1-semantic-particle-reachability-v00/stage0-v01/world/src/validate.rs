use crate::{Clause, Task};

/// Fast direct validator for a complete role assignment.
///
/// Invalid task shapes and assignments return false. The solver performs
/// shape validation once before search, so this function is intended for
/// external checks and final-state annotation rather than an inner loop.
pub fn validate(task: &Task, assignment: &[u8]) -> bool {
    if task.shape_error().is_some()
        || assignment.len() != usize::from(task.n)
        || assignment.iter().any(|role| *role >= task.k)
    {
        return false;
    }

    task.clauses.iter().all(|clause| match clause {
        Clause::Same { a, b } => assignment[usize::from(*a)] == assignment[usize::from(*b)],
        Clause::Different { a, b } => assignment[usize::from(*a)] != assignment[usize::from(*b)],
        Clause::FixedRole { entity, role } => assignment[usize::from(*entity)] == *role,
        Clause::ForbiddenRole { entity, role } => assignment[usize::from(*entity)] != *role,
        Clause::ExactlyOneRole { entities, role } => {
            entities
                .iter()
                .filter(|entity| assignment[usize::from(**entity)] == *role)
                .count()
                == 1
        }
        Clause::ImpliesNotRole {
            if_entity,
            if_role,
            then_entity,
            then_role,
        } => {
            assignment[usize::from(*if_entity)] != *if_role
                || assignment[usize::from(*then_entity)] != *then_role
        }
    })
}

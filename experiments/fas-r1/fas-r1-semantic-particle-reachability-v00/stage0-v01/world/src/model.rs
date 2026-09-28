use serde::{Deserialize, Serialize};
use std::fmt;

/// A typed symbolic constraint. Entity IDs are zero-based and roles are
/// integers in 0..Task::k.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
pub enum Clause {
    Same {
        a: u16,
        b: u16,
    },
    Different {
        a: u16,
        b: u16,
    },
    FixedRole {
        entity: u16,
        role: u8,
    },
    ForbiddenRole {
        entity: u16,
        role: u8,
    },
    ExactlyOneRole {
        entities: Vec<u16>,
        role: u8,
    },
    ImpliesNotRole {
        if_entity: u16,
        if_role: u8,
        then_entity: u16,
        then_role: u8,
    },
}

/// A complete symbolic assignment task.
///
/// The seed is offline metadata. The inference projection intentionally
/// omits it because the deterministic generator seed can rebuild the AST.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Task {
    pub id: String,
    pub family_id: String,
    pub seed: u64,
    pub n: u16,
    pub k: u8,
    pub clauses: Vec<Clause>,
    pub role_anonymous: bool,
}

impl Task {
    pub(crate) fn shape_error(&self) -> Option<String> {
        if self.n == 0 {
            return Some("n must be positive".to_owned());
        }
        if self.k == 0 {
            return Some("k must be positive".to_owned());
        }

        for (clause_index, clause) in self.clauses.iter().enumerate() {
            let bad_entity = |entity: u16| entity >= self.n;
            let bad_role = |role: u8| role >= self.k;
            let error = match clause {
                Clause::Same { a, b } | Clause::Different { a, b } => {
                    if bad_entity(*a) || bad_entity(*b) {
                        Some("entity index out of range")
                    } else {
                        None
                    }
                }
                Clause::FixedRole { entity, role } | Clause::ForbiddenRole { entity, role } => {
                    if bad_entity(*entity) {
                        Some("entity index out of range")
                    } else if bad_role(*role) {
                        Some("role index out of range")
                    } else {
                        None
                    }
                }
                Clause::ExactlyOneRole { entities, role } => {
                    if entities.is_empty() {
                        Some("ExactlyOneRole needs at least one entity")
                    } else if bad_role(*role) {
                        Some("role index out of range")
                    } else if entities.iter().any(|entity| bad_entity(*entity)) {
                        Some("entity index out of range")
                    } else {
                        let mut seen_entities = vec![false; usize::from(self.n)];
                        let mut duplicate = false;
                        for entity in entities {
                            let index = usize::from(*entity);
                            if seen_entities[index] {
                                duplicate = true;
                                break;
                            }
                            seen_entities[index] = true;
                        }
                        if duplicate {
                            Some("ExactlyOneRole entity list contains duplicates")
                        } else {
                            None
                        }
                    }
                }
                Clause::ImpliesNotRole {
                    if_entity,
                    if_role,
                    then_entity,
                    then_role,
                } => {
                    if bad_entity(*if_entity) || bad_entity(*then_entity) {
                        Some("entity index out of range")
                    } else if bad_role(*if_role) || bad_role(*then_role) {
                        Some("role index out of range")
                    } else {
                        None
                    }
                }
            };
            if let Some(message) = error {
                return Some(format!("clause {clause_index}: {message}"));
            }
        }
        None
    }
}

impl fmt::Display for Clause {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Clause::Same { a, b } => write!(f, "Same({a},{b})"),
            Clause::Different { a, b } => write!(f, "Different({a},{b})"),
            Clause::FixedRole { entity, role } => write!(f, "FixedRole({entity},{role})"),
            Clause::ForbiddenRole { entity, role } => {
                write!(f, "ForbiddenRole({entity},{role})")
            }
            Clause::ExactlyOneRole { entities, role } => {
                write!(f, "ExactlyOneRole({entities:?},{role})")
            }
            Clause::ImpliesNotRole {
                if_entity,
                if_role,
                then_entity,
                then_role,
            } => write!(
                f,
                "ImpliesNotRole({if_entity},{if_role},{then_entity},{then_role})"
            ),
        }
    }
}

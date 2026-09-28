use hashbrown::HashMap;
use r1_world::{
    automorphisms, canonical_assignment, enumerate_solutions, validate, SolveError, Task,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fmt;

/// Complete solution equivalence classes, produced only after the exact
/// enumerator exhausts the finite assignment space.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ExactSolutionClasses {
    task_id: String,
    task_sha256: String,
    raw_solution_count: usize,
    classes: Vec<SolutionClass>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SolutionClass {
    pub canonical_assignment: Vec<u8>,
    /// Every raw satisfying assignment in this role-permutation class.
    pub members: Vec<Vec<u8>>,
}

impl ExactSolutionClasses {
    /// Enumerate every satisfying assignment and group by the public role
    /// automorphisms declared on the task. Cap exhaustion is an error, never a
    /// partial teacher target.
    pub fn solve(task: &Task, solution_cap: usize) -> Result<Self, TeacherError> {
        let solutions = enumerate_solutions(task, solution_cap).map_err(TeacherError::Solve)?;
        let permutations = automorphisms(task);
        let mut groups: HashMap<Vec<u8>, Vec<Vec<u8>>> = HashMap::new();
        for solution in &solutions {
            if !validate(task, solution) {
                return Err(TeacherError::InvalidEnumeratedSolution);
            }
            let key = canonical_assignment(solution, &permutations);
            groups.entry(key).or_default().push(solution.clone());
        }
        let mut classes: Vec<_> = groups
            .into_iter()
            .map(|(canonical_assignment, mut members)| {
                members.sort_unstable();
                members.dedup();
                SolutionClass {
                    canonical_assignment,
                    members,
                }
            })
            .collect();
        classes.sort_by(|left, right| left.canonical_assignment.cmp(&right.canonical_assignment));
        let task_sha256 =
            sha256_hex(&serde_json::to_vec(task).map_err(|_| TeacherError::Serialization)?);
        Ok(Self {
            task_id: task.id.clone(),
            task_sha256,
            raw_solution_count: solutions.len(),
            classes,
        })
    }

    pub fn task_id(&self) -> &str {
        &self.task_id
    }

    pub fn task_sha256(&self) -> &str {
        &self.task_sha256
    }

    pub fn raw_solution_count(&self) -> usize {
        self.raw_solution_count
    }

    pub fn classes(&self) -> &[SolutionClass] {
        &self.classes
    }
}

/// For an edit e, `g_fraction = n_improved_classes / class_count` and the
/// teacher probability is proportional to this fraction. `delta_d_min` is
/// d_min(after) - d_min(before), so a negative value moves closer to the
/// nearest valid class.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TeacherEditTarget {
    pub entity: u16,
    pub new_role: u8,
    pub n_improved_classes: usize,
    pub g_fraction: f64,
    pub delta_d_min: i32,
    pub q_probability: f64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TeacherOutcome {
    PositiveMass,
    ZeroMass,
}

/// Private training target. This structure must not be joined to inference
/// inputs during rollout or evaluation.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TeacherTarget {
    pub schema: String,
    pub task_id: String,
    pub task_sha256: String,
    pub state_sha256: String,
    pub outcome: TeacherOutcome,
    pub class_count: usize,
    pub minimum_distance_before: usize,
    pub total_improved_class_mass: usize,
    pub edits: Vec<TeacherEditTarget>,
}

/// Build the class-balanced one-step reachability teacher:
///
/// `G(e|a) = mean_c 1[d_c(a_e) < d_c(a)]`, `q(e|a) ∝ G(e|a)`.
///
/// Candidate edits are all single-entity role changes. `ZeroMass` is an
/// explicit result (for example, an already-solved state with one valid
/// equivalence class); consumers must mask it instead of normalizing zeros.
pub fn build_teacher_target(
    task: &Task,
    exact_classes: &ExactSolutionClasses,
    assignment: &[u8],
) -> Result<TeacherTarget, TeacherError> {
    validate_assignment_shape(task, assignment)?;
    if task.id != exact_classes.task_id
        || sha256_hex(&serde_json::to_vec(task).map_err(|_| TeacherError::Serialization)?)
            != exact_classes.task_sha256
    {
        return Err(TeacherError::TaskSolutionMismatch);
    }
    if exact_classes.classes.is_empty() {
        return Err(TeacherError::UnsatisfiableTask);
    }

    let distances_before = class_distances(&exact_classes.classes, assignment)?;
    let minimum_distance_before = distances_before
        .iter()
        .copied()
        .min()
        .ok_or(TeacherError::UnsatisfiableTask)?;
    let mut edits = Vec::with_capacity(usize::from(task.n) * usize::from(task.k.saturating_sub(1)));
    let mut total_improved_class_mass = 0usize;

    for entity in 0..task.n {
        let old_role = assignment[usize::from(entity)];
        for new_role in 0..task.k {
            if new_role == old_role {
                continue;
            }
            let mut edited = assignment.to_vec();
            edited[usize::from(entity)] = new_role;
            let distances_after = class_distances(&exact_classes.classes, &edited)?;
            let n_improved_classes = distances_after
                .iter()
                .zip(&distances_before)
                .filter(|(after, before)| after < before)
                .count();
            total_improved_class_mass += n_improved_classes;
            let minimum_after = distances_after
                .iter()
                .copied()
                .min()
                .ok_or(TeacherError::UnsatisfiableTask)?;
            edits.push(TeacherEditTarget {
                entity,
                new_role,
                n_improved_classes,
                g_fraction: n_improved_classes as f64 / exact_classes.classes.len() as f64,
                delta_d_min: minimum_after as i32 - minimum_distance_before as i32,
                q_probability: 0.0,
            });
        }
    }

    let outcome = if total_improved_class_mass == 0 {
        TeacherOutcome::ZeroMass
    } else {
        for edit in &mut edits {
            edit.q_probability = edit.n_improved_classes as f64 / total_improved_class_mass as f64;
        }
        TeacherOutcome::PositiveMass
    };
    let mut state_bytes = Vec::with_capacity(exact_classes.task_sha256.len() + assignment.len());
    state_bytes.extend_from_slice(exact_classes.task_sha256.as_bytes());
    state_bytes.extend_from_slice(assignment);
    Ok(TeacherTarget {
        schema: "r1-class-balanced-one-step-teacher-v01".to_owned(),
        task_id: task.id.clone(),
        task_sha256: exact_classes.task_sha256.clone(),
        state_sha256: sha256_hex(&state_bytes),
        outcome,
        class_count: exact_classes.classes.len(),
        minimum_distance_before,
        total_improved_class_mass,
        edits,
    })
}

fn class_distances(
    classes: &[SolutionClass],
    assignment: &[u8],
) -> Result<Vec<usize>, TeacherError> {
    classes
        .iter()
        .map(|class| {
            class
                .members
                .iter()
                .map(|member| hamming_distance(assignment, member))
                .min()
                .ok_or(TeacherError::EmptySolutionClass)
        })
        .collect()
}

fn hamming_distance(left: &[u8], right: &[u8]) -> usize {
    left.iter().zip(right).filter(|(a, b)| a != b).count()
}

fn validate_assignment_shape(task: &Task, assignment: &[u8]) -> Result<(), TeacherError> {
    if assignment.len() != usize::from(task.n) {
        return Err(TeacherError::AssignmentLength {
            expected: usize::from(task.n),
            actual: assignment.len(),
        });
    }
    if assignment.iter().any(|role| *role >= task.k) {
        return Err(TeacherError::RoleOutOfRange);
    }
    Ok(())
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TeacherError {
    Solve(SolveError),
    AssignmentLength { expected: usize, actual: usize },
    RoleOutOfRange,
    InvalidEnumeratedSolution,
    TaskSolutionMismatch,
    UnsatisfiableTask,
    EmptySolutionClass,
    Serialization,
}

impl fmt::Display for TeacherError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Solve(error) => write!(f, "exact solution enumeration failed: {error}"),
            Self::AssignmentLength { expected, actual } => {
                write!(f, "assignment length {actual}, expected {expected}")
            }
            Self::RoleOutOfRange => write!(f, "assignment contains a role outside the task range"),
            Self::InvalidEnumeratedSolution => {
                write!(f, "exact enumerator returned an invalid assignment")
            }
            Self::TaskSolutionMismatch => {
                write!(f, "solution classes were built for a different task")
            }
            Self::UnsatisfiableTask => {
                write!(f, "teacher requires at least one valid solution class")
            }
            Self::EmptySolutionClass => write!(f, "solution class has no represented assignments"),
            Self::Serialization => write!(f, "could not serialize task for identity hash"),
        }
    }
}

impl std::error::Error for TeacherError {}

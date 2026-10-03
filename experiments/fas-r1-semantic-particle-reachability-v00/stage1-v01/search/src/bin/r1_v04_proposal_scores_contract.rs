//! Input and teacher-row contracts for `r1_v04_proposal_scores`.

use hashbrown::{HashMap, HashSet};
use r1_stage1_search::Edit;
use r1_world::InferenceTask;
use serde::Deserialize;
use serde_json::Value;
use std::error::Error;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

pub(super) const TRAIN_STATES_PER_TASK: usize = 32;
pub(super) const EXPECTED_TRAIN_TASKS: usize = 64;
pub(super) const EXPECTED_VALIDATION_TASKS: usize = 16;

#[derive(Clone, Debug)]
pub(super) struct SupportTask {
    pub family_id: String,
    pub split: String,
}

#[derive(Clone, Debug, Deserialize)]
pub(super) struct TeacherRow {
    pub task_id: String,
    pub family_id: String,
    pub family_split: String,
    pub state_index: usize,
    pub assignment: Vec<u8>,
    pub target: TeacherTarget,
}

#[derive(Clone, Debug, Deserialize)]
pub(super) struct TeacherTarget {
    task_id: String,
    edits: Vec<TeacherEdit>,
}

#[derive(Clone, Debug, Deserialize)]
struct TeacherEdit {
    entity: u16,
    new_role: u8,
}

pub(super) fn legal_edits(
    task: &InferenceTask,
    assignment: &[u8],
) -> Result<Vec<Edit>, Box<dyn Error>> {
    if assignment.len() != usize::from(task.n) || assignment.iter().any(|role| *role >= task.k) {
        return Err(format!("invalid teacher assignment for {}", task.id).into());
    }
    let mut edits = Vec::with_capacity(usize::from(task.n) * usize::from(task.k - 1));
    for entity in 0..task.n {
        for role in 0..task.k {
            if assignment[usize::from(entity)] != role {
                edits.push(Edit {
                    entity,
                    new_role: role,
                });
            }
        }
    }
    Ok(edits)
}

pub(super) fn ensure_teacher_edit_order(
    row: &TeacherRow,
    candidates: &[Edit],
) -> Result<(), Box<dyn Error>> {
    if row.target.task_id != row.task_id || row.target.edits.len() != candidates.len() {
        return Err(format!(
            "teacher target/task/edit count mismatch for {}",
            row.task_id
        )
        .into());
    }
    for (target, candidate) in row.target.edits.iter().zip(candidates) {
        if target.entity != candidate.entity || target.new_role != candidate.new_role {
            return Err(format!(
                "teacher/runtime edit order mismatch for {}:{}",
                row.task_id, row.state_index
            )
            .into());
        }
    }
    Ok(())
}

pub(super) fn read_teacher_rows(
    path: &Path,
    support: &HashMap<String, SupportTask>,
    public: &HashMap<String, InferenceTask>,
) -> Result<Vec<TeacherRow>, Box<dyn Error>> {
    let mut rows = Vec::with_capacity(80 * TRAIN_STATES_PER_TASK);
    let mut states = HashMap::<String, HashSet<usize>>::new();
    for (line_index, line) in BufReader::new(File::open(path)?).lines().enumerate() {
        let line = line?;
        if line.trim().is_empty() {
            return Err(format!("blank teacher target line {}", line_index + 1).into());
        }
        let row = parse_trainval_teacher_row(line.as_bytes(), support)
            .map_err(|message| format!("teacher row {}: {message}", line_index + 1))?;
        let roster = &support[&row.task_id];
        if row.family_split != roster.split || row.family_id != roster.family_id {
            return Err(format!(
                "teacher split/family differs from support for {}",
                row.task_id
            )
            .into());
        }
        let task = public
            .get(&row.task_id)
            .ok_or_else(|| format!("teacher task {} is absent from public tasks", row.task_id))?;
        if task.family_id != row.family_id {
            return Err(format!(
                "teacher family differs from public task for {}",
                row.task_id
            )
            .into());
        }
        if row.state_index >= TRAIN_STATES_PER_TASK
            || !states
                .entry(row.task_id.clone())
                .or_default()
                .insert(row.state_index)
        {
            return Err(format!(
                "invalid or duplicate teacher state {}:{}",
                row.task_id, row.state_index
            )
            .into());
        }
        rows.push(row);
    }
    validate_trainval_state_coverage(support, &states)?;
    rows.sort_by(|left, right| {
        left.task_id
            .cmp(&right.task_id)
            .then(left.state_index.cmp(&right.state_index))
    });
    Ok(rows)
}

fn validate_trainval_state_coverage(
    support: &HashMap<String, SupportTask>,
    states: &HashMap<String, HashSet<usize>>,
) -> Result<(), Box<dyn Error>> {
    let expected_tasks: HashSet<&str> = support
        .iter()
        .filter(|(_, item)| item.split == "train" || item.split == "validation")
        .map(|(task_id, _)| task_id.as_str())
        .collect();
    if expected_tasks.len() != EXPECTED_TRAIN_TASKS + EXPECTED_VALIDATION_TASKS
        || states.len() != expected_tasks.len()
        || states.iter().any(|(task_id, observed)| {
            !expected_tasks.contains(task_id.as_str())
                || observed.len() != TRAIN_STATES_PER_TASK
                || (0..TRAIN_STATES_PER_TASK).any(|index| !observed.contains(&index))
        })
    {
        return Err(
            "teacher targets do not exactly cover 32 states for each train/validation task".into(),
        );
    }
    Ok(())
}

fn parse_trainval_teacher_row(
    bytes: &[u8],
    support: &HashMap<String, SupportTask>,
) -> Result<TeacherRow, String> {
    let value: Value = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    let split = value
        .get("family_split")
        .and_then(Value::as_str)
        .ok_or_else(|| "family_split is absent or not a string".to_owned())?;
    if split == "qualification" {
        return Err("qualification teacher row is prohibited".to_owned());
    }
    if split != "train" && split != "validation" {
        return Err(format!("unsupported teacher split {split:?}"));
    }
    let task_id = value
        .get("task_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "task_id is absent or not a string".to_owned())?;
    let roster = support
        .get(task_id)
        .ok_or_else(|| format!("teacher task {task_id} is absent from support"))?;
    if roster.split == "qualification" {
        return Err("qualification task ID is prohibited in teacher rows".to_owned());
    }
    if split != roster.split {
        return Err(format!("teacher split differs from support for {task_id}"));
    }
    let family_id = value
        .get("family_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "family_id is absent or not a string".to_owned())?;
    if family_id != roster.family_id {
        return Err(format!("teacher family differs from support for {task_id}"));
    }
    serde_json::from_value(value).map_err(|error| error.to_string())
}

pub(super) fn read_public_tasks(
    path: &Path,
) -> Result<HashMap<String, InferenceTask>, Box<dyn Error>> {
    let mut tasks = HashMap::with_capacity(96);
    for (line_index, line) in BufReader::new(File::open(path)?).lines().enumerate() {
        let line = line?;
        if line.trim().is_empty() {
            return Err(format!("blank public task line {}", line_index + 1).into());
        }
        let task: InferenceTask = serde_json::from_str(&line)?;
        if tasks.insert(task.id.clone(), task).is_some() {
            return Err(format!("duplicate public task id on line {}", line_index + 1).into());
        }
    }
    if tasks.len() != 96 {
        return Err(format!("expected 96 public tasks, found {}", tasks.len()).into());
    }
    Ok(tasks)
}

pub(super) fn read_support(path: &Path) -> Result<HashMap<String, SupportTask>, Box<dyn Error>> {
    let root: Value = serde_json::from_slice(&std::fs::read(path)?)?;
    if root.get("schema").and_then(Value::as_str) != Some("R1_STAGE1_STRESS_SENSOR_SUPPORT_V04") {
        return Err("support manifest is not the V04 schema".into());
    }
    let roster = root
        .get("family_roster")
        .and_then(Value::as_array)
        .ok_or("support manifest has no family_roster array")?;
    let mut tasks = HashMap::with_capacity(roster.len());
    let mut counts = HashMap::<String, usize>::new();
    for item in roster {
        let task_id = required_string(item, "task_id")?;
        let family_id = required_string(item, "family_id")?;
        let split = required_string(item, "split")?;
        if !matches!(split.as_str(), "train" | "validation" | "qualification") {
            return Err(format!("unsupported V04 support split {split:?}").into());
        }
        *counts.entry(split.clone()).or_default() += 1;
        if tasks
            .insert(task_id.clone(), SupportTask { family_id, split })
            .is_some()
        {
            return Err(format!("duplicate support task {task_id}").into());
        }
    }
    if tasks.len() != 96
        || counts.get("train") != Some(&EXPECTED_TRAIN_TASKS)
        || counts.get("validation") != Some(&EXPECTED_VALIDATION_TASKS)
        || counts.get("qualification") != Some(&16)
    {
        return Err("V04 support roster must be 64/16/16".into());
    }
    Ok(tasks)
}

fn required_string(value: &Value, key: &str) -> Result<String, Box<dyn Error>> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| format!("support roster row omits string {key}").into())
}

pub(super) fn validate_public_roster(
    support: &HashMap<String, SupportTask>,
    public: &HashMap<String, InferenceTask>,
) -> Result<(), Box<dyn Error>> {
    if support.len() != public.len() || support.keys().any(|task_id| !public.contains_key(task_id))
    {
        return Err("V04 support and public task rosters differ".into());
    }
    for (task_id, item) in support {
        let task = &public[task_id];
        if task.family_id != item.family_id
            || task.n != 20
            || task.k != 3
            || task.clauses.len() != 36
        {
            return Err(format!(
                "public task shape/family differs from V04 contract for {task_id}"
            )
            .into());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qualification_row_is_rejected_before_assignment_or_target_decode() {
        let row = br#"{"family_split":"qualification","task_id":"q0"}"#;
        let error = parse_trainval_teacher_row(row, &HashMap::new()).unwrap_err();
        assert!(error.contains("qualification"));
    }

    #[test]
    fn qualification_task_id_cannot_be_mislabeled_as_train_before_target_decode() {
        let mut support = HashMap::new();
        support.insert(
            "q0".to_owned(),
            SupportTask {
                family_id: "fq".to_owned(),
                split: "qualification".to_owned(),
            },
        );
        let row = br#"{"family_split":"train","task_id":"q0","family_id":"fq"}"#;
        let error = parse_trainval_teacher_row(row, &support).unwrap_err();
        assert!(error.contains("qualification task ID"));
    }

    #[test]
    fn train_and_validation_rows_are_the_only_accepted_splits() {
        for split in ["train", "validation"] {
            let mut support = HashMap::new();
            support.insert(
                "t0".to_owned(),
                SupportTask {
                    family_id: "f0".to_owned(),
                    split: split.to_owned(),
                },
            );
            let bytes = format!(
                "{{\"family_split\":\"{split}\",\"task_id\":\"t0\",\"family_id\":\"f0\",\"state_index\":0,\"assignment\":[0,1],\"target\":{{\"task_id\":\"t0\",\"edits\":[]}}}}"
            );
            assert!(parse_trainval_teacher_row(bytes.as_bytes(), &support).is_ok());
        }
        assert!(
            parse_trainval_teacher_row(br#"{"family_split":"test"}"#, &HashMap::new())
                .unwrap_err()
                .contains("unsupported teacher split")
        );
    }

    #[test]
    fn trainval_coverage_requires_all_eighty_tasks_and_all_thirty_two_states() {
        let mut support = HashMap::with_capacity(80);
        let mut states = HashMap::with_capacity(80);
        for index in 0..80 {
            let task_id = format!("t{index:02}");
            support.insert(
                task_id.clone(),
                SupportTask {
                    family_id: format!("f{index:02}"),
                    split: if index < EXPECTED_TRAIN_TASKS {
                        "train".to_owned()
                    } else {
                        "validation".to_owned()
                    },
                },
            );
            states.insert(task_id, (0..TRAIN_STATES_PER_TASK).collect());
        }
        assert!(validate_trainval_state_coverage(&support, &states).is_ok());
        states.get_mut("t79").unwrap().remove(&31);
        assert!(validate_trainval_state_coverage(&support, &states).is_err());
        states.remove("t79");
        assert!(validate_trainval_state_coverage(&support, &states).is_err());
    }

    #[test]
    fn legal_edits_follow_entity_then_new_role_order() {
        let task = InferenceTask {
            id: "task".into(),
            family_id: "family".into(),
            n: 2,
            k: 3,
            role_anonymous: true,
            global_text: String::new(),
            clauses: vec!["a".into()],
            entity_mentions: vec![vec![0, 1]],
            role_mentions: vec![vec![]],
        };
        let actual = legal_edits(&task, &[0, 1]).unwrap();
        let expected = [
            Edit {
                entity: 0,
                new_role: 1,
            },
            Edit {
                entity: 0,
                new_role: 2,
            },
            Edit {
                entity: 1,
                new_role: 0,
            },
            Edit {
                entity: 1,
                new_role: 2,
            },
        ];
        assert_eq!(actual, expected);
    }

    #[test]
    fn teacher_edit_order_mismatch_fails_closed() {
        let row = TeacherRow {
            task_id: "task".into(),
            family_id: "family".into(),
            family_split: "train".into(),
            state_index: 0,
            assignment: vec![0, 1],
            target: TeacherTarget {
                task_id: "task".into(),
                edits: vec![
                    TeacherEdit {
                        entity: 1,
                        new_role: 0,
                    },
                    TeacherEdit {
                        entity: 0,
                        new_role: 1,
                    },
                ],
            },
        };
        let candidates = [
            Edit {
                entity: 0,
                new_role: 1,
            },
            Edit {
                entity: 1,
                new_role: 0,
            },
        ];
        assert!(ensure_teacher_edit_order(&row, &candidates).is_err());
    }
}

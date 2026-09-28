use super::SplitRow;
use hashbrown::HashMap;
use r1_world::InferenceTask;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::error::Error;
use std::fs;
use std::path::Path;

const START_SCHEMA: &str = "R1_STAGE1_PUBLIC_SEARCH_START_V05";
const START_CONSUMER: &str = "Stage1 search runner only; excluded from sensor extraction";

#[derive(Clone, Debug)]
pub(super) struct SearchStart {
    pub assignment: Vec<u8>,
    pub paired_world_id: String,
    pub density_level: String,
    pub start_kind: String,
}

#[derive(Clone, Debug, Deserialize)]
pub(super) struct SearchStartSource {
    pub path: String,
    pub schema: String,
    pub sha256: String,
    pub bytes: usize,
    pub rows: usize,
    pub consumer: String,
}

#[derive(Debug)]
pub(super) struct LoadedSearchStarts {
    pub starts: HashMap<String, SearchStart>,
    pub sha256: Option<String>,
}

#[derive(Deserialize)]
struct SearchStartRow {
    schema: String,
    task_id: String,
    family_id: String,
    paired_world_id: String,
    density_level: String,
    start_kind: String,
    n: u16,
    k: u8,
    initialization_seed: Option<u64>,
    assignment_sha256: String,
    assignment: Vec<u8>,
}

pub(super) fn load_search_starts(
    path: Option<&Path>,
    source: Option<&SearchStartSource>,
    roster: &HashMap<String, SplitRow>,
    tasks: &HashMap<String, InferenceTask>,
) -> Result<LoadedSearchStarts, Box<dyn Error>> {
    let (Some(path), Some(source)) = (path, source) else {
        if path.is_some() || source.is_some() {
            return Err(
                "search-start file and support-manifest contract must be supplied together".into(),
            );
        }
        return Ok(LoadedSearchStarts {
            starts: HashMap::new(),
            sha256: None,
        });
    };
    if source.schema != START_SCHEMA
        || source.consumer != START_CONSUMER
        || source.rows != tasks.len()
        || path.file_name().and_then(|name| name.to_str()) != Some(source.path.as_str())
    {
        return Err("search-start support contract is incompatible with this runner".into());
    }
    let bytes = fs::read(path)?;
    let digest = sha256_hex(&bytes);
    if bytes.len() != source.bytes || digest != source.sha256.to_ascii_lowercase() {
        return Err("search-start sidecar does not match its support-manifest hash/size".into());
    }

    let mut starts = HashMap::with_capacity(source.rows);
    for (line_number, line) in bytes.split(|byte| *byte == b'\n').enumerate() {
        if line.is_empty() {
            continue;
        }
        let row: SearchStartRow = serde_json::from_slice(line)?;
        let task = tasks
            .get(&row.task_id)
            .ok_or("search-start sidecar contains an unknown task ID")?;
        let metadata = roster
            .get(&row.task_id)
            .ok_or("search-start sidecar task is absent from support roster")?;
        if row.schema != START_SCHEMA
            || row.family_id != task.family_id
            || row.family_id != metadata.family_id
            || row.n != task.n
            || row.k != task.k
            || row.assignment.len() != usize::from(task.n)
            || row.assignment.iter().any(|role| *role >= task.k)
            || row.paired_world_id.is_empty()
            || !matches!(row.density_level.as_str(), "base" | "dense")
            || row.assignment_sha256.to_ascii_lowercase() != sha256_hex(&row.assignment)
            || metadata.start_kind.as_deref() != Some(row.start_kind.as_str())
            || metadata.paired_world_id.as_deref() != Some(row.paired_world_id.as_str())
            || metadata.density_level.as_deref() != Some(row.density_level.as_str())
            || !valid_seed_contract(&row)
        {
            return Err(format!(
                "search-start row {} violates its task/support contract",
                line_number + 1
            )
            .into());
        }
        let start = SearchStart {
            assignment: row.assignment,
            paired_world_id: row.paired_world_id,
            density_level: row.density_level,
            start_kind: row.start_kind,
        };
        if starts.insert(row.task_id, start).is_some() {
            return Err("search-start sidecar contains duplicate task IDs".into());
        }
    }
    if starts.len() != tasks.len() || starts.keys().any(|task_id| !tasks.contains_key(task_id)) {
        return Err("search-start sidecar does not cover the complete public task roster".into());
    }
    Ok(LoadedSearchStarts {
        starts,
        sha256: Some(digest),
    })
}

fn valid_seed_contract(row: &SearchStartRow) -> bool {
    match row.start_kind.as_str() {
        "independent_random_assignment" => row.initialization_seed.is_some(),
        "witness_module1_swap_trap" => row.initialization_seed.is_none(),
        _ => false,
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

    fn fixture() -> (HashMap<String, SplitRow>, HashMap<String, InferenceTask>) {
        let task = InferenceTask {
            id: "task-1".to_owned(),
            family_id: "family-1".to_owned(),
            n: 2,
            k: 2,
            role_anonymous: true,
            global_text: "fixture".to_owned(),
            clauses: Vec::new(),
            entity_mentions: Vec::new(),
            role_mentions: Vec::new(),
        };
        let metadata = SplitRow {
            task_id: task.id.clone(),
            family_id: task.family_id.clone(),
            split: "qualification".to_owned(),
            paired_world_id: Some("pair-1".to_owned()),
            density_level: Some("base".to_owned()),
            start_kind: Some("independent_random_assignment".to_owned()),
        };
        (
            HashMap::from([(task.id.clone(), metadata)]),
            HashMap::from([(task.id.clone(), task)]),
        )
    }

    fn row(assignment: Vec<u8>) -> serde_json::Value {
        serde_json::json!({
            "schema": START_SCHEMA,
            "task_id": "task-1",
            "family_id": "family-1",
            "paired_world_id": "pair-1",
            "density_level": "base",
            "start_kind": "independent_random_assignment",
            "n": 2,
            "k": 2,
            "initialization_seed": 19,
            "assignment_sha256": sha256_hex(&assignment),
            "assignment": assignment,
        })
    }

    fn write_sidecar(bytes: &[u8]) -> (PathBuf, SearchStartSource) {
        let sequence = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "r1-search-start-{}-{sequence}.jsonl",
            std::process::id()
        ));
        fs::write(&path, bytes).unwrap();
        let source = SearchStartSource {
            path: path.file_name().unwrap().to_string_lossy().into_owned(),
            schema: START_SCHEMA.to_owned(),
            sha256: sha256_hex(bytes),
            bytes: bytes.len(),
            rows: 1,
            consumer: START_CONSUMER.to_owned(),
        };
        (path, source)
    }

    #[test]
    fn accepts_hash_bound_complete_start_roster() {
        let (roster, tasks) = fixture();
        let mut bytes = serde_json::to_vec(&row(vec![1, 0])).unwrap();
        bytes.push(b'\n');
        let (path, source) = write_sidecar(&bytes);
        let result = load_search_starts(Some(&path), Some(&source), &roster, &tasks);
        let _ = fs::remove_file(path);
        let loaded = result.unwrap();
        let starts = loaded.starts;
        assert_eq!(starts["task-1"].assignment, [1, 0]);
        assert_eq!(starts["task-1"].paired_world_id, "pair-1");
        assert_eq!(starts["task-1"].density_level, "base");
        assert_eq!(starts["task-1"].start_kind, "independent_random_assignment");
        assert_eq!(loaded.sha256.as_deref(), Some(source.sha256.as_str()));
    }

    #[test]
    fn rejects_sidecar_bytes_that_do_not_match_support_hash() {
        let (roster, tasks) = fixture();
        let mut bytes = serde_json::to_vec(&row(vec![1, 0])).unwrap();
        bytes.push(b'\n');
        let (path, mut source) = write_sidecar(&bytes);
        source.sha256 = "0".repeat(64);
        let result = load_search_starts(Some(&path), Some(&source), &roster, &tasks);
        let _ = fs::remove_file(path);
        assert!(result.unwrap_err().to_string().contains("hash/size"));
    }

    #[test]
    fn rejects_duplicate_task_rows_and_out_of_range_roles() {
        let (roster, tasks) = fixture();
        let valid = serde_json::to_vec(&row(vec![1, 0])).unwrap();
        let mut duplicate = valid.clone();
        duplicate.push(b'\n');
        duplicate.extend_from_slice(&valid);
        duplicate.push(b'\n');
        let (path, source) = write_sidecar(&duplicate);
        let duplicate_result = load_search_starts(Some(&path), Some(&source), &roster, &tasks);
        let _ = fs::remove_file(path);
        assert!(duplicate_result
            .unwrap_err()
            .to_string()
            .contains("duplicate task IDs"));

        let invalid = serde_json::to_vec(&row(vec![2, 0])).unwrap();
        let mut invalid = invalid;
        invalid.push(b'\n');
        let (path, source) = write_sidecar(&invalid);
        let invalid_result = load_search_starts(Some(&path), Some(&source), &roster, &tasks);
        let _ = fs::remove_file(path);
        assert!(invalid_result
            .unwrap_err()
            .to_string()
            .contains("violates its task/support contract"));
    }
}

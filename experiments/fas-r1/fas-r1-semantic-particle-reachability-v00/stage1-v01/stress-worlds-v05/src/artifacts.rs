use hashbrown::HashSet;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{StressError, StressWorld};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SearchStartRow {
    pub schema: String,
    pub task_id: String,
    pub family_id: String,
    pub paired_world_id: String,
    pub density_level: String,
    pub start_kind: String,
    pub n: u16,
    pub k: u8,
    pub initialization_seed: Option<u64>,
    pub assignment_sha256: String,
    pub assignment: Vec<u8>,
}

impl SearchStartRow {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        task_id: String,
        family_id: String,
        paired_world_id: String,
        density_level: String,
        start_kind: &str,
        n: u16,
        k: u8,
        initialization_seed: Option<u64>,
        assignment: Vec<u8>,
    ) -> Self {
        Self {
            schema: "R1_STAGE1_PUBLIC_SEARCH_START_V05".into(),
            task_id,
            family_id,
            paired_world_id,
            density_level,
            start_kind: start_kind.to_owned(),
            n,
            k,
            initialization_seed,
            assignment_sha256: sha256_hex(&assignment),
            assignment,
        }
    }
}

#[derive(Serialize)]
struct PrivateDiagnosticsRow<'a> {
    task_id: &'a str,
    family_id: &'a str,
    paired_world_id: &'a str,
    scenario_id: &'a str,
    seed: u64,
    planted_assignment: &'a [u8],
    module_anchors: &'a [[u16; 3]; 4],
    decoy_conflict_clause_indices: &'a [usize],
    exact_count_status: &'static str,
    raw_solution_count: usize,
    canonical_solution_class_count: usize,
    role_automorphism_count: usize,
}

#[derive(Serialize)]
pub struct SupportManifest<'a> {
    pub schema: &'static str,
    pub status: &'static str,
    pub source: SupportSource,
    pub config: ConfigSource,
    pub search_starts: SearchStartSource,
    pub family_roster: Vec<FamilyRosterEntry<'a>>,
    pub split_counts: SplitCounts,
    pub paired_world_count: usize,
    pub scenario_counts: Vec<ScenarioCounts>,
    pub split_contract: &'static str,
    pub start_contract: &'static str,
}

#[derive(Serialize)]
pub struct SupportSource {
    pub path: &'static str,
    pub sha256: String,
    pub bytes: usize,
    pub rows: usize,
}

#[derive(Serialize)]
pub struct ConfigSource {
    pub path: &'static str,
    pub sha256: String,
    pub bytes: usize,
}

#[derive(Serialize)]
pub struct SearchStartSource {
    pub path: &'static str,
    pub schema: &'static str,
    pub sha256: String,
    pub bytes: usize,
    pub rows: usize,
    pub consumer: &'static str,
}

#[derive(Serialize)]
pub struct FamilyRosterEntry<'a> {
    pub task_id: &'a str,
    pub family_id: &'a str,
    pub paired_world_id: &'a str,
    pub scenario_id: &'a str,
    pub density_level: &'a str,
    pub start_kind: &'a str,
    pub split: &'static str,
}

#[derive(Serialize)]
pub struct SplitCounts {
    pub train: usize,
    pub validation: usize,
    pub qualification: usize,
}

#[derive(Serialize)]
pub struct ScenarioCounts {
    pub scenario_id: &'static str,
    pub train: usize,
    pub validation: usize,
    pub qualification: usize,
}

pub fn public_projection_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| &world.rendered.inference))
}

pub fn public_search_starts_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| &world.search_start))
}

pub fn private_task_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| &world.task))
}

pub fn private_diagnostics_bytes(worlds: &[StressWorld]) -> Result<Vec<u8>, StressError> {
    jsonl_bytes(worlds.iter().map(|world| PrivateDiagnosticsRow {
        task_id: &world.task.id,
        family_id: &world.task.family_id,
        paired_world_id: &world.record.paired_world_id,
        scenario_id: &world.record.scenario_id,
        seed: world.task.seed,
        planted_assignment: &world.private_diagnostics.planted_assignment,
        module_anchors: &world.private_diagnostics.module_anchors,
        decoy_conflict_clause_indices: &world.private_diagnostics.decoy_conflict_clause_indices,
        exact_count_status: world.record.exact_count_status,
        raw_solution_count: world.record.raw_solution_count,
        canonical_solution_class_count: world.record.canonical_solution_class_count,
        role_automorphism_count: world.record.role_automorphism_count,
    }))
}

fn jsonl_bytes<'a, T: Serialize + 'a>(
    rows: impl Iterator<Item = T>,
) -> Result<Vec<u8>, StressError> {
    let mut bytes = Vec::new();
    for row in rows {
        serde_json::to_writer(&mut bytes, &row)
            .map_err(|error| StressError(format!("serialize JSONL row: {error}")))?;
        bytes.push(b'\n');
    }
    Ok(bytes)
}

pub fn make_support_manifest<'a>(
    public_bytes: &[u8],
    search_start_bytes: &[u8],
    config_bytes: &[u8],
    worlds: &'a [StressWorld],
) -> SupportManifest<'a> {
    let scenario_ids = [
        "base-random",
        "base-swap-trap",
        "dense-random",
        "dense-swap-trap",
    ];
    let scenario_counts = scenario_ids
        .iter()
        .map(|scenario_id| ScenarioCounts {
            scenario_id,
            train: count_scenario_split(worlds, scenario_id, "train"),
            validation: count_scenario_split(worlds, scenario_id, "validation"),
            qualification: count_scenario_split(worlds, scenario_id, "qualification"),
        })
        .collect();
    let mut paired_ids = HashSet::with_capacity(worlds.len());
    for world in worlds {
        paired_ids.insert(world.record.paired_world_id.as_str());
    }
    SupportManifest {
        schema: "R1_STAGE1_STRESS_SENSOR_SUPPORT_V05_1",
        status: "STRESS_TRAIN_VALIDATION_QUALIFICATION_READY",
        source: SupportSource {
            path: "public-tasks.jsonl",
            sha256: sha256_hex(public_bytes),
            bytes: public_bytes.len(),
            rows: worlds.len(),
        },
        config: ConfigSource {
            path: "stress-config-v05.json",
            sha256: sha256_hex(config_bytes),
            bytes: config_bytes.len(),
        },
        search_starts: SearchStartSource {
            path: "public-search-starts-v05.jsonl",
            schema: "R1_STAGE1_PUBLIC_SEARCH_START_V05",
            sha256: sha256_hex(search_start_bytes),
            bytes: search_start_bytes.len(),
            rows: worlds.len(),
            consumer: "Stage1 search runner only; excluded from sensor extraction",
        },
        family_roster: worlds
            .iter()
            .map(|world| FamilyRosterEntry {
                task_id: &world.task.id,
                family_id: &world.task.family_id,
                paired_world_id: &world.record.paired_world_id,
                scenario_id: &world.record.scenario_id,
                density_level: &world.record.density_level,
                start_kind: &world.record.start_kind,
                split: world.record.split,
            })
            .collect(),
        split_counts: SplitCounts {
            train: worlds
                .iter()
                .filter(|world| world.record.split == "train")
                .count(),
            validation: worlds
                .iter()
                .filter(|world| world.record.split == "validation")
                .count(),
            qualification: worlds
                .iter()
                .filter(|world| world.record.split == "qualification")
                .count(),
        },
        paired_world_count: paired_ids.len(),
        scenario_counts,
        split_contract: "24 underlying seeds; all four variants of each paired_world_id stay in one split; 16/4/4 seed groups produce 64/16/16 task rows",
        start_contract: "public-search-starts-v05.jsonl is a declared search input, not a sensor-extraction input",
    }
}

fn count_scenario_split(worlds: &[StressWorld], scenario_id: &str, split: &str) -> usize {
    worlds
        .iter()
        .filter(|world| world.record.scenario_id == scenario_id && world.record.split == split)
        .count()
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

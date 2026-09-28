use std::fs;
use std::path::Path;

use hashbrown::HashMap;
use sha2::{Digest, Sha256};

use crate::protocol::{Candidate, StateSnapshot};

pub const EXPECTED_MODEL_STATES_SHA256: &str =
    "895b3b4b16748bd429fd5f86007411b1658698fb523efa07d0088e1a3cab525d";
pub const EXPECTED_DATASET_SHA256: [&str; 3] = [
    "82249938c79f82d2d484780602244f424f3a5b4a831fca666a04229e32491b8c",
    "005388d66f614e49a60f15c7ac19a00dd8b35fb0febbefdef93326fa766cd67f",
    "c5ee81741b5cfc7f20db776e42ef612885c28a0c0454bae5bb72c2b6dd2d33f8",
];

#[derive(Clone, Debug)]
pub struct ExpectedState {
    pub fingerprint: String,
    pub evaluation_candidate_count: usize,
}

#[derive(Clone, Debug)]
pub struct R2Receipt {
    pub states: HashMap<String, ExpectedState>,
    pub candidate_utilities: HashMap<String, f64>,
    pub gradient_partitions: HashMap<String, u8>,
    pub model_states_sha256: String,
    pub dataset_sha256: [String; 3],
}

impl R2Receipt {
    pub fn load(root: &Path) -> Result<Self, String> {
        let state_path = root.join("states.csv");
        let candidate_path = root.join("candidate-index.csv");
        let partition_path = root.join("partitions.csv");
        let model_path = root.join("model-states.bin");
        let states = load_states(&state_path)?;
        let candidate_utilities = load_candidate_utilities(&candidate_path)?;
        let gradient_partitions = load_gradient_partitions(&partition_path)?;
        let model_states_sha256 = sha256_file(&model_path)?;
        if model_states_sha256 != EXPECTED_MODEL_STATES_SHA256 {
            return Err(format!(
                "R2 model-state hash mismatch: {}",
                model_states_sha256
            ));
        }
        let mut dataset_sha256 = std::array::from_fn(|_| String::new());
        for (index, digest) in dataset_sha256.iter_mut().enumerate() {
            *digest = sha256_file(&root.join(format!("dataset-d{index:02}.bin")))?;
            if digest != EXPECTED_DATASET_SHA256[index] {
                return Err(format!("R2 dataset d{index:02} hash mismatch: {digest}"));
            }
        }
        Ok(Self {
            states,
            candidate_utilities,
            gradient_partitions,
            model_states_sha256,
            dataset_sha256,
        })
    }

    pub fn validate_state(&self, state: &StateSnapshot) -> Result<(), String> {
        let key = state_key(
            state.dataset_index,
            state.initialization_index,
            state.seed,
            state.step,
        );
        let expected = self
            .states
            .get(&key)
            .ok_or_else(|| format!("missing R2 checkpoint receipt for {key}"))?;
        if format!("{:016x}", state.fingerprint) != expected.fingerprint {
            return Err(format!("R2 replay fingerprint mismatch at {key}"));
        }
        if state.evaluation_candidates.len() != expected.evaluation_candidate_count {
            return Err(format!("R2 replay candidate count mismatch at {key}"));
        }
        for candidate in &state.evaluation_candidates {
            let candidate_key = candidate_key(
                state.dataset_index,
                state.initialization_index,
                state.seed,
                state.step,
                candidate,
            );
            let expected_utility = self
                .candidate_utilities
                .get(&candidate_key)
                .ok_or_else(|| format!("missing R2 candidate receipt for {candidate_key}"))?;
            if (candidate.exact_utility[0] - expected_utility).abs() > 1.0e-10 {
                return Err(format!("R2 candidate utility mismatch at {candidate_key}"));
            }
        }
        Ok(())
    }

    pub fn validate_gradient_partition(
        &self,
        state: &StateSnapshot,
        ids: &[u8; crate::model::TRAIN_SAMPLES],
    ) -> Result<(), String> {
        for (sample, &stratum) in ids.iter().enumerate() {
            let key = partition_key(state.seed, state.step, sample);
            let expected = self
                .gradient_partitions
                .get(&key)
                .ok_or_else(|| format!("missing R2 gradient partition for {key}"))?;
            if stratum != *expected {
                return Err(format!("R2 gradient partition mismatch at {key}"));
            }
        }
        Ok(())
    }
}

pub fn state_key(dataset: u8, initialization: u8, seed: u64, step: usize) -> String {
    format!("{dataset}:{initialization}:{seed:016x}:{step}")
}

pub fn candidate_key(
    dataset: u8,
    initialization: u8,
    seed: u64,
    step: usize,
    candidate: &Candidate,
) -> String {
    format!(
        "{dataset}:{initialization}:{seed:016x}:{step}:{}:{}:{}:{}:{}",
        candidate.block,
        candidate.left_parameter,
        candidate.right_parameter,
        candidate.left_rank,
        candidate.right_rank
    )
}

fn partition_key(seed: u64, step: usize, sample: usize) -> String {
    format!("{seed:016x}:{step}:{sample}")
}

fn load_states(path: &Path) -> Result<HashMap<String, ExpectedState>, String> {
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut result = HashMap::new();
    for line in text.lines().skip(1) {
        let fields: Vec<_> = line.split(',').collect();
        if fields.len() != 13 || fields[0] != "evaluation" {
            continue;
        }
        let dataset = parse_u8(fields[1])?;
        let initialization = parse_u8(fields[3])?;
        let seed = parse_hex(fields[5])?;
        let step = fields[6]
            .parse::<usize>()
            .map_err(|error| error.to_string())?;
        let key = state_key(dataset, initialization, seed, step);
        result.insert(
            key,
            ExpectedState {
                fingerprint: fields[8].to_owned(),
                evaluation_candidate_count: fields[10]
                    .parse()
                    .map_err(|error: std::num::ParseIntError| error.to_string())?,
            },
        );
    }
    if result.len() != 54 {
        return Err(format!(
            "expected 54 R2 eval state receipts, got {}",
            result.len()
        ));
    }
    Ok(result)
}

fn load_candidate_utilities(path: &Path) -> Result<HashMap<String, f64>, String> {
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut result = HashMap::new();
    for line in text.lines().skip(1) {
        let fields: Vec<_> = line.split(',').collect();
        if fields.len() != 16 || fields[7] != "evaluation" {
            continue;
        }
        let dataset = parse_u8(fields[1])?;
        let initialization = parse_u8(fields[2])?;
        let seed = parse_hex(fields[5])?;
        let step = fields[6]
            .parse::<usize>()
            .map_err(|error| error.to_string())?;
        let key = format!(
            "{dataset}:{initialization}:{seed:016x}:{step}:{}:{}:{}:{}:{}",
            fields[8], fields[9], fields[10], fields[11], fields[12]
        );
        let utility = fields[15]
            .parse::<f64>()
            .map_err(|error| error.to_string())?;
        result.insert(key, utility);
    }
    if result.len() != 18_334 {
        return Err(format!(
            "expected 18,334 R2 eval candidates, got {}",
            result.len()
        ));
    }
    Ok(result)
}

fn load_gradient_partitions(path: &Path) -> Result<HashMap<String, u8>, String> {
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut result = HashMap::new();
    for line in text.lines().skip(1) {
        let fields: Vec<_> = line.split(',').collect();
        if fields.len() != 10 || fields[0] != "evaluation" || fields[5] != "gradient_full171" {
            continue;
        }
        let seed = parse_hex(fields[3])?;
        let step = fields[4]
            .parse::<usize>()
            .map_err(|error| error.to_string())?;
        let sample = fields[6]
            .parse::<usize>()
            .map_err(|error| error.to_string())?;
        let stratum = parse_u8(fields[7])?;
        result.insert(partition_key(seed, step, sample), stratum);
    }
    if result.len() != 54 * crate::model::TRAIN_SAMPLES {
        return Err(format!(
            "unexpected R2 gradient partition rows: {}",
            result.len()
        ));
    }
    Ok(result)
}

fn parse_u8(value: &str) -> Result<u8, String> {
    value.parse::<u8>().map_err(|error| error.to_string())
}

fn parse_hex(value: &str) -> Result<u64, String> {
    u64::from_str_radix(value, 16).map_err(|error| error.to_string())
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|error| error.to_string())?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

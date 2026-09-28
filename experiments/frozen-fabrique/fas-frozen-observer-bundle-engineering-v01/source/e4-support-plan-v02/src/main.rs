use std::{
    env,
    fs::File,
    path::{Path, PathBuf},
};

use hashbrown::HashSet;
use memchr::memchr_iter;
use memmap2::MmapOptions;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const TARGET: u64 = 250;
const SEED: u64 = 2_026_092_605;
const NAMESPACE: &str = "FAS-E4-0-POP-V01";
const INPUTS_SHA256: &str = "9f0076daa147bac37aa80d4f9a55f9225289910ceb8acc41998354c5a166917a";
const TERMS_SHA256: &str = "43b793068ad759a7ec77bd0027e7113a0145a35b1daacb8ea1cefa551803c672";
const INPUT_CHOICE_DOMAIN: &[u8] = b"FAS-E4-0-CANDIDATE-CHOICE-v01\0";
const OBSERVATIONS: [&str; 8] = [
    "In {context}, the {entity} has {relation} {state}.",
    "For {context}: {relation} of {entity} = {state}.",
    "Within {context}, {entity} is recorded as {state} for {relation}.",
    "The {relation} entry for {entity} at {context} reads {state}.",
    "Record: {context} / {entity} / {relation} -> {state}.",
    "{entity} at {context} carries {state} under {relation}.",
    "Index {relation}: {entity} in {context} maps to {state}.",
    "Fact [{context}; {entity}; {relation}] = {state}.",
];
const QUERIES: [&str; 8] = [
    "What is {relation} for {entity} in {context}?",
    "Find the {relation} of {entity} at {context}.",
    "Select {relation}({context}, {entity}).",
    "Report {entity}'s {relation} within {context}.",
    "Return current {relation}: {context} / {entity}.",
    "Which value is stored for {relation} and {entity} under {context}?",
    "Give the {relation} linked to {entity} in {context}.",
    "Look up {context} -> {entity} -> {relation}.",
];
const RELATIONS: [&str; 2] = ["kelmori", "vethaku"];
const STATES: [&str; 3] = ["brinok", "saldem", "tovira"];
const ORDERS: [[usize; 3]; 6] = [
    [0, 1, 2],
    [0, 2, 1],
    [1, 0, 2],
    [1, 2, 0],
    [2, 0, 1],
    [2, 1, 0],
];

#[derive(Deserialize)]
struct InputRow {
    input_text: String,
}

#[derive(Deserialize)]
struct Terms {
    context_terms: Vec<String>,
    entity_terms: Vec<String>,
}

#[derive(Default, Serialize)]
struct Support {
    context_identity: [u64; 32],
    entity_identity: [u64; 32],
    relation: [u64; 2],
    observed_state: [u64; 3],
    exact_target_by_stratum: [[u64; 3]; 4],
}

impl Support {
    fn meets_target(&self) -> bool {
        self.context_identity.iter().all(|n| *n >= TARGET)
            && self.entity_identity.iter().all(|n| *n >= TARGET)
            && self.relation.iter().all(|n| *n >= TARGET)
            && self.observed_state.iter().all(|n| *n >= TARGET)
            && self
                .exact_target_by_stratum
                .iter()
                .all(|counts| counts.iter().all(|n| *n >= TARGET))
    }
}

fn sha256(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        write!(&mut out, "{byte:02x}").unwrap();
    }
    out
}

fn mapped_sha256(path: &Path) -> Result<([u8; 32], memmap2::Mmap), String> {
    let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    // The sealed E1 inputs are read-only mapped to avoid an extra 34 MB heap copy.
    let map = unsafe { MmapOptions::new().map(&file) }
        .map_err(|e| format!("mmap {}: {e}", path.display()))?;
    Ok((sha256(&map), map))
}

fn load_e1_input_hashes(path: &Path) -> Result<HashSet<[u8; 32]>, String> {
    let (digest, map) = mapped_sha256(path)?;
    if hex(&digest) != INPUTS_SHA256 {
        return Err("E1 input file SHA-256 differs from the sealed E1 v04 identity".into());
    }
    let mut unique = HashSet::with_capacity(110_000);
    let mut start = 0;
    for newline in memchr_iter(b'\n', &map) {
        let mut line = &map[start..newline];
        if line.last() == Some(&b'\r') {
            line = &line[..line.len() - 1];
        }
        let row: InputRow = serde_json::from_slice(line)
            .map_err(|e| format!("decode sealed E1 input row at byte {start}: {e}"))?;
        unique.insert(sha256(row.input_text.as_bytes()));
        start = newline + 1;
    }
    if start < map.len() {
        let row: InputRow = serde_json::from_slice(&map[start..])
            .map_err(|e| format!("decode final sealed E1 input row: {e}"))?;
        unique.insert(sha256(row.input_text.as_bytes()));
    }
    Ok(unique)
}

fn render(template: &str, context: &str, entity: &str, relation: &str, state: &str) -> String {
    template
        .replace("{context}", context)
        .replace("{entity}", entity)
        .replace("{relation}", relation)
        .replace("{state}", state)
}

fn render_input(
    context: &str,
    entity: &str,
    relation: &str,
    state: &str,
    obs_id: usize,
    query_id: usize,
    order_id: usize,
) -> String {
    let observation = render(OBSERVATIONS[obs_id], context, entity, relation, state);
    let query = render(QUERIES[query_id], context, entity, relation, "");
    let options = ORDERS[order_id]
        .iter()
        .map(|candidate| STATES[*candidate])
        .collect::<Vec<_>>()
        .join(", ");
    format!("{observation}\n{query}\nOptions: {options}")
}

fn choice_permutation(ordinal: u64) -> (usize, usize) {
    let mut digest = Sha256::new();
    digest.update(INPUT_CHOICE_DOMAIN);
    digest.update(NAMESPACE.as_bytes());
    digest.update([0]);
    digest.update(SEED.to_le_bytes());
    digest.update(ordinal.to_le_bytes());
    let bytes = digest.finalize();
    let start_raw = u32::from_le_bytes(bytes[..4].try_into().unwrap());
    let step_raw = u32::from_le_bytes(bytes[4..8].try_into().unwrap());
    let modulus = 8 * 8 * 6;
    let start = start_raw as usize % modulus;
    let mut step = step_raw as usize % modulus;
    while gcd(step, modulus) != 1 {
        step = (step + 1) % modulus;
    }
    (start, step)
}

fn gcd(mut a: usize, mut b: usize) -> usize {
    while b != 0 {
        (a, b) = (b, a % b);
    }
    a
}

fn choose_rendering(
    used: &mut HashSet<[u8; 32]>,
    ordinal: u64,
    context_base: &str,
    context_partner: &str,
    entity_base: &str,
    entity_partner: &str,
    relation: &str,
    state: &str,
) -> Result<(usize, usize, usize, u64), String> {
    let mut tried = [false; 8 * 8 * 6];
    let mut tried_count = 0;
    let (start, step) = choice_permutation(ordinal);
    for candidate_counter in 0..(8 * 8 * 6) as u64 {
        let choice = (start + candidate_counter as usize * step) % (8 * 8 * 6);
        debug_assert!(!tried[choice]);
        tried[choice] = true;
        tried_count += 1;
        let query_id = choice / 48;
        let observation_id = (choice % 48) / 6;
        let order_id = choice % 6;
        let observation_ids = [
            observation_id,
            observation_id,
            observation_id,
            (observation_id + 4) % 8,
        ];
        let pairs = [
            (context_base, entity_base),
            (context_partner, entity_base),
            (context_base, entity_partner),
            (context_base, entity_base),
        ];
        let hashes: [[u8; 32]; 4] = std::array::from_fn(|i| {
            sha256(
                render_input(
                    pairs[i].0,
                    pairs[i].1,
                    relation,
                    state,
                    observation_ids[i],
                    query_id,
                    order_id,
                )
                .as_bytes(),
            )
        });
        let no_internal_duplicate =
            (0..4).all(|left| (left + 1..4).all(|right| hashes[left] != hashes[right]));
        if no_internal_duplicate && hashes.iter().all(|hash| !used.contains(hash)) {
            used.extend(hashes);
            return Ok((observation_id, query_id, order_id, candidate_counter));
        }
    }
    Err(format!(
        "all {tried_count} unique render choices collide for schedule ordinal {ordinal}"
    ))
}

fn target_position(order: usize, state: usize) -> usize {
    ORDERS[order]
        .iter()
        .position(|candidate| *candidate == state)
        .unwrap()
}

fn add_quartet(
    support: &mut Support,
    context_split: u8,
    entity_split: u8,
    relation_id: u8,
    state_id: u8,
    context_pair: u8,
    entity_pair: u8,
    order: usize,
) {
    let context_start = context_split * 16;
    let entity_start = entity_split * 16;
    let context_base = context_start + context_pair;
    let context_partner = context_start + (context_pair + 7) % 16;
    let entity_base = entity_start + entity_pair;
    let entity_partner = entity_start + (entity_pair + 7) % 16;
    let target = target_position(order, state_id as usize);
    for (context_id, entity_id) in [
        (context_base, entity_base),
        (context_partner, entity_base),
        (context_base, entity_partner),
        (context_base, entity_base),
    ] {
        support.context_identity[context_id as usize] += 1;
        support.entity_identity[entity_id as usize] += 1;
        let stratum = match (context_id >= 16, entity_id >= 16) {
            (false, false) => 0,
            (true, false) => 1,
            (false, true) => 2,
            (true, true) => 3,
        };
        support.exact_target_by_stratum[stratum][target] += 1;
        if context_id < 16 && entity_id < 16 {
            support.relation[relation_id as usize] += 1;
            support.observed_state[state_id as usize] += 1;
        }
    }
}

fn load_terms(path: &Path) -> Result<Terms, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    if hex(&sha256(&bytes)) != TERMS_SHA256 {
        return Err("E1 term inventory SHA-256 differs from sealed E1 v04 identity".into());
    }
    serde_json::from_slice(&bytes).map_err(|e| format!("decode E1 term inventory: {e}"))
}

fn e1_root() -> PathBuf {
    PathBuf::from(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04")
}

fn main() -> Result<(), String> {
    let root = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(e1_root);
    let mut used = load_e1_input_hashes(&root.join("panel/panel-inputs-v01.jsonl"))?;
    let e1_unique_count = used.len();
    let terms = load_terms(&root.join("corpus/term-inventory-v01.json"))?;
    if terms.context_terms.len() != 32 || terms.entity_terms.len() != 32 {
        return Err("sealed E1 inventory must contain 32 IDs for each identity role".into());
    }
    let mut support = Support::default();
    let mut query_rows = [0_u64; 8];
    let mut observation_rows = [0_u64; 8];
    let mut prefix = 0_u64;
    let mut counter_sum = 0_u64;
    let mut max_counter = 0_u64;
    'factorial: for context_split in 0..2_u8 {
        for entity_split in 0..2_u8 {
            for family in 0..8_u8 {
                for relation in 0..2_u8 {
                    for state in 0..3_u8 {
                        for _scheduled_query in 0..8_u8 {
                            let offset = (3 * family
                                + 5 * relation
                                + 7 * state
                                + 11 * context_split
                                + 13 * entity_split)
                                % 16;
                            for context_pair in 0..16_u8 {
                                let entity_pair = (context_pair + offset) % 16;
                                let cs = context_split * 16;
                                let es = entity_split * 16;
                                let (obs, query, order, counter) = choose_rendering(
                                    &mut used,
                                    prefix,
                                    &terms.context_terms[(cs + context_pair) as usize],
                                    &terms.context_terms[(cs + (context_pair + 7) % 16) as usize],
                                    &terms.entity_terms[(es + entity_pair) as usize],
                                    &terms.entity_terms[(es + (entity_pair + 7) % 16) as usize],
                                    RELATIONS[relation as usize],
                                    STATES[state as usize],
                                )?;
                                counter_sum += counter;
                                max_counter = max_counter.max(counter);
                                query_rows[query] += 4;
                                observation_rows[obs] += 3;
                                observation_rows[(obs + 4) % 8] += 1;
                                add_quartet(
                                    &mut support,
                                    context_split,
                                    entity_split,
                                    relation,
                                    state,
                                    context_pair,
                                    entity_pair,
                                    order,
                                );
                                prefix += 1;
                                if support.meets_target() {
                                    break 'factorial;
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    if !support.meets_target() {
        return Err("factorial schedule did not reach the 250/class construction target".into());
    }
    let rows = prefix * 4;
    let primary_bytes = rows * 8_192;
    let all_strata_bytes = primary_bytes * 3;
    let receipt = serde_json::json!({
        "receipt_id": "FAS_E4_0_SYMBOLIC_SUPPORT_PLAN_V02",
        "status": "MODEL_FREE_COLLISION_AWARE_SYMBOLIC_PLAN_ONLY",
        "population_rows_written": false,
        "tokenizer_contacted": false,
        "model_contacted": false,
        "labels_opened": false,
        "e1_input_rows": 106_496,
        "e1_unique_rendered_input_hashes": e1_unique_count,
        "e1_input_sha256": INPUTS_SHA256,
        "e1_term_inventory_sha256": TERMS_SHA256,
        "population_namespace": NAMESPACE,
        "world_render_seed_u64": SEED,
        "construction_target_rows_per_class": TARGET,
        "collision_rule": "For each schedule ordinal, derive a SHA-256 start and coprime step to enumerate all 384 query/observation/order combinations exactly once. Reject a whole quartet if any exact UTF-8 rendered-input SHA-256 is present in E1 or an earlier accepted E4 quartet. First collision-free combination wins; fail closed if all 384 are exhausted.",
        "selected_whole_quartet_prefix": prefix,
        "factorial_quartets_in_prefix": prefix,
        "binding_context_quartets_in_prefix": 0,
        "binding_entity_quartets_in_prefix": 0,
        "candidate_counter_sum": counter_sum,
        "maximum_candidate_counter": max_counter,
        "rows_in_primary_seen_and_lexical_population": rows,
        "minimum_support_by_endpoint_and_stratum": support,
        "primary_query_template_rows": query_rows,
        "primary_observation_template_rows": observation_rows,
        "feature_bytes_primary_only": primary_bytes,
        "planning_full_stratum_copies": 3,
        "feature_bytes_all_strata": all_strata_bytes,
        "feature_atomic_staging_bytes": all_strata_bytes,
        "two_feature_copies_peak_bytes": 2 * all_strata_bytes,
        "feature_bytes_per_row": 8_192,
        "resource_note": "Three full panel copies conservatively bound seen, held-out-template, and joint template-plus-lexical rows; contract must bind the exact selected stratum schedule before seal.",
    });
    println!("{}", serde_json::to_string_pretty(&receipt).unwrap());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{ORDERS, Support, choice_permutation, gcd};

    #[test]
    fn all_candidate_orders_cover_each_target_position_once() {
        for order in ORDERS {
            let mut positions = order.to_vec();
            positions.sort_unstable();
            assert_eq!(positions, vec![0, 1, 2]);
        }
    }

    #[test]
    fn hash_derived_render_order_visits_all_384_choices_once() {
        for ordinal in [0, 1, 17, 18_624, u64::MAX] {
            let (start, step) = choice_permutation(ordinal);
            assert_eq!(gcd(step, 384), 1);
            let mut choices = (0..384)
                .map(|i| (start + i * step) % 384)
                .collect::<Vec<_>>();
            choices.sort_unstable();
            assert_eq!(choices, (0..384).collect::<Vec<_>>());
        }
    }

    #[test]
    fn support_requires_every_class_in_all_endpoints() {
        let mut support = Support::default();
        assert!(!support.meets_target());
        support.context_identity.fill(250);
        support.entity_identity.fill(250);
        support.relation.fill(250);
        support.observed_state.fill(250);
        for classes in &mut support.exact_target_by_stratum {
            classes.fill(250);
        }
        assert!(support.meets_target());
        support.exact_target_by_stratum[3][2] = 249;
        assert!(!support.meets_target());
    }
}

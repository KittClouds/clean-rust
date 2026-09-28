#![recursion_limit = "256"]

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
const TEMPLATE_SHA256: &str = "e3b8a70b90b06fc4185d2e379cbfc7cf3724238d9505590add1cf8bba2e9b068";
const PRIMARY_CHOICE_DOMAIN: &[u8] = b"FAS-E4-0-SEEN-CHOICE-v01\0";
const HELDOUT_CHOICE_DOMAIN: &[u8] = b"FAS-E4-0-HELDOUT-CHOICE-v01\0";
const QUARTET_ID_DOMAIN: &[u8] = b"FAS-E4-0-QUARTET-ID-v01\0";
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

#[derive(Deserialize)]
struct TemplateEntry {
    id: usize,
    text: String,
}

#[derive(Deserialize)]
struct TemplateManifest {
    observation_templates: Vec<TemplateEntry>,
    query_templates: Vec<TemplateEntry>,
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

#[allow(clippy::too_many_arguments)]
fn quartet_id_digest(
    seed: u64,
    candidate_counter: u64,
    ordinal: u64,
    track_code: u8,
    context_split: u8,
    entity_split: u8,
    family_id: u8,
    relation_id: u8,
    state_id: u8,
    observation_template_id: u8,
    query_template_id: u8,
    context_pair_id: u8,
    entity_pair_id: u8,
    candidate_order_id: u8,
) -> [u8; 32] {
    let mut digest = Sha256::new();
    digest.update(QUARTET_ID_DOMAIN);
    digest.update(NAMESPACE.as_bytes());
    digest.update([0]);
    digest.update(seed.to_le_bytes());
    digest.update(candidate_counter.to_le_bytes());
    digest.update(ordinal.to_le_bytes());
    digest.update([
        track_code,
        context_split,
        entity_split,
        family_id,
        relation_id,
        state_id,
        observation_template_id,
        query_template_id,
        context_pair_id,
        entity_pair_id,
        candidate_order_id,
    ]);
    digest.finalize().into()
}

fn row_id(quartet_digest: &[u8; 32], surface_code: u8, variant_code: u8) -> String {
    format!(
        "{}:{surface_code:02x}:{variant_code:02x}",
        hex(quartet_digest)
    )
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
    observations: &[String],
    queries: &[String],
    context: &str,
    entity: &str,
    relation: &str,
    state: &str,
    obs_id: usize,
    query_id: usize,
    order_id: usize,
) -> String {
    let observation = render(&observations[obs_id], context, entity, relation, state);
    let query = render(&queries[query_id], context, entity, relation, "");
    let options = ORDERS[order_id]
        .iter()
        .map(|candidate| STATES[*candidate])
        .collect::<Vec<_>>()
        .join(", ");
    format!("{observation}\n{query}\nOptions: {options}")
}

fn choice_permutation(domain: &[u8], ordinal: u64) -> (usize, usize) {
    let mut digest = Sha256::new();
    digest.update(domain);
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
    observations: &[String],
    queries: &[String],
    domain: &[u8],
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
    let (start, step) = choice_permutation(domain, ordinal);
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
                    observations,
                    queries,
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

fn load_template_manifest(path: &Path) -> Result<(Vec<String>, Vec<String>), String> {
    let bytes = std::fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    if hex(&sha256(&bytes)) != TEMPLATE_SHA256 {
        return Err("held-out template manifest differs from the reviewed v02 identity".into());
    }
    let manifest: TemplateManifest = serde_json::from_slice(&bytes)
        .map_err(|e| format!("decode held-out template manifest: {e}"))?;
    let ordered = |entries: Vec<TemplateEntry>| -> Result<Vec<String>, String> {
        if entries.len() != 8 || entries.iter().enumerate().any(|(id, entry)| id != entry.id) {
            return Err("template manifest must contain ordered IDs 0 through 7".into());
        }
        Ok(entries.into_iter().map(|entry| entry.text).collect())
    };
    Ok((
        ordered(manifest.observation_templates)?,
        ordered(manifest.query_templates)?,
    ))
}

fn e1_root() -> PathBuf {
    PathBuf::from(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04")
}

fn main() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let root = args.next().map(PathBuf::from).unwrap_or_else(e1_root);
    let template_path = args.next().map(PathBuf::from).unwrap_or_else(|| {
        PathBuf::from("experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-HELDOUT-TEMPLATES-v02.json")
    });
    let mut used = load_e1_input_hashes(&root.join("panel/panel-inputs-v01.jsonl"))?;
    let e1_unique_count = used.len();
    let terms = load_terms(&root.join("corpus/term-inventory-v01.json"))?;
    let (heldout_observations, heldout_queries) = load_template_manifest(&template_path)?;
    let primary_observations = OBSERVATIONS
        .iter()
        .map(|text| (*text).to_owned())
        .collect::<Vec<_>>();
    let primary_queries = QUERIES
        .iter()
        .map(|text| (*text).to_owned())
        .collect::<Vec<_>>();
    if terms.context_terms.len() != 32 || terms.entity_terms.len() != 32 {
        return Err("sealed E1 inventory must contain 32 IDs for each identity role".into());
    }
    let mut support = Support::default();
    let mut query_rows = [0_u64; 8];
    let mut observation_rows = [0_u64; 8];
    let mut heldout_query_rows = [0_u64; 8];
    let mut heldout_observation_rows = [0_u64; 8];
    let mut prefix = 0_u64;
    let mut primary_counter_sum = 0_u64;
    let mut heldout_counter_sum = 0_u64;
    let mut maximum_counter = 0_u64;
    let mut joint_rows = 0_u64;
    let mut first_primary_row_id = String::new();
    let mut first_heldout_row_id = String::new();
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
                                    &primary_observations,
                                    &primary_queries,
                                    PRIMARY_CHOICE_DOMAIN,
                                    prefix,
                                    &terms.context_terms[(cs + context_pair) as usize],
                                    &terms.context_terms[(cs + (context_pair + 7) % 16) as usize],
                                    &terms.entity_terms[(es + entity_pair) as usize],
                                    &terms.entity_terms[(es + (entity_pair + 7) % 16) as usize],
                                    RELATIONS[relation as usize],
                                    STATES[state as usize],
                                )?;
                                primary_counter_sum += counter;
                                maximum_counter = maximum_counter.max(counter);
                                query_rows[query] += 4;
                                observation_rows[obs] += 3;
                                observation_rows[(obs + 4) % 8] += 1;

                                let (heldout_obs, heldout_query, heldout_order, heldout_counter) =
                                    choose_rendering(
                                        &mut used,
                                        &heldout_observations,
                                        &heldout_queries,
                                        HELDOUT_CHOICE_DOMAIN,
                                        prefix,
                                        &terms.context_terms[(cs + context_pair) as usize],
                                        &terms.context_terms
                                            [(cs + (context_pair + 7) % 16) as usize],
                                        &terms.entity_terms[(es + entity_pair) as usize],
                                        &terms.entity_terms[(es + (entity_pair + 7) % 16) as usize],
                                        RELATIONS[relation as usize],
                                        STATES[state as usize],
                                    )?;
                                if prefix == 0 {
                                    let primary_digest = quartet_id_digest(
                                        SEED,
                                        counter,
                                        prefix,
                                        0,
                                        context_split,
                                        entity_split,
                                        family,
                                        relation,
                                        state,
                                        obs as u8,
                                        query as u8,
                                        context_pair,
                                        entity_pair,
                                        order as u8,
                                    );
                                    let heldout_digest = quartet_id_digest(
                                        SEED,
                                        heldout_counter,
                                        prefix,
                                        0,
                                        context_split,
                                        entity_split,
                                        family,
                                        relation,
                                        state,
                                        heldout_obs as u8,
                                        heldout_query as u8,
                                        context_pair,
                                        entity_pair,
                                        heldout_order as u8,
                                    );
                                    first_primary_row_id = row_id(&primary_digest, 0, 0);
                                    first_heldout_row_id = row_id(&heldout_digest, 1, 0);
                                }
                                heldout_counter_sum += heldout_counter;
                                maximum_counter = maximum_counter.max(heldout_counter);
                                heldout_query_rows[heldout_query] += 4;
                                heldout_observation_rows[heldout_obs] += 3;
                                heldout_observation_rows[(heldout_obs + 4) % 8] += 1;
                                if context_split != 0 || entity_split != 0 {
                                    joint_rows += 4;
                                }
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
    let heldout_rows = rows;
    let all_unique_feature_rows = rows + heldout_rows;
    let all_strata_bytes = all_unique_feature_rows * 8_192;
    let receipt = serde_json::json!({
        "receipt_id": "FAS_E4_0_SYMBOLIC_SUPPORT_PLAN_V03",
        "status": "MODEL_FREE_TWO_SURFACE_COLLISION_AWARE_SYMBOLIC_PLAN_ONLY",
        "population_rows_written": false,
        "tokenizer_contacted": false,
        "model_contacted": false,
        "labels_opened": false,
        "e1_input_rows": 106_496,
        "e1_unique_rendered_input_hashes": e1_unique_count,
        "e1_input_sha256": INPUTS_SHA256,
        "e1_term_inventory_sha256": TERMS_SHA256,
        "heldout_template_manifest_sha256": TEMPLATE_SHA256,
        "population_namespace": NAMESPACE,
        "world_render_seed_u64": SEED,
        "planner_source_path": "experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-support-plan-v03/src/main.rs",
        "planner_source_sha256": hex(&sha256(include_bytes!("main.rs"))),
        "quartet_id_serialization": "SHA256(UTF8(FAS-E4-0-QUARTET-ID-v01) || 0x00 || ASCII namespace || 0x00 || u64le(seed) || u64le(candidate_counter) || u64le(schedule_ordinal) || 11 ordered u8 fields: track, context_split, entity_split, family, relation, state, observation_template_id, query_template_id, context_pair_id, entity_pair_id, candidate_order_id). Lowercase 64-character hex.",
        "row_id_serialization": "lowercase quartet digest hex || ASCII ':' || two lowercase hex digits for surface code (00 seen, 01 held-out) || ASCII ':' || two lowercase hex digits for variant code (00 A, 01 C, 02 E, 03 P). Joint-template-plus-lexical is a truth stratum on the held-out row and does not create a duplicate row ID.",
        "rendered_input_sha256_serialization": "SHA256 of exact UTF-8 bytes of input_text only; no Unicode normalization, JSON encoding, or line terminator is included.",
        "candidate_counter_serialization": "u64 little-endian; per semantic schedule item and per surface, starts at zero and records the index in the complete 384-element coprime-step permutation.",
        "construction_target_rows_per_class": TARGET,
        "collision_rule": "For each schedule ordinal, derive a SHA-256 start and coprime step to enumerate all 384 query/observation/order combinations exactly once. Reject a whole quartet if any exact UTF-8 rendered-input SHA-256 is present in E1 or an earlier accepted E4 quartet. First collision-free combination wins; fail closed if all 384 are exhausted.",
        "selected_whole_quartet_prefix": prefix,
        "factorial_quartets_in_prefix": prefix,
        "binding_context_quartets_in_prefix": 0,
        "binding_entity_quartets_in_prefix": 0,
        "primary_candidate_counter_sum": primary_counter_sum,
        "heldout_candidate_counter_sum": heldout_counter_sum,
        "maximum_candidate_counter": maximum_counter,
        "sample_primary_A_row_id": first_primary_row_id,
        "sample_heldout_A_row_id": first_heldout_row_id,
        "rows_in_primary_seen_and_lexical_population": rows,
        "rows_in_heldout_template_population": heldout_rows,
        "heldout_template_joint_lexical_rows_subset": joint_rows,
        "joint_rows_additional_feature_rows": 0,
        "minimum_support_by_endpoint_and_stratum": support,
        "primary_query_template_rows": query_rows,
        "primary_observation_template_rows": observation_rows,
        "heldout_query_template_rows": heldout_query_rows,
        "heldout_observation_template_rows": heldout_observation_rows,
        "feature_bytes_primary_only": primary_bytes,
        "feature_bytes_heldout_template_rows": heldout_rows * 8_192,
        "unique_feature_rows_all_materialized_strata": all_unique_feature_rows,
        "feature_bytes_all_materialized_strata": all_strata_bytes,
        "feature_atomic_staging_bytes": all_strata_bytes,
        "two_feature_copies_peak_bytes": 2 * all_strata_bytes,
        "feature_bytes_per_row": 8_192,
        "resource_note": "The joint template-plus-lexical stratum is a label stratum over the held-out-template rows, not a third duplicate feature surface. The exact unique feature count is therefore primary rows plus held-out-template rows.",
    });
    println!("{}", serde_json::to_string_pretty(&receipt).unwrap());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{ORDERS, PRIMARY_CHOICE_DOMAIN, Support, choice_permutation, gcd};

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
            let (start, step) = choice_permutation(PRIMARY_CHOICE_DOMAIN, ordinal);
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

    #[test]
    fn row_ids_include_render_surface_and_variant() {
        let digest = [0xabu8; 32];
        assert_ne!(row_id(&digest, 0, 0), row_id(&digest, 1, 0));
        assert_ne!(row_id(&digest, 0, 0), row_id(&digest, 0, 1));
        assert_eq!(row_id(&digest, 0, 0).len(), 70);
    }
}

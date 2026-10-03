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
const ROW_MANIFEST_SHA256: &str =
    "ebfdf0064430ecae7a9ae2edd139f47c0c61291aa6c30c8ccb97daa195f835bc";
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
struct E1RowIdentity {
    quartet_id: String,
    row_id: String,
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

#[derive(Clone, Copy)]
struct SemanticQuartet {
    ordinal: u64,
    context_split: u8,
    entity_split: u8,
    family_id: u8,
    relation_id: u8,
    state_id: u8,
    context_pair_id: u8,
    entity_pair_id: u8,
}

struct CollisionIndex {
    input_hashes: HashSet<[u8; 32]>,
    quartet_ids: HashSet<String>,
    row_ids: HashSet<String>,
}

struct SurfaceTemplates<'a> {
    observations: &'a [String],
    queries: &'a [String],
}

struct SurfacePair<'a> {
    primary: SurfaceTemplates<'a>,
    heldout: SurfaceTemplates<'a>,
}

struct RenderWorld<'a> {
    context_base: &'a str,
    context_partner: &'a str,
    entity_base: &'a str,
    entity_partner: &'a str,
    relation: &'a str,
    state: &'a str,
}

#[derive(Clone, Copy)]
struct RenderChoice {
    observation: usize,
    query: usize,
    candidate_order: usize,
}

struct RenderChoicePair {
    primary: [usize; 3],
    heldout: [usize; 3],
    candidate_counter: u64,
}

#[derive(Clone, Default, Serialize)]
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

    fn minimum_class_count(&self) -> u64 {
        self.context_identity
            .iter()
            .chain(self.entity_identity.iter())
            .chain(self.relation.iter())
            .chain(self.observed_state.iter())
            .chain(self.exact_target_by_stratum.iter().flatten())
            .copied()
            .min()
            .unwrap_or(0)
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
    context_pair_id: u8,
    entity_pair_id: u8,
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
        context_pair_id,
        entity_pair_id,
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

fn load_e1_row_identities(path: &Path) -> Result<(HashSet<String>, HashSet<String>), String> {
    let (digest, map) = mapped_sha256(path)?;
    if hex(&digest) != ROW_MANIFEST_SHA256 {
        return Err("E1 row manifest SHA-256 differs from the sealed E1 v04 identity".into());
    }
    let mut quartets = HashSet::with_capacity(30_000);
    let mut rows = HashSet::with_capacity(110_000);
    let mut start = 0;
    for newline in memchr_iter(b'\n', &map) {
        let mut line = &map[start..newline];
        if line.last() == Some(&b'\r') {
            line = &line[..line.len() - 1];
        }
        let row: E1RowIdentity = serde_json::from_slice(line)
            .map_err(|e| format!("decode sealed E1 row identity at byte {start}: {e}"))?;
        quartets.insert(row.quartet_id);
        rows.insert(row.row_id);
        start = newline + 1;
    }
    if start < map.len() {
        let row: E1RowIdentity = serde_json::from_slice(&map[start..])
            .map_err(|e| format!("decode final sealed E1 row identity: {e}"))?;
        quartets.insert(row.quartet_id);
        rows.insert(row.row_id);
    }
    Ok((quartets, rows))
}

fn identifiers_are_available(
    quartet_id: &str,
    candidate_row_ids: &[String; 8],
    used_quartets: &HashSet<String>,
    used_rows: &HashSet<String>,
) -> bool {
    !used_quartets.contains(quartet_id)
        && candidate_row_ids.iter().enumerate().all(|(left, row)| {
            !used_rows.contains(row)
                && candidate_row_ids[left + 1..]
                    .iter()
                    .all(|other| row != other)
        })
}

fn render(template: &str, context: &str, entity: &str, relation: &str, state: &str) -> String {
    template
        .replace("{context}", context)
        .replace("{entity}", entity)
        .replace("{relation}", relation)
        .replace("{state}", state)
}

fn render_input(
    surface: &SurfaceTemplates<'_>,
    world: &RenderWorld<'_>,
    choice: RenderChoice,
) -> String {
    let observation = render(
        &surface.observations[choice.observation],
        world.context_base,
        world.entity_base,
        world.relation,
        world.state,
    );
    let query = render(
        &surface.queries[choice.query],
        world.context_base,
        world.entity_base,
        world.relation,
        "",
    );
    let options = ORDERS[choice.candidate_order]
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

fn choice_at(domain: &[u8], ordinal: u64, candidate_counter: usize) -> usize {
    let (start, step) = choice_permutation(domain, ordinal);
    (start + candidate_counter * step) % (8 * 8 * 6)
}

fn render_hashes(
    surface: &SurfaceTemplates<'_>,
    choice: usize,
    world: &RenderWorld<'_>,
) -> ([[u8; 32]; 4], [usize; 3]) {
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
        (world.context_base, world.entity_base),
        (world.context_partner, world.entity_base),
        (world.context_base, world.entity_partner),
        (world.context_base, world.entity_base),
    ];
    let hashes = std::array::from_fn(|i| {
        let variant_world = RenderWorld {
            context_base: pairs[i].0,
            context_partner: pairs[i].0,
            entity_base: pairs[i].1,
            entity_partner: pairs[i].1,
            relation: world.relation,
            state: world.state,
        };
        let render_choice = RenderChoice {
            observation: observation_ids[i],
            query: query_id,
            candidate_order: order_id,
        };
        sha256(render_input(surface, &variant_world, render_choice).as_bytes())
    });
    (hashes, [observation_id, query_id, order_id])
}

fn choose_rendering_pair(
    used: &mut CollisionIndex,
    surfaces: &SurfacePair<'_>,
    semantic: SemanticQuartet,
    world: &RenderWorld<'_>,
) -> Result<RenderChoicePair, String> {
    for candidate_counter in 0..(8 * 8 * 6) {
        let primary_choice = choice_at(PRIMARY_CHOICE_DOMAIN, semantic.ordinal, candidate_counter);
        let heldout_choice = choice_at(HELDOUT_CHOICE_DOMAIN, semantic.ordinal, candidate_counter);
        let (primary_hashes, primary_ids) = render_hashes(&surfaces.primary, primary_choice, world);
        let (heldout_hashes, heldout_ids) = render_hashes(&surfaces.heldout, heldout_choice, world);
        let all_hashes = [
            primary_hashes[0],
            primary_hashes[1],
            primary_hashes[2],
            primary_hashes[3],
            heldout_hashes[0],
            heldout_hashes[1],
            heldout_hashes[2],
            heldout_hashes[3],
        ];
        let all_unique =
            (0..8).all(|left| (left + 1..8).all(|right| all_hashes[left] != all_hashes[right]));
        if all_unique
            && all_hashes
                .iter()
                .all(|hash| !used.input_hashes.contains(hash))
        {
            let digest = quartet_id_digest(
                SEED,
                candidate_counter as u64,
                semantic.ordinal,
                0,
                semantic.context_split,
                semantic.entity_split,
                semantic.family_id,
                semantic.relation_id,
                semantic.state_id,
                semantic.context_pair_id,
                semantic.entity_pair_id,
            );
            let quartet = hex(&digest);
            let candidate_rows = std::array::from_fn(|index| {
                let surface = if index < 4 { 0 } else { 1 };
                let variant = (index % 4) as u8;
                row_id(&digest, surface, variant)
            });
            if identifiers_are_available(
                &quartet,
                &candidate_rows,
                &used.quartet_ids,
                &used.row_ids,
            ) {
                used.input_hashes.extend(all_hashes);
                used.quartet_ids.insert(quartet);
                used.row_ids.extend(candidate_rows);
                return Ok(RenderChoicePair {
                    primary: primary_ids,
                    heldout: heldout_ids,
                    candidate_counter: candidate_counter as u64,
                });
            }
        }
    }
    Err(format!(
        "all 384 paired render choices collide for schedule ordinal {}",
        semantic.ordinal
    ))
}

fn target_position(order: usize, state: usize) -> usize {
    ORDERS[order]
        .iter()
        .position(|candidate| *candidate == state)
        .unwrap()
}

fn add_quartet(support: &mut Support, semantic: SemanticQuartet, order: usize) {
    let context_start = semantic.context_split * 16;
    let entity_start = semantic.entity_split * 16;
    let context_base = context_start + semantic.context_pair_id;
    let context_partner = context_start + (semantic.context_pair_id + 7) % 16;
    let entity_base = entity_start + semantic.entity_pair_id;
    let entity_partner = entity_start + (semantic.entity_pair_id + 7) % 16;
    let target = target_position(order, semantic.state_id as usize);
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
            support.relation[semantic.relation_id as usize] += 1;
            support.observed_state[semantic.state_id as usize] += 1;
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
    let input_hashes = load_e1_input_hashes(&root.join("panel/panel-inputs-v01.jsonl"))?;
    let e1_unique_input_count = input_hashes.len();
    let (quartet_ids, row_ids) =
        load_e1_row_identities(&root.join("panel/row-manifest-v01.jsonl"))?;
    let e1_unique_quartet_count = quartet_ids.len();
    let e1_unique_row_count = row_ids.len();
    let mut collision_index = CollisionIndex {
        input_hashes,
        quartet_ids,
        row_ids,
    };
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
    let surfaces = SurfacePair {
        primary: SurfaceTemplates {
            observations: &primary_observations,
            queries: &primary_queries,
        },
        heldout: SurfaceTemplates {
            observations: &heldout_observations,
            queries: &heldout_queries,
        },
    };
    if terms.context_terms.len() != 32 || terms.entity_terms.len() != 32 {
        return Err("sealed E1 inventory must contain 32 IDs for each identity role".into());
    }
    let mut support = Support::default();
    let mut query_rows = [0_u64; 8];
    let mut observation_rows = [0_u64; 8];
    let mut heldout_query_rows = [0_u64; 8];
    let mut heldout_observation_rows = [0_u64; 8];
    let mut prefix = 0_u64;
    let mut candidate_counter_sum = 0_u64;
    let mut maximum_counter = 0_u64;
    let mut joint_rows = 0_u64;
    let mut first_primary_row_id = String::new();
    let mut first_heldout_row_id = String::new();
    let mut support_before_final_quartet = Support::default();
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
                                let semantic = SemanticQuartet {
                                    ordinal: prefix,
                                    context_split,
                                    entity_split,
                                    family_id: family,
                                    relation_id: relation,
                                    state_id: state,
                                    context_pair_id: context_pair,
                                    entity_pair_id: entity_pair,
                                };
                                let world = RenderWorld {
                                    context_base: &terms.context_terms
                                        [(cs + context_pair) as usize],
                                    context_partner: &terms.context_terms
                                        [(cs + (context_pair + 7) % 16) as usize],
                                    entity_base: &terms.entity_terms[(es + entity_pair) as usize],
                                    entity_partner: &terms.entity_terms
                                        [(es + (entity_pair + 7) % 16) as usize],
                                    relation: RELATIONS[relation as usize],
                                    state: STATES[state as usize],
                                };
                                let selected = choose_rendering_pair(
                                    &mut collision_index,
                                    &surfaces,
                                    semantic,
                                    &world,
                                )?;
                                let [obs, query, order] = selected.primary;
                                let [heldout_obs, heldout_query, _heldout_order] = selected.heldout;
                                let counter = selected.candidate_counter;
                                candidate_counter_sum += counter;
                                maximum_counter = maximum_counter.max(counter);
                                query_rows[query] += 4;
                                observation_rows[obs] += 3;
                                observation_rows[(obs + 4) % 8] += 1;

                                if prefix == 0 {
                                    let semantic_digest = quartet_id_digest(
                                        SEED,
                                        counter,
                                        prefix,
                                        0,
                                        context_split,
                                        entity_split,
                                        family,
                                        relation,
                                        state,
                                        context_pair,
                                        entity_pair,
                                    );
                                    first_primary_row_id = row_id(&semantic_digest, 0, 0);
                                    first_heldout_row_id = row_id(&semantic_digest, 1, 0);
                                }
                                heldout_query_rows[heldout_query] += 4;
                                heldout_observation_rows[heldout_obs] += 3;
                                heldout_observation_rows[(heldout_obs + 4) % 8] += 1;
                                if context_split != 0 || entity_split != 0 {
                                    joint_rows += 4;
                                }
                                support_before_final_quartet = support.clone();
                                add_quartet(&mut support, semantic, order);
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
        "receipt_id": "FAS_E4_0_SYMBOLIC_SUPPORT_PLAN_V11",
        "status": "MODEL_FREE_PAIRED_SURFACE_COLLISION_AWARE_SYMBOLIC_PLAN_ONLY",
        "population_rows_written": false,
        "tokenizer_contacted": false,
        "model_contacted": false,
        "labels_opened": false,
        "e1_input_rows": 106_496,
        "e1_unique_rendered_input_hashes": e1_unique_input_count,
        "e1_unique_quartet_ids": e1_unique_quartet_count,
        "e1_unique_row_ids": e1_unique_row_count,
        "e1_input_sha256": INPUTS_SHA256,
        "e1_row_manifest_sha256": ROW_MANIFEST_SHA256,
        "e1_term_inventory_sha256": TERMS_SHA256,
        "heldout_template_manifest_sha256": TEMPLATE_SHA256,
        "population_namespace": NAMESPACE,
        "world_render_seed_u64": SEED,
        "planner_source_path": "experiments/fas-frozen-observer-bundle-engineering-v01/source/e4-support-plan-v11/src/main.rs",
        "planner_source_sha256": hex(&sha256(include_bytes!("main.rs"))),
        "quartet_id_serialization": "SHA256(UTF8(FAS-E4-0-QUARTET-ID-v01) || 0x00 || ASCII namespace || 0x00 || u64le(seed) || u64le(shared_candidate_counter) || u64le(schedule_ordinal) || 8 ordered u8 semantic fields: track, context_split, entity_split, family, relation, state, context_pair_id, entity_pair_id). Lowercase 64-character hex; shared by seen and held-out renderings of the same semantic quartet.",
        "row_id_serialization": "lowercase quartet digest hex || ASCII ':' || two lowercase hex digits for surface code (00 seen, 01 held-out) || ASCII ':' || two lowercase hex digits for variant code (00 A, 01 C, 02 E, 03 P). Joint-template-plus-lexical is a truth stratum on the held-out row and does not create a duplicate row ID.",
        "rendered_input_sha256_serialization": "SHA256 of exact UTF-8 bytes of input_text only; no Unicode normalization, JSON encoding, or line terminator is included.",
        "candidate_counter_serialization": "u64 little-endian; one shared counter per semantic quartet, starts at zero, and indexes both complete 384-element surface-specific coprime-step permutations.",
        "render_choice_mapping": "For choice index j in 0..383: query_id=floor(j/48), observation_id=floor((j mod 48)/6), candidate_order_id=j mod 6. P observation ID is (observation_id+4) mod 8; A/C/E use observation_id. The same counter selects one index in each surface's independently domain-separated permutation.",
        "construction_target_rows_per_class": TARGET,
        "collision_rule": "For each schedule ordinal, derive separate SHA-256 start/coprime-step permutations for the seen and held-out surfaces. At each shared candidate counter, render all four rows on both surfaces. Reject the whole semantic quartet if its quartet ID, any of its eight row IDs, or any of its eight exact UTF-8 rendered-input SHA-256 values collides with E1 or an earlier accepted E4 item. First collision-free paired choice wins; fail closed if all 384 counters are exhausted.",
        "e1_quartet_ids_checked": true,
        "e1_row_ids_checked": true,
        "e4_paired_quartet_and_row_ids_checked": true,
        "selected_whole_quartet_prefix": prefix,
        "factorial_quartets_in_prefix": prefix,
        "binding_context_quartets_in_prefix": 0,
        "binding_entity_quartets_in_prefix": 0,
        "shared_candidate_counter_sum": candidate_counter_sum,
        "maximum_candidate_counter": maximum_counter,
        "sample_primary_A_row_id": first_primary_row_id,
        "sample_heldout_A_row_id": first_heldout_row_id,
        "rows_in_primary_seen_and_lexical_population": rows,
        "rows_in_heldout_template_population": heldout_rows,
        "heldout_template_joint_lexical_rows_subset": joint_rows,
        "joint_rows_additional_feature_rows": 0,
        "minimum_support_by_endpoint_and_stratum": support,
        "immediately_previous_whole_quartet_prefix_meets_target": support_before_final_quartet.meets_target(),
        "minimum_class_count_at_previous_prefix": support_before_final_quartet.minimum_class_count(),
        "previous_prefix_support": support_before_final_quartet,
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
    use super::{
        HELDOUT_CHOICE_DOMAIN, ORDERS, PRIMARY_CHOICE_DOMAIN, Support, choice_permutation, gcd,
        hex, identifiers_are_available, row_id,
    };
    use hashbrown::HashSet;

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
        for domain in [PRIMARY_CHOICE_DOMAIN, HELDOUT_CHOICE_DOMAIN] {
            for ordinal in [0, 1, 17, 18_624, u64::MAX] {
                let (start, step) = choice_permutation(domain, ordinal);
                assert_eq!(gcd(step, 384), 1);
                let mut choices = (0..384)
                    .map(|i| (start + i * step) % 384)
                    .collect::<Vec<_>>();
                choices.sort_unstable();
                assert_eq!(choices, (0..384).collect::<Vec<_>>());
            }
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

    #[test]
    fn e1_quartet_and_row_collisions_are_checked_independently_of_input_hashes() {
        let digest = [0xabu8; 32];
        let quartet = hex(&digest);
        let rows =
            std::array::from_fn(|index| row_id(&digest, (index / 4) as u8, (index % 4) as u8));
        let mut used_quartets = HashSet::new();
        let mut used_rows = HashSet::new();
        assert!(identifiers_are_available(
            &quartet,
            &rows,
            &used_quartets,
            &used_rows
        ));
        used_quartets.insert(quartet.clone());
        assert!(!identifiers_are_available(
            &quartet,
            &rows,
            &used_quartets,
            &used_rows
        ));
        used_quartets.clear();
        used_rows.insert(rows[6].clone());
        assert!(!identifiers_are_available(
            &quartet,
            &rows,
            &used_quartets,
            &used_rows
        ));
    }
}

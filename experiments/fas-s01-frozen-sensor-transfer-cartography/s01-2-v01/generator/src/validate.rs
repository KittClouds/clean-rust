use std::collections::BTreeMap;
use std::error::Error;
use std::fs::File;
use std::io::Write;
use std::path::Path;

use hashbrown::{HashMap, HashSet};
use memchr::memchr_iter;
use memmap2::MmapOptions;
use serde::Serialize;
use serde_json::Value;

use crate::generate::{
    Counts, EXPECTED_BINDING_CONTEXT_QUARTETS, EXPECTED_BINDING_ENTITY_QUARTETS,
    EXPECTED_FACTORIAL_QUARTETS, EXPECTED_QUARTETS, GENERATOR_SEED, sha256_hex,
    write_repeat_digest,
};
use crate::model::{CharacterSpans, Quartet, Span, TermInventory, Variant};

#[derive(Serialize)]
struct ValidationReport {
    validation_id: &'static str,
    status: &'static str,
    world_contract_sha256: String,
    corpus_sha256: String,
    deterministic_repeat_sha256: String,
    counts: CountsReport,
    gate_results: BTreeMap<&'static str, &'static str>,
    factorial_geometry_cells: usize,
    binding_context_cells: usize,
    binding_entity_cells: usize,
    minimum_support_per_cell: usize,
    model_loaded: bool,
    tokenizer_loaded: bool,
    feature_extraction_performed: bool,
}

#[derive(Serialize)]
struct CountsReport {
    factorial_quartets: usize,
    binding_context_quartets: usize,
    binding_entity_quartets: usize,
    total_quartets: usize,
    rendered_inputs: usize,
    observed_context_terms: usize,
    observed_entity_terms: usize,
    observation_templates: usize,
    query_templates: usize,
}

#[derive(Serialize)]
struct ValidationFingerprint<'a> {
    event_id: &'a str,
    variant_id: &'a str,
    context_term_id: u8,
    entity_term_id: u8,
    observation_template_id: u8,
    query_template_id: u8,
    observation_text: &'a str,
    query_text: &'a str,
    input_text: &'a str,
    candidate_identity_order: &'a [u8],
    character_spans: &'a CharacterSpans,
}

type FactorialCellKey = (u8, u8, u8, u8, u8, u8, u8);

pub fn validate_run(output_root: &Path, contract_path: &Path) -> Result<(), Box<dyn Error>> {
    let corpus_path = output_root.join("corpus/counterfactual-quartets-v01.jsonl");
    let inventory_path = output_root.join("corpus/term-inventory-v01.json");
    let manifest_path = output_root.join("corpus/corpus-manifest-v01.json");
    let corpus_file = File::open(&corpus_path)?;
    // The corpus is a dense immutable byte stream; mmap avoids a second full-size copy.
    let corpus_map = unsafe { MmapOptions::new().map(&corpus_file)? };
    let manifest: Value = serde_json::from_slice(&std::fs::read(&manifest_path)?)?;
    let contract_bytes = std::fs::read(contract_path)?;
    let contract: Value = serde_json::from_slice(&contract_bytes)?;
    let contract_sha = sha256_hex(&contract_bytes);
    if corpus_map.is_empty() || corpus_map.last() != Some(&b'\n') {
        return Err("corpus is empty or lacks its final LF record terminator".into());
    }
    if manifest["manifest_id"].as_str() != Some("FASS01_S01_2_CORPUS_MANIFEST_V01")
        || manifest["project_id"].as_str() != Some("fas-s01-frozen-sensor-transfer-cartography")
        || manifest["phase_id"].as_str() != Some("S01-2-v01")
        || manifest["corpus_bytes"].as_u64() != Some(corpus_map.len() as u64)
    {
        return Err("corpus manifest identity or byte count mismatch".into());
    }
    let corpus_sha = sha256_hex(&corpus_map);
    if manifest["world_contract_sha256"].as_str() != Some(contract_sha.as_str()) {
        return Err("world contract hash differs from corpus manifest".into());
    }
    if manifest["corpus_sha256"].as_str() != Some(corpus_sha.as_str()) {
        return Err("corpus byte hash differs from corpus manifest".into());
    }
    if manifest["generator_seed"].as_u64() != Some(GENERATOR_SEED) {
        return Err("generator seed differs from frozen construction contract".into());
    }
    let inventory_bytes = std::fs::read(&inventory_path)?;
    let inventory: TermInventory = serde_json::from_slice(&inventory_bytes)?;
    if manifest["term_inventory_sha256"].as_str() != Some(sha256_hex(&inventory_bytes).as_str()) {
        return Err("term inventory hash differs from corpus manifest".into());
    }
    validate_inventory_independently(&inventory, &contract)?;

    let mut quartet_ids: HashSet<String> = HashSet::with_capacity(EXPECTED_QUARTETS);
    let mut event_ids: HashSet<String> = HashSet::with_capacity(EXPECTED_QUARTETS * 4);
    let mut context_terms: HashSet<u8> = HashSet::with_capacity(32);
    let mut entity_terms: HashSet<u8> = HashSet::with_capacity(32);
    let mut observation_templates: HashSet<u8> = HashSet::with_capacity(8);
    let mut query_templates: HashSet<u8> = HashSet::with_capacity(8);
    let mut factorial_cells: HashMap<FactorialCellKey, u8> = HashMap::new();
    let mut binding_context_cells: HashMap<(u8, u8, u8), u8> = HashMap::new();
    let mut binding_entity_cells: HashMap<(u8, u8, u8), u8> = HashMap::new();
    let mut track_counts = Counts::default();
    let mut byte_start = 0_usize;

    for byte_end in memchr_iter(b'\n', &corpus_map) {
        let line = &corpus_map[byte_start..byte_end];
        byte_start = byte_end + 1;
        if line.is_empty() {
            return Err("empty corpus record".into());
        }
        let quartet: Quartet = serde_json::from_slice(line)?;
        validate_quartet(&quartet, &inventory, &contract, &mut event_ids)?;
        if !quartet_ids.insert(quartet.quartet_id.clone()) {
            return Err(format!("duplicate quartet id {}", quartet.quartet_id).into());
        }
        for variant in &quartet.variants {
            context_terms.insert(variant.context_term_id);
            entity_terms.insert(variant.entity_term_id);
        }
        observation_templates.insert(quartet.observation_template_id);
        query_templates.insert(quartet.query_template_id);
        track_counts.total += 1;
        match quartet.track_id.as_str() {
            "FACTORIAL_BALANCED" => {
                track_counts.factorial += 1;
                let key = (
                    split_index(&quartet.context_term_split)?,
                    split_index(&quartet.entity_term_split)?,
                    quartet.world_family_id,
                    quartet.relation_id,
                    quartet.state_id,
                    quartet.observation_template_id,
                    quartet.query_template_id,
                );
                *factorial_cells.entry(key).or_default() += 1;
            }
            "BINDING_CONTEXT" => {
                track_counts.binding_context += 1;
                let key = (
                    split_index(&quartet.context_term_split)?,
                    quartet.context_pair_id,
                    split_index(&quartet.entity_term_split)?,
                );
                *binding_context_cells.entry(key).or_default() += 1;
            }
            "BINDING_ENTITY" => {
                track_counts.binding_entity += 1;
                let key = (
                    split_index(&quartet.entity_term_split)?,
                    quartet.entity_pair_id,
                    split_index(&quartet.context_term_split)?,
                );
                *binding_entity_cells.entry(key).or_default() += 1;
            }
            unknown => return Err(format!("unknown corpus track {unknown}").into()),
        }
    }
    if byte_start != corpus_map.len() {
        return Err("corpus has bytes after the final newline".into());
    }
    if track_counts.factorial != EXPECTED_FACTORIAL_QUARTETS
        || track_counts.binding_context != EXPECTED_BINDING_CONTEXT_QUARTETS
        || track_counts.binding_entity != EXPECTED_BINDING_ENTITY_QUARTETS
        || track_counts.total != EXPECTED_QUARTETS
        || quartet_ids.len() != EXPECTED_QUARTETS
        || event_ids.len() != EXPECTED_QUARTETS * 4
    {
        return Err("quartet or event count differs from the sealed design".into());
    }
    if manifest["quartet_count"].as_u64() != Some(track_counts.total as u64)
        || manifest["rendered_input_count"].as_u64() != Some((track_counts.total * 4) as u64)
        || manifest["model_loaded"].as_bool() != Some(false)
        || manifest["tokenizer_loaded"].as_bool() != Some(false)
        || manifest["feature_extraction_performed"].as_bool() != Some(false)
    {
        return Err("corpus manifest counts or no-contact declaration mismatch".into());
    }
    if factorial_cells.len() != 1_536 || factorial_cells.values().any(|count| *count != 16) {
        return Err("factorial geometry cell support is not exactly 16".into());
    }
    if binding_context_cells.len() != 64 || binding_context_cells.values().any(|count| *count != 16)
    {
        return Err("context-binding cell support is not exactly 16".into());
    }
    if binding_entity_cells.len() != 64 || binding_entity_cells.values().any(|count| *count != 16) {
        return Err("entity-binding cell support is not exactly 16".into());
    }
    if context_terms.len() != 32
        || entity_terms.len() != 32
        || observation_templates.len() != 8
        || query_templates.len() != 8
    {
        return Err("term or template coverage differs from the frozen inventory".into());
    }

    let (_, repeat_sha) = write_repeat_digest()?;
    if repeat_sha != corpus_sha
        || manifest["deterministic_regeneration_sha256"].as_str() != Some(repeat_sha.as_str())
    {
        return Err(
            "independent deterministic regeneration hash differs from materialized corpus".into(),
        );
    }
    let gate_results = BTreeMap::from([
        ("CORPUS_COUNTS_EXACT", "PASS"),
        ("TARGETS_RECONSTRUCT_EXACTLY", "PASS"),
        ("QUARTET_FACTOR_ISOLATION", "PASS"),
        ("CANONICAL_WORLD_INVARIANCE", "PASS"),
        ("CANDIDATE_AUTHORITY_AND_ORDER", "PASS"),
        ("CHARACTER_SPANS_EXACT", "PASS"),
        ("TERM_AND_TEMPLATE_COVERAGE", "PASS"),
        ("GEOMETRY_CELL_SUPPORT", "PASS"),
        ("SEED_DETERMINISM", "PASS"),
        ("NO_MODEL_OR_TOKENIZER_CONTACT", "PASS"),
    ]);
    let report = ValidationReport {
        validation_id: "FASS01_S01_2_INDEPENDENT_WORLD_VALIDATION_V01",
        status: "COUNTERFACTUAL_CORPUS_VALID",
        world_contract_sha256: contract_sha,
        corpus_sha256: corpus_sha,
        deterministic_repeat_sha256: repeat_sha,
        counts: CountsReport {
            factorial_quartets: track_counts.factorial,
            binding_context_quartets: track_counts.binding_context,
            binding_entity_quartets: track_counts.binding_entity,
            total_quartets: track_counts.total,
            rendered_inputs: track_counts.total * 4,
            observed_context_terms: context_terms.len(),
            observed_entity_terms: entity_terms.len(),
            observation_templates: observation_templates.len(),
            query_templates: query_templates.len(),
        },
        gate_results,
        factorial_geometry_cells: factorial_cells.len(),
        binding_context_cells: binding_context_cells.len(),
        binding_entity_cells: binding_entity_cells.len(),
        minimum_support_per_cell: 16,
        model_loaded: false,
        tokenizer_loaded: false,
        feature_extraction_performed: false,
    };
    let validation_path = output_root.join("validation-report-v01.json");
    let mut validation_file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(validation_path)?;
    serde_json::to_writer_pretty(&mut validation_file, &report)?;
    validation_file.write_all(b"\n")?;
    Ok(())
}

fn validate_inventory_independently(
    inventory: &TermInventory,
    contract: &Value,
) -> Result<(), Box<dyn Error>> {
    let prefixes: Vec<&str> = contract["term_inventory"]["prefixes"]
        .as_array()
        .ok_or("missing nonce prefixes")?
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    let suffixes: Vec<&str> = contract["term_inventory"]["suffixes"]
        .as_array()
        .ok_or("missing nonce suffixes")?
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    let multiplier = contract["term_inventory"]["permutation_multiplier"]
        .as_u64()
        .ok_or("missing term permutation")? as usize;
    let offset = contract["term_inventory"]["permutation_offset"]
        .as_u64()
        .ok_or("missing term offset")? as usize;
    if prefixes.len() != 8 || suffixes.len() != 8 || multiplier != 17 || offset != 0 {
        return Err("term inventory contract dimensions or permutation mismatch".into());
    }
    let mut generated = Vec::with_capacity(64);
    for ordinal in 0..64 {
        let product_index = (multiplier * ordinal + offset) % 64;
        generated.push(format!(
            "{}{}",
            prefixes[product_index / 8],
            suffixes[product_index % 8]
        ));
    }
    if inventory.context_terms.as_slice() != &generated[..32]
        || inventory.entity_terms.as_slice() != &generated[32..]
    {
        return Err("serialized term inventory does not reconstruct from sealed arrays".into());
    }
    if inventory.generator_seed != GENERATOR_SEED
        || inventory.context_terms.len() != 32
        || inventory.entity_terms.len() != 32
    {
        return Err("serialized term inventory count or seed mismatch".into());
    }
    Ok(())
}

fn validate_quartet(
    quartet: &Quartet,
    inventory: &TermInventory,
    contract: &Value,
    event_ids: &mut HashSet<String>,
) -> Result<(), Box<dyn Error>> {
    if quartet.variants.len() != 4
        || quartet.generator_seed != GENERATOR_SEED
        || quartet.time_step != 0
        || quartet.feedback_marker != "NONE"
    {
        return Err(format!(
            "quartet {} violates fixed row cardinality or seed metadata",
            quartet.quartet_id
        )
        .into());
    }
    if quartet
        .variants
        .iter()
        .map(|variant| variant.variant_id.as_str())
        .collect::<Vec<_>>()
        != ["A", "C", "E", "P"]
    {
        return Err(format!(
            "quartet {} does not serialize A/C/E/P in order",
            quartet.quartet_id
        )
        .into());
    }
    let families: Vec<&str> = contract["world_families"]
        .as_array()
        .ok_or("missing world families")?
        .iter()
        .map(|value| value.as_str().ok_or("invalid world family"))
        .collect::<Result<_, _>>()?;
    let relation = contract["relations"]
        .as_array()
        .ok_or("missing relations")?
        .get(quartet.relation_id as usize)
        .and_then(|value| value["surface"].as_str())
        .ok_or("invalid relation identity")?;
    let state = contract["states_and_targets"]
        .as_array()
        .ok_or("missing states")?
        .get(quartet.state_id as usize)
        .and_then(|value| value["state_surface"].as_str())
        .ok_or("invalid state identity")?;
    if families.get(quartet.world_family_id as usize).copied()
        != Some(quartet.world_family.as_str())
        || quartet.relation_surface != relation
        || quartet.state_surface != state
        || quartet.latent_world.world_family != quartet.world_family
        || quartet.latent_world.world_family_id != quartet.world_family_id
        || quartet.latent_world.time_step != quartet.time_step
        || quartet.latent_world.feedback_marker != quartet.feedback_marker
        || quartet.latent_world.facts.len() != 1
    {
        return Err(format!(
            "quartet {} top-level and serialized world metadata disagree",
            quartet.quartet_id
        )
        .into());
    }
    let fact = &quartet.latent_world.facts[0];
    let current = &quartet.latent_world.current_exact_world_state;
    if current.canonical_context_id != fact.canonical_context_id
        || current.canonical_entity_id != fact.canonical_entity_id
        || current.relation_id != fact.relation_id
        || current.state_id != fact.state_id
        || current.relation_id != quartet.relation_id
        || current.state_id != quartet.state_id
        || current.target_candidate_identity != quartet.target_candidate_identity
        || fact.state_id >= 3
        || quartet.target_candidate_identity != fact.state_id
    {
        return Err(format!(
            "quartet {} exact world state does not reconstruct from its fact",
            quartet.quartet_id
        )
        .into());
    }
    if quartet.candidate_identity_order.len() != 3 || {
        let mut sorted = quartet.candidate_identity_order.clone();
        sorted.sort_unstable();
        sorted != [0, 1, 2]
    } {
        return Err(format!(
            "quartet {} candidate identity order is not a permutation",
            quartet.quartet_id
        )
        .into());
    }
    let candidate_semantics = &quartet.latent_world.candidate_semantics;
    if candidate_semantics.len() != 3 || candidate_semantics.iter().any(|candidate| {
        candidate.candidate_identity != candidate.state_id || candidate.state_id >= 3 ||
            contract["states_and_targets"].as_array().unwrap()[candidate.state_id as usize]["state_surface"].as_str() != Some(candidate.surface.as_str())
    }) {
        return Err(format!("quartet {} candidate authority differs from the sealed state inventory", quartet.quartet_id).into());
    }
    let (context_split, entity_split) = (
        split_index(&quartet.context_term_split)?,
        split_index(&quartet.entity_term_split)?,
    );
    let context_base = context_split * 16;
    let entity_base = entity_split * 16;
    let context_source_id = context_base + quartet.context_pair_id;
    let context_partner_id = context_base + (quartet.context_pair_id + 7) % 16;
    let entity_source_id = entity_base + quartet.entity_pair_id;
    let entity_partner_id = entity_base + (quartet.entity_pair_id + 7) % 16;
    let expected_ids = [
        (context_source_id, entity_source_id),
        (context_partner_id, entity_source_id),
        (context_source_id, entity_partner_id),
        (context_source_id, entity_source_id),
    ];
    let expected_changes = ["NONE", "CONTEXT", "ENTITY", "OBSERVATION_TEMPLATE"];
    let expected_observation_ids = [
        quartet.observation_template_id,
        quartet.observation_template_id,
        quartet.observation_template_id,
        (quartet.observation_template_id + 4) % 8,
    ];
    for (index, variant) in quartet.variants.iter().enumerate() {
        let (context_id, entity_id) = expected_ids[index];
        if variant.context_term_id != context_id
            || variant.entity_term_id != entity_id
            || variant.context_term != inventory.context_terms[context_id as usize]
            || variant.entity_term != inventory.entity_terms[entity_id as usize]
            || variant.changed_factor != expected_changes[index]
            || variant.context_term_split != quartet.context_term_split
            || variant.entity_term_split != quartet.entity_term_split
        {
            return Err(format!(
                "quartet {} has a factor-isolation or term identity error",
                quartet.quartet_id
            )
            .into());
        }
        if variant.observation_template_id != expected_observation_ids[index]
            || variant.query_template_id != quartet.query_template_id
            || variant.observation_template_role
                != if expected_observation_ids[index] < 6 {
                    "TRAIN_SIDE_STYLE"
                } else {
                    "HELDOUT"
                }
            || variant.query_template_role
                != if quartet.query_template_id < 6 {
                    "TRAIN_SIDE_STYLE"
                } else {
                    "HELDOUT"
                }
            || variant.query_semantics.canonical_context_id != current.canonical_context_id
            || variant.query_semantics.canonical_entity_id != current.canonical_entity_id
            || variant.query_semantics.relation_id != quartet.relation_id
        {
            return Err(format!(
                "quartet {} variant changes an undeclared semantic or template factor",
                quartet.quartet_id
            )
            .into());
        }
        if !event_ids.insert(variant.event_id.clone())
            || variant.event_id != format!("{}:{}", quartet.quartet_id, variant.variant_id)
        {
            return Err(
                format!("duplicate or malformed event identity {}", variant.event_id).into(),
            );
        }
        reconstruct_target(quartet, variant)?;
        validate_render_and_spans(quartet, variant, contract)?;
        if variant.target_candidate_identity != quartet.target_candidate_identity
            || variant.exact_target != quartet.exact_target
            || variant.candidate_identity_order != quartet.candidate_identity_order
        {
            return Err(format!(
                "quartet {} changes target or candidate ordering",
                quartet.quartet_id
            )
            .into());
        }
    }
    validate_track_schedule(quartet)?;
    let latent_bytes = serde_json::to_vec(&quartet.latent_world)?;
    if sha256_hex(&latent_bytes) != quartet.latent_world_sha256 {
        return Err(format!("quartet {} latent-world hash mismatch", quartet.quartet_id).into());
    }
    Ok(())
}

fn reconstruct_target(quartet: &Quartet, variant: &Variant) -> Result<(), Box<dyn Error>> {
    let query = &variant.query_semantics;
    let matches: Vec<_> = quartet
        .latent_world
        .facts
        .iter()
        .filter(|fact| {
            fact.canonical_context_id == query.canonical_context_id
                && fact.canonical_entity_id == query.canonical_entity_id
                && fact.relation_id == query.relation_id
        })
        .collect();
    if matches.len() != 1 {
        return Err(format!(
            "quartet {} query resolves to {} latent facts",
            quartet.quartet_id,
            matches.len()
        )
        .into());
    }
    let state = matches[0].state_id;
    let candidate = quartet
        .latent_world
        .candidate_semantics
        .iter()
        .find(|item| item.state_id == state)
        .ok_or("reconstructed state has no candidate authority")?
        .candidate_identity;
    let position = variant
        .candidate_identity_order
        .iter()
        .position(|identity| *identity == candidate)
        .ok_or("reconstructed answer candidate is absent from candidate order")?
        as u8;
    if candidate != quartet.target_candidate_identity
        || state != quartet.state_id
        || position != quartet.exact_target
    {
        return Err(format!(
            "quartet {} generator target disagrees with independent reconstruction",
            quartet.quartet_id
        )
        .into());
    }
    let expected_candidate_text: Vec<&str> = variant
        .candidate_identity_order
        .iter()
        .map(|identity| {
            quartet
                .latent_world
                .candidate_semantics
                .iter()
                .find(|item| item.candidate_identity == *identity)
                .map(|item| item.surface.as_str())
                .unwrap_or("")
        })
        .collect();
    if expected_candidate_text
        != variant
            .candidate_text_order
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>()
    {
        return Err(format!(
            "quartet {} candidate text does not match candidate authority",
            quartet.quartet_id
        )
        .into());
    }
    Ok(())
}

fn validate_render_and_spans(
    quartet: &Quartet,
    variant: &Variant,
    contract: &Value,
) -> Result<(), Box<dyn Error>> {
    let observation_templates: Vec<&str> = contract["templates"]["observation"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    let query_templates: Vec<&str> = contract["templates"]["query"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    let relation =
        contract["relations"].as_array().unwrap()[quartet.relation_id as usize]["surface"]
            .as_str()
            .unwrap();
    let state = contract["states_and_targets"].as_array().unwrap()[quartet.state_id as usize]["state_surface"].as_str().unwrap();
    let expected_observation = substitute(
        observation_templates[variant.observation_template_id as usize],
        &variant.context_term,
        &variant.entity_term,
        relation,
        Some(state),
    );
    let expected_query = substitute(
        query_templates[variant.query_template_id as usize],
        &variant.context_term,
        &variant.entity_term,
        relation,
        None,
    );
    if expected_observation != variant.observation_text || expected_query != variant.query_text {
        return Err(format!(
            "quartet {} text does not match its frozen template",
            quartet.quartet_id
        )
        .into());
    }
    let options = variant.candidate_text_order.join(", ");
    let expected_input = format!(
        "{}\n{}\nOptions: {}",
        expected_observation, expected_query, options
    );
    if expected_input != variant.input_text
        || !variant.input_text.is_ascii()
        || sha256_hex(variant.input_text.as_bytes()) != variant.input_sha256
    {
        return Err(format!(
            "quartet {} input bytes or hash mismatch",
            quartet.quartet_id
        )
        .into());
    }
    let expected_spans = scan_expected_spans(
        &variant.input_text,
        &variant.observation_text,
        &variant.context_term,
        &variant.entity_term,
        relation,
        state,
        &variant.candidate_text_order,
    );
    if expected_spans != variant.character_spans {
        return Err(format!(
            "quartet {} character-span identity mismatch",
            quartet.quartet_id
        )
        .into());
    }
    let fingerprint = ValidationFingerprint {
        event_id: &variant.event_id,
        variant_id: &variant.variant_id,
        context_term_id: variant.context_term_id,
        entity_term_id: variant.entity_term_id,
        observation_template_id: variant.observation_template_id,
        query_template_id: variant.query_template_id,
        observation_text: &variant.observation_text,
        query_text: &variant.query_text,
        input_text: &variant.input_text,
        candidate_identity_order: &variant.candidate_identity_order,
        character_spans: &variant.character_spans,
    };
    let fingerprint_bytes = serde_json::to_vec(&fingerprint)?;
    if sha256_hex(&fingerprint_bytes) != variant.rendered_event_sha256 {
        return Err(format!(
            "quartet {} rendered-event hash mismatch",
            quartet.quartet_id
        )
        .into());
    }
    if variant.query_semantics.canonical_context_id
        != quartet
            .latent_world
            .current_exact_world_state
            .canonical_context_id
        || variant.query_semantics.canonical_entity_id
            != quartet
                .latent_world
                .current_exact_world_state
                .canonical_entity_id
        || variant.query_semantics.relation_id != quartet.relation_id
    {
        return Err(format!("quartet {} query semantics drifted", quartet.quartet_id).into());
    }
    Ok(())
}

fn scan_expected_spans(
    input: &str,
    observation: &str,
    context: &str,
    entity: &str,
    relation: &str,
    state: &str,
    candidates: &[String],
) -> CharacterSpans {
    let query_start = observation.len() + 1;
    let option_start = observation.len()
        + 1
        + input[query_start..].find("\nOptions: ").unwrap()
        + "\nOptions: ".len();
    let mut spans = CharacterSpans {
        context: all_occurrences(input, context),
        entity: all_occurrences(input, entity),
        relation: all_occurrences(input, relation),
        state_in_observation: all_occurrences(observation, state),
        candidate_options: Vec::new(),
    };
    let mut cursor = option_start;
    for (index, candidate) in candidates.iter().enumerate() {
        if index > 0 {
            cursor += 2;
        }
        let end = cursor + candidate.len();
        spans.candidate_options.push(Span {
            start: cursor,
            end,
            occurrence: index as u8,
        });
        cursor = end;
    }
    spans
}

fn all_occurrences(haystack: &str, needle: &str) -> Vec<Span> {
    let mut result = Vec::new();
    if needle.is_empty() {
        return result;
    }
    let mut cursor = 0;
    while let Some(relative) = haystack[cursor..].find(needle) {
        let start = cursor + relative;
        result.push(Span {
            start,
            end: start + needle.len(),
            occurrence: result.len() as u8,
        });
        cursor = start + needle.len();
    }
    result
}

fn substitute(
    template: &str,
    context: &str,
    entity: &str,
    relation: &str,
    state: Option<&str>,
) -> String {
    let rendered = template
        .replace("{context}", context)
        .replace("{entity}", entity)
        .replace("{relation}", relation);
    match state {
        Some(state) => rendered.replace("{state}", state),
        None => rendered,
    }
}

fn validate_track_schedule(quartet: &Quartet) -> Result<(), Box<dyn Error>> {
    let split_c = split_index(&quartet.context_term_split)?;
    let split_e = split_index(&quartet.entity_term_split)?;
    let pair = quartet.replicate_id;
    let expected_order = match quartet.track_id.as_str() {
        "FACTORIAL_BALANCED" => {
            (3 * quartet.world_family_id
                + 5 * quartet.relation_id
                + 7 * quartet.query_template_id
                + pair)
                % 6
        }
        "BINDING_CONTEXT" => (pair + quartet.entity_pair_id + 3 * split_c + split_e) % 6,
        "BINDING_ENTITY" => {
            (quartet.entity_pair_id + quartet.context_pair_id + split_c + 3 * split_e) % 6
        }
        _ => return Err("unknown track in schedule validation".into()),
    };
    let permutations: [[u8; 3]; 6] = [
        [0, 1, 2],
        [0, 2, 1],
        [1, 0, 2],
        [1, 2, 0],
        [2, 0, 1],
        [2, 1, 0],
    ];
    if quartet.candidate_identity_order != permutations[expected_order as usize] {
        return Err(format!(
            "quartet {} candidate order schedule mismatch",
            quartet.quartet_id
        )
        .into());
    }
    let expected_observation_template = if quartet.track_id == "FACTORIAL_BALANCED" {
        (quartet.query_template_id
            + quartet.world_family_id
            + quartet.relation_id
            + 3 * quartet.state_id)
            % 8
    } else {
        0
    };
    if quartet.observation_template_id != expected_observation_template {
        return Err(format!(
            "quartet {} observation-template schedule mismatch",
            quartet.quartet_id
        )
        .into());
    }
    Ok(())
}

fn split_index(label: &str) -> Result<u8, Box<dyn Error>> {
    match label {
        "TRAIN_SIDE_STYLE" => Ok(0),
        "NOVEL_HELDOUT" => Ok(1),
        _ => Err(format!("unknown term split {label}").into()),
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::{scan_expected_spans, validate_inventory_independently};
    use crate::generate::{for_each_quartet, term_inventory};

    #[test]
    fn independent_term_reconstruction_matches_generator_inventory() {
        let contract_path =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../contracts/world-contract-v01.json");
        let contract: serde_json::Value =
            serde_json::from_slice(&std::fs::read(contract_path).unwrap()).unwrap();
        let inventory = term_inventory();
        validate_inventory_independently(&inventory, &contract).unwrap();
    }

    #[test]
    fn character_offsets_reconstruct_template_slots() {
        let observation = "In banuvek, the dekirek has relvane zavik.";
        let query = "What is relvane for dekirek in banuvek?";
        let input = format!("{observation}\n{query}\nOptions: zavik, nurex, pavom");
        let spans = scan_expected_spans(
            &input,
            observation,
            "banuvek",
            "dekirek",
            "relvane",
            "zavik",
            &["zavik".to_owned(), "nurex".to_owned(), "pavom".to_owned()],
        );
        assert_eq!(spans.context.len(), 2);
        assert_eq!(spans.entity.len(), 2);
        assert_eq!(spans.relation.len(), 2);
        assert_eq!(spans.state_in_observation.len(), 1);
        assert_eq!(spans.candidate_options.len(), 3);
        assert_eq!(
            &input[spans.context[0].start..spans.context[0].end],
            "banuvek"
        );
    }

    #[test]
    fn generated_candidate_order_schedules_match_independent_formulas() {
        for_each_quartet(|quartet| {
            super::validate_track_schedule(&quartet)?;
            Ok(())
        })
        .expect("all candidate order schedules reconstruct independently");
    }
}

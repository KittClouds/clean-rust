use std::collections::BTreeMap;
use std::error::Error;

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::model::{
    CandidateSemantic, CharacterSpans, ExactWorldState, LatentWorld, Quartet, QuerySemantics, Span,
    TermInventory, Variant, WorldFact,
};

pub const GENERATOR_SEED: u64 = 2_026_092_501;
pub const EXPECTED_FACTORIAL_QUARTETS: usize = 24_576;
pub const EXPECTED_BINDING_CONTEXT_QUARTETS: usize = 1_024;
pub const EXPECTED_BINDING_ENTITY_QUARTETS: usize = 1_024;
pub const EXPECTED_QUARTETS: usize = 26_624;

pub const WORLD_FAMILIES: [&str; 8] = [
    "STABLE",
    "SINGLE_SWITCH",
    "RETURN",
    "CYCLIC",
    "GRADUAL_DRIFT",
    "TEMPORARY_RULE",
    "CONTRADICTORY_NOISE",
    "POISON_BURST",
];

pub const RELATIONS: [&str; 2] = ["kelmori", "vethaku"];
pub const STATES: [&str; 3] = ["brinok", "saldem", "tovira"];

pub const OBSERVATION_TEMPLATES: [&str; 8] = [
    "In {context}, the {entity} has {relation} {state}.",
    "For {context}: {relation} of {entity} = {state}.",
    "Within {context}, {entity} is recorded as {state} for {relation}.",
    "The {relation} entry for {entity} at {context} reads {state}.",
    "Record: {context} / {entity} / {relation} -> {state}.",
    "{entity} at {context} carries {state} under {relation}.",
    "Index {relation}: {entity} in {context} maps to {state}.",
    "Fact [{context}; {entity}; {relation}] = {state}.",
];

pub const QUERY_TEMPLATES: [&str; 8] = [
    "What is {relation} for {entity} in {context}?",
    "Find the {relation} of {entity} at {context}.",
    "Select {relation}({context}, {entity}).",
    "Report {entity}'s {relation} within {context}.",
    "Return current {relation}: {context} / {entity}.",
    "Which value is stored for {relation} and {entity} under {context}?",
    "Give the {relation} linked to {entity} in {context}.",
    "Look up {context} -> {entity} -> {relation}.",
];

const PREFIXES: [&str; 8] = [
    "doru", "feka", "gima", "huzo", "jare", "lovi", "muse", "paku",
];
const SUFFIXES: [&str; 8] = ["nex", "bir", "dov", "kem", "lus", "mar", "qin", "vek"];

#[derive(Clone, Copy, Debug, Default)]
pub struct Counts {
    pub factorial: usize,
    pub binding_context: usize,
    pub binding_entity: usize,
    pub total: usize,
}

struct QuartetDesign {
    track_id: &'static str,
    context_split: u8,
    entity_split: u8,
    family_id: u8,
    relation_id: u8,
    state_id: u8,
    observation_template_id: u8,
    query_template_id: u8,
    context_pair_id: u8,
    entity_pair_id: u8,
    candidate_order_index: u8,
    ordinal: u64,
}

struct RenderContext<'a> {
    quartet_id: &'a str,
    context_term_split: &'a str,
    entity_term_split: &'a str,
    query_template_id: u8,
    relation: &'a str,
    state: &'a str,
    candidate_identity_order: &'a [u8],
    candidate_text_order: &'a [String],
    target_candidate_identity: u8,
    exact_target: u8,
    query_semantics: &'a QuerySemantics,
}

struct VariantRender<'a> {
    variant_id: &'a str,
    changed_factor: &'a str,
    context_term_id: u8,
    context_term: &'a str,
    entity_term_id: u8,
    entity_term: &'a str,
    observation_template_id: u8,
}

pub fn term_inventory() -> TermInventory {
    let mut all_terms: Vec<String> = PREFIXES
        .iter()
        .flat_map(|prefix| {
            SUFFIXES
                .iter()
                .map(move |suffix| format!("{prefix}{suffix}"))
        })
        .collect();
    all_terms.sort_by_key(|term| {
        let key = format!("{GENERATOR_SEED}|FAS_E1_FRESH_TERM_ALLOCATION|{term}");
        sha256_hex(key.as_bytes())
    });
    TermInventory {
        inventory_id: "FAS_FROZEN_OBSERVER_BUNDLE_E1_TERMS_V01".to_owned(),
        generator_seed: GENERATOR_SEED,
        context_terms: all_terms[..32].to_vec(),
        entity_terms: all_terms[32..].to_vec(),
        train_side_style_ids: (0..16).collect(),
        novel_heldout_ids: (16..32).collect(),
    }
}

pub fn for_each_quartet<F>(mut emit: F) -> Result<Counts, Box<dyn Error>>
where
    F: FnMut(Quartet) -> Result<(), Box<dyn Error>>,
{
    let inventory = term_inventory();
    let mut counts = Counts::default();
    let mut ordinal = 0_u64;
    for context_split in 0..2_u8 {
        for entity_split in 0..2_u8 {
            for family_id in 0..8_u8 {
                for relation_id in 0..2_u8 {
                    for state_id in 0..3_u8 {
                        for query_template_id in 0..8_u8 {
                            let observation_template_id =
                                (query_template_id + family_id + relation_id + 3 * state_id) % 8;
                            let entity_offset = (3 * family_id
                                + 5 * relation_id
                                + 7 * state_id
                                + 11 * context_split
                                + 13 * entity_split)
                                % 16;
                            for pair_index in 0..16_u8 {
                                let entity_pair_index = (pair_index + entity_offset) % 16;
                                let candidate_order_index = (3 * family_id
                                    + 5 * relation_id
                                    + 7 * query_template_id
                                    + pair_index)
                                    % 6;
                                let quartet = make_quartet(
                                    QuartetDesign {
                                        track_id: "FACTORIAL_BALANCED",
                                        context_split,
                                        entity_split,
                                        family_id,
                                        relation_id,
                                        state_id,
                                        observation_template_id,
                                        query_template_id,
                                        context_pair_id: pair_index,
                                        entity_pair_id: entity_pair_index,
                                        candidate_order_index,
                                        ordinal,
                                    },
                                    &inventory,
                                );
                                emit(quartet)?;
                                counts.factorial += 1;
                                ordinal += 1;
                            }
                        }
                    }
                }
            }
        }
    }

    for context_split in 0..2_u8 {
        for entity_split in 0..2_u8 {
            for pair_index in 0..16_u8 {
                for counterpart_index in 0..16_u8 {
                    let order =
                        (pair_index + counterpart_index + 3 * context_split + entity_split) % 6;
                    emit(make_quartet(
                        QuartetDesign {
                            track_id: "BINDING_CONTEXT",
                            context_split,
                            entity_split,
                            family_id: 0,
                            relation_id: 0,
                            state_id: 0,
                            observation_template_id: 0,
                            query_template_id: 0,
                            context_pair_id: pair_index,
                            entity_pair_id: counterpart_index,
                            candidate_order_index: order,
                            ordinal,
                        },
                        &inventory,
                    ))?;
                    counts.binding_context += 1;
                    ordinal += 1;
                }
            }
        }
    }

    for context_split in 0..2_u8 {
        for entity_split in 0..2_u8 {
            for pair_index in 0..16_u8 {
                for counterpart_index in 0..16_u8 {
                    let order =
                        (pair_index + counterpart_index + context_split + 3 * entity_split) % 6;
                    emit(make_quartet(
                        QuartetDesign {
                            track_id: "BINDING_ENTITY",
                            context_split,
                            entity_split,
                            family_id: 0,
                            relation_id: 0,
                            state_id: 0,
                            observation_template_id: 0,
                            query_template_id: 0,
                            context_pair_id: counterpart_index,
                            entity_pair_id: pair_index,
                            candidate_order_index: order,
                            ordinal,
                        },
                        &inventory,
                    ))?;
                    counts.binding_entity += 1;
                    ordinal += 1;
                }
            }
        }
    }
    counts.total = counts.factorial + counts.binding_context + counts.binding_entity;
    Ok(counts)
}

fn make_quartet(design: QuartetDesign, inventory: &TermInventory) -> Quartet {
    let QuartetDesign {
        track_id,
        context_split,
        entity_split,
        family_id,
        relation_id,
        state_id,
        observation_template_id,
        query_template_id,
        context_pair_id,
        entity_pair_id,
        candidate_order_index,
        ordinal,
    } = design;
    let context_start = context_split * 16;
    let entity_start = entity_split * 16;
    let context_term_id = context_start + context_pair_id;
    let context_partner_id = context_start + (context_pair_id + 7) % 16;
    let entity_term_id = entity_start + entity_pair_id;
    let entity_partner_id = entity_start + (entity_pair_id + 7) % 16;
    let family = WORLD_FAMILIES[family_id as usize];
    let relation = RELATIONS[relation_id as usize];
    let state = STATES[state_id as usize];
    let candidate_orders: [[u8; 3]; 6] = [
        [0, 1, 2],
        [0, 2, 1],
        [1, 0, 2],
        [1, 2, 0],
        [2, 0, 1],
        [2, 1, 0],
    ];
    let candidate_order = candidate_orders[candidate_order_index as usize].to_vec();
    let candidate_surfaces = STATES.map(str::to_owned);
    let target_candidate_identity = state_id;
    let exact_target = candidate_order
        .iter()
        .position(|candidate| *candidate == target_candidate_identity)
        .expect("candidate identities form a permutation") as u8;
    let context_split_name = split_name(context_split);
    let entity_split_name = split_name(entity_split);
    let canonical_context_id = format!("canonical-context-{context_split}-{context_pair_id:02}");
    let canonical_entity_id = format!("canonical-entity-{entity_split}-{entity_pair_id:02}");
    let current_state = ExactWorldState {
        canonical_context_id: canonical_context_id.clone(),
        canonical_entity_id: canonical_entity_id.clone(),
        relation_id,
        state_id,
        target_candidate_identity,
    };
    let latent_world = LatentWorld {
        world_family: family.to_owned(),
        world_family_id: family_id,
        time_step: 0,
        feedback_marker: "NONE".to_owned(),
        facts: vec![WorldFact {
            canonical_context_id: canonical_context_id.clone(),
            canonical_entity_id: canonical_entity_id.clone(),
            relation_id,
            state_id,
        }],
        candidate_semantics: candidate_surfaces
            .iter()
            .enumerate()
            .map(|(id, surface)| CandidateSemantic {
                candidate_identity: id as u8,
                state_id: id as u8,
                surface: surface.clone(),
            })
            .collect(),
        current_exact_world_state: current_state,
    };
    let latent_bytes = serde_json::to_vec(&latent_world).expect("latent world serializes");
    let latent_world_sha256 = sha256_hex(&latent_bytes);
    let quartet_key = format!(
        "{track_id}|{context_split}|{entity_split}|{family_id}|{relation_id}|{state_id}|{observation_template_id}|{query_template_id}|{context_pair_id}|{entity_pair_id}|{candidate_order_index}|{ordinal}"
    );
    let quartet_id = sha256_hex(quartet_key.as_bytes());
    let render_seed = splitmix64(GENERATOR_SEED ^ ordinal);
    let query_semantics = QuerySemantics {
        canonical_context_id,
        canonical_entity_id,
        relation_id,
    };
    let candidates: Vec<String> = candidate_order
        .iter()
        .map(|candidate_id| candidate_surfaces[*candidate_id as usize].clone())
        .collect();
    let context_base = &inventory.context_terms[context_term_id as usize];
    let context_partner = &inventory.context_terms[context_partner_id as usize];
    let entity_base = &inventory.entity_terms[entity_term_id as usize];
    let entity_partner = &inventory.entity_terms[entity_partner_id as usize];

    let variant_specs = [
        (
            "A",
            "NONE",
            context_term_id,
            context_base.as_str(),
            entity_term_id,
            entity_base.as_str(),
            observation_template_id,
        ),
        (
            "C",
            "CONTEXT",
            context_partner_id,
            context_partner.as_str(),
            entity_term_id,
            entity_base.as_str(),
            observation_template_id,
        ),
        (
            "E",
            "ENTITY",
            context_term_id,
            context_base.as_str(),
            entity_partner_id,
            entity_partner.as_str(),
            observation_template_id,
        ),
        (
            "P",
            "OBSERVATION_TEMPLATE",
            context_term_id,
            context_base.as_str(),
            entity_term_id,
            entity_base.as_str(),
            (observation_template_id + 4) % 8,
        ),
    ];
    let render_context = RenderContext {
        quartet_id: &quartet_id,
        context_term_split: &context_split_name,
        entity_term_split: &entity_split_name,
        query_template_id,
        relation,
        state,
        candidate_identity_order: &candidate_order,
        candidate_text_order: &candidates,
        target_candidate_identity,
        exact_target,
        query_semantics: &query_semantics,
    };
    let variants = variant_specs
        .into_iter()
        .map(
            |(
                variant_id,
                changed_factor,
                context_id,
                context_surface,
                entity_id,
                entity_surface,
                obs_template,
            )| {
                render_variant(
                    VariantRender {
                        variant_id,
                        changed_factor,
                        context_term_id: context_id,
                        context_term: context_surface,
                        entity_term_id: entity_id,
                        entity_term: entity_surface,
                        observation_template_id: obs_template,
                    },
                    &render_context,
                )
            },
        )
        .collect();

    Quartet {
        quartet_id,
        track_id: track_id.to_owned(),
        replicate_id: context_pair_id,
        context_pair_id,
        entity_pair_id,
        context_term_split: context_split_name,
        entity_term_split: entity_split_name,
        world_family: family.to_owned(),
        world_family_id: family_id,
        relation_id,
        relation_surface: relation.to_owned(),
        state_id,
        state_surface: state.to_owned(),
        observation_template_id,
        query_template_id,
        generator_seed: GENERATOR_SEED,
        render_seed,
        time_step: 0,
        feedback_marker: "NONE".to_owned(),
        latent_world,
        latent_world_sha256,
        target_candidate_identity,
        exact_target,
        candidate_identity_order: candidate_order,
        variants,
    }
}

fn render_variant(spec: VariantRender<'_>, context: &RenderContext<'_>) -> Variant {
    let VariantRender {
        variant_id,
        changed_factor,
        context_term_id,
        context_term,
        entity_term_id,
        entity_term,
        observation_template_id,
    } = spec;
    let RenderContext {
        quartet_id,
        context_term_split,
        entity_term_split,
        query_template_id,
        relation,
        state,
        candidate_identity_order,
        candidate_text_order,
        target_candidate_identity,
        exact_target,
        query_semantics,
    } = context;
    let query_template_id = *query_template_id;
    let values = BTreeMap::from([
        ("context", context_term),
        ("entity", entity_term),
        ("relation", relation),
        ("state", state),
    ]);
    let (observation_text, observation_slots) = render_template(
        OBSERVATION_TEMPLATES[observation_template_id as usize],
        &values,
    );
    let query_values = BTreeMap::from([
        ("context", context_term),
        ("entity", entity_term),
        ("relation", relation),
    ]);
    let (query_text, query_slots) =
        render_template(QUERY_TEMPLATES[query_template_id as usize], &query_values);
    let query_offset = observation_text.len() + 1;
    let options_prefix = format!("{observation_text}\n{query_text}\nOptions: ");
    let mut input_text = options_prefix.clone();
    let mut candidate_spans = Vec::with_capacity(candidate_text_order.len());
    for (index, candidate) in candidate_text_order.iter().enumerate() {
        if index > 0 {
            input_text.push_str(", ");
        }
        let start = input_text.len();
        input_text.push_str(candidate);
        candidate_spans.push(Span {
            start,
            end: input_text.len(),
            occurrence: index as u8,
        });
    }
    let mut spans = CharacterSpans {
        context: observation_slots
            .get("context")
            .cloned()
            .unwrap_or_default(),
        entity: observation_slots.get("entity").cloned().unwrap_or_default(),
        relation: observation_slots
            .get("relation")
            .cloned()
            .unwrap_or_default(),
        state_in_observation: observation_slots.get("state").cloned().unwrap_or_default(),
        candidate_options: candidate_spans,
    };
    append_shifted(&mut spans.context, query_slots.get("context"), query_offset);
    append_shifted(&mut spans.entity, query_slots.get("entity"), query_offset);
    append_shifted(
        &mut spans.relation,
        query_slots.get("relation"),
        query_offset,
    );
    let event_id = format!("{quartet_id}:{variant_id}");
    let fingerprint = RenderedFingerprint {
        event_id: &event_id,
        variant_id,
        context_term_id,
        entity_term_id,
        observation_template_id,
        query_template_id,
        observation_text: &observation_text,
        query_text: &query_text,
        input_text: &input_text,
        candidate_identity_order,
        character_spans: &spans,
    };
    let rendered_bytes = serde_json::to_vec(&fingerprint).expect("render fingerprint serializes");
    let input_sha256 = sha256_hex(input_text.as_bytes());
    let rendered_event_sha256 = sha256_hex(&rendered_bytes);
    Variant {
        event_id,
        variant_id: variant_id.to_owned(),
        changed_factor: changed_factor.to_owned(),
        context_term_id,
        context_term: context_term.to_owned(),
        entity_term_id,
        entity_term: entity_term.to_owned(),
        context_term_split: (*context_term_split).to_owned(),
        entity_term_split: (*entity_term_split).to_owned(),
        observation_template_id,
        query_template_id,
        observation_template_role: if observation_template_id < 6 {
            "TRAIN_SIDE_STYLE"
        } else {
            "HELDOUT"
        }
        .to_owned(),
        query_template_role: if query_template_id < 6 {
            "TRAIN_SIDE_STYLE"
        } else {
            "HELDOUT"
        }
        .to_owned(),
        observation_text,
        query_text,
        input_text,
        query_semantics: (*query_semantics).clone(),
        candidate_identity_order: candidate_identity_order.to_vec(),
        candidate_text_order: candidate_text_order.to_vec(),
        target_candidate_identity: *target_candidate_identity,
        exact_target: *exact_target,
        character_spans: spans,
        input_sha256,
        rendered_event_sha256,
    }
}

#[derive(Serialize)]
struct RenderedFingerprint<'a> {
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

fn render_template(
    template: &str,
    values: &BTreeMap<&str, &str>,
) -> (String, BTreeMap<String, Vec<Span>>) {
    let mut output = String::with_capacity(template.len() + 48);
    let mut slots: BTreeMap<String, Vec<Span>> = BTreeMap::new();
    let bytes = template.as_bytes();
    let mut cursor = 0;
    while cursor < bytes.len() {
        if bytes[cursor] != b'{' {
            output.push(bytes[cursor] as char);
            cursor += 1;
            continue;
        }
        let close = template[cursor + 1..]
            .find('}')
            .map(|offset| cursor + 1 + offset)
            .expect("all frozen template placeholders close");
        let key = &template[cursor + 1..close];
        let value = values
            .get(key)
            .expect("all frozen placeholders have values");
        let start = output.len();
        output.push_str(value);
        let positions = slots.entry(key.to_owned()).or_default();
        positions.push(Span {
            start,
            end: output.len(),
            occurrence: positions.len() as u8,
        });
        cursor = close + 1;
    }
    (output, slots)
}

fn append_shifted(target: &mut Vec<Span>, source: Option<&Vec<Span>>, shift: usize) {
    if let Some(source) = source {
        let base_occurrence = target.len() as u8;
        target.extend(source.iter().enumerate().map(|(index, span)| Span {
            start: span.start + shift,
            end: span.end + shift,
            occurrence: base_occurrence + index as u8,
        }));
    }
}

pub fn split_name(index: u8) -> String {
    if index == 0 {
        "TRAIN_SIDE_STYLE".to_owned()
    } else {
        "NOVEL_HELDOUT".to_owned()
    }
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    format!("{:x}", digest.finalize())
}

fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9E3779B97F4A7C15);
    value = (value ^ (value >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94D049BB133111EB);
    value ^ (value >> 31)
}

pub fn write_repeat_digest() -> Result<(Counts, String), Box<dyn Error>> {
    let mut digest = Sha256::new();
    let counts = for_each_quartet(|quartet| {
        let mut encoded = serde_json::to_vec(&quartet)?;
        encoded.push(b'\n');
        digest.update(encoded);
        Ok(())
    })?;
    Ok((counts, format!("{:x}", digest.finalize())))
}

#[cfg(test)]
mod tests {
    use super::{EXPECTED_QUARTETS, for_each_quartet, term_inventory, write_repeat_digest};

    #[test]
    fn term_inventory_is_fixed_and_role_local() {
        let inventory = term_inventory();
        assert_eq!(inventory.context_terms.len(), 32);
        assert_eq!(inventory.entity_terms.len(), 32);
        assert_eq!(
            inventory
                .context_terms
                .iter()
                .collect::<std::collections::HashSet<_>>()
                .len(),
            32
        );
        assert_eq!(
            inventory
                .entity_terms
                .iter()
                .collect::<std::collections::HashSet<_>>()
                .len(),
            32
        );
        assert!(inventory.context_terms.iter().all(|term| term.is_ascii()));
        assert!(inventory.entity_terms.iter().all(|term| term.is_ascii()));
    }

    #[test]
    fn corpus_counts_and_variant_edges_are_exact() {
        let counts = for_each_quartet(|quartet| {
            assert_eq!(quartet.variants.len(), 4);
            assert_eq!(quartet.variants[0].variant_id, "A");
            assert_eq!(quartet.variants[1].variant_id, "C");
            assert_eq!(quartet.variants[2].variant_id, "E");
            assert_eq!(quartet.variants[3].variant_id, "P");
            assert_eq!(quartet.exact_target, quartet.variants[0].exact_target);
            assert_eq!(quartet.exact_target, quartet.variants[1].exact_target);
            assert_eq!(quartet.exact_target, quartet.variants[2].exact_target);
            assert_eq!(quartet.exact_target, quartet.variants[3].exact_target);
            assert_eq!(
                quartet.variants[0].entity_term_id,
                quartet.variants[1].entity_term_id
            );
            assert_eq!(
                quartet.variants[0].context_term_id,
                quartet.variants[2].context_term_id
            );
            assert_eq!(
                quartet.variants[0].query_text,
                quartet.variants[3].query_text
            );
            Ok(())
        })
        .expect("generation succeeds");
        assert_eq!(counts.total, EXPECTED_QUARTETS);
        assert_eq!(counts.factorial, 24_576);
        assert_eq!(counts.binding_context, 1_024);
        assert_eq!(counts.binding_entity, 1_024);
    }

    #[test]
    fn deterministic_repeat_digest_is_stable() {
        let (_, first) = write_repeat_digest().expect("first digest");
        let (_, second) = write_repeat_digest().expect("second digest");
        assert_eq!(first, second);
    }
}

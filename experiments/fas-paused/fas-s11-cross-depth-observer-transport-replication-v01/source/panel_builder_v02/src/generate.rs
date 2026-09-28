use crate::model::{
    CandidateLedgerRow, CandidateSemantic, Event, ExactWorldState, LatentWorld, Quartet,
    QuerySemantics, TermInventory, WorldFact,
};
use sha2::{Digest, Sha256};

pub const SEED: u64 = 379_211_686_401_371_100;
pub const TOTAL_QUARTETS: usize = 26_624;
pub const QUOTAS: [usize; 3] = [1_733, 1_815, 1_770];

pub const FAMILIES: [&str; 8] = [
    "STABLE",
    "SINGLE_SWITCH",
    "RETURN",
    "CYCLIC",
    "GRADUAL_DRIFT",
    "TEMPORARY_RULE",
    "CONTRADICTORY_NOISE",
    "POISON_BURST",
];
pub const RELATIONS: [&str; 2] = ["relvane", "soprix"];
pub const STATES: [&str; 3] = ["zavik", "nurex", "pavom"];
pub const PREFIXES: [&str; 8] = [
    "cavu", "dome", "feka", "giru", "hano", "jupi", "luse", "moti",
];
pub const SUFFIXES: [&str; 8] = ["bex", "cif", "dun", "fap", "gok", "hiv", "mek", "puz"];

pub const OBSERVATIONS: [&str; 8] = [
    "In {context}, the {entity} has {relation} {state}.",
    "For {context}: {relation} of {entity} = {state}.",
    "Within {context}, {entity} is recorded as {state} for {relation}.",
    "The {relation} entry for {entity} at {context} reads {state}.",
    "Record: {context} / {entity} / {relation} -> {state}.",
    "{entity} at {context} carries {state} under {relation}.",
    "Index {relation}: {entity} in {context} maps to {state}.",
    "Fact [{context}; {entity}; {relation}] = {state}.",
];
pub const QUERIES: [&str; 8] = [
    "What is {relation} for {entity} in {context}?",
    "Find the {relation} of {entity} at {context}.",
    "Select {relation}({context}, {entity}).",
    "Report {entity}'s {relation} within {context}.",
    "Return current {relation}: {context} / {entity}.",
    "Which value is stored for {relation} and {entity} under {context}?",
    "Give the {relation} linked to {entity} in {context}.",
    "Look up {context} -> {entity} -> {relation}.",
];

#[derive(Clone, Copy)]
struct Design {
    track: &'static str,
    context_split: u8,
    entity_split: u8,
    family: u8,
    relation: u8,
    state: u8,
    observation_template: u8,
    query_template: u8,
    context_pair: Option<u8>,
    entity_pair: Option<u8>,
    order_index: u8,
    ordinal: u64,
}

pub fn term_inventory() -> TermInventory {
    let mut all = Vec::with_capacity(64);
    for prefix in PREFIXES {
        for suffix in SUFFIXES {
            all.push(format!("{prefix}{suffix}"));
        }
    }
    TermInventory {
        inventory_id: "FAS_S11_FRESH_TERM_INVENTORY_V01".to_owned(),
        generator_seed: SEED,
        context_terms: all[..32].to_vec(),
        entity_terms: all[32..].to_vec(),
        train_side_style_ids: (0..16).collect(),
        novel_heldout_ids: (16..32).collect(),
    }
}

pub fn generate_all() -> Vec<Quartet> {
    let inventory = term_inventory();
    let designs = designs();
    assert_eq!(designs.len(), TOTAL_QUARTETS);
    designs
        .into_iter()
        .map(|design| make_quartet(design, &inventory))
        .collect()
}

fn designs() -> Vec<Design> {
    let mut result = Vec::with_capacity(TOTAL_QUARTETS);
    let mut ordinal = 0_u64;
    for context_split in 0..2_u8 {
        for entity_split in 0..2_u8 {
            for family in 0..8_u8 {
                for relation in 0..2_u8 {
                    for state in 0..3_u8 {
                        for query_template in 0..8_u8 {
                            let observation_template =
                                (query_template + family + relation + 3 * state) % 8;
                            let offset = (3 * family
                                + 5 * relation
                                + 7 * state
                                + 11 * context_split
                                + 13 * entity_split)
                                % 16;
                            for pair in 0..16_u8 {
                                result.push(Design {
                                    track: "FACTORIAL_BALANCED",
                                    context_split,
                                    entity_split,
                                    family,
                                    relation,
                                    state,
                                    observation_template,
                                    query_template,
                                    context_pair: Some(pair),
                                    entity_pair: Some((pair + offset) % 16),
                                    order_index: (3 * family
                                        + 5 * relation
                                        + 7 * query_template
                                        + pair)
                                        % 6,
                                    ordinal,
                                });
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
            for context_pair in 0..16_u8 {
                for entity_pair in 0..16_u8 {
                    result.push(Design {
                        track: "BINDING_CONTEXT",
                        context_split,
                        entity_split,
                        family: 0,
                        relation: 0,
                        state: 0,
                        observation_template: 0,
                        query_template: 0,
                        context_pair: Some(context_pair),
                        entity_pair: Some(entity_pair),
                        order_index: (context_pair
                            + entity_pair
                            + 3 * context_split
                            + entity_split)
                            % 6,
                        ordinal,
                    });
                    ordinal += 1;
                }
            }
        }
    }
    for context_split in 0..2_u8 {
        for entity_split in 0..2_u8 {
            for entity_pair in 0..16_u8 {
                for context_pair in 0..16_u8 {
                    result.push(Design {
                        track: "BINDING_ENTITY",
                        context_split,
                        entity_split,
                        family: 0,
                        relation: 0,
                        state: 0,
                        observation_template: 0,
                        query_template: 0,
                        context_pair: Some(context_pair),
                        entity_pair: Some(entity_pair),
                        order_index: (entity_pair
                            + context_pair
                            + context_split
                            + 3 * entity_split)
                            % 6,
                        ordinal,
                    });
                    ordinal += 1;
                }
            }
        }
    }
    result
}

fn make_quartet(d: Design, terms: &TermInventory) -> Quartet {
    let cp = d.context_pair.expect("S01 design has context pair IDs");
    let ep = d.entity_pair.expect("S01 design has entity pair IDs");
    let context_base_id = d.context_split * 16 + cp;
    let context_alt_id = d.context_split * 16 + (cp + 7) % 16;
    let entity_base_id = d.entity_split * 16 + ep;
    let entity_alt_id = d.entity_split * 16 + (ep + 7) % 16;
    let context_base = &terms.context_terms[context_base_id as usize];
    let context_alt = &terms.context_terms[context_alt_id as usize];
    let entity_base = &terms.entity_terms[entity_base_id as usize];
    let entity_alt = &terms.entity_terms[entity_alt_id as usize];
    let order = [
        [0, 1, 2],
        [0, 2, 1],
        [1, 0, 2],
        [1, 2, 0],
        [2, 0, 1],
        [2, 1, 0],
    ][d.order_index as usize]
        .to_vec();
    let exact_target = order.iter().position(|id| *id == d.state).unwrap() as u8;
    let context_id = format!("fas-s11-v01-canonical-context-{}-{cp:02}", d.context_split);
    let entity_id = format!("fas-s11-v01-canonical-entity-{}-{ep:02}", d.entity_split);
    let candidates: Vec<CandidateSemantic> = STATES
        .iter()
        .enumerate()
        .map(|(id, surface)| CandidateSemantic {
            candidate_identity: id as u8,
            state_id: id as u8,
            surface: (*surface).to_owned(),
        })
        .collect();
    let latent = LatentWorld {
        regime_id: d.family,
        regime_name: FAMILIES[d.family as usize].to_owned(),
        time_step: 0,
        feedback_marker: "NONE".to_owned(),
        facts: vec![WorldFact {
            canonical_context_id: context_id.clone(),
            canonical_entity_id: entity_id.clone(),
            relation_id: d.relation,
            state_id: d.state,
        }],
        candidate_semantics: candidates,
        current_exact_world_state: ExactWorldState {
            canonical_context_id: context_id.clone(),
            canonical_entity_id: entity_id.clone(),
            relation_id: d.relation,
            state_id: d.state,
            target_candidate_identity: d.state,
        },
    };
    let query_semantics = QuerySemantics {
        canonical_context_id: context_id,
        canonical_entity_id: entity_id,
        relation_id: d.relation,
    };
    let candidate_surfaces: Vec<String> = order
        .iter()
        .map(|id| STATES[*id as usize].to_owned())
        .collect();
    let world_id = format!("fas-s11-v01-world-{:06}", d.ordinal);
    let episode_id = format!("fas-s11-v01-episode-{:06}", d.ordinal);
    let quartet_id = format!("fas-s11-v01-quartet-{:06}", d.ordinal);
    let variant_specs = [
        (
            "A",
            "NONE",
            context_base_id,
            context_base,
            entity_base_id,
            entity_base,
            d.observation_template,
        ),
        (
            "C",
            "CONTEXT",
            context_alt_id,
            context_alt,
            entity_base_id,
            entity_base,
            d.observation_template,
        ),
        (
            "E",
            "ENTITY",
            context_base_id,
            context_base,
            entity_alt_id,
            entity_alt,
            d.observation_template,
        ),
        (
            "P",
            "OBSERVATION_TEMPLATE",
            context_base_id,
            context_base,
            entity_base_id,
            entity_base,
            (d.observation_template + 4) % 8,
        ),
    ];
    let variants = variant_specs
        .into_iter()
        .map(
            |(id, changed, context_term_id, context_term, entity_term_id, entity_term, obs_id)| {
                render_event(
                    d.ordinal,
                    id,
                    changed,
                    context_term_id,
                    context_term,
                    entity_term_id,
                    entity_term,
                    d.context_split,
                    d.entity_split,
                    obs_id,
                    d.query_template,
                    d.relation,
                    d.state,
                    &query_semantics,
                    &order,
                    &candidate_surfaces,
                    d.state,
                    exact_target,
                )
            },
        )
        .collect();
    Quartet {
        ordinal: d.ordinal,
        world_id,
        episode_id,
        quartet_id,
        track_id: d.track.to_owned(),
        context_split: d.context_split,
        entity_split: d.entity_split,
        context_term_split: split_name(d.context_split).to_owned(),
        entity_term_split: split_name(d.entity_split).to_owned(),
        context_pair_id: d.context_pair,
        entity_pair_id: d.entity_pair,
        world_family_id: d.family,
        world_family: FAMILIES[d.family as usize].to_owned(),
        relation_id: d.relation,
        relation_surface: RELATIONS[d.relation as usize].to_owned(),
        state_id: d.state,
        state_surface: STATES[d.state as usize].to_owned(),
        observation_template_id: d.observation_template,
        query_template_id: d.query_template,
        candidate_order_index: d.order_index,
        generator_seed: SEED,
        render_seed: splitmix64(SEED ^ d.ordinal),
        latent_world: latent,
        target_candidate_identity: d.state,
        exact_target,
        candidate_identity_order: order,
        variants,
    }
}

#[allow(clippy::too_many_arguments)]
fn render_event(
    ordinal: u64,
    variant_id: &str,
    changed_factor: &str,
    context_term_id: u8,
    context_term: &str,
    entity_term_id: u8,
    entity_term: &str,
    context_split: u8,
    entity_split: u8,
    observation_id: u8,
    query_id: u8,
    relation_id: u8,
    state_id: u8,
    semantics: &QuerySemantics,
    candidate_ids: &[u8],
    candidate_text: &[String],
    target_identity: u8,
    exact_target: u8,
) -> Event {
    let relation = RELATIONS[relation_id as usize];
    let state = STATES[state_id as usize];
    let observation_text = render_template(
        OBSERVATIONS[observation_id as usize],
        context_term,
        entity_term,
        relation,
        state,
    );
    let query_text = render_template(
        QUERIES[query_id as usize],
        context_term,
        entity_term,
        relation,
        "",
    );
    let mut input_text = String::with_capacity(observation_text.len() + query_text.len() + 64);
    input_text.push_str(&observation_text);
    input_text.push('\n');
    input_text.push_str(&query_text);
    input_text.push_str("\nOptions: ");
    for (index, candidate) in candidate_text.iter().enumerate() {
        if index > 0 {
            input_text.push_str(", ");
        }
        input_text.push_str(candidate);
    }
    Event {
        event_id: format!("fas-s11-v01-event-{ordinal:06}-{variant_id}"),
        variant_id: variant_id.to_owned(),
        changed_factor: changed_factor.to_owned(),
        context_term_id,
        context_term: context_term.to_owned(),
        entity_term_id,
        entity_term: entity_term.to_owned(),
        context_term_split: split_name(context_split).to_owned(),
        entity_term_split: split_name(entity_split).to_owned(),
        observation_template_id: observation_id,
        query_template_id: query_id,
        observation_text,
        query_text,
        input_sha256: sha256_hex(input_text.as_bytes()),
        input_text,
        query_semantics: semantics.clone(),
        candidate_identity_order: candidate_ids.to_vec(),
        candidate_text_order: candidate_text.to_vec(),
        target_candidate_identity: target_identity,
        exact_target,
    }
}

fn render_template(
    template: &str,
    context: &str,
    entity: &str,
    relation: &str,
    state: &str,
) -> String {
    template
        .replace("{context}", context)
        .replace("{entity}", entity)
        .replace("{relation}", relation)
        .replace("{state}", state)
}

pub fn split_name(index: u8) -> &'static str {
    if index == 0 {
        "TRAIN_SIDE_STYLE"
    } else {
        "NOVEL_HELDOUT"
    }
}

pub fn selection_key(q: &Quartet) -> String {
    let c = q.context_pair_id.map(|v| v.to_string()).unwrap_or_default();
    let e = q.entity_pair_id.map(|v| v.to_string()).unwrap_or_default();
    format!(
        "{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
        q.track_id,
        q.context_split,
        q.entity_split,
        q.world_family_id,
        q.relation_id,
        q.state_id,
        q.observation_template_id,
        q.query_template_id,
        c,
        e,
        q.candidate_order_index,
        q.ordinal
    )
}

pub fn selection_hash(target_id: u8, key: &str) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"FAS-S11-V01|SELECT|");
    hasher.update(target_id.to_string().as_bytes());
    hasher.update(b"|");
    hasher.update(key.as_bytes());
    hasher.finalize().into()
}

pub fn ledger_row(
    q: &Quartet,
    identity_fresh: bool,
    input_hashes_fresh: bool,
    selected: bool,
    duplicate_rejected: bool,
) -> Result<CandidateLedgerRow, serde_json::Error> {
    let key = selection_key(q);
    let class = q.exact_target;
    let payload = serde_json::to_vec(q)?;
    let events = q
        .variants
        .iter()
        .map(|v| scoped_identity_hash("event", &v.event_id))
        .collect();
    let inputs = q.variants.iter().map(|v| v.input_sha256.clone()).collect();
    Ok(CandidateLedgerRow {
        ordinal: q.ordinal,
        track_id: q.track_id.clone(),
        context_split: q.context_split,
        entity_split: q.entity_split,
        world_family_id: q.world_family_id,
        relation_id: q.relation_id,
        state_id: q.state_id,
        observation_template_id: q.observation_template_id,
        query_template_id: q.query_template_id,
        context_pair_id: q.context_pair_id,
        entity_pair_id: q.entity_pair_id,
        candidate_order_index: q.candidate_order_index,
        target_class: class,
        canonical_candidate_key: key.clone(),
        selection_sha256: to_hex(&selection_hash(class, &key)),
        identity_fresh,
        input_hashes_fresh,
        selected,
        disposition: if !identity_fresh || !input_hashes_fresh {
            "FRESHNESS_REJECTED"
        } else if selected {
            "SELECTED"
        } else if duplicate_rejected {
            "INTRA_PANEL_DUPLICATE_REJECTED"
        } else {
            "NOT_SELECTED"
        }
        .to_owned(),
        quartet_payload_sha256: sha256_hex(&payload),
        world_identity_sha256: scoped_identity_hash("world", &q.world_id),
        episode_identity_sha256: scoped_identity_hash("episode", &q.episode_id),
        quartet_identity_sha256: scoped_identity_hash("quartet", &q.quartet_id),
        event_identity_sha256: events,
        rendered_input_sha256: inputs,
    })
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    to_hex(&hasher.finalize())
}

pub fn scoped_identity_hash(kind: &str, id: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(kind.as_bytes());
    hasher.update(b"|");
    hasher.update(id.as_bytes());
    to_hex(&hasher.finalize())
}

pub fn to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut result = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        result.push(HEX[(byte >> 4) as usize] as char);
        result.push(HEX[(byte & 0xf) as usize] as char);
    }
    result
}

fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9E3779B97F4A7C15);
    value = (value ^ (value >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94D049BB133111EB);
    value ^ (value >> 31)
}

#[cfg(test)]
mod tests {
    use hashbrown::HashSet;
    use sha2::{Digest, Sha256};

    use super::{
        FAMILIES, QUERIES, QUOTAS, SEED, STATES, TOTAL_QUARTETS, generate_all, selection_hash,
        selection_key, term_inventory,
    };

    #[test]
    fn fresh_terms_follow_contract_product_and_do_not_overlap_parent_terms() {
        let inventory = term_inventory();
        assert_eq!(inventory.context_terms.len(), 32);
        assert_eq!(inventory.entity_terms.len(), 32);
        assert_eq!(inventory.train_side_style_ids, (0..16).collect::<Vec<_>>());
        assert_eq!(inventory.novel_heldout_ids, (16..32).collect::<Vec<_>>());
        let unique: HashSet<&str> = inventory
            .context_terms
            .iter()
            .chain(&inventory.entity_terms)
            .map(String::as_str)
            .collect();
        assert_eq!(unique.len(), 64);
        assert_eq!(inventory.context_terms[0], "cavubex");
        assert_eq!(inventory.context_terms[31], "girupuz");
        assert_eq!(inventory.entity_terms[0], "hanobex");
        assert_eq!(inventory.entity_terms[31], "motipuz");
        let old_prefixes = [
            "banu", "deki", "fimo", "galu", "kove", "mipa", "nozu", "veti",
        ];
        let old_suffixes = ["rek", "tal", "vum", "qof", "zin", "pax", "luj", "sem"];
        let old: HashSet<String> = old_prefixes
            .iter()
            .flat_map(|prefix| {
                old_suffixes
                    .iter()
                    .map(move |suffix| format!("{prefix}{suffix}"))
            })
            .collect();
        assert!(
            inventory
                .context_terms
                .iter()
                .all(|term| !old.contains(term))
        );
        assert!(
            inventory
                .entity_terms
                .iter()
                .all(|term| !old.contains(term))
        );
    }

    #[test]
    fn seed_derivation_matches_sealed_label_and_u64() {
        let digest = Sha256::digest(b"FAS-S11-V01-WORLD-SEED");
        let derived = u64::from_le_bytes(digest[..8].try_into().unwrap());
        assert_eq!(derived, SEED);
        assert_eq!(
            format!("{:x}", digest),
            "dc6ba106053b430501713ebcc4f4d5963bfa861a5b2c1d4ca4b0ac58e81c178a"
        );
    }

    #[test]
    fn full_universe_has_exact_counts_and_counterfactual_invariants() {
        let rows = generate_all();
        assert_eq!(rows.len(), TOTAL_QUARTETS);
        let mut tracks = [0_usize; 3];
        let mut classes = [0_usize; 3];
        for (ordinal, q) in rows.iter().enumerate() {
            assert_eq!(q.ordinal, ordinal as u64);
            assert_eq!(q.generator_seed, SEED);
            assert_eq!(q.world_id, format!("fas-s11-v01-world-{ordinal:06}"));
            assert_eq!(q.episode_id, format!("fas-s11-v01-episode-{ordinal:06}"));
            assert_eq!(q.quartet_id, format!("fas-s11-v01-quartet-{ordinal:06}"));
            assert_eq!(
                q.latent_world.regime_name,
                FAMILIES[q.world_family_id as usize]
            );
            assert_eq!(q.variants.len(), 4);
            assert_eq!(
                q.variants
                    .iter()
                    .map(|event| event.variant_id.as_str())
                    .collect::<Vec<_>>(),
                ["A", "C", "E", "P"]
            );
            classes[q.exact_target as usize] += 1;
            tracks[match q.track_id.as_str() {
                "FACTORIAL_BALANCED" => 0,
                "BINDING_CONTEXT" => 1,
                "BINDING_ENTITY" => 2,
                _ => panic!("unknown track"),
            }] += 1;
            assert_eq!(q.target_candidate_identity, q.state_id);
            assert_eq!(q.latent_world.facts.len(), 1);
            assert_eq!(q.latent_world.facts[0].state_id, q.state_id);
            assert_eq!(
                q.latent_world.current_exact_world_state.state_id,
                q.state_id
            );
            assert_eq!(
                q.variants
                    .iter()
                    .map(|event| event.exact_target)
                    .collect::<Vec<_>>(),
                vec![q.exact_target; 4]
            );
            assert_eq!(
                q.variants
                    .iter()
                    .map(|event| event.target_candidate_identity)
                    .collect::<Vec<_>>(),
                vec![q.state_id; 4]
            );
            assert_eq!(
                q.variants
                    .iter()
                    .map(|event| event.candidate_identity_order.clone())
                    .collect::<Vec<_>>(),
                vec![q.candidate_identity_order.clone(); 4]
            );
            for event in &q.variants {
                assert_eq!(
                    event.query_semantics.canonical_context_id,
                    q.latent_world.facts[0].canonical_context_id
                );
                assert_eq!(
                    event.query_semantics.canonical_entity_id,
                    q.latent_world.facts[0].canonical_entity_id
                );
                assert_eq!(event.query_semantics.relation_id, q.relation_id);
                assert_eq!(
                    event.query_text.contains(
                        QUERIES[q.query_template_id as usize]
                            .split('{')
                            .next()
                            .unwrap()
                    ),
                    true
                );
                assert_eq!(
                    super::sha256_hex(event.input_text.as_bytes()),
                    event.input_sha256
                );
            }
            let [a, c, e, p] = q.variants.as_slice() else {
                unreachable!()
            };
            assert_eq!(a.entity_term_id, c.entity_term_id);
            assert_ne!(a.context_term_id, c.context_term_id);
            assert_eq!(a.context_term_id, e.context_term_id);
            assert_ne!(a.entity_term_id, e.entity_term_id);
            assert_eq!(a.context_term_id, p.context_term_id);
            assert_eq!(a.entity_term_id, p.entity_term_id);
            assert_eq!(a.query_text, p.query_text);
            assert_eq!(c.observation_template_id, a.observation_template_id);
            assert_eq!(e.observation_template_id, a.observation_template_id);
            assert_eq!(
                p.observation_template_id,
                (a.observation_template_id + 4) % 8
            );
            assert_eq!(
                a.candidate_text_order.iter().collect::<HashSet<_>>().len(),
                3
            );
        }
        assert_eq!(tracks, [24_576, 1_024, 1_024]);
        assert_eq!(classes.iter().sum::<usize>(), TOTAL_QUARTETS);
        assert_eq!(QUOTAS.iter().sum::<usize>(), 5_318);
    }

    #[test]
    fn selection_key_and_digest_are_stable_and_class_specific() {
        let q = generate_all().remove(0);
        let key = selection_key(&q);
        assert_eq!(
            key,
            format!(
                "FACTORIAL_BALANCED|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
                q.context_split,
                q.entity_split,
                q.world_family_id,
                q.relation_id,
                q.state_id,
                q.observation_template_id,
                q.query_template_id,
                q.context_pair_id.unwrap(),
                q.entity_pair_id.unwrap(),
                q.candidate_order_index,
                q.ordinal
            )
        );
        assert_ne!(selection_hash(0, &key), selection_hash(1, &key));
        assert_eq!(
            selection_hash(q.exact_target, &key),
            selection_hash(q.exact_target, &key)
        );
        assert_eq!(q.world_family, FAMILIES[q.world_family_id as usize]);
        assert_eq!(q.state_surface, STATES[q.state_id as usize]);
    }
}

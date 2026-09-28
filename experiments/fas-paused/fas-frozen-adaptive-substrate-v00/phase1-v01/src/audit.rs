use std::{
    collections::{BTreeMap, BTreeSet},
    fs::File,
    io::{BufRead, BufReader},
    path::Path,
};

use fas00::world::{Family, Feedback, LABELS, Track};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::types::{BaselineSummary, Gate, LeakageRow, QualificationEvent};

const TERM_POOLS: [[&str; 4]; 3] = [
    ["vorp", "neth", "zuli", "mavik"],
    ["dorul", "pavax", "kelmi", "tovin"],
    ["branik", "sovel", "ximar", "ludek"],
];
const CONTEXT_POOLS: [[&str; 2]; 3] = [["Karo", "Mivu"], ["Dema", "Rilo"], ["Fesa", "Naku"]];

#[derive(Default, Serialize)]
pub struct AuditReport {
    pub gates: Vec<Gate>,
    pub leakage: Vec<LeakageRow>,
    pub baselines: Vec<BaselineSummary>,
    pub return_identity_cases: u64,
    pub return_latent_equal: u64,
    pub return_surface_equal: u64,
    pub return_semantic_rule_equal: u64,
    pub return_query_different: u64,
    pub context_counterfactual_pairs: u64,
    pub context_pairs_different: u64,
    pub entity_counterfactual_pairs: u64,
    pub entity_pairs_different: u64,
    pub transition_counts: BTreeMap<String, u64>,
    pub drift_evidence_rates_by_bin: Vec<f64>,
}

fn digest(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}

#[derive(Serialize)]
struct LatentCanonical<'a> {
    step: u32,
    regime: &'a str,
    regime_phase: u8,
    world_state: &'a [fas00::world::KeyState],
    target: u8,
}

pub fn rendered_hash(event: &QualificationEvent) -> Result<String, String> {
    let mut canonical = event.clone();
    canonical.rendered_event_sha256.clear();
    let bytes = serde_json::to_vec(&canonical).map_err(|error| error.to_string())?;
    Ok(digest(&bytes))
}

fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

fn independent_draw(seed: u64, step: u32, domain: u64, modulo: u64) -> usize {
    let mut value = (seed ^ ((step as u64) << 32) ^ domain).wrapping_add(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
    ((value ^ (value >> 31)) % modulo) as usize
}

pub fn family_name(family: Family) -> &'static str {
    match family {
        Family::Stable => "STABLE",
        Family::SingleSwitch => "SINGLE_SWITCH",
        Family::Return => "RETURN",
        Family::Cyclic => "CYCLIC",
        Family::GradualDrift => "GRADUAL_DRIFT",
        Family::TemporaryRule => "TEMPORARY_RULE",
        Family::ContradictoryNoise => "CONTRADICTORY_NOISE",
        Family::PoisonBurst => "POISON_BURST",
    }
}

fn expected_phase(family: Family, step: u32) -> u8 {
    // Phase 1 is qualification split, whose frozen schedule offset is +1.
    let t = step.saturating_sub(1);
    match family {
        Family::Stable | Family::ContradictoryNoise | Family::PoisonBurst => 0,
        Family::SingleSwitch | Family::GradualDrift => u8::from(t >= 16),
        Family::Return => u8::from((8..16).contains(&t)),
        Family::Cyclic => match t {
            0..=7 => 0,
            8..=15 => 1,
            16..=23 => 2,
            _ => 0,
        },
        Family::TemporaryRule => u8::from((12..16).contains(&t)),
    }
}

fn phase_key(track: Track, context_id: u8, phase: u8) -> u8 {
    if track == Track::ContextBound && context_id == 1 {
        0
    } else {
        phase
    }
}

pub fn expected_observation_for_gate(event: &QualificationEvent) -> Option<u8> {
    let t = event.time_step;
    let visible =
        t.is_multiple_of(3) || (event.world_family == Family::PoisonBurst && (12..18).contains(&t));
    if !visible {
        return None;
    }
    let state = event.current_exact_world_state[event.key_id as usize].answer_index;
    if event.world_family == Family::GradualDrift {
        let old_phase = phase_key(event.task_structure, event.context_id, 0);
        let key_offset = if event.task_structure == Track::ContextBound {
            (event.key_id % 4) % 3
        } else {
            0
        } + event.relation_id;
        let old = (old_phase + key_offset + event.world_seed as u8 % 3) % 3;
        let new = if event.task_structure == Track::ContextBound && event.context_id == 1 {
            old
        } else {
            (old + 1) % 3
        };
        let adjusted = t.saturating_sub(1);
        return Some(if adjusted < 8 {
            old
        } else if adjusted >= 24
            || independent_draw(event.world_seed, t, 13, 16) < (adjusted - 8) as usize
        {
            new
        } else {
            old
        });
    }
    let contradicted = (event.world_family == Family::ContradictoryNoise && t.is_multiple_of(9))
        || (event.world_family == Family::PoisonBurst && (12..18).contains(&t));
    Some(if contradicted { (state + 1) % 3 } else { state })
}

fn expected_query_terms(event: &QualificationEvent) -> (&'static str, &'static str) {
    let split = 1usize;
    let seed = event.world_seed;
    let entity_offset = independent_draw(seed, 0, 11, 4);
    let context_flip = independent_draw(seed, 0, 12, 2);
    let context_slot = (event.context_id as usize + context_flip) % 2;
    let entity_slot = (event.entity_id as usize + entity_offset) % 4;
    (
        CONTEXT_POOLS[split][context_slot],
        TERM_POOLS[split][entity_slot],
    )
}

pub fn validate_world(events: &[QualificationEvent]) -> Result<u64, String> {
    if events.len() != 32 {
        return Err("qualification world must contain exactly 32 events".into());
    }
    let first = &events[0];
    let mut transitions = 0;
    for (step, event) in events.iter().enumerate() {
        let t = step as u32;
        if event.time_step != t
            || event.event_id != format!("{}:{t:02}", first.world_id)
            || event.world_id != first.world_id
            || event.world_seed != first.world_seed
            || event.world_family != first.world_family
            || event.task_structure != first.task_structure
            || event.feedback_condition != first.feedback_condition
        {
            return Err(format!("world/event identity mismatch at {t}"));
        }
        if event.current_exact_world_state.len() != 8
            || event.key_id >= 8
            || event.context_id >= 2
            || event.entity_id >= 2
            || event.relation_id >= 2
        {
            return Err(format!("key or state bounds mismatch at {t}"));
        }
        if event.surface_template_id
            != 3 + (t as usize + independent_draw(first.world_seed, 0, 14, 3)) as u8 % 3
        {
            return Err(format!("template construction mismatch at {t}"));
        }
        if !(3..=5).contains(&event.surface_template_id)
            || !(4..=7).contains(&event.entity_term_id)
            || !(2..=3).contains(&event.context_term_id)
        {
            return Err(format!(
                "qualification surface identity out of split at {t}"
            ));
        }
        let (context, entity) = expected_query_terms(event);
        let relation = if event.relation_id == 0 {
            "status"
        } else {
            "mode"
        };
        if !event.query_text.contains(context)
            || !event.query_text.contains(entity)
            || !event.query_text.contains(relation)
        {
            return Err(format!("query semantics disagree with IDs at {t}"));
        }
        let candidate_set: BTreeSet<_> = event
            .candidate_text_in_order
            .iter()
            .map(String::as_str)
            .collect();
        let expected_candidates: BTreeSet<_> = LABELS.into_iter().collect();
        if candidate_set != expected_candidates {
            return Err(format!("candidate set mismatch at {t}"));
        }
        for (index, candidate) in event.candidate_text_in_order.iter().enumerate() {
            let identity = LABELS.iter().position(|label| label == candidate).unwrap() as u8;
            if identity != event.candidate_identities_in_order[index] {
                return Err(format!("candidate identity/order mismatch at {t}"));
            }
        }
        let expected_context_term =
            2 + (event.context_id as usize + independent_draw(event.world_seed, 0, 12, 2)) % 2;
        let expected_entity_term =
            4 + (event.entity_id as usize + independent_draw(event.world_seed, 0, 11, 4)) % 4;
        if event.context_term_id as usize != expected_context_term
            || event.entity_term_id as usize != expected_entity_term
        {
            return Err(format!("invented-term identity mismatch at {t}"));
        }
        let query_key = event
            .current_exact_world_state
            .iter()
            .find(|state| {
                state.context_id == event.context_id
                    && state.entity_id == event.entity_id
                    && state.relation_id == event.relation_id
            })
            .ok_or_else(|| format!("query has no exact state at {t}"))?;
        if query_key.key_id != event.key_id {
            return Err(format!("key lookup disagrees with query semantics at {t}"));
        }
        if query_key.answer_index != event.exact_target {
            return Err(format!(
                "target differs from independent state lookup at {t}"
            ));
        }
        if event.latent_regime_phase != expected_phase(first.world_family, t)
            || event.latent_regime_id
                != ["A", "B", "C"][expected_phase(first.world_family, t) as usize]
        {
            return Err(format!("regime identity mismatch at {t}"));
        }
        let due = t + if first.feedback_condition == Feedback::Immediate {
            0
        } else {
            8
        };
        if event.feedback_reveal_step != due {
            return Err(format!("feedback reveal step mismatch at {t}"));
        }
        let expected_visible: Vec<_> = events
            .iter()
            .filter(|candidate| candidate.feedback_reveal_step == t)
            .map(|candidate| candidate.event_id.clone())
            .collect();
        if event.visible_feedback_ids_after_score != expected_visible {
            return Err(format!("visible feedback IDs mismatch at {t}"));
        }
        if event.observation_answer_index != expected_observation_for_gate(event) {
            return Err(format!("observation authority mismatch at {t}"));
        }
        match (
            &event.observation_text,
            &event.observation_identity,
            event.observation_answer_index,
        ) {
            (None, identity, None) if identity == "OBS_NONE" => (),
            (Some(text), identity, Some(label))
                if label < 3
                    && identity == &digest(text.as_bytes())
                    && text.matches(LABELS[label as usize]).count() == 1
                    && LABELS
                        .iter()
                        .filter(|candidate| text.contains(**candidate))
                        .count()
                        == 1 =>
            {
                ()
            }
            _ => return Err(format!("observation identity/content mismatch at {t}")),
        }
        if event.query_identity != digest(event.query_text.as_bytes()) {
            return Err(format!("query identity mismatch at {t}"));
        }
        for (key, state) in event.current_exact_world_state.iter().enumerate() {
            if state.key_id as usize != key
                || state.context_id != (key as u8 % 4) / 2
                || state.entity_id != key as u8 % 2
                || state.relation_id != key as u8 / 4
            {
                return Err(format!("latent key identity mismatch at {t}, key {key}"));
            }
            let phase = phase_key(
                event.task_structure,
                state.context_id,
                expected_phase(first.world_family, t),
            );
            let context_entity_offset = if event.task_structure == Track::ContextBound {
                (state.key_id % 4) % 3
            } else {
                0
            };
            let expected_state =
                (phase + context_entity_offset + state.relation_id + (event.world_seed % 3) as u8)
                    % 3;
            if state.answer_index != expected_state {
                return Err(format!(
                    "latent state reconstruction mismatch at {t}, key {key}"
                ));
            }
        }
        if event.rendered_event_sha256 != rendered_hash(event)? {
            return Err(format!("rendered event hash mismatch at {t}"));
        }
        if step > 0 {
            let previous = &events[step - 1];
            let previous_phase = expected_phase(first.world_family, t - 1);
            let phase = expected_phase(first.world_family, t);
            if previous_phase != phase {
                transitions += 1;
            }
            for key in 0..8usize {
                let before = &previous.current_exact_world_state[key];
                let after = &event.current_exact_world_state[key];
                if (before.context_id, before.entity_id, before.relation_id)
                    != (after.context_id, after.entity_id, after.relation_id)
                {
                    return Err(format!("key identity changed at transition into {t}"));
                }
                let active_context =
                    first.task_structure == Track::GlobalRule || before.context_id == 0;
                let expected_after = if active_context {
                    let delta = (phase + 3 - previous_phase) % 3;
                    (before.answer_index + delta) % 3
                } else {
                    before.answer_index
                };
                if after.answer_index != expected_after {
                    return Err(format!("independent transition mismatch at {t}, key {key}"));
                }
            }
        }
    }
    Ok(transitions)
}

pub fn validate_serialized_corpus(
    output: &Path,
    manifest_records: &[crate::types::WorldRecord],
) -> Result<(), String> {
    let file = File::open(output.join("qualification-events-v01.jsonl"))
        .map_err(|error| error.to_string())?;
    let mut events_by_world: BTreeMap<String, Vec<QualificationEvent>> = BTreeMap::new();
    for (line_number, line) in BufReader::new(file).lines().enumerate() {
        let line = line.map_err(|error| error.to_string())?;
        let event: QualificationEvent = serde_json::from_str(&line).map_err(|error| {
            format!("serialized event line {} invalid: {error}", line_number + 1)
        })?;
        events_by_world
            .entry(event.world_id.clone())
            .or_default()
            .push(event);
    }
    if events_by_world.len() != manifest_records.len() {
        return Err("serialized world count differs from world manifest".into());
    }
    for record in manifest_records {
        let world = events_by_world
            .get(&record.world_id)
            .ok_or_else(|| format!("serialized world missing: {}", record.world_id))?;
        validate_world(world)?;
        let mut rendered = Sha256::new();
        let mut latent = Sha256::new();
        for event in world {
            let bytes = serde_json::to_vec(event).map_err(|error| error.to_string())?;
            rendered.update(&bytes);
            rendered.update(b"\n");
            let latent_row = LatentCanonical {
                step: event.time_step,
                regime: &event.latent_regime_id,
                regime_phase: event.latent_regime_phase,
                world_state: &event.current_exact_world_state,
                target: event.exact_target,
            };
            latent.update(serde_json::to_vec(&latent_row).map_err(|error| error.to_string())?);
            latent.update(b"\n");
        }
        if hex(&rendered.finalize()) != record.rendered_events_sha256
            || hex(&latent.finalize()) != record.latent_world_sha256
        {
            return Err(format!(
                "serialized world hash mismatch: {}",
                record.world_id
            ));
        }
    }
    Ok(())
}

pub fn return_identity(events: &[QualificationEvent]) -> Result<(bool, bool, bool, bool), String> {
    if events[0].world_family != Family::Return {
        return Ok((false, false, false, false));
    }
    let split_offset = 1usize;
    let initial_step = split_offset;
    let returned_step = initial_step + 16;
    let initial = &events[initial_step];
    let returned = &events[returned_step];
    let latent_equal = initial.current_exact_world_state == returned.current_exact_world_state;
    let rule_equal = latent_equal
        && initial.exact_target == returned.exact_target
        && initial.latent_regime_id == returned.latent_regime_id;
    let surface_equal = initial.query_text == returned.query_text
        && initial.observation_text == returned.observation_text;
    let query_different = initial.query_text != returned.query_text;
    Ok((latent_equal, surface_equal, rule_equal, query_different))
}

pub fn context_pair_counts(events: &[QualificationEvent]) -> (u64, u64, u64, u64) {
    let mut context_total = 0;
    let mut context_different = 0;
    let mut entity_total = 0;
    let mut entity_different = 0;
    if events[0].task_structure != Track::ContextBound {
        return (0, 0, 0, 0);
    }
    for event in events {
        for left in &event.current_exact_world_state {
            for right in &event.current_exact_world_state {
                if left.entity_id == right.entity_id
                    && left.relation_id == right.relation_id
                    && left.context_id != right.context_id
                {
                    context_total += 1;
                    context_different += u64::from(left.answer_index != right.answer_index);
                }
                if left.context_id == right.context_id
                    && left.relation_id == right.relation_id
                    && left.entity_id != right.entity_id
                {
                    entity_total += 1;
                    entity_different += u64::from(left.answer_index != right.answer_index);
                }
            }
        }
    }
    (
        context_total,
        context_different,
        entity_total,
        entity_different,
    )
}

fn most_common(values: &[u32; 3]) -> u8 {
    let mut best = 0;
    for index in 1..3 {
        if values[index] > values[best] {
            best = index;
        }
    }
    best as u8
}

pub fn baseline_correct(events: &[QualificationEvent]) -> [u32; 5] {
    let mut correct = [0; 5];
    let mut global_counts = [0u32; 3];
    let mut last_global = 0u8;
    let mut key_counts = [[0u32; 3]; 8];
    let mut last_key = [None; 8];
    for event in events {
        if let Some(observed) = event.observation_answer_index {
            global_counts[observed as usize] += 1;
            last_global = observed;
            key_counts[event.key_id as usize][observed as usize] += 1;
            last_key[event.key_id as usize] = Some(observed);
        }
        let predictions = [
            most_common(&global_counts),
            last_global,
            last_key[event.key_id as usize].unwrap_or(0),
            most_common(&key_counts[event.key_id as usize]),
            {
                let phase = event.latent_regime_phase;
                let initial =
                    events[0].current_exact_world_state[event.key_id as usize].answer_index;
                let key_phase = phase_key(event.task_structure, event.context_id, phase);
                (initial + key_phase) % 3
            },
        ];
        for (index, prediction) in predictions.into_iter().enumerate() {
            correct[index] += u32::from(prediction == event.exact_target);
        }
    }
    correct
}

fn category(event: &QualificationEvent, name: &str) -> String {
    let word_count = event.query_text.split_whitespace().count();
    let punctuation: String = event
        .query_text
        .chars()
        .filter(|c| !c.is_alphanumeric() && !c.is_whitespace())
        .collect();
    let candidate = event
        .candidate_identities_in_order
        .iter()
        .map(u8::to_string)
        .collect::<Vec<_>>()
        .join("");
    match name {
        "template_id" => event.surface_template_id.to_string(),
        "candidate_order" => candidate,
        "query_length_bucket" => (event.query_text.len() / 16).to_string(),
        "word_count_bucket" => (word_count / 3).to_string(),
        "punctuation_pattern" => punctuation,
        "invented_term_id" => event.entity_term_id.to_string(),
        "region_name_id" => event.context_term_id.to_string(),
        "relation_id" => event.relation_id.to_string(),
        "time_position_bucket" => (event.time_step / 4).to_string(),
        "feedback_condition" => format!("{:?}", event.feedback_condition),
        "world_family" => format!("{:?}", event.world_family),
        "public_surface_bundle" => format!(
            "{}|{}|{}|{}|{}|{}|{}|{}|{}",
            event.surface_template_id,
            candidate,
            event.query_text.len() / 16,
            word_count / 3,
            punctuation,
            event.entity_term_id,
            event.context_term_id,
            event.relation_id,
            event.time_step / 4
        ),
        "family_time_key_bundle" => format!(
            "{:?}|{:?}|{}|{}|{}|{}|{}",
            event.world_family,
            event.feedback_condition,
            event.time_step / 4,
            event.key_id,
            event.context_id,
            event.entity_id,
            event.relation_id
        ),
        _ => String::new(),
    }
}

fn audit_category(events: &[QualificationEvent], group: &str) -> LeakageRow {
    let mut counts: BTreeMap<String, [u32; 3]> = BTreeMap::new();
    let mut prior = [0u32; 3];
    for event in events.iter().filter(|e| e.world_seed < 16) {
        let category = category(event, group);
        counts.entry(category).or_default()[event.exact_target as usize] += 1;
        prior[event.exact_target as usize] += 1;
    }
    let mut confusion = [[0u64; 3]; 3];
    for event in events.iter().filter(|e| e.world_seed >= 16) {
        let votes = counts.get(&category(event, group)).unwrap_or(&prior);
        let predicted = most_common(votes) as usize;
        confusion[event.exact_target as usize][predicted] += 1;
    }
    let n: u64 = confusion.iter().flatten().sum();
    let correct: u64 = (0..3).map(|i| confusion[i][i]).sum();
    let balanced = (0..3)
        .map(|i| {
            let class_n: u64 = confusion[i].iter().sum();
            if class_n == 0 {
                0.0
            } else {
                confusion[i][i] as f64 / class_n as f64
            }
        })
        .sum::<f64>()
        / 3.0;
    LeakageRow {
        feature_group: group.into(),
        held_out_accuracy: correct as f64 / n.max(1) as f64,
        held_out_balanced_accuracy: balanced,
        predictions: n,
        partition: "train seeds 0..15; held-out seeds 16..31".into(),
    }
}

pub fn leakage_audit(events: &[QualificationEvent]) -> Vec<LeakageRow> {
    [
        "template_id",
        "candidate_order",
        "query_length_bucket",
        "word_count_bucket",
        "punctuation_pattern",
        "invented_term_id",
        "region_name_id",
        "relation_id",
        "time_position_bucket",
        "feedback_condition",
        "world_family",
        "public_surface_bundle",
        "family_time_key_bundle",
    ]
    .into_iter()
    .map(|group| audit_category(events, group))
    .collect()
}

pub fn summaries(
    world_baselines: &[[u32; 5]],
    context_world_baselines: &[[u32; 5]],
) -> Vec<BaselineSummary> {
    let names = [
        "GLOBAL_MAJORITY",
        "LAST_GLOBAL_OBSERVATION",
        "LAST_OBSERVATION_PER_KEY",
        "PER_KEY_COUNTER",
        "ORACLE_REGIME_ID",
    ];
    names
        .iter()
        .enumerate()
        .map(|(index, name)| {
            let total: u64 = world_baselines.iter().map(|r| r[index] as u64).sum();
            let predictions = (world_baselines.len() * 32) as u64;
            let context_total: u64 = context_world_baselines
                .iter()
                .map(|r| r[index] as u64)
                .sum();
            let context_n = (context_world_baselines.len() * 32) as u64;
            BaselineSummary {
                name: (*name).into(),
                accuracy: total as f64 / predictions.max(1) as f64,
                predictions,
                context_bound_accuracy: if context_n > 0 {
                    Some(context_total as f64 / context_n as f64)
                } else {
                    None
                },
            }
        })
        .collect()
}

pub fn transition_gate(counts: &BTreeMap<String, u64>) -> Vec<Gate> {
    let specifications = [
        ("STABLE", 0u64),
        ("SINGLE_SWITCH", 1),
        ("RETURN", 2),
        ("CYCLIC", 3),
        ("GRADUAL_DRIFT", 1),
        ("TEMPORARY_RULE", 2),
        ("CONTRADICTORY_NOISE", 0),
        ("POISON_BURST", 0),
    ];
    specifications
        .into_iter()
        .map(|(family, expected)| {
            let actual = counts.get(family).copied().unwrap_or(u64::MAX);
            let expected_total = expected * 128;
            Gate {
                gate: format!("TRANSITION_SHAPE_{family}"),
                status: if actual == expected_total { "PASS" } else { "FAIL" }.into(),
                detail: format!("summed transitions across 128 paired worlds={actual}; expected={expected_total}"),
            }
        })
        .collect()
}

pub fn drift_rates(events: &[QualificationEvent]) -> Vec<f64> {
    let mut positive = [0u64; 4];
    let mut total = [0u64; 4];
    for event in events
        .iter()
        .filter(|event| event.world_family == Family::GradualDrift)
    {
        if event.task_structure == Track::ContextBound && event.context_id == 1 {
            continue;
        }
        let adjusted = event.time_step.saturating_sub(1);
        if !(8..24).contains(&adjusted) {
            continue;
        }
        let Some(observed) = event.observation_answer_index else {
            continue;
        };
        let key_offset = (if event.task_structure == Track::ContextBound {
            (event.key_id % 4) % 3
        } else {
            0
        }) + event.relation_id;
        let old = (key_offset + (event.world_seed % 3) as u8) % 3;
        let bin = ((adjusted - 8) / 4) as usize;
        total[bin] += 1;
        positive[bin] += u64::from(observed == (old + 1) % 3);
    }
    (0..4)
        .map(|index| positive[index] as f64 / total[index].max(1) as f64)
        .collect()
}

pub fn observation_identity(text: Option<&str>) -> String {
    text.map(|value| digest(value.as_bytes()))
        .unwrap_or_else(|| "OBS_NONE".into())
}

pub fn query_identity(text: &str) -> String {
    digest(text.as_bytes())
}

pub fn render_seed(seed: u64, step: u32) -> u64 {
    let mut value = seed ^ ((step as u64) << 32) ^ 0x4641535f52454e44;
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
    value ^ (value >> 31)
}

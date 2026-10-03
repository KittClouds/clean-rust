use std::collections::{BTreeMap, BTreeSet};

use crate::world::{
    Family, LABELS, Split, Track, WorldConfig, WorldEvent, generate, qualification_triplet,
};

// Deliberately independent of the generator's regime_phase helper.
fn expected_phase(family: Family, t: u32, split: Split) -> u8 {
    let t = t.saturating_sub(split.index() as u32);
    match family {
        Family::Stable | Family::ContradictoryNoise | Family::PoisonBurst => 0,
        Family::SingleSwitch | Family::GradualDrift => {
            if t < 16 {
                0
            } else {
                1
            }
        }
        Family::Return => {
            if (8..16).contains(&t) {
                1
            } else {
                0
            }
        }
        Family::Cyclic => {
            if !(8..24).contains(&t) {
                0
            } else if t < 16 {
                1
            } else {
                2
            }
        }
        Family::TemporaryRule => {
            if (12..16).contains(&t) {
                1
            } else {
                0
            }
        }
    }
}

fn expected_draw(seed: u64, step: u32, domain: u64) -> usize {
    let mut value = (seed ^ ((step as u64) << 32) ^ domain).wrapping_add(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
    ((value ^ (value >> 31)) % 16) as usize
}

pub fn validate(config: &WorldConfig, events: &[WorldEvent]) -> Result<(), String> {
    if events.len() != config.events as usize {
        return Err("event count mismatch".into());
    }
    let mut ids = BTreeSet::new();
    for (t, event) in events.iter().enumerate() {
        let t = t as u32;
        let x = &event.exposure;
        if x.step != t || !ids.insert(&x.event_id) {
            return Err(format!("step or ID defect at {t}"));
        }
        if event.world_seed != config.world_seed
            || event.family != config.family
            || event.track != config.track
            || event.split != config.split
            || event.feedback != config.feedback
            || event.label_rotation != config.label_rotation
        {
            return Err(format!("identity mismatch at {t}"));
        }
        if x.key_id != (t % 8) as u8
            || x.context_id != (x.key_id % 4) / 2
            || x.entity_id != x.key_id % 2
            || x.relation_id != x.key_id / 4
        {
            return Err(format!("key binding mismatch at {t}"));
        }
        let phase = expected_phase(config.family, t, config.split);
        if event.regime_phase != phase || event.regime_identity != ["A", "B", "C"][phase as usize] {
            return Err(format!("regime transition mismatch at {t}"));
        }
        if event.world_state.len() != 8 {
            return Err(format!("world-state size mismatch at {t}"));
        }
        for (key, state) in event.world_state.iter().enumerate() {
            let key = key as u8;
            let key_offset = if config.track == Track::ContextBound {
                (key % 4) % 3
            } else {
                0
            };
            let effective_phase = if config.track == Track::ContextBound && (key % 4) / 2 == 1 {
                0
            } else {
                phase
            };
            let expected = (effective_phase + key_offset + key / 4 + config.label_rotation) % 3;
            if state.key_id != key
                || state.context_id != (key % 4) / 2
                || state.entity_id != key % 2
                || state.relation_id != key / 4
                || state.answer_index != expected
            {
                return Err(format!("world state mismatch at {t}, key {key}"));
            }
        }
        let reconstructed = event.world_state[x.key_id as usize].answer_index;
        if event.target_index != reconstructed {
            return Err(format!("target mismatch at {t}"));
        }
        if event.feedback_due_step != config.feedback.due_step(t) {
            return Err(format!("feedback timing mismatch at {t}"));
        }
        if x.template_id / 3 != config.split.index() as u8 {
            return Err(format!("surface split mismatch at {t}"));
        }
        if x.candidates
            .iter()
            .map(String::as_str)
            .collect::<BTreeSet<_>>()
            != LABELS.into_iter().collect()
        {
            return Err(format!("candidate set mismatch at {t}"));
        }
        if LABELS.iter().any(|label| x.query.contains(label)) {
            return Err(format!("query-only label leakage at {t}"));
        }
        let visible =
            t.is_multiple_of(3) || (config.family == Family::PoisonBurst && (12..18).contains(&t));
        let expected_observed = if !visible {
            None
        } else if config.family == Family::GradualDrift {
            let offset = if config.track == Track::ContextBound {
                (x.key_id % 4) % 3
            } else {
                0
            } + x.relation_id;
            let old = (offset + config.label_rotation) % 3;
            let adjusted = t.saturating_sub(config.split.index() as u32);
            let new = if config.track == Track::ContextBound && x.context_id == 1 {
                old
            } else {
                (old + 1) % 3
            };
            Some(if adjusted < 8 {
                old
            } else if adjusted >= 24
                || expected_draw(config.world_seed, t, 13) < (adjusted - 8) as usize
            {
                new
            } else {
                old
            })
        } else if (config.family == Family::ContradictoryNoise && t.is_multiple_of(9))
            || (config.family == Family::PoisonBurst && (12..18).contains(&t))
        {
            Some((reconstructed + 1) % 3)
        } else {
            Some(reconstructed)
        };
        if x.observed_answer_index != expected_observed {
            return Err(format!("observation authority mismatch at {t}"));
        }
        match (&x.observation, x.observed_answer_index) {
            (Some(observation), Some(index))
                if index < 3
                    && observation.contains(LABELS[index as usize])
                    && LABELS
                        .iter()
                        .filter(|label| observation.contains(**label))
                        .count()
                        == 1 => {}
            (None, None) => (),
            _ => return Err(format!("observation mismatch at {t}")),
        }
    }
    Ok(())
}

pub fn validate_triplet(config: &WorldConfig) -> Result<(), String> {
    let triplet = qualification_triplet(config)?;
    for (rotation, world) in triplet.iter().enumerate() {
        let mut c = config.clone();
        c.label_rotation = rotation as u8;
        validate(&c, world)?;
    }
    for t in 0..config.events as usize {
        let queries: BTreeSet<_> = triplet
            .iter()
            .map(|world| &world[t].exposure.query)
            .collect();
        let candidate_orders: BTreeSet<_> = triplet
            .iter()
            .map(|world| &world[t].exposure.candidates)
            .collect();
        let targets: BTreeSet<_> = triplet.iter().map(|world| world[t].target_index).collect();
        if queries.len() != 1 || candidate_orders.len() != 1 || targets != BTreeSet::from([0, 1, 2])
        {
            return Err(format!("query-only counterfactual imbalance at {t}"));
        }
    }
    Ok(())
}

pub fn validate_split_integrity(configs: &[WorldConfig]) -> Result<(), String> {
    let mut templates: BTreeMap<usize, BTreeSet<u8>> = BTreeMap::new();
    let mut query_surfaces: BTreeMap<usize, BTreeSet<String>> = BTreeMap::new();
    for c in configs {
        let events = generate(c)?;
        validate(c, &events)?;
        let split = c.split.index();
        templates
            .entry(split)
            .or_default()
            .extend(events.iter().map(|e| e.exposure.template_id));
        query_surfaces
            .entry(split)
            .or_default()
            .extend(events.iter().map(|e| e.exposure.query.clone()));
    }
    for left in 0..3 {
        for right in left + 1..3 {
            if let (Some(a), Some(b)) = (templates.get(&left), templates.get(&right))
                && !a.is_disjoint(b)
            {
                return Err("template IDs overlap across splits".into());
            }
            if let (Some(a), Some(b)) = (query_surfaces.get(&left), query_surfaces.get(&right))
                && !a.is_disjoint(b)
            {
                return Err("query surfaces overlap across splits".into());
            }
        }
    }
    if configs
        .iter()
        .map(|c| c.split.index())
        .collect::<BTreeSet<_>>()
        != BTreeSet::from([0, 1, 2])
    {
        return Err("all three splits required".into());
    }
    Ok(())
}

pub fn split_name(split: Split) -> &'static str {
    match split {
        Split::Initialization => "initialization",
        Split::Qualification => "qualification",
        Split::Evaluation => "evaluation",
    }
}

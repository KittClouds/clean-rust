use serde::{Deserialize, Serialize};

pub const LABELS: [&str; 3] = ["safe", "risky", "idle"];
pub const DEFAULT_EVENTS: u32 = 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Split {
    Initialization,
    Qualification,
    Evaluation,
}

impl Split {
    pub fn index(self) -> usize {
        match self {
            Self::Initialization => 0,
            Self::Qualification => 1,
            Self::Evaluation => 2,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Family {
    Stable,
    SingleSwitch,
    Return,
    Cyclic,
    GradualDrift,
    TemporaryRule,
    ContradictoryNoise,
    PoisonBurst,
}

impl Family {
    pub const ALL: [Self; 8] = [
        Self::Stable,
        Self::SingleSwitch,
        Self::Return,
        Self::Cyclic,
        Self::GradualDrift,
        Self::TemporaryRule,
        Self::ContradictoryNoise,
        Self::PoisonBurst,
    ];
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Track {
    GlobalRule,
    ContextBound,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Feedback {
    Immediate,
    Delayed8,
}

impl Feedback {
    pub fn due_step(self, step: u32) -> u32 {
        step + match self {
            Self::Immediate => 0,
            Self::Delayed8 => 8,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorldConfig {
    pub world_seed: u64,
    pub split: Split,
    pub family: Family,
    pub track: Track,
    pub feedback: Feedback,
    pub events: u32,
    /// Counterfactual rotations 0, 1, 2 share query surfaces but cover all answers.
    pub label_rotation: u8,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KeyState {
    pub key_id: u8,
    pub context_id: u8,
    pub entity_id: u8,
    pub relation_id: u8,
    pub answer_index: u8,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Exposure {
    pub event_id: String,
    pub step: u32,
    pub key_id: u8,
    pub context_id: u8,
    pub entity_id: u8,
    pub relation_id: u8,
    pub observation: Option<String>,
    pub observed_answer_index: Option<u8>,
    pub query: String,
    pub candidates: [String; 3],
    pub template_id: u8,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorldEvent {
    pub exposure: Exposure,
    pub world_state: Vec<KeyState>,
    pub target_index: u8,
    pub regime_identity: String,
    pub regime_phase: u8,
    pub feedback_due_step: u32,
    pub world_seed: u64,
    pub family: Family,
    pub track: Track,
    pub split: Split,
    pub feedback: Feedback,
    pub label_rotation: u8,
}

const TERMS: [[&str; 4]; 3] = [
    ["vorp", "neth", "zuli", "mavik"],
    ["dorul", "pavax", "kelmi", "tovin"],
    ["branik", "sovel", "ximar", "ludek"],
];
const CONTEXTS: [[&str; 2]; 3] = [["Karo", "Mivu"], ["Dema", "Rilo"], ["Fesa", "Naku"]];

fn mix(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9e3779b97f4a7c15);
    x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
    x ^ (x >> 31)
}

fn draw(seed: u64, step: u32, domain: u64, modulo: u64) -> usize {
    (mix(seed ^ ((step as u64) << 32) ^ domain) % modulo) as usize
}

pub fn regime_phase(family: Family, step: u32, split: Split) -> u8 {
    // The held-out split contains a prospectively fixed unseen schedule shift.
    let step = step.saturating_sub(split.index() as u32);
    match family {
        Family::Stable | Family::ContradictoryNoise | Family::PoisonBurst => 0,
        Family::SingleSwitch => u8::from(step >= 16),
        Family::Return => u8::from((8..16).contains(&step)),
        Family::Cyclic => match step {
            0..=7 => 0,
            8..=15 => 1,
            16..=23 => 2,
            _ => 0,
        },
        Family::GradualDrift => u8::from(step >= 16),
        Family::TemporaryRule => u8::from((12..16).contains(&step)),
    }
}

fn render(
    template_id: usize,
    context: &str,
    entity: &str,
    relation: &str,
    observed: Option<u8>,
) -> (Option<String>, String) {
    let observation = observed.map(|s| match template_id {
        0 => format!(
            "In {context}, a {entity} has {relation} {}.",
            LABELS[s as usize]
        ),
        1 => format!(
            "A {entity} in {context} carries {relation} {}.",
            LABELS[s as usize]
        ),
        2 => format!(
            "The {relation} {} applies to {context}'s {entity}.",
            LABELS[s as usize]
        ),
        3 => format!(
            "Notice from {context}: {entity} now has {relation} {}.",
            LABELS[s as usize]
        ),
        4 => format!(
            "For the {entity} at {context}, {relation} reads {}.",
            LABELS[s as usize]
        ),
        5 => format!(
            "Record {context}/{entity}: {relation} is {}.",
            LABELS[s as usize]
        ),
        6 => format!(
            "A report places {entity} in {context} with {relation} {}.",
            LABELS[s as usize]
        ),
        7 => format!(
            "At {context}, the {entity}'s {relation} was set to {}.",
            LABELS[s as usize]
        ),
        _ => format!(
            "Entry for {entity}, area {context}: {relation} equals {}.",
            LABELS[s as usize]
        ),
    });
    let query = match template_id {
        0 => format!("What is the current {relation} of a {entity} in {context}?"),
        1 => format!("For {context}, choose the current {relation} of {entity}."),
        2 => format!("Which {relation} currently applies to {context}'s {entity}?"),
        3 => format!("What {relation} holds now for {entity} at {context}?"),
        4 => format!("Name the present {relation} for the {context} {entity}."),
        5 => format!("Select {entity}'s latest {relation} in {context}."),
        6 => format!("Report the current {relation} of {entity}, area {context}."),
        7 => format!("At {context}, what {relation} does {entity} presently have?"),
        _ => format!("Current {relation} for {entity} in {context}: choose one."),
    };
    (observation, query)
}

pub fn generate(config: &WorldConfig) -> Result<Vec<WorldEvent>, String> {
    if config.events < DEFAULT_EVENTS || config.label_rotation > 2 {
        return Err("events must be at least 32 and label_rotation at most 2".into());
    }
    let split = config.split.index();
    let term_offset = draw(config.world_seed, 0, 11, 4);
    let context_flip = draw(config.world_seed, 0, 12, 2);
    let mut events = Vec::with_capacity(config.events as usize);
    for step in 0..config.events {
        let key_id = (step % 8) as u8;
        let context_id = (key_id % 4) / 2;
        let entity_id = key_id % 2;
        let relation_id = key_id / 4;
        let relation = if relation_id == 0 { "status" } else { "mode" };
        let context = CONTEXTS[split][(context_id as usize + context_flip) % 2];
        let entity = TERMS[split][(entity_id as usize + term_offset) % 4];
        let phase = regime_phase(config.family, step, config.split);
        let key_offset = if config.track == Track::ContextBound {
            (key_id % 4) % 3
        } else {
            0
        };
        let key_offset = key_offset + relation_id;
        let active_phase = if config.track == Track::ContextBound && context_id == 1 {
            0
        } else {
            phase
        };
        let answer = (active_phase + key_offset + config.label_rotation) % 3;
        let world_state = (0..8u8)
            .map(|key| KeyState {
                key_id: key,
                context_id: (key % 4) / 2,
                entity_id: key % 2,
                relation_id: key / 4,
                answer_index: (if config.track == Track::ContextBound && (key % 4) / 2 == 1 {
                    0
                } else {
                    phase
                } + if config.track == Track::ContextBound {
                    (key % 4) % 3
                } else {
                    0
                } + key / 4
                    + config.label_rotation)
                    % 3,
            })
            .collect();

        let visible =
            step % 3 == 0 || (config.family == Family::PoisonBurst && (12..18).contains(&step));
        let false_evidence = match config.family {
            Family::ContradictoryNoise => step % 9 == 0,
            Family::PoisonBurst => (12..18).contains(&step),
            _ => false,
        };
        let observed_answer = if config.family == Family::GradualDrift {
            let adjusted = step.saturating_sub(split as u32);
            let old = (key_offset + config.label_rotation) % 3;
            let new = if config.track == Track::ContextBound && context_id == 1 {
                old
            } else {
                (old + 1) % 3
            };
            if adjusted < 8 {
                old
            } else if adjusted >= 24
                || draw(config.world_seed, step, 13, 16) < (adjusted - 8) as usize
            {
                new
            } else {
                old
            }
        } else if false_evidence {
            (answer + 1) % 3
        } else {
            answer
        };
        let observed = visible.then_some(observed_answer);
        let template = (step as usize + draw(config.world_seed, 0, 14, 3)) % 3;
        let (mut observation, mut query) =
            render(split * 3 + template, context, entity, relation, observed);
        if step % 2 == 0 {
            let modifier = ["The nearby marker is blue.", "The nearby marker is square."]
                [draw(config.world_seed, step, 16, 2)];
            if let Some(text) = &mut observation {
                text.push(' ');
                text.push_str(modifier);
            }
            query.push(' ');
            query.push_str("Ignore the nearby marker.");
        }
        let shift = draw(config.world_seed, step, 15, 3);
        let candidates = std::array::from_fn(|i| LABELS[(i + shift) % 3].to_owned());
        events.push(WorldEvent {
            exposure: Exposure {
                event_id: format!(
                    "{:016x}-{:?}-{:?}-{:?}-r{}-{}",
                    config.world_seed,
                    config.split,
                    config.family,
                    config.track,
                    config.label_rotation,
                    step
                ),
                step,
                key_id,
                context_id,
                entity_id,
                relation_id,
                observation,
                observed_answer_index: observed,
                query,
                candidates,
                template_id: (split * 3 + template) as u8,
            },
            world_state,
            target_index: answer,
            regime_identity: ["A", "B", "C"][phase as usize].into(),
            regime_phase: phase,
            feedback_due_step: config.feedback.due_step(step),
            world_seed: config.world_seed,
            family: config.family,
            track: config.track,
            split: config.split,
            feedback: config.feedback,
            label_rotation: config.label_rotation,
        });
    }
    Ok(events)
}

pub fn qualification_triplet(config: &WorldConfig) -> Result<[Vec<WorldEvent>; 3], String> {
    let mut c = config.clone();
    let mut worlds = Vec::with_capacity(3);
    for rotation in 0..3 {
        c.label_rotation = rotation;
        worlds.push(generate(&c)?);
    }
    Ok(worlds.try_into().expect("exactly three rotations"))
}

use serde::{Deserialize, Serialize};

use fas00::world::{Family, Feedback, KeyState, Track};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QualificationEvent {
    pub event_id: String,
    pub world_id: String,
    pub world_family: Family,
    pub world_seed: u64,
    pub task_structure: Track,
    pub feedback_condition: Feedback,
    pub time_step: u32,
    pub latent_regime_id: String,
    pub latent_regime_phase: u8,
    pub key_id: u8,
    pub context_id: u8,
    pub entity_id: u8,
    pub relation_id: u8,
    pub current_exact_world_state: Vec<KeyState>,
    pub observation_identity: String,
    pub observation_text: Option<String>,
    pub observation_answer_index: Option<u8>,
    pub query_identity: String,
    pub query_text: String,
    pub candidate_identities_in_order: [u8; 3],
    pub candidate_text_in_order: [String; 3],
    pub exact_target: u8,
    pub feedback_reveal_step: u32,
    pub visible_feedback_ids_after_score: Vec<String>,
    pub surface_template_id: u8,
    pub context_term_id: u8,
    pub entity_term_id: u8,
    pub render_seed: u64,
    pub rendered_event_sha256: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorldRecord {
    pub world_id: String,
    pub world_family: Family,
    pub world_seed: u64,
    pub task_structure: Track,
    pub feedback_condition: Feedback,
    pub label_rotation: u8,
    pub event_count: usize,
    pub latent_world_sha256: String,
    pub rendered_events_sha256: String,
    pub baseline_correct: [u32; 5],
    pub baseline_accuracy: [f64; 5],
    pub resource_basis: ResourceBasis,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResourceBasis {
    pub key_count: u32,
    pub possible_current_fact_count: u32,
    pub current_fact_count: u32,
    pub regime_identity_count: u32,
    pub generator_regime_bits: u32,
    pub arbitrary_per_key_state_bits_lower_bound: u32,
    pub arbitrary_per_key_state_bytes_lower_bound: u32,
    pub stream_length: u32,
    pub feedback_event_count_delivered_within_world: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Gate {
    pub gate: String,
    pub status: String,
    pub detail: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LeakageRow {
    pub feature_group: String,
    pub held_out_accuracy: f64,
    pub held_out_balanced_accuracy: f64,
    pub predictions: u64,
    pub partition: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BaselineSummary {
    pub name: String,
    pub accuracy: f64,
    pub predictions: u64,
    pub context_bound_accuracy: Option<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Phase1Status {
    pub project_id: String,
    pub phase: String,
    pub qualification_world_count: usize,
    pub scored_event_count: usize,
    pub phase1_ready: bool,
    pub model_contact_authorized: bool,
    pub model_contact_performed: bool,
    pub qualification_corpus_reusable_for_phase5: bool,
    pub gates: Vec<Gate>,
}

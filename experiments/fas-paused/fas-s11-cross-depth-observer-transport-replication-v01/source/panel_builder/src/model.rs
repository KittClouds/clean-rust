use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorldFact {
    pub canonical_context_id: String,
    pub canonical_entity_id: String,
    pub relation_id: u8,
    pub state_id: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CandidateSemantic {
    pub candidate_identity: u8,
    pub state_id: u8,
    pub surface: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExactWorldState {
    pub canonical_context_id: String,
    pub canonical_entity_id: String,
    pub relation_id: u8,
    pub state_id: u8,
    pub target_candidate_identity: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LatentWorld {
    pub regime_id: u8,
    pub regime_name: String,
    pub time_step: u32,
    pub feedback_marker: String,
    pub facts: Vec<WorldFact>,
    pub candidate_semantics: Vec<CandidateSemantic>,
    pub current_exact_world_state: ExactWorldState,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QuerySemantics {
    pub canonical_context_id: String,
    pub canonical_entity_id: String,
    pub relation_id: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Event {
    pub event_id: String,
    pub variant_id: String,
    pub changed_factor: String,
    pub context_term_id: u8,
    pub context_term: String,
    pub entity_term_id: u8,
    pub entity_term: String,
    pub context_term_split: String,
    pub entity_term_split: String,
    pub observation_template_id: u8,
    pub query_template_id: u8,
    pub observation_text: String,
    pub query_text: String,
    pub input_text: String,
    pub query_semantics: QuerySemantics,
    pub candidate_identity_order: Vec<u8>,
    pub candidate_text_order: Vec<String>,
    pub target_candidate_identity: u8,
    pub exact_target: u8,
    pub input_sha256: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Quartet {
    pub ordinal: u64,
    pub world_id: String,
    pub episode_id: String,
    pub quartet_id: String,
    pub track_id: String,
    pub context_split: u8,
    pub entity_split: u8,
    pub context_term_split: String,
    pub entity_term_split: String,
    pub context_pair_id: Option<u8>,
    pub entity_pair_id: Option<u8>,
    pub world_family_id: u8,
    pub world_family: String,
    pub relation_id: u8,
    pub relation_surface: String,
    pub state_id: u8,
    pub state_surface: String,
    pub observation_template_id: u8,
    pub query_template_id: u8,
    pub candidate_order_index: u8,
    pub generator_seed: u64,
    pub render_seed: u64,
    pub latent_world: LatentWorld,
    pub target_candidate_identity: u8,
    pub exact_target: u8,
    pub candidate_identity_order: Vec<u8>,
    pub variants: Vec<Event>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PanelEventRow {
    pub ordinal: u64,
    pub world_id: String,
    pub episode_id: String,
    pub quartet_id: String,
    pub world_family_id: u8,
    pub track_id: String,
    pub context_split: u8,
    pub entity_split: u8,
    pub latent_regime_id: u8,
    pub canonical_context_id: String,
    pub canonical_entity_id: String,
    pub context_term_id: u8,
    pub context_term: String,
    pub entity_term_id: u8,
    pub entity_term: String,
    pub observation_template_id: u8,
    pub query_template_id: u8,
    pub state_id: u8,
    pub event_id: String,
    pub variant_id: String,
    pub exact_target: u8,
    pub target_candidate_identity: u8,
    pub candidate_identity_order: Vec<u8>,
    pub candidate_text_order: Vec<String>,
    pub query_semantics: QuerySemantics,
    pub current_exact_world_state: ExactWorldState,
    pub time_step: u32,
    pub feedback_marker: String,
    pub feedback_reveal_step: Option<u32>,
    pub render_seed: u64,
    pub input_text: String,
    pub input_sha256: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CandidateLedgerRow {
    pub ordinal: u64,
    pub track_id: String,
    pub context_split: u8,
    pub entity_split: u8,
    pub world_family_id: u8,
    pub relation_id: u8,
    pub state_id: u8,
    pub observation_template_id: u8,
    pub query_template_id: u8,
    pub context_pair_id: Option<u8>,
    pub entity_pair_id: Option<u8>,
    pub candidate_order_index: u8,
    pub target_class: u8,
    pub canonical_candidate_key: String,
    pub selection_sha256: String,
    pub identity_fresh: bool,
    pub input_hashes_fresh: bool,
    pub selected: bool,
    pub disposition: String,
    pub quartet_payload_sha256: String,
    pub world_identity_sha256: String,
    pub episode_identity_sha256: String,
    pub quartet_identity_sha256: String,
    pub event_identity_sha256: Vec<String>,
    pub rendered_input_sha256: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TermInventory {
    pub inventory_id: String,
    pub generator_seed: u64,
    pub context_terms: Vec<String>,
    pub entity_terms: Vec<String>,
    pub train_side_style_ids: Vec<u8>,
    pub novel_heldout_ids: Vec<u8>,
}

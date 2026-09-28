use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
    pub occurrence: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CharacterSpans {
    pub context: Vec<Span>,
    pub entity: Vec<Span>,
    pub relation: Vec<Span>,
    pub state_in_observation: Vec<Span>,
    pub candidate_options: Vec<Span>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorldFact {
    pub canonical_context_id: String,
    pub canonical_entity_id: String,
    pub relation_id: u8,
    pub state_id: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CandidateSemantic {
    pub candidate_identity: u8,
    pub state_id: u8,
    pub surface: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExactWorldState {
    pub canonical_context_id: String,
    pub canonical_entity_id: String,
    pub relation_id: u8,
    pub state_id: u8,
    pub target_candidate_identity: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LatentWorld {
    pub world_family: String,
    pub world_family_id: u8,
    pub time_step: u32,
    pub feedback_marker: String,
    pub facts: Vec<WorldFact>,
    pub candidate_semantics: Vec<CandidateSemantic>,
    pub current_exact_world_state: ExactWorldState,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct QuerySemantics {
    pub canonical_context_id: String,
    pub canonical_entity_id: String,
    pub relation_id: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Variant {
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
    pub observation_template_role: String,
    pub query_template_role: String,
    pub observation_text: String,
    pub query_text: String,
    pub input_text: String,
    pub query_semantics: QuerySemantics,
    pub candidate_identity_order: Vec<u8>,
    pub candidate_text_order: Vec<String>,
    pub target_candidate_identity: u8,
    pub exact_target: u8,
    pub character_spans: CharacterSpans,
    pub input_sha256: String,
    pub rendered_event_sha256: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Quartet {
    pub quartet_id: String,
    pub track_id: String,
    pub replicate_id: u8,
    pub context_pair_id: u8,
    pub entity_pair_id: u8,
    pub context_term_split: String,
    pub entity_term_split: String,
    pub world_family: String,
    pub world_family_id: u8,
    pub relation_id: u8,
    pub relation_surface: String,
    pub state_id: u8,
    pub state_surface: String,
    pub observation_template_id: u8,
    pub query_template_id: u8,
    pub generator_seed: u64,
    pub render_seed: u64,
    pub time_step: u32,
    pub feedback_marker: String,
    pub latent_world: LatentWorld,
    pub latent_world_sha256: String,
    pub target_candidate_identity: u8,
    pub exact_target: u8,
    pub candidate_identity_order: Vec<u8>,
    pub variants: Vec<Variant>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct TermInventory {
    pub inventory_id: String,
    pub generator_seed: u64,
    pub context_terms: Vec<String>,
    pub entity_terms: Vec<String>,
    pub train_side_style_ids: Vec<u8>,
    pub novel_heldout_ids: Vec<u8>,
}

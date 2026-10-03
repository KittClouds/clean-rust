use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Serialize, Eq, PartialEq)]
pub struct SemanticQuartet {
    pub schedule_ordinal: u64,
    pub track_code: u8,
    pub context_split: u8,
    pub entity_split: u8,
    pub family_id: u8,
    pub relation_id: u8,
    pub state_id: u8,
    pub context_pair_id: u8,
    pub entity_pair_id: u8,
}

#[derive(Clone, Copy, Debug, Serialize, Eq, PartialEq)]
pub struct RenderChoice {
    pub observation_id: u8,
    pub query_id: u8,
    pub candidate_order_id: u8,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct ModelInputRow {
    pub row_id: String,
    pub quartet_id: String,
    pub variant_id: String,
    pub input_text: String,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct RowManifestEntry {
    pub row_index: u64,
    pub row_id: String,
    pub quartet_id: String,
    pub variant_id: String,
    pub surface_id: String,
    pub truth_partition: String,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct FitEligibility {
    #[serde(rename = "CONTEXT_IDENTITY")]
    pub context_identity: bool,
    #[serde(rename = "ENTITY_IDENTITY")]
    pub entity_identity: bool,
    #[serde(rename = "RELATION_IDENTITY")]
    pub relation_identity: bool,
    #[serde(rename = "OBSERVED_STATE")]
    pub observed_state: bool,
    #[serde(rename = "EXACT_TARGET")]
    pub exact_target: bool,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct TerminalLabel {
    pub row_id: String,
    pub quartet_id: String,
    pub variant_id: String,
    pub context_term_id: u8,
    pub entity_term_id: u8,
    pub relation_id: u8,
    pub state_id: u8,
    pub exact_target: u8,
    pub target_candidate_identity: u8,
    pub candidate_identity_order: [u8; 3],
    pub both_terms_train_side: bool,
    pub fit_eligibility: FitEligibility,
    pub score_strata: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub joint_template_lexical: Option<bool>,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct GeneratedRow {
    pub input: ModelInputRow,
    pub manifest: RowManifestEntry,
    pub label: TerminalLabel,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct GeneratedQuartet {
    pub quartet_id: String,
    pub semantic: SemanticQuartet,
    pub candidate_counter: u64,
    pub primary_choice: RenderChoice,
    pub heldout_choice: RenderChoice,
    pub primary_rows: [GeneratedRow; 4],
    pub heldout_rows: [GeneratedRow; 4],
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, Eq, PartialEq)]
pub struct PrimarySupport {
    pub context_identity: [u64; 32],
    pub entity_identity: [u64; 32],
    pub relation: [u64; 2],
    pub observed_state: [u64; 3],
    pub exact_target_by_stratum: [[u64; 3]; 4],
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct CollisionSkip {
    pub schedule_ordinal: u64,
    pub candidate_counter: u64,
    pub collision_classes: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct FileReceipt {
    pub artifact_id: String,
    pub path: String,
    pub byte_length: u64,
    pub sha256: String,
    pub row_count: u64,
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct PopulationReceipt {
    pub receipt_id: String,
    pub status: String,
    pub contract_seal_root_sha256: Option<String>,
    pub authorization_id: Option<String>,
    pub output_root: Option<String>,
    pub population_rows_written: bool,
    pub e1_root_sha256: String,
    pub e1_input_sha256: String,
    pub e1_row_manifest_sha256: String,
    pub e1_term_inventory_sha256: String,
    pub heldout_template_manifest_sha256: String,
    pub population_namespace: String,
    pub world_render_seed_u64: u64,
    pub selected_whole_quartet_prefix: u64,
    pub shared_candidate_counter_sum: u64,
    pub maximum_candidate_counter: u64,
    pub selected_primary_support: PrimarySupport,
    pub previous_prefix_minimum_class_count: u64,
    pub primary_rows: u64,
    pub heldout_template_rows: u64,
    pub unique_feature_rows: u64,
    pub row_order: String,
    pub input_schema: String,
    pub row_manifest_schema: String,
    pub terminal_label_schema: String,
    pub escrow_label_schema: String,
    pub template_truth_opened: bool,
    pub template_joint_support_emitted: bool,
    pub predictions_emitted: bool,
    pub tokenizer_contacted: bool,
    pub model_contacted: bool,
    pub cuda_initialized: bool,
    pub files: Vec<FileReceipt>,
    pub collision_skips: Vec<CollisionSkip>,
}

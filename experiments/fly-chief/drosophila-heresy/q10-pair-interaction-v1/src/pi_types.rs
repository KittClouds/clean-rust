use serde::{Deserialize, Serialize};

pub const SIGNED_STEPS: [i8; 10] = [-1, 1, -2, 2, -4, 4, -8, 8, -16, 16];
pub const FINAL_RESERVE: u32 = 16;
pub const NORMALIZATION_FLOOR: f64 = 1.0e-12;
pub const SHARED_PAIRS_PER_EVENT: usize = 64;
pub const DISJOINT_PAIRS_PER_EVENT: usize = 32;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ReplayFixtureEvent {
    pub event_key: String,
    pub seed: u64,
    pub side: String,
    pub tau: f32,
    pub trial: usize,
    pub row_coordinate_ids: Vec<Vec<u32>>,
    pub initial_committed_bits: Vec<u32>,
    pub baseline_readout_bits: Vec<u32>,
    pub baseline_readout_l2: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ReplayFixtureFile {
    pub protocol: String,
    pub schema_version: u32,
    pub events: Vec<ReplayFixtureEvent>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct OverlayFixtureEvent {
    pub event_key: String,
    pub target_committed_bits: Vec<u32>,
    pub target_readout_bits: Vec<u32>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct OverlayFixtureFile {
    pub protocol: String,
    pub schema_version: u32,
    pub events: Vec<OverlayFixtureEvent>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct RowSupport {
    pub row: u32,
    pub union_position: u32,
    pub positions_a: Vec<u16>,
    pub positions_b: Vec<u16>,
    pub position_distance: Option<u16>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct RowBits {
    pub row: u32,
    pub union_position: u32,
    pub readout_bits: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct InteractionValue {
    pub row: u32,
    pub union_position: u32,
    pub value_bits: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct EndpointMap {
    pub signed_step: i8,
    pub replacement_bits: u32,
    pub changed_readout: Vec<RowBits>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CandidateMap {
    pub signed_steps: [i8; 2],
    pub replacement_bits: [u32; 2],
    pub joint_changed_readout: Vec<RowBits>,
    pub interaction_sparse: Vec<InteractionValue>,
    pub interaction_norm: f64,
    pub interaction_norm_normalized: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct PairMap {
    pub category: String,
    pub coordinate_a: u32,
    pub coordinate_b: u32,
    pub shared_row_count: usize,
    pub union_row_count: usize,
    pub support: Vec<RowSupport>,
    pub single_a: Vec<EndpointMap>,
    pub single_b: Vec<EndpointMap>,
    pub candidates: Vec<CandidateMap>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct EventMap {
    pub event_key: String,
    pub seed: u64,
    pub side: String,
    pub tau: f32,
    pub trial: usize,
    pub fixture_event_key: String,
    pub baseline_readout_l2: f64,
    pub pair_count: usize,
    pub shared_pair_count: usize,
    pub disjoint_pair_count: usize,
    pub selected_distinct_coordinate_count: usize,
    pub selected_distinct_row_count: usize,
    pub pairs: Vec<PairMap>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct EventFailure {
    pub event_key: String,
    pub seed: u64,
    pub side: String,
    pub tau: f32,
    pub trial: usize,
    pub status: String,
    pub parent_status: Option<String>,
    pub baseline_readout_l2: Option<f64>,
    pub reason: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct PairMapFile {
    pub protocol: String,
    pub schema_version: u32,
    pub normalization_floor: f64,
    pub signed_steps: Vec<i8>,
    pub fixture_sha256: String,
    pub events: Vec<EventMap>,
    pub failures: Vec<EventFailure>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct OverlayCandidate {
    pub pair_index: usize,
    pub candidate_index: usize,
    pub signed_steps: [i8; 2],
    pub interaction_cosine_with_negative_error: f64,
    pub additive_error_norm: f64,
    pub actual_joint_error_norm: f64,
    pub actual_joint_bitwise_mismatch_count: usize,
    pub pareto_improvement_vs_baseline: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct OverlayEvent {
    pub event_key: String,
    pub baseline_error_norm: f64,
    pub baseline_bitwise_mismatch_count: usize,
    pub candidates: Vec<OverlayCandidate>,
}

#[derive(Clone, Debug)]
pub struct MapInput<'a> {
    pub fixture: &'a ReplayFixtureEvent,
    pub eligible_coordinates: &'a [usize],
    pub shared_pair_count: usize,
    pub disjoint_pair_count: usize,
}

#[derive(Clone, Debug)]
pub struct OverlayInput<'a> {
    pub map: &'a EventMap,
    pub fixture: &'a ReplayFixtureEvent,
    pub target_readout_bits: &'a [u32],
}

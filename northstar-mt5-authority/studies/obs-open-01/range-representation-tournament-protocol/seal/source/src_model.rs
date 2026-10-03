use serde::{Deserialize, Serialize};

pub const AUTHORITY: &str = "OBS_OPEN_03BP_FROZEN_RANGE_REPRESENTATION_TOURNAMENT_V1";
pub const FUTURE_PROTOCOL_ROOT: &str =
    "3d1da3657154d5a4e11eca99cab021c71c9c8a5d6d4458469133f3d2b8e3a402";
pub const ATLAS_ROOT: &str = "5f6ee8f323cbddfb91589e31b442c9972a23f1a4dd6146bc74b4667b98908eae";
pub const ANATOMY_ROOT: &str = "4e95cc034d683d4951db1fa271a6e4efe12df843b013ff66f1e175166859d7d5";
pub const MEAS02_ROOT: &str = "f7abf12d1473a5e1eddc8a7efb84ff7224811eda83ad62ba4fe300a7648ce5ea";
pub const UNIVERSE_ROOT: &str = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235";
pub const D_A_SESSIONS: usize = 154;
pub const D_B_SESSIONS: usize = 103;
pub const D_C_SESSIONS: usize = 69;
pub const RANGE_COUNT: usize = 4_620;
pub const RANGE_PER_SESSION: usize = 30;
pub const TARGET_HORIZON_MINUTES: u16 = 60;
pub const RANDOMIZATIONS: usize = 9_999;
pub const SEED: u64 = 20_260_814;
pub const MIN_RELATIVE_BRIER_SKILL: f64 = 0.02;
pub const D_B_MIN_COMPLETE_SESSIONS: usize = 80;
pub const D_B_MIN_OFFSET_SESSIONS: usize = 20;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub struct RawSnapshot {
    pub width: f64,
    pub open_minus_mid: f64,
    pub high_minus_mid: f64,
    pub low_minus_mid: f64,
    pub close_minus_mid: f64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub struct ZSnapshot {
    pub z_open: f64,
    pub z_high: f64,
    pub z_low: f64,
    pub z_close: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TargetSupportReceipt {
    pub target_id: String,
    pub range_records_seen: usize,
    pub observed_complete_records: usize,
    pub unavailable_records: usize,
    pub complete_sessions: usize,
    pub incomplete_sessions: usize,
    pub values_decoded: usize,
    pub equality_rule: String,
    pub registry_binding: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct CollisionCensus {
    pub representation: String,
    pub objects: usize,
    pub unique_tuples: usize,
    pub collision_groups: usize,
    pub collision_relations: u64,
    pub largest_group: usize,
    pub canonicalization: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct AlgebraAudit {
    pub primary_classification: String,
    pub context_classification: String,
    pub conditional_classification: String,
    pub removed_degrees_of_freedom: Vec<String>,
    pub preserved_degrees_of_freedom: Vec<String>,
    pub raw_to_z: String,
    pub z_to_raw_given_context: String,
    pub synthetic_collision: serde_json::Value,
    pub raw_collision_census: CollisionCensus,
    pub z_collision_census: CollisionCensus,
}

#[derive(Debug, Clone, Serialize)]
pub struct QualificationCase {
    pub case_id: String,
    pub status: String,
    pub receipt: String,
}

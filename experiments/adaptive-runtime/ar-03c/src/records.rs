#[derive(Clone, Debug)]
pub struct QualityRecord {
    pub dataset: u8,
    pub initialization: u8,
    pub stream_seed: u64,
    pub state_step: usize,
    pub anchor_step: usize,
    pub age: usize,
    pub method: String,
    pub mode: String,
    pub candidate_count: usize,
    pub within_variance_v48: f64,
    pub predicted_rmse_v48: f64,
    pub observed_rmse_v48: f64,
    pub sign_error_v48: f64,
    pub cross_block_regret_v48: f64,
    pub selected_regret_v48: f64,
    pub false_authorization_v48: f64,
}

#[derive(Clone, Debug)]
pub struct PanelRecord {
    pub dataset: u8,
    pub initialization: u8,
    pub stream_seed: u64,
    pub state_step: usize,
    pub anchor_step: usize,
    pub age: usize,
    pub method: String,
    pub mode: String,
    pub panel: usize,
    pub utility_rmse: f64,
    pub sign_error: f64,
    pub cross_block_regret: f64,
    pub selected_regret: f64,
    pub false_authorization: f64,
}

#[derive(Clone, Debug)]
pub struct PartitionCostRecord {
    pub dataset: u8,
    pub initialization: u8,
    pub stream_seed: u64,
    pub state_step: usize,
    pub anchor_step: usize,
    pub age: usize,
    pub method: String,
    pub feature_dimensions: usize,
    pub feature_bytes: usize,
    pub feature_ns: u128,
    pub partition_ns: u128,
    pub iterations: usize,
    pub within_sse: f64,
}

#[derive(Clone, Debug)]
pub struct VerifierCostRecord {
    pub dataset: u8,
    pub initialization: u8,
    pub stream_seed: u64,
    pub state_step: usize,
    pub elapsed_ns: u128,
    pub candidate_count: usize,
    pub sample_evaluations: usize,
}

#[derive(Clone, Debug)]
pub struct CostFrontierRecord {
    pub dataset: u8,
    pub initialization: u8,
    pub stream_seed: u64,
    pub anchor_step: usize,
    pub reuse_commits: usize,
    pub quality_readout_step: usize,
    pub method: String,
    pub build_feature_ns: u128,
    pub build_partition_ns: u128,
    pub amortized_proxy_ns: f64,
    pub verifier_ns: u128,
    pub projected_total_ns: f64,
    pub within_variance_v48: f64,
    pub predicted_rmse_v48: f64,
    pub observed_rmse_v48: f64,
    pub sign_error_v48: f64,
    pub cross_block_regret_v48: f64,
    pub selected_regret_v48: f64,
    pub false_authorization_v48: f64,
}

pub const METHODS: [&str; 5] = [
    "balanced_kmeans",
    "warm_start_balanced_kmeans",
    "projected_order_1d",
    "nearest_centroid_quota_repair",
    "hash_placebo_mean",
];

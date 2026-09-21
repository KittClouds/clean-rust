#[derive(Clone, Debug)]
pub struct Context {
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub stream_seed: u64,
    pub state_step: usize,
    pub phase: String,
    pub anchor_step: Option<usize>,
    pub offset_from_anchor: Option<usize>,
    pub partition_age: usize,
    pub candidate_count: usize,
}

#[derive(Clone, Debug)]
pub struct ErrorRecord {
    pub context: Context,
    pub method: String,
    pub evidence_examples: usize,
    pub samples_per_stratum: usize,
    pub within_stratum_variance: f64,
    pub predicted_rmse: f64,
}

#[derive(Clone, Debug)]
pub struct StateMetricRecord {
    pub context: Context,
    pub method: String,
    pub within_stratum_variance: f64,
    pub predicted_rmse_v48: f64,
    pub observed_rmse_v48: f64,
    pub sign_error_rate_v48: f64,
    pub cross_block_regret_v48: f64,
    pub selected_program_regret_v48: f64,
    pub false_authorization_rate_v48: f64,
}

#[derive(Clone, Debug)]
pub struct PanelRecord {
    pub context: Context,
    pub method: String,
    pub panel: usize,
    pub utility_rmse_v48: f64,
    pub sign_error_rate_v48: f64,
    pub cross_block_regret_v48: f64,
    pub selected_program_regret_v48: f64,
    pub false_authorization_v48: bool,
}

#[derive(Clone, Debug)]
pub struct IntegrityRecord {
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub stream_seed: u64,
    pub state_step: usize,
    pub fingerprint: u64,
    pub evaluation_candidate_count: usize,
    pub r2_checkpoint: bool,
    pub r2_state_match: bool,
    pub r2_candidate_count_match: bool,
    pub r2_utility_match: bool,
    pub r2_gradient_partition_match: bool,
}

#[derive(Clone, Debug)]
pub struct SnapshotRecord {
    pub dataset_index: u8,
    pub initialization_index: u8,
    pub stream_seed: u64,
    pub state_step: usize,
    pub parameter_fingerprint: u64,
    pub train_loss: f32,
    pub evaluation_candidate_count: usize,
    pub r2_checkpoint: bool,
}

#[derive(Clone, Debug)]
pub struct SummaryRecord {
    pub level: String,
    pub dataset_index: Option<u8>,
    pub initialization_index: Option<u8>,
    pub phase: String,
    pub state_step: usize,
    pub anchor_step: Option<usize>,
    pub offset_from_anchor: Option<usize>,
    pub partition_age: usize,
    pub method: String,
    pub evidence_examples: usize,
    pub n_aggregation_units: usize,
    pub within_stratum_variance: f64,
    pub predicted_rmse: f64,
    pub observed_rmse_v48: Option<f64>,
    pub sign_error_rate_v48: Option<f64>,
    pub cross_block_regret_v48: Option<f64>,
    pub selected_program_regret_v48: Option<f64>,
    pub false_authorization_rate_v48: Option<f64>,
}

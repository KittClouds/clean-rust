use northstar_rl_core::Digest;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

pub const ALPHA_DATA_AUTHORITY_V1: &str = "ALPHA_DATA_AUTHORITY_V1";
pub const ALPHA_CORPUS_MANIFEST_V1: &str = "ALPHA_CORPUS_MANIFEST_V1";
pub const ALPHA_PARTITION_TAPE_V1: &str = "ALPHA_PARTITION_TAPE_V1";
pub const EXECUTION_COST_SPEC_V1: &str = "EXECUTION_COST_SPEC_V1";
pub const STRATEGY_CANDIDATE_V1: &str = "STRATEGY_CANDIDATE_V1";
pub const ALPHA_EVALUATION_RECEIPT_V1: &str = "ALPHA_EVALUATION_RECEIPT_V1";
pub const ALPHA_SEARCH_GENEALOGY_V1: &str = "ALPHA_SEARCH_GENEALOGY_V1";
pub const ALPHA_LEADERBOARD_V1: &str = "ALPHA_LEADERBOARD_V1";
pub const MEAN_REVERSION_CAMPAIGN_V1: &str = "MEAN_REVERSION_CAMPAIGN_V1";

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AuthorityState {
    WaitingForFreshData,
    Ready,
}

#[derive(Clone, Copy, Debug, Eq, Hash, JsonSchema, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EvidenceClass {
    FreshAlphaEvidence,
    QualificationOnly,
}

#[derive(Clone, Copy, Debug, Eq, Hash, JsonSchema, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AlphaArtifactKind {
    RawMarket,
    KittDailySwing,
    VolKitt,
    RangeCompression,
    WaynePivot,
}

impl AlphaArtifactKind {
    pub const REQUIRED: [Self; 5] = [
        Self::RawMarket,
        Self::KittDailySwing,
        Self::VolKitt,
        Self::RangeCompression,
        Self::WaynePivot,
    ];
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AlphaCorpusEntry {
    pub artifact_id: Digest,
    pub kind: AlphaArtifactKind,
    pub evidence_class: EvidenceClass,
    pub relative_path: String,
    pub byte_count: u64,
    pub content_hash: Digest,
    pub collected_at_utc: String,
    pub producer_source_hash: Digest,
    pub schema_version: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AlphaCorpusManifest {
    pub schema_version: String,
    pub manifest_id: Digest,
    pub campaign_label: String,
    pub collection_epoch_utc: String,
    pub entries: Vec<AlphaCorpusEntry>,
    pub sealed: bool,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AlphaDataAuthority {
    pub schema_version: String,
    pub authority_id: Digest,
    pub campaign_label: String,
    pub collection_epoch_utc: String,
    pub corpus_root: String,
    pub qualification_root: String,
    pub allowed_evidence_class: EvidenceClass,
    pub required_artifact_kinds: Vec<AlphaArtifactKind>,
    pub forbidden_lineages: Vec<String>,
    pub credential_material_permitted: bool,
    pub state: AuthorityState,
    pub corpus_manifest_id: Option<Digest>,
    pub reason_code: String,
}

#[derive(Clone, Copy, Debug, Eq, Hash, JsonSchema, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum StrategyFamily {
    MeanReversion,
    MarketOpen1630,
    TrendFollowing,
    Volume,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct StrategyFamilyRegistration {
    pub ordinal: u8,
    pub family: StrategyFamily,
    pub frozen_label: String,
    pub state: String,
}

pub fn family_registry() -> Vec<StrategyFamilyRegistration> {
    [
        (1, StrategyFamily::MeanReversion, "MEAN REVERSION", "ACTIVE"),
        (2, StrategyFamily::MarketOpen1630, "MARKET OPEN 1630", "QUEUED"),
        (3, StrategyFamily::TrendFollowing, "TREND FOLLOWING", "QUEUED"),
        (4, StrategyFamily::Volume, "VOLUME", "QUEUED"),
    ]
    .into_iter()
    .map(|(ordinal, family, label, state)| StrategyFamilyRegistration {
        ordinal,
        family,
        frozen_label: label.into(),
        state: state.into(),
    })
    .collect()
}

#[derive(Clone, Copy, Debug, Eq, Hash, JsonSchema, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AlphaPartitionRole {
    Discovery,
    Validation,
    Holdout,
    ExcludedEmbargo,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AlphaSessionInput {
    pub session_id: u32,
    pub instrument_id: u32,
    pub group_id: String,
    pub first_row: u64,
    pub last_row: u64,
    pub start_time_ns: i64,
    pub end_time_ns: i64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AlphaPartitionAssignment {
    pub session_id: u32,
    pub instrument_id: u32,
    pub group_id: String,
    pub chronological_ordinal: u64,
    pub role: AlphaPartitionRole,
    pub reason_code: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AlphaPartitionTape {
    pub schema_version: String,
    pub partition_tape_id: Digest,
    pub corpus_manifest_id: Digest,
    pub strategy: String,
    pub discovery_groups: usize,
    pub validation_groups: usize,
    pub holdout_groups: usize,
    pub embargo_ns: i64,
    pub assignments: Vec<AlphaPartitionAssignment>,
    pub sealed: bool,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct ExecutionCostSpec {
    pub schema_version: String,
    pub execution_cost_spec_id: Digest,
    pub decision_boundary: String,
    pub fill_boundary: String,
    pub spread_multiplier: f64,
    pub fixed_commission_per_exposure_change: f64,
    pub proportional_commission_bps: f64,
    pub slippage_bps: f64,
    pub unavailable_fill_rule: String,
    pub sizing_rule: String,
    pub overlapping_positions_rule: String,
    pub initial_equity: f64,
    pub periods_per_year: f64,
    pub sharpe_return_sampling: String,
    pub risk_free_rate_per_period: f64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct MeanReversionParameters {
    pub lookback: u32,
    pub entry_z: f64,
    pub exit_z: f64,
    pub max_holding_bars: u32,
    pub target_exposure: f64,
}

#[derive(Clone, Copy, Debug, Eq, JsonSchema, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CandidateStatus {
    Planned,
    Evaluated,
    Killed,
    ValidationSurvivor,
    FrozenStrategy,
    HoldoutResult,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct StrategyCandidate {
    pub schema_version: String,
    pub strategy_id: Digest,
    pub family: StrategyFamily,
    pub parent_strategy_id: Option<Digest>,
    pub version: u32,
    pub feature_root: Digest,
    pub model_policy_root: Digest,
    pub parameters: MeanReversionParameters,
    pub discovery_interval: String,
    pub validation_interval: String,
    pub holdout_interval: String,
    pub objective: String,
    pub random_seed: u64,
    pub execution_contract_root: Digest,
    pub prior_evaluation_exposures: u64,
    pub status: CandidateStatus,
}

#[derive(Clone, Debug, Default, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct EconomicMetrics {
    pub gross_pnl: f64,
    pub net_pnl: f64,
    pub out_of_sample_sharpe: f64,
    pub maximum_drawdown: f64,
    pub return_over_drawdown: f64,
    pub volatility: f64,
    pub trade_count: u64,
    pub turnover: f64,
    pub total_cost: f64,
    pub win_count: u64,
    pub loss_count: u64,
    pub tail_loss_01: f64,
    pub mean_absolute_exposure: f64,
    pub evaluated_bars: u64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AlphaEvaluationReceipt {
    pub schema_version: String,
    pub receipt_id: Digest,
    pub strategy_id: Digest,
    pub role: AlphaPartitionRole,
    pub session_ids: Vec<u32>,
    pub metrics: EconomicMetrics,
    pub semantic_replay_root: Digest,
    pub execution_cost_spec_id: Digest,
    pub knowledge_time_verified: bool,
    pub evidence_class: EvidenceClass,
    pub outcome: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct SearchGenealogyEntry {
    pub evaluation_ordinal: u64,
    pub strategy_id: Digest,
    pub parent_strategy_id: Option<Digest>,
    pub role: AlphaPartitionRole,
    pub result_receipt_id: Digest,
    pub prior_exposure_count: u64,
    pub disposition: String,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct SearchGenealogy {
    pub schema_version: String,
    pub genealogy_id: Digest,
    pub candidate_population_hash: Digest,
    pub entries: Vec<SearchGenealogyEntry>,
    pub failed_candidates_retained: bool,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct LeaderboardRow {
    pub rank: u64,
    pub strategy_id: Digest,
    pub family: StrategyFamily,
    pub status: CandidateStatus,
    pub discovery: EconomicMetrics,
    pub validation: EconomicMetrics,
    pub holdout: Option<EconomicMetrics>,
    pub robustness_penalty: f64,
    pub ranking_score: f64,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct AlphaLeaderboard {
    pub schema_version: String,
    pub leaderboard_id: Digest,
    pub principal_objectives: Vec<String>,
    pub family_order: Vec<StrategyFamily>,
    pub rows: Vec<LeaderboardRow>,
    pub holdout_opened: bool,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct MeanReversionCampaignSpec {
    pub schema_version: String,
    pub campaign_id: Digest,
    pub authority_id: Digest,
    pub corpus_manifest_id: Digest,
    pub partition_tape_id: Digest,
    pub execution_cost_spec_id: Digest,
    pub family: StrategyFamily,
    pub candidate_parameters: Vec<MeanReversionParameters>,
    pub baselines: Vec<String>,
    pub holdout_open_authorized: bool,
    pub root_seed: u64,
    pub implementation_hashes: Vec<Digest>,
}

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct CampaignRunOutput {
    pub campaign: MeanReversionCampaignSpec,
    pub partition: AlphaPartitionTape,
    pub candidates: Vec<StrategyCandidate>,
    pub receipts: Vec<AlphaEvaluationReceipt>,
    pub genealogy: SearchGenealogy,
    pub leaderboard: AlphaLeaderboard,
    pub run_root: Digest,
}

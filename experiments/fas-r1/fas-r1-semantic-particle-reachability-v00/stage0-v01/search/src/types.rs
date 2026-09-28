use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Arm {
    Depth,
    SampledDepth,
    RandomWidth,
    LearnedWidth,
    MergedWidth,
    CanonicalMerge,
    Particle,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProposalMode {
    GreedyLearnedStub,
    SampledLearnedStub,
    UniformRandomStub,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SelectorMode {
    QTerminalStub,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RunConfig {
    pub arm: Arm,
    pub budget: u64,
    pub width: u16,
    pub seed: u64,
    pub latent_dim: u16,
    pub resample_period: u64,
    pub minimum_particle_budget: u64,
    pub selector_mode: SelectorMode,
}

impl RunConfig {
    pub fn new(arm: Arm, budget: u64, width: u16, seed: u64) -> Self {
        Self {
            arm,
            budget,
            width,
            seed,
            latent_dim: 128,
            resample_period: 8,
            minimum_particle_budget: 1,
            selector_mode: SelectorMode::QTerminalStub,
        }
    }

    pub fn proposal_mode(&self) -> ProposalMode {
        match self.arm {
            Arm::Depth => ProposalMode::GreedyLearnedStub,
            Arm::RandomWidth => ProposalMode::UniformRandomStub,
            Arm::SampledDepth
            | Arm::LearnedWidth
            | Arm::MergedWidth
            | Arm::CanonicalMerge
            | Arm::Particle => ProposalMode::SampledLearnedStub,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct InitialParticle {
    pub particle_id: u32,
    pub ancestry_id: u64,
    pub assignment: Vec<u8>,
    pub canonical_key: Vec<u8>,
    pub latent_state: Vec<f32>,
    pub rng_state: u64,
    pub q_terminal: f32,
    pub v_reach: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TraceHeader {
    pub schema: String,
    pub trace_id: String,
    pub task_id: String,
    pub family_id: String,
    pub config: RunConfig,
    pub proposal_mode: ProposalMode,
    pub initial_particles: Vec<InitialParticle>,
    pub initial_costs: OperationCosts,
    pub initial_completion_active_ns: u64,
    pub initial_completion_wall_ns: u64,
    pub canonical_merge_public: bool,
    pub public_symmetry_group_size: u64,
    pub timing_kind: String,
    pub timing_granularity: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Edit {
    pub entity: u16,
    pub new_role: u8,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct OperationCosts {
    pub proposal_calls: u64,
    pub logits_scored: u64,
    pub value_calls: u64,
    pub encoder_forward_calls: u64,
    pub encoder_tokens: u64,
    pub canonicalization_calls: u64,
    pub hash_probes: u64,
    pub merges: u64,
    pub resampling_ops: u64,
    pub allocation_decisions: u64,
    pub nonnominal_allocation_decisions: u64,
    pub selection_comparisons: u64,
    pub cpu_active_ns: u64,
    pub gpu_active_ns: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct OperationLedger {
    pub expansions: u64,
    pub proposal_calls: u64,
    pub logits_scored: u64,
    pub value_calls: u64,
    pub encoder_forward_calls: u64,
    pub encoder_tokens: u64,
    pub canonicalization_calls: u64,
    pub hash_probes: u64,
    pub merges: u64,
    pub resampling_ops: u64,
    pub allocation_decisions: u64,
    pub nonnominal_allocation_decisions: u64,
    pub selection_comparisons: u64,
    pub cpu_active_ns: u64,
    pub gpu_active_ns: u64,
    pub end_to_end_wall_ns: u64,
    pub redirected_future_expansions: u64,
    pub peak_live_particles: u32,
    pub trace_bytes_estimate: u64,
}

impl OperationLedger {
    pub(crate) fn charge(&mut self, costs: &OperationCosts) {
        self.expansions += 1;
        self.proposal_calls += costs.proposal_calls;
        self.logits_scored += costs.logits_scored;
        self.value_calls += costs.value_calls;
        self.encoder_forward_calls += costs.encoder_forward_calls;
        self.encoder_tokens += costs.encoder_tokens;
        self.canonicalization_calls += costs.canonicalization_calls;
        self.hash_probes += costs.hash_probes;
        self.merges += costs.merges;
        self.resampling_ops += costs.resampling_ops;
        self.allocation_decisions += costs.allocation_decisions;
        self.nonnominal_allocation_decisions += costs.nonnominal_allocation_decisions;
        self.selection_comparisons += costs.selection_comparisons;
        self.cpu_active_ns += costs.cpu_active_ns;
        self.gpu_active_ns += costs.gpu_active_ns;
    }

    pub(crate) fn charge_initial(&mut self, costs: &OperationCosts) {
        self.value_calls += costs.value_calls;
        self.canonicalization_calls += costs.canonicalization_calls;
        self.hash_probes += costs.hash_probes;
        self.selection_comparisons += costs.selection_comparisons;
        self.cpu_active_ns += costs.cpu_active_ns;
        self.gpu_active_ns += costs.gpu_active_ns;
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TraceEvent {
    pub event_index: u64,
    pub global_expansion_index: u64,
    pub particle_id: u32,
    pub nominal_slot_particle_id: u32,
    pub nominal_slot_redirected: bool,
    pub value_allocation_non_nominal: bool,
    pub parent_particle_id: Option<u32>,
    pub parent_event_index: Option<u64>,
    pub ancestry_id: u64,
    pub particle_depth: u32,
    pub assignment_before: Vec<u8>,
    pub assignment_after: Vec<u8>,
    pub canonical_key: Option<Vec<u8>>,
    pub latent_state_before: Vec<f32>,
    pub latent_state_after: Vec<f32>,
    pub edit: Option<Edit>,
    pub log_probability: f32,
    pub v_reach: f32,
    pub q_terminal: f32,
    pub remaining_budget: u64,
    pub selected: bool,
    pub resampled: bool,
    pub resampling: Option<ResamplingRecord>,
    pub raw_duplicate_detected: bool,
    pub canonical_duplicate_detected: bool,
    pub full_dynamic_duplicate: bool,
    pub raw_merge: bool,
    pub canonical_merge: bool,
    pub merge_representative_event: Option<u64>,
    pub merge_representative_initial_particle: Option<u32>,
    pub merge_representative_ancestry_id: Option<u64>,
    pub representative_value: Option<f32>,
    pub merge_ancestry_ids: Option<Vec<u64>>,
    pub merge_representative_latent_state: Option<Vec<f32>>,
    pub merge_latent_divergence_l2: Option<f32>,
    pub rng_state_before: u64,
    pub rng_state_after: u64,
    pub costs: OperationCosts,
    pub cumulative_active_ns: u64,
    pub cumulative_wall_ns: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ResamplingRecord {
    pub source_particle_id: u32,
    pub retired_particle_id: Option<u32>,
    pub spawned_particle_id: u32,
    pub spawned_ancestry_id: u64,
    pub spawned_parent_event: Option<u64>,
    pub spawned_assignment: Vec<u8>,
    pub spawned_latent_state: Vec<f32>,
    pub spawned_rng_state: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RunTrace {
    pub header: TraceHeader,
    pub events: Vec<TraceEvent>,
    pub ledger: OperationLedger,
    /// `None` selects one of the initial assignments, whose particle ID is
    /// recorded in `selected_initial_particle`.
    pub selected_event: Option<u64>,
    pub selected_initial_particle: Option<u32>,
    pub selected_q_terminal: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PosthocEventLabel {
    pub event_index: u64,
    pub valid: bool,
    pub canonical_solution_class: Option<Vec<u8>>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PosthocSidecar {
    pub schema: String,
    pub trace_id: String,
    pub task_id: String,
    pub initial_valid: bool,
    pub initial_canonical_solution_class: Option<Vec<u8>>,
    pub events: Vec<PosthocEventLabel>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrefixBudget {
    Expansions(u64),
    ActiveNs(u64),
    WallNs(u64),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PrefixMetrics {
    pub prefix: PrefixBudgetRecord,
    pub completed_expansions: u64,
    pub reachability_including_initial: bool,
    pub reachability_excluding_initial: bool,
    pub selected_state_valid: bool,
    pub selected_event: Option<u64>,
    pub selected_initial_particle: Option<u32>,
    pub distinct_valid_classes_reached: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "limit", rename_all = "snake_case")]
pub enum PrefixBudgetRecord {
    Expansions(u64),
    ActiveNs(u64),
    WallNs(u64),
}

impl From<PrefixBudget> for PrefixBudgetRecord {
    fn from(value: PrefixBudget) -> Self {
        match value {
            PrefixBudget::Expansions(v) => Self::Expansions(v),
            PrefixBudget::ActiveNs(v) => Self::ActiveNs(v),
            PrefixBudget::WallNs(v) => Self::WallNs(v),
        }
    }
}

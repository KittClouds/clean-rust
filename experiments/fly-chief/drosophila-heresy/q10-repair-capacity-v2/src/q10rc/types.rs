use crate::q10;
use serde::Serialize;

pub(crate) const FLAG_ZERO_CAPACITY: u8 = 1;
pub(crate) const FLAG_ONE_SIDED: u8 = 2;
pub(crate) const FLAG_NO_HELPFUL: u8 = 4;

#[derive(Clone, Serialize)]
pub(crate) struct BaselineReceipt {
    pub rows: usize,
    pub bitwise_mismatch_count: usize,
    pub signed_zero_mismatch_count: usize,
    pub error_l2: f64,
    pub error_linf: f64,
    pub alternate_bits: Vec<u32>,
    pub true_bits: Vec<u32>,
    pub error: Vec<f64>,
    pub ulp_distance: Vec<u64>,
}

#[derive(Clone, Serialize)]
pub(crate) struct MoveBankReceipt {
    pub candidate_moves: usize,
    pub legal_moves: usize,
    pub illegal_non_adjacent: usize,
    pub illegal_nonfinite_or_bounds: usize,
    pub illegal_boundary: usize,
    pub illegal_reserve: usize,
    pub zero_effect_moves: usize,
    pub active_moves: usize,
    pub numerical_nonzero_moves: usize,
    pub minus_legal: usize,
    pub plus_legal: usize,
    pub move_digest_sha256: String,
    pub minimum_remaining_down_steps_capped: u32,
    pub minimum_remaining_up_steps_capped: u32,
}

#[derive(Clone, Serialize)]
pub(crate) struct RankProjectionReceipt {
    pub row_count: usize,
    pub active_columns: usize,
    pub rank: usize,
    pub rank_fraction: f64,
    pub rank_threshold: f64,
    pub singular_values: Vec<f64>,
    pub smallest_retained: Option<f64>,
    pub largest_discarded: Option<f64>,
    pub condition_number: Option<f64>,
    pub reachable_l2: f64,
    pub reachable_linf: f64,
    pub unreachable_l2: f64,
    pub unreachable_linf: f64,
    pub rho_2: f64,
    pub rho_inf: f64,
    pub max_column_unreachable_inner_product: f64,
    pub normalized_projection_reconstruction_error: f64,
    pub normalized_projection_orthogonality_error: f64,
}

#[derive(Clone, Serialize)]
pub(crate) struct RelaxedBudgetReceipt {
    pub l1: f64,
    pub l2: f64,
    pub linf: f64,
    pub coefficients_above_floor: usize,
    pub coefficient_fraction_above_floor: f64,
    pub ceil_l1_one_ulp_equivalent_scale: f64,
    pub reconstructed_residual_l2: f64,
    pub reconstructed_residual_linf: f64,
    pub normalized_reconstruction_error: f64,
}

#[derive(Clone, Serialize)]
pub(crate) struct RowReceipts {
    pub cue: Vec<u16>,
    pub mbon: Vec<u16>,
    pub source_coordinates: Vec<u32>,
    pub permitted_coordinates: Vec<u32>,
    pub variable_coordinates: Vec<u32>,
    pub legal_minus: Vec<u32>,
    pub legal_plus: Vec<u32>,
    pub nonzero_minus: Vec<u32>,
    pub nonzero_plus: Vec<u32>,
    pub positive_effects: Vec<u32>,
    pub negative_effects: Vec<u32>,
    pub bitwise_zero_effects: Vec<u32>,
    pub helpful_effects: Vec<u32>,
    pub harmful_effects: Vec<u32>,
    pub max_abs_single_effect: Vec<f64>,
    pub summed_positive_authority: Vec<f64>,
    pub summed_absolute_negative_authority: Vec<f64>,
    pub best_single_reduction_fraction: Vec<f64>,
    pub flags: Vec<u8>,
}

impl RowReceipts {
    pub fn with_capacity(rows: usize) -> Self {
        Self {
            cue: Vec::with_capacity(rows),
            mbon: Vec::with_capacity(rows),
            source_coordinates: Vec::with_capacity(rows),
            permitted_coordinates: Vec::with_capacity(rows),
            variable_coordinates: Vec::with_capacity(rows),
            legal_minus: Vec::with_capacity(rows),
            legal_plus: Vec::with_capacity(rows),
            nonzero_minus: Vec::with_capacity(rows),
            nonzero_plus: Vec::with_capacity(rows),
            positive_effects: Vec::with_capacity(rows),
            negative_effects: Vec::with_capacity(rows),
            bitwise_zero_effects: Vec::with_capacity(rows),
            helpful_effects: Vec::with_capacity(rows),
            harmful_effects: Vec::with_capacity(rows),
            max_abs_single_effect: Vec::with_capacity(rows),
            summed_positive_authority: Vec::with_capacity(rows),
            summed_absolute_negative_authority: Vec::with_capacity(rows),
            best_single_reduction_fraction: Vec::with_capacity(rows),
            flags: Vec::with_capacity(rows),
        }
    }

    pub fn zero_capacity_count(&self) -> usize {
        self.flags
            .iter()
            .filter(|&&flags| flags & FLAG_ZERO_CAPACITY != 0)
            .count()
    }

    pub fn no_helpful_count(&self) -> usize {
        self.flags
            .iter()
            .filter(|&&flags| flags & FLAG_NO_HELPFUL != 0)
            .count()
    }
}

#[derive(Clone, Serialize)]
pub(crate) struct CollateralReceipt {
    pub max_abs_axis_delta: f64,
    pub max_abs_norm_delta: f64,
    pub mean_abs_axis_delta: f64,
    pub mean_abs_norm_delta: f64,
}

#[derive(Clone, Serialize)]
pub(crate) struct CapacityReceipt {
    pub status: &'static str,
    pub baseline: BaselineReceipt,
    pub move_bank: MoveBankReceipt,
    pub rank_projection: RankProjectionReceipt,
    pub relaxed_budget: Option<RelaxedBudgetReceipt>,
    pub rows: RowReceipts,
    pub collateral: CollateralReceipt,
    pub learner_mutation: bool,
    pub simulation_rng_consumed_by_audit: bool,
    pub repairs_applied: usize,
    pub multi_move_evaluations: usize,
}

#[derive(Clone, Serialize)]
pub(crate) struct StateHashes {
    pub base_sha256: String,
    pub true_sha256: String,
    pub alternate_sha256: Option<String>,
    pub support_sha256: String,
    pub row_order_sha256: String,
}

#[derive(Clone, Serialize)]
pub(crate) struct EventReceipt {
    pub trial: usize,
    pub endpoint_status: &'static str,
    pub state_hashes: StateHashes,
    pub q10_sm_event: q10::Event,
    pub capacity: Option<CapacityReceipt>,
}

#[derive(Clone, Serialize)]
pub(crate) struct BundleHeader {
    pub protocol: &'static str,
    pub schema_version: u32,
    pub seed: u64,
    pub side: String,
    pub tau: f32,
    pub post_len: usize,
    pub drive_rows: usize,
    pub events: usize,
}

#[derive(Default)]
pub(crate) struct StageCounters {
    pub states: usize,
    pub applicable: usize,
    pub dominated: usize,
    pub already_equal: usize,
    pub legal_moves: u64,
    pub active_moves: u64,
    pub zero_capacity_rows: u64,
    pub no_helpful_rows: u64,
    pub rank_sum: u64,
}

impl StageCounters {
    pub fn add(&mut self, event: &EventReceipt) {
        self.states += 1;
        let Some(capacity) = &event.capacity else {
            self.dominated += 1;
            return;
        };
        self.applicable += 1;
        self.already_equal += usize::from(capacity.status == "ALREADY_EQUAL");
        self.legal_moves += capacity.move_bank.legal_moves as u64;
        self.active_moves += capacity.move_bank.active_moves as u64;
        self.zero_capacity_rows += capacity.rows.zero_capacity_count() as u64;
        self.no_helpful_rows += capacity.rows.no_helpful_count() as u64;
        self.rank_sum += capacity.rank_projection.rank as u64;
    }
}

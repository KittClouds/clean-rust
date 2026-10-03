from __future__ import annotations

from dataclasses import dataclass


PHASE11_CONTRACT = "MST_RG2_PHASE11_EMPIRICAL_STRUCTURE_V1"
TARGETS = (
    "reclaim_given_break",
    "initial_acceptance_given_initial_contact",
    "rejection_given_initial_contact",
    "retest_hold_given_retest_contact",
    "transit_given_episode_acceptance",
)

# All values exist by the eligibility landmark. Terminal geometry, excursions,
# dwell, penetration, end region, and outcome receipts are intentionally absent.
NUMERIC_FEATURES = (
    "ordinal",
    "direction",
    "node_width_atr",
    "initial_distance_atr",
    "approach_efficiency",
    "corridor_up_atr",
    "corridor_down_atr",
    "family_count",
    "member_count",
    "developing_count",
    "frozen_count",
    "node_revision",
    "node_age_seconds",
    "corridor_up_level_count",
    "corridor_down_level_count",
    "corridor_up_noise_count",
    "corridor_down_noise_count",
    "start_median_sigma",
    "node_from_median_sigma",
    "node_from_cog_sigma",
    "node_width_sigma",
    "feature_cog_distance_atr",
    "feature_cog_velocity_atr",
    "feature_c3_distance_atr",
    "feature_c3_velocity_atr",
    "feature_lattice_width_atr",
    "feature_poc_distance_atr",
    "feature_vah_distance_atr",
    "feature_val_distance_atr",
    "feature_spread_atr",
    "feature_raw_level_count",
    "feature_noise_level_count",
    "feature_active_node_count",
    "feature_population_count",
    "feature_population_count_delta",
    "feature_price_from_median_atr",
    "feature_price_from_median_sigma",
    "feature_price_from_cog_atr",
    "feature_price_from_cog_sigma",
    "feature_cog_median_gap_atr",
    "feature_cog_median_gap_sigma",
    "feature_regional_cog_velocity_atr",
    "feature_regional_cog_velocity_sigma",
    "feature_regional_median_velocity_atr",
    "feature_regional_median_velocity_sigma",
    "feature_regional_sigma_log_change_per_bar",
    "contributor_count",
    "eligibility_latency_seconds",
    "server_hour_sin",
    "server_hour_cos",
)

CATEGORICAL_FEATURES = (
    "canonical_instrument",
    "start_region",
    "node_region",
    "contributor_families",
    "contributor_producers",
)

GEOMETRY_DIMENSIONS = (
    "canonical_instrument",
    "direction_label",
    "start_region",
    "node_region",
    "attempt_number_bucket",
    "family_count",
    "contributor_families",
    "node_width_bucket",
    "node_age_bucket",
    "sigma_bucket",
    "corridor_bucket",
    "server_time_bucket",
)

CONTINUOUS_GEOMETRY = (
    "target_time_seconds",
    "node_width_atr",
    "initial_distance_atr",
    "approach_efficiency",
    "corridor_up_atr",
    "corridor_down_atr",
    "start_median_sigma",
    "node_from_median_sigma",
    "node_from_cog_sigma",
    "node_width_sigma",
    "feature_cog_velocity_sigma",
    "feature_regional_median_velocity_sigma",
    "feature_regional_sigma_log_change_per_bar",
    "eligibility_latency_seconds",
)


@dataclass(frozen=True)
class ModelGate:
    minimum_analyzable: int = 200
    minimum_positive: int = 50
    minimum_negative: int = 50
    minimum_runs: int = 10
    maximum_missing_feature_share: float = 0.60
    minimum_group_logloss_improvement: float = 0.0
    minimum_forward_logloss_improvement: float = 0.0
    minimum_instrument_transfer_logloss_improvement: float = 0.0


MODEL_GATE = ModelGate()

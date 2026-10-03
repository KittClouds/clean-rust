"""Frozen per-seed Q labels. No pooling of gate components across seeds."""

from __future__ import annotations

from typing import Any


def seed_gate_record(row: dict[str, Any]) -> dict[str, Any]:
    """Classify one seed using only within-seed paired step-120 values."""
    gain = float(row["delta_p_new_low_minus_sham"])
    low_direction = float(row["sham_low_correct_direction"])
    sham_direction = float(row["sham_correct_direction"])
    preservation_overall = float(row["a_old_low_minus_sham"])
    family_deltas = [float(value) for value in row["family_a_old_low_minus_sham"].values()]

    dup_sham_l1 = float(row["dup_sham_l1"])
    dup_matched_l1 = float(row["dup_matched_neutral_l1"])
    low_sham_l1 = float(row["sham_low_sham_l1"])
    low_matched_l1 = float(row["sham_low_matched_neutral_l1"])
    dup_sham_flip = float(row["dup_sham_map_flip_rate"])
    dup_matched_flip = float(row["dup_matched_neutral_map_flip_rate"])
    low_sham_flip = float(row["sham_low_sham_map_flip_rate"])
    low_matched_flip = float(row["sham_low_matched_neutral_map_flip_rate"])

    gain_pass = gain >= 0.020
    direction_pass = low_direction >= 0.99 and low_direction >= sham_direction - 0.01
    locality_pass = (
        dup_sham_l1 > 0.0
        and dup_matched_l1 > 0.0
        and low_sham_l1 <= 0.75 * dup_sham_l1
        and low_matched_l1 <= 0.75 * dup_matched_l1
        and low_sham_flip <= dup_sham_flip + 0.05
        and low_matched_flip <= dup_matched_flip + 0.05
    )
    preservation_pass = (
        preservation_overall >= -0.05
        and all(delta >= -0.10 for delta in family_deltas)
    )
    map_response_pass = (
        float(row["f_new_low_minus_sham"]) >= 0.10
        and float(row["strict_low_minus_sham"]) >= 0.10
    )

    stiff_locality = (
        dup_sham_l1 > 0.0
        and dup_matched_l1 > 0.0
        and abs(low_sham_l1 - dup_sham_l1) / dup_sham_l1 <= 0.10
        and abs(low_matched_l1 - dup_matched_l1) / dup_matched_l1 <= 0.10
        and abs(low_sham_flip - dup_sham_flip) <= 0.05
        and abs(low_matched_flip - dup_matched_flip) <= 0.05
    )
    return {
        "gain_pass": gain_pass,
        "direction_pass": direction_pass,
        "material_locality_advantage_over_dup_pass": locality_pass,
        "preservation_pass": preservation_pass,
        "q_operating_point_seed_pass": gain_pass and direction_pass and locality_pass and preservation_pass,
        "q_stiff_coupling_seed": gain_pass and stiff_locality,
        "q_map_response_seed_pass": map_response_pass,
        "dup_zero_l1_channel_unclassifiable": dup_sham_l1 == 0.0 or dup_matched_l1 == 0.0,
    }


def cohort_labels(seed_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if len(seed_rows) != 3:
        raise ValueError("Q requires exactly three frozen paired seeds")
    records = {seed: seed_gate_record(row) for seed, row in seed_rows.items()}
    return {
        "seed_records": records,
        "tunable_gain_locality_operating_point": sum(
            record["q_operating_point_seed_pass"] for record in records.values()
        ) >= 2,
        "stiff_coupling_pattern": sum(record["q_stiff_coupling_seed"] for record in records.values()) >= 2,
        "meaningful_map_response": sum(record["q_map_response_seed_pass"] for record in records.values()) >= 2,
    }

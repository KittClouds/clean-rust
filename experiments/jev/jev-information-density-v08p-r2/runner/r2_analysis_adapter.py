"""R2-only, fail-closed bridge from the sealed P analysis contract to its helper.

The sealed contract is read-only. This adapter applies only the separately
sealed R2 bootstrap choices and normalizes one unambiguous English persistence
phrase for the existing parser; it does not redefine an estimand or metric.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Mapping, Sequence

import numpy as np


EXPECTED_PERSISTENCE_TEXT = (
    "A continuous-coordinate onset requires the relevant one-sided simultaneous band "
    "to remain beyond zero for three consecutive optimizer-step checkpoints."
)
EXPECTED_FAMILIES = (
    "exposure_control",
    "respiratory_monitoring",
    "salinity_control",
    "vibration_monitoring",
)


def prepare_runtime_contract(contract: Mapping[str, Any], addendum: Mapping[str, Any], helper: Any) -> dict[str, Any]:
    """Resolve omitted implementation details in a copy; never mutate source JSON."""
    rules = contract.get("descriptive_event_time_rules", {})
    if rules.get("persistence") != EXPECTED_PERSISTENCE_TEXT:
        raise ValueError("sealed persistence wording differs from the addendum-bound source")
    declared = addendum.get("bootstrap_implementation", {})
    family_order = tuple(declared.get("family_order", ()))
    if family_order != EXPECTED_FAMILIES:
        raise ValueError("addendum family order differs from the fixed R2 family identity")
    if declared.get("quantile", {}).get("method") != "linear":
        raise ValueError("unsupported or missing R2 quantile method")
    if declared.get("draw_order", "").split(";")[0] != "family-major":
        raise ValueError("R2 draw order is not family-major")
    scope = declared.get("resample_plan_scope", "")
    if "one 10000 x 2000 index plan" not in scope or "reuse it unchanged" not in scope:
        raise ValueError("R2 shared-plan requirement is absent")

    runtime = copy.deepcopy(dict(contract))
    bootstrap = runtime["descriptive_event_time_rules"]["bootstrap"]
    bootstrap["quantile_method"] = "linear"
    bootstrap["family_order"] = list(family_order)
    bootstrap["resample_scope"] = "one shared neighborhood-index plan reused across all seed-arm-coordinate series"
    runtime["descriptive_event_time_rules"]["persistence"] = "3-consecutive-step checkpoints"
    helper.require_unambiguous_bootstrap_contract(runtime)
    spec = helper.event_time_spec(runtime)
    if spec.persistence_steps != 3 or spec.bootstrap_replicates != 10_000 or spec.bootstrap_seed != 2_773_025_982:
        raise ValueError("resolved runtime contract differs from the sealed P/addendum values")
    return runtime


def canonical_panel_order(neighborhood_rows: Sequence[Mapping[str, Any]], family_order: Sequence[str]) -> tuple[list[str], list[str]]:
    """Return canonical family-major neighborhood IDs and labels, rejecting ambiguity."""
    by_family: dict[str, list[str]] = {family: [] for family in family_order}
    seen: set[str] = set()
    for row in neighborhood_rows:
        neighborhood_id = str(row["neighborhood_id"])
        family = str(row["family_id"]).split(":")[-1]
        if neighborhood_id in seen or family not in by_family:
            raise ValueError("duplicate neighborhood or family outside the addendum domain")
        seen.add(neighborhood_id)
        by_family[family].append(neighborhood_id)
    ordered_ids: list[str] = []
    labels: list[str] = []
    for family in family_order:
        block = sorted(by_family[family])
        if len(block) != 500:
            raise ValueError(f"family {family} does not contain exactly 500 panel neighborhoods")
        ordered_ids.extend(block)
        labels.extend([family] * len(block))
    if len(ordered_ids) != 2_000:
        raise ValueError("canonical R2 panel order does not contain 2000 neighborhoods")
    return ordered_ids, labels


def resample_plan(helper: Any, runtime_contract: Mapping[str, Any], family_labels: Sequence[str], addendum: Mapping[str, Any]) -> tuple[np.ndarray, str]:
    """Materialize the one contract-bound plan once for reuse across all series."""
    spec = addendum["bootstrap_implementation"]
    plan = helper.generate_family_stratified_resamples(
        family_labels,
        runtime_contract,
        family_order=spec["family_order"],
        draw_order="family_major",
    )
    if plan.shape != (10_000, 2_000) or plan.dtype != np.int32:
        raise ValueError("shared R2 resample plan has an unexpected shape or dtype")
    helper.validate_stratified_resamples(
        plan,
        family_labels,
        family_order=spec["family_order"],
        expected_replicates=10_000,
    )
    digest = hashlib.sha256(np.asarray(plan, dtype="<i4").tobytes(order="C")).hexdigest()
    return plan, digest


def continuous_analysis(helper: Any, coordinate: str, values: np.ndarray, family_labels: Sequence[str],
                        plan: np.ndarray, runtime_contract: Mapping[str, Any], addendum: Mapping[str, Any]) -> dict[str, Any]:
    """Call the sealed helper using only addendum-explicit execution arguments."""
    settings = addendum["bootstrap_implementation"]
    return helper.continuous_coordinate_analysis(
        coordinate,
        values,
        family_labels,
        plan,
        runtime_contract,
        family_order=settings["family_order"],
        quantile_method=settings["quantile"]["method"],
    )

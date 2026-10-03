"""Executable, data-independent OBS-OPEN-02R2 discovery semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import floor
from typing import Iterable, Mapping, Sequence


LOCATION_IN_ZONE = 1
LOCATION_ABOVE = 2
LOCATION_BELOW = 3
RETURN_EVENTS = frozenset({4, 5, 8, 9})
CROSS_EVENTS = frozenset({10, 11})


@dataclass(frozen=True)
class PathBar:
    epoch: int
    close: float
    location: int
    event: int
    outside_run: int


@dataclass(frozen=True)
class FormalResult:
    template_id: str
    estimand_id: str
    estimate: float | None
    eligible_sessions: int
    raw_p: float | None
    holm_pass: bool
    temporal_status: str
    availability: str = "ELIGIBLE"


def describe_path(bars: Sequence[PathBar]) -> dict[str, object]:
    if not bars:
        return {"availability": "NOT_EVALUABLE", "reason": "NO_ELIGIBLE_PATH"}
    closes = [bar.close for bar in bars]
    first, last = closes[0], closes[-1]
    displacement = last - first
    positive = max(value - first for value in closes)
    negative = min(value - first for value in closes)
    path_length = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    efficiency = displacement / path_length if path_length else 0.0
    if displacement > 0:
        return_distance = positive - abs(displacement)
    elif displacement < 0:
        return_distance = abs(negative) - abs(displacement)
    else:
        return_distance = max(positive, abs(negative))
    outside = [bar.outside_run for bar in bars if bar.location != LOCATION_IN_ZONE]
    first_outside = next((bar for bar in bars if bar.location != LOCATION_IN_ZONE), None)
    return {
        "availability": "ELIGIBLE",
        "duration_bars": len(bars),
        "duration_seconds": bars[-1].epoch + 300 - bars[0].epoch,
        "in_zone_duration": sum(bar.location == LOCATION_IN_ZONE for bar in bars),
        "above_duration": sum(bar.location == LOCATION_ABOVE for bar in bars),
        "below_duration": sum(bar.location == LOCATION_BELOW for bar in bars),
        "outside_duration": max(outside, default=0),
        "first_outside_time": first_outside.epoch if first_outside else None,
        "first_outside_side": (
            1 if first_outside and first_outside.location == LOCATION_ABOVE
            else -1 if first_outside else None
        ),
        "return_count": sum(bar.event in RETURN_EVENTS for bar in bars),
        "cross_through_count": sum(bar.event in CROSS_EVENTS for bar in bars),
        "terminal_location": bars[-1].location,
        "signed_displacement": displacement,
        "positive_excursion": positive,
        "negative_excursion": negative,
        "path_length": path_length,
        "directional_efficiency": efficiency,
        "return_distance": max(0.0, return_distance),
    }


def adjacent_relations(session_id: str, terminal_by_k: Mapping[int, int]) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for k in range(1, 30):
        left, right = terminal_by_k.get(k), terminal_by_k.get(k + 1)
        rows.append({
            "session_id": session_id,
            "from_k": k,
            "to_k": k + 1,
            "availability": "ELIGIBLE" if left is not None and right is not None else "NOT_EVALUABLE",
            "classification_survival": int(left == right) if left is not None and right is not None else None,
            "state_transition": f"{left}->{right}" if left is not None and right is not None else None,
        })
    return tuple(rows)


def contiguous_terminal_spans(terminal_by_k: Mapping[int, int]) -> tuple[tuple[int, int, int], ...]:
    values = sorted((k, value) for k, value in terminal_by_k.items() if 1 <= k <= 30)
    if not values:
        return ()
    spans: list[tuple[int, int, int]] = []
    start = previous_k = values[0][0]
    current_value = values[0][1]
    for k, value in values[1:]:
        if k != previous_k + 1 or value != current_value:
            spans.append((start, previous_k, current_value))
            start, current_value = k, value
        previous_k = k
    spans.append((start, previous_k, current_value))
    return tuple(spans)


def chronological_blocks(session_ids: Sequence[str], block_count: int = 4) -> dict[str, int]:
    ordered = tuple(sorted(session_ids))
    total = len(ordered)
    if total == 0:
        return {}
    return {session_id: min(block_count - 1, floor(block_count * index / total))
            for index, session_id in enumerate(ordered)}


def calendar_month(civil_date: str) -> str:
    date.fromisoformat(civil_date)
    return civil_date[:7]


def leave_one_month_out(
    values: Mapping[str, float],
    month_by_session: Mapping[str, str],
    supported_months: Iterable[str],
) -> dict[str, tuple[float, ...]]:
    ordered = tuple(sorted(values))
    return {
        month: tuple(values[sid] for sid in ordered if month_by_session[sid] != month)
        for month in sorted(supported_months)
    }


def transition(result: FormalResult, support_pass: bool) -> tuple[str, str | None]:
    if result.availability != "ELIGIBLE" or result.estimate is None or result.raw_p is None:
        return "NOT_EVALUABLE", "NOT_EVALUABLE"
    if not support_pass:
        return "INSUFFICIENT_SUPPORT", "INSUFFICIENT_ELIGIBLE_SUPPORT"
    if result.temporal_status == "TEMPORAL_SUPPORT_INSUFFICIENT":
        return "INSUFFICIENT_SUPPORT", "INSUFFICIENT_TEMPORAL_SUPPORT"
    if result.raw_p > 0.05:
        return "DESCRIPTIVE_ONLY", "FAILS_UNADJUSTED_EVIDENCE"
    if not result.holm_pass:
        return "DESCRIPTIVE_ONLY", "FAILS_FAMILYWISE_CORRECTION"
    if result.temporal_status == "TEMPORALLY_UNSTABLE":
        return "TEMPORALLY_UNSTABLE_STRUCTURE", "TEMPORALLY_UNSTABLE"
    if result.temporal_status != "TEMPORALLY_SUPPORTED":
        return "NOT_EVALUABLE", "NOT_EVALUABLE"
    if result.template_id == "WIDTH_DELTA_ADJACENT":
        return "SCALE_DEPENDENT_STRUCTURE", None
    return "RECURRING_STRUCTURE", None


def emit_confirmation_estimand(
    candidate_id: str,
    estimand_id: str,
    template_id: str,
    representation: str,
    session_value_definition: str,
    eligibility_definition: str,
    natural_null: float,
    discovery_estimate: float,
    range_k: int,
    adjacent_to_k: int | None = None,
) -> dict[str, object]:
    if discovery_estimate == 0:
        raise ValueError("promoted candidate must freeze a nonzero direction")
    return {
        "schema": "OBS_OPEN_FUTURE_CONFIRMATION_ESTIMAND_V1",
        "candidate_id": candidate_id,
        "estimand_id": estimand_id,
        "template_id": template_id,
        "range_k": range_k,
        "adjacent_to_k": adjacent_to_k,
        "representation": representation,
        "session_value_definition": session_value_definition,
        "eligibility_definition": eligibility_definition,
        "natural_null": natural_null,
        "discovery_effect_sign": 1 if discovery_estimate > 0 else -1,
        "population": "FROZEN_CONFIRMATION_69",
        "effect_functional": "ARITHMETIC_MEAN",
        "bootstrap_unit": "SESSION",
        "bootstrap_resamples": 2000,
        "bootstrap_seed": 20260814,
        "raw_decision": "TWO_SIDED_P_LE_0_05_AND_SIGN_MATCH",
        "multiplicity": "HOLM_BONFERRONI_ALPHA_0_05_ACROSS_FROZEN_CANDIDATES",
        "minimum_eligible_sessions": 35,
        "minimum_supported_months": 2,
        "minimum_sessions_per_supported_month": 10,
        "require_both_offset_regimes": True,
        "minimum_sessions_per_offset_regime": 10,
        "equivalence_region": None,
        "discovery_reselection": False,
    }

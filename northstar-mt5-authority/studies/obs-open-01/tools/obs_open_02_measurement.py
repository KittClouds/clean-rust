"""Pure, reversible OBS-OPEN-02 measurement primitives.

This module accepts only caller-provided records. It never loads MT5 files or
the real discovery/confirmation populations; the gate's tests use synthetic
records exclusively.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Literal


Availability = Literal[
    "ELIGIBLE",
    "NOT_EVALUABLE",
    "CENSORED",
    "DATA_GAP",
    "UNAVAILABLE",
    "NOT_APPLICABLE",
    "OPEN",
    "FROZEN_UNOPENED",
]


@dataclass(frozen=True)
class RangeRecord:
    session_id: str
    duration_k: int
    freeze_time: str
    knowledge_time: str
    high: float | None
    low: float | None
    availability: Availability = "ELIGIBLE"


@dataclass(frozen=True)
class Event:
    event_type: str
    timestamp: str
    side: str | None = None


def validate_range_identity(record: RangeRecord) -> None:
    if not record.session_id or not 1 <= record.duration_k <= 30:
        raise ValueError("invalid nested range identity")
    if record.availability == "ELIGIBLE":
        if record.high is None or record.low is None:
            raise ValueError("eligible geometry requires both boundaries")
        if not (isfinite(record.high) and isfinite(record.low)):
            raise ValueError("geometry must be finite")
        if record.high < record.low:
            raise ValueError("high must not be below low")


def geometry_view(record: RangeRecord) -> dict[str, object]:
    validate_range_identity(record)
    result: dict[str, object] = {
        "session_id": record.session_id,
        "duration_k": record.duration_k,
        "freeze_time": record.freeze_time,
        "knowledge_time": record.knowledge_time,
        "availability": record.availability,
        "high": record.high,
        "low": record.low,
        "midpoint": None,
        "width": None,
        "relative_geometry": "NOT_EVALUABLE_GEOMETRY",
    }
    if record.availability != "ELIGIBLE":
        return result
    assert record.high is not None and record.low is not None
    midpoint = (record.high + record.low) / 2.0
    width = record.high - record.low
    result["midpoint"] = midpoint
    result["width"] = width
    if width > 0:
        result["relative_geometry"] = "AVAILABLE"
    return result


def range_relative_price(price: float, record: RangeRecord) -> float | None:
    view = geometry_view(record)
    if view["relative_geometry"] != "AVAILABLE":
        return None
    midpoint = float(view["midpoint"])
    width = float(view["width"])
    return (price - midpoint) / (width / 2.0)


def sequence_view(events: Iterable[Event], availability: Availability = "ELIGIBLE") -> dict[str, object]:
    ordered = tuple(events)
    return {
        "availability": availability,
        "event_count": len(ordered),
        "event_types": tuple(event.event_type for event in ordered),
        "event_times": tuple(event.timestamp for event in ordered),
        "event_sides": tuple(event.side for event in ordered),
    }


def adjacent_scale_delta(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    if left["session_id"] != right["session_id"]:
        raise ValueError("cross-session scale relation is not admissible")
    left_k = int(left["duration_k"])
    right_k = int(right["duration_k"])
    if right_k != left_k + 1:
        raise ValueError("adjacent scale relation requires k and k+1")
    left_width = left.get("width")
    right_width = right.get("width")
    delta = None
    if isinstance(left_width, (int, float)) and isinstance(right_width, (int, float)):
        delta = float(right_width) - float(left_width)
    return {
        "session_id": left["session_id"],
        "from_k": left_k,
        "to_k": right_k,
        "delta_width": delta,
        "availability": "ELIGIBLE" if delta is not None else "NOT_EVALUABLE",
    }


def contiguous_scale_survival(records: Iterable[RangeRecord]) -> tuple[tuple[int, int], ...]:
    eligible = sorted(
        record.duration_k
        for record in records
        if record.availability == "ELIGIBLE"
    )
    if not eligible:
        return ()
    spans: list[tuple[int, int]] = []
    start = previous = eligible[0]
    for current in eligible[1:]:
        if current != previous + 1:
            spans.append((start, previous))
            start = current
        previous = current
    spans.append((start, previous))
    return tuple(spans)

"""Audit SRC-01 clock boundaries and causal grammar handoff.

The online capture is the only authority used for causal timing. Legacy buffer
values are included as boundary evidence but never used to infer causal state.
Timestamps are interpreted as source-clock wall times; no UTC or New York
mapping is asserted by this metrology gate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


BOUNDARIES = ("09:29", "09:30", "09:34", "09:35", "09:39", "09:40")
LEGACY = tuple(f"original_b{i}" for i in range(4))


def wall_time(epoch: str) -> tuple[str, str]:
    value = datetime.fromtimestamp(int(epoch), UTC)
    return value.date().isoformat(), value.strftime("%H:%M")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="cp1252", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def as_int(value: str) -> int | None:
    return None if value in ("", "NA") else int(float(value))


def compact(row: dict[str, str]) -> dict[str, object]:
    day, minute = wall_time(row["bar_open"])
    tick_day, tick_minute = wall_time(row["tick_time"])
    return {
        "source_day": day,
        "bar_open": minute,
        "tick_source_day": tick_day,
        "knowledge_time": tick_minute,
        "event_kind": row["event_kind"],
        "shift": int(row["shift"]),
        "lifecycle": as_int(row["v2_lifecycle"]),
        "geometry_known": as_int(row["v2_geometry_known"]),
        "interaction_eligible": as_int(row["v2_interaction_eligible"]),
        "location": as_int(row["v2_location"]),
        "grammar_event": as_int(row["v2_grammar_event"]),
        "legacy": [row[name] for name in LEGACY],
    }


def check(checks: list[dict[str, object]], check_id: str, passed: bool, evidence: object) -> None:
    checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "evidence": evidence})


def audit_capture(path: Path, expected: str) -> dict[str, object]:
    rows = read_rows(path)
    if not rows:
        return {"path": str(path), "status": "NOT_EVALUABLE_EMPTY_CAPTURE"}
    actual = rows[0]["timeframe"]
    by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        day, minute = wall_time(row["bar_open"])
        by_key[(day, minute, row["event_kind"])] = row
    days = sorted({key[0] for key in by_key})
    checks: list[dict[str, object]] = []
    check(checks, "TIMEFRAME_IDENTITY", actual == expected, {"expected": expected, "actual": actual})
    check(checks, "SINGLE_SOURCE_DAY", len(days) == 1, {"source_days": days})
    if len(days) != 1:
        return {"path": str(path), "status": "FAIL", "checks": checks}
    day = days[0]
    minutes = 1 if expected == "PERIOD_M1" else 5
    commit = "09:36" if minutes == 1 else "09:40"
    applicable = {"09:29", "09:30", "09:34", "09:35", "09:39", "09:40"} if minutes == 1 else {"09:30", "09:35", "09:40"}
    matrix: list[dict[str, object]] = []
    for minute in BOUNDARIES:
        if minute not in applicable:
            matrix.append({
                "boundary": minute,
                "status": "NOT_APPLICABLE_TIMEFRAME_BOUNDARY",
                "reason": f"{expected} has no completed-candle identity at this minute",
            })
            continue
        row = by_key.get((day, minute, "CURRENT_OPEN"))
        matrix.append({"boundary": minute, "status": "OBSERVED" if row else "MISSING", "snapshot": compact(row) if row else None})
        check(checks, f"BOUNDARY_{minute.replace(':', '')}_PRESENT", row is not None, compact(row) if row else None)

    current_rows = [row for row in rows if row["event_kind"] == "CURRENT_OPEN"]
    check(
        checks,
        "CURRENT_OPEN_NEVER_GRAMMAR_ELIGIBLE",
        all(as_int(row["v2_interaction_eligible"]) == 0 for row in current_rows),
        {"rows": len(current_rows)},
    )
    pre_commit = [row for row in current_rows if wall_time(row["bar_open"])[1] < commit and wall_time(row["bar_open"])[1] >= "09:29"]
    check(
        checks,
        "GEOMETRY_UNKNOWN_BEFORE_CAUSAL_COMMIT",
        bool(pre_commit) and all(as_int(row["v2_geometry_known"]) == 0 for row in pre_commit),
        {"commit": commit, "rows": len(pre_commit)},
    )
    commit_open = by_key.get((day, commit, "CURRENT_OPEN"))
    check(
        checks,
        "CAUSAL_FREEZE_COMMIT",
        bool(commit_open) and as_int(commit_open["v2_lifecycle"]) == 2 and as_int(commit_open["v2_geometry_known"]) == 1 and as_int(commit_open["v2_interaction_eligible"]) == 0,
        compact(commit_open) if commit_open else None,
    )
    first_completed = by_key.get((day, commit, "COMPLETED_BAR"))
    check(
        checks,
        "FIRST_COMPLETED_GRAMMAR_HANDOFF",
        bool(first_completed)
        and as_int(first_completed["v2_geometry_known"]) == 1
        and as_int(first_completed["v2_interaction_eligible"]) == 1
        and as_int(first_completed["v2_location"]) is not None
        and as_int(first_completed["v2_grammar_event"]) is not None,
        compact(first_completed) if first_completed else None,
    )
    endpoint = by_key.get((day, "09:35", "CURRENT_OPEN"))
    endpoint_values = [endpoint[name] for name in LEGACY] if endpoint else []
    check(
        checks,
        "INCLUSIVE_ENDPOINT_VISIBLE_IN_LEGACY_ORACLE",
        bool(endpoint) and all(value != "NA" for value in endpoint_values),
        {"boundary": "09:35", "legacy": endpoint_values},
    )
    failed = [item["check_id"] for item in checks if item["status"] != "PASS"]
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "timeframe": expected,
        "source_clock_day": day,
        "boundary_matrix": matrix,
        "causal_commit_bar_open": commit,
        "checks": checks,
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m1", required=True, type=Path)
    parser.add_argument("--m5", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    captures = [audit_capture(args.m1, "PERIOD_M1"), audit_capture(args.m5, "PERIOD_M5")]
    report = {
        "schema": "OBS_OPEN_SRC01_BOUNDARY_AUDIT_V1",
        "clock_authority": "SOURCE_CLOCK_WALL_TIME_ONLY",
        "new_york_clock_transport": "NOT_EVALUATED_BY_SRC01",
        "legacy_repaint_classification": "HISTORICAL_REPAINTING_COMPATIBILITY_OBSERVATION",
        "causal_authority": "V2_CAUSAL_BUFFERS_ONLY",
        "captures": captures,
        "status": "PASS" if all(item["status"] == "PASS" for item in captures) else "FAIL",
    }
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

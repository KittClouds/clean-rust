#!/usr/bin/env python3
"""Build the outcome-blind OBS-OPEN-01 coverage census and frozen universe."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--clock-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def dates(first: date, last: date):
    current = first
    while current <= last:
        yield current
        current += timedelta(days=1)


def minute_epoch(local_day: date, local_time: time, ny: ZoneInfo, offset_minutes: int) -> int:
    ny_instant = datetime.combine(local_day, local_time, ny)
    utc_instant = ny_instant.astimezone(timezone.utc)
    server_wall = utc_instant + timedelta(minutes=offset_minutes)
    return int(server_wall.timestamp())


def in_unresolved(day: date, intervals: list[dict[str, str]]) -> bool:
    return any(date.fromisoformat(row["first"]) <= day <= date.fromisoformat(row["last"]) for row in intervals)


def write_tsv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    if not rows and fieldnames is None:
        raise ValueError(f"cannot infer empty schema for {path}")
    names = fieldnames or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    clock_receipt = json.loads(args.clock_receipt.read_text(encoding="utf-8"))
    if clock_receipt["outcome"] != "QUALIFIED":
        raise ValueError("clock transport is not qualified")
    if sha256(args.source) != contract["source"]["bar_authority_sha256"]:
        raise ValueError("bar authority hash mismatch")
    args.output.mkdir(parents=True, exist_ok=True)

    span = contract["candidate_civil_dates"]
    first, last = date.fromisoformat(span["first"]), date.fromisoformat(span["last"])
    ny = ZoneInfo(span["timezone"])
    proxy = ZoneInfo(contract["clock"]["server_offset_proxy_timezone"])
    closures = {date.fromisoformat(value) for values in contract["calendar"]["full_closures"].values() for value in values}
    early = {date.fromisoformat(value) for values in contract["calendar"]["early_closes"].values() for value in values}
    unresolved = contract["clock"]["excluded_unresolved_intervals"]

    sessions: dict[str, dict[str, object]] = {}
    expected: dict[tuple[str, int], tuple[str, str]] = {}
    for day in dates(first, last):
        sid = f"OBSOPEN_US30_{day:%Y%m%d}"
        row: dict[str, object] = {"session_id": sid, "civil_date": day.isoformat()}
        if day.weekday() >= 5:
            row.update(calendar_status="NON_SESSION_WEEKEND", clock_status="NOT_APPLICABLE", server_offset_minutes="")
        elif day in closures:
            row.update(calendar_status="EXCHANGE_CLOSED", clock_status="NOT_APPLICABLE", server_offset_minutes="")
        elif day in early:
            row.update(calendar_status="EARLY_CLOSE", clock_status="NOT_APPLICABLE", server_offset_minutes="")
        elif in_unresolved(day, unresolved):
            row.update(calendar_status="NORMAL_SESSION", clock_status="NOT_EVALUABLE_CLOCK_TRANSPORT", server_offset_minutes="")
        else:
            noon = datetime.combine(day, time(12), timezone.utc).astimezone(proxy)
            delta = noon.utcoffset()
            if delta is None:
                raise ValueError(f"offset unavailable for {day}")
            offset = int(delta.total_seconds() // 60)
            row.update(calendar_status="NORMAL_SESSION", clock_status="QUALIFIED", server_offset_minutes=offset)
            start = minute_epoch(day, time(9, 30), ny, offset)
            for index in range(30):
                expected[("M1", start + index * 60)] = (sid, "M1_RANGE")
            for index in range(79):
                expected[("M5", start + index * 300)] = (sid, "M5_HORIZON")
        sessions[sid] = row

    observed: Counter[tuple[str, int]] = Counter()
    source_day_rows: dict[str, Counter[str]] = defaultdict(Counter)
    with args.source.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle, delimiter="\t"):
            timeframe = raw["timeframe"]
            if timeframe not in ("M1", "M5"):
                raise ValueError(f"unexpected timeframe {timeframe}")
            source_day_rows[raw["source_day"].replace(".", "-")][timeframe] += 1
            key = (timeframe, int(raw["server_epoch"]))
            if key in expected:
                observed[key] += 1

    census: list[dict[str, object]] = []
    admitted: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    partition = contract["partition"]
    discovery_last = date.fromisoformat(partition["discovery_last"])
    confirmation_first = date.fromisoformat(partition["confirmation_first"])
    for sid, base in sessions.items():
        day = date.fromisoformat(str(base["civil_date"]))
        m1_keys: list[tuple[str, int]] = []
        m5_keys: list[tuple[str, int]] = []
        if base["clock_status"] == "QUALIFIED":
            offset = int(base["server_offset_minutes"])
            start = minute_epoch(day, time(9, 30), ny, offset)
            m1_keys = [("M1", start + index * 60) for index in range(30)]
            m5_keys = [("M5", start + index * 300) for index in range(79)]
        missing_m1 = sum(observed[key] == 0 for key in m1_keys)
        missing_m5 = sum(observed[key] == 0 for key in m5_keys)
        duplicate_m1 = sum(max(0, observed[key] - 1) for key in m1_keys)
        duplicate_m5 = sum(max(0, observed[key] - 1) for key in m5_keys)
        observed_m1 = sum(observed[key] > 0 for key in m1_keys)
        observed_m5 = sum(observed[key] > 0 for key in m5_keys)

        if base["calendar_status"] == "NON_SESSION_WEEKEND":
            decision = "NON_SESSION_WEEKEND"
        elif base["calendar_status"] == "EXCHANGE_CLOSED":
            decision = "EXCHANGE_CLOSED"
        elif base["calendar_status"] == "EARLY_CLOSE":
            decision = "EARLY_CLOSE_HORIZON_INCOMPLETE"
        elif base["clock_status"] != "QUALIFIED":
            decision = "NOT_EVALUABLE_CLOCK_TRANSPORT"
        elif duplicate_m1 or duplicate_m5:
            decision = "NOT_EVALUABLE_DUPLICATE_SOURCE"
        elif missing_m1:
            decision = "NOT_EVALUABLE_SOURCE_COVERAGE_M1"
        elif missing_m5:
            decision = "NOT_EVALUABLE_SOURCE_COVERAGE_M5"
        else:
            decision = "ADMITTED"

        assigned = ""
        if decision == "ADMITTED":
            if day <= discovery_last:
                assigned = "DISCOVERY"
            elif day >= confirmation_first:
                assigned = "CONFIRMATION"
            else:
                raise ValueError(f"partition gap at {day}")
        row = {
            **base,
            "source_day_m1_rows": source_day_rows[day.isoformat()]["M1"],
            "source_day_m5_rows": source_day_rows[day.isoformat()]["M5"],
            "expected_m1_range": len(m1_keys),
            "observed_m1_range": observed_m1,
            "missing_m1_range": missing_m1,
            "duplicate_m1_range": duplicate_m1,
            "expected_m5_horizon": len(m5_keys),
            "observed_m5_horizon": observed_m5,
            "missing_m5_horizon": missing_m5,
            "duplicate_m5_horizon": duplicate_m5,
            "decision": decision,
            "partition": assigned,
        }
        census.append(row)
        if decision == "ADMITTED":
            admitted.append({
                "session_id": sid,
                "civil_date": day.isoformat(),
                "partition": assigned,
                "server_offset_minutes": base["server_offset_minutes"],
                "confirmation_status": "FROZEN_UNOPENED" if assigned == "CONFIRMATION" else "NOT_APPLICABLE",
            })
        else:
            excluded.append({"session_id": sid, "civil_date": day.isoformat(), "reason": decision})

    census_path = args.output / "session_coverage_census.tsv"
    admitted_path = args.output / "admitted_sessions.tsv"
    excluded_path = args.output / "excluded_sessions.tsv"
    partition_path = args.output / "partition_manifest.tsv"
    write_tsv(census_path, census)
    admitted_fields = ["session_id", "civil_date", "partition", "server_offset_minutes", "confirmation_status"]
    write_tsv(admitted_path, admitted, admitted_fields)
    write_tsv(excluded_path, excluded, ["session_id", "civil_date", "reason"])
    write_tsv(partition_path, admitted, admitted_fields)

    counts = Counter(str(row["partition"]) for row in admitted)
    decision_counts = Counter(str(row["decision"]) for row in census)
    months: dict[str, Counter[str]] = defaultdict(Counter)
    offsets: dict[str, set[int]] = defaultdict(set)
    for row in admitted:
        part = str(row["partition"])
        months[part][str(row["civil_date"])[:7]] += 1
        offsets[part].add(int(row["server_offset_minutes"]))
    supported_months = {
        part: sum(value >= partition["minimum_sessions_per_supported_month"] for value in month_counts.values())
        for part, month_counts in months.items()
    }
    gates = {
        "minimum_discovery_sessions": counts["DISCOVERY"] >= partition["minimum_admitted_discovery_sessions"],
        "minimum_confirmation_sessions": counts["CONFIRMATION"] >= partition["minimum_admitted_confirmation_sessions"],
        "minimum_discovery_months": supported_months.get("DISCOVERY", 0) >= partition["minimum_supported_calendar_months_per_partition"],
        "minimum_confirmation_months": supported_months.get("CONFIRMATION", 0) >= partition["minimum_supported_calendar_months_per_partition"],
        "discovery_has_both_offset_regimes": offsets["DISCOVERY"] == {120, 180},
        "confirmation_has_both_offset_regimes": offsets["CONFIRMATION"] == {120, 180},
    }
    qualified = all(gates.values())
    receipt = {
        "schema": "OBS_OPEN_UNIVERSE_QUALIFICATION_RECEIPT_V1",
        "outcome": "QUALIFIED" if qualified else "NOT_EVALUABLE_SOURCE_COVERAGE",
        "candidate_civil_dates": len(census),
        "admitted_sessions": len(admitted),
        "discovery_sessions": counts["DISCOVERY"],
        "confirmation_sessions": counts["CONFIRMATION"],
        "decision_counts": dict(sorted(decision_counts.items())),
        "supported_months": dict(sorted(supported_months.items())),
        "offset_regimes": {key: sorted(value) for key, value in sorted(offsets.items())},
        "gates": gates,
        "confirmation_status": "FROZEN_UNOPENED",
        "substantive_observer_outputs_read": False,
        "source_sha256": sha256(args.source),
        "contract_sha256": sha256(args.contract),
        "clock_receipt_sha256": sha256(args.clock_receipt),
        "artifacts": {
            "session_coverage_census.tsv": sha256(census_path),
            "admitted_sessions.tsv": sha256(admitted_path),
            "excluded_sessions.tsv": sha256(excluded_path),
            "partition_manifest.tsv": sha256(partition_path),
        },
    }
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    (args.output / "universe_qualification_receipt.json").write_bytes(canonical_json(receipt))
    return 0 if qualified else 3


if __name__ == "__main__":
    raise SystemExit(main())

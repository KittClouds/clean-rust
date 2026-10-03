#!/usr/bin/env python3
"""Audit provisional/live versus completed sentinel state.

This is an OBS-OPEN-INST-01 metrology check only. It deliberately avoids all
market-behaviour aggregation and evaluates causal state transitions exclusively.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


NA = "NA"
COMMITTED_FIELDS = (38, 39, 40, 41, 44, 45, 50, 51)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="ascii", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def check(name: str, examined: int, failures: list[dict[str, object]]) -> dict[str, object]:
    return {
        "status": "NOT_EVALUABLE" if examined == 0 else "PASS" if not failures else "FAIL",
        "examined": examined,
        "failures": len(failures),
        "first_failure": failures[0] if failures else None,
    }


def audit(path: Path) -> dict[str, object]:
    rows = read_rows(path)
    tick_rows = [row for row in rows if row["event_kind"] == "CURRENT_TICK_SENTINEL_CHANGE"]
    completed = {
        int(row["bar_open"]): row
        for row in rows
        if row["event_kind"] == "COMPLETED_BAR" and int(row["shift"]) == 1
    }
    by_bar: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in tick_rows:
        by_bar[int(row["bar_open"])].append(row)

    old_failures: list[dict[str, object]] = []
    for row_index, row in enumerate(rows):
        for buffer in range(36):
            if row[f"v200_b{buffer}"] != row[f"v210_b{buffer}"]:
                old_failures.append({"row": row_index, "buffer": buffer})
                break

    provisional_failures: list[dict[str, object]] = []
    upper_live_changes = 0
    lower_live_changes = 0
    for bar_open, group in sorted(by_bar.items()):
        prior_upper = None
        prior_lower = None
        frozen = tuple(group[0][f"v210_b{field}"] for field in COMMITTED_FIELDS)
        for row in group:
            current = tuple(row[f"v210_b{field}"] for field in COMMITTED_FIELDS)
            if current != frozen or row["v210_b42"] != "0.000000000000" or row["v210_b43"] != "0.000000000000":
                provisional_failures.append({"bar_open": bar_open, "tick_time": int(row["tick_time"]), "reason": "committed identity advanced intrabar"})
            live_upper = row["v210_b36"]
            live_lower = row["v210_b37"]
            if prior_upper is not None and live_upper != prior_upper:
                upper_live_changes += 1
            if prior_lower is not None and live_lower != prior_lower:
                lower_live_changes += 1
            prior_upper, prior_lower = live_upper, live_lower

    commit_failures: list[dict[str, object]] = []
    committed_bars = 0
    for bar_open, group in sorted(by_bar.items()):
        final_tick = group[-1]
        terminal = completed.get(bar_open)
        if terminal is None:
            continue
        committed_bars += 1
        if terminal["v210_b38"] != final_tick["v210_b36"] or terminal["v210_b39"] != final_tick["v210_b37"]:
            commit_failures.append({"bar_open": bar_open, "reason": "completed state differs from final provisional extreme"})

    provisional_evidence = len(tick_rows) if upper_live_changes > 0 and lower_live_changes > 0 else 0
    checks = {
        "V2_00_REGRESSION_PARITY": check("V2_00_REGRESSION_PARITY", len(rows) * 36, old_failures),
        "PROVISIONAL_SENTINEL_MOVEMENT": check("PROVISIONAL_SENTINEL_MOVEMENT", provisional_evidence, []),
        "COMMITTED_IDENTITY_INTRABAR_IMMUTABLE": check("COMMITTED_IDENTITY_INTRABAR_IMMUTABLE", len(tick_rows), provisional_failures),
        "PROVISIONAL_TO_COMPLETED_HANDOFF": check("PROVISIONAL_TO_COMPLETED_HANDOFF", committed_bars, commit_failures),
    }
    overall = "PASS" if all(item["status"] == "PASS" for item in checks.values()) else "FAIL"
    result = {
        "schema": "OBS_OPEN_INST01_ONLINE_AUDIT_V1",
        "input": {"path": path.name, "sha256": digest(path), "bytes": path.stat().st_size, "rows": len(rows)},
        "runtime_evidence": {
            "tick_sentinel_change_rows": len(tick_rows),
            "bars_with_tick_changes": len(by_bar),
            "upper_intrabar_changes": upper_live_changes,
            "lower_intrabar_changes": lower_live_changes,
            "completed_handoffs": committed_bars,
        },
        "checks": checks,
        "overall": overall,
        "scope": "INSTRUMENT_METROLOGY_ONLY",
        "market_findings": "FORBIDDEN_NOT_COMPUTED",
    }
    logical = hashlib.sha256((json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
    return {"audit": result, "logical_sha256": logical}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.capture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0 if result["audit"]["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

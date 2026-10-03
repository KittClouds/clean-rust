#!/usr/bin/env python3
"""Audit OBS-OPEN-INST-01 controlled M1 fixture captures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


NA = "NA"
START = 1704187800  # 2024-01-02 09:30 terminal/source time
FREEZE = 1704188160  # first post-range bar (09:36)
AREA_END_BAR = 1704189600  # 10:00 open; bar close is configured area commit


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="ascii", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    rows.sort(key=lambda row: int(row["bar_open"]))
    return rows


def f(row: dict[str, str], name: str) -> float | None:
    value = row[name]
    return None if value == NA else float(value)


def close(a: float | None, b: float, tol: float = 1e-9) -> bool:
    return a is not None and abs(a - b) <= tol


def add(checks: list[dict[str, object]], name: str, passed: bool, detail: str) -> None:
    checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})


def index(rows: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    return {int(row["bar_open"]): row for row in rows}


def audit_full(path: Path) -> dict[str, object]:
    rows = load(path)
    by_time = index(rows)
    checks: list[dict[str, object]] = []

    expected = {
        START: (101.0, 99.0, 1, 1, 0, 0, 1, 1),
        START + 60: (102.0, 99.0, 1, 0, 0, 1, 2, 1),
        START + 120: (102.0, 98.0, 0, 1, 1, 0, 2, 2),
        START + 180: (103.0, 97.0, 1, 1, 0, 0, 3, 3),
        START + 240: (103.0, 97.0, 0, 0, 1, 1, 3, 3),
        START + 300: (103.0, 97.0, 0, 0, 2, 2, 3, 3),
        START + 360: (104.0, 97.0, 1, 0, 0, 3, 4, 3),
        START + 420: (104.0, 96.0, 0, 1, 1, 0, 4, 4),
        START + 480: (104.0, 96.0, 0, 0, 2, 1, 4, 4),
        START + 540: (104.0, 96.0, 0, 0, 3, 2, 4, 4),
    }
    for when, values in expected.items():
        row = by_time.get(when)
        passed = row is not None
        if row is not None:
            fields = (38, 39, 42, 43, 44, 45, 50, 51)
            passed = all(close(f(row, f"v210_b{field}"), float(value)) for field, value in zip(fields, values))
        add(checks, f"fixture_state_{when}", passed, "committed H/L, flags, ages, and IDs")

    in_window = [row for row in rows if START <= int(row["bar_open"]) <= AREA_END_BAR]
    add(checks, "window_active", all(close(f(row, "v210_b52"), 1.0) for row in in_window), "all authorized rows active")
    add(checks, "window_coverage", all(close(f(row, "v210_b53"), 1.0) for row in in_window), "all authorized rows covered")
    before = by_time[START - 60]
    after = by_time[AREA_END_BAR + 60]
    add(checks, "window_start_boundary", close(f(before, "v210_b52"), 0.0) and f(before, "v210_b36") is None, "no sentinel before start")
    add(checks, "window_end_boundary", close(f(after, "v210_b52"), 0.0) and f(after, "v210_b36") is None, "no sentinel after area commit")

    births_ok = True
    for row in in_window:
        if close(f(row, "v210_b42"), 1.0):
            births_ok &= close(f(row, "v210_b40"), float(int(row["bar_open"]) + 60))
        if close(f(row, "v210_b43"), 1.0):
            births_ok &= close(f(row, "v210_b41"), float(int(row["bar_open"]) + 60))
    add(checks, "birth_time_knowledge", births_ok, "new candidates use completed-bar close time")

    mono_h = all(f(b, "v210_b38") >= f(a, "v210_b38") for a, b in zip(in_window, in_window[1:]))
    mono_l = all(f(b, "v210_b39") <= f(a, "v210_b39") for a, b in zip(in_window, in_window[1:]))
    add(checks, "upper_monotonic", mono_h, "committed upper never decreases")
    add(checks, "lower_monotonic", mono_l, "committed lower never increases")

    giveback_ok = all(
        close(f(row, "v210_b46"), max(0.0, f(row, "v210_b38") - float(row["bar_close"])))
        and close(f(row, "v210_b47"), max(0.0, float(row["bar_close"]) - f(row, "v210_b39")))
        for row in in_window
    )
    add(checks, "giveback_identity", giveback_ok, "published givebacks reconstruct from primitive state")

    pre_freeze = [row for row in in_window if int(row["bar_open"]) < FREEZE]
    post_freeze = [row for row in in_window if int(row["bar_open"]) >= FREEZE]
    add(checks, "extension_unavailable_before_freeze", all(f(row, "v210_b48") is None and f(row, "v210_b49") is None for row in pre_freeze), "no fixed-range extension before causal geometry")
    extension_ok = all(
        close(f(row, "v210_b48"), max(0.0, f(row, "v210_b38") - f(row, "v210_b0")))
        and close(f(row, "v210_b49"), max(0.0, f(row, "v210_b1") - f(row, "v210_b39")))
        for row in post_freeze
    )
    add(checks, "extension_identity_after_freeze", extension_ok, "extensions reconstruct from causal range and committed extremes")

    old_parity = all(
        row[f"v200_b{buffer}"] == row[f"v210_b{buffer}"]
        for row in rows for buffer in range(36)
    )
    add(checks, "v200_v210_buffers_0_35", old_parity, f"{len(rows) * 36} exact cells")
    return {
        "capture": str(path.as_posix()),
        "capture_sha256": sha256(path),
        "row_count": len(rows),
        "checks": checks,
        "status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
    }


def audit_gap(path: Path) -> dict[str, object]:
    rows = load(path)
    by_time = index(rows)
    checks: list[dict[str, object]] = []
    missing = FREEZE
    first_after = FREEZE + 60
    add(checks, "omitted_bar_absent", missing not in by_time, "09:36 source bar absent")
    later = [row for row in rows if first_after <= int(row["bar_open"]) <= AREA_END_BAR]
    fail_closed = all(
        close(f(row, "v210_b52"), 1.0)
        and close(f(row, "v210_b53"), 0.0)
        and all(f(row, f"v210_b{buffer}") is None for buffer in (36, 37, 38, 39, 40, 41, 44, 45, 46, 47, 48, 49, 50, 51))
        for row in later
    )
    add(checks, "sentinel_path_gap_fail_closed", fail_closed, "active window remains explicit while coverage and claims fail closed")
    old_parity = all(
        row[f"v200_b{buffer}"] == row[f"v210_b{buffer}"]
        for row in rows for buffer in range(36)
    )
    add(checks, "v200_v210_buffers_0_35", old_parity, f"{len(rows) * 36} exact cells")
    return {
        "capture": str(path.as_posix()),
        "capture_sha256": sha256(path),
        "row_count": len(rows),
        "checks": checks,
        "status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--gap", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "schema": "OBS_OPEN_INST01_CONTROLLED_FIXTURE_AUDIT_V1",
        "full": audit_full(args.full),
        "gap": audit_gap(args.gap),
    }
    result["status"] = "PASS" if result["full"]["status"] == result["gap"]["status"] == "PASS" else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

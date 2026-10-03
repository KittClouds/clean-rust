#!/usr/bin/env python3
"""Deterministic OBS-OPEN-INST-01 capture auditor.

This tool evaluates instrument identities only. It deliberately emits no market
distribution, frequency, expectancy, or economic statistic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


NA = "NA"
EPS = 1e-9


def number(value: str) -> float | None:
    return None if value == NA else float(value)


def equal(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=0.0, abs_tol=EPS)


def integer(value: str) -> int | None:
    parsed = number(value)
    return None if parsed is None else int(round(parsed))


def canonical_sha256(value: Any) -> tuple[bytes, str]:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return payload, hashlib.sha256(payload).hexdigest()


@dataclass
class Check:
    name: str
    examined: int = 0
    failures: int = 0
    first_failure: dict[str, Any] | None = None

    def require(self, ok: bool, row: dict[str, str], detail: str) -> None:
        self.examined += 1
        if ok:
            return
        self.failures += 1
        if self.first_failure is None:
            self.first_failure = {
                "bar_open": row["bar_open"],
                "shift": int(row["shift"]),
                "detail": detail,
            }

    def receipt(self) -> dict[str, Any]:
        if self.examined == 0:
            status = "NOT_EVALUABLE"
        else:
            status = "PASS" if self.failures == 0 else "FAIL"
        return {
            "status": status,
            "examined": self.examined,
            "failures": self.failures,
            "first_failure": self.first_failure,
        }


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError("capture has no header")
        rows = list(reader)
        return list(reader.fieldnames), rows


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sorted_completed(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return sorted((row for row in rows if int(row["shift"]) > 0), key=lambda r: int(r["bar_open"]))


def audit(path: Path) -> dict[str, Any]:
    fields, raw_rows = read_rows(path)
    required = {
        "symbol", "timeframe", "bar_open", "shift", "bar_high", "bar_low", "bar_close",
        *(f"v200_b{i}" for i in range(36)), *(f"v210_b{i}" for i in range(54)),
    }
    missing = sorted(required.difference(fields))
    if missing:
        raise ValueError(f"missing columns: {missing}")

    checks = {name: Check(name) for name in (
        "V2_00_REGRESSION_PARITY",
        "SENTINEL_WINDOW_SEMANTICS",
        "COMMITTED_EXTREME_MONOTONICITY",
        "CANDIDATE_IDENTITY",
        "BIRTH_TIME_CAUSALITY",
        "AGE_SEMANTICS",
        "GIVEBACK_IDENTITY",
        "RANGE_EXTENSION_IDENTITY",
    )}

    # Append-only regression authority: values and NA placement are both exact.
    for row in raw_rows:
        for index in range(36):
            left = row[f"v200_b{index}"]
            right = row[f"v210_b{index}"]
            checks["V2_00_REGRESSION_PARITY"].require(
                left == right, row, f"buffer={index} v200={left} v210={right}"
            )

    # Sentinel identities operate on completed observations grouped by the
    # already-published session identity. No session identity is inferred.
    sessions: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in sorted_completed(raw_rows):
        session = row["v210_b35"]
        if session != NA:
            sessions[session].append(row)

    qualified_sessions = 0
    for session_rows in sessions.values():
        active = [row for row in session_rows if integer(row["v210_b52"]) == 1]
        if not active:
            continue
        qualified_sessions += 1
        previous: dict[str, str] | None = None
        for row in active:
            coverage = integer(row["v210_b53"])
            upper = number(row["v210_b38"])
            lower = number(row["v210_b39"])
            upper_id = integer(row["v210_b50"])
            lower_id = integer(row["v210_b51"])
            upper_age = integer(row["v210_b44"])
            lower_age = integer(row["v210_b45"])
            new_upper = integer(row["v210_b42"])
            new_lower = integer(row["v210_b43"])
            period_seconds = 60 if row["timeframe"] == "PERIOD_M1" else 300 if row["timeframe"] == "PERIOD_M5" else None

            checks["SENTINEL_WINDOW_SEMANTICS"].require(
                coverage in (0, 1), row, f"coverage={coverage}"
            )
            if coverage != 1 or upper is None or lower is None:
                previous = None
                continue

            high = float(row["bar_high"])
            low = float(row["bar_low"])
            close = float(row["bar_close"])
            checks["COMMITTED_EXTREME_MONOTONICITY"].require(
                upper + EPS >= high and lower - EPS <= low,
                row, f"upper={upper} high={high} lower={lower} low={low}",
            )
            checks["GIVEBACK_IDENTITY"].require(
                equal(number(row["v210_b46"]), max(0.0, upper - close))
                and equal(number(row["v210_b47"]), max(0.0, close - lower)),
                row, "published giveback differs from primitive identity",
            )

            geometry_known = integer(row["v210_b25"]) == 1
            upper_ext = number(row["v210_b48"])
            lower_ext = number(row["v210_b49"])
            if geometry_known:
                range_high = number(row["v210_b0"])
                range_low = number(row["v210_b1"])
                checks["RANGE_EXTENSION_IDENTITY"].require(
                    range_high is not None and range_low is not None
                    and equal(upper_ext, max(0.0, upper - range_high))
                    and equal(lower_ext, max(0.0, range_low - lower)),
                    row, "published range extension differs from primitive identity",
                )
            else:
                checks["RANGE_EXTENSION_IDENTITY"].require(
                    upper_ext is None and lower_ext is None,
                    row, "extension published before GeometryKnownFlag",
                )

            if previous is None:
                checks["CANDIDATE_IDENTITY"].require(
                    upper_id == 1 and lower_id == 1 and new_upper == 1 and new_lower == 1,
                    row, f"first ids/flags upper={upper_id}/{new_upper} lower={lower_id}/{new_lower}",
                )
                checks["AGE_SEMANTICS"].require(
                    upper_age == 0 and lower_age == 0,
                    row, f"first ages upper={upper_age} lower={lower_age}",
                )
                if period_seconds is not None:
                    close_time = int(row["bar_open"]) + period_seconds
                    checks["BIRTH_TIME_CAUSALITY"].require(
                        integer(row["v210_b40"]) == close_time and integer(row["v210_b41"]) == close_time,
                        row, f"first candidate birth must equal close={close_time}",
                    )
            else:
                prev_upper = number(previous["v210_b38"])
                prev_lower = number(previous["v210_b39"])
                prev_upper_id = integer(previous["v210_b50"])
                prev_lower_id = integer(previous["v210_b51"])
                prev_upper_age = integer(previous["v210_b44"])
                prev_lower_age = integer(previous["v210_b45"])
                expect_new_upper = high > (prev_upper if prev_upper is not None else math.inf) + EPS
                expect_new_lower = low < (prev_lower if prev_lower is not None else -math.inf) - EPS
                checks["COMMITTED_EXTREME_MONOTONICITY"].require(
                    prev_upper is not None and prev_lower is not None
                    and upper + EPS >= prev_upper and lower - EPS <= prev_lower,
                    row, "committed extreme reversed",
                )
                checks["CANDIDATE_IDENTITY"].require(
                    upper_id == prev_upper_id + int(expect_new_upper)
                    and lower_id == prev_lower_id + int(expect_new_lower)
                    and new_upper == int(expect_new_upper)
                    and new_lower == int(expect_new_lower),
                    row, "candidate id/flag did not follow strict completed-bar inequality",
                )
                checks["AGE_SEMANTICS"].require(
                    upper_age == (0 if expect_new_upper else prev_upper_age + 1)
                    and lower_age == (0 if expect_new_lower else prev_lower_age + 1),
                    row, "candidate age did not reset/increment exactly once",
                )
                if period_seconds is not None:
                    close_time = int(row["bar_open"]) + period_seconds
                    checks["BIRTH_TIME_CAUSALITY"].require(
                        (not expect_new_upper or integer(row["v210_b40"]) == close_time)
                        and (not expect_new_lower or integer(row["v210_b41"]) == close_time),
                        row, f"new candidate birth must equal close={close_time}",
                    )
            previous = row

    timeframes = sorted({row["timeframe"] for row in raw_rows})
    symbols = sorted({row["symbol"] for row in raw_rows})
    results = {name: check.receipt() for name, check in sorted(checks.items())}
    overall = "PASS" if all(item["status"] == "PASS" for item in results.values()) else "FAIL"
    return {
        "schema": "OBS_OPEN_INST01_CAPTURE_AUDIT_V1",
        "input": {
            "path": path.name,
            "sha256": source_hash(path),
            "bytes": path.stat().st_size,
            "rows": len(raw_rows),
            "symbols": symbols,
            "timeframes": timeframes,
        },
        "qualified_session_paths": qualified_sessions,
        "checks": results,
        "overall": overall,
        "scope": "INSTRUMENT_METROLOGY_ONLY",
        "market_findings": "FORBIDDEN_NOT_COMPUTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.capture)
    payload, digest = canonical_sha256(result)
    envelope = {"audit": result, "logical_sha256": digest}
    final = (json.dumps(envelope, sort_keys=True, indent=2) + "\n").encode()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(final)
    else:
        print(final.decode(), end="")
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

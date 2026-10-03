"""Deterministic SRC-01 capture parity and causal-separation audit.

The tool is intentionally fail-closed: absent capture files produce an
explicit NOT_EVALUABLE result, never a synthetic pass. TSV values are compared
as canonical cells so NA/empty/number distinctions cannot disappear.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


LEGACY_GROUPS = {
    "original_translated": ("original_b", "translated_b"),
    "original_v2_compatibility": ("original_b", "v2_legacy_b"),
    "translated_v2_compatibility": ("translated_b", "v2_legacy_b"),
}
KEY = ("capture_mode", "event_kind", "symbol", "timeframe", "bar_open", "shift")


def read_rows(path: Path) -> dict[tuple[str, ...], dict[str, str]]:
    with path.open("r", encoding="cp1252", newline="") as fh:
        rows = csv.DictReader(fh, delimiter="\t")
        return {tuple(row[name] for name in KEY): row for row in rows}


def canonical(row: dict[str, str], prefix: str, index: int) -> str:
    return row.get(f"{prefix}{index}", "")


def compare(left: dict[tuple[str, ...], dict[str, str]], right: dict[tuple[str, ...], dict[str, str]], a: str, b: str) -> dict[str, object]:
    keys = sorted(set(left) | set(right))
    missing_left = sum(key not in left for key in keys)
    missing_right = sum(key not in right for key in keys)
    cells = equal = mismatched = 0
    mismatch_examples: list[dict[str, object]] = []
    for key in keys:
        if key not in left or key not in right:
            continue
        for index in range(4):
            cells += 1
            lv = canonical(left[key], a, index)
            rv = canonical(right[key], b, index)
            if lv == rv:
                equal += 1
            else:
                mismatched += 1
                if len(mismatch_examples) < 10:
                    mismatch_examples.append({"key": key, "buffer": index, "left": lv, "right": rv})
    return {
        "left": a,
        "right": b,
        "rows_union": len(keys),
        "rows_left": len(left),
        "rows_right": len(right),
        "missing_left": missing_left,
        "missing_right": missing_right,
        "cells_compared": cells,
        "cells_equal": equal,
        "cells_mismatched": mismatched,
        "status": "PASS" if cells and mismatched == 0 and not missing_left and not missing_right else "FAIL",
        "mismatch_examples": mismatch_examples,
    }


def audit(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"path": str(path), "status": "NOT_EVALUABLE_CAPTURE_MISSING"}
    rows = read_rows(path)
    results = [compare(rows, rows, "original_b", "translated_b")]  # overwritten below for same-row source columns
    results.clear()
    for label, (a, b) in LEGACY_GROUPS.items():
        result = compare(rows, rows, a, b)
        result["comparison"] = label
        results.append(result)
    event_counts = Counter(row["event_kind"] for row in rows.values())
    mode_counts = Counter(row["capture_mode"] for row in rows.values())
    causal_present = all(name in next(iter(rows.values()), {}) for name in ("v2_lifecycle", "v2_geometry_known", "v2_interaction_eligible", "v2_location", "v2_grammar_event"))
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status": "CAPTURE_READ",
        "rows": len(rows),
        "event_kinds": dict(sorted(event_counts.items())),
        "capture_modes": dict(sorted(mode_counts.items())),
        "legacy_parity": results,
        "causal_columns_present": causal_present,
        "causal_inference": "SEPARATE_FROM_LEGACY_BUFFER_PARITY",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"schema": "OBS_OPEN_SRC01_PARITY_V1", "captures": [audit(path) for path in args.paths]}
    payload = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()

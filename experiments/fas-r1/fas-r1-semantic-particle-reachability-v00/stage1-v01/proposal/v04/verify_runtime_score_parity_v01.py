#!/usr/bin/env python3
"""Verify fitted Python validation logits against the exact Rust runtime export."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

SCORE_SCHEMA = "R1_V04_RUNTIME_PROPOSAL_SCORE_ROWS_V01"
SCORE_RECEIPT_SCHEMA = "R1_V04_RUNTIME_PROPOSAL_SCORE_RECEIPT_V01"
FIT_RECEIPT_SCHEMA = "FAS_R1_PROPOSAL_RUNTIME_FIT_V01"
EXPECTED_ROWS = {"train": 81920, "validation": 20480}
EXPECTED_VALIDATION_STATES = 512
EXPECTED_ACTIONS_PER_STATE = 40


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    digest, size = sha256_file(resolved)
    return {"path": str(resolved), "sha256": digest, "bytes": size}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
            if not isinstance(value, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield value


def canonical_path(value: str | Path) -> str:
    raw = os.fspath(value)
    folded = raw.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        raw = "\\\\" + raw[8:]
    elif folded.startswith("\\\\?\\"):
        raw = raw[4:]
    return os.path.normcase(os.path.normpath(str(Path(raw).resolve(strict=False))))


def check_record(record: Any, observed: dict[str, Any], label: str) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"receipt omits the {label} file record")
    if any(record.get(key) != observed[key] for key in ("sha256", "bytes")):
        raise ValueError(f"{label} does not match its receipt")
    if record.get("path") is not None and canonical_path(record["path"]) != canonical_path(
        observed["path"]
    ):
        raise ValueError(f"{label} path differs from its receipt")


def within_tolerance(left: float, right: float, atol: float, rtol: float) -> bool:
    return abs(left - right) <= atol + rtol * abs(right)


def verify(
    fit_receipt_path: Path,
    fit_dir: Path,
    score_dump_path: Path,
    score_receipt_path: Path,
    *,
    atol: float = 3e-4,
    rtol: float = 3e-5,
) -> dict[str, Any]:
    if atol < 0 or rtol < 0 or not math.isfinite(atol + rtol):
        raise ValueError("parity tolerances must be finite and nonnegative")
    fit_receipt = read_json(fit_receipt_path.resolve(strict=True))
    if (
        fit_receipt.get("schema") != FIT_RECEIPT_SCHEMA
        or fit_receipt.get("status") != "R1_RUNTIME_PROPOSAL_FIT_COMPLETE"
    ):
        raise ValueError("runtime proposal fit receipt is not complete")
    weight_path = fit_dir / "proposal-weights-runtime-v01.json"
    logits_path = fit_dir / "validation-runtime-logits-v01.jsonl"
    weights_record = file_record(weight_path)
    logits_record = file_record(logits_path)
    check_record(
        fit_receipt.get("output_files", {}).get(weight_path.name),
        weights_record,
        "fitted proposal weights",
    )
    check_record(
        fit_receipt.get("output_files", {}).get(logits_path.name),
        logits_record,
        "Python validation logits",
    )
    model_sha = fit_receipt.get("model", {}).get("output_weights_sha256")
    if model_sha != weights_record["sha256"]:
        raise ValueError("fit receipt model digest differs from fitted weights")

    score_receipt = read_json(score_receipt_path.resolve(strict=True))
    if (
        score_receipt.get("schema") != SCORE_RECEIPT_SCHEMA
        or score_receipt.get("status") != "R1_V04_RUNTIME_PROPOSAL_SCORE_EXPORT_COMPLETE"
        or score_receipt.get("output_schema") != SCORE_SCHEMA
    ):
        raise ValueError("Rust score receipt is not a completed supported export")
    score_record = file_record(score_dump_path.resolve(strict=True))
    check_record(score_receipt.get("output"), score_record, "Rust score dump")
    if canonical_path(score_receipt.get("output_path", "")) != canonical_path(
        score_record["path"]
    ):
        raise ValueError("Rust score receipt output_path differs from the supplied dump")
    runtime = score_receipt.get("runtime", {})
    proposal_record = score_receipt.get("inputs", {}).get("proposal_weights", {})
    if (
        proposal_record.get("sha256") != weights_record["sha256"]
        or runtime.get("proposal_sha256") != weights_record["sha256"]
    ):
        raise ValueError("Rust scores were not produced from this fitted checkpoint")
    if runtime.get("proposal_mix_logits", {}).get("logit_incidence_masked_norm_4") != (
        "IncidenceMaskedNormalizedV03 spread_ratio=4.0"
    ):
        raise ValueError("Rust score receipt does not declare the fitted runtime mix")

    expected: dict[tuple[str, int], dict[tuple[int, int], float]] = {}
    for row in read_jsonl(logits_path):
        if row.get("family_split") != "validation":
            raise ValueError("Python logit file contains a non-validation row")
        key = (row.get("task_id"), row.get("state_index"))
        edits = row.get("edits")
        values = row.get("runtime_logits_f32")
        if (
            not isinstance(key[0], str)
            or type(key[1]) is not int
            or not isinstance(edits, list)
            or not isinstance(values, list)
            or len(edits) != EXPECTED_ACTIONS_PER_STATE
            or len(values) != EXPECTED_ACTIONS_PER_STATE
            or key in expected
        ):
            raise ValueError(f"invalid or duplicate Python validation state {key!r}")
        actions: dict[tuple[int, int], float] = {}
        for edit, value in zip(edits, values):
            action = (edit.get("entity"), edit.get("new_role"))
            numeric = float(value)
            if (
                type(action[0]) is not int
                or type(action[1]) is not int
                or not math.isfinite(numeric)
                or action in actions
            ):
                raise ValueError(f"invalid Python action/logit in state {key!r}")
            actions[action] = numeric
        expected[key] = actions
    if len(expected) != EXPECTED_VALIDATION_STATES:
        raise ValueError(f"Python validation state count is {len(expected)}, expected 512")

    split_rows = {"train": 0, "validation": 0}
    seen_states: set[tuple[str, int]] = set()
    absolute_errors: list[float] = []
    violations = 0
    for row in read_jsonl(score_dump_path):
        if row.get("schema") != SCORE_SCHEMA:
            raise ValueError("Rust score row has an unsupported schema")
        if row.get("proposal_weights_sha256") != weights_record["sha256"]:
            raise ValueError("Rust score row binds a different proposal checkpoint")
        split = row.get("family_split")
        if split not in split_rows:
            raise ValueError(f"unexpected Rust score split {split!r}")
        split_rows[split] += 1
        if split != "validation":
            continue
        key = (row.get("task_id"), row.get("state_index"))
        expected_actions = expected.get(key)
        if expected_actions is None:
            raise ValueError(f"Rust validation score has unexpected state {key!r}")
        edit = row.get("edit", {})
        action = (edit.get("entity"), edit.get("new_role"))
        reference = expected_actions.pop(action, None)
        actual = row.get("logit_incidence_masked_norm_4")
        if reference is None or isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise ValueError(f"Rust score has an unexpected or missing action {key!r} {action!r}")
        actual_value = float(actual)
        if not math.isfinite(actual_value):
            raise ValueError(f"Rust score is nonfinite at {key!r} {action!r}")
        absolute_errors.append(abs(reference - actual_value))
        if not within_tolerance(reference, actual_value, atol, rtol):
            violations += 1
        seen_states.add(key)
    if split_rows != EXPECTED_ROWS:
        raise ValueError(f"Rust split row counts differ from contract: {split_rows!r}")
    if seen_states != set(expected) or any(expected.values()):
        raise ValueError("Python and Rust validation state/action rosters differ")

    ordered_errors = sorted(absolute_errors)
    p99_index = min(len(ordered_errors) - 1, math.ceil(0.99 * len(ordered_errors)) - 1)
    return {
        "schema": "R1_V04_RUNTIME_SCORE_PARITY_V01",
        "status": "PASS" if violations == 0 else "PARITY_TOLERANCE_EXCEEDED",
        "fit_receipt": file_record(fit_receipt_path),
        "fitted_weights": weights_record,
        "python_validation_logits": logits_record,
        "rust_score_dump": score_record,
        "rust_score_receipt": file_record(score_receipt_path),
        "runtime_mix": "IncidenceMaskedNormalizedV03 spread_ratio=4.0",
        "split_row_counts": split_rows,
        "validation_states": len(seen_states),
        "validation_action_logits_compared": len(absolute_errors),
        "tolerance": {"absolute": atol, "relative": rtol},
        "error_summary": {
            "max_absolute": max(absolute_errors, default=0.0),
            "mean_absolute": sum(absolute_errors) / max(1, len(absolute_errors)),
            "p99_absolute": ordered_errors[p99_index] if ordered_errors else 0.0,
            "tolerance_violations": violations,
        },
        "reachability_evidence": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-receipt", type=Path, required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--score-dump", type=Path, required=True)
    parser.add_argument("--score-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--atol", type=float, default=3e-4)
    parser.add_argument("--rtol", type=float, default=3e-5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = verify(
            args.fit_receipt,
            args.fit_dir,
            args.score_dump,
            args.score_receipt,
            atol=args.atol,
            rtol=args.rtol,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    except Exception as error:
        print(f"R1_RUNTIME_SCORE_PARITY_V01_FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "R1_RUNTIME_SCORE_PARITY_V01_" + receipt["status"]
        + f" states={receipt['validation_states']}"
        + f" logits={receipt['validation_action_logits_compared']}"
        + f" max_abs={receipt['error_summary']['max_absolute']:.9g}"
        + f" receipt={args.output.resolve()}"
    )
    return 0 if receipt["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

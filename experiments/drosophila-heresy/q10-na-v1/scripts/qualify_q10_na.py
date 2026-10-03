"""Fail-closed Q10-NA NA-0/NA-1/NA-2 preflight.

This module verifies the frozen Q10-NA contract and the one canonical Q10-RMT
receipt.  It deliberately stops before any candidate replay.  The output is a
lineage and coverage receipt only; it contains no replay findings.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


RMT_STEPS = (1, -1, 2, -2, 4, -4, 8, -8, 16, -16)
RMT_RESERVE = 16
EXPECTED_RMT_STATUS = "Q10_RMT_VALID__TOPOLOGY_MAPPED"
EXPECTED_NA_STATUS = "Q10_NA_PREFLIGHT_VALID__READY_FOR_REPLAY"
BLOCKED_NA_STATUS = "Q10_NA_PREFLIGHT_BLOCKED__PREFIX_COVERAGE_INCOMPLETE"
HASH_ERROR_STATUS = "Q10_NA_PREFLIGHT_BLOCKED__PARENT_HASH_OR_SCHEMA_ERROR"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def from_bits(raw: int) -> float:
    return struct.unpack("<f", struct.pack("<I", raw & 0xFFFF_FFFF))[0]


def nextafter32(value: float, upward: bool) -> float:
    raw = bits(value)
    if raw == 0x0000_0000 and not upward:
        return from_bits(0x8000_0001)
    if raw == 0x8000_0000 and upward:
        return from_bits(0x0000_0001)
    if raw & 0x8000_0000:
        raw += -1 if upward else 1
    else:
        raw += 1 if upward else -1
    return from_bits(raw)


def prefix_value(value: float, choice: int) -> float:
    result = value
    for _ in range(abs(choice)):
        result = nextafter32(result, choice > 0)
    return result


def legal_value(value: float, choice: int) -> float | None:
    candidate = prefix_value(value, choice)
    raw = bits(candidate)
    if not (math.isfinite(candidate) and 0.0 < candidate < 2.0):
        return None
    if raw - bits(0.0) < RMT_RESERVE or bits(2.0) - raw < RMT_RESERVE:
        return None
    return candidate


def sequential(row: list[int], weights: list[float]) -> float:
    value = from_bits(0x8000_0000)
    for coordinate in row:
        value = f32(value + weights[coordinate])
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def protocol_root() -> Path:
    return Path(__file__).resolve().parents[1]


def workspace_root() -> Path:
    return protocol_root().parents[2]


def inside_protocol(path: Path) -> bool:
    try:
        path.resolve().relative_to(protocol_root().resolve())
        return True
    except ValueError:
        return False


def parent_paths(contract: dict[str, Any]) -> tuple[Path, Path]:
    workspace = workspace_root()
    parent = workspace / contract["parent"]["root"]
    receipt = workspace / contract["parent"]["receipt_root"]
    if parent.resolve() != (workspace / "experiments/drosophila-heresy/q10-rmt-v1").resolve():
        raise ValueError("Q10-RMT parent root is not the frozen q10-rmt-v1 root")
    if receipt.resolve() != (parent / "qualification/sample-9731-9732").resolve():
        raise ValueError("Q10-RMT receipt root is not the canonical sample receipt")
    return parent, receipt


def verify_expected_hashes(
    parent: Path,
    receipt: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    observed: dict[str, str] = {}
    missing: list[str] = []
    mismatches: list[dict[str, str]] = []

    for relative, expected in contract["parent"]["protocol_file_sha256"].items():
        path = parent / relative
        key = f"parent/{relative}"
        if not path.is_file():
            missing.append(key)
            continue
        actual = sha256(path)
        observed[key] = actual
        if actual != expected.upper():
            mismatches.append({"path": key, "expected": expected.upper(), "actual": actual})

    for relative, expected in contract["parent"]["receipt_file_sha256"].items():
        path = receipt / relative
        key = f"receipt/{relative}"
        if not path.is_file():
            missing.append(key)
            continue
        actual = sha256(path)
        observed[key] = actual
        if actual != expected.upper():
            mismatches.append({"path": key, "expected": expected.upper(), "actual": actual})

    plan = protocol_root() / "PLAN.md"
    contract_path = protocol_root() / "CONTRACT.json"
    expected_plan = contract["plan_sha256"].upper()
    actual_plan = sha256(plan)
    observed["q10-na/PLAN.md"] = actual_plan
    if actual_plan != expected_plan:
        mismatches.append({"path": "q10-na/PLAN.md", "expected": expected_plan, "actual": actual_plan})

    if not contract_path.is_file():
        missing.append("q10-na/CONTRACT.json")

    parent_preexecution_path = parent / "PREEXECUTION.json"
    if parent_preexecution_path.is_file():
        parent_preexecution = load_json(parent_preexecution_path)
        if parent_preexecution.get("status") != "FROZEN_PRE_EXECUTION":
            mismatches.append(
                {
                    "path": "parent/PREEXECUTION.json.status",
                    "expected": "FROZEN_PRE_EXECUTION",
                    "actual": str(parent_preexecution.get("status")),
                }
            )
        for entry in parent_preexecution.get("source_manifest", []):
            source = parent / entry["path"]
            key = f"parent/source-manifest/{entry['path']}"
            if not source.is_file():
                missing.append(key)
                continue
            actual = sha256(source)
            observed[key] = actual
            if actual != entry["sha256"].upper():
                mismatches.append(
                    {"path": key, "expected": entry["sha256"].upper(), "actual": actual}
                )
        input_root = Path(parent_preexecution.get("input_root", ""))
        for filename, expected in parent_preexecution.get("input_sha256", {}).items():
            source = input_root / filename
            key = f"parent/input/{filename}"
            if not source.is_file():
                missing.append(key)
                continue
            actual = sha256(source)
            observed[key] = actual
            if actual != expected.upper():
                mismatches.append(
                    {"path": key, "expected": expected.upper(), "actual": actual}
                )
    else:
        missing.append("parent/PREEXECUTION.json")

    return {"observed": observed, "missing": missing, "mismatches": mismatches}


def verify_replay_inputs(
    contract: dict[str, Any],
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, Any], list[str]]:
    """Bind and load the immutable inputs needed to replay omitted prefixes."""
    replay = contract["parent"]["replay_inputs"]
    workspace = workspace_root()
    source_root = workspace / replay["source_root"]
    da2_path = workspace / replay["da2_results_path"]
    errors: list[str] = []
    source_files: dict[str, Path] = {}
    for filename, expected in replay["source_files_sha256"].items():
        path = source_root / filename
        if not path.is_file():
            errors.append(f"missing replay source fixture: {filename}")
            continue
        if sha256(path) != str(expected).upper():
            errors.append(f"replay source fixture hash mismatch: {filename}")
            continue
        source_files[filename] = path
    if not da2_path.is_file():
        errors.append("missing bound DA2 results")
        return {}, {"source_root": str(source_root), "da2_path": str(da2_path)}, errors
    if sha256(da2_path) != str(replay["da2_results_sha256"]).upper():
        errors.append("bound DA2 results hash mismatch")
        return {}, {"source_root": str(source_root), "da2_path": str(da2_path)}, errors
    da2_results = load_json(da2_path)
    if not isinstance(da2_results, list) or len(da2_results) != 32:
        errors.append("bound DA2 results are not the declared 32-endpoint list")
        return {}, {"source_root": str(source_root), "da2_path": str(da2_path)}, errors

    states: dict[tuple[str, int], dict[str, Any]] = {}
    for result in da2_results:
        key = (str(result["source_event"]), int(result["set_index"]))
        if key in states:
            errors.append(f"duplicate DA2 endpoint identity: {key}")
            continue
        fixture_path = source_files.get(key[0])
        if fixture_path is None:
            errors.append(f"missing fixture for DA2 endpoint: {key}")
            continue
        source_record = load_json(fixture_path)
        fixture = source_record["fixture"]
        if result.get("status") != "DA2_GEOMETRY_PASS":
            continue
        weights = [from_bits(value) for value in fixture["initial_weight_bits"]]
        for coordinate_text, choice in result["selected_steps"].items():
            coordinate = int(coordinate_text)
            if not isinstance(choice, int):
                errors.append(f"non-integer selected step for {key}: {coordinate}")
                continue
            weights[coordinate] = prefix_value(weights[coordinate], choice)
        states[key] = {
            "fixture": fixture,
            "result": result,
            "weights": weights,
            "target_weights": [from_bits(value) for value in fixture["target_weight_bits"]],
        }
    return states, {
        "source_root": str(source_root),
        "da2_path": str(da2_path),
        "source_fixture_count": len(source_files),
        "da2_result_count": len(da2_results),
        "valid_endpoint_state_count": len(states),
    }, errors


def verify_target_replays(
    targets: list[dict[str, Any]],
    states: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    """Verify the reconstructed endpoint and target bits on every target row."""
    mismatches: list[dict[str, Any]] = []
    checked = 0
    for target in targets:
        key = (str(target["endpoint"]), int(target["set_index"]))
        state = states.get(key)
        if state is None:
            mismatches.append({"target": list(target_key(target)), "error": "missing endpoint state"})
            continue
        fixture_rows = state["fixture"]["operator"]["rows"]
        row = int(target["row"])
        actual = sequential(fixture_rows[row], state["weights"])
        expected = from_bits(int(target["baseline_bits"]))
        target_actual = sequential(fixture_rows[row], state["target_weights"])
        target_expected = from_bits(int(target["target_bits"]))
        checked += 1
        if bits(actual) != int(target["baseline_bits"]) or bits(target_actual) != int(target["target_bits"]):
            mismatches.append(
                {
                    "target": list(target_key(target)),
                    "baseline_observed_bits": bits(actual),
                    "baseline_expected_bits": int(target["baseline_bits"]),
                    "target_observed_bits": bits(target_actual),
                    "target_expected_bits": int(target["target_bits"]),
                    "baseline_observed": actual,
                    "baseline_expected": expected,
                    "target_observed": target_actual,
                    "target_expected": target_expected,
                }
            )
    return {"checked": checked, "mismatch_count": len(mismatches), "mismatches": mismatches[:128], "complete": not mismatches}


def endpoint_key(item: dict[str, Any]) -> tuple[str, int]:
    return (str(item["source_event"]), int(item["set_index"]))


def target_key(item: dict[str, Any]) -> tuple[str, int, int]:
    return (str(item["endpoint"]), int(item["set_index"]), int(item["row"]))


def verify_parent_schema(receipt: Path) -> dict[str, Any]:
    execution = load_json(receipt / "execution.json")
    authority = load_json(receipt / "authority-summary.json")
    endpoints = load_json(receipt / "endpoints.json")
    rows = load_json(receipt / "rows.json")
    excluded = load_json(receipt / "excluded-noncontract.json")

    errors: list[str] = []
    if execution.get("protocol") != "Q10-RMT":
        errors.append("execution protocol is not Q10-RMT")
    if execution.get("status") != EXPECTED_RMT_STATUS:
        errors.append("execution status is not Q10_RMT_VALID__TOPOLOGY_MAPPED")
    expected_flags = {
        "repair_applied": False,
        "behavioral_inference": False,
        "scientific_seed_bundles_used": 0,
        "dh08b_authorized": False,
    }
    for field, expected in expected_flags.items():
        if execution.get(field) != expected:
            errors.append(f"execution.{field} does not match the sealed value")
    if len(endpoints) != 28 or execution.get("primary_valid_endpoints") != 28:
        errors.append("primary endpoint count is not 28")
    if len(excluded) != 4 or execution.get("excluded_noncontract_endpoints") != 4:
        errors.append("excluded endpoint count is not 4")
    if len(rows) != 7003 or execution.get("mismatch_rows_mapped") != 7003:
        errors.append("RMT mismatch row count is not 7003")
    if authority.get("mismatch_rows_total") != 7003:
        errors.append("RMT authority mismatch row count is not 7003")
    if authority.get("no_local_authority_rows") != 326:
        errors.append("RMT no-local-authority count is not 326")
    if len({endpoint_key(item) for item in endpoints}) != len(endpoints):
        errors.append("duplicate RMT endpoint identity")
    if len({(item["source_event"], item["set_index"]) for item in excluded}) != len(excluded):
        errors.append("duplicate excluded endpoint identity")

    endpoint_move_counts = sum(int(item.get("move_count_serialized", 0)) for item in endpoints)
    return {
        "errors": errors,
        "execution": execution,
        "authority": authority,
        "endpoints": endpoints,
        "rows": rows,
        "excluded": excluded,
        "endpoint_move_counts": endpoint_move_counts,
    }


def collect_targets(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    target_rows = [item for item in rows if item.get("class_final") == "no_local_authority"]
    identities = [target_key(item) for item in target_rows]
    if len(target_rows) != 326:
        errors.append(f"target row count is {len(target_rows)}, expected 326")
    if len(set(identities)) != len(identities):
        errors.append("duplicate target endpoint-row identity")
    for item in target_rows:
        if item.get("k_star") not in (None, "none"):
            errors.append(f"target {target_key(item)} has a non-empty k_star")
        if item.get("one_step_helpful_coordinates") != 0:
            errors.append(f"target {target_key(item)} has one-step helpful authority")
        if item.get("all_helpful_coordinates") != 0:
            errors.append(f"target {target_key(item)} has helpful authority through 16 ULP")
        if item.get("baseline_bits") == item.get("target_bits"):
            errors.append(f"target {target_key(item)} is not a bitwise mismatch")
    return sorted(target_rows, key=target_key), errors


def collect_moves(
    receipt: Path,
    targets: list[dict[str, Any]],
    expected_move_count: int,
) -> dict[str, Any]:
    target_identities = {target_key(item) for item in targets}
    raw_coordinates: defaultdict[tuple[str, int, int], set[int]] = defaultdict(set)
    move_keys: set[tuple[str, int, int, int]] = set()
    duplicate_keys: list[tuple[str, int, int, int]] = []
    malformed: list[str] = []
    lines = 0
    endpoint_row_sets: dict[tuple[str, int], set[int]] = defaultdict(set)

    with (receipt / "moves.jsonl").open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            lines += 1
            try:
                move = json.loads(line)
                endpoint = str(move["endpoint"])
                set_index = int(move["set_index"])
                coordinate = int(move["coordinate"])
                step = int(move["step"])
                raw_rows = move["raw_rows"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                malformed.append(f"line {line_number}: {exc}")
                continue

            if step not in RMT_STEPS:
                malformed.append(f"line {line_number}: unsupported step {step}")
            key = (endpoint, set_index, coordinate, step)
            if key in move_keys:
                duplicate_keys.append(key)
            move_keys.add(key)
            if not isinstance(raw_rows, list) or any(not isinstance(row, int) for row in raw_rows):
                malformed.append(f"line {line_number}: raw_rows is not an integer list")
                continue
            for row in raw_rows:
                endpoint_row_sets[(endpoint, set_index)].add(row)
                target = (endpoint, set_index, row)
                if target in target_identities:
                    raw_coordinates[target].add(coordinate)

    return {
        "line_count": lines,
        "expected_line_count": expected_move_count,
        "line_count_matches": lines == expected_move_count,
        "move_keys": move_keys,
        "duplicate_keys": duplicate_keys,
        "malformed": malformed,
        "raw_coordinates": raw_coordinates,
        "endpoint_row_sets": endpoint_row_sets,
    }


def check_raw_support(
    targets: list[dict[str, Any]],
    raw_coordinates: dict[tuple[str, int, int], set[int]],
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    total_coordinates = 0
    for item in targets:
        key = target_key(item)
        actual = raw_coordinates.get(key, set())
        expected_count = int(item.get("all_raw_coordinates", -1))
        total_coordinates += len(actual)
        if len(actual) != expected_count:
            mismatches.append(
                {
                    "target": list(key),
                    "expected_count": expected_count,
                    "observed_count": len(actual),
                    "observed_coordinates": sorted(actual),
                }
            )
    return {
        "target_rows_checked": len(targets),
        "union_mismatch_count": len(mismatches),
        "union_mismatches": mismatches,
        "total_raw_support_coordinates": total_coordinates,
        "complete": not mismatches,
    }


def check_prefix_coverage(
    targets: list[dict[str, Any]],
    raw_coordinates: dict[tuple[str, int, int], set[int]],
    move_keys: set[tuple[str, int, int, int]],
) -> dict[str, Any]:
    required = 0
    present = 0
    missing: list[dict[str, Any]] = []
    per_target_missing: Counter[tuple[str, int, int]] = Counter()
    for item in targets:
        target = target_key(item)
        for coordinate in sorted(raw_coordinates.get(target, set())):
            for step in RMT_STEPS:
                required += 1
                key = (target[0], target[1], coordinate, step)
                if key in move_keys:
                    present += 1
                else:
                    per_target_missing[target] += 1
                    if len(missing) < 128:
                        missing.append(
                            {
                                "target": list(target),
                                "coordinate": coordinate,
                                "step": step,
                            }
                        )
    return {
        "required_prefix_keys": required,
        "present_prefix_keys": present,
        "missing_prefix_keys": required - present,
        "missing_target_count": len(per_target_missing),
        "missing_by_target_top": [
            {"target": list(target), "missing": count}
            for target, count in sorted(
                per_target_missing.items(), key=lambda item: (-item[1], item[0])
            )[:32]
        ],
        "missing_examples": missing,
        "complete": required == present,
    }


def check_replay_prefix_coverage(
    targets: list[dict[str, Any]],
    raw_coordinates: dict[tuple[str, int, int], set[int]],
    move_keys: set[tuple[str, int, int, int]],
    states: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    """Classify every raw-support prefix as replayable or unavailable by rule."""
    serialized_present = 0
    serialized_missing = 0
    replayable = 0
    unavailable = 0
    malformed_support: list[dict[str, Any]] = []
    per_target: list[dict[str, Any]] = []
    for item in targets:
        identity = target_key(item)
        state = states.get((identity[0], identity[1]))
        if state is None:
            malformed_support.append({"target": list(identity), "error": "missing endpoint state"})
            continue
        fixture = state["fixture"]
        permitted = fixture["permitted"]
        interior = set(fixture["interior_indices"])
        coordinates = sorted(raw_coordinates.get(identity, set()))
        row_report = {
            "target": list(identity),
            "support_size": len(coordinates),
            "legal_prefix_keys": 0,
            "unavailable_prefix_keys": 0,
            "serialized_prefix_keys": 0,
            "missing_serialized_prefix_keys": 0,
            "unavailable_coordinates": [],
            "legal_choice_counts": {},
        }
        for coordinate in coordinates:
            coordinate_unavailable = 0
            for step in RMT_STEPS:
                key = (identity[0], identity[1], coordinate, step)
                if key in move_keys:
                    serialized_present += 1
                    row_report["serialized_prefix_keys"] += 1
                else:
                    serialized_missing += 1
                    row_report["missing_serialized_prefix_keys"] += 1
                legal = (
                    coordinate in interior
                    and bool(permitted[coordinate])
                    and legal_value(state["weights"][coordinate], step) is not None
                )
                if legal:
                    replayable += 1
                    row_report["legal_prefix_keys"] += 1
                else:
                    unavailable += 1
                    coordinate_unavailable += 1
                    row_report["unavailable_prefix_keys"] += 1
            if coordinate_unavailable:
                row_report["unavailable_coordinates"].append(coordinate)
            row_report["legal_choice_counts"][str(coordinate)] = (
                1 + len(RMT_STEPS) - coordinate_unavailable
            )
        per_target.append(row_report)
    return {
        "serialized_prefix_keys": serialized_present,
        "missing_serialized_prefix_keys": serialized_missing,
        "replayable_prefix_keys": replayable,
        "unavailable_prefix_keys": unavailable,
        "raw_support_replay_complete": not malformed_support,
        "malformed_support": malformed_support,
        "per_target": per_target,
    }


def classify_target_domains(
    targets: list[dict[str, Any]],
    raw_coordinates: dict[tuple[str, int, int], set[int]],
    move_keys: set[tuple[str, int, int, int]],
) -> dict[str, Any]:
    """Describe each local domain without opening candidate replay.

    An empty raw-support set is a complete empty local domain.  It is safe to
    describe that local fact, but it is never promoted to a global statement
    about the endpoint or the full coordinate space.
    """

    records: list[dict[str, Any]] = []
    for item in targets:
        identity = target_key(item)
        coordinates = sorted(raw_coordinates.get(identity, set()))
        required = len(coordinates) * len(RMT_STEPS)
        present = sum(
            (identity[0], identity[1], coordinate, step) in move_keys
            for coordinate in coordinates
            for step in RMT_STEPS
        )
        empty = not coordinates
        records.append(
            {
                "endpoint": identity[0],
                "set_index": identity[1],
                "row": identity[2],
                "support_size": len(coordinates),
                "raw_support_coordinates": coordinates,
                "required_prefix_keys": required,
                "present_prefix_keys": present,
                "missing_prefix_keys": required - present,
                "complete_empty_domain": empty,
                "local_preflight_classification": (
                    "no-effect-within-complete-domain"
                    if empty
                    else "replay-gated__nonempty-support"
                ),
                "pair_replay_required": not empty,
                "triple_replay_required": not empty,
                "replay_findings_emitted": False,
                "global_impossibility_claim": False,
            }
        )
    empty_records = [item for item in records if item["complete_empty_domain"]]
    return {
        "records": records,
        "target_count": len(records),
        "empty_support_count": len(empty_records),
        "nonempty_support_count": len(records) - len(empty_records),
        "empty_support_rows": sorted(item["row"] for item in empty_records),
        "empty_support_complete": all(
            item["required_prefix_keys"] == 0
            and item["present_prefix_keys"] == 0
            and item["missing_prefix_keys"] == 0
            for item in empty_records
        ),
    }


def project_domain_costs(
    targets: list[dict[str, Any]],
    raw_coordinates: dict[tuple[str, int, int], set[int]],
    contract: dict[str, Any],
    replay_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project exhaustive domain sizes without executing any candidate."""

    choice_count = 1 + len(RMT_STEPS)
    coverage_by_target = {
        tuple(item["target"]): item
        for item in (replay_coverage or {}).get("per_target", [])
    }
    pair_limit = int(contract["budgets"]["max_pair_replays_per_row"])
    pair_total_limit = int(contract["budgets"]["max_pair_replays_total"])
    triple_limit = int(contract["budgets"]["max_triple_replays_per_row"])
    triple_total_limit = int(contract["budgets"]["max_triple_replays_total"])
    row_costs: list[dict[str, Any]] = []
    support_sizes: list[int] = []
    pair_total = 0
    triple_total = 0
    pair_rows_over_limit = 0
    triple_rows_within_limit = 0
    triple_rows_over_limit = 0
    for item in targets:
        identity = target_key(item)
        coordinates = sorted(raw_coordinates.get(identity, set()))
        support_size = len(coordinates)
        coverage = coverage_by_target.get(identity, {})
        legal_counts = {
            int(coordinate): int(count)
            for coordinate, count in coverage.get("legal_choice_counts", {}).items()
        }
        legal_counts = {coordinate: legal_counts.get(coordinate, choice_count) for coordinate in coordinates}
        pair_candidates = sum(
            legal_counts[left] * legal_counts[right]
            for index, left in enumerate(coordinates)
            for right in coordinates[index + 1 :]
        )
        triple_candidates = sum(
            legal_counts[left] * legal_counts[middle] * legal_counts[right]
            for index, left in enumerate(coordinates)
            for middle_index, middle in enumerate(coordinates[index + 1 :], start=index + 1)
            for right in coordinates[middle_index + 1 :]
        )
        pair_total += pair_candidates
        triple_total += triple_candidates
        support_sizes.append(support_size)
        pair_within = pair_candidates <= pair_limit
        triple_within = triple_candidates <= triple_limit
        pair_rows_over_limit += not pair_within
        triple_rows_within_limit += triple_within
        triple_rows_over_limit += not triple_within
        row_costs.append(
            {
                "endpoint": identity[0],
                "set_index": identity[1],
                "row": identity[2],
                "support_size": support_size,
                "choice_count_default": choice_count,
                "legal_choice_counts": legal_counts,
                "exact_pair_candidates": pair_candidates,
                "pair_within_row_budget": pair_within,
                "exact_triple_candidates": triple_candidates,
                "triple_within_row_budget": triple_within,
            }
        )
    median_support = statistics.median(support_sizes) if support_sizes else 0
    if isinstance(median_support, float) and median_support.is_integer():
        median_support = int(median_support)
    return {
        "domain_definition": "zero plus ten signed prefixes",
        "choice_count_per_coordinate": choice_count,
        "support_size_summary": {
            "minimum": min(support_sizes, default=0),
            "median": median_support,
            "maximum": max(support_sizes, default=0),
            "target_count": len(support_sizes),
        },
        "pair": {
            "exact_total_candidates": pair_total,
            "per_row_budget": pair_limit,
            "total_budget": pair_total_limit,
            "within_total_budget": pair_total <= pair_total_limit,
            "rows_over_per_row_budget": pair_rows_over_limit,
        },
        "triple": {
            "exact_total_candidates": triple_total,
            "per_row_budget": triple_limit,
            "total_budget": triple_total_limit,
            "within_total_budget": triple_total <= triple_total_limit,
            "rows_within_per_row_budget": triple_rows_within_limit,
            "rows_over_per_row_budget": triple_rows_over_limit,
            "global_truncation_required": triple_total > triple_total_limit,
        },
        "fixed_schedule": contract["replay"]["ordering"],
        "support_size_priority_used": False,
        "residual_mass_priority_used": False,
        "classification_guard": {
            "incomplete_global_triple_domain": "higher-order-or-untested",
            "incomplete_per_row_triple_domain": "higher-order-or-untested",
            "no_effect_within_complete_domain_requires": "complete declared local domain",
            "global_impossibility_claim": False,
        },
        "per_target": row_costs,
    }


def build_receipt() -> dict[str, Any]:
    root = protocol_root()
    contract_path = root / "CONTRACT.json"
    contract = load_json(contract_path)
    receipt: dict[str, Any] = {
        "protocol": "Q10-NA",
        "scope": "NA-0/NA-1/NA-2 preflight only",
        "engineering_only": True,
        "scientific_seed_bundles_used": 0,
        "behavioral_inference": False,
        "canonical_repair_applied": False,
        "dh08b_authorized": False,
        "replay_findings_emitted": False,
        "status": HASH_ERROR_STATUS,
        "parent": {},
        "targets": {},
        "raw_support": {},
        "prefix_coverage": {},
        "cost_projection": {},
        "errors": [],
        "writes": ["qualification/preflight.json", "STATUS.json"],
    }

    try:
        if contract.get("protocol") != "Q10-NA":
            raise ValueError("CONTRACT.json protocol is not Q10-NA")
        if int(contract.get("version", -1)) != 2:
            raise ValueError("unsupported Q10-NA contract version")
        parent, canonical_receipt = parent_paths(contract)
        receipt["parent"]["root"] = str(parent)
        receipt["parent"]["receipt_root"] = str(canonical_receipt)

        hash_report = verify_expected_hashes(parent, canonical_receipt, contract)
        receipt["parent"]["hashes"] = hash_report
        if hash_report["missing"] or hash_report["mismatches"]:
            receipt["errors"].append("parent hash or manifest verification failed")
            return receipt

        replay_states, replay_input_report, replay_input_errors = verify_replay_inputs(contract)
        receipt["parent"]["replay_inputs"] = replay_input_report
        receipt["errors"].extend(replay_input_errors)

        schema = verify_parent_schema(canonical_receipt)
        receipt["parent"]["schema"] = {
            "status": schema["execution"].get("status"),
            "primary_valid_endpoints": len(schema["endpoints"]),
            "excluded_endpoints": len(schema["excluded"]),
            "mismatch_rows": len(schema["rows"]),
            "expected_move_lines": schema["endpoint_move_counts"],
        }
        receipt["errors"].extend(schema["errors"])
        targets, target_errors = collect_targets(schema["rows"])
        receipt["targets"] = {
            "expected": 326,
            "observed": len(targets),
            "unique_identities": len({target_key(item) for item in targets}),
            "identity_definition": ["endpoint", "set_index", "row"],
            "errors": target_errors,
        }
        receipt["errors"].extend(target_errors)

        target_replay = verify_target_replays(targets, replay_states)
        receipt["parent"]["target_replay"] = target_replay
        if not target_replay["complete"]:
            receipt["errors"].append("reconstructed endpoint or target bit mismatch")

        moves = collect_moves(
            canonical_receipt,
            targets,
            schema["endpoint_move_counts"],
        )
        receipt["parent"]["moves"] = {
            "line_count": moves["line_count"],
            "expected_line_count": moves["expected_line_count"],
            "line_count_matches": moves["line_count_matches"],
            "unique_endpoint_coordinate_step_keys": len(moves["move_keys"]),
            "duplicate_key_count": len(moves["duplicate_keys"]),
            "malformed_line_count": len(moves["malformed"]),
        }
        if not moves["line_count_matches"]:
            receipt["errors"].append("moves.jsonl line count differs from sealed endpoint receipts")
        if moves["duplicate_keys"]:
            receipt["errors"].append("duplicate endpoint-coordinate-step move key")
        if moves["malformed"]:
            receipt["errors"].append("malformed move record")

        raw_report = check_raw_support(targets, moves["raw_coordinates"])
        receipt["raw_support"] = raw_report
        if not raw_report["complete"]:
            receipt["errors"].append("raw-support union mismatch")

        serialized_prefix_report = check_prefix_coverage(
            targets,
            moves["raw_coordinates"],
            moves["move_keys"],
        )
        replay_prefix_report = check_replay_prefix_coverage(
            targets,
            moves["raw_coordinates"],
            moves["move_keys"],
            replay_states,
        )
        receipt["prefix_coverage"] = {
            "serialized": serialized_prefix_report,
            "replay": replay_prefix_report,
            "serialized_coverage_is_not_legality": True,
        }
        if not replay_prefix_report["raw_support_replay_complete"]:
            receipt["errors"].append("raw-support endpoint state could not be replayed")

        domain_report = classify_target_domains(
            targets,
            moves["raw_coordinates"],
            moves["move_keys"],
        )
        receipt["targets"]["domain_records"] = domain_report["records"]
        replay_by_target = {
            tuple(item["target"]): item
            for item in replay_prefix_report["per_target"]
        }
        for record in receipt["targets"]["domain_records"]:
            coverage = replay_by_target.get(
                (record["endpoint"], record["set_index"], record["row"]),
                {},
            )
            record["serialized_prefix_keys"] = coverage.get("serialized_prefix_keys", 0)
            record["missing_serialized_prefix_keys"] = coverage.get(
                "missing_serialized_prefix_keys", 0
            )
            record["replayable_prefix_keys"] = coverage.get("legal_prefix_keys", 0)
            record["unavailable_prefix_keys"] = coverage.get("unavailable_prefix_keys", 0)
            record["legal_choice_counts"] = coverage.get("legal_choice_counts", {})
            record["replay_domain_complete"] = True
        receipt["targets"]["empty_support_summary"] = {
            "empty_support_count": domain_report["empty_support_count"],
            "nonempty_support_count": domain_report["nonempty_support_count"],
            "empty_support_rows": domain_report["empty_support_rows"],
            "empty_support_complete": domain_report["empty_support_complete"],
            "classification_scope": "local-domain-only",
            "global_impossibility_claim": False,
        }
        if domain_report["empty_support_count"] != 2:
            receipt["errors"].append(
                "expected exactly two zero-raw-support target rows in the sealed parent"
            )
        if domain_report["empty_support_rows"] != [251, 251]:
            receipt["errors"].append(
                "zero-raw-support target rows are not the two sealed row-251 targets"
            )
        if not domain_report["empty_support_complete"]:
            receipt["errors"].append("empty raw-support domain is not complete")

        cost_report = project_domain_costs(
            targets,
            moves["raw_coordinates"],
            contract,
            replay_prefix_report,
        )
        receipt["cost_projection"] = cost_report
        for target_record, cost_record in zip(
            receipt["targets"]["domain_records"], cost_report["per_target"]
        ):
            target_record.update(
                {
                    "exact_pair_candidates": cost_record["exact_pair_candidates"],
                    "pair_within_row_budget": cost_record["pair_within_row_budget"],
                    "exact_triple_candidates": cost_record["exact_triple_candidates"],
                    "triple_within_row_budget": cost_record["triple_within_row_budget"],
                }
            )

        if receipt["errors"]:
            receipt["status"] = HASH_ERROR_STATUS
        else:
            receipt["status"] = EXPECTED_NA_STATUS
        return receipt
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        receipt["errors"].append(f"preflight exception: {type(exc).__name__}: {exc}")
        return receipt


def write_outputs(receipt: dict[str, Any]) -> tuple[Path, Path]:
    root = protocol_root()
    qualification = root / "qualification"
    preflight_path = qualification / "preflight.json"
    status_path = root / "STATUS.json"
    if not inside_protocol(preflight_path) or not inside_protocol(status_path):
        raise RuntimeError("refusing to write outside q10-na-v1")
    write_json(preflight_path, receipt)
    status = {
        "protocol": "Q10-NA",
        "status": receipt["status"],
        "preflight_receipt": "qualification/preflight.json",
        "replay_findings_emitted": False,
        "scientific_seed_bundles_used": 0,
        "behavioral_inference": False,
        "canonical_repair_applied": False,
        "dh08b_authorized": False,
        "target_rows": receipt.get("targets", {}).get("observed", 0),
        "empty_support_targets": receipt.get("targets", {})
        .get("empty_support_summary", {})
        .get("empty_support_count", 0),
        "nonempty_support_targets": receipt.get("targets", {})
        .get("empty_support_summary", {})
        .get("nonempty_support_count", 0),
        "raw_support_union_mismatches": receipt.get("raw_support", {}).get(
            "union_mismatch_count", 0
        ),
        "missing_serialized_prefix_keys": receipt.get("prefix_coverage", {})
        .get("serialized", {})
        .get("missing_prefix_keys", 0),
        "replayable_prefix_keys": receipt.get("prefix_coverage", {})
        .get("replay", {})
        .get("replayable_prefix_keys", 0),
        "unavailable_prefix_keys": receipt.get("prefix_coverage", {})
        .get("replay", {})
        .get("unavailable_prefix_keys", 0),
        "exact_pair_candidates": receipt.get("cost_projection", {})
        .get("pair", {})
        .get("exact_total_candidates", 0),
        "exact_triple_candidates": receipt.get("cost_projection", {})
        .get("triple", {})
        .get("exact_total_candidates", 0),
        "triple_total_budget_exceeded": receipt.get("cost_projection", {})
        .get("triple", {})
        .get("global_truncation_required", False),
        "incomplete_triple_classification": receipt.get("cost_projection", {})
        .get("classification_guard", {})
        .get("incomplete_global_triple_domain"),
    }
    write_json(status_path, status)
    return preflight_path, status_path


def main() -> int:
    receipt = build_receipt()
    preflight_path, status_path = write_outputs(receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "preflight": str(preflight_path),
                "status_file": str(status_path),
                "targets": receipt.get("targets", {}).get("observed", 0),
                "raw_support_union_mismatches": receipt.get("raw_support", {}).get(
                    "union_mismatch_count", 0
                ),
                "missing_serialized_prefix_keys": receipt.get("prefix_coverage", {})
                .get("serialized", {})
                .get("missing_prefix_keys", 0),
                "replayable_prefix_keys": receipt.get("prefix_coverage", {})
                .get("replay", {})
                .get("replayable_prefix_keys", 0),
                "replay_findings_emitted": False,
            },
            sort_keys=True,
        )
    )
    if receipt["status"] == EXPECTED_NA_STATUS:
        return 0
    return 2 if receipt["status"] == BLOCKED_NA_STATUS else 3


if __name__ == "__main__":
    raise SystemExit(main())

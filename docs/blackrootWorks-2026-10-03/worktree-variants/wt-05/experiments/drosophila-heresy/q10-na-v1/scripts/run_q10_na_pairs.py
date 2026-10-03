"""Exact pair-only Q10-NA engineering replay.

The default invocation is a two-row dry run. ``--full`` is required for the
declared 324 nonempty target rows. No canonical model or scientific seed is
ever mutated or opened.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
import qualify_q10_na as na  # noqa: E402


PAIR_LIMIT_PER_ROW = 131_072
PAIR_LIMIT_TOTAL = 25_000_000
CHOICES = (0,) + na.RMT_STEPS


def ordered_bits(raw: int) -> int:
    if (raw & 0x7FFF_FFFF) == 0:
        raw = 0x8000_0000
    magnitude = raw & 0x7FFF_FFFF
    return 0x8000_0000 - magnitude if raw & 0x8000_0000 else 0x8000_0000 + raw


def ulp_distance(left: float, right: float) -> int:
    return abs(ordered_bits(na.bits(left)) - ordered_bits(na.bits(right)))


def geometry_signature(weights: list[float], fixture: dict[str, Any]) -> dict[str, float]:
    base = [na.from_bits(value) for value in fixture["snapshot_base_bits"]]
    axis = fixture["acquisition_axis"]
    displacement = [value - initial for value, initial in zip(weights, base)]
    linear = [
        math.fsum(displacement[coordinate] for coordinate in row)
        for row in fixture["operator"]["rows"]
    ]
    return {
        "axis": math.fsum(value * direction for value, direction in zip(displacement, axis)),
        "norm": math.sqrt(math.fsum(value * value for value in displacement)),
        "linear_l2": math.sqrt(math.fsum(value * value for value in linear)),
        "linear_max_abs": max((abs(value) for value in linear), default=0.0),
    }


def candidate_weights(state: dict[str, Any], assignments: tuple[tuple[int, int], ...]) -> list[float]:
    weights = state["weights"][:]
    for coordinate, choice in assignments:
        weights[coordinate] = na.prefix_value(weights[coordinate], choice)
    return weights


def row_value(state: dict[str, Any], weights: list[float], row: int) -> float:
    return na.sequential(state["fixture"]["operator"]["rows"][row], weights)


def row_value_assignments(
    state: dict[str, Any], row: int, assignments: tuple[tuple[int, int], ...]
) -> float:
    replacements = {
        coordinate: na.prefix_value(state["weights"][coordinate], choice)
        for coordinate, choice in assignments
        if choice != 0
    }
    value = na.from_bits(0x8000_0000)
    for coordinate in state["fixture"]["operator"]["rows"][row]:
        value = na.f32(value + replacements.get(coordinate, state["weights"][coordinate]))
    return value


def prepare() -> tuple[dict[str, Any], list[dict[str, Any]], dict[tuple[str, int], dict[str, Any]], dict[tuple[str, int, int], set[int]]]:
    root = na.protocol_root()
    contract = na.load_json(root / "CONTRACT.json")
    if contract.get("protocol") != "Q10-NA" or contract.get("version") != 2:
        raise RuntimeError("Q10-NA v2 contract is required")
    parent, receipt = na.parent_paths(contract)
    hashes = na.verify_expected_hashes(parent, receipt, contract)
    if hashes["missing"] or hashes["mismatches"]:
        raise RuntimeError("Q10-NA parent hash gate failed")
    states, _, replay_errors = na.verify_replay_inputs(contract)
    if replay_errors or len(states) != 28:
        raise RuntimeError(f"Q10-NA replay-input gate failed: {replay_errors[:3]}")
    schema = na.verify_parent_schema(receipt)
    if schema["errors"]:
        raise RuntimeError(f"Q10-RMT schema gate failed: {schema['errors']}")
    targets, target_errors = na.collect_targets(schema["rows"])
    if target_errors or len(targets) != 326:
        raise RuntimeError(f"Q10-NA target gate failed: {target_errors[:3]}")
    moves = na.collect_moves(receipt, targets, schema["endpoint_move_counts"])
    if moves["duplicate_keys"] or moves["malformed"] or not moves["line_count_matches"]:
        raise RuntimeError("Q10-NA serialized move gate failed")
    raw = na.check_raw_support(targets, moves["raw_coordinates"])
    if not raw["complete"]:
        raise RuntimeError("Q10-NA raw-support union gate failed")
    replay = na.check_replay_prefix_coverage(
        targets, moves["raw_coordinates"], moves["move_keys"], states
    )
    if not replay["raw_support_replay_complete"] or replay["unavailable_prefix_keys"]:
        raise RuntimeError("Q10-NA deterministic prefix replay gate failed")
    target_replay = na.verify_target_replays(targets, states)
    if not target_replay["complete"]:
        raise RuntimeError("Q10-NA baseline/target bit gate failed")
    return contract, targets, states, moves["raw_coordinates"]


def legal_choices(state: dict[str, Any], coordinate: int) -> tuple[int, ...]:
    choices = [0]
    for choice in na.RMT_STEPS:
        if na.legal_value(state["weights"][coordinate], choice) is not None:
            choices.append(choice)
    return tuple(choices)


def run_target(
    target: dict[str, Any],
    state: dict[str, Any],
    coordinates: set[int],
    remaining_budget: int,
) -> dict[str, Any]:
    row = int(target["row"])
    baseline = na.from_bits(int(target["baseline_bits"]))
    target_value = na.from_bits(int(target["target_bits"]))
    baseline_ulp = int(target["baseline_ulp_distance"])
    ordered_coordinates = sorted(coordinates)
    domains = {coordinate: legal_choices(state, coordinate) for coordinate in ordered_coordinates}
    individual_replays = 0
    individual_helpful: list[dict[str, Any]] = []
    for coordinate in ordered_coordinates:
        for choice in domains[coordinate]:
            if choice == 0:
                continue
            actual = row_value_assignments(state, row, ((coordinate, choice),))
            individual_replays += 1
            distance = ulp_distance(actual, target_value)
            if distance < baseline_ulp:
                individual_helpful.append({"coordinate": coordinate, "choice": choice, "ulp": distance})
    if individual_helpful:
        raise RuntimeError(f"parent individual-helpfulness invariant violated at {target}")

    pair_domain = sum(
        len(domains[left]) * len(domains[right])
        for index, left in enumerate(ordered_coordinates)
        for right in ordered_coordinates[index + 1 :]
    )
    if pair_domain > PAIR_LIMIT_PER_ROW or pair_domain > remaining_budget:
        return {
            "target": [target["endpoint"], target["set_index"], row],
            "support_size": len(ordered_coordinates),
            "individual_replays": individual_replays,
            "pair_domain": pair_domain,
            "pair_replays": 0,
            "pair_domain_complete": False,
            "classification": "higher-order-or-untested",
            "improving_pair_count": 0,
            "best": None,
            "geometry": None,
        }

    best: dict[str, Any] | None = None
    pair_replays = 0
    improving = 0
    for left_index, left in enumerate(ordered_coordinates):
        for right in ordered_coordinates[left_index + 1 :]:
            for left_choice, right_choice in itertools.product(domains[left], domains[right]):
                assignments = ((left, left_choice), (right, right_choice))
                actual = row_value_assignments(state, row, assignments)
                distance = ulp_distance(actual, target_value)
                pair_replays += 1
                if distance < baseline_ulp:
                    improving += 1
                    candidate = candidate_weights(state, assignments)
                    record = {
                        "coordinates": [left, right],
                        "choices": [left_choice, right_choice],
                        "observed_bits": na.bits(actual),
                        "target_bits": int(target["target_bits"]),
                        "baseline_ulp": baseline_ulp,
                        "candidate_ulp": distance,
                        "geometry": geometry_signature(candidate, state["fixture"]),
                    }
                    if best is None or (distance, left, right, left_choice, right_choice) < (
                        best["candidate_ulp"],
                        best["coordinates"][0],
                        best["coordinates"][1],
                        best["choices"][0],
                        best["choices"][1],
                    ):
                        best = record
    return {
        "target": [target["endpoint"], target["set_index"], row],
        "support_size": len(ordered_coordinates),
        "individual_replays": individual_replays,
        "pair_domain": pair_domain,
        "pair_replays": pair_replays,
        "pair_domain_complete": pair_replays == pair_domain,
        "classification": "pair" if improving else "no-effect-within-complete-domain",
        "improving_pair_count": improving,
        "best": best,
        "geometry": best["geometry"] if best else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-targets", type=int, default=2)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("qualification/pair-dry-run.json"))
    args = parser.parse_args()
    contract, targets, states, raw_coordinates = prepare()
    nonempty = [
        target for target in targets
        if raw_coordinates.get((target["endpoint"], target["set_index"], target["row"]), set())
    ]
    selected = nonempty if args.full else nonempty[: max(0, args.limit_targets)]
    if not selected:
        raise RuntimeError("pair run selected no nonempty targets")
    remaining = PAIR_LIMIT_TOTAL
    records: list[dict[str, Any]] = []
    for target in selected:
        key = (target["endpoint"], target["set_index"])
        record = run_target(target, states[key], raw_coordinates[(target["endpoint"], target["set_index"], target["row"])], remaining)
        remaining -= int(record["pair_replays"])
        records.append(record)
    output = na.protocol_root() / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "protocol": "Q10-NA",
        "stage": "PAIR_REPLAY_DRY_RUN" if not args.full else "PAIR_REPLAY_FULL",
        "engineering_only": True,
        "contract_plan_sha256": contract["plan_sha256"],
        "target_rows_requested": len(selected),
        "target_rows_replayed": len(records),
        "scientific_seed_bundles_used": 0,
        "behavioral_inference": False,
        "canonical_repair_applied": False,
        "dh08b_authorized": False,
        "triple_replay_executed": False,
        "remaining_pair_budget": remaining,
        "records": records,
    }
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "targets": len(records), "pair_replays": sum(item["pair_replays"] for item in records), "triple_replay_executed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

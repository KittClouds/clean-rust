"""Run Q10-RH1-AC2 against the real PF5 learner machinery."""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PF5_ROOT = REPO / "experiments/drosophila-heresy/q10-pf5-v1"
CQ_ROOT = REPO / "experiments/drosophila-heresy/q10-rh1-cq1-v1/scripts"
sys.path.insert(0, str(CQ_ROOT))
sys.path.insert(0, str(PF5_ROOT / "scripts"))
import common_runtime as CQ  # noqa: E402
import run_q10_pf5 as PF5  # noqa: E402


OUT_ROOT = ROOT / "qualification"
EFFECTS_PATH = OUT_ROOT / "effects.jsonl"
FEATURES_PATH = OUT_ROOT / "features.jsonl"
PREFIX_DOMAIN = tuple(PF5.CHOICES)


def verify_contract() -> dict[str, Any]:
    contract = CQ.load_json(ROOT / "CONTRACT.json")
    preexecution = CQ.load_json(ROOT / "PREEXECUTION.json")
    CQ.require(preexecution["plan_sha256"] == CQ.digest(ROOT / "PLAN.md"), "AC2 plan hash drift")
    CQ.require(preexecution["contract_sha256"] == CQ.digest(ROOT / "CONTRACT.json"), "AC2 contract hash drift")
    bindings: dict[str, str] = {}
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        CQ.require(path.is_file(), f"missing AC2 parent: {binding['label']}")
        actual = CQ.digest(path)
        CQ.require(actual == binding["sha256"].upper(), f"AC2 parent drift: {binding['label']}")
        bindings[binding["label"]] = actual
    return bindings


def support_index(state: Any) -> tuple[dict[int, list[int]], dict[int, list[tuple[int, int]]]]:
    rows_by_coordinate: dict[int, list[int]] = defaultdict(list)
    counts_by_coordinate: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for row_index, row in enumerate(state.rows):
        counts = Counter(row)
        for coordinate, count in sorted(counts.items()):
            rows_by_coordinate[coordinate].append(row_index)
            counts_by_coordinate[coordinate].append((row_index, count))
    return dict(rows_by_coordinate), dict(counts_by_coordinate)


def geometry_for_coordinate(state: Any, coordinate: int, candidate_weight: float) -> dict[str, float]:
    old_weight = state.baseline_weights[coordinate]
    delta = candidate_weight - old_weight
    final_axis = state.baseline_axis + delta * state.axis[coordinate]
    old_displacement = state.baseline_displacement[coordinate]
    new_displacement = candidate_weight - state.base_weights[coordinate]
    final_norm = math.sqrt(max(
        state.baseline_norm * state.baseline_norm
        - old_displacement * old_displacement
        + new_displacement * new_displacement,
        0.0,
    ))
    cue_squared = state.baseline_drive_squared
    for row_index, multiplicity in state.support_counts[coordinate]:
        old_error = state.baseline_drive_errors[row_index]
        new_error = old_error + delta * multiplicity
        cue_squared += new_error * new_error - old_error * old_error
    cue_error = math.sqrt(max(cue_squared, 0.0))
    axis_scale = max(abs(state.target_axis), 1.0e-12)
    norm_scale = max(state.target_norm, 1.0e-12)
    return {
        "axis_normalized_error": abs(final_axis - state.target_axis) / axis_scale,
        "norm_normalized_error": abs(final_norm - state.target_norm) / norm_scale,
        "cue_linear_normalized_error": cue_error / state.cue_scale,
        "final_axis": final_axis,
        "target_axis": state.target_axis,
        "final_norm": final_norm,
        "target_norm": state.target_norm,
    }


def prefix_record(state: Any, coordinate: int, choice: int, support_rows: list[int]) -> dict[str, Any] | None:
    raw = PF5.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
    if raw is None:
        return None
    candidate_weight = PF5.from_bits(raw)
    effect_bits: list[int] = []
    changed_rows: list[int] = []
    helpful_rows: list[int] = []
    for row_index in support_rows:
        actual = PF5._sequential_bits_with_replacement(
            state.rows[row_index], state.baseline_weights, coordinate, candidate_weight
        )
        effect_bits.append(actual)
        if actual != state.baseline_readout_bits[row_index]:
            changed_rows.append(row_index)
        before = PF5.ulp_distance(
            PF5.from_bits(state.baseline_readout_bits[row_index]),
            PF5.from_bits(state.target_readout_bits[row_index]),
        )
        after = PF5.ulp_distance(
            PF5.from_bits(actual),
            PF5.from_bits(state.target_readout_bits[row_index]),
        )
        if after < before:
            helpful_rows.append(row_index)
    CQ.require(len(effect_bits) == len(support_rows), f"missing AC2 row effect: {state.key} {coordinate} {choice}")
    CQ.require(all(math.isfinite(PF5.from_bits(value)) for value in effect_bits), "non-finite AC2 effect")
    return {
        "choice": choice,
        "weight_bits": raw,
        "changed_rows": changed_rows,
        "helpful_rows": helpful_rows,
        "effect_bits": effect_bits,
        "geometry": geometry_for_coordinate(state, coordinate, candidate_weight),
    }


def build_pair_record(state: Any, coordinate: int, support_rows: list[int]) -> dict[str, Any]:
    prefixes: list[dict[str, Any]] = []
    illegal: list[int] = []
    for choice in PREFIX_DOMAIN:
        record = prefix_record(state, coordinate, choice, support_rows)
        if record is None:
            illegal.append(choice)
        else:
            prefixes.append(record)
    legal_choices = [record["choice"] for record in prefixes]
    CQ.require(set(legal_choices) | set(illegal) == set(PREFIX_DOMAIN), "AC2 prefix domain not fully accounted for")
    CQ.require(not (set(legal_choices) & set(illegal)), "AC2 prefix classified both legal and illegal")
    return {
        "endpoint": state.key[0],
        "set_index": state.key[1],
        "coordinate": coordinate,
        "support_rows": support_rows,
        "support_row_count": len(support_rows),
        "legal_prefixes": prefixes,
        "illegal_prefixes": illegal,
        "prefix_domain_complete": True,
        "physical_support_complete": all(len(item["effect_bits"]) == len(support_rows) for item in prefixes),
        "finite_effects": True,
    }


def selected_pairs(groups: list[dict[str, Any]]) -> dict[tuple[str, int], set[int]]:
    result: dict[tuple[str, int], set[int]] = defaultdict(set)
    for group in groups:
        key = (group["endpoint"], group["set_index"])
        result[key].update(group["coordinates"])
    return dict(result)


def derive_features(
    groups: list[dict[str, Any]],
    state_by_key: dict[tuple[str, int], Any],
    records_by_pair: dict[tuple[str, int, int], dict[str, Any]],
) -> tuple[int, int]:
    feature_count = 0
    collateral_records = 0
    with FEATURES_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for group in groups:
            key = (group["endpoint"], group["set_index"])
            state = state_by_key[key]
            target_bits = state.target_readout_bits
            for coordinate in group["coordinates"]:
                pair = records_by_pair[(key[0], key[1], coordinate)]
                support_rows = pair["support_rows"]
                declared_rows = sorted(set(group["rows"]) & set(support_rows))
                row_position = {row: index for index, row in enumerate(support_rows)}
                helpful_rows: set[int] = set()
                first_helpful: dict[int, int] = {}
                collateral_by_prefix: list[int] = []
                for prefix in pair["legal_prefixes"]:
                    choice = int(prefix["choice"])
                    effect_bits = prefix["effect_bits"]
                    collateral = 0
                    for row in declared_rows:
                        position = row_position[row]
                        baseline = state.baseline_readout_bits[row]
                        target = target_bits[row]
                        actual = int(effect_bits[position])
                        before = PF5.ulp_distance(PF5.from_bits(baseline), PF5.from_bits(target))
                        after = PF5.ulp_distance(PF5.from_bits(actual), PF5.from_bits(target))
                        if after < before:
                            helpful_rows.add(row)
                            first_helpful.setdefault(row, abs(choice))
                        if before == 0 and actual != baseline:
                            collateral += 1
                    collateral_by_prefix.append(collateral)
                burden = sum(
                    PF5.ulp_distance(
                        PF5.from_bits(state.baseline_readout_bits[row]),
                        PF5.from_bits(target_bits[row]),
                    )
                    for row in helpful_rows
                )
                feature = {
                    "endpoint": key[0],
                    "set_index": key[1],
                    "group_index": group["group_index"],
                    "coordinate": coordinate,
                    "declared_row_count": len(declared_rows),
                    "helpful_row_count": len(helpful_rows),
                    "helpful_ulp_burden": burden,
                    "first_helpful_scale_median": statistics.median(first_helpful.values()) if first_helpful else None,
                    "helpful_rows": sorted(helpful_rows),
                    "minimum_collateral_exact_support_rows": min(collateral_by_prefix, default=0),
                    "legal_prefixes": [int(item["choice"]) for item in pair["legal_prefixes"]],
                    "illegal_prefixes": [int(choice) for choice in pair["illegal_prefixes"]],
                    "complete": bool(pair["prefix_domain_complete"] and pair["physical_support_complete"]),
                }
                CQ.require(feature["complete"], "AC2 incomplete feature record")
                handle.write(json.dumps(feature, separators=(",", ":")) + "\n")
                feature_count += 1
                collateral_records += int(bool(collateral_by_prefix))
    return feature_count, collateral_records


def run() -> dict[str, Any]:
    bindings = verify_contract()
    groups = CQ.load_groups()
    required = selected_pairs(groups)
    lineage = PF5.load_lineage(PF5_ROOT)
    states = PF5.load_endpoint_states(lineage, selected_keys=set(required))
    state_by_key = {state.key: state for state in states}
    CQ.require(set(state_by_key) == set(required), "AC2 endpoint cohort drift")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if EFFECTS_PATH.exists():
        EFFECTS_PATH.unlink()
    pair_count = 0
    prefix_count = 0
    illegal_count = 0
    support_rows_total = 0
    records_by_pair: dict[tuple[str, int, int], dict[str, Any]] = {}
    with EFFECTS_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for key in sorted(required):
            state = state_by_key[key]
            rows_by_coordinate, _ = support_index(state)
            for coordinate in sorted(required[key]):
                support_rows = rows_by_coordinate.get(coordinate, [])
                CQ.require(support_rows, f"AC2 coordinate has no physical support: {key} {coordinate}")
                record = build_pair_record(state, coordinate, support_rows)
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                records_by_pair[(key[0], key[1], coordinate)] = record
                pair_count += 1
                prefix_count += len(record["legal_prefixes"])
                illegal_count += len(record["illegal_prefixes"])
                support_rows_total += record["support_row_count"]
    effect_hash = CQ.digest(EFFECTS_PATH)
    feature_count, collateral_records = derive_features(groups, state_by_key, records_by_pair)
    feature_hash = CQ.digest(FEATURES_PATH)
    summary = {
        "protocol": "Q10-PF6-RH1-AC2",
        "status": "AC2_COMPLETE_AUTHORITY_TABLE_NO_FACTORIAL",
        "parent_bindings_verified": bindings,
        "groups": len(groups),
        "endpoints": len(states),
        "unique_endpoint_coordinate_pairs": pair_count,
        "legal_prefix_records": prefix_count,
        "illegal_prefix_records": illegal_count,
        "declared_prefix_domain_size": len(PREFIX_DOMAIN),
        "support_rows_total": support_rows_total,
        "effects_sha256": effect_hash,
        "features_sha256": feature_hash,
        "feature_records": feature_count,
        "feature_records_complete": feature_count == 2707,
        "collateral_feature_records": collateral_records,
        "all_pairs_complete": pair_count == 2707,
        "all_legal_prefixes_accounted": prefix_count + illegal_count == pair_count * len(PREFIX_DOMAIN),
        "all_physical_support_effects_complete": True,
        "scope": {
            "ranking": False,
            "beam_search": False,
            "measured_factorial_started": False,
            "scientific_seed_bundles": 0,
            "behavioral_probe": False,
            "dh08b_authorized": False,
        },
    }
    (OUT_ROOT / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (OUT_ROOT / "RESULT.md").write_text(
        "\n".join([
            "# Q10-RH1-AC2 result",
            "",
            "Complete real-learner authority table for the frozen RH1 cohort.",
            "",
            f"Status: `{summary['status']}`.",
            f"Unique endpoint-coordinate pairs: {pair_count}.",
            f"Legal prefix records: {prefix_count}; illegal measured domain members: {illegal_count}.",
            f"Physical support rows retained: {support_rows_total}.",
            f"Effects SHA-256: `{effect_hash}`.",
            f"Derived complete feature records: {feature_count}; features SHA-256: `{feature_hash}`.",
            "All effects were generated from committed f32 weights with exact learner-order sequential-f32 replay.",
            "No ranking, beam search, RH1 factorial, scientific seed, behavioral, or DH08B work ran.",
        ]) + "\n",
        encoding="utf-8",
    )
    status = {
        "protocol": "Q10-PF6-RH1-AC2",
        "status": summary["status"],
        "summary_sha256": CQ.digest(OUT_ROOT / "SUMMARY.json"),
        "effects_sha256": effect_hash,
        "features_sha256": feature_hash,
        "feature_records": feature_count,
        "unique_endpoint_coordinate_pairs": pair_count,
        "measured_factorial_started": False,
        "scientific_seed_bundles": 0,
        "behavioral_probe": False,
        "dh08b_authorized": False,
    }
    (OUT_ROOT / "STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))

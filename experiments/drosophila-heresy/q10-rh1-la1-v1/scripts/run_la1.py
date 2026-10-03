"""Q10-RH1-LA1 receipt-backed late-authority endpoint audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
F2_ROOT = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1"
F2_EXECUTION = F2_ROOT / "qualification/execution/execution.json"
F2_SUMMARY = F2_ROOT / "qualification/derived/SUMMARY.json"
F2_INTERPRETATION = F2_ROOT / "qualification/INTERPRETATION.json"
F2_SCRIPT_ROOT = F2_ROOT / "scripts"
sys.path.insert(0, str(F2_SCRIPT_ROOT))
import run_rh1 as F2  # noqa: E402

PF5 = F2.PF5


SCORE_FIELDS = (
    "mismatch_count",
    "total_ulp_distance",
    "residual_l2",
    "maximum_absolute_residual",
)
ACTUAL_ENDPOINTS = (
    "W0",
    "historical_authority_h16",
    "authority_h32_full",
)
COUNTERFACTUAL_ENDPOINTS = (
    "authority_h32_early_ranks_1_16",
    "authority_h32_late_only_ranks_17_32",
)


class LA1Error(RuntimeError):
    """A fail-closed LA1 contract or replay violation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LA1Error(message)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        raise LA1Error(f"cannot load JSON {path}: {error}") from error


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()
    except OSError as error:
        raise LA1Error(f"cannot hash {path}: {error}") from error


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def u32_digest(values: tuple[int, ...]) -> str:
    payload = b"".join(int(value).to_bytes(4, "little", signed=False) for value in values)
    return hashlib.sha256(payload).hexdigest().upper()


def json_digest(value: Any) -> str:
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def verify_provenance() -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    contract = load_json(ROOT / "CONTRACT.json")
    preexecution = load_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == "Q10-PF6-RH1-LA1", "LA1 contract protocol drift")
    require(preexecution["protocol"] == contract["protocol"], "LA1 preexecution protocol drift")
    require(
        preexecution.get("plan_sha256", "").upper() == digest(ROOT / "PLAN.md"),
        "LA1 plan hash drift",
    )
    require(
        preexecution.get("contract_sha256", "").upper() == digest(ROOT / "CONTRACT.json"),
        "LA1 contract hash drift",
    )
    actual: dict[str, str] = {}
    for binding in contract.get("source_bindings", []):
        label = str(binding["label"])
        path = REPO / str(binding["path"])
        require(path.is_file(), f"missing sealed F2 input: {label}")
        actual[label] = digest(path)
        require(actual[label] == str(binding["sha256"]).upper(), f"F2 hash drift: {label}")
    required = {"f2_execution", "f2_summary", "f2_interpretation", "f2_runner", "f2_contract"}
    require(required <= actual.keys(), "LA1 F2 provenance bindings are incomplete")
    pre_fields = {
        "f2_execution": "f2_execution_sha256",
        "f2_summary": "f2_summary_sha256",
        "f2_interpretation": "f2_interpretation_sha256",
        "f2_runner": "f2_runner_sha256",
        "f2_contract": "f2_contract_sha256",
    }
    for label, field in pre_fields.items():
        require(
            str(preexecution.get(field, "")).upper() == actual[label],
            f"LA1 preexecution provenance drift: {field}",
        )
    return contract, preexecution, actual


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    require(all(field in score for field in SCORE_FIELDS), "incomplete declared-row score")
    return (
        int(score["mismatch_count"]),
        int(score["total_ulp_distance"]),
        float(score["residual_l2"]),
        float(score["maximum_absolute_residual"]),
    )


def score_key_json(score: dict[str, Any]) -> list[Any]:
    key = score_key(score)
    return [key[0], key[1], key[2], key[3]]


def validate_score(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for field in SCORE_FIELDS:
        require(field in actual and field in expected, f"missing score field {label}.{field}")
        require(actual[field] == expected[field], f"replay score mismatch: {label}.{field}")


def identity_key(identity: Any) -> tuple[str, int, int]:
    require(isinstance(identity, list) and len(identity) == 3, "invalid F2 group identity")
    return (str(identity[0]), int(identity[1]), int(identity[2]))


def validate_f2_inputs(
    contract: dict[str, Any],
    actual_hashes: dict[str, str],
) -> dict[str, Any]:
    execution = load_json(F2_EXECUTION)
    summary = load_json(F2_SUMMARY)
    interpretation = load_json(F2_INTERPRETATION)
    require(execution.get("status") == "RH1_F2_ENGINEERING_FACTORIAL_COMPLETE", "F2 raw execution is not complete")
    require(int(execution.get("groups_processed", -1)) == 55, "F2 group cardinality drift")
    require(int(execution.get("primary_groups_processed", -1)) == 32, "F2 primary cardinality drift")
    require(int(execution.get("secondary_groups_processed", -1)) == 23, "F2 secondary cardinality drift")
    require(int(execution.get("arm_results", -1)) == 220, "F2 arm cardinality drift")
    require(len(execution.get("results", [])) == 220, "F2 result receipt cardinality drift")
    require(summary.get("raw_execution_sha256", "").upper() == actual_hashes["f2_execution"], "F2 summary/raw hash mismatch")
    require(summary.get("interpretation_status") == "ENGINEERING_FACTORIAL_COMPLETE_NO_SCIENTIFIC_PROMOTION", "F2 summary status drift")
    require(int(summary.get("integrity", {}).get("issue_count", -1)) == 0, "F2 summary reports structural issues")
    require(summary.get("authority_factor_gated") is False, "F2 authority factor is gated")
    require(summary.get("scientific_promotion") is False, "F2 scientific promotion flag drift")
    require(interpretation.get("source_execution_sha256", "").upper() == actual_hashes["f2_execution"], "F2 interpretation/raw hash mismatch")
    require(interpretation.get("source_derived_summary_sha256", "").upper() == actual_hashes["f2_summary"], "F2 interpretation/summary hash mismatch")
    require(interpretation.get("scope", {}).get("behavioral_probe") is False, "F2 behavioral probe scope drift")
    require(interpretation.get("scope", {}).get("scientific_promotion") is False, "F2 interpretation promotion drift")

    by_group: dict[tuple[str, int, int], dict[tuple[str, int], dict[str, Any]]] = {}
    for row in execution["results"]:
        key = identity_key(row.get("identity"))
        arm = (str(row.get("ranking")), int(row.get("horizon")))
        require(key not in by_group or arm not in by_group[key], f"duplicate F2 arm receipt: {key} {arm}")
        require(row.get("final_geometry_pass") is True, f"F2 final geometry failed: {key} {arm}")
        require(row.get("independent_audit") == row.get("final_geometry"), f"F2 geometry audit mismatch: {key} {arm}")
        by_group.setdefault(key, {})[arm] = row

    primary = {key: arms for key, arms in by_group.items() if arms[next(iter(arms))]["cohort"] == "primary"}
    require(len(primary) == 32, "F2 primary receipt set drift")
    expected_arms = {("authority", 16), ("authority", 32), ("residual", 16), ("residual", 32)}
    evaluated: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for key in sorted(primary):
        arms = primary[key]
        require(set(arms) == expected_arms, f"F2 primary arm set drift: {key}")
        h16 = arms[("authority", 16)]
        h32 = arms[("authority", 32)]
        require(int(h16["coordinates_total"]) >= 32, f"non-primary coordinate count in primary cohort: {key}")
        left = score_key(h16["chosen"]["D"])
        right = score_key(h32["chosen"]["D"])
        decision = {
            "identity": list(key),
            "cohort": "primary",
            "coordinates_total": int(h32["coordinates_total"]),
            "authority_h16_score": score_key_json(h16["chosen"]["D"]),
            "authority_h32_score": score_key_json(h32["chosen"]["D"]),
            "authority_h32_strictly_beats_h16": right < left,
        }
        evaluated.append(decision)
        if decision["authority_h32_strictly_beats_h16"]:
            selected.append(decision)
    require(len(evaluated) == 32, "F2 primary selection scan incomplete")
    require(selected, "LA1 selection is empty")
    return {
        "execution": execution,
        "summary": summary,
        "interpretation": interpretation,
        "by_group": by_group,
        "evaluated": evaluated,
        "selected": selected,
        "source_hashes": actual_hashes,
        "contract": contract,
    }


def prefix_from_receipt(row: dict[str, Any], coordinates: tuple[int, ...], label: str) -> tuple[int, ...]:
    state = row.get("chosen_state", {})
    pairs = [(int(item[0]), int(item[1])) for item in state.get("canonical_mapping", [])]
    require(pairs == sorted(pairs), f"{label} prefix map is not canonical")
    require(tuple(coordinate for coordinate, _ in pairs) == coordinates, f"{label} prefix coordinates drift")
    require(F2.CQ.state_identity(pairs) == str(state.get("state_identity", "")).upper(), f"{label} state identity mismatch")
    choices = tuple(choice for _, choice in pairs)
    require(all(choice in PF5_CHOICES for choice in choices), f"{label} contains an illegal choice")
    return choices


def compare_geometry(left: dict[str, Any], right: dict[str, Any], label: str) -> None:
    require(left == right, f"geometry replay mismatch: {label}")


def endpoint_record(
    name: str,
    state: Any,
    group: Any,
    physical_rows: list[int],
    candidate: Any,
    pf5_contract: dict[str, Any],
    hard_gate: bool,
) -> dict[str, Any]:
    values = tuple(PF5.from_bits(raw) for raw in candidate.weight_bits)
    replayed = PF5.readout_bits(state.rows, values)
    require(replayed == candidate.readout_bits, f"{name} sequential-f32 replay mismatch")
    geometry = PF5.geometry_metrics(state.rows, values, state.base_weights, state.target_weights, state.axis)
    require(all(math.isfinite(float(value)) for value in geometry.values()), f"{name} geometry is non-finite")
    audit = PF5.independent_candidate_audit(state, group, candidate, pf5_contract)
    compare_geometry(geometry, audit, name)
    diagnostic_pass = PF5.final_geometry_pass(geometry, pf5_contract)
    prefix_map = [[int(coordinate), int(choice)] for coordinate, choice in zip(group.coordinates, candidate.prefix_tuple)]
    changed_bits = [
        [int(coordinate), int(candidate.weight_bits[coordinate])]
        for coordinate, choice in zip(group.coordinates, candidate.prefix_tuple)
        if choice != 0
    ]
    debt = {
        "axis_normalized_signed": (geometry["final_axis"] - geometry["target_axis"]) / max(abs(geometry["target_axis"]), 1.0e-12),
        "norm_normalized_signed": (geometry["final_norm"] - geometry["target_norm"]) / max(geometry["target_norm"], 1.0e-12),
        "cue_linear_normalized_abs": geometry["cue_linear_normalized_error"],
    }
    return {
        "name": name,
        "canonical_prefix_map": prefix_map,
        "changed_weight_bits": changed_bits,
        "weight_bits_sha256": u32_digest(candidate.weight_bits),
        "readout_bits_sha256": u32_digest(candidate.readout_bits),
        "scores": F2.score_domains(state, group, physical_rows, candidate),
        "final_geometry": geometry,
        "geometry_debt": debt,
        "final_geometry_pass": diagnostic_pass,
        "diagnostic_geometry_pass": diagnostic_pass,
        "geometry_gate_role": "hard" if hard_gate else "diagnostic_only",
        "independent_f32_replay": True,
    }


def interaction_records(state: Any, candidates: dict[str, Any], group: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    names = ("W0", "historical_authority_h16", "authority_h32_early_ranks_1_16", "authority_h32_late_only_ranks_17_32", "authority_h32_full")
    readouts = {name: candidates[name].readout_bits for name in names}
    declared = set(int(row) for row in group.rows)
    physical = {
        int(row)
        for coordinate in group.coordinates
        for row, _ in state.support_counts[coordinate]
    }
    records: list[dict[str, Any]] = []
    for row in range(len(state.rows)):
        bits = {name: int(readouts[name][row]) for name in names}
        values = {name: PF5.from_bits(readouts[name][row]) for name in names}
        interaction = values["authority_h32_full"] - values["W0"] - values["authority_h32_early_ranks_1_16"] + values["W0"]
        interaction -= values["authority_h32_late_only_ranks_17_32"] - values["W0"]
        records.append({
            "row": row,
            "declared": row in declared,
            "physical_support": row in physical,
            "W0_bits": bits["W0"],
            "historical_authority_h16_bits": bits["historical_authority_h16"],
            "authority_h32_early_bits": bits["authority_h32_early_ranks_1_16"],
            "authority_h32_late_only_bits": bits["authority_h32_late_only_ranks_17_32"],
            "authority_h32_full_bits": bits["authority_h32_full"],
            "W0_value": values["W0"],
            "historical_authority_h16_value": values["historical_authority_h16"],
            "authority_h32_early_value": values["authority_h32_early_ranks_1_16"],
            "authority_h32_late_only_value": values["authority_h32_late_only_ranks_17_32"],
            "authority_h32_full_value": values["authority_h32_full"],
            "interaction_I": interaction,
        })
    nonzero = [row for row in records if row["interaction_I"] != 0.0]
    positive = sum(row["interaction_I"] > 0.0 for row in nonzero)
    negative = sum(row["interaction_I"] < 0.0 for row in nonzero)
    if not nonzero:
        support_label = "zero_support"
    elif len(nonzero) <= max(1, len(declared)):
        support_label = "localized_support"
    else:
        support_label = "distributed_support"
    sign_label = "zero_sign" if not nonzero else ("positive_only" if not negative else ("negative_only" if not positive else "mixed_sign"))
    morphology = {
        "label": f"{support_label}+{sign_label}",
        "support_rows": len(nonzero),
        "declared_support_rows": sum(row["declared"] and row["interaction_I"] != 0.0 for row in records),
        "physical_support_rows": sum(row["physical_support"] and row["interaction_I"] != 0.0 for row in records),
        "positive_rows": positive,
        "negative_rows": negative,
        "descriptive_only": True,
    }
    return records, morphology


def build_group_receipt(
    item: dict[str, Any],
    f2: dict[str, Any],
    state: Any,
    raw_group: Any,
    frozen: dict[str, Any],
    pf5_contract: dict[str, Any],
) -> dict[str, Any]:
    identity = tuple(item["identity"])
    arms = f2["by_group"][(str(identity[0]), int(identity[1]), int(identity[2]))]
    h16 = arms[("authority", 16)]
    h32 = arms[("authority", 32)]
    coordinates = tuple(int(value) for value in raw_group.coordinates)
    require(coordinates == tuple(sorted(coordinates)), f"group coordinates are not canonical: {identity}")
    require(coordinates == tuple(int(value) for value in h32["coordinates_canonical"]), f"F2 coordinate baseline mismatch: {identity}")
    require(coordinates == tuple(int(value) for value in h16["coordinates_canonical"]), f"F2 h16 coordinate mismatch: {identity}")
    require(len(coordinates) == int(item["coordinates_total"]), f"coordinate count mismatch: {identity}")
    ranking = tuple(int(value) for value in h32["ranking_order"])
    require(len(ranking) == len(set(ranking)) == len(coordinates), f"authority ranking is not a permutation: {identity}")
    require(set(ranking) == set(coordinates), f"authority ranking coordinate mismatch: {identity}")
    require(tuple(int(value) for value in h16["ranking_order"]) == ranking, f"authority ranking changed between horizons: {identity}")
    h16_prefix = prefix_from_receipt(h16, coordinates, "historical authority h16")
    h32_prefix = prefix_from_receipt(h32, coordinates, "authority h32")
    rank_of = {coordinate: index + 1 for index, coordinate in enumerate(ranking)}
    require(all(choice == 0 for coordinate, choice in zip(coordinates, h16_prefix) if rank_of[coordinate] > 16), f"h16 committed a late prefix: {identity}")
    require(all(choice == 0 for coordinate, choice in zip(coordinates, h32_prefix) if rank_of[coordinate] > 32), f"h32 committed a post-h32 prefix: {identity}")
    early_prefix = tuple(choice if rank_of[coordinate] <= 16 else 0 for coordinate, choice in zip(coordinates, h32_prefix))
    late_prefix = tuple(choice if 17 <= rank_of[coordinate] <= 32 else 0 for coordinate, choice in zip(coordinates, h32_prefix))
    zero_prefix = tuple(0 for _ in coordinates)
    prefixes = {
        "W0": zero_prefix,
        "historical_authority_h16": h16_prefix,
        "authority_h32_early_ranks_1_16": early_prefix,
        "authority_h32_late_only_ranks_17_32": late_prefix,
        "authority_h32_full": h32_prefix,
    }
    candidates = {
        name: PF5._candidate(state, raw_group, prefix)
        for name, prefix in prefixes.items()
    }
    physical_rows = sorted({row for coordinate in coordinates for row, _ in state.support_counts[coordinate]})
    baseline = endpoint_record("W0", state, raw_group, physical_rows, candidates["W0"], pf5_contract, True)
    require(candidates["W0"].weight_bits == state.baseline_weight_bits, f"W0 baseline weight mismatch: {identity}")
    require(candidates["W0"].readout_bits == state.baseline_readout_bits, f"W0 baseline readout mismatch: {identity}")
    require(candidates["W0"].prefix_tuple == zero_prefix, f"W0 prefix mismatch: {identity}")
    for arm in arms.values():
        validate_score(baseline["scores"]["D"], arm["baseline"]["D"], f"{identity} baseline D")
        validate_score(baseline["scores"]["P"], arm["baseline"]["P"], f"{identity} baseline P")
        validate_score(baseline["scores"]["G"], arm["baseline"]["G"], f"{identity} baseline G")
    historical = endpoint_record("historical_authority_h16", state, raw_group, physical_rows, candidates["historical_authority_h16"], pf5_contract, True)
    early = endpoint_record("authority_h32_early_ranks_1_16", state, raw_group, physical_rows, candidates["authority_h32_early_ranks_1_16"], pf5_contract, False)
    late = endpoint_record("authority_h32_late_only_ranks_17_32", state, raw_group, physical_rows, candidates["authority_h32_late_only_ranks_17_32"], pf5_contract, False)
    full = endpoint_record("authority_h32_full", state, raw_group, physical_rows, candidates["authority_h32_full"], pf5_contract, True)
    validate_score(historical["scores"]["D"], h16["chosen"]["D"], f"{identity} historical D")
    validate_score(historical["scores"]["P"], h16["chosen"]["P"], f"{identity} historical P")
    validate_score(historical["scores"]["G"], h16["chosen"]["G"], f"{identity} historical G")
    validate_score(full["scores"]["D"], h32["chosen"]["D"], f"{identity} full D")
    validate_score(full["scores"]["P"], h32["chosen"]["P"], f"{identity} full P")
    validate_score(full["scores"]["G"], h32["chosen"]["G"], f"{identity} full G")
    require(baseline["final_geometry_pass"], f"W0 final geometry failed: {identity}")
    require(historical["final_geometry_pass"], f"historical h16 final geometry failed: {identity}")
    require(full["final_geometry_pass"], f"full h32 final geometry failed: {identity}")
    interactions, morphology = interaction_records(state, candidates, raw_group)
    endpoints = {
        "W0": baseline,
        "historical_authority_h16": historical,
        "authority_h32_early_ranks_1_16": early,
        "authority_h32_late_only_ranks_17_32": late,
        "authority_h32_full": full,
    }
    return {
        "protocol": "Q10-PF6-RH1-LA1",
        "identity": list(identity),
        "cohort": "primary",
        "coordinates_total": len(coordinates),
        "declared_rows": list(raw_group.rows),
        "physical_support_rows": physical_rows,
        "canonical_coordinates": list(coordinates),
        "authority_ranking_order": list(ranking),
        "authority_rank_1_16": list(ranking[:16]),
        "authority_rank_17_32": list(ranking[16:32]),
        "selection": {
            "authority_h16_declared_score": score_key_json(h16["chosen"]["D"]),
            "authority_h32_declared_score": score_key_json(h32["chosen"]["D"]),
            "strict_h32_beats_h16": True,
        },
        "baseline_anchor": {
            "baseline_weight_bits_sha256": u32_digest(state.baseline_weight_bits),
            "baseline_readout_bits_sha256": u32_digest(state.baseline_readout_bits),
            "baseline_coordinates": len(state.baseline_weight_bits),
            "baseline_rows": len(state.rows),
        },
        "endpoints": endpoints,
        "row_interaction": interactions,
        "row_interaction_sha256": json_digest(interactions),
        "morphology": morphology,
        "integrity": {
            "same_baseline": True,
            "exact_sequential_f32_replay": True,
            "actual_endpoint_geometry_hard_gate_pass": True,
            "counterfactual_geometry_is_diagnostic_only": True,
            "counterfactual_diagnostic_pass": {
                name: endpoints[name]["diagnostic_geometry_pass"] for name in COUNTERFACTUAL_ENDPOINTS
            },
        },
        "scope": {
            "engineering_only": True,
            "behavioral_probe": False,
            "scientific_promotion": False,
            "morphology_descriptive_only": True,
        },
    }


PF5_CHOICES = frozenset((0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16))


def output_path(root: Path, requested: Path) -> Path:
    resolved = requested.resolve()
    root_resolved = root.resolve()
    require(resolved != root_resolved and root_resolved in resolved.parents, "LA1 output must remain under q10-rh1-la1-v1")
    return resolved


def run(output_dir: Path, limit_groups: int | None = None, smoke: bool = False) -> dict[str, Any]:
    contract, preexecution, source_hashes = verify_provenance()
    f2 = validate_f2_inputs(contract, source_hashes)
    selected = f2["selected"] if limit_groups is None else f2["selected"][:limit_groups]
    require(selected, "LA1 run selected no groups")
    output_dir = output_path(ROOT, output_dir)
    selected_keys = {(str(item["identity"][0]), int(item["identity"][1])) for item in selected}
    bindings, states, groups = F2.load_runtime(selected_keys)
    require(bindings, "F2 runtime provenance is empty")
    frozen_primary, _ = F2.frozen_groups()
    frozen_by_identity = {tuple(item["identity"]): item for item in frozen_primary}
    pf5_contract = PF5.load_json(F2.PF5_ROOT / "CONTRACT.json")
    group_receipts: list[dict[str, Any]] = []
    selection_receipt = {
        "protocol": "Q10-PF6-RH1-LA1",
        "status": "LA1_SELECTION_DERIVED_FROM_F2_RECEIPTS",
        "source_hashes": source_hashes,
        "selection_rule": contract["selection"],
        "evaluated_primary_groups": f2["evaluated"],
        "selected_group_count": len(f2["selected"]),
        "selected_groups_for_this_run": [item["identity"] for item in selected],
        "smoke": smoke,
    }
    write_json(output_dir / "selection.json", selection_receipt)
    for item in selected:
        identity = tuple(item["identity"])
        frozen = frozen_by_identity.get(identity)
        require(frozen is not None, f"missing frozen F2 group: {identity}")
        key = (identity[0], identity[1])
        state = states.get(key)
        raw_group = groups.get((identity[0], identity[1], identity[2]))
        require(state is not None and raw_group is not None, f"missing reconstructed group baseline: {identity}")
        receipt = build_group_receipt(item, f2, state, raw_group, frozen, pf5_contract)
        safe = f"{identity[0].replace('.json', '')}__set{identity[1]}__group{identity[2]}.json"
        receipt_path = output_dir / "groups" / safe
        write_json(receipt_path, receipt)
        group_receipts.append({
            "identity": list(identity),
            "path": str(receipt_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": digest(receipt_path),
            "row_interaction_sha256": receipt["row_interaction_sha256"],
            "morphology_label": receipt["morphology"]["label"],
            "actual_endpoint_geometry_hard_gate_pass": receipt["integrity"]["actual_endpoint_geometry_hard_gate_pass"],
            "counterfactual_diagnostic_pass": receipt["integrity"]["counterfactual_diagnostic_pass"],
        })
    execution = {
        "protocol": "Q10-PF6-RH1-LA1",
        "status": "LA1_SMOKE_COMPLETE" if smoke else "LA1_RAW_EXECUTION_COMPLETE",
        "run_scope": "smoke" if smoke else "full",
        "la1_plan_sha256": digest(ROOT / "PLAN.md"),
        "la1_contract_sha256": digest(ROOT / "CONTRACT.json"),
        "la1_preexecution_sha256": digest(ROOT / "PREEXECUTION.json"),
        "source_hashes": source_hashes,
        "f2_runtime_bindings": bindings,
        "selected_group_count": len(group_receipts),
        "full_selected_group_count": len(f2["selected"]),
        "selection_complete": not smoke and len(group_receipts) == len(f2["selected"]),
        "group_receipts": sorted(group_receipts, key=lambda item: tuple(item["identity"])),
        "geometry_policy": contract["geometry"],
        "scope": contract["scope"],
    }
    write_json(output_dir / "execution.json", execution)
    print(json.dumps({"status": execution["status"], "selected_groups": len(group_receipts)}, indent=2))
    return execution


def main() -> int:
    parser = argparse.ArgumentParser(description="run the receipt-backed Q10-RH1-LA1 engineering audit")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "qualification" / "execution")
    parser.add_argument("--limit-groups", type=int)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.limit_groups is not None:
        require(args.limit_groups > 0, "--limit-groups must be positive")
    try:
        run(args.output_dir, args.limit_groups, args.smoke)
    except (LA1Error, OSError, KeyError, TypeError, ValueError) as error:
        print(f"Q10-RH1-LA1 failed closed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

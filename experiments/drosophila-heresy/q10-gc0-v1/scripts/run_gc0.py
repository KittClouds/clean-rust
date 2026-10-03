"""Q10-GC0 bounded global candidate-palette qualification runner.

The runner imports the sealed RH1-F2 runtime and evaluates every retained
candidate by the PF5 sequential-f32 readout. It writes only below q10-gc0-v1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
F2_ROOT = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1"
F2_SCRIPTS = F2_ROOT / "scripts"
sys.path.insert(0, str(F2_SCRIPTS))
import run_rh1 as RH1  # noqa: E402


PROTOCOL = "Q10-GC0"
QUALIFICATION_ROOT = ROOT / "qualification"
EXECUTION_ROOT = QUALIFICATION_ROOT / "execution"
GROUP_ROOT = EXECUTION_ROOT / "groups"
RECEIPT_ROOT = QUALIFICATION_ROOT / "receipts"
MAX_PALETTE_NONZERO = 8


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def json_hash(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest().upper()


def bits_hash(values: Iterable[int]) -> str:
    payload = b"".join(struct.pack("<I", int(value) & 0xFFFF_FFFF) for value in values)
    return hashlib.sha256(payload).hexdigest().upper()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


@dataclass(frozen=True)
class Evaluation:
    coordinate_ids: tuple[int, ...]
    prefix: tuple[int, ...]
    weight_bits: tuple[int, ...]
    readout_bits: tuple[int, ...]
    objective: Any
    debt: Any
    scores: dict[str, dict[str, Any]]
    geometry: dict[str, float]
    newly_damaged: dict[str, tuple[int, ...]]
    active_support: tuple[int, ...]
    prefix_scale_profile: tuple[int, ...]
    active_physical_support: tuple[int, ...]
    changed_rows: tuple[int, ...]
    first_seen_replay_index: int
    guard_pass: bool


def load_local_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = RH1.CQ.load_json(ROOT / "CONTRACT.json")
    preexecution = RH1.CQ.load_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL, "GC0 contract identity drift")
    require(contract["identity"] == "q10-gc0-v1", "GC0 contract version drift")
    require(preexecution["protocol"] == PROTOCOL, "GC0 PREEXECUTION identity drift")
    require(preexecution["plan_sha256"] == RH1.CQ.digest(ROOT / "PLAN.md"), "GC0 PLAN hash drift")
    require(preexecution["contract_sha256"] == RH1.CQ.digest(ROOT / "CONTRACT.json"), "GC0 CONTRACT hash drift")
    require(contract["plan_sha256"] == preexecution["plan_sha256"], "GC0 plan binding drift")
    return contract, preexecution


def verify_parent_provenance(contract: dict[str, Any], preexecution: dict[str, Any]) -> dict[str, str]:
    expected = {str(item["label"]): str(item["sha256"]).upper() for item in contract["parent_bindings"]}
    sealed = {str(key): str(value).upper() for key, value in preexecution["sealed_parent_sha256"].items()}
    require(set(expected) == set(sealed), "GC0 sealed parent binding labels drift")
    verified: dict[str, str] = {}
    for binding in contract["parent_bindings"]:
        relative = Path(str(binding["path"]))
        require(not relative.is_absolute(), f"GC0 parent path is absolute: {relative}")
        path = REPO / relative
        require(path.is_file(), f"GC0 parent is missing: {binding['label']}")
        actual = RH1.CQ.digest(path)
        require(actual == expected[binding["label"]], f"GC0 parent drift: {binding['label']}")
        require(actual == sealed[binding["label"]], f"GC0 PREEXECUTION parent drift: {binding['label']}")
        verified[binding["label"]] = actual

    # The qualified F2 runtime performs its own complete parent audit.
    f2_bindings = RH1.verify_contract()
    require(f2_bindings["rh1_runner"] == verified["rh1_f2_runner"], "RH1-F2 runner audit mismatch")
    require(f2_bindings["pf5_contract"] == verified["pf5_contract"], "PF5 contract audit mismatch")

    f2_execution = RH1.CQ.load_json(F2_ROOT / "qualification/execution/execution.json")
    f2_summary = RH1.CQ.load_json(F2_ROOT / "qualification/derived/SUMMARY.json")
    f2_status = RH1.CQ.load_json(F2_ROOT / "qualification/derived/STATUS.json")
    root_status = RH1.CQ.load_json(F2_ROOT / "STATUS.json")
    require(f2_execution["status"] == "RH1_F2_ENGINEERING_FACTORIAL_COMPLETE", "RH1-F2 execution is not complete")
    require(f2_execution["groups_processed"] == 55 and f2_execution["arm_results"] == 220, "RH1-F2 cardinality drift")
    require(f2_summary["groups"] == 55, "RH1-F2 derived summary cardinality drift")
    require(f2_summary["interpretation_status"] == "ENGINEERING_FACTORIAL_COMPLETE_NO_SCIENTIFIC_PROMOTION", "RH1-F2 interpretation drift")
    require(f2_status["status"] == "ENGINEERING_FACTORIAL_COMPLETE_NO_SCIENTIFIC_PROMOTION", "RH1-F2 derived status drift")
    require(root_status["status"] == "ENGINEERING_FACTORIAL_COMPLETE_NO_SCIENTIFIC_PROMOTION", "RH1-F2 root status drift")
    require(f2_execution["scientific_seed_bundles"] == 0, "RH1-F2 scientific seed firewall drift")
    require(f2_execution["behavioral_probe"] is False and f2_execution["dh08b_authorized"] is False, "RH1-F2 behavior firewall drift")
    for label in ("rh1_ac2_features", "rh1_ac2_effects"):
        require(f2_execution["parent_bindings_verified"][label] == verified[label], f"RH1-F2 authority input mismatch: {label}")
    return verified


def load_sample(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, int], Any], dict[tuple[str, int, int], Any], dict[tuple[str, int, int, int], dict[str, Any]], dict[str, Any]]:
    sample = contract["sample"]
    endpoint_names = {str(endpoint) for endpoint in sample["endpoint_names"]}
    endpoint_keys = {(str(endpoint), int(set_index)) for endpoint, set_index in sample["endpoint_keys"]}
    primary, secondary = RH1.frozen_groups()
    frozen = [group for group in primary + secondary if str(group["endpoint"]) in endpoint_names]
    actual_endpoint_keys = {(str(group["endpoint"]), int(group["set_index"])) for group in frozen}
    require(len(endpoint_names) == int(sample["expected_endpoint_count"]), "GC0 sample endpoint count drift")
    require(actual_endpoint_keys == endpoint_keys, "GC0 sample endpoint-set key drift")
    require(len(endpoint_keys) == int(sample["expected_endpoint_set_count"]), "GC0 sample endpoint-set count drift")
    require(len(frozen) == int(sample["expected_group_count"]), "GC0 sample group count drift")
    require(len(primary) + len(secondary) == int(sample["full_f2_group_count"]), "GC0 F2 library count drift")
    features = RH1.load_features()
    _, states, groups = RH1.load_runtime(endpoint_keys)
    require(set(states) == endpoint_keys, "GC0 sample runtime endpoint-set coverage drift")
    for group in frozen:
        key = (str(group["endpoint"]), int(group["set_index"]), int(group["group_index"]))
        require(key in groups, f"GC0 missing sample group runtime: {key}")
    pf5_contract = RH1.CQ.load_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    return frozen, states, groups, features, pf5_contract


def score_rows(actual: tuple[int, ...], target: tuple[int, ...], rows: Iterable[int]) -> dict[str, Any]:
    mismatch_count = 0
    total_ulp = 0
    residuals: list[float] = []
    maximum = 0.0
    for row in rows:
        left = RH1.PF5.from_bits(actual[row])
        right = RH1.PF5.from_bits(target[row])
        error = left - right
        residuals.append(error)
        mismatch_count += int(actual[row] != target[row])
        total_ulp += RH1.PF5.ulp_distance(left, right)
        maximum = max(maximum, abs(error))
    result = {
        "mismatch_count": mismatch_count,
        "total_ulp_distance": total_ulp,
        "residual_l2": math.sqrt(math.fsum(error * error for error in residuals)),
        "maximum_absolute_residual": maximum,
    }
    require(math.isfinite(result["residual_l2"]) and math.isfinite(result["maximum_absolute_residual"]), "GC0 non-finite score")
    return result


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(score["mismatch_count"]),
        int(score["total_ulp_distance"]),
        float(score["residual_l2"]),
        float(score["maximum_absolute_residual"]),
    )


def prefix_mapping(group: Any, prefix: tuple[int, ...]) -> list[list[int]]:
    require(len(group.coordinates) == len(prefix), "GC0 prefix arity drift")
    return [[int(coordinate), int(choice)] for coordinate, choice in zip(group.coordinates, prefix)]


def evaluate_candidate(
    state: Any,
    group: Any,
    prefix: tuple[int, ...],
    physical_rows: list[int],
    pf5_contract: dict[str, Any],
    replay_index: int,
) -> Evaluation:
    weight_bits = RH1.weight_bits_for(state, group, prefix)
    weights = tuple(RH1.PF5.from_bits(raw) for raw in weight_bits)
    readout_bits = RH1.PF5.readout_bits(state.rows, weights)
    scores = {
        "D": score_rows(readout_bits, state.target_readout_bits, group.rows),
        "P": score_rows(readout_bits, state.target_readout_bits, physical_rows),
        "G": score_rows(readout_bits, state.target_readout_bits, range(len(state.rows))),
    }
    geometry = RH1.PF5.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    axis_scale = max(abs(state.target_axis), 1.0e-12)
    norm_scale = max(state.target_norm, 1.0e-12)
    debt = RH1.PF5.GeometryDebt(
        (geometry["final_axis"] - geometry["target_axis"]) / axis_scale,
        (geometry["final_norm"] - geometry["target_norm"]) / norm_scale,
        geometry["cue_linear_normalized_error"],
    )
    objective = RH1.PF5.Objective(
        scores["D"]["mismatch_count"],
        scores["D"]["total_ulp_distance"],
        scores["D"]["residual_l2"],
        scores["D"]["maximum_absolute_residual"],
        prefix,
    )
    guard_values = pf5_contract["geometry"]["intermediate_guardrails"]
    guard = RH1.PF5.GeometryDebt(
        guard_values["axis_normalized_abs"],
        guard_values["norm_normalized_abs"],
        guard_values["cue_linear_normalized_abs"],
    )
    active_support = tuple(sorted(int(coordinate) for coordinate, choice in zip(group.coordinates, prefix) if choice != 0))
    prefix_scale_profile = tuple(sorted(abs(int(choice)) for choice in prefix if choice != 0))
    active_rows = sorted({int(row) for coordinate in active_support for row, _ in state.support_counts[coordinate]})
    changed_rows = tuple(int(row) for row in range(len(state.rows)) if readout_bits[row] != state.baseline_readout_bits[row])
    domains = {"D": list(group.rows), "P": physical_rows, "G": list(range(len(state.rows)))}
    newly_damaged = {
        label: tuple(
            int(row)
            for row in rows
            if state.baseline_readout_bits[row] == state.target_readout_bits[row]
            and readout_bits[row] != state.target_readout_bits[row]
        )
        for label, rows in domains.items()
    }
    return Evaluation(
        coordinate_ids=tuple(int(coordinate) for coordinate in group.coordinates),
        prefix=prefix,
        weight_bits=tuple(int(raw) for raw in weight_bits),
        readout_bits=tuple(int(raw) for raw in readout_bits),
        objective=objective,
        debt=debt,
        scores=scores,
        geometry=geometry,
        newly_damaged=newly_damaged,
        active_support=tuple(active_support),
        prefix_scale_profile=prefix_scale_profile,
        active_physical_support=tuple(active_rows),
        changed_rows=changed_rows,
        first_seen_replay_index=replay_index,
        guard_pass=debt.within(guard),
    )


def beam_state(evaluation: Evaluation) -> Any:
    candidate = RH1.PF5.CandidateEvaluation(
        evaluation.prefix,
        evaluation.objective,
        evaluation.debt,
        evaluation.readout_bits,
        evaluation.weight_bits,
    )
    return RH1.PF5._state_for(candidate)


def full_candidate_key(evaluation: Evaluation) -> tuple[Any, ...]:
    return (
        score_key(evaluation.scores["D"]),
        score_key(evaluation.scores["P"]),
        len(evaluation.newly_damaged["P"]),
        abs(float(evaluation.debt.axis)),
        abs(float(evaluation.debt.norm)),
        float(evaluation.debt.cue_linear),
        evaluation.active_support,
        evaluation.prefix_scale_profile,
        evaluation.prefix,
        RH1.CQ.state_identity(dict(zip(evaluation.coordinate_ids, evaluation.prefix))),
    )


def select_palette(evaluations: dict[tuple[int, ...], Evaluation], zero: Evaluation) -> tuple[list[tuple[Evaluation, list[str]]], dict[str, str | None], int]:
    eligible = [item for item in evaluations.values() if item.prefix != zero.prefix and item.guard_pass]
    selected: dict[str, tuple[Evaluation, list[str]]] = {}
    role_selection: dict[str, str | None] = {}
    used_support: set[tuple[int, ...]] = set()
    used_profiles: set[tuple[int, ...]] = set()

    def identity(item: Evaluation) -> str:
        return RH1.CQ.state_identity(dict(zip(item.coordinate_ids, item.prefix)))

    def add_role(role: str, item: Evaluation | None) -> None:
        if item is None:
            role_selection[role] = None
            return
        item_id = identity(item)
        role_selection[role] = item_id
        existing = selected.get(item_id)
        if existing is None:
            selected[item_id] = (item, [role])
        elif role not in existing[1]:
            existing[1].append(role)
        used_support.add(item.active_support)
        used_profiles.add(item.prefix_scale_profile)

    def choose(key: Any, predicate: Any = None) -> Evaluation | None:
        pool = [item for item in eligible if predicate is None or predicate(item)]
        return min(pool, key=key) if pool else None

    add_role("best_D", choose(lambda item: (score_key(item.scores["D"]), item.prefix)))
    add_role("best_P", choose(lambda item: (score_key(item.scores["P"]), item.prefix)))
    add_role("lowest_collateral", choose(lambda item: (len(item.newly_damaged["P"]), full_candidate_key(item))))
    add_role("lowest_axis_debt", choose(lambda item: (abs(float(item.debt.axis)), full_candidate_key(item))))
    add_role("lowest_norm_debt", choose(lambda item: (abs(float(item.debt.norm)), full_candidate_key(item))))
    add_role("lowest_linear_drive_debt", choose(lambda item: (float(item.debt.cue_linear), full_candidate_key(item))))
    add_role("distinct_active_coordinate_support", choose(full_candidate_key, lambda item: item.active_support not in used_support))
    add_role("distinct_prefix_scale_profile", choose(full_candidate_key, lambda item: item.prefix_scale_profile not in used_profiles))

    ordered = sorted(eligible, key=full_candidate_key)
    for item in ordered:
        if len(selected) >= MAX_PALETTE_NONZERO:
            break
        item_id = identity(item)
        if item_id not in selected:
            selected[item_id] = (item, ["lexicographic_fill"])
            used_support.add(item.active_support)
            used_profiles.add(item.prefix_scale_profile)

    entries = [(zero, ["ZERO"])]
    entries.extend((item, roles) for item, roles in selected.values())
    shortfall = max(0, MAX_PALETTE_NONZERO - (len(entries) - 1))
    return entries, role_selection, shortfall


def serialize_candidate(state: Any, group: Any, evaluation: Evaluation, roles: list[str], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    mapping = prefix_mapping(group, evaluation.prefix)
    committed_mapping = [
        [int(coordinate), int(choice), int(evaluation.weight_bits[coordinate])]
        for coordinate, choice in zip(group.coordinates, evaluation.prefix)
    ]
    state_identity = RH1.CQ.state_identity(dict(mapping))
    committed_mapping_hash = json_hash(committed_mapping)
    exact_audit = RH1.PF5.independent_candidate_audit(
        state,
        group,
        RH1.PF5.CandidateEvaluation(
            evaluation.prefix,
            evaluation.objective,
            evaluation.debt,
            evaluation.readout_bits,
            evaluation.weight_bits,
        ),
        pf5_contract,
    )
    for key, value in exact_audit.items():
        require(math.isfinite(float(value)), f"GC0 non-finite independent audit: {key}")
    geometry_signature_payload = {
        "axis_debt": float(evaluation.debt.axis),
        "norm_debt": float(evaluation.debt.norm),
        "linear_drive_debt": float(evaluation.debt.cue_linear),
        "geometry": evaluation.geometry,
    }
    final_geometry_pass = RH1.PF5.final_geometry_pass(evaluation.geometry, pf5_contract)
    return {
        "candidate_identity": state_identity,
        "roles": list(roles),
        "canonical_mapping": mapping,
        "committed_f32_mapping": committed_mapping,
        "committed_f32_mapping_sha256": committed_mapping_hash,
        "committed_f32_weight_state_sha256": bits_hash(evaluation.weight_bits),
        "exact_readout_encoding": "sequential_f32_readout_bits_in_endpoint_row_order",
        "exact_readout_bits": list(evaluation.readout_bits),
        "exact_readout_sha256": bits_hash(evaluation.readout_bits),
        "scores": evaluation.scores,
        "newly_damaged_exact_rows": {label: list(rows) for label, rows in evaluation.newly_damaged.items()},
        "geometry": evaluation.geometry,
        "geometry_signature": {
            "axis_debt": float(evaluation.debt.axis),
            "norm_debt": float(evaluation.debt.norm),
            "linear_drive_debt": float(evaluation.debt.cue_linear),
            "final_geometry_pass": final_geometry_pass,
            "sha256": json_hash(geometry_signature_payload),
        },
        "independent_f32_audit": exact_audit,
        "geometry_guard_pass": evaluation.guard_pass,
        "support_metadata": {
            "active_coordinate_ids": list(evaluation.active_support),
            "active_coordinate_count": len(evaluation.active_support),
            "active_physical_support_rows": list(evaluation.active_physical_support),
            "active_physical_support_row_count": len(evaluation.active_physical_support),
            "changed_readout_rows": list(evaluation.changed_rows),
            "changed_readout_row_count": len(evaluation.changed_rows),
            "prefix_scale_profile": list(evaluation.prefix_scale_profile),
            "physical_support_rows_for_group": sorted({int(row) for coordinate in group.coordinates for row, _ in state.support_counts[coordinate]}),
        },
        "collateral": {
            "newly_damaged_exact_physical_row_count": len(evaluation.newly_damaged["P"]),
            "newly_damaged_exact_physical_rows": list(evaluation.newly_damaged["P"]),
        },
        "first_seen_replay_index": evaluation.first_seen_replay_index,
    }


def run_group(
    state: Any,
    raw_group: Any,
    frozen_group: dict[str, Any],
    features: dict[tuple[str, int, int, int], dict[str, Any]],
    pf5_contract: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    group = RH1.canonical_group(raw_group)
    endpoint, set_index, group_index = frozen_group["identity"]
    require(tuple(group.rows) == tuple(frozen_group["rows"]), f"GC0 group row drift: {frozen_group['identity']}")
    require(set(group.coordinates) == set(frozen_group["coordinates"]), f"GC0 group coordinate drift: {frozen_group['identity']}")
    ranking = RH1.rank_authority(frozen_group, features)
    require(set(ranking) == set(group.coordinates), f"GC0 authority ranking lost coordinates: {frozen_group['identity']}")
    horizon = min(32, len(group.coordinates))
    horizon_ranking = ranking[:horizon]
    physical_rows = sorted({int(row) for coordinate in group.coordinates for row, _ in state.support_counts[coordinate]})
    max_replays = int(contract["candidate_generation"]["max_unique_replays_per_group"])
    frontier_width = int(contract["candidate_generation"]["frontier_width"])
    exploit_width = int(contract["candidate_generation"]["exploit_width"])
    explore_width = int(contract["candidate_generation"]["explore_width"])
    zero_prefix = tuple(0 for _ in group.coordinates)
    evaluations: dict[tuple[int, ...], Evaluation] = {}
    replay_index = 0

    def ensure(prefix: tuple[int, ...]) -> Evaluation | None:
        nonlocal replay_index
        existing = evaluations.get(prefix)
        if existing is not None:
            return existing
        if len(evaluations) >= max_replays:
            return None
        replay_index += 1
        candidate = evaluate_candidate(state, group, prefix, physical_rows, pf5_contract, replay_index)
        evaluations[prefix] = candidate
        return candidate

    zero = ensure(zero_prefix)
    require(zero is not None, "GC0 could not evaluate zero candidate")
    frontier = [zero]
    guard_rejected = 0
    rounds_completed = 0
    cutoff = False
    no_expansion = False
    termination = "HORIZON"
    coordinate_index = {int(coordinate): index for index, coordinate in enumerate(group.coordinates)}
    for round_index, coordinate in enumerate(horizon_ranking):
        expanded: list[Evaluation] = []
        canonical_index = coordinate_index[int(coordinate)]
        parents = sorted(frontier, key=lambda item: (score_key(item.scores["D"]), item.prefix))
        for parent in parents:
            for choice in group.domains[canonical_index]:
                prefix_values = list(parent.prefix)
                prefix_values[canonical_index] = int(choice)
                prefix = tuple(prefix_values)
                candidate = ensure(prefix)
                if candidate is None:
                    cutoff = True
                    break
                if candidate.guard_pass:
                    expanded.append(candidate)
                else:
                    guard_rejected += 1
            if cutoff:
                break
        if not expanded:
            no_expansion = True
            termination = "REPLAY_CUTOFF" if cutoff else "NO_EXPANSION"
            break
        beam_states = RH1.PF5.select_beam(
            [beam_state(item) for item in expanded],
            exploit_width=min(exploit_width, frontier_width),
            explore_width=min(explore_width, max(0, frontier_width - min(exploit_width, frontier_width))),
        )
        frontier = [evaluations[state_item.prefix_tuple] for state_item in beam_states]
        rounds_completed = round_index + 1
        if cutoff:
            termination = "REPLAY_CUTOFF"
            break
    else:
        termination = "NATURAL_COORDINATE_END" if horizon == len(group.coordinates) else "HORIZON"
    if len(evaluations) >= max_replays and termination not in {"NATURAL_COORDINATE_END", "HORIZON"}:
        cutoff = True
    entries, role_selection, shortfall = select_palette(evaluations, zero)
    candidate_receipts = [serialize_candidate(state, group, item, roles, pf5_contract) for item, roles in entries]
    require(candidate_receipts and candidate_receipts[0]["roles"] == ["ZERO"], "GC0 zero candidate was not first")
    require(candidate_receipts[0]["canonical_mapping"] == prefix_mapping(group, zero.prefix), "GC0 zero mapping drift")
    identities = [entry["candidate_identity"] for entry in candidate_receipts]
    require(len(identities) == len(set(identities)), f"GC0 duplicate palette candidate identity: {frozen_group['identity']}")
    status = "PALETTE_COMPLETE" if shortfall == 0 else "PALETTE_SHORTFALL_PRESERVED"
    return {
        "protocol": PROTOCOL,
        "identity": [str(endpoint), int(set_index), int(group_index)],
        "coordinates_total": len(group.coordinates),
        "coordinates_canonical": [int(value) for value in group.coordinates],
        "authority_ranking": [int(value) for value in ranking],
        "horizon": horizon,
        "horizon_ranking": [int(value) for value in horizon_ranking],
        "physical_support_rows": physical_rows,
        "baseline": candidate_receipts[0],
        "palette": candidate_receipts,
        "role_selection": role_selection,
        "candidate_generation": {
            "exact_unique_evaluations_including_zero": len(evaluations),
            "exact_nonzero_replays": max(0, len(evaluations) - 1),
            "max_unique_replays_including_zero": max_replays,
            "frontier_width": frontier_width,
            "exploit_width": exploit_width,
            "explore_width": explore_width,
            "rounds_completed": rounds_completed,
            "termination": termination,
            "cutoff_reached": cutoff,
            "geometry_guard_rejected_expansions": guard_rejected,
            "eligible_nonzero_pool": sum(1 for item in evaluations.values() if item.prefix != zero.prefix and item.guard_pass),
        },
        "palette_counts": {
            "zero_candidates": 1,
            "nonzero_candidates": len(candidate_receipts) - 1,
            "nonzero_requested": MAX_PALETTE_NONZERO,
            "nonzero_shortfall": shortfall,
        },
        "status": status,
        "firewall": {
            "engineering_only": True,
            "scientific_seed_bundles": 0,
            "behavioral_probe": False,
            "scientific_promotion": False,
            "gc1_authorized": False,
        },
    }


def group_filename(identity: list[Any]) -> str:
    endpoint, set_index, group_index = identity
    stem = str(endpoint).removesuffix(".json").replace("/", "_").replace("\\", "_")
    return f"{stem}__set{int(set_index)}__group{int(group_index)}.json"


def run() -> dict[str, Any]:
    contract, preexecution = load_local_contract()
    bindings = verify_parent_provenance(contract, preexecution)
    frozen, states, groups, features, pf5_contract = load_sample(contract)
    runner_hash = RH1.CQ.digest(Path(__file__).resolve())
    preflight = {
        "protocol": PROTOCOL,
        "identity": "q10-gc0-v1",
        "status": "GC0_PREFLIGHT_PASS",
        "plan_sha256": RH1.CQ.digest(ROOT / "PLAN.md"),
        "contract_sha256": RH1.CQ.digest(ROOT / "CONTRACT.json"),
        "runner_sha256": runner_hash,
        "parent_bindings_verified": bindings,
        "sample": contract["sample"],
        "authority_feature_records_loaded": len(features),
        "runtime_endpoints_loaded": len(states),
        "runtime_groups_loaded": len(groups),
        "firewall": contract["firewall"],
    }
    write_json(RECEIPT_ROOT / "preflight.json", preflight)
    write_json(
        QUALIFICATION_ROOT / "derived/STATUS.json",
        {
            "protocol": PROTOCOL,
            "identity": "q10-gc0-v1",
            "status": "GC0_EXECUTION_IN_PROGRESS",
            "plan_sha256": preflight["plan_sha256"],
            "contract_sha256": preflight["contract_sha256"],
            "runner_sha256": runner_hash,
            "parent_bindings_verified": bindings,
            "sample": contract["sample"],
            "scientific_promotion": False,
            "gc1_authorized": False,
        },
    )
    GROUP_ROOT.mkdir(parents=True, exist_ok=True)
    group_receipts: list[dict[str, Any]] = []
    endpoint_keys: set[tuple[str, int]] = set()
    for index, frozen_group in enumerate(frozen, start=1):
        endpoint, set_index, group_index = frozen_group["identity"]
        key = (str(endpoint), int(set_index))
        endpoint_keys.add(key)
        state = states[key]
        raw_group = groups[(key[0], key[1], int(group_index))]
        result = run_group(state, raw_group, frozen_group, features, pf5_contract, contract)
        result["sample_sequence"] = index
        result["receipt_path"] = f"qualification/execution/groups/{group_filename(result['identity'])}"
        path = GROUP_ROOT / group_filename(result["identity"])
        write_json(path, result)
        group_receipts.append(result)
        print(
            f"Q10-GC0 {index}/{len(frozen)} {result['identity']} "
            f"status={result['status']} palette={len(result['palette'])} "
            f"replays={result['candidate_generation']['exact_nonzero_replays']} "
            f"termination={result['candidate_generation']['termination']}",
            flush=True,
        )

    execution = {
        "protocol": PROTOCOL,
        "identity": "q10-gc0-v1",
        "status": "GC0_PALETTES_EXECUTED_PENDING_DERIVATION",
        "plan_sha256": preflight["plan_sha256"],
        "contract_sha256": preflight["contract_sha256"],
        "runner_sha256": runner_hash,
        "parent_bindings_verified": bindings,
        "sample": {
            "endpoint_count": len({key[0] for key in endpoint_keys}),
            "endpoint_set_count": len(endpoint_keys),
            "group_count": len(group_receipts),
            "expected_endpoint_count": contract["sample"]["expected_endpoint_count"],
            "expected_endpoint_set_count": contract["sample"]["expected_endpoint_set_count"],
            "expected_group_count": contract["sample"]["expected_group_count"],
            "full_f2_group_count": contract["sample"]["full_f2_group_count"],
            "endpoint_names": sorted({key[0] for key in endpoint_keys}),
            "endpoint_keys": [list(key) for key in sorted(endpoint_keys)],
        },
        "counts": {
            "endpoint_count": len({key[0] for key in endpoint_keys}),
            "endpoint_set_count": len(endpoint_keys),
            "group_count": len(group_receipts),
            "palette_count": len(group_receipts),
            "zero_candidate_count": sum(item["palette_counts"]["zero_candidates"] for item in group_receipts),
            "nonzero_candidate_count": sum(item["palette_counts"]["nonzero_candidates"] for item in group_receipts),
            "nonzero_candidate_requested": sum(item["palette_counts"]["nonzero_requested"] for item in group_receipts),
            "nonzero_shortfall_group_count": sum(item["palette_counts"]["nonzero_shortfall"] > 0 for item in group_receipts),
            "nonzero_shortfall_total": sum(item["palette_counts"]["nonzero_shortfall"] for item in group_receipts),
            "exact_unique_evaluations_including_zero": sum(item["candidate_generation"]["exact_unique_evaluations_including_zero"] for item in group_receipts),
            "exact_nonzero_replays": sum(item["candidate_generation"]["exact_nonzero_replays"] for item in group_receipts),
        },
        "group_receipts": [item["receipt_path"] for item in group_receipts],
        "qualification": {
            "global_gate_pending": True,
            "conflict_topology_pending": True,
            "gc1_authorized": False,
        },
        "firewall": contract["firewall"],
    }
    write_json(EXECUTION_ROOT / "execution.json", execution)
    print(json.dumps({"status": execution["status"], "endpoints": len(endpoint_keys), "groups": len(group_receipts), "nonzero_candidates": execution["counts"]["nonzero_candidate_count"]}, indent=2))
    return execution


def main() -> int:
    parser = argparse.ArgumentParser(description="run the sealed Q10-GC0 sample")
    parser.parse_args()
    try:
        run()
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as error:
        raise SystemExit(f"Q10-GC0 execution failed closed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

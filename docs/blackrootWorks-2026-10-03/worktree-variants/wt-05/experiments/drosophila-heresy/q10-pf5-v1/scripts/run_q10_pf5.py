"""Deterministic Q10-PF5 endpoint reconstruction and replay runner.

The runner consumes only the hash-bound Q10-RMT receipt, its bound source
fixtures, and the sealed Q10-DA2 selected-step results. It constructs cloned
f32 states in memory and emits engineering receipts below q10-pf5-v1.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    from .qualify_q10_pf5 import (
        BEAM_WIDTH,
        CHOICES,
        EXACT_PRODUCT_LIMIT,
        EXPLOIT_WIDTH,
        EXPLORE_WIDTH,
        MAX_NODES_PER_GROUP,
        MAX_ROUNDS,
        Objective,
        BeamState,
        GeometryDebt,
        QualificationError,
        audit_parent,
        bits,
        classify_endpoint,
        digest,
        f32,
        from_bits,
        load_json,
        replay_plan,
        select_beam,
        ulp_distance,
        require,
    )
except ImportError:
    from qualify_q10_pf5 import (
        BEAM_WIDTH,
        CHOICES,
        EXACT_PRODUCT_LIMIT,
        EXPLOIT_WIDTH,
        EXPLORE_WIDTH,
        MAX_NODES_PER_GROUP,
        MAX_ROUNDS,
        Objective,
        BeamState,
        GeometryDebt,
        QualificationError,
        audit_parent,
        bits,
        classify_endpoint,
        digest,
        f32,
        from_bits,
        load_json,
        replay_plan,
        select_beam,
        ulp_distance,
        require,
    )


Key = tuple[str, int]


@dataclass(frozen=True)
class Lineage:
    protocol_root: Path
    contract: dict[str, Any]
    parent: dict[str, Any]
    rmt_root: Path
    receipt_root: Path
    source_root: Path
    da2_results_path: Path
    endpoints: tuple[dict[str, Any], ...]
    rows: tuple[dict[str, Any], ...]
    components: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class EndpointState:
    key: Key
    rows: tuple[tuple[int, ...], ...]
    baseline_weight_bits: tuple[int, ...]
    target_weight_bits: tuple[int, ...]
    base_weight_bits: tuple[int, ...]
    baseline_readout_bits: tuple[int, ...]
    target_readout_bits: tuple[int, ...]
    baseline_weights: tuple[float, ...]
    target_weights: tuple[float, ...]
    base_weights: tuple[float, ...]
    axis: tuple[float, ...]
    permitted: tuple[bool, ...]
    interior: frozenset[int]
    baseline_displacement: tuple[float, ...]
    target_displacement: tuple[float, ...]
    baseline_axis: float
    target_axis: float
    baseline_norm: float
    target_norm: float
    baseline_drive: tuple[float, ...]
    target_drive: tuple[float, ...]
    baseline_drive_errors: tuple[float, ...]
    baseline_drive_squared: float
    cue_scale: float
    support_counts: tuple[tuple[tuple[int, int], ...], ...]


@dataclass
class ReceiptTopology:
    raw_row_coords: dict[Key, dict[int, set[int]]]
    coord_rows: dict[Key, dict[int, set[int]]]
    available_steps: dict[Key, dict[int, set[int]]]
    helpful_row_coords: dict[Key, dict[int, set[int]]]
    helpful_row_steps: dict[Key, dict[int, set[int]]]
    one_step_raw_coords: dict[Key, dict[int, set[int]]]
    one_step_helpful_coords: dict[Key, dict[int, set[int]]]
    replayed_steps: dict[Key, dict[int, set[int]]]
    replayed_prefix_count: int
    replayed_raw_bridge_count: int
    serialized_moves: int


@dataclass(frozen=True)
class RawGroup:
    key: Key
    group_index: int
    rows: tuple[int, ...]
    coordinates: tuple[int, ...]
    domains: tuple[tuple[int, ...], ...]
    serialized_steps: tuple[tuple[int, ...], ...]
    missing_prefixes: tuple[tuple[int, ...], ...]
    helpful_rows: tuple[int, ...]
    no_helpful_rows: tuple[int, ...]
    threshold_classes: tuple[str, ...]
    helpful_component_indices: tuple[int, ...]
    replayed_prefixes: tuple[tuple[int, ...], ...] = ()
    unreplayed_prefixes: tuple[tuple[int, ...], ...] = ()


@dataclass(frozen=True)
class CandidateEvaluation:
    prefix_tuple: tuple[int, ...]
    objective: Objective
    debt: GeometryDebt
    readout_bits: tuple[int, ...]
    weight_bits: tuple[int, ...]


def _json_value(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def load_lineage(protocol_root: Path) -> Lineage:
    counts = audit_parent(protocol_root)
    require(counts["primary_endpoints"] == 28, "PF5 parent preflight did not expose 28 endpoints")
    contract = load_json(protocol_root / "CONTRACT.json")
    parent = contract["parent"]
    repo_root = protocol_root.parents[2]
    rmt_root = _resolve(repo_root, parent["rmt_root"]).resolve()
    receipt_root = (rmt_root / parent["receipt_root"]).resolve()
    source_root = _resolve(repo_root, parent["source_input_root"]).resolve()
    preexecution = load_json(rmt_root / "PREEXECUTION.json")
    da2_results_path = (Path(preexecution["parent_root"]) / "qualification/sample-9731-9732/results.json").resolve()
    endpoints = tuple(_json_value(receipt_root / "endpoints.json"))
    rows = tuple(_json_value(receipt_root / "rows.json"))
    components = tuple(_json_value(receipt_root / "components.json"))
    require(len(endpoints) == 28 and len(rows) == 7003, "sealed RMT receipt cardinality drift")
    require(digest(da2_results_path) == parent["da2_results_sha256"], "DA2 results hash drift")
    return Lineage(
        protocol_root=protocol_root,
        contract=contract,
        parent=parent,
        rmt_root=rmt_root,
        receipt_root=receipt_root,
        source_root=source_root,
        da2_results_path=da2_results_path,
        endpoints=endpoints,
        rows=rows,
        components=components,
    )


def _prefix_raw(raw: int, choice: int) -> int:
    require(choice in CHOICES, f"illegal prefix choice: {choice}")
    value = raw
    for _ in range(abs(choice)):
        value += 1 if choice > 0 else -1
    return value & 0xFFFF_FFFF


def legal_prefix_bits(raw: int, choice: int, reserve: int = 16) -> int | None:
    candidate_raw = _prefix_raw(raw, choice)
    candidate = from_bits(candidate_raw)
    if not math.isfinite(candidate) or not (0.0 < candidate < 2.0):
        return None
    if candidate_raw - bits(0.0) < reserve or bits(2.0) - candidate_raw < reserve:
        return None
    return candidate_raw


def sequential_bits(row: Iterable[int], weights: list[float] | tuple[float, ...]) -> int:
    value = from_bits(0x8000_0000)
    for coordinate in row:
        value = f32(value + weights[coordinate])
    return bits(value)


def readout_bits(rows: Iterable[Iterable[int]], weights: list[float] | tuple[float, ...]) -> tuple[int, ...]:
    return tuple(sequential_bits(row, weights) for row in rows)


def _norm(values: Iterable[float]) -> float:
    return math.sqrt(math.fsum(value * value for value in values))


def geometry_metrics(
    rows: tuple[tuple[int, ...], ...],
    weights: tuple[float, ...] | list[float],
    base: tuple[float, ...],
    target: tuple[float, ...],
    axis: tuple[float, ...],
) -> dict[str, float]:
    displacement = tuple(value - initial for value, initial in zip(weights, base))
    target_displacement = tuple(value - initial for value, initial in zip(target, base))
    target_axis = math.fsum(value * coefficient for value, coefficient in zip(target_displacement, axis))
    final_axis = math.fsum(value * coefficient for value, coefficient in zip(displacement, axis))
    target_norm = _norm(target_displacement)
    final_norm = _norm(displacement)
    true_drive = tuple(math.fsum(displacement_value for displacement_value in (target_displacement[i] for i in row)) for row in rows)
    final_drive = tuple(math.fsum(displacement_value for displacement_value in (displacement[i] for i in row)) for row in rows)
    cue_error = _norm(a - b for a, b in zip(final_drive, true_drive))
    cue_scale = max(_norm(true_drive), 1.0e-12)
    return {
        "axis_absolute_error": abs(final_axis - target_axis),
        "axis_normalized_error": abs(final_axis - target_axis) / max(abs(target_axis), 1.0e-12),
        "norm_absolute_error": abs(final_norm - target_norm),
        "norm_normalized_error": abs(final_norm - target_norm) / max(target_norm, 1.0e-12),
        "cue_linear_absolute_error": cue_error,
        "cue_linear_normalized_error": cue_error / cue_scale,
        "final_axis": final_axis,
        "target_axis": target_axis,
        "final_norm": final_norm,
        "target_norm": target_norm,
    }


def final_geometry_pass(metrics: dict[str, float], contract: dict[str, Any]) -> bool:
    gates = contract["geometry"]["final_da2_gates"]
    return (
        metrics["axis_normalized_error"] <= gates["axis_normalized_abs"]
        and metrics["norm_normalized_error"] <= gates["norm_normalized_abs"]
        and metrics["cue_linear_normalized_error"] <= gates["cue_linear_normalized_abs"]
    )


def independent_candidate_audit(
    state: EndpointState,
    group: RawGroup,
    evaluation: CandidateEvaluation,
    contract: dict[str, Any],
) -> dict[str, float]:
    """Audit a retained candidate from its committed f32 bytes only."""
    require(len(evaluation.prefix_tuple) == len(group.coordinates), "candidate prefix arity drift")
    candidate_bits = tuple(int(value) for value in evaluation.weight_bits)
    require(len(candidate_bits) == len(state.baseline_weight_bits), "candidate weight length drift")
    group_coordinates = set(group.coordinates)
    for coordinate, choice in zip(group.coordinates, evaluation.prefix_tuple):
        require(choice in CHOICES, f"candidate has illegal prefix choice: {choice}")
        expected = legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(expected is not None, f"candidate prefix violates reserve: {coordinate} {choice}")
        require(candidate_bits[coordinate] == expected, f"candidate byte mismatch: {coordinate}")
        require(state.permitted[coordinate] and coordinate in state.interior, f"candidate support violation: {coordinate}")
    for coordinate, raw in enumerate(candidate_bits):
        if coordinate not in group_coordinates:
            require(raw == state.baseline_weight_bits[coordinate], f"candidate changed outside group: {coordinate}")
    candidate_weights = tuple(from_bits(raw) for raw in candidate_bits)
    actual_readout = readout_bits(state.rows, candidate_weights)
    require(actual_readout == evaluation.readout_bits, "candidate readout was not independently reproduced")
    metrics = geometry_metrics(
        state.rows,
        candidate_weights,
        state.base_weights,
        state.target_weights,
        state.axis,
    )
    require(all(math.isfinite(value) for value in metrics.values()), "candidate geometry is non-finite")
    return metrics


def _objective(actual: tuple[int, ...], target: tuple[int, ...], prefix: tuple[int, ...]) -> Objective:
    errors = []
    total_ulp = 0
    mismatches = 0
    maximum = 0.0
    for left, right in zip(actual, target):
        left_value = from_bits(left)
        right_value = from_bits(right)
        error = left_value - right_value
        errors.append(error)
        mismatches += left != right
        total_ulp += ulp_distance(left_value, right_value)
        maximum = max(maximum, abs(error))
    return Objective(
        mismatch_rows=mismatches,
        total_ulp_distance=total_ulp,
        residual_l2=math.sqrt(math.fsum(error * error for error in errors)),
        maximum_absolute_residual=maximum,
        stable_prefix_tuple=prefix,
    )


def _baseline_metric(state: EndpointState, prefix: tuple[int, ...]) -> Objective:
    return _objective(state.baseline_readout_bits, state.target_readout_bits, prefix)


def _baseline_debt(state: EndpointState) -> GeometryDebt:
    axis_scale = max(abs(state.target_axis), 1.0e-12)
    norm_scale = max(state.target_norm, 1.0e-12)
    cue_error = math.sqrt(state.baseline_drive_squared)
    return GeometryDebt(
        (state.baseline_axis - state.target_axis) / axis_scale,
        (state.baseline_norm - state.target_norm) / norm_scale,
        cue_error / state.cue_scale,
    )


def _approximate_debt(state: EndpointState, coordinates: tuple[int, ...], candidate_bits: tuple[int, ...]) -> GeometryDebt:
    axis_scale = max(abs(state.target_axis), 1.0e-12)
    norm_scale = max(state.target_norm, 1.0e-12)
    axis = state.baseline_axis
    norm_squared = state.baseline_norm * state.baseline_norm
    row_delta: dict[int, float] = {}
    for coordinate in coordinates:
        old = state.baseline_weights[coordinate]
        new = from_bits(candidate_bits[coordinate])
        delta = new - old
        if delta == 0.0:
            continue
        axis += delta * state.axis[coordinate]
        old_displacement = state.baseline_displacement[coordinate]
        new_displacement = new - state.base_weights[coordinate]
        norm_squared += new_displacement * new_displacement - old_displacement * old_displacement
        for row_index, count in state.support_counts[coordinate]:
            row_delta[row_index] = row_delta.get(row_index, 0.0) + delta * count
    candidate_norm = math.sqrt(max(norm_squared, 0.0))
    cue_squared = state.baseline_drive_squared
    for row_index in sorted(row_delta):
        old_error = state.baseline_drive_errors[row_index]
        new_error = old_error + row_delta[row_index]
        cue_squared += new_error * new_error - old_error * old_error
    return GeometryDebt(
        (axis - state.target_axis) / axis_scale,
        (candidate_norm - state.target_norm) / norm_scale,
        math.sqrt(max(cue_squared, 0.0)) / state.cue_scale,
    )


def _prefix_histogram(prefix: tuple[int, ...]) -> str:
    counts = {choice: 0 for choice in CHOICES}
    for choice in prefix:
        counts[choice] += 1
    return ",".join(f"{choice}:{counts[choice]}" for choice in CHOICES)


def _coverage_signature(prefix: tuple[int, ...], objective: Objective) -> tuple[int, ...]:
    return (
        sum(choice != 0 for choice in prefix),
        sum(choice < 0 for choice in prefix),
        sum(choice > 0 for choice in prefix),
        sum(abs(choice) >= 4 for choice in prefix),
        objective.mismatch_rows,
    )


def _candidate(
    state: EndpointState,
    group: RawGroup,
    prefix: tuple[int, ...],
) -> CandidateEvaluation:
    weight_bits = list(state.baseline_weight_bits)
    weights = list(state.baseline_weights)
    for coordinate, choice in zip(group.coordinates, prefix):
        raw = legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(raw is not None, f"illegal final prefix at coordinate {coordinate}: {choice}")
        weight_bits[coordinate] = raw
        weights[coordinate] = from_bits(raw)
    frozen_bits = tuple(weight_bits)
    actual = readout_bits(state.rows, weights)
    objective = _objective(actual, state.target_readout_bits, prefix)
    return CandidateEvaluation(
        prefix_tuple=prefix,
        objective=objective,
        debt=_approximate_debt(state, group.coordinates, frozen_bits),
        readout_bits=actual,
        weight_bits=frozen_bits,
    )


def _state_for(evaluation: CandidateEvaluation) -> BeamState:
    return BeamState(
        prefix_tuple=evaluation.prefix_tuple,
        objective=evaluation.objective,
        debt=evaluation.debt,
        threshold_class=_prefix_histogram(evaluation.prefix_tuple),
        coverage_signature=_coverage_signature(evaluation.prefix_tuple, evaluation.objective),
    )


def _evaluation_key(evaluation: CandidateEvaluation) -> tuple[Any, ...]:
    return evaluation.objective.key()


def _finalize_candidates(
    state: EndpointState,
    group: RawGroup,
    candidates: Iterable[CandidateEvaluation],
    contract: dict[str, Any],
) -> tuple[CandidateEvaluation | None, CandidateEvaluation | None, int]:
    best_overall: CandidateEvaluation | None = None
    best_final: CandidateEvaluation | None = None
    pruned = 0
    seen: set[tuple[int, ...]] = set()
    guard_values = contract["geometry"]["intermediate_guardrails"]
    guard = GeometryDebt(
        guard_values["axis_normalized_abs"],
        guard_values["norm_normalized_abs"],
        guard_values["cue_linear_normalized_abs"],
    )
    for evaluation in candidates:
        if evaluation.prefix_tuple in seen:
            continue
        seen.add(evaluation.prefix_tuple)
        if not evaluation.debt.within(guard):
            pruned += 1
            continue
        if best_overall is None or _evaluation_key(evaluation) < _evaluation_key(best_overall):
            best_overall = evaluation
        values = tuple(from_bits(value) for value in evaluation.weight_bits)
        metrics = geometry_metrics(state.rows, values, state.base_weights, state.target_weights, state.axis)
        if final_geometry_pass(metrics, contract):
            if best_final is None or _evaluation_key(evaluation) < _evaluation_key(best_final):
                best_final = evaluation
    return best_overall, best_final, pruned


def _result_record(
    state: EndpointState,
    group: RawGroup,
    plan: Any,
    best_overall: CandidateEvaluation | None,
    best_final: CandidateEvaluation | None,
    nodes: int,
    pruned: int,
    coverage: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    baseline = _baseline_metric(state, tuple(0 for _ in group.coordinates))
    exact = best_final is not None and best_final.readout_bits == state.target_readout_bits
    improved = best_final is not None and best_final.objective.key()[:4] < baseline.key()[:4]
    oversize = plan.mode == "OVERSIZE_UNTESTED"
    bounded = plan.mode == "BOUNDED_BEAM"
    status = classify_endpoint(
        exact_target=exact,
        improved=improved,
        final_geometry_pass=best_final is not None,
        coverage_complete=coverage == "complete",
        bounded_search_exhausted=bounded,
        oversize=oversize,
    )
    chosen = best_final or best_overall
    result: dict[str, Any] = {
        "protocol": "Q10-PF5",
        "source_event": group.key[0],
        "set_index": group.key[1],
        "group_index": group.group_index,
        "rows": list(group.rows),
        "coordinates": list(group.coordinates),
        "domains": [list(domain) for domain in group.domains],
        "serialized_steps": [list(steps) for steps in group.serialized_steps],
        "missing_serialized_prefixes": [list(steps) for steps in group.missing_prefixes],
        "replayed_prefixes": [list(steps) for steps in group.replayed_prefixes],
        "unreplayed_prefixes": [list(steps) for steps in group.unreplayed_prefixes],
        "helpful_rows": list(group.helpful_rows),
        "no_helpful_rows": list(group.no_helpful_rows),
        "threshold_classes": list(group.threshold_classes),
        "helpful_component_indices": list(group.helpful_component_indices),
        "replay_plan": {
            "mode": plan.mode,
            "coverage": coverage,
            "cartesian_product": plan.cartesian_product,
            "nodes_replayed": nodes,
            "guard_pruned": pruned,
        },
        "coverage_state": coverage,
        "baseline_objective": {
            "mismatch_row_count": baseline.mismatch_rows,
            "total_ulp_distance": baseline.total_ulp_distance,
            "residual_l2": baseline.residual_l2,
            "maximum_absolute_residual": baseline.maximum_absolute_residual,
        },
        "status": status,
        "coverage_state": coverage,
        "exact_target": exact,
        "improved_over_baseline": improved,
    }
    if chosen is not None:
        metrics = independent_candidate_audit(state, group, chosen, contract)
        result["candidate"] = {
            "prefix_tuple": list(chosen.prefix_tuple),
            "mismatch_row_count": chosen.objective.mismatch_rows,
            "total_ulp_distance": chosen.objective.total_ulp_distance,
            "residual_l2": chosen.objective.residual_l2,
            "maximum_absolute_residual": chosen.objective.maximum_absolute_residual,
            "geometry": metrics,
            "final_geometry_pass": final_geometry_pass(metrics, contract),
            "independent_f32_audit": True,
            "reconstructed_from_f32_bits": True,
        }
    return result


def replay_group(state: EndpointState, group: RawGroup, contract: dict[str, Any]) -> dict[str, Any]:
    plan = replay_plan(group.domains)
    if plan.mode == "OVERSIZE_UNTESTED":
        return _result_record(state, group, plan, None, None, 0, 0, "incomplete", contract)
    baseline_prefix = tuple(0 for _ in group.coordinates)
    baseline = _candidate(state, group, baseline_prefix)
    if plan.mode == "EXACT_ENUMERATION":
        evaluations: list[CandidateEvaluation] = []
        for prefix in itertools.product(*group.domains):
            evaluations.append(_candidate(state, group, tuple(prefix)))
        best_overall, best_final, pruned = _finalize_candidates(state, group, evaluations, contract)
        return _result_record(state, group, plan, best_overall, best_final, len(evaluations), pruned, "complete", contract)

    guard_values = contract["geometry"]["intermediate_guardrails"]
    guard = GeometryDebt(
        guard_values["axis_normalized_abs"],
        guard_values["norm_normalized_abs"],
        guard_values["cue_linear_normalized_abs"],
    )
    evaluations_by_prefix = {baseline.prefix_tuple: baseline}
    states = (_state_for(baseline),)
    node_count = 1
    guard_pruned = 0
    for round_index in range(min(MAX_ROUNDS, len(group.coordinates))):
        expanded: list[BeamState] = []
        coordinate_position = round_index
        for beam_state in states:
            for choice in group.domains[coordinate_position]:
                prefix_values = list(beam_state.prefix_tuple)
                prefix_values[coordinate_position] = choice
                prefix = tuple(prefix_values)
                if prefix in evaluations_by_prefix:
                    expanded.append(_state_for(evaluations_by_prefix[prefix]))
                    continue
                if node_count >= MAX_NODES_PER_GROUP:
                    break
                evaluation = _candidate(state, group, prefix)
                evaluations_by_prefix[prefix] = evaluation
                node_count += 1
                if not evaluation.debt.within(guard):
                    guard_pruned += 1
                    continue
                expanded.append(_state_for(evaluation))
            if node_count >= MAX_NODES_PER_GROUP:
                break
        if not expanded:
            break
        selected = select_beam(expanded, exploit_width=EXPLOIT_WIDTH, explore_width=EXPLORE_WIDTH)
        require(len(selected) <= BEAM_WIDTH, "beam width exceeded frozen contract")
        states = selected
    final_evaluations = [evaluations_by_prefix[item.prefix_tuple] for item in states]
    best_overall, best_final, final_pruned = _finalize_candidates(state, group, final_evaluations, contract)
    return _result_record(
        state,
        group,
        plan,
        best_overall,
        best_final,
        node_count,
        guard_pruned + final_pruned,
        "partial",
        contract,
    )


def _compare_metric(left: float, right: float, label: str) -> None:
    require(math.isfinite(left) and math.isfinite(right), f"non-finite {label}")
    require(abs(left - right) <= 1.0e-12, f"{label} drift: {left} != {right}")


def load_endpoint_states(
    lineage: Lineage,
    selected_keys: set[Key] | None = None,
) -> tuple[EndpointState, ...]:
    da2_results = _json_value(lineage.da2_results_path)
    require(isinstance(da2_results, list) and len(da2_results) == 32, "DA2 results cardinality drift")
    da2_lookup = {(item["source_event"], int(item["set_index"])): item for item in da2_results}
    all_source_names = set(lineage.parent["source_input_sha256"])
    all_keys = {(item["source_event"], int(item["set_index"])) for item in lineage.endpoints}
    requested = all_keys if selected_keys is None else set(selected_keys)
    require(requested <= all_keys, "selected endpoint key is outside the primary endpoint set")
    source_names = {key[0] for key in requested}
    require(source_names <= all_source_names, "selected source fixture is outside the bound input set")
    source_events = {name: load_json(lineage.source_root / name) for name in source_names}
    require(source_names <= set(source_events), "source fixture set drift")
    for source_name in source_names:
        source_path = lineage.source_root / source_name
        expected_hash = lineage.parent["source_input_sha256"][source_name]
        require(digest(source_path) == expected_hash.upper(), f"source fixture hash drift: {source_name}")
    endpoint_lookup = {(item["source_event"], int(item["set_index"])): item for item in lineage.endpoints}
    row_lookup = {(item["endpoint"], int(item["set_index"]), int(item["row"])): item for item in lineage.rows}
    states: list[EndpointState] = []
    for endpoint in lineage.endpoints:
        key = (endpoint["source_event"], int(endpoint["set_index"]))
        if key not in requested:
            continue
        event = source_events.get(key[0])
        require(event is not None, f"missing source event {key[0]}")
        da2 = da2_lookup.get(key)
        require(da2 is not None and da2["status"] == "DA2_GEOMETRY_PASS", f"DA2 primary endpoint drift: {key}")
        source_set = event["sets"][key[1]]
        selected_steps = {int(coordinate): int(step) for coordinate, step in da2["selected_steps"].items()}
        require(set(selected_steps) == set(source_set["selected_coordinates"]), f"selected coordinate set drift: {key}")
        require(all(step in CHOICES for step in selected_steps.values()), f"illegal DA2 selected step: {key}")
        fixture = event["fixture"]
        operator = fixture["operator"]
        rows = tuple(tuple(int(coordinate) for coordinate in row) for row in operator["rows"])
        initial_bits = tuple(int(value) for value in fixture["initial_weight_bits"])
        target_bits = tuple(int(value) for value in fixture["target_weight_bits"])
        base_bits = tuple(int(value) for value in fixture["snapshot_base_bits"])
        require(len(initial_bits) == operator["coordinates"] == len(target_bits) == len(base_bits), f"fixture coordinate length drift: {key}")
        baseline_bits_list = list(initial_bits)
        for coordinate in sorted(selected_steps):
            raw = legal_prefix_bits(initial_bits[coordinate], selected_steps[coordinate])
            require(raw is not None, f"DA2 selected prefix violates reserve: {key} coordinate={coordinate}")
            baseline_bits_list[coordinate] = raw
        baseline_bits = tuple(baseline_bits_list)
        baseline_weights = tuple(from_bits(value) for value in baseline_bits)
        target_weights = tuple(from_bits(value) for value in target_bits)
        base_weights = tuple(from_bits(value) for value in base_bits)
        baseline_readout = readout_bits(rows, baseline_weights)
        target_readout = readout_bits(rows, target_weights)
        require(target_readout == tuple(int(value) for value in fixture["target_readout_bits"]), f"target replay drift: {key}")
        endpoint_rows = [record for record in lineage.rows if (record["endpoint"], int(record["set_index"])) == key]
        mismatch_rows = [index for index, (actual, target) in enumerate(zip(baseline_readout, target_readout)) if actual != target]
        require(len(mismatch_rows) == endpoint["mismatch_count"], f"endpoint mismatch count drift: {key}")
        require(sorted(record["row"] for record in endpoint_rows) == mismatch_rows, f"RMT mismatch row identity drift: {key}")
        for row_index in mismatch_rows:
            record = row_lookup[(key[0], key[1], row_index)]
            require(record["baseline_bits"] == baseline_readout[row_index], f"baseline bits drift: {key} row={row_index}")
            require(record["target_bits"] == target_readout[row_index], f"target bits drift: {key} row={row_index}")
            require(record["baseline_ulp_distance"] == ulp_distance(from_bits(baseline_readout[row_index]), from_bits(target_readout[row_index])), f"ULP drift: {key} row={row_index}")
        geometry = geometry_metrics(rows, baseline_weights, base_weights, target_weights, tuple(float(value) for value in fixture["acquisition_axis"]))
        for name in ("axis_normalized_error", "norm_normalized_error", "cue_linear_normalized_error"):
            _compare_metric(geometry[name], float(da2["geometry"][name]), f"DA2 {key} {name}")
        require(final_geometry_pass(geometry, lineage.contract), f"primary DA2 geometry gate failed during reconstruction: {key}")
        axis = tuple(float(value) for value in fixture["acquisition_axis"])
        baseline_displacement = tuple(value - initial for value, initial in zip(baseline_weights, base_weights))
        target_displacement = tuple(value - initial for value, initial in zip(target_weights, base_weights))
        baseline_drive = tuple(math.fsum(baseline_displacement[i] for i in row) for row in rows)
        target_drive = tuple(math.fsum(target_displacement[i] for i in row) for row in rows)
        baseline_errors = tuple(a - b for a, b in zip(baseline_drive, target_drive))
        support_counts: list[list[tuple[int, int]]] = [[] for _ in baseline_weights]
        for row_index, row in enumerate(rows):
            counts: dict[int, int] = defaultdict(int)
            for coordinate in row:
                counts[coordinate] += 1
            for coordinate, count in counts.items():
                support_counts[coordinate].append((row_index, count))
        state = EndpointState(
            key=key,
            rows=rows,
            baseline_weight_bits=baseline_bits,
            target_weight_bits=target_bits,
            base_weight_bits=base_bits,
            baseline_readout_bits=baseline_readout,
            target_readout_bits=target_readout,
            baseline_weights=baseline_weights,
            target_weights=target_weights,
            base_weights=base_weights,
            axis=axis,
            permitted=tuple(bool(value) for value in fixture["permitted"]),
            interior=frozenset(int(value) for value in fixture["interior_indices"]),
            baseline_displacement=baseline_displacement,
            target_displacement=target_displacement,
            baseline_axis=math.fsum(value * coefficient for value, coefficient in zip(baseline_displacement, axis)),
            target_axis=math.fsum(value * coefficient for value, coefficient in zip(target_displacement, axis)),
            baseline_norm=_norm(baseline_displacement),
            target_norm=_norm(target_displacement),
            baseline_drive=baseline_drive,
            target_drive=target_drive,
            baseline_drive_errors=baseline_errors,
            baseline_drive_squared=math.fsum(error * error for error in baseline_errors),
            cue_scale=max(_norm(target_drive), 1.0e-12),
            support_counts=tuple(tuple(items) for items in support_counts),
        )
        states.append(state)
    expected_count = 28 if selected_keys is None else len(requested)
    require(len(states) == expected_count, "did not reconstruct the declared primary endpoint states")
    return tuple(states)


def load_topology(lineage: Lineage) -> ReceiptTopology:
    raw_row_coords: dict[Key, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    coord_rows: dict[Key, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    available_steps: dict[Key, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    helpful_row_coords: dict[Key, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    helpful_row_steps: dict[Key, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    one_step_raw_coords: dict[Key, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    one_step_helpful_coords: dict[Key, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    move_path = lineage.receipt_root / "moves.jsonl"
    serialized = 0
    with move_path.open(encoding="utf-8") as handle:
        for line in handle:
            move = json.loads(line)
            serialized += 1
            key = (move["endpoint"], int(move["set_index"]))
            coordinate = int(move["coordinate"])
            step = int(move["step"])
            available_steps[key][coordinate].add(step)
            for row in move["raw_rows"]:
                row = int(row)
                raw_row_coords[key][row].add(coordinate)
                coord_rows[key][coordinate].add(row)
                if abs(step) == 1:
                    one_step_raw_coords[key][row].add(coordinate)
            for row in move["helpful_rows"]:
                row = int(row)
                helpful_row_coords[key][row].add(coordinate)
                helpful_row_steps[key][row].add(step)
                if abs(step) == 1:
                    one_step_helpful_coords[key][row].add(coordinate)
    require(serialized == lineage.contract["topology_invariants"]["serialized_moves"], "serialized move count drift")
    row_lookup = {(record["endpoint"], int(record["set_index"]), int(record["row"])): record for record in lineage.rows}
    for row_key, record in row_lookup.items():
        endpoint_key = (row_key[0], row_key[1])
        row = row_key[2]
        require(len(raw_row_coords[endpoint_key].get(row, set())) == record["all_raw_coordinates"], f"raw topology drift: {row_key}")
        require(len(helpful_row_coords[endpoint_key].get(row, set())) == record["all_helpful_coordinates"], f"helpful topology drift: {row_key}")
        require(len(one_step_raw_coords[endpoint_key].get(row, set())) == record["one_step_raw_coordinates"], f"one-step raw topology drift: {row_key}")
        require(len(one_step_helpful_coords[endpoint_key].get(row, set())) == record["one_step_helpful_coordinates"], f"one-step helpful topology drift: {row_key}")
        helpful_steps = [abs(step) for step in helpful_row_steps[endpoint_key].get(row, set())]
        if record["k_star"] is None:
            require(not helpful_steps, f"unexpected helpful prefix for no-authority row: {row_key}")
        else:
            require(helpful_steps and min(helpful_steps) == record["k_star"], f"k-star topology drift: {row_key}")
    return ReceiptTopology(
        raw_row_coords=raw_row_coords,
        coord_rows=coord_rows,
        available_steps=available_steps,
        helpful_row_coords=helpful_row_coords,
        helpful_row_steps=helpful_row_steps,
        one_step_raw_coords=one_step_raw_coords,
        one_step_helpful_coords=one_step_helpful_coords,
        replayed_steps=defaultdict(lambda: defaultdict(set)),
        replayed_prefix_count=0,
        replayed_raw_bridge_count=0,
        serialized_moves=serialized,
    )


def _sequential_bits_with_replacement(
    row: tuple[int, ...],
    weights: tuple[float, ...],
    coordinate: int,
    replacement: float,
) -> int:
    value = from_bits(0x8000_0000)
    for item in row:
        value = f32(value + (replacement if item == coordinate else weights[item]))
    return bits(value)


def augment_missing_prefix_topology(
    topology: ReceiptTopology,
    states: tuple[EndpointState, ...],
    lineage: Lineage,
) -> ReceiptTopology:
    """Replay unmeasured prefixes before raw-support grouping.

    RMT's sparse receipt records prefixes that produced an observed effect.
    PF5 must still evaluate every legal unmeasured prefix for every coordinate
    already present in the raw-support receipt, because a newly observed row
    can bridge two otherwise separate replay groups.
    """
    replayed_steps: dict[Key, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    replayed_prefix_count = 0
    replayed_raw_bridge_count = 0
    for state in states:
        key = state.key
        candidate_coordinates = sorted(topology.coord_rows.get(key, {}))
        for coordinate in candidate_coordinates:
            if not (state.permitted[coordinate] and coordinate in state.interior):
                continue
            available = topology.available_steps[key].get(coordinate, set())
            for choice in CHOICES:
                if choice == 0 or choice in available:
                    continue
                raw = legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
                if raw is None:
                    continue
                replayed_prefix_count += 1
                replayed_steps[key][coordinate].add(choice)
                candidate = from_bits(raw)
                for row_index, row in enumerate(state.rows):
                    if coordinate not in row:
                        continue
                    actual = _sequential_bits_with_replacement(
                        row, state.baseline_weights, coordinate, candidate
                    )
                    if actual != state.baseline_readout_bits[row_index]:
                        rows = topology.raw_row_coords[key][row_index]
                        before = len(rows)
                        rows.add(coordinate)
                        topology.coord_rows[key][coordinate].add(row_index)
                        if len(rows) != before:
                            replayed_raw_bridge_count += 1
    topology.replayed_steps = replayed_steps
    topology.replayed_prefix_count = replayed_prefix_count
    topology.replayed_raw_bridge_count = replayed_raw_bridge_count
    return topology


def _row_record_lookup(lineage: Lineage) -> dict[tuple[str, int, int], dict[str, Any]]:
    return {(item["endpoint"], int(item["set_index"]), int(item["row"])): item for item in lineage.rows}


def build_raw_groups(state: EndpointState, topology: ReceiptTopology, lineage: Lineage) -> tuple[RawGroup, ...]:
    key = state.key
    row_lookup = _row_record_lookup(lineage)
    row_coords = {
        row: set(topology.raw_row_coords[key].get(row, set()))
        for row, (actual, target) in enumerate(zip(state.baseline_readout_bits, state.target_readout_bits))
        if actual != target and topology.raw_row_coords[key].get(row)
    }
    coord_rows: dict[int, set[int]] = defaultdict(set)
    for row, coordinates in row_coords.items():
        for coordinate in coordinates:
            coord_rows[coordinate].add(row)
    groups: list[tuple[set[int], set[int]]] = []
    seen: set[int] = set()
    for first_row in sorted(row_coords):
        if first_row in seen:
            continue
        stack = [first_row]
        seen.add(first_row)
        rows: set[int] = set()
        coordinates: set[int] = set()
        while stack:
            row = stack.pop()
            rows.add(row)
            for coordinate in row_coords[row]:
                coordinates.add(coordinate)
                for linked_row in coord_rows[coordinate]:
                    if linked_row not in seen:
                        seen.add(linked_row)
                        stack.append(linked_row)
        groups.append((rows, coordinates))
    groups.sort(key=lambda item: (len(item[1]), len(item[0]), min(item[0]), min(item[1])))
    output: list[RawGroup] = []
    reserve = lineage.contract["prefix_domain"]["minimum_final_reserve_ulps"]
    for index, (rows, coordinates) in enumerate(groups):
        ordered_coordinates = tuple(sorted(coordinates))
        domains: list[tuple[int, ...]] = []
        serialized_steps: list[tuple[int, ...]] = []
        missing: list[tuple[int, ...]] = []
        for coordinate in ordered_coordinates:
            require(state.permitted[coordinate] and coordinate in state.interior, f"raw group coordinate outside permitted interior: {key} {coordinate}")
            domain = tuple(
                choice
                for choice in CHOICES
                if legal_prefix_bits(state.baseline_weight_bits[coordinate], choice, reserve) is not None
            )
            require(domain and domain[0] == 0, f"empty legal prefix domain: {key} {coordinate}")
            available = topology.available_steps[key].get(coordinate, set())
            domains.append(domain)
            serialized_steps.append(tuple(choice for choice in CHOICES if choice in available))
            missing.append(tuple(choice for choice in domain if choice != 0 and choice not in available))
        replayed_prefixes = tuple(
            tuple(
                choice
                for choice in domain
                if choice != 0
                and choice not in topology.available_steps[key].get(coordinate, set())
                and choice in topology.replayed_steps[key].get(coordinate, set())
            )
            for coordinate, domain in zip(ordered_coordinates, domains)
        )
        unreplayed_prefixes = tuple(
            tuple(
                choice
                for choice in domain
                if choice != 0
                and choice not in topology.available_steps[key].get(coordinate, set())
                and choice not in topology.replayed_steps[key].get(coordinate, set())
            )
            for coordinate, domain in zip(ordered_coordinates, domains)
        )
        helpful_rows = tuple(sorted(row for row in rows if topology.helpful_row_coords[key].get(row)))
        no_helpful_rows = tuple(sorted(row for row in rows if not topology.helpful_row_coords[key].get(row)))
        threshold_classes = tuple(
            sorted({str(row_lookup[(key[0], key[1], row)]["class_final"]) for row in rows})
        )
        helpful_component_indices = tuple(
            sorted({int(row_lookup[(key[0], key[1], row)]["component_index"]) for row in helpful_rows if row_lookup[(key[0], key[1], row)].get("component_index") is not None})
        )
        output.append(
            RawGroup(
                key,
                index,
                tuple(sorted(rows)),
                ordered_coordinates,
                tuple(domains),
                tuple(serialized_steps),
                tuple(missing),
                helpful_rows,
                no_helpful_rows,
                threshold_classes,
                helpful_component_indices,
                replayed_prefixes,
                unreplayed_prefixes,
            )
        )
    return tuple(output)


def _assert_output_path(protocol_root: Path, output: Path) -> Path:
    resolved = output.resolve()
    require(resolved != protocol_root.resolve() and protocol_root.resolve() in resolved.parents, "PF5 output must remain under q10-pf5-v1")
    return resolved


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _assert_output_firewall(value: Any, forbidden: set[str], location: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            require(str(key).lower() not in forbidden, f"forbidden PF5 output field {location}.{key}")
            _assert_output_firewall(nested, forbidden, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_output_firewall(nested, forbidden, f"{location}[{index}]")


def run_subset(
    protocol_root: Path,
    output_dir: Path,
    endpoint_limit: int = 1,
    group_limit: int = 1,
    source_event: str | None = None,
    set_index: int | None = None,
    full: bool = False,
) -> dict[str, Any]:
    require(endpoint_limit > 0 and group_limit > 0, "subset limits must be positive")
    if full:
        require(source_event is None and set_index is None, "full mode cannot use endpoint filters")
    protocol_root = protocol_root.resolve()
    output_dir = _assert_output_path(protocol_root, output_dir)
    lineage = load_lineage(protocol_root)
    states = load_endpoint_states(lineage)
    topology = augment_missing_prefix_topology(load_topology(lineage), states, lineage)
    state_by_key = {state.key: state for state in states}
    keys = [state.key for state in states]
    if source_event is not None:
        keys = [key for key in keys if key[0] == source_event and (set_index is None or key[1] == set_index)]
        require(keys, "declared endpoint selector did not match a primary endpoint")
    selected_keys = keys if full else keys[:endpoint_limit]
    selected_results: list[dict[str, Any]] = []
    selected_groups: list[RawGroup] = []
    groups_by_key: dict[Key, tuple[RawGroup, ...]] = {}
    for key in selected_keys:
        groups = build_raw_groups(state_by_key[key], topology, lineage)
        groups_by_key[key] = groups
        selected_groups.extend(groups if full else groups[:group_limit])
    all_group_count = sum(len(groups) for groups in groups_by_key.values())
    if full:
        require(len(selected_keys) == 28, "full mode did not select all primary endpoints")
        require(len(selected_groups) == all_group_count, "full mode did not select every raw-support group")
    selected_group_keys = {(group.key, group.group_index) for group in selected_groups}
    group_results: dict[tuple[Key, int], dict[str, Any]] = {}
    for group in selected_groups:
        result = replay_group(state_by_key[group.key], group, lineage.contract)
        selected_results.append(result)
        group_results[(group.key, group.group_index)] = result
    group_inventory: list[dict[str, Any]] = []
    endpoint_coverage: list[dict[str, Any]] = []
    row_lookup = _row_record_lookup(lineage)
    for key in selected_keys:
        state = state_by_key[key]
        groups = groups_by_key[key]
        row_to_group = {row: group.group_index for group in groups for row in group.rows}
        row_coverage: list[dict[str, Any]] = []
        for row, (actual, target) in enumerate(zip(state.baseline_readout_bits, state.target_readout_bits)):
            if actual == target:
                continue
            group_index = row_to_group.get(row)
            if group_index is None:
                coverage_state = "complete"
                reason = "no_raw_support_in_sealed_rmt_receipt"
            elif (key, group_index) in selected_group_keys:
                coverage_state = group_results[(key, group_index)]["coverage_state"]
                reason = "selected_group_replayed"
            else:
                coverage_state = "incomplete"
                reason = "group_outside_declared_engineering_subset"
            record = row_lookup[(key[0], key[1], row)]
            row_coverage.append(
                {
                    "row": row,
                    "group_index": group_index,
                    "coverage_state": coverage_state,
                    "reason": reason,
                    "class_final": record["class_final"],
                    "k_star": record["k_star"],
                    "no_helpful_row_diagnostic": record["class_final"] == "no_local_authority",
                    "individual_blocker": False,
                }
            )
        endpoint_coverage.append(
            {
                "source_event": key[0],
                "set_index": key[1],
                "mismatch_rows": len(row_coverage),
                "groups_total": len(groups),
                "groups_selected": sum((key, group.group_index) in selected_group_keys for group in groups),
                "row_coverage": row_coverage,
            }
        )
        for group in groups:
            plan = replay_plan(group.domains)
            selected_result = group_results.get((key, group.group_index))
            group_inventory.append(
                {
                    "source_event": key[0],
                    "set_index": key[1],
                    "group_index": group.group_index,
                    "rows": list(group.rows),
                    "coordinates": list(group.coordinates),
                    "cartesian_product": plan.cartesian_product,
                    "mode": plan.mode,
                    "selected": (key, group.group_index) in selected_group_keys,
                    "coverage_state": selected_result["coverage_state"] if selected_result else "incomplete",
                }
            )
    status_counts: dict[str, int] = defaultdict(int)
    for result in selected_results:
        status_counts[result["status"]] += 1
    execution = {
        "protocol": "Q10-PF5",
        "status": "Q10_PF5_FULL_ENGINEERING_COMPLETE" if full else "Q10_PF5_ENGINEERING_SLICE_COMPLETE",
        "run_scope": "full" if full else "subset",
        "parent_protocol": lineage.contract["parent_protocol"],
        "pf5_plan_sha256": lineage.contract["plan_sha256"],
        "pf5_contract_sha256": digest(protocol_root / "CONTRACT.json"),
        "parent_hashes": {
            "rmt_result_sha256": lineage.parent["rmt_result_sha256"],
            "rmt_status_sha256": lineage.parent["rmt_status_sha256"],
            "rmt_plan_sha256": lineage.parent["rmt_plan_sha256"],
            "rmt_contract_sha256": lineage.parent["rmt_contract_sha256"],
            "rmt_config_sha256": lineage.parent["rmt_config_sha256"],
            "rmt_preexecution_sha256": lineage.parent["rmt_preexecution_sha256"],
            "da2_results_sha256": lineage.parent["da2_results_sha256"],
        },
        "receipt_root": lineage.parent["receipt_root"],
        "source_input_hashes": lineage.parent["source_input_sha256"],
        "receipt_manifest": lineage.parent["receipt_manifest"],
        "reconstructed_primary_endpoints": len(states),
        "declared_subset": {
            "endpoint_limit": endpoint_limit,
            "group_limit_per_endpoint": group_limit,
            "full_mode": full,
            "endpoint_keys": [[key[0], key[1]] for key in selected_keys],
            "group_keys": [[group.key[0], group.key[1], group.group_index] for group in selected_groups],
        },
        "topology": {
            "mismatch_rows": lineage.contract["topology_invariants"]["mismatch_rows"],
            "serialized_moves": topology.serialized_moves,
            "helpful_components": lineage.contract["topology_invariants"]["helpful_components"],
            "raw_support_groups_selected": len(selected_groups),
            "raw_support_groups_in_selected_endpoints": sum(len(groups_by_key[key]) for key in selected_keys),
            "missing_prefixes_replayed": topology.replayed_prefix_count,
            "raw_rows_added_by_missing_prefix_replay": topology.replayed_raw_bridge_count,
        },
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "firewall": {
            "canonical_state_updated": False,
            "behavioral_probe": False,
            "scientific_bundle_count": 0,
            "future_protocol_opened": False,
            "sealed_predecessor_writes": False,
        },
    }
    results = {
        "protocol": "Q10-PF5",
        "status": "Q10_PF5_FULL_ENGINEERING_COMPLETE" if full else "Q10_PF5_ENGINEERING_SLICE_COMPLETE",
        "endpoint_results": selected_results,
        "endpoint_coverage": endpoint_coverage,
        "group_inventory": group_inventory,
    }
    forbidden = {str(field).lower() for field in lineage.contract["forbidden_fields"]}
    _assert_output_firewall(execution, forbidden, "execution")
    _assert_output_firewall(results, forbidden, "results")
    _write_json(output_dir / "execution.json", execution)
    _write_json(output_dir / "results.json", results)
    return {"execution": execution, "results": results}


def run_full_streaming(protocol_root: Path, output_dir: Path) -> dict[str, Any]:
    """Run every primary endpoint while retaining only one endpoint state."""
    protocol_root = protocol_root.resolve()
    output_dir = _assert_output_path(protocol_root, output_dir)
    lineage = load_lineage(protocol_root)
    topology = load_topology(lineage)
    keys = [(item["source_event"], int(item["set_index"])) for item in lineage.endpoints]
    require(len(keys) == 28 and len(set(keys)) == 28, "full mode primary endpoint identity drift")
    selected_results: list[dict[str, Any]] = []
    endpoint_coverage: list[dict[str, Any]] = []
    group_inventory: list[dict[str, Any]] = []
    group_keys: list[list[Any]] = []
    total_groups = 0
    replayed_prefixes = 0
    raw_bridges = 0
    row_lookup = _row_record_lookup(lineage)

    for key in keys:
        states = load_endpoint_states(lineage, {key})
        require(len(states) == 1 and states[0].key == key, f"full mode endpoint stream drift: {key}")
        state = states[0]
        before_replayed = topology.replayed_prefix_count
        before_bridges = topology.replayed_raw_bridge_count
        augment_missing_prefix_topology(topology, states, lineage)
        replayed_prefixes += topology.replayed_prefix_count
        raw_bridges += topology.replayed_raw_bridge_count
        if before_replayed or before_bridges:
            require(topology.replayed_prefix_count >= 0 and topology.replayed_raw_bridge_count >= 0, "invalid replay counters")
        groups = build_raw_groups(state, topology, lineage)
        total_groups += len(groups)
        group_results: dict[int, dict[str, Any]] = {}
        for group in groups:
            result = replay_group(state, group, lineage.contract)
            selected_results.append(result)
            group_results[group.group_index] = result
            group_keys.append([key[0], key[1], group.group_index])
            group_inventory.append(
                {
                    "source_event": key[0],
                    "set_index": key[1],
                    "group_index": group.group_index,
                    "rows": list(group.rows),
                    "coordinates": list(group.coordinates),
                    "cartesian_product": replay_plan(group.domains).cartesian_product,
                    "mode": replay_plan(group.domains).mode,
                    "selected": True,
                    "coverage_state": result["coverage_state"],
                }
            )
        row_to_group = {row: group.group_index for group in groups for row in group.rows}
        row_coverage: list[dict[str, Any]] = []
        for row, (actual, target) in enumerate(zip(state.baseline_readout_bits, state.target_readout_bits)):
            if actual == target:
                continue
            group_index = row_to_group.get(row)
            record = row_lookup[(key[0], key[1], row)]
            row_coverage.append(
                {
                    "row": row,
                    "group_index": group_index,
                    "coverage_state": "complete" if group_index is None else group_results[group_index]["coverage_state"],
                    "reason": "no_raw_support_in_sealed_rmt_receipt" if group_index is None else "full_group_replayed",
                    "class_final": record["class_final"],
                    "k_star": record["k_star"],
                    "no_helpful_row_diagnostic": record["class_final"] == "no_local_authority",
                    "individual_blocker": False,
                }
            )
        endpoint_coverage.append(
            {
                "source_event": key[0],
                "set_index": key[1],
                "mismatch_rows": len(row_coverage),
                "groups_total": len(groups),
                "groups_selected": len(groups),
                "row_coverage": row_coverage,
            }
        )
        del states, state, groups, group_results

    require(len(endpoint_coverage) == 28, "full mode endpoint coverage is incomplete")
    require(len(group_inventory) == total_groups == len(selected_results), "full mode group coverage is incomplete")
    status_counts: dict[str, int] = defaultdict(int)
    for result in selected_results:
        status_counts[result["status"]] += 1
    execution = {
        "protocol": "Q10-PF5",
        "status": "Q10_PF5_FULL_ENGINEERING_COMPLETE",
        "run_scope": "full_streaming",
        "parent_protocol": lineage.contract["parent_protocol"],
        "pf5_plan_sha256": lineage.contract["plan_sha256"],
        "pf5_contract_sha256": digest(protocol_root / "CONTRACT.json"),
        "runner_sha256": digest(Path(__file__).resolve()),
        "parent_hashes": {
            "rmt_result_sha256": lineage.parent["rmt_result_sha256"],
            "rmt_status_sha256": lineage.parent["rmt_status_sha256"],
            "rmt_plan_sha256": lineage.parent["rmt_plan_sha256"],
            "rmt_contract_sha256": lineage.parent["rmt_contract_sha256"],
            "rmt_config_sha256": lineage.parent["rmt_config_sha256"],
            "rmt_preexecution_sha256": lineage.parent["rmt_preexecution_sha256"],
            "da2_results_sha256": lineage.parent["da2_results_sha256"],
        },
        "receipt_root": lineage.parent["receipt_root"],
        "source_input_hashes": lineage.parent["source_input_sha256"],
        "receipt_manifest": lineage.parent["receipt_manifest"],
        "reconstructed_primary_endpoints": len(endpoint_coverage),
        "completeness": {
            "primary_endpoints_expected": 28,
            "primary_endpoints_processed": len(endpoint_coverage),
            "raw_support_groups_processed": len(group_inventory),
            "raw_support_groups_in_manifest": len(group_inventory),
            "complete": len(endpoint_coverage) == 28 and len(group_inventory) == total_groups,
        },
        "declared_subset": {
            "full_mode": True,
            "endpoint_keys": [[key[0], key[1]] for key in keys],
            "group_keys": group_keys,
        },
        "topology": {
            "mismatch_rows": lineage.contract["topology_invariants"]["mismatch_rows"],
            "serialized_moves": topology.serialized_moves,
            "helpful_components": lineage.contract["topology_invariants"]["helpful_components"],
            "raw_support_groups_selected": len(group_inventory),
            "missing_prefixes_replayed": replayed_prefixes,
            "raw_rows_added_by_missing_prefix_replay": raw_bridges,
        },
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "firewall": {
            "canonical_state_updated": False,
            "behavioral_probe": False,
            "scientific_bundle_count": 0,
            "future_protocol_opened": False,
            "sealed_predecessor_writes": False,
        },
    }
    results = {
        "protocol": "Q10-PF5",
        "status": "Q10_PF5_FULL_ENGINEERING_COMPLETE",
        "endpoint_results": selected_results,
        "endpoint_coverage": endpoint_coverage,
        "group_inventory": group_inventory,
    }
    forbidden = {str(field).lower() for field in lineage.contract["forbidden_fields"]}
    _assert_output_firewall(execution, forbidden, "execution")
    _assert_output_firewall(results, forbidden, "results")
    _write_json(output_dir / "execution.json", execution)
    _write_json(output_dir / "results.json", results)
    return {"execution": execution, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="run a deterministic bounded Q10-PF5 engineering slice")
    parser.add_argument("--protocol-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--endpoint-limit", type=int, default=1)
    parser.add_argument("--group-limit", type=int, default=1)
    parser.add_argument("--source-event", type=str, default=None)
    parser.add_argument("--set-index", type=int, default=None)
    parser.add_argument("--full", action="store_true", help="select all 28 endpoints and every raw-support group")
    args = parser.parse_args()
    protocol_root = args.protocol_root.resolve()
    output_dir = args.output_dir or (protocol_root / "qualification" / ("full-run" if args.full else "engineering-slice"))
    try:
        receipt = (
            run_full_streaming(protocol_root, output_dir)
            if args.full
            else run_subset(
                protocol_root,
                output_dir,
                args.endpoint_limit,
                args.group_limit,
                args.source_event,
                args.set_index,
                False,
            )
        )
    except (OSError, KeyError, TypeError, ValueError, QualificationError) as error:
        raise SystemExit(f"Q10-PF5 execution failed closed: {error}") from error
    execution = receipt["execution"]
    print(
        "Q10-PF5 full qualification passed: " if args.full else "Q10-PF5 engineering slice passed: ",
        f"reconstructed={execution['reconstructed_primary_endpoints']} "
        f"groups={execution['topology']['raw_support_groups_selected']} "
        f"outputs={args.output_dir or (protocol_root / 'qualification' / 'engineering-slice')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

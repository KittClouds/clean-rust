"""Q10-PF6 distributed beam core and engineering runner helpers.

This module reuses the sealed PF5 replay implementation read-only. It exposes
the target-aware ordering and complete-endpoint beam mechanics separately so
they can be tested without loading scientific or behavioral artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
PF5_ROOT = ROOT.parent / "q10-pf5-v1"


def load_pf5() -> ModuleType:
    path = PF5_ROOT / "scripts" / "run_q10_pf5.py"
    expected = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))["runtime"]["pf5_helper_sha256"]
    actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    if actual != expected:
        raise RuntimeError(f"PF6 imported PF5 helper hash drift: {actual} != {expected}")
    spec = importlib.util.spec_from_file_location("q10_pf5_readonly", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load sealed PF5 runner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    script_dir = str(path.parent)
    sys.path.insert(0, script_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(script_dir)
    return module


PF5 = load_pf5()


@dataclass(frozen=True)
class RankedCoordinate:
    coordinate: int
    residual_mass: float
    mismatched_rows: int
    replayed_prefix_count: int


@dataclass(frozen=True)
class TrajectoryPoint:
    round: int
    mismatch_count: int
    total_ulp_distance: int
    residual_l2: float
    max_residual: float
    geometry_debt: dict[str, float]
    active_coordinate_count: int
    selected_coordinate_ids: tuple[int, ...]
    unselected_coordinate_ids: tuple[int, ...]


def _residuals(state: Any) -> tuple[float, ...]:
    return tuple(
        PF5.from_bits(actual) - PF5.from_bits(target)
        for actual, target in zip(state.baseline_readout_bits, state.target_readout_bits)
    )


def rank_coordinates(state: Any, group: Any) -> tuple[RankedCoordinate, ...]:
    """Return the frozen PF6 coordinate order without discarding coordinates."""
    residuals = _residuals(state)
    mismatched = {
        row for row in group.rows
        if state.baseline_readout_bits[row] != state.target_readout_bits[row]
    }
    ranked: list[RankedCoordinate] = []
    for coordinate, replayed in zip(group.coordinates, group.replayed_prefixes):
        influenced = {
            row for row, count in state.support_counts[coordinate]
            if count != 0 and row in group.rows
        }
        rows = influenced & mismatched
        ranked.append(
            RankedCoordinate(
                coordinate=coordinate,
                residual_mass=math.fsum(residuals[row] ** 2 for row in rows),
                mismatched_rows=len(rows),
                replayed_prefix_count=len(replayed),
            )
        )
    ranked.sort(
        key=lambda item: (
            -item.residual_mass,
            -item.mismatched_rows,
            -item.replayed_prefix_count,
            item.coordinate,
        )
    )
    return tuple(ranked)


def reorder_group(group: Any, ranked: Iterable[RankedCoordinate]) -> Any:
    """Return a PF5 RawGroup with domains aligned to the PF6 ranking."""
    by_coordinate = {
        coordinate: index for index, coordinate in enumerate(group.coordinates)
    }
    order = tuple(item.coordinate for item in ranked)
    indices = [by_coordinate[coordinate] for coordinate in order]
    return PF5.RawGroup(
        key=group.key,
        group_index=group.group_index,
        rows=group.rows,
        coordinates=order,
        domains=tuple(group.domains[index] for index in indices),
        serialized_steps=tuple(group.serialized_steps[index] for index in indices),
        missing_prefixes=tuple(group.missing_prefixes[index] for index in indices),
        helpful_rows=group.helpful_rows,
        no_helpful_rows=group.no_helpful_rows,
        threshold_classes=group.threshold_classes,
        helpful_component_indices=group.helpful_component_indices,
        replayed_prefixes=tuple(group.replayed_prefixes[index] for index in indices),
        unreplayed_prefixes=tuple(group.unreplayed_prefixes[index] for index in indices),
    )


def complete_prefix(
    group: Any,
    selected_choices: dict[int, int],
) -> tuple[int, ...]:
    """Build a full endpoint; every unvisited coordinate remains legal zero."""
    result: list[int] = []
    for coordinate, domain in zip(group.coordinates, group.domains):
        choice = selected_choices.get(coordinate, 0)
        if choice not in domain:
            raise ValueError(f"illegal prefix {choice} for coordinate {coordinate}")
        result.append(choice)
    return tuple(result)


def _trajectory_point(round_index: int, evaluation: Any, group: Any) -> TrajectoryPoint:
    objective = evaluation.objective
    prefix = evaluation.prefix_tuple
    active = sum(choice != 0 for choice in prefix)
    selected = tuple(group.coordinates[:round_index])
    unselected = tuple(group.coordinates[round_index:])
    debt = evaluation.debt
    return TrajectoryPoint(
        round=round_index,
        mismatch_count=objective.mismatch_rows,
        total_ulp_distance=objective.total_ulp_distance,
        residual_l2=objective.residual_l2,
        max_residual=objective.maximum_absolute_residual,
        geometry_debt={
            "axis": debt.axis,
            "norm": debt.norm,
            "cue_linear": debt.cue_linear,
        },
        active_coordinate_count=active,
        selected_coordinate_ids=selected,
        unselected_coordinate_ids=unselected,
    )


def _best(evaluations: Iterable[Any]) -> Any:
    return min(evaluations, key=lambda item: item.objective.key())


def replay_oversized_group(
    state: Any,
    group: Any,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Run the bounded PF6 beam on one PF5 oversized group."""
    ranked = rank_coordinates(state, group)
    ordered = reorder_group(group, ranked)
    baseline = PF5._candidate(state, ordered, tuple(0 for _ in ordered.coordinates))
    evaluations: dict[tuple[int, ...], Any] = {baseline.prefix_tuple: baseline}
    beam: tuple[Any, ...] = (PF5._state_for(baseline),)
    trajectory = [_trajectory_point(0, baseline, ordered)]
    nodes = 1
    guard_values = contract["geometry"]["intermediate_guardrails"]
    guard = PF5.GeometryDebt(
        guard_values["axis_normalized_abs"],
        guard_values["norm_normalized_abs"],
        guard_values["cue_linear_normalized_abs"],
    )
    max_rounds = min(16, len(ordered.coordinates))
    for round_index in range(max_rounds):
        expanded: list[Any] = []
        position = round_index
        for beam_state in beam:
            for choice in ordered.domains[position]:
                prefix_values = list(beam_state.prefix_tuple)
                prefix_values[position] = choice
                prefix = tuple(prefix_values)
                if prefix not in evaluations:
                    if nodes >= 32768:
                        break
                    evaluations[prefix] = PF5._candidate(state, ordered, prefix)
                    nodes += 1
                evaluation = evaluations[prefix]
                if evaluation.debt.within(guard):
                    expanded.append(PF5._state_for(evaluation))
            if nodes >= 32768:
                break
        if not expanded:
            break
        beam = tuple(PF5.select_beam(expanded, exploit_width=24, explore_width=8))
        trajectory.append(
            _trajectory_point(
                round_index + 1,
                _best(evaluations[item.prefix_tuple] for item in beam),
                ordered,
            )
        )
    chosen = _best(evaluations[item.prefix_tuple] for item in beam)
    while len(trajectory) < 17:
        trajectory.append(_trajectory_point(len(trajectory), chosen, ordered))
    final_weights = tuple(PF5.from_bits(raw) for raw in chosen.weight_bits)
    final_metrics = PF5.geometry_metrics(
        state.rows, final_weights, state.base_weights, state.target_weights, state.axis
    )
    final_pass = PF5.final_geometry_pass(final_metrics, contract)
    exact = chosen.readout_bits == state.target_readout_bits
    baseline_objective = baseline.objective
    improved = chosen.objective.key()[:4] < baseline_objective.key()[:4]
    if exact and final_pass:
        status = "EXACT_TARGET_REACHED"
    elif final_pass and improved:
        status = "PARTIAL_FEASIBILITY_FOUND"
    else:
        status = "INCONCLUSIVE_BOUNDED_SEARCH"
    return {
        "protocol": "Q10-PF6",
        "group_index": group.group_index,
        "rows": list(group.rows),
        "coordinates": list(ordered.coordinates),
        "ranked_coordinates": [item.__dict__ for item in ranked],
        "status": status,
        "coverage_state": "partial",
        "nodes_replayed": nodes,
        "exact_target": exact,
        "improved_over_baseline": improved,
        "candidate_prefix": list(chosen.prefix_tuple),
        "final_geometry_pass": final_pass,
        "final_geometry": final_metrics,
        "trajectory": [point.__dict__ for point in trajectory],
        "tested_zero_label": "tested_zero",
        "unselected_zero_label": "unselected_zero_by_horizon",
    }


def run_engineering_slice(output: Path | None = None) -> dict[str, Any]:
    """Replay one real PF5 oversized group as a non-scientific smoke slice."""
    lineage = PF5.load_lineage(PF5_ROOT)
    first_endpoint = lineage.endpoints[0]
    key = (str(first_endpoint["source_event"]), int(first_endpoint["set_index"]))
    states = PF5.load_endpoint_states(lineage, selected_keys={key})
    if len(states) != 1:
        raise RuntimeError("PF6 slice did not reconstruct exactly one endpoint")
    topology = PF5.augment_missing_prefix_topology(PF5.load_topology(lineage), states, lineage)
    groups = PF5.build_raw_groups(states[0], topology, lineage)
    selected = None
    for group in groups:
        if PF5.replay_plan(group.domains).mode == "OVERSIZE_UNTESTED":
            selected = group
            break
    if selected is None:
        raise RuntimeError("selected PF5 endpoint has no oversized group")
    result = replay_oversized_group(states[0], selected, lineage.contract)
    result["slice"] = {
        "endpoint": [key[0], key[1]],
        "groups_in_endpoint": len(groups),
        "selected_group_is_oversize": True,
        "pf5_helper_sha256": hashlib.sha256(
            (PF5_ROOT / "scripts" / "run_q10_pf5.py").read_bytes()
        ).hexdigest().upper(),
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Q10-PF6 engineering beam runner")
    parser.add_argument("--dry", action="store_true", help="run only the synthetic dry fixture")
    parser.add_argument("--slice", action="store_true", help="replay one real PF5 oversized group")
    parser.add_argument("--output", type=Path, help="optional JSON output for --slice")
    args = parser.parse_args()
    if args.dry:
        print("Q10-PF6 dry core available")
        return 0
    if args.slice:
        result = run_engineering_slice(args.output)
        print(
            "Q10-PF6 slice complete: "
            f"group={result['group_index']} status={result['status']} "
            f"nodes={result['nodes_replayed']}"
        )
        return 0
    raise SystemExit("full PF6 execution is intentionally not enabled; use --dry or --slice")


if __name__ == "__main__":
    raise SystemExit(main())

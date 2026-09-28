"""Q10-PF6-S1 fixed-sample engineering runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PF6_ROOT = REPO / "experiments/drosophila-heresy/q10-pf6-v1"
sys.path.insert(0, str(PF6_ROOT / "scripts"))
import run_q10_pf6 as PF6  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def state_hash(prefix: tuple[int, ...]) -> str:
    return hashlib.sha256("|".join(str(value) for value in prefix).encode()).hexdigest().upper()


def objective_dict(evaluation: Any) -> dict[str, Any]:
    objective = evaluation.objective
    return {
        "mismatch_count": objective.mismatch_rows,
        "total_ulp_distance": objective.total_ulp_distance,
        "residual_l2": objective.residual_l2,
        "max_residual": objective.maximum_absolute_residual,
        "prefix": list(evaluation.prefix_tuple),
    }


def geometry_dict(debt: Any) -> dict[str, float]:
    return {"axis": debt.axis, "norm": debt.norm, "cue_linear": debt.cue_linear}


def final_metrics(state: Any, group: Any, evaluation: Any, contract: dict[str, Any]) -> tuple[dict[str, float], bool]:
    weights = tuple(PF6.PF5.from_bits(raw) for raw in evaluation.weight_bits)
    metrics = PF6.PF5.geometry_metrics(
        state.rows, weights, state.base_weights, state.target_weights, state.axis
    )
    return metrics, PF6.PF5.final_geometry_pass(metrics, contract)


def trajectory_point(
    round_index: int,
    evaluation: Any,
    group: Any,
    replay_count: int,
    cumulative_replays: int,
    tested_zero: tuple[int, ...],
    guard_rejects: int,
    bounds_rejects: int,
    exploit_survivors: int,
    exploration_survivors: int,
) -> dict[str, Any]:
    objective = evaluation.objective
    prefix = evaluation.prefix_tuple
    baseline_l2 = max(objective.residual_l2, 1.0e-300)
    return {
        "round": round_index,
        "mismatch_count": objective.mismatch_rows,
        "total_ulp_distance": objective.total_ulp_distance,
        "residual_l2": objective.residual_l2,
        "max_residual": objective.maximum_absolute_residual,
        "geometry_debt": geometry_dict(evaluation.debt),
        "active_nonzero_coordinate_count": sum(choice != 0 for choice in prefix),
        "selected_coordinate_ids": list(group.coordinates[:round_index]),
        "tested_zero_coordinate_ids": list(tested_zero),
        "unselected_coordinate_ids": list(group.coordinates[round_index:]),
        "candidate_replays": replay_count,
        "cumulative_candidate_replays": cumulative_replays,
        "exploit_survivors": exploit_survivors,
        "exploration_survivors": exploration_survivors,
        "intermediate_geometry_rejects": guard_rejects,
        "bounds_reserve_rejects": bounds_rejects,
        "unique_beam_states": exploit_survivors + exploration_survivors,
        "best_state_hash": state_hash(prefix),
        "descriptive_residual_improvement": 0.0 if round_index == 0 else None,
        "trajectory_l2_guard": baseline_l2,
    }


def replay_group_s1(state: Any, group: Any, contract: dict[str, Any]) -> dict[str, Any]:
    ranked = PF6.rank_coordinates(state, group)
    ordered = PF6.reorder_group(group, ranked)
    baseline = PF6.PF5._candidate(state, ordered, tuple(0 for _ in ordered.coordinates))
    evaluations: dict[tuple[int, ...], Any] = {baseline.prefix_tuple: baseline}
    beam: tuple[Any, ...] = (PF6.PF5._state_for(baseline),)
    trajectory: list[dict[str, Any]] = []
    total_replays = 0
    guard_rejects = 0
    bounds_rejects = 0
    budget_exhausted = False
    max_rounds = 16
    guard_values = contract["geometry"]["intermediate_guardrails"]
    guard = PF6.PF5.GeometryDebt(
        guard_values["axis_normalized_abs"],
        guard_values["norm_normalized_abs"],
        guard_values["cue_linear_normalized_abs"],
    )

    def best_beam() -> Any:
        return min((evaluations[item.prefix_tuple] for item in beam), key=lambda item: item.objective.key())

    baseline_metrics, baseline_valid = final_metrics(state, ordered, baseline, contract)
    best_search_so_far = baseline
    best_valid_so_far: Any | None = baseline if baseline_valid else None
    best_valid_metrics_so_far = baseline_metrics if baseline_valid else None
    trajectory.append(trajectory_point(0, baseline, ordered, 0, 0, (), 0, 0, 1, 0))
    trajectory[0]["best_search_state"] = objective_dict(baseline)
    trajectory[0]["best_final_gate_valid_state"] = objective_dict(baseline) if baseline_valid else None
    completed_rounds = 0
    for round_index in range(min(max_rounds, len(ordered.coordinates))):
        expanded: list[Any] = []
        round_replays = 0
        round_guard_rejects = 0
        round_bounds_rejects = 0
        position = round_index
        tested_zero = (ordered.coordinates[position],) if 0 in ordered.domains[position] else ()
        for beam_state in beam:
            for choice in ordered.domains[position]:
                prefix_values = list(beam_state.prefix_tuple)
                prefix_values[position] = choice
                prefix = tuple(prefix_values)
                if prefix not in evaluations:
                    if total_replays >= 32768:
                        budget_exhausted = True
                        break
                    try:
                        evaluations[prefix] = PF6.PF5._candidate(state, ordered, prefix)
                    except PF6.PF5.QualificationError:
                        round_bounds_rejects += 1
                        continue
                    total_replays += 1
                    round_replays += 1
                evaluation = evaluations[prefix]
                if evaluation.debt.within(guard):
                    expanded.append(PF6.PF5._state_for(evaluation))
                else:
                    guard_rejects += 1
                    round_guard_rejects += 1
            if budget_exhausted:
                break
        if expanded:
            beam = tuple(PF6.PF5.select_beam(expanded, exploit_width=24, explore_width=8))
            completed_rounds = round_index + 1
        current = best_beam()
        if current.objective.key() < best_search_so_far.objective.key():
            best_search_so_far = current
        for state_item in beam:
            candidate = evaluations[state_item.prefix_tuple]
            metrics, valid = final_metrics(state, ordered, candidate, contract)
            if valid and (best_valid_so_far is None or candidate.objective.key() < best_valid_so_far.objective.key()):
                best_valid_so_far = candidate
                best_valid_metrics_so_far = metrics
        trajectory.append(
            trajectory_point(
                round_index + 1,
                current,
                ordered,
                round_replays,
                total_replays,
                tested_zero,
                round_guard_rejects,
                round_bounds_rejects,
                min(24, len(beam)),
                max(0, len(beam) - 24),
            )
        )
        trajectory[-1]["best_search_state"] = objective_dict(current)
        trajectory[-1]["best_final_gate_valid_state"] = (
            objective_dict(best_valid_so_far) if best_valid_so_far is not None else None
        )
        if budget_exhausted or not expanded:
            break

    best_search = best_search_so_far
    best_valid = best_valid_so_far
    best_valid_metrics = best_valid_metrics_so_far
    while len(trajectory) < 17:
        trajectory.append(
            trajectory_point(
                len(trajectory), best_search, ordered, 0, total_replays, (), 0, 0, min(24, len(beam)), max(0, len(beam) - 24)
            )
        )
        trajectory[-1]["best_search_state"] = objective_dict(best_search)
        trajectory[-1]["best_final_gate_valid_state"] = (
            objective_dict(best_valid) if best_valid is not None else None
        )

    baseline_key = baseline.objective.key()[:4]
    best_search_improved = best_search.objective.key()[:4] < baseline_key
    best_valid_improved = best_valid is not None and best_valid.objective.key()[:4] < baseline_key
    exact = best_valid is not None and best_valid.readout_bits == state.target_readout_bits
    if exact:
        status = "EXACT_TARGET_REACHED"
    elif best_valid_improved:
        status = "PARTIAL_FEASIBILITY_FOUND"
    elif best_search_improved and best_valid is None:
        status = "READOUT_IMPROVEMENT_GEOMETRY_REJECTED"
    elif budget_exhausted:
        status = "REPLAY_BUDGET_EXHAUSTED"
    else:
        status = "INCONCLUSIVE_BOUNDED_SEARCH"
    chosen = best_valid or best_search
    audited_metrics, audited_valid = final_metrics(state, ordered, chosen, contract)
    audited = PF6.PF5.independent_candidate_audit(state, ordered, chosen, contract)
    baseline_point = trajectory[0]
    for point in trajectory:
        point["descriptive_residual_improvement"] = (
            (baseline_point["residual_l2"] - point["residual_l2"])
            / max(baseline_point["residual_l2"], 1.0e-300)
        )
    return {
        "protocol": "Q10-PF6-S1",
        "identity": [group.key[0], group.key[1], group.group_index],
        "status": status,
        "coverage_state": "partial",
        "coordinates_total": len(ordered.coordinates),
        "coordinates_ranked": list(ordered.coordinates),
        "rows": list(ordered.rows),
        "nodes_replayed": total_replays,
        "rounds_completed": completed_rounds,
        "baseline": objective_dict(baseline),
        "best_search": objective_dict(best_search),
        "best_search_final_geometry": final_metrics(state, ordered, best_search, contract)[1],
        "best_valid": objective_dict(best_valid) if best_valid is not None else None,
        "best_valid_geometry": best_valid_metrics,
        "best_valid_found": best_valid is not None,
        "final_audit": audited,
        "final_geometry": audited_metrics,
        "final_geometry_pass": audited_valid,
        "active_nonzero_coordinate_count": sum(choice != 0 for choice in chosen.prefix_tuple),
        "trajectory": trajectory,
        "replay_budget_exhausted": budget_exhausted,
        "pf6_helper_sha256": digest(PF6_ROOT / "scripts/run_q10_pf6.py"),
    }


def run(output_dir: Path, limit: int | None = None) -> dict[str, Any]:
    preflight = ROOT / "scripts/preflight_q10_pf6_s1.py"
    import subprocess
    check = subprocess.run([sys.executable, "-B", str(preflight)], cwd=ROOT, capture_output=True, text=True)
    if check.returncode != 0:
        raise RuntimeError(check.stdout + check.stderr)
    sample = json.loads((ROOT / "qualification/sample.json").read_text(encoding="utf-8"))
    selected = sample["selected_groups"]
    if limit is not None:
        selected = selected[:limit]
    lineage = PF6.PF5.load_lineage(PF6.PF5_ROOT)
    states = PF6.PF5.load_endpoint_states(lineage)
    state_by_key = {state.key: state for state in states}
    topology = PF6.PF5.augment_missing_prefix_topology(PF6.PF5.load_topology(lineage), states, lineage)
    groups_by_key: dict[tuple[str, int], dict[int, Any]] = {}
    for state in states:
        groups = PF6.PF5.build_raw_groups(state, topology, lineage)
        groups_by_key[state.key] = {group.group_index: group for group in groups}
    output_dir.mkdir(parents=True, exist_ok=True)
    group_dir = output_dir / "groups"
    group_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for record in selected:
        event, set_index, group_index = record["identity"]
        key = (event, int(set_index))
        group = groups_by_key[key][int(group_index)]
        result = replay_group_s1(state_by_key[key], group, lineage.contract)
        result["stratum"] = record["stratum"]
        result["baseline_selection_metadata"] = record["baseline"]
        results.append(result)
        group_id = f"{event.replace('.json', '')}__set{set_index}__group{group_index}"
        (group_dir / f"{group_id}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    execution = {
        "protocol": "Q10-PF6-S1",
        "status": "Q10_PF6_S1_SMOKE_COMPLETE" if limit is not None else "Q10_PF6_S1_VALID__MULTIGROUP_ENGINEERING_PROFILE_COMPLETE",
        "measured_sample": limit is None,
        "groups_processed": len(results),
        "status_counts": counts,
        "sample_sha256": digest(ROOT / "qualification/sample.json"),
        "preexecution_sha256": digest(ROOT / "qualification/PREEXECUTION.json"),
        "pf6_helper_sha256": digest(PF6_ROOT / "scripts/run_q10_pf6.py"),
        "results": results,
    }
    (output_dir / "execution.json").write_text(json.dumps(execution, indent=2) + "\n", encoding="utf-8")
    return execution


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "qualification/execution")
    parser.add_argument("--limit", type=int, help="engineering smoke only; never the S1 measured sample")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")
    execution = run(args.output_dir.resolve(), args.limit)
    print(f"Q10-PF6-S1 complete: groups={execution['groups_processed']} statuses={execution['status_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

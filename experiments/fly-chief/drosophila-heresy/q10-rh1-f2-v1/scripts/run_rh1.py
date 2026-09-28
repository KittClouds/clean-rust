"""Q10-RH1-F2 corrected ranking-by-horizon engineering factorial runner."""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PF5_ROOT = REPO / "experiments/drosophila-heresy/q10-pf5-v1"
CQ_ROOT = REPO / "experiments/drosophila-heresy/q10-rh1-cq1-v1/scripts"
sys.path.insert(0, str(CQ_ROOT))
sys.path.insert(0, str(PF5_ROOT / "scripts"))
import common_runtime as CQ  # noqa: E402
import run_q10_pf5 as PF5  # noqa: E402


OUT_ROOT = ROOT / "qualification"
EXECUTION_ROOT = OUT_ROOT / "execution"
BEAM_EXPLOIT = 24
BEAM_EXPLORE = 8
MAX_NODES_16 = 32768
MAX_NODES_LONG = 65536


@dataclass(frozen=True)
class CandidateLite:
    """A cached candidate without a copied full weight vector."""

    prefix_tuple: tuple[int, ...]
    objective: Any
    debt: Any
    declared_readout_bits: tuple[int, ...]


def verify_contract() -> dict[str, str]:
    contract = CQ.load_json(ROOT / "CONTRACT.json")
    preexecution = CQ.load_json(ROOT / "PREEXECUTION.json")
    CQ.require(preexecution["plan_sha256"] == CQ.digest(ROOT / "PLAN.md"), "RH1-F2 plan hash drift")
    CQ.require(preexecution["contract_sha256"] == CQ.digest(ROOT / "CONTRACT.json"), "RH1-F2 contract hash drift")
    bindings: dict[str, str] = {}
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        CQ.require(path.is_file(), f"missing RH1-F2 parent: {binding['label']}")
        actual = CQ.digest(path)
        CQ.require(actual == binding["sha256"].upper(), f"RH1-F2 parent drift: {binding['label']}")
        bindings[binding["label"]] = actual
    CQ.require(
        contract["ranking"]["authority"]
        == [
            "helpful_row_count_desc",
            "helpful_ulp_burden_desc",
            "median_first_helpful_scale_asc",
            "declared_row_count_desc",
            "coordinate_id_asc",
        ],
        "RH1-F2 authority ranking contract drift",
    )
    CQ.require("rh1_runner" in bindings, "RH1-F2 runner hash binding missing")
    CQ.require("pf5_contract" in bindings, "RH1-F2 PF5 contract hash binding missing")
    CQ.require(
        preexecution.get("rh1_runner_sha256", "").upper() == bindings["rh1_runner"],
        "RH1-F2 runner provenance drift",
    )
    CQ.require(
        preexecution.get("pf5_contract_sha256", "").upper() == bindings["pf5_contract"],
        "RH1-F2 PF5 contract provenance drift",
    )
    return bindings


def load_features() -> dict[tuple[str, int, int, int], dict[str, Any]]:
    path = REPO / "experiments/drosophila-heresy/q10-rh1-ac2-v1/qualification/features.jsonl"
    features: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            key = (str(item["endpoint"]), int(item["set_index"]), int(item["group_index"]), int(item["coordinate"]))
            CQ.require(item["complete"] is True, f"incomplete AC2 feature entered RH1: {key}")
            features[key] = item
    CQ.require(len(features) == 2707, f"AC2 feature cardinality drift: {len(features)}")
    return features


def frozen_groups() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = CQ.load_groups()
    primary = sorted((group for group in groups if group["coordinates_total"] >= 32), key=lambda item: tuple(item["identity"]))
    secondary = sorted((group for group in groups if 17 <= group["coordinates_total"] <= 31), key=lambda item: tuple(item["identity"]))
    CQ.require(len(primary) == 32 and len(secondary) == 23, "RH1 cohort cardinality drift")
    return primary, secondary


def canonical_group(group: Any) -> Any:
    order = tuple(sorted(group.coordinates))
    by_coordinate = {coordinate: index for index, coordinate in enumerate(group.coordinates)}
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


def weight_bits_for(state: Any, group: Any, prefix: tuple[int, ...]) -> tuple[int, ...]:
    bits = list(state.baseline_weight_bits)
    for coordinate, choice in zip(group.coordinates, prefix):
        raw = PF5.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        CQ.require(raw is not None, f"illegal RH1 prefix: {state.key} {coordinate} {choice}")
        bits[coordinate] = raw
    return tuple(bits)


def score_rows(actual: Iterable[int], target: Iterable[int], rows: Iterable[int], prefix: tuple[int, ...]) -> Any:
    actual_values = tuple(actual)
    target_values = tuple(target)
    errors = []
    mismatches = 0
    total_ulp = 0
    maximum = 0.0
    for row in rows:
        left = PF5.from_bits(actual_values[row])
        right = PF5.from_bits(target_values[row])
        error = left - right
        errors.append(error)
        mismatches += actual_values[row] != target_values[row]
        total_ulp += PF5.ulp_distance(left, right)
        maximum = max(maximum, abs(error))
    return PF5.Objective(
        mismatch_rows=mismatches,
        total_ulp_distance=total_ulp,
        residual_l2=math.sqrt(math.fsum(error * error for error in errors)),
        maximum_absolute_residual=maximum,
        stable_prefix_tuple=prefix,
    )


def geometry_metrics_from_prefix(state: Any, group: Any, prefix: tuple[int, ...]) -> dict[str, float]:
    """Evaluate the PF5 geometry equations without copying the full vector."""
    axis_delta = []
    norm_delta = []
    row_delta: dict[int, float] = {}
    for coordinate, choice in zip(group.coordinates, prefix):
        if choice == 0:
            continue
        raw = PF5.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        CQ.require(raw is not None, "geometry received illegal prefix")
        new_weight = PF5.from_bits(raw)
        delta = new_weight - state.baseline_weights[coordinate]
        axis_delta.append(delta * state.axis[coordinate])
        old_displacement = state.baseline_displacement[coordinate]
        new_displacement = new_weight - state.base_weights[coordinate]
        norm_delta.append(new_displacement * new_displacement - old_displacement * old_displacement)
        for row_index, count in state.support_counts[coordinate]:
            row_delta[row_index] = row_delta.get(row_index, 0.0) + delta * count
    final_axis = state.baseline_axis + math.fsum(axis_delta)
    final_norm = math.sqrt(max(state.baseline_norm * state.baseline_norm + math.fsum(norm_delta), 0.0))
    cue_squared = state.baseline_drive_squared
    for row_index in sorted(row_delta):
        old_error = state.baseline_drive_errors[row_index]
        new_error = old_error + row_delta[row_index]
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


def debt_from_metrics(metrics: dict[str, float]) -> Any:
    return PF5.GeometryDebt(
        metrics["final_axis"] - metrics["target_axis"],
        metrics["final_norm"] - metrics["target_norm"],
        metrics["cue_linear_normalized_error"],
    )


def candidate_lite(state: Any, group: Any, prefix: tuple[int, ...]) -> CandidateLite:
    bits = weight_bits_for(state, group, prefix)
    weights = list(state.baseline_weights)
    for coordinate, choice in zip(group.coordinates, prefix):
        if choice != 0:
            weights[coordinate] = PF5.from_bits(bits[coordinate])
    declared_rows = group.rows
    actual_declared = PF5.readout_bits((state.rows[row] for row in declared_rows), weights)
    declared_target = tuple(state.target_readout_bits[row] for row in declared_rows)
    objective = score_rows(actual_declared, declared_target, range(len(declared_rows)), prefix)
    metrics = geometry_metrics_from_prefix(state, group, prefix)
    debt = PF5.GeometryDebt(
        (metrics["final_axis"] - metrics["target_axis"]) / max(abs(state.target_axis), 1.0e-12),
        (metrics["final_norm"] - metrics["target_norm"]) / max(state.target_norm, 1.0e-12),
        metrics["cue_linear_normalized_error"],
    )
    return CandidateLite(prefix, objective, debt, actual_declared)


def materialize(state: Any, group: Any, lite: CandidateLite) -> Any:
    bits = weight_bits_for(state, group, lite.prefix_tuple)
    weights = tuple(PF5.from_bits(raw) for raw in bits)
    actual = PF5.readout_bits(state.rows, weights)
    declared_actual = tuple(actual[row] for row in group.rows)
    declared_target = tuple(state.target_readout_bits[row] for row in group.rows)
    objective = score_rows(declared_actual, declared_target, range(len(group.rows)), lite.prefix_tuple)
    return PF5.CandidateEvaluation(lite.prefix_tuple, objective, lite.debt, actual, bits)


def rank_residual(group: dict[str, Any]) -> list[int]:
    return [int(value) for value in group["coordinates"]]


def rank_authority(group: dict[str, Any], features: dict[tuple[str, int, int, int], dict[str, Any]]) -> list[int]:
    endpoint, set_index, group_index = group["identity"]
    records = []
    for coordinate in group["coordinates"]:
        feature = features[(str(endpoint), int(set_index), int(group_index), int(coordinate))]
        records.append(feature)
    records.sort(key=lambda item: (
        -int(item["helpful_row_count"]),
        -int(item["helpful_ulp_burden"]),
        float(item["first_helpful_scale_median"]) if item["first_helpful_scale_median"] is not None else float("inf"),
        -int(item["declared_row_count"]),
        int(item["coordinate"]),
    ))
    return [int(item["coordinate"]) for item in records]


def score_dict(actual: tuple[int, ...], target: tuple[int, ...], rows: list[int]) -> dict[str, Any]:
    score = score_rows(actual, target, rows, ())
    return {
        "mismatch_count": score.mismatch_rows,
        "total_ulp_distance": score.total_ulp_distance,
        "residual_l2": score.residual_l2,
        "maximum_absolute_residual": score.maximum_absolute_residual,
    }


def score_domains(state: Any, group: Any, physical_rows: list[int], candidate: Any) -> dict[str, dict[str, Any]]:
    target = state.target_readout_bits
    return {
        "D": score_dict(candidate.readout_bits, target, list(group.rows)),
        "P": score_dict(candidate.readout_bits, target, physical_rows),
        "G": score_dict(candidate.readout_bits, target, list(range(len(state.rows)))),
    }


def better(left: CandidateLite, right: CandidateLite | None) -> bool:
    return right is None or left.objective.key()[:4] < right.objective.key()[:4]


def trajectory_point(
    state: Any,
    group: Any,
    physical_rows: list[int],
    round_index: int,
    current: CandidateLite,
    best_search: CandidateLite,
    best_valid: CandidateLite | None,
    ranking: list[int],
    horizon: int,
    replays: int,
    rounds_completed: int,
    termination: str | None = None,
) -> dict[str, Any]:
    current_full = materialize(state, group, current)
    best_full = materialize(state, group, best_search)
    valid_full = materialize(state, group, best_valid) if best_valid is not None else None
    return {
        "round": round_index,
        "horizon": horizon,
        "rounds_completed": rounds_completed,
        "ranking_coordinate": ranking[round_index - 1] if round_index > 0 and round_index <= len(ranking) else None,
        "current_search": score_domains(state, group, physical_rows, current_full),
        "best_search": score_domains(state, group, physical_rows, best_full),
        "best_valid": score_domains(state, group, physical_rows, valid_full) if valid_full else None,
        "active_nonzero_coordinate_count": sum(choice != 0 for choice in current.prefix_tuple),
        "selected_coordinate_ids": ranking[:round_index],
        "unselected_coordinate_ids": ranking[round_index:],
        "candidate_replays": replays,
        "termination": termination,
    }


def run_arm(
    state: Any,
    raw_group: Any,
    frozen_group: dict[str, Any],
    features: dict[tuple[str, int, int, int], dict[str, Any]],
    ranking_name: str,
    horizon: int,
) -> dict[str, Any]:
    group = canonical_group(raw_group)
    ranking = rank_residual(frozen_group) if ranking_name == "residual" else rank_authority(frozen_group, features)
    CQ.require(set(ranking) == set(group.coordinates), "RH1 ranking lost or duplicated coordinates")
    domain_by_coordinate = {coordinate: domain for coordinate, domain in zip(group.coordinates, group.domains)}
    baseline_prefix = tuple(0 for _ in group.coordinates)
    evaluations: dict[tuple[int, ...], CandidateLite] = {baseline_prefix: candidate_lite(state, group, baseline_prefix)}
    beam: tuple[Any, ...] = (PF5._state_for(evaluations[baseline_prefix]),)
    physical_rows = sorted({row for coordinate in group.coordinates for row, _ in state.support_counts[coordinate]})
    # The RH1 contract inherits PF5 guardrails; load them from the sealed PF5 contract.
    pf5_contract = CQ.load_json(PF5_ROOT / "CONTRACT.json")
    guard_values = pf5_contract["geometry"]["intermediate_guardrails"]
    guard = PF5.GeometryDebt(guard_values["axis_normalized_abs"], guard_values["norm_normalized_abs"], guard_values["cue_linear_normalized_abs"])
    budget = MAX_NODES_16 if horizon == 16 else MAX_NODES_LONG
    best_search = evaluations[baseline_prefix]
    baseline_geometry = geometry_metrics_from_prefix(state, group, baseline_prefix)
    baseline_valid = (
        baseline_geometry["axis_normalized_error"] <= pf5_contract["geometry"]["final_da2_gates"]["axis_normalized_abs"]
        and baseline_geometry["norm_normalized_error"] <= pf5_contract["geometry"]["final_da2_gates"]["norm_normalized_abs"]
        and baseline_geometry["cue_linear_normalized_error"] <= pf5_contract["geometry"]["final_da2_gates"]["cue_linear_normalized_abs"]
    )
    best_valid: CandidateLite | None = best_search if baseline_valid else None
    trajectory = [trajectory_point(state, group, physical_rows, 0, best_search, best_search, best_valid, ranking, horizon, 0, 0)]
    total_replays = 0
    rounds_completed = 0
    budget_exhausted = False
    no_expansion = False
    for round_index in range(min(horizon, len(ranking))):
        coordinate = ranking[round_index]
        canonical_index = group.coordinates.index(coordinate)
        expanded: list[Any] = []
        round_replays = 0
        for beam_state in beam:
            for choice in domain_by_coordinate[coordinate]:
                prefix_values = list(beam_state.prefix_tuple)
                prefix_values[canonical_index] = choice
                prefix = tuple(prefix_values)
                if prefix not in evaluations:
                    if total_replays >= budget:
                        budget_exhausted = True
                        break
                    evaluations[prefix] = candidate_lite(state, group, prefix)
                    total_replays += 1
                    round_replays += 1
                candidate = evaluations[prefix]
                if candidate.debt.within(guard):
                    expanded.append(PF5._state_for(candidate))
            if budget_exhausted:
                break
        if not expanded:
            no_expansion = True
            break
        beam = tuple(PF5.select_beam(expanded, exploit_width=BEAM_EXPLOIT, explore_width=BEAM_EXPLORE))
        rounds_completed = round_index + 1
        current = min((evaluations[item.prefix_tuple] for item in beam), key=lambda item: item.objective.key())
        if better(current, best_search):
            best_search = current
        for beam_state in beam:
            candidate = evaluations[beam_state.prefix_tuple]
            metrics = geometry_metrics_from_prefix(state, group, candidate.prefix_tuple)
            final_gates = pf5_contract["geometry"]["final_da2_gates"]
            valid = (
                metrics["axis_normalized_error"] <= final_gates["axis_normalized_abs"]
                and metrics["norm_normalized_error"] <= final_gates["norm_normalized_abs"]
                and metrics["cue_linear_normalized_error"] <= final_gates["cue_linear_normalized_abs"]
            )
            if valid and better(candidate, best_valid):
                best_valid = candidate
        trajectory.append(trajectory_point(state, group, physical_rows, rounds_completed, current, best_search, best_valid, ranking, horizon, round_replays, rounds_completed))
        if budget_exhausted:
            break
    termination = "REPLAY_BUDGET" if budget_exhausted else ("NO_EXPANSION" if no_expansion else ("NATURAL_COORDINATE_END" if horizon >= len(ranking) else "HORIZON"))
    baseline = evaluations[baseline_prefix]
    exact_declared = best_valid is not None and all(
        bit == state.target_readout_bits[row]
        for bit, row in zip(best_valid.declared_readout_bits, group.rows)
    )
    improved = best_valid is not None and better(best_valid, baseline)
    if exact_declared:
        status = "EXACT_DECLARED_TARGET_REACHED"
    elif improved:
        status = "PARTIAL_FEASIBILITY_FOUND"
    elif budget_exhausted:
        status = "REPLAY_BUDGET"
    elif better(best_search, baseline) and best_valid is None:
        status = "READOUT_IMPROVEMENT_GEOMETRY_REJECTED"
    else:
        status = "INCONCLUSIVE_BOUNDED_SEARCH"
    chosen = best_valid or best_search
    chosen_full = materialize(state, group, chosen)
    exact_geometry = PF5.geometry_metrics(state.rows, tuple(PF5.from_bits(raw) for raw in chosen_full.weight_bits), state.base_weights, state.target_weights, state.axis)
    final_valid = PF5.final_geometry_pass(exact_geometry, pf5_contract)
    audit = PF5.independent_candidate_audit(state, group, chosen_full, pf5_contract)
    rank_residual_positions = {coordinate: index + 1 for index, coordinate in enumerate(rank_residual(frozen_group))}
    rank_authority_positions = {coordinate: index + 1 for index, coordinate in enumerate(rank_authority(frozen_group, features))}
    nonzero = [
        {"coordinate": coordinate, "prefix": choice, "residual_rank": rank_residual_positions[coordinate], "authority_rank": rank_authority_positions[coordinate], "rank_migration": rank_residual_positions[coordinate] - rank_authority_positions[coordinate]}
        for coordinate, choice in zip(group.coordinates, chosen.prefix_tuple) if choice != 0
    ]
    baseline_damaged = {row for row in physical_rows if state.baseline_readout_bits[row] == state.target_readout_bits[row]}
    chosen_damaged = {row for row in physical_rows if chosen_full.readout_bits[row] != state.target_readout_bits[row]}
    fixed_declared = sum(state.baseline_readout_bits[row] != state.target_readout_bits[row] and chosen_full.readout_bits[row] == state.target_readout_bits[row] for row in group.rows)
    return {
        "protocol": "Q10-PF6-RH1-F2",
        "identity": frozen_group["identity"],
        "cohort": "primary" if frozen_group["coordinates_total"] >= 32 else "secondary",
        "ranking": ranking_name,
        "horizon": horizon,
        "coordinates_total": len(group.coordinates),
        "coordinates_canonical": list(group.coordinates),
        "ranking_order": ranking,
        "status": status,
        "termination": termination,
        "rounds_completed": rounds_completed,
        "candidate_replays": total_replays,
        "budget": budget,
        "baseline": score_domains(state, group, physical_rows, materialize(state, group, baseline)),
        "best_search": score_domains(state, group, physical_rows, materialize(state, group, best_search)),
        "best_valid": score_domains(state, group, physical_rows, materialize(state, group, best_valid)) if best_valid else None,
        "chosen": score_domains(state, group, physical_rows, chosen_full),
        "chosen_state": {
            "canonical_mapping": [[coordinate, choice] for coordinate, choice in zip(group.coordinates, chosen.prefix_tuple)],
            "state_identity": CQ.state_identity(dict(zip(group.coordinates, chosen.prefix_tuple))),
        },
        "exact_declared_target": exact_declared,
        "final_geometry_pass": final_valid,
        "final_geometry": exact_geometry,
        "independent_audit": audit,
        "collateral": {
            "declared_rows": len(group.rows),
            "physical_support_rows": len(physical_rows),
            "declared_rows_fixed": fixed_declared,
            "baseline_exact_physical_rows": len(baseline_damaged),
            "chosen_newly_damaged_exact_physical_rows": len(baseline_damaged & chosen_damaged),
            "global_mismatch_change": score_domains(state, group, physical_rows, chosen_full)["G"]["mismatch_count"] - score_domains(state, group, physical_rows, materialize(state, group, baseline))["G"]["mismatch_count"],
        },
        "rank_migration": nonzero,
        "trajectory": trajectory,
    }


def load_runtime(selected_keys: set[tuple[str, int]] | None = None) -> tuple[dict[str, str], dict[tuple[str, int], Any], dict[tuple[str, int, int], Any]]:
    bindings = verify_contract()
    lineage = PF5.load_lineage(PF5_ROOT)
    states = PF5.load_endpoint_states(lineage, selected_keys=selected_keys)
    state_by_key = {state.key: state for state in states}
    topology = PF5.augment_missing_prefix_topology(PF5.load_topology(lineage), states, lineage)
    groups_by_key: dict[tuple[str, int, int], Any] = {}
    for state in states:
        for group in PF5.build_raw_groups(state, topology, lineage):
            groups_by_key[(state.key[0], state.key[1], group.group_index)] = group
    return bindings, state_by_key, groups_by_key


def run(output_dir: Path, limit_groups: int | None = None, smoke: bool = False) -> dict[str, Any]:
    features = load_features()
    primary, secondary = frozen_groups()
    selected = primary + secondary
    if limit_groups is not None:
        selected = selected[:limit_groups]
    selected_keys = {(str(group["endpoint"]), int(group["set_index"])) for group in selected}
    bindings, state_by_key, groups_by_key = load_runtime(selected_keys)
    output_dir.mkdir(parents=True, exist_ok=True)
    group_dir = output_dir / "groups"
    group_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for index, frozen_group in enumerate(selected, start=1):
        endpoint, set_index, group_index = frozen_group["identity"]
        key = (str(endpoint), int(set_index))
        state = state_by_key[key]
        raw_group = groups_by_key[(key[0], key[1], int(group_index))]
        CQ.require(tuple(raw_group.rows) == tuple(frozen_group["rows"]), f"RH1 group row drift: {frozen_group['identity']}")
        CQ.require(set(raw_group.coordinates) == set(frozen_group["coordinates"]), f"RH1 group coordinate drift: {frozen_group['identity']}")
        max_horizon = 32 if frozen_group["coordinates_total"] >= 32 else frozen_group["coordinates_total"]
        arm_specs = [("residual", 16), ("residual", max_horizon), ("authority", 16), ("authority", max_horizon)]
        for ranking_name, horizon in arm_specs:
            result = run_arm(state, raw_group, frozen_group, features, ranking_name, horizon)
            results.append(result)
            arm_name = f"{ranking_name}__h{horizon}"
            group_id = f"{endpoint.replace('.json', '')}__set{set_index}__group{group_index}__{arm_name}"
            (group_dir / f"{group_id}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"RH1-F2 {'smoke' if smoke else 'run'} {index}/{len(selected)} {result['identity']} {arm_name} status={result['status']} rounds={result['rounds_completed']} replays={result['candidate_replays']}", flush=True)
    summary = {
        "protocol": "Q10-PF6-RH1-F2",
        "status": "RH1_F2_SMOKE_COMPLETE" if smoke else "RH1_F2_ENGINEERING_FACTORIAL_COMPLETE",
        "parent_bindings_verified": bindings,
        "groups_processed": len(selected),
        "primary_groups_processed": sum(group["coordinates_total"] >= 32 for group in selected),
        "secondary_groups_processed": sum(17 <= group["coordinates_total"] <= 31 for group in selected),
        "arms_per_group": 4,
        "arm_results": len(results),
        "measured_factorial_started": not smoke,
        "scientific_seed_bundles": 0,
        "behavioral_probe": False,
        "dh08b_authorized": False,
        "results": results,
    }
    (output_dir / "execution.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=EXECUTION_ROOT)
    parser.add_argument("--limit-groups", type=int)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.limit_groups is not None and args.limit_groups <= 0:
        raise SystemExit("--limit-groups must be positive")
    result = run(args.output_dir.resolve(), args.limit_groups, args.smoke)
    print(json.dumps({"status": result["status"], "groups": result["groups_processed"], "arms": result["arm_results"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

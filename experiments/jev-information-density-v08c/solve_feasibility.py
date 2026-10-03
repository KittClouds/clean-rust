"""Exact, objective-free v0.8C CP-SAT feasibility checks."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import importlib.metadata
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ortools.sat.python import cp_model


HERE = Path(__file__).resolve().parent
V08_DIR = HERE.parent / "jev-information-density-v08"
sys.path.insert(0, str(V08_DIR))
import select_banks as v08  # noqa: E402

GROUP_LIMIT = 100_000
FAMILY_AXES = v08.FAMILY_AXES
GROUP_FIELDS = v08.GROUP_FIELDS


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_ids(path: Path) -> set[str]:
    result: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = row.get("group_id")
            if not isinstance(group_id, str) or not group_id or group_id in result:
                raise ValueError(f"invalid or duplicate group_id at {path}:{line_number}")
            result.add(group_id)
    return result


def entropy_band(value: float) -> str:
    if value < 0.20:
        return "very_low"
    if value < 0.55:
        return "low"
    if value < 0.95:
        return "medium"
    if value < 1.30:
        return "high"
    return "very_high"


def one_digest(keys: list[str], prefix: str, where: str) -> str:
    values = [key.removeprefix(prefix) for key in keys if key.startswith(prefix)]
    if len(values) != 1:
        raise ValueError(f"expected one {prefix[:-1]} digest at {where}")
    return values[0]


def parse_row(row: dict[str, Any], line_number: int) -> tuple[str, ...] | None:
    if set(row) != GROUP_FIELDS:
        raise ValueError(f"group record schema mismatch at line {line_number}")
    if row["valid"] is not True:
        return None
    families = row["family_ids"]
    if not isinstance(families, dict) or set(families) != set(FAMILY_AXES):
        raise ValueError(f"family axes mismatch at line {line_number}")
    if any(families.get(axis) in (None, "", "none", "unknown") for axis in FAMILY_AXES):
        raise ValueError(f"empty family identity at line {line_number}")
    strata = row["strata"]
    if not isinstance(strata, dict):
        raise ValueError(f"invalid strata at line {line_number}")
    coverage = row["coverage_features"]
    if not isinstance(coverage, dict) or not isinstance(coverage.get("structural_coverage"), list):
        raise ValueError(f"invalid structural coverage at line {line_number}")
    overlap = row["overlap_keys"]
    if not isinstance(overlap, list):
        raise ValueError(f"invalid overlap keys at line {line_number}")
    input_id = one_digest(overlap, "model_input:", f"line {line_number}")
    one_digest(overlap, "gold_target:", f"line {line_number}")
    bundle = str(row["split_family_bundle_id"])
    root = str(row["root_id"])
    group_id = str(row["group_id"])
    episode_id = str(row["episode_id"])
    entropy = float(row["posterior_entropy_nats"])
    if not group_id or not episode_id or not root or not bundle or not math.isfinite(entropy) or entropy < 0:
        raise ValueError(f"invalid identity or entropy at line {line_number}")
    return group_id, episode_id, root, bundle, input_id, str(entropy)


def inspect_and_thresholds(group_records: Path, eval_ids: set[str]) -> tuple[list[float], dict[str, Any]]:
    seen: set[str] = set()
    eval_found: set[str] = set()
    train_entropy: list[float] = []
    owners: dict[tuple[str, str], str] = {}
    root_owner: dict[str, str] = {}
    episode_owner: dict[str, str] = {}
    gold_by_input: dict[str, str] = {}
    valid_rows = 0
    held_rows = 0
    with group_records.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if set(row) != GROUP_FIELDS:
                raise ValueError(f"group record schema mismatch at line {line_number}")
            group_id = str(row["group_id"])
            if not group_id or group_id in seen:
                raise ValueError(f"empty or duplicate group identity at line {line_number}")
            seen.add(group_id)
            if row["valid"] is not True:
                continue
            parsed = parse_row(row, line_number)
            assert parsed is not None
            _gid, episode_id, root, bundle, input_id, _entropy_text = parsed
            entropy = float(row["posterior_entropy_nats"])
            valid_rows += 1
            is_eval = v08.is_held_out(bundle)
            if is_eval:
                held_rows += 1
                eval_found.add(group_id)
            else:
                train_entropy.append(entropy)
            for axis in FAMILY_AXES:
                identity = (axis, str(row["family_ids"][axis]))
                previous = owners.setdefault(identity, bundle)
                if previous != bundle:
                    raise ValueError("a family identity crosses split bundles")
            for mapping, identity, label in (
                (root_owner, root, "root"),
                (episode_owner, episode_id, "episode"),
            ):
                previous = mapping.setdefault(identity, bundle)
                if previous != bundle:
                    raise ValueError(f"a {label} crosses split bundles")
            gold = one_digest(row["overlap_keys"], "gold_target:", f"line {line_number}")
            prior_gold = gold_by_input.setdefault(input_id, gold)
            if prior_gold != gold:
                raise ValueError("one model input maps to conflicting gold targets")
    if eval_found != eval_ids:
        raise ValueError(
            f"evaluation identity mismatch: derived={len(eval_found)} manifest={len(eval_ids)}"
        )
    train_entropy.sort()
    if not train_entropy:
        raise ValueError("eligible training pool is empty")
    thresholds = [
        train_entropy[min(len(train_entropy) - 1, math.floor(len(train_entropy) * q / 5))]
        for q in range(1, 5)
    ]
    return thresholds, {
        "valid_group_count": valid_rows,
        "eligible_group_count": len(train_entropy),
        "evaluation_group_count": held_rows,
        "evaluation_manifest_count": len(eval_ids),
        "unique_group_count": len(seen),
        "unique_input_count": len(gold_by_input),
        "input_gold_conflict_count": 0,
        "family_root_episode_split_checks": "pass",
    }


def cell_for(row: dict[str, Any], thresholds: list[float]) -> tuple[str, ...]:
    strata = row["strata"]
    entropy = float(row["posterior_entropy_nats"])
    q = bisect.bisect_right(thresholds, entropy) + 1
    return (
        str(strata["world_family"]),
        str(row["split_family_bundle_id"]),
        str(strata["query_view_type"]),
        str(strata["candidate_cardinality_bin"]),
        f"q{q}",
        entropy_band(entropy),
    )


def atom_for(row: dict[str, Any], cell: tuple[str, ...], input_id: str) -> tuple[Any, ...]:
    topology = tuple(sorted({
        str(value) for value in row["coverage_features"]["structural_coverage"]
        if str(value).startswith("topology:")
    }))
    intervention = str(row["family_ids"]["intervention_family"])
    return input_id, str(row["root_id"]), cell, topology, intervention


def make_profiles_and_atoms(
    group_records: Path,
    thresholds: list[float],
    r_ids: set[str],
    c_ids: set[str],
) -> tuple[list[tuple[Any, ...]], Counter[tuple[Any, ...]], dict[str, dict[str, Counter[Any]]], dict[str, Any]]:
    atoms: Counter[tuple[Any, ...]] = Counter()
    profiles: dict[str, dict[str, Counter[Any]]] = {
        name: {key: Counter() for key in ("cells", "inputs", "roots", "topology", "interventions", "views", "cardinality", "bundles", "entropy_bands")}
        for name in ("R100", "C100")
    }
    found = Counter()
    input_cells: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    with group_records.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row["valid"] is not True:
                continue
            group_id = str(row["group_id"])
            if v08.is_held_out(str(row["split_family_bundle_id"])):
                continue
            parsed = parse_row(row, line_number)
            assert parsed is not None
            input_id = parsed[4]
            cell = cell_for(row, thresholds)
            atoms[atom_for(row, cell, input_id)] += 1
            input_cells[input_id].add(cell)
            for name, ids in (("R100", r_ids), ("C100", c_ids)):
                if group_id not in ids:
                    continue
                found[name] += 1
                p = profiles[name]
                p["cells"][cell] += 1
                p["inputs"][input_id] += 1
                p["roots"][str(row["root_id"])] += 1
                p["views"][cell[2]] += 1
                p["cardinality"][cell[3]] += 1
                p["bundles"][cell[1]] += 1
                p["entropy_bands"][cell[5]] += 1
                for feature in atom_for(row, cell, input_id)[3]:
                    p["topology"][feature.removeprefix("topology:")] += 1
                p["interventions"][str(row["family_ids"]["intervention_family"])] += 1
    if found["R100"] != len(r_ids) or found["C100"] != len(c_ids):
        raise ValueError("reference manifest identities are not all eligible training groups")
    cross_cell_inputs = sum(len(cells) > 1 for cells in input_cells.values())
    if cross_cell_inputs:
        raise ValueError(f"{cross_cell_inputs} input signatures cross joint cells")
    atom_rows = sorted(atoms)
    return atom_rows, atoms, profiles, {
        "atom_count": len(atom_rows),
        "eligible_group_count": sum(atoms.values()),
        "input_signatures_crossing_joint_cells": cross_cell_inputs,
        "reference_membership_found": dict(found),
        "maximum_atom_capacity": max(atoms.values(), default=0),
    }


def histogram(counter: Counter[Any]) -> Counter[int]:
    return Counter(counter.values())


def histogram_tv_integer_pass(
    selected_histogram: Counter[int],
    reference_histogram: Counter[int],
    selected_total: int,
    reference_total: int,
) -> bool:
    if selected_total <= 0 or reference_total <= 0:
        return selected_total == reference_total == 0
    bins = set(selected_histogram) | set(reference_histogram)
    discrepancy = sum(
        abs(reference_total * selected_histogram.get(k, 0) - selected_total * reference_histogram.get(k, 0))
        for k in bins
    )
    return 25 * discrepancy <= selected_total * reference_total


def outward_interval(reference_count: int) -> tuple[int, int]:
    return math.floor(reference_count * 0.98), math.ceil(reference_count * 1.02)


def add_histogram_constraints(
    model: cp_model.CpModel,
    degree_vars_by_id: list[list[cp_model.IntVar]],
    presence_vars: list[cp_model.IntVar],
    ref_counts: Counter[Any],
    assumption: cp_model.IntVar,
    total_label: str,
) -> tuple[list[cp_model.IntVar], int, dict[str, Any]]:
    ref_hist = histogram(ref_counts)
    ref_unique = len(ref_counts)
    low, high = outward_interval(ref_unique)
    selected_unique = model.new_int_var(low, high, "")
    model.add(selected_unique == sum(presence_vars)).only_enforce_if(assumption)
    selected_hist: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    for degree_vars in degree_vars_by_id:
        for degree, variable in enumerate(degree_vars, 1):
            selected_hist[degree].append(variable)
    categories = range(1, max(max(selected_hist, default=0), max(ref_hist, default=0)) + 1)
    deviations: list[cp_model.IntVar] = []
    for degree in categories:
        selected_bin: Any = sum(selected_hist.get(degree, ()))
        reference_bin = ref_hist.get(degree, 0)
        deviation_bound = ref_unique * len(degree_vars_by_id) + high * reference_bin
        deviation = model.new_int_var(0, max(1, deviation_bound), "")
        model.add_abs_equality(
            deviation,
            ref_unique * selected_bin - reference_bin * selected_unique,
        )
        deviations.append(deviation)
    model.add(25 * sum(deviations) <= ref_unique * selected_unique).only_enforce_if(assumption)
    return deviations, ref_unique, {
        "reference_unique_count": ref_unique,
        "unique_count_interval": [low, high],
        "reference_multiplicity_bins": len(ref_hist),
        "modeled_multiplicity_bins": len(list(categories)),
        "tv_limit": 0.02,
        "total_name": total_label,
    }


def add_profile_model(
    atoms: list[tuple[Any, ...]],
    capacities: Counter[tuple[Any, ...]],
    reference: dict[str, Counter[Any]],
    random_seed: int,
    max_time: int,
) -> tuple[cp_model.CpModel, dict[str, Any]]:
    model = cp_model.CpModel()
    atom_vars = [model.new_int_var(0, capacities[key], "") for key in atoms]
    assumption_names = ("joint_cells", "input_profile", "root_profile", "topology", "intervention")
    assumptions = {name: model.new_bool_var("") for name in assumption_names}
    model.add_assumptions(list(assumptions.values()))
    cell_vars: dict[tuple[str, ...], list[cp_model.IntVar]] = defaultdict(list)
    input_vars: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    root_vars: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    topology_vars: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    intervention_vars: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    input_caps: Counter[str] = Counter()
    root_caps: Counter[str] = Counter()

    for key, variable in zip(atoms, atom_vars):
        input_id, root_id, cell, topology_features, intervention = key
        cell_vars[cell].append(variable)
        input_vars[input_id].append(variable)
        root_vars[root_id].append(variable)
        input_caps[input_id] += capacities[key]
        root_caps[root_id] += capacities[key]
        for feature in topology_features:
            topology_vars[feature.removeprefix("topology:")].append(variable)
        intervention_vars[intervention].append(variable)

    model.add(sum(atom_vars) == GROUP_LIMIT)
    cell_keys = set(cell_vars) | set(reference["cells"])
    for cell in cell_keys:
        model.add(sum(cell_vars.get(cell, ())) == reference["cells"].get(cell, 0)).only_enforce_if(assumptions["joint_cells"])

    def add_degree_profile(
        identities: dict[Any, list[cp_model.IntVar]],
        upper_caps: Counter[Any],
        reference_counts: Counter[Any],
        assumption: cp_model.IntVar,
        label: str,
    ) -> dict[str, Any]:
        degree_vars_by_id: list[list[cp_model.IntVar]] = []
        presence_vars: list[cp_model.IntVar] = []
        counts: list[cp_model.IntVar] = []
        for identity in sorted(identities):
            cap = upper_caps[identity]
            count_var = model.new_int_var(0, cap, "")
            present = model.new_bool_var("")
            bins = [model.new_bool_var("") for _ in range(cap)]
            model.add(count_var == sum(identities[identity]))
            model.add(sum(bins) == present)
            model.add(count_var == sum((degree + 1) * variable for degree, variable in enumerate(bins)))
            degree_vars_by_id.append(bins)
            presence_vars.append(present)
            counts.append(count_var)
        _deviations, ref_unique, histogram_info = add_histogram_constraints(
            model, degree_vars_by_id, presence_vars, reference_counts, assumption, label
        )
        low, high = outward_interval(ref_unique)
        model.add(sum(presence_vars) >= low).only_enforce_if(assumption)
        model.add(sum(presence_vars) <= high).only_enforce_if(assumption)
        return {
            "identity_count": len(identities),
            "degree_indicator_count": sum(len(row) for row in degree_vars_by_id),
            "max_candidate_capacity": max(upper_caps.values(), default=0),
            **histogram_info,
        }

    input_info = add_degree_profile(input_vars, input_caps, reference["inputs"], assumptions["input_profile"], "inputs")
    root_info = add_degree_profile(root_vars, root_caps, reference["roots"], assumptions["root_profile"], "roots")

    ref_topology = reference["topology"]
    topology_keys = set(topology_vars) | set(ref_topology)
    selected_topology_total = sum(
        len(key[3]) * variable for key, variable in zip(atoms, atom_vars)
    )
    ref_topology_total = sum(ref_topology.values())
    if ref_topology_total:
        model.add(selected_topology_total >= 1).only_enforce_if(assumptions["topology"])
        topology_deviations = []
        for name in sorted(topology_keys):
            selected_count = sum(topology_vars.get(name, ()))
            ref_count = ref_topology.get(name, 0)
            bound = ref_topology_total * GROUP_LIMIT * max(1, max((len(k[3]) for k in atoms), default=1)) + GROUP_LIMIT * ref_count
            deviation = model.new_int_var(0, max(1, bound), "")
            model.add_abs_equality(deviation, ref_topology_total * selected_count - ref_count * selected_topology_total)
            topology_deviations.append(deviation)
        model.add(25 * sum(topology_deviations) <= ref_topology_total * selected_topology_total).only_enforce_if(assumptions["topology"])
    else:
        model.add(selected_topology_total == 0).only_enforce_if(assumptions["topology"])

    intervention_keys = set(intervention_vars) | set(reference["interventions"])
    intervention_deviations = []
    for name in sorted(intervention_keys):
        selected_count = sum(intervention_vars.get(name, ()))
        ref_count = reference["interventions"].get(name, 0)
        deviation = model.new_int_var(0, GROUP_LIMIT, "")
        model.add_abs_equality(deviation, selected_count - ref_count)
        intervention_deviations.append(deviation)
    model.add(sum(intervention_deviations) <= 4000).only_enforce_if(assumptions["intervention"])

    info = {
        "atom_variable_count": len(atom_vars),
        "joint_cell_count": len(cell_keys),
        "input": input_info,
        "root": root_info,
        "topology_category_count": len(topology_keys),
        "topology_reference_feature_count": ref_topology_total,
        "intervention_category_count": len(intervention_keys),
        "assumptions": {str(literal.index): name for name, literal in assumptions.items()},
        "random_seed": random_seed,
        "max_time_seconds": max_time,
        "objective": None,
        "atom_key_order_sha256": sha256_json(atoms),
    }
    return model, {"info": info, "assumptions": assumptions, "atoms": atoms, "atom_vars": atom_vars}


def profile_solution(atoms: list[tuple[Any, ...]], values: list[int]) -> dict[str, Counter[Any]]:
    result = {name: Counter() for name in ("cells", "inputs", "roots", "topology", "interventions")}
    for key, count in zip(atoms, values):
        if count <= 0:
            continue
        input_id, root_id, cell, topology_features, intervention = key
        result["cells"][cell] += count
        result["inputs"][input_id] += count
        result["roots"][root_id] += count
        result["interventions"][intervention] += count
        for feature in topology_features:
            result["topology"][feature.removeprefix("topology:")] += count
    return result


def profile_audit(selected: dict[str, Counter[Any]], reference: dict[str, Counter[Any]]) -> dict[str, Any]:
    from collections import Counter as C

    def tv(left: Counter[Any], right: Counter[Any]) -> float:
        left_total, right_total = sum(left.values()), sum(right.values())
        if not left_total or not right_total:
            return 0.0 if not left_total and not right_total else 1.0
        keys = set(left) | set(right)
        return 0.5 * sum(abs(left.get(key, 0) / left_total - right.get(key, 0) / right_total) for key in keys)

    def within(actual: int, expected: int) -> bool:
        low, high = outward_interval(expected)
        return low <= actual <= high

    input_hist_tv = tv(histogram(selected["inputs"]), histogram(reference["inputs"]))
    root_hist_tv = tv(histogram(selected["roots"]), histogram(reference["roots"]))
    input_hist_integer_pass = histogram_tv_integer_pass(
        histogram(selected["inputs"]), histogram(reference["inputs"]),
        len(selected["inputs"]), len(reference["inputs"]),
    )
    root_hist_integer_pass = histogram_tv_integer_pass(
        histogram(selected["roots"]), histogram(reference["roots"]),
        len(selected["roots"]), len(reference["roots"]),
    )

    view = C()
    cardinality = C()
    bundles = C()
    entropy_bands = C()
    for cell, count in selected["cells"].items():
        view[cell[2]] += count
        cardinality[cell[3]] += count
        bundles[cell[1]] += count
        entropy_bands[cell[5]] += count
    ref_view = C()
    ref_cardinality = C()
    ref_bundles = C()
    ref_entropy = C()
    for cell, count in reference["cells"].items():
        ref_view[cell[2]] += count
        ref_cardinality[cell[3]] += count
        ref_bundles[cell[1]] += count
        ref_entropy[cell[5]] += count

    result = {
        "selected_group_count": sum(selected["cells"].values()),
        "joint_cells_exact": selected["cells"] == reference["cells"],
        "query_views_exact": view == ref_view,
        "candidate_cardinality_exact": cardinality == ref_cardinality,
        "family_bundles_exact": bundles == ref_bundles,
        "gold_entropy_bands_exact": entropy_bands == ref_entropy,
        "unique_inputs": {
            "count": len(selected["inputs"]),
            "reference": len(reference["inputs"]),
            "pass_2pct": within(len(selected["inputs"]), len(reference["inputs"])),
            "multiplicity_histogram_tv": input_hist_tv,
            "integer_constraint_pass": input_hist_integer_pass,
        },
        "unique_roots": {
            "count": len(selected["roots"]),
            "reference": len(reference["roots"]),
            "pass_2pct": within(len(selected["roots"]), len(reference["roots"])),
            "multiplicity_histogram_tv": root_hist_tv,
            "integer_constraint_pass": root_hist_integer_pass,
        },
        "topology_tv": tv(selected["topology"], reference["topology"]),
        "intervention_tv": tv(selected["interventions"], reference["interventions"]),
    }
    result["all_constraints_pass"] = all((
        result["selected_group_count"] == GROUP_LIMIT,
        result["joint_cells_exact"],
        result["query_views_exact"],
        result["candidate_cardinality_exact"],
        result["family_bundles_exact"],
        result["gold_entropy_bands_exact"],
        result["unique_inputs"]["pass_2pct"],
        result["unique_inputs"]["integer_constraint_pass"],
        result["unique_roots"]["pass_2pct"],
        result["unique_roots"]["integer_constraint_pass"],
        result["topology_tv"] <= 0.02 + 1e-12,
        result["intervention_tv"] <= 0.02 + 1e-12,
    ))
    return result


def solve_one(
    name: str,
    atoms: list[tuple[Any, ...]],
    capacities: Counter[tuple[Any, ...]],
    reference: dict[str, Counter[Any]],
    seed: int,
    time_limit: int,
    output_dir: Path,
    contract_hash: str,
    source_hash: str,
) -> dict[str, Any]:
    build_started = time.perf_counter()
    model, bundle = add_profile_model(atoms, capacities, reference, seed, time_limit)
    model_seconds = time.perf_counter() - build_started
    validation = model.validate()
    proto = model.proto
    model_info = {
        **bundle["info"],
        "variable_count": len(proto.variables),
        "constraint_count": len(proto.constraints),
        "validation_error": validation or None,
        "build_seconds": model_seconds,
    }
    if validation:
        return {
            "profile": name,
            "status": "MODEL_INVALID",
            "model": model_info,
            "contract_sha256": contract_hash,
            "solver_source_sha256": source_hash,
            "objective": None,
        }

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = float(time_limit)
    solve_started = time.perf_counter()
    status = solver.solve(model)
    solve_seconds = time.perf_counter() - solve_started
    names = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    result: dict[str, Any] = {
        "profile": name,
        "status": names.get(status, f"UNRECOGNIZED_{status}"),
        "contract_sha256": contract_hash,
        "solver_source_sha256": source_hash,
        "solver_version": importlib.metadata.version("ortools"),
        "workers": 1,
        "random_seed": seed,
        "wall_time_limit_seconds": time_limit,
        "build_seconds": model_seconds,
        "solve_seconds": solve_seconds,
        "solver_wall_time_seconds": solver.wall_time,
        "conflicts": solver.num_conflicts,
        "branches": solver.num_branches,
        "model": model_info,
        "objective": None,
        "response_stats": solver.response_stats(),
    }
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        values = [solver.value(variable) for variable in bundle["atom_vars"]]
        selected = profile_solution(atoms, values)
        audit = profile_audit(selected, reference)
        result["independent_witness_audit"] = audit
        if audit["all_constraints_pass"]:
            solution_rows = [
                {"atom_index": index, "selected_count": count}
                for index, count in enumerate(values)
                if count
            ]
            solution_hash = sha256_json(solution_rows)
            witness = {
                "profile": name,
                "atom_key_order_sha256": bundle["info"]["atom_key_order_sha256"],
                "selected_atom_count": len(solution_rows),
                "solution_sha256": solution_hash,
                "selected_atom_counts": solution_rows,
            }
            witness_path = output_dir / f"{name.lower()}-feasibility-witness.json"
            witness_path.write_text(json.dumps(witness, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            result["solution_sha256"] = solution_hash
            result["witness_path"] = str(witness_path)
            result["status"] = "FEASIBLE"
        else:
            result["status"] = "WITNESS_VALIDATION_FAILED"
    elif status == cp_model.INFEASIBLE:
        index_to_name = {int(index): label for index, label in bundle["info"]["assumptions"].items()}
        core = []
        for literal in solver.sufficient_assumptions_for_infeasibility():
            index = literal if literal >= 0 else -literal - 1
            core.append(index_to_name.get(index, f"unknown_assumption_{index}"))
        result["sufficient_unsat_core"] = sorted(set(core))
        result["unsat_core_is_minimal"] = False
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = HERE / "v08c-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    source_hash = sha256_file(Path(__file__))
    if contract["solver"].get("source_sha256") != source_hash:
        raise ValueError("frozen v0.8C solver source hash mismatch")
    installed_solver = importlib.metadata.version("ortools")
    if installed_solver != contract["solver"]["version"]:
        raise ValueError("installed OR-Tools version differs from the frozen contract")
    expected = contract["inputs"]
    v08b_contract = HERE.parent / "jev-information-density-v08b" / "v08b-contract.json"
    v08_selector = V08_DIR / "select_banks.py"
    v08_contract = V08_DIR / "v08-contract.json"
    failed_build = args.v08b_failed_report
    actual = {
        "group_records_sha256": sha256_file(args.group_records),
        "r100_manifest_sha256": sha256_file(args.r100),
        "c100_manifest_sha256": sha256_file(args.c100),
        "eval_manifest_sha256": sha256_file(args.eval),
        "v08b_contract_sha256": sha256_file(v08b_contract),
        "v08_contract_sha256": sha256_file(v08_contract),
        "v08_selector_sha256": sha256_file(v08_selector),
        "v08b_failed_report_sha256": sha256_file(failed_build),
    }
    for field in ("group_records_sha256", "r100_manifest_sha256", "c100_manifest_sha256", "eval_manifest_sha256"):
        if expected[field] != actual[field]:
            raise ValueError(f"pinned input hash mismatch: {field}")
    if contract["v08b_immutable"]["contract_sha256"] != actual["v08b_contract_sha256"]:
        raise ValueError("v0.8B contract hash mismatch")
    if contract["v08b_immutable"]["failed_constructor_report_sha256"] != actual["v08b_failed_report_sha256"]:
        raise ValueError("v0.8B failed-constructor report hash mismatch")
    v08b = json.loads(v08b_contract.read_text(encoding="utf-8"))
    if v08b["inherited_v08"]["contract_sha256"] != actual["v08_contract_sha256"]:
        raise ValueError("inherited v0.8 contract hash mismatch")
    if v08b["inherited_v08"]["selector_source_sha256"] != actual["v08_selector_sha256"]:
        raise ValueError("inherited v0.8 selector hash mismatch")

    r_ids, c_ids, eval_ids = (read_ids(path) for path in (args.r100, args.c100, args.eval))
    if len(r_ids) != GROUP_LIMIT or len(c_ids) != GROUP_LIMIT:
        raise ValueError("R100/C100 reference manifest must contain exactly 100,000 IDs")
    if (r_ids | c_ids) & eval_ids:
        raise ValueError("a reference bank contains a NewTight-Eval group")
    thresholds, firewall = inspect_and_thresholds(args.group_records, eval_ids)
    atoms, capacities, profiles, atom_summary = make_profiles_and_atoms(
        args.group_records, thresholds, r_ids, c_ids
    )
    if atom_summary["eligible_group_count"] != expected["eligible_group_count"]:
        raise ValueError("eligible group count differs from frozen contract")
    if atom_summary["reference_membership_found"] != {"R100": len(r_ids), "C100": len(c_ids)}:
        raise ValueError("reference membership count mismatch")

    args.out.mkdir(parents=True, exist_ok=False)
    preflight = {
        "contract": contract["contract"],
        "contract_sha256": sha256_file(contract_path),
        "solver_source_sha256": sha256_file(Path(__file__)),
        "inputs": actual,
        "eligible_pool_audit": firewall,
        "training_entropy_quintile_thresholds_nats": thresholds,
        "atomization": atom_summary,
        "reference_profiles": {
            name: {
                key: len(value) if key in ("inputs", "roots") else sum(value.values())
                for key, value in profile.items()
            }
            for name, profile in profiles.items()
        },
        "phase1_reference_witnesses": {
            name: {
                "status": "FEASIBLE_BY_REFERENCE_IDENTITY",
                "witness_manifest_sha256": actual[f"{name.lower()}_manifest_sha256"],
                "target_profile_is_defined_from_same_reference_bank": True,
                "group_count": sum(profile["cells"].values()),
                "eligible_reference_groups_found": atom_summary["reference_membership_found"][name],
                "self_comparison_exact_cell_mismatches": 0,
                "self_comparison_unique_count_relative_error": 0.0,
                "self_comparison_occurrence_histogram_tv": 0.0,
                "self_comparison_topology_tv": 0.0,
                "self_comparison_intervention_tv": 0.0,
                "solver_needed_to_establish_nonempty_feasible_set": False,
            }
            for name, profile in profiles.items()
        },
        "model_contact_authorized": False,
        "phoenix_in_scope": False,
    }
    (args.out / "preflight.json").write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.preflight_only:
        report = {
            "contract": contract["contract"],
            "contract_sha256": preflight["contract_sha256"],
            "preflight_status": "COMPLETE",
            "solver_model_built": False,
            "model_contact_authorized": False,
            "phoenix_in_scope": False,
        }
        (args.out / "feasibility-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    results = []
    for name in ("R100", "C100"):
        result = solve_one(
            name,
            atoms,
            capacities,
            profiles[name],
            contract["solver"]["random_seed"],
            contract["solver"]["wall_time_limit_seconds_per_profile"],
            args.out,
            preflight["contract_sha256"],
            preflight["solver_source_sha256"],
        )
        result_path = args.out / f"{name.lower()}-feasibility.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(result)

    statuses = {result["status"] for result in results}
    fallback = "proven_infeasible" if "INFEASIBLE" in statuses else "not_triggered"
    report = {
        "contract": contract["contract"],
        "contract_sha256": preflight["contract_sha256"],
        "solver_source_sha256": preflight["solver_source_sha256"],
        "profiles": {result["profile"]: result["status"] for result in results},
        "fallback_status": fallback,
        "fallback_may_run": fallback == "proven_infeasible",
        "model_contact_authorized": False,
        "phoenix_in_scope": False,
        "bank_ids_emitted": False,
        "training_banks_materialized": False,
    }
    (args.out / "feasibility-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-records", type=Path, required=True)
    parser.add_argument("--r100", type=Path, required=True)
    parser.add_argument("--c100", type=Path, required=True)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--v08b-failed-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {args.out}")
    report = run(args)
    if "profiles" in report:
        summary = {
            "profiles": report["profiles"],
            "fallback_status": report["fallback_status"],
            "model_contact_authorized": False,
        }
    else:
        summary = {
            "preflight_status": report["preflight_status"],
            "solver_model_built": report["solver_model_built"],
            "model_contact_authorized": False,
        }
    print(json.dumps(summary))


if __name__ == "__main__":
    main()

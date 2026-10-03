"""Metadata-only Phase 2 optimizer for the Jev v0.8C matched banks."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ortools.sat.python import cp_model


HERE = Path(__file__).resolve().parent
V08_DIR = HERE.parent / "jev-information-density-v08"
V08B_DIR = HERE.parent / "jev-information-density-v08b"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(V08_DIR))
sys.path.insert(0, str(V08B_DIR))
import select_banks as v08  # noqa: E402
import build_factorial_banks as v08b  # noqa: E402
import solve_feasibility as v08c  # noqa: E402


def load_contract() -> tuple[dict[str, Any], Path]:
    path = HERE / "v08c-phase2-contract.json"
    return json.loads(path.read_text(encoding="utf-8")), path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_phase1(path: Path, expected_contract_hash: str) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("contract_sha256") != expected_contract_hash:
        raise ValueError("Phase 1 receipt contract hash mismatch")
    witnesses = receipt.get("phase1_reference_witnesses", {})
    for name in ("R100", "C100"):
        if witnesses.get(name, {}).get("status") != "FEASIBLE_BY_REFERENCE_IDENTITY":
            raise ValueError(f"missing accepted Phase 1 witness for {name}")
    return receipt


def train_groups_and_profiles(
    group_records: Path,
    eval_manifest: Path,
    r100_manifest: Path,
    c100_manifest: Path,
) -> tuple[list[v08.Group], list[tuple[Any, ...]], dict[tuple[Any, ...], int], dict[str, Any], dict[str, list[v08.Group]]]:
    eval_ids = v08c.read_ids(eval_manifest)
    r_ids = v08c.read_ids(r100_manifest)
    c_ids = v08c.read_ids(c100_manifest)
    thresholds, _firewall = v08c.inspect_and_thresholds(group_records, eval_ids)
    atoms, capacities, profiles, atom_summary = v08c.make_profiles_and_atoms(
        group_records, thresholds, r_ids, c_ids
    )

    all_groups = v08.read_group_records(group_records)
    train_groups, eval_pairs, _axes = v08.split_families(all_groups)
    if {group.group_id for group, _ in eval_pairs} != eval_ids:
        raise ValueError("NewTight-Eval identity differs from the pinned manifest")
    train_groups = v08.assign_training_entropy_quintiles(train_groups)
    if len(train_groups) != atom_summary["eligible_group_count"]:
        raise ValueError("loaded eligible group count differs from atom preflight")

    references = {
        "R100": [group for group in train_groups if group.group_id in r_ids],
        "C100": [group for group in train_groups if group.group_id in c_ids],
    }
    if any(len(groups) != v08.GROUP_LIMIT for groups in references.values()):
        raise ValueError("reference manifest does not resolve to 100,000 eligible groups")
    if (r_ids | c_ids) & eval_ids:
        raise ValueError("an existing training bank overlaps NewTight-Eval")
    return train_groups, atoms, capacities, profiles, references


def group_atom(group: v08.Group) -> tuple[Any, ...]:
    input_id = v08b.model_input_id(group)
    cell = v08b.joint_cell(group)
    topology = tuple(sorted({
        feature for feature in group.features[3]
        if feature.startswith("topology:")
    }))
    intervention = dict(group.families)["intervention_family"]
    return input_id, group.root_id, cell, topology, intervention


def priority_ranks(
    groups: list[v08.Group], mode: str, seed: str
) -> dict[str, int]:
    if mode == "curated":
        counts = v08b.feature_counts(groups)
        scored = [
            (v08b.group_coverage_score(group, counts), group)
            for group in groups
        ]
        ordered = sorted(
            scored,
            key=lambda item: (
                -item[0],
                v08b.stable_digest(seed, item[1].group_id),
                item[1].group_id,
            ),
        )
    elif mode == "random":
        ordered = [
            (None, group)
            for group in sorted(
                groups,
                key=lambda group: (
                    v08b.stable_digest(seed, group.group_id),
                    group.group_id,
                ),
            )
        ]
    else:
        raise ValueError(f"unknown priority mode: {mode}")
    total = len(ordered)
    # Larger integer means higher frozen priority; this encodes the complete
    # deterministic ordering without floating-point objective coefficients.
    return {group.group_id: total - rank for rank, (_score, group) in enumerate(ordered)}


def add_priority_objective(
    model: cp_model.CpModel,
    atom_vars: list[cp_model.IntVar],
    atoms: list[tuple[Any, ...]],
    members_by_atom: dict[tuple[Any, ...], list[v08.Group]],
    priorities: dict[str, int],
) -> tuple[list[tuple[v08.Group, cp_model.IntVar]], int]:
    selected_vars: list[tuple[v08.Group, cp_model.IntVar]] = []
    objective_terms: list[Any] = []
    variable_index = 0
    for atom_index, atom in enumerate(atoms):
        members = members_by_atom.get(atom, [])
        if not members:
            raise ValueError("atom has capacity but no group records")
        member_vars: list[cp_model.IntVar] = []
        for group in members:
            variable = model.new_bool_var(f"pick_{variable_index}")
            variable_index += 1
            member_vars.append(variable)
            selected_vars.append((group, variable))
            objective_terms.append(priorities[group.group_id] * variable)
        model.add(sum(member_vars) == atom_vars[atom_index])
    model.maximize(sum(objective_terms))
    return selected_vars, variable_index


def verify_pins(
    args: argparse.Namespace,
    contract: dict[str, Any],
    contract_path: Path,
) -> dict[str, str]:
    pins = contract["inputs"]
    v08b_contract = V08B_DIR / "v08b-contract.json"
    v08_contract = V08_DIR / "v08-contract.json"
    v08_selector = V08_DIR / "select_banks.py"
    v08c_contract = HERE / "v08c-contract.json"
    phase1_solver = HERE / "solve_feasibility.py"
    actual = {
        "group_records_sha256": sha256_file(args.group_records),
        "r100_manifest_sha256": sha256_file(args.r100),
        "c100_manifest_sha256": sha256_file(args.c100),
        "eval_manifest_sha256": sha256_file(args.eval),
        "v08_contract_sha256": sha256_file(v08_contract),
        "v08_selector_sha256": sha256_file(v08_selector),
        "v08b_contract_sha256": sha256_file(v08b_contract),
        "v08c_contract_sha256": sha256_file(v08c_contract),
        "phase1_solver_sha256": sha256_file(phase1_solver),
        "phase2_solver_sha256": sha256_file(Path(__file__)),
        "phase1_receipt_sha256": sha256_file(args.phase1_receipt),
        "phase2_contract_sha256": sha256_file(contract_path),
    }
    for name in (
        "group_records_sha256", "r100_manifest_sha256", "c100_manifest_sha256",
        "eval_manifest_sha256", "v08_contract_sha256", "v08_selector_sha256",
        "v08b_contract_sha256", "v08c_contract_sha256", "phase1_solver_sha256",
    ):
        if actual[name] != pins[name]:
            raise ValueError(f"frozen input hash mismatch: {name}")
    if actual["phase2_solver_sha256"] != contract["solver"]["source_sha256"]:
        raise ValueError("Phase 2 solver source hash mismatch")
    if actual["phase2_solver_sha256"] != pins["phase2_solver_sha256"]:
        raise ValueError("Phase 2 solver source pin mismatch")
    if actual["phase1_receipt_sha256"] != pins["phase1_receipt_sha256"]:
        raise ValueError("Phase 1 receipt hash mismatch")
    if actual["v08c_contract_sha256"] != contract["phase1_contract_sha256"]:
        raise ValueError("Phase 1 contract hash differs from the Phase 2 amendment")
    if importlib_version() != contract["solver"]["version"]:
        raise ValueError("OR-Tools version differs from Phase 2 contract")
    load_phase1(args.phase1_receipt, actual["v08c_contract_sha256"])
    return actual


def importlib_version() -> str:
    import importlib.metadata

    return importlib.metadata.version("ortools")


def solve_bank(
    output_name: str,
    reference_name: str,
    mode: str,
    seed: str,
    train_groups: list[v08.Group],
    atoms: list[tuple[Any, ...]],
    capacities: dict[tuple[Any, ...], int],
    profiles: dict[str, Any],
    references: dict[str, list[v08.Group]],
    args: argparse.Namespace,
    contract: dict[str, Any],
    pins: dict[str, str],
) -> dict[str, Any]:
    members_by_atom: dict[tuple[Any, ...], list[v08.Group]] = defaultdict(list)
    for group in train_groups:
        members_by_atom[group_atom(group)].append(group)
    if set(members_by_atom) != set(atoms):
        raise ValueError("loaded group atom identities differ from the frozen atom table")
    for atom in atoms:
        members_by_atom[atom].sort(key=lambda group: group.group_id)
        if len(members_by_atom[atom]) != capacities[atom]:
            raise ValueError("atom capacity differs from member record count")

    priorities = priority_ranks(train_groups, mode, seed)
    reference_profile = v08b.profile(references[reference_name])
    model_started = time.perf_counter()
    model, bundle = v08c.add_profile_model(
        atoms,
        capacities,
        profiles[reference_name],
        contract["solver"]["random_seed"],
        contract["solver"]["wall_time_limit_seconds_per_bank"],
    )
    selected_vars, selection_var_count = add_priority_objective(
        model, bundle["atom_vars"], atoms, members_by_atom, priorities
    )
    model_seconds = time.perf_counter() - model_started
    validation_error = model.validate()
    if validation_error:
        raise ValueError(f"CP-SAT model validation failed: {validation_error}")

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = contract["solver"]["workers"]
    solver.parameters.random_seed = contract["solver"]["random_seed"]
    solver.parameters.max_time_in_seconds = contract["solver"]["wall_time_limit_seconds_per_bank"]
    solve_started = time.perf_counter()
    status_code = solver.solve(model)
    solve_seconds = time.perf_counter() - solve_started
    status_names = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status = status_names.get(status_code, f"UNRECOGNIZED_{status_code}")
    result: dict[str, Any] = {
        "bank": output_name,
        "reference_profile": reference_name,
        "selection_policy": mode,
        "status": status,
        "contract_sha256": pins["phase2_contract_sha256"],
        "phase1_receipt_sha256": pins["phase1_receipt_sha256"],
        "solver_source_sha256": pins["phase2_solver_sha256"],
        "solver_version": importlib_version(),
        "workers": solver.parameters.num_search_workers,
        "random_seed": solver.parameters.random_seed,
        "model_build_seconds": model_seconds,
        "solve_seconds": solve_seconds,
        "solver_wall_time_seconds": solver.wall_time,
        "conflicts": solver.num_conflicts,
        "branches": solver.num_branches,
        "model_variable_count": len(model.proto.variables),
        "model_constraint_count": len(model.proto.constraints),
        "selection_variable_count": selection_var_count,
        "objective_policy": contract["objective"][f"{mode}_objective"],
        "objective_value": solver.objective_value if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        "best_objective_bound": solver.best_objective_bound if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        "response_stats": solver.response_stats(),
        "bank_ids_emitted": False,
        "independent_audit": None,
    }
    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return result

    selected = [group for group, variable in selected_vars if solver.value(variable)]
    if len(selected) != v08.GROUP_LIMIT:
        raise ValueError(f"solver selected {len(selected)} groups, expected {v08.GROUP_LIMIT}")
    selected_profile = v08b.profile(selected)
    audit = v08c.profile_audit(selected_profile, reference_profile)
    passed = audit["all_constraints_pass"]
    result["independent_audit"] = audit
    result["selected_group_count"] = len(selected)
    result["reference_group_overlap"] = len({group.group_id for group in selected} & {group.group_id for group in references[reference_name]})
    result["reference_group_overlap_fraction"] = result["reference_group_overlap"] / v08.GROUP_LIMIT
    if not passed:
        result["status"] = "WITNESS_VALIDATION_FAILED"
        return result

    manifest_path = args.out / f"{output_name.lower()}-ids.jsonl"
    v08b.write_ids(manifest_path, selected)
    result["manifest_path"] = str(manifest_path)
    result["manifest_sha256"] = sha256_file(manifest_path)
    result["bank_ids_emitted"] = True
    result["selected_priority_sum"] = sum(priorities[group.group_id] for group in selected)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract, contract_path = load_contract()
    pins = verify_pins(args, contract, contract_path)
    args.out.mkdir(parents=True, exist_ok=False)
    train_groups, atoms, capacities, profiles, references = train_groups_and_profiles(
        args.group_records, args.eval, args.r100, args.c100
    )
    bank_specs = (
        ("CM100", "R100", "curated", contract["objective"]["curated_seed"]),
        ("RM100", "C100", "random", contract["objective"]["random_seed"]),
    )
    results = []
    for output_name, ref_name, mode, seed in bank_specs:
        print(json.dumps({"status": "STARTING", "bank": output_name}), flush=True)
        result = solve_bank(
            output_name, ref_name, mode, seed, train_groups, atoms, capacities,
            profiles, references, args, contract, pins,
        )
        result_path = args.out / f"{output_name.lower()}-result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(result)
        print(json.dumps({"status": result["status"], "bank": output_name, "bank_ids_emitted": result["bank_ids_emitted"]}), flush=True)

    report = {
        "contract": contract["contract"],
        "contract_sha256": pins["phase2_contract_sha256"],
        "inputs": pins,
        "profiles": {result["bank"]: result["status"] for result in results},
        "banks": {result["bank"]: result for result in results},
        "model_contact_authorized": False,
        "phoenix_in_scope": False,
        "training_materialized": False,
        "all_required_banks_pass": all(
            result["bank_ids_emitted"] and result["independent_audit"]["all_constraints_pass"]
            for result in results
        ),
    }
    (args.out / "phase2-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-records", type=Path, required=True)
    parser.add_argument("--r100", type=Path, required=True)
    parser.add_argument("--c100", type=Path, required=True)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--phase1-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {args.out}")
    report = run(args)
    print(json.dumps({
        "profiles": report["profiles"],
        "all_required_banks_pass": report["all_required_banks_pass"],
        "model_contact_authorized": False,
    }))


if __name__ == "__main__":
    main()

"""Metadata-only support-mobility census for frozen Phase 2C banks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_CONTRACT = HERE / "v08c-phase2c-mobility-contract.json"
DEFAULT_FREEZE = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\support-mobility-v01\freeze-receipt.json")
DEFAULT_OUT = DEFAULT_FREEZE.parent
BANKS = ("R100", "C100", "CM100_atom", "RM100_atom")
PROFILE_TOLERANCE = 0.02


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_manifest(path: Path, expected_count: int) -> set[str]:
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = row.get("group_id")
            if not isinstance(group_id, str) or not group_id or group_id in ids:
                raise ValueError(f"invalid/duplicate group_id in {path}:{line_no}")
            ids.add(group_id)
    if len(ids) != expected_count:
        raise ValueError(f"{path} has {len(ids)} IDs; expected {expected_count}")
    return ids


def tv(left: Counter[str], right: Counter[str]) -> float:
    n_left, n_right = sum(left.values()), sum(right.values())
    if not n_left or not n_right:
        return 0.0 if n_left == n_right == 0 else 1.0
    return 0.5 * sum(
        abs(left.get(key, 0) / n_left - right.get(key, 0) / n_right)
        for key in set(left) | set(right)
    )


def histogram(counter: Counter[str]) -> Counter[int]:
    return Counter(counter.values())


def read_and_verify_freeze(contract_path: Path, receipt_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if contract.get("status") != "frozen_before_support_mobility_census":
        raise ValueError("mobility contract is not prospectively frozen")
    if receipt.get("status") != "SEALED_BEFORE_SUPPORT_MOBILITY_CENSUS":
        raise ValueError("mobility freeze receipt is not sealed")
    if receipt.get("contract_sha256") != sha256_file(contract_path):
        raise ValueError("mobility contract differs from its freeze receipt")
    for relative, expected in receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"frozen mobility source changed: {relative}")
    for name, record in contract["inputs"].items():
        actual = sha256_file(Path(record["path"]))
        if actual != record["sha256"]:
            raise ValueError(f"pinned mobility input changed: {name}")
    for name, record in receipt["external_inputs"].items():
        if sha256_file(Path(record["path"])) != record["sha256"]:
            raise ValueError(f"external input changed after mobility freeze: {name}")
    if receipt.get("contract_sha256") != sha256_file(contract_path):
        raise ValueError("mobility freeze contract hash mismatch")
    return contract, receipt


def verify_parent_lineage(contract: dict[str, Any], receipt: dict[str, Any]) -> None:
    phase2c_receipt_path = Path(contract["inputs"]["phase2c_freeze_receipt"]["path"])
    phase2c_receipt = json.loads(phase2c_receipt_path.read_text(encoding="utf-8"))
    phase2c_contract = ROOT / "experiments/jev-information-density-v08c/v08c-phase2c-contract.json"
    if phase2c_receipt.get("contract_sha256") != sha256_file(phase2c_contract):
        raise ValueError("parent Phase 2C receipt does not pin the current parent contract")
    if phase2c_receipt.get("status") != "SEALED_BEFORE_SIGNATURE_AUDIT":
        raise ValueError("parent Phase 2C receipt status mismatch")
    for relative, expected in phase2c_receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"parent frozen source changed: {relative}")
    audit = json.loads(Path(contract["inputs"]["training_equivalence_audit"]["path"]).read_text(encoding="utf-8"))
    if audit.get("status") != "PASS_METADATA_SIGNATURES_RECONSTRUCTED":
        raise ValueError("training-signature audit is not a passing frozen audit")
    if audit.get("freeze_receipt_sha256") != contract["lineage"]["phase2c_freeze_receipt_sha256"]:
        raise ValueError("training-signature audit points at another Phase 2C receipt")
    if audit.get("external_artifacts", {}).get("sqlite_index_sha256") != contract["inputs"]["signature_sqlite"]["sha256"]:
        raise ValueError("audit report does not pin the mobility SQLite input")
    if receipt["parent_audit_sha256"] != sha256_file(Path(contract["inputs"]["training_equivalence_audit"]["path"])):
        raise ValueError("mobility receipt parent audit hash mismatch")


def bank_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cells = Counter(row["cell_json"] for row in rows)
    inputs = Counter(row["input_id"] for row in rows)
    roots = Counter(row["root_id"] for row in rows)
    topology: Counter[str] = Counter()
    interventions: Counter[str] = Counter()
    for row in rows:
        topology.update(row["topology"])
        interventions[row["intervention"]] += 1
    return {
        "group_count": len(rows),
        "unique_inputs": len(inputs),
        "unique_roots": len(roots),
        "input_occurrence_histogram": dict(sorted((str(k), v) for k, v in histogram(inputs).items())),
        "root_occurrence_histogram": dict(sorted((str(k), v) for k, v in histogram(roots).items())),
        "joint_cell_count": len(cells),
        "joint_cell_multiset_sha256": digest(sorted(cells.items())),
        "topology_total_feature_occurrences": sum(topology.values()),
        "topology_counts": dict(sorted(topology.items())),
        "intervention_counts": dict(sorted(interventions.items())),
    }


def profile_matches_audit(name: str, profile: dict[str, Any], audit: dict[str, Any]) -> None:
    expected = audit["banks"][name]
    checks = {
        "group_count": profile["group_count"] == expected["group_count"],
        "unique_inputs": profile["unique_inputs"] == expected["unique_state_query_input_count"],
        "unique_roots": profile["unique_roots"] == expected["unique_root_count"],
    }
    if not all(checks.values()):
        raise ValueError(f"bank profile differs from sealed signature audit: {name} {checks}")


def marginal_delta(source: tuple[str, ...], destination: tuple[str, ...], source_intervention: str, destination_intervention: str) -> tuple[Counter[str], Counter[str]]:
    topology = Counter(destination)
    topology.subtract(source)
    interventions: Counter[str] = Counter({destination_intervention: 1, source_intervention: -1})
    return topology, interventions


def apply_delta(base: Counter[str], delta: Counter[str]) -> Counter[str]:
    result = base.copy()
    result.update(delta)
    return +result


def profile_tv_after_swap(
    base_topology: Counter[str],
    base_interventions: Counter[str],
    reference_topology: Counter[str],
    reference_interventions: Counter[str],
    source_topology: tuple[str, ...],
    destination_topology: tuple[str, ...],
    source_intervention: str,
    destination_intervention: str,
) -> tuple[float, float]:
    topology_delta, intervention_delta = marginal_delta(
        source_topology, destination_topology, source_intervention, destination_intervention
    )
    return (
        tv(apply_delta(base_topology, topology_delta), reference_topology),
        tv(apply_delta(base_interventions, intervention_delta), reference_interventions),
    )


def build_census(contract: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    audit = json.loads(Path(contract["inputs"]["training_equivalence_audit"]["path"]).read_text(encoding="utf-8"))
    memberships = {
        bank: read_manifest(Path(contract["inputs"][bank]["path"]), contract["inputs"][bank]["count"])
        for bank in (*BANKS, "NewTight_Eval")
    }
    eval_ids = memberships.pop("NewTight_Eval")
    if any(ids & eval_ids for ids in memberships.values()):
        raise ValueError("training bank intersects NewTight-Eval")
    if set(BANKS) != set(memberships):
        raise AssertionError("bank membership set differs from frozen list")

    bank_by_group: dict[str, list[str]] = defaultdict(list)
    for bank, ids in memberships.items():
        for group_id in ids:
            bank_by_group[group_id].append(bank)

    atoms: dict[str, dict[str, Any]] = {}
    core_to_atoms: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    profiles: dict[str, dict[str, Any]] = {}
    selected_rows: dict[str, list[dict[str, Any]]] = {bank: [] for bank in BANKS}
    profiles_by_bank: dict[str, dict[str, Any]] = {}
    signatures_all: dict[str, Counter[str]] = defaultdict(Counter)
    signatures_selected: dict[str, dict[str, Counter[str]]] = {
        bank: defaultdict(Counter) for bank in BANKS
    }

    db_path = Path(contract["inputs"]["signature_sqlite"]["path"])
    uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    cursor = connection.execute(
        "SELECT group_id,root_id,selector_model_input_sha256,supervised_signature_sha256,"
        "perturbation_class,adapter_kind,view,open_world,probability_source,candidate_count,"
        "posterior_entropy_nats,joint_cell_json,family_ids_json,coverage_features_json,atom_id "
        "FROM training_groups WHERE held_out=0 ORDER BY group_id"
    )
    total = 0
    started = time.perf_counter()
    progress = out_dir / "progress.jsonl"
    with progress.open("x", encoding="utf-8", newline="\n") as progress_stream:
        for row in cursor:
            total += 1
            group_id = str(row["group_id"])
            input_id = str(row["selector_model_input_sha256"])
            root_id = str(row["root_id"])
            cell = json.loads(row["joint_cell_json"])
            families = json.loads(row["family_ids_json"])
            features = json.loads(row["coverage_features_json"])
            topology = tuple(sorted(
                str(value) for value in features.get("structural_coverage", [])
                if str(value).startswith("topology:")
            ))
            intervention = str(families["intervention_family"])
            computed_atom = digest([input_id, root_id, cell, list(topology), intervention])
            if computed_atom != row["atom_id"]:
                raise ValueError(f"atom identity mismatch at eligible group {group_id}")
            atom = atoms.get(computed_atom)
            if atom is None:
                atom = {
                    "atom_id": computed_atom,
                    "input_id": input_id,
                    "root_id": root_id,
                    "joint_cell": cell,
                    "cell_json": str(row["joint_cell_json"]),
                    "topology": list(topology),
                    "intervention": intervention,
                    "capacity": 0,
                    "selected": Counter(),
                }
                atoms[computed_atom] = atom
                core_to_atoms[(input_id, root_id, str(row["joint_cell_json"]))].add(computed_atom)
            atom["capacity"] += 1
            signature = str(row["supervised_signature_sha256"])
            signatures_all[computed_atom][signature] += 1
            banks = bank_by_group.get(group_id, ())
            for bank in banks:
                atom["selected"][bank] += 1
                signatures_selected[bank][computed_atom][signature] += 1
                selected_rows[bank].append({
                    "atom_id": computed_atom,
                    "input_id": input_id,
                    "root_id": root_id,
                    "cell_json": str(row["joint_cell_json"]),
                    "topology": topology,
                    "intervention": intervention,
                })
            if total % 50_000 == 0:
                event = {
                    "stage": "support_scan",
                    "eligible_groups": total,
                    "atoms": len(atoms),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
                progress_stream.write(json.dumps(event, separators=(",", ":")) + "\n")
                progress_stream.flush()
                print(json.dumps(event), flush=True)
    connection.close()
    if total != 416_672:
        raise ValueError(f"SQLite eligible row count {total} != frozen 416,672")
    if any(len(selected_rows[bank]) != 100_000 for bank in BANKS):
        raise ValueError({bank: len(rows) for bank, rows in selected_rows.items()})

    target_names = {"R100": "R100", "CM100_atom": "R100", "C100": "C100", "RM100_atom": "C100"}
    for bank, rows in selected_rows.items():
        profile = bank_profile(rows)
        profile_matches_audit(bank, profile, audit)
        profiles[bank] = profile
        profiles_by_bank[bank] = profile

    atom_count_maps = {
        bank: Counter({atom_id: int(atom["selected"].get(bank, 0)) for atom_id, atom in atoms.items() if atom["selected"].get(bank, 0)})
        for bank in BANKS
    }
    atom_reconciliation = {
        "CM100_atom_matches_R100_atom_count_vector": atom_count_maps["CM100_atom"] == atom_count_maps["R100"],
        "RM100_atom_matches_C100_atom_count_vector": atom_count_maps["RM100_atom"] == atom_count_maps["C100"],
    }
    if not all(atom_reconciliation.values()):
        raise ValueError(f"Phase 2B atom vectors do not match their witnesses: {atom_reconciliation}")

    atom_path = out_dir / "atom-support.jsonl"
    atom_sha = hashlib.sha256()
    occupancy: dict[str, Any] = {}
    with atom_path.open("x", encoding="utf-8", newline="\n") as stream:
        for atom_id in sorted(atoms):
            atom = atoms[atom_id]
            row = {
                key: atom[key]
                for key in ("atom_id", "input_id", "root_id", "joint_cell", "topology", "intervention", "capacity")
            }
            row["selected"] = {bank: int(atom["selected"].get(bank, 0)) for bank in BANKS}
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            stream.write(line)
            atom_sha.update(line.encode("utf-8"))

    for bank in BANKS:
        selected_atoms = [(atom, int(atom["selected"].get(bank, 0))) for atom in atoms.values() if atom["selected"].get(bank, 0)]
        occupancy[bank] = {
            "atom_count": len(selected_atoms),
            "selected_mass": sum(count for _atom, count in selected_atoms),
            "locked_selected_atoms_capacity_equals_count": sum(atom["capacity"] == count for atom, count in selected_atoms),
            "locked_selected_mass_capacity_equals_count": sum(count for atom, count in selected_atoms if atom["capacity"] == count),
            "selected_atoms_with_within_atom_slack": sum(atom["capacity"] > count for atom, count in selected_atoms),
            "selected_mass_in_atoms_with_within_atom_slack": sum(count for atom, count in selected_atoms if atom["capacity"] > count),
            "unselected_atoms_with_capacity": sum(not atom["selected"].get(bank, 0) for atom in atoms.values()),
            "unselected_group_capacity": sum(atom["capacity"] - int(atom["selected"].get(bank, 0)) for atom in atoms.values()),
        }

    cell_support: dict[str, dict[str, int]] = defaultdict(lambda: {"capacity": 0, "selected": 0})
    for atom in atoms.values():
        cell = atom["cell_json"]
        cell_support[cell]["capacity"] += atom["capacity"]
    cell_only = {}
    for bank in BANKS:
        selected_by_cell: Counter[str] = Counter(row["cell_json"] for row in selected_rows[bank])
        available_cells = sum(1 for cell, values in cell_support.items() if values["capacity"] > selected_by_cell[cell])
        cell_only[bank] = {
            "distinct_joint_cells": len(selected_by_cell),
            "selected_mass_in_cells_with_any_unselected_capacity": sum(count for cell, count in selected_by_cell.items() if cell_support[cell]["capacity"] > count),
            "cells_with_selection_and_unselected_capacity": sum(1 for cell, count in selected_by_cell.items() if cell_support[cell]["capacity"] > count),
            "cells_with_capacity_only": sum(1 for cell in cell_support if not selected_by_cell[cell]),
            "cell_slots": available_cells,
            "interpretation": "support-only diagnostic; preserves joint-cell counts only if paired within the cell, and ignores remaining profile constraints",
        }

    swaps: dict[str, Any] = {}
    for bank in BANKS:
        ref = target_names[bank]
        selected_topology: Counter[str] = Counter()
        selected_intervention: Counter[str] = Counter()
        for row in selected_rows[bank]:
            selected_topology.update(row["topology"])
            selected_intervention[row["intervention"]] += 1
        reference_topology: Counter[str] = Counter()
        reference_intervention: Counter[str] = Counter()
        for row in selected_rows[ref]:
            reference_topology.update(row["topology"])
            reference_intervention[row["intervention"]] += 1

        core_stats = {
            "core_contexts": len(core_to_atoms),
            "multi_atom_core_contexts": 0,
            "selected_mass_in_multi_atom_contexts": 0,
            "directed_atom_edges": 0,
            "one_unit_full_profile_valid_edges": 0,
            "signature_distinct_full_profile_valid_edges": 0,
            "gross_transfer_capacity_on_valid_edges": 0,
            "max_single_edge_transfer_units": 0,
            "max_tv_topology_after_single_swap": 0.0,
            "max_tv_intervention_after_single_swap": 0.0,
            "example_valid_edges": [],
        }
        bank_counter = 0
        for core, atom_ids in core_to_atoms.items():
            if len(atom_ids) < 2:
                continue
            options = sorted(atom_ids)
            active = [atom_id for atom_id in options if atoms[atom_id]["selected"].get(bank, 0)]
            if not active:
                continue
            core_stats["multi_atom_core_contexts"] += 1
            core_stats["selected_mass_in_multi_atom_contexts"] += sum(int(atoms[a]["selected"].get(bank, 0)) for a in active)
            for source_id in active:
                source = atoms[source_id]
                source_count = int(source["selected"].get(bank, 0))
                for destination_id in options:
                    if destination_id == source_id:
                        continue
                    destination = atoms[destination_id]
                    destination_slack = int(destination["capacity"] - destination["selected"].get(bank, 0))
                    if destination_slack <= 0:
                        continue
                    core_stats["directed_atom_edges"] += 1
                    topo_tv, intervention_tv = profile_tv_after_swap(
                        selected_topology,
                        selected_intervention,
                        reference_topology,
                        reference_intervention,
                        tuple(source["topology"]),
                        tuple(destination["topology"]),
                        source["intervention"],
                        destination["intervention"],
                    )
                    core_stats["max_tv_topology_after_single_swap"] = max(core_stats["max_tv_topology_after_single_swap"], topo_tv)
                    core_stats["max_tv_intervention_after_single_swap"] = max(core_stats["max_tv_intervention_after_single_swap"], intervention_tv)
                    if topo_tv > PROFILE_TOLERANCE + 1e-12 or intervention_tv > PROFILE_TOLERANCE + 1e-12:
                        continue
                    core_stats["one_unit_full_profile_valid_edges"] += 1
                    transfer_capacity = min(source_count, destination_slack)
                    core_stats["gross_transfer_capacity_on_valid_edges"] += transfer_capacity
                    core_stats["max_single_edge_transfer_units"] = max(core_stats["max_single_edge_transfer_units"], transfer_capacity)
                    source_sigs = set(signatures_selected[bank][source_id])
                    destination_sigs = {
                        signature for signature, count in signatures_all[destination_id].items()
                        if count > signatures_selected[bank][destination_id].get(signature, 0)
                    }
                    signature_distinct = any(left != right for left in source_sigs for right in destination_sigs)
                    if signature_distinct:
                        core_stats["signature_distinct_full_profile_valid_edges"] += 1
                    if len(core_stats["example_valid_edges"]) < 12:
                        core_stats["example_valid_edges"].append({
                            "core_key_sha256": digest(list(core)),
                            "source_atom_id": source_id,
                            "destination_atom_id": destination_id,
                            "selected_source_count": source_count,
                            "destination_slack": destination_slack,
                            "signature_distinct_option_exists": signature_distinct,
                            "support_only": True,
                        })
            bank_counter += 1

        # A single same-core atom swap leaves all dimensions except topology and
        # intervention unchanged; this records the audited baseline distance.
        core_stats["baseline_topology_tv_to_reference"] = tv(selected_topology, reference_topology)
        core_stats["baseline_intervention_tv_to_reference"] = tv(selected_intervention, reference_intervention)
        core_stats["full_profile_validity_scope"] = [
            "one-unit swap preserves group count, exact joint cell, exact input/root identities and occurrence histograms by construction",
            "topology and intervention marginals are recomputed against the frozen reference",
            "no cumulative multi-swap feasibility claim",
        ]
        swaps[bank] = core_stats

    # Rank-free policy contrasts are deliberately not reconstructed in this census.
    report = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-support-mobility-census",
        "status": "PASS_METADATA_SUPPORT_CENSUS",
        "freeze_receipt_sha256": sha256_file(DEFAULT_FREEZE),
        "parent_lineage": contract["lineage"],
        "source_hashes": {name: record["sha256"] for name, record in contract["inputs"].items()},
        "source_row_counts": {"eligible_rows_scanned": total, "atom_count": len(atoms), "held_out_groups_not_scanned": 83_328},
        "atom_reconciliation": atom_reconciliation,
        "banks": profiles_by_bank,
        "occupancy": occupancy,
        "cell_only_transfer_potential": cell_only,
        "same_core_cross_atom_one_unit_swaps": swaps,
        "atom_support_artifact": {"path": str(atom_path), "sha256": atom_sha.hexdigest(), "line_count": len(atoms)},
        "interpretation": {
            "support_mobility_is_not_joint_global_feasibility": True,
            "one_unit_full_profile_valid_edges_are_local_witnesses_only": True,
            "gross_transfer_capacity_double_counts_competing_edges": True,
            "supervised_signature_change_does_not_include_the_capped_invariance_regularizer": True,
            "model_contact_or_optimizer_authorized": False,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "phoenix_access": False,
        "model_contact": False,
        "optimizer_started": False,
        "training_materialized": False,
    }
    report_path = out_dir / "support-mobility-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    contract, receipt = read_and_verify_freeze(args.contract, args.freeze_receipt)
    verify_parent_lineage(contract, receipt)
    if args.out.resolve() != args.freeze_receipt.parent.resolve():
        raise ValueError("outputs must remain in the frozen external mobility directory")
    report = build_census(contract, args.out)
    print(json.dumps({
        "status": report["status"],
        "atoms": report["source_row_counts"]["atom_count"],
        "atom_support_sha256": report["atom_support_artifact"]["sha256"],
        "report": str(args.out / "support-mobility-report.json"),
        "elapsed_seconds": report["elapsed_seconds"],
    }, separators=(",", ":"), flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

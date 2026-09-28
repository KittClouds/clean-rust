"""Build deterministic atom-preserving CM100/RM100 candidate manifests.

This is the first Phase 2B construction stage only. For each witness atom
count, it takes the highest frozen-policy-ranked group IDs available in that
atom. It preserves every declared profile constraint contribution exactly;
it does not claim global optimality across alternative atom-count vectors.
Outputs are provisional until the separate raw-record validator passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "jev-information-density-v08"))
sys.path.insert(0, str(HERE.parent / "jev-information-density-v08b"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(path: Path, groups: list[Any]) -> str:
    digest = hashlib.sha256()
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for group in sorted(groups, key=lambda item: item.group_id):
            line = json.dumps({"group_id": group.group_id, "episode_id": group.episode_id}, separators=(",", ":")) + "\n"
            stream.write(line)
            digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def build_one(
    bank: str,
    reference_name: str,
    policy: str,
    seed: str,
    train_groups: list[Any],
    references: dict[str, list[Any]],
    priority: dict[str, int],
    group_limit: int = 100_000,
) -> tuple[list[Any], dict[str, Any]]:
    import optimize_matched_banks as optimizer

    reference = references[reference_name]
    requested = Counter(optimizer.group_atom(group) for group in reference)
    members: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
    for group in train_groups:
        members[optimizer.group_atom(group)].append(group)

    selected: list[Any] = []
    missing_capacity: list[str] = []
    for atom, count in requested.items():
        candidates = members.get(atom, [])
        if len(candidates) < count:
            missing_capacity.append(f"{atom!r}:{len(candidates)}/{count}")
            continue
        candidates.sort(key=lambda group: (-priority[group.group_id], group.group_id))
        selected.extend(candidates[:count])
    if missing_capacity:
        raise ValueError(f"witness atom capacity unavailable: {missing_capacity[:10]}")
    if len(selected) != group_limit or len({group.group_id for group in selected}) != group_limit:
        raise ValueError(f"candidate cardinality/uniqueness failed for {bank}")

    reference_ids = {group.group_id for group in reference}
    selected_ids = {group.group_id for group in selected}
    identity_objective = sum(priority[group_id] for group_id in reference_ids)
    candidate_objective = sum(priority[group_id] for group_id in selected_ids)
    overlap = len(reference_ids & selected_ids)
    detail = {
        "bank": bank,
        "reference_profile": reference_name,
        "policy": policy,
        "seed": seed,
        "group_count": len(selected),
        "distinct_group_count": len(selected_ids),
        "reference_overlap_count": overlap,
        "reference_overlap_fraction": overlap / len(reference_ids),
        "changed_group_count": len(selected_ids ^ reference_ids),
        "identity_objective": identity_objective,
        "candidate_objective": candidate_objective,
        "objective_delta": candidate_objective - identity_objective,
        "objective_positive_separation": candidate_objective >= identity_objective + 1,
        "atom_count_map_preserved": True,
        "conditional_on_witness_atom_counts": "exact optimum: additive objective maximized independently by choosing highest-ranked group IDs in each atom",
        "global_optimality": "FEASIBLE_NOT_PROVEN",
        "selection_is_nonidentical": selected_ids != reference_ids,
    }
    return selected, detail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\full-universe-500k-v08\group-records.jsonl"))
    parser.add_argument("--r100", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-r100-group-ids.jsonl"))
    parser.add_argument("--c100", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-c100-group-ids.jsonl"))
    parser.add_argument("--eval", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-eval-group-ids.jsonl"))
    parser.add_argument("--phase1-receipt", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\preflight-v03\preflight.json"))
    parser.add_argument("--witness-receipt", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\witness-validation-v02.json"))
    parser.add_argument("--out", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\equivalent-substitution-v01"))
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite candidate output: {args.out}")
    args.out.mkdir(parents=True, exist_ok=False)
    import optimize_matched_banks as optimizer

    contract, contract_path = optimizer.load_contract()
    verification_args = argparse.Namespace(
        group_records=args.groups,
        r100=args.r100,
        c100=args.c100,
        eval=args.eval,
        phase1_receipt=args.phase1_receipt,
    )
    pins = optimizer.verify_pins(verification_args, contract, contract_path)
    source_start = time.perf_counter()
    train_groups, _atoms, _capacities, _profiles, references = optimizer.train_groups_and_profiles(
        args.groups, args.eval, args.r100, args.c100
    )
    source_load_seconds = time.perf_counter() - source_start
    timings: dict[str, float] = {"source_load_and_profile_index_seconds": source_load_seconds}
    construction_start = time.perf_counter()
    bank_specs = (
        ("CM100", "R100", "curated", contract["objective"]["curated_seed"]),
        ("RM100", "C100", "random", contract["objective"]["random_seed"]),
    )
    receipts: dict[str, Any] = {}
    for bank, reference_name, mode, seed in bank_specs:
        rank_start = time.perf_counter()
        priorities = optimizer.priority_ranks(train_groups, mode, seed)
        timings[f"{bank}_priority_ranking_seconds"] = time.perf_counter() - rank_start
        selected, detail = build_one(
            bank, reference_name, mode, seed, train_groups, references, priorities
        )
        manifest = args.out / f"{bank.lower()}-provisional-ids.jsonl"
        detail["provisional_manifest_path"] = str(manifest)
        detail["provisional_manifest_sha256"] = write_manifest(manifest, selected)
        receipts[bank] = detail
    timings["both_atom_preserving_constructions_seconds"] = time.perf_counter() - construction_start

    witness = json.loads(args.witness_receipt.read_text(encoding="utf-8"))
    curated_reference_objectives = witness["phase2_identity_objective_receipts"]["curated"]["selected_priority_sums"]
    random_reference_objectives = witness["phase2_identity_objective_receipts"]["seeded_random_priority"]["selected_priority_sums"]
    curated_upper = witness["phase2_identity_objective_receipts"]["curated"]["cell_relaxed_valid_upper_bounds"]["R100"]
    random_upper = witness["phase2_identity_objective_receipts"]["seeded_random_priority"]["cell_relaxed_valid_upper_bounds"]["C100"]
    for bank, base, upper in (
        ("CM100", curated_reference_objectives["R100"], curated_upper),
        ("RM100", random_reference_objectives["C100"], random_upper),
    ):
        candidate_obj = receipts[bank]["candidate_objective"]
        receipts[bank]["identity_objective_reproduced_from_witness_receipt"] = base
        receipts[bank]["valid_cell_relaxed_upper_bound"] = upper
        receipts[bank]["headroom_recovery"] = (
            (candidate_obj - base) / (upper - base) if upper > base else None
        )
        receipts[bank]["bound_caveat"] = "cell-relaxed upper bound; remaining constraints can make it loose"

    report = {
        "experiment": "jev-information-density-v08c-phase2b-exact-atom-substitution/v1",
        "status": "PROVISIONAL_CANDIDATES_READY_FOR_INDEPENDENT_AUDIT",
        "source_pins": pins,
        "phase2b_contract_sha256": sha256_file(HERE / "v08c-phase2b-contract.json"),
        "witness_receipt_sha256": sha256_file(args.witness_receipt),
        "inputs": {
            "groups_sha256": pins["group_records_sha256"],
            "R100_sha256": pins["r100_manifest_sha256"],
            "C100_sha256": pins["c100_manifest_sha256"],
        },
        "method": {
            "stage": "proven-equivalent substitutions",
            "atom": "model_input_id + root_id + exact_joint_cell + topology_feature_tuple + intervention_family",
            "constraint_incidence_basis": "these are the frozen Phase 2 constraint contributions; all candidate groups within an atom are interchangeable for the declared hard constraints",
            "objective": "additive frozen per-group priority rank",
            "proof_scope": "exact optimum conditional on the identity witness atom-count vector only",
            "not_claimed": ["global optimum", "absence of further atom-level headroom", "material downstream model effect"],
        },
        "timing_seconds": timings,
        "banks": receipts,
        "model_contact": False,
        "phoenix_access": False,
        "training_materialized": False,
    }
    out_path = args.out / "construction-report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "timing_seconds": timings,
        "banks": {name: {key: value for key, value in detail.items() if key in (
            "group_count", "reference_overlap_count", "changed_group_count", "identity_objective",
            "candidate_objective", "objective_delta", "objective_positive_separation", "headroom_recovery",
            "provisional_manifest_sha256",
        )} for name, detail in receipts.items()},
        "report": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

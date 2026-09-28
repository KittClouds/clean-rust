"""Independently validate one provisional Phase 2C cross-atom bank."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V08_DIR = ROOT / "experiments/jev-information-density-v08"
V08B_DIR = ROOT / "experiments/jev-information-density-v08b"
DEFAULT_CONTRACT = HERE / "v08c-phase2c-search-contract.json"
DEFAULT_ROOT = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\cross-atom-search-v01")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import pinned validator dependency {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_freeze(contract_path: Path, receipt_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if contract.get("status") != "frozen_before_candidate_optimization":
        raise ValueError("search contract is not frozen")
    if receipt.get("status") != "SEALED_BEFORE_CROSS_ATOM_SEARCH":
        raise ValueError("search freeze receipt status mismatch")
    if receipt.get("contract_sha256") != sha256_file(contract_path):
        raise ValueError("search contract hash mismatch")
    for relative, expected in receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"frozen source changed: {relative}")
    for name, record in contract["inputs"].items():
        if sha256_file(Path(record["path"])) != record["sha256"]:
            raise ValueError(f"frozen input changed: {name}")
    return contract


def read_ids(path: Path, expected: int = 100_000) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id, episode_id = row.get("group_id"), row.get("episode_id")
            if not isinstance(group_id, str) or not group_id or group_id in result:
                raise ValueError(f"invalid/duplicate group ID at {path}:{line_no}")
            if not isinstance(episode_id, str) or not episode_id:
                raise ValueError(f"missing episode ID at {path}:{line_no}")
            result[group_id] = episode_id
    if len(result) != expected:
        raise ValueError(f"{path} has {len(result)} IDs, expected {expected}")
    return result


def exact_distances(candidate_ids: set[str], reference_ids: set[str], sqlite_path: Path) -> dict[str, Any]:
    sys.path.insert(0, str(HERE))
    import audit_phase2c_training_signatures as sig_audit  # noqa: E402
    import phase2c_training_signatures as sig  # noqa: E402

    connection = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        candidate_rows = sig_audit.bank_rows(connection, {value: "" for value in candidate_ids})
        reference_rows = sig_audit.bank_rows(connection, {value: "" for value in reference_ids})
    finally:
        connection.close()
    candidate_final, candidate_pairs = sig.attach_invariance_context(candidate_rows)
    reference_final, reference_pairs = sig.attach_invariance_context(reference_rows)
    return {
        "supervised_multiset_distance": sig.multiset_distance(
            (row["supervised_signature_sha256"] for row in candidate_rows),
            (row["supervised_signature_sha256"] for row in reference_rows),
        ),
        "exact_training_signature_distance": sig.multiset_distance(candidate_final.values(), reference_final.values()),
        "candidate_selected_pair_count": len(candidate_pairs),
        "reference_selected_pair_count": len(reference_pairs),
        "candidate_training_multiset_sha256": sig.digest(sorted(candidate_final.values())),
        "reference_training_multiset_sha256": sig.digest(sorted(reference_final.values())),
    }


def validate(contract: dict[str, Any], bank: str, candidate_path: Path, output_path: Path) -> dict[str, Any]:
    validator = load_module("phase2c_cross_atom_independent_validator", HERE / "validate_phase2b_candidates.py")
    mode = "random" if bank == "RM100" else "curated"
    seed = contract["search"]["policy_seeds"][bank]
    reference_name = "C100" if bank == "RM100" else "R100"
    reference_path = Path(contract["inputs"]["c100"]["path"] if bank == "RM100" else contract["inputs"]["r100"]["path"])
    candidate = read_ids(candidate_path)
    reference = read_ids(reference_path)
    eval_path = Path(contract["inputs"]["eval"]["path"])
    eval_ids = read_ids(eval_path, 83_328)
    candidate_ids, reference_ids = set(candidate), set(reference)
    if candidate_ids & eval_ids or reference_ids & eval_ids:
        raise ValueError("candidate/reference intersects NewTight-Eval")
    run_report = json.loads(candidate_path.with_name("search-report.json").read_text(encoding="utf-8"))
    if run_report["candidate_manifest"]["sha256"] != sha256_file(candidate_path):
        raise ValueError("search report candidate manifest hash mismatch")
    if run_report["bank"] != bank:
        raise ValueError("candidate run report bank mismatch")

    group_records = Path(contract["inputs"]["group_records"]["path"])
    selected_names: dict[str, set[str]] = {}
    for name, ids in ((bank, candidate_ids), (reference_name, reference_ids)):
        for group_id in ids:
            selected_names.setdefault(group_id, set()).add(name)
    expected_episode = {**reference, **candidate}
    rows_by_bank: dict[str, list[dict[str, Any]]] = {bank: [], reference_name: []}
    feature_counts = [Counter() for _ in validator.COVERAGE_AXES]
    entropies: list[float] = []
    input_gold: dict[str, str] = {}
    found: Counter[str] = Counter()
    valid_count = eligible_count = heldout_count = 0
    raw_hash = hashlib.sha256()
    started = time.perf_counter()

    with group_records.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            raw_hash.update(raw)
            if not raw.strip():
                continue
            row = json.loads(raw)
            if set(row) != validator.GROUP_FIELDS:
                raise ValueError(f"source schema drift at line {line_no}")
            if row["valid"] is not True:
                continue
            valid_count += 1
            group_id = str(row["group_id"])
            bundle = str(row["split_family_bundle_id"])
            if validator.held_out(bundle):
                heldout_count += 1
                if group_id in selected_names:
                    raise ValueError(f"held-out group in training candidate: {group_id}")
                continue
            eligible_count += 1
            input_id, gold_id = validator.parse_input_gold(row["overlap_keys"], group_id)
            if input_gold.setdefault(input_id, gold_id) != gold_id:
                raise ValueError(f"conflicting model-input gold mapping: {input_id}")
            entropy = float(row["posterior_entropy_nats"])
            if entropy < 0:
                raise ValueError(f"negative posterior entropy at line {line_no}")
            entropies.append(entropy)
            features = validator.row_features(row, input_id)
            for axis, values in enumerate(features):
                feature_counts[axis].update(values)
            if group_id not in selected_names:
                continue
            if expected_episode[group_id] != str(row["episode_id"]):
                raise ValueError(f"episode ID mismatch for selected group {group_id}")
            topology = tuple(sorted({
                str(value) for value in row["coverage_features"]["structural_coverage"]
                if str(value).startswith("topology:")
            }))
            selected_for = selected_names[group_id]
            profile_row = {
                "group_id": group_id,
                "input": input_id,
                "root": str(row["root_id"]),
                "bundle": bundle,
                "world": str(row["strata"]["world_family"]),
                "query": str(row["strata"]["query_view_type"]),
                "cardinality": str(row["strata"]["candidate_cardinality_bin"]),
                "entropy": entropy,
                "topology": topology,
                "intervention": str(row["family_ids"]["intervention_family"]),
            }
            for selected in selected_for:
                rows_by_bank[selected].append(profile_row)
                found[selected] += 1

    if raw_hash.hexdigest() != contract["inputs"]["group_records"]["sha256"]:
        raise ValueError("raw group-record file hash mismatch")
    if (valid_count, eligible_count, heldout_count) != (500_000, 416_672, 83_328):
        raise ValueError("raw-source population differs from frozen universe")
    if any(found[name] != 100_000 for name in (bank, reference_name)):
        raise ValueError(f"candidate/reference eligibility incomplete: {dict(found)}")
    entropies.sort()
    thresholds = [entropies[min(len(entropies) - 1, (len(entropies) * q) // 5)] for q in range(1, 5)]
    reference_metrics = validator.profile_comparison(rows_by_bank[bank], rows_by_bank[reference_name], thresholds)
    if not reference_metrics["all_hard_constraints_pass"]:
        raise ValueError("independent full-profile validation failed")

    target_cells = {
        bank: Counter(validator.profile_cell(row, thresholds) for row in rows_by_bank[bank]),
        reference_name: Counter(validator.profile_cell(row, thresholds) for row in rows_by_bank[reference_name]),
    }
    objective = validator.objective_scores(
        group_records,
        target_cells,
        thresholds,
        feature_counts,
        {bank: candidate_ids, reference_name: reference_ids},
        seed,
        mode,
    )
    objective_gain = objective["selected_objective_sums"][bank] - objective["selected_objective_sums"][reference_name]
    reported = run_report["objective"]
    if objective["selected_objective_sums"][bank] != reported["candidate_sum"]:
        raise ValueError("independent candidate objective does not match search report")
    if objective["selected_objective_sums"][reference_name] != reported["reference_sum"]:
        raise ValueError("independent reference objective does not match search report")
    distances = exact_distances(candidate_ids, reference_ids, Path(contract["inputs"]["training_signatures_sqlite"]["path"]))
    accepted = (
        reference_metrics["all_hard_constraints_pass"]
        and objective_gain >= 1
        and distances["exact_training_signature_distance"] >= 0.10
    )
    report = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-independent-candidate-validation",
        "status": "PASS_MODEL_COUNTERFACTUAL_AND_POLICY_SEPARATION" if accepted else "FAIL_OR_WEAK_TREATMENT",
        "bank": bank,
        "reference_bank": reference_name,
        "source_hashes": {
            "group_records": raw_hash.hexdigest(),
            "candidate_manifest": sha256_file(candidate_path),
            "reference_manifest": sha256_file(reference_path),
            "eval_manifest": sha256_file(eval_path),
            "search_report": sha256_file(candidate_path.with_name("search-report.json")),
        },
        "population": {
            "valid": valid_count,
            "eligible_training": eligible_count,
            "held_out": heldout_count,
            "candidate_ids": len(candidate_ids),
            "reference_ids": len(reference_ids),
            "input_gold_conflicts": 0,
            "entropy_thresholds_nats": thresholds,
        },
        "full_profile": reference_metrics,
        "objective": {
            "candidate_sum": objective["selected_objective_sums"][bank],
            "reference_sum": objective["selected_objective_sums"][reference_name],
            "gain_vs_reference": objective_gain,
            "independently_reproduced": True,
            "valid_cell_relaxed_upper_bound": objective["cell_relaxed_valid_upper_bounds"][bank],
        },
        "distance": distances,
        "gate": {
            "profile_pass": reference_metrics["all_hard_constraints_pass"],
            "policy_gain_pass": objective_gain >= 1,
            "exact_training_distance_pass": distances["exact_training_signature_distance"] >= 0.10,
            "authorized_for_model_contact": False,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "candidate_finalized": False,
        "model_contact": False,
        "phoenix_access": False,
        "training_materialized": False,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", choices=("RM100", "CM100"), required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_ROOT / "freeze-receipt.json")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    contract = verify_freeze(args.contract, args.freeze_receipt)
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite candidate-validation report: {args.out}")
    report = validate(contract, args.bank, args.candidate, args.out)
    print(json.dumps({
        "status": report["status"],
        "bank": args.bank,
        "profile_pass": report["gate"]["profile_pass"],
        "objective_gain": report["objective"]["gain_vs_reference"],
        "D_train": report["distance"]["exact_training_signature_distance"],
        "report": str(args.out),
    }, separators=(",", ":")), flush=True)
    return 0 if report["status"] == "PASS_MODEL_COUNTERFACTUAL_AND_POLICY_SEPARATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())

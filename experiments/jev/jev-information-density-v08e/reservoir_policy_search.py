"""Test a common 2x random-witness reservoir for profile-matched curation."""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path
from typing import Any

import build_policy_arms as policy
import state_exposure as v08e

ROOT = v08e.ROOT
SEALED = Path(r"D:\codex-runs\jev-information-density-v08e\sealed-pstar-v01")
REPAIR = Path(r"D:\codex-runs\jev-information-density-v08e\repair-v01")
OUT = Path(r"D:\codex-runs\jev-information-density-v08e\reservoir-policy-v01")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_ids(path: Path) -> list[str]:
    return [json.loads(line)["group_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to reuse reservoir policy directory: {OUT}")
    contract = v08e.require_v03_integrity()
    profile_body = policy.read_json(SEALED / "pstar-profile.json")
    pstar_receipt = policy.read_json(SEALED / "integrity-receipt.json")
    if pstar_receipt.get("status") != "SEALED_PSTAR_PROFILE_AND_CAPACITY_WITNESS" or sha256(SEALED / "pstar-profile.json") != pstar_receipt.get("sealed_profile_sha256"):
        raise ValueError("P* profile failed its sealed hash check")
    anchor_profile = policy.thaw_profile(profile_body["anchor_profile"])
    all_items, by_stratum, quotas, feature_counts, features_by_id = policy.selection_features_and_pool(
        contract, profile_body["stratum_counts"]
    )
    scores = {
        item.group_id: policy.curation_score(features_by_id[item.group_id], feature_counts)
        for item in all_items
    }
    all_by_id = {item.group_id: item for item in all_items}
    a_ids = read_ids(REPAIR / "best-witness-a-ids.jsonl")
    b_ids = read_ids(REPAIR / "best-witness-b-ids.jsonl")
    if len(a_ids) != v08e.TARGET or len(b_ids) != v08e.TARGET or set(a_ids) & set(b_ids):
        raise ValueError("capacity witness manifests are not a disjoint 100k pair")
    random_arm = [all_by_id[group_id] for group_id in a_ids]
    reservoir_ids = set(a_ids) | set(b_ids)
    reservoir_by_stratum: dict[str, list[v08e.core.Item]] = collections.defaultdict(list)
    for group_id in reservoir_ids:
        item = all_by_id[group_id]
        reservoir_by_stratum[item.stratum_id].append(item)
    curated_arm: list[v08e.core.Item] = []
    for stratum, quota in quotas.items():
        reservoir = reservoir_by_stratum[stratum]
        if len(reservoir) != 2 * quota:
            raise ValueError(f"witness reservoir is not exactly 2x quota in {stratum}")
        ranked = sorted(reservoir, key=lambda item: (-scores[item.group_id], policy.digest(policy.CURATED_SEED, item.group_id), item.group_id))
        curated_arm.extend(ranked[:quota])

    OUT.mkdir(parents=True, exist_ok=False)
    r_path, c_path = OUT / "candidate-R100-star-ids.jsonl", OUT / "candidate-C100-star-ids.jsonl"
    r_path.write_text(policy.manifest_text(random_arm), encoding="utf-8", newline="\n")
    c_path.write_text(policy.manifest_text(curated_arm), encoding="utf-8", newline="\n")

    limits = contract["design"]["profile_constraints"]
    tol = {"unique_relative_error_max": limits["unique_input_relative_error_max"],
           "occurrence_histogram_tv_max": limits["input_occurrence_histogram_tv_max"],
           "marginal_tv_max": limits["extra_family_axis_tv_max"]}
    profile_r, profile_c = v08e.core.profile(random_arm), v08e.core.profile(curated_arm)
    check_r = v08e.core.profile_check(anchor_profile, profile_r, tol)
    check_c = v08e.core.profile_check(anchor_profile, profile_c, tol)
    check_pair = v08e.core.profile_check(profile_r, profile_c, tol)
    coverage = [
        v08e.core.full_profile_coverage(all_items, all_items, arm, int(contract["design"]["required_family_category_min_population"]))
        for arm in (random_arm, curated_arm)
    ]
    coverage_pass = all(x["all_core_categories_retained"] and x["family_min_population_categories_retained"] for x in coverage)
    distance = v08e.core.exact_training_distance(random_arm, curated_arm)
    score_r = sum(scores[item.group_id] for item in random_arm) / v08e.TARGET
    score_c = sum(scores[item.group_id] for item in curated_arm) / v08e.TARGET
    overlap = set(a_ids) & {item.group_id for item in curated_arm}
    ready = (
        check_r["all_pass"] and check_c["all_pass"] and check_pair["all_pass"]
        and coverage_pass and distance["exact_training_signature_distance"] >= 0.10
        and score_c > score_r
    )
    result = {
        "status": "POLICY_ARMS_READY_MODEL_CONTACT_NOT_AUTHORIZED" if ready else "RESERVOIR_POLICY_CANDIDATES_NOT_READY",
        "common_candidate_reservoir": {
            "construction": "union of the two disjoint deterministic capacity witnesses from the frozen v0.8D seed-01 hash ranking",
            "group_count": len(reservoir_ids),
            "groups_per_Pstar_stratum": "exactly 2x quota",
            "model_outputs_or_features_used": False,
        },
        "selection_semantics": {
            "R100_star": "witness A, the first quota-sized random-priority half of the shared reservoir",
            "C100_star": "top frozen v0.8 rarity-score groups within each exact P* stratum, selected from that same reservoir",
            "curation_score_scope": "global eligible S* feature frequencies",
            "global_optimality": "not claimed outside the shared reservoir",
        },
        "composition": {
            "R_vs_anchor": check_r,
            "C_vs_anchor": check_c,
            "R_vs_C": check_pair,
            "coverage_pass": coverage_pass,
            "coverage_R": coverage[0],
            "coverage_C": coverage[1],
        },
        "treatment": {
            "D_supervised": distance["supervised_signature_distance"],
            "D_train": distance["exact_training_signature_distance"],
            "D_train_gate": 0.10,
            "group_id_overlap": len(overlap),
            "random_mean_curation_score": score_r,
            "curated_mean_curation_score": score_c,
            "curation_score_delta": score_c - score_r,
            "frozen_policy_objective_improved": score_c > score_r,
            "training_distance": distance,
        },
        "candidate_manifests": {
            "R100_star": {"path": str(r_path), "sha256": sha256(r_path)},
            "C100_star": {"path": str(c_path), "sha256": sha256(c_path)},
        },
        "model_contact": False,
        "feature_extraction": False,
        "training_materialized": False,
        "phoenix_access": False,
    }
    report_path = OUT / "reservoir-policy-validation.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    integrity = {
        "status": result["status"],
        "Pstar_integrity_sha256": sha256(SEALED / "integrity-receipt.json"),
        "policy_source_sha256": sha256(ROOT / "experiments/jev-information-density-v08/select_banks.py"),
        "builder_source_sha256": sha256(Path(__file__)),
        "report_sha256": sha256(report_path),
        "manifest_sha256": {"R100_star": sha256(r_path), "C100_star": sha256(c_path)},
        "model_contact": False,
        "phoenix_access": False,
    }
    (OUT / "integrity-receipt.json").write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "D_train": distance["exact_training_signature_distance"],
                      "R_profile": check_r["all_pass"], "C_profile": check_c["all_pass"],
                      "pair_profile": check_pair["all_pass"], "curation_delta": score_c - score_r,
                      "run_directory": str(OUT)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

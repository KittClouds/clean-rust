"""Probe score-positive A-to-B swaps within the validated witness reservoir."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import build_policy_arms as policy
import state_exposure as v08e

ROOT = v08e.ROOT
SEALED = Path(r"D:\codex-runs\jev-information-density-v08e\sealed-pstar-v01")
REPAIR = Path(r"D:\codex-runs\jev-information-density-v08e\repair-v01")
OUT = Path(r"D:\codex-runs\jev-information-density-v08e\witness-pair-policy-v01")
PROBES = (500, 1_000, 2_000, 4_000, 6_000, 8_000, 10_000, 12_500, 15_000, 20_000, 25_000, 30_000, 40_000)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_ids(path: Path) -> list[str]:
    return [json.loads(line)["group_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_pairs(by_stratum: dict[str, list[v08e.core.Item]], quotas: dict[str, int], scores: dict[str, float], ids_a: set[str], ids_b: set[str]):
    pairs = []
    for stratum, q in quotas.items():
        rows_a = [row for row in by_stratum[stratum] if row.group_id in ids_a]
        rows_b = [row for row in by_stratum[stratum] if row.group_id in ids_b]
        if len(rows_a) != q or len(rows_b) != q:
            raise ValueError(f"witness pair not aligned to frozen quota for {stratum}")
        rows_a.sort(key=lambda row: (scores[row.group_id], row.group_id))
        rows_b.sort(key=lambda row: (-scores[row.group_id], policy.digest(policy.CURATED_SEED, row.group_id), row.group_id))
        for old, new in zip(rows_a, rows_b):
            gain = scores[new.group_id] - scores[old.group_id]
            if gain > 0:
                pairs.append((gain, hashlib.sha256(f"{old.group_id}|{new.group_id}".encode()).hexdigest(), old, new))
    pairs.sort(key=lambda row: (-row[0], row[1]))
    return pairs


def candidate_from_prefix(anchor: list[v08e.core.Item], pairs: list[Any], count: int):
    selected = {row.group_id: row for row in anchor}
    gain = 0.0
    for delta, _tie, old, new in pairs[:count]:
        if old.group_id not in selected or new.group_id in selected:
            raise ValueError("non-disjoint witness-pair swap path")
        del selected[old.group_id]
        selected[new.group_id] = new
        gain += delta
    return list(selected.values()), gain


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to reuse witness-pair policy output: {OUT}")
    contract = v08e.require_v03_integrity()
    profile_path = SEALED / "pstar-profile.json"
    pstar_receipt = policy.read_json(SEALED / "integrity-receipt.json")
    if sha256(profile_path) != pstar_receipt.get("sealed_profile_sha256"):
        raise ValueError("P* profile hash mismatch")
    pstar = policy.read_json(profile_path)
    anchor_profile = policy.thaw_profile(pstar["anchor_profile"])
    all_items, by_stratum, quotas, counts, features = policy.selection_features_and_pool(contract, pstar["stratum_counts"])
    scores = {item.group_id: policy.curation_score(features[item.group_id], counts) for item in all_items}
    by_id = {item.group_id: item for item in all_items}
    ids_a, ids_b = set(read_ids(REPAIR / "best-witness-a-ids.jsonl")), set(read_ids(REPAIR / "best-witness-b-ids.jsonl"))
    if len(ids_a) != v08e.TARGET or len(ids_b) != v08e.TARGET or ids_a & ids_b:
        raise ValueError("invalid sealed capacity witness pair")
    anchor = [by_id[group_id] for group_id in sorted(ids_a)]
    pairs = make_pairs(by_stratum, quotas, scores, ids_a, ids_b)
    if len(pairs) < max(PROBES):
        raise ValueError(f"positive score-exchange count below largest probe: {len(pairs)}")
    OUT.mkdir(parents=True, exist_ok=False)
    limits = contract["design"]["profile_constraints"]
    tol = {"unique_relative_error_max": limits["unique_input_relative_error_max"],
           "occurrence_histogram_tv_max": limits["input_occurrence_histogram_tv_max"],
           "marginal_tv_max": limits["extra_family_axis_tv_max"]}
    family_floor = int(contract["design"]["required_family_category_min_population"])
    results = []
    eligible = []
    for count in PROBES:
        candidate, gain = candidate_from_prefix(anchor, pairs, count)
        comparison = v08e.core.profile_check(anchor_profile, v08e.core.profile(candidate), tol)
        coverage = v08e.core.full_profile_coverage(all_items, all_items, candidate, family_floor)
        coverage_pass = coverage["all_core_categories_retained"] and coverage["family_min_population_categories_retained"]
        row = {"replacement_count": count, "profile_pass": comparison["all_pass"],
               "coverage_pass": coverage_pass, "curation_score_gain_total": gain,
               "state_tv": comparison["state_input"]["occurrence_histogram_tv"],
               "selector_tv": comparison["selector_input"]["occurrence_histogram_tv"],
               "root_tv": comparison["root"]["occurrence_histogram_tv"],
               "selector_unique_relative_error": comparison["selector_input"]["relative_error"],
               "failing_marginals": [axis for axis, value in comparison["marginal_tv"].items() if not value["pass"]]}
        if comparison["all_pass"] and coverage_pass:
            distance = v08e.core.exact_training_distance(anchor, candidate)
            row["D_train"] = distance["exact_training_signature_distance"]
            row["D_supervised"] = distance["supervised_signature_distance"]
            row["training_distance"] = distance
            eligible.append((count, candidate, row, gain))
        results.append(row)
    ready = [entry for entry in eligible if entry[2].get("D_train", 0.0) >= 0.10]
    chosen = max(ready, key=lambda entry: (entry[3], entry[0])) if ready else None
    best = max(eligible, key=lambda entry: (entry[3], entry[0])) if eligible else None
    independent_validation = None
    if chosen:
        c_path = OUT / "candidate-C100-star-ids.jsonl"
        c_path.write_text(policy.manifest_text(chosen[1]), encoding="utf-8", newline="\n")
        r_path = OUT / "candidate-R100-star-ids.jsonl"
        r_path.write_text(policy.manifest_text(anchor), encoding="utf-8", newline="\n")
        ids_r = [item.group_id for item in anchor]
        ids_c = [item.group_id for item in chosen[1]]
        reloaded_r = policy.independent_reload(ids_r)
        reloaded_c = policy.independent_reload(ids_c)
        check_r = v08e.core.profile_check(anchor_profile, v08e.core.profile(reloaded_r), tol)
        check_c = v08e.core.profile_check(anchor_profile, v08e.core.profile(reloaded_c), tol)
        check_pair = v08e.core.profile_check(v08e.core.profile(reloaded_r), v08e.core.profile(reloaded_c), tol)
        coverage = [
            v08e.core.full_profile_coverage(all_items, all_items, arm, family_floor)
            for arm in (reloaded_r, reloaded_c)
        ]
        coverage_pass = all(x["all_core_categories_retained"] and x["family_min_population_categories_retained"] for x in coverage)
        distance = v08e.core.exact_training_distance(reloaded_r, reloaded_c)
        independent_validation = {
            "R_profile_pass": check_r["all_pass"], "C_profile_pass": check_c["all_pass"],
            "pair_profile_pass": check_pair["all_pass"], "coverage_pass": coverage_pass,
            "D_train": distance["exact_training_signature_distance"],
            "selected_rows_reloaded": len(reloaded_r) + len(reloaded_c),
        }
        chosen_ready = (
            check_r["all_pass"] and check_c["all_pass"] and check_pair["all_pass"]
            and coverage_pass and distance["exact_training_signature_distance"] >= 0.10
        )
        arms = {"R100_star": {"path": str(r_path), "sha256": sha256(r_path)},
                "C100_star": {"path": str(c_path), "sha256": sha256(c_path)}}
    else:
        distance, arms, chosen_ready = None, {}, False
    result = {
        "status": "POLICY_ARMS_READY_MODEL_CONTACT_NOT_AUTHORIZED" if chosen_ready else "WITNESS_PAIR_CURATION_NOT_READY",
        "policy_method": "score-positive one-for-one exchanges from anchor A to witness B; all moves remain within exact P* strata",
        "curation_objective": "frozen v0.8 rarity-coverage score using global S* feature frequencies",
        "positive_score_swap_capacity": len(pairs),
        "probes": results,
        "chosen_replacement_count": None if chosen is None else chosen[0],
        "best_profile_valid_probe": None if best is None else best[2],
        "chosen_D_train": None if chosen is None else distance["exact_training_signature_distance"],
        "curation_gain": None if chosen is None else chosen[3],
        "independent_validation": independent_validation,
        "manifests": arms,
        "model_contact": False,
        "phoenix_access": False,
    }
    report = OUT / "witness-pair-policy-report.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    integrity = {"status": result["status"], "Pstar_integrity_sha256": sha256(SEALED / "integrity-receipt.json"),
                 "policy_source_sha256": sha256(ROOT / "experiments/jev-information-density-v08/select_banks.py"),
                 "builder_source_sha256": sha256(Path(__file__)), "report_sha256": sha256(report),
                 "manifests": arms, "model_contact": False, "phoenix_access": False}
    (OUT / "integrity-receipt.json").write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "positive_swaps": len(pairs),
                      "probes_profile_valid": len(eligible), "chosen_replacements": result["chosen_replacement_count"],
                      "D_train": result["chosen_D_train"], "run_directory": str(OUT)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

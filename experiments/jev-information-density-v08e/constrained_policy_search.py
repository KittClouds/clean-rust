"""Bounded score-directed construction of profile-matched P* policy arms."""

from __future__ import annotations

import collections
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import build_policy_arms as policy
import state_exposure as v08e

ROOT = v08e.ROOT
SEALED = Path(r"D:\codex-runs\jev-information-density-v08e\sealed-pstar-v01")
REPAIR = Path(r"D:\codex-runs\jev-information-density-v08e\repair-v01")
OUT = Path(r"D:\codex-runs\jev-information-density-v08e\policy-repair-v01")
DB = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\training-signatures.sqlite")
PROBES = (2_000, 4_000, 6_000, 8_000, 10_000, 12_500, 15_000, 20_000, 25_000, 30_000)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_anchor_ids() -> list[str]:
    path = REPAIR / "best-witness-a-ids.jsonl"
    return [json.loads(line)["group_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_swap_path(
    by_stratum: dict[str, list[v08e.core.Item]],
    quotas: dict[str, int],
    anchor_ids: list[str],
    scores: dict[str, float],
) -> list[tuple[float, str, v08e.core.Item, v08e.core.Item]]:
    selected = set(anchor_ids)
    pairs: list[tuple[float, str, v08e.core.Item, v08e.core.Item]] = []
    for stratum in sorted(quotas):
        rows = by_stratum[stratum]
        in_arm = [item for item in rows if item.group_id in selected]
        alternatives = [item for item in rows if item.group_id not in selected]
        q = quotas[stratum]
        if len(in_arm) != q or len(alternatives) < q:
            raise ValueError(f"stratum support/anchor mismatch while building swap path: {stratum}")
        out_ranked = sorted(
            in_arm,
            key=lambda item: (scores[item.group_id], item.group_id),
        )
        in_ranked = sorted(
            alternatives,
            key=lambda item: (-scores[item.group_id], policy.digest(policy.CURATED_SEED, item.group_id), item.group_id),
        )
        for old, new in zip(out_ranked[:q], in_ranked[:q]):
            gain = scores[new.group_id] - scores[old.group_id]
            if gain <= 0:
                break
            tie = hashlib.sha256(f"jev-v08e-curation-swap-v1|{old.group_id}|{new.group_id}".encode("utf-8")).hexdigest()
            pairs.append((gain, tie, old, new))
    pairs.sort(key=lambda row: (-row[0], row[1]))
    return pairs


def make_candidate(
    anchor_items: list[v08e.core.Item],
    pairs: list[tuple[float, str, v08e.core.Item, v08e.core.Item]],
    count: int,
) -> tuple[list[v08e.core.Item], float]:
    selected = {item.group_id: item for item in anchor_items}
    total_gain = 0.0
    for gain, _tie, old, new in pairs[:count]:
        if old.group_id not in selected or new.group_id in selected:
            raise ValueError("curation swap path is not a disjoint sequence")
        del selected[old.group_id]
        selected[new.group_id] = new
        total_gain += gain
    candidate = sorted(selected.values(), key=lambda item: item.group_id)
    if len(candidate) != v08e.TARGET:
        raise AssertionError("candidate bank size changed during same-stratum swaps")
    return candidate, total_gain


def atomic_manifest(path: Path, items: list[v08e.core.Item]) -> None:
    policy.atomic_write(path, policy.manifest_text(items))


def reload_ids(ids: list[str]) -> list[v08e.core.Item]:
    found: dict[str, v08e.core.Item] = {}
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        for start in range(0, len(ids), 800):
            batch = ids[start : start + 800]
            slots = ",".join("?" for _ in batch)
            query = v08e.SELECT.replace(
                " FROM training_groups WHERE held_out=0 ORDER BY group_id",
                f" FROM training_groups WHERE held_out=0 AND group_id IN ({slots})",
            )
            for row in conn.execute(query, batch):
                item = v08e.core.item_from_row(row)
                found[item.group_id] = item
    finally:
        conn.close()
    if len(found) != len(set(ids)):
        raise ValueError("independent source reload did not recover every selected row")
    return [found[group_id] for group_id in ids]


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to reuse constrained policy search directory: {OUT}")
    contract = v08e.require_v03_integrity()
    pstar_receipt = policy.read_json(SEALED / "integrity-receipt.json")
    profile_path = SEALED / "pstar-profile.json"
    if pstar_receipt.get("status") != "SEALED_PSTAR_PROFILE_AND_CAPACITY_WITNESS" or sha256(profile_path) != pstar_receipt.get("sealed_profile_sha256"):
        raise ValueError("sealed P* identity did not verify")
    profile_body = policy.read_json(profile_path)
    anchor_profile = policy.thaw_profile(profile_body["anchor_profile"])
    all_items, by_stratum, quotas, feature_counts, features_by_id = policy.selection_features_and_pool(
        contract, profile_body["stratum_counts"]
    )
    scores = {
        item.group_id: policy.curation_score(features_by_id[item.group_id], feature_counts)
        for item in all_items
    }
    anchor_ids = load_anchor_ids()
    if len(anchor_ids) != v08e.TARGET or len(set(anchor_ids)) != v08e.TARGET:
        raise ValueError("P* random-priority anchor manifest is malformed")
    by_id = {item.group_id: item for item in all_items}
    anchor = [by_id[group_id] for group_id in anchor_ids]
    if v08e.core.profile(anchor)["strata"] != anchor_profile["strata"]:
        raise ValueError("anchor manifest no longer matches sealed P* stratum profile")
    swaps = build_swap_path(by_stratum, quotas, anchor_ids, scores)
    if len(swaps) < PROBES[-1]:
        raise ValueError(f"insufficient positive curation swap headroom: {len(swaps)}")

    OUT.mkdir(parents=True, exist_ok=False)
    limits = contract["design"]["profile_constraints"]
    tolerances = {
        "unique_relative_error_max": limits["unique_input_relative_error_max"],
        "occurrence_histogram_tv_max": limits["input_occurrence_histogram_tv_max"],
        "marginal_tv_max": limits["extra_family_axis_tv_max"],
    }
    family_floor = int(contract["design"]["required_family_category_min_population"])
    probe_results: list[dict[str, Any]] = []
    passing: list[tuple[int, list[v08e.core.Item], dict[str, Any], float]] = []
    for count in PROBES:
        candidate, gain = make_candidate(anchor, swaps, count)
        profile = v08e.core.profile(candidate)
        comparison = v08e.core.profile_check(anchor_profile, profile, tolerances)
        coverage = v08e.core.full_profile_coverage(all_items, all_items, candidate, family_floor)
        coverage_pass = coverage["all_core_categories_retained"] and coverage["family_min_population_categories_retained"]
        record = {
            "replacement_count": count,
            "replacement_fraction": count / v08e.TARGET,
            "curation_score_gain_total": gain,
            "curation_score_gain_per_group": gain / v08e.TARGET,
            "profile_pass": comparison["all_pass"],
            "coverage_pass": coverage_pass,
            "state_tv": comparison["state_input"]["occurrence_histogram_tv"],
            "selector_tv": comparison["selector_input"]["occurrence_histogram_tv"],
            "root_tv": comparison["root"]["occurrence_histogram_tv"],
            "state_unique_relative_error": comparison["state_input"]["relative_error"],
            "selector_unique_relative_error": comparison["selector_input"]["relative_error"],
            "root_unique_relative_error": comparison["root"]["relative_error"],
            "failing_marginals": [name for name, value in comparison["marginal_tv"].items() if not value["pass"]],
        }
        if comparison["all_pass"] and coverage_pass:
            distance = v08e.core.exact_training_distance(anchor, candidate)
            record["D_train"] = distance["exact_training_signature_distance"]
            record["D_supervised"] = distance["supervised_signature_distance"]
            record["training_distance"] = distance
            passing.append((count, candidate, record, gain))
        probe_results.append(record)

    # The arm must clear treatment strength as well as composition. Select the
    # largest objective gain among points satisfying both frozen requirements.
    treatment_ready = [row for row in passing if row[2].get("D_train", 0.0) >= 0.10]
    chosen = max(treatment_ready, key=lambda row: (row[3], row[0])) if treatment_ready else None
    best_profile_only = max(passing, key=lambda row: (row[3], row[0])) if passing else None
    chosen_count = None if chosen is None else chosen[0]
    if chosen is not None:
        candidate_c = chosen[1]
        r_manifest = OUT / "R100-star-ids.jsonl"
        c_manifest = OUT / "C100-star-ids.jsonl"
        atomic_manifest(r_manifest, anchor)
        atomic_manifest(c_manifest, candidate_c)
        ids_r = [item.group_id for item in anchor]
        ids_c = [item.group_id for item in candidate_c]
        reloaded_r, reloaded_c = reload_ids(ids_r), reload_ids(ids_c)
        check_r = v08e.core.profile_check(anchor_profile, v08e.core.profile(reloaded_r), tolerances)
        check_c = v08e.core.profile_check(anchor_profile, v08e.core.profile(reloaded_c), tolerances)
        check_pair = v08e.core.profile_check(v08e.core.profile(reloaded_r), v08e.core.profile(reloaded_c), tolerances)
        distance = v08e.core.exact_training_distance(reloaded_r, reloaded_c)
        r_cov = v08e.core.full_profile_coverage(all_items, all_items, reloaded_r, family_floor)
        c_cov = v08e.core.full_profile_coverage(all_items, all_items, reloaded_c, family_floor)
        coverage_pass = all(x["all_core_categories_retained"] and x["family_min_population_categories_retained"] for x in (r_cov, c_cov))
        held = {
            str(json.loads(line)["group_id"])
            for line in Path(contract["inputs"]["heldout_manifest"]["path"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        eval_intersection = (set(ids_r) | set(ids_c)) & held
        ready = (
            check_r["all_pass"] and check_c["all_pass"] and check_pair["all_pass"]
            and coverage_pass and not eval_intersection
            and distance["exact_training_signature_distance"] >= 0.10
            and chosen[3] > 0
        )
        independent = {
            "R_profile_pass": check_r["all_pass"], "C_profile_pass": check_c["all_pass"],
            "pair_profile_pass": check_pair["all_pass"], "coverage_pass": coverage_pass,
            "heldout_intersection_count": len(eval_intersection),
            "D_train": distance["exact_training_signature_distance"],
        }
        bank_paths = {"R100_star": {"path": str(r_manifest), "sha256": sha256(r_manifest)},
                      "C100_star": {"path": str(c_manifest), "sha256": sha256(c_manifest)}}
    else:
        ready = False
        independent = None
        distance = None
        bank_paths = {}

    result = {
        "status": "POLICY_ARMS_READY_MODEL_CONTACT_NOT_AUTHORIZED" if ready else "CONSTRAINED_CURATION_NOT_READY",
        "selection_semantics": {
            "random_arm": "P* anchor A; deterministic hash-priority witness selected by the frozen v0.8D 32-seed profile-witness search, no model outcomes used",
            "curated_arm": "starting from random anchor; replace same-stratum groups along descending frozen v0.8 rarity-score gains",
            "curation_objective": "unchanged equal-weight mean of five global rarity axes; feature frequencies use all eligible S* groups",
            "profile_constraints": "each arm matches the sealed P* anchor; exact strata plus all frozen tolerances",
            "global_optimality": "not claimed; bounded score-directed swap path",
        },
        "positive_swap_headroom": len(swaps),
        "probe_replacement_counts": list(PROBES),
        "probe_results": probe_results,
        "chosen_replacement_count": chosen_count,
        "chosen_curation_score_gain_total": None if chosen is None else chosen[3],
        "chosen_D_train": None if chosen is None else chosen[2].get("D_train"),
        "best_profile_valid_probe": None if best_profile_only is None else best_profile_only[2],
        "independent_validation": independent,
        "candidate_manifests": bank_paths,
        "model_contact": False,
        "feature_extraction": False,
        "training_materialized": False,
        "phoenix_access": False,
    }
    result_path = OUT / "constrained-policy-search.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    integrity = {
        "status": result["status"],
        "sealed_pstar_integrity_sha256": sha256(SEALED / "integrity-receipt.json"),
        "policy_source_sha256": sha256(ROOT / "experiments/jev-information-density-v08/select_banks.py"),
        "builder_source_sha256": sha256(Path(__file__)),
        "result_sha256": sha256(result_path),
        "manifests": bank_paths,
        "model_contact": False,
        "phoenix_access": False,
    }
    (OUT / "integrity-receipt.json").write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "probes": len(probe_results),
                      "chosen_replacements": chosen_count,
                      "D_train": result["chosen_D_train"],
                      "run_directory": str(OUT)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

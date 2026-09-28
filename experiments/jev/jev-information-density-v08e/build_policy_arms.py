"""Construct metadata-only constrained-random and curated P* policy arms."""

from __future__ import annotations

import collections
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

import state_exposure as v08e

ROOT = v08e.ROOT
SEALED = Path(r"D:\codex-runs\jev-information-density-v08e\sealed-pstar-v01")
OUT = Path(r"D:\codex-runs\jev-information-density-v08e\policy-arms-v01")
DB = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\training-signatures.sqlite")
RANDOM_SEED = "jev-idv08-r100-sha256-v1"
CURATED_SEED = "jev-idv08-c100-sha256-v3-static-frequency-coverage"
AXES = ("semantic_novelty", "local_discrimination", "probability_geometry", "structural_coverage", "redundancy")
SELECT_WITH_FEATURES = v08e.SELECT.replace(
    " perturbation_class\n FROM training_groups", " perturbation_class, coverage_features_json\n FROM training_groups"
)


def digest(seed: str, value: str) -> bytes:
    return hashlib.sha256(f"{seed}|{value}".encode("utf-8")).digest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def thaw_profile(body: dict[str, Any]) -> dict[str, Any]:
    """Restore JSON-serialized profile counters for the frozen checker."""
    counter_keys = (
        "strata", "state_input_counts", "selector_input_counts", "root_counts",
        "topology_counts", "intervention_counts", "kind_counts", "view_counts",
        "candidate_count_counts", "open_world_counts", "probability_source_counts",
    )
    result = dict(body)
    for key in counter_keys:
        result[key] = collections.Counter({str(k): int(v) for k, v in body[key].items()})
    result["family_counts"] = {
        axis: collections.Counter({str(k): int(v) for k, v in counts.items()})
        for axis, counts in body["family_counts"].items()
    }
    return result


def features_for(item: v08e.core.Item, coverage_raw: str) -> tuple[tuple[str, ...], ...]:
    coverage = json.loads(coverage_raw)
    features = [set(str(value) for value in coverage[axis]) for axis in AXES]
    features[-1].add(f"input:{item.input_selector}")
    if any(not values for values in features):
        raise ValueError(f"frozen curation feature axis empty for {item.group_id}")
    return tuple(tuple(sorted(values)) for values in features)


def curation_score(features: tuple[tuple[str, ...], ...], counts: list[collections.Counter[str]]) -> float:
    per_axis = [
        sum(1.0 / math.sqrt(counts[i][feature]) for feature in values) / len(values)
        for i, values in enumerate(features)
    ]
    return sum(per_axis) / len(per_axis)


def selection_features_and_pool(contract: dict[str, Any], quotas: list[dict[str, Any]]) -> tuple[
    list[v08e.core.Item], dict[str, list[v08e.core.Item]], dict[str, int], list[collections.Counter[str]], dict[str, tuple[tuple[str, ...], ...]]
]:
    quota_by_stratum = {v08e.core.canonical_json(row["stratum"]): int(row["quota"]) for row in quotas}
    capacity_by_stratum = {v08e.core.canonical_json(row["stratum"]): int(row["capacity"]) for row in quotas}
    all_items: list[v08e.core.Item] = []
    by_stratum: dict[str, list[v08e.core.Item]] = collections.defaultdict(list)
    features_by_id: dict[str, tuple[tuple[str, ...], ...]] = {}
    feature_counts = [collections.Counter() for _ in AXES]
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        for row in conn.execute(SELECT_WITH_FEATURES):
            item = v08e.core.item_from_row(row[:21])
            if item.stratum_id not in quota_by_stratum:
                continue
            features = features_for(item, str(row[21]))
            features_by_id[item.group_id] = features
            for i, values in enumerate(features):
                feature_counts[i].update(values)
            all_items.append(item)
            by_stratum[item.stratum_id].append(item)
    finally:
        conn.close()
    if len(all_items) != 416_672:
        raise ValueError(f"eligible P* support size changed: {len(all_items)}")
    if set(by_stratum) != set(quota_by_stratum):
        raise ValueError("P* stratum support differs from frozen quota table")
    for key, capacity in capacity_by_stratum.items():
        if len(by_stratum[key]) != capacity or capacity < 4 * quota_by_stratum[key]:
            raise ValueError(f"P* source capacity mismatch for stratum {key}")
    return all_items, by_stratum, quota_by_stratum, feature_counts, features_by_id


def select_arms(
    by_stratum: dict[str, list[v08e.core.Item]],
    quota: dict[str, int],
    feature_counts: list[collections.Counter[str]],
    features_by_id: dict[str, tuple[tuple[str, ...], ...]],
) -> tuple[list[v08e.core.Item], list[v08e.core.Item], dict[str, float]]:
    random_arm: list[v08e.core.Item] = []
    curated_arm: list[v08e.core.Item] = []
    scores = {
        item.group_id: curation_score(features_by_id[item.group_id], feature_counts)
        for rows in by_stratum.values() for item in rows
    }
    for stratum in sorted(quota):
        rows = by_stratum[stratum]
        q = quota[stratum]
        random_ranked = sorted(rows, key=lambda x: (digest(RANDOM_SEED, x.group_id), x.group_id))
        curated_ranked = sorted(
            rows,
            key=lambda x: (
                -scores[x.group_id],
                digest(CURATED_SEED, x.group_id),
                x.group_id,
            ),
        )
        random_arm.extend(random_ranked[:q])
        curated_arm.extend(curated_ranked[:q])
    return random_arm, curated_arm, scores


def manifest_text(items: list[v08e.core.Item]) -> str:
    return "".join(
        json.dumps({"group_id": item.group_id, "episode_id": item.episode_id}, separators=(",", ":")) + "\n"
        for item in sorted(items, key=lambda x: x.group_id)
    )


def independent_reload(ids: list[str]) -> list[v08e.core.Item]:
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
        raise ValueError("independent policy-arm source lookup mismatch")
    return [found[group_id] for group_id in ids]


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to reuse policy-arm output directory: {OUT}")
    contract = v08e.require_v03_integrity()
    sealed_receipt = read_json(SEALED / "integrity-receipt.json")
    profile_path = SEALED / "pstar-profile.json"
    if sealed_receipt.get("status") != "SEALED_PSTAR_PROFILE_AND_CAPACITY_WITNESS":
        raise ValueError("P* profile is not sealed")
    if sha256(profile_path) != sealed_receipt.get("sealed_profile_sha256"):
        raise ValueError("sealed P* profile hash mismatch")
    profile_body = read_json(profile_path)
    if profile_body.get("status") != "PSTAR_PROFILE_FROZEN":
        raise ValueError("P* profile status mismatch")
    anchor = thaw_profile(profile_body["anchor_profile"])
    all_items, by_stratum, quota, feature_counts, features_by_id = selection_features_and_pool(contract, profile_body["stratum_counts"])
    random_arm, curated_arm, scores = select_arms(by_stratum, quota, feature_counts, features_by_id)
    if len(random_arm) != v08e.TARGET or len(curated_arm) != v08e.TARGET:
        raise ValueError("policy arm size mismatch")

    OUT.mkdir(parents=True, exist_ok=False)
    r_path, c_path = OUT / "candidate-R100-star-ids.jsonl", OUT / "candidate-C100-star-ids.jsonl"
    r_path.write_text(manifest_text(random_arm), encoding="utf-8", newline="\n")
    c_path.write_text(manifest_text(curated_arm), encoding="utf-8", newline="\n")

    limits = contract["design"]["profile_constraints"]
    tol = {
        "unique_relative_error_max": limits["unique_input_relative_error_max"],
        "occurrence_histogram_tv_max": limits["input_occurrence_histogram_tv_max"],
        "marginal_tv_max": limits["extra_family_axis_tv_max"],
    }
    profile_r, profile_c = v08e.core.profile(random_arm), v08e.core.profile(curated_arm)
    check_r = v08e.core.profile_check(anchor, profile_r, tol)
    check_c = v08e.core.profile_check(anchor, profile_c, tol)
    check_pair = v08e.core.profile_check(profile_r, profile_c, tol)
    coverage = [
        v08e.core.full_profile_coverage(all_items, all_items, arm, int(contract["design"]["required_family_category_min_population"]))
        for arm in (random_arm, curated_arm)
    ]
    coverage_pass = all(x["all_core_categories_retained"] and x["family_min_population_categories_retained"] for x in coverage)
    ids_r, ids_c = [x.group_id for x in random_arm], [x.group_id for x in curated_arm]
    overlap_ids = set(ids_r) & set(ids_c)
    overlap_inputs = {x.input_selector for x in random_arm} & {x.input_selector for x in curated_arm}
    distance = v08e.core.exact_training_distance(random_arm, curated_arm)
    score_r = sum(scores[x.group_id] for x in random_arm) / len(random_arm)
    score_c = sum(scores[x.group_id] for x in curated_arm) / len(curated_arm)

    # Rebuild selected rows from source SQLite before assigning a promotable status.
    independent_r = independent_reload(ids_r)
    independent_c = independent_reload(ids_c)
    recheck_r = v08e.core.profile_check(anchor, v08e.core.profile(independent_r), tol)
    recheck_c = v08e.core.profile_check(anchor, v08e.core.profile(independent_c), tol)
    recheck_pair = v08e.core.profile_check(v08e.core.profile(independent_r), v08e.core.profile(independent_c), tol)
    independent_distance = v08e.core.exact_training_distance(independent_r, independent_c)
    ids_held = {
        str(json.loads(line)["group_id"])
        for line in Path(contract["inputs"]["heldout_manifest"]["path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    eval_overlap = (set(ids_r) | set(ids_c)) & ids_held
    gate = (
        recheck_r["all_pass"] and recheck_c["all_pass"] and recheck_pair["all_pass"]
        and coverage_pass and not eval_overlap
        and independent_distance["exact_training_signature_distance"] >= 0.10
        and score_c > score_r
    )
    result = {
        "status": "POLICY_ARMS_READY_MODEL_CONTACT_NOT_AUTHORIZED" if gate else "POLICY_ARM_CANDIDATES_NOT_READY",
        "Pstar_profile_sha256": sha256(profile_path),
        "selector_semantics": {
            "random": "frozen v0.8 random SHA priority restricted to exact P* stratum quotas",
            "curated": "frozen v0.8 global rarity-weighted equal-axis score restricted to exact P* stratum quotas",
            "curated_feature_counts_scope": "all 416672 eligible S* groups; metadata only",
            "objective_was_changed": False,
        },
        "bank_counts": {"R100_star": len(random_arm), "C100_star": len(curated_arm)},
        "composition_checks": {
            "R_vs_Pstar_anchor": check_r,
            "C_vs_Pstar_anchor": check_c,
            "R_vs_C": check_pair,
            "coverage_pass": coverage_pass,
            "coverage_R": coverage[0],
            "coverage_C": coverage[1],
            "stratum_counts_exact_R": profile_r["strata"] == anchor["strata"],
            "stratum_counts_exact_C": profile_c["strata"] == anchor["strata"],
        },
        "treatment": {
            "D_supervised": independent_distance["supervised_signature_distance"],
            "D_train": independent_distance["exact_training_signature_distance"],
            "D_train_gate": 0.10,
            "group_id_overlap": len(overlap_ids),
            "unique_selector_input_intersection": len(overlap_inputs),
            "unique_selector_input_union": len({x.input_selector for x in random_arm} | {x.input_selector for x in curated_arm}),
            "random_mean_curation_score": score_r,
            "curated_mean_curation_score": score_c,
            "curation_score_delta": score_c - score_r,
            "frozen_policy_objective_improved": score_c > score_r,
        },
        "independent_revalidation": {
            "R_profile_pass": recheck_r["all_pass"],
            "C_profile_pass": recheck_c["all_pass"],
            "pair_profile_pass": recheck_pair["all_pass"],
            "D_train": independent_distance["exact_training_signature_distance"],
            "heldout_intersection_count": len(eval_overlap),
            "coverage_pass": coverage_pass,
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
    report_path = OUT / "policy-arm-validation.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    integrity = {
        "status": result["status"],
        "Pstar_integrity_receipt_sha256": sha256(SEALED / "integrity-receipt.json"),
        "selection_source_sha256": sha256(ROOT / "experiments/jev-information-density-v08/select_banks.py"),
        "builder_source_sha256": sha256(Path(__file__)),
        "report_sha256": sha256(report_path),
        "manifest_sha256": {"R100_star": sha256(r_path), "C100_star": sha256(c_path)},
        "model_contact": False,
        "phoenix_access": False,
    }
    (OUT / "integrity-receipt.json").write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "D_train": result["treatment"]["D_train"],
                      "R_profile": check_r["all_pass"], "C_profile": check_c["all_pass"],
                      "pair_profile": check_pair["all_pass"], "curation_delta": score_c - score_r,
                      "run_directory": str(OUT)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

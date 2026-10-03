"""Independently seal the repaired P* profile and capacity witness."""

from __future__ import annotations

import collections
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import state_exposure as v08e

ROOT = v08e.ROOT
RUN = Path(r"D:\codex-runs\jev-information-density-v08e\repair-v01")
OUT = Path(r"D:\codex-runs\jev-information-density-v08e\sealed-pstar-v01")
DB = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\training-signatures.sqlite")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_manifest(path: Path) -> list[dict[str, str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_selected(ids: list[str]) -> list[v08e.core.Item]:
    result: dict[str, v08e.core.Item] = {}
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
                result[item.group_id] = item
    finally:
        conn.close()
    if len(result) != len(set(ids)):
        raise ValueError(f"source lookup mismatch: requested={len(set(ids))} found={len(result)}")
    return [result[group_id] for group_id in ids]


def jsonable_profile(profile: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in profile.items():
        if isinstance(value, collections.Counter):
            result[key] = {str(k): value[k] for k in sorted(value, key=str)}
        elif isinstance(value, dict):
            result[key] = {
                axis: ({str(k): count for k, count in sorted(counter.items(), key=lambda row: str(row[0]))}
                       if isinstance(counter, collections.Counter) else counter)
                for axis, counter in value.items()
            }
        else:
            result[key] = value
    return result


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to reuse sealed P* directory: {OUT}")
    contract = v08e.require_v03_integrity()
    repair = json.loads((RUN / "repair-result.json").read_text(encoding="utf-8"))
    if repair.get("status") != "PSTAR_PROFILE_VALIDATED":
        raise ValueError("repair result is not an independently validated P* profile")
    validation = repair.get("independent_validation", {})
    if validation.get("status") != "PASS" or validation.get("D_train", 0.0) < 0.20:
        raise ValueError("profile/capacity witness does not pass its frozen promotion condition")

    source_receipt = v08e.core.read_json(v08e.V03_RUN / "integrity-receipt.json")
    pstar_source_path = v08e.V03_RUN / "pstar-profile.json"
    expected_pstar_hash = source_receipt["outputs"]["pstar_profile_sha256"]
    if sha256(pstar_source_path) != expected_pstar_hash:
        raise ValueError("sealed v0.8D quota profile hash mismatch")
    source_pstar = json.loads(pstar_source_path.read_text(encoding="utf-8"))
    quotas = source_pstar["stratum_counts"]
    if sum(int(row["quota"]) for row in quotas) != v08e.TARGET:
        raise ValueError("v0.8D quota table does not total the frozen 100k target")

    manifest_a = read_manifest(RUN / "best-witness-a-ids.jsonl")
    manifest_b = read_manifest(RUN / "best-witness-b-ids.jsonl")
    if len(manifest_a) != v08e.TARGET or len(manifest_b) != v08e.TARGET:
        raise ValueError("repaired witness manifest count mismatch")
    ids_a = [row["group_id"] for row in manifest_a]
    ids_b = [row["group_id"] for row in manifest_b]
    if set(ids_a) & set(ids_b):
        raise ValueError("repaired witness manifests overlap")
    items_a, items_b = load_selected(ids_a), load_selected(ids_b)
    profile_a, profile_b = v08e.core.profile(items_a), v08e.core.profile(items_b)
    limits = contract["design"]["profile_constraints"]
    comparison = v08e.core.profile_check(profile_a, profile_b, {
        "unique_relative_error_max": limits["unique_input_relative_error_max"],
        "occurrence_histogram_tv_max": limits["input_occurrence_histogram_tv_max"],
        "marginal_tv_max": limits["extra_family_axis_tv_max"],
    })
    if not comparison["all_pass"]:
        raise ValueError("final source-row profile reconstruction failed")
    independent_distance = v08e.core.exact_training_distance(items_a, items_b)
    if not (independent_distance["exact_training_signature_distance"] >= 0.20):
        raise ValueError("recomputed D_train fell below the frozen capacity target")
    if independent_distance["exact_training_multiset_sha256" if "exact_training_multiset_sha256" in independent_distance else "left_training_multiset_sha256"] != validation["training_distance"]["left_training_multiset_sha256"]:
        raise ValueError("training-signature digest differs from independent v0.8E validation")

    OUT.mkdir(parents=True, exist_ok=False)
    anchor = jsonable_profile(profile_a)
    profile_body = {
        "protocol": "jev-decision-data-information-density/v0.8e-state-exposure",
        "status": "PSTAR_PROFILE_FROZEN",
        "group_count_per_arm": v08e.TARGET,
        "support_group_count": 416_672,
        "support_stratum_count": len(quotas),
        "quota_rule": source_pstar["quota_rule"],
        "stratum_counts": quotas,
        "profile_limits": limits,
        "profile_matching_semantics": "two policy arms must each match this anchor profile under the listed frozen per-axis TV/unique-count limits; exact stratum counts are mandatory",
        "anchor_witness_seed": v08e.SEED,
        "anchor_arm": "A",
        "anchor_profile": anchor,
        "anchor_profile_sha256": hashlib.sha256(json.dumps(anchor, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "witness_pair_profile_comparison": comparison,
        "D_train_capacity_witness": independent_distance,
        "new_tight_eval_excluded": True,
        "model_contact": False,
        "phoenix_access": False,
    }
    profile_path = OUT / "pstar-profile.json"
    profile_path.write_text(json.dumps(profile_body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source_paths = [
        ROOT / "docs/jev-information-density-v0.8e-state-exposure.md",
        ROOT / "experiments/jev-information-density-v08e/state_exposure.py",
        ROOT / "experiments/jev-information-density-v08e/seal_pstar.py",
        ROOT / "experiments/jev-information-density-v08e/tests/test_state_exposure.py",
    ]
    integrity = {
        "protocol": "jev-decision-data-information-density/v0.8e-state-exposure",
        "status": "SEALED_PSTAR_PROFILE_AND_CAPACITY_WITNESS",
        "upstream_v08d_integrity_sha256": sha256(v08e.V03_RUN / "integrity-receipt.json"),
        "upstream_v08d_contract_sha256": v08e.core.sha256_file(v08e.V08D_DIR / "v08d-contract.json"),
        "upstream_inputs_sha256": {name: item["sha256"] for name, item in contract["inputs"].items()},
        "implementation_sources": {str(path.relative_to(ROOT)): sha256(path) for path in source_paths},
        "repair_result_sha256": sha256(RUN / "repair-result.json"),
        "repair_manifest_sha256": {
            "A": sha256(RUN / "best-witness-a-ids.jsonl"),
            "B": sha256(RUN / "best-witness-b-ids.jsonl"),
        },
        "sealed_profile_sha256": sha256(profile_path),
        "result": {
            "state_occurrence_histogram_tv": comparison["state_input"]["occurrence_histogram_tv"],
            "selector_occurrence_histogram_tv": comparison["selector_input"]["occurrence_histogram_tv"],
            "root_occurrence_histogram_tv": comparison["root"]["occurrence_histogram_tv"],
            "D_train": independent_distance["exact_training_signature_distance"],
            "profile_pass": comparison["all_pass"],
        },
        "authorization": {
            "metadata_only": True,
            "model_contact": False,
            "feature_extraction": False,
            "training_materialized": False,
            "phoenix_access": False,
            "policy_arms_constructed": False,
        },
    }
    integrity_path = OUT / "integrity-receipt.json"
    integrity_path.write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": integrity["status"], "state_tv": integrity["result"]["state_occurrence_histogram_tv"],
                      "D_train": integrity["result"]["D_train"], "profile": str(profile_path),
                      "integrity": str(integrity_path)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

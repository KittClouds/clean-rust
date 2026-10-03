"""Read-only v0.8G provenance/profile preflight; never loads the LFM model."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\codex-runs\jev-information-density-v08g")
PYTHON = Path(r"D:\codex-runs\jev-python-v06\Scripts\python.exe")
V08C = ROOT / "experiments" / "jev-information-density-v08c"
V08D = ROOT / "experiments" / "jev-information-density-v08d"
V08E = ROOT / "experiments" / "jev-information-density-v08e"
V07 = ROOT / "experiments" / "jev-lfm-variable-v07"
V05 = ROOT / "experiments" / "jev-frozen-scaling-v05"
PROBE = ROOT / "experiments" / "jev-frozen-readout-v01" / "probe.py"

PSTAR_DIR = Path(r"D:\codex-runs\jev-information-density-v08e\sealed-pstar-v01")
ARMS_DIR = Path(r"D:\codex-runs\jev-information-density-v08e\policy-mobility-v06-balanced-cycles-v04")
PHASE2C_DIR = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01")
V08_RUN = Path(r"D:\codex-runs\jev-information-density-v08")
V07_RUN = Path(r"D:\codex-runs\jev-lfm-variable-v07")
CANONICAL = V08_RUN / "full-universe-500k-v08" / "new-universe-canonical.jsonl"
GROUP_RECORDS = V08_RUN / "full-universe-500k-v08" / "group-records.jsonl"
EVAL_MANIFEST = V08_RUN / "selection-v08-c100v12" / "new-tight-eval-group-ids.jsonl"
DB = PHASE2C_DIR / "training-signatures.sqlite"

EXPECTED = {
    "Pstar": "6da6f11ae447634ee06abc2228e15cfc16a541c46761faa4308f167f9a9fb40d",
    "C100_star": "571104b6091a81bc714dfeaf52b59ead35d28e0b8a116c6f633e824fb356f4f0",
    "R100_star": "850cb2805aa5e677d8d89792a3ea716e1aa3a007bcb1f0a87dedbbeb77e9429c",
    "NewTight_Eval": "3e72cd7596fbf0b302501b88dd9dc645a5749de10884b57eceb5552bfc5ef8ae",
    "v07_contract": "9b831ae49e2be227141e5145e12593101c59ebad3bc2b9944666ec710060ab79",
    "LFM_revision": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} hash mismatch: {actual} != {expected} ({path})")
    return actual


def verify_recorded_files(value: Any, base: Path, receipts: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            path = Path(value["path"])
            if not path.is_absolute():
                path = base / path
            actual = require_hash(path, value["sha256"], "lineage input")
            receipts.append({"path": str(path), "sha256": actual})
            return
        for child in value.values():
            verify_recorded_files(child, base, receipts)
    elif isinstance(value, list):
        for child in value:
            verify_recorded_files(child, base, receipts)


def verify_source_map(source_map: dict[str, str], receipts: list[dict[str, str]]) -> None:
    for relative, expected in sorted(source_map.items()):
        path = ROOT / relative
        actual = require_hash(path, expected, "frozen source")
        receipts.append({"path": str(path), "sha256": actual})


def read_id_manifest(path: Path, expected_count: int) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id, episode_id = row.get("group_id"), row.get("episode_id")
            if not isinstance(group_id, str) or not group_id or group_id in result:
                raise ValueError(f"invalid or duplicate group ID at {path}:{line_number}")
            if not isinstance(episode_id, str) or not episode_id:
                raise ValueError(f"missing episode ID at {path}:{line_number}")
            result[group_id] = episode_id
    if len(result) != expected_count:
        raise ValueError(f"{path} contains {len(result)} unique IDs; expected {expected_count}")
    return result


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen validator source {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_ids_in_database(banks: dict[str, dict[str, str]]) -> None:
    uri = f"file:{DB.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        for bank_name, ids in banks.items():
            expected = ids
            rows_seen = 0
            ordered = sorted(expected.items())
            for start in range(0, len(ordered), 700):
                chunk = ordered[start : start + 700]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    "SELECT group_id, episode_id, held_out FROM training_groups "
                    f"WHERE group_id IN ({placeholders})",
                    [group_id for group_id, _episode_id in chunk],
                )
                found = {row[0]: (row[1], int(row[2])) for row in rows}
                if len(found) != len(chunk):
                    raise ValueError(f"{bank_name}: signature index missing selected IDs")
                for group_id, episode_id in chunk:
                    actual_episode, held_out = found[group_id]
                    if actual_episode != episode_id:
                        raise ValueError(f"{bank_name}: episode mismatch for {group_id}")
                    if bank_name in {"R100-star", "C100-star"} and held_out:
                        raise ValueError(f"{bank_name}: training ID marked held_out: {group_id}")
                rows_seen += len(found)
            if rows_seen != len(expected):
                raise ValueError(f"{bank_name}: database row count mismatch")
    finally:
        connection.close()


def recompute_profile_and_distance(
    random_ids: dict[str, str], curated_ids: dict[str, str], pstar: dict[str, Any]
) -> dict[str, Any]:
    sys.path.insert(0, str(V08D))
    sys.path.insert(0, str(V08E))
    sys.path.insert(0, str(V08C))
    core = load_module("jev_v08g_profile_core", V08D / "discover_v08d_common_support.py")
    signature_audit = load_module(
        "jev_v08g_signature_audit", V08C / "audit_phase2c_training_signatures.py"
    )
    signatures = load_module(
        "jev_v08g_training_signatures", V08C / "phase2c_training_signatures.py"
    )
    # Load the P* anchor decoder from the frozen v0.8E policy module.
    policy = load_module("jev_v08g_policy", V08E / "build_policy_arms.py")
    anchor = policy.thaw_profile(pstar["anchor_profile"])
    limits = pstar["profile_limits"]
    tolerances = {
        "unique_relative_error_max": limits["unique_relative_error_max"],
        "occurrence_histogram_tv_max": limits["occurrence_histogram_tv_max"],
        "marginal_tv_max": limits["marginal_tv_max"],
    }

    selected: dict[str, list[Any]] = {"R100-star": [], "C100-star": []}
    uri = f"file:{DB.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    query = (
        "SELECT group_id, episode_id, root_id, joint_cell_json, "
        "selector_model_input_sha256, state_input_sha256, coverage_features_json, "
        "family_ids_json, adapter_kind, view, open_world, probability_source, "
        "candidate_count, state_input_sha256, candidate_ordered_sha256, "
        "candidate_set_sha256, target_ordered_sha256, supervised_signature_sha256, "
        "ordered_signature_sha256, invariant_key_sha256, perturbation_class "
        "FROM training_groups WHERE group_id=? AND held_out=0"
    )
    try:
        for bank_name, manifest in (("R100-star", random_ids), ("C100-star", curated_ids)):
            for group_id in sorted(manifest):
                row = connection.execute(query, (group_id,)).fetchone()
                if row is None:
                    raise ValueError(f"{bank_name}: selected group is absent or held out: {group_id}")
                if row[1] != manifest[group_id]:
                    raise ValueError(f"{bank_name}: source episode mismatch: {group_id}")
                selected[bank_name].append(core.item_from_row(row))
    finally:
        connection.close()

    profiles = {name: core.profile(items) for name, items in selected.items()}
    checks = {
        "R100-star_vs_Pstar": core.profile_check(anchor, profiles["R100-star"], tolerances),
        "C100-star_vs_Pstar": core.profile_check(anchor, profiles["C100-star"], tolerances),
        "R100-star_vs_C100-star": core.profile_check(
            profiles["R100-star"], profiles["C100-star"], tolerances
        ),
    }

    bank_rows: dict[str, list[dict[str, Any]]] = {}
    connection = sqlite3.connect(uri, uri=True)
    try:
        bank_rows["R100-star"] = signature_audit.bank_rows(
            connection, {key: "" for key in random_ids}
        )
        bank_rows["C100-star"] = signature_audit.bank_rows(
            connection, {key: "" for key in curated_ids}
        )
    finally:
        connection.close()
    final = {}
    pair_hashes = {}
    for name in ("R100-star", "C100-star"):
        final[name], pair_hashes[name] = signatures.attach_invariance_context(bank_rows[name])
    distance = signatures.multiset_distance(final["R100-star"].values(), final["C100-star"].values())
    training_hashes = {
        name: signatures.digest(sorted(values.values())) for name, values in final.items()
    }
    return {
        "profile_checks": checks,
        "all_profile_checks_pass": all(check["all_pass"] for check in checks.values()),
        "exact_training_signature_distance": distance,
        "training_multiset_sha256": training_hashes,
        "invariance_pair_counts": {name: len(value) for name, value in pair_hashes.items()},
        "group_counts": {name: len(items) for name, items in selected.items()},
    }


def write_legacy_id_manifests(out_dir: Path, feature_cache_path: Path) -> dict[str, Any]:
    import torch

    cache = torch.load(feature_cache_path, map_location="cpu", weights_only=False)
    if cache.get("revision") != EXPECTED["LFM_revision"]:
        raise ValueError("legacy v0.7 cache revision mismatch")
    groups = cache.get("groups")
    if not isinstance(groups, list):
        raise ValueError("legacy v0.7 feature cache lacks group rows")
    result: dict[str, Any] = {}
    for split in ("dev", "test", "external"):
        selected = [
            (cache_index, group) for cache_index, group in enumerate(groups)
            if group.get("split") == split
            and not group.get("open_world")
            and group.get("kind") in {"choice", "independent"}
        ]
        target = out_dir / f"legacy-{split}-group-ids.jsonl"
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            ids = sorted(
                (str(group["group_id"]), int(cache_index), str(group["episode_id"]))
                for cache_index, group in selected
            )
            for group_id, cache_index, episode_id in ids:
                stream.write(json.dumps({
                    "group_id": group_id,
                    "episode_id": episode_id,
                    "cache_row_index": cache_index,
                }, separators=(",", ":")) + "\n")
        unique_ids = len({group["group_id"] for _index, group in selected})
        result[split] = {
            "path": str(target),
            "sha256": sha256_file(target),
            "group_count": len(selected),
            "unique_group_id_count": unique_ids,
            "duplicate_group_id_rows": len(selected) - unique_ids,
            "feature_cache_path": str(feature_cache_path),
        }
    return result


def write_binding_id_manifest(out_dir: Path, cache_path: Path) -> dict[str, Any]:
    import torch

    cache = torch.load(cache_path, map_location="cpu", weights_only=False)
    if cache.get("revision") != EXPECTED["LFM_revision"]:
        raise ValueError("contradictory-binding feature cache revision mismatch")
    groups = cache.get("groups")
    if not isinstance(groups, list):
        raise ValueError("contradictory-binding cache lacks group rows")
    target = out_dir / "contradictory-binding-group-ids.jsonl"
    selected = [
        (index, row) for index, row in enumerate(groups)
        if row.get("kind") == "choice" and not row.get("open_world")
    ]
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        for cache_index, row in selected:
            stream.write(json.dumps({
                "group_id": str(row["group_id"]),
                "episode_id": str(row["episode_id"]),
                "cache_row_index": cache_index,
            }, separators=(",", ":")) + "\n")
    unique_ids = len({row["group_id"] for _index, row in selected})
    manifest_path = V07_RUN / "features" / "binding" / "lfm2.5-1.2b-base-feature-manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("revision") != EXPECTED["LFM_revision"]:
        raise ValueError("contradictory-binding feature manifest revision mismatch")
    return {
        "group_id_manifest": {
            "path": str(target),
            "sha256": sha256_file(target),
            "group_count": len(selected),
            "unique_group_id_count": unique_ids,
            "duplicate_group_id_rows": len(selected) - unique_ids,
        },
        "feature_cache": {
            "path": str(cache_path),
            "bytes": cache_path.stat().st_size,
            "sha256": sha256_file(cache_path),
        },
        "feature_manifest": {
            "path": str(manifest_path),
            "bytes": manifest_path.stat().st_size,
            "sha256": sha256_file(manifest_path),
        },
    }


def preflight() -> dict[str, Any]:
    if OUT.exists() and any(OUT.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty v0.8G run directory: {OUT}")

    lineage_hashes: list[dict[str, str]] = []
    phase2c_receipt_path = PHASE2C_DIR / "phase2c-freeze-receipt.json"
    phase2c_receipt = read_json(phase2c_receipt_path)
    pstar_receipt_path = PSTAR_DIR / "integrity-receipt.json"
    pstar_receipt = read_json(pstar_receipt_path)
    arms_receipt_path = ARMS_DIR / "integrity-receipt.json"
    arms_receipt = read_json(arms_receipt_path)
    arms_result_path = ARMS_DIR / "balanced-cycle-search.json"
    arms_result = read_json(arms_result_path)

    require_hash(V07 / "v07-contract.json", EXPECTED["v07_contract"], "v0.7 contract")
    if phase2c_receipt.get("status") != "SEALED_BEFORE_SIGNATURE_AUDIT":
        raise ValueError("v0.8C lineage receipt is not sealed")
    if sha256_file(phase2c_receipt_path) != pstar_receipt["upstream_inputs_sha256"]["phase2c_freeze_receipt"]:
        raise ValueError("v0.8C freeze receipt hash mismatch in v0.8E")
    if pstar_receipt.get("status") != "SEALED_PSTAR_PROFILE_AND_CAPACITY_WITNESS":
        raise ValueError("P* integrity receipt status mismatch")
    if sha256_file(PSTAR_DIR / "pstar-profile.json") != EXPECTED["Pstar"]:
        raise ValueError("sealed P* profile hash mismatch")
    if arms_receipt.get("status") != "POLICY_ARMS_READY_MODEL_CONTACT_NOT_AUTHORIZED":
        raise ValueError("v0.8F policy-arm receipt status mismatch")
    if arms_receipt.get("authorization", {}).get("model_contact") is not False:
        raise ValueError("historical v0.8F receipt unexpectedly changed its authorization boundary")
    if arms_result.get("status") != "POLICY_ARMS_READY_MODEL_CONTACT_NOT_AUTHORIZED":
        raise ValueError("v0.8F result status mismatch")
    if arms_result.get("model_contact_authorized") is not False:
        raise ValueError("v0.8F result authorization field changed")

    for name, expected in arms_receipt["source_hashes"].items():
        paths = {
            "cycle_search": V08E / "balanced_policy_cycles_v06.py",
            "policy_builder": V08E / "build_policy_arms.py",
            "sealed_profile": PSTAR_DIR / "pstar-profile.json",
            "sealed_receipt": pstar_receipt_path,
            "source_db": DB,
        }
        if name not in paths:
            raise ValueError(f"unrecognized v0.8F source hash: {name}")
        actual = require_hash(paths[name], expected, f"v0.8F {name}")
        lineage_hashes.append({"path": str(paths[name]), "sha256": actual})
    require_hash(arms_result_path, arms_receipt["result_sha256"], "v0.8F result")
    for arm_name, item in arms_receipt["candidate_manifests"].items():
        require_hash(Path(item["path"]), item["sha256"], f"v0.8F {arm_name} manifest")

    # Validate the complete phase-2C source inventory and its source-code freeze.
    verify_source_map(phase2c_receipt["repository_sources"], lineage_hashes)
    verify_recorded_files(phase2c_receipt.get("external_inputs", {}), ROOT, lineage_hashes)
    # Verify v0.8E's upstream inputs that are explicitly named in its receipt.
    named_v08e_inputs = {
        "group_records": GROUP_RECORDS,
        "canonical_episodes": CANONICAL,
        "heldout_manifest": EVAL_MANIFEST,
        "training_signature_index": DB,
        "input_target_consistency": V08_RUN / "full-universe-500k-v08" / "input-target-consistency.json",
        "generation_receipt": V08_RUN / "full-universe-500k-v08" / "generation-receipt.json",
    }
    for label, path in named_v08e_inputs.items():
        expected = pstar_receipt["upstream_inputs_sha256"].get(label)
        if expected:
            actual = require_hash(path, expected, f"v0.8E upstream {label}")
            lineage_hashes.append({"path": str(path), "sha256": actual})
    require_hash(EVAL_MANIFEST, EXPECTED["NewTight_Eval"], "NewTight-Eval manifest")
    if sha256_file(arms_receipt_path) != pstar_receipt.get("upstream_inputs_sha256", {}).get("policy_arm_receipt"):
        # Older P* receipts do not bind v0.8F. If the field exists, enforce it.
        if "policy_arm_receipt" in pstar_receipt.get("upstream_inputs_sha256", {}):
            raise ValueError("v0.8F receipt hash mismatch in P* receipt")

    random_path = ARMS_DIR / "candidate-R100-star-ids.jsonl"
    curated_path = ARMS_DIR / "candidate-C100-star-ids.jsonl"
    random_ids = read_id_manifest(random_path, 100_000)
    curated_ids = read_id_manifest(curated_path, 100_000)
    eval_ids = read_id_manifest(EVAL_MANIFEST, 83_328)
    cross_arm_group_id_overlap = set(random_ids) & set(curated_ids)
    heldout_overlap = (set(random_ids) | set(curated_ids)) & set(eval_ids)
    if heldout_overlap:
        raise ValueError(f"training arms overlap NewTight-Eval: {len(heldout_overlap)} IDs")
    verify_ids_in_database({"R100-star": random_ids, "C100-star": curated_ids})

    pstar = read_json(PSTAR_DIR / "pstar-profile.json")
    profile_distance = recompute_profile_and_distance(random_ids, curated_ids, pstar)
    independent = arms_result["independent_validation"]
    stored_distance = independent["training_distance"]
    expected_hashes = {
        "R100-star": stored_distance["left_training_multiset_sha256"],
        "C100-star": stored_distance["right_training_multiset_sha256"],
    }
    if profile_distance["training_multiset_sha256"] != expected_hashes:
        raise ValueError("independent training-multiset hashes differ from v0.8F sealed result")
    if abs(profile_distance["exact_training_signature_distance"] - 0.13489) > 1e-12:
        raise ValueError("independent D_train does not equal the declared 0.13489")
    if not profile_distance["all_profile_checks_pass"]:
        raise ValueError("independent profile reconstruction failed")

    # Bind the full v0.7 model snapshot and the already validated cache lineage.
    v07_integrity_path = V07_RUN / "reports" / "v07-integrity-receipt.json"
    v07_integration_path = V07_RUN / "reports" / "lfm-integration-receipt.json"
    v07_feature_validation_path = V07_RUN / "reports" / "lfm-feature-validation.json"
    v07_receipt = read_json(v07_integrity_path)
    v07_integration = read_json(v07_integration_path)
    v07_validation = read_json(v07_feature_validation_path)
    if v07_receipt.get("contract_sha256") != EXPECTED["v07_contract"]:
        raise ValueError("v0.7 receipt contract hash mismatch")
    if v07_integration.get("status") != "validated_snapshot_and_frozen_adapter":
        raise ValueError("v0.7 LFM integration status is not validated")
    if v07_integration["model"].get("revision") != EXPECTED["LFM_revision"]:
        raise ValueError("v0.7 pinned LFM revision mismatch")
    if v07_validation.get("checks", {}).get("deterministic") is not True:
        raise ValueError("v0.7 LFM determinism check did not pass")
    if v07_validation.get("checks", {}).get("single_row_reproducible") is not True:
        raise ValueError("v0.7 LFM single-row check did not pass")
    if v07_validation.get("checks", {}).get("frozen") is not True:
        raise ValueError("v0.7 LFM frozen-backbone check did not pass")
    model_path = Path(r"D:\codex-runs\jev-lfm-variable-v07\models\lfm2.5-1.2b-base")
    model_file_receipts = []
    for relative, record in sorted(v07_integration["model"]["files"].items()):
        file_path = model_path / relative
        if file_path.stat().st_size != int(record["bytes"]):
            raise ValueError(f"LFM snapshot byte count mismatch: {relative}")
        actual = require_hash(file_path, record["sha256"], f"LFM snapshot {relative}")
        model_file_receipts.append({"path": str(file_path), "bytes": int(record["bytes"]), "sha256": actual})

    feature_manifest_path = V07_RUN / "features" / "lfm2.5-1.2b-base-feature-manifest.json"
    expected_feature_manifest = v07_integration.get("feature_manifest_sha256")
    require_hash(feature_manifest_path, expected_feature_manifest, "v0.7 feature manifest")
    feature_cache_path = V07_RUN / "features" / "lfm2.5-1.2b-base-features.pt"
    cache_hash = sha256_file(feature_cache_path)
    cache_size = feature_cache_path.stat().st_size
    binding_cache_path = V07_RUN / "features" / "binding" / "lfm2.5-1.2b-base-features.pt"

    contract_path = ROOT / "experiments" / "jev-information-density-v08g" / "v08g-contract.json"
    contract_hash = sha256_file(contract_path)
    preflight_source_hash = sha256_file(Path(__file__))

    OUT.mkdir(parents=True, exist_ok=True)
    preflight_dir = OUT / "preflight"
    preflight_dir.mkdir(exist_ok=False)
    legacy_surfaces = write_legacy_id_manifests(preflight_dir, feature_cache_path)
    binding_surface = write_binding_id_manifest(preflight_dir, binding_cache_path)

    manifest_receipts = {
        "R100-star": {"path": str(random_path), "sha256": sha256_file(random_path), "group_count": len(random_ids)},
        "C100-star": {"path": str(curated_path), "sha256": sha256_file(curated_path), "group_count": len(curated_ids)},
        "Pstar": {"path": str(PSTAR_DIR / "pstar-profile.json"), "sha256": sha256_file(PSTAR_DIR / "pstar-profile.json")},
        "NewTight-Eval": {"path": str(EVAL_MANIFEST), "sha256": sha256_file(EVAL_MANIFEST), "group_count": len(eval_ids)},
        "legacy_protected": legacy_surfaces,
        "contradictory_binding_eval": binding_surface,
    }
    run_manifest = {
        "protocol": "jev-information-density/v0.8g-matched-policy-lfm",
        "status": "FROZEN_MODEL_CONTACT_AUTHORIZED",
        "authorized_by": "explicit user authorization in v0.8G request",
        "model_contact_authorized": True,
        "phoenix_access": False,
        "contract": {"path": str(contract_path), "sha256": contract_hash},
        "preflight_source": {"path": str(Path(__file__)), "sha256": preflight_source_hash},
        "frozen_inputs": manifest_receipts,
        "lineage_receipts": {
            "v08c_phase2c_freeze": {"path": str(phase2c_receipt_path), "sha256": sha256_file(phase2c_receipt_path)},
            "v08e_pstar_integrity": {"path": str(pstar_receipt_path), "sha256": sha256_file(pstar_receipt_path)},
            "v08f_policy_arm_integrity": {"path": str(arms_receipt_path), "sha256": sha256_file(arms_receipt_path)},
            "v08f_policy_arm_result": {"path": str(arms_result_path), "sha256": sha256_file(arms_result_path)},
            "v07_integration": {"path": str(v07_integration_path), "sha256": sha256_file(v07_integration_path)},
            "v07_integrity": {"path": str(v07_integrity_path), "sha256": sha256_file(v07_integrity_path)},
            "v07_feature_validation": {"path": str(v07_feature_validation_path), "sha256": sha256_file(v07_feature_validation_path)},
        },
        "independent_preflight": {
            "selected_groups_per_arm": {"R100-star": len(random_ids), "C100-star": len(curated_ids)},
            "cross_arm_raw_group_id_overlap_count": len(cross_arm_group_id_overlap),
            "heldout_overlap_count": len(heldout_overlap),
            "D_train": profile_distance["exact_training_signature_distance"],
            "profile_checks": profile_distance["profile_checks"],
            "training_multiset_sha256": profile_distance["training_multiset_sha256"],
            "invariance_pair_counts": profile_distance["invariance_pair_counts"],
        },
        "model": {
            "repo_id": "LiquidAI/LFM2.5-1.2B-Base",
            "revision": EXPECTED["LFM_revision"],
            "snapshot_path": str(model_path),
            "snapshot_files": model_file_receipts,
            "v07_extract_source_sha256": sha256_file(V07 / "extract_lfm.py"),
            "frozen_probe_sha256": sha256_file(PROBE),
            "frozen_trainer_sha256": sha256_file(V05 / "train_v05.py"),
            "feature_cache": {"path": str(feature_cache_path), "bytes": cache_size, "sha256": cache_hash},
            "feature_manifest": {"path": str(feature_manifest_path), "sha256": expected_feature_manifest},
        },
        "lineage_files_verified": lineage_hashes,
        "result_driven_tuning": False,
    }
    manifest_path = OUT / "v08g-run-manifest.json"
    with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(run_manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    authorization = {
        "status": "PASS",
        "model_contact_authorized": True,
        "authorized_by": "explicit user v0.8G request",
        "all_banks_and_lineage_verified": True,
        "D_train": profile_distance["exact_training_signature_distance"],
        "heldout_overlap_count": 0,
        "profile_pass": profile_distance["all_profile_checks_pass"],
        "phoenix_access": False,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
    }
    auth_path = preflight_dir / "model-contact-authorization.json"
    with auth_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(authorization, stream, indent=2)
        stream.write("\n")
    return authorization


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = preflight()
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

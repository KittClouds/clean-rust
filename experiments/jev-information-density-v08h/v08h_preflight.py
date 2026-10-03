"""Sealed-input verification and immutable metadata joins for v0.8H."""

from __future__ import annotations

import collections
import hashlib
import importlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from v08h_core import read_json, read_jsonl, sha256_file, signature_distance

REPO = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("v08h-contract.json")
V08E_DIR = REPO / "experiments" / "jev-information-density-v08e"
SIGNATURES_DIR = REPO / "experiments" / "jev-information-density-v08c"


def _verify(path: Path, expected: str, label: str, verified: dict[str, Any]) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing sealed {label}: {path}")
    actual = sha256_file(path)
    if actual.lower() != expected.lower():
        raise ValueError(f"sealed hash mismatch for {label}: expected={expected} actual={actual}")
    verified[label] = {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def _manifest_item(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    for item in manifest.get("lineage_files_verified", []):
        if Path(item["path"]).name == name:
            return item
    raise KeyError(f"v0.8G manifest has no lineage hash for {name}")


def _read_training_groups(path: Path) -> list[dict[str, Any]]:
    keep = (
        "group_id", "episode_id", "query_id", "kind", "view", "candidate_semantic_ids",
        "gold", "open_world", "probability_source", "authority", "split", "invariant_key",
        "semantic_fingerprint", "perturbation_class", "candidate_cardinality", "root_id",
        "family_ids", "coverage_features", "strata",
    )
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            row = {key: raw.get(key) for key in keep}
            if row["group_id"] is None:
                raise ValueError(f"missing group_id at {path}:{line_number}")
            rows.append(row)
    return rows


def _read_metadata(db_path: Path, group_ids: set[str]) -> dict[str, dict[str, Any]]:
    uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    columns = (
        "group_id, episode_id, root_id, split_family_bundle_id, selector_model_input_sha256, "
        "selector_gold_target_sha256, selector_structural_sha256, state_input_sha256, "
        "supervised_signature_sha256, adapter_kind, view, open_world, probability_source, "
        "candidate_count, posterior_entropy_nats, family_ids_json, coverage_features_json, held_out, "
        "candidate_ordered_sha256, candidate_set_sha256, target_ordered_sha256, "
        "ordered_signature_sha256, invariant_key_sha256, perturbation_class"
    )
    result: dict[str, dict[str, Any]] = {}
    try:
        count = conn.execute("SELECT COUNT(*) FROM training_groups WHERE held_out=0").fetchone()[0]
        if count != 416_672:
            raise ValueError(f"signature index eligible row count changed: {count}")
        values = sorted(group_ids)
        for start in range(0, len(values), 700):
            chunk = values[start : start + 700]
            marks = ",".join("?" for _ in chunk)
            query = f"SELECT {columns} FROM training_groups WHERE group_id IN ({marks})"
            for row in conn.execute(query, chunk):
                (group_id, episode_id, root_id, bundle_id, selector_input,
                 selector_target, structural, state_input, signature, kind, view,
                 open_world, probability_source, candidate_count, entropy_nats,
                 family_json, features_json, held_out, candidate_ordered, candidate_set,
                 target_ordered, ordered_signature, invariant_key, perturbation_class) = row
                result[str(group_id)] = {
                    "episode_id": str(episode_id),
                    "root_id": str(root_id),
                    "source_family": str(bundle_id),
                    "selector_input_signature": str(selector_input),
                    "selector_gold_target_sha256": str(selector_target),
                    "selector_structural_sha256": str(structural),
                    "state_signature": str(state_input),
                    "supervised_signature": str(signature),
                    "candidate_ordered_signature": str(candidate_ordered),
                    "candidate_set_signature": str(candidate_set),
                    "target_ordered_signature": str(target_ordered),
                    "ordered_signature": str(ordered_signature),
                    "invariant_key": str(invariant_key),
                    "perturbation_class": None if perturbation_class is None else str(perturbation_class),
                    "kind": str(kind),
                    "view": str(view),
                    "open_world": bool(open_world),
                    "probability_source": str(probability_source),
                    "candidate_count": int(candidate_count),
                    "posterior_entropy_nats_index": float(entropy_nats),
                    "family_ids": json.loads(family_json),
                    "coverage_features": json.loads(features_json),
                    "held_out": int(held_out),
                }
    finally:
        conn.close()
    if len(result) != len(group_ids):
        missing = group_ids - result.keys()
        raise ValueError(f"{len(missing)} selected IDs are absent from the signature index")
    return result


def _attach_and_check(rows: list[dict[str, Any]], metadata: dict[str, dict[str, Any]], arm: str) -> None:
    seen: set[str] = set()
    for row in rows:
        group_id = str(row["group_id"])
        if group_id in seen:
            raise ValueError(f"duplicate {arm} training group ID: {group_id}")
        seen.add(group_id)
        meta = metadata[group_id]
        checks = {
            "episode_id": row["episode_id"] == meta["episode_id"],
            "root_id": row["root_id"] == meta["root_id"],
            "kind": row["kind"] == meta["kind"],
            "view": row["view"] == meta["view"],
            "probability_source": row["probability_source"] == meta["probability_source"],
            "candidate_cardinality": int(row["candidate_cardinality"]) == meta["candidate_count"],
            "open_world": bool(row["open_world"]) == meta["open_world"],
            "family_ids": row["family_ids"] == meta["family_ids"],
            "coverage_features": row["coverage_features"] == meta["coverage_features"],
        }
        failed = [key for key, passed in checks.items() if not passed]
        if failed or meta["held_out"] != 0:
            raise ValueError(f"materialized/index mismatch for {arm} {group_id}: {failed}; held_out={meta['held_out']}")
        # Arms can share raw group IDs while receiving different v0.5 invariance-role
        # contexts. Give each occurrence its own mutable row metadata container.
        row["_meta"] = dict(meta)


def _exact_training_signatures(rows: list[dict[str, Any]], signature_ops: Any) -> tuple[dict[str, str], int, str]:
    """Replay the pinned v0.5 supervised plus capped invariance-role signature."""
    signature_rows = []
    for row in rows:
        meta = row["_meta"]
        signature_rows.append({
            "group_id": str(row["group_id"]),
            "state_input_sha256": meta["state_signature"],
            "candidate_ordered_sha256": meta["candidate_ordered_signature"],
            "candidate_set_sha256": meta["candidate_set_signature"],
            "target_ordered_sha256": meta["target_ordered_signature"],
            "supervised_signature_sha256": meta["supervised_signature"],
            "ordered_signature_sha256": meta["ordered_signature"],
            "invariant_key": meta["invariant_key"],
            "perturbation_class": meta["perturbation_class"],
            "kind": row["kind"],
            "view": row["view"],
            "open_world": bool(row["open_world"]),
            "probability_source": row["probability_source"],
        })
    final, selected_pairs = signature_ops.attach_invariance_context(signature_rows, max_pairs=16)
    return final, len(selected_pairs), signature_ops.digest(sorted(final.values()))


def _load_policy_scores() -> tuple[dict[str, Any], dict[str, dict[str, float]], dict[str, float], dict[str, Any]]:
    """Replay exact frozen scoring source over its pinned metadata universe."""
    sys.path.insert(0, str(V08E_DIR))
    v08e = importlib.import_module("state_exposure")
    policy = importlib.import_module("build_policy_arms")
    if policy.__file__ is None:
        raise RuntimeError("frozen policy module has no source path")
    pinned_policy = sha256_file(Path(policy.__file__))
    if pinned_policy.lower() != "2b1c7b2011da4a5c6dc3a3df1d2f01d13b8964a502ccb5f83ac1d8103441ca6b":
        raise ValueError("frozen build_policy_arms.py source hash changed")
    contract = v08e.require_v03_integrity()
    profile = read_json(Path(r"D:\codex-runs\jev-information-density-v08e\sealed-pstar-v01\pstar-profile.json"))
    items, _by_stratum, _quota, feature_counts, features_by_id = policy.selection_features_and_pool(
        contract, profile["stratum_counts"]
    )
    scores: dict[str, float] = {}
    components: dict[str, dict[str, float]] = {}
    for item in items:
        features = features_by_id[item.group_id]
        axis_components = {
            axis: sum(1.0 / (feature_counts[index][feature] ** 0.5) for feature in values) / len(values)
            for index, (axis, values) in enumerate(zip(policy.AXES, features))
        }
        score = sum(axis_components.values()) / len(policy.AXES)
        exact_score = policy.curation_score(features, feature_counts)
        if abs(score - exact_score) > 1e-15:
            raise ValueError(f"component decomposition does not replay frozen score for {item.group_id}")
        scores[item.group_id] = exact_score
        components[item.group_id] = axis_components
    if len(scores) != 416_672:
        raise ValueError(f"frozen scorer support size changed: {len(scores)}")
    return policy, components, scores, {
        "policy_source_path": str(Path(policy.__file__).resolve()),
        "policy_source_sha256": pinned_policy,
        "eligible_support_count": len(items),
        "axes": list(policy.AXES),
        "component_method": "exact per-axis reciprocal-square-root rarity means from frozen build_policy_arms.curation_score; no formula changes",
    }


def preflight(contract_path: Path | None = None) -> dict[str, Any]:
    contract_path = contract_path or CONTRACT_PATH
    contract = read_json(contract_path)
    sealed = contract["sealed_v08g"]
    verified: dict[str, Any] = {}
    run_manifest_path = Path(sealed["run_manifest"]["path"])
    integrity_path = Path(sealed["integrity_receipt"]["path"])
    scope_path = Path(sealed["execution_scope"]["path"])
    _verify(run_manifest_path, sealed["run_manifest"]["sha256"], "v08g_run_manifest", verified)
    _verify(integrity_path, sealed["integrity_receipt"]["sha256"], "v08g_integrity_receipt", verified)
    _verify(scope_path, sealed["execution_scope"]["sha256"], "v08g_execution_scope", verified)
    manifest, integrity, scope = read_json(run_manifest_path), read_json(integrity_path), read_json(scope_path)
    if integrity.get("status") != "PASS" or scope.get("status") != "READY_FOR_FROZEN_HEAD_TRAINING":
        raise ValueError("v0.8G sealed status is not the expected completed status")
    if integrity.get("execution_scope_sha256") != sha256_file(scope_path):
        raise ValueError("v0.8G execution-scope linkage changed")
    if scope.get("run_manifest_sha256") != sha256_file(run_manifest_path):
        raise ValueError("v0.8G run-manifest linkage changed")
    if integrity.get("phoenix_access") is not False or integrity.get("backbone_frozen") is not True:
        raise ValueError("v0.8G boundary receipt mismatch")
    if manifest.get("phoenix_access") is not False or manifest.get("model_contact_authorized") is not True:
        raise ValueError("v0.8G manifest boundary/status mismatch")

    expected_contract = sealed["contract_sha256"]
    _verify(Path(manifest["contract"]["path"]), expected_contract, "v08g_contract", verified)
    for receipt_name, entry in manifest["lineage_receipts"].items():
        _verify(Path(entry["path"]), entry["sha256"], f"lineage_{receipt_name}", verified)
    for entry in manifest.get("lineage_files_verified", []):
        _verify(Path(entry["path"]), entry["sha256"], f"lineage_file_{Path(entry['path']).name}", verified)

    # Validate the exact metadata and training occurrences used by the sealed run.
    materialization_path = Path(scope["input_sha256"]["materialization_receipt"]["path"])
    _verify(materialization_path, sealed["materialization_receipt_sha256"], "materialization_receipt", verified)
    materialization = read_json(materialization_path)
    for name, item in materialization["group_files"].items():
        _verify(Path(item["path"]), item["sha256"], f"materialized_{name}_groups", verified)
    for name, expected in materialization["source_hashes_rechecked"].items():
        path = None
        for entry in manifest.get("lineage_files_verified", []):
            if entry["sha256"].lower() == expected.lower():
                path = Path(entry["path"])
                break
        if path is None:
            raise ValueError(f"cannot resolve canonical source metadata path for {name}")
        _verify(path, expected, f"canonical_source_{name}", verified)

    # Verify six final NewTight prediction files, six run reports, and every sealed analysis report.
    run_files = integrity["run_reports_and_predictions"]
    run_reports = [path for path in run_files if path.endswith("run-report.json")]
    primary_predictions = [path for path in run_files if path.endswith("newtight-final-predictions.jsonl")]
    if len(run_reports) != 6 or len(primary_predictions) != 6:
        raise ValueError(f"v0.8G receipt expected six run reports and six primary predictions; got {len(run_reports)}, {len(primary_predictions)}")
    for name, expected in run_files.items():
        _verify(Path(name), expected, f"run_artifact_{Path(name).name}_{Path(name).parent.name}", verified)
    for path, descriptor in integrity["analysis_reports"].items():
        _verify(Path(path), descriptor["sha256"], f"analysis_report_{Path(path).name}", verified)

    # Resolve and verify lineage anchors required by the v0.8H analysis.
    anchors = manifest["frozen_inputs"]
    for name in ("R100-star", "C100-star", "Pstar", "NewTight-Eval"):
        _verify(Path(anchors[name]["path"]), anchors[name]["sha256"], f"frozen_anchor_{name}", verified)
    signature_index = _manifest_item(manifest, "training-signatures.sqlite")
    _verify(Path(signature_index["path"]), signature_index["sha256"], "supervised_signature_index", verified)
    source_file = _manifest_item(manifest, "build_policy_arms.py")
    _verify(Path(source_file["path"]), source_file["sha256"], "frozen_curation_policy_source", verified)
    cycle_file = _manifest_item(manifest, "balanced_policy_cycles_v06.py")
    _verify(Path(cycle_file["path"]), cycle_file["sha256"], "frozen_cycle_source", verified)
    signature_file = _manifest_item(manifest, "phase2c_training_signatures.py")
    _verify(Path(signature_file["path"]), signature_file["sha256"], "frozen_training_signature_source", verified)

    # The binding prediction artifacts were not individually listed in the v0.8G integrity map.
    # Their paths are checked against the completed run reports; hashes are recorded as observed now.
    binding_predictions: dict[str, dict[str, Any]] = {}
    reports_by_run = {Path(path).as_posix(): read_json(Path(path)) for path in run_reports}
    for run_name, report in reports_by_run.items():
        prediction_path = Path(report["contradictory_binding"]["prediction_file"])
        if not prediction_path.is_file():
            raise FileNotFoundError(f"saved binding prediction artifact missing: {prediction_path}")
        binding_predictions[str(prediction_path)] = {
            "sha256_observed_during_v08h": sha256_file(prediction_path),
            "bytes": prediction_path.stat().st_size,
            "v08g_integrity_receipt_pinned_hash": False,
        }

    random_rows = _read_training_groups(Path(materialization["group_files"]["random"]["path"]))
    curated_rows = _read_training_groups(Path(materialization["group_files"]["curated"]["path"]))
    eval_rows = _read_training_groups(Path(materialization["group_files"]["new_tight_eval"]["path"]))
    expected = contract["expected"]
    if (len(random_rows), len(curated_rows), len(eval_rows)) != (
        expected["groups_per_arm"], expected["groups_per_arm"], expected["new_tight_eval_occurrences"]
    ):
        raise ValueError("materialized group count differs from frozen v0.8G contract")

    id_manifests = {
        "random": read_jsonl(Path(anchors["R100-star"]["path"])),
        "curated": read_jsonl(Path(anchors["C100-star"]["path"])),
        "eval": read_jsonl(Path(anchors["NewTight-Eval"]["path"])),
    }
    for name, rows, ids in (
        ("random", random_rows, id_manifests["random"]),
        ("curated", curated_rows, id_manifests["curated"]),
        ("eval", eval_rows, id_manifests["eval"]),
    ):
        row_ids = [str(row["group_id"]) for row in rows]
        manifest_ids = [str(row["group_id"]) for row in ids]
        if len(set(row_ids)) != len(row_ids) or Counter(row_ids) != Counter(manifest_ids):
            raise ValueError(f"materialized {name} occurrence IDs do not exactly match its sealed manifest")

    selected_ids = {str(row["group_id"]) for row in random_rows + curated_rows}
    db_path = Path(signature_index["path"])
    metadata = _read_metadata(db_path, selected_ids)
    _attach_and_check(random_rows, metadata, "random")
    _attach_and_check(curated_rows, metadata, "curated")
    sys.path.insert(0, str(SIGNATURES_DIR))
    signature_ops = importlib.import_module("phase2c_training_signatures")
    training_signatures_r, pair_count_r, multiset_hash_r = _exact_training_signatures(random_rows, signature_ops)
    training_signatures_c, pair_count_c, multiset_hash_c = _exact_training_signatures(curated_rows, signature_ops)
    for row in random_rows:
        row["_meta"]["training_signature"] = training_signatures_r[str(row["group_id"])]
    for row in curated_rows:
        row["_meta"]["training_signature"] = training_signatures_c[str(row["group_id"])]
    counts_r = Counter(training_signatures_r.values())
    counts_c = Counter(training_signatures_c.values())
    base_counts_r = Counter(row["_meta"]["supervised_signature"] for row in random_rows)
    base_counts_c = Counter(row["_meta"]["supervised_signature"] for row in curated_rows)
    distance = signature_distance(counts_r, counts_c, expected["groups_per_arm"])
    supervised_distance = signature_distance(base_counts_r, base_counts_c, expected["groups_per_arm"])
    l1 = int(distance["signature_count_l1"])
    d_train = float(distance["D_train"])
    if abs(d_train - expected["D_train"]) > 1e-12:
        raise ValueError(f"reconstructed D_train differs: {d_train} != {expected['D_train']}")
    if abs(float(supervised_distance["D_train"]) - expected["D_supervised_only"]) > 1e-12:
        raise ValueError(
            "reconstructed base supervised-signature distance differs: "
            f"{supervised_distance['D_train']} != {expected['D_supervised_only']}"
        )
    frozen_v08f = read_json(Path(manifest["lineage_receipts"]["v08f_policy_arm_result"]["path"]))
    frozen_training = frozen_v08f["independent_validation"]["training_distance"]
    if {pair_count_r, pair_count_c} != {
        frozen_training["left_selected_invariance_pairs"], frozen_training["right_selected_invariance_pairs"]
    }:
        raise ValueError("reconstructed capped-invariance pair counts differ from sealed v0.8F")
    if {multiset_hash_r, multiset_hash_c} != {
        frozen_training["left_training_multiset_sha256"], frozen_training["right_training_multiset_sha256"]
    }:
        raise ValueError("reconstructed exact training-signature multiset hashes differ from sealed v0.8F")

    # Verify the recorded preflight's critical sealed assertions.
    auth = scope["authorization"]
    if (auth.get("D_train") != expected["D_train"] or auth.get("heldout_overlap_count") != 0
            or auth.get("profile_pass") is not True):
        raise ValueError("v0.8G preflight authorization assertions differ")
    if len(primary_predictions) != 6 or len(run_reports) != 6:
        raise ValueError("incomplete paired v0.8G run set")

    policy, score_components, policy_scores, policy_receipt = _load_policy_scores()
    return {
        "contract": contract,
        "manifest": manifest,
        "integrity": integrity,
        "scope": scope,
        "materialization": materialization,
        "verified_hashes": verified,
        "binding_predictions_observed": binding_predictions,
        "run_reports": reports_by_run,
        "run_report_paths": [Path(path) for path in run_reports],
        "primary_prediction_paths": [Path(path) for path in primary_predictions],
        "random_rows": random_rows,
        "curated_rows": curated_rows,
        "eval_rows": eval_rows,
        "metadata": metadata,
        "counts_random": counts_r,
        "counts_curated": counts_c,
        "base_counts_random": base_counts_r,
        "base_counts_curated": base_counts_c,
        "D_train": d_train,
        "D_supervised": float(supervised_distance["D_train"]),
        "signature_l1": l1,
        "invariance_pair_counts": {"random": pair_count_r, "curated": pair_count_c, "cap": 16},
        "training_multiset_hashes": {"random": multiset_hash_r, "curated": multiset_hash_c},
        "policy": policy,
        "score_components": score_components,
        "policy_scores": policy_scores,
        "policy_receipt": policy_receipt,
    }

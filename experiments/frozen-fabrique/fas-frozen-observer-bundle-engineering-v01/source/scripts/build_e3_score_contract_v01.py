from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
E1_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04")
E1_SEAL_PATH = E1_ROOT / "e1-seal-v01.json"
E1_AUDIT_PATH = PROJECT / "audits" / "e1-independent-audit-v04.json"
E1_SUPPORT_PATH = E1_ROOT / "receipts" / "support-receipt-v01.json"
E1_ROWS_PATH = E1_ROOT / "panel" / "row-manifest-v01.jsonl"
E1_SPLIT_PATH = E1_ROOT / "panel" / "split-manifest-v01.jsonl"
FEATURE_CACHE_PATH = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\V1_FINAL_POSITION.f32le")
E3_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02")
E3_SEAL_PATH = E3_ROOT / "e3-v02-seal.json"
E3_AUDIT_PATH = E3_ROOT / "e3-v02-independent-audit-v01.json"
E3_BUNDLE_PATH = E3_ROOT / "frozen-capability-fabric-v02.json"
E0_CONTRACT_PATH = PROJECT / "contracts" / "e0-freeze-v10-sealed-v01.json"
E0_SEAL_PATH = PROJECT / "seals" / "e0-seal-v10.json"
E0_AUDIT_PATH = PROJECT / "audits" / "e0-v10-independent-audit-v01.json"
CONTRACT_PATH = PROJECT / "contracts" / "e3-score-v01.json"
EXPECTED_E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
EXPECTED_E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_ROOT = "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a"
EXPECTED_E3_ROOT = "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1"
ENDPOINTS = (
    "context_identity",
    "entity_identity",
    "relation",
    "observed_state",
    "exact_target_in_domain",
    "exact_target_context_novel",
    "exact_target_entity_novel",
    "exact_target_both_novel",
)
SOURCES = {
    "scorer": "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/score_e3_v01.py",
    "tests": "experiments/fas-frozen-observer-bundle-engineering-v01/source/tests/test_e3_score_v01.py",
    "contract_builder": "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/build_e3_score_contract_v01.py",
    "independent_auditor": "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/audit_e3_score_v01.py",
}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def path_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def artifact_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["artifact_id"]):
        digest.update(f'{entry["artifact_id"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"path": str(path.resolve()), "sha256": digest, "bytes": size}


def main() -> int:
    if CONTRACT_PATH.exists():
        raise RuntimeError("E3 score v01 contract already exists; refusing to replace it")
    e0_contract = read_json(E0_CONTRACT_PATH)
    e0_seal = read_json(E0_SEAL_PATH)
    e0_audit = read_json(E0_AUDIT_PATH)
    e1_seal = read_json(E1_SEAL_PATH)
    e1_audit = read_json(E1_AUDIT_PATH)
    e1_support = read_json(E1_SUPPORT_PATH)
    e3_seal = read_json(E3_SEAL_PATH)
    e3_audit = read_json(E3_AUDIT_PATH)
    e3_bundle = read_json(E3_BUNDLE_PATH)
    if e0_seal.get("root_sha256") != EXPECTED_E0_ROOT or path_root(e0_seal.get("entries", [])) != EXPECTED_E0_ROOT:
        raise RuntimeError("E0 v10 seal identity failed contract construction")
    if e0_audit.get("all_checks_passed") is not True:
        raise RuntimeError("E0 v10 independent audit is not PASS")
    if e1_seal.get("root_sha256") != EXPECTED_E1_ROOT or path_root(e1_seal.get("entries", [])) != EXPECTED_E1_ROOT:
        raise RuntimeError("E1 v04 population root failed contract construction")
    if e1_audit.get("status") != "PASS" or e1_audit.get("e1_root_sha256") != EXPECTED_E1_ROOT:
        raise RuntimeError("E1 v04 independent audit is not PASS")
    if artifact_root(e3_seal.get("entries", [])) != EXPECTED_E3_ROOT or e3_seal.get("root_sha256") != EXPECTED_E3_ROOT:
        raise RuntimeError("E3 v02 fit seal failed contract construction")
    if e3_audit.get("status") != "E3_V02_FIVE_FITS_INDEPENDENT_AUDIT_PASS_HELDOUT_SCORING_CLOSED" or e3_audit.get("all_checks_passed") is not True:
        raise RuntimeError("E3 v02 independent fit audit is not PASS")
    if e3_bundle.get("substrate", {}).get("e2_v07_root_sha256") != EXPECTED_E2_ROOT or e3_bundle.get("substrate", {}).get("feature_cache_sha256") != "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4" or e3_bundle.get("substrate", {}).get("feature_cache_bytes") != 872415232:
        raise RuntimeError("E3 bundle does not bind the frozen E2 v07 feature cache")
    eval_member = next((entry for entry in e1_seal["entries"] if entry["path"] == "labels/eval-labels-v01.jsonl"), None)
    if eval_member is None:
        raise RuntimeError("sealed E1 manifest lacks evaluation-label identity metadata")
    expected_label_path = (E1_ROOT / "labels" / "eval-labels-v01.jsonl").resolve()
    support_by_task = e1_support.get("test_class_support")
    if not isinstance(support_by_task, dict) or set(support_by_task) != {
        "CONTEXT_IDENTITY", "ENTITY_IDENTITY", "RELATION_IDENTITY", "OBSERVED_STATE",
        "EXACT_TARGET_IN_DOMAIN", "EXACT_TARGET_CONTEXT_NOVEL", "EXACT_TARGET_ENTITY_NOVEL", "EXACT_TARGET_BOTH_NOVEL",
    }:
        raise RuntimeError("E1 support receipt does not have the eight frozen endpoints")
    if any(min(values) < int(e0_contract["performance_gates"]["minimum_test_rows_per_class"]) for values in support_by_task.values()):
        raise RuntimeError("E1 sealed test support is below the frozen E0 endpoint floor")

    input_paths = {
        "e0_contract": E0_CONTRACT_PATH,
        "e0_seal": E0_SEAL_PATH,
        "e0_audit": E0_AUDIT_PATH,
        "e1_seal": E1_SEAL_PATH,
        "e1_audit": E1_AUDIT_PATH,
        "e1_support": E1_SUPPORT_PATH,
        "e1_rows": E1_ROWS_PATH,
        "e1_split": E1_SPLIT_PATH,
        "e3_seal": E3_SEAL_PATH,
        "e3_audit": E3_AUDIT_PATH,
        "e3_bundle": E3_BUNDLE_PATH,
    }
    inputs = {key: identity(path) for key, path in input_paths.items()}
    cache_entry = next((entry for entry in e3_seal["entries"] if Path(entry["path"]).resolve() == FEATURE_CACHE_PATH.resolve()), None)
    if cache_entry is None or cache_entry["sha256"] != e3_bundle["substrate"]["feature_cache_sha256"] or cache_entry["bytes"] != e3_bundle["substrate"]["feature_cache_bytes"]:
        raise RuntimeError("E2 feature cache identity differs between sealed E3 manifest and bundle")
    inputs["feature_cache"] = {
        "path": str(FEATURE_CACHE_PATH.resolve()),
        "sha256": cache_entry["sha256"],
        "bytes": cache_entry["bytes"],
        "identity_source": "E3 v02 sealed artifact entry; full content reverified during prelabel scoring preflight",
    }
    sources = {}
    for name, relative in SOURCES.items():
        path = REPO_ROOT / relative
        digest, size = sha256_file(path)
        sources[name] = {"path": relative, "sha256": digest, "bytes": size}

    contract = {
        "schema": "fas-frozen-observer-bundle-e3-score-v01",
        "contract_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_HELDOUT_SCORING_V01",
        "status": "FROZEN_HELDOUT_SCORING_ONLY_AUTHORIZATION_REQUIRED_BY_HASH",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "e0_root_sha256": EXPECTED_E0_ROOT,
        "e1_root_sha256": EXPECTED_E1_ROOT,
        "e2_v07_root_sha256": EXPECTED_E2_ROOT,
        "e3_v02_root_sha256": EXPECTED_E3_ROOT,
        "input_files": inputs,
        "evaluation_labels": {
            "path": str(expected_label_path),
            "sha256": eval_member["sha256"],
            "bytes": eval_member["bytes"],
            "rows": 21292,
            "quartets": 5323,
            "access_rule": "open and stream exactly once after this prelabel contract, authorization, root, source, support, runtime, and disk preflight passes",
            "prelabel_hashing_or_reading": False,
        },
        "task_endpoints": e0_contract["task_endpoints"],
        "endpoints": list(ENDPOINTS),
        "performance_gates": e0_contract["performance_gates"],
        "bootstrap": {
            **e0_contract["bootstrap"],
            "implementation_rng": "NumPy Generator(PCG64); one generator consumed in frozen endpoint order",
            "quantile_method": "linear",
        },
        "support_gate": {
            "minimum_test_rows_per_class": int(e0_contract["performance_gates"]["minimum_test_rows_per_class"]),
            "sealed_e1_test_class_support": support_by_task,
            "all_eight_endpoints_meet_floor": True,
        },
        "inference": {
            "backend": "PyTorch CPU float32 linear inference",
            "batch_rows": 2048,
            "torch_num_threads": 1,
            "torch_num_interop_threads": 1,
            "tf32": False,
            "cuda_contact": False,
            "linear_operation": "torch.nn.functional.linear((features - mean) / scale, weight, bias); argmax over class dimension",
            "head_artifacts": "the five E3 v02 sealed independent heads and scalers",
        },
        "resources": {
            "minimum_free_disk_bytes": 536870912,
            "minimum_free_disk_reason": "reserve at least 512 MiB on score-output volume before creating predictions, metrics, bootstrap outputs, and preservation receipts",
            "gpu_measurement": "not applicable; scoring inference is CPU-only and does not initialize CUDA",
        },
        "scope": {
            "one_heldout_label_opening": True,
            "score_five_frozen_heads_only": True,
            "refit_authorized": False,
            "threshold_or_scaler_changes_authorized": False,
            "representation_or_layer_search_authorized": False,
            "hyperparameter_rescue_authorized": False,
            "shared_or_multitask_heads_authorized": False,
            "drop_failed_endpoint_or_rerun_authorized": False,
            "E4_integration_authorized": False,
            "seal_outputs_and_independent_replay": True,
            "eight_individual_95_percent_gates_are_not_a_simultaneous_95_percent_claim": True,
        },
        "source_files": sources,
        "runtime": {
            "python_version": sys.version.split()[0],
            "numpy_version": np.__version__,
            "torch_version": torch.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "scoring_device": "CPU",
            "cuda_initialized": False,
        },
        "output": {
            "root": r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-score-v01",
            "predictions": "scored-test-rows-v01.jsonl",
            "metrics": "metrics-and-gates-v01.json",
            "bootstrap": "whole-quartet-bootstrap-v01.npz",
            "run_receipt": "e3-score-run-receipt-v01.json",
            "prelabel_receipt": "prelabel-preflight-v01.json",
            "stop_receipt": "e3-score-stop-v01.json when any post-output-creation gate fails",
        },
    }
    CONTRACT_PATH.write_text(json.dumps(contract, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    digest, size = sha256_file(CONTRACT_PATH)
    print(json.dumps({"contract_path": str(CONTRACT_PATH), "contract_sha256": digest, "contract_bytes": size, "e1_eval_label_metadata_only": True, "source_files_bound": list(sources)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

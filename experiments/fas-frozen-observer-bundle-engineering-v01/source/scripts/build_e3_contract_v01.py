from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
E1_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04")
E2_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07")
FIT_LABELS = E1_ROOT / "labels" / "fit-labels-v01.jsonl"
ROW_MANIFEST = E1_ROOT / "panel" / "row-manifest-v01.jsonl"
SPLIT_MANIFEST = E1_ROOT / "panel" / "split-manifest-v01.jsonl"
USER_AUTH_TEXT = "Once that compatibility test passes, proceed to the real goal: model contact, extraction, cache equality, and then fitting."
USER_AUTH_SHA256 = hashlib.sha256(USER_AUTH_TEXT.encode("utf-8")).hexdigest()
E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
E1_ROOT_SHA256 = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_ROOT_SHA256 = "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a"


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


def main() -> int:
    contract_path = PROJECT / "contracts" / "e3-fit-v01.json"
    authorization_path = PROJECT / "audits" / "e3-fit-authorization-v01.json"
    if contract_path.exists() or authorization_path.exists():
        raise RuntimeError("E3 contract or authorization already exists; refusing to rewrite")
    e2_seal = read_json(E2_ROOT / "e2-v07-seal.json")
    e2_audit = read_json(E2_ROOT / "e2-v07-independent-audit-v01.json")
    if e2_seal.get("root_sha256") != E2_ROOT_SHA256 or e2_audit.get("e2_root_sha256") != E2_ROOT_SHA256:
        raise RuntimeError("E3 predecessor E2 v07 seal/audit root mismatch")
    e0_seal = read_json(PROJECT / "seals" / "e0-seal-v10.json")
    e1_seal = read_json(E1_ROOT / "e1-seal-v01.json")
    if e0_seal.get("root_sha256") != E0_ROOT or e1_seal.get("root_sha256") != E1_ROOT_SHA256:
        raise RuntimeError("E3 predecessor E0/E1 root mismatch")
    fit_hash, fit_bytes = sha256_file(FIT_LABELS)
    row_hash, row_bytes = sha256_file(ROW_MANIFEST)
    split_hash, split_bytes = sha256_file(SPLIT_MANIFEST)
    cache = E2_ROOT / "V1_FINAL_POSITION.f32le"
    cache_hash, cache_bytes = sha256_file(cache)
    if cache_hash != e2_seal["feature_cache_sha256"] or cache_bytes != e2_seal["feature_cache_bytes"]:
        raise RuntimeError("E2 sealed feature cache changed before E3 fit contract construction")

    script_rel = f"experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/fit_observers_e3_v01.py"
    test_rel = f"experiments/fas-frozen-observer-bundle-engineering-v01/source/tests/test_e3_fit_v01.py"
    script_hash, _ = sha256_file(REPO_ROOT / script_rel)
    test_hash, _ = sha256_file(REPO_ROOT / test_rel)
    e2_audit_hash, _ = sha256_file(E2_ROOT / "e2-v07-independent-audit-v01.json")
    e2_seal_hash, _ = sha256_file(E2_ROOT / "e2-v07-seal.json")
    contract = {
        "contract_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_FIT_V01",
        "status": "E3_FIT_ONLY_FROZEN_PENDING_USER_AUTHORIZATION",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "predecessors": {"e0_v10_root_sha256": E0_ROOT, "e1_v04_root_sha256": E1_ROOT_SHA256, "e2_v07_root_sha256": E2_ROOT_SHA256, "e2_v07_seal_sha256": e2_seal_hash, "e2_v07_independent_audit_sha256": e2_audit_hash},
        "inputs": {
            "feature_cache": {"path": str(cache), "sha256": cache_hash, "bytes": cache_bytes, "rows": 106496, "dimension": 2048, "dtype": "little-endian float32", "access": "read-only mmap"},
            "fit_labels": {"path": str(FIT_LABELS), "sha256": fit_hash, "bytes": fit_bytes, "access": "read-only; training partition labels only"},
            "row_manifest": {"path": str(ROW_MANIFEST), "sha256": row_hash, "bytes": row_bytes, "access": "read-only row-to-feature index mapping"},
            "split_manifest": {"path": str(SPLIT_MANIFEST), "sha256": split_hash, "bytes": split_bytes, "access": "read-only FIT quartet membership only; no test-label data"},
        },
        "evaluation_data_access": "PROHIBITED; evaluation labels and all TEST-label content remain unopened",
        "tasks": {
            "context_identity": {"label": "context_term_id", "eligibility": "all FIT rows", "classes": 32},
            "entity_identity": {"label": "entity_term_id", "eligibility": "all FIT rows", "classes": 32},
            "relation": {"label": "relation_id", "eligibility": "context_term_id < 16 and entity_term_id < 16", "classes": 2},
            "observed_state": {"label": "state_id", "eligibility": "context_term_id < 16 and entity_term_id < 16", "classes": 3},
            "exact_target": {"label": "exact_target", "eligibility": "context_term_id < 16 and entity_term_id < 16", "classes": 3},
        },
        "scaler": {"algorithm": "train-only float64 chunked Welford population mean/scale", "chunk_rows": 2048, "zero_scales": "replace with 1", "persist_dtype": "little-endian float32"},
        "model": {"family": "independent multinomial linear readout", "initialization": "all weights and bias zero", "loss": "mean cross-entropy + 0.5 * 1e-4 * sum(weights squared); no bias regularization", "regularization": 1e-4, "trainable_parameters_expected": 147528, "trainable_parameter_bytes_f32_expected": 590112, "scaler_bytes_f32_expected": 81920, "total_observer_bytes_f32_expected": 672032},
        "optimizer": {"name": "PyTorch LBFGS", "learning_rate": 1.0, "max_iter": 300, "max_eval": 375, "tolerance_grad": 1e-7, "tolerance_change": 1e-9, "history_size": 10, "line_search": "strong_wolfe", "determinism_seed": 0},
        "bundle_boundary": {"independent_fits": 5, "shared_trainable_parameters": False, "multitask_loss": False, "view_search": False, "backbone_frozen": True, "feature_cache_immutable": True},
        "fit_outputs": {"root": r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v01", "bundle_id": "FAS_FROZEN_CAPABILITY_FABRIC_LFM12B_E3_V01"},
        "resources": {"device": "NVIDIA GeForce RTX 3080", "minimum_free_device_memory_bytes": 3221225472, "process_reserved_ceiling_bytes": 4294967296, "minimum_free_disk_bytes": 1073741824, "total_gpu_memory_claimed": False, "device_wide_gpu_metrics": "diagnostic-only"},
        "authority": {"training_fit_authorized_by_bound_user_instruction": True, "evaluation_scoring_authorized": False, "heldout_outcomes_opened": False, "hyperparameter_search_authorized": False, "model_updates_authorized": False, "E4_integration_authorized": False},
        "authorization_source": {"user_instruction_quote": USER_AUTH_TEXT, "quote_sha256": USER_AUTH_SHA256},
        "user_instruction_sha256": USER_AUTH_SHA256,
        "output_root": r"D:\\codex-runs\\fas-frozen-observer-bundle-engineering-v01\\e3-v01",
        "regularization": 1e-4,
        "implementation": {"fit_source_path": script_rel, "fit_source_sha256": script_hash, "test_source_path": test_rel, "test_source_sha256": test_hash},
    }
    canonical = (json.dumps(contract, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    contract_path.write_bytes(canonical)
    contract_hash = hashlib.sha256(canonical).hexdigest()
    authorization = {
        "authorization_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_FIT_AUTHORIZATION_V01",
        "project_id": "fas-frozen-observer-bundle-engineering-v01",
        "authorization_source": "explicit user instruction in active conversation to proceed through model contact, extraction, cache equality, and then fitting after compatibility tests pass",
        "user_instruction_quote": USER_AUTH_TEXT,
        "user_instruction_sha256": USER_AUTH_SHA256,
        "contract_path": str(contract_path.resolve()),
        "contract_sha256": contract_hash,
        "e0_root_sha256": E0_ROOT,
        "e1_root_sha256": E1_ROOT_SHA256,
        "e2_root_sha256": E2_ROOT_SHA256,
        "fit_labels_sha256": fit_hash,
        "feature_cache_sha256": cache_hash,
        "e3_fit_authorized": True,
        "e3_scoring_authorized": False,
        "evaluation_labels_opened": False,
        "authorized_heads": list(contract["tasks"]),
        "hyperparameter_search_authorized": False,
        "model_updates_authorized": False,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
    }
    authorization_path.write_bytes((json.dumps(authorization, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"status": contract["status"], "contract_sha256": contract_hash, "authorization_path": str(authorization_path), "authorization_sha256": sha256_file(authorization_path)[0], "fit_labels_sha256": fit_hash, "fit_rows": 85204, "evaluation_scoring_authorized": False}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

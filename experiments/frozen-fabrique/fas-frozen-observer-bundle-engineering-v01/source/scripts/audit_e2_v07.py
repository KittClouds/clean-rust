from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
EXPECTED_E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
EXPECTED_E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_CACHE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
EXPECTED_CACHE_BYTES = 872_415_232
EXPECTED_ROWS = 106_496
EXPECTED_DIM = 2_048
EXPECTED_GPU_LIMIT = 10 * 1024**3


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


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["artifact_id"]):
        digest.update(
            f'{entry["artifact_id"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8")
        )
    return digest.hexdigest()


def load_identity_module() -> Any:
    path = PROJECT / "source" / "scripts" / "e2_execution_identity_v07.py"
    spec = importlib.util.spec_from_file_location("e2_execution_identity_v07_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the sealed E2 v07 identity verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def finite_scan(cache_path: Path) -> dict[str, Any]:
    import numpy as np

    rows_per_chunk = 2048
    values = np.memmap(cache_path, dtype="<f4", mode="r", shape=(EXPECTED_ROWS, EXPECTED_DIM))
    checked = 0
    for start in range(0, EXPECTED_ROWS, rows_per_chunk):
        block = values[start : min(start + rows_per_chunk, EXPECTED_ROWS)]
        if not bool(np.isfinite(block).all()):
            raise RuntimeError(f"non-finite feature value detected in rows {start} onward")
        checked += int(block.shape[0])
    del values
    return {"finite": True, "rows_scanned": checked, "chunk_rows": rows_per_chunk, "dtype": "little-endian float32"}


def main() -> int:
    output_root = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07")
    cache_path = output_root / "V1_FINAL_POSITION.f32le"
    run_receipt_path = output_root / "feature-cache-receipt-v07.json"
    seal_path = output_root / "e2-v07-seal.json"
    audit_path = output_root / "e2-v07-independent-audit-v01.json"
    if seal_path.exists() or audit_path.exists():
        raise RuntimeError("E2 v07 audit or seal already exists; refusing to overwrite")

    receipt = read_json(run_receipt_path)
    seal = read_json(PROJECT / "seals" / "e0-seal-v10.json")
    protocol_path = PROJECT / "contracts" / "e2-run-v07.json"
    protocol = read_json(protocol_path)
    identity = load_identity_module()
    e0 = identity.verify_seal(REPO_ROOT, PROJECT / "seals" / "e0-seal-v10.json", EXPECTED_E0_ROOT)
    e1_root = Path(protocol["preflight_paths"]["e1_run_root"])
    e1_seal_path = e1_root / "e1-seal-v01.json"
    e1 = identity.verify_seal(e1_root, e1_seal_path, EXPECTED_E1_ROOT)
    panel_identity = identity.verify_panel_row_identity(
        e1_root, e1, protocol["preflight_paths"], EXPECTED_ROWS,
    )

    cache_hash, cache_bytes = sha256_file(cache_path)
    reference_path = Path(protocol["preflight_paths"]["reference_cache_path"])
    reference_hash, reference_bytes = sha256_file(reference_path)
    finite = finite_scan(cache_path)
    gpu = receipt["gpu_measurement"]
    baseline_keys = (
        "allocated_current_bytes", "reserved_current_bytes",
        "allocated_peak_since_reset_bytes", "reserved_peak_since_reset_bytes",
    )
    checks = {
        "e0_v10_root_and_members_recomputed": e0["root_sha256"] == EXPECTED_E0_ROOT,
        "e1_v04_root_and_members_recomputed": e1["root_sha256"] == EXPECTED_E1_ROOT,
        "ordered_e1_panel_row_identity_verified_labels_unopened": panel_identity["ordered_identity_match"] and panel_identity["row_count"] == EXPECTED_ROWS and panel_identity["labels_opened"] is False,
        "run_receipt_qualified_and_bound_to_e0_e1": receipt["status"] == "FEATURE_CACHE_COMPLETE_GPU_AND_EQUIVALENCE_GATES_PASS_PENDING_INDEPENDENT_SEAL" and receipt["e0_root_sha256"] == EXPECTED_E0_ROOT and receipt["e1_root_sha256"] == EXPECTED_E1_ROOT,
        "cache_exact_shape_dtype_length_and_hash": cache_bytes == EXPECTED_CACHE_BYTES == EXPECTED_ROWS * EXPECTED_DIM * 4 and cache_hash == EXPECTED_CACHE_SHA256 == receipt["feature_sha256"] and receipt["row_count"] == EXPECTED_ROWS and receipt["hidden_dimension"] == EXPECTED_DIM and receipt["surface"] == "V1_FINAL_POSITION" and receipt["tensor_identity"] == "output.last_hidden_state[0, sequence_length - 1, :]",
        "all_feature_values_finite_independently_scanned": finite["finite"] and finite["rows_scanned"] == EXPECTED_ROWS,
        "registered_repeat_gate_byte_exact": receipt["deterministic_repeat_rows"] == 256 and receipt["deterministic_repeat_byte_exact"] is True,
        "allocator_baselines_zero_and_process_gate_passed": all(all(gpu[key] == 0 for key in baseline_keys) for gpu in (gpu["pre_reset_allocator_counters"], gpu["post_reset_allocator_counters"])) and gpu["gate_passed"] is True and gpu["total_gpu_memory_claimed"] is False and gpu["scope"] == "this extractor process PyTorch CUDA caching allocator only" and gpu["final_and_process_peak"]["reserved_peak_since_reset_bytes"] <= EXPECTED_GPU_LIMIT and gpu["final_and_process_peak"]["allocated_peak_since_reset_bytes"] <= gpu["final_and_process_peak"]["reserved_peak_since_reset_bytes"],
        "read_only_v01_comparator_exact_and_unchanged": reference_hash == EXPECTED_CACHE_SHA256 and reference_bytes == EXPECTED_CACHE_BYTES and receipt["representation_equivalence"]["reference_sha256_before_extraction"] == reference_hash and receipt["representation_equivalence"]["reference_sha256_after_extraction"] == reference_hash and receipt["representation_equivalence"]["passed"] is True and receipt["representation_equivalence"]["reference_unchanged_during_extraction"] is True,
        "no_fit_scoring_or_model_update_in_e2": receipt["labels_opened"] is False and receipt["observer_fitting_performed"] is False and receipt["model_parameters_updated"] is False and receipt["gradients_present"] is False,
    }
    if not all(checks.values()):
        failure = {
            "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_V07_INDEPENDENT_AUDIT_FAILURE_V01",
            "status": "E2_V07_INDEPENDENT_AUDIT_FAILED_PRESERVED",
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "model_contact_performed": True,
            "feature_cache_preserved": True,
            "e3_fitting_performed": False,
        }
        audit_path.write_bytes(canonical_json(failure))
        raise RuntimeError(f"independent E2 v07 cache audit failed: {[key for key, value in checks.items() if not value]}")

    provenance = {
        "e0_v10_seal": PROJECT / "seals" / "e0-seal-v10.json",
        "e0_v10_audit": PROJECT / "audits" / "e0-v10-independent-audit-v01.json",
        "e1_v04_seal": e1_seal_path,
        "e2_v07_authorization_v01_rejected": PROJECT / "audits" / "e2-v07-model-contact-authorization-v01.json",
        "e2_v07_authorization_v02": PROJECT / "audits" / "e2-v07-model-contact-authorization-v02.json",
        "e2_v07_authorization_v01_stop": PROJECT / "audits" / "e2-v07-authorization-validation-stop-v01.json",
        "e2_v07_precontact_validation": PROJECT / "audits" / "e2-v07-authorization-v02-precontact-validation-pass-v01.json",
        "e2_v07_preflight": PROJECT / "audits" / "e2-v07-preauthorization-preflight-pass-v01.json",
        "e2_v07_run_receipt": run_receipt_path,
        "e2_v01_comparator": reference_path,
        "e2_v07_feature_cache": cache_path,
        "e2_v07_verifier_source": PROJECT / "source" / "scripts" / "e2_execution_identity_v07.py",
        "e2_v07_extractor_source": PROJECT / "source" / "scripts" / "extract_features_v07.py",
    }
    entries = []
    for artifact_id, path in provenance.items():
        digest, size = sha256_file(path.resolve(strict=True))
        entries.append({"artifact_id": artifact_id, "path": str(path.resolve()), "bytes": size, "sha256": digest})
    e2_root = tree_root(entries)
    manifest = {
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_SEAL_V07",
        "status": "E2_V07_SEALED_INDEPENDENT_AUDIT_PASS",
        "root_sha256": e2_root,
        "entry_count": len(entries),
        "entries": sorted(entries, key=lambda row: row["artifact_id"]),
        "e0_v10_root_sha256": EXPECTED_E0_ROOT,
        "e1_v04_root_sha256": EXPECTED_E1_ROOT,
        "feature_cache_sha256": cache_hash,
        "feature_cache_bytes": cache_bytes,
        "model_contact_authorized": True,
        "tokenizer_contact_authorized": True,
        "feature_extraction_authorized": True,
        "observer_fitting_performed": False,
        "evaluation_scoring_performed": False,
        "total_gpu_memory_claimed": False,
        "successful_e2_authorizes_e3": False,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    seal_path.write_bytes(canonical_json(manifest))
    sealed_manifest = read_json(seal_path)
    for entry in sealed_manifest["entries"]:
        digest, size = sha256_file(Path(entry["path"]))
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"E2 v07 sealed artifact changed on readback: {entry['artifact_id']}")
    audit = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_V07_INDEPENDENT_AUDIT_V01",
        "status": "E2_V07_INDEPENDENT_AUDIT_PASS_E3_NOT_AUTHORIZED_BY_E0_FREEZE",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "e2_root_sha256": e2_root,
        "e0_v10_root_sha256": EXPECTED_E0_ROOT,
        "e1_v04_root_sha256": EXPECTED_E1_ROOT,
        "feature_cache_sha256": cache_hash,
        "feature_cache_bytes": cache_bytes,
        "finite_scan": finite,
        "panel_identity": panel_identity,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "observer_fitting_performed": False,
        "evaluation_scoring_performed": False,
        "model_contact_performed": True,
        "cuda_allocator_initialized": True,
        "e3_authorized": False,
    }
    audit_path.write_bytes(canonical_json(audit))
    print(json.dumps({"status": audit["status"], "e2_root_sha256": e2_root, "cache_sha256": cache_hash, "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Seal the v0.8G execution code/data footprint before head training."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\codex-runs\jev-information-density-v08g")
PYTHON = Path(r"D:\codex-runs\jev-python-v06\Scripts\python.exe")
CONTRACT = ROOT / "experiments" / "jev-information-density-v08g" / "v08g-contract.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    manifest_path = OUT / "v08g-run-manifest.json"
    manifest = read_json(manifest_path)
    auth = read_json(OUT / "preflight" / "model-contact-authorization.json")
    if auth.get("status") != "PASS" or auth.get("model_contact_authorized") is not True:
        raise RuntimeError("sealed preflight authorization is not PASS")
    if auth.get("phoenix_access") is not False:
        raise RuntimeError("Phoenix is not explicitly excluded")
    if sha256_file(CONTRACT) != manifest["contract"]["sha256"]:
        raise RuntimeError("frozen contract hash mismatch")
    if sha256_file(manifest_path) != auth["manifest_sha256"]:
        raise RuntimeError("run manifest hash mismatch")
    feature_receipt = read_json(OUT / "feature-cache" / "extraction-receipt.json")
    if feature_receipt.get("status") != "FEATURE_EXTRACTION_COMPLETE":
        raise RuntimeError("feature extraction receipt is not complete")

    source_paths = [
        ROOT / "experiments/jev-information-density-v08g/v08g-contract.json",
        ROOT / "experiments/jev-information-density-v08g/preflight.py",
        ROOT / "experiments/jev-information-density-v08g/materialize_inputs.py",
        ROOT / "experiments/jev-information-density-v08g/extract_lfm_features.py",
        ROOT / "experiments/jev-information-density-v08g/finalize_extraction_receipt.py",
        ROOT / "experiments/jev-information-density-v08g/train_v08g.py",
        ROOT / "experiments/jev-information-density-v08g/tests/test_v08g.py",
        ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py",
        ROOT / "experiments/jev-frozen-readout-v01/probe.py",
        ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py",
    ]
    source_hashes = {str(path): sha256_file(path) for path in source_paths}
    if feature_receipt["path"]["implementation_sha256"] != source_hashes[str(
        ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py")]:
        raise RuntimeError("v0.7 representation adapter hash differs from feature receipt")
    if feature_receipt["cache"]["sha256"] != sha256_file(Path(feature_receipt["cache"]["path"])):
        raise RuntimeError("LFM feature cache changed after extraction receipt")

    external_inputs = {
        "run_manifest": manifest_path,
        "materialization_receipt": OUT / "materialized-inputs" / "materialization-receipt.json",
        "authorization": OUT / "preflight" / "model-contact-authorization.json",
        "feature_receipt": OUT / "feature-cache" / "extraction-receipt.json",
        "lfm_feature_cache": Path(feature_receipt["cache"]["path"]),
        "legacy_feature_cache": Path(manifest["frozen_inputs"]["legacy_protected"]["dev"]["feature_cache_path"]),
        "binding_feature_cache": Path(manifest["frozen_inputs"]["contradictory_binding_eval"]["feature_cache"]["path"]),
        "random_group_occurrences": Path(OUT / "materialized-inputs" / "random-groups.jsonl"),
        "curated_group_occurrences": Path(OUT / "materialized-inputs" / "curated-groups.jsonl"),
        "new_tight_eval_occurrences": Path(OUT / "materialized-inputs" / "new_tight_eval-groups.jsonl"),
    }
    input_hashes = {name: {"path": str(path), "bytes": path.stat().st_size,
                           "sha256": sha256_file(path)}
                    for name, path in external_inputs.items()}
    correction = {
        "protocol": "jev-information-density/v0.8g-matched-policy-lfm",
        "semantic_impact": "none",
        "items": [
            {"issue": "Windows GetProcessMemoryInfo ctypes handle conversion raised after all feature chunks and cache were written",
             "action": "finalize receipt using a separate cache/chunk equality validator without loading LFM",
             "validation": "47 chunks reconstructed the final cache exactly; extraction smoke max error 0.0"},
            {"issue": "training runner initially read model revision from the authorization receipt instead of frozen run manifest",
             "action": "corrected metadata lookup; no training began before correction",
             "validation": "full immutable bank/cache preflight and four unit tests pass"},
            {"issue": "NewTight materializer did not copy held-out-axis annotation onto compact rows",
             "action": "derive analysis-only unseen ontology/world family indicators from frozen training/evaluation family metadata",
             "validation": "all 83,328 NewTight rows receive deterministic axis labels; labels are not used in training or selection"},
        ],
    }
    reports = OUT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    correction_path = reports / "implementation-corrections.json"
    if correction_path.exists():
        raise FileExistsError(correction_path)
    correction_path.write_text(json.dumps(correction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "status": "READY_FOR_FROZEN_HEAD_TRAINING",
        "protocol": manifest["protocol"],
        "run_manifest_sha256": sha256_file(manifest_path),
        "contract_sha256": sha256_file(CONTRACT),
        "authorization": {"status": auth["status"], "model_contact_authorized": auth["model_contact_authorized"],
                          "phoenix_access": auth["phoenix_access"], "D_train": auth["D_train"],
                          "heldout_overlap_count": auth["heldout_overlap_count"],
                          "profile_pass": auth["profile_pass"]},
        "model": manifest["model"],
        "feature_extraction": {"status": feature_receipt["status"],
                               "feature_cache_sha256": feature_receipt["cache"]["sha256"],
                               "smoke_max_abs_error": feature_receipt["smoke"]["max_abs_error"],
                               "batch_size": 1, "padding": False, "pooling": "mean_full", "layer": "final"},
        "training_recipe": {"head": "dynamic_mlp_compatibility", "projection_width": 128,
                            "epochs": 3, "batch_groups": 256, "optimizer": "AdamW",
                            "learning_rate": 0.002, "weight_decay": 0.01,
                            "brier_weight": 0.25, "invariance_weight": 0.10,
                            "seeds": [20260927, 20260928, 20260929], "paired": True},
        "source_sha256": source_hashes,
        "input_sha256": input_hashes,
        "tests": {"suite": "experiments/jev-information-density-v08g/tests/test_v08g.py",
                  "passed": 4, "failed": 0},
        "correction_record": {"path": str(correction_path), "sha256": sha256_file(correction_path)},
        "phoenix_access": False,
        "backbone_weight_updates": False,
    }
    receipt_path = reports / "v08g-execution-scope.json"
    if receipt_path.exists():
        raise FileExistsError(receipt_path)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "receipt": str(receipt_path),
                      "receipt_sha256": sha256_file(receipt_path), "source_count": len(source_hashes),
                      "input_count": len(input_hashes)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

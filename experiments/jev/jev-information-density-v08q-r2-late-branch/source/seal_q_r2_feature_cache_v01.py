"""Independently validate and seal the Q-R2 frozen feature cache."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01")
FEATURES = RUN_ROOT / "features"
PANEL = RUN_ROOT / "panel"
RECEIPT = FEATURES / "r2-feature-extraction-receipt.json"
SEAL = RUN_ROOT / "seals/q-r2-feature-cache-seal-v01.json"
PANEL_SEAL = RUN_ROOT / "seals/q-r2-panel-construction-seal-v01.json"
FEATURE_KEY = "mean_full@16"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def tensor_hash(row: torch.Tensor) -> str:
    return sha256_bytes(row.detach().cpu().contiguous().numpy().tobytes())


def main() -> int:
    if SEAL.exists():
        raise RuntimeError("refusing to replace an existing Q-R2 feature-cache seal")
    receipt = read_json(RECEIPT)
    if receipt.get("status") != "Q_R2_FROZEN_PANEL_FEATURE_EXTRACTION_PASS" or not receipt.get("feature_cache_seal_pending"):
        raise RuntimeError("Q-R2 feature extraction receipt is not at the expected pre-seal state")
    if receipt.get("feature_key") != FEATURE_KEY or receipt.get("backbone_revision") != MODEL_REVISION:
        raise RuntimeError("Q-R2 feature key or model revision mismatch")
    if receipt.get("model_id") != "LiquidAI/LFM2.5-1.2B-Base" or not receipt.get("backbone_snapshot_files_unchanged") or receipt.get("backbone_snapshot_files_after_sha256") != receipt.get("runtime", {}).get("snapshot_sha256"):
        raise RuntimeError("Q-R2 model identity or before/after snapshot file check failed")
    tokenizer_identity = receipt.get("tokenizer_identity", {})
    if not tokenizer_identity.get("fast_tokenizer") or tokenizer_identity.get("tokenizer_json_sha256") != receipt["runtime"]["snapshot_sha256"].get("tokenizer.json") or tokenizer_identity.get("tokenizer_config_sha256") != receipt["runtime"]["snapshot_sha256"].get("tokenizer_config.json"):
        raise RuntimeError("Q-R2 tokenizer identity mismatch")
    if not receipt.get("backbone_parameter_identity_unchanged") or receipt.get("backbone_parameter_identity_before_sha256") != receipt.get("backbone_parameter_identity_after_sha256"):
        raise RuntimeError("Q-R2 backbone parameter identity changed")
    if not receipt.get("repeat_smoke", {}).get("pass") or receipt["repeat_smoke"]["max_abs_error"] > 1e-5:
        raise RuntimeError("Q-R2 deterministic repeat extraction failed")
    panel_seal = read_json(PANEL_SEAL)
    if receipt.get("panel_seal_sha256") != sha256_file(PANEL_SEAL):
        raise RuntimeError("Q-R2 feature receipt does not bind the sealed panel")
    if receipt.get("panel_root_sha256") != panel_seal.get("root_sha256"):
        raise RuntimeError("Q-R2 feature receipt panel root mismatch")

    scope = read_jsonl(PANEL / "panel-feature-scope.jsonl")
    candidates = read_jsonl(PANEL / "fresh-candidate-text-manifest.jsonl")
    state_manifest = read_jsonl(FEATURES / "r2-state-feature-manifest.jsonl")
    candidate_manifest = read_jsonl(FEATURES / "r2-candidate-feature-manifest.jsonl")
    state_blob = torch.load(FEATURES / "r2-state-features.pt", map_location="cpu", weights_only=True)
    candidate_blob = torch.load(FEATURES / "r2-candidate-features.pt", map_location="cpu", weights_only=True)
    states = state_blob["features"]
    candidate_features = candidate_blob["features"]
    if tuple(states.shape) != (22_000, 2_048) or tuple(candidate_features.shape) != (16, 2_048):
        raise RuntimeError("Q-R2 feature tensor dimensions mismatch")
    if states.dtype != torch.float32 or candidate_features.dtype != torch.float32 or not torch.isfinite(states).all() or not torch.isfinite(candidate_features).all():
        raise RuntimeError("Q-R2 feature tensor dtype/finite check failed")
    if state_blob.get("scope_sha256") != sha256_file(PANEL / "panel-feature-scope.jsonl") or candidate_blob.get("candidate_ids") != [row["candidate_semantic_id"] for row in candidates]:
        raise RuntimeError("Q-R2 tensor-to-input manifest binding mismatch")
    if receipt["state_tensor"]["sha256"] != sha256_file(FEATURES / "r2-state-features.pt") or receipt["candidate_tensor"]["sha256"] != sha256_file(FEATURES / "r2-candidate-features.pt"):
        raise RuntimeError("Q-R2 feature tensor file hash differs from extraction receipt")
    if receipt["state_tensor"]["tensor_sha256"] != tensor_hash(states) or receipt["candidate_tensor"]["tensor_sha256"] != tensor_hash(candidate_features):
        raise RuntimeError("Q-R2 feature tensor content hash differs from extraction receipt")
    if receipt["state_manifest_sha256"] != sha256_file(FEATURES / "r2-state-feature-manifest.jsonl") or receipt["candidate_manifest_sha256"] != sha256_file(FEATURES / "r2-candidate-feature-manifest.jsonl"):
        raise RuntimeError("Q-R2 feature row manifest hash differs from extraction receipt")
    if len(state_manifest) != len(scope) or len(candidate_manifest) != len(candidates):
        raise RuntimeError("Q-R2 feature manifest count mismatch")
    for index, (source, row) in enumerate(zip(scope, state_manifest, strict=True)):
        if row.get("index") != index or row.get("episode_id") != source["episode_id"] or row.get("input_sha256") != source["input_sha256"]:
            raise RuntimeError(f"Q-R2 state feature/input identity mismatch at row {index}")
        if row.get("feature_key") != FEATURE_KEY or not 1 <= int(row["token_count"]) <= 1024 or len(row["token_ids_sha256"]) != 64:
            raise RuntimeError(f"Q-R2 state token/feature identity malformed at row {index}")
        if tensor_hash(states[index]) != row["feature_sha256"]:
            raise RuntimeError(f"Q-R2 state feature row hash mismatch at row {index}")
    for index, (source, row) in enumerate(zip(candidates, candidate_manifest, strict=True)):
        if row.get("index") != index or row.get("candidate_semantic_id") != source["candidate_semantic_id"] or row.get("input_text_sha256") != source["text_sha256"] or int(row["candidate_order"]) != int(source["candidate_order"]):
            raise RuntimeError(f"Q-R2 candidate feature/input identity mismatch at row {index}")
        if row.get("feature_key") != FEATURE_KEY or not 1 <= int(row["token_count"]) <= 1024 or len(row["token_ids_sha256"]) != 64:
            raise RuntimeError(f"Q-R2 candidate token/feature identity malformed at row {index}")
        if tensor_hash(candidate_features[index]) != row["feature_sha256"]:
            raise RuntimeError(f"Q-R2 candidate feature row hash mismatch at row {index}")

    names = [
        "r2-state-features.pt",
        "r2-candidate-features.pt",
        "r2-state-feature-manifest.jsonl",
        "r2-candidate-feature-manifest.jsonl",
        "r2-feature-extraction-receipt.json",
    ]
    entries = sorted(
        [{"path": f"features/{name}", "bytes": (FEATURES / name).stat().st_size, "sha256": sha256_file(FEATURES / name)} for name in names],
        key=lambda row: row["path"],
    )
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    seal = {
        "schema": "jev-v08q-r2-feature-cache-seal-v01",
        "status": "Q_R2_FEATURE_CACHE_SEALED",
        "panel_construction_root_sha256": panel_seal["root_sha256"],
        "panel_seal_sha256": sha256_file(PANEL_SEAL),
        "feature_receipt_sha256": sha256_file(RECEIPT),
        "feature_key": FEATURE_KEY,
        "model_revision": MODEL_REVISION,
        "state_rows": len(scope),
        "candidate_rows": len(candidates),
        "dimension": 2_048,
        "dtype": "float32",
        "backbone_parameter_identity_unchanged": True,
        "repeat_extraction_pass": True,
        "feature_cache_seal_pending": False,
        "root_sha256": sha256_bytes(payload.encode("utf-8")),
        "entries": entries,
        "entry_count": len(entries),
        "head_loaded": False,
        "training": False,
        "heldout_inference": False,
        "outcome_analysis": False,
    }
    SEAL.parent.mkdir(parents=True, exist_ok=True)
    SEAL.write_text(json.dumps(seal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": seal["status"], "root_sha256": seal["root_sha256"], "entry_count": len(entries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

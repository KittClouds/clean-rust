"""Extract only contract-authorized frozen LFM features for the sealed P panel."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
P_ROOT = ROOT / "experiments/jev-information-density-v08p"
CONTRACT_PATH = P_ROOT / "phase_a/fresh-panel-contract-v01.json"
AUTH_PATH = P_ROOT / "phase_a/phase-a-authorization-receipt-v01.json"
BUNDLE_PATH = P_ROOT / "contracts/contract-bundle-seal-v01.json"
EXTRACTOR_PATH = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")
PANEL_ROOT = Path(r"D:\codex-runs\jev-information-density-v08p\v0.8P-fresh-eval-panel-v01")
DEVICE = "cuda"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tensor_sha256(tensor: torch.Tensor) -> str:
    return sha256_bytes(tensor.detach().cpu().contiguous().numpy().tobytes())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08p_frozen_lfm_extractor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load pinned extractor module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def snapshot_hashes(model_dir: Path, contract: dict[str, Any]) -> dict[str, str]:
    expected = contract["representation_and_matching"]["snapshot_sha256"]
    actual: dict[str, str] = {}
    for filename, digest in expected.items():
        path = model_dir / filename
        if not path.is_file():
            raise RuntimeError(f"pinned model file missing: {filename}")
        actual[filename] = sha256_file(path)
        if actual[filename] != digest:
            raise RuntimeError(f"pinned backbone file hash mismatch: {filename}")
    return actual


def token_identity(token_ids: list[int]) -> tuple[int, str]:
    packed = b"".join(struct.pack("<I", int(token)) for token in token_ids)
    return len(token_ids), sha256_bytes(packed)


def main() -> None:
    contract = read_json(CONTRACT_PATH)
    authorization = read_json(AUTH_PATH)
    bundle = read_json(BUNDLE_PATH)
    if authorization.get("authorization") != "AUTHORIZED_BY_USER":
        raise RuntimeError("P Phase-A authorization receipt is absent")
    if sha256_file(BUNDLE_PATH) != authorization["bindings"]["contract_bundle_seal_sha256"]:
        raise RuntimeError("contract bundle identity drift")
    if sha256_file(CONTRACT_PATH) != authorization["bindings"]["fresh_panel_contract_sha256"]:
        raise RuntimeError("fresh-panel contract identity drift")
    if bundle["state"]["training_authorized"] or bundle["state"]["evaluation_authorized"]:
        raise RuntimeError("training/evaluation authorization must remain false")
    if not torch.cuda.is_available():
        raise RuntimeError("contracted extraction device CUDA is unavailable; no fallback device permitted")
    if PANEL_ROOT != Path(contract["output"]["root"]):
        raise RuntimeError("panel root differs from frozen contract")

    semantic_receipt_path = PANEL_ROOT / "semantic-validation-receipt.json"
    overlap_path = PANEL_ROOT / "training-and-prior-panel-identity-overlap-receipt.json"
    semantic_receipt = read_json(semantic_receipt_path)
    overlap_receipt = read_json(overlap_path)
    if semantic_receipt.get("status") != "V08P_SEMANTIC_PANEL_VALIDATION_PASS":
        raise RuntimeError("semantic construction has not passed")
    if overlap_receipt.get("status") != "V08P_IDENTITY_OVERLAP_AUDIT_PASS":
        raise RuntimeError("identity overlap audit has not passed")

    feature_dir = PANEL_ROOT / "feature-cache"
    feature_dir.mkdir(parents=False, exist_ok=False)
    model_dir = MODEL_ROOT / "lfm2.5-1.2b-base"
    snapshot_before = snapshot_hashes(model_dir, contract)
    if sha256_file(EXTRACTOR_PATH) != contract["parents_and_source_bindings"]["existing_frozen_extractor"]["sha256"]:
        raise RuntimeError("frozen LFM extractor source drift")

    scope_path = PANEL_ROOT / "heldout-feature-scope.jsonl"
    candidate_path = PANEL_ROOT / "fresh-candidate-text-manifest.jsonl"
    scope = read_jsonl(scope_path)
    candidates = read_jsonl(candidate_path)
    if len(scope) != 22_000 or len(candidates) != 16:
        raise RuntimeError("P feature input cardinality mismatch")
    if any(row.get("partition") != "eval_v08p" for row in scope):
        raise RuntimeError("non-P evaluation row in feature scope")
    if len({row["candidate_semantic_id"] for row in candidates}) != 16:
        raise RuntimeError("duplicate P candidate semantic identity")

    extractor = load_module(EXTRACTOR_PATH)
    spec = extractor.MODEL_SPEC
    if spec["revision"] != contract["representation_and_matching"]["revision"]:
        raise RuntimeError("LFM model revision differs from contract")
    tokenizer, model = extractor.load_model(MODEL_ROOT, DEVICE)
    if model.config.hidden_size != 2048 or model.config.num_hidden_layers != 16:
        raise RuntimeError("LFM architecture differs from frozen feature contract")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("backbone parameters are not frozen")

    max_length = int(contract["representation_and_matching"]["maximum_length"])
    all_items = [("state", row) for row in scope] + [("candidate", row) for row in candidates]
    input_texts = [str(row["text"] if kind == "state" else row["input_text"]) for kind, row in all_items]
    token_rows: list[list[int]] = []
    token_records: list[dict[str, Any]] = []
    for kind, row in all_items:
        text = str(row["text"] if kind == "state" else row["input_text"])
        encoded = tokenizer(text, add_special_tokens=True, padding=False, truncation=False)
        ids = [int(item) for item in encoded["input_ids"]]
        if not ids or len(ids) > max_length:
            raise RuntimeError(f"token-length gate failed for {kind}/{row.get('episode_id', row.get('candidate_semantic_id'))}")
        expected_input_hash = row["input_sha256"] if kind == "state" else row["input_text_sha256"]
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected_input_hash:
            raise RuntimeError("input text hash mismatch before tokenization")
        length, token_hash = token_identity(ids)
        token_rows.append(ids)
        token_records.append({
            "record_type": kind,
            "identity": str(row["episode_id"] if kind == "state" else row["candidate_semantic_id"]),
            "schema_family_id": row.get("schema_family_id"),
            "input_text_sha256": expected_input_hash,
            "token_ids_sha256": token_hash,
            "sequence_length": length,
        })

    batch_size = int(contract["representation_and_matching"]["production_batch_size"])
    if batch_size != 1:
        raise RuntimeError("P contract no longer requires single-row extraction")
    location = contract["representation_and_matching"]["pooling"].split(" over ")[0]
    layer_count = int(model.config.num_hidden_layers)
    encoded = extractor.encode_lfm_texts(
        model, tokenizer, input_texts, ["mean_full"], [layer_count], batch_size, DEVICE, spec,
    )[f"mean_full@{layer_count}"]
    if tuple(encoded.shape) != (22_016, 2_048) or encoded.dtype != torch.float32 or not torch.isfinite(encoded).all().item():
        raise RuntimeError("P feature tensor shape/dtype/finiteness gate failed")
    encoded = encoded.detach().cpu().contiguous()
    state_features = encoded[:22_000].contiguous()
    candidate_features = encoded[22_000:].contiguous()
    state_file = feature_dir / "state-features.pt"
    candidate_file = feature_dir / "candidate-features.pt"
    torch.save({"features": state_features, "scope_sha256": sha256_file(scope_path), "identity": contract["identity"]}, state_file)
    torch.save({"features": candidate_features, "manifest_sha256": sha256_file(candidate_path), "identity": contract["identity"]}, candidate_file)

    for index, record in enumerate(token_records):
        feature = encoded[index]
        record["feature_row_index"] = index if record["record_type"] == "state" else index - 22_000
        record["feature_sha256"] = tensor_sha256(feature.reshape(1, -1))
        record["feature_dimension"] = 2_048
        record["feature_dtype"] = "float32"
    identity_path = feature_dir / "feature-identity-manifest.jsonl"
    write_jsonl(identity_path, token_records)
    write_json(feature_dir / "token-length-receipt.json", {
        "status": "PASS_NO_TRUNCATION",
        "identity": contract["identity"],
        "row_count": len(token_records),
        "maximum_length": max_length,
        "truncation": False,
        "record_type_counts": {"state": 22_000, "candidate": 16},
        "per_record_manifest_sha256": sha256_file(identity_path),
        "head_or_evaluation_targets_used": False,
    })
    del model
    if DEVICE == "cuda":
        torch.cuda.empty_cache()
    snapshot_after = snapshot_hashes(model_dir, contract)
    if snapshot_before != snapshot_after:
        raise RuntimeError("frozen backbone files changed during extraction")

    receipt = {
        "status": "V08P_FROZEN_LFM_FEATURE_CACHE_SEALED_BEHAVIOR_UNOPENED",
        "identity": contract["identity"],
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "authorization_receipt_sha256": sha256_file(AUTH_PATH),
        "contract_bundle_sha256": sha256_file(BUNDLE_PATH),
        "semantic_validation_receipt_sha256": sha256_file(semantic_receipt_path),
        "identity_overlap_receipt_sha256": sha256_file(overlap_path),
        "scope_sha256": sha256_file(scope_path),
        "candidate_text_manifest_sha256": sha256_file(candidate_path),
        "model": {
            "repo_id": spec["repo_id"],
            "revision": spec["revision"],
            "snapshot_hashes_before": snapshot_before,
            "snapshot_hashes_after": snapshot_after,
            "backbone_frozen": True,
            "hidden_dimension": 2_048,
            "layers": layer_count,
        },
        "extraction": {
            "source_path": str(EXTRACTOR_PATH.relative_to(ROOT)).replace("\\", "/"),
            "source_sha256": sha256_file(EXTRACTOR_PATH),
            "pooling": "final-layer mean_full@16",
            "exact_length": True,
            "single_row": True,
            "padding": False,
            "batch_size": 1,
            "maximum_length": max_length,
            "backbone_dtype": "bfloat16",
            "output_dtype": "float32",
            "row_count": 22_016,
            "shape_state": list(state_features.shape),
            "shape_candidates": list(candidate_features.shape),
        },
        "artifacts": {
            "state_file_sha256": sha256_file(state_file),
            "state_tensor_sha256": tensor_sha256(state_features),
            "candidate_file_sha256": sha256_file(candidate_file),
            "candidate_tensor_sha256": tensor_sha256(candidate_features),
            "identity_manifest_sha256": sha256_file(identity_path),
            "token_length_receipt_sha256": sha256_file(feature_dir / "token-length-receipt.json"),
        },
        "behavioral_opening": False,
        "head_load": False,
        "head_training": False,
        "predictions": False,
        "treatment_metrics": False,
        "event_time_analysis": False,
        "newtight_access": False,
        "legacy_evaluation_access": False,
        "phoenix_access": False,
    }
    write_json(feature_dir / "feature-cache-receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "state_rows": 22_000, "candidate_rows": 16, "max_length": max(record["sequence_length"] for record in token_records), "backbone_unchanged": True}, separators=(",", ":")))


if __name__ == "__main__":
    main()

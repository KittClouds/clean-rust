"""Materialize the immutable shared training-only v0.8N LFM feature cache."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08n/phase-a-v01-contract.json"
ADAPTER = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
DEFAULT_MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")
NEUTRAL_COUNT = 8


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def tensor_sha256(tensor: torch.Tensor) -> str:
    return hashlib.sha256(tensor.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_lfm_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load adapter: {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    selection = read_json(args.selection / "selection-receipt.json")
    selected = read_jsonl(args.selection / "selected-training-neighborhoods.jsonl")
    if selection["status"] != "V08N_N0_FEATURE_FREE_SELECTION_PASS" or len(selected) != 5_000:
        raise RuntimeError("N0 selection gate not passed")
    if contract["phase_boundaries"]["model_head_training"] or contract["phase_boundaries"]["evaluation_inference"]:
        raise RuntimeError("model boundary drift")
    canonical_path = args.run / "train-canonical-episodes.jsonl"
    canonical = read_jsonl(canonical_path)
    by_episode = {row["episode_id"]: row for row in canonical}
    if len(by_episode) != len(canonical):
        raise RuntimeError("duplicate training episode id")

    scope: list[dict[str, Any]] = []
    for neighborhood in selected:
        episode_ids = [neighborhood["episode_ids"]["anchor"], neighborhood["episode_ids"]["fact_flip"], neighborhood["episode_ids"]["sham"], *neighborhood["episode_ids"]["neutrals"]]
        roles = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, NEUTRAL_COUNT + 1)]]
        for role, episode_id in zip(roles, episode_ids):
            row = by_episode.get(episode_id)
            if row is None or row["evaluation_constraints"]["partition"] != "train":
                raise RuntimeError(f"training episode scope failure: {episode_id}")
            text = row["state"]["observable"]["content"]
            scope.append({"index": len(scope), "neighborhood_id": neighborhood["anchor_id"], "family_id": neighborhood["family_id"], "role": role, "episode_id": episode_id, "text": text, "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    if len(scope) != 55_000 or len({row["episode_id"] for row in scope}) != len(scope):
        raise RuntimeError("shared feature scope count/identity drift")

    feature_dir = args.output / "shared-feature-cache"
    feature_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = feature_dir / "shared-feature-cache-receipt.json"
    if receipt_path.exists():
        raise RuntimeError("shared feature cache already exists; refusing overwrite")
    scope_path = feature_dir / "training-only-feature-scope.jsonl"
    with scope_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in scope:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    scope_hash = sha256_json(scope)
    contract_hash = sha256_file(CONTRACT)
    authorization = {
        "status": "V08N_SHARED_CACHE_EXTRACTION_AUTHORIZED_TRAINING_ONLY",
        "protocol": contract["protocol"],
        "phase_identity": "v0.8N-base-v01",
        "contract_sha256": contract_hash,
        "selection_manifest_sha256": sha256_file(args.selection / "selected-training-neighborhoods.jsonl"),
        "source_train_canonical_sha256": sha256_file(canonical_path),
        "scope_content_sha256": scope_hash,
        "scope_rows": len(scope),
        "roles": ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, NEUTRAL_COUNT + 1)]],
        "model_repo_id": contract["representation_gate"]["model_repo_id"],
        "model_revision": contract["representation_gate"]["model_revision"],
        "representation": contract["representation_gate"],
        "head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }
    write_json(feature_dir / "shared-cache-authorization.json", authorization)

    adapter = load_adapter()
    if adapter.MODEL_SPEC["revision"] != contract["representation_gate"]["model_revision"]:
        raise RuntimeError("LFM revision drift")
    tokenizer, model = adapter.load_model(args.model_root, args.device)
    if int(model.config.hidden_size) != 2048 or int(model.config.num_hidden_layers) != 16:
        raise RuntimeError("LFM architecture drift")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("backbone is not frozen")
    key = "mean_full@16"
    smoke = [row["text"] for row in scope[:4]]
    first = adapter.encode_lfm_texts(model, tokenizer, smoke, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[key]
    second = adapter.encode_lfm_texts(model, tokenizer, smoke, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[key]
    smoke_error = float((first - second).abs().max().cpu())
    if smoke_error != 0.0:
        raise RuntimeError(f"determinism smoke failure: {smoke_error}")

    started = time.perf_counter()
    chunk_dir = feature_dir / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_size = 128
    parts: list[torch.Tensor] = []
    chunks: list[dict[str, Any]] = []
    texts = [row["text"] for row in scope]
    for start in range(0, len(texts), chunk_size):
        end = min(start + chunk_size, len(texts))
        features = adapter.encode_lfm_texts(model, tokenizer, texts[start:end], ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[key]
        if tuple(features.shape) != (end - start, 2048) or features.dtype != torch.float32:
            raise RuntimeError(f"feature shape/dtype drift: {start}:{end}")
        path = chunk_dir / f"features-{start:05d}-{end:05d}.pt"
        torch.save({"start": start, "end": end, "features": features.cpu().contiguous()}, path)
        parts.append(features.cpu().contiguous())
        chunks.append({"path": str(path), "sha256": sha256_file(path), "start": start, "end": end})
        print(json.dumps({"stage": "feature_chunk", "start": start, "end": end}, separators=(",", ":")), flush=True)
    tensor = torch.cat(parts, dim=0).to(torch.float32)
    feature_path = feature_dir / "shared-training-features.pt"
    torch.save({"features": tensor, "scope_content_sha256": scope_hash, "feature_key": key}, feature_path)
    receipt = {
        "status": "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY",
        "protocol": contract["protocol"], "phase_identity": "v0.8N-base-v01", "contract_sha256": contract_hash,
        "authorization_sha256": sha256_file(feature_dir / "shared-cache-authorization.json"),
        "selection_manifest_sha256": sha256_file(args.selection / "selected-training-neighborhoods.jsonl"),
        "source_train_canonical_sha256": sha256_file(canonical_path),
        "scope": {"path": str(scope_path), "sha256": sha256_file(scope_path), "content_sha256": scope_hash, "rows": len(scope), "neighborhoods": 5_000, "episodes_per_neighborhood": 11},
        "model": {"repo_id": adapter.MODEL_SPEC["repo_id"], "revision": adapter.MODEL_SPEC["revision"], "hidden_dim": 2048, "layer_count": 16, "backbone_frozen": True},
        "representation": {"feature_key": key, "pooling": "mean_full", "layer": "final", "exact_length": True, "single_row": True, "padding": False, "dtype": "float32"},
        "feature_tensor": {"path": str(feature_path), "sha256": sha256_file(feature_path), "tensor_sha256": tensor_sha256(tensor), "shape": list(tensor.shape), "bytes": feature_path.stat().st_size},
        "chunks": chunks, "smoke": {"status": "PASS", "repeat_max_abs_error": smoke_error},
        "runtime": {"device": args.device, "elapsed_seconds": time.perf_counter() - started, "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if args.device == "cuda" else 0},
        "head_training": False, "evaluation_inference": False, "protected_evaluation_bodies_opened": False, "newtight_access": False, "phoenix_access": False,
    }
    write_json(receipt_path, receipt)
    del model
    if args.device == "cuda": torch.cuda.empty_cache()
    print(json.dumps({"status": receipt["status"], "rows": len(scope), "feature_sha256": receipt["feature_tensor"]["sha256"], "elapsed_seconds": round(receipt["runtime"]["elapsed_seconds"], 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

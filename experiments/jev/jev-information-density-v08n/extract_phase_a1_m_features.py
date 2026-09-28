"""Extract training-only frozen LFM features for v0.8M radius validation.

The selected neighborhood set is frozen before this script runs.  This
script reads only the generated training canonical episode stream and never
opens the held-out stream or any protected evaluation material.
"""

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
CONTRACT = ROOT / "experiments/jev-information-density-v08m/phase_a/phase-a-v01-contract.json"
ADAPTER = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
DEFAULT_MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def tensor_sha256(tensor: torch.Tensor) -> str:
    return hashlib.sha256(tensor.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08m_lfm_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen LFM adapter: {ADAPTER}")
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
    selection_receipt = read_json(args.selection / "selection-receipt.json")
    selection_contract = read_json(args.selection / "selection-contract.json")
    selected = read_jsonl(args.selection / "selected-training-neighborhoods.jsonl")
    require(selection_receipt["status"] == "PHASE_A0_TRAINING_NEIGHBORHOOD_SELECTION_PASS", "selection gate is not passed")
    require(selection_contract["uses_features"] is False if "uses_features" in selection_contract else True, "selection contract drift")
    require(selection_receipt["selected_count"] == 5_000 and len(selected) == 5_000, "selected count drift")
    require(contract["phase_boundaries"]["phase_a1_frozen_feature_extraction_only"] is True, "A1 boundary drift")
    require(contract["phase_boundaries"]["model_head_training"] is False, "head-training boundary drift")
    require(contract["phase_boundaries"]["evaluation_inference"] is False, "evaluation boundary drift")
    require(contract["phase_boundaries"]["protected_evaluation_bodies_opened"] is False, "protected boundary drift")

    canonical_path = args.run / "train-canonical-episodes.jsonl"
    canonical_rows = read_jsonl(canonical_path)
    by_episode = {row["episode_id"]: row for row in canonical_rows}
    require(len(by_episode) == len(canonical_rows), "duplicate training episode id")

    scope: list[dict[str, Any]] = []
    for neighborhood in selected:
        for role in ("anchor", "fact_flip", "sham", "neutral"):
            episode_id = neighborhood["episode_ids"][role]
            row = by_episode.get(episode_id)
            require(row is not None, f"selected training episode missing: {episode_id}")
            require(row["evaluation_constraints"]["partition"] == "train", f"non-training episode: {episode_id}")
            scope.append({
                "index": len(scope),
                "neighborhood_id": neighborhood["anchor_id"],
                "family_id": neighborhood["family_id"],
                "role": role,
                "episode_id": episode_id,
                "text": row["state"]["observable"]["content"],
                "input_sha256": hashlib.sha256(row["state"]["observable"]["content"].encode("utf-8")).hexdigest(),
            })
    require(len(scope) == 20_000, f"feature scope count drift: {len(scope)}")
    require(len({row["episode_id"] for row in scope}) == len(scope), "duplicate feature scope episode")
    require(not any(row["episode_id"].startswith("v08m-eval-") for row in scope), "eval episode in feature scope")

    args.output.mkdir(parents=True, exist_ok=True)
    feature_dir = args.output / "feature-cache"
    feature_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = feature_dir / "extraction-receipt.json"
    require(not receipt_path.exists(), "A1 feature receipt already exists; refusing overwrite")
    scope_path = feature_dir / "training-feature-scope.jsonl"
    with scope_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in scope:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    scope_content_sha = sha256_json(scope)
    contract_sha = sha256_file(CONTRACT)
    selection_sha = sha256_file(args.selection / "selected-training-neighborhoods.jsonl")
    authorization = {
        "status": "PHASE_A1_FEATURE_EXTRACTION_AUTHORIZED_TRAINING_ONLY",
        "protocol": contract["protocol"],
        "phase_a_identity": contract["phase_a_identity"],
        "contract_sha256": contract_sha,
        "selection_receipt_sha256": sha256_file(args.selection / "selection-receipt.json"),
        "selection_manifest_sha256": selection_sha,
        "source_scope": "selected fresh v0.8M training neighborhoods A/F/S/N only",
        "source_run": str(args.run),
        "source_train_canonical_sha256": sha256_file(canonical_path),
        "scope_content_sha256": scope_content_sha,
        "scope_count": len(scope),
        "model_repo_id": contract["representation_gate"]["model_repo_id"],
        "model_revision": contract["representation_gate"]["model_revision"],
        "representation": contract["representation_gate"],
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }
    write_json(feature_dir / "feature-extraction-authorization.json", authorization)

    adapter = load_adapter()
    require(adapter.MODEL_SPEC["revision"] == contract["representation_gate"]["model_revision"], "LFM revision drift")
    tokenizer, model = adapter.load_model(args.model_root, args.device)
    require(int(model.config.hidden_size) == 2048 and int(model.config.num_hidden_layers) == 16, "LFM architecture drift")
    require(all(not parameter.requires_grad for parameter in model.parameters()), "backbone is not frozen")

    key = "mean_full@16"
    smoke_texts = [row["text"] for row in scope[:4]]
    smoke_one = adapter.encode_lfm_texts(model, tokenizer, smoke_texts, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[key]
    smoke_two = adapter.encode_lfm_texts(model, tokenizer, smoke_texts, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[key]
    smoke_error = float((smoke_one - smoke_two).abs().max().cpu())
    require(smoke_error == 0.0, f"repeated extraction drift: {smoke_error}")

    started = time.perf_counter()
    chunk_dir = feature_dir / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    all_features: list[torch.Tensor] = []
    chunks: list[dict[str, Any]] = []
    texts = [row["text"] for row in scope]
    chunk_size = 128
    for start in range(0, len(texts), chunk_size):
        end = min(start + chunk_size, len(texts))
        features = adapter.encode_lfm_texts(
            model, tokenizer, texts[start:end], ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC,
        )[key]
        require(tuple(features.shape) == (end - start, 2048), f"feature shape drift: {start}:{end}")
        require(features.dtype == torch.float32, f"feature dtype drift: {start}:{end}")
        chunk_path = chunk_dir / f"features-{start:05d}-{end:05d}.pt"
        torch.save({"start": start, "end": end, "features": features.cpu().contiguous()}, chunk_path)
        all_features.append(features.cpu().contiguous())
        chunks.append({"path": str(chunk_path), "sha256": sha256_file(chunk_path), "start": start, "end": end})
        print(json.dumps({"stage": "feature_chunk", "start": start, "end": end}, separators=(",", ":")), flush=True)

    feature_tensor = torch.cat(all_features, dim=0).to(torch.float32)
    feature_path = feature_dir / "training-features.pt"
    torch.save({"features": feature_tensor, "scope_content_sha256": scope_content_sha, "feature_key": key}, feature_path)
    receipt = {
        "status": "PHASE_A1_FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY",
        "protocol": contract["protocol"],
        "phase_a_identity": contract["phase_a_identity"],
        "contract_sha256": contract_sha,
        "authorization_sha256": sha256_file(feature_dir / "feature-extraction-authorization.json"),
        "selection_manifest_sha256": selection_sha,
        "source": {"run": str(args.run), "train_canonical_sha256": sha256_file(canonical_path)},
        "scope": {"path": str(scope_path), "sha256": sha256_file(scope_path), "content_sha256": scope_content_sha, "rows": len(scope), "neighborhoods": 5_000},
        "model": {"repo_id": adapter.MODEL_SPEC["repo_id"], "revision": adapter.MODEL_SPEC["revision"], "hidden_dim": 2048, "layer_count": 16, "backbone_frozen": True},
        "representation": {"feature_key": key, "pooling": "mean_full", "layer": "final", "exact_length": True, "single_row": True, "padding": False, "dtype": "float32"},
        "feature_tensor": {"path": str(feature_path), "sha256": sha256_file(feature_path), "tensor_sha256": tensor_sha256(feature_tensor), "shape": list(feature_tensor.shape), "bytes": feature_path.stat().st_size},
        "chunks": chunks,
        "smoke": {"status": "PASS", "repeat_max_abs_error": smoke_error},
        "runtime": {"device": args.device, "elapsed_seconds": time.perf_counter() - started, "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if args.device == "cuda" else 0},
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }
    write_json(receipt_path, receipt)
    del model
    if args.device == "cuda":
        torch.cuda.empty_cache()
    print(json.dumps({"status": receipt["status"], "rows": len(scope), "feature_sha256": receipt["feature_tensor"]["sha256"], "elapsed_seconds": round(receipt["runtime"]["elapsed_seconds"], 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

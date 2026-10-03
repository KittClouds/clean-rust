"""Extract frozen LFM features for the sealed held-out panel scope only."""

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
CONTRACT = ROOT / "experiments/jev-information-density-v08n/eval-panel-v01-contract.json"
ADAPTER = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
DEFAULT_MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tensor_sha256(tensor: torch.Tensor) -> str:
    return hashlib.sha256(tensor.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_eval_lfm_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load adapter: {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    scope_receipt = read_json(args.panel / "semantic-scope-receipt.json")
    scope_path = args.panel / "heldout-feature-scope.jsonl"
    scope = read_jsonl(scope_path)
    if scope_receipt["status"] != "V08N_HELDOUT_PANEL_SEMANTIC_SCOPE_PASS":
        raise RuntimeError("semantic held-out scope is not sealed")
    if len(scope) != 22_000 or any(row.get("partition") != "eval" for row in scope):
        raise RuntimeError("held-out feature scope drift")
    if scope_receipt["outputs"]["feature_scope"]["sha256"] != sha256_file(scope_path):
        raise RuntimeError("held-out scope hash drift")
    if contract["boundaries"]["head_load"] or contract["boundaries"]["head_training"] or contract["boundaries"]["evaluation_inference"]:
        raise RuntimeError("forbidden boundary drift")

    args.output.mkdir(parents=True, exist_ok=False)
    authorization = {
        "status": "V08N_HELDOUT_FEATURE_EXTRACTION_AUTHORIZED_FROZEN_BACKBONE_ONLY",
        "identity": contract["identity"],
        "contract_sha256": sha256_file(CONTRACT),
        "scope_sha256": sha256_file(scope_path),
        "scope_rows": len(scope),
        "model_repo_id": contract["representation"]["model_repo_id"],
        "model_revision": contract["representation"]["model_revision"],
        "pooling": contract["representation"]["pooling"],
        "input_mode": contract["representation"]["input_mode"],
        "head_load": False,
        "head_training": False,
        "evaluation_inference": False,
        "newtight_access": False,
        "legacy_evaluation_access": False,
        "phoenix_access": False,
        "panel_remains_locked": True,
    }
    write_json(args.output / "feature-extraction-authorization.json", authorization)

    adapter = load_adapter()
    if adapter.MODEL_SPEC["revision"] != contract["representation"]["model_revision"]:
        raise RuntimeError("LFM revision drift")
    tokenizer, model = adapter.load_model(args.model_root, args.device)
    if int(model.config.hidden_size) != 2048 or int(model.config.num_hidden_layers) != 16:
        raise RuntimeError("LFM architecture drift")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("backbone is not frozen")

    key = "mean_full@16"
    texts = [row["text"] for row in scope]
    smoke = texts[:4]
    first = adapter.encode_lfm_texts(model, tokenizer, smoke, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[key]
    second = adapter.encode_lfm_texts(model, tokenizer, smoke, ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[key]
    smoke_error = float((first - second).abs().max().cpu())
    if smoke_error != 0.0:
        raise RuntimeError(f"determinism smoke failure: {smoke_error}")

    started = time.perf_counter()
    chunk_dir = args.output / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_size = 128
    parts: list[torch.Tensor] = []
    chunks: list[dict[str, Any]] = []
    for start in range(0, len(texts), chunk_size):
        end = min(start + chunk_size, len(texts))
        features = adapter.encode_lfm_texts(model, tokenizer, texts[start:end], ["mean_full"], [16], 1, args.device, adapter.MODEL_SPEC)[key]
        if tuple(features.shape) != (end - start, 2048) or features.dtype != torch.float32:
            raise RuntimeError(f"feature shape/dtype drift: {start}:{end}")
        path = chunk_dir / f"features-{start:05d}-{end:05d}.pt"
        torch.save({"start": start, "end": end, "features": features.cpu().contiguous()}, path)
        parts.append(features.cpu().contiguous())
        chunks.append({"path": str(path), "sha256": sha256_file(path), "start": start, "end": end})
        print(json.dumps({"stage": "heldout_feature_chunk", "start": start, "end": end}, separators=(",", ":")), flush=True)

    tensor = torch.cat(parts, dim=0).to(torch.float32)
    feature_path = args.output / "heldout-features.pt"
    torch.save({"features": tensor, "scope_sha256": sha256_file(scope_path), "feature_key": key}, feature_path)
    receipt = {
        "status": "V08N_HELDOUT_FEATURE_CACHE_SEALED_FROZEN_BACKBONE_ONLY",
        "identity": contract["identity"],
        "contract_sha256": sha256_file(CONTRACT),
        "authorization_sha256": sha256_file(args.output / "feature-extraction-authorization.json"),
        "scope_sha256": sha256_file(scope_path),
        "scope_rows": len(scope),
        "model": {"repo_id": adapter.MODEL_SPEC["repo_id"], "revision": adapter.MODEL_SPEC["revision"], "hidden_dim": 2048, "layer_count": 16, "backbone_frozen": True},
        "representation": {"feature_key": key, "pooling": "mean_full", "layer": "final", "exact_length": True, "single_row": True, "padding": False, "dtype": "float32"},
        "feature_tensor": {"path": str(feature_path), "sha256": sha256_file(feature_path), "tensor_sha256": tensor_sha256(tensor), "shape": list(tensor.shape), "bytes": feature_path.stat().st_size},
        "chunks": chunks,
        "smoke": {"status": "PASS", "repeat_max_abs_error": smoke_error},
        "runtime": {"device": args.device, "elapsed_seconds": time.perf_counter() - started, "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if args.device == "cuda" else 0},
        "head_load": False,
        "head_training": False,
        "evaluation_inference": False,
        "newtight_access": False,
        "legacy_evaluation_access": False,
        "phoenix_access": False,
        "panel_remains_locked": True,
    }
    write_json(args.output / "heldout-feature-cache-receipt.json", receipt)
    del model
    if args.device == "cuda":
        torch.cuda.empty_cache()
    print(json.dumps({"status": receipt["status"], "rows": len(scope), "feature_sha256": receipt["feature_tensor"]["sha256"], "elapsed_seconds": round(receipt["runtime"]["elapsed_seconds"], 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

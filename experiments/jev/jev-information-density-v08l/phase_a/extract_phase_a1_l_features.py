"""Materialize training-only frozen LFM state features for v0.8L matching."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "experiments/jev-information-density-v08l/phase_a/phase-a-v01-contract.json"
OUT = Path(r"D:\codex-runs\jev-information-density-v08l\phase-a-v01-clean")
F100 = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\F100-groups.jsonl")
STATE_INPUTS = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\state-inputs.jsonl")
POOL = OUT / "candidate-pool.jsonl"
MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")
ADAPTER = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
CHUNK_SIZE = 256


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
    spec = importlib.util.spec_from_file_location("jev_v08l_lfm_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen LFM adapter: {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    contract = read_json(CONTRACT_PATH)
    summary = read_json(OUT / "candidate-pool-summary.json")
    require(summary["status"] == "PHASE_A0_CANDIDATE_POOL_READY_NO_MODEL_CONTACT", "Phase A0 is not ready")
    require(contract["boundaries"]["model_head_training"] is False, "head training boundary drift")
    require(contract["boundaries"]["evaluation_inference"] is False, "evaluation boundary drift")
    require(contract["boundaries"]["protected_evaluation_bodies"] is False, "protected boundary drift")
    require(sha256_file(POOL) == summary["candidate_pool_sha256"], "candidate pool changed after A0")

    primary = read_jsonl(F100)
    state_rows = read_jsonl(STATE_INPUTS)
    pool = read_jsonl(POOL)
    needed = {int(row["anchor_state_idx"]) for row in pool}
    needed.update(int(row["sham_state_idx"]) for row in pool)
    needed.update(int(row["candidate_state_idx"]) for row in pool)
    require(needed and max(needed) < len(state_rows), "state scope index drift")
    scope_source = [{"source_state_idx": index, "text": state_rows[index]["text"]} for index in sorted(needed)]
    scope_sha = hashlib.sha256(json.dumps(scope_source, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    feature_dir = OUT / "feature-cache"
    scope_path = feature_dir / "state-scope.jsonl"
    feature_path = feature_dir / "state-features.pt"
    receipt_path = feature_dir / "extraction-receipt.json"
    if receipt_path.exists() or feature_path.exists():
        raise FileExistsError("A1 feature cache already exists; refusing overwrite")
    feature_dir.mkdir(parents=True, exist_ok=True)
    with scope_path.open("w", encoding="utf-8", newline="\n") as stream:
        for index, row in enumerate(scope_source):
            stream.write(json.dumps({"index": index, **row}, ensure_ascii=False, separators=(",", ":")) + "\n")

    contract_hash = sha256_file(CONTRACT_PATH)
    authorization = {
        "status": "PHASE_A1_FEATURE_EXTRACTION_AUTHORIZED_TRAINING_ONLY",
        "protocol": contract["protocol"],
        "phase_a_identity": contract["phase_a_identity"],
        "contract_sha256": contract_hash,
        "source_scope": "training-only F100 states, sham states, and NOVEL candidate states",
        "primary_bank_sha256": sha256_file(F100),
        "candidate_pool_sha256": sha256_file(POOL),
        "scope_sha256": scope_sha,
        "model_repo_id": contract["representation_matching"]["model_repo_id"],
        "model_revision": contract["representation_matching"]["model_revision"],
        "representation": contract["representation_matching"],
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }
    write_json(feature_dir / "feature-extraction-authorization.json", authorization)

    adapter = load_adapter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer, model = adapter.load_model(MODEL_ROOT, device)
    require(adapter.MODEL_SPEC["revision"] == contract["representation_matching"]["model_revision"], "LFM revision drift")
    require(int(model.config.hidden_size) == 2048 and int(model.config.num_hidden_layers) == 16, "LFM architecture drift")
    require(all(not parameter.requires_grad for parameter in model.parameters()), "backbone is not frozen")
    key = "mean_full@16"
    smoke_values = [row["text"] for row in scope_source[: min(8, len(scope_source))]]
    smoke_one = adapter.encode_lfm_texts(model, tokenizer, smoke_values, ["mean_full"], [16], 1, device, adapter.MODEL_SPEC)[key]
    smoke_two = adapter.encode_lfm_texts(model, tokenizer, smoke_values, ["mean_full"], [16], 1, device, adapter.MODEL_SPEC)[key]
    smoke_error = float((smoke_one - smoke_two).abs().max().cpu()) if smoke_one.numel() else 0.0
    require(smoke_error == 0.0, f"repeated extraction drift: {smoke_error}")

    started = time.perf_counter()
    parts: list[torch.Tensor] = []
    chunks: list[dict[str, Any]] = []
    checkpoint_dir = feature_dir / "chunks"
    checkpoint_dir.mkdir(exist_ok=True)
    texts = [row["text"] for row in scope_source]
    for start in range(0, len(texts), CHUNK_SIZE):
        end = min(len(texts), start + CHUNK_SIZE)
        features = adapter.encode_lfm_texts(model, tokenizer, texts[start:end], ["mean_full"], [16], 1, device, adapter.MODEL_SPEC)[key]
        require(features.shape == (end - start, 2048) and features.dtype == torch.float32, f"feature shape/dtype drift: {start}:{end}")
        chunk_path = checkpoint_dir / f"states-{start:06d}-{end:06d}.pt"
        torch.save({"start": start, "end": end, "features": features.cpu().contiguous()}, chunk_path)
        parts.append(features.cpu())
        chunks.append({"path": str(chunk_path), "sha256": sha256_file(chunk_path), "start": start, "end": end})
        print(json.dumps({"stage": "feature_chunk", "start": start, "end": end}, separators=(",", ":")), flush=True)
    features = torch.cat(parts, dim=0).to(torch.float32)
    torch.save({"features": features, "scope_sha256": scope_sha, "feature_key": key}, feature_path)
    receipt = {
        "status": "PHASE_A1_FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY",
        "protocol": contract["protocol"],
        "phase_a_identity": contract["phase_a_identity"],
        "contract_sha256": contract_hash,
        "authorization_sha256": sha256_file(feature_dir / "feature-extraction-authorization.json"),
        "source_hashes": {"F100": sha256_file(F100), "candidate_pool": sha256_file(POOL), "state_inputs": sha256_file(STATE_INPUTS)},
        "scope": {"path": str(scope_path), "sha256": sha256_file(scope_path), "scope_content_sha256": scope_sha, "state_count": len(scope_source)},
        "model": {"repo_id": adapter.MODEL_SPEC["repo_id"], "revision": adapter.MODEL_SPEC["revision"], "hidden_dim": 2048, "layer_count": 16, "backbone_frozen": True},
        "representation": {"feature_key": key, "pooling": "mean_full", "layer": "final", "exact_length": True, "single_row": True, "padding": False, "dtype": "bfloat16_backbone_float32_features"},
        "feature_tensor": {"path": str(feature_path), "sha256": sha256_file(feature_path), "shape": list(features.shape), "tensor_sha256": tensor_sha256(features), "bytes": feature_path.stat().st_size},
        "chunks": chunks,
        "smoke": {"status": "PASS", "repeat_max_abs_error": smoke_error},
        "runtime": {"device": device, "elapsed_seconds": time.perf_counter() - started, "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if device == "cuda" else 0},
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }
    write_json(receipt_path, receipt)
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    print(json.dumps({"status": receipt["status"], "state_count": len(scope_source), "feature_sha256": receipt["feature_tensor"]["sha256"], "elapsed_seconds": round(receipt["runtime"]["elapsed_seconds"], 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

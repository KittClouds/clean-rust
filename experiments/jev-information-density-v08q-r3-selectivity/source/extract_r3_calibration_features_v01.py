"""Outcome-blind frozen-LFM feature extraction for R3 calibration only."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import tokenizers
import transformers


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02")
INPUTS = RUN / "calibration-inputs-v03"
PANEL = RUN / "calibration-panel-v02"
OUTPUT = RUN / "calibration-features-v01"
MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")
MODEL_DIR = MODEL_ROOT / "lfm2.5-1.2b-base"
ADAPTER = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
EXPECTED_ADAPTER_SHA256 = "b8cd79a9a3265eca0fde5f509ba7c058bc2065d7747efe17ff7c7c1f6335b2d0"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
FEATURE_KEY = "mean_full@16"
MODEL_FILES = {
    "config.json": "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185",
    "model.safetensors": "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff",
    "tokenizer.json": "d7a0ab0fc22e41ec8c6d7450a9ff9ce40e196ec5e5a2fa6a2105e064e0514ed7",
    "tokenizer_config.json": "8cba5b0c7acab23a0d4cc9ac587346c9220a1b6d288fc5346fe118202fd6f43e",
    "special_tokens_map.json": "742aefe2b7dec496e8caffdba03a75d0c1a9925d53bd3f3e0d388c96b591b6f4",
}
EXPECTED_INPUTS = {
    "panel": "6b813445b14bb8494962b2cc9b0cc8a229244177083c3a605d21ef4f880dbaef",
    "candidates": "cc45c81e2b6d70d222170872e9ddd96e1b48dfe90d26e588d319a34a7f101b33",
    "panel_receipt": "3a39f9d682096528e534ab4ddefd8516ce9de15abd5c1fbe8d4ff10947c28b64",
    "admissions": "4fa7d9c7b4ea5049ae39478240b93bf8932368fe04ad781b6ed0b11b079ccf0f",
    "rendered_denylist": "e78c28d14d745c32be65937442682f14fa798aaf4c9b5c6a5bacd94a9619bb86",
    "reverse_sham": "d75104b5574ea52ad62fb0c72c1e778dc7d4f3da76d678cf2cb756fb39ec40d0",
    "balanced_primary": "8c75354d6225762e275552fcf279d65fb4870f382405bdbbccc36576a950a859",
    "balanced_sham": "98ec35a78fbf2a65d050b1086bbf6337acaaae743cd4208af89107d235247617",
    "input_receipt": "be61d01bb9567bd76cdeb7e9980696ba961fa3e26749a5f334d486db26cd09b5",
    "training_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
}
CONTRACT_HASHES = {
    "run": "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6",
    "analysis": "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64",
    "panel": "a835b3d2934265b8f64ebd287e4dbf48f80ffe9bbbfcc1d6ed2650da69f63153",
}


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tensor_sha(tensor: torch.Tensor) -> str:
    return sha_bytes(tensor.detach().cpu().contiguous().numpy().tobytes(order="C"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")


def verify_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    paths = {
        "panel": PANEL / "calibration-panel-views.jsonl",
        "candidates": PANEL / "candidate-texts.jsonl",
        "panel_receipt": PANEL / "panel-generation-receipt.json",
        "admissions": PANEL / "candidate-admission-receipts.jsonl",
        "rendered_denylist": Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v01\calibration-exclusions-v01\full-rendered-input-hash-denylist.json"),
        "reverse_sham": INPUTS / "reverse-sham-texts.jsonl",
        "balanced_primary": INPUTS / "balanced-primary-occurrences.jsonl",
        "balanced_sham": INPUTS / "balanced-sham-events.jsonl",
        "input_receipt": INPUTS / "pretraining-input-validation-receipt.json",
        "training_features": Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache\shared-training-features.pt"),
        "candidate_features": Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01\feature-cache\candidate-features.pt"),
        "candidate_catalog": Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs\candidate-catalog.json"),
    }
    observed = {key: sha_file(path) for key, path in paths.items()}
    if observed != EXPECTED_INPUTS:
        raise RuntimeError(f"R3 calibration input binding mismatch: {observed}")
    contract_paths = {
        "run": ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-run-contract-v01.json",
        "analysis": ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-analysis-contract-v01.json",
        "panel": ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-panel-contract-v01.json",
    }
    contract_hashes = {key: sha_file(path) for key, path in contract_paths.items()}
    if contract_hashes != CONTRACT_HASHES:
        raise RuntimeError(f"R3 inherited contract identity mismatch: {contract_hashes}")
    panel = read_jsonl(paths["panel"])
    candidates = read_jsonl(paths["candidates"])
    reverse = read_jsonl(paths["reverse_sham"])
    if (len(panel), len(candidates), len(reverse)) != (4_000, 16, 2_500):
        raise RuntimeError("R3 calibration extraction input cardinality mismatch")
    if len({row["full_rendered_input_hash"] for row in panel}) != 4_000:
        raise RuntimeError("R3 calibration panel lost model-visible uniqueness")
    for row in panel:
        if sha_bytes(row["text"].encode("utf-8")) != row["full_rendered_input_hash"]:
            raise RuntimeError("R3 panel text/hash mismatch")
    for row in reverse:
        if sha_bytes(row["text"].encode("utf-8")) != row["input_sha256"]:
            raise RuntimeError("R3 reverse-SHAM text/hash mismatch")
    catalog = json.loads(paths["candidate_catalog"].read_text(encoding="utf-8"))
    candidate_index = {str(row["candidate_semantic_id"]): index for index, row in enumerate(catalog["rows"])}
    if len(candidate_index) != 48:
        raise RuntimeError("R3 training candidate catalog must have 48 unique semantic IDs")
    primary = read_jsonl(INPUTS / "balanced-primary-occurrences.jsonl")
    if len(primary) != 10_000 or any(
        row["candidate_indices"] != [candidate_index[item] for item in row["candidate_semantic_ids"]]
        for row in primary
    ):
        raise RuntimeError("R3 training sidecar candidate indices do not bind exact semantic IDs to the 48-row catalog")
    panel_receipt = json.loads(paths["panel_receipt"].read_text(encoding="utf-8"))
    if (panel_receipt.get("status") != "R3_CALIBRATION_PANEL_GENERATED_POLARITY_BALANCED"
            or panel_receipt.get("admitted_rendered_identity_count") != 4_000
            or panel_receipt.get("rendered_denylist_sha256") != EXPECTED_INPUTS["rendered_denylist"]):
        raise RuntimeError("R3 panel generator receipt status/count mismatch")
    return panel, candidates, reverse


def load_adapter() -> Any:
    if sha_file(ADAPTER) != EXPECTED_ADAPTER_SHA256:
        raise RuntimeError("pinned frozen LFM adapter hash mismatch")
    spec = importlib.util.spec_from_file_location("jev_v08q_r3_lfm_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load pinned LFM adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.MODEL_SPEC["revision"] != REVISION:
        raise RuntimeError("pinned LFM revision mismatch")
    return module


def model_parameter_sha(model: Any) -> str:
    digest = hashlib.sha256()
    for name, parameter in model.named_parameters():
        value = parameter.detach().to(device="cpu").contiguous()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(value.dtype).encode("ascii") + b"\0")
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii") + b"\0")
        digest.update(value.view(torch.uint8).numpy().tobytes(order="C"))
    return digest.hexdigest()


def verify_runtime() -> dict[str, Any]:
    if platform.python_version() != "3.13.15":
        raise RuntimeError(f"R3 runtime Python mismatch: {platform.python_version()}")
    if torch.__version__ != "2.11.0+cu128" or transformers.__version__ != "5.17.0" or tokenizers.__version__ != "0.23.2" or np.__version__ != "2.5.3":
        raise RuntimeError("R3 frozen extraction package version mismatch")
    if not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise RuntimeError("R3 frozen CUDA device unavailable or mismatched")
    if torch.version.cuda != "12.8" or list(torch.cuda.get_device_capability(0)) != [8, 6]:
        raise RuntimeError("R3 frozen CUDA runtime mismatch")
    observed = {name: sha_file(MODEL_DIR / name) for name in MODEL_FILES}
    if observed != MODEL_FILES:
        raise RuntimeError("R3 pinned LFM snapshot file hash mismatch")
    return {
        "python": platform.python_version(), "torch": torch.__version__,
        "transformers": transformers.__version__, "tokenizers": tokenizers.__version__,
        "numpy": np.__version__, "cuda": torch.version.cuda,
        "device": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
        "model_files_sha256": observed,
    }


def token_digest(token_ids: list[int]) -> str:
    encoded = json.dumps(token_ids, separators=(",", ":")).encode("ascii")
    return sha_bytes(encoded)


def encode_rows(adapter: Any, model: Any, tokenizer: Any, texts: list[str], device: str) -> torch.Tensor:
    parts: list[torch.Tensor] = []
    for start in range(0, len(texts), 128):
        end = min(start + 128, len(texts))
        result = adapter.encode_lfm_texts(
            model, tokenizer, texts[start:end], ["mean_full"], [16], 1, device, adapter.MODEL_SPEC
        )[FEATURE_KEY]
        if tuple(result.shape) != (end - start, 2048) or result.dtype != torch.float32 or not torch.isfinite(result).all():
            raise RuntimeError(f"R3 feature output invalid at rows {start}:{end}")
        parts.append(result.detach().cpu().contiguous())
        print(json.dumps({"stage": "r3_calibration_feature_chunk", "start": start, "end": end}), flush=True)
    return torch.cat(parts, dim=0)


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing existing feature output: {OUTPUT}")
    panel, candidates, reverse = verify_inputs()
    runtime = verify_runtime()
    adapter = load_adapter()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    panel_texts = [row["text"] for row in panel]
    candidate_texts = [row["text"] for row in candidates]
    reverse_texts = [row["text"] for row in reverse]
    all_texts = panel_texts + candidate_texts + reverse_texts
    tokenizer, model = adapter.load_model(MODEL_ROOT, "cuda")
    if int(model.config.hidden_size) != 2048 or int(model.config.num_hidden_layers) != 16:
        raise RuntimeError("R3 LFM architecture mismatch")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("R3 LFM is not frozen")
    tokenized = tokenizer(all_texts, add_special_tokens=True, padding=False, truncation=False)
    token_rows = tokenized["input_ids"]
    if len(token_rows) != len(all_texts) or any(not row or len(row) > 1024 for row in token_rows):
        raise RuntimeError("R3 extraction text has empty/overlong token sequence")
    token_records = [
        {"token_count": len(ids), "token_ids_sha256": token_digest(ids)} for ids in token_rows
    ]
    parameter_before = model_parameter_sha(model)
    smoke_texts = panel_texts[:8] + candidate_texts
    first = adapter.encode_lfm_texts(model, tokenizer, smoke_texts, ["mean_full"], [16], 1, "cuda", adapter.MODEL_SPEC)[FEATURE_KEY]
    second = adapter.encode_lfm_texts(model, tokenizer, smoke_texts, ["mean_full"], [16], 1, "cuda", adapter.MODEL_SPEC)[FEATURE_KEY]
    repeat_error = float((first - second).abs().max().cpu())
    if tuple(first.shape) != (24, 2048) or repeat_error > 1e-5:
        raise RuntimeError(f"R3 deterministic feature repeat failed: max_abs={repeat_error}")

    started = time.perf_counter()
    panel_features = encode_rows(adapter, model, tokenizer, panel_texts, "cuda")
    candidate_features = encode_rows(adapter, model, tokenizer, candidate_texts, "cuda")
    reverse_features = encode_rows(adapter, model, tokenizer, reverse_texts, "cuda")
    parameter_after = model_parameter_sha(model)
    after = {name: sha_file(MODEL_DIR / name) for name in MODEL_FILES}
    if parameter_after != parameter_before or after != runtime["model_files_sha256"]:
        raise RuntimeError("R3 frozen LFM identity changed during extraction")

    panel_path = OUTPUT / "calibration-panel-state-features.pt"
    candidate_path = OUTPUT / "calibration-candidate-features.pt"
    reverse_path = OUTPUT / "reverse-sham-state-features.pt"
    torch.save({"features": panel_features, "feature_key": FEATURE_KEY}, panel_path)
    torch.save({"features": candidate_features, "candidate_ids": [row["candidate_semantic_id"] for row in candidates], "feature_key": FEATURE_KEY}, candidate_path)
    torch.save({"features": reverse_features, "input_sha256": [row["input_sha256"] for row in reverse], "feature_key": FEATURE_KEY}, reverse_path)

    offset_candidate = len(panel)
    offset_reverse = offset_candidate + len(candidates)
    panel_manifest = [
        {"index": i, "neighborhood_id": row["neighborhood_id"], "family_slug": row["family_slug"],
         "direction": row["direction"], "view": row["view"], "episode_id": row["episode_id"],
         "input_sha256": row["full_rendered_input_hash"], "token_count": token_records[i]["token_count"],
         "token_ids_sha256": token_records[i]["token_ids_sha256"], "feature_sha256": tensor_sha(panel_features[i]),
         "feature_key": FEATURE_KEY}
        for i, row in enumerate(panel)
    ]
    candidate_manifest = [
        {"index": i, "candidate_semantic_id": row["candidate_semantic_id"], "family_slug": row["family_slug"],
         "text_sha256": row["text_sha256"], "token_count": token_records[offset_candidate + i]["token_count"],
         "token_ids_sha256": token_records[offset_candidate + i]["token_ids_sha256"],
         "feature_sha256": tensor_sha(candidate_features[i]), "feature_key": FEATURE_KEY}
        for i, row in enumerate(candidates)
    ]
    reverse_manifest = [
        {"index": i, "neighborhood_id": row["neighborhood_id"], "family_slug": row["family_slug"],
         "input_sha256": row["input_sha256"], "token_count": token_records[offset_reverse + i]["token_count"],
         "token_ids_sha256": token_records[offset_reverse + i]["token_ids_sha256"],
         "feature_sha256": tensor_sha(reverse_features[i]), "feature_key": FEATURE_KEY}
        for i, row in enumerate(reverse)
    ]
    write_jsonl(OUTPUT / "calibration-panel-feature-manifest.jsonl", panel_manifest)
    write_jsonl(OUTPUT / "candidate-feature-manifest.jsonl", candidate_manifest)
    write_jsonl(OUTPUT / "reverse-sham-feature-manifest.jsonl", reverse_manifest)
    receipt = {
        "status": "R3_PRETREATMENT_FEATURE_EXTRACTION_PASS",
        "extractor_sha256": sha_file(Path(__file__).resolve()),
        "model_revision": REVISION, "feature_key": FEATURE_KEY,
        "representation": {"pooling": "mean_full", "layer": "final", "exact_length": True,
            "single_row": True, "padding": False, "max_length": 1024,
            "backbone_dtype": "bfloat16", "output_dtype": "float32", "dimension": 2048},
        "runtime": runtime, "model_files_unchanged": True,
        "model_parameter_sha256_before": parameter_before,
        "model_parameter_sha256_after": parameter_after,
        "repeat_smoke": {"rows": 24, "max_abs_error": repeat_error, "tolerance": 1e-5,
            "pass": repeat_error <= 1e-5},
        "input_counts": {"panel_views": len(panel), "candidate_texts": len(candidates),
            "reverse_sham_texts": len(reverse), "total": len(all_texts)},
        "token_count_range": [min(item["token_count"] for item in token_records), max(item["token_count"] for item in token_records)],
        "feature_tensors": {
            "panel": {"path": str(panel_path), "sha256": sha_file(panel_path), "tensor_sha256": tensor_sha(panel_features), "shape": list(panel_features.shape)},
            "candidates": {"path": str(candidate_path), "sha256": sha_file(candidate_path), "tensor_sha256": tensor_sha(candidate_features), "shape": list(candidate_features.shape)},
            "reverse_sham": {"path": str(reverse_path), "sha256": sha_file(reverse_path), "tensor_sha256": tensor_sha(reverse_features), "shape": list(reverse_features.shape)},
        },
        "feature_manifests": {
            "panel_sha256": sha_file(OUTPUT / "calibration-panel-feature-manifest.jsonl"),
            "candidate_sha256": sha_file(OUTPUT / "candidate-feature-manifest.jsonl"),
            "reverse_sham_sha256": sha_file(OUTPUT / "reverse-sham-feature-manifest.jsonl"),
        },
        "elapsed_seconds": time.perf_counter() - started,
        "head_loaded": False, "training": False, "inference": False,
        "treatment_metrics": False, "confirmatory_panel": False,
    }
    write_json(OUTPUT / "feature-extraction-receipt.json", receipt)
    del model
    torch.cuda.empty_cache()
    print(json.dumps({"status": receipt["status"], "input_counts": receipt["input_counts"],
        "repeat_max_abs_error": repeat_error, "elapsed_seconds": round(receipt["elapsed_seconds"], 1)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

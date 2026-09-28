"""Extract/seal R3 evaluation and balanced-training-only SHAM features."""

from __future__ import annotations

import hashlib
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
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
PANEL = RUN / "panel-v03"
INPUTS = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-inputs-v03")
FEATURES = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache\shared-training-features.pt")
CANDIDATES = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01\feature-cache\candidate-features.pt")
MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")
MODEL_DIR = MODEL_ROOT / "lfm2.5-1.2b-base"
ADAPTER = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
EXPECTED_ADAPTER_SHA256 = "b8cd79a9a3265eca0fde5f509ba7c058bc2065d7747efe17ff7c7c1f6335b2d0"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
FEATURE_KEY = "mean_full@16"
INPUT_HASHES = {
    "reverse_sham": "d75104b5574ea52ad62fb0c72c1e778dc7d4f3da76d678cf2cb756fb39ec40d0",
    "training_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
}
MODEL_FILES = {
    "config.json": "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185",
    "model.safetensors": "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff",
    "tokenizer.json": "d7a0ab0fc22e41ec8c6d7450a9ff9ce40e196ec5e5a2fa6a2105e064e0514ed7",
    "tokenizer_config.json": "8cba5b0c7acab23a0d4cc9ac587346c9220a1b6d288fc5346fe118202fd6f43e",
    "special_tokens_map.json": "742aefe2b7dec496e8caffdba03a75d0c1a9925d53bd3f3e0d388c96b591b6f4",
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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def load_adapter() -> Any:
    if sha_file(ADAPTER) != EXPECTED_ADAPTER_SHA256:
        raise RuntimeError("pinned frozen LFM adapter identity mismatch")
    import importlib.util
    spec = importlib.util.spec_from_file_location("jev_r3_confirmatory_lfm_adapter", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned LFM adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.MODEL_SPEC["revision"] != REVISION:
        raise RuntimeError("pinned LFM revision mismatch")
    return module


def model_parameter_sha(model: Any) -> str:
    digest = hashlib.sha256()
    for name, parameter in model.named_parameters():
        value = parameter.detach().cpu().contiguous()
        digest.update(name.encode() + b"\0" + str(value.dtype).encode() + b"\0")
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode() + b"\0")
        digest.update(value.view(torch.uint8).numpy().tobytes(order="C"))
    return digest.hexdigest()


def verify_runtime() -> dict[str, Any]:
    if platform.python_version() != "3.13.15" or torch.__version__ != "2.11.0+cu128":
        raise RuntimeError("R3 extraction Python/PyTorch runtime mismatch")
    if transformers.__version__ != "5.17.0" or tokenizers.__version__ != "0.23.2" or np.__version__ != "2.5.3":
        raise RuntimeError("R3 extraction package version mismatch")
    if (not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080"
            or torch.version.cuda != "12.8" or list(torch.cuda.get_device_capability(0)) != [8, 6]):
        raise RuntimeError("R3 pinned CUDA device/runtime mismatch")
    observed = {name: sha_file(MODEL_DIR / name) for name in MODEL_FILES}
    if observed != MODEL_FILES:
        raise RuntimeError("pinned LFM model files changed")
    return {"python": platform.python_version(), "torch": torch.__version__,
        "transformers": transformers.__version__, "tokenizers": tokenizers.__version__,
        "numpy": np.__version__, "cuda": torch.version.cuda, "device": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)), "model_files_sha256": observed}


def token_digest(ids: list[int]) -> str:
    return sha_bytes(json.dumps(ids, separators=(",", ":")).encode("ascii"))


def encode(adapter: Any, model: Any, tokenizer: Any, texts: list[str]) -> torch.Tensor:
    chunks: list[torch.Tensor] = []
    for start in range(0, len(texts), 128):
        end = min(start + 128, len(texts))
        value = adapter.encode_lfm_texts(model, tokenizer, texts[start:end], ["mean_full"], [16], 1, "cuda", adapter.MODEL_SPEC)[FEATURE_KEY]
        if tuple(value.shape) != (end - start, 2048) or value.dtype != torch.float32 or not bool(torch.isfinite(value).all()):
            raise RuntimeError(f"invalid LFM feature block {start}:{end}")
        chunks.append(value.detach().cpu().contiguous())
        print(json.dumps({"stage": "r3_feature_rows", "start": start, "end": end}), flush=True)
    return torch.cat(chunks, dim=0).contiguous()


def verify_panel_sources() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    seal_path = PANEL / "seals/r3-panel-seal-v01.json"
    seal = read_json(seal_path)
    if seal.get("status") != "R3_V03_PANEL_SEALED_FEATURE_EXTRACTION_PENDING" or seal.get("head_initialization") is not False:
        raise RuntimeError("R3 panel seal state does not permit feature extraction")
    seal_body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(seal["entries"], key=lambda item: item["path"]))
    if hashlib.sha256(seal_body.encode()).hexdigest() != seal.get("entries_root_sha256"):
        raise RuntimeError("R3 panel seal entry root is malformed")
    entries = {row["path"]: row["sha256"] for row in seal["entries"]}
    required = ("r3-panel-inference-manifest.jsonl", "r3-panel-texts-target-free-v01.jsonl", "candidate-texts.jsonl")
    for name in required:
        path = PANEL / name
        if name not in entries or sha_file(path) != entries[name]:
            raise RuntimeError(f"target-free sealed feature input mismatch: {name}")
    if sha_file(INPUTS / "reverse-sham-texts.jsonl") != INPUT_HASHES["reverse_sham"]:
        raise RuntimeError("reverse SHAM source identity mismatch")
    inference = read_jsonl(PANEL / required[0])
    texts = read_jsonl(PANEL / required[1])
    candidates = read_jsonl(PANEL / required[2])
    reverse = read_jsonl(INPUTS / "reverse-sham-texts.jsonl")
    if len(inference) != 4_000 or len(texts) != 4_000 or len(candidates) != 16 or len(reverse) != 2_500:
        raise RuntimeError("R3 target-free feature input cardinality mismatch")
    if [row["row_index"] for row in inference] != list(range(4_000)) or [row["row_index"] for row in texts] != list(range(4_000)):
        raise RuntimeError("R3 feature row order is not dense/canonical")
    for meta, item in zip(inference, texts, strict=True):
        if meta["row_index"] != item["row_index"] or meta["full_rendered_input_hash"] != item["full_rendered_input_hash"]:
            raise RuntimeError("R3 text/inference manifest identity join mismatch")
        if sha_bytes(item["text"].encode("utf-8")) != item["full_rendered_input_hash"]:
            raise RuntimeError("R3 model-visible input hash mismatch")
    for row in reverse:
        if sha_bytes(row["text"].encode("utf-8")) != row["input_sha256"]:
            raise RuntimeError("reverse SHAM text hash mismatch")
    if sha_file(FEATURES) != INPUT_HASHES["training_features"] or sha_file(CANDIDATES) != INPUT_HASHES["candidate_features"]:
        raise RuntimeError("sealed training/candidate feature cache identity mismatch")
    return inference, texts, candidates, {"panel_seal_sha256": sha_file(seal_path), "reverse": reverse}


def main() -> int:
    if len(sys.argv) != 2:
        raise RuntimeError("usage: extract_r3_confirmatory_features_v01.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1])
    if output.exists():
        raise RuntimeError(f"refusing existing feature output: {output}")
    inference, panel_rows, candidates, extra = verify_panel_sources()
    reverse = extra.pop("reverse")
    runtime = verify_runtime()
    adapter = load_adapter()
    output.mkdir(parents=True, exist_ok=False)
    panel_texts = [row["text"] for row in panel_rows]
    candidate_texts = [row["text"] for row in candidates]
    reverse_texts = [row["text"] for row in reverse]
    all_texts = panel_texts + candidate_texts + reverse_texts
    tokenizer, model = adapter.load_model(MODEL_ROOT, "cuda")
    if int(model.config.hidden_size) != 2048 or int(model.config.num_hidden_layers) != 16:
        raise RuntimeError("pinned LFM architecture mismatch")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("pinned LFM backbone is not frozen")
    token_rows = tokenizer(all_texts, add_special_tokens=True, padding=False, truncation=False)["input_ids"]
    if len(token_rows) != len(all_texts) or any(not row or len(row) > 1024 for row in token_rows):
        raise RuntimeError("empty or overlong exact-length tokenization")
    token_rows_meta = [{"token_count": len(ids), "token_ids_sha256": token_digest(ids)} for ids in token_rows]
    before = model_parameter_sha(model)
    started = time.perf_counter()
    panel_features = encode(adapter, model, tokenizer, panel_texts)
    candidate_features = encode(adapter, model, tokenizer, candidate_texts)
    reverse_features = encode(adapter, model, tokenizer, reverse_texts)
    after = model_parameter_sha(model)
    current_files = {name: sha_file(MODEL_DIR / name) for name in MODEL_FILES}
    if before != after or current_files != runtime["model_files_sha256"]:
        raise RuntimeError("pinned LFM identity changed during extraction")

    tensors = {
        "r3-panel-state-features.pt": {"features": panel_features, "feature_key": FEATURE_KEY},
        "r3-candidate-features.pt": {"features": candidate_features,
            "candidate_ids": [row["candidate_semantic_id"] for row in candidates], "feature_key": FEATURE_KEY},
        "reverse-sham-state-features.pt": {"features": reverse_features,
            "input_sha256": [row["input_sha256"] for row in reverse], "feature_key": FEATURE_KEY},
    }
    for name, payload in tensors.items():
        torch.save(payload, output / name)
    panel_manifest = [{"row_index": i, "neighborhood_id": row["neighborhood_id"],
        "family_slug": row["family_slug"], "direction": row["direction"], "view": row["view"],
        "input_sha256": row["full_rendered_input_hash"], "token_count": token_rows_meta[i]["token_count"],
        "token_ids_sha256": token_rows_meta[i]["token_ids_sha256"], "feature_sha256": tensor_sha(panel_features[i]),
        "feature_key": FEATURE_KEY} for i, row in enumerate(inference)]
    off_candidate, off_reverse = len(panel_texts), len(panel_texts) + len(candidate_texts)
    candidate_manifest = [{"index": i, "candidate_semantic_id": row["candidate_semantic_id"],
        "family_slug": row["family_slug"], "text_sha256": row["text_sha256"],
        "token_count": token_rows_meta[off_candidate + i]["token_count"],
        "token_ids_sha256": token_rows_meta[off_candidate + i]["token_ids_sha256"],
        "feature_sha256": tensor_sha(candidate_features[i]), "feature_key": FEATURE_KEY}
        for i, row in enumerate(candidates)]
    reverse_manifest = [{"index": i, "neighborhood_id": row["neighborhood_id"],
        "family_slug": row["family_slug"], "input_sha256": row["input_sha256"],
        "token_count": token_rows_meta[off_reverse + i]["token_count"],
        "token_ids_sha256": token_rows_meta[off_reverse + i]["token_ids_sha256"],
        "feature_sha256": tensor_sha(reverse_features[i]), "feature_key": FEATURE_KEY}
        for i, row in enumerate(reverse)]
    for name, values in (("r3-panel-feature-manifest.jsonl", panel_manifest),
        ("candidate-feature-manifest.jsonl", candidate_manifest), ("reverse-sham-feature-manifest.jsonl", reverse_manifest)):
        write_jsonl(output / name, values)
    receipt = {
        "status": "R3_V03_FEATURE_EXTRACTION_PASS", "extractor_sha256": sha_file(Path(__file__).resolve()),
        "panel_seal": extra["panel_seal_sha256"], "model_revision": REVISION, "feature_key": FEATURE_KEY,
        "extraction_contract": {"pooling": "mean_full", "layer": "final", "exact_length": True,
            "single_row": True, "padding": False, "backbone_dtype": "bfloat16", "output_dtype": "float32", "dimension": 2048},
        "runtime": runtime, "model_parameter_sha256_before": before, "model_parameter_sha256_after": after,
        "model_files_unchanged": True, "input_counts": {"panel_rows": len(panel_texts),
            "candidate_texts": len(candidate_texts), "reverse_sham_texts": len(reverse), "total": len(all_texts)},
        "token_count_range": [min(row["token_count"] for row in token_rows_meta), max(row["token_count"] for row in token_rows_meta)],
        "features": {name: {"sha256": sha_file(output / name), "tensor_sha256": tensor_sha(data["features"]),
            "shape": list(data["features"].shape)} for name, data in tensors.items()},
        "manifests": {name: sha_file(output / name) for name in
            ("r3-panel-feature-manifest.jsonl", "candidate-feature-manifest.jsonl", "reverse-sham-feature-manifest.jsonl")},
        "elapsed_seconds": time.perf_counter() - started, "targets_read": False,
        "head_initialized": False, "training": False, "inference": False, "treatment_metrics": False,
    }
    write_json(output / "feature-extraction-receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "rows": receipt["input_counts"],
        "elapsed_seconds": round(receipt["elapsed_seconds"], 1), "targets_read": False}, indent=2), flush=True)
    del model
    torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

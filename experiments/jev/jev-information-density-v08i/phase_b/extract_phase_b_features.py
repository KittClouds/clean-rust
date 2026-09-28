"""Frozen LFM extraction for Phase B; exact-length, batch-one, no padding."""

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
PHASE_B = Path(__file__).resolve().parent
CONTRACT = PHASE_B / "phase-b-v01-contract.json"
RUN = Path(r"D:\codex-runs\jev-information-density-v08i\phase-b-v01")
V07 = Path(r"D:\codex-runs\jev-lfm-variable-v07")
INPUTS = RUN / "inputs"
FEATURE_DIR = RUN / "feature-cache"
FEATURE_KEY = "mean_full@16"
CHUNK_ROWS = 256


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_frozen_code(auth: dict[str, Any]) -> None:
    for relative, expected in auth["source_code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"frozen implementation drift: {relative}")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load pinned LFM adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_texts(path: Path) -> list[str]:
    output = []
    with path.open("r", encoding="utf-8") as stream:
        for expected, line in enumerate(stream):
            row = json.loads(line)
            if row.get("index") != expected or not isinstance(row.get("text"), str):
                raise ValueError(f"invalid indexed text at {path}:{expected + 1}")
            output.append(row["text"])
    return output


def encode_table(reference: Any, model: Any, tokenizer: Any, values: list[str], device: str,
                 name: str, checkpoint_root: Path) -> tuple[torch.Tensor, dict[str, Any]]:
    layer_count = int(model.config.num_hidden_layers)
    parts: list[torch.Tensor] = []
    chunk_receipts = []
    started = time.perf_counter()
    for start in range(0, len(values), CHUNK_ROWS):
        end = min(len(values), start + CHUNK_ROWS)
        path = checkpoint_root / f"{name}-{start:06d}-{end:06d}.pt"
        if path.exists():
            checkpoint = torch.load(path, map_location="cpu", weights_only=True)
            if checkpoint.get("start") != start or checkpoint.get("end") != end:
                raise ValueError(f"wrong extraction chunk bounds: {path}")
            features = checkpoint["features"]
        else:
            features = reference.encode_lfm_texts(
                model, tokenizer, values[start:end], ["mean_full"], [layer_count],
                1, device, reference.MODEL_SPEC,
            )[f"mean_full@{layer_count}"]
            if features.ndim != 2 or features.shape != (end - start, int(model.config.hidden_size)):
                raise ValueError(f"feature shape mismatch for {name}:{start}-{end}")
            temp = path.with_suffix(".pt.tmp")
            torch.save({"start": start, "end": end, "features": features.cpu().contiguous()}, temp)
            temp.replace(path)
        parts.append(features.cpu())
        chunk_receipts.append({"path": str(path), "sha256": sha256_file(path), "start": start, "end": end})
        print(json.dumps({"event": "feature_chunk", "table": name, "start": start,
                          "end": end, "chunk_count": len(chunk_receipts),
                          "elapsed_seconds": round(time.perf_counter() - started, 3)}, separators=(",", ":")), flush=True)
    merged = torch.cat(parts, dim=0).to(torch.float32) if parts else torch.empty((0, int(model.config.hidden_size)))
    return merged, {"name": name, "count": len(values), "chunks": chunk_receipts,
                    "elapsed_seconds": time.perf_counter() - started}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")

    auth_path = RUN / "preflight/model-contact-authorization.json"
    inputs_receipt_path = INPUTS / "phase-b-inputs-receipt.json"
    auth = read_json(auth_path)
    inputs = read_json(inputs_receipt_path)
    contract_hash = sha256_file(CONTRACT)
    if auth.get("status") != "PASS" or auth.get("model_contact_authorized") is not True:
        raise RuntimeError("preflight does not authorize model contact")
    if auth.get("contract_sha256") != contract_hash or inputs.get("contract_sha256") != contract_hash:
        raise RuntimeError("Phase-B contract changed after preflight/materialization")
    verify_frozen_code(auth)
    for item in inputs["input_tables"].values():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise RuntimeError(f"Phase-B materialized input changed: {item['path']}")

    state_texts = read_texts(Path(inputs["input_tables"]["state_inputs"]["path"]))
    candidate_texts = read_texts(Path(inputs["input_tables"]["candidate_inputs"]["path"]))
    feature_dir = FEATURE_DIR
    checkpoint_dir = feature_dir / "chunks"
    binding_path = feature_dir / "extraction-run-binding.json"
    feature_path = feature_dir / "phase-b-train-features.pt"
    feature_receipt_path = feature_dir / "extraction-receipt.json"
    adapter_path = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
    run_binding = {
        "contract_sha256": contract_hash,
        "authorization_receipt_sha256": sha256_file(auth_path),
        "inputs_receipt_sha256": sha256_file(inputs_receipt_path),
        "state_table_sha256": inputs["input_tables"]["state_inputs"]["sha256"],
        "candidate_table_sha256": inputs["input_tables"]["candidate_inputs"]["sha256"],
        "adapter_sha256": sha256_file(adapter_path),
        "model_revision": read_json(CONTRACT)["model"]["revision"],
        "device": args.device,
        "chunk_rows": CHUNK_ROWS,
        "batch_size": 1,
        "padding": False,
    }
    feature_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    if feature_receipt_path.exists():
        raise FileExistsError("completed Phase-B feature extraction is sealed; refusing overwrite")
    if binding_path.exists():
        if read_json(binding_path) != run_binding:
            raise RuntimeError("partial feature cache belongs to a different frozen run")
    else:
        if any(feature_dir.glob("phase-b-train-features.pt")) or feature_receipt_path.exists():
            raise FileExistsError("feature cache exists without matching run binding")
        binding_path.write_text(json.dumps(run_binding, indent=2) + "\n", encoding="utf-8")

    reference = load_module("jev_lfm_extract_v07_phase_b", adapter_path)
    if reference.MODEL_SPEC["revision"] != run_binding["model_revision"]:
        raise RuntimeError("pinned v0.7 adapter revision differs from Phase-B contract")
    tokenizer, model = reference.load_model(V07 / "models", args.device)
    if int(model.config.hidden_size) != 2048 or int(model.config.num_hidden_layers) != 16:
        raise RuntimeError("loaded LFM architecture dimensions drifted")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("backbone was not fully frozen")

    smoke_texts = state_texts[: min(8, len(state_texts))] + candidate_texts[: min(8, len(candidate_texts))]
    smoke_one = reference.encode_lfm_texts(
        model, tokenizer, smoke_texts, ["mean_full"], [16], 1, args.device, reference.MODEL_SPEC,
    )[FEATURE_KEY]
    smoke_two = reference.encode_lfm_texts(
        model, tokenizer, smoke_texts, ["mean_full"], [16], 1, args.device, reference.MODEL_SPEC,
    )[FEATURE_KEY]
    smoke_error = float((smoke_one - smoke_two).abs().max().cpu()) if smoke_one.numel() else 0.0
    if smoke_error != 0.0:
        raise RuntimeError(f"exact-input LFM repeated extraction drifted: {smoke_error}")

    started = time.perf_counter()
    state_features, state_receipt = encode_table(
        reference, model, tokenizer, state_texts, args.device, "states", checkpoint_dir,
    )
    candidate_features, candidate_receipt = encode_table(
        reference, model, tokenizer, candidate_texts, args.device, "candidates-name_definition", checkpoint_dir,
    )
    if state_features.shape != (len(state_texts), 2048) or candidate_features.shape != (len(candidate_texts), 2048):
        raise RuntimeError("merged Phase-B feature tensor shape mismatch")

    cache = {
        "repo_id": reference.MODEL_SPEC["repo_id"],
        "revision": reference.MODEL_SPEC["revision"],
        "hidden_dim": 2048,
        "layer_count": 16,
        "pooling": "mean_full",
        "layer": "final",
        "dtype": "float32",
        "backbone_frozen": True,
        "features": {
            "state": {FEATURE_KEY: state_features.contiguous()},
            "candidate": {"name_definition": {FEATURE_KEY: candidate_features.contiguous()}},
        },
    }
    temporary = feature_path.with_suffix(".pt.tmp")
    torch.save(cache, temporary)
    temporary.replace(feature_path)
    receipt = {
        "protocol": read_json(CONTRACT)["protocol"],
        "status": "FEATURE_EXTRACTION_COMPLETE",
        "contract_sha256": contract_hash,
        "authorization_receipt_sha256": sha256_file(auth_path),
        "inputs_receipt_sha256": sha256_file(inputs_receipt_path),
        "model": {"repo_id": reference.MODEL_SPEC["repo_id"], "revision": reference.MODEL_SPEC["revision"],
                  "hidden_dim": 2048, "layer_count": 16, "backbone_frozen": True},
        "path": {"implementation": str(adapter_path), "implementation_sha256": sha256_file(adapter_path),
                 "pooling": "mean_full", "layer": "final", "batch_size": 1, "padding": False,
                 "max_length": 1024, "dtype": "bfloat16_backbone_float32_features"},
        "smoke": {"status": "PASS", "text_count": len(smoke_texts), "repeat_max_abs_error": smoke_error,
                  "input_path": "exact-length, single-row, no padding"},
        "input_counts": {"state_texts": len(state_texts), "candidate_name_definition_texts": len(candidate_texts)},
        "feature_shape": {"state": list(state_features.shape), "candidate": list(candidate_features.shape),
                          "all_float32": state_features.dtype == torch.float32 and candidate_features.dtype == torch.float32},
        "tables": {"state": state_receipt, "candidate_name_definition": candidate_receipt},
        "feature_cache": {"path": str(feature_path), "sha256": sha256_file(feature_path),
                          "bytes": feature_path.stat().st_size},
        "runtime": {"device": args.device, "elapsed_seconds": time.perf_counter() - started,
                    "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if args.device.startswith("cuda") else 0},
        "training": False,
        "evaluation_inference": False,
        "phoenix_access": False,
    }
    feature_receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "state_texts": len(state_texts),
                      "candidate_texts": len(candidate_texts), "feature_sha256": receipt["feature_cache"]["sha256"],
                      "elapsed_seconds": round(receipt["runtime"]["elapsed_seconds"], 2)}, separators=(",", ":")), flush=True)
    del model
    if args.device.startswith("cuda"):
        torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Authorized first model-contact operation: extract the 48 fixed candidates."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import math
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
INPUTS = RUN / "phase-b-v03-inputs"
PACKET = RUN / "phase-b-authorization-packet-v01"
MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")
ADAPTER = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha256(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_adapter(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("jev_v08n_lfm_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load pinned LFM adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run() -> dict[str, Any]:
    contract_path = PHASE / "phase-b-run-contract-v01.json"
    contract = read_json(contract_path)
    auth_path = PHASE / "phase-b-authorization-event-v01.json"
    auth = read_json(auth_path)
    if auth.get("status") != "PHASE_B_AUTHORIZED" or auth.get("phase_b_authorized") is not True:
        raise RuntimeError("candidate extraction is not explicitly authorized")
    if sha256_file(contract_path) != auth["bindings"]["run_contract"]["sha256"]:
        raise RuntimeError("run contract hash drift before first model contact")
    if sha256_file(PHASE / "phase-b-analysis-contract-v01.json") != auth["bindings"]["analysis_contract"]["sha256"]:
        raise RuntimeError("analysis contract hash drift before first model contact")
    for relative, expected in auth["implementation_bindings"].items():
        if sha256_file(ROOT / relative) != expected:
            raise RuntimeError(f"authorized implementation drift: {relative}")

    extraction = contract["candidate_feature_extraction"]
    input_path = PACKET / "candidate-model-input-manifest.jsonl"
    catalog_path = INPUTS / "candidate-catalog.json"
    if sha256_file(input_path) != extraction["candidate_text_manifest_sha256"]:
        raise RuntimeError("candidate text manifest hash mismatch")
    if sha256_file(catalog_path) != extraction["parent_candidate_catalog_sha256"]:
        raise RuntimeError("candidate catalog hash mismatch")
    rows = read_jsonl(input_path)
    catalog = read_json(catalog_path)
    ids = [row["candidate_semantic_id"] for row in rows]
    if len(rows) != 48 or ids != sorted(ids) or len(set(ids)) != 48:
        raise RuntimeError("candidate list count/order/identity mismatch")
    if [row["candidate_semantic_id"] for row in catalog["rows"]] != ids:
        raise RuntimeError("candidate catalog and model-input manifest order differ")
    if any(row.get("index") != i or row.get("profile") != "name_definition" for i, row in enumerate(rows)):
        raise RuntimeError("candidate input indices/profile differ from contract")
    texts = [row["model_input_text"] for row in rows]
    for row, text in zip(rows, texts):
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual != row["model_input_utf8_sha256"]:
            raise RuntimeError(f"candidate text hash mismatch: {row['candidate_semantic_id']}")
        catalog_row = catalog["rows"][row["index"]]
        expected_text = catalog_row["name"] + " — " + catalog_row["description"]
        if text != expected_text:
            raise RuntimeError(f"candidate text serialization mismatch: {row['candidate_semantic_id']}")

    model_cfg = contract["model_and_representation"]
    model_dir = Path(model_cfg["snapshot_directory"])
    for name, expected in model_cfg["snapshot_file_sha256"].items():
        path = model_dir / name
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"pinned model snapshot file mismatch: {name}")
    adapter_expected = model_cfg["extractor_sha256"]
    if sha256_file(ADAPTER) != adapter_expected:
        raise RuntimeError("pinned extraction adapter hash mismatch")

    runtime = contract["runtime_environment"]
    actual_runtime = {
        "python": ".".join(map(str, sys.version_info[:3])), "torch": torch.__version__,
        "transformers": metadata.version("transformers"), "tokenizers": metadata.version("tokenizers"),
        "numpy": metadata.version("numpy"), "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "compute_capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
    }
    for key, value in actual_runtime.items():
        if value != runtime[key]:
            raise RuntimeError(f"runtime mismatch before first model load: {key}={value!r}; expected {runtime[key]!r}")
    if not torch.cuda.is_available():
        raise RuntimeError("frozen CUDA device unavailable")
    if torch.backends.cuda.matmul.allow_tf32 is not False:
        raise RuntimeError("TF32 matmul must be disabled")

    # Tokenizer inspection is part of this authorized candidate-extraction operation.
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, use_fast=True, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token or tokenizer.unk_token
    token_counts = [len(tokenizer.encode(text, add_special_tokens=True)) for text in texts]
    if any(count > model_cfg["maximum_length"] for count in token_counts):
        raise RuntimeError("candidate input would truncate; abort without changing serialization")

    out = contract["output"]["candidate_feature_artifacts"]
    final_dir = Path(out["directory"])
    final_paths = [Path(out[k]) for k in ("tensor_path", "token_length_receipt_path", "feature_receipt_path")]
    if final_dir.exists() or any(path.exists() for path in final_paths):
        raise FileExistsError("candidate output path already exists; refusing overwrite")
    run_root = Path(contract["output"]["root"])
    if run_root.exists():
        existing = {path.name for path in run_root.iterdir()}
        if existing - {"failed-attempts"}:
            raise FileExistsError(f"unexpected artifacts in the reserved run root: {sorted(existing)}")
    else:
        run_root.mkdir(parents=True, exist_ok=False)
    failed_root = run_root / "failed-attempts"
    failed_root.mkdir(parents=True, exist_ok=True)
    attempt = failed_root / f"candidate-extraction-{uuid.uuid4().hex}"
    attempt.mkdir(parents=True, exist_ok=False)

    started = time.perf_counter()
    try:
        adapter = load_adapter(ADAPTER)
        if adapter.MODEL_SPEC["revision"] != model_cfg["revision"]:
            raise RuntimeError("adapter/model revision mismatch")
        tokenizer, model = adapter.load_model(MODEL_ROOT, "cuda")
        if int(model.config.hidden_size) != 2048 or int(model.config.num_hidden_layers) != 16:
            raise RuntimeError("loaded candidate model architecture mismatch")
        if any(param.requires_grad for param in model.parameters()):
            raise RuntimeError("LFM backbone is not frozen")
        features = adapter.encode_lfm_texts(
            model, tokenizer, texts, ["mean_full"], [16], 1, "cuda", adapter.MODEL_SPEC,
        )["mean_full@16"].detach().cpu().contiguous().to(torch.float32)
        if tuple(features.shape) != (48, 2048) or not torch.isfinite(features).all().item():
            raise RuntimeError("candidate feature tensor shape/dtype/finite check failed")
        tensor_file = attempt / "candidate-features.pt"
        torch.save(features, tensor_file)
        loaded = torch.load(tensor_file, map_location="cpu", weights_only=True)
        if loaded.dtype != torch.float32 or loaded.shape != (48, 2048) or tensor_sha256(loaded) != tensor_sha256(features):
            raise RuntimeError("serialized candidate tensor parity check failed")

        sorted_counts = sorted(token_counts)
        token_receipt = {
            "status": "PASS_NO_TRUNCATION", "candidate_manifest_sha256": sha256_file(input_path),
            "count": len(rows), "per_candidate": [
                {"index": row["index"], "candidate_semantic_id": row["candidate_semantic_id"], "token_count": count}
                for row, count in zip(rows, token_counts)
            ],
            "summary": {"min": sorted_counts[0], "median": (sorted_counts[23] + sorted_counts[24]) / 2,
                        "p95_nearest_rank": sorted_counts[math.ceil(0.95 * len(sorted_counts)) - 1], "max": sorted_counts[-1]},
            "tokenizer_snapshot_hashes": model_cfg["snapshot_file_sha256"], "truncation": False,
        }
        token_path = attempt / "candidate-token-lengths.json"
        write_json(token_path, token_receipt)
        feature_receipt = {
            "status": "CANDIDATE_FEATURES_VALIDATED", "protocol": contract["protocol"],
            "authorization_event_sha256": sha256_file(auth_path),
            "run_contract_sha256": sha256_file(contract_path),
            "model": {"repo_id": model_cfg["repo_id"], "revision": model_cfg["revision"], "snapshot_sha256": model_cfg["snapshot_file_sha256"]},
            "extractor": {"path": str(ADAPTER), "sha256": sha256_file(ADAPTER), "pooling": "final-layer mean_full", "batch_size": 1, "exact_length": True, "padding": False, "max_length": 1024, "backbone_dtype": "bfloat16", "feature_dtype": "float32"},
            "input_manifest_sha256": sha256_file(input_path), "catalog_sha256": sha256_file(catalog_path),
            "token_length_receipt_sha256": sha256_file(token_path), "semantic_ids": ids,
            "shape": list(features.shape), "dtype": str(features.dtype), "contiguous": features.is_contiguous(),
            "tensor_sha256": tensor_sha256(features), "feature_file_sha256": sha256_file(tensor_file),
            "feature_file_bytes": tensor_file.stat().st_size, "elapsed_seconds": time.perf_counter() - started,
            "head_initialization": False, "training": False, "evaluation_inference": False,
            "protected_panel_opened": False, "newtight_access": False, "phoenix_access": False,
        }
        feature_path = attempt / "candidate-feature-receipt.json"
        write_json(feature_path, feature_receipt)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        attempt.replace(final_dir)
        return {"status": feature_receipt["status"], "tensor_sha256": feature_receipt["tensor_sha256"], "feature_file_sha256": feature_receipt["feature_file_sha256"], "elapsed_seconds": feature_receipt["elapsed_seconds"]}
    except BaseException as exc:
        write_json(attempt / "failure-receipt.json", {"status": "CANDIDATE_EXTRACTION_FAILED_RETAINED", "exception_type": type(exc).__name__, "exception": str(exc), "elapsed_seconds": time.perf_counter() - started, "evaluation_access": False})
        raise


def main() -> int:
    result = run()
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np
import torch
import transformers

_RUN_ROOT = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
sys.path.insert(0, str(_RUN_ROOT / "source"))
sys.path.insert(0, str(_RUN_ROOT / "inputs" / "parent-sources"))

from s11_exec_common_v03 import FEATURES, MANIFEST, RUN, TOKEN_ROWS, canonical_json, entry, jsonl_rows, read_json, sha256_file, tree_root, verify_ancestry, verify_code_binding, write_json
from s09_math import layer_surface_vectors


MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
EXPECTED_STATE = "14b8ccb6c347eb5a91ccb718de39d70865f15410f5b6e62ca747aaf77f6bb9e5"
EXPECTED_ROWS = 21_272
DIMENSION = 2_048
LAYERS = 16
REPEAT_ROWS = 256
MODEL_ROOT = Path(r"D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v02\model-assets\snapshot")


def tensor_state_identity(model: torch.nn.Module) -> dict[str, object]:
    digest = hashlib.sha256()
    tensors = elements = byte_count = 0
    for name, tensor in sorted(model.state_dict().items(), key=lambda item: item[0]):
        if not isinstance(tensor, torch.Tensor):
            raise RuntimeError(f"non-tensor model state entry: {name}")
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(tensor.dtype).encode("ascii") + b"\0")
        digest.update(canonical_json(list(tensor.shape)) + b"\0")
        cpu = tensor.detach().contiguous().reshape(-1).view(torch.uint8).to(device="cpu").numpy()
        view = memoryview(cpu).cast("B")
        for offset in range(0, len(view), 8 * 1024 * 1024):
            chunk = view[offset:offset + 8 * 1024 * 1024]
            digest.update(chunk)
            byte_count += len(chunk)
        tensors += 1
        elements += tensor.numel()
        del cpu, view
    return {"sha256": digest.hexdigest(), "state_tensor_count": tensors, "state_element_count": elements, "serialized_state_bytes": byte_count}


def verify_token_inputs() -> tuple[list[dict[str, object]], dict[str, object]]:
    seal = read_json(RUN / "tokenization-v01" / "tokenization-seal-v01.json")
    base = RUN / "tokenization-v01"
    actual = [entry(base.joinpath(*row["path"].split("/")), base) for row in seal["entries"]]
    if actual != seal["entries"] or tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError("tokenization parent seal failed verification")
    token_receipt = read_json(base / "tokenization-receipt-v01.json")
    if token_receipt["rows"] != EXPECTED_ROWS or not token_receipt["deterministic_repeat"]["byte_identity"]:
        raise RuntimeError("tokenization receipt is incomplete or nondeterministic")
    rows = [row for _, row in jsonl_rows(TOKEN_ROWS)]
    if len(rows) != EXPECTED_ROWS or any(row["row_index"] != i for i, row in enumerate(rows)):
        raise RuntimeError("token row order or count is invalid")
    for row in rows:
        ids = row["token_ids"]
        digest = hashlib.sha256(struct.pack(f"<{len(ids)}I", *ids)).hexdigest()
        if digest != row["token_ids_sha256"] or len(ids) != row["sequence_length"]:
            raise RuntimeError(f"token row integrity failure at {row['row_index']}")
    return rows, token_receipt


def state_for(ids_list: list[int], model: torch.nn.Module, device: torch.device) -> np.ndarray:
    if not ids_list or len(ids_list) > 2_048:
        raise RuntimeError("empty or contract-exceeding token sequence")
    ids = torch.tensor(ids_list, dtype=torch.long, device=device).reshape(1, -1)
    output = model(input_ids=ids, output_hidden_states=True, use_cache=False, return_dict=True)
    vectors = layer_surface_vectors(output.hidden_states, len(ids_list), DIMENSION)
    result = vectors.detach().contiguous().cpu().numpy().astype("<f4", copy=False)
    if result.shape != (LAYERS, 2, DIMENSION) or not np.isfinite(result).all():
        raise RuntimeError("layer/surface result shape, dtype, or finite-value check failed")
    return result


def main() -> int:
    started = time.perf_counter()
    manifest = read_json(MANIFEST)
    verify_ancestry(manifest)
    code_binding = verify_code_binding(manifest)
    if FEATURES.exists() or FEATURES.with_name(FEATURES.name + ".tmp").exists():
        raise RuntimeError("feature-cache output already exists; preserve it and use a versioned attempt")
    rows, token_receipt = verify_token_inputs()

    if torch.__version__ != "2.11.0+cu128" or transformers.__version__ != "5.17.0" or np.__version__ != "2.5.3":
        raise RuntimeError("frozen S11 Python package versions differ")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise RuntimeError("the contracted single RTX 3080 is unavailable")
    torch.set_num_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision("highest")
    torch.use_deterministic_algorithms(True)
    torch.cuda.manual_seed_all(0)
    device = torch.device("cuda:0")

    model_files = read_json(RUN / "inputs" / "parent" / "s09-model-asset-manifest-v02.json")
    if model_files["asset_root_sha256"] != "661a7e73c0804e98bfb4ca9d1786ca9126a0a21595fbd2d3aea517c342fba1b3":
        raise RuntimeError("pinned model asset manifest identity mismatch")
    for item in model_files["files"]:
        path = MODEL_ROOT / item["path"].split("/")[-1]
        digest, size = sha256_file(path)
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"pinned model asset changed: {path}")

    from transformers import AutoModel

    model = AutoModel.from_pretrained(str(MODEL_ROOT), local_files_only=True, trust_remote_code=False, dtype=torch.float32)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.to(device)
    config = getattr(model.config, "text_config", model.config)
    hidden_size = getattr(config, "hidden_size", None)
    layer_count = getattr(config, "num_hidden_layers", None)
    if hidden_size != DIMENSION or layer_count != LAYERS:
        raise RuntimeError(f"pinned model dimensions differ: hidden={hidden_size}, layers={layer_count}")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise RuntimeError("model parameters were not frozen")
    before = tensor_state_identity(model)
    if before["sha256"] != EXPECTED_STATE:
        raise RuntimeError(f"backbone state identity differs from S09: {before['sha256']}")

    temp = FEATURES.with_name(FEATURES.name + ".tmp")
    temp.mkdir(parents=True)
    matrices_dir = temp / "matrices"
    matrices_dir.mkdir()
    matrices: dict[tuple[int, str], np.memmap] = {}
    paths: dict[tuple[int, str], Path] = {}
    for layer in range(1, LAYERS + 1):
        for surface, slot in (("M", 0), ("F", 1)):
            path = matrices_dir / f"layer-{layer:02d}-{surface}.f32le"
            paths[(layer, surface)] = path
            matrices[(layer, surface)] = np.memmap(path, dtype="<f4", mode="w+", shape=(EXPECTED_ROWS, DIMENSION), order="C")

    row_manifest = temp / "feature-rows-v01.jsonl"
    row_hash = hashlib.sha256()
    row_bytes = 0
    repeat_reference: list[np.ndarray] = []
    with torch.inference_mode(), row_manifest.open("wb") as stream:
        for row_index, row in enumerate(rows):
            vectors = state_for(row["token_ids"], model, device)
            feature_hashes: dict[str, str] = {}
            for layer in range(1, LAYERS + 1):
                for surface, slot in (("M", 0), ("F", 1)):
                    vector = np.ascontiguousarray(vectors[layer - 1, slot], dtype="<f4")
                    matrices[(layer, surface)][row_index] = vector
                    feature_hashes[f"L{layer:02d}_{surface}"] = hashlib.sha256(memoryview(vector).cast("B")).hexdigest()
            if row_index < REPEAT_ROWS:
                repeat_reference.append(vectors.copy())
            record = {
                "row_index": row_index,
                "event_id": row["event_id"],
                "input_sha256": row["input_sha256"],
                "token_ids_sha256": row["token_ids_sha256"],
                "sequence_length": row["sequence_length"],
                "features_sha256": feature_hashes,
            }
            payload = canonical_json(record) + b"\n"
            stream.write(payload)
            row_hash.update(payload)
            row_bytes += len(payload)
            if (row_index + 1) % 256 == 0:
                print(f"S11 feature rows {row_index + 1}/{EXPECTED_ROWS} in {time.perf_counter()-started:.1f}s", flush=True)
        stream.flush()
        os.fsync(stream.fileno())

    for matrix in matrices.values():
        matrix.flush()
    del matrices
    repeat_rows = []
    with torch.inference_mode():
        for row_index in range(REPEAT_ROWS):
            repeated = state_for(rows[row_index]["token_ids"], model, device)
            if repeated.tobytes(order="C") != repeat_reference[row_index].tobytes(order="C"):
                raise RuntimeError(f"repeat extraction feature mismatch at row {row_index}")
            repeat_rows.append({"row_index": row_index, "event_id": rows[row_index]["event_id"], "all_32_views_byte_equal": True})
            if (row_index + 1) % 64 == 0:
                print(f"S11 deterministic repeat {row_index + 1}/{REPEAT_ROWS}", flush=True)

    after = tensor_state_identity(model)
    if after != before or after["sha256"] != EXPECTED_STATE:
        raise RuntimeError("backbone state identity changed during S11 extraction")

    matrix_records = []
    for (layer, surface), path in sorted(paths.items()):
        digest, size = sha256_file(path)
        expected_size = EXPECTED_ROWS * DIMENSION * 4
        if size != expected_size:
            raise RuntimeError(f"feature matrix byte length mismatch: {path}")
        matrix_records.append({"layer": layer, "surface": surface, "path": path.relative_to(temp).as_posix(), "shape": [EXPECTED_ROWS, DIMENSION], "dtype": "<f4", "bytes": size, "sha256": digest})

    repeat_payload = {"receipt_id": "FAS_S11_FEATURE_REPEAT_RECEIPT_V01", "sample_rows": REPEAT_ROWS, "all_32_layer_surface_vectors_byte_equal": True, "rows": repeat_rows}
    backbone_payload = {"receipt_id": "FAS_S11_BACKBONE_IDENTITY_RECEIPT_V01", "model_id": MODEL_ID, "revision": REVISION, "before": before, "after": after, "identical": True, "parameter_delta": 0}
    feature_payload = {
        "receipt_id": "FAS_S11_FEATURE_EXTRACTION_RECEIPT_V01",
        "complete": True,
        "rows": EXPECTED_ROWS,
        "matrix_count": len(matrix_records),
        "dimension": DIMENSION,
        "dtype": "<f4",
        "model_id": MODEL_ID,
        "revision": REVISION,
        "implementation_code_manifest_sha256": code_binding["manifest_sha256"],
        "protocol_root_sha256": manifest["authoritative_s11_ancestry"]["protocol_root_sha256"],
        "collision_admission_amendment_json_sha256": manifest["authoritative_s11_ancestry"]["collision_admission_amendment_json_sha256"],
        "panel_tree_root_sha256": manifest["authoritative_s11_ancestry"]["panel_tree_root_sha256"],
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "numpy": np.__version__,
        "device": torch.cuda.get_device_name(0),
        "inference_dtype": "float32",
        "single_row_exact_length_no_padding": True,
        "input_ids_with_special_tokens": True,
        "attention_mask_passed": False,
        "hidden_states_count": 17,
        "backbone_parameter_delta": 0,
        "tokenization_seal_root": read_json(RUN / "tokenization-v01" / "tokenization-seal-v01.json")["root_sha256"],
        "token_rows_sha256": token_receipt["token_rows_sha256"],
        "feature_row_manifest": {"path": row_manifest.relative_to(temp).as_posix(), "rows": EXPECTED_ROWS, "bytes": row_bytes, "sha256": row_hash.hexdigest()},
        "matrices": matrix_records,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "probe_or_observer_loaded": False,
    }
    write_json(temp / "feature-repeat-receipt-v01.json", repeat_payload)
    write_json(temp / "backbone-identity-receipt-v01.json", backbone_payload)
    write_json(temp / "feature-extraction-receipt-v01.json", feature_payload)
    entries = [entry(path, temp) for path in temp.rglob("*") if path.is_file() and path.name != "feature-cache-seal-v01.json"]
    entries.sort(key=lambda item: item["path"])
    cache_root = tree_root(entries)
    write_json(temp / "feature-cache-seal-v01.json", {"seal_id": "FAS_S11_FEATURE_CACHE_SEAL_V01", "entries": entries, "root_sha256": cache_root})
    temp.replace(FEATURES)
    run_manifest = read_json(MANIFEST)
    run_manifest["tokenizer_loaded"] = True
    run_manifest["model_loaded"] = True
    run_manifest["features_extracted"] = True
    run_manifest["feature_cache_root_sha256"] = cache_root
    run_manifest["status"] = "FEATURE_CACHE_SEALED_OBSERVERS_NOT_YET_LOADED"
    write_json(MANIFEST, run_manifest)
    print(f"S11 fresh feature cache sealed: {cache_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

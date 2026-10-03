from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np
import torch
from transformers import AutoModel

from s09_common import (
    DIMENSION,
    EVENTS,
    LAYERS,
    MODEL_ID,
    REVISION,
    RUN_ROOT,
    S01_2_ROOT,
    SURFACES,
    configure_determinism,
    entry_for,
    read_json,
    sha256_file,
    tensor_state_identity,
    tree_root,
    write_json,
)
from s09_math import layer_surface_vectors


def verify_preflight() -> None:
    seal_path = RUN_ROOT / "seals" / "preflight-seal-v02.json"
    seal = read_json(seal_path)
    actual = [entry_for(RUN_ROOT.joinpath(*entry["path"].split("/")), RUN_ROOT) for entry in seal["entries"]]
    actual.sort(key=lambda item: item["path"])
    if actual != seal["entries"] or tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError("S09 preflight snapshot no longer matches its seal")


def feature_to_numpy(vector: torch.Tensor) -> np.ndarray:
    if vector.dtype != torch.float32 or tuple(vector.shape) != (DIMENSION,):
        raise RuntimeError(f"feature vector has unexpected shape/dtype {tuple(vector.shape)} {vector.dtype}")
    array = vector.detach().contiguous().cpu().numpy().astype("<f4", copy=False)
    if not np.isfinite(array).all():
        raise RuntimeError("feature vector contains non-finite values")
    return array


def load_rows(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for expected_index, line in enumerate(stream):
            row = json.loads(line)
            if row.get("row_index") != expected_index or len(row.get("token_ids", [])) != row.get("sequence_length"):
                raise RuntimeError(f"token-only row identity/length mismatch at {expected_index}")
            yield row


def main() -> int:
    if (RUN_ROOT / "feature-cache-v02").exists() or (RUN_ROOT / "extraction-receipt-v02.json").exists():
        raise RuntimeError("S09 extraction already started; refusing in-place rerun")
    verify_preflight()
    model_manifest = read_json(RUN_ROOT / "model-asset-manifest-v02.json")
    if model_manifest.get("model_id") != MODEL_ID or model_manifest.get("resolved_revision") != REVISION:
        raise RuntimeError("S09 model asset identity differs")
    for asset in model_manifest["assets"]:
        digest, size = sha256_file(RUN_ROOT.joinpath(*asset["path"].split("/")))
        if digest != asset["sha256"] or size != asset["bytes"]:
            raise RuntimeError(f"S09 model asset changed before load: {asset['path']}")
    device = configure_determinism()
    if torch.__version__ != "2.11.0+cu128" or np.__version__ != "2.5.3":
        raise RuntimeError("S09 frozen runtime versions differ")
    import transformers
    if transformers.__version__ != "5.17.0":
        raise RuntimeError("S09 frozen Transformers version differs")

    model_path = RUN_ROOT / "model-assets" / "snapshot"
    model = AutoModel.from_pretrained(
        str(model_path), local_files_only=True, trust_remote_code=False, dtype=torch.float32,
    )
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.to(device)
    cfg = model.config
    if getattr(cfg, "num_hidden_layers", None) != 16 or getattr(cfg, "hidden_size", None) != DIMENSION:
        raise RuntimeError("loaded LFM config differs from frozen dimensions")
    if getattr(cfg, "_attn_implementation", None) != "sdpa":
        raise RuntimeError(f"S09 attention implementation differs from S01 receipt: {getattr(cfg, '_attn_implementation', None)}")
    before = tensor_state_identity(model)
    if before["serialized_state_bytes"] <= 0:
        raise RuntimeError("empty model parameter identity")

    parent_cache_seal = read_json(RUN_ROOT / "inputs" / "S01-2" / "feature-cache-seal-v01.json")
    parent_entries = {entry["path"]: entry for entry in parent_cache_seal["entries"]}
    old_m_path = S01_2_ROOT / "feature-cache-v01" / "V0_MEAN_FULL.f32le"
    old_f_path = S01_2_ROOT / "feature-cache-v01" / "V1_FINAL_POSITION.f32le"
    for path in (old_m_path, old_f_path):
        expected = parent_entries.get(path.relative_to(S01_2_ROOT).as_posix())
        if expected is None:
            raise RuntimeError(f"terminal parity parent is not listed in the sealed S01 cache: {path.name}")
        digest, size = sha256_file(path)
        if digest != expected["sha256"] or size != expected["bytes"]:
            raise RuntimeError(f"terminal parity parent changed after preflight: {path.name}")
    rows_path = RUN_ROOT / "inputs" / "token-only-feature-rows-v02.jsonl"
    rows_digest, _ = sha256_file(rows_path)
    old_m = np.memmap(old_m_path, dtype="<f4", mode="r", shape=(EVENTS, DIMENSION))
    old_f = np.memmap(old_f_path, dtype="<f4", mode="r", shape=(EVENTS, DIMENSION))
    output_dir = RUN_ROOT / "feature-cache-v02"
    output_dir.mkdir(parents=True, exist_ok=False)
    arrays: dict[tuple[int, str], np.memmap] = {}
    for layer in LAYERS:
        for surface in SURFACES:
            arrays[(layer, surface)] = np.memmap(
                output_dir / f"layer-{layer:02d}-{surface}.f32le",
                dtype="<f4", mode="w+", shape=(EVENTS, DIMENSION), order="C",
            )

    start = time.perf_counter()
    count = 0
    try:
        with torch.inference_mode():
            for row in load_rows(rows_path):
                tokens = row["token_ids"]
                seq_len = int(row["sequence_length"])
                if not tokens or seq_len > 2048:
                    raise RuntimeError(f"sequence outside frozen length bounds at row {count}")
                input_ids = torch.tensor(tokens, dtype=torch.long, device=device).reshape(1, -1)
                output = model(input_ids=input_ids, use_cache=False, output_hidden_states=True, return_dict=True)
                hidden_states = output.hidden_states
                if hidden_states is None or len(hidden_states) != 17:
                    raise RuntimeError(f"model returned {0 if hidden_states is None else len(hidden_states)} hidden states, expected embedding plus 16 layers")
                if not torch.equal(hidden_states[-1], output.last_hidden_state):
                    raise RuntimeError("final hidden-state tuple entry differs from last_hidden_state")
                vectors = layer_surface_vectors(hidden_states, seq_len, DIMENSION).detach().cpu().numpy().astype("<f4", copy=False)
                if not np.isfinite(vectors).all():
                    raise RuntimeError(f"non-finite layer feature at row {count}")
                for layer in LAYERS:
                    m = vectors[layer - 1, 0]
                    f = vectors[layer - 1, 1]
                    if layer == 16:
                        if not np.array_equal(m, old_m[count]) or not np.array_equal(f, old_f[count]):
                            raise RuntimeError(f"terminal layer feature parity failed at row {count} event {row['event_id']}")
                    arrays[(layer, "M")][count] = m
                    arrays[(layer, "F")][count] = f
                count += 1
                if count % 5000 == 0:
                    print(f"extracted_rows={count}/{EVENTS} elapsed_seconds={time.perf_counter()-start:.1f}", flush=True)
        if count != EVENTS:
            raise RuntimeError(f"S09 extracted row count differs: {count}")

        for array in arrays.values():
            array.flush()
        repeat_rows = []
        with torch.inference_mode():
            for row in load_rows(rows_path):
                if int(row["row_index"]) >= 256:
                    break
                tokens = row["token_ids"]
                output = model(input_ids=torch.tensor(tokens, dtype=torch.long, device=device).reshape(1, -1), use_cache=False, output_hidden_states=True, return_dict=True)
                if not torch.equal(output.hidden_states[-1], output.last_hidden_state):
                    raise RuntimeError("repeat final hidden-state identity failed")
                repeat = layer_surface_vectors(output.hidden_states, len(tokens), DIMENSION).detach().cpu().numpy().astype("<f4", copy=False)
                row_index = int(row["row_index"])
                for layer in LAYERS:
                    for surface_index, surface in enumerate(SURFACES):
                        if not np.array_equal(repeat[layer - 1, surface_index], arrays[(layer, surface)][row_index]):
                            raise RuntimeError(f"deterministic repeat mismatch at row {row_index}, layer {layer}, surface {surface}")
                repeat_rows.append(row["event_id"])
        if len(repeat_rows) != 256:
            raise RuntimeError(f"deterministic repeat row count differs: {len(repeat_rows)}")
    except Exception as exc:
        for array in arrays.values():
            array.flush()
        write_json(RUN_ROOT / "execution-failure-v02.json", {
            "stage": "FEATURE_EXTRACTION_OR_QUALIFICATION",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "model_loaded": True,
            "rows_completed": count,
            "feature_cache_sealed": False,
            "probe_fitting_started": False,
        })
        raise

    after = tensor_state_identity(model)
    if before["sha256"] != after["sha256"]:
        write_json(RUN_ROOT / "execution-failure-v02.json", {
            "stage": "BACKBONE_IDENTITY_AFTER_EXTRACTION",
            "error": "frozen backbone parameter identity changed during extraction",
            "model_loaded": True,
            "rows_completed": count,
            "feature_cache_sealed": False,
            "probe_fitting_started": False,
            "parameter_hash_before": before["sha256"],
            "parameter_hash_after": after["sha256"],
        })
        raise RuntimeError("frozen backbone parameter identity changed during extraction")
    file_entries = []
    for layer in LAYERS:
        for surface in SURFACES:
            name = f"layer-{layer:02d}-{surface}.f32le"
            path = output_dir / name
            digest, size = sha256_file(path)
            expected_size = EVENTS * DIMENSION * 4
            if size != expected_size:
                raise RuntimeError(f"feature matrix byte count differs: {name}")
            file_entries.append({"path": name, "bytes": size, "sha256": digest, "shape": [EVENTS, DIMENSION], "dtype": "<f4", "layer": layer, "surface": surface})
    repeat = {
        "sample_rows": 256,
        "event_ids_sha256": hashlib.sha256("\n".join(repeat_rows).encode("ascii")).hexdigest(),
        "all_32_layer_surface_vectors_byte_equal": True,
    }
    receipt = {
        "receipt_id": "FAS_S09_FEATURE_EXTRACTION_RECEIPT_V01",
        "model_id": MODEL_ID,
        "model_revision": REVISION,
        "model_asset_root_sha256": model_manifest["asset_manifest_root_sha256"],
        "layers": list(LAYERS),
        "hidden_state_tuple_count_including_embedding": 17,
        "events": count,
        "quartets": QUARTETS,
        "views": ["M=mean_full", "F=final_position"],
        "feature_arrays": file_entries,
        "token_only_manifest_sha256": rows_digest,
        "terminal_parent_parity": {"M_byte_equal_to_S01_V0": True, "F_byte_equal_to_S01_V1": True, "events_compared": EVENTS, "max_abs_error": 0.0},
        "deterministic_repeat": repeat,
        "backbone_before": before,
        "backbone_after": after,
        "backbone_parameter_delta": 0,
        "single_row_exact_length_no_padding": True,
        "tokenizer_called": False,
        "probe_fitting_performed": False,
        "fas00_data_accessed": False,
        "elapsed_seconds": round(time.perf_counter() - start, 3),
    }
    write_json(RUN_ROOT / "extraction-receipt-v02.json", receipt)
    cache_entries = [entry_for(path, output_dir) for path in sorted(output_dir.iterdir()) if path.is_file()]
    cache_seal = {"seal_id": "FAS_S09_FEATURE_CACHE_SEAL_V01", "entries": cache_entries, "root_sha256": tree_root(cache_entries), "rows": EVENTS, "matrices": len(cache_entries)}
    write_json(output_dir / "feature-cache-seal-v02.json", cache_seal)
    print(f"feature_cache_root_sha256={cache_seal['root_sha256']} arrays={len(cache_entries)} elapsed_seconds={receipt['elapsed_seconds']}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

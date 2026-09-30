"""Bounded operational attention-group ablation for Lexi's locked atlas.

This is an inference-only diagnostic. It never reads task labels, fits readouts,
changes a checkpoint, or writes into the source caches.
"""
from __future__ import annotations

import argparse
import collections
import gc
import hashlib
import heapq
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SURFACE_SPEC = REPO / "experiments" / "bank-v1-surface-extremes-20260929"
GRAPH_SPEC = REPO / "experiments" / "bank-v1-graph-surface-v2-20260929"
PROTOCOL = HERE / "HEAD-MASKING-PROTOCOL.json"

BANK_ROOT = Path(r"C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1")
R0_ROOT = Path(r"D:\phoenix-target-overgraph\bank-v1-surface-extremes-20260929")
GRAPH_ROOT = Path(r"D:\phoenix-target-overgraph\bank-v1-graph-surface-v2-20260929")
SURVIVAL_ROOT = Path(r"D:\phoenix-target-overgraph\lexi-specialization-survival-20260929")
OUTPUT_ROOT = Path(r"D:\phoenix-target-overgraph\lexi-head-masking-20260930")

BASE_MODEL = Path(r"D:\phoenix-models\lfm2.5-230m-base-9d2be55")
NER_MODEL = SURVIVAL_ROOT / "runs" / "ner-late-lora-r8-500" / "checkpoints" / "step-000500" / "backbone"
NLI_MODEL = SURVIVAL_ROOT / "runs" / "nli-late-lora-r8-500" / "checkpoints" / "step-000500" / "backbone"

TEST_SPLITS = (
    "TEST-IID", "TEST-LEXICAL", "TEST-ENTITY", "TEST-TEMPLATE",
    "TEST-COMPOSITION", "TEST-DEPTH", "TEST-ABSTENTION", "TEST-JOINT",
)
SURFACES = ("middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean", "first_token")
PRIMITIVES = ("final_token", "full_mean", "first_token", "layer_m4_final", "middle_final")
READOUT_HEADS = ("decision", "action_type", "abstain_reason", "nli")
SEED = "LEXI-HEAD-MASKING-2026-09-30"
ROWS_PER_STRATUM = 32
PAIRS_PER_STRATUM = 16
BATCH_SIZE = 16
MAX_LENGTH = 2048

MODEL_INFO = {
    "base": {
        "path": BASE_MODEL,
        "features": R0_ROOT / "features",
        "local_features": GRAPH_ROOT / "features",
        "specialized_refit": None,
    },
    "ner_lora_step500": {
        "path": NER_MODEL,
        "features": SURVIVAL_ROOT / "features" / "ner-step500-atlas" / "features",
        "local_features": SURVIVAL_ROOT / "features" / "ner-step500-edge-local" / "features",
        "specialized_refit": SURVIVAL_ROOT / "scored" / "ner-step500-atlas" / "refit-head" / "models",
    },
    "nli_lora_step500": {
        "path": NLI_MODEL,
        "features": SURVIVAL_ROOT / "features" / "nli-step500-atlas" / "features",
        "local_features": SURVIVAL_ROOT / "features" / "nli-step500-edge-local" / "features",
        "specialized_refit": SURVIVAL_ROOT / "scored" / "nli-step500-atlas" / "refit-head" / "models",
    },
}

INPUT_FILES = (
    ("TRAIN", "inputs/TRAIN.jsonl"),
    ("DEV", "inputs/DEV.jsonl"),
    ("TEST-IID", "public/test-inputs/TEST-IID.jsonl"),
    ("TEST-LEXICAL", "public/test-inputs/TEST-LEXICAL.jsonl"),
    ("TEST-ENTITY", "public/test-inputs/TEST-ENTITY.jsonl"),
    ("TEST-TEMPLATE", "public/test-inputs/TEST-TEMPLATE.jsonl"),
    ("TEST-COMPOSITION", "public/test-inputs/TEST-COMPOSITION.jsonl"),
    ("TEST-DEPTH", "public/test-inputs/TEST-DEPTH.jsonl"),
    ("TEST-ABSTENTION", "public/test-inputs/TEST-ABSTENTION.jsonl"),
    ("TEST-JOINT", "public/test-inputs/TEST-JOINT.jsonl"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def selection_digest(value: str) -> str:
    return hashlib.sha256(f"{SEED}|{value}".encode("utf-8")).hexdigest()


def select_global_rows(rowmap_path: Path) -> list[dict]:
    strata: dict[tuple[str, str], list[tuple[str, dict]]] = collections.defaultdict(list)
    for meta in read_jsonl(rowmap_path):
        split = meta["split"]
        family = meta.get("surface_family")
        if split not in TEST_SPLITS or not family:
            continue
        digest = selection_digest(str(meta["world_id"]))
        item = {key: meta[key] for key in ("idx", "row_id", "split", "surface_family")}
        strata[(split, family)].append((digest, item))
    selected = []
    for key in sorted(strata):
        bucket = sorted(strata[key], key=lambda value: value[0])
        selected.extend(item for _, item in bucket[:ROWS_PER_STRATUM])
    if not selected:
        raise RuntimeError("no rows selected from the declared test splits")
    return sorted(selected, key=lambda item: item["idx"])


def select_graph_pairs(task_dir: Path) -> list[dict]:
    """Bottom-k sample uses identifiers and renderer metadata only, never labels."""
    heaps: dict[tuple[str, str], list[tuple[int, dict]]] = collections.defaultdict(list)
    for split in TEST_SPLITS:
        path = task_dir / f"{split}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(path)
        for raw in read_jsonl(path):
            family = str(raw.get("family", ""))
            if not family or any(key not in raw for key in ("row_idx", "a_idx", "b_idx")):
                continue
            record = {
                "split": split,
                "family": family,
                "row_idx": int(raw["row_idx"]),
                "a_idx": int(raw["a_idx"]),
                "b_idx": int(raw["b_idx"]),
                "world_id": str(raw.get("world_id", "")),
            }
            identity = "|".join(str(record[key]) for key in
                                ("split", "family", "row_idx", "a_idx", "b_idx"))
            digest = int(selection_digest(identity), 16)
            key = (split, family)
            heap = heaps[key]
            entry = (-digest, record)
            if len(heap) < PAIRS_PER_STRATUM:
                heapq.heappush(heap, entry)
            elif entry[0] > heap[0][0]:
                heapq.heapreplace(heap, entry)
    pairs = [record for heap in heaps.values() for _, record in heap]
    if not pairs:
        raise RuntimeError("no edge-existence candidate pairs selected")
    return sorted(pairs, key=lambda item: (item["split"], item["family"],
                                           item["row_idx"], item["a_idx"], item["b_idx"]))


def model_config_summary(path: Path) -> dict:
    config = read_json(path / "config.json")
    layer_types = config.get("layer_types")
    full_layers = [i for i, kind in enumerate(layer_types or []) if kind == "full_attention"]
    if not full_layers:
        raise RuntimeError(f"no full-attention layers in {path}")
    return {
        "config_sha256": sha256_file(path / "config.json"),
        "weights_sha256": sha256_file(path / "model.safetensors"),
        "tokenizer_sha256": sha256_file(path / "tokenizer.json"),
        "hidden_size": int(config["hidden_size"]),
        "num_hidden_layers": int(config["num_hidden_layers"]),
        "num_attention_heads": int(config.get("num_attention_heads", config.get("num_heads"))),
        "num_key_value_heads": int(config.get("num_key_value_heads",
                                               config.get("num_attention_heads", config.get("num_heads")))),
        "layer_types": layer_types,
        "full_attention_layers": full_layers,
    }


def source_receipts() -> dict:
    source_lock_path = R0_ROOT / "source-lock.json"
    source_lock = read_json(source_lock_path)
    if source_lock.get("release") != "BANK-v1":
        raise RuntimeError("Rung-0 input source lock is not BANK-v1")
    for item in source_lock["files"]:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            raise RuntimeError(f"source file missing or size changed: {path}")
        if sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"source file changed: {path}")
    rowmap = R0_ROOT / "rowmap.jsonl"
    if sha256_file(rowmap) != source_lock["rowmap_sha256"]:
        raise RuntimeError("Rung-0 rowmap hash mismatch")
    return {
        "source_lock_path": str(source_lock_path),
        "source_lock_sha256": sha256_file(source_lock_path),
        "rowmap_path": str(rowmap),
        "rowmap_sha256": sha256_file(rowmap),
        "bank_manifest_path": source_lock["bank_manifest_path"],
        "bank_manifest_sha256": source_lock["bank_manifest_sha256"],
        "input_files": source_lock["files"],
    }


def build_conditions(model_shape: dict) -> list[dict]:
    q_heads = int(model_shape["num_attention_heads"])
    kv_heads = int(model_shape["num_key_value_heads"])
    if q_heads % kv_heads:
        raise RuntimeError("query-head count must be divisible by KV-head count")
    heads_per_kv = q_heads // kv_heads
    if heads_per_kv != 2:
        raise RuntimeError(f"protocol expects 2 query heads per KV group, found {heads_per_kv}")
    layers = model_shape["full_attention_layers"][-4:]
    if len(layers) != 4:
        raise RuntimeError(f"expected at least four full-attention layers, found {layers}")
    result = []
    for layer in layers:
        result.append({
            "condition_id": f"layer-{layer:02d}-all",
            "kind": "whole_layer",
            "layer": layer,
            "heads": list(range(q_heads)),
        })
        for kv_group in range(kv_heads):
            heads = list(range(kv_group * heads_per_kv, (kv_group + 1) * heads_per_kv))
            result.append({
                "condition_id": f"layer-{layer:02d}-kv-{kv_group:02d}",
                "kind": "kv_group",
                "layer": layer,
                "kv_group": kv_group,
                "heads": heads,
            })
    return result


def prepare(output: Path) -> None:
    protocol = read_json(PROTOCOL)
    l_s0_path = HERE / "L-S0-lock.json"
    l_s0 = read_json(l_s0_path)
    if l_s0.get("status") != "LOCKED":
        raise RuntimeError("Rung-0/L-S0 lock is not locked")
    r0_lock_path = REPO / "experiments" / "bank-v1-rung0-atlas-20260929" / "rung0-lock.json"
    if sha256_file(r0_lock_path) != l_s0["rung0"]["lock_sha256"]:
        raise RuntimeError("Rung-0 lock does not match the L-S0 receipt")
    sources = source_receipts()
    rowmap_path = R0_ROOT / "rowmap.jsonl"
    global_rows = select_global_rows(rowmap_path)
    graph_pairs = select_graph_pairs(GRAPH_ROOT / "task-examples" / "edge_existence")
    model_shapes = {key: model_config_summary(info["path"])
                    for key, info in MODEL_INFO.items()}
    base_shape = model_shapes["base"]
    for key, shape in model_shapes.items():
        for field in ("hidden_size", "num_hidden_layers", "num_attention_heads",
                      "num_key_value_heads", "layer_types"):
            if shape[field] != base_shape[field]:
                raise RuntimeError(f"{key} architecture differs from base at {field}")
    conditions = build_conditions(base_shape)
    row_ids_payload = {
        "global_rows": global_rows,
        "graph_pairs": graph_pairs,
    }
    output.mkdir(parents=True, exist_ok=True)
    sample_path = output / "sample-selection.json"
    if sample_path.exists():
        if read_json(sample_path) != row_ids_payload:
            raise RuntimeError("existing sample selection differs; refusing to replace it")
    else:
        write_json(sample_path, row_ids_payload)

    feature_seals = {}
    readout_files = {}
    for model_key, info in MODEL_INFO.items():
        seal_path = info["features"] / "extraction-seal.json"
        local_seal = info["local_features"] / "extraction-seal.json"
        if not seal_path.is_file() or not local_seal.is_file():
            raise FileNotFoundError(f"missing feature seal for {model_key}")
        feature_seals[model_key] = {
            "whole_row": {"path": str(seal_path), "sha256": sha256_file(seal_path)},
            "local": {"path": str(local_seal), "sha256": sha256_file(local_seal)},
        }
        readout_files[model_key] = {}
        for surface in SURFACES:
            base_path = R0_ROOT / "models" / f"{surface}.npz"
            readout_files[model_key][surface] = {
                "base_head": str(base_path.resolve()),
                "base_head_sha256": sha256_file(base_path),
            }
            refit_dir = info["specialized_refit"]
            if refit_dir is not None:
                refit_path = refit_dir / f"{surface}.npz"
                readout_files[model_key][surface]["own_refit_head"] = str(refit_path.resolve())
                readout_files[model_key][surface]["own_refit_sha256"] = sha256_file(refit_path)

    graph_model = GRAPH_ROOT / "models" / "edge_existence-middle_plus_final-tiny_mlp.pt"
    graph_scaler = GRAPH_ROOT / "scalers" / "local-middle_plus_final.npz"
    graph_receipts = {
        "graph_results": str((GRAPH_ROOT / "graph-readout-results.json").resolve()),
        "graph_results_sha256": sha256_file(GRAPH_ROOT / "graph-readout-results.json"),
        "edge_head": str(graph_model.resolve()),
        "edge_head_sha256": sha256_file(graph_model),
        "edge_scaler": str(graph_scaler.resolve()),
        "edge_scaler_sha256": sha256_file(graph_scaler),
        "row_mentions": str((GRAPH_ROOT / "row-mentions.jsonl").resolve()),
        "row_mentions_sha256": sha256_file(GRAPH_ROOT / "row-mentions.jsonl"),
    }
    lock = {
        "schema": "phoenix.lexi-head-masking/execution-lock-v1",
        "status": "LOCKED_LABEL_BLIND_INFERENCE",
        "protocol_path": str(PROTOCOL.resolve()),
        "protocol_sha256": sha256_file(PROTOCOL),
        "implementation": {
            "head_masking.py": sha256_file(HERE / "head_masking.py"),
            "head_masking_protocol.py": sha256_file(HERE / "head_masking_protocol.py"),
        },
        "l_s0_lock_path": str(l_s0_path.resolve()),
        "l_s0_lock_sha256": sha256_file(l_s0_path),
        "rung0_lock_path": str(r0_lock_path.resolve()),
        "rung0_lock_sha256": sha256_file(r0_lock_path),
        "sources": sources,
        "models": {
            key: {"path": str(info["path"].resolve()), **model_shapes[key]}
            for key, info in MODEL_INFO.items()
        },
        "feature_seals": feature_seals,
        "readouts": readout_files,
        "graph": graph_receipts,
        "sampling": {
            "seed": SEED,
            "rows_per_split_renderer_stratum": ROWS_PER_STRATUM,
            "global_row_count": len(global_rows),
            "global_row_ids_sha256": canonical_hash(global_rows),
            "graph_pairs_per_split_renderer_stratum": PAIRS_PER_STRATUM,
            "graph_pair_count": len(graph_pairs),
            "graph_pair_ids_sha256": canonical_hash(graph_pairs),
            "sample_file": str(sample_path.resolve()),
            "sample_file_sha256": sha256_file(sample_path),
            "label_fields_used": False,
        },
        "conditions": conditions,
        "condition_count": len(conditions),
        "inference": {
            "device": "CUDA:0",
            "dtype": "float32",
            "batch_size": BATCH_SIZE,
            "max_length": MAX_LENGTH,
            "output_hidden_states": True,
            "generation": False,
            "backbone_tuning": False,
            "readout_fitting": False,
            "truth_join": False,
        },
    }
    lock["lock_sha256"] = canonical_hash(lock)
    write_json(output / "HEAD-MASKING-LOCK.json", lock)
    print(json.dumps({
        "status": lock["status"],
        "rows": len(global_rows),
        "graph_pairs": len(graph_pairs),
        "conditions_per_model": len(conditions),
        "models": list(MODEL_INFO),
        "lock_sha256": lock["lock_sha256"],
    }, sort_keys=True))


def configure_torch():
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    if hasattr(torch.backends.cuda, "enable_flash_sdp"):
        torch.backends.cuda.enable_flash_sdp(False)
    if hasattr(torch.backends.cuda, "enable_mem_efficient_sdp"):
        torch.backends.cuda.enable_mem_efficient_sdp(False)
    return torch


def validate_lock(output: Path) -> dict:
    lock_path = output / "HEAD-MASKING-LOCK.json"
    lock = read_json(lock_path)
    if lock.get("status") != "LOCKED_LABEL_BLIND_INFERENCE":
        raise RuntimeError("head masking execution lock is missing or invalid")
    if lock.get("protocol_sha256") != sha256_file(PROTOCOL):
        raise RuntimeError("protocol changed after lock")
    for name, digest in lock.get("implementation", {}).items():
        if sha256_file(HERE / name) != digest:
            raise RuntimeError(f"implementation changed after lock: {name}")
    if lock.get("sampling", {}).get("sample_file_sha256") != sha256_file(
            Path(lock["sampling"]["sample_file"])):
        raise RuntimeError("sample selection changed after lock")
    for model_key, info in MODEL_INFO.items():
        current = model_config_summary(info["path"])
        frozen = lock["models"][model_key]
        for key in ("config_sha256", "weights_sha256", "tokenizer_sha256"):
            if current[key] != frozen[key]:
                raise RuntimeError(f"{model_key} {key} changed after lock")
    for model_key, seals in lock["feature_seals"].items():
        for item in seals.values():
            if sha256_file(Path(item["path"])) != item["sha256"]:
                raise RuntimeError(f"{model_key} feature receipt changed after lock")
    return lock


def load_sample(lock: dict) -> tuple[list[dict], list[dict]]:
    sample = read_json(Path(lock["sampling"]["sample_file"]))
    return sample["global_rows"], sample["graph_pairs"]


def load_rows(rowmap_path: Path, selected_rows: list[dict],
              pairs: list[dict]) -> tuple[dict[int, dict], dict[int, list[dict]]]:
    global_meta = {int(row["idx"]): row for row in selected_rows}
    needed = set(global_meta)
    pair_by_row: dict[int, list[dict]] = collections.defaultdict(list)
    for pair in pairs:
        needed.add(int(pair["row_idx"]))
        pair_by_row[int(pair["row_idx"])].append(pair)
    rowmap = list(read_jsonl(rowmap_path))
    idx_meta = {int(row["idx"]): row for row in rowmap if int(row["idx"]) in needed}
    if set(idx_meta) != needed:
        raise RuntimeError("sample indices are missing from the locked rowmap")
    result = {}
    global_idx = 0
    for split, relative in INPUT_FILES:
        path = BANK_ROOT / relative
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if global_idx in needed:
                    row = json.loads(line)
                    metadata = idx_meta[global_idx]
                    if row.get("world_id") != metadata["world_id"]:
                        raise RuntimeError(f"source and rowmap mismatch at row {global_idx}")
                    if split != metadata["split"]:
                        raise RuntimeError(f"source split mismatch at row {global_idx}")
                    result[global_idx] = {
                        "idx": global_idx,
                        "world_id": str(row["world_id"]),
                        "split": split,
                        "surface_family": str(metadata["surface_family"]),
                        "input_text": str(row["input_text"]),
                    }
                global_idx += 1
    if set(result) != needed:
        raise RuntimeError(f"source rows missing: expected {len(needed)}, found {len(result)}")
    return result, pair_by_row


def load_mentions(mentions_path: Path, needed_rows: set[int],
                  needed_entities: set[int]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {}
    for raw in read_jsonl(mentions_path):
        row_idx = int(raw["row_idx"])
        if row_idx not in needed_rows:
            continue
        result[row_idx] = [
            {"entity_index": int(item["entity_index"]), "spans": item.get("spans") or []}
            for item in raw["mentions"]
            if int(item["entity_index"]) in needed_entities
        ]
    return result


def span_token_indices(offsets: np.ndarray, span: list[int]) -> np.ndarray:
    start, stop = int(span[0]), int(span[1])
    starts = offsets[:, 0]
    ends = offsets[:, 1]
    active = ends > starts
    return np.flatnonzero(active & (starts < stop) & (ends > start))


def vector_surfaces(hidden_states, attention_mask, torch) -> dict[str, np.ndarray]:
    batch = attention_mask.shape[0]
    lengths = attention_mask.sum(dim=1)
    last = lengths - 1
    rows = torch.arange(batch, device=attention_mask.device)
    final = hidden_states[-1][rows, last, :]
    first = hidden_states[-1][:, 0, :]
    weights = attention_mask.to(dtype=hidden_states[-1].dtype).unsqueeze(-1)
    full_mean = (hidden_states[-1] * weights).sum(dim=1) / lengths.unsqueeze(-1)
    layer_m4 = hidden_states[-4][rows, last, :]
    middle_index = 1 + (len(hidden_states) - 1) // 2
    middle = hidden_states[middle_index][rows, last, :]
    values = {
        "final_token": final,
        "full_mean": full_mean,
        "first_token": first,
        "layer_m4_final": layer_m4,
        "middle_final": middle,
    }
    return {name: value.detach().float().cpu().numpy().astype("<f4", copy=False)
            for name, value in values.items()}


def surface_from_primitives(primitives: dict[str, np.ndarray], name: str) -> np.ndarray:
    if name == "middle_plus_final":
        return np.concatenate((primitives["middle_final"], primitives["final_token"]), axis=1)
    if name == "final_plus_mean":
        return np.concatenate((primitives["final_token"], primitives["full_mean"]), axis=1)
    if name == "layer_m4_final":
        return primitives["layer_m4_final"]
    if name == "full_mean":
        return primitives["full_mean"]
    if name == "first_token":
        return primitives["first_token"]
    raise KeyError(name)


def cached_primitives(features: Path, row_indices: list[int]) -> dict[str, np.ndarray]:
    indexes = np.asarray(row_indices, dtype=np.int64)
    result = {}
    for name in PRIMITIVES:
        array = np.load(features / f"{name}.npy", mmap_mode="r", allow_pickle=False)
        if array.ndim != 2 or array.shape[1] != 1024 or array.dtype != np.dtype("<f4"):
            raise RuntimeError(f"invalid cached primitive: {features / f'{name}.npy'}")
        result[name] = np.asarray(array[indexes], dtype=np.float32)
    return result


def load_readout(path: Path) -> dict:
    with np.load(path, allow_pickle=False) as archive:
        keys = ("mean", "scale", *(f"{head}.{part}" for head in READOUT_HEADS
                                   for part in ("weight", "bias")))
        return {key: np.array(archive[key], copy=True) for key in keys}


def apply_readouts(primitives: dict[str, np.ndarray],
                   model_paths: dict[str, dict[str, Path]]) -> dict:
    outputs: dict[str, dict] = {}
    for lane, paths in model_paths.items():
        outputs[lane] = {}
        for surface, path in paths.items():
            bundle = load_readout(path)
            raw = surface_from_primitives(primitives, surface).astype(np.float32, copy=False)
            normalized = (raw - bundle["mean"]) / bundle["scale"]
            surface_outputs = {}
            for head in READOUT_HEADS:
                logits = normalized @ bundle[f"{head}.weight"].T + bundle[f"{head}.bias"]
                surface_outputs[head] = logits.astype(np.float32, copy=False)
            outputs[lane][surface] = surface_outputs
    return outputs


def readout_paths(model_key: str) -> dict[str, dict[str, Path]]:
    base = {surface: R0_ROOT / "models" / f"{surface}.npz" for surface in SURFACES}
    if model_key == "base":
        return {"base_frozen": base}
    own = {surface: MODEL_INFO[model_key]["specialized_refit"] / f"{surface}.npz"
           for surface in SURFACES}
    return {"base_head_unchanged": base, "own_refit_head": own}


def top_margin(logits: np.ndarray) -> np.ndarray:
    if logits.shape[1] < 2:
        return np.zeros(len(logits), dtype=np.float32)
    top = np.partition(logits, -2, axis=1)[:, -2:]
    return top.max(axis=1) - top.min(axis=1)


def prediction_metrics(base: np.ndarray, masked: np.ndarray, indexes: np.ndarray) -> dict:
    if not len(indexes):
        return {"n": 0}
    left = base[indexes]
    right = masked[indexes]
    return {
        "n": int(len(indexes)),
        "prediction_flip_rate": float(np.mean(np.argmax(left, axis=1) != np.argmax(right, axis=1))),
        "mean_abs_logit_delta": float(np.mean(np.abs(right - left))),
        "p95_abs_logit_delta": float(np.quantile(np.abs(right - left), 0.95)),
        "mean_margin_delta": float(np.mean(top_margin(right) - top_margin(left))),
    }


def population_indexes(sample_rows: list[dict]) -> dict[str, np.ndarray]:
    keys = {
        "all": lambda row: True,
        "held_renderers_S7_S8_S9": lambda row: row["surface_family"] in {"S7", "S8", "S9"},
        "other_renderers": lambda row: row["surface_family"] not in {"S7", "S8", "S9"},
    }
    for split in TEST_SPLITS:
        keys[split] = lambda row, selected=split: row["split"] == selected
    return {
        name: np.fromiter((i for i, row in enumerate(sample_rows) if predicate(row)),
                          dtype=np.int64)
        for name, predicate in keys.items()
    }


def compare_global(baseline: dict, masked: dict, sample_rows: list[dict]) -> dict:
    populations = population_indexes(sample_rows)
    output = {}
    for lane, surfaces in masked.items():
        output[lane] = {}
        for surface, heads in surfaces.items():
            base_heads = baseline[lane][surface]
            surface_summary = {}
            for population, indexes in populations.items():
                item = {
                    "heads": {
                        head: prediction_metrics(base_heads[head], heads[head], indexes)
                        for head in ("decision", "nli")
                    }
                }
                if len(indexes):
                    base_route = np.column_stack([
                        base_heads[name][indexes].argmax(axis=1)
                        for name in ("decision", "action_type", "abstain_reason")
                    ])
                    masked_route = np.column_stack([
                        heads[name][indexes].argmax(axis=1)
                        for name in ("decision", "action_type", "abstain_reason")
                    ])
                    item["route_tuple_flip_rate"] = float(np.mean(np.any(base_route != masked_route, axis=1)))
                else:
                    item["route_tuple_flip_rate"] = None
                surface_summary[population] = item
            output[lane][surface] = surface_summary
    return output



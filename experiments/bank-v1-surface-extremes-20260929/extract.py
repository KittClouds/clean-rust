"""One-pass, resumable BANK-v1 feature extraction for LFM2.5-230M."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import time
from pathlib import Path

import numpy as np

from common import (PRIMITIVES, SEED, input_paths, read_jsonl, row_identity,
                    sha256, write_json)

def canon_hash(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()

def source_manifest(bank_root: Path) -> tuple[list[tuple[str, Path]], dict]:
    paths = input_paths(bank_root)
    bank_manifest_path = bank_root / "manifests" / "release.json"
    bank_manifest = json.loads(bank_manifest_path.read_text(encoding="utf-8"))
    if bank_manifest.get("release") != "BANK-v1" or bank_manifest.get("terminal_truth_opened") is not False:
        raise RuntimeError("input is not the sealed full BANK-v1 release")
    files = []
    for split, path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        expected = int(bank_manifest["stats"][split]["input_rows"])
        files.append({"split": split, "path": str(path.resolve()), "rows_expected": expected,
                      "bytes": path.stat().st_size, "sha256": sha256(path)})
    return paths, {"bank_manifest_path": str(bank_manifest_path.resolve()),
                   "bank_manifest_sha256": sha256(bank_manifest_path),
                   "release": "BANK-v1", "files": files}

def prepare_rowmap(paths: list[tuple[str, Path]], expected_by_split: dict[str, int],
                   output: Path) -> tuple[int, str]:
    target = output / "rowmap.jsonl"
    tmp = output / "rowmap.jsonl.tmp"
    counts: dict[str, int] = {}
    seen: set[str] = set()
    idx = 0
    with tmp.open("w", encoding="utf-8", newline="\n") as dst:
        for split, path in paths:
            n = 0
            for row in read_jsonl(path):
                rid = row_identity(row)
                if rid in seen:
                    raise RuntimeError(f"duplicate BANK row identity: {rid}")
                seen.add(rid)
                meta = {
                    "idx": idx, "row_id": rid, "world_id": row["world_id"],
                    "split": split, "surface_family": row.get("surface_family"),
                    "paired_world": row.get("paired_world"),
                    "difficulty": row.get("difficulty") or {},
                }
                dst.write(json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n")
                idx += 1
                n += 1
            counts[split] = n
            if n != expected_by_split[split]:
                raise RuntimeError(f"{split} input rows {n} != manifest {expected_by_split[split]}")
    if target.exists():
        if sha256(target) != sha256(tmp):
            tmp.unlink()
            raise RuntimeError("existing rowmap differs from source inputs")
        tmp.unlink()
    else:
        tmp.replace(target)
    return idx, sha256(target)

def iter_input_rows(paths: list[tuple[str, Path]]):
    for split, path in paths:
        for row in read_jsonl(path):
            yield split, row

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

def output_vectors(hidden_states, mask, torch):
    batch = mask.shape[0]
    lengths = mask.sum(dim=1)
    last = lengths - 1
    rows = torch.arange(batch, device=mask.device)
    final = hidden_states[-1][rows, last, :]
    first = hidden_states[-1][:, 0, :]
    weights = mask.to(dtype=hidden_states[-1].dtype).unsqueeze(-1)
    full_mean = (hidden_states[-1] * weights).sum(dim=1) / lengths.unsqueeze(-1)
    layer_vectors = [hidden_states[-4][rows, last, :], hidden_states[-3][rows, last, :],
                     hidden_states[-2][rows, last, :]]
    middle_idx = 1 + (len(hidden_states) - 1) // 2
    middle = hidden_states[middle_idx][rows, last, :]
    vectors = {
        "final_token": final,
        "full_mean": full_mean,
        "first_token": first,
        "layer_m4_final": layer_vectors[0],
        "layer_m3_final": layer_vectors[1],
        "layer_m2_final": layer_vectors[2],
        "middle_final": middle,
    }
    return {name: np.asarray(value.detach().float().cpu().numpy(), dtype="<f4", order="C")
            for name, value in vectors.items()}

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64,
                        help="checkpoint/input grouping size")
    parser.add_argument("--microbatch-size", type=int, default=32,
                        help="forward pass size; changes throughput, not feature semantics")
    parser.add_argument("--max-length", type=int, default=2048)
    args = parser.parse_args()
    if args.batch_size < 2 or args.microbatch_size < 1 or args.microbatch_size > args.batch_size or args.max_length < 16:
        raise ValueError("require 1 <= microbatch-size <= batch-size and max-length >=16")
    args.output.mkdir(parents=True, exist_ok=True)
    feature_dir = args.output / "features"
    feature_dir.mkdir(exist_ok=True)
    paths, source_lock = source_manifest(args.bank_root)
    expected_by_split = {f["split"]: f["rows_expected"] for f in source_lock["files"]}
    row_count, rowmap_hash = prepare_rowmap(paths, expected_by_split, args.output)
    source_lock["rowmap_sha256"] = rowmap_hash
    source_lock["row_count"] = row_count
    source_lock["source_lock_sha256"] = canon_hash(source_lock)
    write_json(args.output / "source-lock.json", source_lock)

    torch = configure_torch()
    import transformers
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA:0 is required for this run")
    device = torch.device("cuda:0")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        args.model, use_fast=True, local_files_only=True, trust_remote_code=False
    )
    if not tokenizer.is_fast:
        raise RuntimeError("fast tokenizer required")
    if tokenizer.padding_side != "right":
        raise RuntimeError(f"expected right padding, got {tokenizer.padding_side}")
    model = transformers.AutoModel.from_pretrained(
        args.model, local_files_only=True, trust_remote_code=False, dtype=torch.float32
    ).eval().to(device)
    hidden_size = int(model.config.hidden_size)
    layers = int(model.config.num_hidden_layers)
    if hidden_size != 1024 or layers < 4:
        raise RuntimeError(f"unexpected LFM2.5-230M architecture: hidden={hidden_size}, layers={layers}")
    layer_map = {
        "layer_m4_final": layers - 3,
        "layer_m3_final": layers - 2,
        "layer_m2_final": layers - 1,
        "middle_final": 1 + layers // 2,
    }
    model_id = {
        "path": str(args.model.resolve()),
        "config_sha256": sha256(args.model / "config.json"),
        "weights_sha256": sha256(args.model / "model.safetensors"),
        "tokenizer_sha256": sha256(args.model / "tokenizer.json"),
        "hidden_size": hidden_size, "transformer_layers": layers,
    }
    extraction_contract = {
        "source_lock_sha256": source_lock["source_lock_sha256"],
        "model": model_id, "batch_size": args.batch_size, "max_length": args.max_length,
        "primitives": PRIMITIVES, "layer_indices": layer_map,
        "padding": "right", "first_token": "first non-padding token including BOS if present",
        "last_token": "last non-padding token including EOS if present",
        "mean": "attention-mask weighted mean including special tokens",
        "dtype": "float32", "seed": SEED,
    }
    contract_hash = canon_hash(extraction_contract)
    progress_path = feature_dir / "extraction-progress.json"
    file_paths = {name: feature_dir / f"{name}.npy" for name in PRIMITIVES}
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("contract_sha256") != contract_hash:
            raise RuntimeError("resume contract changed")
        complete = int(progress["complete_rows"])
        parity_checked = bool(progress.get("batch_parity_checked")) and int(
            progress.get("forward_microbatch_size", -1)) == args.microbatch_size
        arrays = {name: np.lib.format.open_memmap(path, mode="r+", dtype="<f4",
                                                   shape=(row_count, hidden_size))
                  for name, path in file_paths.items()}
    else:
        if any(path.exists() for path in file_paths.values()):
            raise RuntimeError("feature files exist without a resumable progress receipt")
        complete = 0
        parity_checked = False
        arrays = {name: np.lib.format.open_memmap(path, mode="w+", dtype="<f4",
                                                   shape=(row_count, hidden_size))
                  for name, path in file_paths.items()}
        progress = {"contract_sha256": contract_hash, "complete_rows": 0,
                    "batch_parity_checked": False}
        write_json(progress_path, progress)

    projection_rng = np.random.default_rng(SEED)
    projection = projection_rng.standard_normal((hidden_size, 256), dtype=np.float32) / np.sqrt(hidden_size)
    projection_path = feature_dir / "random-projection-1024x256.npy"
    if projection_path.exists():
        existing = np.load(projection_path, mmap_mode="r")
        if existing.shape != projection.shape or not np.array_equal(existing, projection):
            raise RuntimeError("stored fixed random projection differs")
    else:
        np.save(projection_path, projection, allow_pickle=False)

    started = time.perf_counter()
    rowmap_iter = iter(read_jsonl(args.output / "rowmap.jsonl"))
    inputs_iter = iter_input_rows(paths)
    skipped = 0
    batch_rows = []
    batch_meta = []
    seen = 0
    torch.cuda.reset_peak_memory_stats(device)

    def process_batch(rows, metadata, start_idx):
        texts = [r["input_text"] for _, r in rows]
        encoded = tokenizer(texts, padding=True, truncation=False, add_special_tokens=True,
                            return_tensors="pt")
        if encoded["input_ids"].shape[1] > args.max_length:
            raise RuntimeError(f"input exceeds {args.max_length} tokens: {metadata[0]['row_id']}")
        ids = encoded["input_ids"].to(device)
        mask = encoded["attention_mask"].to(device)
        with torch.inference_mode():
            output = model(input_ids=ids, attention_mask=mask, output_hidden_states=True,
                           use_cache=False, return_dict=True)
        states = output.hidden_states
        if states is None or len(states) != layers + 1:
            raise RuntimeError("model did not return the frozen hidden-state stack")
        vectors = output_vectors(states, mask, torch)
        if not np.isfinite(vectors["final_token"]).all():
            raise RuntimeError(f"nonfinite features at row {start_idx}")
        nonlocal parity_checked
        if not parity_checked:
            count = min(2, len(rows))
            for i in range(count):
                one = tokenizer(rows[i][1]["input_text"], add_special_tokens=True,
                                return_tensors="pt")
                one_ids = one["input_ids"].to(device)
                one_mask = torch.ones_like(one_ids)
                with torch.inference_mode():
                    solo = model(input_ids=one_ids, attention_mask=one_mask,
                                 output_hidden_states=True, use_cache=False, return_dict=True)
                solo_vecs = output_vectors(solo.hidden_states, one_mask, torch)
                for key in PRIMITIVES:
                    delta = np.max(np.abs(vectors[key][i] - solo_vecs[key][0]))
                    if not np.isfinite(delta) or delta > 2e-4:
                        raise RuntimeError(f"batched/single parity failed for {key}: max_abs={delta}")
            parity_checked = True
        stop_idx = start_idx + len(rows)
        for key in PRIMITIVES:
            arrays[key][start_idx:stop_idx] = vectors[key]
        del output, states, vectors, ids, mask, encoded
        return stop_idx

    for (split, row), meta in zip(inputs_iter, rowmap_iter):
        if row_identity(row) != meta["row_id"] or split != meta["split"]:
            raise RuntimeError(f"input/rowmap identity mismatch at {seen}")
        if seen < complete:
            seen += 1
            continue
        batch_rows.append((split, row))
        batch_meta.append(meta)
        seen += 1
        if len(batch_rows) >= args.batch_size:
            for offset in range(0, len(batch_rows), args.microbatch_size):
                end = min(offset + args.microbatch_size, len(batch_rows))
                complete = process_batch(batch_rows[offset:end], batch_meta[offset:end], complete)
            batch_rows, batch_meta = [], []
            for value in arrays.values():
                value.flush()
            progress = {"contract_sha256": contract_hash, "complete_rows": complete,
                        "batch_parity_checked": parity_checked,
                        "forward_microbatch_size": args.microbatch_size}
            write_json(progress_path, progress)
            if complete % 1024 < args.batch_size:
                elapsed = time.perf_counter() - started
                print(json.dumps({"phase": "extract", "rows": complete, "total": row_count,
                                  "rows_per_second": round(complete / max(elapsed, 1e-9), 2),
                                  "gpu_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device))}),
                      flush=True)
    if batch_rows:
        for offset in range(0, len(batch_rows), args.microbatch_size):
            end = min(offset + args.microbatch_size, len(batch_rows))
            complete = process_batch(batch_rows[offset:end], batch_meta[offset:end], complete)
    if seen != row_count or complete != row_count:
        raise RuntimeError(f"extraction rows seen/complete={seen}/{complete}, expected={row_count}")
    for value in arrays.values():
        value.flush()
    del arrays
    torch.cuda.synchronize(device)
    source_lock_after = []
    for split, path in paths:
        source_lock_after.append({"split": split, "sha256": sha256(path), "bytes": path.stat().st_size})
    if any(source_lock_after[i]["sha256"] != source_lock["files"][i]["sha256"]
           for i in range(len(source_lock_after))):
        raise RuntimeError("BANK inputs changed during extraction")
    receipt = {
        "schema": "phoenix.bank-v1-230m-surface-extraction/v1",
        "surface_sweep": "BANK-v1-230M-SURFACE-EXTREMES-2026-09-29",
        "rows": row_count, "hidden_size": hidden_size, "layers": layers,
        "layer_indices": layer_map, "primitives": {
            name: {"path": str(path.resolve()), "sha256": sha256(path), "shape": [row_count, hidden_size],
                   "dtype": "float32-le"} for name, path in file_paths.items()
        },
        "random_projection": {"path": str(projection_path.resolve()), "sha256": sha256(projection_path),
                              "shape": list(projection.shape), "seed": SEED,
                              "normalization": "standard normal divided by sqrt(hidden_size)"},
        "source_lock_sha256": source_lock["source_lock_sha256"],
        "rowmap_sha256": rowmap_hash, "model": model_id,
        "batch_size": args.batch_size, "forward_microbatch_size": args.microbatch_size, "max_length": args.max_length,
        "batch_single_parity": {"checked": parity_checked, "max_abs_tolerance": 2e-4},
        "truth_joined": False, "generation": False, "fine_tuning": False,
        "elapsed_seconds": time.perf_counter() - started,
        "gpu_peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
        "gpu_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
        "runtime": {"torch": torch.__version__, "transformers": transformers.__version__,
                    "device": torch.cuda.get_device_name(device)},
    }
    write_json(feature_dir / "extraction-seal.json", receipt)
    progress_path.unlink(missing_ok=True)
    print(json.dumps({"phase": "extract_complete", "rows": row_count,
                      "elapsed_seconds": receipt["elapsed_seconds"],
                      "gpu_peak_reserved_bytes": receipt["gpu_peak_reserved_bytes"]}), flush=True)

if __name__ == "__main__":
    main()

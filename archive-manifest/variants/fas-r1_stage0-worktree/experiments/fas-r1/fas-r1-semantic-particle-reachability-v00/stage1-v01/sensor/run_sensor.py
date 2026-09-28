#!/usr/bin/env python3
"""Extract frozen LFM final-layer mean vectors for public R1 renderings."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import sys
import traceback
from pathlib import Path
from typing import Any

MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
SCHEMA = "R1_STAGE1_SENSOR_EXTRACTION_V01"
TASK_FIELDS = {
    "id", "family_id", "n", "k", "role_anonymous", "global_text", "clauses",
    "entity_mentions", "role_mentions",
}
TOKENIZER_FILES = {
    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "added_tokens.json", "spiece.model", "sentencepiece.bpe.model",
    "vocab.json", "vocab.txt", "merges.txt",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "MISSING"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, obj: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def read_tasks(path: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"bad JSON on line {line_no}: {exc}") from exc
            if not isinstance(row, dict) or set(row) != TASK_FIELDS:
                raise ValueError(f"line {line_no} is not the exact public InferenceTask schema")
            if not isinstance(row["id"], str) or not row["id"] or row["id"] in seen:
                raise ValueError(f"line {line_no} has an empty or duplicate task id")
            if not isinstance(row["family_id"], str) or not row["family_id"]:
                raise ValueError(f"line {line_no} has an invalid family id")
            if not isinstance(row["global_text"], str) or not row["global_text"]:
                raise ValueError(f"line {line_no} has empty global text")
            clauses = row["clauses"]
            if not isinstance(clauses, list) or any(
                not isinstance(item, str) or not item for item in clauses
            ):
                raise ValueError(f"line {line_no} has invalid clauses")
            for key in ("entity_mentions", "role_mentions"):
                if not isinstance(row[key], list) or len(row[key]) != len(clauses):
                    raise ValueError(f"line {line_no} has invalid {key}")
            seen.add(row["id"])
            tasks.append(row)
    if not tasks:
        raise ValueError("input contains no public tasks")
    return tasks


def verify_support_manifest(path: Path | None, input_hash: str,
                            tasks: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, str]]:
    if path is None:
        return None, {}
    manifest_path = path.expanduser().resolve(strict=True)
    digest, _ = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = manifest.get("source", {})
    if source.get("sha256") != input_hash:
        raise ValueError("input SHA-256 does not match frozen sensor support manifest")
    if source.get("rows") != len(tasks):
        raise ValueError("input row count does not match frozen sensor support manifest")
    roster = manifest.get("family_roster")
    if not isinstance(roster, list) or len(roster) != len(tasks):
        raise ValueError("support manifest has no complete family roster")
    roster_by_id = {entry.get("task_id"): entry for entry in roster}
    if len(roster_by_id) != len(roster):
        raise ValueError("support manifest contains duplicate task ids")
    family_split: dict[str, str] = {}
    split_counts: dict[str, int] = {}
    for task in tasks:
        entry = roster_by_id.get(task["id"])
        if entry is None or entry.get("family_id") != task["family_id"]:
            raise ValueError(f"task/family roster mismatch for {task['id']}")
        split = entry.get("split")
        if split not in ("train", "validation", "qualification"):
            raise ValueError(f"unsupported family split {split!r}")
        family_split[task["family_id"]] = split
        split_counts[split] = split_counts.get(split, 0) + 1
    observed_counts = {key: split_counts.get(key, 0)
                       for key in ("train", "validation", "qualification")}
    expected_counts = manifest.get("split_counts")
    legacy_counts = {f"{key}_families": observed_counts[key] for key in observed_counts}
    if expected_counts not in (observed_counts, legacy_counts):
        raise ValueError("observed family split counts do not match frozen manifest")
    return {
        "path": str(manifest_path), "sha256": digest,
        "split_counts": observed_counts,
        "action_relevance_support": manifest.get("action_relevance_support"),
        "gates": manifest.get("gates"),
    }, family_split


def resolve_snapshot(snapshot_dir: Path | None, cache_dir: Path | None) -> Path:
    if snapshot_dir is None:
        if cache_dir is None:
            raise ValueError("supply --snapshot-dir or --cache-dir")
        from huggingface_hub import snapshot_download
        snapshot_dir = Path(snapshot_download(
            repo_id=MODEL_ID, revision=MODEL_REVISION,
            cache_dir=str(cache_dir), local_files_only=True,
        ))
    snapshot = snapshot_dir.expanduser().resolve(strict=True)
    if not snapshot.is_dir():
        raise ValueError(f"snapshot path is not a directory: {snapshot}")
    return snapshot


def hash_snapshot(snapshot: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files: list[dict[str, Any]] = []
    tokenizer_files: list[dict[str, Any]] = []
    paths = sorted(
        path for path in snapshot.rglob("*")
        if path.is_file() and ".cache" not in path.relative_to(snapshot).parts
    )
    for number, path in enumerate(paths, start=1):
        digest, size = sha256_file(path)
        item = {"path": path.relative_to(snapshot).as_posix(), "bytes": size, "sha256": digest}
        files.append(item)
        name = path.name.lower()
        if name in TOKENIZER_FILES or name.startswith(("vocab.", "merges.")):
            tokenizer_files.append(item)
        if number % 4 == 0 or number == len(paths):
            print(f"hashed snapshot files: {number}/{len(paths)}", file=sys.stderr, flush=True)
    if not files or not tokenizer_files:
        raise ValueError("snapshot is missing model files or identifiable tokenizer files")
    return files, tokenizer_files


def verify_model_manifest(path: Path, snapshot: Path,
                          snapshot_files: list[dict[str, Any]]) -> dict[str, Any]:
    manifest_path = path.expanduser().resolve(strict=True)
    manifest_hash, _ = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("model_id") != MODEL_ID or manifest.get("revision") != MODEL_REVISION:
        raise ValueError("model contact manifest does not match pinned model ID/revision")
    declared_snapshot = Path(manifest.get("local_snapshot", "")).resolve()
    if os.path.normcase(str(declared_snapshot)) != os.path.normcase(str(snapshot)):
        raise ValueError("resolved local model path disagrees with frozen model contact manifest")
    records = {item["path"].lower(): item for item in snapshot_files}
    expected = manifest.get("files", {})
    for relpath, spec in expected.items():
        item = records.get(str(relpath).lower())
        if item is None:
            raise ValueError(f"model manifest file missing from snapshot: {relpath}")
        if item["sha256"].lower() != str(spec.get("sha256", "")).lower():
            raise ValueError(f"model manifest hash mismatch for {relpath}")
        if "bytes" in spec and item["bytes"] != spec["bytes"]:
            raise ValueError(f"model manifest size mismatch for {relpath}")
    return {"path": str(manifest_path), "sha256": manifest_hash, "files": expected}


def get_hidden_size(config: Any) -> int:
    for name in ("hidden_size", "d_model"):
        value = getattr(config, name, None)
        if isinstance(value, int) and value > 0:
            return value
    raise ValueError("config exposes neither positive hidden_size nor d_model")


def choose_device_dtype(torch: Any, device_request: str, dtype_request: str) -> tuple[Any, Any, str]:
    device = torch.device(
        "cuda" if device_request == "auto" and torch.cuda.is_available()
        else "cpu" if device_request == "auto"
        else device_request
    )
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    if dtype_request == "auto":
        if device.type == "cuda":
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        else:
            dtype = torch.float32
    else:
        dtype = {
            "float32": torch.float32, "bfloat16": torch.bfloat16,
            "float16": torch.float16,
        }[dtype_request]
    if device.type == "cpu" and dtype is not torch.float32:
        raise ValueError("CPU extraction requires --model-dtype float32")
    return device, dtype, str(dtype).removeprefix("torch.")


def set_determinism(torch: Any, seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.deterministic = True
    torch.set_float32_matmul_precision("highest")
    torch.use_deterministic_algorithms(True)


def encode_mean(text: str, tokenizer: Any, model: Any, torch: Any,
                device: Any, hidden_size: int) -> tuple[Any, int]:
    encoded = tokenizer(
        text, add_special_tokens=True, padding=False, truncation=False,
        return_tensors="pt",
    )
    ids, mask = encoded.get("input_ids"), encoded.get("attention_mask")
    if ids is None or ids.ndim != 2 or ids.shape[0] != 1:
        raise ValueError("tokenizer did not return one unpadded sequence")
    if mask is None or mask.shape != ids.shape:
        raise ValueError("tokenizer returned no matching attention mask")
    token_count = int(ids.shape[1])
    if token_count == 0 or int(mask.sum().item()) != token_count:
        raise ValueError("tokenizer introduced padding or an empty sequence")
    inputs = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        outputs = model(
            **inputs, output_hidden_states=True, return_dict=True, use_cache=False,
        )
    states = getattr(outputs, "hidden_states", None)
    if states is None or len(states) < 2:
        raise ValueError("model did not return final hidden states")
    final = states[-1]
    if final.ndim != 3 or tuple(final.shape) != (1, token_count, hidden_size):
        raise ValueError("final hidden shape disagrees with token count/config")
    visible = inputs["attention_mask"][0].to(dtype=torch.bool)
    mean = final[0, visible, :].to(dtype=torch.float32).mean(dim=0).cpu().contiguous()
    if mean.shape != (hidden_size,) or not bool(torch.isfinite(mean).all().item()):
        raise ValueError("mean vector has invalid shape or non-finite values")
    return mean, token_count


def vector_bytes(vector: Any, np: Any) -> bytes:
    return np.asarray(vector, dtype="<f4").tobytes(order="C")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Stage 0 public-tasks.jsonl")
    parser.add_argument("--output", type=Path, required=True, help="new output directory")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshot-dir", type=Path, help="materialized pinned local snapshot")
    src.add_argument("--cache-dir", type=Path, help="HF cache, resolved local_files_only")
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or torch device")
    parser.add_argument("--model-dtype", choices=("auto", "float32", "bfloat16", "float16"),
                        default="auto")
    parser.add_argument("--seed", type=int, default=73025)
    parser.add_argument("--support-manifest", type=Path, help="frozen v01 sensor support manifest")
    parser.add_argument("--model-manifest", type=Path, required=True, help="frozen model contact manifest")
    return parser.parse_args()


def run(args: argparse.Namespace) -> None:
    input_path = args.input.expanduser().resolve(strict=True)
    output_path = args.output.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing output {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.mkdir()
    input_hash, input_size = sha256_file(input_path)
    tasks = read_tasks(input_path)
    support_record, family_split = verify_support_manifest(args.support_manifest, input_hash, tasks)
    import numpy as np
    import torch
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    set_determinism(torch, args.seed)
    snapshot = resolve_snapshot(args.snapshot_dir, args.cache_dir)
    snapshot_files, tokenizer_files = hash_snapshot(snapshot)
    model_manifest_record = verify_model_manifest(args.model_manifest, snapshot, snapshot_files)
    config = AutoConfig.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    hidden_size = get_hidden_size(config)
    device, dtype, dtype_name = choose_device_dtype(torch, args.device, args.model_dtype)
    tokenizer = AutoTokenizer.from_pretrained(
        snapshot, local_files_only=True, trust_remote_code=False, use_fast=True,
    )
    model = AutoModel.from_pretrained(
        snapshot, local_files_only=True, trust_remote_code=False,
        dtype=dtype, low_cpu_mem_usage=True,
    ).to(device)
    model.eval()
    if model.training or get_hidden_size(model.config) != hidden_size:
        raise RuntimeError("loaded model is training or config hidden size changed")

    # Repeat one public input before corpus extraction and require byte identity.
    verification_text = tasks[0]["global_text"]
    verify1, token_count = encode_mean(verification_text, tokenizer, model, torch, device, hidden_size)
    verify2, token_count2 = encode_mean(verification_text, tokenizer, model, torch, device, hidden_size)
    verify_hash1 = sha256_bytes(vector_bytes(verify1.numpy(), np))
    verify_hash2 = sha256_bytes(vector_bytes(verify2.numpy(), np))
    if token_count != token_count2 or verify_hash1 != verify_hash2:
        raise RuntimeError("identical verification input produced different float32 outputs")

    constraints = sum(len(task["clauses"]) for task in tasks)
    h_path, g_path = output_path / "constraint_H.float32.npy", output_path / "global_h.float32.npy"
    h = np.lib.format.open_memmap(h_path, mode="w+", dtype="<f4",
                                  shape=(constraints, hidden_size))
    g = np.lib.format.open_memmap(g_path, mode="w+", dtype="<f4",
                                  shape=(len(tasks), hidden_size))
    rows_path = output_path / "rows.jsonl"
    constraint_row = 0
    with rows_path.open("x", encoding="utf-8", newline="\n") as rows_file:
        for task_index, task in enumerate(tasks):
            vec, count = encode_mean(task["global_text"], tokenizer, model, torch, device, hidden_size)
            raw = vector_bytes(vec.numpy(), np)
            g[task_index, :] = np.frombuffer(raw, dtype="<f4")
            row = {
                "kind": "global", "task_index": task_index, "task_id": task["id"],
                "family_id": task["family_id"], "split": family_split.get(task["family_id"]),
                "row": task_index, "token_count": count,
                "input_text_sha256": sha256_bytes(task["global_text"].encode("utf-8")),
                "output_float32_sha256": sha256_bytes(raw),
            }
            rows_file.write(json.dumps(row, sort_keys=True) + "\n")
            for clause_index, clause in enumerate(task["clauses"]):
                vec, count = encode_mean(clause, tokenizer, model, torch, device, hidden_size)
                raw = vector_bytes(vec.numpy(), np)
                h[constraint_row, :] = np.frombuffer(raw, dtype="<f4")
                row = {
                    "kind": "constraint", "task_index": task_index, "task_id": task["id"],
                    "family_id": task["family_id"], "split": family_split.get(task["family_id"]),
                    "clause_index": clause_index,
                    "row": constraint_row, "token_count": count,
                    "input_text_sha256": sha256_bytes(clause.encode("utf-8")),
                    "output_float32_sha256": sha256_bytes(raw),
                }
                rows_file.write(json.dumps(row, sort_keys=True) + "\n")
                constraint_row += 1
            if (task_index + 1) % 8 == 0 or task_index + 1 == len(tasks):
                h.flush()
                g.flush()
                rows_file.flush()
                print(f"encoded tasks: {task_index + 1}/{len(tasks)}", file=sys.stderr, flush=True)
    h.flush()
    g.flush()
    del h, g

    post_files, _ = hash_snapshot(snapshot)
    expected_before = {item["path"]: item["sha256"] for item in snapshot_files}
    expected_after = {item["path"]: item["sha256"] for item in post_files}
    if expected_before != expected_after:
        raise RuntimeError("pinned snapshot file hashes changed during extraction")
    output_files = []
    for path in sorted(output_path.iterdir()):
        if path.is_file():
            digest, size = sha256_file(path)
            output_files.append({"path": path.name, "bytes": size, "sha256": digest})
    device_name = torch.cuda.get_device_name(device) if device.type == "cuda" else platform.processor() or "CPU"
    receipt = {
        "schema": SCHEMA,
        "status": "R1_SENSOR_EXTRACTION_COMPLETE",
        "created_utc": utc_now(),
        "model": {
            "repo_id": MODEL_ID, "revision": MODEL_REVISION,
            "snapshot_path": str(snapshot), "model_class": type(model).__name__,
            "config_model_type": getattr(model.config, "model_type", None),
            "config_architectures": getattr(model.config, "architectures", None),
            "hidden_size": hidden_size, "model_compute_dtype": dtype_name,
            "output_dtype": "float32", "device": str(device), "device_name": device_name,
            "snapshot_files": snapshot_files, "tokenizer_files": tokenizer_files,
            "model_contact_manifest": model_manifest_record,
            "snapshot_hashes_unchanged_after_extraction": True,
        },
        "extraction": {
            "representation": "final hidden layer; arithmetic mean over visible token positions",
            "cast": "visible activations cast to float32 before arithmetic mean",
            "special_tokens": "tokenizer defaults enabled",
            "padding": False, "truncation": False, "eval_mode": True, "inference_mode": True,
            "deterministic_algorithms": True, "seed": args.seed,
            "verification": {
                "input_text_sha256": sha256_bytes(verification_text.encode("utf-8")),
                "token_count": token_count,
                "repeat_1_output_float32_sha256": verify_hash1,
                "repeat_2_output_float32_sha256": verify_hash2,
                "exact_repeat_match": True,
            },
        },
        "input": {
            "path": str(input_path), "bytes": input_size, "sha256": input_hash,
            "public_task_count": len(tasks), "constraint_count": constraints,
            "support_manifest": support_record,
        },
        "software": {
            "python": sys.version, "platform": platform.platform(),
            "torch": version("torch"), "transformers": version("transformers"),
            "huggingface_hub": version("huggingface_hub"), "numpy": version("numpy"),
        },
        "training_performed": False, "probe_fit_performed": False,
        "selector_training_performed": False, "proposal_training_performed": False,
        "reach_value_training_performed": False, "output_files": output_files,
    }
    write_json(output_path / "receipt.json", receipt)
    print("R1_SENSOR_EXTRACTION_COMPLETE")


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    already_existed = output.exists()
    try:
        run(args)
    except BaseException as error:
        print(f"R1_SENSOR_EXTRACTION_FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        if not already_existed and output.is_dir() and not (output / "failure.json").exists():
            try:
                write_json(output / "failure.json", {
                    "schema": "R1_STAGE1_SENSOR_FAILURE_V01",
                    "status": "R1_SENSOR_EXTRACTION_FAILED", "created_utc": utc_now(),
                    "exception_type": type(error).__name__, "error": str(error),
                    "traceback": traceback.format_exc(),
                })
            except Exception as report_error:
                print(f"could not write failure receipt: {report_error}", file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


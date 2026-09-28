#!/usr/bin/env python3
"""Extract frozen LFM final-layer mean vectors for public R1 renderings.

The program is intentionally an extraction harness only. It does not fit a
probe, proposal, value function, or selector. The typed task AST and oracle
labels are not accepted as inputs.
"""

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
import time
from pathlib import Path
from typing import Any, Iterator

MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
SCHEMA = "R1_STAGE1_SENSOR_EXTRACTION_V01"
THREAD_ENV = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
TOKENIZER_FILENAMES = {
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "spiece.model",
    "sentencepiece.bpe.model",
    "vocab.json",
    "vocab.txt",
    "merges.txt",
}
REQUIRED_TASK_FIELDS = {
    "id",
    "family_id",
    "n",
    "k",
    "role_anonymous",
    "global_text",
    "clauses",
    "entity_mentions",
    "role_mentions",
}
REQUIRED_NAME_FIELDS = {"name_id", "kind", "surface"}


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


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "MISSING"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def read_public_tasks(path: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                task = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on input line {line_number}: {error}") from error
            if not isinstance(task, dict) or set(task) != REQUIRED_TASK_FIELDS:
                raise ValueError(
                    f"input line {line_number} is not the exact public InferenceTask schema"
                )
            if not isinstance(task["id"], str) or not task["id"]:
                raise ValueError(f"input line {line_number} has an invalid task id")
            if task["id"] in seen:
                raise ValueError(f"duplicate task id on input line {line_number}")
            if not isinstance(task["family_id"], str) or not task["family_id"]:
                raise ValueError(f"input line {line_number} has an invalid family id")
            if not isinstance(task["global_text"], str) or not task["global_text"]:
                raise ValueError(f"input line {line_number} has no global text")
            clauses = task["clauses"]
            if not isinstance(clauses, list) or not clauses or any(
                not isinstance(clause, str) or not clause for clause in clauses
            ):
                raise ValueError(f"input line {line_number} has invalid rendered clauses")
            if not isinstance(task["entity_mentions"], list) or not isinstance(
                task["role_mentions"], list
            ):
                raise ValueError(f"input line {line_number} has invalid public mention metadata")
            if len(task["entity_mentions"]) != len(clauses) or len(
                task["role_mentions"]
            ) != len(clauses):
                raise ValueError(f"input line {line_number} mention metadata length mismatch")
            seen.add(task["id"])
            tasks.append(task)
    if not tasks:
        raise ValueError("input contains no public R1 tasks")
    return tasks


def read_name_queries(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    queries: list[dict[str, str]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on name-query line {line_number}: {error}") from error
            if not isinstance(row, dict) or set(row) != REQUIRED_NAME_FIELDS:
                raise ValueError(f"name-query line {line_number} does not match the exact schema")
            if (
                not isinstance(row["name_id"], str)
                or not row["name_id"]
                or row["name_id"] in seen
                or row["kind"] not in {"entities", "roles"}
                or not isinstance(row["surface"], str)
                or not row["surface"]
            ):
                raise ValueError(f"invalid or duplicate name-query row {line_number}")
            queries.append(row)
            seen.add(row["name_id"])
    if not queries:
        raise ValueError("name-query input contains no records")
    return queries


def text_rows(tasks: list[dict[str, Any]]) -> Iterator[tuple[str, str, int | None, str]]:
    for task in tasks:
        task_id = task["id"]
        yield task_id, task["family_id"], None, task["global_text"]
        for clause_index, clause in enumerate(task["clauses"]):
            yield task_id, task["family_id"], clause_index, clause


def resolve_snapshot(snapshot_dir: Path | None, cache_dir: Path | None) -> Path:
    if snapshot_dir is not None:
        snapshot = snapshot_dir.expanduser().resolve(strict=True)
    else:
        if cache_dir is None:
            raise ValueError("supply --snapshot-dir or --cache-dir")
        from huggingface_hub import snapshot_download

        snapshot = Path(
            snapshot_download(
                repo_id=MODEL_ID,
                revision=MODEL_REVISION,
                cache_dir=str(cache_dir),
                local_files_only=True,
            )
        ).resolve(strict=True)
    if not snapshot.is_dir():
        raise ValueError(f"snapshot path is not a directory: {snapshot}")
    if snapshot.name != MODEL_REVISION:
        raise ValueError(
            f"snapshot directory name is {snapshot.name!r}; expected pinned revision {MODEL_REVISION}"
        )
    return snapshot


def hash_snapshot(snapshot: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_files: list[dict[str, Any]] = []
    tokenizer_files: list[dict[str, Any]] = []
    paths = sorted(
        path
        for path in snapshot.rglob("*")
        if path.is_file() and ".cache" not in path.relative_to(snapshot).parts
    )
    for index, path in enumerate(paths, start=1):
        digest, size = sha256_file(path)
        record = {"path": path.relative_to(snapshot).as_posix(), "bytes": size, "sha256": digest}
        all_files.append(record)
        basename = path.name.lower()
        if basename in TOKENIZER_FILENAMES or basename.startswith("vocab.") or basename.startswith(
            "merges."
        ):
            tokenizer_files.append(record)
        if index % 4 == 0 or index == len(paths):
            print(f"hashed snapshot files: {index}/{len(paths)}", file=sys.stderr, flush=True)
    if not all_files:
        raise ValueError("resolved model snapshot contains no files")
    if not tokenizer_files:
        raise ValueError("could not identify tokenizer files in pinned snapshot")
    return all_files, tokenizer_files


def choose_device_dtype(torch: Any, requested_device: str, requested_dtype: str) -> tuple[Any, Any, str]:
    if requested_device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(requested_device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but torch.cuda.is_available() is false")
    if requested_dtype == "auto":
        if device.type == "cuda":
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        else:
            dtype = torch.float32
    else:
        dtype = {
            "float32": torch.float32,
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
        }[requested_dtype]
    if device.type == "cpu" and dtype in (torch.float16, torch.bfloat16):
        raise ValueError("CPU extraction requires --model-dtype float32")
    return device, dtype, str(dtype).removeprefix("torch.")


def configure_determinism(torch: Any, seed: int) -> None:
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.deterministic = True
    torch.set_float32_matmul_precision("highest")
    torch.use_deterministic_algorithms(True)


def get_hidden_size(config: Any) -> int:
    for field in ("hidden_size", "d_model"):
        value = getattr(config, field, None)
        if isinstance(value, int) and value > 0:
            return value
    raise ValueError("pinned model config exposes neither a positive hidden_size nor d_model")


def encode_mean(
    text: str,
    tokenizer: Any,
    model: Any,
    torch: Any,
    device: Any,
    hidden_size: int,
) -> tuple[Any, int]:
    encoded = tokenizer(
        text,
        add_special_tokens=True,
        padding=False,
        truncation=False,
        return_tensors="pt",
    )
    input_ids = encoded.get("input_ids")
    attention_mask = encoded.get("attention_mask")
    if input_ids is None or input_ids.ndim != 2 or input_ids.shape[0] != 1:
        raise ValueError("tokenizer did not produce one unpadded input sequence")
    if attention_mask is None or attention_mask.shape != input_ids.shape:
        raise ValueError("tokenizer did not produce a matching attention mask")
    token_count = int(input_ids.shape[1])
    visible_cpu = attention_mask[0].to(dtype=torch.bool)
    if token_count == 0 or int(visible_cpu.sum().item()) != token_count:
        raise ValueError("tokenizer introduced padding or returned an empty visible sequence")
    model_inputs = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        outputs = model(
            **model_inputs,
            output_hidden_states=True,
            return_dict=True,
            use_cache=False,
        )
    hidden_states = getattr(outputs, "hidden_states", None)
    if hidden_states is None or len(hidden_states) < 2:
        raise ValueError("model did not return final hidden states")
    final_hidden = hidden_states[-1]
    if final_hidden.ndim != 3 or final_hidden.shape[0] != 1:
        raise ValueError("final hidden layer has unexpected batch/sequence shape")
    if final_hidden.shape[1] != token_count or final_hidden.shape[2] != hidden_size:
        raise ValueError("final hidden layer shape disagrees with token count/config hidden size")
    visible = model_inputs["attention_mask"][0].to(dtype=torch.bool)
    # Convert each visible activation to float32 before the arithmetic mean.
    mean = final_hidden[0, visible, :].to(dtype=torch.float32).mean(dim=0)
    if mean.shape != (hidden_size,) or not bool(torch.isfinite(mean).all().item()):
        raise ValueError("mean vector has an invalid shape or non-finite values")
    return mean.cpu().contiguous(), token_count


def output_bytes(vector: Any, numpy: Any) -> bytes:
    return numpy.asarray(vector, dtype="<f4").tobytes(order="C")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Stage 0 public-tasks.jsonl")
    parser.add_argument(
        "--name-input",
        type=Path,
        help="optional exact name-query JSONL for the Stage 1 binding probe",
    )
    parser.add_argument("--output", type=Path, required=True, help="new, empty output directory")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot-dir", type=Path, help="already-materialized pinned snapshot")
    source.add_argument("--cache-dir", type=Path, help="HF cache, resolved local_files_only")
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or an explicit torch device")
    parser.add_argument(
        "--model-dtype",
        choices=("auto", "float32", "bfloat16", "float16"),
        default="auto",
        help="model compute dtype; extracted means are always float32",
    )
    parser.add_argument("--seed", type=int, default=73025, help="deterministic runtime seed")
    return parser.parse_args()


def run(args: argparse.Namespace) -> None:
    for name in THREAD_ENV:
        configured = os.environ.get(name)
        if configured not in (None, "1"):
            raise ValueError(f"{name} must be unset or 1 before numerical runtime import; got {configured!r}")
        os.environ[name] = "1"
    input_path = args.input.expanduser().resolve(strict=True)
    name_input_path = args.name_input.expanduser().resolve(strict=True) if args.name_input else None
    output_path = args.output.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.mkdir()
    input_digest, input_bytes = sha256_file(input_path)
    name_input_digest, name_input_bytes = (
        sha256_file(name_input_path) if name_input_path is not None else (None, 0)
    )
    tasks = read_public_tasks(input_path)
    name_queries = read_name_queries(name_input_path)
    rows = list(text_rows(tasks))

    import numpy as np
    import torch
    import transformers
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    configure_determinism(torch, args.seed)
    snapshot = resolve_snapshot(args.snapshot_dir, args.cache_dir)
    snapshot_files, tokenizer_files = hash_snapshot(snapshot)
    config = AutoConfig.from_pretrained(
        snapshot,
        local_files_only=True,
        trust_remote_code=False,
    )
    hidden_size = get_hidden_size(config)
    device, model_dtype, model_dtype_name = choose_device_dtype(
        torch, args.device, args.model_dtype
    )
    tokenizer = AutoTokenizer.from_pretrained(
        snapshot,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    model = AutoModel.from_pretrained(
        snapshot,
        local_files_only=True,
        trust_remote_code=False,
        dtype=model_dtype,
        low_cpu_mem_usage=True,
    )
    model.to(device)
    model.eval()
    if model.training:
        raise RuntimeError("model remained in training mode")
    loaded_hidden_size = get_hidden_size(model.config)
    if loaded_hidden_size != hidden_size:
        raise ValueError("AutoConfig and loaded model hidden sizes disagree")

    # Verify repeat stability before writing any task embeddings.
    verification_text = tasks[0]["global_text"]
    verify_a, verify_tokens_a = encode_mean(
        verification_text, tokenizer, model, torch, device, hidden_size
    )
    verify_b, verify_tokens_b = encode_mean(
        verification_text, tokenizer, model, torch, device, hidden_size
    )
    verify_hash_a = sha256_bytes(output_bytes(verify_a.numpy(), np))
    verify_hash_b = sha256_bytes(output_bytes(verify_b.numpy(), np))
    if verify_tokens_a != verify_tokens_b or verify_hash_a != verify_hash_b:
        raise RuntimeError("pinned model output changed across exact repeated inference")

    constraint_count = sum(len(task["clauses"]) for task in tasks)
    constraint_path = output_path / "constraint_H.float32.npy"
    global_path = output_path / "global_h.float32.npy"
    constraint_array = np.lib.format.open_memmap(
        constraint_path, mode="w+", dtype="<f4", shape=(constraint_count, hidden_size)
    )
    global_array = np.lib.format.open_memmap(
        global_path, mode="w+", dtype="<f4", shape=(len(tasks), hidden_size)
    )
    name_array = (
        np.lib.format.open_memmap(
            output_path / "name_H.float32.npy",
            mode="w+",
            dtype="<f4",
            shape=(len(name_queries), hidden_size),
        )
        if name_queries
        else None
    )
    row_path = output_path / "rows.jsonl"
    constraint_row = 0
    with row_path.open("x", encoding="utf-8", newline="\n") as row_stream:
        if name_array is not None:
            for name_index, query in enumerate(name_queries):
                vector, token_count = encode_mean(
                    query["surface"], tokenizer, model, torch, device, hidden_size
                )
                raw = output_bytes(vector.numpy(), np)
                name_array[name_index, :] = np.frombuffer(raw, dtype="<f4")
                row = {
                    "kind": "name",
                    "name_id": query["name_id"],
                    "name_kind": query["kind"],
                    "surface": query["surface"],
                    "row": name_index,
                    "token_count": token_count,
                    "input_text_sha256": sha256_bytes(query["surface"].encode("utf-8")),
                    "output_float32_sha256": sha256_bytes(raw),
                }
                row_stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            name_array.flush()
        for task_index, task in enumerate(tasks):
            vector, token_count = encode_mean(
                task["global_text"], tokenizer, model, torch, device, hidden_size
            )
            raw = output_bytes(vector.numpy(), np)
            global_array[task_index, :] = np.frombuffer(raw, dtype="<f4")
            row = {
                "kind": "global",
                "task_index": task_index,
                "task_id": task["id"],
                "family_id": task["family_id"],
                "row": task_index,
                "token_count": token_count,
                "input_text_sha256": sha256_bytes(task["global_text"].encode("utf-8")),
                "output_float32_sha256": sha256_bytes(raw),
            }
            row_stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            for clause_index, clause in enumerate(task["clauses"]):
                vector, token_count = encode_mean(clause, tokenizer, model, torch, device, hidden_size)
                raw = output_bytes(vector.numpy(), np)
                constraint_array[constraint_row, :] = np.frombuffer(raw, dtype="<f4")
                row = {
                    "kind": "constraint",
                    "task_index": task_index,
                    "task_id": task["id"],
                    "family_id": task["family_id"],
                    "clause_index": clause_index,
                    "row": constraint_row,
                    "token_count": token_count,
                    "input_text_sha256": sha256_bytes(clause.encode("utf-8")),
                    "output_float32_sha256": sha256_bytes(raw),
                }
                row_stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                constraint_row += 1
            if (task_index + 1) % 8 == 0 or task_index + 1 == len(tasks):
                constraint_array.flush()
                global_array.flush()
                row_stream.flush()
                print(f"encoded tasks: {task_index + 1}/{len(tasks)}", file=sys.stderr, flush=True)
    constraint_array.flush()
    global_array.flush()
    if name_array is not None:
        name_array.flush()
    del constraint_array, global_array, name_array

    output_files = []
    for path in sorted(output_path.iterdir()):
        if path.is_file() and path.name not in {"receipt.json", "receipt.json.partial"}:
            digest, size = sha256_file(path)
            output_files.append({"path": path.name, "bytes": size, "sha256": digest})
    device_name = (
        torch.cuda.get_device_name(device) if device.type == "cuda" else platform.processor() or "CPU"
    )
    verification = {
        "text_sha256": sha256_bytes(verification_text.encode("utf-8")),
        "token_count": verify_tokens_a,
        "repeat_1_output_float32_sha256": verify_hash_a,
        "repeat_2_output_float32_sha256": verify_hash_b,
        "exact_repeat_match": True,
    }
    receipt = {
        "schema": SCHEMA,
        "status": "R1_SENSOR_EXTRACTION_COMPLETE",
        "created_utc": utc_now(),
        "stage": "frozen extraction only",
        "model": {
            "repo_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "snapshot_path": str(snapshot),
            "model_class": type(model).__name__,
            "config_model_type": getattr(model.config, "model_type", None),
            "config_architectures": getattr(model.config, "architectures", None),
            "hidden_size": hidden_size,
            "model_compute_dtype": model_dtype_name,
            "output_dtype": "float32",
            "device": str(device),
            "device_name": device_name,
            "eval_mode": True,
            "inference_mode": True,
            "weights_tied_or_shared": None,
            "snapshot_files": snapshot_files,
            "tokenizer_files": tokenizer_files,
        },
        "extraction": {
            "representation": "final hidden layer; arithmetic mean over visible token positions",
            "output_cast": "each visible final-layer activation converted to float32 before mean",
            "special_tokens": "tokenizer defaults enabled",
            "padding": False,
            "truncation": False,
            "per_constraint_encoding": "each rendered clause is tokenized and encoded independently",
            "global_encoding": "global_text is tokenized and encoded independently",
            "deterministic_algorithms": True,
            "seed": args.seed,
            "verification": verification,
        },
        "input": {
            "path": str(input_path),
            "bytes": input_bytes,
            "sha256": input_digest,
            "public_task_count": len(tasks),
            "constraint_count": constraint_count,
            "name_query": {
                "path": str(name_input_path) if name_input_path is not None else None,
                "bytes": name_input_bytes,
                "sha256": name_input_digest,
                "count": len(name_queries),
            },
            "row_order": "name rows first when supplied; then task input order with global row and clauses in rendered order",
        },
        "software": {
            "python": sys.version,
            "platform": platform.platform(),
            "torch": package_version("torch"),
            "transformers": package_version("transformers"),
            "huggingface_hub": package_version("huggingface_hub"),
            "numpy": package_version("numpy"),
            "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
            "torch_intraop_threads": torch.get_num_threads(),
            "torch_interop_threads": torch.get_num_interop_threads(),
        },
        "fit_performed": False,
        "selector_training_performed": False,
        "proposal_training_performed": False,
        "reach_value_training_performed": False,
        "output_files": output_files,
    }
    write_json(output_path / "receipt.json", receipt)
    print("R1_SENSOR_EXTRACTION_COMPLETE")


def main() -> int:
    args = parse_args()
    requested_output = args.output.expanduser().resolve()
    output_existed_before_run = requested_output.exists()
    try:
        run(args)
    except Exception as error:
        print(f"R1_SENSOR_EXTRACTION_FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        if not output_existed_before_run and requested_output.is_dir():
            failure_path = requested_output / "failure.json"
            if not failure_path.exists():
                try:
                    write_json(
                        failure_path,
                        {
                            "schema": "R1_STAGE1_SENSOR_FAILURE_V01",
                            "status": "R1_SENSOR_EXTRACTION_FAILED",
                            "created_utc": utc_now(),
                            "exception_type": type(error).__name__,
                            "error": str(error),
                            "traceback": traceback.format_exc(),
                        },
                    )
                except Exception as report_error:
                    print(f"could not write failure receipt: {report_error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

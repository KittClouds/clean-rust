#!/usr/bin/env python3
"""Frozen FAS-00 Phase 2A feature extraction. No labels are parsed or used."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXEC_ROOT = Path(__file__).resolve().parent
FAS_ROOT = EXEC_ROOT.parent
PAPERWORK_ROOT = FAS_ROOT / "phase2a-v01"
PLAN_PATH = EXEC_ROOT / "execution-plan-v02.json"
SOURCE_SEAL_SCRIPT = EXEC_ROOT / "scripts" / "seal-execution.ps1"
SOURCE_SEAL_PATH = EXEC_ROOT / "seals" / "execution-source-seal-v02.json"
PACKET_PATH = PAPERWORK_ROOT / "contracts" / "phase2a-feature-extraction-packet-v01.json"
PACKET_SEAL_PATH = PAPERWORK_ROOT / "seals" / "phase2a-v01-seal.json"
CORPUS_ROOT = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase1-v03\corpus")
EVENTS_PATH = CORPUS_ROOT / "qualification-events-v03.jsonl"
RUN_ROOT = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase2a-v01")
MODEL_ROOT = RUN_ROOT / "model-snapshot-v01"
HF_HOME = RUN_ROOT / "hf-home-v01"
FEATURE_ROOT = RUN_ROOT / "feature-cache-v01"
PREFLIGHT_PATH = RUN_ROOT / "preflight-v01.json"
MODEL_MANIFEST_PATH = RUN_ROOT / "model-snapshot-manifest-v01.json"
EXECUTION_RECEIPT_PATH = RUN_ROOT / "phase2a-execution-receipt-v01.json"

REPO_ID = "LiquidAI/LFM2.5-1.2B-Base"
REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
FEATURE_CONTRACT_SHA256 = "1f60ef84da2de16a053b3f53a725bd079efa94065728025840fe7f3bcfad85d7"
PAPERWORK_ROOT_SHA256 = "e1ce39935e566f7dad53fae69c18a091dfc05526c3c5a3cdc8fae52b27357189"
PHASE1_ROOT_SHA256 = "d3ca9f8ef988a6f0ae93318fc0ea7c504b23b3be801dbf133d66f67746a69274"
EVENTS_SHA256 = "9fdd7ce9e49b86ac9acb3da035429c616865f527123bd0ac7c312b1b912439ca"
MANIFEST_SHA256 = "1a6905972dd397c2035bc8a3349933530a1ce4184f576df57d7f57746fc0628f"
WORLD_MANIFEST_SHA256 = "59caae81aee1a303f7f2320691665cca8a8673fdd084500d5bd53d9272ee213f"
HIDDEN_DIMENSION = 2048
EXPECTED_EVENTS = 32768
EXPECTED_ROWS = 65536
EXPECTED_PYTHON = "3.13.15"
FEATURE_BYTES = HIDDEN_DIMENSION * 4
CANONICAL_CANDIDATES = "safe | risky | idle"
ALLOWED_FIELDS = {"event_id", "rendered_event_sha256", "observation_text", "query_text"}
EXPECTED_DISTRIBUTIONS = {
    "transformers": "5.17.0",
    "tokenizers": "0.23.2",
    "huggingface_hub": "1.32.0",
    "safetensors": "0.8.0",
    "numpy": "2.5.3",
    "torch": "2.11.0+cu128",
}


class FailingClosed(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def verify_powershell(script: Path, *arguments: str) -> None:
    powershell = shutil.which("pwsh.exe") or shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise FailingClosed("PowerShell is required to verify the sealed parent artifacts.")
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FailingClosed(f"Seal verification failed: {result.stdout}\n{result.stderr}")
    print(result.stdout.strip(), flush=True)


def json_string_end(data: bytes, index: int) -> int:
    if index >= len(data) or data[index] != 0x22:
        raise FailingClosed(f"Expected JSON string at byte offset {index}.")
    cursor = index + 1
    while cursor < len(data):
        value = data[cursor]
        if value == 0x5C:
            cursor += 2
        elif value == 0x22:
            return cursor + 1
        else:
            cursor += 1
    raise FailingClosed("Unterminated JSON string in sealed event corpus.")


def skip_json_value(data: bytes, index: int) -> int:
    while index < len(data) and data[index] in b" \t\r\n":
        index += 1
    if index >= len(data):
        raise FailingClosed("Missing JSON value in sealed event corpus.")
    first = data[index]
    if first == 0x22:
        return json_string_end(data, index)
    if first in (0x7B, 0x5B):
        stack = [first]
        cursor = index + 1
        in_string = False
        escaped = False
        while cursor < len(data):
            value = data[cursor]
            if in_string:
                if escaped:
                    escaped = False
                elif value == 0x5C:
                    escaped = True
                elif value == 0x22:
                    in_string = False
            elif value == 0x22:
                in_string = True
            elif value in (0x7B, 0x5B):
                stack.append(value)
            elif value in (0x7D, 0x5D):
                opening = stack.pop() if stack else None
                if (opening, value) not in ((0x7B, 0x7D), (0x5B, 0x5D)):
                    raise FailingClosed("Mismatched JSON container in sealed event corpus.")
                if not stack:
                    return cursor + 1
            cursor += 1
        raise FailingClosed("Unterminated JSON container in sealed event corpus.")
    cursor = index
    while cursor < len(data) and data[cursor] not in b",} \t\r\n":
        cursor += 1
    if cursor == index:
        raise FailingClosed(f"Invalid JSON scalar at byte offset {index}.")
    return cursor


def decode_selected_string(data: bytes, index: int, nullable: bool = False) -> tuple[str | None, int]:
    while index < len(data) and data[index] in b" \t\r\n":
        index += 1
    if nullable and data[index : index + 4] == b"null":
        return None, index + 4
    end = json_string_end(data, index)
    try:
        value = json.loads(data[index:end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FailingClosed(f"Malformed permitted string field in event corpus: {error}") from error
    if not isinstance(value, str):
        raise FailingClosed("A required projected field was not a JSON string.")
    return value, end


def project_event_line(line: bytes) -> dict[str, str | None]:
    """Decode only the four packet-whitelisted fields; skip every other value as raw JSON bytes."""
    data = line.rstrip(b"\r\n")
    index = 0
    while index < len(data) and data[index] in b" \t":
        index += 1
    if index >= len(data) or data[index] != 0x7B:
        raise FailingClosed("Each sealed corpus line must be a JSON object.")
    index += 1
    result: dict[str, str | None] = {}
    while True:
        while index < len(data) and data[index] in b" \t\r\n":
            index += 1
        if index >= len(data):
            raise FailingClosed("Truncated top-level JSON object in event corpus.")
        if data[index] == 0x7D:
            index += 1
            break
        key_end = json_string_end(data, index)
        try:
            key = json.loads(data[index:key_end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FailingClosed(f"Invalid top-level JSON key: {error}") from error
        index = key_end
        while index < len(data) and data[index] in b" \t\r\n":
            index += 1
        if index >= len(data) or data[index] != 0x3A:
            raise FailingClosed("Missing colon after event JSON key.")
        index += 1
        if key in ALLOWED_FIELDS:
            if key in result:
                raise FailingClosed(f"Duplicate permitted event field: {key}")
            value, index = decode_selected_string(data, index, nullable=(key == "observation_text"))
            result[key] = value
        else:
            index = skip_json_value(data, index)
        while index < len(data) and data[index] in b" \t\r\n":
            index += 1
        if index < len(data) and data[index] == 0x2C:
            index += 1
            continue
        if index < len(data) and data[index] == 0x7D:
            index += 1
            break
        raise FailingClosed("Invalid separator in top-level event JSON object.")
    if data[index:].strip():
        raise FailingClosed("Unexpected bytes after top-level event JSON object.")
    if set(result) != ALLOWED_FIELDS:
        raise FailingClosed(f"Missing required projected event fields: {sorted(ALLOWED_FIELDS - set(result))}")
    for key in ("event_id", "rendered_event_sha256", "query_text"):
        if not isinstance(result[key], str) or not result[key]:
            raise FailingClosed(f"Required projected field {key} is empty or null.")
    return result


def load_projection() -> list[dict[str, str | None]]:
    expected = {
        EVENTS_PATH: EVENTS_SHA256,
        CORPUS_ROOT / "corpus-manifest-v03.json": MANIFEST_SHA256,
        CORPUS_ROOT / "world-manifest-v03.jsonl": WORLD_MANIFEST_SHA256,
    }
    for path, expected_sha in expected.items():
        if not path.is_file() or sha256_file(path) != expected_sha:
            raise FailingClosed(f"Sealed Phase 1 input identity mismatch: {path}")
    events: list[dict[str, str | None]] = []
    seen: set[str] = set()
    with EVENTS_PATH.open("rb", buffering=1024 * 1024) as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise FailingClosed(f"Blank event row at line {line_number}.")
            row = project_event_line(line)
            event_id = str(row["event_id"])
            if event_id in seen:
                raise FailingClosed(f"Duplicate event_id in sealed corpus: {event_id}")
            seen.add(event_id)
            events.append(row)
    if len(events) != EXPECTED_EVENTS or len(seen) != EXPECTED_EVENTS:
        raise FailingClosed(f"Expected {EXPECTED_EVENTS} projected events, found {len(events)}.")
    return events


def deterministic_sample(events: list[dict[str, str | None]]) -> list[str]:
    ranked = sorted(
        (sha256_bytes(b"FAS_PHASE2A_REPEAT_V01\0" + str(event["event_id"]).encode("utf-8")), str(event["event_id"]))
        for event in events
    )
    return [event_id for _, event_id in ranked[:32]]


def input_text(event: dict[str, str | None], view: str) -> str:
    if view == "FULL":
        observation = event["observation_text"] if event["observation_text"] is not None else "[none]"
    elif view == "QUERY_ONLY":
        observation = "[none]"
    else:
        raise FailingClosed(f"Unknown frozen feature view: {view}")
    return f"Observation: {observation}\nQuery: {event['query_text']}\nCandidates: {CANONICAL_CANDIDATES}"


def runtime_versions() -> dict[str, str]:
    observed: dict[str, str] = {"python": platform.python_version()}
    if observed["python"] != EXPECTED_PYTHON:
        raise FailingClosed(f"Python version mismatch: expected {EXPECTED_PYTHON}, found {observed['python']}.")
    for name in EXPECTED_DISTRIBUTIONS:
        try:
            observed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise FailingClosed(f"Required pinned runtime package is absent: {name}") from error
    mismatches = {name: (EXPECTED_DISTRIBUTIONS[name], observed[name]) for name in EXPECTED_DISTRIBUTIONS if observed[name] != EXPECTED_DISTRIBUTIONS[name]}
    if mismatches:
        raise FailingClosed(f"Runtime version mismatch; expected/observed={mismatches}")
    return observed


def load_plan() -> dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan["paperwork_root_sha256"] != PAPERWORK_ROOT_SHA256:
        raise FailingClosed("Execution plan is bound to a different Phase 2A paperwork root.")
    if plan["extractor_source_sha256"] != sha256_file(Path(__file__)):
        raise FailingClosed("Extractor source changed after its execution plan was frozen.")
    return plan


def preflight() -> None:
    plan = load_plan()
    verify_powershell(SOURCE_SEAL_SCRIPT, "-Verify")
    verify_powershell(PAPERWORK_ROOT / "scripts" / "seal-phase2a.ps1", "-Verify")
    packet_seal = json.loads(PACKET_SEAL_PATH.read_text(encoding="utf-8"))
    if packet_seal["root_sha256"] != PAPERWORK_ROOT_SHA256:
        raise FailingClosed("Phase 2A paperwork seal root mismatch.")
    for path in (MODEL_ROOT, HF_HOME, FEATURE_ROOT, MODEL_MANIFEST_PATH, EXECUTION_RECEIPT_PATH):
        if path.exists():
            raise FailingClosed(f"Refusing to reuse an existing FAS Phase 2A output path: {path}")
    events = load_projection()
    if sha256_file(EVENTS_PATH) != EVENTS_SHA256:
        raise FailingClosed("Phase 1 event corpus changed during preflight.")
    versions = runtime_versions()
    RUN_ROOT.mkdir(parents=True, exist_ok=False)
    receipt = {
        "receipt_id": "FAS00_PHASE2A_PREFLIGHT_V01",
        "paperwork_root_sha256": PAPERWORK_ROOT_SHA256,
        "phase1_root_sha256": PHASE1_ROOT_SHA256,
        "event_corpus_sha256": EVENTS_SHA256,
        "projected_event_count": len(events),
        "projected_fields_only": sorted(ALLOWED_FIELDS),
        "forbidden_fields_deserialized": False,
        "determinism_sample_event_ids": deterministic_sample(events),
        "extractor_source_sha256": plan["extractor_source_sha256"],
        "execution_plan_sha256": sha256_file(PLAN_PATH),
        "runtime_versions": versions,
        "feature_cache_created": False,
        "model_contact_performed": False,
        "preflight_passed": True,
    }
    write_json(PREFLIGHT_PATH, receipt)
    print(f"FAS00_PHASE2A_PREFLIGHT_PASS events={len(events)} rows_expected={EXPECTED_ROWS}", flush=True)


def canonical_file_rows(root: Path, exclude_dirs: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = exclude_dirs or set()
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts):
            continue
        resolved = path.resolve()
        if os.path.commonpath((str(root.resolve()), str(resolved))) != str(root.resolve()):
            raise FailingClosed(f"Snapshot file resolves outside the FAS-only root: {path}")
        rows.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if not rows:
        raise FailingClosed(f"No repository files found under {root}")
    return rows


def rows_root(rows: list[dict[str, Any]]) -> str:
    canonical = "".join(f"{row['path']} {row['bytes']} {row['sha256']}\n" for row in sorted(rows, key=lambda row: row["path"]))
    return sha256_bytes(canonical.encode("utf-8"))


def run_model_extraction(events: list[dict[str, str | None]], sample_ids: list[str]) -> None:
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HOME / "hub")
    os.environ["TRANSFORMERS_CACHE"] = str(HF_HOME / "transformers")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

    import numpy as np
    import torch
    import transformers
    from huggingface_hub import HfApi, snapshot_download
    from transformers import AutoModel, AutoTokenizer

    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise FailingClosed("The frozen execution plan requires the verified CUDA device; no fallback is authorized.")
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.allow_tf32 = False
    device = torch.device("cuda:0")

    print("FAS00_PHASE2A_MODEL_SNAPSHOT_START pinned_revision=true", flush=True)
    resolved_path = snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        repo_type="model",
        cache_dir=str(HF_HOME / "hub"),
        local_dir=str(MODEL_ROOT),
        force_download=True,
        max_workers=8,
    )
    info = HfApi().model_info(REPO_ID, revision=REVISION, files_metadata=True)
    if info.sha != REVISION:
        raise FailingClosed(f"Hub resolved a different model revision: {info.sha}")
    if not MODEL_ROOT.is_dir() or not Path(resolved_path).exists():
        raise FailingClosed("Pinned model snapshot was not materialized into the FAS-only paths.")

    snapshot_rows = canonical_file_rows(MODEL_ROOT, exclude_dirs={".cache"})
    snapshot_root = rows_root(snapshot_rows)
    model_manifest = {
        "manifest_id": "FAS00_PHASE2A_MODEL_SNAPSHOT_V01",
        "repository": REPO_ID,
        "requested_revision": REVISION,
        "resolved_revision": info.sha,
        "snapshot_download_return_path": str(resolved_path),
        "fas_only_snapshot_root": str(MODEL_ROOT),
        "files": snapshot_rows,
        "snapshot_root_sha256": snapshot_root,
        "file_count": len(snapshot_rows),
        "total_bytes": sum(row["bytes"] for row in snapshot_rows),
    }
    write_json(MODEL_MANIFEST_PATH, model_manifest)
    print(f"FAS00_PHASE2A_MODEL_SNAPSHOT_PASS files={len(snapshot_rows)} bytes={model_manifest['total_bytes']} root={snapshot_root}", flush=True)

    tokenizer = AutoTokenizer.from_pretrained(
        str(MODEL_ROOT), local_files_only=True, trust_remote_code=False, use_fast=True
    )
    tokenizer_files = tokenizer_asset_rows(MODEL_ROOT, tokenizer)
    tokenizer_manifest_canonical = "".join(f"{row['path']} {row['sha256']}\n" for row in tokenizer_files)
    tokenizer_manifest_sha = sha256_bytes(tokenizer_manifest_canonical.encode("utf-8"))
    tokenizer_identity = f"{REPO_ID}@{REVISION}"
    model_manifest["tokenizer_identity"] = tokenizer_identity
    model_manifest["tokenizer_file_manifest_sha256"] = tokenizer_manifest_sha
    model_manifest["tokenizer_files"] = tokenizer_files
    write_json(MODEL_MANIFEST_PATH, model_manifest)

    print("FAS00_PHASE2A_MODEL_LOAD_START", flush=True)
    model = AutoModel.from_pretrained(
        str(MODEL_ROOT),
        local_files_only=True,
        trust_remote_code=False,
        dtype="auto",
        low_cpu_mem_usage=False,
    )
    actual_dimension = getattr(model.config, "hidden_size", None)
    if actual_dimension != HIDDEN_DIMENSION:
        raise FailingClosed(f"Hidden dimension mismatch: expected {HIDDEN_DIMENSION}, found {actual_dimension}.")
    model.to(device)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise FailingClosed("A backbone parameter remains gradient-enabled.")
    parameter_sha_before = model_parameter_sha256(model, torch)
    runtime = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "huggingface_hub": importlib.metadata.version("huggingface_hub"),
        "tokenizers": importlib.metadata.version("tokenizers"),
        "safetensors": importlib.metadata.version("safetensors"),
        "numpy": np.__version__,
        "device": torch.cuda.get_device_name(0),
        "device_index": 0,
        "weight_dtype": str(next(model.parameters()).dtype),
        "cuda_version": torch.version.cuda,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "tf32": False,
    }

    id_to_event = {str(event["event_id"]): event for event in events}
    sample_rows: dict[tuple[str, str], dict[str, Any]] = {}
    sample_outputs: list[dict[str, Any]] = []
    for event_id in sample_ids:
        event = id_to_event[event_id]
        for view in ("FULL", "QUERY_ONLY"):
            prompt = input_text(event, view)
            sample_rows[(event_id, view)] = tokenize_and_feature(tokenizer, model, torch, np, prompt, device)
    for event_id in sample_ids:
        event = id_to_event[event_id]
        for view in ("FULL", "QUERY_ONLY"):
            prompt = input_text(event, view)
            repeated = tokenize_and_feature(tokenizer, model, torch, np, prompt, device)
            first = sample_rows[(event_id, view)]
            if repeated["token_ids"] != first["token_ids"] or repeated["feature_bytes"] != first["feature_bytes"]:
                raise FailingClosed(f"Deterministic repeat mismatch for {event_id}/{view}; extraction stopped.")
            sample_outputs.append(
                {
                    "event_id": event_id,
                    "view": view,
                    "sequence_length": len(first["token_ids"]),
                    "token_ids_sha256": token_ids_sha256(first["token_ids"]),
                    "feature_sha256": sha256_bytes(first["feature_bytes"]),
                }
            )
    determinism_receipt = {
        "receipt_id": "FAS00_PHASE2A_DETERMINISM_REPEAT_V01",
        "status": "PASS",
        "sample_event_count": len(sample_ids),
        "sample_feature_rows": len(sample_outputs),
        "sample_event_ids": sample_ids,
        "sample_rows": sample_outputs,
        "comparison": "Two frozen forward passes produced identical token IDs and float32 feature bytes for every selected row.",
        "runtime": runtime,
    }

    FEATURE_ROOT.mkdir(parents=True, exist_ok=False)
    write_json(FEATURE_ROOT / "determinism-repeat-v01.json", determinism_receipt)
    write_json(
        FEATURE_ROOT / "tokenizer-file-manifest-v01.json",
        {
            "tokenizer_identity": tokenizer_identity,
            "tokenizer_revision": REVISION,
            "files": tokenizer_files,
            "canonical_manifest_sha256": tokenizer_manifest_sha,
        },
    )

    feature_partial = FEATURE_ROOT / "features-v01.f32le.partial"
    rows_partial = FEATURE_ROOT / "feature-rows-v01.jsonl.partial"
    feature_hash = hashlib.sha256()
    row_count = 0
    sample_hashes = {(row["event_id"], row["view"]): row["feature_sha256"] for row in sample_outputs}
    start_time = time.time()
    with feature_partial.open("wb", buffering=8 * 1024 * 1024) as feature_out, rows_partial.open(
        "w", encoding="utf-8", newline="\n", buffering=1024 * 1024
    ) as rows_out:
        for event_index, event in enumerate(events, start=1):
            for view in ("FULL", "QUERY_ONLY"):
                prompt = input_text(event, view)
                result = tokenize_and_feature(tokenizer, model, torch, np, prompt, device)
                token_ids = result["token_ids"]
                feature_bytes = result["feature_bytes"]
                vector_sha = sha256_bytes(feature_bytes)
                event_id = str(event["event_id"])
                expected_sample_sha = sample_hashes.get((event_id, view))
                if expected_sample_sha is not None and vector_sha != expected_sample_sha:
                    raise FailingClosed(f"Full-extraction sample differs from repeat check: {event_id}/{view}")
                input_bytes = prompt.encode("utf-8")
                input_sha = sha256_bytes(input_bytes)
                row_id = sha256_bytes(
                    b"FAS_FEATURE_ROW_V1\0"
                    + event_id.encode("utf-8")
                    + b"\0"
                    + view.encode("ascii")
                    + b"\0"
                    + input_sha.encode("ascii")
                )
                row = {
                    "row_index": row_count,
                    "row_id": row_id,
                    "event_id": event_id,
                    "input_view": view,
                    "source_rendered_event_sha256": event["rendered_event_sha256"],
                    "input_utf8_sha256": input_sha,
                    "input_utf8_bytes": len(input_bytes),
                    "token_ids": token_ids,
                    "token_ids_sha256": token_ids_sha256(token_ids),
                    "sequence_length": len(token_ids),
                    "hidden_dimension": HIDDEN_DIMENSION,
                    "pooling_rule": "final layer; arithmetic mean over all model-visible positions; float32 accumulation",
                    "feature_shape": [HIDDEN_DIMENSION],
                    "feature_sha256": vector_sha,
                    "model_id": REPO_ID,
                    "model_revision": REVISION,
                    "tokenizer_identity": tokenizer_identity,
                    "tokenizer_file_manifest_sha256": tokenizer_manifest_sha,
                    "feature_contract_sha256": FEATURE_CONTRACT_SHA256,
                }
                feature_out.write(feature_bytes)
                feature_hash.update(feature_bytes)
                rows_out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                row_count += 1
            if event_index % 128 == 0:
                elapsed = max(time.time() - start_time, 0.001)
                print(
                    f"FAS00_PHASE2A_PROGRESS events={event_index}/{EXPECTED_EVENTS} rows={row_count}/{EXPECTED_ROWS} rows_per_second={row_count/elapsed:.2f}",
                    flush=True,
                )
        feature_out.flush()
        os.fsync(feature_out.fileno())
        rows_out.flush()
        os.fsync(rows_out.fileno())

    if row_count != EXPECTED_ROWS or feature_partial.stat().st_size != EXPECTED_ROWS * FEATURE_BYTES:
        raise FailingClosed(f"Feature cache count/size mismatch: rows={row_count} bytes={feature_partial.stat().st_size}")
    parameter_sha_after = model_parameter_sha256(model, torch)
    if parameter_sha_after != parameter_sha_before:
        raise FailingClosed("Loaded LFM parameter hash changed; Δθ_LFM check failed.")
    post_snapshot_rows = canonical_file_rows(MODEL_ROOT, exclude_dirs={".cache"})
    if rows_root(post_snapshot_rows) != snapshot_root:
        raise FailingClosed("Pinned model snapshot files changed during feature extraction.")

    feature_final = FEATURE_ROOT / "features-v01.f32le"
    rows_final = FEATURE_ROOT / "feature-rows-v01.jsonl"
    feature_partial.replace(feature_final)
    rows_partial.replace(rows_final)
    feature_sha = feature_hash.hexdigest()
    row_receipt_sha = sha256_file(rows_final)
    manifest = {
        "manifest_id": "FAS00_PHASE2A_FEATURE_CACHE_V01",
        "paperwork_root_sha256": PAPERWORK_ROOT_SHA256,
        "phase1_world_root_sha256": PHASE1_ROOT_SHA256,
        "source_event_corpus_sha256": EVENTS_SHA256,
        "feature_contract_sha256": FEATURE_CONTRACT_SHA256,
        "model_id": REPO_ID,
        "requested_model_revision": REVISION,
        "resolved_model_revision": info.sha,
        "model_snapshot_root_sha256": snapshot_root,
        "model_parameter_sha256_before": parameter_sha_before,
        "model_parameter_sha256_after": parameter_sha_after,
        "backbone_parameter_delta": 0,
        "tokenizer_identity": tokenizer_identity,
        "tokenizer_file_manifest_sha256": tokenizer_manifest_sha,
        "tokenizer_files": tokenizer_files,
        "input_views": ["FULL", "QUERY_ONLY"],
        "event_count": EXPECTED_EVENTS,
        "feature_row_count": row_count,
        "feature_shape": [EXPECTED_ROWS, HIDDEN_DIMENSION],
        "feature_tensor_dtype": "float32 little-endian",
        "feature_tensor_bytes": feature_final.stat().st_size,
        "feature_tensor_sha256": feature_sha,
        "row_receipt_sha256": row_receipt_sha,
        "determinism_repeat_status": "PASS",
        "runtime": runtime,
        "probe_training_performed": False,
        "phase3_authorized": False,
        "online_mechanisms_authorized": False,
    }
    write_json(FEATURE_ROOT / "extraction-manifest-v01.json", manifest)
    receipt = {
        "receipt_id": "FAS00_PHASE2A_EXECUTION_V01",
        "status": "FEATURE_CACHE_READY",
        "paperwork_root_sha256": PAPERWORK_ROOT_SHA256,
        "execution_source_sha256": sha256_file(Path(__file__)),
        "execution_plan_sha256": sha256_file(PLAN_PATH),
        "phase1_event_corpus_sha256": EVENTS_SHA256,
        "model_snapshot_root_sha256": snapshot_root,
        "model_parameter_sha256_before": parameter_sha_before,
        "model_parameter_sha256_after": parameter_sha_after,
        "backbone_parameter_delta": 0,
        "feature_cache_root": str(FEATURE_ROOT),
        "feature_tensor_sha256": feature_sha,
        "feature_row_count": row_count,
        "determinism_repeat_status": "PASS",
        "model_contact_authorized": True,
        "model_contact_performed": True,
        "feature_extraction_authorized": True,
        "sensor_probe_authorized": False,
        "online_mechanisms_authorized": False,
        "phase5_corpus_generation_authorized": False,
        "probe_training_performed": False,
    }
    write_json(EXECUTION_RECEIPT_PATH, receipt)
    print(f"FAS00_PHASE2A_EXTRACTION_PASS rows={row_count} tensor_sha256={feature_sha}", flush=True)


def tokenizer_asset_rows(model_root: Path, tokenizer: Any) -> list[dict[str, str]]:
    names = {
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "added_tokens.json",
        "vocab.json",
        "vocab.txt",
        "merges.txt",
        "tokenizer.model",
        "sentencepiece.bpe.model",
        "spiece.model",
        "tekken.json",
    }
    names.update(Path(str(value)).name for value in getattr(tokenizer, "vocab_files_names", {}).values() if value)
    init_kwargs = getattr(tokenizer, "init_kwargs", {})
    names.update(Path(str(value)).name for key, value in init_kwargs.items() if key.endswith("_file") and value)
    found = [
        path
        for path in model_root.rglob("*")
        if path.is_file() and ".cache" not in path.relative_to(model_root).parts and path.name in names
    ]
    rows = [{"path": path.relative_to(model_root).as_posix(), "sha256": sha256_file(path)} for path in sorted(found)]
    if not any(Path(row["path"]).name in {"tokenizer.json", "tokenizer.model", "vocab.json", "vocab.txt", "tekken.json"} for row in rows):
        raise FailingClosed("No tokenizer vocabulary asset was identified and hashed.")
    return rows


def token_ids_sha256(token_ids: list[int]) -> str:
    if any(value < 0 or value > 0xFFFFFFFF for value in token_ids):
        raise FailingClosed("Tokenizer emitted an ID outside the packet's uint32 serialization.")
    data = b"FAS_TOKEN_IDS_V1\0" + len(token_ids).to_bytes(8, "little")
    data += b"".join(struct.pack("<I", value) for value in token_ids)
    return sha256_bytes(data)


def tokenize_and_feature(tokenizer: Any, model: Any, torch: Any, np: Any, prompt: str, device: Any) -> dict[str, Any]:
    token_ids = [int(value) for value in tokenizer.encode(prompt, add_special_tokens=True)]
    if not token_ids:
        raise FailingClosed("Tokenizer returned an empty sequence.")
    max_positions = getattr(model.config, "max_position_embeddings", None)
    if max_positions is not None and len(token_ids) > int(max_positions):
        raise FailingClosed(f"Exact input length {len(token_ids)} exceeds model limit {max_positions}; no truncation allowed.")
    input_ids = torch.tensor([token_ids], dtype=torch.long, device=device)
    attention_mask = torch.ones_like(input_ids)
    with torch.inference_mode():
        output = model(input_ids=input_ids, attention_mask=attention_mask, use_cache=False, return_dict=True)
        hidden = output.last_hidden_state
        if tuple(hidden.shape) != (1, len(token_ids), HIDDEN_DIMENSION):
            raise FailingClosed(f"Final hidden state shape mismatch: {tuple(hidden.shape)}")
        pooled = hidden.to(dtype=torch.float32).mean(dim=1).squeeze(0).contiguous().cpu()
    feature = pooled.numpy().astype("<f4", copy=False)
    if feature.shape != (HIDDEN_DIMENSION,) or not np.isfinite(feature).all():
        raise FailingClosed("Pooled feature has the wrong shape or contains NaN/Inf.")
    feature_bytes = feature.tobytes(order="C")
    if len(feature_bytes) != FEATURE_BYTES:
        raise FailingClosed("Serialized feature byte length mismatch.")
    return {"token_ids": token_ids, "feature_bytes": feature_bytes}


def model_parameter_sha256(model: Any, torch: Any) -> str:
    digest = hashlib.sha256()
    digest.update(b"FAS_LFM_PARAMETER_STATE_V1\0")
    state = model.state_dict()
    for name in sorted(state):
        tensor = state[name].detach().to("cpu").contiguous()
        metadata = f"{name}\0{tensor.dtype}\0{','.join(map(str, tensor.shape))}\0".encode("utf-8")
        digest.update(metadata)
        digest.update(tensor.reshape(-1).view(torch.uint8).numpy().tobytes(order="C"))
    return digest.hexdigest()


def validate_cache() -> None:
    verify_powershell(SOURCE_SEAL_SCRIPT, "-Verify")
    verify_powershell(PAPERWORK_ROOT / "scripts" / "seal-phase2a.ps1", "-Verify")
    manifest_path = FEATURE_ROOT / "extraction-manifest-v01.json"
    rows_path = FEATURE_ROOT / "feature-rows-v01.jsonl"
    feature_path = FEATURE_ROOT / "features-v01.f32le"
    repeat_path = FEATURE_ROOT / "determinism-repeat-v01.json"
    tokenizer_path = FEATURE_ROOT / "tokenizer-file-manifest-v01.json"
    required = (manifest_path, rows_path, feature_path, repeat_path, tokenizer_path, MODEL_MANIFEST_PATH, PREFLIGHT_PATH, EXECUTION_RECEIPT_PATH)
    if any(not path.is_file() for path in required):
        raise FailingClosed("One or more required Phase 2A cache/receipt artifacts are missing.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(EXECUTION_RECEIPT_PATH.read_text(encoding="utf-8"))
    if manifest["paperwork_root_sha256"] != PAPERWORK_ROOT_SHA256 or manifest["phase1_world_root_sha256"] != PHASE1_ROOT_SHA256:
        raise FailingClosed("Feature cache manifest does not bind the sealed parent roots.")
    if manifest["event_count"] != EXPECTED_EVENTS or manifest["feature_row_count"] != EXPECTED_ROWS:
        raise FailingClosed("Feature cache manifest row counts are wrong.")
    if manifest["feature_shape"] != [EXPECTED_ROWS, HIDDEN_DIMENSION] or manifest["feature_tensor_dtype"] != "float32 little-endian":
        raise FailingClosed("Feature cache tensor contract mismatch.")
    if manifest["feature_tensor_bytes"] != EXPECTED_ROWS * FEATURE_BYTES or feature_path.stat().st_size != EXPECTED_ROWS * FEATURE_BYTES:
        raise FailingClosed("Feature tensor file size mismatch.")
    if sha256_file(feature_path) != manifest["feature_tensor_sha256"] or sha256_file(rows_path) != manifest["row_receipt_sha256"]:
        raise FailingClosed("Feature tensor or row receipt file hash mismatch.")
    if manifest["model_parameter_sha256_before"] != manifest["model_parameter_sha256_after"] or manifest["backbone_parameter_delta"] != 0:
        raise FailingClosed("Backbone immutability receipt failed.")
    repeat = json.loads(repeat_path.read_text(encoding="utf-8"))
    if repeat["status"] != "PASS" or repeat["sample_feature_rows"] != 64:
        raise FailingClosed("Deterministic repeat receipt is absent or failed.")
    tokenizer_manifest = json.loads(tokenizer_path.read_text(encoding="utf-8"))
    if tokenizer_manifest["canonical_manifest_sha256"] != manifest["tokenizer_file_manifest_sha256"]:
        raise FailingClosed("Tokenizer identity manifest mismatch.")
    tokenizer_canonical = "".join(f"{row['path']} {row['sha256']}\n" for row in tokenizer_manifest["files"])
    if sha256_bytes(tokenizer_canonical.encode("utf-8")) != tokenizer_manifest["canonical_manifest_sha256"]:
        raise FailingClosed("Tokenizer file-manifest canonical hash mismatch.")

    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HOME / "hub")
    os.environ["TRANSFORMERS_CACHE"] = str(HF_HOME / "transformers")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_ROOT), local_files_only=True, trust_remote_code=False, use_fast=True)
    actual_tokenizer_files = tokenizer_asset_rows(MODEL_ROOT, tokenizer)
    if actual_tokenizer_files != tokenizer_manifest["files"]:
        raise FailingClosed("Resolved tokenizer files differ from the sealed row identity.")

    events = load_projection()
    event_by_id = {str(row["event_id"]): row for row in events}
    expected_rows = EXPECTED_ROWS
    seen: set[tuple[str, str]] = set()
    validated_row_count = 0
    with rows_path.open("r", encoding="utf-8") as row_handle, feature_path.open("rb", buffering=8 * 1024 * 1024) as feature_handle:
        for expected_index, line in enumerate(row_handle):
            row = json.loads(line)
            required_fields = {
                "row_index", "row_id", "event_id", "input_view", "source_rendered_event_sha256", "input_utf8_sha256",
                "input_utf8_bytes", "token_ids", "token_ids_sha256", "sequence_length", "hidden_dimension", "pooling_rule",
                "feature_shape", "feature_sha256", "model_id", "model_revision", "tokenizer_identity",
                "tokenizer_file_manifest_sha256", "feature_contract_sha256",
            }
            if set(row) != required_fields:
                raise FailingClosed(f"Feature row has missing or unexpected fields at index {expected_index}.")
            if row["row_index"] != expected_index:
                raise FailingClosed(f"Noncanonical feature row index at {expected_index}.")
            event_id = row["event_id"]
            view = row["input_view"]
            key = (event_id, view)
            if key in seen or event_id not in event_by_id or view not in {"FULL", "QUERY_ONLY"}:
                raise FailingClosed(f"Duplicate, unknown event, or invalid view at feature row {expected_index}.")
            seen.add(key)
            expected_event = events[expected_index // 2]
            expected_view = ("FULL", "QUERY_ONLY")[expected_index % 2]
            if event_id != expected_event["event_id"] or view != expected_view:
                raise FailingClosed(f"Feature row order mismatch at index {expected_index}.")
            source = event_by_id[event_id]
            prompt = input_text(source, view)
            input_bytes = prompt.encode("utf-8")
            input_sha = sha256_bytes(input_bytes)
            ids = row["token_ids"]
            if row["source_rendered_event_sha256"] != source["rendered_event_sha256"] or row["input_utf8_sha256"] != input_sha or row["input_utf8_bytes"] != len(input_bytes):
                raise FailingClosed(f"Input identity mismatch at feature row {expected_index}.")
            if row["token_ids_sha256"] != token_ids_sha256(ids) or row["sequence_length"] != len(ids):
                raise FailingClosed(f"Token identity mismatch at feature row {expected_index}.")
            if [int(token_id) for token_id in tokenizer.encode(prompt, add_special_tokens=True)] != ids:
                raise FailingClosed(f"Token IDs do not match the pinned tokenizer at feature row {expected_index}.")
            expected_row_id = sha256_bytes(
                b"FAS_FEATURE_ROW_V1\0" + event_id.encode("utf-8") + b"\0" + view.encode("ascii") + b"\0" + input_sha.encode("ascii")
            )
            if (
                row["row_id"] != expected_row_id
                or row["hidden_dimension"] != HIDDEN_DIMENSION
                or row["feature_shape"] != [HIDDEN_DIMENSION]
                or row["pooling_rule"] != "final layer; arithmetic mean over all model-visible positions; float32 accumulation"
                or row["feature_contract_sha256"] != FEATURE_CONTRACT_SHA256
            ):
                raise FailingClosed(f"Row contract mismatch at feature row {expected_index}.")
            if row["model_id"] != REPO_ID or row["model_revision"] != REVISION or row["tokenizer_file_manifest_sha256"] != manifest["tokenizer_file_manifest_sha256"]:
                raise FailingClosed(f"Model/tokenizer identity mismatch at feature row {expected_index}.")
            vector = feature_handle.read(FEATURE_BYTES)
            if len(vector) != FEATURE_BYTES or sha256_bytes(vector) != row["feature_sha256"]:
                raise FailingClosed(f"Feature bytes mismatch at row {expected_index}.")
            validated_row_count += 1
    if validated_row_count != expected_rows or len(seen) != expected_rows:
        raise FailingClosed(f"Serialized row count mismatch: found {validated_row_count}, expected {expected_rows}.")
    if receipt["status"] != "FEATURE_CACHE_READY" or receipt["sensor_probe_authorized"] or receipt["online_mechanisms_authorized"] or receipt["probe_training_performed"]:
        raise FailingClosed("Execution receipt crosses the Phase 3 or online-mechanism boundary.")
    model_manifest = json.loads(MODEL_MANIFEST_PATH.read_text(encoding="utf-8"))
    if model_manifest["resolved_revision"] != REVISION or model_manifest["tokenizer_file_manifest_sha256"] != manifest["tokenizer_file_manifest_sha256"]:
        raise FailingClosed("Model snapshot or tokenizer revision identity mismatch.")
    actual_snapshot_rows = canonical_file_rows(MODEL_ROOT, exclude_dirs={".cache"})
    if rows_root(actual_snapshot_rows) != model_manifest["snapshot_root_sha256"]:
        raise FailingClosed("FAS-only model snapshot tree no longer matches its manifest.")
    print(f"FAS00_PHASE2A_CACHE_VALID rows={expected_rows} tensor_sha256={manifest['feature_tensor_sha256']}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--extract", action="store_true")
    action.add_argument("--validate-cache", action="store_true")
    args = parser.parse_args()
    try:
        if args.preflight:
            preflight()
        elif args.validate_cache:
            validate_cache()
        else:
            plan = load_plan()
            verify_powershell(SOURCE_SEAL_SCRIPT, "-Verify")
            verify_powershell(PAPERWORK_ROOT / "scripts" / "seal-phase2a.ps1", "-Verify")
            preflight_receipt = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
            if not preflight_receipt["preflight_passed"] or preflight_receipt["model_contact_performed"]:
                raise FailingClosed("Preflight receipt is missing, failed, or contaminated by prior model contact.")
            if preflight_receipt["extractor_source_sha256"] != plan["extractor_source_sha256"] or preflight_receipt["execution_plan_sha256"] != sha256_file(PLAN_PATH):
                raise FailingClosed("Execution code or plan changed after preflight.")
            for path in (MODEL_ROOT, HF_HOME, FEATURE_ROOT, MODEL_MANIFEST_PATH, EXECUTION_RECEIPT_PATH):
                if path.exists():
                    raise FailingClosed(f"Refusing to reuse existing Phase 2A output: {path}")
            events = load_projection()
            run_model_extraction(events, preflight_receipt["determinism_sample_event_ids"])
        return 0
    except Exception as error:
        if isinstance(error, FailingClosed):
            print(f"FAS00_PHASE2A_FAIL_CLOSED {error}", file=sys.stderr, flush=True)
        else:
            print(f"FAS00_PHASE2A_FAIL_CLOSED {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        try:
            if RUN_ROOT.exists():
                write_json(
                    RUN_ROOT / "phase2a-failure-v01.json",
                    {
                        "status": "FAIL_CLOSED",
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "model_contact_performed": MODEL_ROOT.exists(),
                        "feature_cache_ready": False,
                        "sensor_probe_authorized": False,
                        "online_mechanisms_authorized": False,
                    },
                )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

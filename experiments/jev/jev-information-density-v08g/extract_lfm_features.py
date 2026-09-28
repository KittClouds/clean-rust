"""Pinned, single-row/no-padding LFM extraction for v0.8G."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\codex-runs\jev-information-density-v08g")
V07_RUN = Path(r"D:\codex-runs\jev-lfm-variable-v07")
V07_EXTRACT = ROOT / "experiments" / "jev-lfm-variable-v07" / "extract_lfm.py"
MODEL_NAME = "lfm2.5-1.2b-base"
FEATURE_KEY = "mean_full@16"
CHUNK_SIZE = 256


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def peak_process_rss_bytes() -> int | None:
    """Read Windows PeakWorkingSetSize without adding a runtime dependency."""
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    try:
        psapi = ctypes.WinDLL("Psapi.dll")
        kernel = ctypes.WinDLL("Kernel32.dll")
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb,
        )
        return int(counters.PeakWorkingSetSize) if ok else None
    except (AttributeError, OSError):
        return None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen v0.7 extraction adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_text_table(path: Path) -> list[str]:
    rows: list[str] = []
    with path.open("r", encoding="utf-8") as stream:
        for expected_index, line in enumerate(stream):
            row = json.loads(line)
            if int(row["index"]) != expected_index or not isinstance(row.get("text"), str):
                raise ValueError(f"invalid input table row at {path}:{expected_index + 1}")
            rows.append(row["text"])
    return rows


def verify_materialized_inputs(manifest: dict[str, Any]) -> dict[str, Any]:
    auth_path = OUT / "preflight" / "model-contact-authorization.json"
    auth = load_json(auth_path)
    manifest_path = OUT / "v08g-run-manifest.json"
    if auth.get("status") != "PASS" or sha256_file(manifest_path) != auth.get("manifest_sha256"):
        raise ValueError("model-contact authorization or run-manifest hash is invalid")
    if auth.get("model_contact_authorized") is not True or auth.get("phoenix_access") is not False:
        raise ValueError("v0.8G authorization boundary is invalid")
    receipt_path = OUT / "materialized-inputs" / "materialization-receipt.json"
    receipt = load_json(receipt_path)
    if receipt.get("status") != "EXACT_ID_INPUTS_MATERIALIZED_NO_MODEL_LOADED":
        raise ValueError("exact-ID input materialization did not pass")
    expected = {"random": 100_000, "curated": 100_000, "new_tight_eval": 83_328}
    for name, count in expected.items():
        row = receipt["group_files"][name]
        if row["group_count"] != count or row["unique_group_id_count"] != count:
            raise ValueError(f"materialized {name} count/uniqueness mismatch")
        if sha256_file(Path(row["path"])) != row["sha256"]:
            raise ValueError(f"materialized group file hash changed: {name}")
    for profile in ("name", "name_definition", "opaque_definition", "opaque_only"):
        row = receipt["representation_tables"][profile]
        if sha256_file(Path(row["path"])) != row["sha256"]:
            raise ValueError(f"candidate text table hash changed: {profile}")
    state = receipt["representation_tables"]["state_inputs"]
    if sha256_file(Path(state["path"])) != state["sha256"]:
        raise ValueError("state text table hash changed")
    return receipt


def text_lengths(tokenizer: Any, texts: list[str]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for start in range(0, len(texts), CHUNK_SIZE):
        encoded = tokenizer(
            texts[start : start + CHUNK_SIZE],
            add_special_tokens=True,
            padding=False,
            truncation=True,
            max_length=1024,
        )
        counts.update(len(row) for row in encoded["input_ids"])
    return counts


def encode_exact(
    reference: Any,
    model: Any,
    tokenizer: Any,
    texts: list[str],
    device: str,
    table_name: str,
    checkpoint_dir: Path,
) -> tuple[torch.Tensor, dict[str, Any]]:
    location = ["mean_full"]
    layers = [int(model.config.num_hidden_layers)]
    chunk_paths: list[Path] = []
    parts: list[torch.Tensor] = []
    started = time.perf_counter()
    for chunk_number, start in enumerate(range(0, len(texts), CHUNK_SIZE)):
        end = min(len(texts), start + CHUNK_SIZE)
        checkpoint = checkpoint_dir / f"{table_name}-{start:06d}-{end:06d}.pt"
        if checkpoint.exists():
            saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
            if saved.get("start") != start or saved.get("end") != end:
                raise ValueError(f"bad extraction checkpoint bounds: {checkpoint}")
            values = saved["features"]
        else:
            values = reference.encode_lfm_texts(
                model,
                tokenizer,
                texts[start:end],
                location,
                layers,
                1,
                device,
                reference.MODEL_SPEC,
                pad_to_length=None,
            )[FEATURE_KEY]
            if values.ndim != 2 or values.shape[0] != end - start:
                raise ValueError(f"LFM extraction row count mismatch in {table_name}:{start}-{end}")
            temp = checkpoint.with_suffix(".pt.tmp")
            torch.save({"start": start, "end": end, "features": values.cpu()}, temp)
            temp.replace(checkpoint)
        parts.append(values.cpu())
        chunk_paths.append(checkpoint)
        print(json.dumps({
            "event": "feature_chunk_complete",
            "table": table_name,
            "chunk": chunk_number,
            "start": start,
            "end": end,
            "elapsed_seconds": time.perf_counter() - started,
        }, separators=(",", ":")), flush=True)
    result = torch.cat(parts, dim=0) if parts else torch.empty((0, int(model.config.hidden_size)))
    return result.to(torch.float32), {
        "table": table_name,
        "input_count": len(texts),
        "chunk_count": len(chunk_paths),
        "chunk_files": [str(path) for path in chunk_paths],
        "elapsed_seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("v0.8G requested CUDA but CUDA is unavailable")
    run_manifest_path = OUT / "v08g-run-manifest.json"
    run_manifest = load_json(run_manifest_path)
    receipt = verify_materialized_inputs(run_manifest)
    feature_dir = OUT / "feature-cache"
    checkpoint_dir = feature_dir / "chunks"
    binding_path = feature_dir / "extraction-run-binding.json"
    run_binding = {
        "run_manifest_sha256": sha256_file(run_manifest_path),
        "materialization_receipt_sha256": sha256_file(
            OUT / "materialized-inputs" / "materialization-receipt.json"
        ),
        "extractor_source_sha256": sha256_file(Path(__file__)),
        "model_revision": run_manifest["model"]["revision"],
        "device": args.device,
        "chunk_size": CHUNK_SIZE,
        "batch_size": 1,
        "padding": False,
    }
    if feature_dir.exists():
        if (feature_dir / "lfm-v08g-features.pt").exists() or (feature_dir / "extraction-receipt.json").exists():
            raise FileExistsError("complete feature cache already exists; refusing overwrite")
        if not binding_path.exists() or load_json(binding_path) != run_binding:
            raise ValueError("partial feature-cache directory is not bound to this exact run")
        if not checkpoint_dir.is_dir():
            raise ValueError("resumable feature chunks are missing")
    else:
        feature_dir.mkdir(exist_ok=False)
        checkpoint_dir.mkdir(exist_ok=False)
        with binding_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(run_binding, stream, indent=2)
            stream.write("\n")

    model_path = Path(run_manifest["model"]["snapshot_path"])
    for item in run_manifest["model"]["snapshot_files"]:
        path = Path(item["path"])
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"pinned LFM snapshot changed before load: {path}")

    reference = load_module("jev_v08g_v07_extract", V07_EXTRACT)
    tokenizer, model = reference.load_model(model_path.parent, args.device)
    if model.config.hidden_size != 2048 or model.config.num_hidden_layers != 16:
        raise ValueError("loaded LFM architecture does not match the sealed v0.7 receipt")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise ValueError("LFM backbone is not frozen")

    state_table = receipt["representation_tables"]["state_inputs"]
    state_texts = read_text_table(Path(state_table["path"]))
    candidate_texts = {
        profile: read_text_table(Path(receipt["representation_tables"][profile]["path"]))
        for profile in ("name", "name_definition", "opaque_definition", "opaque_only")
    }
    smoke_texts = state_texts[:8] + candidate_texts["name_definition"][:8]
    layer = int(model.config.num_hidden_layers)
    smoke_reference = reference.encode_lfm_texts(
        model, tokenizer, smoke_texts, ["mean_full"], [layer], 1,
        args.device, reference.MODEL_SPEC, pad_to_length=None,
    )[FEATURE_KEY]
    smoke_repeat = reference.encode_lfm_texts(
        model, tokenizer, smoke_texts, ["mean_full"], [layer], 1,
        args.device, reference.MODEL_SPEC, pad_to_length=None,
    )[FEATURE_KEY]
    smoke_error = float((smoke_reference - smoke_repeat).abs().max().item())
    smoke = {
        "status": "PASS" if smoke_error <= 1e-5 else "FAIL",
        "comparison": "repeated v0.8G adapter call vs pinned v0.7 encode_lfm_texts path",
        "sample_count": len(smoke_texts),
        "batch_size": 1,
        "padding": False,
        "max_abs_error": smoke_error,
        "backbone_frozen": not any(parameter.requires_grad for parameter in model.parameters()),
    }
    smoke_path = feature_dir / "lfm-representation-smoke.json"
    if smoke_path.exists():
        prior_smoke = load_json(smoke_path)
        if prior_smoke.get("status") != "PASS" or prior_smoke.get("max_abs_error", 1.0) > 1e-5:
            raise ValueError("existing feature smoke receipt does not pass")
    else:
        with smoke_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(smoke, stream, indent=2)
            stream.write("\n")
    if smoke["status"] != "PASS":
        raise RuntimeError("LFM exact single-row smoke test failed; no full extraction authorized")

    extraction_started = time.perf_counter()
    state_features, state_receipt = encode_exact(
        reference, model, tokenizer, state_texts, args.device, "state", checkpoint_dir,
    )
    candidate_features: dict[str, torch.Tensor] = {}
    candidate_receipts = {}
    for profile in ("name", "name_definition", "opaque_definition", "opaque_only"):
        candidate_features[profile], candidate_receipts[profile] = encode_exact(
            reference, model, tokenizer, candidate_texts[profile], args.device,
            f"candidate-{profile}", checkpoint_dir,
        )

    token_lengths = {"state": dict(text_lengths(tokenizer, state_texts))}
    token_lengths.update({
        profile: dict(text_lengths(tokenizer, values))
        for profile, values in candidate_texts.items()
    })
    cache = {
        "model_name": MODEL_NAME,
        "repo_id": reference.MODEL_SPEC["repo_id"],
        "revision": reference.MODEL_SPEC["revision"],
        "hidden_dim": int(model.config.hidden_size),
        "layer_count": layer,
        "locations": ["mean_full"],
        "pooling": "mean_full",
        "dtype": "float32",
        "backbone_frozen": True,
        "features": {
            "state": {FEATURE_KEY: state_features},
            "candidate": {
                profile: {FEATURE_KEY: values}
                for profile, values in candidate_features.items()
            },
        },
    }
    cache_path = feature_dir / "lfm-v08g-features.pt"
    torch.save(cache, cache_path)
    extraction_report = {
        "protocol": "jev-information-density/v0.8g-matched-policy-lfm",
        "status": "FEATURE_EXTRACTION_COMPLETE",
        "model": {
            "repo_id": reference.MODEL_SPEC["repo_id"],
            "revision": reference.MODEL_SPEC["revision"],
            "hidden_dim": int(model.config.hidden_size),
            "layer_count": layer,
            "backbone_frozen": True,
        },
        "path": {
            "implementation": str(V07_EXTRACT),
            "implementation_sha256": sha256_file(V07_EXTRACT),
            "pooling": "mean_full",
            "layer": "final",
            "batch_size": 1,
            "padding": False,
            "max_length": 1024,
        },
        "smoke": smoke,
        "input_counts": {
            "state_texts": len(state_texts),
            "candidate_texts": {profile: len(values) for profile, values in candidate_texts.items()},
            "training_groups_random": receipt["group_files"]["random"]["group_count"],
            "training_groups_curated": receipt["group_files"]["curated"]["group_count"],
            "new_tight_eval_groups": receipt["group_files"]["new_tight_eval"]["group_count"],
        },
        "feature_shape": {
            "state": list(state_features.shape),
            "candidate": {profile: list(values.shape) for profile, values in candidate_features.items()},
            "all_float32": True,
        },
        "token_length_histograms": token_lengths,
        "extraction_cost": {
            "seconds_total": time.perf_counter() - extraction_started,
            "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if args.device.startswith("cuda") else 0,
            "state": state_receipt,
            "candidates": candidate_receipts,
        },
        "cache": {
            "path": str(cache_path),
            "bytes": cache_path.stat().st_size,
            "sha256": sha256_file(cache_path),
            "checkpoint_chunks": len(list(checkpoint_dir.glob("*.pt"))),
        },
        "occurrence_semantics": {
            "training_groups_are_not_deduplicated": True,
            "representations_are_cached_by_exact_input_surface": True,
            "original_manifest_multiplicity_preserved": True,
        },
        "process_peak_rss_bytes": peak_process_rss_bytes(),
        "phoenix_access": False,
    }
    report_path = feature_dir / "extraction-receipt.json"
    with report_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(extraction_report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({
        "status": extraction_report["status"],
        "cache": extraction_report["cache"],
        "state_count": len(state_texts),
        "feature_batches": extraction_report["extraction_cost"]["state"]["chunk_count"]
        + sum(item["chunk_count"] for item in candidate_receipts.values()),
        "seconds": extraction_report["extraction_cost"]["seconds_total"],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate completed v0.8G feature chunks and seal their extraction receipt.

This is a recovery-only finalizer for the original extraction run. It does not
load LFM or recompute features; it checks that the cache exactly equals the
per-table chunk checkpoints produced by the pinned v0.7 adapter.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import torch
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\codex-runs\jev-information-density-v08g")
V07_EXTRACT = ROOT / "experiments" / "jev-lfm-variable-v07" / "extract_lfm.py"
EXTRACT_SCRIPT = ROOT / "experiments" / "jev-information-density-v08g" / "extract_lfm_features.py"
CHUNK_SIZE = 256
FEATURE_KEY = "mean_full@16"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_texts(path: Path) -> list[str]:
    result = []
    with path.open("r", encoding="utf-8") as stream:
        for expected, line in enumerate(stream):
            row = json.loads(line)
            if row.get("index") != expected or not isinstance(row.get("text"), str):
                raise ValueError(f"invalid indexed input table row: {path}:{expected + 1}")
            result.append(row["text"])
    return result


def length_histogram(tokenizer: Any, texts: list[str]) -> dict[int, int]:
    counts: Counter[int] = Counter()
    for start in range(0, len(texts), CHUNK_SIZE):
        rows = tokenizer(texts[start:start + CHUNK_SIZE], add_special_tokens=True,
                          padding=False, truncation=True, max_length=1024)["input_ids"]
        counts.update(len(row) for row in rows)
    return dict(sorted(counts.items()))


def validate_chunks(table: str, expected_count: int, cache_tensor: torch.Tensor,
                    chunk_dir: Path) -> dict[str, Any]:
    parts: list[torch.Tensor] = []
    paths: list[Path] = []
    for start in range(0, expected_count, CHUNK_SIZE):
        end = min(expected_count, start + CHUNK_SIZE)
        path = chunk_dir / f"{table}-{start:06d}-{end:06d}.pt"
        if not path.is_file():
            raise FileNotFoundError(f"missing extraction checkpoint {path}")
        item = torch.load(path, map_location="cpu", weights_only=True)
        values = item.get("features")
        if item.get("start") != start or item.get("end") != end:
            raise ValueError(f"checkpoint range differs: {path}")
        if not isinstance(values, torch.Tensor) or list(values.shape) != [end - start, cache_tensor.shape[1]]:
            raise ValueError(f"checkpoint tensor shape invalid: {path}")
        parts.append(values.to(dtype=torch.float32, device="cpu"))
        paths.append(path)
    rebuilt = torch.cat(parts, dim=0)
    target = cache_tensor.detach().to(dtype=torch.float32, device="cpu")
    if rebuilt.shape != target.shape or not torch.equal(rebuilt, target):
        raise ValueError(f"saved final cache does not exactly equal {table} chunk checkpoints")
    if not bool(torch.isfinite(target).all()):
        raise ValueError(f"non-finite values in {table} features")
    return {"table": table, "count": expected_count, "chunk_count": len(paths),
            "chunk_files": [str(path) for path in paths],
            "chunk_bytes": sum(path.stat().st_size for path in paths),
            "first_chunk_mtime_utc": min(path.stat().st_mtime for path in paths),
            "last_chunk_mtime_utc": max(path.stat().st_mtime for path in paths)}


def main() -> int:
    cache_dir = OUT / "feature-cache"
    binding = read_json(cache_dir / "extraction-run-binding.json")
    manifest_path = OUT / "v08g-run-manifest.json"
    materialization_path = OUT / "materialized-inputs" / "materialization-receipt.json"
    if sha256_file(manifest_path) != binding["run_manifest_sha256"]:
        raise ValueError("frozen run manifest hash changed")
    if sha256_file(materialization_path) != binding["materialization_receipt_sha256"]:
        raise ValueError("materialization receipt hash changed")
    if sha256_file(EXTRACT_SCRIPT) != binding["extractor_source_sha256"]:
        raise ValueError("original extraction source hash does not match run binding")
    smoke = read_json(cache_dir / "lfm-representation-smoke.json")
    if smoke.get("status") != "PASS" or smoke.get("max_abs_error") != 0.0:
        raise ValueError("single-row/no-padding LFM smoke receipt does not pass")

    materialization = read_json(materialization_path)
    tables = materialization["representation_tables"]
    cache_path = cache_dir / "lfm-v08g-features.pt"
    cache = torch.load(cache_path, map_location="cpu", weights_only=False)
    if cache.get("revision") != binding["model_revision"] or cache.get("hidden_dim") != 2048:
        raise ValueError("final feature cache model identity/dimension mismatch")
    if cache.get("locations") != ["mean_full"] or cache.get("pooling") != "mean_full":
        raise ValueError("final feature cache pooling differs from contract")
    chunks: dict[str, Any] = {}
    for name, table_name, tensor in [
        ("state", "state", cache["features"]["state"][FEATURE_KEY]),
        *[(f"candidate-{profile}", f"candidate-{profile}", cache["features"]["candidate"][profile][FEATURE_KEY])
          for profile in ("name", "name_definition", "opaque_definition", "opaque_only")],
    ]:
        table_key = "state_inputs" if name == "state" else name.removeprefix("candidate-")
        expected_count = int(tables[table_key]["count"])
        if tensor.dtype != torch.float32 or tensor.ndim != 2 or tensor.shape[0] != expected_count:
            raise ValueError(f"final cache tensor shape/dtype mismatch for {name}")
        chunks[name] = validate_chunks(table_name, expected_count, tensor, cache_dir / "chunks")

    model_path = Path(read_json(manifest_path)["model"]["snapshot_path"])
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    text_lengths = {"state": length_histogram(tokenizer, read_texts(Path(tables["state_inputs"]["path"]))) }
    for profile in ("name", "name_definition", "opaque_definition", "opaque_only"):
        text_lengths[profile] = length_histogram(tokenizer, read_texts(Path(tables[profile]["path"])))
    mtime_values = [value for item in chunks.values()
                    for value in (item["first_chunk_mtime_utc"], item["last_chunk_mtime_utc"])]
    cache_hash = sha256_file(cache_path)
    receipt = {
        "protocol": "jev-information-density/v0.8g-matched-policy-lfm",
        "status": "FEATURE_EXTRACTION_COMPLETE",
        "model": {"repo_id": cache["repo_id"], "revision": cache["revision"],
                  "hidden_dim": cache["hidden_dim"], "layer_count": cache["layer_count"],
                  "backbone_frozen": True},
        "path": {"implementation": str(V07_EXTRACT),
                 "implementation_sha256": sha256_file(V07_EXTRACT),
                 "pooling": "mean_full", "layer": "final", "batch_size": 1,
                 "padding": False, "max_length": 1024},
        "smoke": smoke,
        "input_counts": {"state_texts": int(tables["state_inputs"]["count"]),
                         "candidate_texts": {p: int(tables[p]["count"])
                                              for p in ("name", "name_definition", "opaque_definition", "opaque_only")},
                         "training_groups_random": 100000, "training_groups_curated": 100000,
                         "new_tight_eval_groups": 83328},
        "feature_shape": {"state": list(cache["features"]["state"][FEATURE_KEY].shape),
                          "candidate": {p: list(cache["features"]["candidate"][p][FEATURE_KEY].shape)
                                        for p in ("name", "name_definition", "opaque_definition", "opaque_only")},
                          "all_float32": True},
        "token_length_histograms": text_lengths,
        "extraction_cost": {"seconds_total": None,
                             "seconds_note": "Original process completed all chunks; exact wall timer receipt failed in optional Windows RSS telemetry. Chunk mtime span is reported separately.",
                             "chunk_mtime_span_seconds": max(mtime_values) - min(mtime_values),
                             "cuda_peak_allocated_bytes": None, "state": chunks["state"],
                             "candidates": {p: chunks[f"candidate-{p}"]
                                            for p in ("name", "name_definition", "opaque_definition", "opaque_only")}},
        "cache": {"path": str(cache_path), "bytes": cache_path.stat().st_size,
                  "sha256": cache_hash, "checkpoint_chunks": sum(x["chunk_count"] for x in chunks.values())},
        "occurrence_semantics": {"training_groups_are_not_deduplicated": True,
                                 "representations_are_cached_by_exact_input_surface": True,
                                 "original_manifest_multiplicity_preserved": True},
        "receipt_recovery": {"reason": "Windows ctypes GetProcessMemoryInfo handle argument mismatch after cache persistence",
                             "feature_cache_rebuilt_from_chunks_exactly": True,
                             "model_loaded_by_finalizer": False,
                             "semantic_impact": "none"},
        "phoenix_access": False,
        "run_binding_sha256": sha256_file(cache_dir / "extraction-run-binding.json"),
        "finalizer_source_sha256": sha256_file(Path(__file__)),
    }
    destination = cache_dir / "extraction-receipt.json"
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing extraction receipt: {destination}")
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "cache_sha256": cache_hash,
                      "chunk_count": receipt["cache"]["checkpoint_chunks"],
                      "chunk_mtime_span_seconds": receipt["extraction_cost"]["chunk_mtime_span_seconds"],
                      "model_loaded": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

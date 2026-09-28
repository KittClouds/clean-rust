from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

import scorer


SEAL_SCHEMA = "FAS_E4_0_ARTIFACT_SEAL_V01"


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def e4_artifact_tree_root(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["artifact_id"].encode("utf-8")):
        digest.update(
            f'{entry["artifact_id"]}\t{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8")
        )
    return digest.hexdigest()


def atomic_create_bytes(path: Path, payload: bytes) -> None:
    """Durably create one immutable output without replacing an earlier artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite preserved scoring output: {path}")
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_name, path)
        os.unlink(temp_name)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_json(path: Path, value: Any) -> None:
    atomic_create_bytes(path, canonical_json(value))


def jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        for row in rows
    )


def artifact_entry(artifact_id: str, path: Path, *, run_root: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    relative = path.resolve().relative_to(run_root.resolve()).as_posix()
    return {"artifact_id": artifact_id, "path": relative, "bytes": size, "sha256": digest}


def stage_seal_payload(
    *,
    entries: Sequence[Mapping[str, Any]],
    contract_sha256: str,
    contract_seal_root_sha256: str,
    predecessor_roots: Mapping[str, str],
) -> dict[str, Any]:
    rows = sorted((dict(entry) for entry in entries), key=lambda row: row["artifact_id"].encode("utf-8"))
    return {
        "schema": SEAL_SCHEMA,
        "status": "SEALED",
        "seal_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_FRESH_SCORING_SEAL_V01",
        "stage": "FRESH_SCORING",
        "path_root_kind": "E4_RUN_ROOT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": contract_sha256,
        "contract_seal_root_sha256": contract_seal_root_sha256,
        "exact_predecessor_roots": dict(predecessor_roots),
        "entries": rows,
        "entry_count": len(rows),
        "root_sha256": e4_artifact_tree_root(rows),
    }


def write_prediction_rows(
    path: Path,
    primary: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, np.ndarray],
) -> None:
    rows = []
    for position, row in enumerate(primary):
        rows.append({
            "row_index": row["row_index"],
            "row_id": row["row_id"],
            "quartet_id": row["quartet_id"],
            "variant_id": row["variant_id"],
            "surface_id": row["surface_id"],
            "truth_partition": row["truth_partition"],
            "head_predictions": {task: int(predictions[task][position]) for task in scorer.TASKS},
        })
    atomic_create_bytes(path, jsonl_bytes(rows))


def write_scored_rows(path: Path, joined: Sequence[Mapping[str, Any]]) -> None:
    rows = []
    for row in joined:
        rows.append({
            "row_index": row["row_index"],
            "row_id": row["row_id"],
            "quartet_id": row["quartet_id"],
            "variant_id": row["variant_id"],
            "surface_id": row["surface_id"],
            "truth_partition": row["truth_partition"],
            "labels": row["labels"],
            "head_predictions": row["predictions"],
        })
    atomic_create_bytes(path, jsonl_bytes(rows))


def metrics_and_bootstrap(metrics: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    metrics_out = json.loads(json.dumps(metrics, allow_nan=False))
    arrays: dict[str, np.ndarray] = {}
    for ordinal, endpoint in enumerate(scorer.ENDPOINT_ORDER):
        key = f"endpoint_{ordinal:02d}__bootstrap_balanced_accuracy"
        result = metrics_out["endpoints"][endpoint]
        values = result.pop("bootstrap_scores", [])
        arrays[key] = np.asarray(values, dtype=np.float64)
        result["bootstrap_array_key"] = key
    metrics_out["bootstrap"]["storage"] = {
        "format": "NumPy NPZ, float64 arrays; endpoint order is the frozen contract order",
        "artifact_path": "score/bootstrap-v01.npz",
        "array_keys": list(arrays),
        "support_failed_endpoint_array": "empty float64 array; no bootstrap or RNG draws consumed",
    }
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    return metrics_out, buffer.getvalue()


def label_open_receipt(label_receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "FAS_E4_0_PRIMARY_LABEL_OPEN_RECEIPT_V01",
        "status": "PRIMARY_TERMINAL_LABELS_OPENED_ONCE",
        **dict(label_receipt),
        "escrow_label_file_open_count": 0,
        "scoring_authorization_checked_immediately_before_open": True,
    }

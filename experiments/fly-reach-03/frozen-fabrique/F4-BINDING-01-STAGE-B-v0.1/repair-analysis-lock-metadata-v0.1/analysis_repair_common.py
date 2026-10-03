"""Helpers for the versioned lock-metadata analysis continuation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent
STUDY = BRANCH.parents[1]
REPO = STUDY.parents[1]
RUN = STUDY / "runs" / "F4-BINDING-01-STAGE-B-PROSP-v0.1"
EMPTY_BLOCK_REPAIR = BRANCH / "repair-empty-block-loader-v0.1"
MANIFEST = HERE / "ANALYSIS-REPAIR-MANIFEST.json"
MANIFEST_SHA = HERE / "ANALYSIS-REPAIR-MANIFEST.sha256"
IDENTITY = "F4-BINDING-01-STAGE-B-ANALYSIS-METADATA-REPAIR-v0.1"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new_json(path: Path, value: Any) -> str:
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def require_manifest() -> dict[str, Any]:
    value = read_json(MANIFEST)
    expected = MANIFEST_SHA.read_text(encoding="ascii").strip()
    if value.get("identity") != IDENTITY or value.get("status") != "PASS" or sha_file(MANIFEST) != expected:
        raise RuntimeError("analysis metadata repair manifest/hash mismatch")
    for row in value["repair_sources"]:
        path = REPO / Path(row["path"])
        if not path.is_file() or path.stat().st_size != row["byte_length"] or sha_file(path) != row["sha256"]:
            raise RuntimeError(f"analysis repair source drift: {row['path']}")
    for row in value["immutable_inputs"]:
        path = REPO / Path(row["path"])
        if not path.is_file() or path.stat().st_size != row["byte_length"] or sha_file(path) != row["sha256"]:
            raise RuntimeError(f"analysis repair input drift: {row['path']}")
    return value


def enrich_lock_metadata(lock: dict[str, Any], registry_models: list[dict[str, Any]]) -> dict[str, Any]:
    """Join frozen fold metadata by fit_id without editing locked JSON bytes."""
    registry = {row["fit_id"]: row for row in registry_models}
    rows = lock.get("predictions")
    if not isinstance(rows, list) or len(rows) != 36 or len(registry) != 36:
        raise RuntimeError("frozen lock/registry model grid is not 36 unique models")
    enriched = dict(lock)
    output = []
    seen: set[str] = set()
    for row in rows:
        fit_id = row.get("fit_id")
        source = registry.get(fit_id)
        if source is None or fit_id in seen:
            raise RuntimeError("prediction lock and frozen model registry identities differ")
        seen.add(fit_id)
        item = dict(row)
        for key in ("fold_index", "heldout_block", "replicate_index"):
            if key in item and item[key] != source[key]:
                raise RuntimeError(f"prediction-lock metadata conflicts with registry: {fit_id}/{key}")
            item[key] = source[key]
        output.append(item)
    if seen != set(registry):
        raise RuntimeError("prediction lock omitted a frozen registry identity")
    enriched["predictions"] = output
    return enriched

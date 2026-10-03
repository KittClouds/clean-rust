"""Hash and identity checks shared by the empty-block repair continuation."""
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
MANIFEST_PATH = HERE / "REPAIR-MANIFEST.json"
MANIFEST_SHA_PATH = HERE / "REPAIR-MANIFEST.sha256"
REPAIR_ID = "F4-BINDING-01-STAGE-B-EMPTY-BLOCK-REPAIR-v0.1"


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


def require_repair_manifest() -> dict[str, Any]:
    manifest = read_json(MANIFEST_PATH)
    expected = MANIFEST_SHA_PATH.read_text(encoding="ascii").strip()
    actual = sha_file(MANIFEST_PATH)
    if actual != expected or manifest.get("identity") != REPAIR_ID or manifest.get("status") != "PASS":
        raise RuntimeError("empty-block repair manifest identity/hash mismatch")
    for entry in manifest["repair_sources"]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"empty-block repair source drift: {entry['path']}")
    freeze_path = BRANCH / "IMPLEMENTATION-FREEZE.json"
    if sha_file(freeze_path) != manifest["original_implementation_freeze_sha256"]:
        raise RuntimeError("original Stage B freeze changed during repair continuation")
    return manifest


def verify_immutable_inputs(manifest: dict[str, Any]) -> None:
    for entry in manifest["immutable_inputs"]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"immutable Stage B input drift: {entry['path']}")

#!/usr/bin/env python3
"""Verify the hash-bound Rung 0 atlas receipts without modifying any artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
LOCK_PATH = HERE / "rung0-lock.json"


def sha256(path: Path, normalize_text: bool = False) -> str:
    if normalize_text:
        content = path.read_bytes().replace(b"\r\n", b"\n")
        return hashlib.sha256(content).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-primitives",
        action="store_true",
        help="hash the large selected cached vectors as well as their extraction receipt",
    )
    args = parser.parse_args()

    receipt_path = HERE / "rung0-lock.sha256"
    expected_lock_hash = receipt_path.read_text(encoding="utf-8").split()[0].lower()
    actual_lock_hash = sha256(LOCK_PATH, normalize_text=True)
    if actual_lock_hash != expected_lock_hash:
        raise SystemExit(
            f"lock receipt mismatch: expected {expected_lock_hash} got {actual_lock_hash}"
        )

    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("schema") != "phoenix.bank-v1-rung0-atlas-lock/v1":
        raise SystemExit("unsupported Rung 0 lock schema")
    expected_surfaces = {
        "middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean"
    }
    actual_surfaces = {item["id"] for item in lock["selected_surfaces"]}
    if actual_surfaces != expected_surfaces:
        raise SystemExit(f"selected surface roster drift: {sorted(actual_surfaces)}")
    if lock["negative_control"]["id"] != "first_token":
        raise SystemExit("dead negative-control identity drifted")

    checked = 0
    failures: list[str] = []
    for group in ("artifacts", "source_files"):
        for entry in lock[group]:
            path = resolve_path(entry["path"])
            if not path.is_file():
                failures.append(f"missing: {path}")
                continue
            actual = sha256(path, normalize_text=(group == "source_files"))
            checked += 1
            if actual != entry["sha256"]:
                failures.append(
                    f"hash mismatch: {path} expected {entry['sha256']} got {actual}"
                )

    extraction_entry = next(
        item for item in lock["artifacts"]
        if item["role"] == "surface extraction receipt and primitive-cache hashes"
    )
    extraction_seal = json.loads(
        resolve_path(extraction_entry["path"]).read_text(encoding="utf-8")
    )
    for primitive in lock["cached_primitives"]:
        recorded = extraction_seal["primitives"][primitive["name"]]["sha256"]
        if recorded != primitive["sha256"]:
            failures.append(f"primitive receipt drift: {primitive['name']}")
        if args.verify_primitives:
            path = resolve_path(primitive["path"])
            if not path.is_file():
                failures.append(f"missing primitive: {path}")
                continue
            actual = sha256(path)
            checked += 1
            if actual != primitive["sha256"]:
                failures.append(
                    f"primitive hash mismatch: {path} expected "
                    f"{primitive['sha256']} got {actual}"
                )

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    mode = "including cached primitives" if args.verify_primitives else "receipt/source hashes"
    print(f"RUNG0_LOCK_VERIFIED mode={mode} checked_files={checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
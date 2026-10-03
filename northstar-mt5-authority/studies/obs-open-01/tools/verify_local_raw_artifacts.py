#!/usr/bin/env python3
"""Verify D-only OBS-OPEN-01 artifacts against the committed compact manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--local-root", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text("utf-8"))
    rows = []
    for artifact in manifest["artifacts"]:
        path = args.local_root / artifact["logical_path"]
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        digest = sha256_file(path) if exists else None
        rows.append({
            "logical_path": artifact["logical_path"],
            "exists": exists,
            "bytes_match": size == artifact["bytes"],
            "sha256_match": digest == artifact["sha256"],
        })
    passed = all(row["exists"] and row["bytes_match"] and row["sha256_match"] for row in rows)
    receipt = {
        "schema": "OBS_OPEN_LOCAL_RAW_VERIFICATION_V1",
        "outcome": "PASS" if passed else "FAIL",
        "artifact_count": len(rows),
        "verified_count": sum(row["exists"] and row["bytes_match"] and row["sha256_match"] for row in rows),
        "rows": rows,
    }
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_bytes(payload)
    print(payload.decode(), end="")
    return 0 if passed else 5


if __name__ == "__main__":
    raise SystemExit(main())

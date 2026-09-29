"""Verify the new extractor reproduces historical 1.2B E2 bytes on 256 rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from common import sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical-cache", type=Path, required=True)
    parser.add_argument("--smoke-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("parity receipt already exists")
    byte_count = 256 * 2048 * 4
    if args.smoke_cache.stat().st_size != byte_count:
        raise RuntimeError("smoke cache is not exactly 256 x 2048 f32")
    with args.historical_cache.open("rb") as source:
        reference = source.read(byte_count)
    smoke = args.smoke_cache.read_bytes()
    if len(reference) != byte_count or smoke != reference:
        raise RuntimeError("new extractor did not reproduce historical bytes")
    receipt = {
        "schema": "phoenix.e4-scale-extraction-parity/v1",
        "rows": 256, "dimension": 2048, "bytes_compared": byte_count,
        "byte_identical": True,
        "slice_sha256": hashlib.sha256(smoke).hexdigest(),
        "historical_full_cache_sha256": sha256(args.historical_cache),
        "new_smoke_cache_sha256": sha256(args.smoke_cache),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()

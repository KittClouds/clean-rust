"""Independent label-blind freshness audit for the E4-shaped comparison TEST."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from common import read_jsonl, sha256


def key(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--e1-inputs", type=Path, required=True)
    parser.add_argument("--test-inputs", type=Path, required=True)
    parser.add_argument("--test-seal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("audit output already exists")
    seal = json.loads(args.test_seal.read_text(encoding="utf-8"))
    expected = {entry["path"]: entry["sha256"] for entry in seal["files"]}
    if sha256(args.test_inputs) != expected["inputs.jsonl"]:
        raise RuntimeError("TEST input differs from frozen seal")
    e1_texts = set()
    e1_rows = set()
    for row in read_jsonl(args.e1_inputs):
        e1_texts.add(key(row["input_text"]))
        e1_rows.add(row["row_id"])
    test_texts = set()
    test_rows = set()
    count = 0
    for row in read_jsonl(args.test_inputs):
        digest = key(row["input_text"])
        if digest in e1_texts or digest in test_texts or row["row_id"] in e1_rows or row["row_id"] in test_rows:
            raise RuntimeError(f"freshness collision at TEST row {count}")
        test_texts.add(digest)
        test_rows.add(row["row_id"])
        count += 1
    if count != seal["primary_rows"]:
        raise RuntimeError("TEST row count differs from seal")
    report = {
        "schema": "phoenix.e4-scale-independent-freshness-audit/v1",
        "e1_rows": len(e1_rows), "test_rows": count,
        "duplicate_test_texts": 0, "test_text_overlap_with_e1": 0,
        "test_row_id_overlap_with_e1": 0,
        "e1_input_sha256": sha256(args.e1_inputs),
        "test_population_seal_sha256": sha256(args.test_seal),
        "truth_accessed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

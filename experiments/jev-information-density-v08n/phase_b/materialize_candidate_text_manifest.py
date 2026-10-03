"""Materialize the frozen text inputs for v0.8N candidate feature extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


CATALOG_SHA256 = "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e"
CATALOG_DEFAULT = Path(
    r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01"
    r"\phase-b-v03-inputs\candidate-catalog.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=CATALOG_DEFAULT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if sha256_file(args.catalog) != CATALOG_SHA256:
        raise RuntimeError("candidate catalog hash does not match sealed v0.8N input")
    catalog: dict[str, Any] = json.loads(args.catalog.read_text(encoding="utf-8"))
    if catalog.get("index_order") != "lexicographic candidate_semantic_id":
        raise RuntimeError("candidate catalog ordering is not the frozen lexical order")
    if catalog.get("profile") != "name_definition" or catalog.get("feature_dimension") != 2048:
        raise RuntimeError("candidate profile or feature dimension drift")
    entries = catalog.get("rows", [])
    if len(entries) != 48 or catalog.get("candidate_count") != 48:
        raise RuntimeError("candidate catalog must contain exactly 48 entries")

    semantic_ids = [str(row["candidate_semantic_id"]) for row in entries]
    if semantic_ids != sorted(semantic_ids) or len(set(semantic_ids)) != 48:
        raise RuntimeError("candidate IDs are not unique and lexicographically ordered")

    output_rows = []
    for index, row in enumerate(entries):
        name = str(row["name"])
        description = str(row["description"])
        text = f"{name} — {description}"
        output_rows.append(
            {
                "index": index,
                "candidate_semantic_id": semantic_ids[index],
                "profile": "name_definition",
                "name": name,
                "description": description,
                "model_input_text": text,
                "model_input_utf8_sha256": sha256_text(text),
                "feature_key": "mean_full@16",
                "expected_feature_dimension": 2048,
                "expected_feature_dtype": "float32",
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite candidate text manifest: {args.output}")
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for row in output_rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(
        json.dumps(
            {
                "status": "CANDIDATE_TEXT_MANIFEST_MATERIALIZED_NO_MODEL_CONTACT",
                "candidate_count": len(output_rows),
                "catalog_sha256": CATALOG_SHA256,
                "manifest_sha256": sha256_file(args.output),
                "model_loaded": False,
                "feature_extracted": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

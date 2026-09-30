"""Prepare a source-locked MultiNLI arm without loading BANK data."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq


HF_DATASET = "nyu-mll/glue"
HF_REVISION = "a17903a5822db5c0f065b813544eff839645333c"
CONFIG = "mnli"
LICENSE = "CC-BY-4.0"
ARCHIVE_URL = "https://dl.fbaipublicfiles.com/glue/data/MNLI.zip"
ARCHIVE_SHA256 = "e7c1d896d26ed6caf700110645df426cc2d8ebf02a5ab743d5a5c68ac1c83633"
SPLITS = {
    "train": 392702,
    "validation_matched": 9815,
    "validation_mismatched": 9832,
}
LABELS = {0: "entailment", 1: "neutral", 2: "contradiction"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_split(source: Path, output: Path, split: str, expected_rows: int) -> dict:
    counts: Counter[str] = Counter()
    rows = 0
    temporary = output.with_suffix(output.suffix + ".tmp")
    parquet = pq.ParquetFile(source)
    required = {"premise", "hypothesis", "label", "idx"}
    if not required.issubset(parquet.schema_arrow.names):
        raise RuntimeError(f"unexpected MultiNLI columns in {source}: {parquet.schema_arrow.names}")
    with temporary.open("w", encoding="utf-8", newline="\n") as target:
        for batch in parquet.iter_batches(batch_size=16384,
                                          columns=["premise", "hypothesis", "label", "idx"]):
            for row in batch.to_pylist():
                label_id = int(row["label"])
                label = LABELS.get(label_id)
                premise = (row["premise"] or "").strip()
                hypothesis = (row["hypothesis"] or "").strip()
                if label is None or not premise or not hypothesis:
                    raise RuntimeError(f"invalid labeled row {rows} in {source}")
                record = {
                    "row_id": f"mnli:{split}:{int(row['idx'])}",
                    "source_split": split,
                    "premise": premise,
                    "hypothesis": hypothesis,
                    "label": label,
                    "label_id": label_id,
                }
                target.write(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")) + "\n")
                rows += 1
                counts[label] += 1
    if rows != expected_rows:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{split} row count {rows} != expected {expected_rows}")
    temporary.replace(output)
    return {"rows": rows, "label_counts": dict(sorted(counts.items())),
            "sha256": sha256(output), "path": str(output.resolve())}


def prepare(archive_path: Path, parquet_dir: Path, output: Path) -> dict:
    archive_hash = sha256(archive_path)
    if archive_hash != ARCHIVE_SHA256:
        raise RuntimeError(f"MultiNLI archive SHA-256 mismatch: {archive_hash}")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    prepared = {}
    parquet_sources = {}
    for split, expected_rows in SPLITS.items():
        source = parquet_dir / f"{split}.parquet"
        if not source.is_file():
            raise FileNotFoundError(source)
        prepared[split] = write_split(source, output / f"{split}.jsonl",
                                      split, expected_rows)
        parquet_sources[split] = {"path": str(source.resolve()), "bytes": source.stat().st_size,
                                  "sha256": sha256(source)}
    lock = {
        "schema": "lexi-specialization-nli-source-lock/v1",
        "dataset": HF_DATASET,
        "dataset_revision": HF_REVISION,
        "config": CONFIG,
        "license": LICENSE,
        "source_url": ARCHIVE_URL,
        "archive": {"path": str(archive_path.resolve()), "bytes": archive_path.stat().st_size,
                    "sha256": archive_hash},
        "hub_parquet_conversion": "refs/convert/parquet for the pinned nyu-mll/glue MNLI config; exact files hashed below",
        "parquet_sources": parquet_sources,
        "label_map": LABELS,
        "split_policy": "train is specialization input; matched and mismatched validation are evaluation only",
        "bank_v1_used_for_training": False,
        "prepared": prepared,
    }
    lock_path = output / "source-lock.json"
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, sort_keys=True,
                                    indent=2) + "\n", encoding="utf-8")
    lock_hash = sha256(lock_path)
    (output / "source-lock-seal.json").write_text(
        json.dumps({"source_lock_sha256": lock_hash, "path": str(lock_path.resolve())},
                   sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"prepared": prepared, "source_lock_sha256": lock_hash,
            "source_lock_path": str(lock_path.resolve())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--parquet-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive.resolve(), args.parquet_dir.resolve(), args.output.resolve()),
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

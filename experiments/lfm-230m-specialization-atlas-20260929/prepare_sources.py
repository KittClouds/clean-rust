"""Validate pinned external datasets and write separate, source-preserving JSONL arms."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

OPENNER_REVISION = "725f738bf3a97ec102acfeec232fc5b2e54aa8ea"
GLICLASS_REVISION = "ee8e07d42c1f95a4421ae78498eec23aec74f1d7"
OPENNER_SOURCES = ("Tweebank", "UNER_English_EWT", "WNUT17")
SPLITS = ("train", "dev", "test")
SEED = 20260929


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_bucket(group_id: str) -> int:
    digest = hashlib.sha256(f"{SEED}:{group_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 100


def gliclass_split(group_id: str) -> str:
    bucket = stable_bucket(group_id)
    return "train" if bucket < 80 else ("dev" if bucket < 90 else "test")


def write_jsonl(path: Path, rows) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8", newline="\n") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")) + "\n")
            count += 1
    tmp.replace(path)
    return count, sha256(path)


def read_openner_file(path: Path, source: str, split: str):
    table = pq.read_table(path)
    if table.column_names != ["id", "tokens", "ner_tags"]:
        raise RuntimeError(f"unexpected OpenNER schema in {path}: {table.column_names}")
    metadata = table.schema.metadata or {}
    hf = json.loads(metadata[b"huggingface"])
    names = hf["info"]["features"]["ner_tags"]["feature"]["names"]
    if names[0] != "O":
        raise RuntimeError(f"unexpected outside label in {path}")
    for row in table.to_pylist():
        tokens = row["tokens"]
        tag_ids = row["ner_tags"]
        if len(tokens) != len(tag_ids):
            raise RuntimeError(f"token/tag length mismatch: {source}/{split}/{row['id']}")
        if any(tag < 0 or tag >= len(names) for tag in tag_ids):
            raise RuntimeError(f"tag ID outside schema: {source}/{split}/{row['id']}")
        yield {
            "row_id": f"{source}:{split}:{row['id']}",
            "source": source,
            "source_split": split,
            "source_id": int(row["id"]),
            "tokens": tokens,
            "ner_tags": [names[tag] for tag in tag_ids],
        }, names


def read_gliclass_file(path: Path):
    table = pq.read_table(path)
    if table.column_names != ["text", "true_labels", "all_labels"]:
        raise RuntimeError(f"unexpected GLiClass schema: {table.column_names}")
    for source_id, row in enumerate(table.to_pylist()):
        candidates = list(dict.fromkeys(str(x).strip() for x in row["all_labels"]
                                        if str(x).strip()))
        positives = {str(x).strip() for x in row["true_labels"] if str(x).strip()}
        missing = sorted(positives.difference(candidates))
        # A small number of source rows omit one or more positives from all_labels.
        # Preserve the source labels and add those positives as candidate options.
        candidates.extend(missing)
        yield {
            "row_id": f"gliclass:{source_id}",
            "source_id": source_id,
            "text": str(row["text"]),
            "true_labels": sorted(positives),
            "all_labels": candidates,
            "candidate_labels_repaired": len(missing),
            "split": gliclass_split(str(source_id)),
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    data_root = args.data_root.resolve()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty prepared directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": "lfm-230m-specialization-source-lock/v1",
        "seed": SEED,
        "arms": {},
        "bank_v1_used_for_training": False,
    }
    openner_splits = {split: [] for split in SPLITS}
    openner_tags = set()
    openner_source_files = []
    for source in OPENNER_SOURCES:
        for split in SPLITS:
            path = data_root / "openner" / source / "eng" / f"{split}-00000-of-00001.parquet"
            if not path.is_file():
                raise FileNotFoundError(path)
            count = 0
            for row, names in read_openner_file(path, source, split):
                openner_splits[split].append(row)
                openner_tags.update(row["ner_tags"])
                count += 1
            openner_source_files.append({"path": str(path), "split": split, "source": source,
                                         "rows": count, "bytes": path.stat().st_size,
                                         "sha256": sha256(path)})
    openner_outputs = {}
    for split, rows in openner_splits.items():
        count, digest = write_jsonl(output / "openner" / f"{split}.jsonl", rows)
        openner_outputs[split] = {"rows": count, "sha256": digest,
                                  "by_source": dict(Counter(r["source"] for r in rows))}
    manifest["arms"]["openner_en"] = {
        "repo": "bltlab/open-ner-standardized", "revision": OPENNER_REVISION,
        "sources": list(OPENNER_SOURCES), "source_split_policy": "preserve upstream train/dev/test",
        "tag_names_observed_in_source_splits": sorted(openner_tags),
        "files": openner_source_files, "prepared": openner_outputs,
        "note": "OpenNER collection CC-BY-4.0; each upstream corpus retains its own license terms.",
    }

    gliclass_path = data_root / "gliclass" / "data" / "train-00000-of-00001.parquet"
    if not gliclass_path.is_file():
        raise FileNotFoundError(gliclass_path)
    gliclass_rows = list(read_gliclass_file(gliclass_path))
    repaired_candidates = sum(r["candidate_labels_repaired"] for r in gliclass_rows)
    gliclass_outputs = {}
    for split in SPLITS:
        rows = [r for r in gliclass_rows if r["split"] == split]
        count, digest = write_jsonl(output / "gliclass" / f"{split}.jsonl", rows)
        gliclass_outputs[split] = {"rows": count, "sha256": digest}
    manifest["arms"]["gliclass_logic"] = {
        "repo": "knowledgator/gliclass-v3-logic-dataset", "revision": GLICLASS_REVISION,
        "license": "Apache-2.0", "source_split_policy": "deterministic 80/10/10 row-group split from upstream train-only file",
        "positive_candidates_appended": repaired_candidates,
        "source_file": {"path": str(gliclass_path), "rows": len(gliclass_rows),
                        "bytes": gliclass_path.stat().st_size, "sha256": sha256(gliclass_path)},
        "prepared": gliclass_outputs,
    }
    manifest_path = output / "source-lock.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                        indent=2) + "\n", encoding="utf-8")
    lock_hash = sha256(manifest_path)
    (output / "source-lock-seal.json").write_text(
        json.dumps({"source_lock_sha256": lock_hash,
                    "source_lock_path": str(manifest_path)}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({"phase": "sources_prepared", "output": str(output),
                      "openner": openner_outputs, "gliclass": gliclass_outputs,
                      "source_lock_sha256": lock_hash}, ensure_ascii=False))


if __name__ == "__main__":
    main()

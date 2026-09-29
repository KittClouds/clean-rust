"""Derive a shared quartet-disjoint TRAIN/DEV from historical E1 FIT only."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 << 20):
            h.update(block)
    return h.hexdigest()


def read_rows(path: Path):
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--e1", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("fit split already exists")
    split_path = args.e1 / "panel" / "split-manifest-v01.jsonl"
    inputs_path = args.e1 / "panel" / "panel-inputs-v01.jsonl"
    rows_path = args.e1 / "panel" / "row-manifest-v01.jsonl"
    labels_path = args.e1 / "labels" / "fit-labels-v01.jsonl"
    split_by_quartet = {r["quartet_id"]: r["split"] for r in read_rows(split_path)}
    labels = {r["row_id"]: r for r in read_rows(labels_path)}
    if len(labels) != 85_204:
        raise RuntimeError("E1 FIT label count differs from frozen population")
    rows = list(read_rows(rows_path))
    if len(rows) != 106_496 or any(r["row_index"] != i for i, r in enumerate(rows)):
        raise RuntimeError("E1 row manifest order is not contiguous")
    args.output.mkdir(parents=True)
    fit_input = args.output / "fit-inputs.jsonl"
    fit_map = args.output / "fit-row-map.jsonl"
    counts: Counter[str] = Counter()
    quartet_partitions: dict[str, str] = {}
    with inputs_path.open("r", encoding="utf-8") as source, fit_input.open("x", encoding="utf-8", newline="\n") as out_input, fit_map.open("x", encoding="utf-8", newline="\n") as out_map:
        compact = 0
        for index, line in enumerate(source):
            model_input = json.loads(line)
            manifest = rows[index]
            if model_input["row_id"] != manifest["row_id"]:
                raise RuntimeError(f"E1 row ordering mismatch at {index}")
            quartet = manifest["quartet_id"]
            if split_by_quartet[quartet] != "FIT":
                continue
            label = labels[model_input["row_id"]]
            if quartet not in quartet_partitions:
                value = int.from_bytes(hashlib.sha256(("E4-SCALE-DEV-20260928:" + quartet).encode()).digest()[:8], "big")
                quartet_partitions[quartet] = "DEV" if value % 10 == 0 else "TRAIN"
            partition = quartet_partitions[quartet]
            out_input.write(json.dumps(model_input, separators=(",", ":"), ensure_ascii=True) + "\n")
            row = {
                "row_id": model_input["row_id"],
                "quartet_id": quartet,
                "variant_id": model_input["variant_id"],
                "e1_index": index,
                "compact_index": compact,
                "partition": partition,
                "context_term_id": label["context_term_id"],
                "entity_term_id": label["entity_term_id"],
                "relation_id": label["relation_id"],
                "state_id": label["state_id"],
                "exact_target": label["exact_target"],
                "both_terms_train_side": label["both_terms_train_side"],
            }
            out_map.write(json.dumps(row, separators=(",", ":"), ensure_ascii=True) + "\n")
            counts[partition] += 1
            compact += 1
    if compact != 85_204 or counts["TRAIN"] == 0 or counts["DEV"] == 0:
        raise RuntimeError("invalid derived FIT TRAIN/DEV counts")
    if len({r["quartet_id"] for r in rows if split_by_quartet[r["quartet_id"]] == "FIT"}) != len(quartet_partitions):
        raise RuntimeError("not all FIT quartets were assigned")
    seal = {
        "schema": "phoenix.e4-scale-fit-split/v1",
        "split": "SHA256(E4-SCALE-DEV-20260928:quartet_id) first64 mod10=0 => DEV",
        "source": "E1 FIT only; historical E1 TEST excluded",
        "source_hashes": {p.name: sha256(p) for p in (split_path, inputs_path, rows_path, labels_path)},
        "counts": dict(counts),
        "quartet_counts": dict(Counter(quartet_partitions.values())),
        "fit_inputs_sha256": sha256(fit_input),
        "fit_row_map_sha256": sha256(fit_map),
    }
    (args.output / "fit-split-seal.json").write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": dict(counts), "quartets": len(quartet_partitions)}))


if __name__ == "__main__":
    main()

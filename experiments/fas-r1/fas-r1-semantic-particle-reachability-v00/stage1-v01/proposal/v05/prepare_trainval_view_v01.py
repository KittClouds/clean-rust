#!/usr/bin/env python3
"""Create a physically filtered V05 train/validation input view.

This utility reads the V05.1 task bundle and support roster, verifies their
receipts, then emits only train and validation rows. Its support manifest is a
train/validation-only projection suitable for the exact Rust teacher CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WORLD_SCHEMA = "R1_STAGE1_STRESS_GENERATION_V05_1"
SUPPORT_SCHEMA = "R1_STAGE1_STRESS_SENSOR_SUPPORT_V05_1"
SOURCE_IDENTITY = (
    "fas-r1-semantic-particle-reachability-v00/"
    "stage1-v01/stress-worlds-v05.1-support-manifest-repair"
)
SPLITS = {"train": 64, "validation": 16, "qualification": 16}
SCENARIOS = {
    "base-random",
    "base-swap-trap",
    "dense-random",
    "dense-swap-trap",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": sha256_bytes(data), "bytes": len(data)}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def parse_jsonl(data: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(data.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid {label} JSONL line {line_number}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"{label} JSONL line {line_number} is not an object")
        rows.append(value)
    return rows


def _artifact_records(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    outputs = receipt.get("output_hashes")
    if not isinstance(outputs, list):
        raise ValueError("generation receipt has no output hash list")
    records: dict[str, dict[str, Any]] = {}
    for item in outputs:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("malformed generation output record")
        if item["path"] in records:
            raise ValueError(f"duplicate generation output record {item['path']}")
        records[item["path"]] = item
    return records


def _verify_bundle(bundle_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, bytes]]:
    paths = {
        "private-tasks.jsonl": bundle_dir / "private-tasks.jsonl",
        "public-tasks.jsonl": bundle_dir / "public-tasks.jsonl",
        "public-search-starts-v05.jsonl": bundle_dir / "public-search-starts-v05.jsonl",
        "private-diagnostics.jsonl": bundle_dir / "private-diagnostics.jsonl",
        "stress-support-manifest-v05-1.json": bundle_dir / "stress-support-manifest-v05-1.json",
        "stress-config-v05.json": bundle_dir / "stress-config-v05.json",
    }
    generation_path = bundle_dir / "private-generation-receipt-v05-1.json"
    generation = load_json(generation_path)
    support = load_json(paths["stress-support-manifest-v05-1.json"])
    if (
        generation.get("schema") != WORLD_SCHEMA
        or generation.get("status") != "STRESS_GENERATION_COMPLETE"
        or generation.get("source_identity") != SOURCE_IDENTITY
        or generation.get("accepted_worlds") != 96
        or generation.get("lfm_or_model_contact_performed") is not False
        or generation.get("probe_or_training_performed") is not False
    ):
        raise ValueError("V05.1 generation receipt identity or source status changed")
    if support.get("schema") != SUPPORT_SCHEMA or support.get("status") != "STRESS_TRAIN_VALIDATION_QUALIFICATION_READY":
        raise ValueError("V05.1 support manifest identity or status changed")
    if support.get("split_counts") != SPLITS or support.get("paired_world_count") != 24:
        raise ValueError("V05.1 support split or paired-world counts changed")

    artifact_records = _artifact_records(generation)
    data: dict[str, bytes] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        raw = path.read_bytes()
        expected = artifact_records.get(name)
        if expected is None or expected.get("sha256") != sha256_bytes(raw) or expected.get("bytes") != len(raw):
            raise ValueError(f"V05.1 generation receipt does not bind {name}")
        data[name] = raw

    source = support.get("source", {})
    public = data["public-tasks.jsonl"]
    if source.get("path") != "public-tasks.jsonl" or source.get("sha256") != sha256_bytes(public):
        raise ValueError("support source does not bind the V05.1 public tasks")
    if source.get("bytes") != len(public) or source.get("rows") != 96:
        raise ValueError("support source size or row count changed")
    manifest_start = support.get("search_starts", {})
    starts = data["public-search-starts-v05.jsonl"]
    if manifest_start.get("sha256") != sha256_bytes(starts) or manifest_start.get("bytes") != len(starts):
        raise ValueError("support manifest does not bind the V05.1 public starts")
    return generation, support, artifact_records, data


def validate_roster(support: dict[str, Any], generation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    roster = support.get("family_roster")
    worlds = generation.get("worlds")
    if not isinstance(roster, list) or len(roster) != 96:
        raise ValueError("V05.1 roster must contain exactly 96 tasks")
    if not isinstance(worlds, list) or len(worlds) != 96:
        raise ValueError("V05.1 generation receipt must contain exactly 96 world rows")
    task_rows: dict[str, dict[str, Any]] = {}
    pair_roster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in roster:
        if not isinstance(row, dict):
            raise ValueError("support roster row is not an object")
        task_id = row.get("task_id")
        family_id = row.get("family_id")
        pair_id = row.get("paired_world_id")
        split = row.get("split")
        scenario = row.get("scenario_id")
        if not all(isinstance(value, str) and value for value in (task_id, family_id, pair_id)):
            raise ValueError("support roster has an empty task, family, or pair ID")
        if split not in SPLITS or scenario not in SCENARIOS:
            raise ValueError(f"unsupported split/scenario for {task_id}")
        if task_id in task_rows:
            raise ValueError(f"duplicate task ID {task_id}")
        task_rows[task_id] = row
        pair_roster[pair_id].append(row)
    if len(pair_roster) != 24:
        raise ValueError("V05.1 roster must contain 24 paired worlds")

    receipt_by_id = {row.get("task_id"): row for row in worlds if isinstance(row, dict)}
    if len(receipt_by_id) != 96 or set(receipt_by_id) != set(task_rows):
        raise ValueError("generation world roster does not match support task IDs")
    for pair_id, rows in pair_roster.items():
        if len(rows) != 4 or {row["scenario_id"] for row in rows} != SCENARIOS:
            raise ValueError(f"paired world {pair_id} must have four scenario variants")
        if len({row["split"] for row in rows}) != 1:
            raise ValueError(f"paired world {pair_id} crosses train/validation/qualification splits")
        worlds_for_pair = [receipt_by_id[row["task_id"]] for row in rows]
        if any(world.get("paired_world_id") != pair_id for world in worlds_for_pair):
            raise ValueError(f"generation paired-world identity differs for {pair_id}")
        if len({world.get("seed") for world in worlds_for_pair}) != 1:
            raise ValueError(f"paired world {pair_id} does not share one seed")
        for row, world in zip(rows, worlds_for_pair):
            if world.get("split") != row["split"] or world.get("scenario_id") != row["scenario_id"]:
                raise ValueError(f"generation/support split or scenario mismatch for {row['task_id']}")
    if Counter(row["split"] for row in task_rows.values()) != Counter(SPLITS):
        raise ValueError("support roster does not have the expected 64/16/16 split")
    return task_rows


def _filtered_rows(data: bytes, label: str, roster: dict[str, dict[str, Any]]) -> tuple[bytes, dict[str, int]]:
    rows = parse_jsonl(data, label)
    if len(rows) != 96:
        raise ValueError(f"{label} must contain exactly 96 rows")
    output = {"train": bytearray(), "validation": bytearray()}
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    for row in rows:
        task_id = row.get("id")
        if not isinstance(task_id, str) or task_id not in roster:
            raise ValueError(f"{label} contains an unknown task ID {task_id!r}")
        if task_id in seen:
            raise ValueError(f"{label} contains duplicate task ID {task_id}")
        seen.add(task_id)
        split = roster[task_id]["split"]
        if label == "public tasks" and row.get("family_id") != roster[task_id]["family_id"]:
            raise ValueError(f"public family mismatch for {task_id}")
        if label == "private tasks" and row.get("family_id") != roster[task_id]["family_id"]:
            raise ValueError(f"private family mismatch for {task_id}")
        if split in output:
            output[split].extend(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
            counts[split] += 1
    if seen != set(roster):
        raise ValueError(f"{label} task IDs do not exactly cover the V05.1 support roster")
    if counts != Counter({"train": SPLITS["train"], "validation": SPLITS["validation"]}):
        raise ValueError(f"{label} train/validation row counts changed: {dict(counts)}")
    joined = bytes(output["train"] + output["validation"])
    return joined, dict(counts)


def prepare(bundle_dir: Path, output_dir: Path) -> dict[str, Any]:
    bundle = bundle_dir.resolve(strict=True)
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite V05 train/validation view {output}")
    generation, support, _, data = _verify_bundle(bundle)
    roster = validate_roster(support, generation)
    private_view, private_counts = _filtered_rows(data["private-tasks.jsonl"], "private tasks", roster)
    public_view, public_counts = _filtered_rows(data["public-tasks.jsonl"], "public tasks", roster)

    selected_rows = [row for row in support["family_roster"] if row["split"] in ("train", "validation")]
    view_support = {
        "schema": "R1_STAGE1_STRESS_TRAIN_VALIDATION_VIEW_V05_V01",
        "status": "TRAIN_VALIDATION_VIEW_READY",
        "source": {
            "path": "public-tasks-trainval-v05.jsonl",
            "sha256": sha256_bytes(public_view),
            "bytes": len(public_view),
            "rows": 80,
        },
        "split_counts": {"train": 64, "validation": 16},
        "paired_world_count": 20,
        "family_roster": selected_rows,
        "pairing_contract": "all four V05 scenario variants of each paired_world_id remain in one split",
    }
    support_bytes = (json.dumps(view_support, sort_keys=True, indent=2) + "\n").encode("utf-8")
    output.mkdir(parents=True)
    outputs = {
        "private-tasks-trainval-v05.jsonl": private_view,
        "public-tasks-trainval-v05.jsonl": public_view,
        "stress-support-trainval-v05.json": support_bytes,
    }
    for name, raw in outputs.items():
        (output / name).write_bytes(raw)
    script_record = record(Path(__file__))
    receipt = {
        "schema": "R1_STAGE1_TRAIN_VALIDATION_VIEW_RECEIPT_V05_V01",
        "status": "TRAIN_VALIDATION_VIEW_COMPLETE",
        "input_bundle": str(bundle),
        "source_identity": generation["source_identity"],
        "source_generation_receipt_sha256": sha256_bytes(
            (bundle / "private-generation-receipt-v05-1.json").read_bytes()
        ),
        "source_support_manifest_sha256": sha256_bytes(data["stress-support-manifest-v05-1.json"]),
        "source_public_tasks_sha256": sha256_bytes(data["public-tasks.jsonl"]),
        "source_private_tasks_sha256": sha256_bytes(data["private-tasks.jsonl"]),
        "train_rows": 64,
        "validation_rows": 16,
        "qualification_rows_emitted": 0,
        "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "pair_count": 20,
        "pair_split_validation": "passed; every pair has exactly four scenario variants in one split",
        "private_task_view_split_counts": private_counts,
        "public_task_view_split_counts": public_counts,
        "source_script": script_record,
        "outputs": {name: {"sha256": sha256_bytes(raw), "bytes": len(raw)} for name, raw in outputs.items()},
    }
    receipt_bytes = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
    (output / "trainval-view-receipt-v05-v01.json").write_bytes(receipt_bytes)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = prepare(args.bundle, args.output)
    print(
        "R1_V05_TRAINVAL_VIEW_COMPLETE "
        f"train={receipt['train_rows']} validation={receipt['validation_rows']} "
        f"qualification_emitted={receipt['qualification_rows_emitted']} "
        f"receipt={args.output.resolve() / 'trainval-view-receipt-v05-v01.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

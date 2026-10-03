#!/usr/bin/env python3
"""Fit a v04 class-balanced proposal without using qualification targets.

This is a versioned engineering entrypoint for the immutable v04 world and
sensor artifacts. It reuses the v02 feature/model math, but deliberately owns
its support contract and receipt instead of importing the old support pins.
It does not fit V_reach.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

PROPOSAL_DIR = Path(__file__).resolve().parents[1]
STAGE1_DIR = PROPOSAL_DIR.parent
REPO_ROOT = STAGE1_DIR.parents[2]
V02_DIR = PROPOSAL_DIR / "v02"
sys.path.insert(0, str(PROPOSAL_DIR))
sys.path.insert(0, str(V02_DIR))

import feature_math as FM  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "r1_v04_reuse_v02_proposal_routines", V02_DIR / "train_pipeline.py"
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("could not load the frozen v02 proposal training routines")
V02 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = V02
_SPEC.loader.exec_module(V02)

GENERATION_SCHEMA = "R1_STAGE1_STRESS_GENERATION_V04"
SUPPORT_SCHEMA = "R1_STAGE1_STRESS_SENSOR_SUPPORT_V04"
SENSOR_SCHEMA = "R1_STAGE1_SENSOR_EXTRACTION_V01"
MODEL_ID = "LiquidAI/LFM2.5-1.2B-Base"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
RENDER_SEED_RULE = "render_task(task, task.seed ^ 0x0053_5552_4641_4345)"

EXPECTED = {
    "public": "4b257f4e484b268a14454a2392923f1b6d87f545d698191478c8c4e1396f6104",
    "private": "57705fa8c73281ffdd91e5b742f34fcdbdb443dc168cfc98ef1d7c029ab66ce8",
    "support": "f2984a29897abff1271223ee3b570d9f5497b3a0ea4a66e3b669838bb6197c5c",
    "generation_receipt": "e05a65b58e5e6f327b80e32d9611eab74a526d48a9d0d6df3db9bf3ba12d4786",
    "generator_src_lib": "20eef8fb31b1a3138af7324a9a88c113b8257c1ba4d1fac6f37c3c3d9c297464",
    "world_renderer": "24d51db581b6f7031b62de75c34ce0de93c6b6e3b9e7933ae95dd4f68bcbe2d4",
    "sensor_receipt": "5b513325fdc2b7ed5a17d0456df5d37f4599d69c8c3bf78a143327660699b28c",
    "identity_model": "9ffd60dfe8b2134843b50cc1a614a3f05ce69d8cc2fcb458f7999486214f50ff",
    "identity_receipt": "4dc5a448fe93f6b86252ea19f83a90b61e3c7226ef6377bde346e64cfe18fa78",
    "initial_proposal": "f8871c7877295e8b200ce40951fdb77b488b09ad7c3221810e0252afcc7969aa",
}
SPLIT_COUNTS = {"train": 64, "validation": 16, "qualification": 16}
STATES_PER_FAMILY = 32
N_ENTITIES = 20
N_ROLES = 3
RAW_SOLUTION_COUNT = 54
CANONICAL_CLASS_COUNT = 9
LEGAL_EDIT_COUNT = N_ENTITIES * (N_ROLES - 1)

# The target implementation is pinned because its class-distance helper takes
# the minimum over every raw assignment in each canonical class.
SOURCE_PINS = {
    "proposal/Cargo.toml": "af3dc007e18541b11560f77d2ee3789a3acd578663eac311b4397655f535b855",
    "proposal/Cargo.lock": "c2c281bc9b8b4460437e690eb808fa7f4032d9eb3107433174b359669b9040b1",
    "proposal/src/lib.rs": "8394d3b4c0e1de430a8be0d3fbefeaf613edfdf480ca996a65c563c8b937a155",
    "proposal/src/teacher.rs": "847db5a002cce34c5f700ad270acd822a25cd6cc457ac3fe2c28cbc1ddc6be93",
    "proposal/src/rollout.rs": "3121bc80704bae4378be5188735eee79771edf21297a6ae8a1f415bd2bbb34b5",
    "proposal/src/bin/r1_proposal_data.rs": "430fa95a9997aefdfeb5ddc0f953631c6e962357d8366eb3261e9ad1e2c285f3",
    "proposal/v02/train_pipeline.py": "3213bb8149f2ed84a6aa9362ee632a958d5a5b1d4be7af3e29810dbd3cb7276b",
    "proposal/v02/value_training.py": "7456c7e7de784c641bd691a68aa0d2d7b7e7b0ddbaf8adc91c27f16535d78394",
    "proposal/feature_math.py": "84265b1f714ed1711f1227437bde70d9582a4635759c946d0d502b6811c436fe",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-dir", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--identity-model", type=Path, required=True)
    parser.add_argument("--identity-receipt", type=Path, required=True)
    parser.add_argument("--initial-proposal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--states-per-family", type=int, default=STATES_PER_FAMILY)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument(
        "--cargo-target-dir",
        type=Path,
        default=Path(r"G:\cargo-targets\fas-r1-v04-proposal-v01"),
    )
    return parser.parse_args()


def file_record(path: Path) -> dict[str, Any]:
    digest, size = FM.sha256_file(path)
    return {"path": str(path.resolve()), "sha256": digest, "bytes": size}


def require_pin(path: Path, expected: str, label: str) -> dict[str, Any]:
    record = file_record(path.resolve(strict=True))
    if record["sha256"] != expected:
        raise ValueError(
            f"{label} SHA-256 changed: got {record['sha256']}, expected {expected}"
        )
    return record


def validate_support_manifest(manifest: dict[str, Any]) -> dict[str, str]:
    """Validate the exact v04 one-task-per-family 64/16/16 roster."""
    if manifest.get("schema") != SUPPORT_SCHEMA or manifest.get("status") != "STRESS_TRAIN_VALIDATION_QUALIFICATION_READY":
        raise ValueError("support manifest identity is not the expected frozen v04 contract")
    counts = manifest.get("split_counts")
    if counts != SPLIT_COUNTS:
        raise ValueError(f"v04 split counts changed: {counts!r}")
    roster = manifest.get("family_roster")
    if not isinstance(roster, list) or len(roster) != sum(SPLIT_COUNTS.values()):
        raise ValueError("v04 support roster must contain exactly 96 rows")
    task_split: dict[str, str] = {}
    family_split: dict[str, str] = {}
    observed = Counter()
    for row in roster:
        task_id = row.get("task_id")
        family_id = row.get("family_id")
        split = row.get("split")
        if not all(isinstance(value, str) and value for value in (task_id, family_id)):
            raise ValueError("support roster contains an empty task or family id")
        if split not in SPLIT_COUNTS:
            raise ValueError(f"unsupported v04 split {split!r}")
        if task_id in task_split or family_id in family_split:
            raise ValueError("v04 contract requires unique task and family IDs")
        task_split[task_id] = split
        family_split[family_id] = split
        observed[split] += 1
    if dict(observed) != SPLIT_COUNTS:
        raise ValueError(f"observed support split counts differ: {dict(observed)!r}")
    return task_split


def validate_teacher_rows(
    rows: list[dict[str, Any]],
    task_split: dict[str, str],
    states_per_family: int,
    task_family: dict[str, str] | None = None,
) -> dict[str, int]:
    """Validate split coverage and the exact v04 class-balanced target contract."""
    if states_per_family < 1:
        raise ValueError("states_per_family must be positive")
    expected_tasks = {task_id for task_id, split in task_split.items() if split != "qualification"}
    expected_rows = len(expected_tasks) * states_per_family
    if len(rows) != expected_rows:
        raise ValueError(f"teacher row count {len(rows)} != expected {expected_rows}")

    seen: dict[str, set[int]] = defaultdict(set)
    split_counts = Counter()
    for row in rows:
        task_id = row.get("task_id")
        split = row.get("family_split")
        if task_id not in task_split:
            raise ValueError(f"teacher target names an unknown task {task_id!r}")
        expected_split = task_split[task_id]
        if expected_split == "qualification" or split == "qualification":
            raise ValueError("qualification teacher target is forbidden")
        if split != expected_split:
            raise ValueError(f"teacher split mismatch for {task_id}: {split!r}")
        if task_family is not None and row.get("family_id") != task_family.get(task_id):
            raise ValueError(f"teacher family mismatch for {task_id}")
        if row.get("raw_solution_count") != RAW_SOLUTION_COUNT:
            raise ValueError(f"v04 raw solution count differs for {task_id}")
        if row.get("canonical_solution_class_count") != CANONICAL_CLASS_COUNT:
            raise ValueError(f"v04 canonical solution class count differs for {task_id}")
        assignment = row.get("assignment")
        if (
            not isinstance(assignment, list)
            or len(assignment) != N_ENTITIES
            or any(type(role) is not int or not 0 <= role < N_ROLES for role in assignment)
        ):
            raise ValueError(f"invalid v04 sampled assignment for {task_id}")
        state_index = row.get("state_index")
        if type(state_index) is not int or not 0 <= state_index < states_per_family:
            raise ValueError(f"invalid teacher state index for {task_id}")
        if state_index in seen[task_id]:
            raise ValueError(f"duplicate teacher state for {task_id}:{state_index}")
        seen[task_id].add(state_index)
        split_counts[split] += 1

        target = row.get("target")
        if (
            not isinstance(target, dict)
            or target.get("schema") != "r1-class-balanced-one-step-teacher-v01"
            or target.get("task_id") != task_id
            or target.get("class_count") != CANONICAL_CLASS_COUNT
        ):
            raise ValueError(f"class-balanced teacher target identity differs for {task_id}")
        if type(target.get("minimum_distance_before")) is not int or not (
            0 <= target["minimum_distance_before"] <= N_ENTITIES
        ):
            raise ValueError(f"invalid nearest-class distance telemetry for {task_id}")
        edits = target.get("edits")
        if not isinstance(edits, list) or len(edits) != LEGAL_EDIT_COUNT:
            raise ValueError(f"teacher target must contain all {LEGAL_EDIT_COUNT} legal edits")
        expected_edits = {
            (entity, role)
            for entity, old_role in enumerate(assignment)
            for role in range(N_ROLES)
            if role != old_role
        }
        actual_edits: set[tuple[int, int]] = set()
        improved_total = 0
        for edit in edits:
            entity = edit.get("entity")
            new_role = edit.get("new_role")
            if type(entity) is not int or type(new_role) is not int:
                raise ValueError("teacher edit entity/role must be integers")
            key = (entity, new_role)
            if key not in expected_edits or key in actual_edits:
                raise ValueError("teacher edits do not exactly enumerate legal role changes")
            actual_edits.add(key)
            improved = edit.get("n_improved_classes")
            delta_d_min = edit.get("delta_d_min")
            probability = edit.get("q_probability")
            if type(improved) is not int or not 0 <= improved <= CANONICAL_CLASS_COUNT:
                raise ValueError("teacher improved-class count is outside [0, 9]")
            if type(delta_d_min) is not int or not -1 <= delta_d_min <= 1:
                raise ValueError("Δd_min telemetry is outside the one-edit Hamming bound")
            if not isinstance(probability, (int, float)) or not math.isfinite(probability):
                raise ValueError("teacher q probability is not finite")
            improved_total += improved
        if actual_edits != expected_edits:
            raise ValueError("teacher target omits a legal edit")
        if target.get("total_improved_class_mass") != improved_total:
            raise ValueError("teacher total improved-class mass differs from its edit rows")
        outcome = target.get("outcome")
        if improved_total == 0:
            if outcome != "zero_mass" or any(edit["q_probability"] != 0 for edit in edits):
                raise ValueError("zero-mass teacher state must keep an explicit zero distribution")
        else:
            if outcome != "positive_mass":
                raise ValueError("positive-mass teacher state has the wrong outcome")
            for edit in edits:
                expected_q = edit["n_improved_classes"] / improved_total
                if not math.isclose(edit["q_probability"], expected_q, rel_tol=1e-7, abs_tol=1e-9):
                    raise ValueError("teacher q is not proportional to improved class count")
    if set(seen) != expected_tasks or any(
        indices != set(range(states_per_family)) for indices in seen.values()
    ):
        raise ValueError("teacher starts do not exactly cover the v04 train/validation roster")
    expected_split_rows = {
        split: SPLIT_COUNTS[split] * states_per_family for split in ("train", "validation")
    }
    observed_split_rows = {split: split_counts[split] for split in expected_split_rows}
    if observed_split_rows != expected_split_rows:
        raise ValueError(f"teacher split row counts differ: {observed_split_rows!r}")
    return {**observed_split_rows, "qualification": 0}


def verify_source_pins() -> dict[str, dict[str, Any]]:
    """Bind the exact teacher, fitting routines, and feature implementation."""
    records: dict[str, dict[str, Any]] = {}
    for relative, expected in SOURCE_PINS.items():
        path = (PROPOSAL_DIR / relative.removeprefix("proposal/")).resolve(strict=True)
        record = file_record(path)
        if record["sha256"] != expected:
            raise ValueError(f"pinned Stage1 source changed: {relative}")
        records[relative] = record
    return records


def validate_generation_world_roster(
    world_rows: list[dict[str, Any]], public_by_id: dict[str, dict[str, Any]]
) -> str:
    """Bind receipt seeds and exact-solver diagnostics to the rendered roster."""
    if len(world_rows) != 96 or len(public_by_id) != 96:
        raise ValueError("v04 generation diagnostics and public roster must each contain 96 worlds")
    if any(not isinstance(row, dict) for row in world_rows):
        raise ValueError("v04 generation world diagnostics must be objects")
    world_by_id = {row.get("task_id"): row for row in world_rows}
    if len(world_by_id) != 96 or set(world_by_id) != set(public_by_id):
        raise ValueError("v04 receipt world IDs differ from the public task roster")
    seed_projection = []
    for task_id in sorted(public_by_id):
        task = public_by_id[task_id]
        world = world_by_id[task_id]
        if (
            world.get("family_id") != task.get("family_id")
            or type(world.get("seed")) is not int
            or not 0 <= world["seed"] < 2**64
            or world.get("n") != N_ENTITIES
            or world.get("k") != N_ROLES
            or world.get("edge_count") != 36
            or world.get("raw_solution_count") != RAW_SOLUTION_COUNT
            or world.get("canonical_solution_class_count") != CANONICAL_CLASS_COUNT
            or world.get("role_automorphism_count") != 6
            or world.get("role_anonymous") is not True
        ):
            raise ValueError(f"v04 seed/solution diagnostics differ for {task_id}")
        seed_projection.append(
            {"task_id": task_id, "family_id": task["family_id"], "seed": world["seed"]}
        )
    return hashlib.sha256(
        json.dumps(seed_projection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def write_trainval_private_view(
    private_path: Path,
    task_split: dict[str, str],
    output_path: Path,
    task_family: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write only support-listed train/validation private tasks to a new file."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite private task view {output_path}")
    included: list[bytes] = []
    seen: set[str] = set()
    split_counts = Counter()
    omitted_qualification = 0
    with private_path.open("rb") as source:
        for line_number, raw_line in enumerate(source, 1):
            if not raw_line.strip():
                raise ValueError(f"blank line in private task JSONL at line {line_number}")
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid private task JSON at line {line_number}: {error}") from error
            task_id = row.get("id") if isinstance(row, dict) else None
            if not isinstance(task_id, str) or task_id not in task_split:
                raise ValueError(f"private task row {line_number} is absent from the support roster")
            if task_family is not None and row.get("family_id") != task_family.get(task_id):
                raise ValueError(f"private task family differs from support/public roster for {task_id}")
            if task_id in seen:
                raise ValueError(f"duplicate private task {task_id}")
            seen.add(task_id)
            split = task_split[task_id]
            if split in ("train", "validation"):
                included.append(raw_line if raw_line.endswith(b"\n") else raw_line + b"\n")
                split_counts[split] += 1
            elif split == "qualification":
                omitted_qualification += 1
            else:
                raise ValueError(f"unsupported private task split {split!r}")

    if seen != set(task_split):
        raise ValueError("private task IDs do not exactly cover the support roster")
    expected = {"train": SPLIT_COUNTS["train"], "validation": SPLIT_COUNTS["validation"]}
    observed = {split: split_counts[split] for split in expected}
    if observed != expected or omitted_qualification != SPLIT_COUNTS["qualification"]:
        raise ValueError(
            "filtered private task view must contain 64/16 train/validation rows "
            "and omit exactly 16 qualification rows"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as destination:
        for raw_line in included:
            destination.write(raw_line)
    view_record = file_record(output_path)
    return {
        "file": output_path.name,
        "sha256": view_record["sha256"],
        "bytes": view_record["bytes"],
        "rows": len(included),
        "split_counts": observed,
        "qualification_rows_omitted": omitted_qualification,
        "source_private_sha256": file_record(private_path)["sha256"],
        "included_task_ids_sha256": hashlib.sha256(
            "\n".join(
                sorted(task_id for task_id, split in task_split.items() if split in ("train", "validation"))
            ).encode("utf-8")
        ).hexdigest(),
    }


def verify_world_bundle(world_dir: Path) -> tuple[Path, Path, Path, dict[str, str], dict[str, Any]]:
    world_dir = world_dir.resolve(strict=True)
    public_path = world_dir / "public-tasks.jsonl"
    private_path = world_dir / "private-tasks.jsonl"
    support_path = world_dir / "stress-support-manifest-v04.json"
    generation_path = world_dir / "private-generation-receipt-v04.json"
    records = {
        "public": require_pin(public_path, EXPECTED["public"], "v04 public tasks"),
        "private": require_pin(private_path, EXPECTED["private"], "v04 private tasks"),
        "support": require_pin(support_path, EXPECTED["support"], "v04 support manifest"),
        "generation_receipt": require_pin(
            generation_path, EXPECTED["generation_receipt"], "v04 generation receipt"
        ),
    }
    receipt = json.loads(generation_path.read_text(encoding="utf-8"))
    if (
        receipt.get("schema") != GENERATION_SCHEMA
        or receipt.get("status") != "STRESS_GENERATION_COMPLETE"
        or receipt.get("source_identity")
        != "fas-r1-semantic-particle-reachability-v00/stage1-v01/stress-worlds-v04"
        or receipt.get("accepted_worlds") != 96
        or receipt.get("lfm_or_model_contact_performed") is not False
        or receipt.get("probe_or_training_performed") is not False
    ):
        raise ValueError("v04 generation receipt identity or no-model-contact declaration changed")
    source_hashes = {item["path"]: item["sha256"] for item in receipt["source_hashes"]}
    if (
        source_hashes.get("src/lib.rs") != EXPECTED["generator_src_lib"]
        or source_hashes.get("stage0-v01/world/src/render.rs") != EXPECTED["world_renderer"]
    ):
        raise ValueError("v04 renderer/generator source hash differs from the pinned seed contract")
    generator_source_path = STAGE1_DIR / "stress-worlds-v04" / "src" / "lib.rs"
    generator_source_record = require_pin(
        generator_source_path, EXPECTED["generator_src_lib"], "v04 renderer/generator source"
    )
    world_renderer_path = STAGE1_DIR.parent / "stage0-v01" / "world" / "src" / "render.rs"
    world_renderer_record = require_pin(
        world_renderer_path, EXPECTED["world_renderer"], "Stage0 task renderer source"
    )
    renderer_text = generator_source_path.read_text(encoding="utf-8")
    if "render_task(&task, seed ^ 0x0053_5552_4641_4345)" not in renderer_text:
        raise ValueError("v04 renderer seed salt no longer matches the pinned contract")
    output_hashes = {item["path"]: item for item in receipt["output_hashes"]}
    for name, path_key in (
        ("public-tasks.jsonl", "public"),
        ("private-tasks.jsonl", "private"),
        ("stress-support-manifest-v04.json", "support"),
    ):
        output = output_hashes.get(name)
        if output is None or output["sha256"] != records[path_key]["sha256"]:
            raise ValueError(f"v04 generation receipt does not bind {name}")
    support = json.loads(support_path.read_text(encoding="utf-8"))
    task_split = validate_support_manifest(support)
    source = support.get("source", {})
    if source.get("sha256") != records["public"]["sha256"] or source.get("rows") != 96:
        raise ValueError("v04 support source digest or row count differs")
    public_rows = FM.read_jsonl(public_path)
    public_by_id = {row.get("id"): row for row in public_rows}
    if len(public_rows) != 96 or set(public_by_id) != set(task_split):
        raise ValueError("v04 public task roster differs from support")
    support_by_task = {row["task_id"]: row for row in support["family_roster"]}
    receipt_world_rows = receipt.get("worlds")
    if not isinstance(receipt_world_rows, list):
        raise ValueError("v04 generation receipt lacks per-world seed diagnostics")
    seed_projection_sha256 = validate_generation_world_roster(receipt_world_rows, public_by_id)
    for task_id, task in public_by_id.items():
        support_row = support_by_task[task_id]
        if task.get("family_id") != support_row["family_id"]:
            raise ValueError(f"v04 family ID mismatch for {task_id}")
        if (task.get("n"), task.get("k"), len(task.get("clauses", []))) != (20, 3, 36):
            raise ValueError(f"v04 task shape changed for {task_id}")
    records["public_rows"] = {"rows": public_rows, "by_id": public_by_id}
    records["rendering"] = {
        "rule": RENDER_SEED_RULE,
        "generator_source_sha256": source_hashes["src/lib.rs"],
        "world_renderer_source_sha256": source_hashes["stage0-v01/world/src/render.rs"],
        "seed_projection_sha256": seed_projection_sha256,
    }
    records["renderer_sources"] = {
        "generator": generator_source_record,
        "world_renderer": world_renderer_record,
    }
    return public_path, private_path, support_path, task_split, records


def verify_sensor(sensor_dir: Path, public_path: Path, support_path: Path) -> tuple[Any, dict[str, Any]]:
    sensor_dir = sensor_dir.resolve(strict=True)
    receipt_path = sensor_dir / "receipt.json"
    receipt_pin = require_pin(receipt_path, EXPECTED["sensor_receipt"], "v04 sensor receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    model = receipt.get("model", {})
    extraction = receipt.get("extraction", {})
    if (
        receipt.get("schema") != SENSOR_SCHEMA
        or receipt.get("status") != "R1_SENSOR_EXTRACTION_COMPLETE"
        or model.get("repo_id") != MODEL_ID
        or model.get("revision") != MODEL_REVISION
        or model.get("hidden_size") != FM.HIDDEN_DIM
        or model.get("output_dtype") != "float32"
        or extraction.get("truncation") is not False
        or receipt.get("input", {}).get("support_manifest", {}).get("sha256")
        != file_record(support_path)["sha256"]
    ):
        raise ValueError("v04 sensor receipt model/extraction/support contract changed")
    feature_store = FM.load_feature_store(sensor_dir, public_path, FM.read_jsonl(public_path), support_path)
    if len(feature_store.tasks) != 96:
        raise ValueError("v04 sensor feature store does not cover 96 tasks")
    return feature_store, receipt_pin


def run_teacher(
    private_path: Path,
    public_path: Path,
    support_path: Path,
    states_per_family: int,
    output_path: Path,
    cargo_target_dir: Path,
) -> dict[str, Any]:
    """Run the pinned Stage1 teacher; Rust skips qual before solving/targeting."""
    manifest = PROPOSAL_DIR / "Cargo.toml"
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(cargo_target_dir.resolve())
    command = [
        "cargo",
        "run",
        "--release",
        "--manifest-path",
        str(manifest),
        "--bin",
        "r1_proposal_data",
        "--",
        "teacher",
        str(private_path),
        str(public_path),
        str(support_path),
        str(states_per_family),
        str(output_path),
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    (output_path.parent / "teacher-rust.log").write_text(
        "$ " + " ".join(command) + "\n" + completed.stdout + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode:
        raise RuntimeError(f"v04 Rust teacher failed with exit {completed.returncode}")
    return {"stdout": completed.stdout, "stderr": completed.stderr, "command": command}


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite v04 proposal attempt {output}")
    if args.states_per_family != STATES_PER_FAMILY or args.epochs <= 0:
        raise ValueError("v04 proposal contract uses 32 states/family and positive epochs")

    source_pins = verify_source_pins()
    public_path, private_path, support_path, task_split, world_records = verify_world_bundle(args.world_dir)
    feature_store, sensor_pin = verify_sensor(args.sensor_dir, public_path, support_path)
    # Retain the complete roster only for integrity checks. Downstream identity
    # inference and fitting receive train/validation features only.
    trainval_ids = {task_id for task_id, split in task_split.items() if split in ("train", "validation")}
    feature_store = FM.FeatureStore(
        sensor_dir=feature_store.sensor_dir,
        receipt_sha256=feature_store.receipt_sha256,
        receipt=feature_store.receipt,
        tasks={task_id: feature_store.tasks[task_id] for task_id in sorted(trainval_ids)},
    )
    identity_pin = require_pin(args.identity_model, EXPECTED["identity_model"], "identity checkpoint")
    identity_receipt_pin = require_pin(
        args.identity_receipt, EXPECTED["identity_receipt"], "identity probe receipt"
    )
    initial_proposal_pin = require_pin(
        args.initial_proposal, EXPECTED["initial_proposal"], "initial v01 proposal"
    )

    import torch

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    identity_probs = V02.identity_probabilities(
        feature_store, args.identity_model.resolve(strict=True), torch.device("cpu"), torch
    )
    expected_trainval = {
        task_id for task_id, split in task_split.items() if split in ("train", "validation")
    }
    if set(identity_probs) != expected_trainval:
        raise ValueError("frozen identity posterior must cover v04 train/validation only")

    output.mkdir(parents=True)
    task_family = {
        task_id: row["family_id"]
        for task_id, row in world_records["public_rows"]["by_id"].items()
    }
    private_view_record = write_trainval_private_view(
        private_path,
        task_split,
        output / "private-tasks-trainval-v04.jsonl",
        task_family,
    )
    targets_path = output / "proposal-teacher-targets-v04.jsonl"
    teacher_run = run_teacher(
        private_path,
        public_path,
        support_path,
        args.states_per_family,
        targets_path,
        args.cargo_target_dir,
    )
    teacher_rows = FM.read_jsonl(targets_path)
    teacher_counts = validate_teacher_rows(
        teacher_rows, task_split, args.states_per_family, task_family
    )
    examples, _, telemetry = V02.make_teacher_examples(
        teacher_rows,
        feature_store,
        world_records["public_rows"]["by_id"],
        identity_probs,
        output / "proposal-edit-diagnostics-v04.jsonl",
    )
    example_counts = {
        split: sum(row.split == split for row in examples) for split in ("train", "validation")
    }
    expected_example_counts = {
        "train": SPLIT_COUNTS["train"] * args.states_per_family,
        "validation": SPLIT_COUNTS["validation"] * args.states_per_family,
    }
    if example_counts != expected_example_counts:
        raise ValueError(f"proposal example counts differ: {example_counts!r}")

    proposal, history = V02.fit_proposal(
        examples, args.initial_proposal.resolve(strict=True), args.seed, args.epochs, torch
    )
    weights_path = output / "proposal-weights-v04.json"
    weights_sha = V02.export_proposal(proposal, weights_path)
    history_path = output / "proposal-training-history-v04.json"
    history_path.write_text(json.dumps(history, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    fit_rows = [row for row in examples if row.split == "train"]
    validation_rows = [row for row in examples if row.split == "validation"]
    metrics = {
        "train": V02.proposal_metrics(proposal, fit_rows),
        "validation": V02.proposal_metrics(proposal, validation_rows),
    }
    input_paths = [
        public_path,
        private_path,
        support_path,
        args.world_dir.resolve(strict=True) / "private-generation-receipt-v04.json",
        STAGE1_DIR / "stress-worlds-v04" / "src" / "lib.rs",
        STAGE1_DIR.parent / "stage0-v01" / "world" / "src" / "render.rs",
        args.sensor_dir.resolve(strict=True) / "receipt.json",
        args.sensor_dir.resolve(strict=True) / "constraint_H.float32.npy",
        args.sensor_dir.resolve(strict=True) / "global_h.float32.npy",
        args.sensor_dir.resolve(strict=True) / "rows.jsonl",
        args.identity_model.resolve(strict=True),
        args.identity_receipt.resolve(strict=True),
        args.initial_proposal.resolve(strict=True),
        Path(__file__).resolve(),
        Path(__file__).with_name("test_train_proposal.py").resolve(),
        V02_DIR / "train_pipeline.py",
        PROPOSAL_DIR / "feature_math.py",
    ]
    receipt = {
        "schema": "FAS_R1_PROPOSAL_FIT_V04_V01",
        "status": "R1_V04_PROPOSAL_FIT_COMPLETE",
        "analysis_mode": "ADAPTIVE_ENGINEERING",
        "qualification_previously_opened": True,
        "scientific_confirmation_eligible": False,
        "fit_scope": "class-balanced proposal only; V_reach not fitted",
        "world_bundle": {
            "generation_receipt_sha256": world_records["generation_receipt"]["sha256"],
            "public_sha256": world_records["public"]["sha256"],
            "private_sha256": world_records["private"]["sha256"],
            "support_sha256": world_records["support"]["sha256"],
            "rendering_contract": world_records["rendering"],
        },
        "private_trainval": private_view_record,
        "sensor_receipt": sensor_pin,
        "model": {"repo_id": MODEL_ID, "revision": MODEL_REVISION, "hidden_dim": FM.HIDDEN_DIM},
        "split_counts": SPLIT_COUNTS,
        "teacher_rows": teacher_counts,
        "proposal_examples": example_counts,
        "qualification_private_labels_used_for_targets": False,
        "qualification_targets_generated": False,
        "qualification_embeddings_hash_checked_during_feature_store_validation": True,
        "qualification_embeddings_used_for_identity_inference": False,
        "qualification_embeddings_retained_for_fit": False,
        "qualification_features_used_for_fit": False,
        "qualification_metrics_used_for_selection": False,
        "teacher_generation": {
            "states_per_family": args.states_per_family,
            "raw_solution_count_per_world": RAW_SOLUTION_COUNT,
            "canonical_solution_classes_per_world": CANONICAL_CLASS_COUNT,
            "legal_edits_per_start": LEGAL_EDIT_COUNT,
            "q_definition": "n_improved_classes / sum(n_improved_classes over all legal edits); zero mass remains explicit",
            "distance_semantics": "minimum Hamming distance over every raw assignment in each canonical class",
            "delta_d_min_role": "telemetry only; excluded from proposal features and loss",
            "positive_mass_states": telemetry["positive_mass_states"],
            "zero_mass_states": telemetry["zero_mass_states"],
            "edit_diagnostics": telemetry["edit_diagnostics"],
            "rust_stdout": teacher_run["stdout"].strip(),
        },
        "proposal": {
            "weights_file": weights_path.name,
            "weights_sha256": weights_sha,
            "architecture": "tanh_mlp_base_f10_h16_plus_adapter_bias_v02",
            "teacher": "class-balanced one-step reachability teacher",
            "initial_v01_sha256": initial_proposal_pin["sha256"],
            "frozen_identity_sha256": identity_pin["sha256"],
            "identity_receipt_sha256": identity_receipt_pin["sha256"],
            "metrics": metrics,
            "history_file": history_path.name,
        },
        "training": {"seed": args.seed, "epochs_max": args.epochs, "device": "cpu"},
        "pinned_source_hashes": source_pins,
        "source_and_input_hashes": {str(path): file_record(path) for path in input_paths},
        "cargo_target_dir": str(args.cargo_target_dir.resolve()),
    }
    receipt_path = output / "proposal-fit-receipt-v04-v01.json"
    receipt["output_files"] = {
        path.name: file_record(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path != receipt_path
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    args = parse_args()
    if args.output.resolve().exists():
        raise FileExistsError(f"refusing to overwrite v04 proposal attempt {args.output.resolve()}")
    try:
        receipt = run(args)
    except Exception as error:
        output = args.output.resolve()
        if output.exists() and not (output / "failure-v04.json").exists():
            (output / "failure-v04.json").write_text(
                json.dumps({"status": "R1_V04_PROPOSAL_FIT_FAILED", "error": str(error)}, indent=2)
                + "\n",
                encoding="utf-8",
            )
        raise
    print(
        "R1_V04_PROPOSAL_FIT_COMPLETE "
        f"weights_sha256={receipt['proposal']['weights_sha256']} "
        f"receipt={args.output.resolve() / 'proposal-fit-receipt-v04-v01.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

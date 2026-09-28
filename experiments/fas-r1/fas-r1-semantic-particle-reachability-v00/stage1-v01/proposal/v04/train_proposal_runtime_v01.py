#!/usr/bin/env python3
"""Fit V04 proposal weights against the frozen Rust runtime score contract.

This version starts from the V04 checkpoint, verifies its MLP base logits
against a Rust score dump, then fits only the MLP under the runtime
``incidence_masked_norm_4`` action adjustment. It consumes train/validation
teacher targets only and never fits V_reach.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

V04_DIR = Path(__file__).resolve().parent
PROPOSAL_DIR = V04_DIR.parent
STAGE1_DIR = PROPOSAL_DIR.parent
REPO_ROOT = STAGE1_DIR.parents[2]
V02_DIR = PROPOSAL_DIR / "v02"
sys.path.insert(0, str(PROPOSAL_DIR))
sys.path.insert(0, str(V02_DIR))

import feature_math as FM  # noqa: E402


def _load_sibling(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V02 = _load_sibling("r1_v04_runtime_reuse_v02", V02_DIR / "train_pipeline.py")
V04 = _load_sibling("r1_v04_runtime_reuse_v04", V04_DIR / "train_proposal.py")

STATES_PER_FAMILY = 32
LEGAL_EDIT_COUNT = 40
TRAIN_TASKS = 64
VALIDATION_TASKS = 16
N_ROLES = 3
N_ENTITIES = 20
RUNTIME_SPREAD_RATIO = np.float32(4.0)
RUNTIME_SD_EPSILON = 1e-8
BASE_PARITY_ATOL = 3e-4
BASE_PARITY_RTOL = 3e-5
TEMPERATURE_BETA_BOUNDS = (0.02, 20.0)
TEMPERATURE_BISECTION_STEPS = 96
TEMPERATURE_GRADIENT_TOLERANCE = 1e-12
TEMPERATURE_OBJECTIVE_TOLERANCE = 1e-12

SCORE_FIELDS = {
    "task_id",
    "family_id",
    "family_split",
    "state_index",
    "edit",
    "base_logit",
    "delta_c_raw",
    "delta_c_incidence_masked",
}
SCORE_ROW_SCHEMA = "R1_V04_RUNTIME_PROPOSAL_SCORE_ROWS_V01"
SCORE_RECEIPT_SCHEMA = "R1_V04_RUNTIME_PROPOSAL_SCORE_RECEIPT_V01"
SCORE_RECEIPT_STATUS = "R1_V04_RUNTIME_PROPOSAL_SCORE_EXPORT_COMPLETE"
INITIAL_PROPOSAL_SCHEMA = "r1-proposal-weights-v02"
SCORE_TASK_COUNTS = {"train": TRAIN_TASKS, "validation": VALIDATION_TASKS, "qualification": 0}
SCORE_STATE_COUNTS = {
    split: count * STATES_PER_FAMILY for split, count in SCORE_TASK_COUNTS.items()
}
SCORE_ROW_COUNTS = {
    split: count * STATES_PER_FAMILY * LEGAL_EDIT_COUNT
    for split, count in SCORE_TASK_COUNTS.items()
}
HISTORICAL_ONLY_SOURCE_PINS = {
    "proposal/src/lib.rs": (
        "The Stage1 V_reach simulator module was added after the frozen V04 fit; "
        "the historical file pin is taken from the V04 receipt and the current "
        "file hash is recorded separately."
    )
}


@dataclass(slots=True)
class RuntimeExample:
    task_id: str
    family_id: str
    family_split: str
    state_index: int
    actions: list[tuple[int, int]]
    features: np.ndarray
    q: np.ndarray
    base_logit_reference: np.ndarray
    delta_c_raw: np.ndarray
    delta_c_incidence_masked: np.ndarray
    zero_mass: bool
    target_sha256: str


@dataclass(slots=True)
class RuntimePrediction:
    task_id: str
    family_id: str
    state_index: int
    actions: list[tuple[int, int]]
    q: np.ndarray
    logits: np.ndarray
    zero_mass: bool
    target_sha256: str


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    digest, size = sha256_file(resolved)
    return {"path": str(resolved), "sha256": digest, "bytes": size}


def canonical_path_key(value: str | Path) -> str:
    """Normalize ordinary and Windows extended-length paths for provenance checks."""
    raw = os.fspath(value)
    folded = raw.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        raw = "\\\\" + raw[8:]
    elif folded.startswith("\\\\?\\"):
        raw = raw[4:]
    try:
        resolved = str(Path(raw).resolve(strict=False))
    except (OSError, RuntimeError):
        resolved = os.path.normpath(raw)
    return os.path.normcase(os.path.normpath(resolved))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def require_train_validation_split(split: Any, kind: str) -> str:
    """Reject qualification rows before reading any target or score fields."""
    if split == "qualification":
        raise ValueError(f"qualification {kind} row is forbidden")
    if split not in ("train", "validation"):
        raise ValueError(f"invalid {kind} split {split!r}")
    return str(split)


def _finite_f32(value: Any, label: str) -> np.float32:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = np.float32(value)
    if not np.isfinite(result):
        raise ValueError(f"{label} must be representable as finite f32")
    return result


def _target_digest(row: dict[str, Any]) -> str:
    raw = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_fit_receipt(
    fit_receipt: dict[str, Any], teacher_targets_path: Path, initial_weights_path: Path
) -> None:
    if fit_receipt.get("schema") != "FAS_R1_PROPOSAL_FIT_V04_V01":
        raise ValueError("input receipt is not the V04 proposal-fit receipt")
    if fit_receipt.get("status") != "R1_V04_PROPOSAL_FIT_COMPLETE":
        raise ValueError("V04 proposal fit receipt is not complete")
    if fit_receipt.get("split_counts") != {
        "train": TRAIN_TASKS,
        "validation": VALIDATION_TASKS,
        "qualification": 16,
    }:
        raise ValueError("V04 fit receipt split counts differ from the frozen 64/16/16 roster")
    if fit_receipt.get("teacher_rows") != {
        "train": TRAIN_TASKS * STATES_PER_FAMILY,
        "validation": VALIDATION_TASKS * STATES_PER_FAMILY,
        "qualification": 0,
    }:
        raise ValueError("V04 fit receipt teacher row counts differ from train/validation-only contract")
    for field in (
        "qualification_private_labels_used_for_targets",
        "qualification_targets_generated",
        "qualification_embeddings_used_for_identity_inference",
        "qualification_embeddings_retained_for_fit",
        "qualification_features_used_for_fit",
        "qualification_metrics_used_for_selection",
    ):
        if fit_receipt.get(field) is not False:
            raise ValueError(f"V04 fit receipt does not certify {field}=false")

    teacher_record = fit_receipt.get("output_files", {}).get(
        "proposal-teacher-targets-v04.jsonl", {}
    )
    weights_record = fit_receipt.get("output_files", {}).get(
        "proposal-weights-v04.json", {}
    )
    teacher_sha, _ = sha256_file(teacher_targets_path.resolve(strict=True))
    weights_sha, _ = sha256_file(initial_weights_path.resolve(strict=True))
    if teacher_record.get("sha256") != teacher_sha:
        raise ValueError("teacher targets do not match the V04 fit receipt")
    proposal_record = fit_receipt.get("proposal", {})
    if (
        weights_record.get("sha256") != weights_sha
        or proposal_record.get("weights_sha256") != weights_sha
    ):
        raise ValueError("initial weights do not match the V04 fit receipt")


def verify_historical_v04_source_pins(
    fit_receipt: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Verify V04 lineage without mistaking later V_reach wiring for refit drift."""
    receipt_pins = fit_receipt.get("pinned_source_hashes")
    expected_pins = V04.SOURCE_PINS
    if not isinstance(receipt_pins, dict) or set(receipt_pins) != set(expected_pins):
        raise ValueError("V04 fit receipt source pins differ from the pinned source registry")

    historical: dict[str, dict[str, Any]] = {}
    current_checked: list[str] = []
    current_excluded: dict[str, Any] = {}
    for relative, expected_sha256 in expected_pins.items():
        historical_record = receipt_pins[relative]
        if (
            not isinstance(historical_record, dict)
            or historical_record.get("sha256") != expected_sha256
            or type(historical_record.get("bytes")) is not int
            or historical_record["bytes"] <= 0
        ):
            raise ValueError(f"V04 fit receipt has an invalid historical source pin: {relative}")
        historical[relative] = historical_record
        source_path = (V04.PROPOSAL_DIR / relative.removeprefix("proposal/")).resolve(
            strict=True
        )
        current_record = file_record(source_path)
        if relative in HISTORICAL_ONLY_SOURCE_PINS:
            current_excluded[relative] = {
                "reason": HISTORICAL_ONLY_SOURCE_PINS[relative],
                "historical_sha256": expected_sha256,
                "current_source": current_record,
            }
            continue
        if (
            current_record["sha256"] != expected_sha256
            or current_record["bytes"] != historical_record["bytes"]
        ):
            raise ValueError(f"pinned V04 source changed: {relative}")
        current_checked.append(relative)

    return historical, {
        "historical_pin_source": "V04 proposal-fit receipt, checked against the frozen V04 pin registry",
        "current_source_revalidated": sorted(current_checked),
        "current_source_hash_recorded_without_historical_comparison": current_excluded,
    }


def _require_file_record_match(record: Any, observed: dict[str, Any], label: str) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"score receipt omits its {label} file record")
    for field in ("sha256", "bytes"):
        if record.get(field) != observed[field]:
            raise ValueError(f"{label} differs from score receipt ({field})")
    if record.get("path") is not None and canonical_path_key(record["path"]) != canonical_path_key(
        observed["path"]
    ):
        raise ValueError(f"{label} path differs from score receipt")


def validate_score_dump_receipt(
    score_receipt: dict[str, Any],
    score_dump_path: Path,
    initial_weights_path: Path,
    *,
    teacher_targets_path: Path | None = None,
    public_tasks_path: Path | None = None,
    support_manifest_path: Path | None = None,
    sensor_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate the Rust exporter's receipt before accepting any score rows."""
    if score_receipt.get("schema") != SCORE_RECEIPT_SCHEMA:
        raise ValueError("Rust score receipt has an unsupported schema")
    if score_receipt.get("status") != SCORE_RECEIPT_STATUS:
        raise ValueError("Rust score receipt is not complete")
    if score_receipt.get("output_schema") != SCORE_ROW_SCHEMA:
        raise ValueError("Rust score receipt declares an unsupported output schema")

    score_record = file_record(score_dump_path)
    _require_file_record_match(score_receipt.get("output"), score_record, "score dump")
    expected_score_path = canonical_path_key(score_dump_path.resolve(strict=True))
    receipt_output_path = score_receipt.get("output_path")
    if not isinstance(receipt_output_path, str) or canonical_path_key(
        receipt_output_path
    ) != expected_score_path:
        raise ValueError("score receipt output_path does not identify the supplied score dump")

    expected_rows = sum(SCORE_ROW_COUNTS.values())
    expected_states = sum(SCORE_STATE_COUNTS.values())
    if score_receipt.get("row_count") != expected_rows:
        raise ValueError("Rust score receipt row_count is not 80 tasks x 32 states x 40 edits")
    if score_receipt.get("state_count") != expected_states:
        raise ValueError("Rust score receipt state_count is not 80 tasks x 32 states")
    observed_split_rows = score_receipt.get("split_row_counts")
    if not isinstance(observed_split_rows, dict) or any(
        observed_split_rows.get(split, 0) != count for split, count in SCORE_ROW_COUNTS.items()
    ) or set(observed_split_rows).difference(SCORE_ROW_COUNTS):
        raise ValueError("Rust score receipt split counts differ from the 64/16/0 roster")

    inputs = score_receipt.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Rust score receipt omits input records")
    initial_record = file_record(initial_weights_path)
    _require_file_record_match(inputs.get("proposal_weights"), initial_record, "proposal weights")
    for label, expected_path in (
        ("teacher targets", teacher_targets_path),
        ("public tasks", public_tasks_path),
        ("support manifest", support_manifest_path),
    ):
        if expected_path is not None:
            _require_file_record_match(
                inputs.get({
                    "teacher targets": "teacher_targets",
                    "public tasks": "public_tasks",
                    "support manifest": "support_manifest",
                }[label]),
                file_record(expected_path),
                label,
            )
    if sensor_dir is not None:
        sensor_records = inputs.get("sensor_extraction")
        if not isinstance(sensor_records, dict):
            raise ValueError("Rust score receipt omits sensor extraction file records")
        for filename in (
            "receipt.json",
            "constraint_H.float32.npy",
            "global_h.float32.npy",
            "rows.jsonl",
        ):
            _require_file_record_match(
                sensor_records.get(filename),
                file_record(sensor_dir / filename),
                f"sensor input {filename}",
            )

    runtime = score_receipt.get("runtime")
    declarations = runtime.get("proposal_mix_logits") if isinstance(runtime, dict) else None
    if not isinstance(declarations, dict):
        raise ValueError("Rust score receipt omits runtime proposal-mix declarations")
    base_source = declarations.get("base_logit")
    if base_source != "BaseOnlyV03":
        raise ValueError("Rust score receipt does not declare BaseOnlyV03 as the base-logit source")
    masked_mix = declarations.get("logit_incidence_masked_norm_4")
    if not isinstance(masked_mix, str) or "IncidenceMaskedNormalizedV03" not in masked_mix or "4.0" not in masked_mix:
        raise ValueError("Rust score receipt does not declare incidence_masked_norm_4")
    proposal_sha = runtime.get("proposal_sha256")
    if proposal_sha != initial_record["sha256"]:
        raise ValueError("Rust runtime proposal digest differs from --initial-weights")

    return {
        "score_dump": score_record,
        "proposal_weights": initial_record,
        "row_schema": SCORE_ROW_SCHEMA,
        "base_logit_source": base_source,
        "runtime_mix_declaration": masked_mix,
        "row_count": expected_rows,
        "state_count": expected_states,
        "split_row_counts": dict(SCORE_ROW_COUNTS),
    }


def _teacher_roster(
    rows: list[dict[str, Any]], task_split: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    task_family: dict[str, str] = {}
    observed_split: dict[str, str] = {}
    for row in rows:
        # Check split first so a qualification target is never inspected.
        split = require_train_validation_split(row.get("family_split"), "teacher")
        task_id = row.get("task_id")
        family_id = row.get("family_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("teacher row has no task_id")
        if not isinstance(family_id, str) or not family_id:
            raise ValueError("teacher row has no family_id")
        if task_id not in task_split or task_split[task_id] != split:
            raise ValueError(f"teacher split differs from the pinned roster for {task_id}")
        if task_id in observed_split and observed_split[task_id] != split:
            raise ValueError(f"task {task_id} appears in multiple splits")
        if task_id in task_family and task_family[task_id] != family_id:
            raise ValueError(f"task {task_id} changes family identity")
        task_family[task_id] = family_id
        observed_split[task_id] = split
    if Counter(observed_split.values()) != Counter(
        {"train": TRAIN_TASKS, "validation": VALIDATION_TASKS}
    ):
        raise ValueError("teacher task roster must contain exactly 64 train and 16 validation tasks")
    if len(set(task_family.values())) != TRAIN_TASKS + VALIDATION_TASKS:
        raise ValueError("V04 train/validation tasks must have unique family IDs")
    return task_family, observed_split


def read_score_groups(
    path: Path,
    task_family: dict[str, str],
    task_split: dict[str, str],
    expected_proposal_sha256: str,
    expected_proposal_schema: str,
) -> dict[tuple[str, int], dict[tuple[int, int], dict[str, np.float32]]]:
    grouped: dict[
        tuple[str, int], dict[tuple[int, int], dict[str, np.float32]]
    ] = defaultdict(dict)
    row_splits: Counter[str] = Counter()
    for row_index, row in enumerate(read_jsonl(path), 1):
        split = require_train_validation_split(row.get("family_split"), "Rust score")
        missing = SCORE_FIELDS.union(
            {"schema", "proposal_weights_sha256", "proposal_schema"}
        ).difference(row)
        if missing:
            raise ValueError(f"Rust score row {row_index} misses fields {sorted(missing)}")
        if row.get("schema") != SCORE_ROW_SCHEMA:
            raise ValueError(f"Rust score row {row_index} has an unsupported schema")
        if row.get("proposal_weights_sha256") != expected_proposal_sha256:
            raise ValueError(f"Rust score row {row_index} uses a different proposal checkpoint")
        if row.get("proposal_schema") != expected_proposal_schema:
            raise ValueError(f"Rust score row {row_index} declares a different proposal schema")
        task_id = row.get("task_id")
        family_id = row.get("family_id")
        state_index = row.get("state_index")
        if not isinstance(task_id, str) or task_id not in task_family:
            raise ValueError(f"Rust score row {row_index} names an unknown task")
        if family_id != task_family[task_id] or split != task_split[task_id]:
            raise ValueError(f"Rust score row {row_index} split/family mismatch")
        if type(state_index) is not int or not 0 <= state_index < STATES_PER_FAMILY:
            raise ValueError(f"Rust score row {row_index} has an invalid state_index")
        edit = row.get("edit")
        if not isinstance(edit, dict):
            raise ValueError(f"Rust score row {row_index} has no edit object")
        entity, new_role = edit.get("entity"), edit.get("new_role")
        if type(entity) is not int or not 0 <= entity < N_ENTITIES:
            raise ValueError(f"Rust score row {row_index} has an invalid edit entity")
        if type(new_role) is not int or not 0 <= new_role < N_ROLES:
            raise ValueError(f"Rust score row {row_index} has an invalid edit role")
        action = (entity, new_role)
        key = (task_id, state_index)
        action_scores = grouped[key]
        if action in action_scores:
            raise ValueError(f"duplicate Rust score edit {task_id}:{state_index}:{action}")
        row_splits[split] += 1
        action_scores[action] = {
            "base_logit": _finite_f32(row["base_logit"], "base_logit"),
            "delta_c_raw": _finite_f32(row["delta_c_raw"], "delta_c_raw"),
            "delta_c_incidence_masked": _finite_f32(
                row["delta_c_incidence_masked"], "delta_c_incidence_masked"
            ),
        }
    if row_splits != Counter(SCORE_ROW_COUNTS):
        raise ValueError("Rust score rows do not contain the 64/16/0 train/validation action counts")
    if len(grouped) != sum(SCORE_STATE_COUNTS.values()):
        raise ValueError("Rust score rows do not contain exactly 2,560 train/validation states")
    if any(len(group) != LEGAL_EDIT_COUNT for group in grouped.values()):
        raise ValueError("each Rust score state must contain exactly 40 legal edits")
    return grouped


def build_runtime_examples(
    teacher_rows: list[dict[str, Any]],
    score_groups: dict[tuple[str, int], dict[tuple[int, int], dict[str, np.float32]]],
    feature_store: Any,
    public_by_id: dict[str, dict[str, Any]],
) -> list[RuntimeExample]:
    examples: list[RuntimeExample] = []
    static_by_task: dict[str, np.ndarray] = {}
    teacher_states: set[tuple[str, int]] = set()
    for row in teacher_rows:
        split = require_train_validation_split(row.get("family_split"), "teacher")
        task_id = row["task_id"]
        state_index = row["state_index"]
        key = (task_id, state_index)
        if key in teacher_states:
            raise ValueError(f"duplicate teacher state {task_id}:{state_index}")
        teacher_states.add(key)
        task = feature_store.tasks.get(task_id)
        public = public_by_id.get(task_id)
        if task is None or public is None:
            raise ValueError(f"missing train/validation public features for {task_id}")
        if task.split != split or task.family_id != row["family_id"]:
            raise ValueError(f"sensor task split/family mismatch for {task_id}")
        if task_id not in static_by_task:
            static_by_task[task_id] = FM.build_static_candidate_features(
                task, int(public["n"]), int(public["k"])
            )
        assignment = [int(role) for role in row["assignment"]]
        actions, candidate_features = FM.candidate_features(
            static_by_task[task_id], assignment
        )
        edits = row["target"]["edits"]
        expected_actions = [(int(edit["entity"]), int(edit["new_role"])) for edit in edits]
        if actions != expected_actions:
            raise ValueError(f"teacher action order differs from V02 feature order for {task_id}")
        score_by_action = score_groups.get(key)
        if score_by_action is None or set(score_by_action) != set(actions):
            raise ValueError(f"Rust score rows do not exactly cover {task_id}:{state_index}")
        ordered_scores = [score_by_action[action] for action in actions]
        q = np.asarray([float(edit["q_probability"]) for edit in edits], dtype=np.float32)
        zero_mass = row["target"]["outcome"] == "zero_mass"
        if zero_mass:
            if np.any(q != 0.0):
                raise ValueError(f"zero-mass teacher state has nonzero q for {task_id}:{state_index}")
        elif not np.isfinite(q).all() or not math.isclose(
            float(q.sum()), 1.0, rel_tol=0.0, abs_tol=1e-5
        ):
            raise ValueError(f"positive-mass teacher q is not normalized for {task_id}:{state_index}")
        examples.append(
            RuntimeExample(
                task_id=task_id,
                family_id=row["family_id"],
                family_split=split,
                state_index=state_index,
                actions=actions,
                features=np.asarray(candidate_features, dtype=np.float32),
                q=q,
                base_logit_reference=np.asarray(
                    [value["base_logit"] for value in ordered_scores], dtype=np.float32
                ),
                delta_c_raw=np.asarray(
                    [value["delta_c_raw"] for value in ordered_scores], dtype=np.float32
                ),
                delta_c_incidence_masked=np.asarray(
                    [value["delta_c_incidence_masked"] for value in ordered_scores],
                    dtype=np.float32,
                ),
                zero_mass=zero_mass,
                target_sha256=_target_digest(row),
            )
        )
    if set(score_groups) != teacher_states:
        extra = set(score_groups).difference(teacher_states)
        missing = teacher_states.difference(score_groups)
        raise ValueError(
            f"Rust score state coverage differs: extra={len(extra)} missing={len(missing)}"
        )
    if len(examples) != (TRAIN_TASKS + VALIDATION_TASKS) * STATES_PER_FAMILY:
        raise ValueError("V04 runtime fit requires exactly 2,560 train/validation states")
    for key, group in score_groups.items():
        if len(group) != LEGAL_EDIT_COUNT:
            raise ValueError(f"Rust score group {key} must contain exactly 40 legal edits")
    return examples


def runtime_mean_std_f32(values: np.ndarray) -> tuple[np.float32, np.float32]:
    """Rust mean_std semantics: f64 population accumulation, f32 outputs."""
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 1:
        raise ValueError("runtime mean/std input must be one-dimensional")
    if array.size == 0 or not np.isfinite(array).all():
        raise ValueError("runtime mean/std input must be nonempty and finite")
    values64 = [float(value) for value in array]
    mean64 = sum(values64) / len(values64)
    variance64 = sum((value - mean64) ** 2 for value in values64) / len(values64)
    return np.float32(mean64), np.float32(math.sqrt(variance64))


def runtime_normalized_logits_numpy(
    base_logits: np.ndarray,
    masked_delta: np.ndarray,
    spread_ratio: np.float32 = RUNTIME_SPREAD_RATIO,
) -> np.ndarray:
    """Forward reference for Rust's f32 ``incidence_masked_norm_4`` mix."""
    base = np.asarray(base_logits, dtype=np.float32)
    delta = np.asarray(masked_delta, dtype=np.float32)
    if base.ndim != 1 or delta.shape != base.shape or base.size == 0:
        raise ValueError("base logits and masked delta must be nonempty aligned vectors")
    if not np.isfinite(base).all() or not np.isfinite(delta).all():
        raise ValueError("base logits and masked delta must be finite")
    delta_mean, delta_sd = runtime_mean_std_f32(delta)
    _, base_sd = runtime_mean_std_f32(base)
    if delta_sd <= RUNTIME_SD_EPSILON or base_sd <= RUNTIME_SD_EPSILON or spread_ratio == 0:
        return base.copy()
    centered = np.subtract(delta, delta_mean, dtype=np.float32)
    normalized = np.divide(centered, delta_sd, dtype=np.float32)
    base_scaled = np.multiply(normalized, base_sd, dtype=np.float32)
    adjustment = np.multiply(base_scaled, spread_ratio, dtype=np.float32)
    return np.add(base, adjustment, dtype=np.float32)


def runtime_normalized_logits_torch(base_logits: Any, masked_delta: Any, torch: Any) -> Any:
    """Differentiable runtime mix with f64 population stats and f32 stages."""
    base = base_logits.to(dtype=torch.float32)
    delta = masked_delta.to(dtype=torch.float32)
    was_vector = base.ndim == 1
    if was_vector:
        base = base.unsqueeze(0)
        delta = delta.unsqueeze(0)
    if base.ndim != 2 or delta.shape != base.shape or base.numel() == 0:
        raise ValueError("base logits and masked delta must be aligned action vectors")
    base64 = base.to(dtype=torch.float64)
    delta64 = delta.to(dtype=torch.float64)
    delta_mean64 = torch.zeros(base.shape[0], dtype=torch.float64, device=base.device)
    base_mean64 = torch.zeros(base.shape[0], dtype=torch.float64, device=base.device)
    for action_index in range(base.shape[1]):
        delta_mean64 = delta_mean64 + delta64[:, action_index]
        base_mean64 = base_mean64 + base64[:, action_index]
    delta_mean64 = delta_mean64 / base.shape[1]
    base_mean64 = base_mean64 / base.shape[1]
    delta_variance64 = torch.zeros_like(delta_mean64)
    base_variance64 = torch.zeros_like(base_mean64)
    for action_index in range(base.shape[1]):
        delta_difference = delta64[:, action_index] - delta_mean64
        base_difference = base64[:, action_index] - base_mean64
        delta_variance64 = delta_variance64 + delta_difference * delta_difference
        base_variance64 = base_variance64 + base_difference * base_difference
    delta_sd64 = torch.sqrt(delta_variance64 / base.shape[1])
    base_sd64 = torch.sqrt(base_variance64 / base.shape[1])
    delta_mean = delta_mean64.to(dtype=torch.float32).unsqueeze(1)
    delta_sd = delta_sd64.to(dtype=torch.float32).unsqueeze(1)
    base_sd = base_sd64.to(dtype=torch.float32).unsqueeze(1)
    valid = (delta_sd > RUNTIME_SD_EPSILON) & (base_sd > RUNTIME_SD_EPSILON)
    safe_delta_sd = torch.where(valid, delta_sd, torch.ones_like(delta_sd))
    centered = delta - delta_mean
    normalized = centered / safe_delta_sd
    base_scaled = normalized * base_sd
    adjustment = base_scaled * torch.tensor(4.0, dtype=torch.float32, device=base.device)
    result = torch.where(valid, base + adjustment, base)
    return result.squeeze(0) if was_vector else result


def _torch_base_logits(model: Any, features: Any, torch: Any) -> Any:
    """V02 MLP in Rust's f32 accumulation order, vectorized over actions."""
    inputs = features.to(dtype=torch.float32)
    was_matrix = inputs.ndim == 2
    if was_matrix:
        inputs = inputs.unsqueeze(0)
    if inputs.ndim != 3 or inputs.shape[-1] != 10:
        raise ValueError("runtime proposal features must have shape [batch, actions, 10]")
    layer1 = model.network[0]
    layer2 = model.network[2]
    batch_size, action_count, _ = inputs.shape
    activation = layer1.bias.view(1, 1, -1).expand(batch_size, action_count, -1)
    for feature_index in range(10):
        product = inputs[:, :, feature_index].unsqueeze(-1) * layer1.weight[
            :, feature_index
        ].view(1, 1, -1)
        activation = activation + product
    hidden = torch.tanh(activation)
    output = layer2.bias.view(1, 1).expand(batch_size, action_count)
    for hidden_index in range(16):
        output = output + layer2.weight[0, hidden_index] * hidden[:, :, hidden_index]
    return output.squeeze(0) if was_matrix else output


def runtime_temperature_objective_and_gradient(
    examples: list[RuntimePrediction], beta: float
) -> tuple[float, float, dict[str, float]]:
    if not math.isfinite(beta) or beta <= 0:
        raise ValueError("inverse temperature must be finite and positive")
    task_losses: dict[str, list[float]] = defaultdict(list)
    task_gradients: dict[str, list[float]] = defaultdict(list)
    for row in examples:
        if row.zero_mass:
            continue
        z = np.asarray(row.logits, dtype=np.float32).astype(np.float64)
        q = np.asarray(row.q, dtype=np.float32).astype(np.float64)
        scaled = z * beta
        maximum = float(np.max(scaled))
        exponentials = np.exp(scaled - maximum)
        denominator = float(np.sum(exponentials, dtype=np.float64))
        log_denominator = math.log(denominator)
        log_probability = (scaled - maximum) - log_denominator
        probability = exponentials / denominator
        q_mass = float(np.sum(q, dtype=np.float64))
        loss = -float(np.sum(q * log_probability, dtype=np.float64))
        gradient = q_mass * float(np.sum(probability * z, dtype=np.float64)) - float(
            np.sum(q * z, dtype=np.float64)
        )
        task_losses[row.task_id].append(loss)
        task_gradients[row.task_id].append(gradient)
    if not task_losses:
        raise ValueError("temperature calibration has no positive-mass validation states")
    per_task = {
        task_id: float(np.mean(losses, dtype=np.float64))
        for task_id, losses in task_losses.items()
    }
    per_task_gradients = {
        task_id: float(np.mean(task_gradients[task_id], dtype=np.float64))
        for task_id in per_task
    }
    return (
        float(np.mean(list(per_task.values()), dtype=np.float64)),
        float(np.mean(list(per_task_gradients.values()), dtype=np.float64)),
        per_task,
    )


def calibrate_runtime_temperature(
    validation_predictions: list[RuntimePrediction],
    beta_bounds: tuple[float, float] = TEMPERATURE_BETA_BOUNDS,
) -> dict[str, Any]:
    beta_low, beta_high = beta_bounds
    if not (0 < beta_low < beta_high and math.isfinite(beta_high)):
        raise ValueError("inverse-temperature bounds must be finite, positive, and ordered")
    positive = [row for row in validation_predictions if not row.zero_mass]
    zero_count = sum(row.zero_mass for row in validation_predictions)
    if not positive:
        raise ValueError("temperature calibration has no positive-mass validation states")
    objective_low, gradient_low, _ = runtime_temperature_objective_and_gradient(
        positive, beta_low
    )
    objective_high, gradient_high, _ = runtime_temperature_objective_and_gradient(
        positive, beta_high
    )
    objective_mid, _, _ = runtime_temperature_objective_and_gradient(
        positive, (beta_low + beta_high) / 2.0
    )
    selected_beta: float | None = None
    iterations = 0
    if max(objective_low, objective_mid, objective_high) - min(
        objective_low, objective_mid, objective_high
    ) <= TEMPERATURE_OBJECTIVE_TOLERANCE:
        status = "NONIDENTIFIABLE_FALLBACK_T1"
    elif gradient_low >= -TEMPERATURE_GRADIENT_TOLERANCE:
        status = "LOWER_BOUNDARY_FALLBACK_T1"
    elif gradient_high <= TEMPERATURE_GRADIENT_TOLERANCE:
        status = "UPPER_BOUNDARY_FALLBACK_T1"
    else:
        lo, hi = beta_low, beta_high
        for iterations in range(1, TEMPERATURE_BISECTION_STEPS + 1):
            mid = (lo + hi) / 2.0
            _, gradient_mid, _ = runtime_temperature_objective_and_gradient(positive, mid)
            if gradient_mid > 0.0:
                hi = mid
            else:
                lo = mid
            if hi - lo <= 1e-12:
                break
        selected_beta = (lo + hi) / 2.0
        status = "INTERIOR_OPTIMUM"

    selected_temperature = 1.0 / selected_beta if selected_beta is not None else 1.0
    baseline_objective, _, baseline_by_task = runtime_temperature_objective_and_gradient(
        positive, 1.0
    )
    selected_objective, selected_gradient, selected_by_task = (
        runtime_temperature_objective_and_gradient(positive, 1.0 / selected_temperature)
    )
    return {
        "schema": "FAS_R1_RUNTIME_TEMPERATURE_CALIBRATION_V01",
        "status": status,
        "calibration_scope": "validation one-step teacher-distribution calibration",
        "search_reachability_evidence": False,
        "objective": "task-macro soft q cross-entropy of runtime logits divided by temperature",
        "objective_formula": "mean_task(mean_positive_validation_state(-sum_a q_a * log_softmax(z_a / T)))",
        "aggregation": "mean states within each task, then unweighted mean across tasks with positive states",
        "inverse_temperature_bounds": [beta_low, beta_high],
        "optimizer": "deterministic bisection of the convex objective derivative",
        "optimizer_iterations": iterations,
        "selected_inverse_temperature": selected_beta,
        "selected_temperature": selected_temperature,
        "fallback_temperature": 1.0 if selected_beta is None else None,
        "fallback_reason": status if selected_beta is None else None,
        "gradient_at_selected_inverse_temperature": selected_gradient,
        "baseline_temperature": 1.0,
        "baseline_task_macro_cross_entropy": baseline_objective,
        "selected_task_macro_cross_entropy": selected_objective,
        "validation_tasks_scored": len(selected_by_task),
        "validation_states_scored": len(positive),
        "zero_mass_validation_states_excluded": zero_count,
        "per_task_baseline_cross_entropy": baseline_by_task,
        "per_task_selected_cross_entropy": selected_by_task,
        "qualification_teacher_rows_used": False,
        "qualification_labels_or_outcomes_used": False,
    }


def load_initial_model(weights_path: Path, torch: Any) -> tuple[Any, dict[str, Any]]:
    payload = read_json(weights_path)
    if (
        payload.get("schema") != "r1-proposal-weights-v02"
        or payload.get("architecture") != "tanh_mlp_base_f10_h16_plus_adapter_bias_v02"
        or payload.get("input_dim") != 10
        or payload.get("hidden_dim") != 16
        or payload.get("static_feature_dim") != 8
    ):
        raise ValueError("initial checkpoint does not match the frozen V02 proposal schema")
    if (
        len(payload.get("w1", [])) != 16
        or any(len(row) != 10 for row in payload["w1"])
        or len(payload.get("b1", [])) != 16
        or len(payload.get("w2", [])) != 16
    ):
        raise ValueError("initial checkpoint tensor shapes differ from V02")
    numeric = [
        *[value for row in payload["w1"] for value in row],
        *payload["b1"],
        *payload["w2"],
        payload["b2"],
        payload["adapter_logit_bias"],
    ]
    if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in numeric):
        raise ValueError("initial checkpoint contains non-finite values")
    model = V02.ProposalModel(torch)
    with torch.no_grad():
        model.network[0].weight.copy_(torch.as_tensor(payload["w1"], dtype=torch.float32))
        model.network[0].bias.copy_(torch.as_tensor(payload["b1"], dtype=torch.float32))
        model.network[2].weight.copy_(
            torch.as_tensor(payload["w2"], dtype=torch.float32).reshape(1, -1)
        )
        model.network[2].bias.copy_(torch.as_tensor([payload["b2"]], dtype=torch.float32))
        model.adapter_logit_bias.copy_(
            torch.as_tensor(payload["adapter_logit_bias"], dtype=torch.float32)
        )
    model.adapter_logit_bias.requires_grad_(False)
    return model, payload


def verify_initial_base_parity(
    model: Any,
    examples: list[RuntimeExample],
    torch: Any,
    atol: float = BASE_PARITY_ATOL,
    rtol: float = BASE_PARITY_RTOL,
) -> dict[str, Any]:
    model.network.eval()
    differences: list[np.ndarray] = []
    references: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(examples), 32):
            batch = examples[start : start + 32]
            features = torch.as_tensor(
                np.stack([row.features for row in batch]), dtype=torch.float32
            )
            predicted = _torch_base_logits(model, features, torch).cpu().numpy().astype(np.float32)
            expected = np.stack([row.base_logit_reference for row in batch])
            differences.append(np.abs(predicted - expected))
            references.append(np.abs(expected))
    errors = np.concatenate(differences)
    magnitudes = np.concatenate(references)
    thresholds = atol + rtol * magnitudes
    if np.any(errors > thresholds):
        index = int(np.argmax(errors - thresholds))
        raise ValueError(
            "initial V04 MLP base logits fail Rust score parity: "
            f"max_abs={float(errors.max())} exceeds atol+rtol at flattened candidate {index}"
        )
    max_abs = float(errors.max(initial=np.float32(0.0)))
    max_relative = float(np.max(errors / np.maximum(magnitudes, np.float32(1e-12))))
    return {
        "status": "PASS",
        "candidate_rows": int(errors.size),
        "absolute_tolerance": atol,
        "relative_tolerance": rtol,
        "max_absolute_error": max_abs,
        "max_relative_error": max_relative,
        "reference": "Rust score dump base_logit",
    }


def _torch_runtime_logits(model: Any, row: RuntimeExample, torch: Any) -> Any:
    features = torch.as_tensor(row.features, dtype=torch.float32)
    delta = torch.as_tensor(row.delta_c_incidence_masked, dtype=torch.float32)
    base = _torch_base_logits(model, features, torch)
    return runtime_normalized_logits_torch(base, delta, torch)


def _torch_runtime_batch_logits(model: Any, rows: list[RuntimeExample], torch: Any) -> Any:
    features = torch.as_tensor(np.stack([row.features for row in rows]), dtype=torch.float32)
    delta = torch.as_tensor(
        np.stack([row.delta_c_incidence_masked for row in rows]), dtype=torch.float32
    )
    base = _torch_base_logits(model, features, torch)
    return runtime_normalized_logits_torch(base, delta, torch)


def evaluate_runtime(
    model: Any, rows: list[RuntimeExample], torch: Any
) -> tuple[dict[str, Any], list[RuntimePrediction]]:
    model.network.eval()
    losses_by_task: dict[str, list[float]] = defaultdict(list)
    top_mass_by_task: dict[str, list[float]] = defaultdict(list)
    predictions: list[RuntimePrediction] = []
    zero_mass = 0
    with torch.no_grad():
        for row in rows:
            logits = _torch_runtime_logits(model, row, torch)
            logits_np = logits.cpu().numpy().astype(np.float32, copy=True)
            predictions.append(
                RuntimePrediction(
                    task_id=row.task_id,
                    family_id=row.family_id,
                    state_index=row.state_index,
                    actions=row.actions,
                    q=row.q,
                    logits=logits_np,
                    zero_mass=row.zero_mass,
                    target_sha256=row.target_sha256,
                )
            )
            if row.zero_mass:
                zero_mass += 1
                continue
            q = torch.as_tensor(row.q, dtype=torch.float32)
            log_probability = torch.log_softmax(logits, dim=0)
            state_loss = float((-(q * log_probability).sum()).item())
            top_mass = float(row.q[int(torch.argmax(logits).item())])
            if not math.isfinite(state_loss) or not math.isfinite(top_mass):
                raise ValueError("runtime validation metric is non-finite")
            losses_by_task[row.task_id].append(state_loss)
            top_mass_by_task[row.task_id].append(top_mass)
    if not losses_by_task:
        raise ValueError("runtime proposal fit has no positive-mass states")
    per_task_loss = {
        task_id: float(np.mean(values, dtype=np.float64))
        for task_id, values in losses_by_task.items()
    }
    per_task_top_mass = {
        task_id: float(np.mean(top_mass_by_task[task_id], dtype=np.float64))
        for task_id in per_task_loss
    }
    pooled_losses = [value for values in losses_by_task.values() for value in values]
    metrics = {
        "task_macro_cross_entropy": float(np.mean(list(per_task_loss.values()), dtype=np.float64)),
        "state_mean_cross_entropy": float(np.mean(pooled_losses, dtype=np.float64)),
        "task_macro_top_action_teacher_q_mass": float(
            np.mean(list(per_task_top_mass.values()), dtype=np.float64)
        ),
        "positive_teacher_states": len(pooled_losses),
        "zero_mass_teacher_states": zero_mass,
        "tasks_scored": len(per_task_loss),
        "per_task_cross_entropy": per_task_loss,
    }
    return metrics, predictions


def fit_runtime_proposal(
    model: Any,
    examples: list[RuntimeExample],
    seed: int,
    epochs: int,
    torch: Any,
) -> tuple[Any, list[dict[str, Any]], int]:
    train = [row for row in examples if row.family_split == "train" and not row.zero_mass]
    validation = [row for row in examples if row.family_split == "validation"]
    if not train or not validation or epochs <= 0:
        raise ValueError("runtime V04 fit requires positive train support, validation rows, and epochs")
    torch.manual_seed(seed)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    model.adapter_logit_bias.requires_grad_(False)
    optimizer = torch.optim.AdamW(
        list(model.network.parameters()), lr=1e-3, weight_decay=1e-4
    )
    best_state: dict[str, Any] | None = None
    best_loss = float("inf")
    best_epoch = 0
    stale = 0
    history: list[dict[str, Any]] = []
    for epoch in range(1, epochs + 1):
        model.network.train()
        order = torch.randperm(len(train), generator=generator).tolist()
        for start in range(0, len(order), 32):
            batch = [train[index] for index in order[start : start + 32]]
            logits = _torch_runtime_batch_logits(model, batch, torch)
            q = torch.as_tensor(np.stack([row.q for row in batch]), dtype=torch.float32)
            loss = (-(q * torch.log_softmax(logits, dim=-1)).sum(dim=-1)).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        train_metrics, _ = evaluate_runtime(
            model, [row for row in examples if row.family_split == "train"], torch
        )
        validation_metrics, _ = evaluate_runtime(model, validation, torch)
        history.append(
            {
                "epoch": epoch,
                "train": train_metrics,
                "validation": validation_metrics,
                "adapter_logit_bias_frozen_ignored": float(
                    model.adapter_logit_bias.detach().cpu()
                ),
            }
        )
        val_loss = validation_metrics["task_macro_cross_entropy"]
        if val_loss < best_loss - 1e-8:
            best_loss = val_loss
            best_epoch = epoch
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.network.state_dict().items()
            }
            stale = 0
        else:
            stale += 1
            if stale >= 6:
                break
    if best_state is None:
        raise RuntimeError("runtime V04 fit did not select a checkpoint")
    model.network.load_state_dict(best_state)
    model.network.eval()
    history.append({"selected_epoch": best_epoch, "early_stopping_patience": 6})
    return model, history, best_epoch


def _input_record_from_fit_receipt(
    fit_receipt: dict[str, Any], path: Path, label: str
) -> dict[str, Any]:
    records = fit_receipt.get("source_and_input_hashes", {})
    key = str(path.resolve(strict=True))
    record = records.get(key)
    if not isinstance(record, dict) or not record.get("sha256"):
        raise ValueError(f"V04 fit receipt does not bind {label}: {key}")
    observed = file_record(path)
    if observed["sha256"] != record["sha256"] or observed["bytes"] != record["bytes"]:
        raise ValueError(f"{label} differs from the V04 fit receipt")
    return observed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-receipt", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--rust-score-dump", type=Path, required=True)
    parser.add_argument(
        "--rust-score-receipt",
        type=Path,
        help="Rust score receipt; defaults to <score dump>.receipt.json",
    )
    parser.add_argument("--initial-weights", type=Path, required=True)
    parser.add_argument("--public-tasks", type=Path, required=True)
    parser.add_argument("--support-manifest", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--base-parity-atol", type=float, default=BASE_PARITY_ATOL)
    parser.add_argument("--base-parity-rtol", type=float, default=BASE_PARITY_RTOL)
    parser.add_argument(
        "--score-dump-producer-source",
        type=Path,
        help="optional source file for the Rust exporter, included in the receipt",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite runtime proposal attempt {output}")
    if args.epochs <= 0 or args.base_parity_atol < 0 or args.base_parity_rtol < 0:
        raise ValueError("epochs must be positive and parity tolerances nonnegative")

    fit_receipt = read_json(args.fit_receipt.resolve(strict=True))
    validate_fit_receipt(fit_receipt, args.teacher_targets, args.initial_weights)
    score_dump_path = args.rust_score_dump.resolve(strict=True)
    score_receipt_path = (
        args.rust_score_receipt
        if args.rust_score_receipt is not None
        else Path(str(score_dump_path) + ".receipt.json")
    ).resolve(strict=True)
    score_receipt = read_json(score_receipt_path)
    score_contract = validate_score_dump_receipt(
        score_receipt,
        score_dump_path,
        args.initial_weights.resolve(strict=True),
        teacher_targets_path=args.teacher_targets.resolve(strict=True),
        public_tasks_path=args.public_tasks.resolve(strict=True),
        support_manifest_path=args.support_manifest.resolve(strict=True),
        sensor_dir=args.sensor_dir.resolve(strict=True),
    )
    task_split = V04.validate_support_manifest(read_json(args.support_manifest.resolve(strict=True)))
    task_family = {
        row["task_id"]: row["family_id"]
        for row in read_json(args.support_manifest.resolve(strict=True))["family_roster"]
    }
    teacher_rows = read_jsonl(args.teacher_targets.resolve(strict=True))
    task_family_from_targets, target_splits = _teacher_roster(teacher_rows, task_split)
    if task_family_from_targets != {key: task_family[key] for key in task_family_from_targets}:
        raise ValueError("teacher task/family mapping differs from the support manifest")
    teacher_counts = V04.validate_teacher_rows(
        teacher_rows,
        task_split,
        STATES_PER_FAMILY,
        task_family,
    )
    expected_teacher_counts = {
        "train": TRAIN_TASKS * STATES_PER_FAMILY,
        "validation": VALIDATION_TASKS * STATES_PER_FAMILY,
        "qualification": 0,
    }
    if teacher_counts != expected_teacher_counts:
        raise ValueError(f"teacher counts differ from the train/validation contract: {teacher_counts}")

    score_groups = read_score_groups(
        score_dump_path,
        task_family_from_targets,
        target_splits,
        expected_proposal_sha256=score_contract["proposal_weights"]["sha256"],
        expected_proposal_schema=INITIAL_PROPOSAL_SCHEMA,
    )
    public_rows = FM.read_jsonl(args.public_tasks.resolve(strict=True))
    public_by_id = {row["id"]: row for row in public_rows}
    if len(public_by_id) != len(public_rows):
        raise ValueError("public task IDs are not unique")
    full_feature_store = FM.load_feature_store(
        args.sensor_dir.resolve(strict=True),
        args.public_tasks.resolve(strict=True),
        public_rows,
        args.support_manifest.resolve(strict=True),
    )
    trainval_ids = set(task_family_from_targets)
    feature_store = FM.FeatureStore(
        sensor_dir=full_feature_store.sensor_dir,
        receipt_sha256=full_feature_store.receipt_sha256,
        receipt=full_feature_store.receipt,
        tasks={task_id: full_feature_store.tasks[task_id] for task_id in sorted(trainval_ids)},
    )
    public_trainval = {task_id: public_by_id[task_id] for task_id in trainval_ids}
    examples = build_runtime_examples(
        teacher_rows, score_groups, feature_store, public_trainval
    )

    source_pins, source_pin_audit = verify_historical_v04_source_pins(fit_receipt)
    source_paths = [
        Path(__file__).resolve(),
        V04_DIR / "train_proposal.py",
        V02_DIR / "train_pipeline.py",
        PROPOSAL_DIR / "feature_math.py",
        STAGE1_DIR / "search" / "src" / "inference_v02.rs",
        STAGE1_DIR / "search" / "src" / "terminal.rs",
        STAGE1_DIR / "search" / "src" / "policy.rs",
        STAGE1_DIR / "search" / "src" / "bin" / "r1_stage1_pilot.rs",
    ]
    if args.score_dump_producer_source is not None:
        source_paths.append(args.score_dump_producer_source.resolve(strict=True))
    source_hashes = {str(path.resolve(strict=True)): file_record(path) for path in source_paths}

    public_record = _input_record_from_fit_receipt(fit_receipt, args.public_tasks, "public tasks")
    support_record = _input_record_from_fit_receipt(
        fit_receipt, args.support_manifest, "support manifest"
    )
    sensor_records = {
        name: _input_record_from_fit_receipt(
            fit_receipt, args.sensor_dir / name, f"sensor input {name}"
        )
        for name in (
            "receipt.json",
            "constraint_H.float32.npy",
            "global_h.float32.npy",
            "rows.jsonl",
        )
    }
    input_records = {
        "fit_receipt": file_record(args.fit_receipt),
        "teacher_targets": file_record(args.teacher_targets),
        "rust_score_dump": file_record(args.rust_score_dump),
        "rust_score_receipt": file_record(score_receipt_path),
        "rust_score_contract": score_contract,
        "initial_weights": file_record(args.initial_weights),
        "public_tasks": public_record,
        "support_manifest": support_record,
        "sensor_files": sensor_records,
    }
    if args.score_dump_producer_source is not None:
        input_records["score_dump_producer_source"] = file_record(
            args.score_dump_producer_source
        )

    import torch

    random.seed(args.seed if args.seed is not None else fit_receipt.get("training", {}).get("seed", 0))
    np.random.seed(args.seed if args.seed is not None else fit_receipt.get("training", {}).get("seed", 0))
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    seed = args.seed if args.seed is not None else int(fit_receipt.get("training", {}).get("seed", 0))
    model, initial_payload = load_initial_model(args.initial_weights.resolve(strict=True), torch)
    parity = verify_initial_base_parity(
        model,
        examples,
        torch,
        atol=args.base_parity_atol,
        rtol=args.base_parity_rtol,
    )
    train_rows = [row for row in examples if row.family_split == "train"]
    validation_rows = [row for row in examples if row.family_split == "validation"]
    initial_train_metrics, _ = evaluate_runtime(model, train_rows, torch)
    initial_validation_metrics, _ = evaluate_runtime(model, validation_rows, torch)

    # Parity and matched-mix baseline evaluation precede any output or fitting.
    output.mkdir(parents=True)
    model, history, selected_epoch = fit_runtime_proposal(
        model, examples, seed, args.epochs, torch
    )
    train_metrics, _ = evaluate_runtime(model, train_rows, torch)
    validation_metrics, validation_predictions = evaluate_runtime(model, validation_rows, torch)

    weights_path = output / "proposal-weights-runtime-v01.json"
    weights_sha = V02.export_proposal(model, weights_path)
    history_path = output / "proposal-training-history-runtime-v01.json"
    history_path.write_text(
        json.dumps(history, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temperature = calibrate_runtime_temperature(validation_predictions)
    temperature_path = output / "runtime-temperature-calibration-v01.json"
    temperature_path.write_text(
        json.dumps(temperature, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    logits_path = output / "validation-runtime-logits-v01.jsonl"
    with logits_path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in validation_predictions:
            record = {
                "task_id": row.task_id,
                "family_id": row.family_id,
                "family_split": "validation",
                "state_index": row.state_index,
                "target_sha256": row.target_sha256,
                "edits": [
                    {"entity": entity, "new_role": role}
                    for entity, role in row.actions
                ],
                "runtime_logits_f32": [float(value) for value in row.logits],
            }
            stream.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")

    receipt_path = output / "proposal-runtime-fit-receipt-v01.json"
    receipt = {
        "schema": "FAS_R1_PROPOSAL_RUNTIME_FIT_V01",
        "status": "R1_RUNTIME_PROPOSAL_FIT_COMPLETE",
        "analysis_mode": "ADAPTIVE_ENGINEERING",
        "scientific_confirmation_eligible": False,
        "fit_scope": "V04 proposal MLP only; V_reach not fitted",
        "initial_matched_runtime_baseline": {
            "checkpoint_sha256": input_records["initial_weights"]["sha256"],
            "stage": "V84 checkpoint before runtime refit",
            "runtime_mix": "incidence_masked_norm_4",
            "metrics": {
                "train": initial_train_metrics,
                "validation": initial_validation_metrics,
            },
        },
        "runtime_mix": {
            "name": "incidence_masked_norm_4",
            "formula": "f32_base_logit + f32(((masked_delta - f32(mean_f64(masked_delta))) / f32(population_sd_f64(masked_delta))) * f32(population_sd_f64(base_logit)) * 4)",
            "population_standard_deviation": True,
            "statistic_accumulation": "f64; means and standard deviations cast to f32 before f32 adjustment operations",
            "fallback": "base logits unchanged if masked-delta or base-logit population SD <= 1e-8",
            "adapter_logit_bias": "frozen at V04 value and ignored by this runtime mix",
        },
        "initial_parity": parity,
        "split_counts": {
            "tasks": {"train": TRAIN_TASKS, "validation": VALIDATION_TASKS},
            "teacher_states": teacher_counts,
            "rust_score_actions": {
                "train": TRAIN_TASKS * STATES_PER_FAMILY * LEGAL_EDIT_COUNT,
                "validation": VALIDATION_TASKS * STATES_PER_FAMILY * LEGAL_EDIT_COUNT,
                "qualification": 0,
            },
        },
        "qualification_non_use": {
            "teacher_rows_used_for_fit": False,
            "score_rows_used_for_fit": False,
            "private_labels_or_outcomes_read": False,
            "features_used_for_fit": False,
            "metrics_used_for_selection": False,
            "feature_store_integrity_check_includes_qualification_embeddings": True,
            "qualification_embeddings_used_for_fit": False,
        },
        "model": {
            "architecture": "tanh_mlp_base_f10_h16_plus_adapter_bias_v02",
            "feature_schema": "r1-candidate-features-h-global-entity-role-load-v01-plus-semantic-adapter-expected-delta-v02",
            "initial_weights_sha256": input_records["initial_weights"]["sha256"],
            "output_weights_sha256": weights_sha,
            "adapter_logit_bias_initial": float(initial_payload["adapter_logit_bias"]),
            "adapter_logit_bias_trainable": False,
        },
        "training": {
            "seed": seed,
            "device": "cpu",
            "epochs_max": args.epochs,
            "selected_epoch": selected_epoch,
            "batch_states": 32,
            "optimizer": "AdamW",
            "learning_rate": 1e-3,
            "weight_decay": 1e-4,
            "early_stopping_patience": 6,
            "selection_metric": "validation task-macro runtime soft q cross-entropy",
            "metrics": {"train": train_metrics, "validation": validation_metrics},
            "history_file": history_path.name,
        },
        "temperature_calibration": {
            "artifact_file": temperature_path.name,
            "calibration_scope": "validation one-step teacher-distribution calibration",
            "search_reachability_evidence": False,
            "temperature_sha256": file_record(temperature_path)["sha256"],
            "selected_temperature": temperature["selected_temperature"],
            "status": temperature["status"],
            "validation_logits_file": logits_path.name,
        },
        "validation_logits_file": logits_path.name,
        "v04_fit_receipt_sha256": input_records["fit_receipt"]["sha256"],
        "pinned_v04_source_hashes": source_pins,
        "v04_source_pin_audit": source_pin_audit,
        "source_hashes": source_hashes,
        "input_hashes": input_records,
    }
    receipt["output_files"] = {
        path.name: file_record(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path != receipt_path
    }
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    args = parse_args()
    try:
        receipt = run(args)
    except Exception as error:
        print(f"R1_RUNTIME_PROPOSAL_FIT_V01_FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "R1_RUNTIME_PROPOSAL_FIT_V01_COMPLETE "
        f"weights_sha256={receipt['model']['output_weights_sha256']} "
        f"temperature={receipt['temperature_calibration']['selected_temperature']} "
        f"receipt={args.output.resolve() / 'proposal-runtime-fit-receipt-v01.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

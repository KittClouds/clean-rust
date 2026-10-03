#!/usr/bin/env python3
"""Validate V05 teacher targets and derive train/validation action labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


STATES_PER_TASK = 32
RAW_SOLUTIONS = 54
SOLUTION_CLASSES = 9


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    result = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number} is not a JSON object")
                result.append(row)
    return result


def satisfied(clause: dict[str, Any], assignment: list[int]) -> bool:
    if len(clause) != 1:
        raise ValueError("typed clause must have exactly one variant")
    kind, body = next(iter(clause.items()))
    if kind in ("Same", "Different"):
        equal = assignment[int(body["a"])] == assignment[int(body["b"])]
        return equal if kind == "Same" else not equal
    if kind == "FixedRole":
        return assignment[int(body["entity"])] == int(body["role"])
    if kind == "ForbiddenRole":
        return assignment[int(body["entity"])] != int(body["role"])
    if kind == "ExactlyOneRole":
        return sum(assignment[int(entity)] == int(body["role"]) for entity in body["entities"]) == 1
    if kind == "ImpliesNotRole":
        antecedent = assignment[int(body["if_entity"])] == int(body["if_role"])
        consequent = assignment[int(body["then_entity"])] == int(body["then_role"])
        return not (antecedent and consequent)
    raise ValueError(f"unsupported clause variant {kind!r}")


def satisfied_count(task: dict[str, Any], assignment: list[int]) -> int:
    return sum(satisfied(clause, assignment) for clause in task["clauses"])


def _expected_actions(assignment: list[int], roles: int) -> list[tuple[int, int]]:
    return [
        (entity, new_role)
        for entity, old_role in enumerate(assignment)
        for new_role in range(roles)
        if new_role != old_role
    ]


def build_action_rows(
    tasks: list[dict[str, Any]],
    teacher_rows: list[dict[str, Any]],
    split_by_task: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    task_by_id = {row.get("id"): row for row in tasks}
    if len(task_by_id) != len(tasks) or len(tasks) != 80:
        raise ValueError("V05 train/validation task view must contain 80 unique tasks")
    state_counts: Counter[tuple[str, str]] = Counter()
    action_rows: list[dict[str, Any]] = []
    split_signs: dict[str, Counter[str]] = defaultdict(Counter)
    improved_classes: Counter[int] = Counter()
    nearest_distance_delta: Counter[int] = Counter()

    for teacher in teacher_rows:
        task_id = teacher.get("task_id")
        task = task_by_id.get(task_id)
        split = teacher.get("family_split")
        if task is None or split not in ("train", "validation"):
            raise ValueError(f"teacher row has unknown task or forbidden split {task_id!r}/{split!r}")
        if split_by_task.get(task_id) != split:
            raise ValueError(f"teacher/support split mismatch for {task_id}")
        if teacher.get("family_id") != task["family_id"]:
            raise ValueError(f"teacher family mismatch for {task_id}")
        if teacher.get("schema") != "r1-proposal-teacher-sample-v01":
            raise ValueError(f"unsupported teacher row schema for {task_id}")
        if teacher.get("raw_solution_count") != RAW_SOLUTIONS or teacher.get("canonical_solution_class_count") != SOLUTION_CLASSES:
            raise ValueError(f"V05 exact solution contract differs for {task_id}")
        assignment = teacher.get("assignment")
        if not isinstance(assignment, list) or len(assignment) != task["n"]:
            raise ValueError(f"invalid assignment shape for {task_id}")
        if any(type(role) is not int or role < 0 or role >= task["k"] for role in assignment):
            raise ValueError(f"invalid assignment role for {task_id}")
        state_index = teacher.get("state_index")
        if type(state_index) is not int or not 0 <= state_index < STATES_PER_TASK:
            raise ValueError(f"invalid state index for {task_id}")
        state_key = (task_id, split)
        if state_counts[state_key] & (1 << state_index):
            raise ValueError(f"duplicate teacher state {task_id}:{state_index}")
        state_counts[state_key] |= 1 << state_index

        target = teacher.get("target", {})
        if target.get("schema") != "r1-class-balanced-one-step-teacher-v01" or target.get("task_id") != task_id:
            raise ValueError(f"unsupported teacher target identity for {task_id}")
        edits = target.get("edits")
        expected = _expected_actions(assignment, int(task["k"]))
        observed = [(row.get("entity"), row.get("new_role")) for row in edits or []]
        if observed != expected:
            raise ValueError(f"teacher legal edit order/coverage differs for {task_id}:{state_index}")
        before = satisfied_count(task, assignment)
        q_values = []
        for edit, (entity, new_role) in zip(edits, expected):
            q = edit.get("q_probability")
            if type(q) not in (int, float) or not math.isfinite(float(q)) or q < 0:
                raise ValueError(f"invalid teacher probability for {task_id}:{state_index}")
            q_values.append(float(q))
            next_assignment = assignment.copy()
            next_assignment[entity] = new_role
            after = satisfied_count(task, next_assignment)
            delta = after - before
            sign = (delta > 0) - (delta < 0)
            split_signs[split][str(sign)] += 1
            improved_classes[int(edit["n_improved_classes"])] += 1
            nearest_distance_delta[int(edit["delta_d_min"])] += 1
            action_rows.append({
                "schema": "r1-v05-action-relevance-label-v01",
                "task_id": task_id,
                "family_id": task["family_id"],
                "family_split": split,
                "state_index": state_index,
                "assignment": assignment,
                "satisfied_before": before,
                "edit": {"entity": entity, "from_role": assignment[entity], "to_role": new_role},
                "satisfied_after": after,
                "delta_satisfied": delta,
                "sign_delta": sign,
                "teacher_q_probability": float(q),
                "n_improved_classes": int(edit["n_improved_classes"]),
                "delta_d_min": int(edit["delta_d_min"]),
            })
        if target.get("outcome") == "positive_mass":
            if not math.isclose(sum(q_values), 1.0, rel_tol=0.0, abs_tol=1e-5):
                raise ValueError(f"positive teacher target is not normalized for {task_id}:{state_index}")
        elif target.get("outcome") == "zero_mass":
            if any(value != 0.0 for value in q_values):
                raise ValueError(f"zero-mass teacher target has nonzero mass for {task_id}:{state_index}")
        else:
            raise ValueError(f"unknown teacher outcome for {task_id}:{state_index}")

    expected_tasks = {(task["id"], split_by_task[task["id"]]) for task in tasks}
    if set(state_counts) != expected_tasks:
        raise ValueError("teacher task/split roster does not exactly cover the V05 train/validation view")
    expected_mask = (1 << STATES_PER_TASK) - 1
    if any(mask != expected_mask for mask in state_counts.values()):
        raise ValueError("teacher states do not cover 0..31 exactly once for each task")
    expected_rows = 80 * STATES_PER_TASK * 40
    if len(action_rows) != expected_rows:
        raise ValueError(f"action label count {len(action_rows)} != {expected_rows}")
    summary = {
        "teacher_state_rows": len(teacher_rows),
        "action_rows": len(action_rows),
        "task_counts": dict(Counter(split_by_task[task["id"]] for task in tasks)),
        "state_counts": dict(Counter(split for _, split in state_counts)),
        "action_sign_counts": {split: dict(counts) for split, counts in split_signs.items()},
        "improved_solution_class_count_histogram": {str(k): v for k, v in sorted(improved_classes.items())},
        "delta_d_min_histogram": {str(k): v for k, v in sorted(nearest_distance_delta.items())},
        "teacher_semantics": "class-balanced one-step reachability teacher; q proportional to number of improved canonical solution classes",
        "action_relevance_semantics": "sign of exact change in satisfied typed constraints after one legal edit",
    }
    return action_rows, summary


def export(view_dir: Path, teacher_path: Path, output_dir: Path) -> dict[str, Any]:
    view = view_dir.resolve(strict=True)
    targets = teacher_path.resolve(strict=True)
    output = output_dir.resolve(strict=True)
    receipt_path = view / "trainval-view-receipt-v05-v01.json"
    view_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if view_receipt.get("status") != "TRAIN_VALIDATION_VIEW_COMPLETE" or view_receipt.get("qualification_rows_emitted") != 0:
        raise ValueError("input is not the completed V05 train/validation-only view")
    for name, expected in view_receipt.get("outputs", {}).items():
        observed = sha256_file(view / name)
        if observed != (expected.get("sha256"), expected.get("bytes")):
            raise ValueError(f"train/validation view hash mismatch for {name}")
    private_tasks_path = view / "private-tasks-trainval-v05.jsonl"
    support_path = view / "stress-support-trainval-v05.json"
    tasks = read_jsonl(private_tasks_path)
    support = json.loads(support_path.read_text(encoding="utf-8"))
    split_by_task = {row["task_id"]: row["split"] for row in support["family_roster"]}
    if len(split_by_task) != 80 or set(split_by_task.values()) != {"train", "validation"}:
        raise ValueError("filtered support manifest is not an 80-row train/validation roster")
    teacher_rows = read_jsonl(targets)
    action_rows, summary = build_action_rows(tasks, teacher_rows, split_by_task)
    action_path = output / "private-action-relevance-labels-v05-v01.jsonl"
    if action_path.exists():
        raise FileExistsError(f"refusing to overwrite {action_path}")
    with action_path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in action_rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    receipt = {
        "schema": "R1_STAGE1_V05_ACTION_LABEL_RECEIPT_V01",
        "status": "V05_TRAINVAL_ACTION_LABELS_COMPLETE",
        "view_receipt_sha256": sha256_file(receipt_path)[0],
        "view_source_support_manifest_sha256": view_receipt["source_support_manifest_sha256"],
        "trainval_private_tasks": {"sha256": sha256_file(private_tasks_path)[0], "bytes": sha256_file(private_tasks_path)[1]},
        "teacher_targets": {"sha256": sha256_file(targets)[0], "bytes": sha256_file(targets)[1]},
        "action_labels": {"file": action_path.name, "sha256": sha256_file(action_path)[0], "bytes": sha256_file(action_path)[1]},
        "source_script": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__))[0]},
        "teacher_sources": {
            str(path.resolve()): {"sha256": sha256_file(path)[0], "bytes": sha256_file(path)[1]}
            for path in (
                Path(__file__).resolve().parents[1] / "Cargo.toml",
                Path(__file__).resolve().parents[1] / "Cargo.lock",
                Path(__file__).resolve().parents[1] / "src" / "lib.rs",
                Path(__file__).resolve().parents[1] / "src" / "teacher.rs",
                Path(__file__).resolve().parents[1] / "src" / "bin" / "r1_proposal_data.rs",
            )
        },
        "teacher_executable": {
            "path": r"G:\cargo-targets\fas-r1-stage1-search-v20\release\r1_proposal_data.exe",
            "sha256": sha256_file(Path(r"G:\cargo-targets\fas-r1-stage1-search-v20\release\r1_proposal_data.exe"))[0],
            "bytes": sha256_file(Path(r"G:\cargo-targets\fas-r1-stage1-search-v20\release\r1_proposal_data.exe"))[1],
        },
        "teacher_command": "r1_proposal_data teacher <trainval-private> <trainval-public> <trainval-support> 32 <teacher-target-jsonl>",
        "qualification_rows": 0,
        "qualification_targets_generated": False,
        "qualification_target_paths_or_hashes_recorded": False,
        "summary": summary,
    }
    receipt_path_out = output / "action-label-receipt-v05-v01.json"
    receipt_path_out.write_text(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view-dir", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = export(args.view_dir, args.teacher_targets, args.output_dir)
    print(f"R1_V05_ACTION_LABELS_COMPLETE rows={receipt['summary']['action_rows']} receipt={args.output_dir / 'action-label-receipt-v05-v01.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

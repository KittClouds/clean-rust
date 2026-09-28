from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
SOURCE = BANK / "vault" / "task-source-fixtures-final-v1.json"
CHECKS = BANK / "vault" / "candidate-check-labels-final-v1.json"
FRAMES = BANK / "observer-frames.json"
TRUTH = BANK / "vault" / "frame-truth-index.json"
OUTPUT = BANK / "vault" / "paired-truth-audit-v1.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_by_role(task: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    role_by_id = {
        int(action_id): role
        for action_id, role in task["candidate_role_by_action_id_hidden"].items()
    }
    return {
        role_by_id[int(option["action"]["id"])]: (
            str(option["patch_sha256"]), str(option["summary"]), str(option["diff_excerpt"])
        )
        for option in task["candidate_options_hidden"]
    }


def role_order(task: dict[str, Any]) -> tuple[str, ...]:
    role_by_id = {
        int(action_id): role
        for action_id, role in task["candidate_role_by_action_id_hidden"].items()
    }
    return tuple(role_by_id[int(value)] for value in task["producer_order_action_ids_hidden"])


def semantic_valid_roles(task: dict[str, Any]) -> frozenset[str]:
    role_by_id = {
        int(action_id): role
        for action_id, role in task["candidate_role_by_action_id_hidden"].items()
    }
    return frozenset(
        role_by_id[int(value)] for value in task["expected_valid_action_ids_hidden"]
    )


def signatures(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "E_t": task["request_text_authentic"],
        "E_c.content": candidate_by_role(task),
        "E_x": task["execution_text_authentic"],
        "E_r": (
            task["repository_id_hidden"], task["repository_code"],
            task["repository_revision"], task["snapshot_sha256"],
            task["task_family_code"], json.dumps(task["context_authentic"], sort_keys=True),
        ),
        "E_p": role_order(task),
        "action_ids_by_role": tuple(sorted(
            (role, int(action_id))
            for action_id, role in task["candidate_role_by_action_id_hidden"].items()
        )),
    }


def changed_fields(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    a, b = signatures(left), signatures(right)
    return [name for name in a if a[name] != b[name]]


def pair_rows(tasks: list[dict[str, Any]], groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair_id, members in sorted(groups.items()):
        members.sort(key=lambda row: int(row["within_family_index"]))
        declared = sorted({str(row["counterfactual_change_channel_hidden"]) for row in members})
        if len(members) == 2 and len(declared) == 1:
            target = declared[0]
            left, right = members
            if target in {"E_t", "E_x", "E_r", "E_c.content"}:
                outside = [
                    key for key in signatures(left)
                    if key not in {target, "action_ids_by_role"}
                ]
                # Stable IDs are part of the candidate/action identity contract and must
                # match even when candidate content itself is the manipulated channel.
                if signatures(left)["action_ids_by_role"] != signatures(right)["action_ids_by_role"]:
                    outside.append("action_ids_by_role")
                mismatches = [key for key in outside if signatures(left)[key] != signatures(right)[key]]
                if target == "E_c.content" and signatures(left)["E_c.content"] == signatures(right)["E_c.content"]:
                    mismatches.append("target_channel_unchanged")
                valid_left, valid_right = semantic_valid_roles(left), semantic_valid_roles(right)
                rows.append({
                    "pair_id": pair_id,
                    "family": left["family_name_hidden"],
                    "declared_change": target,
                    "task_ids": [left["task_id"], right["task_id"]],
                    "changed_channels_observed": changed_fields(left, right),
                    "valid_roles": [sorted(valid_left), sorted(valid_right)],
                    "valid_set_changed": valid_left != valid_right,
                    "paired_twin_pass": not mismatches and valid_left != valid_right,
                    "mismatches": mismatches,
                })
            else:
                rows.append({
                    "pair_id": pair_id,
                    "family": members[0]["family_name_hidden"],
                    "declared_change": target,
                    "task_ids": [row["task_id"] for row in members],
                    "paired_twin_pass": False,
                    "mismatches": ["unsupported_or_non-single-channel_pair"],
                })
        elif len(members) == 4 and declared == ["E_t+E_x"]:
            by_bits = {
                (int(row["family_spec_hidden"]["request_bit"]), int(row["family_spec_hidden"]["execution_bit"])): row
                for row in members
            }
            expected_bits = {(0, 0), (0, 1), (1, 0), (1, 1)}
            if set(by_bits) != expected_bits:
                rows.append({
                    "pair_id": pair_id,
                    "family": members[0]["family_name_hidden"],
                    "declared_change": target,
                    "task_ids": [row["task_id"] for row in members],
                    "paired_twin_pass": False,
                    "declared_change": "E_t+E_x factorial",
                    "mismatches": ["incomplete_factorial_bits"],
                })
                continue
            comparisons = []
            for varying in ("E_t", "E_x"):
                fixed_bit = 1 if varying == "E_t" else 0
                pairs = []
                for held_value in (0, 1):
                    key_a = (held_value, fixed_bit) if varying == "E_t" else (fixed_bit, held_value)
                    key_b = (held_value, 1 - fixed_bit) if varying == "E_t" else (1 - fixed_bit, held_value)
                    a, b = by_bits[key_a], by_bits[key_b]
                    changed = changed_fields(a, b)
                    expected_changed = {varying}
                    role_sets_differ = semantic_valid_roles(a) != semantic_valid_roles(b)
                    pairs.append({
                        "task_ids": [a["task_id"], b["task_id"]],
                        "changed_channels_observed": changed,
                        "valid_set_changed": role_sets_differ,
                        "pass": set(changed) == expected_changed and role_sets_differ,
                    })
                comparisons.append({"varying_channel": varying, "pairs": pairs})
            rows.append({
                "pair_id": pair_id,
                "family": members[0]["family_name_hidden"],
                "declared_change": "E_t+E_x factorial",
                "task_ids": [row["task_id"] for row in members],
                "factorial_pairs": comparisons,
                "paired_twin_pass": all(pair["pass"] for c in comparisons for pair in c["pairs"]),
                "mismatches": [
                    f"{c['varying_channel']}:{','.join(p['task_ids'])}"
                    for c in comparisons for p in c["pairs"] if not p["pass"]
                ],
            })
        else:
            rows.append({
                "pair_id": pair_id,
                "family": members[0]["family_name_hidden"],
                "declared_change": declared,
                "task_ids": [row["task_id"] for row in members],
                "paired_twin_pass": False,
                "mismatches": ["unexpected_pair_cardinality_or_factor"],
            })
    return rows


def frame_seal_checks(frames: list[dict[str, Any]], truth: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[tuple[str, str], dict[str, Any]] = {}
    for frame, entry in zip(frames, truth, strict=True):
        by_task[(entry["task_id"], entry["condition"])] = frame
    mismatches = []
    checked = 0
    for task_id in sorted({task for task, _ in by_task}):
        base = by_task[(task_id, "full_frame")]
        for condition, channel in (
            ("leave_out_E_t", "E_t"), ("leave_out_E_c", "E_c.content"),
            ("leave_out_E_x", "E_x"), ("leave_out_E_r", "E_r"),
        ):
            checked += 1
            frame = by_task[(task_id, condition)]
            if frame["action_options"] != base["action_options"]:
                mismatches.append({"task_id": task_id, "condition": condition, "error": "candidate_or_order_drift"})
            if channel == "E_t" and frame["task_prompt"] == base["task_prompt"]:
                mismatches.append({"task_id": task_id, "condition": condition, "error": "E_t_not_removed"})
            elif channel == "E_c.content" and not all(
                option["summary"] == "Candidate summary is withheld in this diagnostic frame."
                and option["diff_excerpt"] == "Candidate source content is withheld in this diagnostic frame."
                for option in frame["action_options"]
            ):
                mismatches.append({"task_id": task_id, "condition": condition, "error": "E_c_not_removed"})
            elif channel == "E_x" and frame["evidence"][0] == base["evidence"][0]:
                mismatches.append({"task_id": task_id, "condition": condition, "error": "E_x_not_removed"})
            elif channel == "E_r" and frame["evidence"][1] == base["evidence"][1]:
                mismatches.append({"task_id": task_id, "condition": condition, "error": "E_r_not_removed"})
    return {"checked_tasks": len({task for task, _ in by_task}), "condition_cells": checked, "mismatches": mismatches}


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite {OUTPUT}")
    source = read_json(SOURCE)
    checks = read_json(CHECKS)
    frames = read_json(FRAMES)["frames"]
    truth = read_json(TRUTH)
    if source.get("model_contact_authorized") is not False or checks.get("model_contact_authorized") is not False:
        raise SystemExit("unexpected model-contact authorization marker")
    tasks = source["tasks_hidden"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        groups[str(task["pair_id"])].append(task)
    pairs = pair_rows(tasks, groups)
    frame_checks = frame_seal_checks(frames, truth)
    passed = sum(bool(row["paired_twin_pass"]) for row in pairs)
    result = {
        "schema_version": 1,
        "state": "PAIRED_TRUTH_AUDIT_COMPLETE_NO_MODEL_CONTACT",
        "model_contact_authorized": False,
        "task_count": len(tasks),
        "pair_group_count": len(pairs),
        "paired_truth_groups_passed": passed,
        "paired_truth_groups_failed": len(pairs) - passed,
        "paired_truth_groups": pairs,
        "leave_one_out_frame_preservation": frame_checks,
        "input_hashes": {
            "task_source_sha256": sha256(SOURCE),
            "candidate_labels_sha256": sha256(CHECKS),
            "observer_frames_sha256": sha256(FRAMES),
            "truth_index_sha256": sha256(TRUTH),
        },
        "interpretation_boundary": "precontact bank-construction diagnostic; no model outputs or tuning",
    }
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "state": result["state"],
        "groups": len(pairs),
        "passed": passed,
        "failed": len(pairs) - passed,
        "output": str(OUTPUT),
    }, indent=2))


if __name__ == "__main__":
    main()

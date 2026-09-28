from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-a14"
SOURCE = BANK / "vault" / "task-source-fixtures-final-v3.json"
CHECKS = BANK / "vault" / "candidate-check-labels-final-v3.json"
FRAMES = BANK / "observer-frames.json"
TRUTH = BANK / "vault" / "frame-truth-index.json"
RECEIPTS = BANK / "vault" / "presentation-receipts.json"
OUTPUT = BANK / "vault" / "paired-truth-audit-a16-v1.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_content_by_id(task: dict[str, Any]) -> tuple[tuple[int, str, str, str], ...]:
    return tuple(sorted(
        (
            int(option["action"]["id"]), str(option["patch_sha256"]),
            str(option["summary"]), str(option["diff_excerpt"]),
        )
        for option in task["candidate_options_hidden"]
    ))


def order_ids(task: dict[str, Any]) -> tuple[int, ...]:
    return tuple(int(value) for value in task["producer_order_action_ids_hidden"])


def signatures(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "E_t": str(task["request_text_authentic"]),
        "E_c.content": candidate_content_by_id(task),
        "E_x": str(task["execution_text_authentic"]),
        "E_r": (
            str(task["repository_id_hidden"]), str(task["repository_code"]),
            str(task["repository_revision"]), str(task["snapshot_sha256"]),
            str(task["task_family_code"]), json.dumps(task["context_authentic"], sort_keys=True),
        ),
        "E_p": order_ids(task),
        "presentation_task_id": str(task["observer_task_id_hidden"]),
        "task_variant": int(task["task_variant"]),
    }


def diff_fields(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    a, b = signatures(left), signatures(right)
    return [key for key in a if a[key] != b[key]]


def valid_ids_from_checks(checks: dict[str, Any]) -> dict[str, set[int]]:
    values: dict[str, set[int]] = defaultdict(set)
    for row in checks["candidate_rows"]:
        if row["task_candidate_passed"]:
            values[str(row["task_id"])].add(int(row["action_id_hidden"]))
        else:
            values[str(row["task_id"])]
    return values


def test_suite_signature(task_id: str, checks: dict[str, Any]) -> tuple[Any, ...]:
    rows = [row for row in checks["candidate_rows"] if str(row["task_id"]) == task_id]
    if not rows:
        return ()
    return tuple(sorted({
        (
            tuple(sorted(str(item["case_id"]) for item in row["check_cases"])),
            str(row["overlay_test_sha256"]),
        ) for row in rows
    }))


def audit_pair(members: list[dict[str, Any]], valid_ids: dict[str, set[int]], checks: dict[str, Any]) -> dict[str, Any]:
    members = sorted(members, key=lambda task: int(task["within_family_index"]))
    pair_id = str(members[0]["pair_id"])
    family = str(members[0]["family_name_hidden"])
    changes = {str(task["counterfactual_change_channel_hidden"]) for task in members}
    if changes == {"none"}:
        all_abstain = all(not valid_ids[str(task["task_id"])] for task in members)
        return {
            "pair_id": pair_id, "family": family, "kind": "abstention_control",
            "applicable": False, "all_candidates_fail": all_abstain,
            "pass": all_abstain,
        }
    if len(members) == 2 and len(changes) == 1:
        target = next(iter(changes))
        if target not in {"E_t", "E_c.content", "E_x", "E_r"}:
            return {"pair_id": pair_id, "family": family, "kind": "invalid", "pass": False, "errors": ["unknown_single_channel_target"]}
        left, right = members
        changed = diff_fields(left, right)
        left_valid, right_valid = valid_ids[str(left["task_id"])], valid_ids[str(right["task_id"])]
        errors = []
        if changed != [target]:
            errors.append("observer_visible_channel_delta_not_isolated")
        if left_valid == right_valid:
            errors.append("executable_valid_action_ids_do_not_change")
        if target == "E_c.content":
            if test_suite_signature(str(left["task_id"]), checks) != test_suite_signature(str(right["task_id"]), checks):
                errors.append("candidate_content_twins_use_different_test_suites")
        else:
            a, b = signatures(left), signatures(right)
            if a["E_c.content"] != b["E_c.content"]:
                errors.append("candidate_content_changed_outside_declared_channel")
        return {
            "pair_id": pair_id, "family": family, "kind": "single_channel_counterfactual",
            "target": target,
            "task_ids": [str(left["task_id"]), str(right["task_id"])],
            "presentation_task_ids": [str(left["observer_task_id_hidden"]), str(right["observer_task_id_hidden"])],
            "changed_fields": changed,
            "valid_action_ids": [sorted(left_valid), sorted(right_valid)],
            "test_suites_equal": test_suite_signature(str(left["task_id"]), checks) == test_suite_signature(str(right["task_id"]), checks),
            "pass": not errors,
            "errors": errors,
        }
    if len(members) == 4 and changes == {"E_t+E_x"}:
        by_channels = {
            (str(task["request_text_authentic"]), str(task["execution_text_authentic"])): task
            for task in members
        }
        request_values = sorted({key[0] for key in by_channels})
        execution_values = sorted({key[1] for key in by_channels})
        errors = []
        if len(request_values) != 2 or len(execution_values) != 2 or len(by_channels) != 4:
            errors.append("incomplete_visible_E_t_by_E_x_factorial")
        else:
            pair_results = []
            for varying in ("E_t", "E_x"):
                fixed_values = execution_values if varying == "E_t" else request_values
                for fixed_index, fixed in enumerate(fixed_values):
                    if varying == "E_t":
                        a, b = by_channels[(request_values[0], fixed)], by_channels[(request_values[1], fixed)]
                    else:
                        a, b = by_channels[(fixed, execution_values[0])], by_channels[(fixed, execution_values[1])]
                    changed = diff_fields(a, b)
                    valid_changed = valid_ids[str(a["task_id"])] != valid_ids[str(b["task_id"])]
                    pair_ok = changed == [varying] and valid_changed
                    pair_results.append({
                        "varying_channel": varying,
                        "fixed_factor": fixed_index,
                        "task_ids": [str(a["task_id"]), str(b["task_id"])],
                        "changed_fields": changed,
                        "valid_action_ids": [sorted(valid_ids[str(a["task_id"])]), sorted(valid_ids[str(b["task_id"])])],
                        "pass": pair_ok,
                    })
                    if not pair_ok:
                        errors.append(f"factor_pair_failed:{varying}:{fixed_index}")
            common = [by_channels[(request, execution)] for request in request_values for execution in execution_values]
            invariant_keys = ("E_c.content", "E_r", "E_p", "presentation_task_id", "task_variant")
            for key in invariant_keys:
                if len({json.dumps(signatures(task)[key], sort_keys=True) for task in common}) != 1:
                    errors.append(f"factorial_invariant_failed:{key}")
            return {
                "pair_id": pair_id, "family": family, "kind": "two_by_two_joint_counterfactual",
                "applicable": True, "factor_pairs": pair_results,
                "pass": not errors, "errors": errors,
            }
        return {"pair_id": pair_id, "family": family, "kind": "two_by_two_joint_counterfactual", "pass": False, "errors": errors}
    return {
        "pair_id": pair_id, "family": family, "kind": "invalid",
        "pass": False, "errors": ["unexpected_pair_size_or_mixed_channel_contract"],
    }


def audit_projection(source: dict[str, Any], frames: list[dict[str, Any]], truth: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    source_by_id = {str(task["task_id"]): task for task in source["tasks_hidden"]}
    errors = []
    visible_ids = set()
    for index, (frame, entry, receipt) in enumerate(zip(frames, truth, receipts, strict=True)):
        task_id = str(entry["task_id"])
        task = source_by_id.get(task_id)
        if task is None:
            errors.append(f"truth_index_unknown_internal_task_id:{index}")
            continue
        expected_visible = str(task["observer_task_id_hidden"])
        visible_ids.add(expected_visible)
        condition = str(entry["condition"])
        if entry.get("presentation_task_id") != expected_visible:
            errors.append(f"truth_index_presentation_task_id_mismatch:{index}")
        if frame.get("task_id") != expected_visible or receipt.get("task_id") != expected_visible:
            errors.append(f"public_presentation_task_id_mismatch:{index}")
        if receipt.get("condition") != condition:
            errors.append(f"receipt_condition_mismatch:{index}")
        observed = [int(option["action"]["id"]) for option in frame["action_options"]]
        if receipt.get("ordered_action_ids") != observed:
            errors.append(f"receipt_sequence_mismatch:{index}")
        if condition == "E_p_balanced_coordinate_control":
            expected = [int(value) for value in task["coordinate_control_action_ids_hidden"]]
        elif condition == "E_p_isomorphic_donor_coordinate":
            donor_id = str(entry.get("coordinate_donor_task_id_hidden"))
            donor = source_by_id.get(donor_id)
            if donor is None:
                errors.append(f"coordinate_donor_missing:{index}")
                continue
            donor_role_by_id = {int(key): value for key, value in donor["candidate_role_by_action_id_hidden"].items()}
            recipient_id_by_role = {value: int(key) for key, value in task["candidate_role_by_action_id_hidden"].items()}
            donor_roles = [donor_role_by_id[int(value)] for value in donor["producer_order_action_ids_hidden"]]
            expected = [recipient_id_by_role[role] for role in donor_roles]
        else:
            expected = [int(value) for value in task["producer_order_action_ids_hidden"]]
        if observed != expected:
            errors.append(f"frame_order_mismatch:{index}")
    return {
        "frame_count": len(frames),
        "receipt_count": len(receipts),
        "unique_presentation_task_ids": len(visible_ids),
        "errors": errors,
        "pass": not errors and len(frames) == len(truth) == len(receipts) == 1248,
    }


def verify_audit_lock() -> None:
    lock_path = ROOT / "bank" / "construction-01" / "paired-truth-audit-lock-a16-v1.json"
    if not lock_path.is_file():
        raise SystemExit("A15 paired-truth audit lock is missing")
    lock = read_json(lock_path)
    if lock.get("state") != "FROZEN_BEFORE_A16_PAIRED_AUDIT" or lock.get("model_contact_authorized") is not False:
        raise SystemExit("A15 paired-truth audit lock state is invalid")
    if lock.get("audit_sha256") != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise SystemExit("A15 paired-truth audit script drifted after lock")
    for item in lock["files"]:
        path = ROOT / Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise SystemExit(f"A15 paired-truth audit input drift: {item['path']}")


def main() -> None:
    verify_audit_lock()
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite {OUTPUT}")
    source = read_json(SOURCE)
    checks = read_json(CHECKS)
    frames = read_json(FRAMES)["frames"]
    truth = read_json(TRUTH)
    receipts = read_json(RECEIPTS)
    if any(document.get("model_contact_authorized") is not False for document in (source, checks)):
        raise SystemExit("unexpected model-contact authorization marker")
    valid_ids = valid_ids_from_checks(checks)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in source["tasks_hidden"]:
        groups[str(task["pair_id"])].append(task)
    pair_results = [audit_pair(members, valid_ids, checks) for _, members in sorted(groups.items())]
    projection = audit_projection(source, frames, truth, receipts)
    passed = sum(bool(row["pass"]) for row in pair_results)
    report = {
        "schema_version": 1,
        "state": "A16_PAIRED_TRUTH_AUDIT_PASS_NO_MODEL_CONTACT" if passed == len(pair_results) and projection["pass"] else "A16_PAIRED_TRUTH_AUDIT_FAIL_REQUIRES_REPAIR",
        "model_contact_authorized": False,
        "task_count": len(source["tasks_hidden"]),
        "pair_group_count": len(pair_results),
        "pair_groups_passed": passed,
        "pair_groups_failed": len(pair_results) - passed,
        "pair_groups": pair_results,
        "projection_receipt_audit": projection,
        "input_hashes": {
            "source_sha256": sha256(SOURCE), "labels_sha256": sha256(CHECKS),
            "frames_sha256": sha256(FRAMES), "truth_index_sha256": sha256(TRUTH),
            "receipts_sha256": sha256(RECEIPTS),
        },
        "interpretation_boundary": "precontact construction qualification; no observer outputs or tuning",
    }
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "state": report["state"], "pair_groups": len(pair_results),
        "passed": passed, "failed": len(pair_results) - passed,
        "projection_receipts_pass": projection["pass"], "output": str(OUTPUT),
    }, indent=2))


if __name__ == "__main__":
    main()

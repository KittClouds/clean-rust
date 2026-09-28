from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
SOURCE = BANK / "vault" / "task-source-fixtures-final-v1.json"
CHECKS = BANK / "vault" / "candidate-check-labels-final-v1.json"
FRAMES = BANK / "observer-frames.json"
TRUTH = BANK / "vault" / "frame-truth-index.json"
RECEIPTS = BANK / "vault" / "presentation-receipts.json"
OUTPUT = BANK / "vault" / "precontact-audit-v1.json"
PRESENTER = Path(r"D:\rdc-e012-target\runtime-integration\release\e011-presentation.exe")
BLAKE3 = Path(r"D:\rdc-e012-target\runtime-integration\release\e011-hash.exe")

SENTINELS = {
    "E_t": "Task/request evidence is withheld in this diagnostic frame.",
    "E_c.summary": "Candidate summary is withheld in this diagnostic frame.",
    "E_c.diff": "Candidate source content is withheld in this diagnostic frame.",
    "E_x": "No task-relevant pre-action execution evidence is available.",
    "E_r": "No task-specific repository context is available.",
}
MASKS = {
    "E_c_only": {"E_c.content"},
    "E_t_only_diagnostic": {"E_t"},
    "E_x_only_diagnostic": {"E_x"},
    "E_r_only_diagnostic": {"E_r"},
    "E_t_plus_E_c": {"E_t", "E_c.content"},
    "E_c_plus_E_x": {"E_c.content", "E_x"},
    "E_c_plus_E_r": {"E_c.content", "E_r"},
    "E_t_plus_E_x_diagnostic": {"E_t", "E_x"},
    "E_t_plus_E_c_plus_E_x": {"E_t", "E_c.content", "E_x"},
    "E_t_plus_E_c_plus_E_r": {"E_t", "E_c.content", "E_r"},
}
FRAME_KEYS = {
    "schema_id", "task_id", "task_family", "repository_id", "task_variant",
    "task_prompt", "repository_revision", "snapshot_sha256", "evidence", "action_options",
}
FORBIDDEN_KEYS = {
    "condition", "condition_id", "donor_id", "donor_task_id", "gold", "label", "truth",
    "role", "candidate_role", "expected_valid_action_ids", "primary_gold_action_id",
    "family_name_hidden", "truth_support_hidden", "direct_decision_hidden",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blake3_text(text: str) -> str:
    result = subprocess.run([str(BLAKE3), "--stdin"], input=text.encode("utf-8"), capture_output=True, check=True)
    return result.stdout.decode("ascii").strip()


def fail(message: str) -> None:
    raise ValueError(message)


def forbidden_keys(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_KEYS or key.lower().endswith("_hidden"):
                found.append(f"{path}.{key}")
            found.extend(forbidden_keys(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(forbidden_keys(child, f"{path}[{index}]"))
    return found


def channel_content(frame: dict[str, Any], channel: str) -> Any:
    if channel == "E_t":
        return frame["task_prompt"]
    if channel == "E_c.content":
        return {
            int(option["action"]["id"]): (option["summary"], option["diff_excerpt"])
            for option in frame["action_options"]
        }
    if channel == "E_x":
        return frame["evidence"][0]
    if channel == "E_r":
        return (
            frame["repository_id"], frame["repository_revision"], frame["snapshot_sha256"],
            frame["task_family"], frame["evidence"][1],
        )
    raise ValueError(channel)


def set_absent(frame: dict[str, Any], channel: str) -> None:
    if channel == "E_t":
        frame["task_prompt"] = SENTINELS["E_t"]
    elif channel == "E_c.content":
        for option in frame["action_options"]:
            option["summary"] = SENTINELS["E_c.summary"]
            option["diff_excerpt"] = SENTINELS["E_c.diff"]
    elif channel == "E_x":
        frame["evidence"][0]["content"] = SENTINELS["E_x"]
        frame["evidence"][0]["content_blake3"] = blake3_text(SENTINELS["E_x"])
    elif channel == "E_r":
        frame["repository_id"] = "context-withheld"
        frame["repository_revision"] = "context-withheld"
        frame["snapshot_sha256"] = "context-withheld"
        frame["task_family"] = "family-context-withheld"
        frame["evidence"][1]["content"] = SENTINELS["E_r"]
        frame["evidence"][1]["content_blake3"] = blake3_text(SENTINELS["E_r"])
    else:
        raise ValueError(channel)


def restore_channel(actual: dict[str, Any], base: dict[str, Any], channel: str) -> None:
    if channel == "E_t":
        actual["task_prompt"] = base["task_prompt"]
    elif channel == "E_c.content":
        base_by_id = {int(item["action"]["id"]): item for item in base["action_options"]}
        for option in actual["action_options"]:
            original = base_by_id[int(option["action"]["id"])]
            option["summary"] = original["summary"]
            option["diff_excerpt"] = original["diff_excerpt"]
    elif channel == "E_x":
        actual["evidence"][0] = copy.deepcopy(base["evidence"][0])
    elif channel == "E_r":
        for key in ("repository_id", "repository_revision", "snapshot_sha256", "task_family"):
            actual[key] = base[key]
        actual["evidence"][1] = copy.deepcopy(base["evidence"][1])
    else:
        raise ValueError(channel)


def assert_only_channel_changed(actual: dict[str, Any], base: dict[str, Any], channel: str, label: str) -> None:
    normalized = copy.deepcopy(actual)
    restore_channel(normalized, base, channel)
    if normalized != base:
        fail(f"{label} changed content outside {channel}")


def role_transfer_order(recipient: dict[str, Any], donor: dict[str, Any]) -> list[int]:
    donor_role_by_id = {int(key): value for key, value in donor["candidate_role_by_action_id_hidden"].items()}
    recipient_id_by_role = {value: int(key) for key, value in recipient["candidate_role_by_action_id_hidden"].items()}
    donor_ids = donor["producer_order_action_ids_hidden"]
    roles = [donor_role_by_id[int(action_id)] for action_id in donor_ids]
    if set(roles) != set(recipient_id_by_role):
        fail(f"nonisomorphic coordinate donor {recipient['task_id']} <- {donor['task_id']}")
    return [recipient_id_by_role[role] for role in roles]


def replay_receipt(frame: dict[str, Any], expected: dict[str, Any], temp: Path, index: int) -> None:
    digest = sha256(compact(frame))
    request = {
        "task_digest_hex": digest,
        "options": [
            {"producer_ordinal": ordinal, **option}
            for ordinal, option in enumerate(frame["action_options"])
        ],
    }
    input_path = temp / f"replay-{index:04d}-in.json"
    output_path = temp / f"replay-{index:04d}-out.json"
    input_path.write_bytes(compact(request))
    result = subprocess.run([str(PRESENTER), str(input_path), str(output_path)], capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"presenter replay failed for {index}: {result.stderr}")
    presented = read_json(output_path)
    checks = {
        "task_digest_hex": presented["task_digest_hex"],
        "request_id_hex": presented["request_id_hex"],
        "receipt_hex": presented["receipt_hex"],
        "receipt_digest_hex": presented["receipt_digest_hex"],
        "frame_sha256": digest,
        "ordered_action_ids": [option["action"]["id"] for option in presented["ordered_options"]],
    }
    if checks != {key: expected[key] for key in checks}:
        fail(f"presentation receipt replay identity mismatch for frame {index}")


def main() -> None:
    source = read_json(SOURCE)
    checks = read_json(CHECKS)
    frames = read_json(FRAMES)["frames"]
    truth = read_json(TRUTH)
    receipts = read_json(RECEIPTS)
    if source.get("model_contact_authorized") is not False or checks.get("model_contact_authorized") is not False:
        fail("unexpected model-contact authorization marker")
    if checks.get("state") != "CANDIDATE_CHECKS_COMPLETE_NO_MODEL_CONTACT":
        fail("candidate checks are incomplete")
    if len(source["tasks_hidden"]) != 48 or len(frames) != 1248 or len(truth) != 1248 or len(receipts) != 1248:
        fail("task, frame, truth-index, or receipt count mismatch")
    if not PRESENTER.exists():
        fail("E011 presentation runtime is unavailable")

    tasks = {task["task_id"]: task for task in source["tasks_hidden"]}
    if len(tasks) != 48:
        fail("duplicate task IDs")
    checks_by_task: dict[str, set[int]] = defaultdict(set)
    for row in checks["candidate_rows"]:
        if row["task_candidate_passed"]:
            checks_by_task[row["task_id"]].add(int(row["action_id_hidden"]))
    for task_id, task in tasks.items():
        observed = sorted(checks_by_task[task_id])
        expected = sorted(int(value) for value in task["expected_valid_action_ids_hidden"])
        if observed != expected:
            fail(f"executable check labels differ from locked task source for {task_id}: {observed} != {expected}")

    family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    id_valid_counts: dict[str, Counter[int]] = defaultdict(Counter)
    for task in tasks.values():
        family = task["family_name_hidden"]
        family_rows[family].append(task)
        option_ids = [int(item["action"]["id"]) for item in task["candidate_options_hidden"]]
        if option_ids != [int(value) for value in task["producer_order_action_ids_hidden"]]:
            fail(f"source option sequence differs from producer order for {task['task_id']}")
        if len(option_ids) != 4 or len(set(option_ids)) != 4:
            fail(f"candidate IDs are not four unique options for {task['task_id']}")
        for action_id in option_ids:
            if action_id in task["expected_valid_action_ids_hidden"]:
                id_valid_counts[family][action_id] += 1

    family_position_report: dict[str, Any] = {}
    for family, members in family_rows.items():
        members.sort(key=lambda item: int(item["within_family_index"]))
        if len(members) != 4:
            fail(f"family size is not four: {family}")
        ids = {int(option["action"]["id"]) for option in members[0]["candidate_options_hidden"]}
        for schedule_key in ("producer_order_action_ids_hidden", "coordinate_control_action_ids_hidden"):
            schedule = [member[schedule_key] for member in members]
            for position in range(4):
                if {int(row[position]) for row in schedule} != ids:
                    fail(f"{schedule_key} is not Latin in {family}, position {position}")
            valid_by_position = [
                sum(int(row[position]) in member["expected_valid_action_ids_hidden"] for row, member in zip(schedule, members, strict=True))
                for position in range(4)
            ]
            if schedule_key == "producer_order_action_ids_hidden" and any(
                count in {0, 4} for count in valid_by_position
            ) and any(member["expected_valid_action_ids_hidden"] for member in members):
                fail(f"candidate position perfectly predicts action validity in {family}: {valid_by_position}")
            if schedule_key == "coordinate_control_action_ids_hidden":
                producer_counts = [
                    sum(int(row[position]) in member["expected_valid_action_ids_hidden"] for row, member in zip(
                        [m["producer_order_action_ids_hidden"] for m in members], members, strict=True
                    ))
                    for position in range(4)
                ]
                if valid_by_position != list(reversed(producer_counts)):
                    fail(f"reverse coordinate control did not mirror position validity counts in {family}")
        gold_positions = [
            member["producer_order_action_ids_hidden"].index(member["primary_gold_action_id_hidden"])
            for member in members if member["primary_gold_action_id_hidden"] is not None
        ]
        if gold_positions and Counter(gold_positions) != Counter(range(4)):
            fail(f"primary gold action positions are not balanced in {family}: {gold_positions}")
        if any(member["expected_valid_action_ids_hidden"] for member in members):
            counts = id_valid_counts[family]
            for action_id in ids:
                if counts[action_id] in {0, 4}:
                    fail(f"action ID perfectly predicts validity in {family}: {action_id} count={counts[action_id]}")
        family_position_report[family] = {
            "valid_action_count_by_producer_position": [
                sum(int(row[position]) in member["expected_valid_action_ids_hidden"] for row, member in zip(
                    [m["producer_order_action_ids_hidden"] for m in members], members, strict=True
                )) for position in range(4)
            ],
            "valid_action_count_by_action_id": {str(key): value for key, value in sorted(id_valid_counts[family].items())},
            "primary_gold_positions": gold_positions,
        }

    frame_by_task_condition: dict[tuple[str, str], dict[str, Any]] = {}
    index_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for position, (frame, entry, receipt) in enumerate(zip(frames, truth, receipts, strict=True)):
        key = (entry["task_id"], entry["condition"])
        if key in frame_by_task_condition:
            fail(f"duplicate task condition {key}")
        if entry["task_id"] != receipt["task_id"] or entry["condition"] != receipt["condition"]:
            fail(f"receipt/index alignment failed at frame {position}")
        if set(frame) != FRAME_KEYS:
            fail(f"observer frame keys drifted at {key}: {sorted(set(frame) ^ FRAME_KEYS)}")
        hidden = forbidden_keys(frame)
        if hidden:
            fail(f"sealed fields leaked to observer frame at {key}: {hidden[:4]}")
        if len(frame["action_options"]) != 4:
            fail(f"observer frame candidate count drifted at {key}")
        ids = [int(option["action"]["id"]) for option in frame["action_options"]]
        if len(set(ids)) != 4 or ids != receipt["ordered_action_ids"]:
            fail(f"presentation sequence mismatch at {key}")
        for option in frame["action_options"]:
            if set(option) != {"action", "summary", "diff_excerpt", "patch_sha256"}:
                fail(f"candidate option schema drifted at {key}")
            if set(option["action"]) != {"id", "schema_id"}:
                fail(f"action identity schema drifted at {key}")
        frame_digest = sha256(compact(frame))
        if frame_digest != entry["frame_sha256"] or frame_digest != receipt["frame_sha256"]:
            fail(f"frame digest mismatch at {key}")
        if receipt["ordered_action_ids"] != ids:
            fail(f"receipt sequence mismatch at {key}")
        frame_by_task_condition[key] = frame
        index_by_key[key] = entry

    conditions = {entry["condition"] for entry in truth}
    if len(conditions) != 26:
        fail(f"expected 26 distinct conditions, got {len(conditions)}")
    base_by_task = {task_id: frame_by_task_condition[(task_id, "full_frame")] for task_id in tasks}
    truth_by_key = {(entry["task_id"], entry["condition"]): entry for entry in truth}

    for task_id, task in tasks.items():
        task_conditions = {condition for row_task, condition in frame_by_task_condition if row_task == task_id}
        if len(task_conditions) != 26:
            fail(f"task does not have 26 conditions: {task_id}")
        base = base_by_task[task_id]
        base_by_id = {int(option["action"]["id"]): option for option in base["action_options"]}
        expected_absent = {
            "leave_out_E_t": {"E_t"},
            "leave_out_E_c": {"E_c.content"},
            "leave_out_E_x": {"E_x"},
            "leave_out_E_r": {"E_r"},
            **{name: {"E_t", "E_c.content", "E_x", "E_r"} - active for name, active in MASKS.items()},
            "identity_only_diagnostic": {"E_t", "E_c.content", "E_x", "E_r"},
        }
        for condition, absent_channels in expected_absent.items():
            actual = frame_by_task_condition[(task_id, condition)]
            expected = copy.deepcopy(base)
            for channel in absent_channels:
                set_absent(expected, channel)
            if actual != expected:
                fail(f"condition {condition} has an undeclared frame change for {task_id}")
        for condition, channel in (
            ("control_E_t", "E_t"), ("control_E_c_content", "E_c.content"),
            ("control_E_x", "E_x"), ("control_E_r", "E_r"),
        ):
            current = frame_by_task_condition[(task_id, condition)]
            assert_only_channel_changed(current, base, channel, f"{condition}/{task_id}")
        for condition, channel in (
            ("swap_E_t", "E_t"), ("swap_E_c_content", "E_c.content"),
            ("swap_E_x", "E_x"), ("swap_E_r", "E_r"),
        ):
            current = frame_by_task_condition[(task_id, condition)]
            assert_only_channel_changed(current, base, channel, f"{condition}/{task_id}")
            entry = truth_by_key[(task_id, condition)]
            donor = frame_by_task_condition[(entry["swap_donor_task_id_hidden"], "full_frame")]
            if channel_content(current, channel) != channel_content(donor, channel):
                fail(f"swap payload is not the declared donor channel for {condition}/{task_id}")
        control = frame_by_task_condition[(task_id, "E_p_balanced_coordinate_control")]
        donor_coord = frame_by_task_condition[(task_id, "E_p_isomorphic_donor_coordinate")]
        for candidate_frame, condition in ((control, "E_p_balanced_coordinate_control"), (donor_coord, "E_p_isomorphic_donor_coordinate")):
            candidate_by_id = {int(option["action"]["id"]): option for option in candidate_frame["action_options"]}
            if {key: {k: v for k, v in value.items() if k != "action"} for key, value in candidate_by_id.items()} != {
                key: {k: v for k, v in value.items() if k != "action"} for key, value in base_by_id.items()
            }:
                fail(f"coordinate condition altered candidate content for {task_id}/{condition}")
        coordinate_entry = truth_by_key[(task_id, "E_p_isomorphic_donor_coordinate")]
        donor_task = tasks[coordinate_entry["coordinate_donor_task_id_hidden"]]
        if donor_task["pair_id"] != task["pair_id"] or donor_task["task_id"] == task_id:
            fail(f"coordinate donor escaped pair boundary for {task_id}")
        expected_order = role_transfer_order(task, donor_task)
        observed_order = [int(option["action"]["id"]) for option in donor_coord["action_options"]]
        if observed_order != expected_order:
            fail(f"coordinate donor role order mismatch for {task_id}")
        expected_control_order = [int(value) for value in task["coordinate_control_action_ids_hidden"]]
        observed_control_order = [int(option["action"]["id"]) for option in control["action_options"]]
        if observed_control_order != expected_control_order:
            fail(f"coordinate-control order mismatch for {task_id}")

    replayed = 0
    with tempfile.TemporaryDirectory(prefix="e012-receipt-replay-") as temp_dir:
        temp = Path(temp_dir)
        for index, (frame, receipt) in enumerate(zip(frames, receipts, strict=True), start=1):
            replay_receipt(frame, receipt, temp, index)
            replayed += 1

    result = {
        "schema_version": 1,
        "state": "PRECONTACT_AUDIT_PASS_NO_MODEL_CONTACT",
        "model_contact_authorized": False,
        "task_count": len(tasks),
        "family_count": len(family_rows),
        "repository_count": len({task["repository_id_hidden"] for task in tasks.values()}),
        "condition_count": len(conditions),
        "frame_count": len(frames),
        "presentation_receipt_replays": replayed,
        "candidate_position_and_id_leakage_diagnostics": family_position_report,
        "observer_frame_schema": "PASS",
        "sealed_field_scan": "PASS",
        "task_condition_projection": "PASS",
        "pair_local_donors": "PASS",
        "presentation_replay_identity": "PASS",
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

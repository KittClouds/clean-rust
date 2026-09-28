from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
BANK = CONSTRUCTION / "scored-bank-a14"
SOURCE_FIXTURES = BANK / "vault" / "task-source-fixtures-final-v3.json"
CHECKS = BANK / "vault" / "candidate-check-labels-final-v3.json"
OUTPUT_FRAMES = BANK / "observer-frames.json"
OUTPUT_INDEX = BANK / "vault" / "frame-truth-index.json"
OUTPUT_RECEIPTS = BANK / "vault" / "presentation-receipts.json"
PRESENTER = Path(r"D:\rdc-e012-target\runtime-integration\release\e011-presentation.exe")
BLAKE3 = Path(r"D:\rdc-e012-target\runtime-integration\release\e011-hash.exe")
TRUTH_CHANNELS = ("E_t", "E_c.content", "E_x", "E_r")
SENTINELS = {
    "E_t": "Task/request evidence is withheld in this diagnostic frame.",
    "E_c.summary": "Candidate summary is withheld in this diagnostic frame.",
    "E_c.diff": "Candidate source content is withheld in this diagnostic frame.",
    "E_x": "No task-relevant pre-action execution evidence is available.",
    "E_r": "No task-specific repository context is available.",
}
MASK_CONDITIONS = [
    ("E_c_only", {"E_c.content"}),
    ("E_t_only_diagnostic", {"E_t"}),
    ("E_x_only_diagnostic", {"E_x"}),
    ("E_r_only_diagnostic", {"E_r"}),
    ("E_t_plus_E_c", {"E_t", "E_c.content"}),
    ("E_c_plus_E_x", {"E_c.content", "E_x"}),
    ("E_c_plus_E_r", {"E_c.content", "E_r"}),
    ("E_t_plus_E_x_diagnostic", {"E_t", "E_x"}),
    ("E_t_plus_E_c_plus_E_x", {"E_t", "E_c.content", "E_x"}),
    ("E_t_plus_E_c_plus_E_r", {"E_t", "E_c.content", "E_r"}),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def blake3_text(text: str, cache: dict[str, str]) -> str:
    if text not in cache:
        result = subprocess.run([str(BLAKE3), "--stdin"], input=text.encode("utf-8"), capture_output=True, check=True)
        cache[text] = result.stdout.decode("ascii").strip()
    return cache[text]


def evidence(kind: str, source_id: str, content: str, cache: dict[str, str]) -> dict[str, str]:
    return {"kind": kind, "source_id": source_id, "content_blake3": blake3_text(content, cache), "content": content}


def neutral_of_length(size: int) -> str:
    return "." * max(1, size)


def producer_ids(task: dict[str, Any]) -> list[int]:
    ids = [int(value) for value in task["producer_order_action_ids_hidden"]]
    option_ids = [int(option["action"]["id"]) for option in task["candidate_options_hidden"]]
    if ids != option_ids:
        raise ValueError(f"candidate options do not preserve the locked producer sequence for {task['task_id']}")
    return ids


def make_authentic_options(task: dict[str, Any], order: list[int]) -> list[dict[str, Any]]:
    by_id = {int(option["action"]["id"]): option for option in task["candidate_options_hidden"]}
    return [
        {
            "action": option["action"],
            "summary": option["summary"],
            "diff_excerpt": option["diff_excerpt"],
            "patch_sha256": option["patch_sha256"],
        }
        for action_id in order
        for option in [by_id[action_id]]
    ]


def transfer_role_order(recipient: dict[str, Any], donor: dict[str, Any]) -> list[int]:
    donor_role_by_id = {int(key): value for key, value in donor["candidate_role_by_action_id_hidden"].items()}
    recipient_id_by_role = {value: int(key) for key, value in recipient["candidate_role_by_action_id_hidden"].items()}
    donor_roles = [donor_role_by_id[action_id] for action_id in producer_ids(donor)]
    if set(donor_roles) != set(recipient_id_by_role):
        raise ValueError(f"candidate role sets are not isomorphic: {recipient['task_id']} <- {donor['task_id']}")
    return [recipient_id_by_role[role] for role in donor_roles]


def channel_signature(task: dict[str, Any], channel: str) -> Any:
    if channel == "E_t":
        return task["request_text_authentic"]
    if channel == "E_c.content":
        by_id = {int(option["action"]["id"]): option for option in task["candidate_options_hidden"]}
        role_by_id = {int(key): value for key, value in task["candidate_role_by_action_id_hidden"].items()}
        return tuple(sorted(
            (role_by_id[action_id], by_id[action_id]["summary"], by_id[action_id]["diff_excerpt"])
            for action_id in by_id
        ))
    if channel == "E_x":
        return task["execution_text_authentic"]
    if channel == "E_r":
        return (
            task["repository_code"], task["repository_revision"], task["snapshot_sha256"],
            task["task_family_code"], json.dumps(task["context_authentic"], sort_keys=True),
        )
    raise ValueError(channel)


def select_pair_donors(tasks: list[dict[str, Any]]) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        by_pair.setdefault(task["pair_id"], []).append(task)
    for members in by_pair.values():
        members.sort(key=lambda item: int(item["within_family_index"]))
        if len(members) < 2:
            raise ValueError(f"pair has no nonself donor: {members[0]['pair_id']}")
    channel_donors: dict[str, dict[str, dict[str, Any]]] = {}
    coordinate_donors: dict[str, dict[str, Any]] = {}
    for pair_id, members in by_pair.items():
        for task in members:
            task_id = task["task_id"]
            next_member = members[(members.index(task) + 1) % len(members)]
            coordinate_donors[task_id] = next_member
            channel_donors[task_id] = {}
            for channel in TRUTH_CHANNELS:
                current = channel_signature(task, channel)
                candidates = [member for member in members if member["task_id"] != task_id]
                scored = []
                for candidate in candidates:
                    differs = channel_signature(candidate, channel) != current
                    other_differences = sum(
                        channel_signature(candidate, other) != channel_signature(task, other)
                        for other in TRUTH_CHANNELS if other != channel
                    )
                    cyclic_distance = (int(candidate["within_family_index"]) - int(task["within_family_index"])) % 4
                    scored.append((not differs, other_differences, cyclic_distance, candidate["task_id"], candidate))
                channel_donors[task_id][channel] = min(scored, key=lambda row: row[:4])[-1]
            if any(donor["pair_id"] != pair_id or donor["task_id"] == task_id for donor in channel_donors[task_id].values()):
                raise ValueError(f"invalid same-pair donor selection for {task_id}")
    return channel_donors, coordinate_donors


def apply_er(
    frame: dict[str, Any], content: str, values: dict[str, Any] | None,
    family_code: str, cache: dict[str, str],
) -> None:
    if values is None:
        frame["repository_id"] = "context-withheld"
        frame["repository_revision"] = "context-withheld"
        frame["snapshot_sha256"] = "context-withheld"
        frame["task_family"] = "family-context-withheld"
    else:
        frame["repository_id"] = values["repository_code"]
        frame["repository_revision"] = values["repository_revision"]
        frame["snapshot_sha256"] = values["snapshot_sha256"]
        frame["task_family"] = family_code
    frame["evidence"][1] = evidence("repository_context", "repository-context", content, cache)


def build_base_frame(
    task: dict[str, Any], order: list[int], cache: dict[str, str],
    et_text: str | None = None, ec_donor: dict[str, Any] | None = None,
    ex_text: str | None = None, er_task: dict[str, Any] | None = None,
    er_content: str | None = None,
) -> dict[str, Any]:
    family_code = task["task_family_code"]
    frame: dict[str, Any] = {
        "schema_id": "rdc-real-coding-observation.v1",
        "task_id": str(task["observer_task_id_hidden"]),
        "task_family": family_code,
        "repository_id": task["repository_code"],
        "task_variant": task["task_variant"],
        "task_prompt": task["request_text_authentic"] if et_text is None else et_text,
        "repository_revision": task["repository_revision"],
        "snapshot_sha256": task["snapshot_sha256"],
        "evidence": [
            evidence("baseline_tool_result", "pre-action-test", task["execution_text_authentic"] if ex_text is None else ex_text, cache),
            evidence("repository_context", "repository-context", json.dumps(task["context_authentic"], sort_keys=True), cache),
        ],
        "action_options": make_authentic_options(task, order),
        "_hash_cache": cache,
    }
    if ec_donor is not None:
        donor_by_id = {int(opt["action"]["id"]): opt for opt in ec_donor["candidate_options_hidden"]}
        for option in frame["action_options"]:
            donor_option = donor_by_id[int(option["action"]["id"])]
            option["summary"] = donor_option["summary"]
            option["diff_excerpt"] = donor_option["diff_excerpt"]
    if er_task is not None:
        apply_er(
            frame,
            er_content if er_content is not None else json.dumps(er_task["context_authentic"], sort_keys=True),
            er_task,
            er_task["task_family_code"],
            cache,
        )
    frame.pop("_hash_cache")
    return frame


def absent_truth_channel(frame: dict[str, Any], channel: str, cache: dict[str, str]) -> None:
    if channel == "E_t":
        frame["task_prompt"] = SENTINELS["E_t"]
    elif channel == "E_c.content":
        for option in frame["action_options"]:
            option["summary"] = SENTINELS["E_c.summary"]
            option["diff_excerpt"] = SENTINELS["E_c.diff"]
    elif channel == "E_x":
        frame["evidence"][0] = evidence("baseline_tool_result", "pre-action-test", SENTINELS["E_x"], cache)
    elif channel == "E_r":
        apply_er(frame, SENTINELS["E_r"], None, "family-context-withheld", cache)
    else:
        raise ValueError(channel)


def control_truth_channel(frame: dict[str, Any], task: dict[str, Any], channel: str, cache: dict[str, str]) -> None:
    if channel == "E_t":
        frame["task_prompt"] = neutral_of_length(len(task["request_text_authentic"].encode("utf-8")))
    elif channel == "E_c.content":
        for option in frame["action_options"]:
            option["summary"] = neutral_of_length(len(option["summary"].encode("utf-8")))
            option["diff_excerpt"] = neutral_of_length(len(option["diff_excerpt"].encode("utf-8")))
    elif channel == "E_x":
        frame["evidence"][0] = evidence(
            "baseline_tool_result", "pre-action-test",
            neutral_of_length(len(task["execution_text_authentic"].encode("utf-8"))), cache,
        )
    elif channel == "E_r":
        current = frame["evidence"][1]["content"]
        control = neutral_of_length(len(current.encode("utf-8")))
        apply_er(frame, control, None, "family-context-control", cache)
        frame["task_family"] = "family-context-control"
    else:
        raise ValueError(channel)


def swap_truth_channel(frame: dict[str, Any], task: dict[str, Any], donor: dict[str, Any], channel: str, cache: dict[str, str]) -> None:
    if channel == "E_t":
        frame["task_prompt"] = donor["request_text_authentic"]
    elif channel == "E_c.content":
        donor_options = {int(opt["action"]["id"]): opt for opt in donor["candidate_options_hidden"]}
        for option in frame["action_options"]:
            donor_option = donor_options[int(option["action"]["id"])]
            option["summary"] = donor_option["summary"]
            option["diff_excerpt"] = donor_option["diff_excerpt"]
    elif channel == "E_x":
        frame["evidence"][0] = evidence("baseline_tool_result", "pre-action-test", donor["execution_text_authentic"], cache)
    elif channel == "E_r":
        apply_er(frame, json.dumps(donor["context_authentic"], sort_keys=True), donor, donor["task_family_code"], cache)
    else:
        raise ValueError(channel)


def frame_for(
    task: dict[str, Any], condition: str, cache: dict[str, str],
    active: set[str] | None = None, replace_channel: str | None = None,
    replace_kind: str | None = None, order: list[int] | None = None,
    donor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_order = order if order is not None else producer_ids(task)
    frame = build_base_frame(task, selected_order, cache)
    if active is not None:
        for channel in TRUTH_CHANNELS:
            if channel not in active:
                absent_truth_channel(frame, channel, cache)
    elif replace_channel is not None and replace_kind is not None:
        if replace_kind == "absent":
            absent_truth_channel(frame, replace_channel, cache)
        elif replace_kind == "control":
            control_truth_channel(frame, task, replace_channel, cache)
        elif replace_kind == "swap":
            if donor is None or donor["task_id"] == task["task_id"] or donor["pair_id"] != task["pair_id"]:
                raise ValueError(f"swap condition lacks a nonself same-pair donor for {task['task_id']} {replace_channel}")
            swap_truth_channel(frame, task, donor, replace_channel, cache)
        else:
            raise ValueError(replace_kind)
    return frame


def ordered_input(frame: dict[str, Any], digest_hex: str) -> dict[str, Any]:
    return {
        "task_digest_hex": digest_hex,
        "options": [
            {"producer_ordinal": index, **option}
            for index, option in enumerate(frame["action_options"])
        ],
    }


def make_receipt(frame: dict[str, Any], temp: Path, counter: int) -> dict[str, Any]:
    frame_bytes = compact_json(frame)
    frame_digest = sha256(frame_bytes)
    input_path = temp / f"present-{counter:04d}-in.json"
    output_path = temp / f"present-{counter:04d}-out.json"
    input_path.write_bytes(compact_json(ordered_input(frame, frame_digest)))
    result = subprocess.run([str(PRESENTER), str(input_path), str(output_path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"E011 presenter failed for frame #{counter}: {result.stderr}")
    presented = json.loads(output_path.read_text(encoding="utf-8"))
    if [option["action"]["id"] for option in presented["ordered_options"]] != [option["action"]["id"] for option in frame["action_options"]]:
        raise RuntimeError(f"presenter changed the declared sequence for frame #{counter}")
    return {
        "task_digest_hex": presented["task_digest_hex"],
        "request_id_hex": presented["request_id_hex"],
        "receipt_hex": presented["receipt_hex"],
        "receipt_digest_hex": presented["receipt_digest_hex"],
        "frame_sha256": frame_digest,
        "ordered_action_ids": [option["action"]["id"] for option in presented["ordered_options"]],
    }


def verify_projection_lock() -> None:
    lock_path = CONSTRUCTION / "frame-projection-lock-a14-v1.json"
    if not lock_path.is_file():
        raise SystemExit("A14 frame-projection lock is missing")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("state") != "FROZEN_BEFORE_A14_FRAME_PROJECTION" or lock.get("model_contact_authorized") is not False:
        raise SystemExit("A14 frame-projection lock state is invalid")
    if lock.get("projector_sha256") != sha256(Path(__file__).read_bytes()):
        raise SystemExit("A14 frame projector drifted after lock")
    for item in lock["files"]:
        path = Path(item["path"]) if str(item["path"]).startswith("external::") else ROOT / Path(item["path"])
        if str(item["path"]).startswith("external::"):
            path = Path(str(item["path"]).removeprefix("external::"))
        if not path.is_file() or sha256(path.read_bytes()) != item["sha256"]:
            raise SystemExit(f"A14 frame-projection input drift: {item['path']}")


def main() -> None:
    verify_projection_lock()
    if any(path.exists() for path in (OUTPUT_FRAMES, OUTPUT_INDEX, OUTPUT_RECEIPTS)):
        raise SystemExit("refusing to overwrite projected frame artifacts")
    if not PRESENTER.exists() or not BLAKE3.exists():
        raise SystemExit("D: release binaries for E011 presentation and BLAKE3 hashing are required")
    source = json.loads(SOURCE_FIXTURES.read_text(encoding="utf-8"))
    checks = json.loads(CHECKS.read_text(encoding="utf-8"))
    if checks["state"] != "CANDIDATE_CHECKS_COMPLETE_NO_MODEL_CONTACT":
        raise SystemExit("candidate check bank is incomplete or contains compile failures")
    checks_by_task: dict[str, set[int]] = {}
    for row in checks["candidate_rows"]:
        if row["task_candidate_passed"]:
            checks_by_task.setdefault(row["task_id"], set()).add(int(row["action_id_hidden"]))
    for task in source["tasks_hidden"]:
        observed = sorted(checks_by_task.get(task["task_id"], set()))
        expected = sorted(task["expected_valid_action_ids_hidden"])
        if observed != expected:
            raise SystemExit(f"scored completion check changed expected set for {task['task_id']}: {observed} != {expected}")
    by_family: dict[str, list[dict[str, Any]]] = {}
    for task in source["tasks_hidden"]:
        by_family.setdefault(task["family_name_hidden"], []).append(task)
    for tasks in by_family.values():
        tasks.sort(key=lambda item: item["within_family_index"])
    all_frames: list[dict[str, Any]] = []
    truth_index: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    hash_cache: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="present-batch-") as temp_dir:
        temp = Path(temp_dir)
        counter = 0
        for family, tasks in sorted(by_family.items()):
            channel_donors, coordinate_donors = select_pair_donors(tasks)
            for task in tasks:
                task_id = task["task_id"]
                coordinate_donor = coordinate_donors[task_id]
                conditions: list[tuple[str, dict[str, Any]]] = []
                conditions.append(("full_frame", frame_for(task, "full_frame", hash_cache)))
                for channel in TRUTH_CHANNELS:
                    name = {"E_t": "leave_out_E_t", "E_c.content": "leave_out_E_c", "E_x": "leave_out_E_x", "E_r": "leave_out_E_r"}[channel]
                    conditions.append((name, frame_for(task, name, hash_cache, active=set(TRUTH_CHANNELS) - {channel})))
                for name, active in MASK_CONDITIONS:
                    conditions.append((name, frame_for(task, name, hash_cache, active=active)))
                for channel in TRUTH_CHANNELS:
                    short = {"E_t": "E_t", "E_c.content": "E_c_content", "E_x": "E_x", "E_r": "E_r"}[channel]
                    conditions.append((f"control_{short}", frame_for(task, f"control_{short}", hash_cache, replace_channel=channel, replace_kind="control")))
                for channel in TRUTH_CHANNELS:
                    short = {"E_t": "E_t", "E_c.content": "E_c_content", "E_x": "E_x", "E_r": "E_r"}[channel]
                    conditions.append((f"swap_{short}", frame_for(
                        task, f"swap_{short}", hash_cache, replace_channel=channel,
                        replace_kind="swap", donor=channel_donors[task_id][channel],
                    )))
                control_order = [int(value) for value in task["coordinate_control_action_ids_hidden"]]
                conditions.append(("E_p_balanced_coordinate_control", frame_for(
                    task, "E_p_balanced_coordinate_control", hash_cache, order=control_order,
                )))
                donor_order = transfer_role_order(task, coordinate_donor)
                conditions.append(("E_p_isomorphic_donor_coordinate", frame_for(
                    task, "E_p_isomorphic_donor_coordinate", hash_cache, order=donor_order,
                )))
                conditions.append(("identity_only_diagnostic", frame_for(task, "identity_only_diagnostic", hash_cache, active=set())))
                if len(conditions) != 26:
                    raise ValueError(f"condition count drifted for {task['task_id']}: {len(conditions)}")
                for condition, frame in conditions:
                    counter += 1
                    receipt = make_receipt(frame, temp, counter)
                    frame_digest = receipt["frame_sha256"]
                    if sha256(compact_json(frame)) != frame_digest:
                        raise ValueError("frame digest changed during presentation")
                    all_frames.append(frame)
                    truth_index.append({
                        "task_id": task["task_id"],
                        "presentation_task_id": frame["task_id"],
                        "condition": condition,
                        "frame_sha256": frame_digest,
                        "family_hidden": family,
                        "repository_hidden": task["repository_id_hidden"],
                        "stratum_hidden": task["stratum_hidden"],
                        "truth_support_hidden": task["truth_support_hidden"],
                        "primary_gold_action_id_hidden": task["primary_gold_action_id_hidden"],
                        "expected_valid_action_ids_hidden": task["expected_valid_action_ids_hidden"],
                        "direct_decision_hidden": task["direct_decision_hidden"],
                        "position_schedule_hidden": [option["action"]["id"] for option in frame["action_options"]],
                        "pair_id_hidden": task["pair_id"],
                        "coordinate_donor_task_id_hidden": coordinate_donor["task_id"],
                        "swap_donor_task_id_hidden": (
                            channel_donors[task_id].get({
                                "swap_E_t": "E_t", "swap_E_c_content": "E_c.content",
                                "swap_E_x": "E_x", "swap_E_r": "E_r",
                            }.get(condition, ""), {}).get("task_id")
                            if condition.startswith("swap_") else None
                        ),
                    })
                    receipts.append({"task_id": frame["task_id"], "condition": condition, **receipt})
    if len(all_frames) != 1248 or len(receipts) != 1248:
        raise ValueError(f"expected 1248 frames and receipts, got {len(all_frames)} and {len(receipts)}")
    OUTPUT_FRAMES.write_text(json.dumps({"frames": all_frames}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_INDEX.write_text(json.dumps(truth_index, indent=2) + "\n", encoding="utf-8")
    OUTPUT_RECEIPTS.write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": "FRAMES_PROJECTED_NO_MODEL_CONTACT", "frames": len(all_frames), "receipts": len(receipts), "unique_blake3_content": len(hash_cache), "output": str(OUTPUT_FRAMES)}, indent=2))


if __name__ == "__main__":
    main()

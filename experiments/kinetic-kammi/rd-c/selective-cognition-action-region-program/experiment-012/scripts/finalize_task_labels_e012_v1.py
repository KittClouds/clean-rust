from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-v1"
RAW_SOURCE = BANK / "vault" / "task-source-fixtures.json"
RAW_CHECKS = BANK / "vault" / "candidate-check-results.json"
TASK_LOCK = ROOT / "bank" / "construction-01" / "task-construction-lock-v1.1.json"
RUN_LOCK = ROOT / "bank" / "construction-01" / "scored-check-run-lock-v1.2.json"
OUTPUT_SOURCE = BANK / "vault" / "task-source-fixtures-final-v1.json"
OUTPUT_CHECKS = BANK / "vault" / "candidate-check-labels-final-v1.json"
OUTPUT_REPORT = BANK / "vault" / "label-finalization-report-v1.json"
BUILDER_PATH = ROOT / "scripts" / "build_task_sources_e012_v1.py"
SPEC = importlib.util.spec_from_file_location("e012_builder", BUILDER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load locked E012 schedule builder")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes())


def map_score(
    mapping_by_task: dict[str, dict[str, int]],
    tasks: list[dict[str, Any]],
    passing_roles_by_task: dict[str, set[str]],
    action_ids: list[int],
) -> tuple[int, int, int, str]:
    counts = Counter({action_id: 0 for action_id in action_ids})
    for task in tasks:
        role_map = mapping_by_task[task["task_id"]]
        for role in passing_roles_by_task[task["task_id"]]:
            counts[role_map[role]] += 1
    values = [counts[action_id] for action_id in action_ids]
    total = sum(values)
    signature = json.dumps(mapping_by_task, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tie = sha256(signature)
    perfect_indicators = sum(value in {0, len(tasks)} for value in values) if total else 0
    spread = max(values) - min(values) if values else 0
    variance = sum((len(action_ids) * value - total) ** 2 for value in values)
    return perfect_indicators, spread, variance, tie


def balanced_role_mapping(
    family: str,
    tasks: list[dict[str, Any]],
    passing_roles_by_task: dict[str, set[str]],
) -> dict[str, dict[str, int]]:
    roles = sorted(tasks[0]["candidate_role_by_action_id_hidden"].values())
    ids = sorted(int(value) for value in tasks[0]["candidate_role_to_action_id_hidden"].values())
    if any(set(task["candidate_role_by_action_id_hidden"].values()) != set(roles) for task in tasks):
        raise ValueError(f"role set changes within family {family}")
    if not any(passing_roles_by_task[task["task_id"]] for task in tasks):
        return {
            task["task_id"]: {role: int(action_id) for role, action_id in task["candidate_role_to_action_id_hidden"].items()}
            for task in tasks
        }

    task_candidates: list[list[dict[str, int]]] = []
    for task in tasks:
        target_role = task["family_spec_hidden"].get("target_role")
        target_id = task["primary_gold_action_id_hidden"]
        if target_role is None or target_id is None:
            raise ValueError(f"action task lacks primary role/id in {family}/{task['task_id']}")
        if target_role not in passing_roles_by_task[task["task_id"]]:
            raise ValueError(f"primary gold role failed executable check in {family}/{task['task_id']}")
        assignments = []
        for candidate_ids in itertools.permutations(ids):
            mapping = dict(zip(roles, candidate_ids, strict=True))
            if mapping[target_role] == int(target_id):
                assignments.append(mapping)
        if not assignments:
            raise ValueError(f"no valid identity assignment for {family}/{task['task_id']}")
        task_candidates.append(assignments)

    best: tuple[int, int, int, str] | None = None
    best_mapping: dict[str, dict[str, int]] | None = None
    for choices in itertools.product(*task_candidates):
        candidate = {task["task_id"]: mapping for task, mapping in zip(tasks, choices, strict=True)}
        score = map_score(candidate, tasks, passing_roles_by_task, ids)
        if best is None or score < best:
            best, best_mapping = score, candidate
    if best_mapping is None:
        raise ValueError(f"failed to assign opaque IDs in {family}")
    counts = Counter({action_id: 0 for action_id in ids})
    for task in tasks:
        for role in passing_roles_by_task[task["task_id"]]:
            counts[best_mapping[task["task_id"]][role]] += 1
    if any(value in {0, len(tasks)} for value in counts.values()):
        raise ValueError(f"opaque ID is a perfect validity indicator in {family}: {dict(counts)}")
    return best_mapping


def main() -> None:
    outputs = (OUTPUT_SOURCE, OUTPUT_CHECKS, OUTPUT_REPORT)
    if any(path.exists() for path in outputs):
        raise SystemExit("refusing to overwrite finalized label artifacts")
    if not RUN_LOCK.exists() or not TASK_LOCK.exists():
        raise SystemExit("task and scored-check locks are required")
    source = json.loads(RAW_SOURCE.read_text(encoding="utf-8"))
    checks = json.loads(RAW_CHECKS.read_text(encoding="utf-8"))
    if checks.get("state") != "CANDIDATE_CHECKS_COMPLETE_NO_MODEL_CONTACT":
        raise SystemExit("candidate check run is incomplete")
    if any(row["compile_failed"] for row in checks["candidate_rows"] + checks["base_rows"]):
        raise SystemExit("compiler failures prevent label finalization")

    consistency: dict[tuple[str, str, str, str, str], set[bool]] = defaultdict(set)
    for row in checks["candidate_rows"] + checks["base_rows"]:
        for case in row["check_cases"]:
            key = (row["family_hidden"], row["overlay_manifest_sha256"], row["overlay_source_sha256"], row["overlay_test_sha256"], case["case_id"])
            consistency[key].add(bool(case["passed"]))
    conflicts = [key for key, outcomes in consistency.items() if len(outcomes) != 1]
    if conflicts:
        raise ValueError(f"identical content/case inputs have conflicting outputs: {len(conflicts)}")

    if len(source["tasks_hidden"]) != 48 or len(checks["candidate_rows"]) != 192 or len(checks["base_rows"]) != 48:
        raise ValueError("locked task/candidate/base row counts drifted")
    source_hash = file_sha(RAW_SOURCE)
    checks_hash = file_sha(RAW_CHECKS)
    check_rows_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    passing_roles_by_task: dict[str, set[str]] = defaultdict(set)
    for row in checks["candidate_rows"]:
        check_rows_by_task[row["task_id"]].append(row)
        if row["task_candidate_passed"]:
            passing_roles_by_task[row["task_id"]].add(row["candidate_role_hidden"])
    task_by_id = {task["task_id"]: task for task in source["tasks_hidden"]}
    if set(check_rows_by_task) != set(task_by_id) or any(len(rows) != 4 for rows in check_rows_by_task.values()):
        raise ValueError("candidate execution rows do not cover exactly four candidates per task")

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in source["tasks_hidden"]:
        by_family[task["family_name_hidden"]].append(task)
    final_maps: dict[str, dict[str, int]] = {}
    family_report: dict[str, Any] = {}
    for family, tasks in sorted(by_family.items()):
        tasks.sort(key=lambda item: int(item["within_family_index"]))
        before = {
            task["task_id"]: {role: int(value) for role, value in task["candidate_role_to_action_id_hidden"].items()}
            for task in tasks
        }
        after = balanced_role_mapping(family, tasks, passing_roles_by_task)
        final_maps.update(after)
        ids = sorted({int(value) for value in before[tasks[0]["task_id"]].values()})
        before_counts = Counter({action_id: 0 for action_id in ids})
        after_counts = Counter({action_id: 0 for action_id in ids})
        for task in tasks:
            for role in passing_roles_by_task[task["task_id"]]:
                before_counts[before[task["task_id"]][role]] += 1
                after_counts[after[task["task_id"]][role]] += 1
        family_report[family] = {
            "passing_roles_by_task": {task["task_id"]: sorted(passing_roles_by_task[task["task_id"]]) for task in tasks},
            "valid_action_count_by_id_before": {str(key): value for key, value in sorted(before_counts.items())},
            "valid_action_count_by_id_after": {str(key): value for key, value in sorted(after_counts.items())},
            "id_mapping_changed": before != after,
            "perfect_id_indicator_before": any(value in {0, len(tasks)} for value in before_counts.values()) if sum(before_counts.values()) else False,
            "perfect_id_indicator_after": any(value in {0, len(tasks)} for value in after_counts.values()) if sum(after_counts.values()) else False,
        }

    final_source = json.loads(json.dumps(source))
    final_source["state"] = "TASK_SOURCE_FIXTURES_FINALIZED_FROM_EXECUTABLE_CHECKS_NO_MODEL_CONTACT"
    final_source["source_fixture_version"] = 2
    final_source["derived_from"] = {
        "raw_source_fixture_sha256": source_hash,
        "consistent_candidate_check_result_sha256": checks_hash,
        "candidate_check_run_lock_sha256": file_sha(RUN_LOCK),
        "task_construction_lock_sha256": file_sha(TASK_LOCK),
        "finalizer_sha256": file_sha(Path(__file__)),
        "model_contact": False,
    }
    for task in final_source["tasks_hidden"]:
        task_id = task["task_id"]
        new_map = final_maps[task_id]
        pass_roles = passing_roles_by_task[task_id]
        task["candidate_role_to_action_id_hidden"] = new_map
        task["candidate_role_by_action_id_hidden"] = {str(value): role for role, value in new_map.items()}
        task["primary_gold_action_id_hidden"] = (
            new_map[task["family_spec_hidden"]["target_role"]]
            if task["family_spec_hidden"].get("target_role") is not None else None
        )
        task["expected_valid_action_ids_hidden"] = sorted(new_map[role] for role in pass_roles)
        options_by_role = {option["hidden_candidate_role"]: option for option in task["candidate_options_hidden"]}
        for role, option in options_by_role.items():
            option["action"]["id"] = new_map[role]
        family = task["family_name_hidden"]
        members = sorted(by_family[family], key=lambda item: int(item["within_family_index"]))
        local_targets = {
            int(member["within_family_index"]): (
                None if member["family_spec_hidden"].get("target_role") is None
                else final_maps[member["task_id"]][member["family_spec_hidden"]["target_role"]]
            ) for member in members
        }
        local_valid = {
            int(member["within_family_index"]): {
                final_maps[member["task_id"]][role] for role in passing_roles_by_task[member["task_id"]]
            } for member in members
        }
        ids = sorted(new_map.values())
        producer, control = builder.producer_order_schedules(ids, local_targets, local_valid, family)
        index = int(task["within_family_index"])
        task["producer_order_action_ids_hidden"] = producer[index]
        task["coordinate_control_action_ids_hidden"] = control[index]
        ordered_roles = [task["candidate_role_by_action_id_hidden"][str(action_id)] for action_id in producer[index]]
        task["candidate_options_hidden"] = [options_by_role[role] for role in ordered_roles]
        for ordinal, option in enumerate(task["candidate_options_hidden"]):
            option["producer_ordinal_hidden"] = ordinal

    final_tasks_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in final_source["tasks_hidden"]:
        final_tasks_by_family[task["family_name_hidden"]].append(task)
    for family_audit in final_source["family_audit_hidden"]:
        family = family_audit["family_hidden"]
        members = sorted(final_tasks_by_family[family], key=lambda item: int(item["within_family_index"]))
        family_audit["candidate_mappings_by_task_hidden"] = {
            task["task_id"]: task["candidate_role_to_action_id_hidden"] for task in members
        }
        family_audit["producer_order_by_task_hidden"] = {
            str(task["within_family_index"]): task["producer_order_action_ids_hidden"] for task in members
        }
        family_audit["coordinate_control_order_by_task_hidden"] = {
            str(task["within_family_index"]): task["coordinate_control_action_ids_hidden"] for task in members
        }

    source_bytes = (json.dumps(final_source, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    final_source_hash = sha256(source_bytes)
    OUTPUT_SOURCE.write_bytes(source_bytes)

    final_check_rows = []
    for row in checks["candidate_rows"]:
        derived = dict(row)
        derived["source_action_id_hidden"] = row["action_id_hidden"]
        derived["action_id_hidden"] = final_maps[row["task_id"]][row["candidate_role_hidden"]]
        final_check_rows.append(derived)
    final_checks = {
        "schema_version": 1,
        "state": "CANDIDATE_CHECKS_COMPLETE_NO_MODEL_CONTACT",
        "artifact_kind": "DERIVED_ACTION_ID_LABELS_FROM_EXECUTABLE_ROLE_RESULTS",
        "model_contact_authorized": False,
        "source_fixture_sha256": final_source_hash,
        "raw_candidate_check_result_sha256": checks_hash,
        "candidate_check_run_lock_sha256": file_sha(RUN_LOCK),
        "action_id_derivation": "remap by hidden candidate role under final balanced mapping; execution outputs and overlay hashes copied byte-for-byte",
        "candidate_task_rows": len(final_check_rows),
        "candidate_case_invocations": checks["candidate_case_invocations"],
        "base_task_rows": len(checks["base_rows"]),
        "base_case_invocations": checks["base_case_invocations"],
        "candidate_rows": final_check_rows,
        "base_rows": checks["base_rows"],
    }
    OUTPUT_CHECKS.write_text(json.dumps(final_checks, indent=2) + "\n", encoding="utf-8")

    position_report: dict[str, Any] = {}
    for family, tasks in sorted(by_family.items()):
        tasks.sort(key=lambda item: int(item["within_family_index"]))
        valid = [set(final_source["tasks_hidden"][source["tasks_hidden"].index(task)]["expected_valid_action_ids_hidden"]) for task in tasks]
        schedules = [final_source["tasks_hidden"][source["tasks_hidden"].index(task)]["producer_order_action_ids_hidden"] for task in tasks]
        position_report[family] = [
            sum(schedules[row][position] in valid[row] for row in range(4)) for position in range(4)
        ]
        if any(count in {0, 4} for count in position_report[family]) and any(valid):
            raise ValueError(f"candidate position perfectly predicts validity after finalization: {family}")
        family_report[family]["valid_action_count_by_producer_position_final"] = position_report[family]

    report = {
        "schema_version": 1,
        "state": "LABEL_FINALIZATION_COMPLETE_NO_MODEL_CONTACT",
        "model_contact_authorized": False,
        "raw_source_fixture_sha256": source_hash,
        "raw_candidate_check_result_sha256": checks_hash,
        "derived_source_fixture_sha256": final_source_hash,
        "derived_candidate_check_labels_sha256": file_sha(OUTPUT_CHECKS),
        "consistent_input_case_groups": len(consistency),
        "same_input_case_conflicts": 0,
        "expected_set_divergences": {
            task_id: {
                "prior_expected_ids": sorted(int(value) for value in task_by_id[task_id]["expected_valid_action_ids_hidden"]),
                "executable_valid_roles": sorted(passing_roles_by_task[task_id]),
                "executable_valid_ids_under_prior_mapping": sorted(
                    int(row["action_id_hidden"]) for row in check_rows_by_task[task_id] if row["task_candidate_passed"]
                ),
            }
            for task_id in task_by_id
            if sorted(int(value) for value in task_by_id[task_id]["expected_valid_action_ids_hidden"])
            != sorted(int(row["action_id_hidden"]) for row in check_rows_by_task[task_id] if row["task_candidate_passed"])
        },
        "families": family_report,
        "position_validity_counts": position_report,
        "model_contact": False,
    }
    OUTPUT_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": report["state"], "families": len(family_report), "expected_set_divergences": len(report["expected_set_divergences"]), "source_sha256": final_source_hash, "output": str(OUTPUT_SOURCE)}, indent=2))


if __name__ == "__main__":
    main()

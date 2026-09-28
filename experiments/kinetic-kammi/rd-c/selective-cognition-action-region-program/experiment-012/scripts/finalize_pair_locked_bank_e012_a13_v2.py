from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
BANK = CONSTRUCTION / "scored-bank-a12"
SOURCE = BANK / "vault" / "task-source-fixtures-precheck-v2.json"
CHECKS = BANK / "vault" / "candidate-check-results-precheck-v2.json"
SOURCE_OUT = BANK / "vault" / "task-source-fixtures-final-v2.json"
CHECKS_OUT = BANK / "vault" / "candidate-check-labels-final-v2.json"
REPORT_OUT = BANK / "vault" / "label-finalization-report-v2.json"
LOCK = CONSTRUCTION / "a13-retry-design-lock-v1.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def verify_lock() -> dict[str, Any]:
    if not LOCK.is_file():
        raise SystemExit("A13 construction lock is missing")
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if lock.get("state") != "FROZEN_BEFORE_A13_RETRY":
        raise SystemExit("A13 construction lock state is invalid")
    for item in lock["files"]:
        path = ROOT / Path(item["path"])
        if not path.is_file() or digest(path.read_bytes()) != item["sha256"]:
            raise SystemExit(f"A13 locked input drift: {item['path']}")
    return lock


def maps_for(roles: list[str], ids: list[int]) -> list[dict[str, int]]:
    return [dict(zip(roles, arrangement, strict=True)) for arrangement in itertools.permutations(ids)]


def passing_roles_by_task(checks: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    seen: set[tuple[str, str]] = set()
    for row in checks["candidate_rows"]:
        key = (str(row["task_id"]), str(row["candidate_role_hidden"]))
        if key in seen:
            raise ValueError(f"duplicate candidate result for {key}")
        seen.add(key)
        result.setdefault(key[0], set())
        if row["compile_failed"]:
            raise ValueError(f"candidate compile failure for {key}")
        if row["task_candidate_passed"]:
            result[key[0]].add(key[1])
    return result


def ids_for_roles(mapping: dict[str, int], roles: set[str]) -> set[int]:
    return {mapping[role] for role in roles}


def gold_role(task: dict[str, Any], passing: set[str]) -> tuple[str | None, str | None]:
    if task["direct_decision_hidden"] != "ACT":
        if passing:
            raise ValueError(f"abstention task has an executable passing action: {task['task_id']}")
        return None, None
    requested = task["family_spec_hidden"].get("target_role")
    if requested in passing:
        return str(requested), None
    if not passing:
        raise ValueError(f"action task has no executable passing action: {task['task_id']}")
    if len(passing) == 1:
        return next(iter(passing)), f"reselected_{requested}_to_unique_executable_role"
    raise ValueError(f"locked primary role {requested} is not among passing roles for {task['task_id']}")


def action_options_by_role(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {str(option["hidden_candidate_role"]): option for option in task["candidate_options_hidden"]}
    if len(result) != 4:
        raise ValueError(f"task lacks four unique candidate roles: {task['task_id']}")
    return result


def make_config(
    members: list[dict[str, Any]], maps: list[dict[str, int]], order: tuple[int, ...],
    pass_by_task: dict[str, set[str]], gold_by_task: dict[str, str | None],
) -> dict[str, Any]:
    if len(members) != len(maps):
        raise ValueError("mapping/task cardinality mismatch")
    id_counts = Counter({value: 0 for value in order})
    position_counts = [0, 0, 0, 0]
    gold_counts = [0, 0, 0, 0]
    valid_ids_by_task: dict[str, set[int]] = {}
    gold_positions: dict[str, int | None] = {}
    mapping_by_task: dict[str, dict[str, int]] = {}
    for task, mapping in zip(members, maps, strict=True):
        task_id = str(task["task_id"])
        passing = pass_by_task[task_id]
        valid_ids = ids_for_roles(mapping, passing)
        valid_ids_by_task[task_id] = valid_ids
        mapping_by_task[task_id] = mapping
        for action_id in valid_ids:
            id_counts[action_id] += 1
        for position, action_id in enumerate(order):
            if action_id in valid_ids:
                position_counts[position] += 1
        primary = gold_by_task[task_id]
        if primary is None:
            gold_positions[task_id] = None
        else:
            action_id = mapping[primary]
            position = order.index(action_id)
            gold_positions[task_id] = position
            gold_counts[position] += 1
    return {
        "mapping_by_task": mapping_by_task,
        "order": order,
        "valid_ids_by_task": valid_ids_by_task,
        "id_counts": tuple(id_counts[value] for value in sorted(order)),
        "position_counts": tuple(position_counts),
        "gold_counts": tuple(gold_counts),
        "gold_positions": gold_positions,
    }


def state_key(config: dict[str, Any]) -> tuple[int, ...]:
    return config["id_counts"] + config["position_counts"] + config["gold_counts"]


def candidate_block_configs(
    members: list[dict[str, Any]], target: str,
    pass_by_task: dict[str, set[str]], gold_by_task: dict[str, str | None],
    patch_by_task_role: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    members = sorted(members, key=lambda task: int(task["within_family_index"]))
    role_sets = [set(action_options_by_role(task)) for task in members]
    if any(roles != role_sets[0] for roles in role_sets[1:]):
        raise ValueError(f"candidate role set drift within pair {members[0]['pair_id']}")
    roles = sorted(role_sets[0])
    ids = sorted(int(value) for value in members[0]["candidate_role_to_action_id_hidden"].values())
    if any(sorted(int(value) for value in task["candidate_role_to_action_id_hidden"].values()) != ids for task in members):
        raise ValueError(f"action-ID universe drift within {members[0]['pair_id']}")
    mappings = maps_for(roles, ids)
    orders = list(itertools.permutations(ids))
    results: list[dict[str, Any]] = []

    if target == "E_c.content":
        if len(members) != 2:
            raise ValueError("candidate-content contrast must have exactly two tasks")
        if members[0]["check_cases"] != members[1]["check_cases"]:
            raise ValueError(f"candidate-content twin test suites differ in {members[0]['pair_id']}")
        for first_map in mappings:
            for second_map in mappings:
                if first_map == second_map:
                    continue
                if ids_for_roles(first_map, pass_by_task[members[0]["task_id"]]) == ids_for_roles(
                    second_map, pass_by_task[members[1]["task_id"]]
                ):
                    continue
                first_content = {first_map[role]: patch_by_task_role[members[0]["task_id"]][role] for role in roles}
                second_content = {second_map[role]: patch_by_task_role[members[1]["task_id"]][role] for role in roles}
                if first_content == second_content:
                    continue
                for order in orders:
                    results.append(make_config(members, [first_map, second_map], order, pass_by_task, gold_by_task))
    else:
        if len(members) != 2:
            raise ValueError(f"single-channel pair must have two tasks: {members[0]['pair_id']}")
        if pass_by_task[members[0]["task_id"]] == pass_by_task[members[1]["task_id"]]:
            raise ValueError(f"declared {target} pair does not switch passing roles: {members[0]['pair_id']}")
        left_options = action_options_by_role(members[0])
        right_options = action_options_by_role(members[1])
        if {role: left_options[role]["patch_sha256"] for role in roles} != {
            role: right_options[role]["patch_sha256"] for role in roles
        }:
            raise ValueError(f"candidate patches changed outside declared channel in {members[0]['pair_id']}")
        for mapping in mappings:
            for order in orders:
                results.append(make_config(members, [mapping, mapping], order, pass_by_task, gold_by_task))
    if not results:
        raise ValueError(f"no legal paired assignment for {members[0]['pair_id']}")
    return results


def factorial_configs(
    members: list[dict[str, Any]], pass_by_task: dict[str, set[str]],
    gold_by_task: dict[str, str | None],
) -> list[dict[str, Any]]:
    members = sorted(members, key=lambda task: int(task["within_family_index"]))
    if len(members) != 4:
        raise ValueError(f"joint factorial block must have four tasks: {members[0]['pair_id']}")
    bits = {
        (int(task["family_spec_hidden"]["request_bit"]), int(task["family_spec_hidden"]["execution_bit"])): task
        for task in members
    }
    if set(bits) != {(0, 0), (0, 1), (1, 0), (1, 1)}:
        raise ValueError(f"joint factorial bits are incomplete: {members[0]['pair_id']}")
    for fixed in (0, 1):
        for bit in (0, 1):
            et_a, et_b = bits[(bit, fixed)], bits[(1 - bit, fixed)]
            ex_a, ex_b = bits[(fixed, bit)], bits[(fixed, 1 - bit)]
            if pass_by_task[et_a["task_id"]] == pass_by_task[et_b["task_id"]]:
                raise ValueError(f"E_t does not alter valid roles in joint block {members[0]['pair_id']}")
            if pass_by_task[ex_a["task_id"]] == pass_by_task[ex_b["task_id"]]:
                raise ValueError(f"E_x does not alter valid roles in joint block {members[0]['pair_id']}")
    roles = sorted(action_options_by_role(members[0]))
    ids = sorted(int(value) for value in members[0]["candidate_role_to_action_id_hidden"].values())
    first_options = action_options_by_role(members[0])
    patch_signature = {role: first_options[role]["patch_sha256"] for role in roles}
    for task in members[1:]:
        options = action_options_by_role(task)
        if {role: options[role]["patch_sha256"] for role in roles} != patch_signature:
            raise ValueError(f"joint block candidate content changes across cells: {members[0]['pair_id']}")
    results = []
    for mapping in maps_for(roles, ids):
        for order in itertools.permutations(ids):
            results.append(make_config(members, [mapping] * 4, order, pass_by_task, gold_by_task))
    return results


def exact_pair_assignment(
    family: str, blocks: list[tuple[str, list[dict[str, Any]]]],
    pass_by_task: dict[str, set[str]], gold_by_task: dict[str, str | None],
    patch_by_task_role: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    if len(blocks) != 2:
        raise ValueError(f"expected two pair blocks for {family}, got {len(blocks)}")
    block_configs = [
        candidate_block_configs(members, target, pass_by_task, gold_by_task, patch_by_task_role)
        for target, members in blocks
    ]
    total_valid = sum(len(pass_by_task[task["task_id"]]) for _, members in blocks for task in members)
    total_gold = sum(gold_by_task[task["task_id"]] is not None for _, members in blocks for task in members)
    if total_valid % 4 or total_gold % 4:
        raise ValueError(f"exact action/position balance is impossible in {family}: valid={total_valid}, gold={total_gold}")
    target_valid = total_valid // 4
    target_gold = total_gold // 4
    target = (target_valid,) * 8 + (target_gold,) * 4
    right_index: dict[tuple[int, ...], dict[str, Any]] = {}
    for config in block_configs[1]:
        right_index.setdefault(state_key(config), config)
    for left in block_configs[0]:
        complement = tuple(value - count for value, count in zip(target, state_key(left), strict=True))
        if any(value < 0 for value in complement):
            continue
        right = right_index.get(complement)
        if right is not None:
            return [left, right]
    raise ValueError(f"no exact action-ID, position, and primary-gold balance assignment for {family}")


def write_assignment(
    task: dict[str, Any], mapping: dict[str, int], order: tuple[int, ...],
    valid_roles: set[str], primary_role: str | None,
) -> None:
    options = action_options_by_role(task)
    for role, option in options.items():
        option["action"]["id"] = mapping[role]
    ordered = []
    for ordinal, action_id in enumerate(order):
        role = next(role for role, value in mapping.items() if value == action_id)
        option = options[role]
        option["producer_ordinal_hidden"] = ordinal
        ordered.append(option)
    task["candidate_options_hidden"] = ordered
    task["candidate_role_to_action_id_hidden"] = mapping
    task["candidate_role_by_action_id_hidden"] = {str(value): role for role, value in mapping.items()}
    task["producer_order_action_ids_hidden"] = list(order)
    task["coordinate_control_action_ids_hidden"] = list(reversed(order))
    task["expected_valid_action_ids_hidden"] = sorted(mapping[role] for role in valid_roles)
    task["primary_gold_action_id_hidden"] = mapping[primary_role] if primary_role is not None else None


def main() -> None:
    if any(path.exists() for path in (SOURCE_OUT, CHECKS_OUT, REPORT_OUT)):
        raise SystemExit("refusing to overwrite A13 finalizer outputs")
    lock = verify_lock()
    source_bytes = SOURCE.read_bytes()
    checks_bytes = CHECKS.read_bytes()
    source = json.loads(source_bytes)
    checks = json.loads(checks_bytes)
    if checks.get("state") != "CANDIDATE_CHECKS_COMPLETE_NO_MODEL_CONTACT" or checks.get("model_contact_authorized") is not False:
        raise SystemExit("A13 executable candidate checks are incomplete or unexpectedly authorized")
    if checks.get("compile_failures", 0):
        raise SystemExit("A13 candidate checks contain a compilation failure")
    tasks = source["tasks_hidden"]
    pass_by_task = passing_roles_by_task(checks)
    check_roles: dict[str, set[str]] = defaultdict(set)
    patch_by_task_role: dict[str, dict[str, str]] = defaultdict(dict)
    result_by_task_role: dict[tuple[str, str], dict[str, Any]] = {}
    for row in checks["candidate_rows"]:
        task_id, role = str(row["task_id"]), str(row["candidate_role_hidden"])
        check_roles[task_id].add(role)
        patch_by_task_role[task_id][role] = str(row["patch_sha256_hidden"])
        result_by_task_role[(task_id, role)] = row
    task_by_id = {str(task["task_id"]): task for task in tasks}
    if set(check_roles) != set(task_by_id) or any(len(roles) != 4 for roles in check_roles.values()):
        raise ValueError("A13 checks do not cover exactly four candidate roles per task")
    gold_by_task: dict[str, str | None] = {}
    gold_fallbacks: dict[str, str] = {}
    for task_id, task in task_by_id.items():
        primary, fallback = gold_role(task, pass_by_task.get(task_id, set()))
        gold_by_task[task_id] = primary
        if fallback is not None:
            gold_fallbacks[task_id] = fallback

    family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        family_groups[str(task["family_name_hidden"])].append(task)
    all_assignment_rows: dict[str, dict[str, Any]] = {}
    family_reports: dict[str, Any] = {}
    for family, members in sorted(family_groups.items()):
        by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for task in members:
            by_pair[str(task["pair_id"])].append(task)
        declared = {str(task["counterfactual_change_channel_hidden"]) for task in members}
        if declared == {"none"}:
            ids = sorted(int(value) for value in members[0]["candidate_role_to_action_id_hidden"].values())
            mapping = {str(role): int(value) for role, value in members[0]["candidate_role_to_action_id_hidden"].items()}
            for task in members:
                if pass_by_task[task["task_id"]]:
                    raise ValueError(f"abstention family has passing candidate: {task['task_id']}")
                row = int(task["within_family_index"]) - 1
                order = tuple(ids[row:] + ids[:row])
                all_assignment_rows[task["task_id"]] = {
                    "mapping": mapping.copy(), "order": order,
                    "valid_ids": set(), "gold_position": None,
                }
            family_reports[family] = {"state": "ABSTENTION_CONTROL", "blocks": len(by_pair)}
            continue

        factorial_groups = [group for group in by_pair.values() if len(group) == 4]
        if factorial_groups:
            if len(by_pair) != 1 or len(factorial_groups) != 1:
                raise ValueError(f"unexpected block mixture in joint family {family}")
            target = factorial_groups[0][0]["counterfactual_change_channel_hidden"]
            if target != "E_t+E_x":
                raise ValueError(f"unexpected factorial target in {family}: {target}")
            configs = factorial_configs(factorial_groups[0], pass_by_task, gold_by_task)
            total_valid = sum(len(pass_by_task[task["task_id"]]) for task in factorial_groups[0])
            total_gold = sum(gold_by_task[task["task_id"]] is not None for task in factorial_groups[0])
            if total_valid % 4 or total_gold % 4:
                raise ValueError(f"exact balance impossible in joint family {family}")
            target_state = (total_valid // 4,) * 8 + (total_gold // 4,) * 4
            selected = next((config for config in configs if state_key(config) == target_state), None)
            if selected is None:
                raise ValueError(f"no exact ID/position balance in joint family {family}")
            for task_id, mapping in selected["mapping_by_task"].items():
                all_assignment_rows[task_id] = {
                    "mapping": mapping.copy(), "order": selected["order"],
                    "valid_ids": selected["valid_ids_by_task"][task_id],
                    "gold_position": selected["gold_positions"][task_id],
                }
            family_reports[family] = {"state": "JOINT_FACTORIAL", "candidate_assignments_examined": len(configs)}
            continue

        if len(by_pair) != 2 or any(len(group) != 2 for group in by_pair.values()):
            raise ValueError(f"expected two paired blocks in action family {family}")
        blocks = []
        for pair_id, group in sorted(by_pair.items()):
            targets = {str(task["counterfactual_change_channel_hidden"]) for task in group}
            if len(targets) != 1:
                raise ValueError(f"paired block target drift in {pair_id}")
            blocks.append((next(iter(targets)), group))
        selected_configs = exact_pair_assignment(family, blocks, pass_by_task, gold_by_task, patch_by_task_role)
        for config in selected_configs:
            for task_id, mapping in config["mapping_by_task"].items():
                all_assignment_rows[task_id] = {
                    "mapping": mapping.copy(), "order": config["order"],
                    "valid_ids": config["valid_ids_by_task"][task_id],
                    "gold_position": config["gold_positions"][task_id],
                }
        family_reports[family] = {
            "state": "PAIRED_ACTION_FAMILY",
            "blocks": [{"target": target, "pair_id": group[0]["pair_id"]} for target, group in blocks],
            "candidate_assignments_examined_by_block": [
                len(candidate_block_configs(group, target, pass_by_task, gold_by_task, patch_by_task_role))
                for target, group in blocks
            ],
        }

    if set(all_assignment_rows) != set(task_by_id):
        raise ValueError("paired assignment solver omitted tasks")
    final_source = json.loads(json.dumps(source))
    final_source["state"] = "A13_TASK_SOURCE_FINALIZED_FROM_EXECUTABLE_CHECKS_NO_MODEL_CONTACT"
    final_source["source_fixture_version"] = "a13-final-v2"
    final_source["derived_from_a13_retry"] = {
        "precheck_source_sha256": digest(source_bytes),
        "candidate_check_results_sha256": digest(checks_bytes),
        "construction_lock_sha256": digest(LOCK.read_bytes()),
        "finalizer_sha256": digest(Path(__file__).read_bytes()),
        "model_contact": False,
    }
    opaque_ids: dict[str, str] = {}
    variants: dict[str, int] = {}
    for task in final_source["tasks_hidden"]:
        task_id = str(task["task_id"])
        assignment = all_assignment_rows[task_id]
        task_pass = pass_by_task[task_id]
        primary_role = gold_by_task[task_id]
        write_assignment(task, assignment["mapping"], assignment["order"], task_pass, primary_role)
        for option in task["candidate_options_hidden"]:
            role = str(option["hidden_candidate_role"])
            check_row = result_by_task_role[(task_id, role)]
            option["patch_sha256"] = str(check_row["patch_sha256_hidden"])
            option["hidden_patch_text"] = next(
                candidate["hidden_patch_text"]
                for candidate in source["tasks_hidden"]
                if candidate["task_id"] == task_id
                for candidate in candidate["candidate_options_hidden"]
                if candidate["hidden_candidate_role"] == role
            )
        task["primary_gold_role_hidden"] = primary_role
        task["primary_gold_action_id_hidden"] = assignment["mapping"][primary_role] if primary_role is not None else None
        if task["counterfactual_change_channel_hidden"] == "none":
            task["observer_task_id_hidden"] = task_id
        else:
            pair_id = str(task["pair_id"])
            if pair_id not in opaque_ids:
                opaque_ids[pair_id] = "task-" + hashlib.sha256(("e012-a13-retry-presentation:" + pair_id).encode()).hexdigest()[:8]
                variants[pair_id] = int(hashlib.sha256(("e012-a13-retry-variant:" + pair_id).encode()).hexdigest()[:8], 16) % (2**31)
            task["observer_task_id_hidden"] = opaque_ids[pair_id]
            task["task_variant"] = variants[pair_id]

    # Rebuild family-level mapping and order summaries after the paired assignment.
    final_task_by_id = {str(task["task_id"]): task for task in final_source["tasks_hidden"]}
    for family_audit in final_source["family_audit_hidden"]:
        family = str(family_audit["family_hidden"])
        family_members = sorted(family_groups[family], key=lambda row: int(row["within_family_index"]))
        finalized_members = [final_task_by_id[str(row["task_id"])] for row in family_members]
        family_audit["candidate_mappings_by_task_hidden"] = {
            task["task_id"]: task["candidate_role_to_action_id_hidden"] for task in finalized_members
        }
        family_audit["producer_order_by_task_hidden"] = {
            str(task["within_family_index"]): task["producer_order_action_ids_hidden"] for task in finalized_members
        }
        family_audit["coordinate_control_order_by_task_hidden"] = {
            str(task["within_family_index"]): task["coordinate_control_action_ids_hidden"] for task in finalized_members
        }

    final_source_bytes = json_bytes(final_source)
    final_source_hash = digest(final_source_bytes)
    SOURCE_OUT.write_bytes(final_source_bytes)

    final_rows = []
    family_balance: dict[str, Any] = {}
    for task in final_source["tasks_hidden"]:
        task_id = str(task["task_id"])
        mapping = {str(role): int(value) for role, value in task["candidate_role_to_action_id_hidden"].items()}
        role_by_id = {value: role for role, value in mapping.items()}
        for row in checks["candidate_rows"]:
            if str(row["task_id"]) != task_id:
                continue
            role = str(row["candidate_role_hidden"])
            derived = dict(row)
            derived["source_action_id_hidden"] = row["action_id_hidden"]
            derived["action_id_hidden"] = mapping[role]
            derived["task_candidate_passed"] = role in pass_by_task[task_id]
            final_rows.append(derived)
        if set(role_by_id.values()) != set(check_roles[task_id]):
            raise ValueError(f"candidate action mapping lost roles for {task_id}")

    for family, members in sorted(((name, [final_task_by_id[str(task["task_id"])] for task in rows]) for name, rows in family_groups.items())):
        ids = sorted(int(value) for value in members[0]["candidate_role_to_action_id_hidden"].values())
        id_counts = Counter({action_id: 0 for action_id in ids})
        position_counts = [0, 0, 0, 0]
        gold_positions = []
        for task in members:
            valid_ids = set(int(value) for value in task["expected_valid_action_ids_hidden"])
            id_to_position = {int(value): position for position, value in enumerate(task["producer_order_action_ids_hidden"])}
            for action_id in valid_ids:
                id_counts[action_id] += 1
                position_counts[id_to_position[action_id]] += 1
            if task["primary_gold_action_id_hidden"] is not None:
                gold_positions.append(id_to_position[int(task["primary_gold_action_id_hidden"])])
        total_valid = sum(id_counts.values())
        exact_target = total_valid // 4 if total_valid % 4 == 0 else None
        if exact_target is not None and (set(id_counts.values()) != {exact_target} or set(position_counts) != {exact_target}):
            raise ValueError(f"exact valid/invalid balance failed in {family}: IDs={dict(id_counts)}, positions={position_counts}")
        if len(gold_positions) and len(gold_positions) % 4 == 0 and Counter(gold_positions) != Counter({0: len(gold_positions)//4, 1: len(gold_positions)//4, 2: len(gold_positions)//4, 3: len(gold_positions)//4}):
            raise ValueError(f"primary-gold positions are not balanced in {family}: {gold_positions}")
        family_balance[family] = {
            "valid_candidate_rows": total_valid,
            "valid_count_by_action_id": {str(key): value for key, value in sorted(id_counts.items())},
            "valid_count_by_position": position_counts,
            "primary_gold_positions": gold_positions,
        }

    final_checks = {
        "schema_version": 1,
        "state": "CANDIDATE_CHECKS_COMPLETE_NO_MODEL_CONTACT",
        "artifact_kind": "A13_PAIRED_ACTION_ID_LABELS_FROM_EXECUTABLE_RESULTS",
        "model_contact_authorized": False,
        "source_fixture_sha256": final_source_hash,
        "precheck_source_sha256": digest(source_bytes),
        "candidate_check_result_sha256": digest(checks_bytes),
        "construction_lock_sha256": digest(LOCK.read_bytes()),
        "candidate_task_rows": len(final_rows),
        "candidate_case_invocations": checks["candidate_case_invocations"],
        "base_task_rows": len(checks["base_rows"]),
        "base_case_invocations": checks["base_case_invocations"],
        "candidate_rows": final_rows,
        "base_rows": checks["base_rows"],
    }
    CHECKS_OUT.write_bytes(json_bytes(final_checks))
    report = {
        "schema_version": 1,
        "state": "A13_LABEL_FINALIZATION_COMPLETE_NO_MODEL_CONTACT",
        "model_contact_authorized": False,
        "precheck_source_sha256": digest(source_bytes),
        "candidate_check_result_sha256": digest(checks_bytes),
        "final_source_sha256": final_source_hash,
        "final_labels_sha256": digest(CHECKS_OUT.read_bytes()),
        "construction_lock_sha256": digest(LOCK.read_bytes()),
        "primary_gold_fallbacks": gold_fallbacks,
        "family_balance": family_balance,
        "family_assignment_summary": family_reports,
        "model_contact": False,
    }
    REPORT_OUT.write_bytes(json_bytes(report))
    print(json.dumps({
        "state": report["state"], "tasks": len(tasks), "candidate_rows": len(final_rows),
        "families": len(family_balance), "primary_gold_fallbacks": len(gold_fallbacks),
        "source_sha256": final_source_hash, "report": str(REPORT_OUT),
    }, indent=2))


if __name__ == "__main__":
    main()

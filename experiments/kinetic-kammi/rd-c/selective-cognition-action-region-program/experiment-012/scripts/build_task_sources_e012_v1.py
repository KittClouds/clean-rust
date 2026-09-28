from __future__ import annotations

import hashlib
import itertools
import json
import random
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
OUTPUT = CONSTRUCTION / "scored-bank-v1"
DESIGN = CONSTRUCTION / "family-design-v1.1.json"
SOURCE_INVENTORY = CONSTRUCTION / "repository-source-inventory.json"
FEASIBILITY = CONSTRUCTION / "feasibility"
SOURCES = {
    "bounded-prefix-copy": "bytes-prefix",
    "cursor-advance-observation": "bytes-cursor-repair-01",
    "composite-frame-field": "bytes-composite-repair-01",
    "wire-endian-contract": "bytes-endian",
    "number-mode-plus-error-site": "serde-numeric-joint-repair-01",
    "repeated-option-policy": "clap-repeat-repair-01",
    "map-order-feature-contract": "serde-map-order-repair-02",
    "conflicting-alias-requirement": "clap-alias",
    "possible-value-validation": "clap-values",
    "stream-byte-offset": "serde-offset-repair-02",
    "help-color-capability": "clap-color-repair-01",
    "raw-number-lossless": "serde-raw-number",
}
GOLD_ID_POSITION_ORDER = (0, 3, 1, 2)
CASE_SPECIFIC_FAMILIES = {
    "cursor-advance-observation", "composite-frame-field", "wire-endian-contract",
    "number-mode-plus-error-site", "repeated-option-policy", "map-order-feature-contract",
    "stream-byte-offset", "help-color-capability",
}
FULL_SUITE_FAMILIES = {
    "bounded-prefix-copy", "possible-value-validation",
    "conflicting-alias-requirement", "raw-number-lossless",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_contract_context(family: str, patch_body: str) -> str:
    context = {
        "bounded-prefix-copy": (
            "API context: take_prefix returns a bounded zero-copy view; the result shares "
            "the input Bytes backing storage.\n"
        ),
        "possible-value-validation": (
            'API context: the parser accepts exactly the finite values "fast" and "safe"; '
            "other strings are rejected.\n"
        ),
    }.get(family, "")
    return context + patch_body


def patch_body(patch_path: Path) -> str:
    lines = patch_path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith(("--- ", "+++ ")))


def target_id(ids: list[int], within_index: int) -> int:
    return ids[GOLD_ID_POSITION_ORDER[within_index - 1]]


def producer_order_schedules(
    ids: list[int], targets_by_index: dict[int, int | None],
    valid_ids_by_index: dict[int, set[int]], family: str,
) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """Create a seeded Latin schedule minimizing position-only validity imbalance."""
    seed_material = hashlib.sha256(f"E012-A05:{family}:20260925".encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(seed_material[:8], "big"))
    targets = [targets_by_index[index] for index in range(1, 5)]
    if any(target is None for target in targets) and not all(target is None for target in targets):
        raise ValueError(f"mixed action/abstention target schedule in {family}")
    target_position_schedules = (
        list(itertools.permutations(range(4))) if targets[0] is not None else [(None,) * 4]
    )
    rng.shuffle(target_position_schedules)
    schedules: list[tuple[tuple[int, ...], ...]] = []
    all_orders = list(itertools.permutations(ids))
    for gold_positions in target_position_schedules:
        row_candidates = [list(all_orders) for _ in range(4)]
        for row, target in enumerate(targets):
            if target is not None:
                row_candidates[row] = [
                    order for order in row_candidates[row]
                    if order[int(gold_positions[row])] == int(target)
                ]
            rng.shuffle(row_candidates[row])
        used_by_position = [set() for _ in ids]
        rows: list[tuple[int, ...]] = []

        def enumerate_rows(row_index: int) -> None:
            if row_index == 4:
                schedules.append(tuple(rows))
                return
            for order in row_candidates[row_index]:
                if any(order[position] in used_by_position[position] for position in range(4)):
                    continue
                for position, action_id in enumerate(order):
                    used_by_position[position].add(action_id)
                rows.append(order)
                enumerate_rows(row_index + 1)
                rows.pop()
                for position, action_id in enumerate(order):
                    used_by_position[position].remove(action_id)

        enumerate_rows(0)
    if not schedules:
        raise ValueError(f"could not construct a balanced producer schedule for {family}")

    def position_score(rows: tuple[tuple[int, ...], ...]) -> tuple[int, int, int]:
        counts = [
            sum(rows[row][position] in valid_ids_by_index[row + 1] for row in range(4))
            for position in range(4)
        ]
        # Primary criterion is the smallest spread; secondary is squared imbalance.
        return max(counts) - min(counts), sum((4 * count - sum(counts)) ** 2 for count in counts), rng.randrange(2**31)

    scored_schedules = [(position_score(rows), rows) for rows in schedules]
    best_score = min(score[:2] for score, _ in scored_schedules)
    finalists = [rows for score, rows in scored_schedules if score[:2] == best_score]
    producer_rows = rng.choice(finalists)
    producer = {index: list(producer_rows[index - 1]) for index in range(1, 5)}
    control = {index: list(reversed(producer[index])) for index in range(1, 5)}
    for schedule_name, schedule in (("producer", producer), ("coordinate-control", control)):
        for position in range(4):
            if {schedule[index][position] for index in range(1, 5)} != set(ids):
                raise ValueError(f"{schedule_name} action-position balance failed for {family}")
        targets = [targets_by_index[index] for index in range(1, 5)]
        if all(target is not None for target in targets):
            gold_positions = [schedule[index].index(int(targets[index - 1])) for index in range(1, 5)]
            if set(gold_positions) != set(range(4)):
                raise ValueError(f"{schedule_name} gold-position balance failed for {family}")
    return producer, control


def pass_roles(summary: dict[str, Any], case: str) -> set[str]:
    declared = summary.get("intended_positive_sets", {}).get(case)
    if declared is not None:
        return set(declared)
    return {
        role for role, cases in summary["candidate_pass_matrix_hidden_roles"].items()
        if cases.get(case, False)
    }


def choose_support_mappings(
    tasks: list[dict[str, Any]], roles: list[str], ids: list[int], summary: dict[str, Any]
) -> dict[str, dict[str, int]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        groups.setdefault(task["pair_id"], []).append(task)
    mappings: dict[str, dict[str, int]] = {}
    for pair_id, members in sorted(groups.items()):
        members.sort(key=lambda item: item["within_family_index"])
        target_sets = []
        for task in members:
            case = f"case-{task['within_family_index']:02d}"
            target_sets.append((target_id(ids, task["within_family_index"]), pass_roles(summary, case)))
        if any(not positive for _, positive in target_sets):
            raise ValueError(f"no declared positive candidates for {pair_id}")
        found = None
        for assigned_ids in itertools.permutations(ids):
            role_to_id = dict(zip(roles, assigned_ids, strict=True))
            id_to_role = {value: key for key, value in role_to_id.items()}
            if all(id_to_role[goal] in positive for goal, positive in target_sets):
                found = role_to_id
                break
        if found is None:
            raise ValueError(f"cannot align locked gold roles to executable candidates in {pair_id}")
        for task in members:
            mappings[task["task_id"]] = found.copy()
    return mappings


def selected_role_for_candidate_family(family: str, summary: dict[str, Any]) -> str:
    if family == "bounded-prefix-copy":
        return "slice_prefix"
    if family == "possible-value-validation":
        passing = [
            role for role, cases in summary["candidate_pass_matrix_hidden_roles"].items()
            if all(cases.values())
        ]
        if passing != ["allow_fast_and_safe"]:
            raise ValueError(f"unexpected full-suite value-validation pass set: {passing}")
        return passing[0]
    raise ValueError(f"not a candidate-action family: {family}")


def expected_roles_for_task(family: str, task: dict[str, Any], summary: dict[str, Any]) -> set[str]:
    if family in {"bounded-prefix-copy", "possible-value-validation"}:
        return {selected_role_for_candidate_family(family, summary)}
    if family in {"conflicting-alias-requirement", "raw-number-lossless"}:
        return set()
    return pass_roles(summary, f"case-{int(task['within_family_index']):02d}")


def candidate_only_mappings(
    family: str, tasks: list[dict[str, Any]], roles: list[str], ids: list[int], summary: dict[str, Any]
) -> dict[str, dict[str, int]]:
    passing_role = selected_role_for_candidate_family(family, summary)
    output = {}
    for task in tasks:
        goal = target_id(ids, task["within_family_index"])
        remaining = [value for value in ids if value != goal]
        role_to_id = {passing_role: goal}
        for role, value in zip((r for r in roles if r != passing_role), remaining, strict=True):
            role_to_id[role] = value
        output[task["task_id"]] = role_to_id
    return output


def fixed_abstention_mapping(roles: list[str], ids: list[int]) -> dict[str, int]:
    return dict(zip(roles, ids, strict=True))


def prompt_for(family: str, index: int, labels: dict[str, Any]) -> str:
    case = f"case-{index:02d}"
    if family == "wire-endian-contract":
        role = labels["target_role"]
        order = "big-endian" if role == "emit_big_endian_word" else "little-endian"
        return f"Implement the requested two-byte word order: {order}. Choose one offered patch."
    if family == "repeated-option-policy":
        role = labels["target_role"]
        behavior = "append every occurrence" if role == "append_all" else "use only the last occurrence"
        return f"For repeated --tag arguments, the caller requires that we {behavior}. Choose one patch."
    if family == "composite-frame-field":
        field = "header" if labels["request_bit"] == 0 else "payload"
        return f"Implement the two-byte frame decoder for the requested target field: {field}."
    if family == "number-mode-plus-error-site":
        mode = "whole" if labels["number_mode_bit"] == 0 else "ratio"
        return f"The requested JSON numeric mode is {mode}. Use the failing-path observation to select a patch."
    if family == "conflicting-alias-requirement":
        variant = ("primary spelling first", "alias first", "override last", "override before aliases")[index - 1]
        return (
            "Support both --color and --colour as equivalent spellings, plus --no-color "
            f"with the required precedence ({variant}); preserve the current public alias contract."
        )
    if family == "raw-number-lossless":
        token = ("1.2300e+02", "9007199254740993", "-0.000", "6.022000e23")[index - 1]
        return f"Rewrite the JSON document while preserving the exact source number token {token}; do not normalize it."
    prompts = {
        "bounded-prefix-copy": "Review the code-local API contract included with the offered changes. Select the conforming patch.",
        "cursor-advance-observation": "The adapter contract test fails on the frozen base snapshot. Use its pre-action cursor observation to choose a patch.",
        "possible-value-validation": "Review the code-local parser contract included with the offered changes. Select the conforming patch.",
        "stream-byte-offset": "The streaming adapter test fails on the frozen base snapshot. Use the pre-action parser observation to choose a patch.",
        "help-color-capability": "Choose the help-color patch that satisfies the current terminal/build compatibility context.",
        "map-order-feature-contract": "Choose the map-order patch that satisfies the active build-feature contract.",
    }
    if case and family in prompts:
        return prompts[family]
    raise ValueError(f"no prompt rule for {family}")


def ex_content(family: str, index: int, summary: dict[str, Any], records: list[dict[str, Any]], labels: dict[str, Any]) -> str:
    if family == "composite-frame-field":
        order = "big" if labels["execution_bit"] == 0 else "little"
        return f"Pre-action decoder observation: the frame bytes are in {order}-endian order."
    if family == "number-mode-plus-error-site":
        site = "header" if labels["error_site_bit"] == 0 else "payload"
        return f"Pre-action parser observation: the first failure is at /{site}."
    if family not in {"cursor-advance-observation", "stream-byte-offset"}:
        return "The untouched base snapshot produced no task-relevant pre-action execution observation."
    expected_by_case: dict[str, tuple[str, str]] = {}
    for row in records:
        if row.get("candidate_id") is None and row.get("case_id") == f"case-{index:02d}":
            match = __import__("re").search(r"left:\s*([^\r\n]+)\s*\r?\n\s*right:\s*([^\r\n]+)", row.get("stdout", ""))
            if match:
                expected_by_case[row["case_id"]] = (match.group(1).strip(), match.group(2).strip())
    pair = expected_by_case.get(f"case-{index:02d}")
    if pair is None:
        raise ValueError(f"execution trace lacks actual/expected values: {family} case-{index:02d}")
    noun = "cursor" if family == "cursor-advance-observation" else "first-item byte offset"
    return f"Untouched base-snapshot assertion: observed {noun} {pair[0]}; reference value {pair[1]}."


def context_for(repository: dict[str, Any], family: str, index: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "language": "Rust",
        "toolchain": "stable",
        "target": "host",
        "dependency_release": repository["release"],
        "repository_code": repository["opaque_code"],
        "build_features": "baseline",
    }
    if family == "help-color-capability":
        supported = index in (1, 3)
        payload["terminal_ansi_capability"] = "supported" if supported else "suppressed"
        payload["help_color_policy"] = "emit-color" if supported else "plain-text"
    elif family == "map-order-feature-contract":
        preserve = index in (2, 4)
        payload["serde_json_preserve_order_feature"] = preserve
        payload["map_iteration_contract"] = "preserve-insertion-order" if preserve else "lexical-order"
    return payload


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite scored bank directory: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    vault = OUTPUT / "vault"
    vault.mkdir()
    design = read_json(DESIGN)
    inventory = read_json(SOURCE_INVENTORY)
    repositories = {item["repository_id"]: item for item in inventory["selected_repositories"]}
    for ordinal, item in enumerate(sorted(repositories.values(), key=lambda x: x["repository_id"]), start=1):
        item["opaque_code"] = f"repo-{ordinal:02d}"
    records: list[dict[str, Any]] = []
    family_audit: list[dict[str, Any]] = []
    for family_spec in design["families"]:
        family = family_spec["hidden_family_name"]
        selected_dir = SOURCES[family]
        feasible = FEASIBILITY / selected_dir
        summary = read_json(feasible / "feasibility-summary.json")
        raw_tests = read_json(feasible / "candidate-test-records.json")
        role_ids = {role: int(value) for role, value in summary["candidate_ids_hidden_role_map"].items()}
        roles = list(role_ids)
        ids = sorted(role_ids.values())
        id_by_role = {role: role_ids[role] for role in roles}
        patch_by_role = {
            role: (feasible / f"candidate-{role_ids[role]}.patch").read_text(encoding="utf-8")
            for role in roles
        }
        role_mapping: dict[str, dict[str, int]]
        if family in {"bounded-prefix-copy", "possible-value-validation"}:
            role_mapping = candidate_only_mappings(family, family_spec["tasks"], roles, ids, summary)
        elif family in {"conflicting-alias-requirement", "raw-number-lossless"}:
            fixed = fixed_abstention_mapping(roles, ids)
            role_mapping = {task["task_id"]: fixed.copy() for task in family_spec["tasks"]}
        else:
            role_mapping = choose_support_mappings(family_spec["tasks"], roles, ids, summary)
        family_tasks = sorted(family_spec["tasks"], key=lambda item: int(item["within_family_index"]))
        targets_by_index = {
            int(task["within_family_index"]): (
                None if family in {"conflicting-alias-requirement", "raw-number-lossless"}
                else target_id(ids, int(task["within_family_index"]))
            )
            for task in family_tasks
        }
        valid_ids_by_index = {
            int(task["within_family_index"]): {
                role_mapping[task["task_id"]][role]
                for role in expected_roles_for_task(family, task, summary)
            }
            for task in family_tasks
        }
        producer_orders, coordinate_orders = producer_order_schedules(
            ids, targets_by_index, valid_ids_by_index, family
        )
        for task in family_tasks:
            index = int(task["within_family_index"])
            case = f"case-{index:02d}"
            repo = repositories[family_spec["repository_id"]]
            inverse = {action_id: role for role, action_id in role_mapping[task["task_id"]].items()}
            expected_roles = expected_roles_for_task(family, task, summary)
            expected_ids = sorted(role_mapping[task["task_id"]][role] for role in expected_roles)
            target = target_id(ids, index) if family not in {"conflicting-alias-requirement", "raw-number-lossless"} else None
            if target is not None and target not in expected_ids:
                raise ValueError(f"locked target action not positive for {task['task_id']}: {expected_ids}")
            action_options = []
            producer_order = producer_orders[index]
            for producer_ordinal, action_id in enumerate(producer_order):
                role = inverse[action_id]
                diff = patch_body(feasible / f"candidate-{role_ids[role]}.patch")
                content = apply_contract_context(family, diff)
                action_options.append({
                    "producer_ordinal_hidden": producer_ordinal,
                    "action": {"id": action_id, "schema_id": 1},
                    "summary": "Apply the candidate change shown in the code excerpt.",
                    "diff_excerpt": content,
                    "patch_sha256": sha256_bytes(patch_by_role[role].encode("utf-8")),
                    "hidden_candidate_role": role,
                    "hidden_patch_text": patch_by_role[role],
                })
            labels: dict[str, Any] = {
                "case_id": case,
                "target_role": next((role for role, action_id in role_mapping[task["task_id"]].items() if action_id == target), None),
                "request_bit": task.get("latent_request_bit"),
                "execution_bit": task.get("latent_execution_bit"),
            }
            if family == "number-mode-plus-error-site":
                role = next(role for role, action_id in role_mapping[task["task_id"]].items() if action_id == target)
                labels["number_mode_bit"] = 0 if role.endswith("_whole") else 1
                labels["error_site_bit"] = 0 if role.startswith("header_") else 1
            check_cases = [f"case-{n:02d}" for n in range(1, 5)] if family in FULL_SUITE_FAMILIES else [case]
            request = prompt_for(family, index, labels)
            ex = ex_content(family, index, summary, raw_tests, labels)
            record = {
                "task_id": task["task_id"],
                "task_variant": random.Random(20260925 + int(task["task_id"].split("-")[-1])).randrange(1000, 2**31),
                "pair_id": task["pair_id"],
                "within_family_index": index,
                "repository_id_hidden": family_spec["repository_id"],
                "repository_code": repo["opaque_code"],
                "repository_revision": repo["commit"],
                "snapshot_sha256": repo["archive_sha256"],
                "task_family_code": family_spec["observer_family_code"],
                "family_name_hidden": family,
                "stratum_hidden": family_spec["stratum"],
                "truth_support_hidden": list(task["truth_support"]),
                "counterfactual_change_channel_hidden": task["counterfactual_change_channel"],
                "candidate_role_to_action_id_hidden": role_mapping[task["task_id"]],
                "candidate_role_by_action_id_hidden": inverse,
                "candidate_options_hidden": action_options,
                "producer_order_action_ids_hidden": producer_order,
                "coordinate_control_action_ids_hidden": coordinate_orders[index],
                "expected_valid_action_ids_hidden": expected_ids,
                "primary_gold_action_id_hidden": target,
                "direct_decision_hidden": task["full_frame_direct_decision"],
                "check_cases": check_cases,
                "request_text_authentic": request,
                "execution_text_authentic": ex,
                "context_authentic": context_for(repo, family, index),
                "family_spec_hidden": labels,
                "feasibility_dir_hidden": selected_dir,
                "task_prompt_generic": family in {"bounded-prefix-copy", "possible-value-validation"},
            }
            records.append(record)
        family_audit.append({
            "family_hidden": family,
            "selected_feasibility": selected_dir,
            "role_ids_hidden": role_ids,
            "candidate_mappings_by_task_hidden": {key: value for key, value in role_mapping.items()},
            "producer_order_by_task_hidden": {str(index): order for index, order in producer_orders.items()},
            "coordinate_control_order_by_task_hidden": {str(index): order for index, order in coordinate_orders.items()},
        })
    records.sort(key=lambda item: (item["repository_id_hidden"], item["family_name_hidden"], item["within_family_index"]))
    if len(records) != 48 or len({row["task_id"] for row in records}) != 48:
        raise ValueError("family design did not yield 48 unique tasks")
    output = {
        "schema_version": 1,
        "state": "TASK_SOURCE_FIXTURES_BUILT_NO_MODEL_CONTACT",
        "model_contact_authorized": False,
        "task_count": len(records),
        "family_count": len(family_audit),
        "family_audit_hidden": family_audit,
        "tasks_hidden": records,
    }
    (vault / "task-source-fixtures.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": output["state"], "tasks": len(records), "families": len(family_audit), "output": str(vault / 'task-source-fixtures.json')}, indent=2))


if __name__ == "__main__":
    main()

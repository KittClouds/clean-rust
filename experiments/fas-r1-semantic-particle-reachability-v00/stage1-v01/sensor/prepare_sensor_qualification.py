#!/usr/bin/env python3
"""Build the frozen, reference-free R1 Stage 1 sensor qualification corpus.

This preparation stage reads Stage 0 public/private task records, creates a
family-disjoint render/template/vocabulary design, and writes labels to a
separate private sidecar. It does not load the LFM or fit a probe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

SPLIT_DOMAIN = b"R1-STAGE1-FAMILY-SPLIT-v1\0"
ACTION_DOMAIN = b"R1-STAGE1-ACTION-STATE-v1\0"
SCHEMA = "R1_STAGE1_SENSOR_QUALIFICATION_DATA_V01"

VOCABULARIES = {
    "V0": {
        "entities": [
            "daxen", "mivor", "pelka", "ronet", "suvin", "tavro",
            "wexal", "yemri", "zupan", "brelka", "corvin", "duske",
        ],
        "roles": ["velin", "sorga", "tremu", "wexen"],
    },
    "V1": {
        "entities": [
            "qevron", "fyalin", "gromet", "hiskal", "jovren", "kluvia",
            "moxari", "nyther", "praxen", "qulori", "ryvane", "zomtek",
        ],
        "roles": ["qorin", "fayra", "ghest", "jopel"],
    },
}

GLOBAL_TEMPLATES = {
    "T0": "Assign every entity to exactly one available role. Entities: {entities}. Available roles: {roles}.",
    "T1": "Place each participant in one listed role, one role apiece. Participants: {entities}. Role options: {roles}.",
    "T2": "Give every object precisely one position. Objects: {entities}. Positions to use: {roles}.",
}

CLAUSE_TEMPLATES = {
    "Same": {
        "T0": "{a} and {b} must have the same role.",
        "T1": "Assign {a} and {b} to one identical role.",
        "T2": "{a} shares a role with {b}.",
    },
    "Different": {
        "T0": "{a} and {b} must have different roles.",
        "T1": "Do not give {a} and {b} one shared role.",
        "T2": "{a} and {b} must occupy distinct positions.",
    },
    "FixedRole": {
        "T0": "{entity} must be assigned to {role}.",
        "T1": "The role for {entity} is {role}.",
        "T2": "Place {entity} in the {role} position.",
    },
    "ForbiddenRole": {
        "T0": "{entity} cannot take {role}.",
        "T1": "Do not assign {entity} to {role}.",
        "T2": "Keep {entity} out of the {role} position.",
    },
    "ExactlyOneRole": {
        "T0": "Exactly one of {a} and {b} must take {role}.",
        "T1": "Among {a} and {b}, one and only one must occupy {role}.",
        "T2": "Assign precisely one of {a} and {b} to position {role}.",
    },
    "ImpliesNotRole": {
        "T0": "If {if_entity} takes {if_role}, then {then_entity} must not take {then_role}.",
        "T1": "When {if_entity} has role {if_role}, keep {then_entity} out of {then_role}.",
        "T2": "{if_entity} in position {if_role} implies {then_entity} is not in {then_role}.",
    },
}

CLAUSE_KINDS = tuple(CLAUSE_TEMPLATES)
ARG_SLOTS = ("entity_arg_0", "entity_arg_1", "role_arg_0", "role_arg_1")
ACTION_CLASSES = ("improve", "neutral", "worsen")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
            count += len(block)
    return digest.hexdigest(), count


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[str, int, int]:
    count = 0
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
        stream.flush()
        os.fsync(stream.fileno())
    digest, size = sha256_file(path)
    return digest, size, count


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def build_split_map(tasks: list[dict[str, Any]]) -> dict[str, str]:
    family_ids = sorted(
        {task["family_id"] for task in tasks},
        key=lambda value: hashlib.sha256(SPLIT_DOMAIN + value.encode("utf-8")).digest(),
    )
    if len(family_ids) != 96:
        raise ValueError(f"expected exactly 96 independent families, got {len(family_ids)}")
    return {
        family_id: "train" if index < 48 else "validation" if index < 64 else "evaluation"
        for index, family_id in enumerate(family_ids)
    }


def argument_slots(clause: dict[str, Any]) -> dict[str, int]:
    kind, values = next(iter(clause.items()))
    if kind in ("Same", "Different"):
        return {"entity_arg_0": values["a"], "entity_arg_1": values["b"]}
    if kind in ("FixedRole", "ForbiddenRole"):
        return {"entity_arg_0": values["entity"], "role_arg_0": values["role"]}
    if kind == "ExactlyOneRole":
        slots = {"entity_arg_0": values["entities"][0], "role_arg_0": values["role"]}
        if len(values["entities"]) > 1:
            slots["entity_arg_1"] = values["entities"][1]
        return slots
    if kind == "ImpliesNotRole":
        return {
            "entity_arg_0": values["if_entity"],
            "entity_arg_1": values["then_entity"],
            "role_arg_0": values["if_role"],
            "role_arg_1": values["then_role"],
        }
    raise ValueError(f"unknown clause kind {kind}")


def render_clause(clause: dict[str, Any], names: dict[str, list[str]], template_id: str) -> tuple[str, list[int], list[int], dict[str, int]]:
    kind, values = next(iter(clause.items()))
    entities, roles = names["entities"], names["roles"]
    args = argument_slots(clause)
    if kind in ("Same", "Different"):
        fields = {"a": entities[values["a"]], "b": entities[values["b"]]}
    elif kind in ("FixedRole", "ForbiddenRole"):
        fields = {"entity": entities[values["entity"]], "role": roles[values["role"]]}
    elif kind == "ExactlyOneRole":
        fields = {"a": entities[values["entities"][0]], "role": roles[values["role"]]}
        if len(values["entities"]) > 1:
            fields["b"] = entities[values["entities"][1]]
    elif kind == "ImpliesNotRole":
        fields = {
            "if_entity": entities[values["if_entity"]],
            "if_role": roles[values["if_role"]],
            "then_entity": entities[values["then_entity"]],
            "then_role": roles[values["then_role"]],
        }
    else:
        raise ValueError(f"unknown clause kind {kind}")
    if kind == "ExactlyOneRole" and len(values["entities"]) == 1:
        singleton = {
            "T0": "Exactly {a} must take {role}.",
            "T1": "Only {a} may occupy {role}.",
            "T2": "Assign {a} to position {role} as the sole occupant.",
        }
        text = singleton[template_id].format(**fields)
    else:
        text = CLAUSE_TEMPLATES[kind][template_id].format(**fields)
    entity_mentions = sorted({value for key, value in args.items() if key.startswith("entity_")})
    role_mentions = sorted({value for key, value in args.items() if key.startswith("role_")})
    return text, entity_mentions, role_mentions, args


def render_global(names: dict[str, list[str]], template_id: str) -> str:
    return GLOBAL_TEMPLATES[template_id].format(
        entities=", ".join(names["entities"]), roles=", ".join(names["roles"])
    )


def rendering_conditions(split: str) -> list[tuple[str, str, str]]:
    if split in ("train", "validation"):
        return [("train_seen_t0_v0", "T0", "V0"), ("train_seen_t1_v0", "T1", "V0")]
    return [
        ("eval_id_t0_v0", "T0", "V0"),
        ("eval_id_t1_v0", "T1", "V0"),
        ("eval_template_t2_v0", "T2", "V0"),
        ("eval_vocab_t0_v1", "T0", "V1"),
        ("eval_vocab_t1_v1", "T1", "V1"),
        ("eval_joint_t2_v1", "T2", "V1"),
    ]


def violation(clause: dict[str, Any], assignment: list[int]) -> bool:
    kind, values = next(iter(clause.items()))
    if kind == "Same":
        return assignment[values["a"]] != assignment[values["b"]]
    if kind == "Different":
        return assignment[values["a"]] == assignment[values["b"]]
    if kind == "FixedRole":
        return assignment[values["entity"]] != values["role"]
    if kind == "ForbiddenRole":
        return assignment[values["entity"]] == values["role"]
    if kind == "ExactlyOneRole":
        return sum(assignment[entity] == values["role"] for entity in values["entities"]) != 1
    if kind == "ImpliesNotRole":
        return assignment[values["if_entity"]] == values["if_role"] and assignment[values["then_entity"]] == values["then_role"]
    raise ValueError(f"unknown clause kind {kind}")


def violation_vector(clauses: list[dict[str, Any]], assignments: np.ndarray) -> np.ndarray:
    result = np.zeros(assignments.shape[0], dtype=np.int16)
    for clause in clauses:
        kind, values = next(iter(clause.items()))
        if kind == "Same":
            result += assignments[:, values["a"]] != assignments[:, values["b"]]
        elif kind == "Different":
            result += assignments[:, values["a"]] == assignments[:, values["b"]]
        elif kind == "FixedRole":
            result += assignments[:, values["entity"]] != values["role"]
        elif kind == "ForbiddenRole":
            result += assignments[:, values["entity"]] == values["role"]
        elif kind == "ExactlyOneRole":
            result += (assignments[:, values["entities"]] == values["role"]).sum(axis=1) != 1
        elif kind == "ImpliesNotRole":
            result += (
                (assignments[:, values["if_entity"]] == values["if_role"])
                & (assignments[:, values["then_entity"]] == values["then_role"])
            )
        else:
            raise ValueError(f"unknown clause kind {kind}")
    return result


def exact_solutions(task: dict[str, Any], expected: int) -> np.ndarray:
    n, k = task["n"], task["k"]
    total = k**n
    powers = np.asarray([k**index for index in range(n)], dtype=np.uint64)
    solutions: list[np.ndarray] = []
    chunk_size = 131_072
    for begin in range(0, total, chunk_size):
        end = min(begin + chunk_size, total)
        codes = np.arange(begin, end, dtype=np.uint64)
        states = np.empty((end - begin, n), dtype=np.uint8)
        for entity in range(n):
            states[:, entity] = ((codes // powers[entity]) % k).astype(np.uint8)
        violations = violation_vector(task["clauses"], states)
        valid = states[violations == 0]
        if valid.size:
            solutions.append(valid)
    result = np.concatenate(solutions, axis=0) if solutions else np.empty((0, n), dtype=np.uint8)
    if result.shape[0] != expected:
        raise ValueError(
            f"independent exact enumerator disagrees for {task['id']}: {result.shape[0]} != {expected}"
        )
    return result


def state_for(family_id: str, state_index: int, n: int, k: int) -> list[int]:
    result = []
    family = family_id.encode("utf-8")
    for entity in range(n):
        digest = hashlib.sha256(
            ACTION_DOMAIN + family + state_index.to_bytes(4, "big") + entity.to_bytes(2, "big")
        ).digest()
        result.append(int.from_bytes(digest[:8], "big") % k)
    return result


def eval_condition_name(variant: str) -> str:
    if variant.startswith("eval_id_"):
        return "id_seen"
    if variant.startswith("eval_template_"):
        return "template_ood"
    if variant.startswith("eval_vocab_"):
        return "vocabulary_ood"
    if variant.startswith("eval_joint_"):
        return "joint_ood"
    return "not_applicable"


def prepare(source: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing preparation directory: {output}")
    output.mkdir(parents=True)
    public_input = source / "public-tasks.jsonl"
    private_input = source / "private-tasks.jsonl"
    evidence_input = source / "task-evidence.json"
    source_receipt = source / "construction-receipt.json"
    artifact_manifest_path = source / "artifact-manifest-v01.json"
    artifact_manifest = json.loads(artifact_manifest_path.read_text(encoding="utf-8"))
    if artifact_manifest.get("status") != "R1_CONSTRUCTION_READY":
        raise ValueError("Stage 0 artifact manifest is not R1_CONSTRUCTION_READY")
    if artifact_manifest.get("artifact_root_sha256") != "2078a366082a358275fa2b10d9f657967ef71a7c259a709822e631f01ce929d7":
        raise ValueError("Stage 0 artifact root identity differs from the reviewed construction")
    parent_entries = {row["path"]: row for row in artifact_manifest.get("files", [])}
    for relative in ("public-tasks.jsonl", "private-tasks.jsonl", "task-evidence.json", "construction-receipt.json"):
        expected = parent_entries.get(relative)
        if expected is None:
            raise ValueError(f"Stage 0 manifest lacks required source {relative}")
        observed_hash, observed_bytes = sha256_file(source / relative)
        if observed_hash != expected["sha256"] or observed_bytes != expected["bytes"]:
            raise ValueError(f"Stage 0 source hash/length differs from manifest: {relative}")
    public_tasks = read_jsonl(public_input)
    private_tasks = read_jsonl(private_input)
    evidence = json.loads(evidence_input.read_text(encoding="utf-8"))
    if len(public_tasks) != 96 or len(private_tasks) != 96:
        raise ValueError("frozen parent input must contain 96 public and 96 private tasks")
    public_by_id = {task["id"]: task for task in public_tasks}
    private_by_id = {task["id"]: task for task in private_tasks}
    evidence_by_id = {row["task_id"]: row for row in evidence}
    if set(public_by_id) != set(private_by_id) or set(public_by_id) != set(evidence_by_id):
        raise ValueError("public/private/evidence task identity sets disagree")
    for task_id in public_by_id:
        if public_by_id[task_id]["family_id"] != private_by_id[task_id]["family_id"]:
            raise ValueError(f"family identity mismatch for {task_id}")
        if evidence_by_id[task_id]["exact_count_status"] != "EXHAUSTED":
            raise ValueError(f"task lacks exact solution exhaustion proof: {task_id}")
    split_map = build_split_map(private_tasks)
    public_rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []
    name_queries = [
        {"name_id": f"{vocab_id}_{kind}_{index:02d}", "kind": kind, "surface": surface}
        for vocab_id, vocab in VOCABULARIES.items()
        for kind in ("entities", "roles")
        for index, surface in enumerate(vocab[kind])
    ]
    split_manifest: list[dict[str, Any]] = []
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    argument_counts: dict[str, Counter[str]] = defaultdict(Counter)
    condition_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    condition_argument_counts: dict[str, Counter[str]] = defaultdict(Counter)
    condition_families: dict[str, set[str]] = defaultdict(set)
    action_counts: dict[str, Counter[str]] = defaultdict(Counter)
    action_rows: list[dict[str, Any]] = []
    solution_counts = {}

    for task_id in sorted(private_by_id):
        task = private_by_id[task_id]
        task_public = public_by_id[task_id]
        task_evidence = evidence_by_id[task_id]
        family_id = task["family_id"]
        split = split_map[family_id]
        solution_set = exact_solutions(task, int(task_evidence["raw_solution_count"]))
        solution_counts[task_id] = int(solution_set.shape[0])
        task_variants = rendering_conditions(split)
        split_manifest.append(
            {
                "task_id": task_id,
                "family_id": family_id,
                "split": split,
                "n": task["n"],
                "k": task["k"],
                "role_anonymous": task["role_anonymous"],
                "canonical_solution_class_count": task_evidence["canonical_solution_class_count"],
                "render_variants": [item[0] for item in task_variants],
            }
        )

        for variant_id, template_id, vocab_id in task_variants:
            names = VOCABULARIES[vocab_id]
            clauses = []
            entity_incidence = []
            role_incidence = []
            clause_targets = []
            condition = eval_condition_name(variant_id)
            for clause in task["clauses"]:
                clause_kind = next(iter(clause))
                text, entities, roles, args = render_clause(clause, names, template_id)
                clauses.append(text)
                entity_incidence.append(entities)
                role_incidence.append(roles)
                clause_targets.append(
                    {
                        "kind": clause_kind,
                        "argument_slots": args,
                        "entity_mentions": entities,
                        "role_mentions": roles,
                    }
                )
                type_counts[split][clause_kind] += 1
                if condition != "not_applicable":
                    condition_type_counts[condition][clause_kind] += 1
                for slot in ARG_SLOTS:
                    if slot in args:
                        argument_counts[split][slot] += 1
                        if condition != "not_applicable":
                            condition_argument_counts[condition][slot] += 1
            if condition != "not_applicable":
                condition_families[condition].add(family_id)
            public_task_id = f"{task_id}__{variant_id}"
            public_rows.append(
                {
                    "id": public_task_id,
                    "family_id": family_id,
                    "n": task["n"],
                    "k": task["k"],
                    "role_anonymous": task["role_anonymous"],
                    "global_text": render_global(names, template_id),
                    "clauses": clauses,
                    "entity_mentions": entity_incidence,
                    "role_mentions": role_incidence,
                }
            )
            target_rows.append(
                {
                    "public_task_id": public_task_id,
                    "task_id": task_id,
                    "family_id": family_id,
                    "split": split,
                    "render_variant": variant_id,
                    "eval_condition": eval_condition_name(variant_id),
                    "template_id": template_id,
                    "vocab_id": vocab_id,
                    "n": task["n"],
                    "k": task["k"],
                    "role_anonymous": task["role_anonymous"],
                    "canonical_solution_class_count": task_evidence["canonical_solution_class_count"],
                    "clauses": clause_targets,
                }
            )

        # Generate a fixed family-seeded sample of complete assignments. Labels
        # are private offline targets and are never included in public text.
        for state_index in range(32):
            assignment = state_for(family_id, state_index, task["n"], task["k"])
            before = sum(violation(clause, assignment) for clause in task["clauses"])
            nearest = int(np.abs(solution_set.astype(np.int16) - np.asarray(assignment, dtype=np.int16)).sum(axis=1).min())
            for entity in range(task["n"]):
                old_role = assignment[entity]
                for new_role in range(task["k"]):
                    if new_role == old_role:
                        continue
                    edited = assignment.copy()
                    edited[entity] = new_role
                    after = sum(violation(clause, edited) for clause in task["clauses"])
                    delta = after - before
                    label = "improve" if delta < 0 else "neutral" if delta == 0 else "worsen"
                    action_counts[split][label] += 1
                    action_rows.append(
                        {
                            "task_id": task_id,
                            "family_id": family_id,
                            "split": split,
                            "state_index": state_index,
                            "assignment": assignment,
                            "violations_before": before,
                            "nearest_solution_hamming": nearest,
                            "edit_entity": entity,
                            "old_role": old_role,
                            "new_role": new_role,
                            "delta_violations": delta,
                            "target_sign": label,
                        }
                    )

    if not public_rows or not target_rows or not action_rows:
        raise ValueError("prepared qualification corpus is empty")
    public_digest, public_size, public_count = write_jsonl(output / "public-probe-tasks.jsonl", public_rows)
    targets_digest, targets_size, targets_count = write_jsonl(output / "private-probe-targets.jsonl", target_rows)
    names_digest, names_size, names_count = write_jsonl(output / "name-queries.jsonl", name_queries)
    action_digest, action_size, action_count = write_jsonl(output / "private-action-examples.jsonl", action_rows)
    split_digest, split_size, split_count = write_jsonl(output / "family-split.jsonl", split_manifest)

    requirements = {
        "families": {"train": 48, "validation": 16, "evaluation": 32},
        "clause_kind_instances_min": {"train": 20, "validation": 5, "evaluation": 8},
        "argument_slot_positive_min": {"train": 20, "validation": 5, "evaluation": 8},
        "action_class_instances_min": {"train": 1000, "validation": 500, "evaluation": 1000},
        "states_per_family": 32,
        "rendering_eval_conditions": ["id_seen", "template_ood", "vocabulary_ood", "joint_ood"],
    }
    support_ok = True
    failures: list[str] = []
    for split in ("train", "validation", "evaluation"):
        type_min = requirements["clause_kind_instances_min"][split]
        arg_min = requirements["argument_slot_positive_min"][split]
        action_min = requirements["action_class_instances_min"][split]
        for kind in CLAUSE_KINDS:
            value = type_counts[split][kind]
            if value < type_min:
                support_ok = False
                failures.append(f"{split}: clause kind {kind} support {value} < {type_min}")
        for slot in ARG_SLOTS:
            value = argument_counts[split][slot]
            if value < arg_min:
                support_ok = False
                failures.append(f"{split}: argument slot {slot} support {value} < {arg_min}")
        for label in ACTION_CLASSES:
            value = action_counts[split][label]
            if value < action_min:
                support_ok = False
                failures.append(f"{split}: action class {label} support {value} < {action_min}")
    for condition in ("id_seen", "template_ood", "vocabulary_ood", "joint_ood"):
        if len(condition_families[condition]) != 32:
            support_ok = False
            failures.append(f"{condition}: expected all 32 held-out families")
        for kind in CLAUSE_KINDS:
            value = condition_type_counts[condition][kind]
            if value < 8:
                support_ok = False
                failures.append(f"{condition}: clause kind {kind} support {value} < 8")
        for slot in ARG_SLOTS:
            value = condition_argument_counts[condition][slot]
            if value < 8:
                support_ok = False
                failures.append(f"{condition}: argument slot {slot} support {value} < 8")
    if not support_ok:
        raise ValueError("pre-model support gate failed: " + "; ".join(failures))

    source_files = {}
    for key, path in {
        "public_tasks": public_input,
        "private_tasks": private_input,
        "task_evidence": evidence_input,
        "construction_receipt": source_receipt,
        "artifact_manifest": artifact_manifest_path,
        "preparation_source": Path(__file__).resolve(),
    }.items():
        digest, size = sha256_file(path)
        source_files[key] = {"path": str(path), "bytes": size, "sha256": digest}
    support = {
        "schema": "R1_STAGE1_SENSOR_SUPPORT_AUDIT_V01",
        "status": "SUPPORT_PASS_PREMODEL",
        "source": source_files,
        "family_counts": dict(Counter(split_map.values())),
        "public_rendered_task_rows": public_count,
        "private_target_rows": targets_count,
        "name_query_rows": names_count,
        "action_examples": action_count,
        "raw_solution_counts_reconciled_to_parent": True,
        "solution_enumeration_total_assignments": int(sum(task["k"] ** task["n"] for task in private_tasks)),
        "clause_kind_support": {split: dict(type_counts[split]) for split in ("train", "validation", "evaluation")},
        "argument_slot_positive_support": {split: dict(argument_counts[split]) for split in ("train", "validation", "evaluation")},
        "evaluation_condition_families": {condition: len(condition_families[condition]) for condition in sorted(condition_families)},
        "evaluation_condition_clause_kind_support": {condition: dict(condition_type_counts[condition]) for condition in sorted(condition_type_counts)},
        "evaluation_condition_argument_slot_support": {condition: dict(condition_argument_counts[condition]) for condition in sorted(condition_argument_counts)},
        "action_class_support": {split: dict(action_counts[split]) for split in ("train", "validation", "evaluation")},
        "requirements": requirements,
        "failures": failures,
        "public_probe_tasks": {"path": "public-probe-tasks.jsonl", "bytes": public_size, "sha256": public_digest},
        "private_probe_targets": {"path": "private-probe-targets.jsonl", "bytes": targets_size, "sha256": targets_digest},
        "name_queries": {"path": "name-queries.jsonl", "bytes": names_size, "sha256": names_digest},
        "private_action_examples": {"path": "private-action-examples.jsonl", "bytes": action_size, "sha256": action_digest},
        "family_split": {"path": "family-split.jsonl", "bytes": split_size, "sha256": split_digest},
        "model_contact_performed": False,
        "probe_fitting_performed": False,
    }
    write_json(output / "SUPPORT-AUDIT.json", support)
    print(json.dumps({"status": support["status"], "families": support["family_counts"], "rendered_tasks": public_count, "action_rows": action_count, "support": support["action_class_support"]}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="frozen Stage 0 construction attempt")
    parser.add_argument("--output", type=Path, required=True, help="new, empty preparation directory")
    args = parser.parse_args()
    try:
        prepare(args.source.resolve(strict=True), args.output.resolve())
    except Exception as error:
        print(f"R1_SENSOR_PREPARATION_STOP: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

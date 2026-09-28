#!/usr/bin/env python3
"""Freeze deterministic task, empty-stratum, ordinal, candidate-role, and ID assignments."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum\pc-build\assignments")
OUT = ROOT / "E012-PC-ASSIGNMENTS-v1.0.json"
LOCK = ROOT / "E012-PC-ASSIGNMENTS-LOCK-v1.0.json"
V13_LOCK = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum\E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-LOCK-v1.3.json")
V131_LOCK = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum\E012-POSITIVE-CONTROL-RESERVE-POLICY-LOCK-v1.3.1.json")
V132_LOCK = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum\E012-PC-ACTION-ID-SCHEMA-LOCK-v1.3.2.json")
SEED = 13064


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def make_assignment() -> dict:
    v13, v131, v132 = load_json(V13_LOCK), load_json(V131_LOCK), load_json(V132_LOCK)
    seed_sequence = np.random.SeedSequence(SEED)
    children = seed_sequence.spawn(5)
    names = ["empty_cells", "empty_task_slots", "ordinal_assignment", "candidate_slot_order", "opaque_ids"]
    rng = {name: np.random.Generator(np.random.PCG64(child)) for name, child in zip(names, children)}
    stream_meta = {name: {"spawn_key": list(child.spawn_key), "state": child.generate_state(4, dtype=np.uint32).tolist()} for name, child in zip(names, children)}
    families = range(4)
    cells = [(repo, cohort, family) for repo in range(2) for cohort in ("PC", "difficulty") for family in families]

    repo0_count = 2 if int(rng["empty_cells"].integers(0, 2)) == 0 else 3
    repo_counts = [repo0_count, 5 - repo0_count]
    selected_families = []
    for repo, count in enumerate(repo_counts):
        picked = sorted(int(x) for x in rng["empty_cells"].choice(4, size=count, replace=False))
        selected_families.extend((repo, family) for family in picked)
    empty_cells = sorted(selected_families)
    empty_slots = {(repo, family): int(rng["empty_task_slots"].integers(0, 4)) for repo, family in empty_cells}

    task_map: dict[tuple[int, str, int, int], dict] = {}
    for repo, cohort, family in cells:
        for slot in range(4):
            is_empty = cohort == "difficulty" and (repo, family) in empty_slots and empty_slots[(repo, family)] == slot
            task_map[(repo, cohort, family, slot)] = {
                "repository_index": repo,
                "repository_id": f"repo_{repo}",
                "cohort": cohort,
                "family_index": family,
                "family_id": f"family_{family}",
                "task_slot": slot,
                "empty_valid_set": is_empty,
                "valid_anchor_ordinal": None,
                "candidate_role_by_ordinal": None,
                "task_id": None,
                "candidate_action_ids_by_ordinal": None,
            }

    ordinal_rng = rng["ordinal_assignment"]
    for repo in range(2):
        for family in families:
            order = [int(v) for v in ordinal_rng.permutation(4)]
            for slot, ordinal in enumerate(order):
                task_map[(repo, "PC", family, slot)]["valid_anchor_ordinal"] = ordinal
    difficulty_empty_cells = [(repo, family) for repo, family in empty_cells]
    omitted = [0, 0, 1, 2, 3]
    ordinal_rng.shuffle(omitted)
    for repo in range(2):
        for family in families:
            empty_slot = empty_slots.get((repo, family))
            if empty_slot is None:
                order = [int(v) for v in ordinal_rng.permutation(4)]
                for slot, ordinal in enumerate(order):
                    task_map[(repo, "difficulty", family, slot)]["valid_anchor_ordinal"] = ordinal
            else:
                cell_rank = difficulty_empty_cells.index((repo, family))
                omitted_ordinal = omitted[cell_rank]
                available = [x for x in range(4) if x != omitted_ordinal]
                order = [int(v) for v in ordinal_rng.permutation(available)]
                for slot, ordinal in zip([s for s in range(4) if s != empty_slot], order):
                    task_map[(repo, "difficulty", family, slot)]["valid_anchor_ordinal"] = ordinal

    task_keys = [(repo, cohort, family, slot) for repo in range(2) for cohort in ("PC", "difficulty") for family in families for slot in range(4)]
    role_rng = rng["candidate_slot_order"]
    candidate_roles = ["partial_fix", "wrong_location", "over_broad", "visible_pass_hidden_fail"]
    for key in task_keys:
        row = task_map[key]
        if row["empty_valid_set"]:
            row["candidate_role_by_ordinal"] = [str(x) for x in role_rng.permutation(candidate_roles)]
        else:
            anchor = row["valid_anchor_ordinal"]
            distractors = [str(x) for x in role_rng.permutation(candidate_roles)]
            row["candidate_role_by_ordinal"] = ["valid_anchor" if ordinal == anchor else distractors.pop(0) for ordinal in range(4)]

    id_rng = rng["opaque_ids"]
    task_ids = set()
    def make_task_id() -> str:
        while True:
            value = id_rng.bytes(16).hex()
            if value not in task_ids:
                task_ids.add(value)
                return value
    def make_action_ids() -> list[int]:
        used: set[int] = set()
        result = []
        while len(result) < 4:
            value = int(id_rng.integers(0, 65536, dtype=np.uint16))
            if value not in used:
                used.add(value)
                result.append(value)
        return result

    for key in task_keys:
        row = task_map[key]
        row["task_id"] = make_task_id()
        row["candidate_action_ids_by_ordinal"] = make_action_ids()

    reserves = []
    for repo in range(2):
        for cohort in ("PC", "difficulty"):
            for family in families:
                target = task_map[(repo, cohort, family, 0)]
                reserves.append({
                    "repository_index": repo,
                    "repository_id": f"repo_{repo}",
                    "cohort": cohort,
                    "family_index": family,
                    "family_id": f"family_{family}",
                    "reserve_rank": 0,
                    "replaces_task_slot": 0,
                    "empty_valid_set": target["empty_valid_set"],
                    "required_rater_score_vector": None,
                    "valid_anchor_ordinal": target["valid_anchor_ordinal"],
                    "candidate_role_by_ordinal": None,
                    "task_id": None,
                    "candidate_action_ids_by_ordinal": None,
                    "disposition": "PENDING_CONSTRUCTION",
                })
    for reserve in reserves:
        if reserve["empty_valid_set"]:
            reserve["candidate_role_by_ordinal"] = [str(x) for x in role_rng.permutation(candidate_roles)]
        else:
            anchor = reserve["valid_anchor_ordinal"]
            distractors = [str(x) for x in role_rng.permutation(candidate_roles)]
            reserve["candidate_role_by_ordinal"] = ["valid_anchor" if ordinal == anchor else distractors.pop(0) for ordinal in range(4)]
        reserve["task_id"] = make_task_id()
        reserve["candidate_action_ids_by_ordinal"] = make_action_ids()

    empty_counts = Counter(row["valid_anchor_ordinal"] for row in task_map.values() if row["cohort"] == "difficulty" and not row["empty_valid_set"])
    positive_counts = Counter(row["valid_anchor_ordinal"] for row in task_map.values() if row["cohort"] == "PC")
    assignment = {
        "schema": "e012-positive-control-structural-assignments.v1",
        "state": "ASSIGNMENTS_FROZEN_BANK_NOT_BUILT",
        "seed": SEED,
        "numpy_version": np.__version__,
        "rng": {"root": "numpy.random.SeedSequence", "spawn_count": 5, "bit_generator": "PCG64", "streams": stream_meta},
        "repository_order": ["first eligible repository in frozen candidate order", "second eligible repository in frozen candidate order"],
        "family_order": ["boundary_off_by_one", "error_handling", "parsing_configuration", "api_behavior"],
        "cohort_order": ["PC", "difficulty"],
        "empty_allocation": {"count": 5, "repo_family_cells": [{"repository_index": repo, "family_index": family, "task_slot": empty_slots[(repo, family)]} for repo, family in empty_cells], "repo_counts": repo_counts, "positive_control_count": 0},
        "task_assignments": [task_map[key] for key in task_keys],
        "reserve_assignments": reserves,
        "ordinal_counts": {"PC_by_ordinal": [positive_counts[x] for x in range(4)], "difficulty_nonempty_by_ordinal": [empty_counts[x] for x in range(4)]},
        "id_schema": {"task_id": "128-bit lowercase hex", "candidate_action_id": "integer 0..65535 unique within task", "draw_order": "core tasks canonical cell and task-slot order; task ID then action IDs by producer ordinal; reserves after all core tasks in canonical cell order"},
        "parent_locks_sha256": {"v1_3": sha_bytes(V13_LOCK.read_bytes()), "v1_3_1": sha_bytes(V131_LOCK.read_bytes()), "v1_3_2": sha_bytes(V132_LOCK.read_bytes())},
    }
    if len(task_map) != 64 or len(reserves) != 16 or sum(row["empty_valid_set"] for row in task_map.values()) != 5 or any(row["candidate_action_ids_by_ordinal"] is None for row in task_map.values()):
        raise RuntimeError("structural assignment count failed")
    if [positive_counts[x] for x in range(4)] != [8, 8, 8, 8] or [empty_counts[x] for x in range(4)] != [6, 7, 7, 7]:
        raise RuntimeError("ordinal-balance check failed")
    return assignment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if not args.build:
        parser.error("pass --build")
    if OUT.exists() or LOCK.exists():
        raise FileExistsError("refusing to overwrite assignments")
    payload = json.dumps(make_assignment(), indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    ROOT.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(payload)
    lock = {"artifact_id": "E012-PC-ASSIGNMENTS-LOCK-v1.0", "state": "PASS; BANK_NOT_BUILT", "assignment_path": str(OUT), "assignment_sha256": sha_bytes(payload), "parent_locks_sha256": {"v1_3": sha_bytes(V13_LOCK.read_bytes()), "v1_3_1": sha_bytes(V131_LOCK.read_bytes()), "v1_3_2": sha_bytes(V132_LOCK.read_bytes())}, "bank_generated_by_agent": False, "model_contact_performed": False}
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": "SEALED_ASSIGNMENT_LOCK", "sha256": lock["assignment_sha256"], "lock_sha256": sha_bytes(LOCK.read_bytes()), "numpy_version": np.__version__, "empty_count": 5, "pc_ordinal_counts": [8, 8, 8, 8], "difficulty_nonempty_ordinal_counts": [6, 7, 7, 7]}, indent=2))


if __name__ == "__main__":
    main()

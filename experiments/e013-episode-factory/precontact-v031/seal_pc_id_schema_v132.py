#!/usr/bin/env python3
"""Seal the action-ID compatibility correction for the E012 PC construction lock."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum")
WORK = Path(r"C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust\experiments\e013-episode-factory\precontact-v031")
PARENT = ROOT / "E012-POSITIVE-CONTROL-RESERVE-POLICY-AMENDMENT-v1.3.1.md"
PARENT_LOCK = ROOT / "E012-POSITIVE-CONTROL-RESERVE-POLICY-LOCK-v1.3.1.json"
PARENT_VERIFY = ROOT / "E012-POSITIVE-CONTROL-RESERVE-POLICY-VERIFICATION-v1.3.1.json"
OUTPUT = ROOT / "E012-PC-ACTION-ID-SCHEMA-AMENDMENT-v1.3.2.md"
LOCK = ROOT / "E012-PC-ACTION-ID-SCHEMA-LOCK-v1.3.2.json"
VERIFY = ROOT / "E012-PC-ACTION-ID-SCHEMA-VERIFICATION-v1.3.2.json"
SCRIPT = WORK / "seal_pc_id_schema_v132.py"
PARENT_SHA = "ED37D45DE3DCB51367BA5F0BC56D82B318E0096682008766A9DBF4B4A9CDBDE8"
PARENT_LOCK_SHA = "1C8016C95C78C8FE2531644DF8F18431BB8EE24BA66EC25322517A2A14BF5EA1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_parent() -> dict:
    if sha(PARENT).upper() != PARENT_SHA or sha(PARENT_LOCK).upper() != PARENT_LOCK_SHA:
        raise RuntimeError("v1.3.1 parent bytes changed")
    lock = json.loads(PARENT_LOCK.read_text(encoding="utf-8-sig"))
    receipt = json.loads(PARENT_VERIFY.read_text(encoding="utf-8-sig"))
    if receipt.get("state") != "PASS" or receipt.get("lock_sha256", "").upper() != PARENT_LOCK_SHA:
        raise RuntimeError("v1.3.1 parent verification is not passing")
    if lock.get("bank_owner") != "USER" or lock.get("model_contact_performed") is not False:
        raise RuntimeError("construction or model-contact boundary changed")
    return lock


AMENDMENT_TEXT = """# E012 Positive-Control Action-ID Schema Amendment v1.3.2

**Amends:** only the identifier encoding in `E012-POSITIVE-CONTROL-RESERVE-POLICY-AMENDMENT-v1.3.1.md`.  
**State:** `PREAUTHORING_SCHEMA_CORRECTION_SEALED; BANK_NOT_BUILT`  
**Bank owner:** user

The v1.3.1 reserve policy described candidate IDs as 16-byte hex strings. That conflicts with the frozen E009 v5 output schema, whose `action_choice` accepts only integers from 0 through 65,535 or `null`. Correct the identifier encoding before assigning any task or candidate IDs. All other v1.3/v1.3.1 rules remain unchanged.

## Locked ID encoding and draw order

- Task IDs are 128-bit opaque lowercase hexadecimal strings generated with `Generator(PCG64(opaque_ids_child)).bytes(16).hex()`. They must be unique across the 80 core/reserve task records; retry a duplicate by consuming the next draw.
- Candidate/action IDs are unsigned 16-bit integers in `[0, 65535]`, matching `observer-output.v2.json`. They must be unique among the four candidates within each task. A duplicate within that task consumes the next integer draw; uniqueness across different tasks is not required.
- Construct the generator from the fifth child returned by the single frozen `SeedSequence(13064).spawn(5)` call. Use the NumPy version recorded in the environment lock. Do not seed a second RNG or mix in task content.
- Draw core IDs first in canonical cell order (repository index ascending; cohort order `PC`, then `difficulty`; family index ascending), then task slot ascending. For each task draw its task ID, then four candidate/action IDs in producer-ordinal order. After all 64 core tasks, draw reserve IDs in the same canonical cell order and reserve-rank order; for each reserve draw its task ID, then its four candidate/action IDs in producer-ordinal order.
- Draw order is independent of candidate role and validity. The ID stream is not reseeded per cell. Record the complete task/action ID map and its hash before label access; preserve the stream version and collision retries in the receipt.

This corrects representation only. It does not alter task/candidate order, the v1.3.1 reserve mapping, task counts, rubric requirements, or authority semantics. No bank is built and no model is contacted by this amendment.
"""


def outputs() -> dict[Path, bytes]:
    parent = check_parent()
    body = AMENDMENT_TEXT.encode("utf-8")
    paths = {"amendment": OUTPUT, "generator": SCRIPT, "parent_amendment_v131": PARENT, "parent_lock_v131": PARENT_LOCK, "parent_verification_v131": PARENT_VERIFY}
    lock = {
        "schema_version": 1,
        "artifact_id": "E012-PC-ACTION-ID-SCHEMA-v1.3.2",
        "state": "PREAUTHORING_SCHEMA_CORRECTION_SEALED_BANK_NOT_BUILT",
        "parent_amendment_sha256": sha(PARENT),
        "parent_lock_sha256": sha(PARENT_LOCK),
        "bank_owner": "USER",
        "bank_generated_by_agent": False,
        "model_contact_performed": False,
        "action_choice_schema_max": 65535,
        "task_id_encoding": "unique 128-bit lowercase hex",
        "candidate_action_id_encoding": "integer uint16 range 0..65535; unique within task",
        "rng": {"seed": 13064, "stream": "opaque_ids fifth SeedSequence child", "algorithm": "numpy Generator(PCG64)", "draw_order": "all core task IDs then action IDs; then all reserves in cell order; record retries and full map"},
        "reserve_policy_inherited_sha256": parent.get("sha256", {}).get("amendment"),
        "artifact_paths": {key: str(value) for key, value in paths.items()},
        "sha256": {key: hashlib.sha256(body).hexdigest() if key == "amendment" else sha(value) for key, value in paths.items()},
        "self_hash_note": "Lock excludes itself and post-lock verification receipt.",
    }
    return {OUTPUT: body, LOCK: (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8")}


def verify() -> dict:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    checks = {}
    for key, value in lock["artifact_paths"].items():
        path = Path(value)
        checks[f"exists:{key}"] = path.is_file()
        if path.is_file():
            checks[f"sha256:{key}"] = sha(path) == lock["sha256"][key]
    check_parent()
    checks["schema_range"] = lock["candidate_action_id_encoding"] == "integer uint16 range 0..65535; unique within task" and lock["action_choice_schema_max"] == 65535
    checks["owner_boundary"] = lock["bank_owner"] == "USER" and lock["bank_generated_by_agent"] is False
    checks["no_contact"] = lock["model_contact_performed"] is False
    return {"artifact_id": "E012-PC-ACTION-ID-SCHEMA-VERIFICATION-v1.3.2", "state": "PASS" if all(checks.values()) else "FAIL", "lock_sha256": sha(LOCK), "checks": checks, "model_contact_performed": False, "bank_generated_by_agent": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.build:
        check_parent()
        files = outputs()
        existing = [str(path) for path in files if path.exists()]
        if existing:
            raise FileExistsError("refusing to overwrite: " + ", ".join(existing))
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
        print(json.dumps({"state": "BUILT", "files": {str(p): hashlib.sha256(data).hexdigest() for p, data in files.items()}}, indent=2))
    else:
        receipt = verify()
        print(json.dumps(receipt, indent=2))
        if receipt["state"] != "PASS":
            raise SystemExit(1)
        if VERIFY.exists():
            raise FileExistsError(f"refusing to overwrite {VERIFY}")
        VERIFY.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

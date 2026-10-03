#!/usr/bin/env python3
"""Seal the precontact reserve-policy amendment for the E012 PC bank."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum")
WORK = Path(r"C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust\experiments\e013-episode-factory\precontact-v031")
PARENT_SPEC = ROOT / "E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-SPEC-v1.3.md"
PARENT_LOCK = ROOT / "E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-LOCK-v1.3.json"
PARENT_VERIFY = ROOT / "E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-VERIFICATION-v1.3.json"
AMENDMENT = ROOT / "E012-POSITIVE-CONTROL-RESERVE-POLICY-AMENDMENT-v1.3.1.md"
LOCK = ROOT / "E012-POSITIVE-CONTROL-RESERVE-POLICY-LOCK-v1.3.1.json"
VERIFY = ROOT / "E012-POSITIVE-CONTROL-RESERVE-POLICY-VERIFICATION-v1.3.1.json"
SCRIPT = WORK / "seal_pc_reserve_v131.py"
PARENT_SPEC_SHA = "7D4BE952441F9619C876A2080D19D0D1D7CE57BF52D59F7F12A84A4AC7A3B254"
PARENT_LOCK_SHA = "0659C005CA2EA03D76164D423F14FD785FB1066CC34D9D1A7B0FCB629A2F958B"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parent_check() -> dict:
    if sha(PARENT_SPEC).upper() != PARENT_SPEC_SHA or sha(PARENT_LOCK).upper() != PARENT_LOCK_SHA:
        raise RuntimeError("sealed v1.3 parent changed")
    parent_lock = json.loads(PARENT_LOCK.read_text(encoding="utf-8-sig"))
    parent_verify = json.loads(PARENT_VERIFY.read_text(encoding="utf-8-sig"))
    if parent_verify.get("state") != "PASS" or parent_verify.get("lock_sha256", "").upper() != PARENT_LOCK_SHA:
        raise RuntimeError("v1.3 parent verification is not passing")
    if parent_lock.get("bank_owner") != "USER" or parent_lock.get("bank_generated_by_agent") is not False:
        raise RuntimeError("bank ownership boundary changed")
    if parent_lock.get("positive_control_bank_status") != "USER_BUILD_PENDING":
        raise RuntimeError("bank is no longer pending user construction")
    return parent_lock


POLICY = {
    "reserve_count_per_cell": 1,
    "cell_count": 16,
    "total_reserves": 16,
    "cell_key_order": ["repository_index ascending", "cohort order PC then difficulty", "family_index ascending"],
    "reserve_rank_per_cell": 0,
    "eligible_primary_slot": 0,
    "replacement_trigger": "eligible primary slot 0 fails a task-local check (reference/candidate execution, determinism, leakage, or per-task T1 runtime) before any observer contact; bank-level quota failures are not replaceable",
    "structural_match": ["same repository/cohort/family cell", "same empty-valid status", "same six-dimension independent-rater score vector", "same preassigned valid-anchor ordinal when nonempty"],
    "candidate_and_label_checks": "reserve must pass every v1.3 reference, leakage, execution-label, determinism, and runtime-bound check before substitution",
    "id_assignment": "use Generator(PCG64(opaque_ids_child)) and 16-byte draws rendered as lowercase hex; core IDs are drawn first in cell_key_order, task_slot ascending, task ID then candidate IDs by producer ordinal; then reserve IDs are drawn in cell_key_order, reserve_rank order, reserve task ID then candidate IDs by producer ordinal; retry collisions by consuming the next 16-byte draw; record NumPy version and the full ID map before label access",
    "consumption": "replace only primary task slot 0 in its own cell; consume at most once; preserve the slot, cell, task class, rubric vector, and valid-anchor ordinal",
    "other_primary_failure": "any rejected primary task outside slot 0 fails bank construction; no cross-slot or cross-cell borrowing",
    "reserve_failure_or_exhaustion": "if the reserve fails any acceptance check, or a second failure occurs in a cell after its one reserve is consumed, bank construction fails; no reserve is generated, repaired, or selected after inspecting observer outputs",
    "unused_reserve": "seal in construction archive as UNUSED_RESERVE; exclude from the 64-task run manifest and all task-level run analyses",
    "rejected_artifacts": "retain rejected primary/reserve bytes, checks, labels, and reasons in the construction failure ledger; never overwrite",
}


def amendment_text() -> str:
    return """# E012 Positive-Control Bank Reserve Policy Amendment v1.3.1

**Amends:** `E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-SPEC-v1.3.md` and its lock only for reserve handling.  
**State:** `PREAUTHORING_AMENDMENT_SEALED; BANK_NOT_BUILT`  
**Bank owner:** user

The sealed v1.3 specification permits use of a “predeclared outcome-blind reserve” but does not freeze the reserve count, ordering, identifiers, consumption trigger, or exhaustion behavior. This amendment closes that construction seam before authoring begins. It does not change the 64-task layout, rubric targets, task labels, analysis rules, positive-control contact authorization, or E013-D/C contact status. The v1.3 files remain byte-for-byte unchanged.

## Locked reserve policy

- Create exactly **one reserve task per repository × cohort × family cell**: 16 reserves total. A reserve is additional construction material, not an additional member of the 64-task bank.
- In each cell, the reserve is preassigned to replace only primary task slot `0`. This target is fixed for every cell before task authoring; no curator chooses a target after seeing a rejection.
- Assign reserve rank `0` in each cell. Traverse cells in repository index ascending, cohort order `PC` then `difficulty`, and family index ascending. Use `Generator(PCG64(opaque_ids_child))`; draw 16 bytes per ID and render as lowercase hex. Draw core IDs first in cell order, then task slot ascending, task ID followed by candidate IDs in producer-ordinal order. Draw reserve IDs afterward in cell/rank order, reserve task ID followed by candidate IDs in producer-ordinal order. On collision, consume the next 16-byte draw. Record the exact NumPy version and complete ID map before label access. IDs must not encode reserve status, cell, candidate role, slot, or validity.
- Before any labels are opened, the reserve must match its target slot's repository/cohort/family cell, empty-valid status, six-dimension independent-rater rubric vector, and preassigned valid-anchor ordinal when the target is nonempty. Thus substitution preserves the locked empty quota, difficulty marginals, and ordinal totals.
- Validate each reserve through the full v1.3 pipeline, including execution-only labels, leakage review, two-clean-worktree determinism, and the T1 construction-time ceiling. A reserve is eligible only after it passes every check.
- Consume it only if its mapped primary slot `0` fails a task-local check before observer contact: reference/candidate execution, determinism, leakage, or the per-task T1 runtime ceiling. Replace that slot with its already-validated reserve; do not alter any other task, ordinal, label, or analysis rule. A bank-level quota failure is not replaceable because the matched reserve preserves the original rubric vector.
- A failure in primary slot `1`, `2`, or `3` fails bank construction. A failed reserve or a second rejection in a cell after its reserve is consumed also fails bank construction. Do not borrow from another cell, create a new reserve, or choose among replacements after inspecting observer outputs. Preserve every failure artifact and reason.
- Seal an unused reserve as `UNUSED_RESERVE` in the construction archive. Exclude it from the 64-task run manifest and all task-level run analyses. If consumed, the accepted reserve occupies the original slot and the rejected primary remains in the failure ledger.

## Authorization boundary

This is a construction-only amendment. It does not build any task or bank and does not authorize or perform model contact. The user remains the bank builder. The already-authorized positive-control run can proceed only after the user-built 64-task bank, reserve disposition, and synthetic dry run are sealed. E013-D/C contact remains unauthorized.
"""


def outputs() -> dict[Path, bytes]:
    parent_check()
    amendment = amendment_text().encode("utf-8")
    bindings = {"amendment": AMENDMENT, "generator": SCRIPT, "parent_spec_v13": PARENT_SPEC, "parent_lock_v13": PARENT_LOCK, "parent_verification_v13": PARENT_VERIFY}
    lock = {
        "schema_version": 1,
        "artifact_id": "E012-PC-RESERVE-POLICY-v1.3.1",
        "state": "PREAUTHORING_AMENDMENT_SEALED_BANK_NOT_BUILT",
        "parent_spec_sha256": sha(PARENT_SPEC),
        "parent_lock_sha256": sha(PARENT_LOCK),
        "bank_owner": "USER",
        "bank_generated_by_agent": False,
        "model_contact_performed": False,
        "positive_control_contact_authorization": "unchanged from v1.2; pending user-built sealed bank and dry run",
        "e013_d_c_model_contact_authorized": False,
        "reserve_policy": POLICY,
        "artifact_paths": {key: str(path) for key, path in bindings.items()},
        "sha256": {key: hashlib.sha256(amendment).hexdigest() if key == "amendment" else sha(path) for key, path in bindings.items()},
        "self_hash_note": "Lock excludes itself and post-lock verification receipt.",
    }
    return {AMENDMENT: amendment, LOCK: (json.dumps(lock, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")}


def verify() -> dict:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    checks = {f"exists:{name}": Path(path).is_file() for name, path in lock["artifact_paths"].items()}
    for name, path in lock["artifact_paths"].items():
        if checks[f"exists:{name}"]:
            checks[f"sha256:{name}"] = sha(Path(path)) == lock["sha256"][name]
    parent_check()
    checks["fixed_16_reserves"] = lock["reserve_policy"]["total_reserves"] == 16 and lock["reserve_policy"]["reserve_count_per_cell"] == 1
    checks["slot_zero_only"] = lock["reserve_policy"]["eligible_primary_slot"] == 0
    checks["bank_owner_user"] = lock["bank_owner"] == "USER" and lock["bank_generated_by_agent"] is False
    checks["no_model_contact"] = lock["model_contact_performed"] is False and lock["e013_d_c_model_contact_authorized"] is False
    return {"artifact_id": "E012-PC-RESERVE-POLICY-VERIFICATION-v1.3.1", "state": "PASS" if all(checks.values()) else "FAIL", "lock_sha256": sha(LOCK), "checks": checks, "bank_generated_by_agent": False, "model_contact_performed": False}


def self_test() -> dict:
    parent_check()
    text = amendment_text()
    required = ("16 reserves total", "primary task slot `0`", "six-dimension independent-rater rubric vector", "A failure in primary slot `1`, `2`, or `3` fails bank construction", "exclude it from the 64-task run manifest")
    for phrase in required:
        assert phrase.casefold() in text.casefold(), phrase
    return {"state": "PASS", "reserve_tasks": 16, "reserve_per_cell": 1, "replacement_slot": 0, "core_bank_tasks": 64}


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--build", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    elif args.build:
        self_test()
        files = outputs()
        existing = [str(path) for path in files if path.exists()]
        if existing:
            raise FileExistsError("refusing to overwrite versioned artifacts: " + ", ".join(existing))
        for path, payload in files.items():
            write_new(path, payload)
        print(json.dumps({"state": "BUILT", "sha256": {str(path): hashlib.sha256(payload).hexdigest() for path, payload in files.items()}}, indent=2))
    else:
        result = verify()
        print(json.dumps(result, indent=2))
        if result["state"] != "PASS":
            raise SystemExit(1)
        if VERIFY.exists():
            raise FileExistsError(f"refusing to overwrite {VERIFY}")
        write_new(VERIFY, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()

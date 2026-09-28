from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import seal_e0_v05 as v01


PROJECT_ROOT = v01.PROJECT_ROOT
REPO_ROOT = v01.REPO_ROOT
PROJECT_REL = v01.PROJECT_REL
FREEZE_PATH = PROJECT_ROOT / "contracts" / "e0-freeze-v05-sealed-v02.json"
PROTOCOL_PATH = PROJECT_ROOT / "contracts" / "e2-run-v02-sealed-v02.json"
SEAL_PATH = PROJECT_ROOT / "seals" / "e0-seal-v05.json"
FAILURE_RECEIPT_PATH = PROJECT_ROOT / "audits" / "e0-v05-seal-attempt-failure-v01.json"
EXPECTED_FAILURE_RECEIPT_ID = "FAS_FROZEN_OBSERVER_BUNDLE_E0_V05_SEAL_ATTEMPT_FAILURE_V01"
SEALER_RELATIVE_PATH = (
    "experiments/fas-frozen-observer-bundle-engineering-v01/"
    "source/scripts/seal_e0_v05_v02.py"
)


def add_verified(
    entries_by_path: dict[str, dict[str, Any]],
    path: Path,
    expected_sha: str | None = None,
) -> None:
    relative = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    digest, size = v01.sha256_file(path)
    if expected_sha is not None and digest != expected_sha:
        raise RuntimeError(f"sealed artifact hash mismatch: {relative}")
    row = {"path": relative, "bytes": size, "sha256": digest}
    if relative in entries_by_path and entries_by_path[relative] != row:
        raise RuntimeError(f"conflicting seal entry: {relative}")
    entries_by_path[relative] = row


def main(dry_run: bool = False) -> int:
    for path in (FREEZE_PATH, PROTOCOL_PATH, SEAL_PATH):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing E0 v05 v02 artifact: {path}")

    draft_tree, draft_tree_receipt_sha, draft_tree_root = v01.verify_draft_tree()
    draft = v01.read_json(v01.DRAFT_FREEZE_PATH)
    protocol = v01.read_json(v01.DRAFT_PROTOCOL_PATH)
    predecessor, predecessor_sha = v01.verify_predecessors_and_gates(draft, protocol)

    failure = v01.read_json(FAILURE_RECEIPT_PATH)
    if failure.get("receipt_id") != EXPECTED_FAILURE_RECEIPT_ID or failure.get("not_a_seal") is not True:
        raise RuntimeError("the earlier stopped seal attempt is not preserved with its failure receipt")
    for item in failure.get("preserved_unsealed_outputs", {}).values():
        path = REPO_ROOT / Path(item["path"])
        digest, size = v01.sha256_file(path)
        if digest != item["sha256"] or size != item["bytes"]:
            raise RuntimeError(f"preserved failed-seal artifact changed: {item['path']}")

    frozen_protocol = dict(protocol)
    frozen_protocol["status"] = "E2_V02_FROZEN_NOT_AUTHORIZED"
    frozen_protocol["freeze_note"] = (
        "Protocol bytes are frozen as part of E0 v05. This state does not authorize tokenizer or model contact."
    )
    protocol_data = v01.json_bytes(frozen_protocol)
    protocol_sha = hashlib.sha256(protocol_data).hexdigest()

    frozen = dict(draft)
    frozen["status"] = v01.EXPECTED_STATUS
    frozen["e2_v02_protocol_path"] = PROJECT_REL + "/contracts/e2-run-v02-sealed-v02.json"
    frozen["e2_v02_protocol_sha256"] = protocol_sha
    frozen["frozen_source_sha256"] = dict(draft["frozen_source_sha256"])
    sealer_sha, _ = v01.sha256_file(Path(__file__).resolve())
    frozen["frozen_source_sha256"][SEALER_RELATIVE_PATH] = sealer_sha
    frozen["reviewed_draft_tree"] = {
        "receipt_path": PROJECT_REL + "/audits/e0-e2-draft-integrity-receipt-v08.json",
        "receipt_sha256": draft_tree_receipt_sha,
        "tree_root_sha256": draft_tree_root,
        "status": draft_tree["status"],
        "full_entry_set_and_receipt_manifest_included_in_e0_seal": True,
    }
    frozen["concurrent_gpu_wait_gate"] = dict(draft["concurrent_gpu_wait_gate"])
    frozen["concurrent_gpu_wait_gate"]["receipt_sha256"] = v01.EXPECTED_WAIT_RECEIPT_SHA256
    frozen["amendment"] = dict(draft["amendment"])
    frozen["amendment"]["e2_protocol_frozen_in_e0_v05_seal"] = True
    frozen["amendment"]["seal_remains_model_contact_unauthorized"] = True
    frozen["seal_attempt_history"] = [{
        "failure_receipt_path": PROJECT_REL + "/audits/e0-v05-seal-attempt-failure-v01.json",
        "failure_receipt_sha256": v01.sha256_file(FAILURE_RECEIPT_PATH)[0],
        "disposition": "preserved; superseded by the versioned seal script and contracts in this seal",
    }]
    for key in ("model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized", "observer_fitting_authorized"):
        frozen[key] = False
    freeze_data = v01.json_bytes(frozen)

    entries_by_path: dict[str, dict[str, Any]] = {}

    def add_planned(relative: str, data: bytes) -> None:
        row = {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if relative in entries_by_path and entries_by_path[relative] != row:
            raise RuntimeError(f"conflicting planned seal entry: {relative}")
        entries_by_path[relative] = row
    # Preserve every v08 reviewed draft-tree byte and bind its receipt manifest too.
    for row in draft_tree["entries"]:
        add_verified(entries_by_path, PROJECT_ROOT / Path(row["path"]), row["sha256"])
    add_verified(entries_by_path, v01.DRAFT_TREE_RECEIPT_PATH, draft_tree_receipt_sha)
    add_planned(PROJECT_REL + "/contracts/e0-freeze-v05-sealed-v02.json", freeze_data)
    add_planned(PROJECT_REL + "/contracts/e2-run-v02-sealed-v02.json", protocol_data)

    # Preserve the failed first seal attempt rather than repairing its artifacts in place.
    add_verified(entries_by_path, FAILURE_RECEIPT_PATH)
    add_verified(entries_by_path, PROJECT_ROOT / "contracts" / "e0-freeze-v05.json")
    add_verified(entries_by_path, PROJECT_ROOT / "contracts" / "e2-run-v02.json")
    add_verified(entries_by_path, PROJECT_ROOT / "source" / "scripts" / "seal_e0_v05.py")

    # Carry forward E0 v04 membership and all v05-bound source/contract bytes.
    for row in predecessor["entries"]:
        add_verified(entries_by_path, REPO_ROOT / Path(row["path"]), row["sha256"])
    for relative, expected_sha in frozen["frozen_source_sha256"].items():
        add_verified(entries_by_path, REPO_ROOT / Path(relative), expected_sha)
    add_verified(
        entries_by_path,
        REPO_ROOT / Path(frozen["representation_abi_path"]),
        frozen["representation_abi_sha256"],
    )
    add_verified(
        entries_by_path,
        REPO_ROOT / Path(frozen["panel_world_contract_path"]),
        frozen["panel_world_contract_sha256"],
    )
    add_verified(entries_by_path, PROJECT_ROOT / "seals" / "e0-seal-v04.json", predecessor_sha)

    required_paths = {
        PROJECT_REL + "/contracts/e0-freeze-v05-sealed-v02.json",
        PROJECT_REL + "/contracts/e2-run-v02-sealed-v02.json",
        PROJECT_REL + "/contracts/representation-abi-v02.json",
        PROJECT_REL + "/audits/e0-e2-draft-integrity-receipt-v08.json",
        PROJECT_REL + "/audits/e2-v02-concurrent-wait-complete-v01.json",
        SEALER_RELATIVE_PATH,
        PROJECT_REL + "/audits/e0-v05-seal-attempt-failure-v01.json",
    }
    missing = required_paths - entries_by_path.keys()
    if missing:
        raise RuntimeError(f"E0 v05 seal membership is missing required artifacts: {sorted(missing)}")
    if PROJECT_REL + "/contracts/e0-freeze-v02.json" in entries_by_path:
        raise RuntimeError("unexpected E0 v02 freeze entry; refusing ambiguous seal membership")

    entries = sorted(entries_by_path.values(), key=lambda row: row["path"])
    seal_root = v01.tree_root(entries)
    if dry_run:
        print(f"E0 v05 dry-run membership PASS: planned_root_sha256={seal_root}; entries={len(entries)}")
        return 0
    v01.write_exclusive(PROTOCOL_PATH, protocol_data)
    v01.write_exclusive(FREEZE_PATH, freeze_data)
    seal = {
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_SEAL_V05",
        "status": v01.EXPECTED_STATUS,
        "root_sha256": seal_root,
        "entry_count": len(entries),
        "entries": entries,
        "freeze_contract_path": PROJECT_REL + "/contracts/e0-freeze-v05-sealed-v02.json",
        "e2_protocol_path": PROJECT_REL + "/contracts/e2-run-v02-sealed-v02.json",
        "predecessor_e0_root_sha256": v01.EXPECTED_E0_V04_ROOT,
        "predecessor_e0_seal_manifest_sha256": predecessor_sha,
        "e1_v04_root_sha256": v01.EXPECTED_E1_V04_ROOT,
        "e2_v01_preservation_root_sha256": v01.EXPECTED_E2_V01_ROOT,
        "reviewed_draft_tree_root_sha256": draft_tree_root,
        "e2_v01_reference_cache": {
            "path": str(Path(protocol["representation_equivalence"]["reference_cache_path"])),
            "sha256": v01.EXPECTED_REFERENCE_CACHE_SHA256,
            "bytes": v01.EXPECTED_REFERENCE_CACHE_BYTES,
            "role": "read-only comparator only; not eligible for fitting",
        },
        "wait_receipt_sha256": v01.EXPECTED_WAIT_RECEIPT_SHA256,
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "feature_extraction_authorized": False,
        "observer_fitting_authorized": False,
        "seal_created_utc": datetime.now(timezone.utc).isoformat(),
    }
    v01.write_exclusive(SEAL_PATH, v01.json_bytes(seal))
    print(f"E0 v05 sealed: root_sha256={seal_root}; entries={len(entries)}; model_contact_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry_run="--dry-run" in sys.argv[1:]))

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = PROJECT_ROOT.relative_to(REPO_ROOT).as_posix()
DRAFT_FREEZE_PATH = PROJECT_ROOT / "contracts" / "e0-freeze-v05-draft.json"
DRAFT_PROTOCOL_PATH = PROJECT_ROOT / "contracts" / "e2-run-v02-draft.json"
DRAFT_TREE_RECEIPT_PATH = PROJECT_ROOT / "audits" / "e0-e2-draft-integrity-receipt-v08.json"
FREEZE_PATH = PROJECT_ROOT / "contracts" / "e0-freeze-v05.json"
PROTOCOL_PATH = PROJECT_ROOT / "contracts" / "e2-run-v02.json"
SEAL_PATH = PROJECT_ROOT / "seals" / "e0-seal-v05.json"
EXPECTED_E0_V04_ROOT = "fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2"
EXPECTED_E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
EXPECTED_REFERENCE_CACHE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
EXPECTED_REFERENCE_CACHE_BYTES = 872_415_232
EXPECTED_WAIT_RECEIPT_SHA256 = "b926124f9aa55b1b9fec2d794d0ac6a7a808128d43df9d53babb6cf143454b80"
EXPECTED_WAIT_RELATIVE_PATH = (
    "experiments/fas-frozen-observer-bundle-engineering-v01/"
    "audits/e2-v02-concurrent-wait-complete-v01.json"
)
EXPECTED_SEALER_RELATIVE_PATH = (
    "experiments/fas-frozen-observer-bundle-engineering-v01/"
    "source/scripts/seal_e0_v05.py"
)
EXPECTED_STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
GPU_SCOPE_CLAIM = (
    "E2 GPU gate = extractor-process PyTorch CUDA caching-allocator reserved peak; "
    "not total GPU memory used by E2."
)


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(entries, key=lambda item: item["path"]):
        digest.update(f'{row["path"]}\t{row["bytes"]}\t{row["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def verify_draft_tree() -> tuple[dict[str, Any], str, str]:
    receipt = read_json(DRAFT_TREE_RECEIPT_PATH)
    if receipt.get("receipt_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E0_E2_DRAFT_INTEGRITY_RECEIPT_V08":
        raise RuntimeError("the seal input is not the reviewed v08 draft-tree receipt")
    if receipt.get("not_a_seal") is not True:
        raise RuntimeError("v08 draft-tree receipt has an invalid disposition")
    actual_entries: list[dict[str, Any]] = []
    for row in receipt.get("entries", []):
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("v08 draft-tree receipt contains an escaping path")
        path = PROJECT_ROOT / relative
        digest, size = sha256_file(path)
        if digest != row["sha256"] or size != row["bytes"]:
            raise RuntimeError(f"v08 draft-tree artifact changed: {relative.as_posix()}")
        actual_entries.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    if tree_root(actual_entries) != receipt.get("draft_tree_sha256"):
        raise RuntimeError("v08 draft-tree root mismatch")
    required = {
        "README.md",
        "contracts/e0-freeze-v05-draft.json",
        "contracts/e2-run-v02-draft.json",
        "contracts/representation-abi-v02.json",
        "source/scripts/extract_features_v02.py",
        "source/tests/test_e2_resource_v02.py",
        "audits/e0-e2-process-gpu-update-v05-draft.md",
        "audits/e2-v02-concurrent-wait-complete-v01.json",
    }
    if not required.issubset({row["path"] for row in actual_entries}):
        raise RuntimeError("v08 draft-tree receipt omits a required E0/E2 review input")
    receipt_sha, _ = sha256_file(DRAFT_TREE_RECEIPT_PATH)
    return receipt, receipt_sha, tree_root(actual_entries)


def verify_predecessors_and_gates(draft: dict[str, Any], protocol: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if draft.get("status") != "E0_V05_DRAFT_NOT_FROZEN":
        raise RuntimeError("E0 v05 draft status is not the expected pre-seal state")
    if any(draft.get(key) is not False for key in (
        "model_contact_authorized", "tokenizer_contact_authorized",
        "feature_extraction_authorized", "observer_fitting_authorized",
    )):
        raise RuntimeError("E0 draft crosses an authorization boundary")
    amendment = draft.get("amendment", {})
    if amendment.get("predecessor_e0_root_sha256") != EXPECTED_E0_V04_ROOT:
        raise RuntimeError("E0 v05 draft does not preserve the E0 v04 predecessor root")
    if amendment.get("e1_v04_root_sha256_preserved") != EXPECTED_E1_V04_ROOT:
        raise RuntimeError("E0 v05 draft does not preserve the E1 v04 root")
    if amendment.get("e2_v01_preservation_root_sha256_preserved") != EXPECTED_E2_V01_ROOT:
        raise RuntimeError("E0 v05 draft does not preserve the E2 v01 attempt root")

    predecessor_seal = PROJECT_ROOT / "seals" / "e0-seal-v04.json"
    predecessor = read_json(predecessor_seal)
    if predecessor.get("root_sha256") != EXPECTED_E0_V04_ROOT:
        raise RuntimeError("the E0 v04 predecessor seal root does not match")
    if tree_root(predecessor.get("entries", [])) != predecessor.get("root_sha256"):
        raise RuntimeError("the E0 v04 predecessor seal has invalid entry membership")
    predecessor_sha, _ = sha256_file(predecessor_seal)
    if amendment.get("predecessor_e0_seal_manifest_sha256") != predecessor_sha:
        raise RuntimeError("E0 v05 draft does not bind the exact E0 v04 manifest bytes")

    if protocol.get("protocol_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V02":
        raise RuntimeError("E2 v02 draft protocol identity mismatch")
    if protocol.get("status") != "E2_V02_DRAFT_NOT_AUTHORIZED":
        raise RuntimeError("E2 v02 input is not the preserved draft protocol")
    if protocol.get("authority", {}).get("model_contact_authorized") is not False:
        raise RuntimeError("E2 v02 draft authorizes model contact")
    if protocol.get("authority", {}).get("feature_extraction_authorized") is not False:
        raise RuntimeError("E2 v02 draft authorizes extraction")

    e2_path = draft.get("e2_v02_protocol_path")
    e2_sha, _ = sha256_file(REPO_ROOT / Path(e2_path))
    if e2_sha != draft.get("e2_v02_protocol_sha256"):
        raise RuntimeError("E0 draft's E2 v02 draft-protocol binding is stale")
    abi_path = REPO_ROOT / Path(draft["representation_abi_path"])
    abi_sha, _ = sha256_file(abi_path)
    if abi_sha != draft.get("representation_abi_sha256"):
        raise RuntimeError("E0 draft's representation ABI v02 binding is stale")
    abi = read_json(abi_path)
    extractor_path = REPO_ROOT / Path(draft["extractor_source_path"])
    extractor_sha, _ = sha256_file(extractor_path)
    if extractor_sha != draft.get("extractor_source_sha256"):
        raise RuntimeError("E0 draft's extractor source binding is stale")
    if abi.get("extractor_source_sha256") != extractor_sha:
        raise RuntimeError("representation ABI v02 does not bind the frozen extractor source")
    gpu = draft["resource_limits"]["gpu_measurement_protocol"]
    if gpu.get("scope_claim_exact") != GPU_SCOPE_CLAIM or gpu.get("total_gpu_memory_claimed") is not False:
        raise RuntimeError("E0 v05 GPU claim does not have the exact required scope")
    if protocol.get("gpu_measurement", {}).get("scope_claim_exact") != GPU_SCOPE_CLAIM:
        raise RuntimeError("E2 v02 GPU claim differs from the E0 v05 scope")
    if protocol.get("gpu_measurement", {}).get("terminal_receipt_required_values") != {"total_gpu_memory_claimed": False}:
        raise RuntimeError("E2 terminal-receipt memory-scope value is not explicitly false")

    equivalence = protocol.get("representation_equivalence", {})
    frozen_equivalence = draft.get("representation_equivalence_gate", {})
    for key in ("reference_cache_path", "reference_cache_sha256", "reference_cache_bytes"):
        if equivalence.get(key) != frozen_equivalence.get(key):
            raise RuntimeError(f"E0/E2 cache equivalence binding differs for {key}")
    if equivalence.get("reference_cache_sha256") != EXPECTED_REFERENCE_CACHE_SHA256:
        raise RuntimeError("the pinned E2 v01 comparator cache hash is unexpected")
    if equivalence.get("reference_cache_bytes") != EXPECTED_REFERENCE_CACHE_BYTES:
        raise RuntimeError("the pinned E2 v01 comparator cache length is unexpected")
    reference_path = Path(equivalence["reference_cache_path"])
    reference_sha, reference_size = sha256_file(reference_path)
    if reference_sha != EXPECTED_REFERENCE_CACHE_SHA256 or reference_size != EXPECTED_REFERENCE_CACHE_BYTES:
        raise RuntimeError("the preserved E2 v01 reference cache failed exact hash/length verification")

    wait_gate = draft.get("concurrent_gpu_wait_gate", {})
    wait_path = REPO_ROOT / Path(wait_gate.get("receipt_path", ""))
    if wait_path.relative_to(REPO_ROOT).as_posix() != EXPECTED_WAIT_RELATIVE_PATH:
        raise RuntimeError("E0 wait receipt path differs from the reviewed canonical path")
    wait_sha, _ = sha256_file(wait_path)
    if wait_sha != EXPECTED_WAIT_RECEIPT_SHA256:
        raise RuntimeError("completed concurrent-run wait receipt hash changed")
    wait = read_json(wait_path)
    if wait.get("status") != "WAIT_COMPLETE_STABLE_ABSENCE" or wait.get("model_contact_performed_by_waiter") is not False:
        raise RuntimeError("S12 concurrent-run wait receipt is not a clean completed wait")
    if wait.get("matching_script_processes_at_final_sample") != [] or wait.get("stable_absent_samples") != 2:
        raise RuntimeError("S12 wait receipt does not document stable process absence")
    if protocol.get("wait_gate", {}).get("receipt_path") != EXPECTED_WAIT_RELATIVE_PATH:
        raise RuntimeError("E2 v02 wait receipt path differs from E0 v05")
    return predecessor, predecessor_sha


def write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    for path in (FREEZE_PATH, PROTOCOL_PATH, SEAL_PATH):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing E0 v05 artifact: {path}")

    draft_tree, draft_tree_sha, draft_tree_root_sha = verify_draft_tree()
    draft = read_json(DRAFT_FREEZE_PATH)
    protocol = read_json(DRAFT_PROTOCOL_PATH)
    predecessor, predecessor_sha = verify_predecessors_and_gates(draft, protocol)

    # Freeze the already-reviewed E2 contract without granting any model contact.
    frozen_protocol = dict(protocol)
    frozen_protocol["status"] = "E2_V02_FROZEN_NOT_AUTHORIZED"
    frozen_protocol["freeze_note"] = (
        "Protocol bytes are frozen as part of E0 v05. This state does not authorize tokenizer or model contact."
    )
    protocol_data = json_bytes(frozen_protocol)
    protocol_sha = hashlib.sha256(protocol_data).hexdigest()

    frozen = dict(draft)
    frozen["status"] = EXPECTED_STATUS
    frozen["e2_v02_protocol_path"] = PROJECT_REL + "/contracts/e2-run-v02.json"
    frozen["e2_v02_protocol_sha256"] = protocol_sha
    frozen["frozen_source_sha256"] = dict(draft["frozen_source_sha256"])
    sealer_sha, _ = sha256_file(Path(__file__).resolve())
    frozen["frozen_source_sha256"][EXPECTED_SEALER_RELATIVE_PATH] = sealer_sha
    frozen["reviewed_draft_tree"] = {
        "receipt_path": PROJECT_REL + "/audits/e0-e2-draft-integrity-receipt-v08.json",
        "receipt_sha256": draft_tree_sha,
        "tree_root_sha256": draft_tree_root_sha,
        "status": draft_tree["status"],
        "full_entry_set_included_in_e0_seal": True,
    }
    frozen["concurrent_gpu_wait_gate"] = dict(draft["concurrent_gpu_wait_gate"])
    frozen["concurrent_gpu_wait_gate"]["receipt_sha256"] = EXPECTED_WAIT_RECEIPT_SHA256
    frozen["amendment"] = dict(draft["amendment"])
    frozen["amendment"]["e2_protocol_frozen_in_e0_v05_seal"] = True
    frozen["amendment"]["seal_remains_model_contact_unauthorized"] = True
    frozen["model_contact_authorized"] = False
    frozen["tokenizer_contact_authorized"] = False
    frozen["feature_extraction_authorized"] = False
    frozen["observer_fitting_authorized"] = False
    freeze_data = json_bytes(frozen)

    write_exclusive(PROTOCOL_PATH, protocol_data)
    write_exclusive(FREEZE_PATH, freeze_data)

    entries_by_path: dict[str, dict[str, Any]] = {}

    def add_verified(path: Path, expected_sha: str | None = None) -> None:
        relative = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        digest, size = sha256_file(path)
        if expected_sha is not None and digest != expected_sha:
            raise RuntimeError(f"sealed artifact hash mismatch: {relative}")
        row = {"path": relative, "bytes": size, "sha256": digest}
        prior = entries_by_path.get(relative)
        if prior is not None and prior != row:
            raise RuntimeError(f"conflicting seal entry: {relative}")
        entries_by_path[relative] = row

    # Include every artifact in the reviewed v08 draft tree, not just its receipt.
    for row in draft_tree["entries"]:
        add_verified(PROJECT_ROOT / Path(row["path"]), row["sha256"])
    add_verified(FREEZE_PATH, hashlib.sha256(freeze_data).hexdigest())
    add_verified(PROTOCOL_PATH, protocol_sha)

    # Carry the complete E0 v04 predecessor seal membership forward, then add the
    # source/contract bytes directly bound by the E0 v05 freeze.
    for row in predecessor["entries"]:
        add_verified(REPO_ROOT / Path(row["path"]), row["sha256"])
    for relative, expected_sha in frozen["frozen_source_sha256"].items():
        add_verified(REPO_ROOT / Path(relative), expected_sha)
    add_verified(REPO_ROOT / Path(frozen["representation_abi_path"]), frozen["representation_abi_sha256"])
    add_verified(REPO_ROOT / Path(frozen["panel_world_contract_path"]), frozen["panel_world_contract_sha256"])
    add_verified(PROJECT_ROOT / "seals" / "e0-seal-v04.json", predecessor_sha)

    required_paths = {
        PROJECT_REL + "/contracts/e0-freeze-v05.json",
        PROJECT_REL + "/contracts/e2-run-v02.json",
        PROJECT_REL + "/contracts/representation-abi-v02.json",
        PROJECT_REL + "/audits/e0-e2-draft-integrity-receipt-v08.json",
        EXPECTED_WAIT_RELATIVE_PATH,
        EXPECTED_SEALER_RELATIVE_PATH,
    }
    if not required_paths.issubset(entries_by_path):
        raise RuntimeError("E0 v05 seal membership is missing a required v05 artifact")
    if PROJECT_REL + "/contracts/e0-freeze-v02.json" in entries_by_path:
        raise RuntimeError("unexpected E0 v02 freeze entry; refusing ambiguous seal membership")
    entries = sorted(entries_by_path.values(), key=lambda row: row["path"])
    root = tree_root(entries)
    seal = {
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_SEAL_V05",
        "status": EXPECTED_STATUS,
        "root_sha256": root,
        "entry_count": len(entries),
        "entries": entries,
        "predecessor_e0_root_sha256": EXPECTED_E0_V04_ROOT,
        "predecessor_e0_seal_manifest_sha256": predecessor_sha,
        "e1_v04_root_sha256": EXPECTED_E1_V04_ROOT,
        "e2_v01_preservation_root_sha256": EXPECTED_E2_V01_ROOT,
        "reviewed_draft_tree_root_sha256": draft_tree_root_sha,
        "e2_v01_reference_cache": {
            "path": str(Path(protocol["representation_equivalence"]["reference_cache_path"])),
            "sha256": EXPECTED_REFERENCE_CACHE_SHA256,
            "bytes": EXPECTED_REFERENCE_CACHE_BYTES,
            "role": "read-only comparator only; not eligible for fitting",
        },
        "wait_receipt_sha256": EXPECTED_WAIT_RECEIPT_SHA256,
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "feature_extraction_authorized": False,
        "observer_fitting_authorized": False,
        "seal_created_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_exclusive(SEAL_PATH, json_bytes(seal))
    print(f"E0 v05 sealed: root_sha256={root}; entries={len(entries)}; model_contact_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

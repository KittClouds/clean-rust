from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
PROJECT = REPO_ROOT / PROJECT_REL
PREDECESSOR_ROOT = "0fec06d018e98203c042a581c01f3f489d5b3e9787c7851cbb9c626c3c63c091"
E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
FREEZE_PATH = PROJECT / "contracts" / "e0-freeze-v10-sealed-v01.json"
PROTOCOL_PATH = PROJECT / "contracts" / "e2-run-v07.json"
ABI_PATH = PROJECT / "contracts" / "representation-abi-v07.json"
PREDECESSOR_SEAL_PATH = PROJECT / "seals" / "e0-seal-v09.json"
SEAL_PATH = PROJECT / "seals" / "e0-seal-v10.json"


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def predecessor_entries(seal: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for entry in seal.get("entries", []):
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe E0 v09 member path: {relative}")
        digest, size = sha256_file(REPO_ROOT / relative)
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"E0 v10 sealed member changed: {relative}")
        rows.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    if len(rows) != seal.get("entry_count") or tree_root(rows) != PREDECESSOR_ROOT:
        raise RuntimeError("E0 v09 predecessor root or entry count failed recomputation")
    return rows


def add_file(entries: dict[str, dict[str, Any]], path: Path) -> None:
    path = path.resolve(strict=True)
    relative = path.relative_to(REPO_ROOT.resolve()).as_posix()
    digest, size = sha256_file(path)
    row = {"path": relative, "bytes": size, "sha256": digest}
    if relative in entries and entries[relative] != row:
        raise RuntimeError(f"conflicting E0 v09 membership row: {relative}")
    entries[relative] = row


def source_path(raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError(f"unsafe freeze source path: {raw}")
    for root in (REPO_ROOT, PROJECT):
        path = root / candidate
        if path.is_file():
            return path
    raise RuntimeError(f"frozen source path is missing: {raw}")


def main() -> int:
    if SEAL_PATH.exists():
        raise RuntimeError(f"refusing to overwrite E0 v10 seal: {SEAL_PATH}")
    predecessor = read_json(PREDECESSOR_SEAL_PATH)
    if predecessor.get("root_sha256") != PREDECESSOR_ROOT or predecessor.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 v09 predecessor identity or authority mismatch")
    entries = {row["path"]: row for row in predecessor_entries(predecessor)}
    freeze = read_json(FREEZE_PATH)
    protocol = read_json(PROTOCOL_PATH)
    abi = read_json(ABI_PATH)
    if freeze.get("freeze_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V10" or freeze.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 v10 freeze identity or closed authority mismatch")
    if protocol.get("protocol_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V07" or any(
        protocol.get("authority", {}).get(key) is not False
        for key in ("model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized", "observer_fitting_authorized", "evaluation_scoring_authorized")
    ):
        raise RuntimeError("E2 v07 identity or closed authority mismatch")
    if abi.get("representation_abi_id") != "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V07":
        raise RuntimeError("representation ABI v07 identity mismatch")
    if sha256_file(PROTOCOL_PATH)[0] != freeze.get("e2_v07_protocol_sha256"):
        raise RuntimeError("canonical E2 v07 protocol byte hash disagrees with E0 v09")
    if sha256_file(ABI_PATH)[0] != freeze.get("representation_abi_sha256"):
        raise RuntimeError("canonical representation ABI byte hash disagrees with E0 v09")

    for mapping in (freeze.get("frozen_source_sha256", {}), freeze.get("validation_source_sha256", {})):
        for relative, expected in mapping.items():
            if sha256_file(source_path(relative))[0] != expected:
                raise RuntimeError(f"E0 v09 source hash mismatch: {relative}")

    history_files = [
        PREDECESSOR_SEAL_PATH,
        PROJECT / "audits" / "e0-v09-independent-audit-v01.json",
        PROJECT / "audits" / "e0-v09-preflight-failure-v01.json",
        PROJECT / "audits" / "e0-v08-independent-audit-failure-v01.json",
        PROJECT / "audits" / "e0-v06-independent-audit-v03.json",
        PROJECT / "audits" / "e2-v02-authorized-attempt-stop-v01.json",
        PROJECT / "audits" / "e2-v03-authorized-attempt-stop-v01.json",
        PROJECT / "audits" / "e2-v03-model-contact-authorization-v01.json",
        PROJECT / "audits" / "e2-v02-concurrent-wait-complete-v01.json",
        FREEZE_PATH,
        PROTOCOL_PATH,
        ABI_PATH,
        PROJECT / "source" / "scripts" / "extract_features_v07.py",
        PROJECT / "source" / "scripts" / "e2_execution_identity_v07.py",
        PROJECT / "source" / "scripts" / "build_e0_v10.py",
        PROJECT / "source" / "scripts" / "seal_e0_v10.py",
        PROJECT / "source" / "scripts" / "audit_e0_v10.py",
        PROJECT / "source" / "tests" / "test_e2_execution_identity_v07.py",
    ]
    for path in history_files:
        if not path.is_file():
            raise RuntimeError(f"required E0 v09 preservation or contract member is missing: {path}")
        add_file(entries, path)

    required = {
        f"{PROJECT_REL}/seals/e0-seal-v09.json",
        f"{PROJECT_REL}/audits/e0-v08-independent-audit-failure-v01.json",
        f"{PROJECT_REL}/audits/e0-v09-independent-audit-v01.json",
        f"{PROJECT_REL}/audits/e0-v09-preflight-failure-v01.json",
        f"{PROJECT_REL}/contracts/e0-freeze-v10-sealed-v01.json",
        f"{PROJECT_REL}/contracts/e2-run-v07.json",
        f"{PROJECT_REL}/contracts/representation-abi-v07.json",
        f"{PROJECT_REL}/source/scripts/extract_features_v07.py",
        f"{PROJECT_REL}/source/scripts/e2_execution_identity_v07.py",
        f"{PROJECT_REL}/source/tests/test_e2_execution_identity_v07.py",
        f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json",
        f"{PROJECT_REL}/audits/e2-v03-authorized-attempt-stop-v01.json",
        f"{PROJECT_REL}/audits/e2-v03-model-contact-authorization-v01.json",
        f"{PROJECT_REL}/audits/e2-v02-concurrent-wait-complete-v01.json",
    }
    missing = required - entries.keys()
    if missing:
        raise RuntimeError(f"E0 v09 required seal members are missing: {sorted(missing)}")

    sorted_entries = sorted(entries.values(), key=lambda row: row["path"])
    seal = {
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_SEAL_V10",
        "status": "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
        "root_sha256": tree_root(sorted_entries),
        "entry_count": len(sorted_entries),
        "entries": sorted_entries,
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "feature_extraction_authorized": False,
        "observer_fitting_authorized": False,
        "evaluation_scoring_authorized": False,
        "total_gpu_memory_claimed": False,
        "freeze_contract_path": f"{PROJECT_REL}/contracts/e0-freeze-v10-sealed-v01.json",
        "e2_protocol_path": f"{PROJECT_REL}/contracts/e2-run-v07.json",
        "representation_abi_path": f"{PROJECT_REL}/contracts/representation-abi-v07.json",
        "predecessor_e0_root_sha256": PREDECESSOR_ROOT,
        "predecessor_e0_seal_manifest_sha256": sha256_file(PREDECESSOR_SEAL_PATH)[0],
        "e1_v04_root_sha256": E1_ROOT,
        "e2_v01_preservation_root_sha256": E2_V01_ROOT,
        "e0_v08_audit_failure_receipt_sha256": sha256_file(PROJECT / "audits" / "e0-v08-independent-audit-failure-v01.json")[0],
        "e0_v09_independent_audit_sha256": sha256_file(PROJECT / "audits" / "e0-v09-independent-audit-v01.json")[0],
        "e0_v09_preflight_failure_receipt_sha256": sha256_file(PROJECT / "audits" / "e0-v09-preflight-failure-v01.json")[0],
        "seal_created_utc": datetime.now(timezone.utc).isoformat(),
    }
    SEAL_PATH.write_bytes((json.dumps(seal, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"status": "E0_V10_SEALED_UNAUDITED", "root_sha256": seal["root_sha256"], "entry_count": seal["entry_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

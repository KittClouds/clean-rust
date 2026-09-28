from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
PROJECT_ROOT = REPO_ROOT / PROJECT_REL
PREDECESSOR_ROOT = "56ab898130ddae394f3fa12a00eccf2bf6e565fde9c58e56f93eb70dde4bd693"
PREDECESSOR_SEAL = PROJECT_ROOT / "seals" / "e0-seal-v05.json"
FREEZE_PATH = PROJECT_ROOT / "contracts" / "e0-freeze-v06.json"
PROTOCOL_PATH = PROJECT_ROOT / "contracts" / "e2-run-v03.json"
ABI_PATH = PROJECT_ROOT / "contracts" / "representation-abi-v03.json"
SEAL_PATH = PROJECT_ROOT / "seals" / "e0-seal-v06.json"
STOP_RECEIPT = PROJECT_ROOT / "audits" / "e2-v02-authorized-attempt-stop-v01.json"
STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"


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


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def verified_entries(root: Path, seal: dict[str, Any]) -> list[dict[str, Any]]:
    actual: list[dict[str, Any]] = []
    for entry in seal["entries"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe predecessor path: {entry['path']}")
        digest, size = sha256_file(root / relative)
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"predecessor artifact changed: {entry['path']}")
        actual.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    if tree_root(actual) != seal.get("root_sha256"):
        raise RuntimeError("E0 v05 predecessor root failed independent recomputation")
    return actual


def add_file(entries: dict[str, dict[str, Any]], path: Path) -> None:
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    digest, size = sha256_file(resolved)
    row = {"path": relative, "bytes": size, "sha256": digest}
    prior = entries.get(relative)
    if prior is not None and prior != row:
        raise RuntimeError(f"conflicting seal membership for {relative}")
    entries[relative] = row


def main() -> int:
    if not REPO_ROOT.is_dir() or not PROJECT_ROOT.is_dir():
        raise RuntimeError("repository or experiment root is missing")
    for path in (FREEZE_PATH, PROTOCOL_PATH, ABI_PATH, SEAL_PATH):
        if path.exists():
            raise RuntimeError(f"refusing to overwrite versioned E0 v06 artifact: {path}")

    predecessor = read_json(PREDECESSOR_SEAL)
    if predecessor.get("root_sha256") != PREDECESSOR_ROOT or predecessor.get("status") != STATUS:
        raise RuntimeError("E0 v05 predecessor identity or status mismatch")
    predecessor_entries = verified_entries(REPO_ROOT, predecessor)
    stop = read_json(STOP_RECEIPT)
    if (
        stop.get("status") != "STOPPED_BEFORE_MODEL_CONTACT_PRESERVE_AND_STOP"
        or stop.get("e0_v05_root_sha256") != PREDECESSOR_ROOT
        or stop.get("model_contact_performed") is not False
    ):
        raise RuntimeError("preserved E2 v02 stop receipt is missing or invalid")

    required_new = [
        PROJECT_ROOT / "contracts" / "e0-freeze-v06.json",
        PROJECT_ROOT / "contracts" / "e2-run-v03.json",
        PROJECT_ROOT / "contracts" / "representation-abi-v03.json",
        PROJECT_ROOT / "source" / "scripts" / "extract_features_v03.py",
        PROJECT_ROOT / "source" / "scripts" / "seal_e0_v06.py",
        PROJECT_ROOT / "source" / "scripts" / "audit_e0_v06.py",
        PROJECT_ROOT / "source" / "scripts" / "build_e0_v06.py",
        PROJECT_ROOT / "audits" / "e0-e2-compatibility-amendment-v06-v03-v01.json",
        PROJECT_ROOT / "audits" / "e2-v02-model-contact-authorization-v01.json",
        STOP_RECEIPT,
        PROJECT_ROOT / "audits" / "e2-v02-preflight-checker-incidents-v01.json",
        PROJECT_ROOT / "audits" / "e2-v02-preflight-checker-incidents-v02.json",
        PROJECT_ROOT / "audits" / "e2-v02-preflight-checker-incidents-v03.json",
        PROJECT_ROOT / "audits" / "e2-v02-operator-preflight-v01.ps1",
        PROJECT_ROOT / "audits" / "e2-v02-operator-preflight-v02.ps1",
        PROJECT_ROOT / "audits" / "e2-v02-operator-preflight-v03.ps1",
        PROJECT_ROOT / "audits" / "e2-v02-operator-preflight-v04.ps1",
        PROJECT_ROOT / "audits" / "e0-v05-independent-seal-audit-v01.json",
    ]
    for path in required_new:
        if not path.is_file():
            raise RuntimeError(f"required v06 preservation or identity artifact is missing: {path}")

    freeze = read_json(FREEZE_PATH)
    protocol = read_json(PROTOCOL_PATH)
    abi = read_json(ABI_PATH)
    if freeze.get("freeze_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06":
        raise RuntimeError("E0 v06 freeze contract ID mismatch")
    if freeze.get("status") != STATUS or freeze.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 v06 is not sealed in an unauthorized state")
    if protocol.get("protocol_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V03":
        raise RuntimeError("E2 v03 protocol ID mismatch")
    if protocol.get("status") != "E2_V03_FROZEN_NOT_AUTHORIZED":
        raise RuntimeError("E2 v03 protocol is not frozen unauthorized")
    if abi.get("representation_abi_id") != "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V03":
        raise RuntimeError("representation ABI v03 ID mismatch")

    entries = {row["path"]: row for row in predecessor_entries}
    add_file(entries, PREDECESSOR_SEAL)
    for path in required_new:
        add_file(entries, path)
    required_paths = {
        f"{PROJECT_REL}/contracts/e0-freeze-v06.json",
        f"{PROJECT_REL}/contracts/e2-run-v03.json",
        f"{PROJECT_REL}/contracts/representation-abi-v03.json",
        f"{PROJECT_REL}/source/scripts/extract_features_v03.py",
        f"{PROJECT_REL}/source/scripts/seal_e0_v06.py",
        f"{PROJECT_REL}/source/scripts/audit_e0_v06.py",
        f"{PROJECT_REL}/source/scripts/build_e0_v06.py",
        f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json",
        f"{PROJECT_REL}/audits/e2-v02-model-contact-authorization-v01.json",
    }
    missing = required_paths - entries.keys()
    if missing:
        raise RuntimeError(f"required v06 seal membership missing: {sorted(missing)}")

    sorted_entries = sorted(entries.values(), key=lambda row: row["path"])
    seal = {
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_SEAL_V06",
        "status": STATUS,
        "root_sha256": tree_root(sorted_entries),
        "entry_count": len(sorted_entries),
        "entries": sorted_entries,
        "freeze_contract_path": f"{PROJECT_REL}/contracts/e0-freeze-v06.json",
        "e2_protocol_path": f"{PROJECT_REL}/contracts/e2-run-v03.json",
        "representation_abi_path": f"{PROJECT_REL}/contracts/representation-abi-v03.json",
        "predecessor_e0_root_sha256": PREDECESSOR_ROOT,
        "predecessor_e0_seal_manifest_sha256": sha256_file(PREDECESSOR_SEAL)[0],
        "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
        "e2_v01_preservation_root_sha256": "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c",
        "e2_v02_stopped_attempt_receipt_sha256": sha256_file(STOP_RECEIPT)[0],
        "e2_v03_protocol_sha256": sha256_file(PROTOCOL_PATH)[0],
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "feature_extraction_authorized": False,
        "observer_fitting_authorized": False,
        "evaluation_scoring_authorized": False,
        "total_gpu_memory_claimed": False,
        "seal_created_utc": datetime.now(timezone.utc).isoformat(),
    }
    with SEAL_PATH.open("xb") as stream:
        stream.write(json_bytes(seal))
        stream.flush()
    print(f"E0 v06 sealed: root_sha256={seal['root_sha256']}; entries={len(sorted_entries)}; model_contact_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

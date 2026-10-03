from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
PROJECT = REPO_ROOT / PROJECT_REL
PREDECESSOR_ROOT = "968e7da8d44e36e31de81e87bdf140e7d766100891cecb7bbf9b4be80e99b3ea"
E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
FREEZE_PATH = PROJECT / "contracts" / "e0-freeze-v07-sealed-v01.json"
PROTOCOL_PATH = PROJECT / "contracts" / "e2-run-v04.json"
ABI_PATH = PROJECT / "contracts" / "representation-abi-v04.json"
PREDECESSOR_SEAL_PATH = PROJECT / "seals" / "e0-seal-v06.json"
SEAL_PATH = PROJECT / "seals" / "e0-seal-v07.json"


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


def verified_predecessor_entries(root: Path, seal: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in seal.get("entries", []):
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe E0 v06 member path: {relative}")
        digest, size = sha256_file(root / relative)
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"E0 v06 sealed member changed: {relative}")
        result.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    if len(result) != seal.get("entry_count") or tree_root(result) != PREDECESSOR_ROOT:
        raise RuntimeError("E0 v06 predecessor root or entry count failed recomputation")
    return result


def add_file(entries: dict[str, dict[str, Any]], path: Path) -> None:
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    digest, size = sha256_file(resolved)
    row = {"path": relative, "bytes": size, "sha256": digest}
    previous = entries.get(relative)
    if previous is not None and previous != row:
        raise RuntimeError(f"conflicting E0 v07 membership row: {relative}")
    entries[relative] = row


def freeze_source_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"unsafe freeze source path: {raw}")
    candidate = REPO_ROOT / path
    if candidate.is_file():
        return candidate
    candidate = PROJECT / path
    if candidate.is_file():
        return candidate
    raise RuntimeError(f"freeze source not found: {raw}")


def main() -> int:
    if SEAL_PATH.exists():
        raise RuntimeError(f"refusing to overwrite E0 v07 seal: {SEAL_PATH}")
    predecessor = read_json(PREDECESSOR_SEAL_PATH)
    if predecessor.get("root_sha256") != PREDECESSOR_ROOT or predecessor.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 v06 predecessor identity or authority mismatch")
    entries = {row["path"]: row for row in verified_predecessor_entries(REPO_ROOT, predecessor)}
    freeze = read_json(FREEZE_PATH)
    protocol = read_json(PROTOCOL_PATH)
    abi = read_json(ABI_PATH)
    if (
        freeze.get("freeze_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V07"
        or freeze.get("status") != STATUS
        or freeze.get("predecessor_e0_root_sha256") != PREDECESSOR_ROOT
        or freeze.get("model_contact_authorized") is not False
    ):
        raise RuntimeError("E0 v07 freeze identity, predecessor, or authority mismatch")
    if protocol.get("protocol_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V04" or any(
        protocol.get("authority", {}).get(key) is not False
        for key in ("model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized", "observer_fitting_authorized", "evaluation_scoring_authorized")
    ):
        raise RuntimeError("E2 v04 protocol identity or closed authority mismatch")
    if abi.get("representation_abi_id") != "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V04":
        raise RuntimeError("representation ABI v04 identity mismatch")

    for relative, expected in {**freeze.get("frozen_source_sha256", {}), **freeze.get("validation_source_sha256", {})}.items():
        path = freeze_source_path(relative)
        digest, _ = sha256_file(path)
        if digest != expected:
            raise RuntimeError(f"E0 v07 frozen source hash mismatch: {relative}")

    preservation_paths = [
        PREDECESSOR_SEAL_PATH,
        PROJECT / "audits" / "e0-v06-independent-audit-v03.json",
        PROJECT / "audits" / "e2-v02-authorized-attempt-stop-v01.json",
        PROJECT / "audits" / "e2-v03-authorized-attempt-stop-v01.json",
        PROJECT / "audits" / "e2-v03-model-contact-authorization-v01.json",
        PROJECT / "audits" / "e2-v02-concurrent-wait-complete-v01.json",
        FREEZE_PATH,
        PROTOCOL_PATH,
        ABI_PATH,
        PROJECT / "source" / "scripts" / "extract_features_v04.py",
        PROJECT / "source" / "scripts" / "e2_execution_identity_v04.py",
        PROJECT / "source" / "scripts" / "build_e0_v07.py",
        PROJECT / "source" / "scripts" / "seal_e0_v07.py",
        PROJECT / "source" / "scripts" / "audit_e0_v07.py",
        PROJECT / "source" / "tests" / "test_e2_execution_identity_v04.py",
    ]
    for path in preservation_paths:
        if not path.is_file():
            raise RuntimeError(f"required E0 v07 preservation/member artifact missing: {path}")
        add_file(entries, path)

    required = {
        f"{PROJECT_REL}/contracts/e0-freeze-v07-sealed-v01.json",
        f"{PROJECT_REL}/contracts/e2-run-v04.json",
        f"{PROJECT_REL}/contracts/representation-abi-v04.json",
        f"{PROJECT_REL}/source/scripts/extract_features_v04.py",
        f"{PROJECT_REL}/source/scripts/e2_execution_identity_v04.py",
        f"{PROJECT_REL}/source/tests/test_e2_execution_identity_v04.py",
        f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json",
        f"{PROJECT_REL}/audits/e2-v03-authorized-attempt-stop-v01.json",
        f"{PROJECT_REL}/audits/e2-v03-model-contact-authorization-v01.json",
        f"{PROJECT_REL}/audits/e2-v02-concurrent-wait-complete-v01.json",
    }
    if required - entries.keys():
        raise RuntimeError(f"E0 v07 membership is missing required paths: {sorted(required - entries.keys())}")

    sorted_entries = sorted(entries.values(), key=lambda row: row["path"])
    seal = {
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_SEAL_V07",
        "status": STATUS,
        "root_sha256": tree_root(sorted_entries),
        "entry_count": len(sorted_entries),
        "entries": sorted_entries,
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "feature_extraction_authorized": False,
        "observer_fitting_authorized": False,
        "evaluation_scoring_authorized": False,
        "total_gpu_memory_claimed": False,
        "freeze_contract_path": f"{PROJECT_REL}/contracts/e0-freeze-v07-sealed-v01.json",
        "e2_protocol_path": f"{PROJECT_REL}/contracts/e2-run-v04.json",
        "representation_abi_path": f"{PROJECT_REL}/contracts/representation-abi-v04.json",
        "predecessor_e0_root_sha256": PREDECESSOR_ROOT,
        "predecessor_e0_seal_manifest_sha256": sha256_file(PREDECESSOR_SEAL_PATH)[0],
        "e1_v04_root_sha256": E1_ROOT,
        "e2_v01_preservation_root_sha256": E2_V01_ROOT,
        "e2_v02_stop_receipt_sha256": sha256_file(PROJECT / "audits" / "e2-v02-authorized-attempt-stop-v01.json")[0],
        "e2_v03_stop_receipt_sha256": sha256_file(PROJECT / "audits" / "e2-v03-authorized-attempt-stop-v01.json")[0],
        "seal_created_utc": datetime.now(timezone.utc).isoformat(),
    }
    SEAL_PATH.write_text(json.dumps(seal, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "E0_V07_SEALED_UNAUDITED", "root_sha256": seal["root_sha256"], "entry_count": seal["entry_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

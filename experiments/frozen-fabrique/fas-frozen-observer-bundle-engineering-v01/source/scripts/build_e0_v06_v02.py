from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
PROJECT_ROOT = REPO_ROOT / PROJECT_REL
FREEZE_V01 = PROJECT_ROOT / "contracts" / "e0-freeze-v06.json"
FREEZE_V02 = PROJECT_ROOT / "contracts" / "e0-freeze-v06-sealed-v02.json"
FAILURE_RECEIPT = PROJECT_ROOT / "audits" / "e0-v06-seal-attempt-failure-v01.json"
EXPECTED_FAILURE_SHA256 = "3ccd35fd76eb0c82cfda8c7c83b4bd7d88a872ad2a418140e1d25d117673864b"


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


def main() -> int:
    if FREEZE_V02.exists():
        raise RuntimeError(f"refusing to overwrite versioned E0 v06 freeze: {FREEZE_V02}")
    if not FREEZE_V01.is_file() or not FAILURE_RECEIPT.is_file():
        raise RuntimeError("preserved v01 draft or failed seal attempt receipt is missing")

    freeze_v01 = read_json(FREEZE_V01)
    failure = read_json(FAILURE_RECEIPT)
    failure_sha, failure_size = sha256_file(FAILURE_RECEIPT)
    if failure_sha != EXPECTED_FAILURE_SHA256:
        raise RuntimeError("preserved v01 seal failure receipt hash mismatch")
    if (
        failure.get("status") != "SEALER_V01_STOPPED_BEFORE_ROOT_PRESERVE_AND_VERSION"
        or failure.get("root_produced") is not False
        or failure.get("seal_manifest_written") is not False
        or failure.get("frozen_contracts_modified") is not False
    ):
        raise RuntimeError("v01 seal failure is not the recorded pre-root, no-mutation stop")
    if (
        freeze_v01.get("freeze_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06"
        or freeze_v01.get("status") != "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
        or freeze_v01.get("model_contact_authorized") is not False
    ):
        raise RuntimeError("preserved v01 draft freeze identity or closed authority mismatch")

    freeze = copy.deepcopy(freeze_v01)
    frozen_sources = dict(freeze["frozen_source_sha256"])
    for name in ("extract_features_v03.py", "seal_e0_v06.py", "audit_e0_v06.py", "build_e0_v06.py"):
        path = PROJECT_ROOT / "source" / "scripts" / name
        relative = f"{PROJECT_REL}/source/scripts/{name}"
        frozen_sources[relative] = sha256_file(path)[0]
    for name in ("seal_e0_v06_v02.py", "audit_e0_v06_v02.py", "build_e0_v06_v02.py"):
        path = PROJECT_ROOT / "source" / "scripts" / name
        relative = f"{PROJECT_REL}/source/scripts/{name}"
        frozen_sources[relative] = sha256_file(path)[0]
    freeze["frozen_source_sha256"] = frozen_sources

    validation_sources = dict(freeze.get("validation_source_sha256", {}))
    validation_sources[f"{PROJECT_REL}/source/scripts/audit_e0_v06.py"] = sha256_file(
        PROJECT_ROOT / "source" / "scripts" / "audit_e0_v06.py"
    )[0]
    validation_sources[f"{PROJECT_REL}/source/scripts/audit_e0_v06_v02.py"] = sha256_file(
        PROJECT_ROOT / "source" / "scripts" / "audit_e0_v06_v02.py"
    )[0]
    freeze["validation_source_sha256"] = validation_sources

    freeze["preseal_version_history"] = {
        "v01_draft_freeze_path": f"{PROJECT_REL}/contracts/e0-freeze-v06.json",
        "v01_draft_freeze_sha256": sha256_file(FREEZE_V01)[0],
        "v01_draft_freeze_disposition": "preserved unchanged as the first E0 v06 draft",
        "v01_sealer_path": f"{PROJECT_REL}/source/scripts/seal_e0_v06.py",
        "v01_sealer_sha256": sha256_file(PROJECT_ROOT / "source/scripts/seal_e0_v06.py")[0],
        "v01_seal_attempt_failure_path": f"{PROJECT_REL}/audits/e0-v06-seal-attempt-failure-v01.json",
        "v01_seal_attempt_failure_sha256": failure_sha,
        "v01_seal_attempt_failure_bytes": failure_size,
        "v01_seal_attempt_disposition": "stopped before root; no seal manifest; inputs unchanged",
        "v02_freeze_disposition": "new final freeze contract identity for corrected sealer path; E2 v03 gates unchanged",
    }
    freeze["seal_contract_path"] = f"{PROJECT_REL}/contracts/e0-freeze-v06-sealed-v02.json"
    freeze["seal_attempt_failure_receipt_path"] = f"{PROJECT_REL}/audits/e0-v06-seal-attempt-failure-v01.json"
    freeze["seal_attempt_failure_receipt_sha256"] = failure_sha
    freeze["fresh_e2_v03_authorization_required_after_independent_audit"] = True

    # The v02 contract may add provenance and helper-source bindings only.
    if freeze["status"] != freeze_v01["status"]:
        raise RuntimeError("v02 freeze changed authority status")
    if freeze["resource_limits"] != freeze_v01["resource_limits"]:
        raise RuntimeError("v02 freeze changed resource limits")
    if freeze["amendment"] != freeze_v01["amendment"]:
        raise RuntimeError("v02 freeze changed the E2 compatibility amendment")

    with FREEZE_V02.open("xb") as stream:
        stream.write(json_bytes(freeze))
        stream.flush()
    digest, size = sha256_file(FREEZE_V02)
    print(f"E0 v06 final freeze v02 prepared: sha256={digest}; bytes={size}; model_contact_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

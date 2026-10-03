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
FREEZE_V03 = PROJECT_ROOT / "contracts" / "e0-freeze-v06-sealed-v03.json"
FAILURE_V01 = PROJECT_ROOT / "audits" / "e0-v06-seal-attempt-failure-v01.json"
FAILURE_V02 = PROJECT_ROOT / "audits" / "e0-v06-seal-attempt-failure-v02.json"


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
    if FREEZE_V03.exists():
        raise RuntimeError(f"refusing to overwrite versioned E0 v06 freeze: {FREEZE_V03}")
    for path in (FREEZE_V01, FREEZE_V02, FAILURE_V01, FAILURE_V02):
        if not path.is_file():
            raise RuntimeError(f"preserved predecessor artifact is missing: {path}")

    base = read_json(FREEZE_V01)
    f1 = read_json(FAILURE_V01)
    f2 = read_json(FAILURE_V02)
    if f1.get("root_produced") is not False or f1.get("seal_manifest_written") is not False:
        raise RuntimeError("preserved v01 seal attempt is not a pre-root stop")
    if f2.get("root_produced") is not False or f2.get("seal_manifest_written") is not False:
        raise RuntimeError("preserved v02 seal attempt is not a pre-root stop")

    freeze = copy.deepcopy(base)
    frozen_sources = dict(freeze["frozen_source_sha256"])
    script_names = (
        "extract_features_v03.py",
        "seal_e0_v06.py",
        "audit_e0_v06.py",
        "build_e0_v06.py",
        "seal_e0_v06_v02.py",
        "audit_e0_v06_v02.py",
        "build_e0_v06_v02.py",
        "seal_e0_v06_v03.py",
        "audit_e0_v06_v03.py",
        "build_e0_v06_v03.py",
    )
    for name in script_names:
        path = PROJECT_ROOT / "source" / "scripts" / name
        frozen_sources[f"{PROJECT_REL}/source/scripts/{name}"] = sha256_file(path)[0]
    freeze["frozen_source_sha256"] = frozen_sources

    validation_sources = dict(freeze.get("validation_source_sha256", {}))
    for name in ("audit_e0_v06.py", "audit_e0_v06_v02.py", "audit_e0_v06_v03.py"):
        path = PROJECT_ROOT / "source" / "scripts" / name
        validation_sources[f"{PROJECT_REL}/source/scripts/{name}"] = sha256_file(path)[0]
    freeze["validation_source_sha256"] = validation_sources

    freeze["preseal_version_history"] = {
        "v01_draft_freeze_path": f"{PROJECT_REL}/contracts/e0-freeze-v06.json",
        "v01_draft_freeze_sha256": sha256_file(FREEZE_V01)[0],
        "v01_seal_attempt_failure_path": f"{PROJECT_REL}/audits/e0-v06-seal-attempt-failure-v01.json",
        "v01_seal_attempt_failure_sha256": sha256_file(FAILURE_V01)[0],
        "v01_sealer_path": f"{PROJECT_REL}/source/scripts/seal_e0_v06.py",
        "v01_sealer_sha256": sha256_file(PROJECT_ROOT / "source/scripts/seal_e0_v06.py")[0],
        "v02_final_freeze_draft_path": f"{PROJECT_REL}/contracts/e0-freeze-v06-sealed-v02.json",
        "v02_final_freeze_draft_sha256": sha256_file(FREEZE_V02)[0],
        "v02_sealer_path": f"{PROJECT_REL}/source/scripts/seal_e0_v06_v02.py",
        "v02_sealer_sha256": sha256_file(PROJECT_ROOT / "source/scripts/seal_e0_v06_v02.py")[0],
        "v02_seal_attempt_failure_path": f"{PROJECT_REL}/audits/e0-v06-seal-attempt-failure-v02.json",
        "v02_seal_attempt_failure_sha256": sha256_file(FAILURE_V02)[0],
        "v02_seal_attempt_disposition": "stopped before root; no seal manifest; freeze unchanged",
        "v03_disposition": "correct source path resolution for both repository-relative and experiment-relative bindings",
    }
    freeze["seal_contract_path"] = f"{PROJECT_REL}/contracts/e0-freeze-v06-sealed-v03.json"
    freeze["seal_attempt_failure_receipt_path"] = f"{PROJECT_REL}/audits/e0-v06-seal-attempt-failure-v01.json"
    freeze["seal_attempt_failure_receipt_sha256"] = sha256_file(FAILURE_V01)[0]
    freeze["seal_attempt_failure_receipts"] = [
        {"path": f"{PROJECT_REL}/audits/e0-v06-seal-attempt-failure-v01.json", "sha256": sha256_file(FAILURE_V01)[0]},
        {"path": f"{PROJECT_REL}/audits/e0-v06-seal-attempt-failure-v02.json", "sha256": sha256_file(FAILURE_V02)[0]},
    ]
    freeze["fresh_e2_v03_authorization_required_after_independent_audit"] = True

    if freeze["status"] != base["status"] or freeze["resource_limits"] != base["resource_limits"]:
        raise RuntimeError("v03 freeze changed authority or substantive resource limits")
    if freeze["amendment"] != base["amendment"]:
        raise RuntimeError("v03 freeze changed the E2 compatibility amendment")
    with FREEZE_V03.open("xb") as stream:
        stream.write(json_bytes(freeze))
        stream.flush()
    digest, size = sha256_file(FREEZE_V03)
    print(f"E0 v06 final freeze v03 prepared: sha256={digest}; bytes={size}; model_contact_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

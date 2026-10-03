from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
SEAL_PATH = PROJECT / "seals" / "runner-correction-seal-v02.json"
PARENT_PROTOCOL_ROOT = "3806a541b09351760f168643d2a46747f26e11ff72c852f04f6c8e91ed88880f"
FILES = (
    "corrections/runner-correction-v02.json",
    "scripts-v02/s04_common_v02.py",
    "scripts-v02/s04_preflight_v02.py",
    "scripts-v02/s04_analyze_v02.py",
    "scripts-v02/s04_seal_results_v02.py",
    "scripts-v02/test_s04_math_v02.py",
    "scripts-v02/seal_runner_v02.py",
)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def root(rows: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']} {row['sha256']}\n" for row in sorted(rows, key=lambda item: item["path"].casefold()))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def verify_parent_protocol() -> None:
    seal = json.loads((PROJECT / "seals" / "protocol-seal-v01.json").read_text(encoding="utf-8"))
    if seal.get("root_sha256") != PARENT_PROTOCOL_ROOT or seal.get("seal_id") != "FAS_S04_PROTOCOL_SEAL_V01":
        raise RuntimeError("Original S04 v01 protocol seal identity differs")
    observed = []
    for row in seal["files"]:
        path = PROJECT / row["path"]
        if not path.is_file() or sha_file(path) != row["sha256"]:
            raise RuntimeError(f"Original S04 v01 protocol member changed: {row['path']}")
        observed.append({"path": row["path"], "sha256": row["sha256"]})
    if root(observed) != PARENT_PROTOCOL_ROOT:
        raise RuntimeError("Original S04 v01 protocol tree does not reproduce")


def main() -> None:
    if SEAL_PATH.exists():
        raise SystemExit("Refusing to replace existing S04 runner-correction seal")
    verify_parent_protocol()
    rows = []
    for relative in FILES:
        path = PROJECT / relative
        if not path.is_file():
            raise SystemExit(f"Missing S04 v02 correction member: {relative}")
        rows.append({"path": relative, "sha256": sha_file(path), "bytes": path.stat().st_size})
    seal = {
        "seal_id": "FAS_S04_RUNNER_CORRECTION_SEAL_V02",
        "status": "PASS",
        "experiment_id": "fas-s04-controlled-factor-to-decision-transfer-geometry-v01",
        "parent_protocol_root_sha256": PARENT_PROTOCOL_ROOT,
        "files": rows,
        "root_sha256": root(rows),
        "scientific_contract_changed": False,
        "model_contact": False,
        "probe_fitting": False,
    }
    SEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEAL_PATH.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S04_RUNNER_CORRECTION_V02_SEALED root={seal['root_sha256']}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[3]
CORRECTION = PROJECT / "corrections" / "input-hash-v02"
SEAL_PATH = CORRECTION / "seals" / "protocol-seal-v02.json"
FILES = (
    "seals/protocol-seal-v01.json",
    "S06-PROTOCOL.md",
    "contracts/analysis-contract-v01.json",
    "contracts/authorization-packet-v01.json",
    "contracts/parent-binding-v01.json",
    "corrections/input-hash-v02/INPUT-HASH-CORRECTION.md",
    "corrections/input-hash-v02/contracts/parent-binding-v02.json",
    "corrections/input-hash-v02/scripts/s06_common.py",
    "corrections/input-hash-v02/scripts/s06_preflight.py",
    "corrections/input-hash-v02/scripts/s06_analyze.py",
    "corrections/input-hash-v02/scripts/test_s06_math.py",
    "corrections/input-hash-v02/scripts/seal_protocol.py",
    "corrections/input-hash-v02/scripts/s06_seal_results.py",
)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if SEAL_PATH.exists():
        raise SystemExit(f"Refusing to overwrite S06 protocol seal: {SEAL_PATH}")
    entries = []
    for relative in FILES:
        path = PROJECT / Path(relative)
        if not path.is_file():
            raise SystemExit(f"Missing protocol artifact: {path}")
        entries.append({"path": relative.replace("\\", "/"), "sha256": sha_file(path), "bytes": path.stat().st_size})
    entries.sort(key=lambda item: item["path"].casefold())
    root_text = "".join(f"{item['path']} {item['sha256']}\n" for item in entries)
    root = hashlib.sha256(root_text.encode("utf-8")).hexdigest()
    seal = {
        "seal_id": "FAS_S06_PROTOCOL_SEAL_V02",
        "status": "SEALED",
        "root_sha256": root,
        "files": entries,
        "supersedes_input_identity_check_only": "FAS_S06_PROTOCOL_SEAL_V01",
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "analysis_execution": False,
    }
    SEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEAL_PATH.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S06_PROTOCOL_SEALED root={root} files={len(entries)}")


if __name__ == "__main__":
    main()

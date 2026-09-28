from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[3]
CORRECTION = PROJECT / "corrections" / "parent-identity-v04"
SEAL_PATH = CORRECTION / "seals" / "protocol-seal-v04.json"
FILES = (
    "S05-PROTOCOL.md",
    "contracts/analysis-contract-v01.json",
    "contracts/authorization-packet-v01.json",
    "contracts/parent-binding-v01.json",
    "seals/protocol-seal-v01.json",
    "corrections/parent-seal-verifier-v02/seals/protocol-seal-v02.json",
    "corrections/parent-seal-verifier-v03/seals/protocol-seal-v03.json",
    "corrections/parent-seal-verifier-v02/VERIFIER-CORRECTION.md",
    "corrections/parent-seal-verifier-v03/VERIFIER-CORRECTION.md",
    "corrections/parent-identity-v04/VERIFIER-CORRECTION.md",
    "corrections/parent-identity-v04/scripts/s05_common.py",
    "corrections/parent-identity-v04/scripts/s05_preflight.py",
    "corrections/parent-identity-v04/scripts/s05_analyze.py",
    "corrections/parent-identity-v04/scripts/test_s05_math.py",
    "corrections/parent-identity-v04/scripts/seal_protocol.py",
    "corrections/parent-identity-v04/scripts/s05_seal_results.py",
)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if SEAL_PATH.exists():
        raise SystemExit(f"Refusing to overwrite protocol seal: {SEAL_PATH}")
    entries = []
    for relative in FILES:
        path = PROJECT / Path(relative)
        if not path.is_file():
            raise SystemExit(f"Missing protocol artifact: {path}")
        entries.append({"path": relative.replace("\\", "/"), "sha256": sha_file(path), "bytes": path.stat().st_size})
    entries.sort(key=lambda item: item["path"].casefold())
    root_material = "".join(f"{item['path']} {item['sha256']}\n" for item in entries).encode("utf-8")
    root = hashlib.sha256(root_material).hexdigest()
    seal = {
        "seal_id": "FAS_S05_PROTOCOL_SEAL_V04",
        "status": "SEALED",
        "root_sha256": root,
        "files": entries,
        "supersedes_verification_behavior_only": ["FAS_S05_PROTOCOL_SEAL_V01", "FAS_S05_PROTOCOL_SEAL_V02", "FAS_S05_PROTOCOL_SEAL_V03"],
        "model_contact": False,
        "probe_fitting": False,
        "analysis_execution": False,
    }
    SEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEAL_PATH.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S05_PROTOCOL_SEALED root={root} files={len(entries)}")


if __name__ == "__main__":
    main()

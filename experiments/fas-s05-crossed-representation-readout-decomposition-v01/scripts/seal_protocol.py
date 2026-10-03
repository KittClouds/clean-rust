from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SEAL_PATH = PROJECT / "seals" / "protocol-seal-v01.json"
FILES = (
    "S05-PROTOCOL.md",
    "contracts/analysis-contract-v01.json",
    "contracts/authorization-packet-v01.json",
    "contracts/parent-binding-v01.json",
    "scripts/s05_common.py",
    "scripts/s05_preflight.py",
    "scripts/s05_analyze.py",
    "scripts/test_s05_math.py",
    "scripts/seal_protocol.py",
    "scripts/s05_seal_results.py",
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
        "seal_id": "FAS_S05_PROTOCOL_SEAL_V01",
        "status": "SEALED",
        "root_sha256": root,
        "files": entries,
        "model_contact": False,
        "probe_fitting": False,
        "analysis_execution": False,
    }
    SEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEAL_PATH.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S05_PROTOCOL_SEALED root={root} files={len(entries)}")


if __name__ == "__main__":
    main()

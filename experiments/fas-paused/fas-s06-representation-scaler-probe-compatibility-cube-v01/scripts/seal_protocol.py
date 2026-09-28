from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SEAL_PATH = PROJECT / "seals" / "protocol-seal-v01.json"
FILES = (
    "S06-PROTOCOL.md",
    "contracts/analysis-contract-v01.json",
    "contracts/parent-binding-v01.json",
    "contracts/authorization-packet-v01.json",
    "scripts/s06_common.py",
    "scripts/s06_preflight.py",
    "scripts/s06_analyze.py",
    "scripts/test_s06_math.py",
    "scripts/seal_protocol.py",
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
        "seal_id": "FAS_S06_PROTOCOL_SEAL_V01",
        "status": "SEALED",
        "root_sha256": root,
        "files": entries,
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

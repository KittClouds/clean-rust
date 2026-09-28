from __future__ import annotations

import json
from pathlib import Path

from s08_common import PROJECT, canonical_root, sha_file, write_json


def main() -> None:
    seal_path = PROJECT / "seals" / "protocol-seal-v01.json"
    if seal_path.exists():
        raise RuntimeError(f"Protocol already sealed: {seal_path}")
    files = []
    for path in PROJECT.rglob("*"):
        if not path.is_file() or "seals" in path.relative_to(PROJECT).parts or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(PROJECT).as_posix()
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha_file(path)})
    files.sort(key=lambda item: item["path"])
    if not files:
        raise RuntimeError("No S08 protocol files found")
    root = canonical_root(files, with_bytes=True, casefold=False)
    seal = {
        "seal_id": "FAS_S08_PROTOCOL_SEAL_V01",
        "status": "SEALED",
        "protocol_root_sha256": root,
        "root_sha256": root,
        "algorithm": "SHA256 of ordinal-sorted path<TAB>bytes<TAB>file_sha256 LF rows",
        "files": files,
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "outcome_analysis_started": False,
    }
    write_json(seal_path, seal)
    print(f"FAS_S08_PROTOCOL_SEALED files={len(files)} root={root}")


if __name__ == "__main__":
    main()

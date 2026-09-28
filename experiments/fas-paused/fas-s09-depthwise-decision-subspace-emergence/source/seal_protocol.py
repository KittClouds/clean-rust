from __future__ import annotations

import json
from pathlib import Path

from s09_common import entry_for, tree_root


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    seal_dir = project / "seals"
    seal_dir.mkdir(parents=True, exist_ok=True)
    seal_path = seal_dir / "protocol-seal-v01.json"
    if seal_path.exists():
        raise SystemExit("protocol seal already exists; refusing overwrite")
    included = []
    for path in project.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path == seal_path:
            continue
        if path.suffix in {".md", ".json", ".py"}:
            included.append(path)
    entries = [entry_for(path, project) for path in included]
    entries.sort(key=lambda item: item["path"])
    seal = {
        "seal_id": "FAS_S09_PROTOCOL_SEAL_V01",
        "project_id": "fas-s09-depthwise-decision-subspace-emergence",
        "entries": entries,
        "root_sha256": tree_root(entries),
        "model_loaded": False,
        "features_extracted": False,
        "probes_fitted": False,
    }
    seal_path.write_text(json.dumps(seal, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"protocol_root_sha256={seal['root_sha256']} files={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

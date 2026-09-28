#!/usr/bin/env python3
"""Create the S11 panel-construction v02 tree seal."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SEAL_REL = Path("seals/panel-tree-seal-v02.json")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: seal_panel_tree_v02.py PANEL_ROOT")
    root = Path(sys.argv[1]).resolve()
    seal = root / SEAL_REL
    if not root.is_dir() or seal.exists():
        raise SystemExit("panel root missing or v02 seal already exists")
    seal.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise SystemExit(f"symlink forbidden in sealed tree: {path}")
        rel = path.relative_to(root)
        if rel == SEAL_REL or rel.parts[0] == "verification":
            continue
        rows.append({
            "path": rel.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        })
    rows.sort(key=lambda row: row["path"])
    tree_hash = hashlib.sha256()
    for row in rows:
        tree_hash.update(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n".encode("utf-8"))
    payload = {
        "seal_id": "FAS_S11_PANEL_TREE_SEAL_V02",
        "algorithm": "sha256(sorted path\\tbyte_length\\tfile_sha256\\n)",
        "tree_root_sha256": tree_hash.hexdigest(),
        "included_file_count": len(rows),
        "excluded_paths": [SEAL_REL.as_posix(), "verification/**"],
        "entries": rows,
    }
    temp = seal.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(seal)
    print(f"S11_PANEL_TREE_SEALED files={len(rows)} root={payload['tree_root_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

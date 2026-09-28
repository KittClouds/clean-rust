"""Record exact development source bytes without sealing a flight."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.identity import canonical

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "acceptance/source-manifest-v0.2.json"


def main() -> None:
    paths = [ROOT / "pyproject.toml"]
    for folder in ("ledgerd", "scripts", "tests"):
        paths.extend((ROOT / folder).rglob("*.py"))
    entries = []
    for path in sorted(paths, key=lambda p: p.relative_to(ROOT).as_posix()):
        raw = path.read_bytes()
        entries.append({
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    root = hashlib.sha256(b"kammi-source-v0.2\0" + canonical(entries)).hexdigest()
    report = {
        "schema": "KAMMI_SOURCE_MANIFEST_V0_2",
        "status": "DEVELOPMENT_SNAPSHOT",
        "entry_count": len(entries),
        "source_root_sha256": root,
        "entries": entries,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"entry_count": len(entries), "source_root_sha256": root}))


if __name__ == "__main__":
    main()


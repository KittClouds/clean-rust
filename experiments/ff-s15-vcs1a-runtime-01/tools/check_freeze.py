"""Checks (or, with --seal, writes) the VCS-1a freeze manifest: sha256 of every runtime source, the synthetic golden fixtures and the freeze record.

  python tools/check_freeze.py            # exit 1 if anything frozen has changed
  python tools/check_freeze.py --seal     # only for a dated amendment; see VCS-1A-FREEZE.md
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "vcs1a-freeze.json"


def frozen_files() -> list:
    files = sorted((ROOT / "vcs").glob("*.py")) + sorted((ROOT / "tests" / "fixtures").rglob("*.json")) + [ROOT / "VCS-1A-FREEZE.md", ROOT / "tools" / "make_golden.py"]
    return [p for p in files if p.is_file()]


def digest() -> dict:
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in frozen_files()}


def freeze_id(files: dict) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def main(argv) -> int:
    now = digest()
    if "--seal" in argv:
        MANIFEST.write_text(json.dumps({"schema": "VCS1A_FREEZE_V1", "freeze_id": freeze_id(now), "files": now}, sort_keys=True, indent=1) + "\n", encoding="ascii", newline="\n")
        print("sealed", freeze_id(now), len(now), "files")
        return 0
    rec = json.loads(MANIFEST.read_text(encoding="ascii"))
    bad = sorted(set(rec["files"]) ^ set(now) | {k for k in now if k in rec["files"] and rec["files"][k] != now[k]})
    if bad or rec["freeze_id"] != freeze_id(now):
        print("FROZEN FILES CHANGED:", *bad, sep="\n  ")
        return 1
    print("freeze intact", rec["freeze_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Rebuild a fresh Ladybug projection from only immutable E4 import objects/events."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from ledgerd.core import Ledger

HERE = Path(__file__).resolve().parents[1]
IMPORT = HERE / "acceptance/e4-0/merkle-import-v1.json"
OUTPUT = HERE / "acceptance/e4-0/projection-rebuild-v1.json"


def main() -> None:
    imported = json.loads(IMPORT.read_text(encoding="utf-8"))
    source = Path(imported["disposable_store"])
    target = Path(tempfile.mkdtemp(prefix="kammi-e4-rebuild-"))
    shutil.copytree(source / "objects" / "sha256", target / "objects" / "sha256")
    (target / "journal").mkdir(parents=True)
    shutil.copy2(source / "journal" / "events.log", target / "journal" / "events.log")
    rebuilt = Ledger(target)
    status = rebuilt.status()
    closure = rebuilt.verify_seal(imported["successor_root"])
    same = (
        status["journal_head"] == imported["projection"]["journal_head"]
        and status["projection_head"] == imported["projection"]["projection_head"]
        and status["counts"] == imported["projection"]["counts"]
        and len(closure) == imported["successor_verified_closure_count"]
    )
    report = {
        "schema": "KAMMI_E4_PROJECTION_REBUILD_V1",
        "status": "PASS" if same else "FAIL",
        "rebuilt_from": ["CAS raw bytes", "journal event frames"],
        "original_head": imported["projection"]["journal_head"],
        "rebuilt_head": status["journal_head"],
        "original_counts": imported["projection"]["counts"],
        "rebuilt_counts": status["counts"],
        "verified_closure_count": len(closure),
        "fresh_db_path": str(target / "custody.lbdb"),
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "head": report["rebuilt_head"], "closure": len(closure)}))
    if not same:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


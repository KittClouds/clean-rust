"""Create the immutable pre-execution receipt for Q10-DA2."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: seal_q10_da2.py DA1_QUALIFICATION")
    root = Path(__file__).parents[1]
    source = Path(sys.argv[1]).resolve()
    paths = [
        Path("PLAN.md"),
        Path("CONTRACT.json"),
        Path("q10-da2-config.json"),
        Path("scripts/run_q10_da2.py"),
        Path("scripts/audit_q10_da2.py"),
        Path("scripts/seal_q10_da2.py"),
    ]
    source_manifest = [
        {"path": path.as_posix(), "sha256": digest(root / path)} for path in paths
    ]
    inputs = sorted(source.glob("seed*.json"))
    assert len(inputs) == 8
    receipt = {
        "protocol": "Q10-DA2",
        "status": "FROZEN_PRE_EXECUTION",
        "source_manifest": source_manifest,
        "input_root": str(source),
        "input_sha256": {path.name: digest(path) for path in inputs},
        "parent_protocol": "Q10-DA1",
        "scientific_seed_bundles": 0,
        "behavioral_inference": False,
        "dh08b_authorized": False,
        "selector": "DA1 local mismatch-first choices plus deterministic one/two-coordinate axis correction",
    }
    path = root / "PREEXECUTION.json"
    assert not path.exists()
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"sealed {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

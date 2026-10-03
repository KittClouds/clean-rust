"""Create the immutable pre-execution receipt for Q10-RMT."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: seal_q10_rmt.py DA2_ROOT DA1_QUALIFICATION")
    root = Path(__file__).parents[1]
    da2 = Path(sys.argv[1]).resolve()
    da1 = Path(sys.argv[2]).resolve()
    paths = [
        Path("PLAN.md"),
        Path("CONTRACT.json"),
        Path("q10-rmt-config.json"),
        Path("scripts/run_q10_rmt.py"),
        Path("scripts/audit_q10_rmt.py"),
        Path("scripts/seal_q10_rmt.py"),
        Path("scripts/merge_q10_rmt.py"),
    ]
    receipt = {
        "protocol": "Q10-RMT",
        "status": "FROZEN_PRE_EXECUTION",
        "source_manifest": [{"path": path.as_posix(), "sha256": digest(root / path)} for path in paths],
        "parent_root": str(da2),
        "da2-results-sha256": digest(da2 / "qualification/sample-9731-9732/results.json"),
        "input_root": str(da1),
        "input_sha256": {path.name: digest(path) for path in sorted(da1.glob("seed*.json"))},
        "primary_endpoint_rule": "all Q10-DA2 status DA2_GEOMETRY_PASS records",
        "repair_applied": False,
        "behavioral_inference": False,
        "scientific_seed_bundles": 0,
        "dh08b_authorized": False,
    }
    assert len(receipt["input_sha256"]) == 8
    path = root / "PREEXECUTION.json"
    assert not path.exists()
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"sealed {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

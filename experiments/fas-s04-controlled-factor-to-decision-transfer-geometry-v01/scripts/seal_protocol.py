from __future__ import annotations

import json
from pathlib import Path

from s04_common import PROJECT, canonical_root, sha_file


FILES = (
    "S04-PROTOCOL.md",
    "contracts/analysis-contract-v01.json",
    "contracts/parent-binding-v01.json",
    "contracts/authorization-packet-v01.json",
    "scripts/s04_common.py",
    "scripts/s04_preflight.py",
    "scripts/s04_analyze.py",
    "scripts/s04_seal_results.py",
    "scripts/test_s04_math.py",
    "scripts/seal_protocol.py",
)


def main() -> None:
    path = PROJECT / "seals" / "protocol-seal-v01.json"
    if path.exists():
        raise SystemExit("Refusing to replace existing S04 protocol seal")
    rows = []
    for relative in FILES:
        source = PROJECT / relative
        if not source.is_file():
            raise SystemExit(f"Missing S04 protocol member: {relative}")
        rows.append({"path": relative, "sha256": sha_file(source)})
    seal = {
        "seal_id": "FAS_S04_PROTOCOL_SEAL_V01",
        "experiment_id": "fas-s04-controlled-factor-to-decision-transfer-geometry-v01",
        "files": rows,
        "root_sha256": canonical_root(rows),
        "S04_PROTOCOL_SEALED": True,
        "S04_MODEL_CONTACT": False,
        "S04_PROBE_FITTING": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "SAE_ANALYSIS_AUTHORIZED": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S04_PROTOCOL_SEALED root={seal['root_sha256']}")


if __name__ == "__main__":
    main()

"""Write an integrity receipt for v0.6 and the protected v0.4 boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v06")
V04_CONTRACT = Path(r"C:\code land\clean-rust\experiments\jev-frozen-saturation-v04\v04-contract.json")
V04_GATE = Path(r"D:\codex-runs\jev-frozen-saturation-v04\reports\qlora-final-gate.json")


def receipt(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main() -> None:
    protected = [receipt(V04_CONTRACT), receipt(V04_GATE)]
    v06 = [
        receipt(RUN / "banks" / "scale-manifest.json"),
        receipt(RUN / "reports" / "frozen-scaling-250k.json"),
        receipt(RUN / "reports" / "contradictory-binding-v06.json"),
        receipt(RUN / "reports" / "open-world-v06.json"),
        receipt(RUN / "reports" / "v06-behavior-map.json"),
    ]
    value = {
        "protocol": "jev-frozen-decision-surface-scaling/v0.6",
        "v04_boundary": {
            "protected": protected,
            "qlora_gate_modified": False,
            "result": "v0.4 remains sealed; no new adaptation gate",
        },
        "v06_artifacts": v06,
        "backbone_adaptation": False,
    }
    out = RUN / "v06-integrity-receipt.json"
    out.write_text(json.dumps(value, indent=2), encoding="utf-8")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()

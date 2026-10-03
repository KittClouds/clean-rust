"""Write the read-only v0.4 boundary and v0.5 input integrity receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v05")
V04 = Path(r"D:\codex-runs\jev-frozen-saturation-v04")


def digest(path: Path) -> dict[str, object]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            size += len(block)
            h.update(block)
    return {"path": str(path), "bytes": size, "sha256": h.hexdigest()}


def main() -> None:
    protected = [
        ROOT / "experiments" / "jev-frozen-saturation-v04" / "v04-contract.json",
        V04 / "reports" / "qlora-final-gate.json",
        V04 / "banks" / "split-manifest.json",
        V04 / "run-manifest.json",
    ]
    inputs = [
        RUN / "real-bank" / "manifest.json",
        RUN / "banks" / "scale-manifest.json",
        RUN / "features" / "minicpm5-1b-base" / "minicpm5-1b-base-feature-manifest.json",
        RUN / "features" / "qwen3-0.6b-base" / "qwen3-0.6b-base-feature-manifest.json",
        RUN / "features" / "k2-horizon-0.9b" / "k2-horizon-0.9b-feature-manifest.json",
    ]
    receipt = {
        "protocol": "jev-frozen-decision-surface-scaling/v0.5",
        "created_by": "write_integrity_receipt.py",
        "v04_boundary": {
            "protected": [digest(path) for path in protected if path.exists()],
            "qlora_gate_modified": False,
            "result": "unauthorized_for_all_three_backbones",
        },
        "v05_inputs": [digest(path) for path in inputs if path.exists()],
    }
    output = RUN / "v05-integrity-receipt.json"
    output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()

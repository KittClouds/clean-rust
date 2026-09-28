"""Audit target-class support for the frozen temporal probe splits."""
from __future__ import annotations

import json
import struct
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY / "runs/qualification-v2/f4-features-v1"
MAGIC = b"FLYREACH3F4\0"


def main() -> None:
    support: dict[str, dict[str, int]] = {}
    for path in sorted(ROOT.glob("*.bin")):
        raw = path.read_bytes()
        pos = len(MAGIC)
        version, width = struct.unpack_from("<IH", raw, pos)
        pos += 6
        if raw[: len(MAGIC)] != MAGIC or version != 1 or width != 80:
            raise SystemExit(f"bad feature stream: {path}")
        substrate_len, = struct.unpack_from("<H", raw, pos)
        pos += 2 + substrate_len
        side_len, = struct.unpack_from("<H", raw, pos)
        pos += 2 + side_len
        block, = struct.unpack_from("<Q", raw, pos)
        pos += 8
        record = 4 + 4 + 8 + 1 + width * 4
        for _ in range((len(raw) - pos) // record):
            trial, _coordinate = struct.unpack_from("<II", raw, pos)
            pos += 8 + 8
            target, = struct.unpack_from("<b", raw, pos)
            pos += 1 + width * 4
            split = "train" if trial < 6144 else "validation"
            key = f"{block}:{split}"
            row = support.setdefault(key, {"rows": 0, "positive": 0, "negative": 0})
            row["rows"] += 1
            row["positive" if target > 0 else "negative"] += 1
    for key, row in support.items():
        row["both_classes"] = int(row["positive"] > 0 and row["negative"] > 0)
    output = {
        "schema": "FLY-REACH-03-F4-CAPACITY-01-class-support-audit-v1",
        "identity": "F4-CAPACITY-01",
        "status": "PASS_WITH_DEGENERATE_TEMPORAL_HOLDS",
        "split_rule": "trial < 6144 versus trial >= 6144",
        "support": dict(sorted(support.items())),
        "interpretation_boundary": "temporal Omega_hat is not comparable as balanced two-class evidence when a validation split contains one class only",
        "measured_namespace_created": False,
        "scientific_interpretation_opened": False,
    }
    path = STUDY / "F4-CAPACITY-01-CLASS-SUPPORT-AUDIT.json"
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "splits": len(support)}, sort_keys=True))


if __name__ == "__main__":
    main()

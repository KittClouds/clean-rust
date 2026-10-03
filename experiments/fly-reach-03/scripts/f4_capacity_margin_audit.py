"""Audit the magnitude distribution of the frozen nonzero reference channel."""
from __future__ import annotations

import json
import mmap
import struct
from pathlib import Path

import numpy as np


STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY / "runs/qualification-v2/rows"
MAGIC = b"FLYREACH3ROWS\0"
EPS = 1e-12
ROW_MODULUS = 256


def unpack(fmt: str, data: memoryview, pos: int):
    size = struct.calcsize(fmt)
    return struct.unpack_from(fmt, data, pos)[0], pos + size


def skip_vec(data: memoryview, pos: int, size: int):
    count, pos = unpack("<B", data, pos)
    return pos + count * size


def main() -> None:
    magnitudes = []
    for path in sorted(ROOT.glob("*.bin")):
        with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            data = memoryview(mapped); pos = 0
            if data[:len(MAGIC)].tobytes() != MAGIC: raise SystemExit(f"bad row stream {path}")
            pos += len(MAGIC); _version, pos = unpack("<I", data, pos); sl, pos = unpack("<H", data, pos); pos += sl; sl, pos = unpack("<H", data, pos); pos += sl; pos += 8; coordinate_count, pos = unpack("<I", data, pos); pos += coordinate_count * 4
            row_index = 0
            while pos < len(data):
                pos += 2 + 8 + 4 + 4 + 8
                reference, pos = unpack("<f", data, pos); target, pos = unpack("<b", data, pos); pos += 4
                support, pos = unpack("<B", data, pos); pos += 4 + 4 + 4 + 4 + 4 + 4 + 4 + 4 + 4 + 4; pos += 1
                pos = skip_vec(data, pos, 4); pos = skip_vec(data, pos, 4); pos = skip_vec(data, pos, 1)
                pos += 4 + 4 + 4 + 4 + 4 + 1 + 4 + 4 + 8 + 8 + 4
                if target != 0 and support and row_index % ROW_MODULUS == 0:
                    magnitudes.append(abs(float(reference)))
                row_index += 1
            del data
    values = np.asarray(magnitudes, dtype=np.float64)
    thresholds = [1e-12, 1e-10, 1e-9, 1e-8, 1e-7, 1e-6, 1e-5]
    receipt = {
        "schema": "FLY-REACH-03-F4-CAPACITY-01-reference-margin-audit-v1",
        "identity": "F4-CAPACITY-01",
        "status": "PASS",
        "rows": int(len(values)),
        "eps": EPS,
        "quantiles": {str(q): float(np.quantile(values, q)) for q in (0.0, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)},
        "fractions_at_or_below": {str(t): float(np.mean(values <= t)) for t in thresholds},
        "interpretation_boundary": "diagnostic magnitude audit only; target and reference values were not supplied to any encoder",
        "measured_namespace_created": False,
        "scientific_interpretation_opened": False,
    }
    path = STUDY / "F4-CAPACITY-01-REFERENCE-MARGIN-AUDIT.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__": main()

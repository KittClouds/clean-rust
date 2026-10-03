"""Seal corrected mobility implementation as a fresh external run identity."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import freeze_phase2c_mobility as freezer  # noqa: E402

freezer.DEFAULT_OUT = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\support-mobility-v02")
freezer.SOURCES = freezer.SOURCES + (
    "experiments/jev-information-density-v08c/audit_phase2c_support_mobility_v02.py",
    "experiments/jev-information-density-v08c/freeze_phase2c_mobility_v02.py",
    "experiments/jev-information-density-v08c/support-mobility-v02-correction.md",
    "experiments/jev-information-density-v08c/tests/test_phase2c_support_mobility_v02.py",
)


if __name__ == "__main__":
    raise SystemExit(freezer.main())

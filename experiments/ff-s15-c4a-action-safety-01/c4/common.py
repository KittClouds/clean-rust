"""C4a shared setup: C3a's frontier code and C2a's CAL loader (which verifies C1's evidence against C1's freeze) are reused unchanged."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C3_ROOT = ROOT.parent / "ff-s15-c3a-risk-geometry-01"
if str(C3_ROOT) not in sys.path:
    sys.path.insert(0, str(C3_ROOT))

from c3.common import PRIMARY, SURFACES, c1fit, load_cal, sha256_file  # noqa: E402,F401
from c3.frontier import correct_at_harm  # noqa: E402,F401
from c1.common import ACTIONS  # noqa: E402,F401

RESULTS = ROOT / "results"
LEVELS = (0.03, 0.05, 0.07, 0.10)
GATE_LEVELS = (0.03, 0.05)
MIN_EXECUTIONS = 100
ELIGIBLE_MIN_CANDIDATES, ELIGIBLE_MIN_SAFE = 300, 100
GAIN_BAR = 0.10
PERMUTATIONS, SEED = 100, 20260929
# The only actions that are ever the truth action of an ACT row in BANK-v1: TRAIN (143,996 rows) has NOOP 32,562, MOVE 24,389, ACTIVATE 10,797 and nothing else.
POSSIBLE_ACT_ACTIONS = ("NOOP", "MOVE", "ACTIVATE")

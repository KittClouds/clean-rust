"""C3a shared setup. C2a's loader (which verifies C1's evidence against C1's freeze and masks to CAL on load) is reused unchanged."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C2_ROOT = ROOT.parent / "ff-s15-c2-coordination-01"
if str(C2_ROOT) not in sys.path:
    sys.path.insert(0, str(C2_ROOT))

from c2.common import PRIMARY, SURFACES, fit as c1fit, load_cal, sha256_file  # noqa: E402,F401

RESULTS = ROOT / "results"
LEVELS = (0.03, 0.05, 0.07, 0.10)
MIN_EXECUTIONS = 100
BOOTSTRAPS, SEED = 500, 20260929
GAIN_BAR = 1.10
LEVELS_NEEDED = 3
BOOTSTRAP_PERCENTILE = 1.0

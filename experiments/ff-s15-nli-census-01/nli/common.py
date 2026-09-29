"""NLI census shared setup. The ASK rung (and through it C1 and C0) is imported unchanged."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASK_ROOT = ROOT.parent / "ff-s15-ask-01"
if str(ASK_ROOT) not in sys.path:
    sys.path.insert(0, str(ASK_ROOT))

from ask.common import (BANK, C1_EVIDENCE, C1_FREEZE, DEV_ROWS, DEV_START, PRIMARY, SURFACES, SWEEP, c1fit, canon, rung0, sha256_file, verify_c1_evidence, write_json)  # noqa: E402,F401
from c1 import observers as c1obs  # noqa: E402

EVIDENCE = ROOT / "evidence"
RESULTS = ROOT / "results"
NLI_LABELS = ("ENTAILED", "CONTRADICTED", "UNKNOWN")
UNKNOWN = 2
NLI_SURFACE = "layer_m4_final"  # the Rung 0 lock's "intermediate-layer NLI reference"
TARGET_PRECISION, MIN_ROWS = 0.5, 50
B_GRID = tuple(range(0, 950_001, 50_000))
PERMUTATIONS, SEED = 200, 20260929
GO_THRESHOLD = 0.25

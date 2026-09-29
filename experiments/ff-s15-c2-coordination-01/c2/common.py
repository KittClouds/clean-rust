"""C2 shared setup. C1 (and through it C0) is imported unchanged; C1's evidence is verified against C1's tracked freeze record."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
C1_ROOT = ROOT.parent / "ff-s15-c1-observers-01"
if str(C1_ROOT) not in sys.path:
    sys.path.insert(0, str(C1_ROOT))

from c1 import fit  # noqa: E402
from c1.common import ACTIONS, DECISIONS, SURFACES, PRIMARY, alpha_tag, sha256_file  # noqa: E402,F401

C1_EVIDENCE = C1_ROOT / "evidence"
C1_FREEZE = C1_ROOT / "results" / "freeze.json"
EVIDENCE = ROOT / "evidence"
RESULTS = ROOT / "results"
TAG = alpha_tag(0.05)  # the C2a operating point: C1's primary alpha


def verify_c1_evidence() -> dict:
    """The arrays and thresholds C2 reads must be byte-identical to the ones C1 froze."""
    freeze = json.loads(C1_FREEZE.read_text(encoding="ascii"))
    for key, path in (("ppm_sha256", "dev-ppm.npz"), ("truth_sha256", "dev-truth.npz"), ("thresholds_sha256", "thresholds.json")):
        if sha256_file(C1_EVIDENCE / path) != freeze[key]:
            raise RuntimeError(f"C1 evidence {path} does not match C1's freeze record; regenerate it with run_c1.py prepare and calibrate")
    return freeze


def load_cal() -> dict:
    """Integer ppm arrays, truth and the frozen thresholds for the CAL half only. HOLD rows are masked out on load and never returned."""
    verify_c1_evidence()
    ppm = np.load(C1_EVIDENCE / "dev-ppm.npz", allow_pickle=False)
    truth = np.load(C1_EVIDENCE / "dev-truth.npz", allow_pickle=False)
    cal = ~truth["hold"]
    thresholds = json.loads((C1_EVIDENCE / "thresholds.json").read_text(encoding="ascii"))["thresholds"]
    return {
        "surfaces": {s: {"dec": ppm[f"{s}.decision"][cal], "act": ppm[f"{s}.action_type"][cal]} for s in SURFACES},
        "truth_decision": truth["truth_decision"][cal], "truth_action": truth["truth_action"][cal], "family": truth["family"][cal], "thresholds": thresholds,
    }

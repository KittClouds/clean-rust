"""ASK rung shared setup. C1 (and through it C0) is imported unchanged; C1's evidence is verified against C1's tracked freeze record."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
C1_ROOT = ROOT.parent / "ff-s15-c1-observers-01"
if str(C1_ROOT) not in sys.path:
    sys.path.insert(0, str(C1_ROOT))

from c1 import fit as c1fit, policy as c1policy, records as c1records, rung0  # noqa: E402,F401
from c1.common import (ACTIONS, BANK, DECISIONS, DEV_ROWS, DEV_START, DEV_STOP, LAYER, PRIMARY, PRIMITIVES, SURFACES, SWEEP, TRAIN_ROWS, alpha_tag,  # noqa: E402,F401
                       c0_source_sha256, canon, model, runtime, sha256_bytes, sha256_file)

C1_EVIDENCE = C1_ROOT / "evidence"
C1_FREEZE = C1_ROOT / "results" / "freeze.json"
EVIDENCE = ROOT / "evidence"
RESULTS = ROOT / "results"
PREREGISTRATION = ROOT / "PREREGISTRATION.md"

SEED = 20260929
EPOCHS, BATCH, LEARNING_RATE, WEIGHT_DECAY, HIDDEN = 8, 2048, 1e-3, 1e-4, 256
LABELS = ("DO_NOT_ASK", "SHOULD_ASK")
ALPHAS = (0.60, 0.50, 0.40, 0.30, 0.20)
PRIMARY_ALPHA = 0.50
MATCHED_PRECISIONS = (0.4, 0.5, 0.6, 0.7)
GRID = tuple(range(50_000, 995_001, 5_000)) + (999_000,)
MIN_ASKS_FIT, MIN_ASKS_MATCHED = 100, 50
HEADS = ("linear", "mlp")


def head_dir(head: str) -> Path:
    return EVIDENCE / head


def verify_c1_evidence() -> dict:
    """The arrays and thresholds read from C1's evidence must be byte-identical to what C1 froze."""
    freeze = json.loads(C1_FREEZE.read_text(encoding="ascii"))
    for key, path in (("ppm_sha256", "dev-ppm.npz"), ("truth_sha256", "dev-truth.npz"), ("thresholds_sha256", "thresholds.json")):
        if sha256_file(C1_EVIDENCE / path) != freeze[key]:
            raise RuntimeError(f"C1 evidence {path} does not match C1's freeze record")
    return freeze


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="ascii", newline="\n")

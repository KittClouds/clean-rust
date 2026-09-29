"""Shared constants and helpers for C1. C0 is imported unchanged from its sibling folder."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C0_ROOT = ROOT.parent / "ff-s15-c0-runtime-01"
if str(C0_ROOT) not in sys.path:
    sys.path.insert(0, str(C0_ROOT))

from s15 import canon, model, runtime  # noqa: E402,F401

SWEEP = Path(os.environ.get("S15_C1_SWEEP", "D:/phoenix-target-overgraph/bank-v1-surface-extremes-20260929"))
BANK = ROOT.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
LOCK = Path(os.environ.get("S15_C1_RUNG0_LOCK", "C:/Users/shuga/.codex/worktrees/bank-v1-surfaces/clean-rust/experiments/bank-v1-rung0-atlas-20260929/rung0-lock.json"))
LOCK_SHA256 = "daa0406aa3f7caccfd84e09712b9448580eb6959faa0e7fba827557f7751c405"
EVIDENCE = ROOT / "evidence"
PREREGISTRATION = ROOT / "PREREGISTRATION.md"

TRAIN_ROWS, DEV_ROWS = 143996, 24000
DEV_START, DEV_STOP = TRAIN_ROWS, TRAIN_ROWS + DEV_ROWS  # DEV is the contiguous block after TRAIN; nothing past DEV_STOP is ever read

SURFACES = ("middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean")
PRIMARY = "middle_plus_final"
PRIMITIVES = {"middle_plus_final": ("middle_final", "final_token"), "final_plus_mean": ("final_token", "full_mean"), "layer_m4_final": ("layer_m4_final",), "full_mean": ("full_mean",)}
LAYER = {"middle_plus_final": "L8+final", "final_plus_mean": "final+mean", "layer_m4_final": "L11", "full_mean": "token_mean"}
DECISIONS = ("ACT", "ASK", "ABSTAIN")
ACTIONS = ("MOVE", "ACTIVATE", "DEACTIVATE", "TAKE", "DROP", "TRANSFER", "OPEN", "CLOSE", "SELECT", "ASSIGN", "REQUEST", "VERIFY", "WAIT", "NOOP")
HEADS = {"decision": DECISIONS, "action_type": ACTIONS}
ALPHAS = (0.20, 0.10, 0.05, 0.02, 0.01)
PRIMARY_ALPHA = 0.05


def alpha_tag(alpha: float) -> str:
    return f"a{round(alpha * 100):02d}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def c0_source_sha256() -> str:
    """Identity of the C0 runtime this result was produced with: its code and its schemas."""
    digest = hashlib.sha256()
    for path in sorted(list((C0_ROOT / "s15").glob("*.py")) + list((C0_ROOT / "schemas").glob("*.json"))):
        digest.update(path.relative_to(C0_ROOT).as_posix().encode("ascii") + b"\0" + sha256_bytes(path.read_bytes()).encode("ascii") + b"\n")
    return digest.hexdigest()

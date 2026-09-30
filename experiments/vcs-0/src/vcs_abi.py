"""VCS-0 VectorControlState ABI.

A typed, versioned, multi-dimensional evidence record describing *why* a control surface
sits where it does. Deliberately NOT a scalar and deliberately NOT a decision.

Design constraints (from the charter):
  - Preserve the shape of the response before authority decides anything.
  - No runtime authority, no execute decision, no best-scalar search.
  - Every coordinate carries its own provenance and its own degeneracy verdict.
  - Coordinates that cannot be trusted are declared degenerate rather than silently scored.

A VectorControlState is a mapping of block -> coordinate. Blocks are grouped so that
geometry can be studied blockwise (e.g. "does specialization rotate the applicability
block?"). Every coordinate is stored as (value, provenance, degenerate) so a downstream
consumer cannot mistake a degenerate coordinate for a real one.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

VCS_ABI_VERSION = "vector-control-state/abi-0.1"
BANK_SCHEMA = "ff-s15-bank-schema-v1"

# --------------------------------------------------------------------------- blocks
# Each block is an ordered tuple of (name, kind, description).
#   kind: prob | score | count | metric | cat | bool | vec

BLOCKS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "control": (
        ("top_choice_prob", "prob", "probability mass on the top-ranked legal action"),
        ("margin", "score", "top1 - top2 probability over the legal action set"),
        ("entropy", "metric", "entropy of the choice distribution over legal actions"),
        ("top1_is_legal", "bool", "whether the argmax action is in the simulator's legal set"),
        ("legal_set_support", "prob", "total probability mass the head puts on legal actions"),
        ("n_legal_actions", "count", "size of the simulator legal action set"),
    ),
    "applicability": (
        ("gold_action_legal", "bool", "is the canonical answer action simulator-legal"),
        ("alt_support", "prob", "probability mass on legal actions other than the chosen one"),
        ("n_legal_alternatives", "count", "legal actions available besides the gold one"),
        ("n_repair_alternatives", "count", "legal actions that would change the world"),
        ("unlawful_top_prob", "prob", "probability mass on the best illegal action"),
    ),
    "semantic": (
        ("n_evidence_facts", "count", "evidence facts attached to the canonical answer"),
        ("has_contradiction", "bool", "world carries a genuine contradiction"),
        ("n_missing_facts", "count", "missing_information entries in the world"),
        ("n_repair_alternatives", "count", "legal actions that would change the world"),
        ("goal_distance", "count", "BFS plan depth from current state to goal"),
    ),
    "representation": (
        ("substrate", "cat", "causal | encoder"),
        ("surface", "cat", "first | final | mean | full_mean | layer-4 | middle"),
        ("head_seed", "cat", "linear-head seed used to produce control coordinates"),
        ("trainable_dim", "count", "input dimension of the fitted head"),
    ),
    "distribution": (
        ("cell", "cat", "shift cell identity (base, LEX, TMPL, ...)"),
        ("renderer_family", "cat", "surface family the row was rendered with"),
        ("split", "cat", "BANK split the latent world came from"),
        ("calibration_family", "cat", "head fit provenance"),
    ),
}

ALL_COORDS = [(blk, name, kind) for blk, cs in BLOCKS.items() for name, kind, _ in cs]
COORD_INDEX = {(b, n): i for i, (b, n, _k) in enumerate(ALL_COORDS)}


def coordinate_order() -> list[str]:
    return [f"{b}.{n}" for (b, n, _k) in ALL_COORDS]


def new_state() -> dict[str, dict[str, Any]]:
    """A blank VectorControlState with every coordinate present and declared unmeasured."""
    return {
        b: {n: {"value": None, "kind": k, "provenance": None, "degenerate": None} for n, k, _d in cs}
        for b, cs in BLOCKS.items()
    }


def set_coord(st: dict, block: str, name: str, value: Any, provenance: str,
              degenerate: bool = False) -> dict:
    if block not in st or name not in st[block]:
        raise KeyError(f"unknown coordinate {block}.{name}")
    st[block][name]["value"] = value
    st[block][name]["provenance"] = provenance
    st[block][name]["degenerate"] = bool(degenerate)
    return st


def to_vector(st: dict, drop_degenerate: bool = True) -> list[float]:
    """Flatten to a numeric vector in ABI order.

    Unmeasured (None) coordinates are emitted as NaN so downstream geometry can exclude
    them explicitly rather than by imputation. Degenerate coordinates are dropped unless
    the caller asks to keep them, because a constant coordinate has no geometry.
    """
    out = []
    for blk, name, _kind in ALL_COORDS:
        c = st[blk][name]
        v = c["value"]
        if drop_degenerate and c["degenerate"]:
            out.append(float("nan"))
            continue
        if v is None:
            out.append(float("nan"))
        elif isinstance(v, bool):
            out.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            out.append(float(v))
        elif isinstance(v, str):
            out.append(float("nan"))  # categorical: handled by the caller, not by geometry
        else:
            out.append(float("nan"))
    return out


def numeric_columns(rows: list[list[float]]) -> list[int]:
    """Indices of columns usable for geometry.

    A column qualifies only if it is fully measured (no NaN in any row), numeric, and
    non-constant. Partial-NaN columns are dropped rather than imputed: an imputed
    coordinate would silently invent geometry that the ABI never measured.
    """
    keep = []
    n = len(rows[0]) if rows else 0
    for j in range(n):
        col = [r[j] for r in rows]
        if any(v != v for v in col):
            continue  # unmeasured somewhere -> drop, do not impute
        if max(col) - min(col) <= 1e-12:
            continue  # constant -> no geometry to describe
        keep.append(j)
    return keep


def degeneracy_report(features: dict[str, Any], n_rows: int, threshold: float = 0.01) -> dict:
    """For each surface, report the count of distinct row vectors and whether it is
    degenerate relative to row count.

    threshold = fraction of rows below which a surface is declared degenerate. This is the
    check that was missing from the encoder run, where the causal `first` coordinate turned
    out to have 7 distinct vectors across 20,000 rows.
    """
    out = {}
    for name, F in features.items():
        n = F.shape[0]
        try:
            uniq = int(torch_unique_rows(F))
        except Exception:
            uniq = -1
        ratio = uniq / max(n, 1)
        out[name] = {
            "rows": int(n),
            "distinct_vectors": uniq,
            "distinct_ratio": round(ratio, 6),
            "degenerate": bool(ratio < threshold),
            "threshold": threshold,
        }
    return out


def torch_unique_rows(F) -> int:
    import torch
    return int(torch.unique(F.float(), dim=0).shape[0])


def state_hash(st: dict) -> str:
    return hashlib.sha256(
        json.dumps(st, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                   default=str).encode()).hexdigest()


def abi_descriptor() -> dict:
    return {
        "abi": VCS_ABI_VERSION,
        "bank_schema": BANK_SCHEMA,
        "blocks": {b: [{"name": n, "kind": k, "description": d} for n, k, d in cs]
                   for b, cs in BLOCKS.items()},
        "n_coordinates": len(ALL_COORDS),
        "principles": [
            "no scalar collapse: geometry is studied in the full typed vector",
            "no runtime authority: this ABI records evidence, it does not decide",
            "degeneracy is declared per coordinate, never silently scored",
            "every coordinate carries provenance",
        ],
    }

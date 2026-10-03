"""Synthetic fixtures. Nothing here is scientific: coordinates x1..x4 mean nothing."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vcs import authority as A, canon, schema as S  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def schema() -> S.Schema:
    return S.load_schema(canon.loads_strict((FIX / "fixture_schema.json").read_bytes()))


def env(sc, x1=0.5, x2=0.5, x3=False, x4="p", *, app=None, rep="rep-a", bundle="bundle-0"):
    return S.make_envelope(sc, producer_bundle_id=bundle, coordinates={"x1": x1, "x2": x2, "x3": x3, "x4": x4}, representation_id=rep, applicability=app or {}, provenance={"note": "synthetic"})


def authority(sc, regions, rules, default=None, **kw):
    src = {"bound_schema": {"schema_id": sc.schema_id, "schema_version": sc.schema_version}, "regions": regions, "rules": rules,
           "default": default or {"type": "ESCALATE", "reason": "no_region"}, **kw}
    return A.load_authority(src, sc)


def case(sc, i, x1, *, acceptable, x2=0.5, x3=False, ctx=None, rep="rep-a", ask_cost=1.0):
    return {"case_id": f"c{i}", "envelope": env(sc, x1, x2, x3, rep=rep), "context": {"score": x1, "proposed_action": "act_a", "routes": ["r1"], **(ctx or {})},
            "truth": {"acceptable": acceptable, "ask_cost": ask_cost}}


def band_cases(sc, n=600, seed=1, lo=0.4, hi=0.6, shift=0.0, rep="rep-a"):
    """Correct to commit only when x1 is in [lo, hi] (non-monotone in x1). `shift` moves the score the scalar sees but not x1's band membership test's ground truth."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        x1 = rng.random()
        ok = lo <= x1 <= hi
        c = case(sc, i, x1, acceptable=[{"type": "EXECUTE", "action": "act_a"}] if ok else [], rep=rep)
        c["context"]["score"] = min(1.0, max(0.0, x1 + shift))
        out.append(c)
    return out

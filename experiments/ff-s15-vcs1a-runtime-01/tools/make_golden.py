"""Regenerates tests/fixtures/golden/* (synthetic fixture only). Golden receipts pin byte-identical output across runs and Python versions.

  python tools/make_golden.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import helpers as T  # noqa: E402
from vcs import authority as A  # noqa: E402

G = ROOT / "tests" / "fixtures" / "golden"
G.mkdir(exist_ok=True)
sc = T.schema()
src = {
    "bound_schema": {"schema_id": sc.schema_id, "schema_version": sc.schema_version},
    "regions": {
        "strong": {"text": 'x["x1"] >= 0.71 and x["x2"] in [0.12, 0.30] and x["x3"] == false'},
        "near": {"op": "ball", "center": {"x1": 0.5, "x2": 0.5}, "radius": 0.25, "norm": "l2"},
        "diag": {"op": "halfspaces", "rows": [{"coefs": {"x1": 1, "x2": 1}, "bound": 0.6}]},
        "quiet": {"text": 'x["x1"] < 0.2 and not present(x["x4"])'},
    },
    "rules": [
        {"rule_id": "go", "region": "strong", "disposition": {"type": "EXECUTE", "action": {"from_context": "proposed_action"}}},
        {"rule_id": "hold", "region": "quiet", "disposition": {"type": "NOOP"}},
        {"rule_id": "ask", "region": "near", "guards": [{"key": "routes", "test": "nonempty"}], "disposition": {"type": "ASK", "requirement": {"from_context": "req"}}},
        {"rule_id": "decline", "region": "diag", "disposition": {"type": "DECLINE_UNAVAILABLE", "reason": "low_mass"}},
    ],
    "default": {"type": "ESCALATE", "reason": "no_region"},
}
auth = A.load_authority(src, sc)
cases = {
    "execute": (T.env(sc, x1=0.8, x2=0.2, x3=False), {"proposed_action": "act_a"}),
    "noop": (T.env(sc, x1=0.1, x2=0.9, x4=None), {}),
    "ask": (T.env(sc, x1=0.5, x2=0.5), {"routes": ["r1"], "req": "need_q"}),
    "decline": (T.env(sc, x1=0.05, x2=0.3, x4="q"), {}),
    "escalate_default": (T.env(sc, x1=0.9, x2=0.9, x3=True), {}),
    "unknown_missing": (T.env(sc, x1=0.8, x2=None, x3=False), {"proposed_action": "act_a"}),
}
(G / "authority_src.json").write_text(json.dumps(src, sort_keys=True, indent=1) + "\n", encoding="ascii", newline="\n")
(G / "authority.json").write_text(json.dumps(auth.spec, sort_keys=True, indent=1) + "\n", encoding="ascii", newline="\n")
for name, (env, ctx) in cases.items():
    (G / f"{name}.envelope.json").write_text(json.dumps(env, sort_keys=True, indent=1) + "\n", encoding="ascii", newline="\n")
    (G / f"{name}.context.json").write_text(json.dumps(ctx, sort_keys=True, indent=1) + "\n", encoding="ascii", newline="\n")
    r = A.decide(auth, env, ctx)
    (G / f"{name}.receipt.json").write_text(json.dumps(r, sort_keys=True, indent=1) + "\n", encoding="ascii", newline="\n")
    print(name, r["decision"]["disposition"], r["decision"]["via"])

"""Fills RESULTS.template.md from results/cg1-census.json and guards every prose claim that names a finding.

  python tools/make_results.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cg1 import transforms as T  # noqa: E402

r = json.loads((ROOT / "results" / "cg1-census.json").read_text(encoding="ascii"))
M = r["methods"]
pc = lambda x, d=2: f"{100 * x:.{d}f}%"  # noqa: E731
pt = lambda x: f"{100 * x:.1f}"  # noqa: E731


def cell(method, eps, pop, key="edge_loss"):
    return M[method]["by_epsilon"][eps][pop][key]


# ---- guards
assert r["decision"]["advancing"] == [], "a transform now advances"
assert abs(cell("raw_logit", "0.01", "pooled") - 0.0665) < 0.0005 and abs(cell("raw_logit", "0.01", "S9") - 0.1714) < 0.0005, "raw_logit no longer reproduces C-G0"
assert all(c[e]["pooled_gain"] < 0.01 for c in r["control_shuffled"].values() for e in c), "the shuffled control now has a gain"
best = {(e, k): min(cell(m, e, k) for m in T.METHODS) for e in ("0.01", "0.02") for k in ("pooled", "held")}
assert best[("0.01", "pooled")] > 0.02 and best[("0.01", "held")] > 0.03 and best[("0.02", "pooled")] > 0.04 and best[("0.02", "held")] > 0.05, "some best loss meets its bound"
assert all(cell(m, e, "pooled", "gain") >= 0.05 for m in T.METHODS for e in ("0.01", "0.02")), "a gain bound now fails"
g = r["geometry"]
raw_q, tp_q = g["raw_logit"]["test_edge_q01_by_renderer"], g["typepair_percentile"]["test_edge_q01_by_renderer"]
raw_spread, tp_spread = max(raw_q.values()) - min(raw_q.values()), max(tp_q.values()) - min(tp_q.values())
assert tp_spread < raw_spread / 5, "the geometry spread no longer shrinks"
ok_set = {f"S{f}" for f in range(12) if cell("typepair_percentile", "0.01", f"S{f}") <= 0.015}
assert ok_set == {"S0", "S1", "S2", "S4", "S6", "S11"}, f"the well-behaved renderer set changed: {sorted(ok_set)}"
assert max(cell("typepair_percentile", "0.01", f"S{f}") for f in range(12)) == cell("typepair_percentile", "0.01", "S9"), "S9 is no longer the worst renderer"
der = r["exploratory_derated_budget_post_hoc"]["by_method"]
d1, d2 = der["typepair_percentile"]["0.002"], der["typepair_percentile"]["0.005"]
assert d1["pooled"]["edge_loss"] <= 0.02 and d1["held"]["edge_loss"] <= 0.03 and d1["pooled"]["gain"] >= 0.05, "the derated 1%-target claim no longer holds"
assert d2["pooled"]["edge_loss"] <= 0.04 and d2["held"]["edge_loss"] <= 0.05 and d2["pooled"]["gain"] >= 0.05, "the derated 2%-target claim no longer holds"
for m, eps, key, bound in (("world_percentile", "0.002", "held", 0.03), ("raw_logit", "0.002", "pooled", 0.02), ("world_percentile", "0.005", "held", 0.05), ("raw_logit", "0.005", "pooled", 0.04)):
    assert der[m][eps][key]["edge_loss"] > bound, f"{m} now meets a derated bound it was said to miss"
assert der["typepair_percentile"]["0.0005"] == der["typepair_percentile"]["0.001"], "the identical-rows note no longer holds"

# ---- tables
gate_rows = ["| transform | target | pooled loss (≤) | held loss (≤) | S9 loss (reported) | pooled gain (≥ 5 pts) | advances |", "|---|---|---|---|---|---|---|"]
for m in T.METHODS:
    for e, bounds in T.GATE.items():
        c = M[m]["gate"]["checks"][e]
        mark = lambda ok: "✓" if ok else "✗"  # noqa: E731
        gate_rows.append(f"| {m} | {float(e):.0%} | {pc(cell(m, e, 'pooled'))} ({bounds['pooled_loss']:.0%}) {mark(c['pooled_loss_ok'])} | {pc(cell(m, e, 'held'))} ({bounds['held_loss']:.0%}) {mark(c['held_loss_ok'])} | {pc(cell(m, e, 'S9'))} | "
                         f"{pt(cell(m, e, 'pooled', 'gain'))} {mark(c['gain_ok'])} | {'**yes**' if M[m]['gate']['advances'] else 'no'} |")
renderer_rows = ["| renderer | typepair_percentile | world_percentile | raw_logit |", "|---|---|---|---|"]
for f in range(12):
    renderer_rows.append(f"| S{f}{' (held)' if f in (7, 8, 9) else ''} | " + " | ".join(pc(cell(m, "0.01", f"S{f}")) for m in ("typepair_percentile", "world_percentile", "raw_logit")) + " |")
derate_rows = ["| transform | DEV budget | pooled loss | held loss | S9 loss | pooled gain (pts) | held gain (pts) |", "|---|---|---|---|---|---|---|"]
for m in ("typepair_percentile", "world_percentile", "raw_logit"):
    for eps in ("0.0005", "0.001", "0.002", "0.005"):
        x = der[m][eps]
        derate_rows.append(f"| {m} | {float(eps):.2%} | {pc(x['pooled']['edge_loss'])} | {pc(x['held']['edge_loss'])} | {pc(x['S9']['edge_loss'])} | {pt(x['pooled']['gain'])} | {pt(x['held']['gain'])} |")
t0 = r["t0_share"]["pooled"]
values = {
    "raw_pool_1": pc(cell("raw_logit", "0.01", "pooled")), "raw_held_1": pc(cell("raw_logit", "0.01", "held")), "raw_s9_1": pc(cell("raw_logit", "0.01", "S9")), "best_pool_1": pc(best[("0.01", "pooled")]),
    "best_held_1": pc(best[("0.01", "held")]), "best_pool_2": pc(best[("0.02", "pooled")]), "best_held_2": pc(best[("0.02", "held")]), "gate_table": "\n".join(gate_rows),
    "ctrl_max_gain": pt(max(c[e]["pooled_gain"] for c in r["control_shuffled"].values() for e in c)), "raw_spread": f"{raw_spread:.2f}", "raw_dev": f"{g['raw_logit']['dev_edge_q01']:.2f}",
    "tp_spread": f"{tp_spread:.2f}", "tp_dev": f"{g['typepair_percentile']['dev_edge_q01']:.2f}", "renderer_table": "\n".join(renderer_rows), "n_ok": len(ok_set), "ok_bound": "1.5%", "s9_tp": pc(cell("typepair_percentile", "0.01", "S9")),
    "derate_table": "\n".join(derate_rows), "d1_eps": "0.20%", "d1_pool": pc(d1["pooled"]["edge_loss"]), "d1_held": pc(d1["held"]["edge_loss"]), "d1_gain": pt(d1["pooled"]["gain"]),
    "d2_eps": "0.50%", "d2_pool": pc(d2["pooled"]["edge_loss"]), "d2_held": pc(d2["held"]["edge_loss"]), "d2_gain": pt(d2["pooled"]["gain"]), "t0_pooled": pc(t0, 1),
    "d1_total": pc(d1["pooled"]["pruned_share"], 0), "d1_s9": pc(d1["S9"]["edge_loss"]),
}
template = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
print("wrote RESULTS.md")

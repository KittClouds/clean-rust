"""Fills RESULTS.template.md from the receipts and guards every prose claim that names a finding.

  python tools/make_results.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = json.loads((ROOT / "results" / "x1-receipt.json").read_text(encoding="ascii"))
X = json.loads((ROOT / "results" / "x1-explore.json").read_text(encoding="ascii"))
P = json.loads((ROOT / "results" / "x1-prepare.json").read_text(encoding="ascii"))
pts = lambda v: f"{100 * v:.2f}"  # noqa: E731
S = R["settings"]

# ---- guards
d = R["decision"]
assert d["outcome"] == "STOP" and d["x1_earns_continuation"] is False and d["levels_graph_better"] == 0, "the preregistered decision changed"
assert all(v == 0 for v in d["levels_graph_better_by_controller"].values())
prim = S["real-m0.2"]
cur = prim["curves-defer"]["kept"]
max_cov = lambda c: max(cur[c]["coverage"])  # noqa: E731
flat_names = ["flat-max", "flat-mean", "flat-calibrated"]
best_flat_cov = max(max_cov(c) for c in flat_names)
assert best_flat_cov < 0.5 and max_cov("graph") < 0.5, "a merger now reaches 0.50 coverage at the primary setting"
cells = [(n, r) for n, b in X["settings"].items() for r in b["levels"] if "ci95" in r]
assert cells and all(r["ci95"][1] >= 0 for _n, r in cells), "a cell now favours the graph"
loss = {n: [r for r in b["levels"] if "ci95" in r and r["ci95"][0] > 0] for n, b in X["settings"].items()}
assert loss["real-m0.2"] and loss["controlled-high"], "the losses named in the prose are gone"
assert not loss["real-m0.0"], "the clean setting now shows a loss"
clean = X["settings"]["real-m0.0"]["levels"]
assert all(abs(r["diff_median"]) < 0.001 for r in clean), "the clean-producer gap is no longer tiny"
curC = S["controlled-low"]["curves-defer"]["kept"]
agree_loss = max(curC["graph"]["coverage"]) - max(curC["graph-noagree"]["coverage"])
assert agree_loss > 0.1, "agreement no longer matters"
assert abs(max(curC["flat-calibrated"]["coverage"]) - max(curC["graph"]["coverage"])) < 0.02, "calibrated flat no longer matches the graph's coverage"
assert max(curC["graph-nosem"]["coverage"][-4:]) >= max(curC["graph"]["coverage"][-4:]) - 0.05
assert prim["level2_graph_quality"]["0.6"]["graph"]["multi_loc"] <= prim["level2_graph_quality"]["0.6"]["graph-nostruct"]["multi_loc"], "structure no longer lowers multi-location rates"

# ---- tables
rows = ["| setting | coverage | graph harm | best-flat harm | diff (95% interval) |", "|---|---|---|---|---|"]
for n, b in X["settings"].items():
    for r in b["levels"]:
        if "ci95" in r:
            rows.append(f"| {n} | {r['coverage']:.3f} | {pts(r['graph_harm'])}% | {pts(r['best_flat_harm'])}% | {pts(r['diff_median'])} pts ({pts(r['ci95'][0])} to {pts(r['ci95'][1])}) |")
        else:
            rows.append(f"| {n} | {r['coverage']:.3f} | {pts(r['graph_harm']) if r['graph_harm'] is not None else 'n/a'}% | {pts(r['best_flat_harm']) if r['best_flat_harm'] is not None else 'n/a'}% | not estimable (a merger cannot reach this coverage in enough resamples) |")
ab = ["| config | max coverage | harm at max coverage | harm at theta 0.6 |", "|---|---|---|---|"]
for c in ["flat-calibrated", "flat-max", "flat-mean", "graph", "graph-nosem", "graph-nocontra", "graph-nodef", "graph-noagree", "graph-nostruct"]:
    v = cur[c]
    i = max(range(len(v["coverage"])), key=lambda j: v["coverage"][j])
    ab.append(f"| {c} | {v['coverage'][i]:.3f} | {pts(v['harm'][i])}% | {pts(v['harm'][6])}% |")
lm = loss["real-m0.2"][0]
lh = loss["controlled-high"][0]
values = {
    "fold_b": P["fold_b"], "kept": S["real-m0.2"]["oracle_agree_worlds"], "aligned": P["t2_alignment"]["aligned"], "worlds": P["t2_alignment"]["worlds"],
    "cov_flat_m02": f"{best_flat_cov:.3f}", "cov_graph_m02": f"{max_cov('graph'):.3f}", "outcome": d["outcome"], "levels_better": d["levels_graph_better"],
    "explore_table": "\n".join(rows), "n_cells": len(cells), "loss_m02": f"+{pts(lm['diff_median'])} points of harm at coverage {lm['coverage']:.2f}, interval {pts(lm['ci95'][0])} to {pts(lm['ci95'][1])}",
    "loss_high": f"+{pts(lh['diff_median'])} points at coverage {lh['coverage']:.2f}", "clean_gap": pts(max(abs(r["diff_median"]) for r in clean)),
    "ablation_table": "\n".join(ab), "agree_loss": f"{100 * agree_loss:.0f}",
}
tmpl = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(tmpl.format_map(values), encoding="utf-8", newline="\n")
print("wrote RESULTS.md")

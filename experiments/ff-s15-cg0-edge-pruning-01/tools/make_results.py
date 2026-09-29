"""Fills RESULTS.template.md from results/cg0-census.json (+ the small post hoc transfer table) and guards every prose claim that names a finding.

  python tools/make_results.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cg import frontier  # noqa: E402
from cg.common import EVIDENCE, HELD, TEST_SPLITS, read_json  # noqa: E402

r = json.loads((ROOT / "results" / "cg0-census.json").read_text(encoding="ascii"))
fr = r["frontier"]
pc = lambda x, d=1: f"{100 * x:.{d}f}%"  # noqa: E731
pts = lambda x: f"{100 * x:+.1f}"  # noqa: E731


def by(name, e):
    return fr[name]["by_epsilon"][e]


# ---- guards
gate = r["gate"]
assert gate["advance_t1"] is True, "the gate changed"
assert all(by("TEST_pooled", e)["gain"] >= 0.10 for e in ("0.01", "0.02")), "pooled gain below the bar"
assert all(by("TEST_held_S7_S8_S9", e)["gain"] < 0.10 for e in ("0.01", "0.02")), "held pooled gain now meets 10 points"
assert all(by(f"TEST_{h}", "0.01")["gain"] > 0 for h in HELD), "a held family is not positive"
assert by("TEST_S9", "0.01")["T1"]["pruned_share"] < by("TEST_S9", "0.01")["T0"]["pruned_share"], "S9: T1 alone no longer below T0"
assert r["integrity_gate"]["worst_difference"] < 1e-5
rates = r["t0_type_pair_rates"]
edge_carrying = [k for k, v in rates.items() if v["edges"] > 0]
assert sorted(edge_carrying) == sorted(["OBJECT->LOCATION", "AGENT->LOCATION", "LOCATION->LOCATION"]), "the edge-carrying type pairs changed"
zero = [v for k, v in rates.items() if v["edges"] == 0]
assert len(zero) == 12, "expected twelve edge-free type pairs"
assert all(by(n, "0.01")["T0"]["edge_loss"] == 0.0 for n in fr), "T0 has edge loss somewhere"
ph = r["dev_fit_transfer"]["0.01"]["T0+T1"]
assert ph["TEST_pooled"]["edge_loss"] > 3 * 0.01 and ph["TEST_S9"]["edge_loss"] > 0.10, "the transfer failure changed"
g = r["score_geometry_test_pooled"]
assert g["edges_quantiles"]["0.5"] > 0 > g["non_edges_quantiles"]["0.5"], "score geometry changed"

# ---- post hoc: conservative DEV budgets and edge-score shift (recomputed from the evidence arrays)
counts = read_json(EVIDENCE / "t0-train-counts.json")
rank = frontier.t0_rank(counts["pairs"], counts["edges"])


def pool(splits):
    parts = [np.load(EVIDENCE / f"universe-{s}.npz") for s in splits]
    return {k: np.concatenate([p[k] for p in parts]) for k in ("label", "pair_type", "family", "score")}


dev, test = pool(["DEV"]), pool(TEST_SPLITS)
held = np.isin(test["family"], [7, 8, 9])
grid = (0.0002, 0.0005, 0.001, 0.002, 0.01)
fits = frontier.frontier(dev["label"], dev["pair_type"], dev["score"], rank, grid)
cons_rows, cons = [], {}
for e in grid:
    p = fits[str(e)]["T0+T1"]
    cells = []
    for name, m in (("pooled", np.ones(len(held), bool)), ("held", held), ("S9", test["family"] == 9)):
        d = {k: v[m] for k, v in test.items()}
        a = frontier.apply_params(d["label"], d["pair_type"], d["score"], rank, p["k"], p["threshold"])
        cons[(e, name)] = a
        cells.append(f"{pc(a['edge_loss'], 2)} / {pc(a['pruned_share'])}")
    cons_rows.append(f"| {100 * e:.2f}% | " + " | ".join(cells) + " |")
cons_table = "| DEV budget | TEST pooled | held S7/S8/S9 | S9 |\n|---|---|---|---|\n" + "\n".join(cons_rows)
dev_q1 = float(np.quantile(dev["score"][dev["label"] == 1], 0.01))
fam_q1 = [float(np.quantile(test["score"][(test["family"] == f) & (test["label"] == 1)], 0.01)) for f in range(12)]
assert dev_q1 > max(fam_q1), "DEV edges are no longer easier than every TEST renderer's"

gate_rows = ["| population | ε | T0 | T0+T1 | T1 alone | gain (pts) | noise p95 (pooled) |", "|---|---|---|---|---|---|---|"]
for name, label in (("TEST_pooled", "TEST pooled"), ("TEST_in_family", "in-family (S0–S6, S10, S11)"), ("TEST_held_S7_S8_S9", "held S7+S8+S9"), ("TEST_S7", "S7"), ("TEST_S8", "S8"), ("TEST_S9", "S9")):
    for e in ("0.005", "0.01", "0.02", "0.05"):
        f = by(name, e)
        noise = pc(r["noise_band_test_pooled"][e]["p95"], 2) if name == "TEST_pooled" else "–"
        mark = " (gate)" if e in ("0.01", "0.02") else " (reported)"
        gate_rows.append(f"| {label} | {float(e):.1%}{mark} | {pc(f['T0']['pruned_share'])} | {pc(f['T0+T1']['pruned_share'])} | {pc(f['T1']['pruned_share'])} | **{pts(f['gain'])}** | {noise} |")
arm_rows = [f"| {label} | {pc(by(n, '0.01')['T0']['pruned_share'])} | {pc(by(n, '0.01')['T1']['pruned_share'])} | {pc(by(n, '0.01')['T0+T1']['pruned_share'])} |"
            for n, label in (("TEST_in_family", "in-family"), ("TEST_held_S7_S8_S9", "held S7+S8+S9"), ("TEST_S7", "S7"), ("TEST_S8", "S8"), ("TEST_S9", "S9"))]
fam_gains = [fr[k]["by_epsilon"]["0.01"]["gain"] for k in fr if k.startswith("TEST_S")]
tp = r["universe"]
test_pairs = sum(v["pairs"] for k, v in tp.items() if k.startswith("TEST"))
test_edges = sum(v["edges"] for k, v in tp.items() if k.startswith("TEST"))
zero_pairs = sum(v["pairs"] for v in zero)
t0 = by("TEST_pooled", "0.01")["T0"]["pruned_share"]
wp = r["within_pair_type_auc"]
values = {
    "gain1": pts(by("TEST_pooled", "0.01")["gain"]), "gain2": pts(by("TEST_pooled", "0.02")["gain"]), "noise1": pc(r["noise_band_test_pooled"]["0.01"]["p95"], 2), "noise2": pc(r["noise_band_test_pooled"]["0.02"]["p95"], 2),
    "worst_diff": r["integrity_gate"]["worst_difference"], "prevalence": pc(test_edges / test_pairs), "test_pairs": f"{test_pairs:,}", "test_edges": f"{test_edges:,}",
    "r_ol": pc(rates["OBJECT->LOCATION"]["rate"]), "r_al": pc(rates["AGENT->LOCATION"]["rate"]), "r_ll": pc(rates["LOCATION->LOCATION"]["rate"]), "train_zero_pairs": f"{zero_pairs:,}",
    "t0_share": pc(t0), "t0_held": pc(by("TEST_held_S7_S8_S9", "0.01")["T0"]["pruned_share"]), "resid_share": pc(1 - t0, 0), "gate_table": "\n".join(gate_rows), "n_bar_pass": "All",
    "infam1": pts(by("TEST_in_family", "0.01")["gain"]), "infam2": pts(by("TEST_in_family", "0.02")["gain"]), "held1": pts(by("TEST_held_S7_S8_S9", "0.01")["gain"]), "held2": pts(by("TEST_held_S7_S8_S9", "0.02")["gain"]),
    "s9_1": pts(by("TEST_S9", "0.01")["gain"]), "s9_2": pts(by("TEST_S9", "0.02")["gain"]), "min_fam": pts(min(fam_gains)), "max_fam": pts(max(fam_gains)), "arm_rows": "\n".join(arm_rows),
    "s9_t1": pc(by("TEST_S9", "0.01")["T1"]["pruned_share"]), "s9_t0": pc(by("TEST_S9", "0.01")["T0"]["pruned_share"]),
    "dev_share": pc(by("DEV", "0.01")["T0+T1"]["pruned_share"]), "tr_pool_loss": pc(ph["TEST_pooled"]["edge_loss"], 2), "tr_pool_share": pc(ph["TEST_pooled"]["pruned_share"]),
    "tr_held_loss": pc(ph["TEST_held_S7_S8_S9"]["edge_loss"], 2), "tr_held_share": pc(ph["TEST_held_S7_S8_S9"]["pruned_share"]), "tr_s9_loss": pc(ph["TEST_S9"]["edge_loss"], 2), "tr_s9_share": pc(ph["TEST_S9"]["pruned_share"]),
    "dev_q1": f"{dev_q1:.2f}", "test_q_lo": f"{max(fam_q1):.2f}", "test_q_hi": f"{min(fam_q1):.2f}", "conservative_table": cons_table,
    "cons_pool_loss": pc(cons[(0.0002, 'pooled')]["edge_loss"], 1), "cons_held_loss": pc(cons[(0.0002, 'held')]["edge_loss"], 1), "cons_pool_share": pc(cons[(0.0002, 'pooled')]["pruned_share"], 0), "cons_held_share": pc(cons[(0.0002, 'held')]["pruned_share"], 0),
    "edge_med": f"{g['edges_quantiles']['0.5']:.2f}", "edge_5": f"{g['edges_quantiles']['0.05']:.2f}", "edge_95": f"{g['edges_quantiles']['0.95']:.2f}", "ne_med": f"{g['non_edges_quantiles']['0.5']:.1f}", "ne_5": f"{g['non_edges_quantiles']['0.05']:.1f}",
    "wp_pool": f"{wp['TEST_pooled']['weighted_mean']:.3f}", "wp_held": f"{wp['TEST_held_S7_S8_S9']['weighted_mean']:.3f}", "full_auc": f"{r['full_pair_pooled_auc_test']:.3f}",
    "resid_gain1": pts(by("TEST_pooled", "0.01")["gain"]).lstrip("+"), "resid_gain2": pts(by("TEST_pooled", "0.02")["gain"]).lstrip("+"),
}
template = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
print("wrote RESULTS.md")

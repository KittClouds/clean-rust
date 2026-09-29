"""Fills RESULTS.template.md from results/c4a-census.json and guards every prose claim that names a finding.

  python tools/make_results.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
r = json.loads((ROOT / "results" / "c4a-census.json").read_text(encoding="ascii"))
SURFACES = ["middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean"]
P = "middle_plus_final"
L = [str(x) for x in r["levels"]]
e = r["surfaces"][P]
ph = e["post_hoc"]


def pct(x, d=1):
    return "inf" if x == "inf" else ("n/a" if x is None else f"{100 * x:.{d}f}%")


def num(x):
    return "inf" if x == "inf" else f"{x:+.1%}"


# ---- guards
assert r["decision"]["c4b_earned"] is False and not any(r["decision"]["gate_by_surface"].values()), "the gate changed"
assert e["oracle_gain"]["0.03"] < 0.10 and e["oracle_gain"]["0.05"] < 0.10, "the primary oracle gain reaches the bar"
assert e["oracle_gain"]["0.1"] >= 0.25 and e["oracle_gain"]["0.1"] > e["noise_band"]["0.1"]["p95"], "the 10%-harm statement no longer holds"
ex = ph["c1_a05_executions_by_predicted_action"]
noop_share = ex["NOOP"]["executed"] / sum(v["executed"] for v in ex.values())
assert noop_share >= 0.9, "NOOP is no longer at least 90% of C1's executions"
for s in SURFACES:
    t = r["surfaces"][s]["post_hoc"]["top_k_harm_by_predicted_action"]
    assert all(t[a]["25"] >= 0.15 for a in ("MOVE", "ACTIVATE")), f"{s}: a real action has a safe top-25"
    assert t["NOOP"]["200"] <= 0.10, f"{s}: NOOP's top 200 is no longer nearly harmless"
    assert (r["surfaces"][s]["coherence"].get("c1_impossible_executed") or 0) == 0, f"{s}: C1 executed an impossible-action candidate"
assert e["oracle"]["0.1"]["per_action"]["MOVE"]["executed"] <= 5 and e["oracle"]["0.1"]["per_action"]["ACTIVATE"]["executed"] == 0, "the 10% oracle now spends budget on real actions"
truth = ph["truth_act_distribution"]
real_truth = truth["MOVE"] + truth["ACTIVATE"]
real_correct = ex["MOVE"]["correct"] + ex.get("ACTIVATE", {"correct": 0})["correct"]

c1_all = []
for s_ in SURFACES:
    x = r["surfaces"][s_]["post_hoc"]["c1_a05_executions_by_predicted_action"]
    tot = sum(v["executed"] for v in x.values())
    if tot == 0:
        c1_all.append(f"| {s_} | none (no ACT rule at alpha 0.05) | – | – |")
        continue
    assert x["NOOP"]["executed"] / tot >= 0.9, f"{s_}: NOOP is under 90% of its executions"
    get = lambda a, k: x.get(a, {"executed": 0, "correct": 0})[k]  # noqa: E731
    c1_all.append(f"| {s_} | {get('NOOP', 'executed')} / {get('MOVE', 'executed')} / {get('ACTIVATE', 'executed')} | {get('NOOP', 'correct')} / {get('MOVE', 'correct')} / {get('ACTIVATE', 'correct')} | {pct(x['NOOP']['executed'] / tot, 0)} |")
o10 = e["oracle"]["0.1"]["per_action"]
gate_rows = []
for l in L:
    g = e["oracle_gain"][l]
    nb = e["noise_band"][l]["p95"]
    passes = "yes" if (l in ("0.03", "0.05") and e["gate_levels_passed"][l]) else ("(gate level) no" if l in ("0.03", "0.05") else "not a gate level")
    gate_rows.append(f"| {float(l):.0%} | {e['global_correct_at_harm'][l]} | {e['oracle'][l]['correct']} | {num(g)} | {num(nb)} | {passes} |")
c1_rows = []
for a in ("NOOP", "MOVE", "ACTIVATE"):
    v = ex.get(a, {"executed": 0, "correct": 0, "harmful": 0})
    c1_rows.append(f"| {a} | {v['executed']} | {v['correct']} | {v['harmful']} | {pct(v['correct'] / truth[a])} of {truth[a]} |")
cond = e["conditional_harm_at_global_threshold"]["0.05"]
cond_rows = [f"| {a} | {v['executed']} | {v['harmful']} | {pct(v['harm_rate'])} |" for a, v in cond.items()]
tk = []
for s in SURFACES:
    t = r["surfaces"][s]["post_hoc"]["top_k_harm_by_predicted_action"]
    cell = lambda a: " / ".join(pct(t[a][k], 0) for k in ("25", "100", "200"))  # noqa: E731
    tk.append(f"| {s} | {cell('NOOP')} | {cell('MOVE')} | {cell('ACTIVATE')} |")
min_top25 = min(r["surfaces"][s]["post_hoc"]["top_k_harm_by_predicted_action"][a]["25"] for s in SURFACES for a in ("MOVE", "ACTIVATE"))
values = {
    "c1_all_rows": chr(10).join(c1_all), "oracle10_noop": o10["NOOP"]["executed"], "oracle10_total": sum(v["executed"] for v in o10.values()),
    "gain3": num(e["oracle_gain"]["0.03"]), "gain5": num(e["oracle_gain"]["0.05"]), "eligible": ", ".join(e["eligible_actions"]), "excluded": e["excluded_candidates"],
    "gate_rows": "\n".join(gate_rows), "c1_rows": "\n".join(c1_rows), "noop_share": pct(noop_share, 0), "real_share": pct(real_correct / real_truth), "real_correct": real_correct, "real_truth": real_truth,
    "noop_recall": pct(ex["NOOP"]["correct"] / truth["NOOP"]), "conditional_rows": "\n".join(cond_rows), "topk_rows": "\n".join(tk), "min_real_top25": pct(min_top25, 0),
    "truth_noop": truth["NOOP"], "truth_move": truth["MOVE"], "truth_activate": truth["ACTIVATE"], "real_share_of_act": pct(real_truth / sum(truth.values()), 0), "impossible": e["coherence"]["impossible_action_candidates"],
}
template = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
print("wrote RESULTS.md")

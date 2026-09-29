"""Fills RESULTS.template.md from results/c3a-census.json and guards every prose claim that names a finding.

  python tools/make_results.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
r = json.loads((ROOT / "results" / "c3a-census.json").read_text(encoding="ascii"))
SURFACES = ["middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean"]
P = "middle_plus_final"
L = [str(x) for x in r["levels"]]
CONTROL = "random_control"
ps = r["surfaces"][P]
base = ps["correct_at_harm"]["c1_min"]


def gain(now, ref):
    return None if ref == 0 else now / ref - 1


# ---- guards
d = r["decision"]
assert d["c3b_earned"] is False and all(not v for v in d["dominating_by_surface"].values()), "some score now dominates"
assert not d["random_control_dominates_anywhere"] and all(v == 0 for s in SURFACES for v in r["surfaces"][s]["correct_at_harm"][CONTROL].values()), "the random control now finds a set"
alts = [n for n in ps["correct_at_harm"] if n not in ("c1_min", CONTROL)]
assert all(ps["correct_at_harm"][n][L[0]] < base[L[0]] and ps["correct_at_harm"][n][L[1]] < base[L[1]] for n in alts), "some alternative now matches C1 at 3-5% harm on the primary"
ten = {n for n in alts if L[3] in ps["dominance"][n]["levels_passed"]}
assert ten == {"product", "margin_product", "rank_mean"} and all(ps["dominance"][n]["levels_passed"] == [L[3]] for n in ten), "the 10%-harm crossing changed"
worst = min(gain(ps["correct_at_harm"][n][L[0]], base[L[0]]) for n in ("p_action", "act_margin", "neg_act_entropy", "neg_p_ask") if base[L[0]])
assert worst <= -0.5, "the 'lose 10% to 75%' range statement no longer holds"
fpm = r["surfaces"]["final_plus_mean"]
assert max(v for n in fpm["bootstrap_low_difference"] for v in fpm["bootstrap_low_difference"][n].values()) <= 0, "final_plus_mean now has a positive bootstrap low"
for s in ("layer_m4_final", "full_mean"):
    assert all(not r["surfaces"][s]["dominance"][n]["levels_passed"] for n in r["surfaces"][s]["dominance"] if n != CONTROL), f"{s} now passes a level"

order = [n for n in ps["correct_at_harm"] if n != "c1_min"]
rows = ["| score | " + " | ".join(f"H ≤ {float(l):.0%}" for l in L) + " |", "|---|" + "---|" * len(L), "| **c1_min (C1's score)** | " + " | ".join(str(base[l]) for l in L) + " |"]
for n in sorted(order, key=lambda n: -sum(ps["correct_at_harm"][n].values())):
    cells = []
    for l in L:
        v = ps["correct_at_harm"][n][l]
        g = gain(v, base[l])
        star = "*" if l in ps["dominance"][n]["levels_passed"] else ""
        cells.append(f"{v} ({'n/a' if g is None else f'{g:+.0%}'}){star}")
    rows.append(f"| {n} | " + " | ".join(cells) + " |")

other = []
for s in SURFACES[1:]:
    e = r["surfaces"][s]
    b = e["correct_at_harm"]["c1_min"]
    best = []
    for l in L:
        top = max((n for n in e["correct_at_harm"] if n not in ("c1_min", CONTROL)), key=lambda n: e["correct_at_harm"][n][l])
        g = gain(e["correct_at_harm"][top][l], b[l])
        best.append(f"{top} {'n/a' if g is None else f'{g:+.0%}'}")
    passing = sum(1 for n, dd in e["dominance"].items() if n != CONTROL and dd["levels_passed"])
    dominating = sum(1 for n, dd in e["dominance"].items() if n != CONTROL and dd["dominates"])
    other.append(f"| {s} | {e['candidates']} | {' / '.join(str(b[l]) for l in L)} | {'; '.join(best)} | {passing} | {dominating} |")

fpm_best = max(gain(fpm["correct_at_harm"][n][l], fpm["correct_at_harm"]["c1_min"][l]) for n in ("product", "margin_product", "rank_mean") for l in L if fpm["correct_at_harm"]["c1_min"][l])
SINGLES = ("p_act", "p_action", "dec_margin", "act_margin", "neg_dec_entropy", "neg_act_entropy", "neg_p_abstain", "neg_p_ask")
closest = [max(gain(ps["correct_at_harm"][n][l], base[l]) for n in alts) for l in L[:2]]
single_best = max(gain(ps["correct_at_harm"][n][l], base[l]) for n in SINGLES for l in L[:2])
prod_gain = {s: gain(r["surfaces"][s]["correct_at_harm"]["product"][L[3]], r["surfaces"][s]["correct_at_harm"]["c1_min"][L[3]]) for s in SURFACES}
assert all(v is not None and v > 0 for v in prod_gain.values()), "product no longer gains at 10% harm on all four surfaces"
assert -0.08 <= min(closest) and max(closest) <= -0.04 and single_best <= -0.10, "the closest-alternative statement no longer holds"
values = {
    "closest_loss": f"{-max(closest):.0%}–{-min(closest):.0%}", "single_loss": f"{-single_best:.0%}", "product_by_surface": ", ".join(f"{s} {v:+.0%}" for s, v in prod_gain.items()),
    "candidates": ps["candidates"], "safe": ps["safe_candidates"], "true_act": r["true_act_rows"], "primary_table": "\n".join(rows),
    "product_gain": f"{gain(ps['correct_at_harm']['product'][L[3]], base[L[3]]):+.0%}", "margin_product_gain": f"{gain(ps['correct_at_harm']['margin_product'][L[3]], base[L[3]]):+.0%}",
    "rank_mean_gain": f"{gain(ps['correct_at_harm']['rank_mean'][L[3]], base[L[3]]):+.0%}", "other_rows": "\n".join(other), "fpm_best_gain": f"{fpm_best:+.0%}",
}
template = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
print("wrote RESULTS.md")

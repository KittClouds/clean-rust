"""Fills C2A-RESULTS.template.md from results/c2a-census.json so no number in the write-up is typed by hand, and guards the prose claims.

  python tools/make_results.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
r = json.loads((ROOT / "results" / "c2a-census.json").read_text(encoding="ascii"))
P = "middle_plus_final"


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


t05 = r["tags"]["a05"]
g = t05["group"]
ex = r["exploratory_post_hoc"]
an = ex["harmful_anatomy"]["a05"]
pairs = t05["pairs"]

# ---- guards: the prose below makes these claims; fail loudly if the data stops supporting them
assert r["decision"]["proceed_to_c2b"] is False and g["oracle_headroom"] < r["go_threshold"], "the go/no-go rule no longer says stop"
assert g["veto_census"]["any_other_vetoes_harmful"] == 0, "some harmful executions are now vetoed"
assert all(an["others"][s]["says"]["ACT"] >= 0.9 * an["primary_harmful"] for s in ("final_plus_mean", "layer_m4_final", "full_mean")), "errors are no longer shared"
assert t05["per_surface"]["full_mean"]["qualifies"] == 0, "full_mean now has an ACT rule at a05"
frontier = ex["single_surface_frontier"]
base = frontier[0]["correct_act_share_of_true_act"]
gain = lambda f: f["correct_act_share_of_true_act"] / base - 1  # noqa: E731
under = [f for f in frontier[1:] if f["cal_harm_rate"] <= 0.07]
over = [f for f in frontier[1:] if f["cal_harm_rate"] > 0.07]
best_under, first_over = max(under, key=gain), min(over, key=lambda f: f["cal_harm_rate"])
assert gain(best_under) >= 0.20 and gain(first_over) >= 0.25, "the single-surface frontier no longer comes close to the proposed gate"
assert not any(gain(f) >= 0.25 and f["cal_harm_rate"] <= 0.07 for f in frontier[1:]), "some single-surface point now meets the gate outright: reword the prose"
jac = [p["qualified"]["jaccard_correct"] for k, p in pairs.items() if "full_mean" not in k]
pair = pairs["middle_plus_final|final_plus_mean"]["qualified"]
pab = [an["others"][s]["p_abstain_median"] for s in ("final_plus_mean", "layer_m4_final", "full_mean")]
rows = []
for tag in ("a02", "a05", "a10", "a20"):
    grp = r["tags"][tag]["group"]
    rows.append(f"| {r['tags'][tag]['alpha_tag'][1:].lstrip('0') and 0.01 * int(r['tags'][tag]['alpha_tag'][1:]):.2f} | {grp['primary_correct']} ({pct(grp['primary_correct_share_of_true_act'])}) | {grp['union_correct']} ({pct(grp['union_correct_share_of_true_act'])}) | {pct(grp['oracle_headroom'])} | {pct(grp['pessimistic_union_harm_rate'])} |")
frows = [f"| {f['alpha']:.2f} | {f['t_act_ppm']} | {pct(f['correct_act_share_of_true_act'])} | {'+%.0f%%' % (100 * (f['correct_act_share_of_true_act'] / base - 1))} | {pct(f['cal_harm_rate'])} |" for f in frontier]
p10 = next(f for f in frontier if abs(f["alpha"] - 0.10) < 1e-9)
values = {
    "headroom": pct(g["oracle_headroom"]), "cal_rows": r["rows"], "true_act": g["true_act_rows"], "primary_correct": g["primary_correct"], "primary_share": pct(g["primary_correct_share_of_true_act"]),
    "union_correct": g["union_correct"], "union_share": pct(g["union_correct_share_of_true_act"]), "inter_correct": g["intersection_correct"], "extra": g["extra_correct_not_found_by_primary"],
    "jaccard_lo": f"{min(jac):.2f}", "jaccard_hi": f"{max(jac):.2f}", "mf_only_a": pair["correct_only_A"], "mf_only_b": pair["correct_only_B"],
    "harm_rows": g["rows_with_a_harmful_qualifier"], "union_exec": g["union_executed"], "veto_harm": g["veto_census"]["any_other_vetoes_harmful"], "prim_harm": an["primary_harmful"],
    "veto_correct": g["veto_census"]["any_other_vetoes_correct"], "harm_abstain": an["truth_of_those_rows"]["ABSTAIN"], "harm_ask": an["truth_of_those_rows"]["ASK"], "harm_wrong": an["truth_of_those_rows"]["ACT"],
    "fpm_act": an["others"]["final_plus_mean"]["says"]["ACT"], "lm4_act": an["others"]["layer_m4_final"]["says"]["ACT"], "fm_act": an["others"]["full_mean"]["says"]["ACT"],
    "pabs_lo": pct(min(pab)), "pabs_hi": pct(max(pab)), "sensitivity_rows": "\n".join(rows), "frontier_rows": "\n".join(frows), "h10": pct(r["tags"]["a10"]["group"]["oracle_headroom"]),
    "primary_10_share": pct(p10["correct_act_share_of_true_act"]), "gate_near": f"+{100 * gain(best_under):.0f}% at {pct(best_under['cal_harm_rate'])} harm (alpha {best_under['alpha']:.2f}), and +{100 * gain(first_over):.0f}% at {pct(first_over['cal_harm_rate'])} (alpha {first_over['alpha']:.2f})", "primary_10_harm": pct(p10["cal_harm_rate"]),
}
template = (ROOT / "C2A-RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "C2A-RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
print("wrote C2A-RESULTS.md")
sys.exit(0)

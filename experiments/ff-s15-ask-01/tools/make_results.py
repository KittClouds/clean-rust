"""Fills RESULTS.template.md from results/ask-report-{linear,mlp}.json, and guards every prose claim that names a specific finding.

  python tools/make_results.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tables as T  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
P = T.PRIMARY
lin, mlp = T.report("linear"), T.report("mlp")
pct, num = T.pct, T.num


def sig(r, who):
    return r["surfaces"][P]["signal"][who]


def rule(r, tag="a50", who="dedicated", surface=P):
    return r["surfaces"][surface]["alphas"][tag][who]


ml, mm, mb = sig(lin, "dedicated"), sig(mlp, "dedicated"), sig(mlp, "baseline")
ctl = mlp["surfaces"][P]["controller"]
comb, c1 = ctl["combined"], ctl["c1_only"]
fpm = mlp["surfaces"]["final_plus_mean"]

# ---- guards: the prose names these findings; fail loudly if the reports stop supporting them
NO_GAIN = "NO GAIN OVER THE EXISTING HEAD"
assert lin["verdict"] == NO_GAIN and mlp["verdict"] == NO_GAIN, "a verdict changed"
assert lin["criteria"][P]["A1_matched_precision_wins"] == 0 and not lin["criteria"][P]["A1_beats_existing_head"], "linear no longer shows zero wins"
assert mlp["criteria"][P]["A1_matched_precision_wins"] == 2 and mm["ap"] < 1.25 * mb["ap"] and mm["ap"] > mb["ap"], "MLP AP/wins statement no longer holds"
assert mm["recall_at"]["0.6"] is None and mb["recall_at"]["0.6"] is None and ml["recall_at"]["0.6"] is None, "precision 0.6 is now reachable"
assert rule(mlp, "a50", "baseline")["threshold_ppm"] is None, "the existing head now fits a rule at alpha 0.50"
assert not mlp["criteria"][P]["A2_usable_rule"] and rule(mlp)["hold"]["recall"] < 0.25 and rule(mlp)["hold"]["precision"] >= 0.45, "the MLP A2 statement no longer holds"
assert mlp["criteria"][P]["A3_acting_tier_intact"] and comb["correct_executed"] == c1["correct_executed"], "the acting tier changed"
assert mlp["criteria"]["final_plus_mean"]["A2_usable_rule"] and not mlp["criteria"]["final_plus_mean"]["A1_beats_existing_head"], "the final_plus_mean sensitivity note no longer holds"
assert 0.10 <= rule(lin)["hold"]["recall"] <= 0.21 and 0.10 <= rule(mlp)["hold"]["recall"] <= 0.21, "the recall-at-alpha-0.50 range statement no longer holds"
assert rule(lin, "a60")["hold"]["precision"] < 0.45 and rule(mlp, "a60")["hold"]["precision"] < 0.45 and rule(mlp, "a60")["hold"]["recall"] >= 0.25, "the alpha-0.60 statement no longer holds"
assert mlp["hold_ask_rows"] == lin["hold_ask_rows"] and lin["runtime_integrity"]["numpy_matches_c0_on_every_row"] and mlp["runtime_integrity"]["numpy_matches_c0_on_every_row"]

hold_ask_rate = mlp["hold_ask_rows"] / mlp["hold_rows"]
a50 = rule(mlp)["hold"]
fa = rule(mlp, surface="final_plus_mean")["hold"]
a60m, a60l, a60b = rule(mlp, "a60")["hold"], rule(lin, "a60")["hold"], rule(mlp, "a60", "baseline")["hold"]
values = {
    "m_ap_ratio": f"{mm['ap'] / mb['ap']:.2f}", "m_ap_pts": f"{100 * (mm['ap'] - mb['ap']):.0f}", "l_a50_r": pct(rule(lin)["hold"]["recall"]),
    "m_a60_asks": a60m["asks"], "m_a60_p": pct(a60m["precision"]), "m_a60_r": pct(a60m["recall"]), "l_a60_p": pct(a60l["precision"]), "l_a60_r": pct(a60l["recall"]), "b_a60_p": pct(a60b["precision"]), "b_a60_r": pct(a60b["recall"]),
    "verdict_linear": lin["verdict"], "verdict_mlp": mlp["verdict"], "policies": mlp["runtime_integrity"]["policies"], "hold_rows": mlp["hold_rows"], "hold_ask": mlp["hold_ask_rows"],
    "prevalence": pct(hold_ask_rate), "b_ap": num(mb["ap"]), "b_auc": num(mb["auroc"]), "l_ap": num(ml["ap"]), "l_auc": num(ml["auroc"]), "m_ap": num(mm["ap"]), "m_auc": num(mm["auroc"]),
    "b_r4": pct(mb["recall_at"]["0.4"]), "b_r5": pct(mb["recall_at"]["0.5"]), "l_r4": pct(ml["recall_at"]["0.4"]), "l_r5": pct(ml["recall_at"]["0.5"]),
    "m_r4": pct(mm["recall_at"]["0.4"]), "m_r5": pct(mm["recall_at"]["0.5"]), "mlp_wins": mlp["criteria"][P]["A1_matched_precision_wins"],
    "m_ap_gain": f"+{100 * (mm['ap'] / mb['ap'] - 1):.0f}%", "m_r4_gain": f"+{100 * (mm['recall_at']['0.4'] / mb['recall_at']['0.4'] - 1):.0f}%", "m_r5_gain": f"+{100 * (mm['recall_at']['0.5'] / mb['recall_at']['0.5'] - 1):.0f}%",
    "criteria_linear": T.criteria_table(lin), "criteria_mlp": T.criteria_table(mlp), "frontier_linear": T.frontier_table(lin), "frontier_mlp": T.frontier_table(mlp), "controller_mlp": T.controller_table(mlp),
    "m_a50_asks": a50["asks"], "m_a50_p": pct(a50["precision"]), "m_a50_r": pct(a50["recall"]),
    "cx_c1": c1["correct_executed"], "cx_comb": comb["correct_executed"], "h_c1": c1["harmful"], "h_comb": comb["harmful"], "hr_c1": pct(c1["harm_rate"]), "hr_comb": pct(comb["harm_rate"]),
    "asks_comb": ctl["combined_ask_outcomes"]["asks"], "correct_asks_comb": ctl["combined_ask_outcomes"]["correct_asks"],
    "fpm_asks": fa["asks"], "fpm_p": pct(fa["precision"]), "fpm_r": pct(fa["recall"]), "fpm_ap": num(fpm["signal"]["dedicated"]["ap"]), "fpm_bap": num(fpm["signal"]["baseline"]["ap"]),
}
template = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
print("wrote RESULTS.md")

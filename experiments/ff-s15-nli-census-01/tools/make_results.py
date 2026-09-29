"""Fills RESULTS.template.md from results/census.json and guards every prose claim that names a finding.

  python tools/make_results.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
r = json.loads((ROOT / "results" / "census.json").read_text(encoding="ascii"))
SURFACES = ["middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean"]
NLI = "layer_m4_final"


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def num(x, d=3):
    return "n/a" if x is None else f"{x:.{d}f}"


p = r["heads"][NLI]
u, cj, nz = p["union"], p["conjunction"], p["noise"]
ceil, strict = r["ceiling_perfect_nli_pass_through_unlabelled"], r["ceiling_perfect_nli_strict_unknown_only"]
ct = r["crosstab_truth_decision_by_true_nli"]
stand = r["true_nli_standalone"]

# ---- guards
assert r["decision"] == {"V_veto_earned": False, "U_union_earned": False, "route_earned": False}, "the decision changed"
assert ceil["headroom"] < 0.25 and strict["headroom"] < 0.25, "the ceiling is no longer below the bar"
assert stand["ask_rate_given_unknown"] < 0.10 and stand["ask_rate_given_entailed_or_contradicted"] == 0.0, "the NLI-label statements no longer hold"
assert all(r["heads"][s]["standalone"]["ap"] < 0.10 for s in SURFACES), "some NLI head is no longer near chance for ASK"
assert u["N"]["kind"] == "size_matched" and cj["headroom"] is not None and cj["headroom"] < 0.05 and nz["p95"] < 0.05, "the conjunction/noise statements no longer hold"
assert u["union"]["precision"] < 0.5 and u["oracle_union_headroom"] < 0.25, "the union statements no longer hold"
assert u["false_positive_share_shared"] < 0.10 and u["true_positives_lost_if_n_required"] > 0.5 * u["A"]["true_positives"], "the near-random-filter statement no longer holds"


an = r["a_false_positive_anatomy_post_hoc"]
assert an["by_true_nli"]["2"] >= 0.7 * an["false_positives"] and an["removable_by_a_perfect_veto"] <= 0.15 * an["false_positives"] and an["by_truth_decision"]["ABSTAIN"] >= 0.7 * an["false_positives"], "the false-positive anatomy no longer supports the prose"


def share(decision, code):
    row = ct[decision]
    return row[str(code)] / sum(row.values())


rows = [f"| {d} | {ct[d]['0']} | {ct[d]['1']} | {ct[d]['2']} | {ct[d]['-1']} |" for d in ("ACT", "ASK", "ABSTAIN")]
sens = [f"| {s} | {num(r['heads'][s]['standalone']['ap'])} | {pct(r['heads'][s]['union'].get('oracle_union_headroom'))} | {pct(r['heads'][s]['conjunction']['headroom'])} | {pct(r['heads'][s]['noise']['p95'])} |" for s in SURFACES]
prevalence = r["prevalence"]
values = {
    "fp_unknown": an["by_true_nli"]["2"], "fp_none": an["by_true_nli"]["-1"], "fp_removable": an["removable_by_a_perfect_veto"], "fp_abstain": an["by_truth_decision"]["ABSTAIN"], "fp_act": an["by_truth_decision"]["ACT"],
    "ceiling_headroom": pct(ceil["headroom"]), "strict_headroom": pct(strict["headroom"]), "cal_rows": r["cal_rows"], "cal_ask": r["cal_ask_rows"], "crosstab_rows": "\n".join(rows),
    "ask_unknown_share": pct(share("ASK", 2), 0), "act_unknown_share": pct(share("ACT", 2), 0), "abstain_unknown_share": pct(share("ABSTAIN", 2), 0),
    "ask_rate_unknown": pct(stand["ask_rate_given_unknown"]), "prevalence": pct(prevalence), "lift": f"{stand['ask_rate_given_unknown'] / prevalence:.1f}", "ask_rate_ec": pct(stand["ask_rate_given_entailed_or_contradicted"], 0),
    "base_recall": pct(ceil["baseline_recall"]), "ceil_recall": pct(ceil["recall"]), "strict_recall": pct(strict["recall"]),
    **{f"{k}_rows": u[key]["rows"] for k, key in (("A", "A"), ("N", "N"), ("I", "intersection"), ("U", "union"))},
    **{f"{k}_tp": u[key]["true_positives"] for k, key in (("A", "A"), ("N", "N"), ("I", "intersection"), ("U", "union"))},
    **{f"{k}_fp": u[key]["false_positives"] for k, key in (("A", "A"), ("N", "N"), ("I", "intersection"), ("U", "union"))},
    **{f"{k}_p": pct(u[key]["precision"]) for k, key in (("A", "A"), ("N", "N"), ("I", "intersection"), ("U", "union"))},
    **{f"{k}_r": pct(u[key]["recall"]) for k, key in (("A", "A"), ("N", "N"), ("I", "intersection"), ("U", "union"))},
    "recovered": u["misses_recovered_by_n"], "misses": u["ask_misses"], "recovered_share": pct(u["misses_recovered_share"]), "oracle_union": pct(u["oracle_union_headroom"]),
    "shared_fp": u["false_positives_shared_with_n"], "shared_fp_share": pct(u["false_positive_share_shared"]),
    "nli_aps": "–".join([num(min(r['heads'][s]['standalone']['ap'] for s in SURFACES)), num(max(r['heads'][s]['standalone']['ap'] for s in SURFACES))]),
    "tp_lost": u["true_positives_lost_if_n_required"], "fp_removed": u["false_positives_removed_if_n_required"],
    "conj_headroom": pct(cj["headroom"]), "conj_b": cj["b"], "noise_median": pct(nz["median"]), "noise_p95": pct(nz["p95"]), "noise_max": pct(nz["max"]), "sensitivity_rows": "\n".join(sens),
}
template = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
print("wrote RESULTS.md")

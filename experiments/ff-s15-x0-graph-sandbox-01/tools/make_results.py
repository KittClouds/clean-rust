"""Fills RESULTS.template.md from the two receipts and guards every prose claim that names a finding.

  python tools/make_results.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = json.loads((ROOT / "results" / "x0-clean.json").read_text(encoding="ascii"))
N = json.loads((ROOT / "results" / "x0-noise.json").read_text(encoding="ascii"))
S = C["summary"]
pc = lambda x, d=1: f"{100 * x:.{d}f}%"  # noqa: E731
pts = lambda x: f"{100 * x:.2f}"  # noqa: E731
ALIAS = "graph_path_slots_alias"

# ---- guards
assert C["n_dev"] == 20000
order = [S[k]["decision_accuracy"] for k in (ALIAS, "flat+", "graph_path_slots", "graph_path", "flat")]
assert order == sorted(order, reverse=True), "the accuracy ordering alias > flat+ > slots > path > flat changed"
assert S["graph_path_slots"]["ask_recall"] > 0.85 and S["flat+"]["ask_recall"] < 0.35 and S["graph_path"]["ask_recall"] < 0.30, "ASK recall story changed"
assert S["graph_path_slots"]["act_labelled_acted"] == 1.0 and S["flat+"]["act_labelled_acted"] < 1.0
assert all("bad" not in a and "noop_bad" not in a for a in C["act_actions"].values()), "a graph first action is off a shortest plan"
assert S[ALIAS]["ask_precision"] < S["flat+"]["ask_precision"], "flat+ no longer has the higher ASK precision"
lc = C["by_label_class"]
for k in ("ACT/plan", "ACT/goal_already"):
    assert set(lc["graph_path_slots"][k]) == {"ACT"}, f"slot completeness now asks or abstains on {k} worlds"
b = C["blocked_count_by_label_(0,1,2+)"]
assert all(v.get("2", 0) == 0 for k, v in b.items() if k not in ("ABSTAIN/IMPOSSIBLE_GOAL", "ABSTAIN/NO_VALID_ACTION")), "BLOCKED>=2 occurs outside IMPOSSIBLE/NO_VALID_ACTION"
assert b["ABSTAIN/IMPOSSIBLE_GOAL"].get("2", 0) == sum(b["ABSTAIN/IMPOSSIBLE_GOAL"].values()), "not all IMPOSSIBLE_GOAL worlds have a doubled BLOCKED"
al = C["duplicated_alias_by_label"]
assert all(v.get("True", 0) == 0 for k, v in al.items() if k != "ABSTAIN/INSUFFICIENT_EVIDENCE"), "duplicated aliases occur outside INSUFFICIENT_EVIDENCE"
sig = C["graph_by_signature"][ALIAS]
assert sig["duplicated alias"] == {"ABSTAIN": al["ABSTAIN/INSUFFICIENT_EVIDENCE"]["True"]}, "the alias edge no longer catches every duplicated-alias world"
IMP = ("ABSTAIN/IMPOSSIBLE_GOAL", "ABSTAIN/NO_VALID_ACTION")
imp_total = sum(sum(lc["flat+"][k].values()) for k in IMP)
flat_imp = sum(lc["flat+"][k].get("ABSTAIN", 0) for k in IMP)
graph_imp = sum(lc[ALIAS][k].get("ABSTAIN", 0) for k in IMP)
assert flat_imp > 0.9 * imp_total and graph_imp < 0.1 * imp_total, "the IMPOSSIBLE-convention contrast changed"
assert lc[ALIAS]["ABSTAIN/IMPOSSIBLE_GOAL"].get("ACT", 0) > 0.8 * sum(lc[ALIAS]["ABSTAIN/IMPOSSIBLE_GOAL"].values()), "detours no longer dominate IMPOSSIBLE worlds"
ask_rel = C["ask_label_relevance"]
ask_n = sum(ask_rel.values())
assert ask_n == 978 and abs(ask_rel["removed fact on the goal path"] / ask_n - S["graph_path"]["ask_recall"]) < 0.005, "goal-path ASK recall no longer equals the on-path share"
idn = C["ask_identifiability"]
assert idn["by_missing_kind"]["AT"]["mean_candidates"] == 1.0 and idn["by_missing_kind"]["STATE"]["mean_candidates"] == 1.0
ph = C["physics_agreement"][ALIAS]
phys_n = sum(ph.values())
phys_bad = ph.get("oracle_ABSTAIN|controller_ACT", 0) + ph.get("oracle_ACT|controller_not_ACT", 0)
assert phys_bad < 0.001 * phys_n
sg = N["sigmas"]
CFGS = ("0.4|0.6", "0.3|0.7", "0.2|0.8")
for s in ("0.1", "0.2", "0.3"):
    for cfg in CFGS:
        assert sg[s]["points"][f"asym|{cfg}"]["harmful_acts"] == sg[s]["points"][f"defer|{cfg}"]["harmful_acts"], "DEFER and the asymmetric control now differ in harm"
for cfg in CFGS:
    for s in ("0.2", "0.3"):
        assert sg[s]["defer_vs_hard_frontier"][cfg]["harm_minus_hard_frontier"] < 0, "DEFER is no longer below the hard frontier at sigma >= 0.2"
assert all(sg["0.0"]["defer_vs_hard_frontier"][c]["harm_minus_hard_frontier"] == 0.0 for c in ("0.3|0.7", "0.2|0.8"))
p02 = sg["0.2"]["points"]
assert p02["hard|0.5"]["coverage"] < 0.7 and p02["defer|0.4|0.6"]["harmful_acts"] < p02["hard|0.6"]["harmful_acts"] / 2
rec = sg["0.2"]["one_round_oracle_answers"]["0.4|0.6"]
assert rec["coverage_after_one_round"] > 2 * p02["defer|0.4|0.6"]["coverage"]

# ---- tables
names = {"graph_path": "graph, goal-path deficiency only", "graph_path_slots": "graph + slot completeness", ALIAS: "graph + slots + alias ambiguity", "flat": "flat (counts)", "flat+": "flat+ (counts + 3 booleans)"}
sys_rows = []
for k in ("graph_path", "graph_path_slots", ALIAS, "flat", "flat+"):
    v = S[k]
    sys_rows.append(f"| {names[k]} | {pc(v['decision_accuracy'])} | {pc(v['ask_recall'])} | {pc(v['ask_precision'])} | {pc(v['act_labelled_acted'])} | {pc(v['nonact_labelled_not_acted'])} |")
noise_rows = [f"| σ | controller | coverage | harmful acts (of {N['kept']}) | ASK | abstain |", "|---|---|---|---|---|---|"]
for s in ("0.0", "0.1", "0.2", "0.3"):
    for cfg, label in (("hard|0.5", "hard τ=0.5"), ("hard|0.6", "hard τ=0.6"), ("asym|0.4|0.6", "asymmetric (0.4, 0.6), no ASK"), ("defer|0.4|0.6", "DEFER (0.4, 0.6)")):
        p = sg[s]["points"][cfg]
        noise_rows.append(f"| {s} | {label} | {pc(p['coverage'])} | {p['harmful_acts']} | {p['ask']} | {p['abstain']} |")
miss = C["graph_by_signature"][ALIAS]["missing fact removed"]
miss_n = sum(miss.values())
miss_ask = sum(lc[ALIAS]["ASK"].values())
nosig_n = sum(C["graph_by_signature"][ALIAS]["no signature"].values())
imp_sealed = sum(b[k].get("2", 0) for k in IMP)
conn = idn["by_missing_kind"]["CONNECTED"]
values = {
    "n_dev": C["n_dev"], "sys_table": "\n".join(sys_rows), "act_ok": C["act_actions"][ALIAS]["ok"], "phys_bad": phys_bad, "phys_n": phys_n,
    "flat_plus_act": pc(S["flat+"]["act_labelled_acted"]), "rec_path": pc(S["graph_path"]["ask_recall"]), "ask_needed": ask_rel["removed fact on the goal path"], "ask_n": ask_n,
    "ask_irrelevant": ask_rel["removed fact not needed for the goal"], "rec_slots": pc(S["graph_path_slots"]["ask_recall"]), "rec_flatplus": pc(S["flat+"]["ask_recall"]), "prec_flatplus": pc(S["flat+"]["ask_precision"]),
    "alias_n": al["ABSTAIN/INSUFFICIENT_EVIDENCE"]["True"], "acc_slots": pc(S["graph_path_slots"]["decision_accuracy"]), "acc_alias": pc(S[ALIAS]["decision_accuracy"]), "acc_flatplus": pc(S["flat+"]["decision_accuracy"]),
    "ident_hit": idn["hit"], "ident_n": idn["n"], "ident_conn_n": conn["n"], "ident_conn_size": f"{conn['mean_candidates']:.1f}",
    "nosig_n": nosig_n, "nosig_pct": pc(nosig_n / C["n_dev"]), "miss_ask": miss_ask, "miss_abs": miss_n - miss_ask, "miss_n": miss_n,
    "imp_sealed": f"{imp_sealed} of {imp_total}", "blocked2_other": 0, "flat_imp": f"{flat_imp} of {imp_total} abstained", "graph_imp": f"{graph_imp} of {imp_total}",
    "kept": N["kept"], "sample": N["sample"], "noise_table": "\n".join(noise_rows), "cov_hard_02": pc(p02["hard|0.5"]["coverage"]),
    "gap_02": pts(-sg["0.2"]["defer_vs_hard_frontier"]["0.4|0.6"]["harm_minus_hard_frontier"]), "gap_03": pts(-sg["0.3"]["defer_vs_hard_frontier"]["0.4|0.6"]["harm_minus_hard_frontier"]),
    "defer_equals_asym": "all three (lo, hi) pairs tried", "cov_before": pc(p02["defer|0.4|0.6"]["coverage"]), "cov_after": pc(rec["coverage_after_one_round"]), "harm_after": pc(rec["harm_rate_after_one_round"], 2),
    "q_02": f"{rec['mean_questions_per_asked_world']:.1f}",
}
template = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
print("wrote RESULTS.md")

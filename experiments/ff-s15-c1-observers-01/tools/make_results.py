"""Fills RESULTS.template.md from evidence/c1-report.json so that no number in RESULTS.md is typed by hand.

  python tools/make_results.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
report = json.loads((ROOT / "evidence" / "c1-report.json").read_text(encoding="ascii"))
SURFACES = ["middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean"]
ALPHAS = ["a20", "a10", "a05", "a02", "a01"]
PRIMARY = "middle_plus_final"


def pct(x, digits=1):
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def entry(surface, tag="a05"):
    return report["surfaces"][surface]["alphas"][tag]


def criteria_table():
    rows = ["| Surface | executed | H (HOLD) | H (CAL) | \\|diff\\| | coverage | correct-executed | H₀ argmax | perm. p5 | M1 | M2 | M3 | M4 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in SURFACES:
        a, c = entry(s), report["criteria"][s]
        h, cal, base = a["hold"], a["cal"], report["surfaces"][s]["baseline_argmax"]
        diff = None if h["harm_rate"] is None or cal["harm_rate"] is None else abs(h["harm_rate"] - cal["harm_rate"])
        mark = lambda k: "pass" if c[k] else "**fail**"  # noqa: E731
        rows.append(f"| {s}{' (primary)' if s == PRIMARY else ''} | {h['executed']} | {pct(h['harm_rate'])} | {pct(cal['harm_rate'])} | {pct(diff)} | {pct(h['coverage'])} | {pct(h['correct_executed_fraction'])} | "
                    f"{pct(base['harm_rate'])} | {pct(a['permutation_p05'])} | {mark('M1_transfer')} | {mark('M2_usefulness')} | {mark('M3_confidence_informative')} | {mark('M4_beats_no_threshold')} |")
    return "\n".join(rows)


def frontier_table():
    rows = ["| Surface | α | T_abstain | T_act | coverage | executed | harmful | H | correct-executed | abstained | escalated |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in SURFACES:
        for tag in ALPHAS:
            a = entry(s, tag)
            h, t = a["hold"], a["thresholds_ppm"]
            rows.append(f"| {s} | {a['alpha']:.2f} | {t['abstain'] or 'omitted'} | {t['act'] or 'omitted'} | {pct(h['coverage'])} | {h['executed']} | {h['harmful']} | {pct(h['harm_rate'])} | {pct(h['correct_executed_fraction'])} | {h['abstained']} | {h['escalated']} |")
    return "\n".join(rows)


def matrix_table():
    m = report["surfaces"][PRIMARY]["primary_breakdown"]["truth_decision_by_disposition"]
    rows = ["| truth ↓ / controller → | executed | abstained | asked | escalated (unresolved) | total |", "|---|---|---|---|---|---|"]
    for truth in ("ACT", "ASK", "ABSTAIN"):
        r = m[truth]
        rows.append(f"| {truth} | {r['executed']} | {r['abstained']} | {r['asked']} | {r['escalated']} | {sum(r.values())} |")
    return "\n".join(rows)


def family_table():
    fam = report["surfaces"][PRIMARY]["primary_breakdown"]["by_family"]
    rows = ["| family | rows | coverage | executed | harmful | H |", "|---|---|---|---|---|---|"]
    for name in sorted(fam, key=lambda n: int(n[1:])):
        o = fam[name]
        rows.append(f"| {name} | {o['rows']} | {pct(o['coverage'])} | {o['executed']} | {o['harmful']} | {pct(o['harm_rate'])} |")
    return "\n".join(rows)


a = entry(PRIMARY)
h, cal, base = a["hold"], a["cal"], report["surfaces"][PRIMARY]["baseline_argmax"]
m = report["surfaces"][PRIMARY]["primary_breakdown"]["truth_decision_by_disposition"]
act_total, abs_total, ask_total = sum(m["ACT"].values()), sum(m["ABSTAIN"].values()), sum(m["ASK"].values())
values = {
    "verdict": report["verdict"]["verdict"], "passing": report["verdict"]["surfaces_passing_all_of_M1_to_M4"], "hold_rows": report["hold_rows"],
    "h_hold": pct(h["harm_rate"]), "h_cal": pct(cal["harm_rate"]), "h_base": pct(base["harm_rate"]), "executed": h["executed"], "harmful": h["harmful"],
    "coverage": pct(h["coverage"]), "cexec": pct(h["correct_executed_fraction"]), "cexec_rows": h["correct_executed"], "perm_p5": pct(a["permutation_p05"]), "perm_median": pct(a["permutation_median"]),
    "precision": pct(h["precision"]), "abstained": h["abstained"], "act_escalated_share": pct(m["ACT"]["escalated"] / act_total, 0), "act_executed_share": pct(m["ACT"]["executed"] / act_total),
    "abstain_correct_share": pct(m["ABSTAIN"]["abstained"] / abs_total, 0), "ask_total": ask_total, "ask_escalated": m["ASK"]["escalated"], "ask_executed": m["ASK"]["executed"],
    "criteria_table": criteria_table(), "frontier_table": frontier_table(), "matrix_table": matrix_table(), "family_table": family_table(),
    "runtime_rows": report["hold_rows"] * report["runtime_integrity"]["policies"], "policies": report["runtime_integrity"]["policies"],
    "rescored": str(report["rescored"]).lower(), "prereg_sha": report["freeze"]["preregistration_sha256"][:12], "c0_sha": report["freeze"]["c0_source_sha256"][:12],
}
# --- values and guards for the prose that names specific findings; the script fails if the report stops supporting them
fam = report["surfaces"][PRIMARY]["primary_breakdown"]["by_family"]
high = {n: fam[n] for n in ("S3", "S4", "S5")}
low = {n: o for n, o in fam.items() if n not in high}
assert all(0.09 <= o["harm_rate"] <= 0.13 for o in high.values()), "S3/S4/S5 no longer sit at 9-13% harm"
assert sum(1 for o in low.values() if o["harm_rate"] < 0.05) == 6 and len(fam) == 9, "expected six of nine families under 5% harm"
for s_ in SURFACES:
    for tag_ in ALPHAS:
        assert report["surfaces"][s_]["alphas"][tag_]["thresholds_ppm"]["ask"] is None, "an ASK rule was fitted after all"
assert all(not c_["M2_usefulness"] for c_ in report["criteria"].values()), "M2 no longer fails everywhere"
assert not report["criteria"]["layer_m4_final"]["M1_transfer"] and report["criteria"]["final_plus_mean"]["all_of_M1_to_M4"] is False
lm4 = entry("layer_m4_final")
values.update({
    "lm4_hold": pct(lm4["hold"]["harm_rate"]), "lm4_cal": pct(lm4["cal"]["harm_rate"]), "lm4_diff": pct(abs(lm4["hold"]["harm_rate"] - lm4["cal"]["harm_rate"])),
    "abstain_correct": m["ABSTAIN"]["abstained"], "abstain_precision": pct(m["ABSTAIN"]["abstained"] / h["abstained"]),
    "fam_high_range": f"{100 * min(o['harm_rate'] for o in high.values()):.1f}%-{100 * max(o['harm_rate'] for o in high.values()):.1f}%",
    "fam_high_exec": f"{min(o['executed'] for o in high.values())}-{max(o['executed'] for o in high.values())}",
})
template = (ROOT / "RESULTS.template.md").read_text(encoding="utf-8")
(ROOT / "RESULTS.md").write_text(template.format_map(values), encoding="utf-8", newline="\n")
import shutil
(ROOT / "results").mkdir(exist_ok=True)
for name in ("c1-report.json", "freeze.json", "thresholds.json", "prepare.json"):  # the receipts behind RESULTS.md; evidence/ itself is git-ignored
    shutil.copyfile(ROOT / "evidence" / name, ROOT / "results" / name)
print("wrote RESULTS.md and results/")
sys.exit(0)

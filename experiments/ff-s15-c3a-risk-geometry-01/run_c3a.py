"""C3a: selective-risk geometry census on CAL. Writes results/c3a-census.json. No training, no HOLD, no policy.

  python run_c3a.py
"""
from __future__ import annotations

import json
import sys

from c3 import frontier, scores
from c3.common import LEVELS, PRIMARY, RESULTS, SURFACES, c1fit, load_cal, sha256_file


def main() -> int:
    cal = load_cal()
    truth_decision, truth_action = cal["truth_decision"], cal["truth_action"]
    true_act = int((truth_decision == c1fit.ACT).sum())
    out = {"schema": "c3a-census/v1", "cal_rows": int(len(truth_decision)), "true_act_rows": true_act, "levels": list(LEVELS), "surfaces": {}}
    dominating = {}
    for surface in SURFACES:
        arrays = cal["surfaces"][surface]
        cand = scores.candidates(arrays["dec"], arrays["act"], truth_decision, truth_action)
        pool = scores.all_scores(cand["d"], cand["a"])
        points = {name: frontier.correct_at_harm(s, cand["safe"]) for name, s in pool.items()}
        low = frontier.paired_bootstrap(pool, cand["safe"])
        dom = frontier.dominance({k: v for k, v in points.items()}, low)
        out["surfaces"][surface] = {
            "candidates": cand["rows"], "safe_candidates": int(cand["safe"].sum()),
            "correct_at_harm": {name: {str(level): v for level, v in per.items()} for name, per in points.items()},
            "bootstrap_low_difference": {name: {str(level): v for level, v in per.items()} for name, per in low.items()},
            "dominance": {name: {"levels_passed": [str(x) for x in d["levels_passed"]], "dominates": d["dominates"]} for name, d in dom.items()},
        }
        dominating[surface] = sorted(name for name, d in dom.items() if d["dominates"] and name != scores.CONTROL)
        base = points["c1_min"]
        best = max((n for n in pool if n not in ("c1_min", scores.CONTROL)), key=lambda n: sum(points[n].values()))
        print(f"{surface:18s} candidates={cand['rows']} C1 correct@harm {[base[l] for l in LEVELS]} | best-by-sum: {best} {[points[best][l] for l in LEVELS]} | random control {[points[scores.CONTROL][l] for l in LEVELS]} | dominating: {dominating[surface]}")
    robust = sorted(set.intersection(*[set(v) for v in dominating.values()])) if all(dominating.values()) else []
    counts = {name: sum(name in dominating[s] for s in SURFACES) for name in scores.NAMES if name != "c1_min"}
    out["decision"] = {"dominating_on_primary": dominating[PRIMARY], "dominating_by_surface": dominating, "surfaces_dominated_per_score": counts,
                       "c3b_earned": bool(dominating[PRIMARY]), "robust_scores": [n for n, c in counts.items() if c >= 3], "random_control_dominates_anywhere": any(scores.CONTROL in v for v in dominating.values())}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "c3a-census.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="ascii", newline="\n")
    print("wrote", path.name, sha256_file(path)[:16])
    print(json.dumps(out["decision"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

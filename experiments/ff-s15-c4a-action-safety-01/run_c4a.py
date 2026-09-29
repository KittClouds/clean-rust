"""C4a: action-conditional safety census on CAL. Writes results/c4a-census.json. No policy, no training, no HOLD.

  python run_c4a.py
"""
from __future__ import annotations

import json
import sys

import numpy as np

from c4 import census
from c4.common import ACTIONS, LEVELS, POSSIBLE_ACT_ACTIONS, PRIMARY, RESULTS, SURFACES, c1fit, load_cal, sha256_file


def main() -> int:
    cal = load_cal()
    truth_decision, truth_action = cal["truth_decision"], cal["truth_action"]
    seen = {ACTIONS[a] for a in set(truth_action[truth_decision == c1fit.ACT].tolist())}
    if not seen <= set(POSSIBLE_ACT_ACTIONS):
        raise SystemExit(f"CAL has truth ACT actions outside {POSSIBLE_ACT_ACTIONS}: {seen}")
    out = {"schema": "c4a-census/v1", "cal_rows": int(len(truth_decision)), "levels": list(LEVELS), "truth_act_actions_on_cal": sorted(seen), "surfaces": {}}
    for surface in SURFACES:
        arrays = cal["surfaces"][surface]
        cand = census.candidates(arrays["dec"], arrays["act"], truth_decision, truth_action)
        t_act = cal["thresholds"][surface]["a05"]["thresholds_ppm"]["act"]
        result = census.analyze(cand, t_act, truth_decision, truth_action)
        out["surfaces"][surface] = result
        gains = " / ".join("n/a" if result["oracle_gain"][str(l)] is None else f"{result['oracle_gain'][str(l)]:+.1%}" if not isinstance(result["oracle_gain"][str(l)], str) else "inf" for l in LEVELS)
        noise = " / ".join(f"{result['noise_band'][str(l)]['p95']:+.1%}" if not isinstance(result["noise_band"][str(l)]["p95"], str) else "inf" for l in LEVELS)
        print(f"{surface:18s} eligible={result['eligible_actions']} excluded={result['excluded_candidates']} | oracle gain at 3/5/7/10% = {gains} | noise p95 = {noise} | gate passed: {result['gate_passed']}")
    passed = {s: out["surfaces"][s]["gate_passed"] for s in SURFACES}
    out["decision"] = {"gate_by_surface": passed, "c4b_earned": bool(passed[PRIMARY]), "robust": sum(passed.values()) >= 3}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "c4a-census.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="ascii", newline="\n")
    print("wrote", path.name, sha256_file(path)[:16])
    print(json.dumps(out["decision"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
